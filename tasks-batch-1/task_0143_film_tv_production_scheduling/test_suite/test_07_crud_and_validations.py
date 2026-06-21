"""CRUD creation, field/range/enum validation, business-rule violations, and
list/computed-read endpoints."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, fixtures,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import LP, AD, PC


# --------------------------------------------------------------------------- #
# Corner/entities/create_production_returns_201_with_defaults
# --------------------------------------------------------------------------- #
def test_create_production_returns_201_with_defaults(api):
    """PRD 3.1: "A freshly created production lands with its status field set to
    DRAFT, and its three rolled-up money figures — committed_cost_cents,
    actual_cost_cents, and residual_reserve_cents — all initialized to zero."
    PRD 2.4: "The version field is an integer that begins at 1 when the resource
    is created".

    Design: Corner/entities/create_production_returns_201_with_defaults
    """
    data = validate_success(api.create_production(
        {"title": "Greenfield", "production_type": "FEATURE",
         "total_budget_cents": 5_000_000}, LP), expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["committed_cost_cents"] == 0
    assert data["version"] == 1


# --------------------------------------------------------------------------- #
# Corner/entities/get_production_not_found
# --------------------------------------------------------------------------- #
def test_get_production_not_found(api):
    """PRD 2.5: "any referenced resource that does not exist yields ERR_NOT_FOUND
    against the first missing reference encountered."

    Design: Corner/entities/get_production_not_found
    """
    resp = api.get_production("00000000-0000-4000-8000-000000000000", LP)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# --------------------------------------------------------------------------- #
# Corner/entities/create_budget_line_missing_required_field
# --------------------------------------------------------------------------- #
def test_create_budget_line_missing_category(api):
    """PRD 2.8: "a missing required field, a wrong type, or an enum value outside
    its declared set fails with ERR_INVALID_REQUEST".

    POST /budget-lines omitting category => ERR_INVALID_REQUEST.

    Design: Corner/entities/create_budget_line_missing_required_field
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    resp = api.create_budget_line(
        {"production_id": prod["id"], "estimated_cents": 100_000}, LP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# --------------------------------------------------------------------------- #
# Corner/entities/create_crew_invalid_enum_union_code
# --------------------------------------------------------------------------- #
def test_create_crew_invalid_union_code_enum(api):
    """PRD 2.8: "an enum value outside its declared set fails with
    ERR_INVALID_REQUEST". PRD 3.4: "union_code, one of SAG_AFTRA, IATSE, DGA, or
    NONE".

    Design: Corner/entities/create_crew_invalid_enum_union_code
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    resp = api.create_crew_member(
        {"production_id": prod["id"], "full_name": "X", "role_title": "Y",
         "daily_rate_cents": 100_000, "union_code": "TEAMSTERS"}, LP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# --------------------------------------------------------------------------- #
# Corner/entities/create_budget_line_negative_amount_validation_failed
# --------------------------------------------------------------------------- #
def test_create_budget_line_negative_amount_validation_failed(api):
    """PRD 2.8: "a numeric field that is present and correctly typed but outside
    its declared range fails with ERR_VALIDATION_FAILED". PRD 3.2: "Each line is
    created with an estimated_cents figure of zero or greater".

    estimated_cents=-1 => ERR_VALIDATION_FAILED (range check, distinct from the
    missing-field 400).

    Design: Corner/entities/create_budget_line_negative_amount_validation_failed
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    resp = api.create_budget_line(
        {"production_id": prod["id"], "category": "POST", "estimated_cents": -1}, LP)
    validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED.value)


