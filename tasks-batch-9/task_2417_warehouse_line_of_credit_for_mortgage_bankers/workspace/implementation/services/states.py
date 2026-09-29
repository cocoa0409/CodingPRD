"""Facility posture, margin-call issuance and the cascade chains.

PRD 2.10: cascades are synchronous and complete within the request that
triggers them; every mutated row has its version incremented by 1 and its
updated_at refreshed.
"""

from clock import clock, plus_days
from db import base_row, db, touch
from money import floor_cents, frac
from services import computed
from services.constants import (
    COVENANT_BREACH_PAYDOWN_PCT,
    DEFAULT_CURE_DAYS,
    ON_BOOK_FUNDING,
    OPEN_CALL_STATUSES,
)
from services.ledger import post_entry


# ------------------------------------------------------------ facility posture

def restrict_if_active(facility):
    """PRD 3.8: from ACTIVE the facility moves to RESTRICTED whenever any margin
    call reaches ISSUED, any covenant test is stored in BREACH, or any
    repurchase demand reaches ESCALATED."""
    if facility["status"] == "ACTIVE":
        facility["status"] = "RESTRICTED"
        touch(facility)
        return True
    return False


def reevaluate_restricted(facility):
    """The return from RESTRICTED to ACTIVE happens only when all three
    conditions hold at once."""
    if facility["status"] != "RESTRICTED":
        return False
    if not computed.facility_is_clean_for_restricted_exit(facility):
        return False
    facility["status"] = "ACTIVE"
    touch(facility)
    return True


def suspend_facility(facility):
    """Every route into SUSPENDED runs the same collateral damage on REQUESTED
    advances and their PENDING_VERIFICATION wires (PRD 3.3 / 3.8)."""
    facility["status"] = "SUSPENDED"
    touch(facility)
    for advance in computed.facility_advances(facility["id"]):
        if advance["funding_status"] != "REQUESTED":
            continue
        advance["funding_status"] = "REJECTED"
        advance["rejected_reason"] = "FACILITY_SUSPENDED"
        touch(advance)
        for wire in computed.advance_wires(advance["id"]):
            if wire["status"] != "PENDING_VERIFICATION":
                continue
            wire["status"] = "BLOCKED"
            wire["block_reason"] = "FACILITY_SUSPENDED"
            touch(wire)


# --------------------------------------------------------------- margin calls

def open_calls_of_advance(advance_id):
    return [m for m in computed.advance_margin_calls(advance_id)
            if m["status"] in OPEN_CALL_STATUSES]


def has_open_call(advance_id):
    return len(open_calls_of_advance(advance_id)) > 0


def facility_level_call_amount(facility_id):
    """PRD 3.6: outstanding_principal_cents multiplied by one tenth, floored."""
    return floor_cents(frac(computed.outstanding_principal(facility_id))
                       * COVENANT_BREACH_PAYDOWN_PCT)


def create_margin_call(facility, advance, trigger_reason, amount_cents,
                       cure_days=DEFAULT_CURE_DAYS, issued_by_user_id=None):
    """A call whose computed amount works out to zero is never created."""
    if amount_cents is None or amount_cents <= 0:
        return None
    issued_at = clock.now()
    call = base_row()
    call.update({
        "facility_id": facility["id"],
        "advance_id": advance["id"] if advance is not None else None,
        "trigger_reason": trigger_reason,
        "call_amount_cents": amount_cents,
        "cured_amount_cents": 0,
        "issued_at": issued_at,
        "cure_deadline_at": plus_days(issued_at, cure_days),
        "issued_by_user_id": issued_by_user_id,
        "waived_by_user_id": None,
        "status": "ISSUED",
    })
    db.margin_calls[call["id"]] = call
    return call


def close_calls(advance_id, trigger_reason=None):
    """Move the advance's open calls to CURED (PRD 3.6: calls also close without
    any payment at all)."""
    closed = 0
    for call in open_calls_of_advance(advance_id):
        if trigger_reason is not None and call["trigger_reason"] != trigger_reason:
            continue
        call["status"] = "CURED"
        touch(call)
        closed += 1
    return closed


# ------------------------------------------------------------------- cascades

def orphan_cascade(facility, commitments):
    """Hops two through four of investor suspension, mirrored by commitment
    withdrawal (PRD 3.2): re-value every FUNDED or SHIPPED advance pointing at
    the now-orphaning commitments, issue a COMMITMENT_WITHDRAWN call where the
    required paydown has become strictly positive, and let the first such call
    move an ACTIVE facility to RESTRICTED."""
    issued = 0
    for commitment in commitments:
        for advance in computed.commitment_advances(commitment["id"]):
            if advance["funding_status"] not in ON_BOOK_FUNDING:
                continue
            result = computed.store_valuation(advance)
            if result["required_paydown_cents"] > 0:
                call = create_margin_call(
                    facility, advance, "COMMITMENT_WITHDRAWN",
                    result["required_paydown_cents"])
                if call is not None:
                    issued += 1
    if issued:
        restrict_if_active(facility)
    return issued


def waive_call(call, facility, user_id):
    """PRD 3.6: one MARGIN_CALL_WAIVED entry with direction CREDIT is appended
    for the uncured obligation; that entry is excluded from both projections."""
    uncured = max(0, call["call_amount_cents"] - call["cured_amount_cents"])
    call["status"] = "WAIVED"
    call["waived_by_user_id"] = user_id
    touch(call)
    post_entry(facility["id"], call["advance_id"], "MARGIN_CALL_WAIVED", "CREDIT",
               uncured, "Margin call waived")
    reevaluate_restricted(facility)
