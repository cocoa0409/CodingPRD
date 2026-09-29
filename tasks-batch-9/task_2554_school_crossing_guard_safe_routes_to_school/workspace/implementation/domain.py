"""Cross-aggregate domain logic: resolvers, coverage propagation, guard
reliability, suspension cascades and the clock checkpoint sweep."""
from datetime import timedelta

import calc
from calc import f2
from db import db, now, touch
from errors import fail
from timeutil import UTC, add_days, fmt_date, fmt_dt, parse_date, parse_dt

OPEN_ABSENCE_STATUSES = ("DISPATCH_PENDING", "OFFER_OUT", "UNCOVERED_GAP")
LIVE_ASSIGNMENT_STATUSES = ("SCHEDULED", "ACTIVE")
FINALIZED_STUDY_STATUSES = ("WARRANTED", "CONDITIONAL", "NOT_WARRANTED")
WARRANT_PERMITTING = ("WARRANTED", "CONDITIONAL")


# ---------------------------------------------------------------------------
# Resolvers (PRD 2.6)
# ---------------------------------------------------------------------------
def _lookup(table, key, error_id):
    if not isinstance(key, str):
        fail(error_id)
    record = table.get(key)
    if record is None:
        fail(error_id)
    return record


def get_school(key):
    return _lookup(db.schools, key, "ERR_SCHOOL_NOT_FOUND")


def get_intersection(key):
    return _lookup(db.intersections, key, "ERR_INTERSECTION_NOT_FOUND")


def get_study(key):
    return _lookup(db.studies, key, "ERR_WARRANT_STUDY_NOT_FOUND")


def get_guard(key):
    return _lookup(db.guards, key, "ERR_GUARD_NOT_FOUND")


def get_post(key):
    return _lookup(db.posts, key, "ERR_GUARD_POST_NOT_FOUND")


def get_assignment(key):
    return _lookup(db.assignments, key, "ERR_ASSIGNMENT_NOT_FOUND")


def get_absence(key):
    return _lookup(db.absences, key, "ERR_ABSENCE_NOT_FOUND")


def get_route(key):
    return _lookup(db.walking_routes, key, "ERR_ROUTE_NOT_FOUND")


def get_complaint(key):
    return _lookup(db.complaints, key, "ERR_COMPLAINT_NOT_FOUND")


def get_program(key):
    return _lookup(db.grant_programs, key, "ERR_GRANT_PROGRAM_NOT_FOUND")


def get_project(key):
    return _lookup(db.projects, key, "ERR_PROJECT_NOT_FOUND")


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------
def school_of_intersection(intersection):
    return db.schools.get(intersection["school_id"])


def intersection_of_post(post):
    return db.intersections.get(post["intersection_id"])


def school_of_post(post):
    intersection = intersection_of_post(post)
    if intersection is None:
        return None
    return school_of_intersection(intersection)


def post_of_assignment(assignment):
    return db.posts.get(assignment["guard_post_id"])


def school_of_assignment(assignment):
    post = post_of_assignment(assignment)
    if post is None:
        return None
    return school_of_post(post)


def assignment_of_absence(absence):
    return db.assignments.get(absence["post_assignment_id"])


def school_of_absence(absence):
    assignment = assignment_of_absence(absence)
    if assignment is None:
        return None
    return school_of_assignment(assignment)


def intersections_of_school(school):
    return [i for i in db.intersections.values() if i["school_id"] == school["id"]]


def posts_of_intersection(intersection):
    return [p for p in db.posts.values() if p["intersection_id"] == intersection["id"]]


def assignments_of_post(post):
    return [a for a in db.assignments.values() if a["guard_post_id"] == post["id"]]


def assignments_of_guard(guard):
    return [a for a in db.assignments.values() if a["guard_id"] == guard["id"]]


def live_assignments_of_guard(guard):
    return [a for a in assignments_of_guard(guard)
            if a["status"] in LIVE_ASSIGNMENT_STATUSES]


def absences_of_assignment(assignment):
    return [a for a in db.absences.values()
            if a["post_assignment_id"] == assignment["id"]]


def absences_of_guard(guard_id):
    return [a for a in db.absences.values() if a["guard_id"] == guard_id]


def routes_of_school(school):
    return [r for r in db.walking_routes.values() if r["school_id"] == school["id"]]