# --------------------------------------------------------------------------- #
# Corner/entities/create_assignment_parent_crew_not_found
# --------------------------------------------------------------------------- #
def test_create_assignment_crew_not_found(api):
    """PRD 2.8: "Existence is third: any path or foreign-key resource that does
    not exist fails with ERR_NOT_FOUND, evaluated left-to-right."

    A non-existent crew_member_id in the body => ERR_NOT_FOUND.

    Design: Corner/entities/create_assignment_parent_crew_not_found
    """
    prod, day = fixtures.production_active_with_day(
        total_budget_cents=1_000_000, shoot_date="2026-09-01", day_number=1)
    resp = api.create_assignment(
        {"shooting_day_id": day["id"],
         "crew_member_id": "00000000-0000-4000-8000-000000000abc",
         "call_time": "2026-09-01T06:00:00.000Z",
         "expected_shooting_day_version": day["version"]}, AD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# --------------------------------------------------------------------------- #
# Corner/entities/system_fields_input_ignored_on_create
# --------------------------------------------------------------------------- #
def test_created_production_status_and_cost_are_server_set(api):
    """PRD 3.1: "A freshly created production lands with its status field set to
    DRAFT, and its three rolled-up money figures — committed_cost_cents,
    actual_cost_cents, and residual_reserve_cents — all initialized to zero."

    Only the declared inputs are accepted; the created production is DRAFT with
    committed_cost_cents 0.

    Design: Corner/entities/system_fields_input_ignored_on_create
    """
    data = validate_success(api.create_production(
        {"title": "Ignore", "production_type": "EPISODIC",
         "total_budget_cents": 1_000_000}, LP), expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["committed_cost_cents"] == 0


# --------------------------------------------------------------------------- #
# Corner/validations/duplicate_day_number_rejected
# --------------------------------------------------------------------------- #
def test_duplicate_day_number_rejected(api):
    """PRD 3.3: "The day_number must be unique among the production's days that
    have not been cancelled: if another non-CANCELLED shooting day of the same
    production already carries that number, the create is refused with
    ERR_DUPLICATE_DAY_NUMBER."

    Design: Corner/validations/duplicate_day_number_rejected
    """
    prod = fixtures.production_in_pre_production(total_budget_cents=1_000_000)
    fixtures.create_shooting_day(prod["id"], shoot_date="2026-09-22", day_number=1)
    resp = api.create_shooting_day(
        {"production_id": prod["id"], "shoot_date": "2026-09-23", "day_number": 1}, AD)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_DAY_NUMBER.value)


# --------------------------------------------------------------------------- #
# Corner/validations/double_booked_same_crew_same_day
# --------------------------------------------------------------------------- #
def test_double_booked_same_crew_same_day(api):
    """PRD 3.4: "a person may hold only one booking per day: if the crew member
    already has an assignment on that shooting day, the create is refused with
    ERR_DOUBLE_BOOKED."

    Design: Corner/validations/double_booked_same_crew_same_day
    """
    ctx = fixtures.setup_scheduled_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=100_000,
        is_sag_aftra=False, union_code="NONE", with_fringe=False,
        call_time="2026-09-24T06:00:00.000Z", shoot_date="2026-09-24")
    current_day = validate_success(api.get_shooting_day(ctx["day"]["id"], AD))
    resp = api.create_assignment(
        {"shooting_day_id": ctx["day"]["id"], "crew_member_id": ctx["crew"]["id"],
         "call_time": "2026-09-24T07:00:00.000Z",
         "expected_shooting_day_version": current_day["version"]}, AD)
    validate_error(resp, ApiErrorId.ERR_DOUBLE_BOOKED.value)


# --------------------------------------------------------------------------- #
# Corner/validations/permit_window_end_before_start_rejected
# --------------------------------------------------------------------------- #
def test_permit_window_end_before_start_rejected(api):
    """PRD 3.7: "The window_end must be strictly after window_start; if it is not,
    the create is refused with ERR_INVALID_TIME_RANGE."

    Design: Corner/validations/permit_window_end_before_start_rejected
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    loc = fixtures.create_location(prod["id"], name="Loc", address="1 St")
    resp = api.create_location_permit(
        {"location_id": loc["id"], "permit_number": "P-X",
         "window_start": "2026-09-25T12:00:00.000Z",
         "window_end": "2026-09-25T10:00:00.000Z"}, LP)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE.value)


# --------------------------------------------------------------------------- #
# Corner/validations/wrap_time_not_after_call_time_rejected
# --------------------------------------------------------------------------- #
def test_wrap_time_equal_to_call_time_rejected(api):
    """PRD 3.4: "The wrap_time must be strictly later than the assignment's
    call_time; if it is not, the check-out is refused with ERR_INVALID_TIME_RANGE."

    wrap_time == call_time => ERR_INVALID_TIME_RANGE; assignment stays CHECKED_IN.

    Design: Corner/validations/wrap_time_not_after_call_time_rejected
    """
    ctx = fixtures.setup_checked_in_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=100_000,
        is_sag_aftra=False, union_code="NONE", with_fringe=False,
        call_time="2026-09-26T06:00:00.000Z", shoot_date="2026-09-26")
    resp = api.check_out_assignment(
        ctx["assignment"]["id"],
        {"wrap_time": "2026-09-26T06:00:00.000Z", "meal_breaks_taken": 0}, AD)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE.value)
    asg = validate_success(api.get_assignment(ctx["assignment"]["id"], AD))
    assert asg["attendance_status"] == "CHECKED_IN"


# --------------------------------------------------------------------------- #
# Corner/validations/duplicate_union_fringe_rejected
# --------------------------------------------------------------------------- #
def test_duplicate_union_fringe_rejected(api):
    """PRD 3.8: "At most one fringe configuration may exist per union per
    production: a second configuration for a union_code already configured on that
    production is refused with ERR_DUPLICATE_FRINGE."

    Design: Corner/validations/duplicate_union_fringe_rejected
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    fixtures.create_union_fringe(prod["id"], union_code="SAG_AFTRA",
                                 fringe_rate_bps=1800, pension_health_flat_cents=15_000)
    resp = api.create_union_fringe(
        {"production_id": prod["id"], "union_code": "SAG_AFTRA",
         "fringe_rate_bps": 1500, "pension_health_flat_cents": 10_000}, LP)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_FRINGE.value)


