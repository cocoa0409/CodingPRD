"""Outage events and the SLA credit control (prepare / apply / reverse)."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import db
import domain
import middleware as mw
import resolve
import response
from errors import ApiError
from util import add_days, dec, start_of_day, whole_minutes_between

bp = Blueprint("outage", __name__)

CAUSES = ("WEATHER_WIND", "WEATHER_ICE", "WEATHER_FLOOD", "POWER", "BACKHAUL",
          "EQUIPMENT", "PLANNED_MAINTENANCE")
CREDIT_STATUSES = ("PENDING", "APPLIED", "DENIED", "REVERSED")
LIVE_CREDIT_STATUSES = ("PENDING", "APPLIED")


def _cycle_bounds(subscriber):
    """The subscriber's current cycle as a half-open instant window."""
    cycle_start = subscriber.get("cycle_start_date")
    if cycle_start is None:
        return None, None
    return start_of_day(cycle_start), start_of_day(add_days(cycle_start, calc.CYCLE_DAYS))


def _subscriber_tower_id(subscriber):
    sector = db.sectors.get(subscriber["sector_id"])
    if sector is None:
        return None
    return sector["tower_id"]


# ---------------------------------------------------------------------------
# outage events
# ---------------------------------------------------------------------------
@bp.post("/outage-events")
def create_outage():
    mw.require(mw.ROLE_NETWORK_ENGINEER)
    payload = mw.body()
    tower_id = mw.v_ref(payload, "tower_id")
    cause = mw.v_enum(payload, "cause", CAUSES)
    started_at = mw.v_ts(payload, "started_at")
    notice_days = mw.v_int(payload, "planned_notice_days", required=False, minimum=0)

    tower = resolve.tower(tower_id)
    record = db.base_record(
        tower_id=tower["id"],
        cause=cause,
        started_at=started_at,
        ended_at=None,
        peak_wind_mph=None,
        planned_notice_days=notice_days,
        status="OPEN",
        duration_minutes=None,
        sla_excluded=False,
    )
    db.outage_events[record["id"]] = record
    return response.created(domain.outage_view(record))


@bp.get("/outage-events/<outage_id>")
def read_outage(outage_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_CAPACITY_PLANNER, mw.ROLE_BILLING_ADMIN,
               mw.ROLE_FINANCE_APPROVER)
    record = resolve.outage(outage_id)
    return response.object_response(domain.outage_view(record))


@bp.post("/outage-events/<outage_id>/closure")
def close_outage(outage_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER)
    payload = mw.body()
    ended_at = mw.v_ts(payload, "ended_at")
    peak_wind = mw.v_num(payload, "peak_wind_mph", required=False, minimum="0.0", places=1)

    record = resolve.outage(outage_id)
    if record["status"] != "OPEN":
        raise ApiError("ERR_OUTAGE_ALREADY_CLOSED")
    if ended_at <= record["started_at"]:
        raise ApiError("ERR_INTERVAL_INVALID")

    # Half-open overlap: intervals that merely abut are accepted.
    for other in db.outage_events.values():
        if other["id"] == record["id"] or other["tower_id"] != record["tower_id"]:
            continue
        if other["status"] != "CLOSED" or other.get("ended_at") is None:
            continue
        if record["started_at"] < other["ended_at"] and other["started_at"] < ended_at:
            raise ApiError("ERR_OUTAGE_WINDOW_OVERLAP")

    record["ended_at"] = ended_at
    if peak_wind is not None:
        record["peak_wind_mph"] = peak_wind
    record["status"] = "CLOSED"
    record["duration_minutes"] = whole_minutes_between(record["started_at"], ended_at)
    record["sla_excluded"] = calc.outage_sla_excluded(
        record["cause"], record.get("peak_wind_mph"), record.get("planned_notice_days"))
    db.touch(record)
    return response.object_response(domain.outage_view(record))


