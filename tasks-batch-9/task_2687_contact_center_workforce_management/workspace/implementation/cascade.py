"""Cascade orchestration: the recompute chains of PRD 2.9, plus the labour-safety
predicates shared by publication and intraday acceptance.

Every helper here writes rows through `set_fields`, which refreshes updated_at and
increments version at most once per row per request (PRD 2.4 / 2.9).
"""
from datetime import timedelta

import calc
from core import D, q2, q4, DB, rows, touch, fail

# ---------------------------------------------------------------------------
# Row writing
# ---------------------------------------------------------------------------
def set_fields(row, updates):
    """Apply updates; touch the row only when a value actually changed."""
    dirty = False
    for key, value in updates.items():
        old = row.get(key)
        if old is None or value is None:
            same = old is None and value is None
        else:
            try:
                same = D(old) == D(value) if isinstance(value, (int, float)) or hasattr(value, "quantize") else old == value
            except Exception:
                same = old == value
        if not same:
            row[key] = value
            dirty = True
    if dirty:
        touch(row)
    return dirty


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------
def shifts_of_agent(agent_id):
    return [r for r in rows("schedule_shifts") if r["agent_id"] == agent_id]


def shifts_of_cycle(cycle_id):
    return [r for r in rows("schedule_shifts") if r["planning_cycle_id"] == cycle_id]


def actions_of_cycle(cycle_id):
    return [r for r in rows("intraday_actions") if r["planning_cycle_id"] == cycle_id]


def actions_of_shift(shift_id):
    return [r for r in rows("intraday_actions") if r["schedule_shift_id"] == shift_id]


def classes_of_cycle(cycle_id):
    return [r for r in rows("hiring_classes") if r["planning_cycle_id"] == cycle_id]


def template_of(shift):
    return DB["shift_templates"][shift["shift_template_id"]]


def agreement_of(agent):
    return DB["labor_agreements"][agent["labor_agreement_id"]]


def cycle_of_row(row):
    """Resolve the PlanningCycle a row belongs to (PRD 2.8 frozen gate)."""
    table = row["_table"]
    if table == "planning_cycles":
        return row
    if table in ("forecast_groups", "marketing_events", "shift_templates", "bid_rounds",
                 "schedule_shifts", "intraday_actions", "hiring_classes"):
        return DB["planning_cycles"].get(row["planning_cycle_id"])
    if table == "interval_plans":
        return calc.cycle_of_interval(row)
    if table == "shift_bids":
        return DB["planning_cycles"].get(DB["bid_rounds"][row["bid_round_id"]]["planning_cycle_id"])
    if table == "adherence_exceptions":
        shift = DB["schedule_shifts"][row["schedule_shift_id"]]
        return DB["planning_cycles"].get(shift["planning_cycle_id"])
    if table == "partner_allocations":
        return calc.cycle_of_interval(DB["interval_plans"][row["interval_plan_id"]])
    return None


def require_not_frozen(cycle):
    if cycle is not None and cycle["posture"] == "FROZEN":
        fail("ERR_CYCLE_FROZEN", "The planning cycle is frozen")


# ---------------------------------------------------------------------------
# Interval supply, coverage and the absorbable-volume chain
# ---------------------------------------------------------------------------
def shift_covers(shift, ip, start=None, end=None):
    s = shift["_start"] if start is None else start
    e = shift["_end"] if end is None else end
    return s <= ip["_start"] and ip["_end"] <= e


def scheduled_agents_for(ip, group, override_shift=None, override_start=None, override_end=None):
    count = 0
    for shift in rows("schedule_shifts"):
        if shift["publication_status"] != "PUBLISHED":
            continue
        if template_of(shift)["skill_code"] != group["skill_code"]:
            continue
        if override_shift is not None and shift["id"] == override_shift["id"]:
            if shift_covers(shift, ip, override_start, override_end):
                count += 1
            continue
        if shift_covers(shift, ip):
            count += 1
    return count