# --------------------------------------------------------------------------- #
# Corner/validations/budget_would_exceed_on_approve_pay
# --------------------------------------------------------------------------- #
def test_budget_would_exceed_on_approve_pay(api):
    """PRD 3.5: "if locking this paid_cost_cents would push the production's
    committed_cost_cents strictly above its total_budget_cents, the approval is
    refused with ERR_BUDGET_WOULD_EXCEED (a result that exactly equals the budget
    is allowed)."

    Budget 300000; actual would be 482000 (OT + meal + turnaround breach + fringe)
    > 300000 => ERR_BUDGET_WOULD_EXCEED; assignment stays UNPAID.

    Design: Corner/validations/budget_would_exceed_on_approve_pay
    """
    prod = fixtures.create_production(total_budget_cents=300_000)
    fixtures.create_budget_line(prod["id"], estimated_cents=200_000)
    fixtures.create_union_fringe(prod["id"], union_code="SAG_AFTRA",
                                 fringe_rate_bps=1800, pension_health_flat_cents=15_000)
    crew = fixtures.create_crew(prod["id"], daily_rate_cents=200_000,
                                is_sag_aftra=True, union_code="SAG_AFTRA")
    fixtures.advance_production(prod["id"])
    day1 = fixtures.create_shooting_day(prod["id"], shoot_date="2026-09-28", day_number=1)
    day2 = fixtures.create_shooting_day(prod["id"], shoot_date="2026-09-29", day_number=2)
    fixtures.advance_production(prod["id"])
    asg1 = fixtures.book_assignment(day1["id"], crew["id"], day1["version"],
                                    call_time="2026-09-28T13:00:00.000Z")
    cs1 = fixtures.create_call_sheet(day1["id"], general_call_time="2026-09-28T13:00:00.000Z")
    validate_success(api.publish_call_sheet(cs1["id"], AD))
    validate_success(api.start_shooting_day(day1["id"], AD))
    validate_success(api.check_in_assignment(asg1["id"], AD))
    validate_success(api.check_out_assignment(
        asg1["id"], {"wrap_time": "2026-09-28T23:00:00.000Z", "meal_breaks_taken": 2}, AD))
    validate_success(api.wrap_shooting_day(day1["id"], AD))
    asg2 = fixtures.book_assignment(day2["id"], crew["id"], day2["version"],
                                    call_time="2026-09-29T06:00:00.000Z")
    cs2 = fixtures.create_call_sheet(day2["id"], general_call_time="2026-09-29T06:00:00.000Z")
    validate_success(api.publish_call_sheet(cs2["id"], AD))
    validate_success(api.start_shooting_day(day2["id"], AD))
    validate_success(api.check_in_assignment(asg2["id"], AD))
    validate_success(api.check_out_assignment(
        asg2["id"], {"wrap_time": "2026-09-29T19:00:00.000Z", "meal_breaks_taken": 0}, AD))
    resp = api.approve_pay_assignment(asg2["id"], PC)
    validate_error(resp, ApiErrorId.ERR_BUDGET_WOULD_EXCEED.value)
    refreshed = validate_success(api.get_assignment(asg2["id"], AD))
    assert refreshed["payment_status"] == "UNPAID"