def complaints_of_intersection(intersection_id):
    return [c for c in db.complaints.values()
            if c["intersection_id"] == intersection_id]


def projects_of_program(program_id):
    return [p for p in db.projects.values() if p["grant_program_id"] == program_id]


# ---------------------------------------------------------------------------
# Coverage propagation (PRD 2.7)
# ---------------------------------------------------------------------------
def recompute_assignment_coverage(assignment):
    count = sum(1 for a in absences_of_assignment(assignment)
                if a["status"] in OPEN_ABSENCE_STATUSES)
    state = "GAP" if count >= 1 else "STAFFED"
    if assignment["open_absence_count"] != count or assignment["coverage_state"] != state:
        assignment["open_absence_count"] = count
        assignment["coverage_state"] = state
        touch(assignment)


def recompute_post_coverage(post):
    gap_count = 0
    has_live = False
    for assignment in assignments_of_post(post):
        if assignment["status"] in LIVE_ASSIGNMENT_STATUSES:
            has_live = True
        for absence in absences_of_assignment(assignment):
            if absence["status"] in OPEN_ABSENCE_STATUSES:
                gap_count += 1
    if not has_live:
        status = "UNSTAFFED"
    elif gap_count >= 1:
        status = "UNCOVERED"
    else:
        status = "COVERED"
    if post["open_gap_count"] != gap_count or post["coverage_status"] != status:
        post["open_gap_count"] = gap_count
        post["coverage_status"] = status
        touch(post)


def hold_routes(school):
    for route in routes_of_school(school):
        if route["status"] == "PUBLISHED":
            route["status"] = "ADVISORY_HOLD"
            route["hold_reason"] = "SCHOOL_COVERAGE_SUSPENDED"
            touch(route)


def release_routes(school):
    for route in routes_of_school(school):
        if route["status"] == "ADVISORY_HOLD":
            route["status"] = "PUBLISHED"
            route["hold_reason"] = None
            touch(route)


def recompute_school_coverage(school):
    if school is None:
        return
    active = 0
    uncovered = 0
    for intersection in intersections_of_school(school):
        for post in posts_of_intersection(intersection):
            if post["status"] != "ACTIVE":
                continue
            active += 1
            if post["coverage_status"] in ("UNCOVERED", "UNSTAFFED"):
                uncovered += 1
    covered = active - uncovered
    rate = f2(calc.coverage_rate_pct(covered, active))
    posture = calc.coverage_posture(uncovered, rate)
    previous = school["coverage_posture"]
    changed = (school["active_post_count"] != active
               or school["covered_post_count"] != covered
               or school["uncovered_post_count"] != uncovered
               or school["coverage_rate_pct"] != rate
               or previous != posture)
    if changed:
        school["active_post_count"] = active
        school["covered_post_count"] = covered
        school["uncovered_post_count"] = uncovered
        school["coverage_rate_pct"] = rate
        school["coverage_posture"] = posture
        touch(school)
    if posture == "SUSPENDED" and previous != "SUSPENDED":
        hold_routes(school)
    elif previous == "SUSPENDED" and posture != "SUSPENDED":
        release_routes(school)


def propagate_from_post(post):
    recompute_post_coverage(post)
    recompute_school_coverage(school_of_post(post))


def propagate_from_assignment(assignment):
    recompute_assignment_coverage(assignment)
    post = post_of_assignment(assignment)
    if post is not None:
        propagate_from_post(post)


# ---------------------------------------------------------------------------
# Guard duty release
# ---------------------------------------------------------------------------
def release_guard(guard):
    """A guard left holding no SCHEDULED or ACTIVE assignment returns to
    UNASSIGNED (PRD 3.4).  ON_LEAVE is never disturbed."""
    if guard is None:
        return
    if guard["duty_status"] != "ASSIGNED":
        return
    if live_assignments_of_guard(guard):
        return
    guard["duty_status"] = "UNASSIGNED"
    touch(guard)


# ---------------------------------------------------------------------------
# Guard reliability (PRD 3.4)
# ---------------------------------------------------------------------------
def _rolling_counts(guard_id):
    anchor = now()
    low = anchor - timedelta(days=calc.ROLLING_WINDOW_DAYS)
    total = 0
    unexcused = 0
    for absence in absences_of_guard(guard_id):
        if absence["status"] == "RESCINDED":
            continue
        created = parse_dt(absence["created_at"])
        if created is None or created < low or created > anchor:
            continue
        total += 1
        if absence["reason"] == "UNEXCUSED":
            unexcused += 1
    return total, unexcused


