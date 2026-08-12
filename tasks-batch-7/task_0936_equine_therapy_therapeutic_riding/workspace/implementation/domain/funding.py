"""The funding waterfall and the charge it settles (PRD §3.8).

The evaluation order is pinned: GRANT, SCHOLARSHIP, SLIDING_SCALE, PAYER,
PRIVATE_PAY.  Every draw is rounded to whole cents AT LINE LEVEL and clamped by
the surviving remainder, so the lines can never over-allocate.
"""

from core import numbers as N
from core import timeutil as T
from core.constants import (
    FUNDING_SOURCES_BY_CHARGE_TYPE,
    SEQUENCE_INDEX_BY_SOURCE,
    SLIDING_SCALE_PCT,
)
from core.errors import fail
from core.store import clock, db, new_row, touch

from . import derive


def _in_period(row, on_date):
    start = T.parse_date(row["period_start"])
    end = T.parse_date(row["period_end"])
    return start <= on_date <= end


def grant_candidates(rider, session_date):
    """Step-1 eligibility filter, then period_end ASC, remaining ASC, created_at ASC."""
    rows = []
    for grant in db["grants"].values():
        if derive.grant_status(grant) != "OPEN":
            continue
        if not _in_period(grant, session_date):
            continue
        restricted_program = grant.get("restricted_program_code")
        if restricted_program is not None and restricted_program != rider["program_code"]:
            continue
        restricted_demo = grant.get("restricted_demographic")
        if restricted_demo is not None and restricted_demo != rider["demographic_group"]:
            continue
        rows.append(grant)
    rows.sort(key=lambda g: (T.parse_date(g["period_end"]),
                             derive.grant_remaining(g),
                             g["created_at"].dt,
                             g["_seq"]))
    return rows


def grant_is_eligible(grant, rider, session_date):
    """The exact same filter, used by rung 41 for a supplied preferred_grant_id."""
    if derive.grant_status(grant) != "OPEN":
        return False
    if not _in_period(grant, session_date):
        return False
    restricted_program = grant.get("restricted_program_code")
    if restricted_program is not None and restricted_program != rider["program_code"]:
        return False
    restricted_demo = grant.get("restricted_demographic")
    if restricted_demo is not None and restricted_demo != rider["demographic_group"]:
        return False
    return True


def active_award(rider, session_date):
    rows = [a for a in derive.rider_awards(rider["id"])
            if derive.award_status(a) == "ACTIVE" and _in_period(a, session_date)]
    rows.sort(key=lambda a: (T.parse_date(a["period_end"]), a["created_at"].dt, a["_seq"]))
    return rows[0] if rows else None


def plan_allocation(rider, session_date, gross, charge_type):
    """Compute every waterfall line without persisting anything."""
    allowed = FUNDING_SOURCES_BY_CHARGE_TYPE[charge_type]
    remaining = gross
    lines = []

    if "GRANT" in allowed:
        for grant in grant_candidates(rider, session_date):
            if remaining <= 0:
                break
            take = min(derive.grant_remaining(grant), remaining)
            if take > 0:
                lines.append({"source_type": "GRANT", "grant_id": grant["id"],
                              "scholarship_award_id": None, "amount_cents": take})
                remaining -= take

    if "SCHOLARSHIP" in allowed and remaining > 0:
        award = active_award(rider, session_date)
        if award is not None:
            pct_cap = N.cents(N.dec(gross) * N.dec(award["cap_pct"]))
            period_room = award["period_cap_cents"] - derive.award_used(award["id"])
            take = min(pct_cap, period_room, remaining)
            if take > 0:
                lines.append({"source_type": "SCHOLARSHIP", "grant_id": None,
                              "scholarship_award_id": award["id"], "amount_cents": take})
                remaining -= take

    if "SLIDING_SCALE" in allowed and remaining > 0:
        pct = N.dec(SLIDING_SCALE_PCT[rider["household_income_band"]])
        take = min(N.cents(N.dec(remaining) * pct), remaining)
        if take > 0:
            lines.append({"source_type": "SLIDING_SCALE", "grant_id": None,
                          "scholarship_award_id": None, "amount_cents": take})
            remaining -= take

    if "PAYER" in allowed and remaining > 0:
        take = min(rider["payer_rate_cents"], remaining)
        if take > 0:
            lines.append({"source_type": "PAYER", "grant_id": None,
                          "scholarship_award_id": None, "amount_cents": take})
            remaining -= take

    return lines, remaining