# --------------------------------------------------------------------------- #
# Corner/validations/scene_schedule_locked_when_day_not_planned
# --------------------------------------------------------------------------- #
def test_scene_schedule_locked_when_day_called(api):
    """PRD 3.3: "scheduling it onto a day is a separate action ... permitted only
    when the target day belongs to the same production as the scene and is
    currently in PLANNED; if the day is not PLANNED or belongs to a different
    production, the request is refused with ERR_SCENE_SCHEDULE_LOCKED."

    Scheduling a scene onto a CALLED day => ERR_SCENE_SCHEDULE_LOCKED.

    Design: Corner/validations/scene_schedule_locked_when_day_not_planned
    """
    ctx = fixtures.setup_scheduled_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=100_000,
        is_sag_aftra=False, union_code="NONE", with_fringe=False,
        call_time="2026-10-01T06:00:00.000Z", shoot_date="2026-10-01")
    cs = fixtures.create_call_sheet(ctx["day"]["id"], general_call_time="2026-10-01T06:00:00.000Z")
    validate_success(api.publish_call_sheet(cs["id"], AD))  # day -> CALLED
    scene = fixtures.create_scene(ctx["prod"]["id"], scene_number="5B", page_eighths=4,
                                  int_ext="INT", day_night="DAY")
    resp = api.schedule_scene(scene["id"], {"shooting_day_id": ctx["day"]["id"]}, AD)
    validate_error(resp, ApiErrorId.ERR_SCENE_SCHEDULE_LOCKED.value)


# --------------------------------------------------------------------------- #
# Corner/validations/dailies_flag_without_reason_rejected
# --------------------------------------------------------------------------- #
def test_dailies_flag_without_reason_rejected(api):
    """PRD 3.10: "Flagging moves the footage from IN_REVIEW to FLAGGED and
    requires a flagged_reason to be supplied; flagging without a reason is refused
    with ERR_DAILIES_FLAG_REASON_REQUIRED."

    Design: Corner/validations/dailies_flag_without_reason_rejected
    """
    ctx = fixtures.setup_dailies_in_review(reel_label="A003")
    resp = api.flag_dailies(ctx["dailies"]["id"], {}, fixtures.PS)
    validate_error(resp, ApiErrorId.ERR_DAILIES_FLAG_REASON_REQUIRED.value)


# --------------------------------------------------------------------------- #
# Corner/validations/cross_production_assignment_rejected
# --------------------------------------------------------------------------- #
def test_cross_production_assignment_rejected(api):
    """PRD 3.4: "the referenced crew member and the referenced shooting day must
    belong to the same production; a cross-reference between productions is
    refused with ERR_CROSS_PRODUCTION_REFERENCE."

    Design: Corner/validations/cross_production_assignment_rejected
    """
    prod_a, day_a = fixtures.production_active_with_day(
        total_budget_cents=1_000_000, shoot_date="2026-10-04", day_number=1)
    prod_b = fixtures.create_production(total_budget_cents=1_000_000, title="Prod B")
    crew_b = fixtures.create_crew(prod_b["id"], full_name="Other", role_title="Grip",
                                  daily_rate_cents=100_000, is_sag_aftra=False, union_code="NONE")
    resp = api.create_assignment(
        {"shooting_day_id": day_a["id"], "crew_member_id": crew_b["id"],
         "call_time": "2026-10-04T06:00:00.000Z",
         "expected_shooting_day_version": day_a["version"]}, AD)
    validate_error(resp, ApiErrorId.ERR_CROSS_PRODUCTION_REFERENCE.value)