def _season_counts(guard_id):
    total = 0
    unexcused = 0
    for absence in absences_of_guard(guard_id):
        if absence["status"] == "RESCINDED":
            continue
        school = school_of_absence(absence)
        if school is None:
            continue
        absence_date = parse_date(absence["absence_date"])
        start = parse_date(school["session_start_date"])
        end = parse_date(school["session_end_date"])
        if absence_date is None or start is None or end is None:
            continue
        if absence_date < start or absence_date > end:
            continue
        total += 1
        if absence["reason"] == "UNEXCUSED":
            unexcused += 1
    return total, unexcused


def refresh_reliability(guard, rolling=True, season=True):
    """Recompute the reliability variants in place.  Returns True when a stored
    value actually moved, so callers on write paths can bump the version while
    read paths stay non-mutating."""
    changed = False
    hours = guard["training_hours_completed"]
    if rolling:
        total, unexcused = _rolling_counts(guard["id"])
        value = f2(calc.reliability_score(hours, total, unexcused, "ROLLING_90D"))
        if guard["reliability_score_rolling_90d"] != value:
            guard["reliability_score_rolling_90d"] = value
            changed = True
    if season:
        total, unexcused = _season_counts(guard["id"])
        value = f2(calc.reliability_score(hours, total, unexcused, "SEASON_TO_DATE"))
        if guard["reliability_score_season_to_date"] != value:
            guard["reliability_score_season_to_date"] = value
            changed = True
    return changed


def refresh_reliability_and_touch(guard, rolling=True, season=True):
    if refresh_reliability(guard, rolling=rolling, season=season):
        touch(guard)


def vacate_assignments(assignments, reason):
    """Move a set of assignments to VACATED and run every downstream
    consequence: guard release, post coverage, school posture, route holds."""
    posts = {}
    guards = {}
    for assignment in assignments:
        if assignment["status"] not in LIVE_ASSIGNMENT_STATUSES:
            continue
        assignment["status"] = "VACATED"
        assignment["vacated_reason"] = reason
        touch(assignment)
        post = post_of_assignment(assignment)
        if post is not None:
            posts[post["id"]] = post
        guard = db.guards.get(assignment["guard_id"])
        if guard is not None:
            guards[guard["id"]] = guard
    for guard in guards.values():
        release_guard(guard)
    for post in posts.values():
        propagate_from_post(post)


def apply_reliability_breach(guard):
    """A newly filed absence that drops the rolling score strictly below the
    floor suspends a CERTIFIED guard and strips their roster (PRD 3.4)."""
    if guard["certification_status"] != "CERTIFIED":
        return
    if calc.dec(guard["reliability_score_rolling_90d"]) >= calc.RELIABILITY_FLOOR:
        return
    guard["certification_status"] = "SUSPENDED"
    guard["suspension_reason"] = "RELIABILITY_BREACH"
    touch(guard)
    vacate_assignments(live_assignments_of_guard(guard), "GUARD_SUSPENDED")


def suspend_posts(posts, reason="WARRANT_LAPSED"):
    """Suspend a set of ACTIVE posts and vacate everything they carried."""
    doomed = []
    for post in posts:
        if post["status"] != "ACTIVE":
            continue
        post["status"] = "SUSPENDED"
        post["suspension_reason"] = reason
        touch(post)
        doomed.extend(a for a in assignments_of_post(post)
                      if a["status"] in LIVE_ASSIGNMENT_STATUSES)
    vacate_assignments(doomed, "POST_SUSPENDED")
    for post in posts:
        propagate_from_post(post)


# ---------------------------------------------------------------------------
# Intersection crash aggregates (PRD 3.2)
# ---------------------------------------------------------------------------
def pedestrian_crashes_in_window(intersection, anchor_date):
    low = add_days(anchor_date, -calc.CRASH_LOOKBACK_DAYS)
    hits = []
    for entry in intersection["crash_history"]:
        if not entry.get("involved_pedestrian"):
            continue
        crash_date = parse_date(entry.get("crash_date"))
        if crash_date is None or crash_date < low or crash_date > anchor_date:
            continue
        hits.append(entry)
    return hits


