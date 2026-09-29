"""Coaching allocations and the on-site hours ledger (PRD §3.9)."""

from decimal import Decimal

from flask import Blueprint, request

import calculations as calc
import cascades
import lookups
import response
import serializers
import store
import validation as v
from auth import require
from errors import fail
from validation import as_date, as_dt, body, iso_week_key

bp = Blueprint("coaching", __name__)

COMPLETION_TOLERANCE_HOURS = Decimal("0.5")


def _allocation_of(session):
    return lookups.get_allocation(session["coaching_allocation_id"])


def _provider_of_allocation(allocation):
    return store.DB.providers.get(allocation["provider_id"])


def _own_session(principal, session):
    """A Provider reaches a session through its allocation; a Coach through the assignment."""
    allocation = _allocation_of(session)
    lookups.own_provider_id(principal, allocation["provider_id"])
    lookups.own_coach_on_allocation(principal, allocation)
    return allocation


def _sibling_sessions(provider_id):
    """Every session under any allocation of one provider, with its allocation."""
    out = []
    for allocation in cascades.allocations_of(provider_id):
        for session in cascades.sessions_of(allocation["id"]):
            out.append((allocation, session))
    return out


def _intervals_conflict(new_start, new_end, other_start, other_end):
    """Coaching intervals are CLOSED, so sessions that merely touch do conflict."""
    return new_start <= other_end and other_start <= new_end


# -------------------------------------------------------------- allocations


@bp.post("/providers/<provider_id>/coaching-allocations")
def create_allocation(provider_id):
    require("StateAdministrator")
    provider = lookups.get_provider(provider_id)
    data = body()
    coach_user_id = v.req_str(data, "coach_user_id")
    funding_source = v.req_enum(data, "funding_source", v.FUNDING_SOURCES)
    funding_grant_id = v.opt_str(data, "funding_grant_id")
    period_start = v.req_instant(data, "period_start")
    period_end = v.req_instant(data, "period_end")
    allocated_hours = v.req_decimal(data, "allocated_hours", minimum=0,
                                   exclusive_min=True, max_places=1)
    hourly_rate_cents = v.req_int(data, "hourly_rate_cents", 1)
    if funding_source == "GRANT" and not funding_grant_id:
        fail("ERR_VALIDATION", "funding_grant_id is required when funding_source is GRANT")

    # Body foreign key (PRD §2.6, §2.7 step 7).
    grant = lookups.get_grant(funding_grant_id) if funding_grant_id else None
    if funding_source == "STATE_BASE":
        # The state base appropriation carries no grant linkage.
        funding_grant_id = None

    base, admin_fee, total = calc.compute_allocation_cost(allocated_hours, hourly_rate_cents)
    spend_cap = calc.compute_spend_cap(provider, funding_source, grant)

    # The hours check is evaluated before the spend check (PRD §3.9).
    hours_ceiling = calc.TIER_HOURS_CEILING[calc.effective_tier(provider)]
    if allocated_hours > hours_ceiling:
        fail("ERR_COACHING_HOURS_CAP_EXCEEDED",
             "allocated_hours may not exceed %s hours at the provider's effective tier"
             % hours_ceiling)
    if total > spend_cap:
        fail("ERR_COACHING_SPEND_CAP_EXCEEDED",
             "total_cost_cents %d exceeds the binding spend cap of %d cents" % (total, spend_cap))

    rec = store.base_record(
        provider_id=provider["id"],
        funding_grant_id=funding_grant_id,
        coach_user_id=coach_user_id,
        funding_source=funding_source,
        period_start=period_start,
        period_end=period_end,
        allocated_hours=allocated_hours,
        hourly_rate_cents=hourly_rate_cents,
        base_hours_cost_cents=base,
        admin_fee_cents=admin_fee,
        total_cost_cents=total,
        spend_cap_cents=spend_cap,
        scheduled_hours=Decimal("0.0"),
        delivered_hours=Decimal("0.0"),
        remaining_hours=allocated_hours,
        status="PROPOSED",
    )
    store.DB.coaching_allocations[rec["id"]] = rec
    return response.created(serializers.dump("coaching_allocation", rec))


