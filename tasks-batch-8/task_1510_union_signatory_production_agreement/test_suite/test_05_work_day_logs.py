"""Work day logs: day-point occupancy, penalty arithmetic, and time sanity (PRD §3.5)."""
import test_helpers as th
from test_helpers import ApiErrorId as E


def _production_with_active_cam(name, fein, cam_rate=100_000, scope="THEATRICAL"):
    return th.create_in_production(
        legal_name=name, fein=fein, scope=scope,
        crew=(("W-CAM-1", "CAMERA", "CAMERA_OPERATOR", cam_rate),) + th.STANDARD_CREW[1:],
        activate=("W-CAM-1",),
    )


def test_duplicate_work_date_rejected(api):
    """PRD §3.5: "Occupancy is day-point based: at most one non-`VOIDED` log
    may exist per assignment per `work_date` — a second is
    `ERR_DUPLICATE_WORK_LOG` (HTTP 409) — while adjacent calendar dates are
    unaffected."

    Design: Difficulty/resource_temporal_overlap/work_log_same_date_point_occupancy
    """
    bundle = _production_with_active_cam("Rowan Field LLC", "15-0000004")
    company = bundle["company"]
    cam = bundle["assignments"]["W-CAM-1"]
    th.record_log(cam, company, "2026-08-10", 480, 960)

    resp = api.create_work_day_log(
        th.create_work_day_log_payload(
            crew_assignment_id=cam["id"], work_date="2026-08-10",
            call_time_minutes=500, wrap_time_minutes=900, meal_breaks=[],
        ),
        th.owner_headers(company),
    )
    th.validate_error(resp, E.ERR_DUPLICATE_WORK_LOG)


def test_adjacent_work_date_allowed(api):
    """PRD §3.5: "at most one non-`VOIDED` log may exist per assignment per
    `work_date` — a second is `ERR_DUPLICATE_WORK_LOG` (HTTP 409) — while
    adjacent calendar dates are unaffected."
    PRD §3.5: "The elapsed rest is the minutes from the previous day's wrap to
    midnight — 1440 minus the previous wrap — plus this day's call time" and
    "Rest exactly equal to the allowance is not a violation." Here rest is
    (1440 - 960) + 480 = 960 minutes against the 720-minute ULB allowance, so
    no turnaround violation.

    Design: Difficulty/resource_temporal_overlap/work_log_same_date_point_occupancy
    """
    bundle = _production_with_active_cam("Rowan Field LLC", "15-0000004")
    company = bundle["company"]
    cam = bundle["assignments"]["W-CAM-1"]
    th.record_log(cam, company, "2026-08-10", 480, 960)

    log2 = th.record_log(cam, company, "2026-08-11", 480, 960)
    th.assert_work_day_log(log2)
    assert log2["status"] == "OPEN", "adjacent day is not occupied"
    assert log2["turnaround_violation"] is False


def test_meal_penalty_units_from_delay(api):
    """PRD §3.5: "The first meal starts at the earliest `start_minutes` among
    the listed breaks" and "A delay of zero or less produces no penalty;
    otherwise `meal_penalty_units` is the delay divided by 30 minutes, rounded
    up to the next whole unit." With call 480 and first meal at 915 the delay
    is 915 - (480 + 360) = 75 minutes, i.e. ceil(75/30) = 3 units. No prior-day
    log exists for the assignment, so there is no turnaround violation.

    Design: Difficulty/combinatorial_formula/work_log_penalty_per_unit_rounding_pinned
    """
    bundle = _production_with_active_cam("Echo Stage LLC", "33-2222222",
                                         cam_rate=100_010, scope="NEW_MEDIA")
    company = bundle["company"]
    cam = bundle["assignments"]["W-CAM-1"]

    log = th.record_log(cam, company, "2026-08-10", 480, 1000,
                        meals=[{"start_minutes": 915, "end_minutes": 945}])
    th.assert_work_day_log(log)
    assert log["meal_penalty_units"] == 3
    assert log["turnaround_violation"] is False


