"""Derived-state recomputation and the cascade machinery (PRD 2.7, 2.8, 2.11)."""

from datetime import timedelta

import calc
from calc import D, num, round_half_up
from db import (
    apply_fields,
    clock_iso,
    db,
    format_iso,
    now,
    now_iso,
    parse_iso,
    sort_key,
    sorted_records,
    touch,
)

COMMITTED = ("CONFIRMED", "COMPLETED")
ROSTER_LIVE = ("TENTATIVE", "CONFIRMED")


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------


def dt(record, field):
    value = record.get(field)
    if value is None:
        return None
    return parse_iso(value)


def plan_posts(plan_id):
    return sorted_records([p for p in db.posts.values() if p.get("staffing_plan_id") == plan_id])


def post_assignments(post_id):
    return sorted_records([a for a in db.assignments.values() if a.get("post_id") == post_id])


def plan_of_post(post):
    return db.plans.get(post.get("staffing_plan_id"))


def event_of_plan(plan):
    if plan is None:
        return None
    return db.events.get(plan.get("event_id"))


def current_plan(event_id):
    candidates = [
        p for p in db.plans.values() if p.get("event_id") == event_id and p.get("is_current")
    ]
    if not candidates:
        return None
    return sorted_records(candidates)[-1]


def event_lanes(event_id):
    return sorted_records([l for l in db.lanes.values() if l.get("event_id") == event_id])


def event_readings(event_id):
    return sorted_records([r for r in db.readings.values() if r.get("event_id") == event_id])


def event_incidents(event_id):
    return sorted_records([i for i in db.incidents.values() if i.get("event_id") == event_id])


def guard_assignments(guard_id):
    return [a for a in db.assignments.values() if a.get("guard_id") == guard_id]


def assignment_sort_key(assignment):
    """Ascending assignment created_at, tie-broken by ascending post created_at."""
    post = db.posts.get(assignment.get("post_id")) or {}
    return (
        assignment.get("created_at") or "",
        post.get("created_at") or "",
        assignment.get("_seq") or 0,
    )


def plan_committed_rows(plan_id):
    rows = []
    for post in plan_posts(plan_id):
        for assignment in post_assignments(post["id"]):
            if assignment.get("assignment_status") in COMMITTED:
                rows.append(assignment)
    rows.sort(key=assignment_sort_key)
    return rows


def plan_roster_rows(plan_id):
    """Assignments on the plan's posts whose roster state is CONFIRMED or COMPLETED."""
    return plan_committed_rows(plan_id)


# --------------------------------------------------------------------------
# Post: filled_guard_count and status (PRD 3.4)
# --------------------------------------------------------------------------


def post_filled_count(post_id):
    count = 0
    for assignment in db.assignments.values():
        if (
            assignment.get("post_id") == post_id
            and assignment.get("assignment_status") in COMMITTED
            and assignment.get("duty_status") != "NO_SHOW"
        ):
            count += 1
    return count


def recompute_post(post, plan=None):
    if plan is None:
        plan = plan_of_post(post)
    filled = post_filled_count(post["id"])
    plan_status = plan.get("status") if plan else None
    if plan_status in ("SUPERSEDED", "CLOSED"):
        status = "CLOSED"
    elif filled >= post.get("required_guard_count", 0):
        status = "FILLED"
    elif plan_status in ("ACTIVATED", "LOCKED"):
        status = "UNDERSTAFFED"
    elif filled > 0:
        status = "PARTIALLY_STAFFED"
    else:
        status = "OPEN"
    return apply_fields(post, {"filled_guard_count": filled, "status": status})


# --------------------------------------------------------------------------
# StaffingPlan: coverage, posture and the two-column ledger (PRD 3.4, 3.6)
# --------------------------------------------------------------------------


def _supervisor_coverage_ok(plan):
    assessment = db.assessments.get(plan.get("risk_assessment_id"))
    required = 0
    if assessment is not None and assessment.get("required_supervisors") is not None:
        required = assessment["required_supervisors"]
    supervisor_post_ids = set(
        post["id"] for post in plan_posts(plan["id"]) if post.get("post_type") == "SUPERVISOR"
    )
    count = 0
    for assignment in db.assignments.values():
        if (
            assignment.get("post_id") in supervisor_post_ids
            and assignment.get("assignment_status") in COMMITTED
            and assignment.get("duty_status") != "NO_SHOW"
        ):
            count += 1
    return count >= required