# ---------------------------------------------------------------------------
# outage credits
# ---------------------------------------------------------------------------
@bp.post("/outage-credits")
def create_credit():
    mw.require(mw.ROLE_BILLING_ADMIN)
    payload = mw.body()
    outage_id = mw.v_ref(payload, "outage_event_id")
    subscriber_id = mw.v_ref(payload, "subscriber_id")

    outage = resolve.outage(outage_id)
    subscriber = resolve.subscriber(subscriber_id)

    # Rung 8 -- an open incident has no fixed duration to price.
    if outage["status"] != "CLOSED":
        raise ApiError("ERR_OUTAGE_NOT_CLOSED")
    # Rung 13 -- the account must hang off a sector on the failed tower.
    if _subscriber_tower_id(subscriber) != outage["tower_id"]:
        raise ApiError("ERR_SUBSCRIBER_NOT_AFFECTED")
    # Rung 14 -- one live credit per (event, account).
    for credit in db.outage_credits.values():
        if credit["outage_event_id"] == outage["id"] \
                and credit["subscriber_id"] == subscriber["id"] \
                and credit["status"] in LIVE_CREDIT_STATUSES:
            raise ApiError("ERR_CREDIT_ALREADY_ISSUED")

    plan = db.service_plans.get(subscriber["service_plan_id"])
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    method = plan["sla_credit_method"]

    window_start, window_end = _cycle_bounds(subscriber)
    this_clipped = calc.clipped_minutes(outage, window_start, window_end)

    if method == "SLA_SHORTFALL":
        cycle_minutes = 0
        events = [e for e in db.outage_events.values()
                  if e["tower_id"] == outage["tower_id"] and e["status"] == "CLOSED"]
        events.sort(key=lambda e: (e["started_at"], e["created_at"], e["_seq"]))
        for event in events:
            cycle_minutes += calc.creditable_minutes(event, window_start, window_end)
        measured, shortfall, gross = calc.sla_shortfall_amounts(plan, cycle_minutes)
        prior = 0
        for credit in db.outage_credits.values():
            if credit["subscriber_id"] != subscriber["id"]:
                continue
            if credit["status"] not in LIVE_CREDIT_STATUSES:
                continue
            other = db.outage_events.get(credit["outage_event_id"])
            if other is None:
                continue
            if calc.clipped_minutes(other, window_start, window_end) <= 0:
                continue
            prior += int(credit["credit_cents"])
        amount = gross - prior
        if amount < 0:
            amount = 0
    else:
        cycle_minutes = calc.creditable_minutes(outage, window_start, window_end)
        measured = Decimal("0.0")
        shortfall = Decimal("0.0")
        prior = 0
        amount = calc.per_incident_amount(plan, cycle_minutes)

    # The three denials, in the pinned order.
    denial_reason = None
    if outage["sla_excluded"]:
        denial_reason = "SLA_EXCLUDED"
    elif this_clipped < calc.MIN_CREDITABLE_MINUTES:
        denial_reason = "BELOW_MINIMUM_DURATION"
    elif amount == 0:
        denial_reason = "NO_SHORTFALL"

    record = db.base_record(
        outage_event_id=outage["id"],
        subscriber_id=subscriber["id"],
        method=method,
        cycle_outage_minutes=int(cycle_minutes),
        measured_uptime_pct=measured,
        shortfall_pct=shortfall,
        prior_cycle_credited_cents=int(prior),
        credit_cents=(0 if denial_reason is not None else int(amount)),
        status=("DENIED" if denial_reason is not None else "PENDING"),
        denial_reason=denial_reason,
        prepared_by_user_id=g.user_id,
        approved_by_user_id=None,
        reversal_reason=None,
    )
    db.outage_credits[record["id"]] = record
    return response.created(domain.credit_view(record))


@bp.get("/outage-credits/<credit_id>")
def read_credit(credit_id):
    mw.require(mw.ROLE_BILLING_ADMIN, mw.ROLE_FINANCE_APPROVER, mw.ROLE_CAPACITY_PLANNER)
    record = resolve.credit(credit_id)
    return response.object_response(domain.credit_view(record))


@bp.get("/outage-credits")
def list_credits():
    mw.require(mw.ROLE_BILLING_ADMIN, mw.ROLE_FINANCE_APPROVER, mw.ROLE_CAPACITY_PLANNER,
               mw.ROLE_SUBSCRIBER)
    limit, offset = mw.pagination()
    spec = mw.filters("subscriber_id", "outage_event_id", "status")
    records = db.ordered(list(db.outage_credits.values()))
    if mw.is_subscriber_caller():
        # A Subscriber caller only ever sees their own credits.
        requested = spec.get("subscriber_id")
        if requested is not None and requested != g.user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")
        records = [c for c in records if c["subscriber_id"] == g.user_id]
    records = mw.apply_filters(records, spec)
    page, total = mw.paginate(records, limit, offset)
    return response.list_response([domain.credit_view(c) for c in page],
                                  limit, offset, total)


@bp.post("/outage-credits/<credit_id>/application")
def apply_credit(credit_id):
    mw.require(mw.ROLE_FINANCE_APPROVER)
    payload = mw.body()
    mw.v_str(payload, "note", required=False)

    record = resolve.credit(credit_id)
    if record["status"] != "PENDING":
        raise ApiError("ERR_CREDIT_NOT_PENDING")
    # Rung 12 -- the applier may not be the preparer.
    if g.user_id == record["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    record["status"] = "APPLIED"
    record["approved_by_user_id"] = g.user_id
    db.touch(record)
    return response.object_response(domain.credit_view(record))


@bp.post("/outage-credits/<credit_id>/reversal")
def reverse_credit(credit_id):
    mw.require(mw.ROLE_FINANCE_APPROVER)
    payload = mw.body()
    reason = mw.v_str(payload, "reversal_reason")

    record = resolve.credit(credit_id)
    if record["status"] != "APPLIED":
        raise ApiError("ERR_CREDIT_NOT_APPLIED")

    # Compensating action: credit_cents is never recomputed, so both money
    # roll-ups return to their exact pre-application values.
    record["status"] = "REVERSED"
    record["reversal_reason"] = reason
    db.touch(record)
    return response.object_response(domain.credit_view(record))