def test_meal_penalty_per_unit_rounding_pinned(api):
    """PRD §3.5: "The per-unit penalty is one thirty-second of the assignment's
    `daily_rate_cents` — a quarter-hour of an eight-hour day rate — and the
    rounding order is pinned: the per-unit amount is rounded half up to a whole
    cent first, then multiplied by the units to produce `meal_penalty_cents`.
    The sum-then-round alternative is rejected."
    Rate 100,010 with 3 units: round_half_up(100010/32) = 3,125 per unit, so
    3 x 3,125 = 9,375 (sum-then-round would give 9,376).

    Design: Difficulty/combinatorial_formula/work_log_penalty_per_unit_rounding_pinned
    """
    bundle = _production_with_active_cam("Echo Stage LLC", "33-2222222",
                                         cam_rate=100_010, scope="NEW_MEDIA")
    company = bundle["company"]
    cam = bundle["assignments"]["W-CAM-1"]

    log = th.record_log(cam, company, "2026-08-10", 480, 1000,
                        meals=[{"start_minutes": 915, "end_minutes": 945}])
    assert log["meal_penalty_cents"] == 9375, (
        "per-unit rounding first: 3 * round_half_up(100010/32) = 3 * 3125"
    )
    assert log["penalty_cents"] == 9375


def test_meal_window_boundary_inclusive(api):
    """PRD §3.5: "The delay is that first-meal start minus the call time plus
    360 minutes (the six-hour meal window). A delay of zero or less produces no
    penalty; otherwise `meal_penalty_units` is the delay divided by 30 minutes,
    rounded up to the next whole unit." A first meal at exactly call + 360
    (840) has delay 0 and draws no penalty; one minute later (841) draws 1
    unit at round_half_up(100000/32) = 3,125 cents.

    Design: Corner/calculations/meal_window_boundary_exactly_360_no_penalty
    """
    bundle = _production_with_active_cam("Yarrow LLC", "20-0000024")
    company = bundle["company"]
    cam = bundle["assignments"]["W-CAM-1"]

    log_at = th.record_log(cam, company, "2026-08-10", 480, 960,
                           meals=[{"start_minutes": 840, "end_minutes": 870}])
    assert log_at["meal_penalty_units"] == 0
    assert log_at["meal_penalty_cents"] == 0
    assert log_at["penalty_cents"] == 0

    log_over = th.record_log(cam, company, "2026-08-11", 480, 960,
                             meals=[{"start_minutes": 841, "end_minutes": 871}])
    assert log_over["meal_penalty_units"] == 1
    assert log_over["meal_penalty_cents"] == 3125


def test_turnaround_boundary_strict(api):
    """PRD §3.5: "`turnaround_violation` is true when that rest is strictly
    shorter than the production's current tier allowance: 12 hours (720
    minutes) for `ULTRA_LOW_BUDGET`" and "Rest exactly equal to the allowance
    is not a violation. When violated, `turnaround_penalty_cents` is one eighth
    of the assignment's `daily_rate_cents`, rounded half up to a whole cent".
    Previous wrap 1200: call 480 gives rest 720 (not a violation); call 419
    gives rest 659 (violation, penalty round_half_up(100000/8) = 12,500).

    Design: Corner/calculations/turnaround_boundary_exactly_threshold_not_violated
    """
    bundle = _production_with_active_cam("Zelkova LLC", "20-0000025")
    company = bundle["company"]
    cam = bundle["assignments"]["W-CAM-1"]

    th.record_log(cam, company, "2026-08-10", 480, 1200)

    log_exact = th.record_log(cam, company, "2026-08-11", 480, 1200)
    assert log_exact["turnaround_violation"] is False, "rest 720 == allowance"
    assert log_exact["turnaround_penalty_cents"] == 0

    log_short = th.record_log(cam, company, "2026-08-12", 419, 900)
    assert log_short["turnaround_violation"] is True, "rest 659 < 720"
    assert log_short["turnaround_penalty_cents"] == 12500