def recompute_plan(plan):
    posts = plan_posts(plan["id"])
    open_posts = [p for p in posts if p.get("status") != "CLOSED"]
    required_total = sum(p.get("required_guard_count", 0) for p in open_posts)
    filled_total = sum(p.get("filled_guard_count", 0) for p in open_posts)
    understaffed = sum(1 for p in open_posts if p.get("status") == "UNDERSTAFFED")
    if required_total == 0:
        coverage = D("0.00")
    else:
        coverage = round_half_up(D(filled_total) / D(required_total), 2)
    if coverage >= D("1.00") and _supervisor_coverage_ok(plan) and understaffed == 0:
        posture = "READY"
    elif coverage >= D("0.90"):
        posture = "AT_RISK"
    else:
        posture = "BLOCKED"

    committed_cost = 0
    hours_total = D(0)
    billed_total = 0
    for assignment in plan_committed_rows(plan["id"]):
        committed_cost += assignment.get("line_cost_cents") or 0
        hours_total += D(assignment.get("scheduled_hours") or 0)
        if assignment.get("duty_status") == "RELIEVED":
            billed_total += assignment.get("billed_cost_cents") or 0
    committed_hours = round_half_up(hours_total, 2)

    return apply_fields(
        plan,
        {
            "required_total_staff": required_total,
            "filled_total_staff": filled_total,
            "understaffed_post_count": understaffed,
            "coverage_ratio": num(coverage),
            "readiness_posture": posture,
            "committed_cost_cents": committed_cost,
            "committed_guard_hours": num(committed_hours),
            "budget_remaining_cents": (plan.get("budget_cents") or 0) - committed_cost,
            "billed_cost_cents": billed_total,
            "is_current": plan.get("status") != "SUPERSEDED",
        },
    )


# --------------------------------------------------------------------------
# SecurityEvent: open critical incidents and gate posture (PRD 2.7)
# --------------------------------------------------------------------------

PRE_PLAN_STATUSES = ("PLANNING", "RISK_ASSESSED")
CRITICAL_READING_WINDOW = timedelta(minutes=15)


def open_critical_incident_count(event_id):
    count = 0
    for incident in db.incidents.values():
        if (
            incident.get("event_id") == event_id
            and incident.get("severity") == "CRITICAL"
            and incident.get("status") not in ("RESOLVED", "CLOSED_UNFOUNDED")
        ):
            count += 1
    return count


def _recent_critical_reading(event_id):
    threshold = now() - CRITICAL_READING_WINDOW
    for reading in db.readings.values():
        if reading.get("event_id") != event_id:
            continue
        if reading.get("effective_level") != "CRITICAL":
            continue
        observed = dt(reading, "observed_at")
        if observed is not None and observed >= threshold:
            return True
    return False


def recompute_event(event):
    critical = open_critical_incident_count(event["id"])
    if critical > 0:
        posture = "FROZEN"
    elif event.get("ingress_status") == "HOLD":
        posture = "FROZEN"
    else:
        plan = current_plan(event["id"])
        pre_plan = event.get("status") in PRE_PLAN_STATUSES
        if not pre_plan and (
            plan is None or plan.get("readiness_posture") in ("AT_RISK", "BLOCKED")
        ):
            posture = "RESTRICTED"
        elif _recent_critical_reading(event["id"]):
            posture = "RESTRICTED"
        else:
            posture = "OPEN"
    return apply_fields(
        event, {"open_critical_incident_count": critical, "gate_posture": posture}
    )


# --------------------------------------------------------------------------
# ScreeningLane figures (PRD 3.7)
# --------------------------------------------------------------------------


def lane_operator_count(lane_id):
    post_ids = set(p["id"] for p in db.posts.values() if p.get("lane_id") == lane_id)
    count = 0
    for assignment in db.assignments.values():
        if (
            assignment.get("post_id") in post_ids
            and assignment.get("assignment_status") in COMMITTED
            and assignment.get("duty_status") == "ON_POST"
        ):
            count += 1
    return count


def recompute_lane(lane):
    operators = lane_operator_count(lane["id"])
    throughput = calc.lane_throughput(
        lane.get("nominal_throughput_pph"),
        operators,
        lane.get("operator_capacity"),
        lane.get("status"),
    )
    return apply_fields(
        lane,
        {"assigned_operator_count": operators, "effective_throughput_pph": throughput},
    )


def refresh_lane_for_post(post):
    """A duty event on a post carrying a lane_id refreshes that lane."""
    lane_id = post.get("lane_id")
    if not lane_id:
        return
    lane = db.lanes.get(lane_id)
    if lane is None:
        return
    if recompute_lane(lane):
        touch(lane)


# --------------------------------------------------------------------------
# The upward cascade
# --------------------------------------------------------------------------


def cascade_up(posts):
    """Posts first (ascending created_at), then their plans, then their events."""
    plans = {}
    for post in sorted_records(list(posts)):
        if recompute_post(post):
            touch(post)
        plan = plan_of_post(post)
        if plan is not None:
            plans[plan["id"]] = plan
    events = {}
    for plan in sorted_records(list(plans.values())):
        if recompute_plan(plan):
            touch(plan)
        event = event_of_plan(plan)
        if event is not None:
            events[event["id"]] = event
    for event in sorted_records(list(events.values())):
        if recompute_event(event):
            touch(event)