def routing_agents_for(ip, group):
    inflow = 0
    outflow = 0
    for act in rows("intraday_actions"):
        if act["kind"] != "ROUTING_ADJUSTMENT" or act["status"] != "ACCEPTED":
            continue
        if act["_interval_start"] != ip["_start"]:
            continue
        if act["target_forecast_group_id"] == group["id"]:
            inflow += int(act["agents_shifted"])
        if act["source_forecast_group_id"] == group["id"]:
            outflow += int(act["agents_shifted"])
    return inflow, outflow


def recompute_interval_supply(ip):
    """scheduled/routing/effective agents, then coverage and the capacity chain."""
    group = calc.group_of(ip)
    cycle = calc.cycle_of_group(group)
    scheduled = scheduled_agents_for(ip, group)
    inflow, outflow = routing_agents_for(ip, group)
    effective = scheduled + inflow - outflow
    gap, state = calc.coverage_of(int(ip["required_agents"]), effective)
    set_fields(ip, {
        "scheduled_agents": scheduled,
        "routing_inflow_agents": inflow,
        "routing_outflow_agents": outflow,
        "effective_scheduled_agents": effective,
        "coverage_gap": gap,
        "coverage_state": state,
    })
    recompute_interval_capacity(ip, group, cycle)


def recompute_interval_capacity(ip, group=None, cycle=None):
    group = group or calc.group_of(ip)
    cycle = cycle or calc.cycle_of_group(group)
    icv = calc.internal_capacity_volume(ip, group, cycle)
    allocatable = int(ip["volume_forecast"]) - icv
    if allocatable < 0:
        allocatable = 0
    committed = calc.partner_committed_volume(ip["id"])
    unserved = allocatable - committed
    if unserved < 0:
        unserved = 0
    set_fields(ip, {
        "internal_capacity_volume": icv,
        "allocatable_volume": allocatable,
        "partner_committed_volume": committed,
        "unserved_volume": unserved,
    })


def recompute_interval_forecast(ip, excluded_event_ids=()):
    """The full forward chain: uplift -> volume -> aht -> staffing -> coverage -> capacity."""
    group = calc.group_of(ip)
    cycle = calc.cycle_of_group(group)
    uplift = calc.applied_event_uplift_pct(ip, group, excluded_event_ids)
    volume = calc.interval_volume_forecast(ip, group, uplift)
    aht = calc.interval_aht_forecast(group, uplift)
    set_fields(ip, {
        "applied_event_uplift_pct": uplift,
        "volume_forecast": volume,
        "aht_forecast_seconds": aht,
    })
    req_sl, req_occ, req = calc.staffing_requirement(ip, group, cycle)
    scheduled = scheduled_agents_for(ip, group)
    inflow, outflow = routing_agents_for(ip, group)
    effective = scheduled + inflow - outflow
    gap, state = calc.coverage_of(req, effective)
    set_fields(ip, {
        "required_service_level": req_sl,
        "required_occupancy_capped": req_occ,
        "required_agents": req,
        "scheduled_agents": scheduled,
        "routing_inflow_agents": inflow,
        "routing_outflow_agents": outflow,
        "effective_scheduled_agents": effective,
        "coverage_gap": gap,
        "coverage_state": state,
    })
    recompute_interval_capacity(ip, group, cycle)


# ---------------------------------------------------------------------------
# Cycle aggregates and the automatic posture edges (PRD 3.7)
# ---------------------------------------------------------------------------
def recompute_short_interval_count(cycle, evaluate_edges=True):
    count = 0
    for ip in calc.cycle_intervals(cycle["id"]):
        if ip["coverage_state"] == "SHORT":
            count += 1
    set_fields(cycle, {"short_interval_count": count})
    if evaluate_edges:
        evaluate_posture_edges(cycle)


