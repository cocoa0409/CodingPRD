"""The three intraday levers: overtime, voluntary time off and routing (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint, g

import calc
from cascade import (
    agreement_of, check_min_rest, check_overlap, check_vto_coverage,
    check_weekly_hours, intervals_covered_by, move_shift_end, projected_weekly_hours,
    recompute_agent_hours, recompute_coverage_for_intervals, recompute_ot_ledgers,
    recompute_short_interval_count, recompute_total_scheduled_hours,
    require_not_frozen, set_fields,
)
from core import (
    D, bad, body, created, fail, get, maybe, new_row, now_dt, ok, present, public, q2,
    q4, rows, require_auth, v_datetime, v_enum, v_id, v_int, v_num, v_forbidden,
)
from listing import std_list

bp = Blueprint("intraday", __name__)

ACTION_READERS = ["CapacityPlanner", "WorkforceAnalyst", "SchedulingManager",
                  "IntradayController", "TeamCoach", "Agent"]
KINDS = ("OT_OFFER", "VTO_OFFER", "ROUTING_ADJUSTMENT")


def v_hours(b, name="hours"):
    hours = v_num(b, name, minimum="0.5", maximum="8.0")
    if (hours * D(2)) != (hours * D(2)).to_integral_value():
        bad(name, "must be a multiple of 0.5")
    return q2(hours)


def interval_at(group_id, instant):
    for ip in rows("interval_plans"):
        if ip["forecast_group_id"] == group_id and ip["_start"] == instant:
            return ip
    return None


def affected_intervals(shift, old_end, new_end):
    seen = {}
    for span_end in (old_end, new_end):
        for ip in intervals_covered_by(shift, shift["_start"], span_end):
            seen[ip["id"]] = ip
    return list(seen.values())


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
@bp.post("/intraday-actions")
def create_intraday_action():
    require_auth(["IntradayController"])
    b = body()
    cycle_id = v_id(b, "planning_cycle_id")
    kind = v_enum(b, "kind", KINDS)
    expires_raw, expires_dt = v_datetime(b, "expires_at")
    agent_id = None
    shift_id = None
    target_id = None
    source_id = None
    hours = None
    agents_shifted = None
    interval_raw = None
    interval_dt = None
    if kind == "OT_OFFER":
        agent_id = v_id(b, "agent_id")
        shift_id = v_id(b, "schedule_shift_id")
        target_id = v_id(b, "target_forecast_group_id")
        hours = v_hours(b)
        v_forbidden(b, "source_forecast_group_id", kind)
        v_forbidden(b, "agents_shifted", kind)
        v_forbidden(b, "interval_start", kind)
    elif kind == "VTO_OFFER":
        agent_id = v_id(b, "agent_id")
        shift_id = v_id(b, "schedule_shift_id")
        hours = v_hours(b)
        v_forbidden(b, "target_forecast_group_id", kind)
        v_forbidden(b, "source_forecast_group_id", kind)
        v_forbidden(b, "agents_shifted", kind)
        v_forbidden(b, "interval_start", kind)
    else:
        target_id = v_id(b, "target_forecast_group_id")
        source_id = v_id(b, "source_forecast_group_id")
        agents_shifted = v_int(b, "agents_shifted", minimum=1)
        interval_raw, interval_dt = v_datetime(b, "interval_start")
        v_forbidden(b, "agent_id", kind)
        v_forbidden(b, "schedule_shift_id", kind)
        v_forbidden(b, "hours", kind)

    cycle = get("planning_cycles", cycle_id)
    agent = get("agents", agent_id) if agent_id is not None else None
    shift = get("schedule_shifts", shift_id) if shift_id is not None else None
    target = get("forecast_groups", target_id) if target_id is not None else None
    source = get("forecast_groups", source_id) if source_id is not None else None
    require_not_frozen(cycle)
    if kind == "OT_OFFER" and target["skill_code"] not in agent["skills"]:
        fail("ERR_SKILL_MISMATCH",
             "The offered agent does not hold skill %s" % target["skill_code"])

    source_ip = None
    target_ip = None
    if kind == "ROUTING_ADJUSTMENT":
        source_ip = interval_at(source["id"], interval_dt)
        target_ip = interval_at(target["id"], interval_dt)
        staffed = 0 if source_ip is None else int(source_ip["effective_scheduled_agents"])
        if agents_shifted > staffed:
            fail("ERR_ROUTING_OUTFLOW_EXCEEDS_STAFFING",
                 "The source interval staffs only %d agents" % staffed)

    row = new_row("intraday_actions", {
        "planning_cycle_id": cycle["id"],
        "agent_id": None if agent is None else agent["id"],
        "schedule_shift_id": None if shift is None else shift["id"],
        "target_forecast_group_id": None if target is None else target["id"],
        "source_forecast_group_id": None if source is None else source["id"],
        "kind": kind,
        "hours": hours,
        "agents_shifted": agents_shifted,
        "interval_start": interval_raw,
        "expires_at": expires_raw,
        "cost_cents": 0,
        "ot_multiplier_applied": None,
        "responded_by_user_id": None,
        "status": "OFFERED",
        "_expires": expires_dt,
        "_interval_start": interval_dt,
    })
    if kind == "ROUTING_ADJUSTMENT":
        set_fields(row, {"status": "ACCEPTED"})
        recompute_coverage_for_intervals([ip for ip in (target_ip, source_ip) if ip is not None])
        recompute_short_interval_count(cycle)
    return created(public(row))


@bp.get("/intraday-actions/<intraday_action_id>")
def read_intraday_action(intraday_action_id):
    require_auth(ACTION_READERS)
    return ok(public(get("intraday_actions", intraday_action_id)))


@bp.get("/intraday-actions")
def list_intraday_actions():
    require_auth(ACTION_READERS)
    return std_list("intraday_actions", [
        ("planning_cycle_id", "planning_cycle_id"),
        ("agent_id", "agent_id"),
        ("schedule_shift_id", "schedule_shift_id"),
        ("target_forecast_group_id", "target_forecast_group_id"),
        ("source_forecast_group_id", "source_forecast_group_id"),
        ("kind", "kind"),
        ("status", "status"),
    ])


# ---------------------------------------------------------------------------
# Responding to an offer
# ---------------------------------------------------------------------------
def hours_delta(hours):
    return timedelta(seconds=int(D(hours) * D(3600)))


def paid_hours_for(shift, new_end):
    seconds = int((new_end - shift["_start"]).total_seconds()) - int(shift["unpaid_break_seconds"])
    return q2(D(seconds) / D(3600))


@bp.post("/intraday-actions/<intraday_action_id>/response")
def respond_to_action(intraday_action_id):
    uid, _role = require_auth(["Agent"])
    b = body()
    answer = v_enum(b, "response", ("ACCEPT", "DECLINE"))
    act = get("intraday_actions", intraday_action_id)
    if act["agent_id"] is None or act["agent_id"] != uid:
        fail("ERR_OWNERSHIP_VIOLATION", "Only the offered agent may respond")
    cycle = get("planning_cycles", act["planning_cycle_id"])
    require_not_frozen(cycle)
    if act["status"] != "OFFERED":
        fail("ERR_ACTION_NOT_OFFERED", "The action is no longer open for a response")

    agent = get("agents", act["agent_id"])
    shift = get("schedule_shifts", act["schedule_shift_id"])
    agreement = agreement_of(agent)
    expired = now_dt() >= act["_expires"]

    if answer == "DECLINE":
        if expired:
            set_fields(act, {"status": "EXPIRED"})
            fail("ERR_ACTION_EXPIRED", "The offer has expired")
        set_fields(act, {"status": "DECLINED", "responded_by_user_id": uid})
        return ok(public(act))

    if act["kind"] == "OT_OFFER":
        new_end = shift["_end"] + hours_delta(act["hours"])
        check_min_rest(agent, agreement, shift, shift["_start"], new_end)
        check_overlap(agent, shift, shift["_start"], new_end)
        check_weekly_hours(
            agreement,
            projected_weekly_hours(agent["id"], shift, paid_hours_for(shift, new_end)),
        )
        if expired:
            set_fields(act, {"status": "EXPIRED"})
            fail("ERR_ACTION_EXPIRED", "The offer has expired")
        pre_spend = int(cycle["ot_spend_committed_cents"])
        tier = calc.ot_tier_multiplier(pre_spend)
        premium = D(agreement["ot_premium_multiplier"])
        cost = calc.overtime_cost(act["hours"], agent["hourly_rate_cents"], tier, premium)
        if pre_spend + cost > int(cycle["ot_budget_cents"]):
            fail("ERR_OT_BUDGET_EXCEEDED",
                 "The acceptance would push committed overtime spend past the cycle budget")
        set_fields(act, {
            "status": "ACCEPTED",
            "responded_by_user_id": uid,
            "cost_cents": cost,
            "ot_multiplier_applied": q4(tier * premium),
        })
        old_end = shift["_end"]
        move_shift_end(shift, new_end)
        recompute_agent_hours(agent)
        recompute_ot_ledgers(cycle)
        recompute_total_scheduled_hours(cycle)
        recompute_coverage_for_intervals(affected_intervals(shift, old_end, new_end))
        recompute_short_interval_count(cycle)
        return ok(public(act))

    # VTO_OFFER
    new_end = shift["_end"] - hours_delta(act["hours"])
    if expired:
        set_fields(act, {"status": "EXPIRED"})
        fail("ERR_ACTION_EXPIRED", "The offer has expired")
    notice_hours = D((shift["_start"] - now_dt()).total_seconds()) / D(3600)
    if notice_hours < D(agreement["vto_min_notice_hours"]):
        fail("ERR_VTO_NOTICE_TOO_SHORT",
             "The notice period of %s hours is below the agreement minimum" % q4(notice_hours))
    check_vto_coverage(shift, new_end)
    set_fields(act, {"status": "ACCEPTED", "responded_by_user_id": uid})
    old_end = shift["_end"]
    move_shift_end(shift, new_end)
    recompute_agent_hours(agent)
    recompute_total_scheduled_hours(cycle)
    recompute_coverage_for_intervals(affected_intervals(shift, old_end, new_end))
    recompute_short_interval_count(cycle)
    return ok(public(act))


# ---------------------------------------------------------------------------
# Revocation
# ---------------------------------------------------------------------------
@bp.post("/intraday-actions/<intraday_action_id>/revoke")
def revoke_action(intraday_action_id):
    require_auth(["IntradayController"])
    act = get("intraday_actions", intraday_action_id)
    cycle = get("planning_cycles", act["planning_cycle_id"])
    require_not_frozen(cycle)
    if act["status"] not in ("OFFERED", "ACCEPTED"):
        fail("ERR_ACTION_NOT_OFFERED", "The action is already terminal")
    was_accepted = act["status"] == "ACCEPTED"
    set_fields(act, {"status": "REVOKED"})
    if not was_accepted:
        return ok(public(act))

    if act["kind"] == "ROUTING_ADJUSTMENT":
        affected = []
        for group_id in (act["target_forecast_group_id"], act["source_forecast_group_id"]):
            ip = interval_at(group_id, act["_interval_start"])
            if ip is not None:
                affected.append(ip)
        recompute_coverage_for_intervals(affected)
        recompute_short_interval_count(cycle)
        return ok(public(act))

    shift = get("schedule_shifts", act["schedule_shift_id"])
    agent = get("agents", shift["agent_id"])
    old_end = shift["_end"]
    if act["kind"] == "OT_OFFER":
        new_end = old_end - hours_delta(act["hours"])
    else:
        new_end = old_end + hours_delta(act["hours"])
    move_shift_end(shift, new_end)
    recompute_agent_hours(agent)
    if act["kind"] == "OT_OFFER":
        recompute_ot_ledgers(cycle)
    recompute_total_scheduled_hours(cycle)
    recompute_coverage_for_intervals(affected_intervals(shift, old_end, new_end))
    recompute_short_interval_count(cycle)
    return ok(public(act))