def cascade_from_assignment(assignment):
    post = db.posts.get(assignment.get("post_id"))
    if post is None:
        return
    cascade_up([post])


def cascade_event_only(event):
    if event is None:
        return
    if recompute_event(event):
        touch(event)


def cascade_plan_and_event(plan):
    if plan is None:
        return
    if recompute_plan(plan):
        touch(plan)
    cascade_event_only(event_of_plan(plan))


# --------------------------------------------------------------------------
# Assignment cost helpers (PRD 3.6)
# --------------------------------------------------------------------------


def guard_markup(guard):
    if guard.get("employment_type") != "SUBCONTRACTED":
        return None
    vendor = db.subcontractors.get(guard.get("subcontractor_id"))
    if vendor is None:
        return D(0)
    return D(vendor.get("markup_pct") or 0)


def price_assignment(assignment, guard):
    """Populate scheduled_hours, night flag, pay_basis and line_cost_cents."""
    start = dt(assignment, "window_start")
    end = dt(assignment, "window_end")
    hours = calc.hours_between(start, end)
    night = calc.night_differential_applies(start)
    line_cost, pay_basis, _ = calc.cost_for_hours(
        hours,
        guard.get("base_hourly_rate_cents"),
        night,
        guard.get("employment_type"),
        guard_markup(guard),
    )
    assignment["scheduled_hours"] = num(hours)
    assignment["night_differential_applies"] = night
    assignment["pay_basis"] = pay_basis
    assignment["line_cost_cents"] = line_cost


def price_billed(assignment, guard):
    """Recompute cost on delivered time at RELIEVE (PRD 3.7)."""
    check_in = dt(assignment, "check_in_at")
    relieved = dt(assignment, "relieved_at")
    hours = calc.hours_between(check_in, relieved)
    night = calc.night_differential_applies(dt(assignment, "window_start"))
    billed_cost, _, _ = calc.cost_for_hours(
        hours,
        guard.get("base_hourly_rate_cents"),
        night,
        guard.get("employment_type"),
        guard_markup(guard),
    )
    assignment["billed_hours"] = num(hours)
    assignment["billed_cost_cents"] = billed_cost


# --------------------------------------------------------------------------
# Downward cascades
# --------------------------------------------------------------------------


def supersede_plan(plan):
    """PRD 3.4: cancel live rows, close posts, recompute, one version bump."""
    plan["status"] = "SUPERSEDED"
    plan["is_current"] = False
    posts = plan_posts(plan["id"])
    rows = []
    for post in posts:
        rows.extend(post_assignments(post["id"]))
    rows.sort(key=assignment_sort_key)
    for assignment in rows:
        if assignment.get("assignment_status") in ROSTER_LIVE:
            assignment["assignment_status"] = "CANCELLED"
            assignment["cancellation_reason"] = "PLAN_SUPERSEDED"
            touch(assignment)
    for post in posts:
        if recompute_post(post, plan):
            touch(post)
    recompute_plan(plan)
    touch(plan)
    cascade_event_only(event_of_plan(plan))


def void_assignments_for_guard(guard):
    """PRD 3.6: void the guard's live rows and run the four-hop re-derivation."""
    rows = [a for a in guard_assignments(guard["id"]) if a.get("assignment_status") in ROSTER_LIVE]
    rows.sort(key=assignment_sort_key)
    affected = []
    for assignment in rows:
        assignment["assignment_status"] = "VOIDED"
        assignment["cancellation_reason"] = "CREDENTIAL_NOT_CURRENT"
        touch(assignment)
        post = db.posts.get(assignment.get("post_id"))
        if post is not None:
            affected.append(post)
    if affected:
        cascade_up(affected)
    return len(rows)


def recompute_vendor_guard_count(vendor):
    count = 0
    for guard in db.guards.values():
        if (
            guard.get("subcontractor_id") == vendor["id"]
            and guard.get("verification_status") == "VERIFIED"
        ):
            count += 1
    return apply_fields(vendor, {"verified_guard_count": count})


def vendor_suspension_cascade(vendor):
    """PRD 3.5: verified guards back to review, then void, then re-derive upward."""
    guards = sorted_records(
        [g for g in db.guards.values() if g.get("subcontractor_id") == vendor["id"]]
    )
    for guard in guards:
        if guard.get("verification_status") == "VERIFIED":
            guard["verification_status"] = "PENDING_REVIEW"
            touch(guard)
            void_assignments_for_guard(guard)


def hold_open_lanes(event):
    for lane in event_lanes(event["id"]):
        if lane.get("status") == "OPEN":
            lane["status"] = "HOLD"
            recompute_lane(lane)
            touch(lane)