def evaluate_posture_edges(cycle):
    threshold = int(cycle["intraday_alert_short_threshold"])
    count = int(cycle["short_interval_count"])
    if cycle["posture"] == "SCHEDULE_PUBLISHED" and count >= threshold:
        set_fields(cycle, {"posture": "INTRADAY_ALERT"})
    elif cycle["posture"] == "INTRADAY_ALERT" and count < threshold:
        set_fields(cycle, {"posture": "SCHEDULE_PUBLISHED"})


def recompute_total_scheduled_hours(cycle):
    total = D(0)
    for shift in shifts_of_cycle(cycle["id"]):
        if shift["publication_status"] == "PUBLISHED":
            total += D(shift["paid_hours"])
    set_fields(cycle, {"total_scheduled_hours": q2(total)})


def recompute_ot_ledgers(cycle):
    hours = D(0)
    cents = 0
    for act in actions_of_cycle(cycle["id"]):
        if act["kind"] == "OT_OFFER" and act["status"] == "ACCEPTED":
            hours += D(act["hours"])
            cents += int(act["cost_cents"])
    set_fields(cycle, {"ot_hours_committed": q2(hours), "ot_spend_committed_cents": cents})


def recompute_headcount_active(cycle):
    graduated_classes = {c["id"] for c in classes_of_cycle(cycle["id"]) if c["status"] == "GRADUATED"}
    agents_with_shift = set()
    for shift in shifts_of_cycle(cycle["id"]):
        if shift["publication_status"] in ("DRAFT", "PUBLISHED"):
            agents_with_shift.add(shift["agent_id"])
    count = 0
    for agent in rows("agents"):
        if agent["status"] != "ACTIVE":
            continue
        if agent["id"] in agents_with_shift or (
            agent["hiring_class_id"] is not None and agent["hiring_class_id"] in graduated_classes
        ):
            count += 1
    set_fields(cycle, {"headcount_active": count})


def recompute_pipeline_fte(cycle):
    total = D(0)
    for cls in classes_of_cycle(cycle["id"]):
        if cls["status"] in ("CHARTERED", "IN_TRAINING"):
            total += D(cls["effective_fte_at_horizon_end"])
    set_fields(cycle, {"pipeline_fte": q2(total)})


# ---------------------------------------------------------------------------
# Agent rollups (PRD 3.6, 3.8)
# ---------------------------------------------------------------------------
def recompute_agent_hours(agent):
    total = D(0)
    for shift in shifts_of_agent(agent["id"]):
        if shift["publication_status"] == "PUBLISHED":
            total += D(shift["paid_hours"])
    set_fields(agent, {"scheduled_hours_committed": q2(total)})


def scored_shifts(agent_id):
    return [
        s for s in shifts_of_agent(agent_id)
        if s["publication_status"] == "PUBLISHED" and s["adherence_status"] != "PENDING"
    ]


def recompute_agent_adherence(agent):
    num = D(0)
    den = D(0)
    flags = 0
    for shift in scored_shifts(agent["id"]):
        num += D(shift["scheduled_seconds"]) - D(shift["out_of_adherence_seconds"]) + D(shift["excused_seconds"])
        den += D(shift["scheduled_seconds"])
        if calc.shift_is_flagged(shift):
            flags += 1
    pct = q4(1) if den == 0 else q4(num / den)
    status = agent["coaching_status"]
    if flags >= 1:
        status = "COACHING_ACTIVE"
    elif agent["coaching_status"] == "COACHING_ACTIVE":
        status = "CLEARED"
    set_fields(agent, {
        "adherence_pct": pct,
        "coaching_flag_count": flags,
        "coaching_status": status,
    })


def recompute_enrolled_agent_count(agreement):
    count = 0
    for agent in rows("agents"):
        if agent["labor_agreement_id"] == agreement["id"] and agent["status"] in ("ACTIVE", "LEAVE"):
            count += 1
    set_fields(agreement, {"enrolled_agent_count": count})


