"""Capture, the allocation waterfall and the abandon compensation (PRD 3.8)."""

import lookup
from money import round_half_up
from services import filings as filing_service
from services import rollups
from store import DB, new_row, touch

ALLOCATABLE_FILING_STATUSES = ("DRAFT", "SUBMITTED", "REJECTED")
STANDALONE_SORT_KEY = "9999-12-31"


def eligible_target(filing, client_id):
    if filing is None:
        return False
    registration = DB.registrations.get(filing["registration_id"])
    if registration is None:
        return False
    if lookup.client_id_of_registration(registration) != client_id:
        return False
    if filing["status"] not in ALLOCATABLE_FILING_STATUSES:
        return False
    return filing["paid_amount_cents"] < filing["total_fee_cents"]


def _due_key(filing):
    obligation_id = filing.get("compliance_obligation_id")
    if obligation_id:
        obligation = DB.obligations.get(obligation_id)
        if obligation is not None and obligation.get("due_date") is not None:
            return obligation["due_date"].isoformat()
    return STANDALONE_SORT_KEY


def candidate_filings(payment, target_filing):
    if target_filing is not None:
        return [target_filing]
    candidates = [
        f
        for f in lookup.filings_of_client(payment["client_id"])
        if f["status"] in ALLOCATABLE_FILING_STATUSES
        and f["paid_amount_cents"] < f["total_fee_cents"]
    ]
    candidates.sort(key=lambda f: (_due_key(f), f["created_at"], f["_seq"]))
    return candidates


def run_waterfall(payment, capture_amount_cents, target_filing):
    remaining = capture_amount_cents
    index = 0
    funded = []
    for filing in candidate_filings(payment, target_filing):
        need = filing["total_fee_cents"] - filing["paid_amount_cents"]
        placed = min(remaining, need)
        if placed <= 0:
            continue
        # rounding order is pinned: the state half rounds first, the service
        # half takes the remainder so the pair sums exactly to amount_cents
        state_portion = round_half_up(
            placed * filing["state_portion_cents"], filing["total_fee_cents"]
        )
        service_portion = placed - state_portion
        new_row(
            DB.allocations,
            {
                "payment_id": payment["id"],
                "filing_id": filing["id"],
                "amount_cents": placed,
                "state_portion_cents": state_portion,
                "service_portion_cents": service_portion,
                "sequence_index": index,
                "is_reversal": False,
            },
            versioned=False,
        )
        filing_service.recompute_paid_amount(filing)
        remaining -= placed
        index += 1
        funded.append(filing)
    payment["allocated_amount_cents"] = capture_amount_cents - remaining
    payment["unallocated_amount_cents"] = remaining
    return funded


def recompute_payment_amounts(payment):
    payment["allocated_amount_cents"] = sum(
        a["amount_cents"] for a in lookup.allocations_of_payment(payment["id"])
    )


def forward_service_sum(filing):
    return sum(
        a["service_portion_cents"]
        for a in lookup.allocations_of_filing(filing["id"])
        if not a["is_reversal"]
    )


def funding_payment(filing):
    """PRD 3.7 speaks of "the funding payment", singular: the payment behind
    the earliest forward allocation row on this filing."""
    forward = [a for a in lookup.allocations_of_filing(filing["id"]) if not a["is_reversal"]]
    if not forward:
        return None
    forward.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return DB.payments.get(forward[0]["payment_id"])


def compensate_abandon(filing):
    """The service portion is returned to account credit; the state portion is
    forfeited.  Returns the refunded amount."""
    service_sum = forward_service_sum(filing)
    payment = funding_payment(filing)
    if payment is None or service_sum <= 0:
        return 0
    next_index = len(lookup.allocations_of_filing(filing["id"]))
    new_row(
        DB.allocations,
        {
            "payment_id": payment["id"],
            "filing_id": filing["id"],
            "amount_cents": -service_sum,
            "state_portion_cents": 0,
            "service_portion_cents": -service_sum,
            "sequence_index": next_index,
            "is_reversal": True,
        },
        versioned=False,
    )
    filing_service.recompute_paid_amount(filing)
    payment["refunded_amount_cents"] += service_sum
    recompute_payment_amounts(payment)
    if payment["refunded_amount_cents"] >= payment["captured_amount_cents"]:
        payment["status"] = "REFUNDED"
    else:
        payment["status"] = "PARTIALLY_REFUNDED"
    touch(payment)
    client = DB.clients.get(payment["client_id"])
    if client is not None:
        rollups.recompute_client(client)
    return service_sum
