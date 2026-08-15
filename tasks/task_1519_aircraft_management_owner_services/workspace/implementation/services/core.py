"""Core shared services: record factory, pagination, sorting, statement
recompute hooks, duty accumulators, and agreement lookup."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
from db import db
from errors import validation, ApiError, ERR_NOT_FOUND
from util import fmt_ts, new_id, parse_date, period_bounds

# ---------------------------------------------------------------------------
# record factory
# ---------------------------------------------------------------------------


def make_record(fields):
    now = fmt_ts(clock.now())
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec, bump_version=False):
    rec["updated_at"] = fmt_ts(clock.now())
    if bump_version:
        rec["version"] += 1


# ---------------------------------------------------------------------------
# pagination & sorting
# ---------------------------------------------------------------------------


def get_pagination(args):
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise validation("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise validation("offset must be an integer")
        if offset < 0:
            raise validation("offset must be >= 0")
    return limit, offset


def sort_records(records):
    """Sort by created_at ascending; creation sequence breaks ties."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(records, limit, offset):
    ordered = sort_records(records)
    total = len(ordered)
    return ordered[offset:offset + limit], total


# ---------------------------------------------------------------------------
# FK resolution helpers
# ---------------------------------------------------------------------------


def require_exists(table, rid, msg="Resource not found"):
    rec = table.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, msg, 404)
    return rec


def filter_value_exists(table, value):
    """For list query filters: a supplied filter value that does not resolve
    to an existing resource yields ERR_NOT_FOUND."""
    if value is not None and value not in table:
        raise ApiError(ERR_NOT_FOUND, "Filter value does not resolve to an existing resource", 404)


# ---------------------------------------------------------------------------
# agreements
# ---------------------------------------------------------------------------

LIVE_AGREEMENT_STATUSES = {"PENDING", "ACTIVE", "TERMINATION_PENDING", "HANDOVER_IN_PROGRESS"}


def live_agreement_for_aircraft(aircraft_id):
    for ag in db.agreements.values():
        if ag["aircraft_id"] == aircraft_id and ag["status"] in LIVE_AGREEMENT_STATUSES:
            return ag
    return None


def current_agreement_for_aircraft(aircraft_id):
    """Return the aircraft's agreement (live first, then most recent)."""
    best = None
    for ag in db.agreements.values():
        if ag["aircraft_id"] != aircraft_id:
            continue
        if ag["status"] in LIVE_AGREEMENT_STATUSES:
            return ag
        if best is None or ag["_seq"] > best["_seq"]:
            best = ag
    return best


# ---------------------------------------------------------------------------
# duty accumulators (calculation: duty_hours_accumulation)
# ---------------------------------------------------------------------------

DUTY_LIMIT_7D_HOURS = Decimal("40")
DUTY_LIMIT_28D_HOURS = Decimal("120")


def compute_duty_hours(duty_start_at, duty_end_at):
    """(end - start) in hours, 2 decimal places, round_half_up."""
    delta = duty_end_at - duty_start_at
    hours = Decimal(delta.total_seconds()) / Decimal(3600)
    return float(hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def duty_window_sums(crew_member_id):
    """Return (duty_hours_7d, duty_hours_28d) over ASSIGNED/COMPLETED
    assignments whose duty_end_at falls in (now-Nd, now]."""
    now = clock.now()
    lo7 = now - timedelta(days=7)
    lo28 = now - timedelta(days=28)
    sum7 = Decimal("0")
    sum28 = Decimal("0")
    for a in db.assignments.values():
        if a["crew_member_id"] != crew_member_id:
            continue
        if a["status"] not in ("ASSIGNED", "COMPLETED"):
            continue
        end = a["_duty_end"]
        hours = Decimal(str(a["duty_hours"]))
        if lo28 < end <= now:
            sum28 += hours
            if lo7 < end <= now:
                sum7 += hours
    return sum7, sum28


def flight_hours_total(crew_member_id):
    """Sum of block_hours_actual over COMPLETED trips where this crew member
    held an assignment (ASSIGNED or COMPLETED). A VOID trip's duty was still
    performed: PRD §3.4 void "does not un-perform" duty and "the crew members'
    flight_hours_total is not reversed", so VOID trips keep contributing."""
    total = Decimal("0")
    seen_trips = set()
    for a in db.assignments.values():
        if a["crew_member_id"] != crew_member_id:
            continue
        if a["status"] not in ("ASSIGNED", "COMPLETED"):
            continue
        trip = db.trips.get(a["trip_id"])
        if trip is None or trip["status"] not in ("COMPLETED", "VOID"):
            continue
        if trip["id"] in seen_trips:
            continue
        seen_trips.add(trip["id"])
        if trip["block_hours_actual"] is not None:
            total += Decimal(str(trip["block_hours_actual"]))
    return float(total)


# ---------------------------------------------------------------------------
# statements: recompute hook
# ---------------------------------------------------------------------------


def find_draft_statement(aircraft_id, period):
    for st in db.statements.values():
        if st["aircraft_id"] == aircraft_id and st["period"] == period and st["status"] == "DRAFT":
            return st
    return None


def recompute_draft_statements_for_date(aircraft_id, date_str):
    """Recompute any DRAFT MonthlyStatement of the aircraft whose period
    covers the given ISO date (used for service_date / completion date)."""
    if not date_str:
        return
    d = parse_date(date_str, "date")
    for st in db.statements.values():
        if st["aircraft_id"] != aircraft_id or st["status"] != "DRAFT":
            continue
        start, end = period_bounds(st["period"])
        if start <= d < end:
            recompute_statement(st)


def stamp_computed(st):
    """Record the computation marker used by the staleness check.

    Marker = (logical time of computation, a freshly consumed store
    sequence). Because the marker sequence is drawn from the same counter
    as record creation, any record created before the computation has a
    strictly smaller (created_at, _seq) pair and any record created after
    has a strictly greater one."""
    st["_computed_at"] = fmt_ts(clock.now())
    st["_computed_seq"] = db.next_seq()


def recompute_statement(st):
    """Run the full derivation stack for a statement (PRD §3.8).

    Arrival-triggered recomputation (expense post/void, trip completion/void)
    refreshes the DRAFT's figures but deliberately does NOT move the
    certification staleness marker: PRD §3.8 rejects certification when a
    POSTED expense "is not reflected in the statement's last computation" and
    prescribes that "the preparer must regenerate the draft to pick up the new
    expense" — i.e. only an explicit POST /statements (generate/regenerate)
    clears staleness (see stamp_computed call sites in routes/statements.py).
    """
    from services.statements import compute_statement_fields
    compute_statement_fields(st)
    touch(st)