def recompute_slots_awarded(template):
    count = 0
    for bid in rows("shift_bids"):
        if bid["status"] == "AWARDED" and bid["awarded_shift_template_id"] == template["id"]:
            count += 1
    set_fields(template, {"slots_awarded": count})


def recompute_interval_count(group):
    set_fields(group, {"interval_count": len(calc.group_intervals(group["id"]))})


# ---------------------------------------------------------------------------
# Shift derived fields
# ---------------------------------------------------------------------------
def recompute_shift_hours(shift):
    elapsed = int((shift["_end"] - shift["_start"]).total_seconds())
    scheduled = elapsed - int(shift["unpaid_break_seconds"])
    ot = D(0)
    vto = D(0)
    for act in actions_of_shift(shift["id"]):
        if act["status"] != "ACCEPTED":
            continue
        if act["kind"] == "OT_OFFER":
            ot += D(act["hours"])
        elif act["kind"] == "VTO_OFFER":
            vto += D(act["hours"])
    set_fields(shift, {
        "scheduled_seconds": scheduled,
        "paid_hours": q2(D(scheduled) / D(3600)),
        "ot_hours": q2(ot),
        "vto_hours": q2(vto),
    })


def move_shift_end(shift, new_end):
    from core import iso3
    shift["_end"] = new_end
    shift["end_at"] = iso3(new_end)
    touch(shift)
    recompute_shift_hours(shift)


def intervals_covered_by(shift, start=None, end=None):
    """Interval plans whose half-open span is fully contained by the shift's span and
    whose group skill matches the shift template's skill (PRD 3.2 coverage)."""
    skill = template_of(shift)["skill_code"]
    out = []
    for ip in rows("interval_plans"):
        group = calc.group_of(ip)
        if group["skill_code"] != skill:
            continue
        if shift_covers(shift, ip, start, end):
            out.append(ip)
    return out


def recompute_coverage_for_intervals(intervals):
    cycles = {}
    for ip in intervals:
        recompute_interval_supply(ip)
        cycle = calc.cycle_of_interval(ip)
        cycles[cycle["id"]] = cycle
    for cycle in cycles.values():
        recompute_short_interval_count(cycle)
    return cycles


# ---------------------------------------------------------------------------
# Labour-safety predicates (PRD 3.6, priorities 110-125)
# ---------------------------------------------------------------------------
def _spans_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def neighbours(agent_id, exclude_shift_id):
    return [
        s for s in shifts_of_agent(agent_id)
        if s["id"] != exclude_shift_id and s["publication_status"] != "CANCELLED"
    ]


def check_min_rest(agent, agreement, shift, start=None, end=None):
    s = shift["_start"] if start is None else start
    e = shift["_end"] if end is None else end
    limit = D(agreement["min_rest_hours"])
    for other in neighbours(agent["id"], shift["id"]):
        if _spans_overlap(s, e, other["_start"], other["_end"]):
            continue  # overlapping neighbours are the overlap rule's business
        if other["_end"] <= s:
            gap = D((s - other["_end"]).total_seconds()) / D(3600)
        else:
            gap = D((other["_start"] - e).total_seconds()) / D(3600)
        if gap < limit:
            fail("ERR_MIN_REST_VIOLATION",
                 "Rest gap of %s hours is below the agreement minimum" % gap)


def check_overlap(agent, shift, start=None, end=None):
    s = shift["_start"] if start is None else start
    e = shift["_end"] if end is None else end
    for other in neighbours(agent["id"], shift["id"]):
        if _spans_overlap(s, e, other["_start"], other["_end"]):
            fail("ERR_SHIFT_OVERLAP", "The agent already holds an overlapping shift")


