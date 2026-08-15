"""Calculation rules: workday calendar, job-order derived terms, weekly wage
reconciliation, three-quarters guarantee, transport reimbursement, penalties."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

FEDERAL_MINIMUM_WAGE_CENTS = 725
CERT_LEAD_DAYS = 30
MAX_RFE_COUNT = 2
MAX_DAILY_CONSULAR_SLOTS = 6
DAYS_PER_DEBARMENT_YEAR = 365

BASE_PENALTY_CENTS = {
    "WAGE_UNDERPAYMENT": 150000,
    "HOUSING_SUBSTANDARD": 120000,
    "TRANSPORT_VIOLATION": 90000,
    "RECRUITMENT_VIOLATION": 110000,
    "RECORDKEEPING": 60000,
}
WILLFUL_MULTIPLIER = 2
PER_KIND_CAP_CENTS = 1000000
GOOD_FAITH_DISCOUNT_PCT = 10

ACTIVITY_ENUM = {"HARVEST", "PACKING", "PLANTING", "GENERAL"}
DECISION_APP_ENUM = {"HIRE", "REJECT"}
QUALIFICATION_ENUM = {"QUALIFIED", "UNQUALIFIED"}
DECISION_PETITION_ENUM = {"APPROVE", "DENY"}
OUTCOME_ENUM = {"ISSUED", "REFUSED", "NO_SHOW"}
INSPECTION_RESULT_ENUM = {"PASS", "FAIL"}
TRANSFER_REASON_ENUM = {"CONTRACT_IMPOSSIBILITY", "GROWER_REQUEST", "WORKER_REQUEST"}
TRIGGER_SOURCE_ENUM = {"MANUAL", "ABANDONMENT", "HOUSING", "WAGE_DISCREPANCY"}
END_REASON_ENUM = {"COMPLETED", "FOR_CAUSE"}

TERMINAL_ASSIGNMENT = {"COMPLETED", "TERMINATED", "TRANSFERRED_OUT"}
LIVE_ASSIGNMENT = {"PLANNED", "ACTIVE"}


def d(iso):
    return date.fromisoformat(iso)


def iso(dt):
    return dt.isoformat()


def rhu(numerator, denominator=1):
    """round half up to whole cents."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def workday_count(d1, d2):
    """Dates in [d1, d2] inclusive whose weekday is not Sunday; 0 if inverted."""
    if d2 < d1:
        return 0
    days = (d2 - d1).days + 1
    count = 0
    cur = d1
    for _ in range(days):
        if cur.weekday() != 6:  # Sunday
            count += 1
        cur += timedelta(days=1)
    return count


# --------------------------------------------------------- job order derived

def wage_sources(order, det, live_det=None):
    """(aewr, prevailing_hourly, prevailing_piece): live while never submitted,
    locked snapshots once submitted at least once. ``live_det`` is the
    currently-PUBLISHED determination for the referenced row's survey key
    (the successor after a supersession); while unsubmitted its values are
    the ones read."""
    if order["locked_aewr_hourly_cents"] is None:
        live = live_det if live_det is not None else det
        return (
            live["aewr_hourly_cents"],
            live["prevailing_hourly_cents"],
            live["prevailing_piece_rate_cents_per_unit"],
        )
    return (
        order["locked_aewr_hourly_cents"],
        order["locked_prevailing_hourly_cents"],
        order["locked_prevailing_piece_rate_cents_per_unit"],
    )


def required_hourly_floor(order, det, live_det=None):
    aewr, prev, _ = wage_sources(order, det, live_det)
    return max(aewr, prev, order["offered_hourly_cents"], FEDERAL_MINIMUM_WAGE_CENTS)


def effective_piece_rate(order, det, live_det=None):
    _, _, prev_piece = wage_sources(order, det, live_det)
    candidates = [v for v in (order["offered_piece_rate_cents_per_unit"], prev_piece)
                  if v is not None]
    return max(candidates) if candidates else None


def total_calendar_days(order):
    return (d(order["work_end_date"]) - d(order["work_start_date"])).days + 1


