"""Finalization, remittance, reversal and the other-payer posting (PRD 3.7, 3.9)."""

from store import db
from services.accumulators import get_or_create
from services.events import append_event
from services.lookup import lines_of, remittances_of
from services.pipeline import (
    earliest_service_year,
    release_line_units,
    zero_claim_totals,
    zero_line_money,
)


def finalize(claim, actor_role, actor_user_id):
    """ADJUDICATED or DENIED -> FINALIZED, issuing one remittance advice."""
    from_status = claim["status"]
    lines = lines_of(claim)
    posts_to_accumulator = from_status == "ADJUDICATED"

    issued_before = len(remittances_of(claim["id"]))
    remit = db.insert(
        "remittance_advices",
        {
            "claim_id": claim["id"],
            "remit_number": "RA-%s-%d" % (claim["claim_number"], issued_before + 1),
            "total_allowed_cents": claim["total_allowed_cents"],
            "total_plan_paid_cents": claim["total_plan_paid_cents"],
            "total_member_liability_cents": claim["total_member_liability_cents"],
            "total_other_payer_paid_cents": claim["other_payer_paid_cents"] or 0,
            "issued_at": db.clock_iso(),
            "status": "ISSUED",
            "_posted_accumulator_id": None,
        },
    )

    claim["payment_status"] = "REMITTED"

    if posts_to_accumulator:
        # A denied claim consumes no benefits, so it posts nothing at all.
        acc = get_or_create(claim["member_id"], earliest_service_year(lines))
        acc["deductible_applied_cents"] += claim["total_deductible_applied_cents"]
        acc["oop_applied_cents"] += claim["total_member_liability_cents"]
        acc["remitted_claim_count"] += 1
        db.touch(acc)
        remit["_posted_accumulator_id"] = acc["id"]

    for line in lines:
        if line["line_status"] == "PRICED":
            line["line_status"] = "PAID"
            db.touch(line)

    claim["status"] = "FINALIZED"
    db.touch(claim)
    append_event(claim, "FINALIZE", from_status, "FINALIZED", None, actor_role, actor_user_id)
    return claim


def _reverse_posted_effects(claim):
    """Hops 2 to 6 of the unwind, shared by void and adjustment."""
    claim["payment_status"] = "REVERSED"
    for remit in remittances_of(claim["id"]):
        if remit["status"] != "ISSUED":
            continue
        remit["status"] = "VOIDED"
        db.touch(remit)
        acc_id = remit.get("_posted_accumulator_id")
        if not acc_id:
            continue
        acc = db.benefit_accumulators.get(acc_id)
        if acc is None:
            continue
        acc["deductible_applied_cents"] = max(
            0, acc["deductible_applied_cents"] - claim["total_deductible_applied_cents"]
        )
        acc["oop_applied_cents"] = max(
            0, acc["oop_applied_cents"] - claim["total_member_liability_cents"]
        )
        acc["remitted_claim_count"] = max(0, acc["remitted_claim_count"] - 1)
        db.touch(acc)
    for line in lines_of(claim):
        if line["line_status"] == "PAID":
            line["line_status"] = "REVERSED"
            release_line_units(line)
            db.touch(line)


def void(claim, actor_role, actor_user_id):
    from_status = claim["status"]
    claim["status"] = "VOIDED"
    _reverse_posted_effects(claim)
    db.touch(claim)
    append_event(claim, "VOID", from_status, "VOIDED", None, actor_role, actor_user_id)
    return claim


def adjust(claim, actor_role, actor_user_id):
    """Reverse the original exactly as a void reverses it, then it is replaced."""
    from_status = claim["status"]
    claim["status"] = "ADJUSTED"
    _reverse_posted_effects(claim)
    db.touch(claim)
    append_event(claim, "ADJUST", from_status, "ADJUSTED", None, actor_role, actor_user_id)
    return claim


def post_other_payer_payment(claim, amount, actor_role, actor_user_id):
    """RECEIVED / PENDED self-loops, or ADJUDICATED -> RECEIVED reprocessing."""
    from_status = claim["status"]
    claim["other_payer_paid_cents"] = amount
    if from_status == "ADJUDICATED":
        for line in lines_of(claim):
            if line["line_status"] == "PRICED":
                release_line_units(line)
            line["line_status"] = "PENDING"
            zero_line_money(line)
            line["authorization_id"] = None
            line["bundled_into_line_number"] = None
            line["edit_reason_code"] = None
            line["_rule"] = None
            db.touch(line)
        zero_claim_totals(claim)
        claim["pricing_variant"] = "UNPRICED"
        claim["status"] = "RECEIVED"
    db.touch(claim)
    append_event(
        claim, "COB_POST", from_status, claim["status"], None, actor_role, actor_user_id
    )
    return claim