def refresh_crash_aggregates(intersection):
    entries = pedestrian_crashes_in_window(intersection, now().date())
    count = len(entries)
    points = calc.severity_points(entries)
    if (intersection["pedestrian_crash_count_window"] != count
            or intersection["crash_severity_points"] != points):
        intersection["pedestrian_crash_count_window"] = count
        intersection["crash_severity_points"] = points
        return True
    return False


def refresh_crash_aggregates_and_touch(intersection):
    if refresh_crash_aggregates(intersection):
        touch(intersection)


def recompute_open_complaint_count(intersection):
    count = sum(1 for c in complaints_of_intersection(intersection["id"])
                if c["status"] in ("RECEIVED", "TRIAGED", "REFERRED"))
    if intersection["open_complaint_count"] != count:
        intersection["open_complaint_count"] = count
        return True
    return False


# ---------------------------------------------------------------------------
# Grant program balance (PRD 2.11)
# ---------------------------------------------------------------------------
def recompute_program_balance(program):
    projects = projects_of_program(program["id"])
    committed = sum(p["awarded_cents"] for p in projects if p["status"] == "FUNDED")
    funded = sum(1 for p in projects if p["status"] == "FUNDED")
    deferred = [p for p in projects if p["status"] == "DEFERRED"]
    program["committed_cents"] = committed
    program["remaining_cents"] = program["total_cents"] - committed
    program["funded_project_count"] = funded
    program["deferred_project_count"] = len(deferred)
    program["next_cycle_carryover_cents"] = sum(
        p["requested_cost_cents"] for p in deferred)
    touch(program)


# ---------------------------------------------------------------------------
# Shift conflict helpers (PRD 3.5)
# ---------------------------------------------------------------------------
def ranges_overlap(start_a, end_a, start_b, end_b):
    """Closed-interval overlap on both sides."""
    return start_a <= end_b and end_a >= start_b


def guard_busy_on(guard, target_date, required_shift, ignore_assignment_id=None):
    """True when the guard holds a live assignment covering target_date whose
    post shift conflicts with required_shift."""
    for assignment in assignments_of_guard(guard):
        if assignment["status"] not in LIVE_ASSIGNMENT_STATUSES:
            continue
        if ignore_assignment_id and assignment["id"] == ignore_assignment_id:
            continue
        start = parse_date(assignment["start_date"])
        end = parse_date(assignment["end_date"])
        if start is None or end is None:
            continue
        if target_date < start or target_date > end:
            continue
        post = post_of_assignment(assignment)
        other_shift = post["required_shift"] if post else assignment["shift"]
        if calc.shifts_conflict(required_shift, other_shift):
            return True
    return False


# ---------------------------------------------------------------------------
# The checkpoint sweep (PRD 2.4)
# ---------------------------------------------------------------------------
def _sweep_sort_key(assignment):
    return (assignment["start_date"], assignment["created_at"], assignment["_seq"])


def advance_clock(target):
    """Set the logical clock and run the checkpoint sweep.  Returns
    (activated_count, ended_count)."""
    db.clock = target
    target_date = target.date()
    activated = 0
    ended = 0
    ended_assignments = []
    for assignment in sorted(db.assignments.values(), key=_sweep_sort_key):
        start = parse_date(assignment["start_date"])
        end = parse_date(assignment["end_date"])
        if assignment["status"] == "SCHEDULED" and start is not None and start <= target_date:
            assignment["status"] = "ACTIVE"
            touch(assignment)
            activated += 1
        if assignment["status"] == "ACTIVE" and end is not None and end < target_date:
            assignment["status"] = "ENDED"
            touch(assignment)
            ended += 1
            ended_assignments.append(assignment)
    posts = {}
    guards = {}
    for assignment in ended_assignments:
        post = post_of_assignment(assignment)
        if post is not None:
            posts[post["id"]] = post
        guard = db.guards.get(assignment["guard_id"])
        if guard is not None:
            guards[guard["id"]] = guard
    for guard in guards.values():
        release_guard(guard)
    for post in posts.values():
        propagate_from_post(post)
    for guard in db.guards.values():
        refresh_reliability_and_touch(guard, rolling=True, season=False)
    for intersection in db.intersections.values():
        refresh_crash_aggregates_and_touch(intersection)
    return activated, ended
