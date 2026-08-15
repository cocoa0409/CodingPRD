"""Check-in cadence, buffer rule, training lifecycle, and health/TTP effects."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    setup_basic_case,
    setup_in_progress,
    setup_day_one_ready,
    get_case_checkins,
    get_case_trainings,
    get_summary,
    make_new_hire_headers,
    make_hiring_manager_headers,
    make_buddy_headers,
)

HR = TEST_USERS["hr_admin_headers"]


def test_checkin_cadence_weekend_shift_forward(api):
    """PRD §3.7: "For each offset in the pinned profile's
    `manager_checkin_offsets_days`, processed in ascending order, a `MANAGER`
    check-in is scheduled at 09:00:00 UTC on the day that offset-many days after
    the `start_date`, shifted forward past any weekend to the following Monday"

    start_date 2026-05-08 (Friday): manager +1 lands Sat 2026-05-09 -> Monday
    2026-05-11; +30 lands Sun 2026-06-07 -> Monday 2026-06-08; buddy day 1 ->
    2026-05-11; day 8 (Sat 2026-05-16) -> Monday 2026-05-18.

    Design: Corner/calculations/checkin_cadence_weekend_shift_forward
    """
    ctx = setup_basic_case(start_date="2026-05-08")
    checkins = get_case_checkins(ctx["case"]["id"])
    assert [c["scheduled_at"] for c in checkins] == [
        "2026-05-11T09:00:00Z",  # MANAGER +1 (Sat -> Mon)
        "2026-06-08T09:00:00Z",  # MANAGER +30 (Sun -> Mon)
        "2026-05-11T09:00:00Z",  # BUDDY day 1
        "2026-05-18T09:00:00Z",  # BUDDY day 8 (Sat -> Mon)
    ]


def test_checkin_buffer_thirty_minutes_semantics(api):
    """PRD §3.7: "it must respect a thirty-minute buffer per owner: for the same
    `owner_employee_id`, every other check-in in `SCHEDULED` or `COMPLETED`
    status must sit at least thirty minutes away from the proposed time —
    exactly thirty minutes apart is permitted — or the reschedule is rejected
    with `ERR_CHECKIN_TOO_CLOSE`."

    Design: Difficulty/resource_temporal_overlap/checkin_buffer_thirty_minutes_semantics
    """
    ctx = setup_basic_case()
    checkins = get_case_checkins(ctx["case"]["id"])
    c_m1 = next(c for c in checkins if c["kind"] == "MANAGER" and c["scheduled_at"] == "2026-05-05T09:00:00Z")
    c_m2 = next(c for c in checkins if c["kind"] == "MANAGER" and c["scheduled_at"] == "2026-06-03T09:00:00Z")

    # 15 minutes away from c_m1 -> ERR_CHECKIN_TOO_CLOSE.
    resp = api.reschedule_check_in(c_m2["id"], {"scheduled_at": "2026-05-05T09:15:00Z"}, HR)
    validate_error(resp, ApiErrorId.ERR_CHECKIN_TOO_CLOSE)

    # Exactly 30 minutes away -> allowed.
    resp2 = api.reschedule_check_in(c_m2["id"], {"scheduled_at": "2026-05-05T09:30:00Z"}, HR)
    data = validate_success(resp2)
    assert data["scheduled_at"] == "2026-05-05T09:30:00Z"
    assert data["status"] == "SCHEDULED"


def test_checkin_buffer_exactly_30_minutes_allowed(api):
    """PRD §3.7: "exactly thirty minutes apart is permitted"

    Boundary-precision: a 30-minute gap is legal (inclusive minimum).

    Design: Difficulty/resource_temporal_overlap/checkin_buffer_thirty_minutes_semantics
    """
    ctx = setup_basic_case()
    checkins = get_case_checkins(ctx["case"]["id"])
    c_m1 = next(c for c in checkins if c["kind"] == "MANAGER" and c["scheduled_at"] == "2026-05-05T09:00:00Z")
    c_m2 = next(c for c in checkins if c["kind"] == "MANAGER" and c["scheduled_at"] == "2026-06-03T09:00:00Z")

    resp = api.reschedule_check_in(c_m2["id"], {"scheduled_at": "2026-05-05T09:30:00Z"}, HR)
    data = validate_success(resp)
    assert data["status"] == "SCHEDULED"
    assert data["scheduled_at"] == "2026-05-05T09:30:00Z"


def test_complete_missed_checkin_requires_reschedule_first(api):
    """PRD §3.7: "Only a `SCHEDULED` check-in can be completed
    (`ERR_INVALID_CHECKIN_STATE`); a `MISSED` one must be rescheduled first."
    PRD §3.7: "Rescuing a `MISSED` check-in back to `SCHEDULED` recomputes the
    case health, since the missed count drops"

    Design: Corner/state_machines/complete_missed_checkin_requires_reschedule_first
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    checkins = get_case_checkins(case_id)
    c_m1 = next(c for c in checkins if c["kind"] == "MANAGER" and c["scheduled_at"] == "2026-05-05T09:00:00Z")
    # Advance past the 24h MISSED grace for c_m1.
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-07T00:00:00Z"}, HR))

    mgr = make_hiring_manager_headers(ctx["manager"]["id"])
    resp = api.complete_check_in(c_m1["id"], {"productivity_rating": 4}, mgr)
    validate_error(resp, ApiErrorId.ERR_INVALID_CHECKIN_STATE)

    r = api.reschedule_check_in(c_m1["id"], {"scheduled_at": "2026-05-08T09:00:00Z"}, HR)
    assert validate_success(r)["status"] == "SCHEDULED"

    r2 = api.complete_check_in(c_m1["id"], {"productivity_rating": 4}, mgr)
    assert validate_success(r2)["status"] == "COMPLETED"