def create_charge(session, rider, charge_type, gross, session_date):
    """Rung 42 first (nothing is persisted when it fires), then the charge."""
    lines, remaining = plan_allocation(rider, session_date, gross, charge_type)

    if charge_type == "SESSION_FEE" and rider["funding_mode"] == "FUNDED_ONLY" \
            and remaining > 0:
        fail("ERR_FUNDS_EXHAUSTED",
             "The waterfall leaves %d cents uncovered for a FUNDED_ONLY rider."
             % remaining)

    charge = new_row("charges")
    charge.update({
        "session_id": session["id"],
        "charge_type": charge_type,
        "amount_cents": gross,
        "scholarship_excluded": charge_type != "SESSION_FEE",
        "reversed_at": None,
        "reversal_reason": None,
    })

    for line in lines:
        _emit(charge, line["source_type"], line["amount_cents"],
              line.get("grant_id"), line.get("scholarship_award_id"))
    # step 5 - the private-pay line is ALWAYS emitted, even at 0 cents.
    _emit(charge, "PRIVATE_PAY", remaining, None, None)

    session["billing_status"] = "FUNDED" if remaining == 0 else "CHARGED"
    return charge


def _emit(charge, source_type, amount_cents, grant_id, award_id):
    allocation = new_row("funding_allocations")
    allocation.update({
        "charge_id": charge["id"],
        "grant_id": grant_id,
        "scholarship_award_id": award_id,
        "source_type": source_type,
        "sequence_index": SEQUENCE_INDEX_BY_SOURCE[source_type],
        "amount_cents": amount_cents,
        "status": "ALLOCATED",
    })
    return allocation


# ------------------------------------------------------------------ reversal
def reverse_charge(charge, reason):
    """The five-hop charge_reversal_cascade."""
    # HOP 1 - the charge itself.
    charge["reversed_at"] = clock.stamp()
    charge["reversal_reason"] = reason
    touch(charge)

    # HOP 2 - caused by hop 1: every allocation line of that charge is released.
    # HOP 3 - caused by hop 2: each released line restores its source ledger.
    #         Grant.remaining_amount_cents and ScholarshipAward.period_used_cents
    #         are derived from the ALLOCATED lines, so releasing the line IS the
    #         restoration, and the OPEN / ACTIVE flip follows from it.
    for allocation in derive.charge_allocations(charge["id"]):
        if allocation["status"] != "ALLOCATED":
            continue
        allocation["status"] = "RELEASED"
        touch(allocation)

    # HOP 4 - caused by hop 3.
    session = db["sessions"].get(charge["session_id"])
    if session is not None:
        siblings = [c for c in db["charges"].values()
                    if c["session_id"] == session["id"]]
        if all(c.get("reversed_at") is not None for c in siblings) \
                and session["billing_status"] in ("CHARGED", "FUNDED"):
            session["billing_status"] = "REVERSED"
            touch(session)
            # HOP 5 - caused by hop 4.
            _amend_period_report(session, charge)
    return charge


def _amend_period_report(session, charge):
    """A FINALIZED report takes the amendment; a DRAFT one simply recomputes."""
    from .gates import finalized_report_covering
    session_date = T.day_of(session["scheduled_start"].dt)
    report = finalized_report_covering(session_date)
    if report is None:
        return
    report["amendment_count"] += 1
    report["amendment_net_cents"] -= charge["amount_cents"]
    touch(report)
