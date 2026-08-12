"""The two non-fungible money streams, the ledger and the conservation identity.

PRD 2.6, 2.11 (Invariants 1, 1a, 1b), 3.6, 3.11.

Roll-up maintenance (adjudication of friction 7 -- the outstanding_cents tension):
the PINNED REFUND DRAW of Invariant 1b governs. A refund takes min(refund,
outstanding) out of outstanding_cents and the remainder out of
service_earned_cents; outstanding_cents therefore never goes negative and
Invariant 1 survives every ledger write exactly.
"""
from decimal import Decimal

import clock
import store
from calendar_util import round_half_up
from constants import REFUND_PCT_BY_STAGE
from services import lookup


def write_entry(order, stream, kind, amount_cents, reason):
    """Append a ledger row (never for a zero amount -- amount_cents must be >= 1)."""
    if amount_cents is None or amount_cents < 1:
        return None
    row = {
        "order_id": order["id"],
        "stream": stream,
        "kind": kind,
        "amount_cents": int(amount_cents),
        "reason": reason,
        "recorded_at": clock.now(),
    }
    store.insert("ledger_entries", row)
    return row


def recompute_collected(order):
    """collected_<stream>_cents = COLLECTION - TRANSFER_OUT + TRANSFER_IN, per stream."""
    gov = 0
    svc = 0
    tendered = 0
    refunded = 0
    for row in lookup.ledger_of(order):
        amount = row["amount_cents"]
        if row["kind"] == "COLLECTION":
            if row["stream"] == "GOVERNMENT":
                gov += amount
            else:
                svc += amount
        elif row["kind"] == "TRANSFER_OUT":
            if row["stream"] == "GOVERNMENT":
                gov -= amount
            else:
                svc -= amount
        elif row["kind"] == "TRANSFER_IN":
            if row["stream"] == "GOVERNMENT":
                gov += amount
            else:
                svc += amount
        elif row["kind"] == "TENDER":
            tendered += amount
        elif row["kind"] == "REFUND":
            refunded += amount
    order["collected_government_cents"] = gov
    order["collected_service_cents"] = svc
    order["government_tendered_cents"] = tendered
    order["refunded_cents"] = refunded


def collected_cents(order):
    return order["collected_government_cents"] + order["collected_service_cents"]


def record_collection(order, stream, amount_cents):
    entry = write_entry(order, stream, "COLLECTION", amount_cents, "CUSTOMER_PAYMENT")
    if entry is not None:
        order["outstanding_cents"] += amount_cents
    return entry


def record_tender(order, amount_cents):
    entry = write_entry(order, "GOVERNMENT", "TENDER", amount_cents, "AGENCY_TENDER")
    if entry is not None:
        order["outstanding_cents"] -= amount_cents
    return entry


def record_earn(order, amount_cents, reason):
    entry = write_entry(order, "SERVICE", "EARN", amount_cents, reason)
    if entry is not None:
        order["service_earned_cents"] += amount_cents
        order["outstanding_cents"] -= amount_cents
    return entry


def record_refund(order, stream, amount_cents, reason):
    """Invariant 1b -- the pinned two-step draw, applied per stream."""
    entry = write_entry(order, stream, "REFUND", amount_cents, reason)
    if entry is None:
        return None
    from_outstanding = min(amount_cents, order["outstanding_cents"])
    order["outstanding_cents"] -= from_outstanding
    remainder = amount_cents - from_outstanding
    order["service_earned_cents"] -= remainder
    return entry


def record_transfer_out(order, stream, amount_cents):
    entry = write_entry(order, stream, "TRANSFER_OUT", amount_cents, "SPLIT_PARTITION")
    if entry is not None:
        order["outstanding_cents"] -= amount_cents
    return entry


def record_transfer_in(order, stream, amount_cents):
    entry = write_entry(order, stream, "TRANSFER_IN", amount_cents, "SPLIT_PARTITION")
    if entry is not None:
        order["outstanding_cents"] += amount_cents
    return entry


# --------------------------------------------------------------------------
# payment_status derivation (PRD 3.6)
# --------------------------------------------------------------------------
REFUND_HALF = ("REFUND_PENDING", "PARTIALLY_REFUNDED", "REFUNDED")


def derive_payment_status(order):
    """Pure function of collected_cents and total_quoted_cents while in the
    collection half; the refund half is set only by adjudication/disbursement."""
    if order["payment_status"] in REFUND_HALF:
        return order["payment_status"]
    collected = collected_cents(order)
    total = order["total_quoted_cents"]
    if collected == 0:
        status = "UNPAID"
    elif total > 0 and collected >= total:
        status = "COLLECTED"
    else:
        status = "PARTIALLY_COLLECTED"
    order["payment_status"] = status
    return status


# --------------------------------------------------------------------------
# payment_stream_allocation (PRD 3.6)
# --------------------------------------------------------------------------
def allocate_payment(order, amount_cents, stream_override):
    gov_remaining = max(order["government_fee_quoted_cents"]
                        - order["collected_government_cents"], 0)
    if stream_override is None:
        gov_part = min(amount_cents, gov_remaining)
        svc_part = amount_cents - gov_part
    elif stream_override == "GOVERNMENT":
        gov_part = amount_cents
        svc_part = 0
    else:
        gov_part = 0
        svc_part = amount_cents
    return gov_part, svc_part


# --------------------------------------------------------------------------
# refund_adjudication (PRD 3.11)
# --------------------------------------------------------------------------
def adjudicate_refund(order, pre_tender_reason="CANCELLATION_REFUND"):
    """Runs the stage-keyed refund. Returns the variant name that was used."""
    stage_pct = REFUND_PCT_BY_STAGE.get(order["furthest_stage_reached"], Decimal("0"))
    service_refund = round_half_up(Decimal(order["collected_service_cents"]) * stage_pct)

    if order["government_tendered_cents"] == 0:
        # pre_tender: pass-through money never reached the agency, all of it comes back
        government_refund = order["collected_government_cents"]
        total_refund = service_refund + government_refund
        before = collected_cents(order)
        if government_refund > 0:
            record_refund(order, "GOVERNMENT", government_refund, pre_tender_reason)
        if service_refund > 0:
            record_refund(order, "SERVICE", service_refund, pre_tender_reason)
        recompute_collected(order)
        if total_refund > 0:
            if total_refund >= before:
                order["payment_status"] = "REFUNDED"
            else:
                order["payment_status"] = "PARTIALLY_REFUNDED"
        return "pre_tender"

    # post_tender: government refund is 0; nothing is disbursed until the
    # AGENCY -> SERVICE return leg reaches DELIVERED.
    total_refund = service_refund
    if total_refund > 0:
        order["refund_scheduled_cents"] = total_refund
        order["payment_status"] = "REFUND_PENDING"
    return "post_tender"


def disburse_scheduled_refund(order):
    """Adjudication of friction 16: every post-tender disbursement carries
    reason REJECTION_REFUND; CANCELLATION_REFUND belongs to the immediate
    pre-tender rows alone. Both reason values therefore stay reachable."""
    amount = order["refund_scheduled_cents"]
    if amount <= 0:
        return False
    record_refund(order, "SERVICE", amount, "REJECTION_REFUND")
    order["refund_scheduled_cents"] = 0
    recompute_collected(order)
    order["payment_status"] = "PARTIALLY_REFUNDED"
    return True


def conservation_ok(order):
    return collected_cents(order) == (
        order["government_tendered_cents"]
        + order["service_earned_cents"]
        + order["refunded_cents"]
        + order["outstanding_cents"]
    )
