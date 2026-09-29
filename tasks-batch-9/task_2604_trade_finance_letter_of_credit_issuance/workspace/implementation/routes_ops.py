"""The logical clock and the deterministic operational sweep (PRD 3.10)."""

from flask import Blueprint

import calc
import ledger
import validate as v
from db import (
    by_created,
    clock_date,
    clock_dt,
    clock_instant,
    db,
    parse_instant,
    touch,
)
from errors import bail
from middleware import SYSTEM_OPERATOR, require
from response import ok

bp = Blueprint("ops", __name__)

PRECLUDABLE_EXAMINATION_STATUSES = ("UNDER_EXAMINATION", "DISCREPANT", "WAIVER_REQUESTED")


# --------------------------------------------------------------------------
# POST /_clock/set_current_utc
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require(SYSTEM_OPERATOR)
    data = v.body()
    to_iso8601 = v.req_str(data, "to_iso8601", 1, 40)
    target = parse_instant(to_iso8601)
    if target is None:
        v.bad("to_iso8601 must be a valid ISO 8601 instant")

    # band 6 -- the clock is monotonic by construction
    if target < clock_dt():
        bail("ERR_CLOCK_REGRESSION")

    db.clock = target
    # setting the clock mutates no entity at all
    return ok({})


# --------------------------------------------------------------------------
# the five sweep passes
# --------------------------------------------------------------------------

def _pass_one_presentations(counters):
    """Preclude presentations whose examination period has run out, and mature
    accepted drawings whose maturity date has arrived."""
    now = clock_instant()
    today = clock_date()
    for presentation in by_created(list(db.presentations.values())):
        deadline = presentation.get("examination_deadline")
        if (deadline is not None
                and now > deadline
                and presentation["examination_status"] in PRECLUDABLE_EXAMINATION_STATUSES):
            if presentation["examination_status"] == "DISCREPANT" \
                    and presentation.get("refusal_notice_sent_at"):
                continue
            presentation["examination_status"] = "PRECLUDED"
            # the bank lost its right to refuse and must honour: the drawing
            # stays reserved, so no credit ledger movement happens here
            touch(presentation)
            counters["presentations_precluded"] += 1

        # ACCEPTED -> MATURED carries no counter of its own in PRD 3.10
        if presentation["settlement_status"] == "ACCEPTED":
            maturity = calc.parse_date(presentation.get("maturity_date"))
            if maturity is not None and today >= maturity:
                presentation["settlement_status"] = "MATURED"
                touch(presentation)


def _pass_two_waivers(counters):
    """Expire pending waiver requests; cited discrepancies are upheld."""
    now = clock_instant()
    for waiver in by_created(list(db.waivers.values())):
        if waiver["status"] != "PENDING":
            continue
        if not waiver.get("deadline_at") or now <= waiver["deadline_at"]:
            continue
        # an expiry is not an answer: responded_at stays unset
        waiver["status"] = "EXPIRED"
        touch(waiver)
        counters["waiver_requests_expired"] += 1

        cited = set(waiver.get("discrepancy_codes") or [])
        for row in ledger.discrepancies_of_presentation(waiver["presentation_id"]):
            if row["status"] == "IDENTIFIED" and row["code"] in cited:
                row["status"] = "UPHELD"
                touch(row)

        presentation = db.presentations.get(waiver["presentation_id"])
        if presentation is None:
            continue
        # an expiry reads exactly as a denial would -- but only while the
        # presentation still sits in WAIVER_REQUESTED; pass one may already have
        # precluded it, and preclusion outranks the demotion.
        if presentation["examination_status"] == "WAIVER_REQUESTED":
            presentation["examination_status"] = "DISCREPANT"
        ledger.recompute_discrepancy_count(presentation)
        touch(presentation)