def test_reschedule_to_past_rejected(api):
    """PRD §3.7: "The new time must lie in the future of the logical clock
    (`ERR_CHECKIN_TIME_IN_PAST`)"

    Design: Corner/state_machines/reschedule_to_past_rejected
    """
    ctx = setup_basic_case()
    checkins = get_case_checkins(ctx["case"]["id"])
    c_m1 = checkins[0]
    resp = api.reschedule_check_in(c_m1["id"], {"scheduled_at": "2026-04-30T09:00:00Z"}, HR)
    validate_error(resp, ApiErrorId.ERR_CHECKIN_TIME_IN_PAST)


def test_checkin_missed_auto_flip_after_grace(api):
    """PRD §3.7: "When the logical time runs more than 24 hours past a
    check-in's `scheduled_at`, the check-in flips automatically to `MISSED`,
    recomputing the case health with the 10-point-per-item penalty."

    Design: Corner/state_machines/checkin_missed_auto_flip_after_grace
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-07T00:00:00Z"}, HR))
    checkins = get_case_checkins(case_id)
    # sort_index order: MANAGER 2026-05-05, MANAGER 2026-06-03, BUDDY 2026-05-05, BUDDY 2026-05-12.
    assert checkins[0]["status"] == "MISSED"      # 2026-05-05 mgr
    assert checkins[1]["status"] == "SCHEDULED"   # 2026-06-03 mgr (far future)
    assert checkins[2]["status"] == "MISSED"      # 2026-05-05 buddy
    assert checkins[3]["status"] == "SCHEDULED"   # 2026-05-12 buddy
    summary = get_summary(case_id)
    assert summary["health_score"] == 80  # 100 - 10*2 MISSED


def test_training_overdue_auto_flip(api):
    """PRD §3.7: "a `status` that begins at `ASSIGNED` and flips automatically
    to `OVERDUE` once the logical time passes `due_at` (recomputing the case
    health with the 15-point-per-item penalty)."

    Design: Corner/state_machines/training_overdue_auto_flip
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-12T00:00:00Z"}, HR))
    trainings = get_case_trainings(case_id)
    assert trainings[0]["status"] == "OVERDUE"   # SEC101 due 2026-05-11T23:59:59Z
    assert trainings[1]["status"] == "ASSIGNED"  # HR201 due 2026-05-18T23:59:59Z


def test_training_double_complete_rejected(api):
    """PRD §3.7: "The owning new hire completes a training — from `ASSIGNED` or
    `OVERDUE` alike (`ERR_INVALID_TRAINING_STATE` otherwise)"

    Design: Corner/state_machines/training_double_complete_rejected
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    nh = make_new_hire_headers(ctx["new_hire"]["id"])
    tr1 = get_case_trainings(case_id)[0]

    r1 = api.complete_training(tr1["id"], {"score": 90}, nh)
    assert validate_success(r1)["status"] == "COMPLETED"
    r2 = api.complete_training(tr1["id"], {"score": 95}, nh)
    validate_error(r2, ApiErrorId.ERR_INVALID_TRAINING_STATE)


def test_estimated_ttp_applies_slip_penalties(api):
    """PRD §3.7: "it starts from the larger of two profile-derived bases — the
    greatest `due_offset_days` among the pinned profile's training modules and
    the greatest offset among its `manager_checkin_offsets_days` — then adds 3
    days for each training assignment currently `OVERDUE` and 5 days for each
    check-in currently `MISSED`"

    Design: Corner/calculations/estimated_ttp_applies_slip_penalties
    """
    ctx = setup_in_progress()
    case_id = ctx["case"]["id"]
    nh = make_new_hire_headers(ctx["new_hire"]["id"])
    mgr = make_hiring_manager_headers(ctx["manager"]["id"])
    bud = make_buddy_headers(ctx["buddy"]["id"])
    checkins = get_case_checkins(case_id)
    c_m1 = next(c for c in checkins if c["kind"] == "MANAGER" and c["scheduled_at"] == "2026-05-05T09:00:00Z")
    c_m2 = next(c for c in checkins if c["kind"] == "MANAGER" and c["scheduled_at"] == "2026-06-03T09:00:00Z")
    c_b1 = next(c for c in checkins if c["kind"] == "BUDDY" and c["scheduled_at"] == "2026-05-05T09:00:00Z")
    c_b2 = next(c for c in checkins if c["kind"] == "BUDDY" and c["scheduled_at"] == "2026-05-12T09:00:00Z")
    # Complete 3 of 4 check-ins early; leave c_m2 to go MISSED.
    get_success_data(api.complete_check_in(c_m1["id"], {"productivity_rating": 4}, mgr))
    get_success_data(api.complete_check_in(c_b1["id"], {}, bud))
    get_success_data(api.complete_check_in(c_b2["id"], {}, bud))
    # Advance to 2026-06-04T10:00:00Z: both trainings OVERDUE, c_m2 MISSED.
    get_success_data(api.set_current_utc({"to_iso8601": "2026-06-04T10:00:00Z"}, HR))
    summary = get_summary(case_id)
    assert summary["estimated_ttp_days"] == 41  # 30 + 3*2 + 5*1