def release_held_lanes(event):
    for lane in event_lanes(event["id"]):
        if lane.get("status") == "HOLD":
            operators = lane_operator_count(lane["id"])
            if operators >= 1:
                lane["status"] = "OPEN"
                recompute_lane(lane)
                touch(lane)
            else:
                if recompute_lane(lane):
                    touch(lane)


def close_event_cascade(event):
    """PRD 3.9: the largest single cascade in the system."""
    event["status"] = "CLOSED"
    plan = current_plan(event["id"])
    if plan is not None:
        posts = plan_posts(plan["id"])
        rows = []
        for post in posts:
            rows.extend(post_assignments(post["id"]))
        rows.sort(key=assignment_sort_key)
        for assignment in rows:
            if assignment.get("duty_status") == "ON_POST":
                assignment["duty_status"] = "RELIEVED"
                assignment["relieved_at"] = clock_iso()
                guard = db.guards.get(assignment.get("guard_id"))
                if guard is not None:
                    price_billed(assignment, guard)
                if assignment.get("assignment_status") == "CONFIRMED":
                    assignment["assignment_status"] = "COMPLETED"
                touch(assignment)
                post = db.posts.get(assignment.get("post_id"))
                if post is not None:
                    refresh_lane_for_post(post)
    for lane in event_lanes(event["id"]):
        if lane.get("status") in ("PLANNED", "OPEN", "HOLD"):
            lane["status"] = "CLOSED"
            recompute_lane(lane)
            touch(lane)
    if plan is not None:
        if plan.get("status") == "ACTIVATED":
            plan["status"] = "LOCKED"
            touch(plan)
        if plan.get("status") == "LOCKED":
            plan["status"] = "CLOSED"
            touch(plan)
        for post in plan_posts(plan["id"]):
            if recompute_post(post, plan):
                touch(post)
        if recompute_plan(plan):
            touch(plan)
    recompute_event(event)
    touch(event)


# --------------------------------------------------------------------------
# After-action metrics (PRD 3.9)
# --------------------------------------------------------------------------


def after_action_metrics(review, event):
    incidents = [
        i for i in event_incidents(event["id"]) if i.get("status") != "CLOSED_UNFOUNDED"
    ]
    total_incident_count = len(incidents)
    sla_breach_count = sum(1 for i in incidents if i.get("sla_breached"))

    peak = "GREEN"
    for reading in event_readings(event["id"]):
        level = reading.get("effective_level") or "GREEN"
        if calc.DENSITY_RANK[level] > calc.DENSITY_RANK[peak]:
            peak = level

    plan = current_plan(event["id"])
    no_show_rate = D("0.0000")
    shortfall_total = D(0)
    if plan is not None:
        roster = plan_roster_rows(plan["id"])
        if roster:
            no_shows = sum(1 for a in roster if a.get("duty_status") == "NO_SHOW")
            no_show_rate = round_half_up(D(no_shows) / D(len(roster)), 4)
        on_post_by_post = {}
        for assignment in roster:
            if assignment.get("duty_status") in ("ON_POST", "RELIEVED"):
                key = assignment.get("post_id")
                on_post_by_post[key] = on_post_by_post.get(key, 0) + 1
        for post in plan_posts(plan["id"]):
            shortfall = (post.get("required_guard_count") or 0) - on_post_by_post.get(post["id"], 0)
            if shortfall < 0:
                shortfall = 0
            window_minutes = calc.minutes_between(dt(post, "window_start"), dt(post, "window_end"))
            shortfall_total += D(shortfall) * window_minutes

    return apply_fields(
        review,
        {
            "total_incident_count": total_incident_count,
            "sla_breach_count": sla_breach_count,
            "peak_density_level": peak,
            "no_show_rate": num(round_half_up(no_show_rate, 4)),
            "coverage_shortfall_minutes": num(round_half_up(shortfall_total, 2)),
        },
    )


# --------------------------------------------------------------------------
# Credential expiry sweep (PRD 3.5)
# --------------------------------------------------------------------------


def credential_expiry_sweep():
    expired_guard_count = 0
    voided_assignment_count = 0
    clock = now()
    for guard in sorted_records(list(db.guards.values())):
        if guard.get("verification_status") != "VERIFIED":
            continue
        expires = dt(guard, "credential_expires_on")
        if expires is None or expires > clock:
            continue
        guard["verification_status"] = "EXPIRED"
        guard["verified_at"] = None
        touch(guard)
        expired_guard_count += 1
        voided_assignment_count += void_assignments_for_guard(guard)
        if guard.get("subcontractor_id"):
            vendor = db.subcontractors.get(guard["subcontractor_id"])
            if vendor is not None and recompute_vendor_guard_count(vendor):
                touch(vendor)
    return expired_guard_count, voided_assignment_count