# --------------------------------------------------------------------------- #
# Corner/validations/publish_callsheet_when_production_not_active_rejected
# --------------------------------------------------------------------------- #
def test_publish_callsheet_when_production_not_active_rejected(api):
    """PRD 3.6: "It is permitted only when the sheet is DRAFT, its parent shooting
    day is PLANNED, that day has at least one assignment, and the grandparent
    production is ACTIVE; if the production is not ACTIVE, publication is refused
    with ERR_PRODUCTION_NOT_ACTIVE".

    Production only PRE_PRODUCTION => publish refused; day stays PLANNED.

    Design: Corner/validations/publish_callsheet_when_production_not_active_rejected
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    fixtures.create_budget_line(prod["id"], estimated_cents=500_000)
    crew = fixtures.create_crew(prod["id"], daily_rate_cents=100_000,
                                is_sag_aftra=False, union_code="NONE")
    fixtures.advance_production(prod["id"])  # -> PRE_PRODUCTION
    day = fixtures.create_shooting_day(prod["id"], shoot_date="2026-10-04", day_number=1)
    fixtures.book_assignment(day["id"], crew["id"], day["version"],
                             call_time="2026-10-04T06:00:00.000Z")
    cs = fixtures.create_call_sheet(day["id"], general_call_time="2026-10-04T06:00:00.000Z")
    resp = api.publish_call_sheet(cs["id"], AD)
    validate_error(resp, ApiErrorId.ERR_PRODUCTION_NOT_ACTIVE.value)
    refreshed = validate_success(api.get_shooting_day(day["id"], AD))
    assert refreshed["status"] == "PLANNED"


# --------------------------------------------------------------------------- #
# Corner/endpoints/list_shooting_days_filtered_by_production_paginated
# --------------------------------------------------------------------------- #
def test_list_shooting_days_filtered_and_paginated(api):
    """PRD 2.3: "The limit parameter caps how many items a single page returns".
    PRD 2.3: "Each list response carries limit, offset, total_count, and has_more
    inside the meta object of the envelope."

    Two days under the production; limit=1 returns 1 item, total_count 2,
    has_more true.

    Design: Corner/endpoints/list_shooting_days_filtered_by_production_paginated
    """
    prod = fixtures.production_in_pre_production(total_budget_cents=1_000_000)
    fixtures.create_shooting_day(prod["id"], shoot_date="2026-10-05", day_number=1)
    fixtures.create_shooting_day(prod["id"], shoot_date="2026-10-06", day_number=2)
    resp = api.list_shooting_days(AD, params={"production_id": prod["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"expected has_more true, got {meta['has_more']}"
    assert len(data) == 1, f"expected 1 item, got {len(data)}"


# --------------------------------------------------------------------------- #
# Corner/endpoints/pagination_limit_over_max_rejected
# --------------------------------------------------------------------------- #
def test_pagination_limit_over_max_rejected(api):
    """PRD 2.3: "a supplied value must lie between a minimum of 1 and a maximum of
    100. ... A limit outside the 1-to-100 band, or a negative offset, is rejected
    with ERR_PAGINATION_INVALID."

    Design: Corner/endpoints/pagination_limit_over_max_rejected
    """
    resp = api.list_productions(LP, params={"limit": 500})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value)


# --------------------------------------------------------------------------- #
# Corner/endpoints/budget_summary_computed_read
# --------------------------------------------------------------------------- #
def test_budget_summary_computed_read_no_actuals(api):
    """PRD 3.1: "It returns total_estimated_cents (the sum of estimated_cents
    across all of the production's budget lines), total_actual_cents (the sum of
    actual_cents across those same lines), total_variance_cents (the total
    estimated minus the total actual), over_budget (true only when total actual is
    strictly greater than total estimated".

    Two lines (500000 + 100000), no actuals => est 600000, act 0, variance 600000,
    over_budget false.

    Design: Corner/endpoints/budget_summary_computed_read
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    fixtures.create_budget_line(prod["id"], category="BELOW_THE_LINE_LABOR", estimated_cents=500_000)
    fixtures.create_budget_line(prod["id"], category="LOCATIONS", estimated_cents=100_000)
    summary = validate_success(api.get_budget_summary(prod["id"], LP))
    assert summary["total_estimated_cents"] == 600000
    assert summary["total_actual_cents"] == 0
    assert summary["total_variance_cents"] == 600000
    assert summary["over_budget"] is False


# --------------------------------------------------------------------------- #
# Corner/endpoints/post_actual_updates_variance
# --------------------------------------------------------------------------- #
def test_post_actual_updates_actual_and_variance(api):
    """PRD 3.2: "A manual posting adds an amount_cents to a chosen budget line's
    actual_cents and recomputes that line's variance_cents". PRD 3.1: "Each
    individual budget line's own variance_cents is its estimated_cents minus its
    actual_cents".

    amount 40000 on a line estimated 100000 => actual 40000, variance 60000.

    Design: Corner/endpoints/post_actual_updates_variance
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    prod_v = prod["version"]
    line = fixtures.create_budget_line(prod["id"], category="LOCATIONS", estimated_cents=100_000)
    updated = validate_success(api.post_actual(
        line["id"], {"amount_cents": 40_000, "expected_production_version": prod_v}, LP))
    assert updated["actual_cents"] == 40000, f"expected actual 40000, got {updated['actual_cents']}"
    assert updated["variance_cents"] == 60000, f"expected variance 60000, got {updated['variance_cents']}"
