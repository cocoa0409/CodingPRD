"""Clock-driven re-derivations and derived projections.

None of these writes a row: PRD 2.5 states that reading a subscription, a device
or a device assignment re-derives its status without bumping any version.
"""

from decimal import Decimal, ROUND_CEILING

import constants as C
from money import round_half_up_2dp
from store import db
from timeutil import add_days, date_of, whole_days_between


# -- Device ------------------------------------------------------------------

def device_status(device):
    if device["calibration_status"] == "QUARANTINED":
        return "QUARANTINED"
    if device["calibration_expires_at"] is not None and db.now() > device["calibration_expires_at"]:
        return "EXPIRED"
    return "CALIBRATED"


# -- DeviceAssignment --------------------------------------------------------

def assignment_status(assignment):
    """PRD 3.2: an entry moves SCHEDULED -> ACTIVE on its own as soon as the
    clock reaches window_start.  The specification names no move back: the only
    exits from ACTIVE are RELEASED and REVOKED_TAINTED, both terminal.  An entry
    whose window has elapsed without being released therefore still reads
    ACTIVE -- which is what keeps the billable-print ledger of PRD 2.11
    balanced, since a lapse audit must move that entry's captures onto its
    tainted_print_count rather than dropping them.
    """
    stored = assignment["status"]
    if stored in ("RELEASED", "REVOKED_TAINTED"):
        return stored
    if db.now() >= assignment["window_start"]:
        return "ACTIVE"
    return stored


# -- RapbackSubscription -----------------------------------------------------

def subscription_status(subscription):
    stored = subscription["status"]
    if stored in ("LAPSED", "CANCELLED", "TERMINATED"):
        return stored
    now = db.now()
    term_end = subscription["term_end"]
    if now > term_end:
        return "LAPSED"
    if now >= add_days(term_end, -C.RAPBACK_RENEWAL_WINDOW_DAYS):
        return "RENEWAL_DUE"
    return "ACTIVE"


# -- Invoice -----------------------------------------------------------------

def invoice_aging_days(invoice):
    if invoice["status"] not in ("ISSUED", "PAST_DUE") or invoice["due_on"] is None:
        return 0
    return max(0, whole_days_between(invoice["due_on"], date_of(db.now())))


# -- Submission --------------------------------------------------------------

def composite_disposition(submission):
    destinations = submission["destinations"]
    required_fbi = "FBI" in destinations
    state_status = submission["state_status"]
    fbi_status = submission["fbi_status"]
    if state_status == "PENDING" or (required_fbi and fbi_status == "PENDING"):
        return "INCOMPLETE"
    state_rejected = state_status in ("REJECTED_TECHNICAL", "REJECTED_ADMIN")
    fbi_rejected = required_fbi and fbi_status in ("REJECTED_TECHNICAL", "REJECTED_ADMIN")
    if state_rejected and (fbi_rejected or not required_fbi):
        return "REJECTED"
    if state_rejected != fbi_rejected:
        return "MIXED"
    for response in db.chr_responses.values():
        if response["submission_id"] != submission["id"]:
            continue
        if response["routing_status"] not in ("RECEIVED", "ROUTED"):
            continue
        if (response["record_count"] or 0) >= 1:
            return "HIT"
    return "CLEARED"


# -- FingerprintCard aggregates ----------------------------------------------

def card_positions(card):
    return [p for p in db.positions.values() if p["card_id"] == card["id"]]


def recompute_card_aggregates(card):
    """Returns True when at least one aggregate field actually changed."""
    positions = card_positions(card)
    passed = [p for p in positions if p["status"] == "PASSED"]
    exceptions = [p for p in positions if p["status"] == "EXCEPTION_CODED"]

    passed_count = len(passed)
    exception_count = len(exceptions)
    if passed:
        total = sum(p["best_score"] for p in passed)
        mean = round_half_up_2dp(Decimal(total) / Decimal(len(passed)))
    else:
        mean = Decimal("0.00")
    worst = min((p["best_score"] for p in passed), default=None)

    all_closed = len(positions) == C.POSITION_COUNT and all(
        p["status"] in ("PASSED", "EXCEPTION_CODED") for p in positions
    )
    ceiling = (
        C.EXCEPTION_POSITION_HARD_MAX
        if card["exception_override_by_user_id"] is not None
        else C.EXCEPTION_POSITION_MAX
    )
    submittable = bool(
        all_closed and exception_count <= ceiling and mean >= C.CARD_MEAN_QUALITY_MIN
    )

    changed = (
        card["positions_passed_count"] != passed_count
        or card["positions_exception_count"] != exception_count
        or card["mean_quality_score"] != mean
        or card["worst_position_score"] != worst
        or card["submittable"] != submittable
    )
    card["positions_passed_count"] = passed_count
    card["positions_exception_count"] = exception_count
    card["mean_quality_score"] = mean
    card["worst_position_score"] = worst
    card["submittable"] = submittable
    return changed


def walkin_usable_capacity(concurrent_capacity):
    """concurrent_capacity less twenty percent of it rounded UP (PRD 3.2)."""
    reserve = (Decimal(concurrent_capacity) * C.SITE_WALKIN_RESERVE_PCT).to_integral_value(
        rounding=ROUND_CEILING
    )
    return concurrent_capacity - int(reserve)