@bp.get("/coaching-allocations")
def list_allocations():
    require("StateAdministrator", "Provider", "Coach")
    records = store.sort_created(list(store.DB.coaching_allocations.values()))
    for field in ("provider_id", "funding_grant_id", "coach_user_id", "status"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return response.paginate(records, serializers.maker("coaching_allocation"))


@bp.get("/coaching-allocations/<coaching_allocation_id>")
def read_allocation(coaching_allocation_id):
    principal = require("StateAdministrator", "Provider", "Coach")
    allocation = lookups.get_allocation(coaching_allocation_id)
    lookups.own_provider_id(principal, allocation["provider_id"])
    lookups.own_coach_on_allocation(principal, allocation)
    return response.ok(serializers.dump("coaching_allocation", allocation))


@bp.post("/coaching-allocations/<coaching_allocation_id>/accept")
def accept_allocation(coaching_allocation_id):
    principal = require("Provider")
    allocation = lookups.get_allocation(coaching_allocation_id)
    lookups.own_provider_id(principal, allocation["provider_id"])
    body()

    if allocation["status"] != "PROPOSED":
        fail("ERR_ALLOCATION_STATE_INVALID", "acceptance is available only from PROPOSED")
    if allocation["funding_source"] == "GRANT":
        grant = store.DB.improvement_grants.get(allocation.get("funding_grant_id"))
        if grant is None or grant["status"] != "OPEN":
            fail("ERR_GRANT_NOT_OPEN",
                 "the funding grant must be OPEN when a grant-funded allocation is accepted")

    allocation["status"] = "ACTIVE"
    store.touch(allocation)
    return response.ok(serializers.dump("coaching_allocation", allocation))


# ----------------------------------------------------------------- sessions


@bp.post("/coaching-allocations/<coaching_allocation_id>/sessions")
def schedule_session(coaching_allocation_id):
    principal = require("Coach")
    allocation = lookups.get_allocation(coaching_allocation_id)
    # The acting coach identity is checked before any period or budget rule.
    lookups.own_coach_on_allocation(principal, allocation)
    provider = _provider_of_allocation(allocation)
    data = body()
    scheduled_start = v.req_instant(data, "scheduled_start")
    scheduled_end = v.req_instant(data, "scheduled_end")

    if allocation["status"] != "ACTIVE":
        fail("ERR_ALLOCATION_STATE_INVALID",
             "sessions may be scheduled only under an ACTIVE allocation")
    if provider is None or provider["status"] != "ACTIVE":
        fail("ERR_PROVIDER_STATE_INVALID",
             "the provider must be ACTIVE for a session to be scheduled")

    start_dt = as_dt(scheduled_start)
    end_dt = as_dt(scheduled_end)
    hours = calc.interval_hours(start_dt, end_dt)
    week_key = iso_week_key(start_dt)

    # Check 1: site occupation on closed intervals, then the weekly capacity bucket.
    for other_allocation, other in _sibling_sessions(provider["id"]):
        if other["status"] != "SCHEDULED":
            continue
        if other_allocation.get("coach_user_id") != allocation.get("coach_user_id"):
            continue
        if _intervals_conflict(start_dt, end_dt,
                               as_dt(other["scheduled_start"]), as_dt(other["scheduled_end"])):
            fail("ERR_ONSITE_CAPACITY_CONFLICT",
                 "the coach already occupies this provider's site over that interval")

    week_total = calc.dec("0")
    for _other_allocation, other in _sibling_sessions(provider["id"]):
        if other.get("iso_week_key") != week_key:
            continue
        if other["status"] == "SCHEDULED":
            week_total += calc.dec(other["scheduled_hours"])
        elif other["status"] == "DELIVERED":
            week_total += calc.dec(other["delivered_hours"] or 0)
    if week_total + hours > calc.dec(provider["weekly_onsite_cap_hours"]):
        fail("ERR_ONSITE_CAPACITY_CONFLICT",
             "the provider's weekly on-site capacity for %s would be exceeded" % week_key)

    # Check 2: the allocation period bounds, both endpoints inclusive.
    period_start = as_date(allocation["period_start"])
    period_end = as_date(allocation["period_end"])
    inside = (period_start <= start_dt.date() <= period_end
              and period_start <= end_dt.date() <= period_end)
    if not inside or end_dt <= start_dt:
        fail("ERR_SESSION_OUTSIDE_ALLOCATION_PERIOD",
             "the session interval must lie inside the allocation period and be non-empty")

    # Check 3: the hours budget.
    if calc.dec(allocation["remaining_hours"]) < hours:
        fail("ERR_COACHING_HOURS_CAP_EXCEEDED",
             "the allocation has only %s hours remaining" % allocation["remaining_hours"])

    rec = store.base_record(
        coaching_allocation_id=allocation["id"],
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        scheduled_hours=hours,
        delivered_hours=None,
        iso_week_key=week_key,
        status="SCHEDULED",
    )
    store.DB.coaching_sessions[rec["id"]] = rec

    allocation["scheduled_hours"] = calc.dec(allocation["scheduled_hours"]) + hours
    allocation["remaining_hours"] = calc.dec(allocation["remaining_hours"]) - hours
    store.touch(allocation)

    return response.created(serializers.dump("coaching_session", rec))


@bp.get("/coaching-sessions")
def list_sessions():
    require("StateAdministrator", "Provider", "Coach")
    records = store.sort_created(list(store.DB.coaching_sessions.values()))
    for field in ("coaching_allocation_id", "status", "iso_week_key"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return response.paginate(records, serializers.maker("coaching_session"))


@bp.get("/coaching-sessions/<coaching_session_id>")
def read_session(coaching_session_id):
    principal = require("StateAdministrator", "Provider", "Coach")
    session = lookups.get_session(coaching_session_id)
    _own_session(principal, session)
    return response.ok(serializers.dump("coaching_session", session))


@bp.post("/coaching-sessions/<coaching_session_id>/complete")
def complete_session(coaching_session_id):
    principal = require("Coach")
    session = lookups.get_session(coaching_session_id)
    allocation = _own_session(principal, session)
    data = body()
    delivered = v.req_decimal(data, "delivered_hours", minimum=0, exclusive_min=True,
                              max_places=1)
    ceiling = calc.dec(session["scheduled_hours"]) + COMPLETION_TOLERANCE_HOURS
    if delivered > ceiling:
        fail("ERR_VALIDATION",
             "delivered_hours may not exceed the scheduled hours plus half an hour of tolerance")

    if session["status"] != "SCHEDULED":
        fail("ERR_SESSION_STATE_INVALID", "only a SCHEDULED session may be completed")

    scheduled = calc.dec(session["scheduled_hours"])
    session["status"] = "DELIVERED"
    session["delivered_hours"] = delivered
    store.touch(session)

    allocation["scheduled_hours"] = calc.dec(allocation["scheduled_hours"]) - scheduled
    allocation["delivered_hours"] = calc.dec(allocation["delivered_hours"]) + delivered
    allocation["remaining_hours"] = (calc.dec(allocation["allocated_hours"])
                                    - calc.dec(allocation["scheduled_hours"])
                                    - calc.dec(allocation["delivered_hours"]))
    store.touch(allocation)

    return response.ok(serializers.dump("coaching_session", session))


@bp.post("/coaching-sessions/<coaching_session_id>/cancel")
def cancel_session(coaching_session_id):
    principal = require("Coach", "StateAdministrator")
    session = lookups.get_session(coaching_session_id)
    allocation = _own_session(principal, session)
    data = body()
    v.opt_str(data, "reason")

    if session["status"] != "SCHEDULED":
        fail("ERR_SESSION_STATE_INVALID", "only a SCHEDULED session may be cancelled")

    scheduled = calc.dec(session["scheduled_hours"])
    session["status"] = "CANCELLED"
    store.touch(session)

    # Delivered hours are permanently consumed; only scheduled hours come back.
    allocation["scheduled_hours"] = calc.dec(allocation["scheduled_hours"]) - scheduled
    allocation["remaining_hours"] = calc.dec(allocation["remaining_hours"]) + scheduled
    store.touch(allocation)

    return response.ok(serializers.dump("coaching_session", session))