def projected_weekly_hours(agent_id, shift, paid_hours, force_include=False):
    total = D(0)
    for other in shifts_of_agent(agent_id):
        if other["id"] == shift["id"]:
            if force_include or other["publication_status"] == "PUBLISHED":
                total += D(paid_hours)
            continue
        if other["publication_status"] == "PUBLISHED":
            total += D(other["paid_hours"])
    return q2(total)


def check_weekly_hours(agreement, projected):
    if D(projected) > D(agreement["max_weekly_hours"]):
        fail("ERR_MAX_WEEKLY_HOURS_EXCEEDED",
             "Projected weekly hours %s exceed the agreement ceiling" % projected)


def longest_consecutive_run(agent_id):
    dates = sorted({
        s["_date"] for s in shifts_of_agent(agent_id)
        if s["publication_status"] != "CANCELLED"
    })
    best = 0
    run = 0
    previous = None
    for d in dates:
        if previous is not None and (d - previous) == timedelta(days=1):
            run += 1
        else:
            run = 1
        best = max(best, run)
        previous = d
    return best


def check_consecutive_days(agent, agreement):
    if longest_consecutive_run(agent["id"]) > int(agreement["max_consecutive_days"]):
        fail("ERR_MAX_CONSECUTIVE_DAYS_EXCEEDED",
             "The agent's consecutive-day run exceeds the agreement ceiling")


def check_vto_coverage(shift, new_end):
    """Releasing hours may not push any covered interval from COVERED to SHORT."""
    for ip in intervals_covered_by(shift):
        if ip["coverage_state"] != "COVERED":
            continue
        group = calc.group_of(ip)
        scheduled = scheduled_agents_for(
            ip, group, override_shift=shift, override_start=shift["_start"], override_end=new_end
        )
        inflow, outflow = routing_agents_for(ip, group)
        gap, state = calc.coverage_of(int(ip["required_agents"]), scheduled + inflow - outflow)
        if state == "SHORT":
            fail("ERR_VTO_WOULD_BREACH_COVERAGE",
                 "Releasing the hours would leave interval %s short" % ip["id"])


# ---------------------------------------------------------------------------
# Shift minting (manual create and the award cascade share this)
# ---------------------------------------------------------------------------
def mint_shift(cycle, agent, template, service_date, shift_bid_id=None):
    from core import new_row, iso3, iso_date, date_to_dt, q2, q4
    hh, mm = template["start_time_local"].split(":")
    start = date_to_dt(service_date) + timedelta(hours=int(hh), minutes=int(mm))
    end = start + timedelta(minutes=int(template["duration_minutes"]))
    unpaid = int(template["unpaid_break_minutes"]) * 60
    scheduled = int((end - start).total_seconds()) - unpaid
    return new_row("schedule_shifts", {
        "planning_cycle_id": cycle["id"],
        "agent_id": agent["id"],
        "shift_template_id": template["id"],
        "service_date": iso_date(service_date),
        "start_at": iso3(start),
        "end_at": iso3(end),
        "unpaid_break_seconds": unpaid,
        "scheduled_seconds": scheduled,
        "paid_hours": q2(D(scheduled) / D(3600)),
        "ot_hours": q2(0),
        "vto_hours": q2(0),
        "publication_status": "DRAFT",
        "adherence_status": "PENDING",
        "out_of_adherence_seconds": 0,
        "excused_seconds": 0,
        "adherence_pct": q4(1),
        "flagged_by_user_id": None,
        "_start": start,
        "_end": end,
        "_date": service_date,
        "_shift_bid_id": shift_bid_id,
    })


def shifts_of_bid(bid_id):
    return [r for r in rows("schedule_shifts") if r.get("_shift_bid_id") == bid_id]


def shifts_of_round(round_id):
    out = []
    for shift in rows("schedule_shifts"):
        bid_id = shift.get("_shift_bid_id")
        if bid_id is None:
            continue
        bid = DB["shift_bids"].get(bid_id)
        if bid is not None and bid["bid_round_id"] == round_id:
            out.append(shift)
    return out