def recruitment_cutoff(order):
    start = d(order["work_start_date"])
    return start + timedelta(days=(total_calendar_days(order) // 2) - 1)


# -------------------------------------------------------- wage reconciliation

def recon_compute(order, assignment, logs, finalized, today):
    """Compute every derived field of a WageReconciliation row.

    finalized=False -> provisional variant (OPEN); finalized=True -> final
    variant (frozen at finalize-reconciliation)."""
    start_d = d(order["work_start_date"])
    end_d = d(order["work_end_date"])
    started = d(assignment["started_on"])

    if assignment["status"] in TERMINAL_ASSIGNMENT:
        through = d(assignment["ended_on"])
    else:
        through = min(today, end_d)

    floor = required_hourly_floor_stored(order)
    prate = effective_piece_rate_stored(order)

    by_date = {}
    for lg in logs:
        by_date[d(lg["work_date"])] = lg

    piece_total = 0
    floor_total = 0
    makeup_total = 0
    if through >= started:
        k = 0
        while True:
            wk_start = start_d + timedelta(days=7 * k)
            if wk_start > end_d or wk_start > through:
                break
            wk_end = min(wk_start + timedelta(days=6), end_d)
            if wk_end < started:
                k += 1
                continue
            wk_units = sum(
                lg["units_picked"] for lg in logs
                if wk_start <= d(lg["work_date"]) <= wk_end
            )
            wk_piece = wk_units * (prate if prate is not None else 0)
            wk_floor = 0
            cur = wk_start
            while cur <= wk_end:
                lg = by_date.get(cur)
                quarters = int(round(lg["hours_worked"] * 4)) if lg else 0
                wk_floor += rhu(quarters * floor, 4)
                cur += timedelta(days=1)
            piece_total += wk_piece
            floor_total += wk_floor
            makeup_total += max(0, wk_floor - wk_piece)
            k += 1

    total_units = sum(lg["units_picked"] for lg in logs)

    basis_start = max(start_d, started)
    basis_end = min(end_d, through)
    basis_workdays = workday_count(basis_start, basis_end)
    total_quarters = basis_workdays * order["daily_standard_hours"] * 4
    guaranteed_quarters = (total_quarters * 3) // 4
    worked_quarters = sum(
        int(round(lg["hours_worked"] * 4)) for lg in logs
        if basis_start <= d(lg["work_date"]) <= basis_end
    )
    shortfall_quarters = max(0, guaranteed_quarters - worked_quarters)

    if finalized:
        guarantee_applied = assignment["end_reason"] not in ("FOR_CAUSE", "ABANDONED")
    else:
        guarantee_applied = True
    guarantee_pay = rhu(shortfall_quarters * floor, 4) if guarantee_applied else 0

    threshold = recruitment_cutoff(order)
    inbound = (
        order["inbound_transport_cents"]
        if through >= threshold
        and (not finalized or assignment["end_reason"] != "ABANDONED")
        else 0
    )
    outbound = (
        order["outbound_transport_cents"]
        if finalized and assignment["end_reason"] == "COMPLETED"
        else 0
    )
    total_due = piece_total + makeup_total + guarantee_pay + inbound + outbound

    return {
        "computed_through_date": iso(through),
        "total_units": total_units,
        "piece_earnings_cents": piece_total,
        "hourly_floor_earnings_cents": floor_total,
        "makeup_pay_cents": makeup_total,
        "guarantee_basis_workdays": basis_workdays,
        "guaranteed_quarters": guaranteed_quarters,
        "worked_quarters": worked_quarters,
        "shortfall_quarters": shortfall_quarters,
        "guarantee_pay_cents": guarantee_pay,
        "guarantee_applied": guarantee_applied,
        "inbound_transport_owed_cents": inbound,
        "outbound_transport_owed_cents": outbound,
        "total_due_cents": total_due,
    }


# These two read the stored locked/live values without a determination lookup
# (reconciliation always runs post-submit, so locked_* are set; fall back to
# offered-only logic defensively).
def required_hourly_floor_stored(order):
    aewr = order["locked_aewr_hourly_cents"]
    prev = order["locked_prevailing_hourly_cents"]
    vals = [order["offered_hourly_cents"], FEDERAL_MINIMUM_WAGE_CENTS]
    if aewr is not None:
        vals.append(aewr)
    if prev is not None:
        vals.append(prev)
    return max(vals)


def effective_piece_rate_stored(order):
    prev_piece = order["locked_prevailing_piece_rate_cents_per_unit"]
    candidates = [v for v in (order["offered_piece_rate_cents_per_unit"], prev_piece)
                  if v is not None]
    return max(candidates) if candidates else None


# ------------------------------------------------------------------ penalties

def provisional_exposure(findings):
    return sum(BASE_PENALTY_CENTS[f["violation_code"]] * f["count"] for f in findings)


def final_penalty(findings, good_faith):
    total = 0
    for f in findings:
        kind_total = BASE_PENALTY_CENTS[f["violation_code"]] * f["count"] * (
            WILLFUL_MULTIPLIER if f.get("willful") else 1)
        total += min(kind_total, PER_KIND_CAP_CENTS)
    if good_faith:
        total = rhu(total * (100 - GOOD_FAITH_DISCOUNT_PCT), 100)
    return total