def test_invalid_worklog_times(api):
    """PRD §3.5: "Time sanity is enforced: both times must be at least 0 and
    strictly below 1440; wrap must be strictly after call; and every meal break
    must lie within the call-to-wrap span with its start before its end.
    Violations are rejected with `ERR_INVALID_WORKLOG_TIMES` (HTTP 422)."

    Design: Corner/validations/invalid_worklog_times_rejected
    """
    bundle = _production_with_active_cam("Oxlip Media LLC", "20-0000042")
    company = bundle["company"]
    cam = bundle["assignments"]["W-CAM-1"]

    resp_wrap = api.create_work_day_log(
        th.create_work_day_log_payload(
            crew_assignment_id=cam["id"], work_date="2026-08-10",
            call_time_minutes=480, wrap_time_minutes=400, meal_breaks=[],
        ),
        th.owner_headers(company),
    )
    th.validate_error(resp_wrap, E.ERR_INVALID_WORKLOG_TIMES)

    resp_meal = api.create_work_day_log(
        th.create_work_day_log_payload(
            crew_assignment_id=cam["id"], work_date="2026-08-10",
            call_time_minutes=480, wrap_time_minutes=960,
            meal_breaks=[{"start_minutes": 300, "end_minutes": 330}],
        ),
        th.owner_headers(company),
    )
    th.validate_error(resp_meal, E.ERR_INVALID_WORKLOG_TIMES)


def test_submit_voided_log_rejected(api):
    """PRD §3.5: "Submitting a log moves it from `OPEN` to `SUBMITTED` (any
    other from-state is `ERR_WORKLOG_STATE`, HTTP 409)" and "`VOIDED` is
    terminal."

    Design: Corner/state_machines/work_log_submit_after_void_rejected
    """
    bundle = _production_with_active_cam("Larkspur LLC", "20-0000012")
    company = bundle["company"]
    cam = bundle["assignments"]["W-CAM-1"]
    log = th.record_log(cam, company, "2026-08-10")
    th.void_log(log, company)

    resp = api.submit_work_day_log(log["id"], th.owner_headers(company))
    th.validate_error(resp, E.ERR_WORKLOG_STATE)

    logs, _ = th.validate_paginated(
        api.list_assignment_work_day_logs(cam["id"], th.owner_headers(company))
    )
    current = next(l for l in logs if l["id"] == log["id"])
    assert current["status"] == "VOIDED", "rejected submit must not change state"


def test_log_on_hired_assignment_rejected(api):
    """PRD §3.5: "The referenced assignment must be `ACTIVE` — logging against
    a `HIRED`, `WRAPPED`, or `TERMINATED` assignment is
    `ERR_ASSIGNMENT_STATE`."

    Design: Difficulty/cross_entity_state_dependency/work_log_create_requires_active_assignment
    """
    bundle = th.create_in_production("Quail Run LLC", "14-0000003",
                                     title="Quail Line", scope="TELEVISION")
    company = bundle["company"]
    cam = bundle["assignments"]["W-CAM-1"]  # still HIRED
    assert cam["status"] == "HIRED"

    resp = api.create_work_day_log(
        th.create_work_day_log_payload(crew_assignment_id=cam["id"],
                                       work_date="2026-08-10"),
        th.owner_headers(company),
    )
    th.validate_error(resp, E.ERR_ASSIGNMENT_STATE)


def test_log_after_activation_succeeds(api):
    """PRD §3.4: "Activation — `HIRED` to `ACTIVE` — requires the production to
    be `IN_PRODUCTION`" and PRD §3.5: "The referenced assignment must be
    `ACTIVE`" with "A new log starts `OPEN`". After the HIRED -> ACTIVE
    transition, the identical log creation succeeds.

    Design: Difficulty/cross_entity_state_dependency/work_log_create_requires_active_assignment
    """
    bundle = th.create_in_production("Quail Run LLC", "14-0000003",
                                     title="Quail Line", scope="TELEVISION")
    company = bundle["company"]
    cam = bundle["assignments"]["W-CAM-1"]

    cam = th.transition_assignment(cam, company, "ACTIVE")
    assert cam["status"] == "ACTIVE"

    log = th.record_log(cam, company, "2026-08-10")
    th.assert_work_day_log(log)
    assert log["status"] == "OPEN"