def _pass_three_amendments(counters):
    """Lapse amendments whose consent window closed unanswered."""
    today = clock_date()
    for amendment in by_created(list(db.amendments.values())):
        if amendment["status"] != "PENDING_CONSENT":
            continue
        deadline = calc.parse_date(amendment.get("consent_deadline_date"))
        if deadline is None or today <= deadline:
            continue
        amendment["status"] = "EXPIRED_NO_CONSENT"
        amendment["resolved_at"] = clock_instant()
        amendment["amendment_fee_cents"] = 0
        # window_end_effective stays at consent_deadline_date: a lapsed
        # amendment blocks the calendar for its full ten days plus buffer
        amendment["window_end_effective"] = amendment.get("consent_deadline_date")
        touch(amendment)
        counters["amendments_lapsed"] += 1

        credit = db.credits.get(amendment["credit_id"])
        if credit is None or credit["status"] != "AMENDMENT_PENDING":
            continue
        if ledger.other_pending_consent(credit["id"], amendment["id"]):
            continue
        credit["status"] = "ISSUED"
        touch(credit)


def _pass_four_credits(counters):
    """Expire issued credits past their presentation deadline with nothing reserved."""
    today = clock_date()
    for credit in by_created(list(db.credits.values())):
        if credit["status"] != "ISSUED":
            continue
        deadline = calc.parse_date(credit.get("presentation_deadline_date"))
        if deadline is None or today <= deadline:
            continue
        if int(credit.get("reserved_cents") or 0) != 0:
            continue
        credit["status"] = "EXPIRED"
        touch(credit)
        counters["credits_expired"] += 1

        # pass five owns the SUSPENDED -> ACTIVE flip so that it is counted once
        released = ledger.release_open_allocation(credit, allow_reactivate=False)
        if released is not None:
            counters["allocations_released"] += 1
        # an expired credit releases its confirmation occupation immediately
        bank = db.banks.get(credit.get("confirming_bank_id"))
        if bank is not None:
            ledger.recompute_bank_line(bank)
            ledger.refresh_bank_score(bank)


def _facility_needs_rederivation(facility):
    """True only when a re-derivation would actually change something, so that a
    second sweep at the same clock is a genuine no-op (no version churn)."""
    allocated = 0
    for row in ledger.facility_allocations(facility["id"]):
        if row["status"] == "OPEN":
            allocated += int(row["allocated_cents"]) + int(row["charge_cents"])
    threshold = calc.fdiv(int(facility["limit_cents"]) * calc.FACILITY_RESTRICT_PCT, 100)
    if allocated != int(facility["allocated_cents"]):
        return True
    if int(facility["limit_cents"]) - allocated != int(facility["available_cents"]):
        return True
    if threshold != int(facility["restrict_threshold_cents"]):
        return True
    if facility["status"] == "ACTIVE" and allocated >= threshold:
        return True
    if (facility["status"] == "SUSPENDED"
            and facility.get("suspended_reason") == "RESTRICT_THRESHOLD_BREACH"
            and allocated < threshold):
        return True
    return False


def _pass_five_facilities(counters):
    """Re-derive facility ledgers and reactivate what fell back below threshold."""
    for facility in by_created(list(db.facilities.values())):
        if not _facility_needs_rederivation(facility):
            continue
        was_suspended = (facility["status"] == "SUSPENDED"
                         and facility.get("suspended_reason") == "RESTRICT_THRESHOLD_BREACH")
        ledger.recompute_facility(facility, allow_reactivate=True)
        if was_suspended and facility["status"] == "ACTIVE":
            counters["facilities_reactivated"] += 1


SWEEP_PASSES = (
    _pass_one_presentations,
    _pass_two_waivers,
    _pass_three_amendments,
    _pass_four_credits,
    _pass_five_facilities,
)


# --------------------------------------------------------------------------
# POST /_ops/run-expiry-sweep
# --------------------------------------------------------------------------

@bp.post("/_ops/run-expiry-sweep")
def run_expiry_sweep():
    require(SYSTEM_OPERATOR)
    data = v.body()
    dry_run = v.opt_bool(data, "dry_run", False)

    counters = {
        "credits_expired": 0,
        "presentations_precluded": 0,
        "waiver_requests_expired": 0,
        "amendments_lapsed": 0,
        "allocations_released": 0,
        "facilities_reactivated": 0,
    }

    snapshot = db.snapshot() if dry_run else None
    try:
        for sweep_pass in SWEEP_PASSES:
            sweep_pass(counters)
    finally:
        if snapshot is not None:
            db.restore(snapshot)
    return ok(counters)
