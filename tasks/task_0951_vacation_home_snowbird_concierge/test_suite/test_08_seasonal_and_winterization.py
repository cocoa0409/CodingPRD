"""The seasonal axis, the winterization record and the independent occupancy axis."""

from test_helpers import (
    AUDITOR,
    DISPATCHER,
    FIELD_TECH,
    PLATFORM_ADMIN,
    ApiErrorId,
    complete_visit,
    issue_key,
    new_eligible_vendor,
    new_key_asset,
    new_owner,
    new_property,
    new_rental_turnover,
    new_template,
    new_visit,
    new_winterization_record,
    record_step,
    refresh_key_issuance,
    refresh_property,
    refresh_visit,
    refresh_winterization,
    run_occupancy,
    run_seasonal,
    run_visit_to_in_progress,
    seasonal,
    set_clock,
    setup_subscribed_property,
    setup_winterized_property,
    validate_error,
    validate_paginated,
    validate_success,
    winterization_record_of,
)

SEASONAL_PLAN = {"tier": "STANDARD", "monthly_fee_cents": 19986, "included_visit_units": 4,
                 "covered_visit_types": ["ROUTINE_WATCH", "SEASONAL_CLOSE", "SEASONAL_OPEN"]}


# --------------------------------------------------------------------------
# The two axes
# --------------------------------------------------------------------------

def test_the_seasonal_cycle_runs_while_occupancy_holds_and_then_defers_the_watches(api):
    """PRD 3.1: "Every home carries two lifecycle states that evolve completely
    independently of one another on the same row."
    PRD 3.1: "An owner moves the home from `VACANT` to `OWNER_IN_RESIDENCE`, permitted
    only while `seasonal_state` is `OPEN` or `OPENING`; the move defers every scheduled
    `ROUTINE_WATCH` visit on the property, stamping each with a `defer_reason` of
    `OWNER_IN_RESIDENCE`, and advances the property's `version` by one."

    Design: Difficulty/non_linear_state_machine/property_seasonal_and_occupancy_axes_evolve_independently
    """
    ctx = setup_subscribed_property(plan_overrides=SEASONAL_PLAN)
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    first = new_visit(ctx["property_id"], template["id"],
                      scheduled_start_at="2026-06-10T13:00:00Z",
                      scheduled_end_at="2026-06-10T15:00:00Z")
    second = new_visit(ctx["property_id"], template["id"],
                       scheduled_start_at="2026-06-17T13:00:00Z",
                       scheduled_end_at="2026-06-17T15:00:00Z")

    closing = run_seasonal(ctx["property_id"], "BEGIN_CLOSE")
    assert closing["seasonal_state"] == "CLOSING"
    assert closing["occupancy_state"] == "VACANT", "the occupancy axis does not move"

    reopened = run_seasonal(ctx["property_id"], "ABORT_CLOSE")
    assert reopened["seasonal_state"] == "OPEN"

    occupied = run_occupancy(ctx["property_id"], "OWNER_IN_RESIDENCE", ctx["owner_headers"])
    assert occupied["occupancy_state"] == "OWNER_IN_RESIDENCE"
    assert occupied["seasonal_state"] == "OPEN"

    for visit in (first, second):
        reread = refresh_visit(visit["id"])
        assert reread["status"] == "DEFERRED"
        assert reread["defer_reason"] == "OWNER_IN_RESIDENCE"
        assert reread["deferral_count"] == 1


def test_the_seasonal_axis_completes_a_whole_cycle_with_occupancy_untouched(api):
    """PRD 3.8: "`COMPLETE_OPEN` closes the cycle from `OPENING` back to `OPEN`. It
    requires at least one visit on the property with `visit_type` `SEASONAL_OPEN` and
    status `COMPLETED` whose `completed_at` is at or after the newest winterization
    record's `created_at`; without one the request is rejected with
    `ERR_NO_SEASONAL_OPEN_VISIT`. Its only effect is to advance `Property.version` by one.
    The seasonal axis has no terminal state."
    PRD 3.1: "`occupancy_state` starts at `VACANT` and is star-shaped: every occupied
    state is entered from `VACANT` and returns to `VACANT`."

    Design: Difficulty/non_linear_state_machine/property_seasonal_and_occupancy_axes_evolve_independently
    """
    ctx = setup_subscribed_property(clock="2026-10-01T00:00:00Z", plan_overrides=SEASONAL_PLAN,
                                    started_on="2026-10-01T00:00:00Z")
    closing = run_seasonal(ctx["property_id"], "BEGIN_CLOSE")
    assert closing["seasonal_state"] == "CLOSING"
    record = winterization_record_of(ctx["property_id"])
    record_step(record["id"], "ALL_REQUIRED", thermostat_f=55)
    winterized = run_seasonal(ctx["property_id"], "COMPLETE_WINTERIZATION")
    assert winterized["seasonal_state"] == "WINTERIZED"
    opening = run_seasonal(ctx["property_id"], "BEGIN_OPEN")
    assert opening["seasonal_state"] == "OPENING"

    template = new_template("SEASONAL_OPEN", item_codes=["REOPEN_CHECK"], critical_item_codes=[])
    visit = new_visit(ctx["property_id"], template["id"], visit_type="SEASONAL_OPEN",
                      scheduled_start_at="2026-10-05T13:00:00Z",
                      scheduled_end_at="2026-10-05T15:00:00Z")
    run_visit_to_in_progress(visit["id"], "2026-10-05T14:00:00Z")
    complete_visit(visit["id"], ["REOPEN_CHECK"], [])

    reopened = run_seasonal(ctx["property_id"], "COMPLETE_OPEN")
    assert reopened["seasonal_state"] == "OPEN"
    assert reopened["occupancy_state"] == "VACANT", "occupancy never moved during the cycle"


def test_owner_in_residence_is_refused_while_the_home_is_closing(api):
    """PRD 3.1: "a move to `OWNER_IN_RESIDENCE` attempted while the home is `CLOSING` or
    `WINTERIZED` is rejected with `ERR_SEASONAL_STATE_FORBIDS_OCCUPANCY`."

    Design: Corner/errors/err_seasonal_state_forbids_occupancy_while_closing_returns_409
    """
    set_clock("2026-10-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="CloOcc House", address_line="42 Shut St",
                        travel_distance_miles=5.0)
    run_seasonal(prop["id"], "BEGIN_CLOSE")

    from test_helpers import make_owner_headers
    response = api.create_property_occupancy_transition(
        prop["id"], {"to_state": "OWNER_IN_RESIDENCE"}, make_owner_headers(owner["id"])
    )
    validate_error(response, ApiErrorId.ERR_SEASONAL_STATE_FORBIDS_OCCUPANCY.value)
    reread = validate_success(api.get_property(prop["id"], DISPATCHER))
    assert reread["occupancy_state"] == "VACANT"
    assert reread["seasonal_state"] == "CLOSING"


def test_rental_occupancy_needs_the_property_enrolled(api):
    """PRD 3.1: "A dispatcher moves the home from `VACANT` to `RENTAL_OCCUPIED`, permitted
    only when `rental_program_enrolled` is true and `seasonal_state` is exactly `OPEN`,
    advancing `version` by one"
    PRD 3.1: "A move to `RENTAL_OCCUPIED` that fails its enrolment or seasonal
    precondition is rejected with `ERR_RENTAL_NOT_ENROLLED`"

    Design: Corner/errors/err_rental_not_enrolled_on_occupancy_transition_returns_409
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="NoRent House", address_line="41 Guest Gr",
                        travel_distance_miles=5.0)
    assert prop["rental_program_enrolled"] is False

    response = api.create_property_occupancy_transition(
        prop["id"], {"to_state": "RENTAL_OCCUPIED"}, DISPATCHER
    )
    validate_error(response, ApiErrorId.ERR_RENTAL_NOT_ENROLLED.value)
    assert validate_success(api.get_property(prop["id"], DISPATCHER))["occupancy_state"] == "VACANT"


# --------------------------------------------------------------------------
# Seasonal close
# --------------------------------------------------------------------------

def test_begin_close_creates_the_winterization_record_immediately(api):
    """PRD 3.8: "`BEGIN_CLOSE` moves the property from `OPEN` to `CLOSING`. It requires
    `occupancy_state` to be `VACANT` and requires that no rental turnover on the property
    sits in `CHECKOUT`, `CLEANING`, `INSPECTION` or `READY`, an in-flight turnover being
    rejected with `ERR_TURNOVER_IN_FLIGHT`. It creates a winterization record for the
    property in status `NOT_STARTED` and advances `Property.version` by one."
    PRD 3.8: "Either way it is born `NOT_STARTED` with a `completeness_pct` of 0.0"

    Design: Corner/consistency_model/immediate_consistency_cascaded_children_visible_in_the_same_request
    """
    set_clock("2026-10-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="ImmCasc House", address_line="1 Now Nook",
                        travel_distance_miles=5.0)
    transitioned = run_seasonal(prop["id"], "BEGIN_CLOSE")
    assert transitioned["seasonal_state"] == "CLOSING"

    rows, meta = validate_paginated(
        api.list_winterization_records(headers=DISPATCHER, params={"property_id": prop["id"]})
    )
    assert meta["total_count"] == 1, "the cascaded child is listable in the very next request"
    assert rows[0]["status"] == "NOT_STARTED"
    assert rows[0]["completeness_pct"] == 0.0
    assert validate_success(
        api.get_property(prop["id"], DISPATCHER)
    )["winterization_completeness_pct"] == 0.0


def test_an_in_flight_turnover_blocks_the_seasonal_close(api):
    """PRD 2.8: "Beginning a seasonal close requires that no rental turnover on the
    property is in status `CHECKOUT`, `CLEANING`, `INSPECTION` or `READY`. This applies to
    seasonal transitions. Otherwise `ERR_TURNOVER_IN_FLIGHT`, HTTP 409."

    Design: Corner/validations/begin_close_blocked_by_in_flight_turnover_not_by_occupancy
    """
    set_clock("2026-06-10T12:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="Flight House", address_line="34 Clean Ct",
                        travel_distance_miles=5.0, rental_program_enrolled=True)
    turnover = new_rental_turnover(prop["id"], checkout_at="2026-06-10T11:00:00Z",
                                   checkin_at="2026-06-12T15:00:00Z", guest_reference="BK-9300")
    validate_success(
        api.advance_rental_turnover(turnover["id"], {"to_status": "CHECKOUT"}, DISPATCHER)
    )
    validate_success(
        api.advance_rental_turnover(turnover["id"], {"to_status": "CLEANING"}, DISPATCHER)
    )

    response = seasonal(prop["id"], "BEGIN_CLOSE")
    validate_error(response, ApiErrorId.ERR_TURNOVER_IN_FLIGHT.value)
    reread = validate_success(api.get_property(prop["id"], DISPATCHER))
    assert reread["seasonal_state"] == "OPEN"
    assert reread["occupancy_state"] == "VACANT"
    _, meta = validate_paginated(
        api.list_winterization_records(headers=DISPATCHER, params={"property_id": prop["id"]})
    )
    assert meta["total_count"] == 0


def test_completing_winterization_needs_all_four_required_steps(api):
    """PRD 3.8: "`COMPLETE_WINTERIZATION` moves the property from `CLOSING` to
    `WINTERIZED`. It requires the newest winterization record to be in status `COMPLETE` —
    anything less is rejected with `ERR_WINTERIZATION_INCOMPLETE` — and requires
    `occupancy_state` to be `VACANT`."
    PRD 3.8: "`completeness_pct` is one hundred multiplied by `completed_step_count` and
    divided by four, rounded to one decimal place, so one of four is 25.0 and three of
    four is 75.0."

    Design: Corner/validations/complete_winterization_blocked_when_record_only_partial
    """
    set_clock("2026-10-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="Part House", address_line="35 Partial Pl",
                        travel_distance_miles=5.0)
    run_seasonal(prop["id"], "BEGIN_CLOSE")
    record = winterization_record_of(prop["id"])
    record_step(record["id"], "WATER_SHUTOFF")
    record_step(record["id"], "LINES_DRAINED")
    partial = record_step(record["id"], "VALVE_TAGGED")
    assert partial["completeness_pct"] == 75.0
    assert partial["status"] == "PARTIAL"

    response = seasonal(prop["id"], "COMPLETE_WINTERIZATION")
    validate_error(response, ApiErrorId.ERR_WINTERIZATION_INCOMPLETE.value)
    assert validate_success(api.get_property(prop["id"], DISPATCHER))["seasonal_state"] == "CLOSING"


def test_spring_open_is_blocked_by_an_overdue_key_issuance(api):
    """PRD 3.8: "`BEGIN_OPEN` moves the property from `WINTERIZED` to `OPENING`. It
    requires that no key issuance on any key asset of the property is `OVERDUE` or `LOST`,
    a custody problem being rejected with `ERR_KEY_CUSTODY_BLOCKS_OPEN`."

    Design: Corner/validations/spring_open_blocked_by_overdue_key_issuance
    """
    set_clock("2026-10-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="Custody House", address_line="36 Latch Ln",
                        travel_distance_miles=5.0)
    vendor = new_eligible_vendor(legal_name="Slow Locks", trade="LOCKSMITH",
                                 coi_expires_at="2027-06-01T00:00:00Z",
                                 license_expires_at="2027-06-01T00:00:00Z",
                                 hourly_rate_cents=7000, rating=3.5)
    key_asset = new_key_asset(prop["id"], key_type="LOCKBOX", label="Side lockbox",
                              copies_total=1, current_code="4444")
    issuance = issue_key(key_asset["id"], vendor["id"])

    run_seasonal(prop["id"], "BEGIN_CLOSE")
    record = winterization_record_of(prop["id"])
    record_step(record["id"], "ALL_REQUIRED", thermostat_f=55)
    winterized = run_seasonal(prop["id"], "COMPLETE_WINTERIZATION")
    assert winterized["seasonal_state"] == "WINTERIZED"

    set_clock("2026-10-03T00:00:00Z")
    validate_success(api.mark_overdue_key_issuance(issuance["id"], {}, DISPATCHER))
    assert refresh_key_issuance(issuance["id"])["status"] == "OVERDUE"

    response = seasonal(prop["id"], "BEGIN_OPEN")
    validate_error(response, ApiErrorId.ERR_KEY_CUSTODY_BLOCKS_OPEN.value)
    assert validate_success(
        api.get_property(prop["id"], DISPATCHER)
    )["seasonal_state"] == "WINTERIZED"


def test_complete_open_needs_a_completed_seasonal_open_visit(api):
    """PRD 2.8: "Completing a spring open requires a completed visit of type
    `SEASONAL_OPEN` whose `completed_at` is at or after the `created_at` of the newest
    winterization record. This applies to seasonal transitions. Otherwise
    `ERR_NO_SEASONAL_OPEN_VISIT`, HTTP 409."

    Design: Corner/errors/err_no_seasonal_open_visit_on_complete_open_returns_409
    """
    scenario = setup_winterized_property(
        property_overrides={"label": "Spring House", "address_line": "37 Thaw Tce",
                            "travel_distance_miles": 5.0}
    )
    set_clock("2027-04-01T00:00:00Z")
    opening = run_seasonal(scenario["property_id"], "BEGIN_OPEN")
    assert opening["seasonal_state"] == "OPENING"

    response = seasonal(scenario["property_id"], "COMPLETE_OPEN")
    validate_error(response, ApiErrorId.ERR_NO_SEASONAL_OPEN_VISIT.value)
    assert validate_success(
        api.get_property(scenario["property_id"], DISPATCHER)
    )["seasonal_state"] == "OPENING"


# --------------------------------------------------------------------------
# The winterization record's re-entrant loop
# --------------------------------------------------------------------------

def test_the_winterization_record_loops_through_partial_complete_and_reopened(api):
    """PRD 3.8: "`completed_step_count` counts the four required steps recorded as done:
    one for `water_shutoff_done`, one for `lines_drained_done`, one for
    `valve_tagged_done`, and one for the thermostat step **only when `thermostat_set_f` is
    non-null and at least 50** — a `THERMOSTAT_SET` step submitted with a `thermostat_f`
    of 49 records the value but does not increase the count, while 50 exactly does."
    PRD 3.8: "It moves the record to `REOPENED`, clears the four required step flags to
    false, clears `thermostat_set_f` and `completed_at` to null, recomputes
    `completeness_pct` to 0.0, and re-derives the property's
    `winterization_completeness_pct`, `freeze_risk_score` and `risk_posture`."

    Design: Difficulty/non_linear_state_machine/winterization_record_reentrant_partial_loop_and_reopen
    """
    set_clock("2026-10-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="Lakeside Lodge", address_line="8 Birch Rd",
                        travel_distance_miles=8.0)
    record = new_winterization_record(prop["id"])
    assert record["status"] == "NOT_STARTED"

    step_one = record_step(record["id"], "WATER_SHUTOFF")
    assert step_one["status"] == "PARTIAL"
    assert step_one["completeness_pct"] == 25.0
    step_two = record_step(record["id"], "LINES_DRAINED")
    assert step_two["completeness_pct"] == 50.0
    cold = record_step(record["id"], "THERMOSTAT_SET", thermostat_f=49)
    assert cold["completeness_pct"] == 50.0, "49 degrees records the value but does not count"
    assert cold["thermostat_set_f"] == 49
    warm = record_step(record["id"], "THERMOSTAT_SET", thermostat_f=55)
    assert warm["completeness_pct"] == 75.0
    complete = record_step(record["id"], "VALVE_TAGGED")
    assert complete["status"] == "COMPLETE"
    assert complete["completeness_pct"] == 100.0

    reopened = validate_success(
        api.reopen_winterization_record(record["id"], {"reopen_reason": "FREEZE_ALARM"},
                                        DISPATCHER)
    )
    assert reopened["status"] == "REOPENED"
    assert reopened["completeness_pct"] == 0.0
    assert reopened["thermostat_set_f"] is None
    assert reopened["completed_at"] is None

    back_to_partial = record_step(record["id"], "WATER_SHUTOFF")
    assert back_to_partial["status"] == "PARTIAL"
    assert back_to_partial["completeness_pct"] == 25.0
    assert validate_success(
        api.get_property(prop["id"], DISPATCHER)
    )["winterization_completeness_pct"] == 25.0


def test_the_optional_antifreeze_step_never_raises_the_count(api):
    """PRD 3.8: "The four required step codes are `WATER_SHUTOFF`, `LINES_DRAINED`,
    `THERMOSTAT_SET` and `VALVE_TAGGED`; the single optional code is `ANTIFREEZE_ADDED`;
    and the literal `ALL_REQUIRED` is a shortcut."
    PRD 3.8: "`antifreeze_added_done` is deliberately not counted at all."

    Design: Difficulty/non_linear_state_machine/winterization_record_reentrant_partial_loop_and_reopen
    """
    set_clock("2026-10-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="Antifreeze Lodge", address_line="9 Birch Rd",
                        travel_distance_miles=8.0)
    record = new_winterization_record(prop["id"])
    record_step(record["id"], "WATER_SHUTOFF")
    with_antifreeze = record_step(record["id"], "ANTIFREEZE_ADDED")

    assert with_antifreeze["antifreeze_added_done"] is True
    assert with_antifreeze["completed_step_count"] == 1
    assert with_antifreeze["completeness_pct"] == 25.0
    assert with_antifreeze["status"] == "PARTIAL"


def test_the_all_required_shortcut_completes_the_record_in_one_call(api):
    """PRD 3.8: "The `ALL_REQUIRED` shortcut moves a record straight from `NOT_STARTED` to
    `COMPLETE`, requires a `thermostat_f` of at least 50 — a lower value is rejected with
    `ERR_THERMOSTAT_BELOW_MINIMUM` — and records all four required steps at once, stamping
    `completed_at` and setting `completeness_pct` to 100.0."
    PRD 3.1: "The second term reads `winterization_completeness_pct`: if that percentage
    is 100.0 or greater the term is 0.0, and otherwise it is 25.0 multiplied by one minus
    the percentage divided by one hundred."

    Design: Corner/calculations/winterization_all_required_shortcut_completes_in_one_call
    """
    set_clock("2026-10-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="Winter House", address_line="4 Drain Dr",
                        travel_distance_miles=18.0)
    run_seasonal(prop["id"], "BEGIN_CLOSE")
    record = winterization_record_of(prop["id"])

    completed = record_step(record["id"], "ALL_REQUIRED", thermostat_f=58)
    assert completed["status"] == "COMPLETE"
    assert completed["completeness_pct"] == 100.0
    assert completed["water_shutoff_done"] is True
    assert completed["lines_drained_done"] is True
    assert completed["valve_tagged_done"] is True
    assert completed["thermostat_set_f"] == 58
    assert completed["completed_step_count"] == 4

    reread = validate_success(api.get_property(prop["id"], DISPATCHER))
    assert reread["winterization_completeness_pct"] == 100.0
    assert reread["freeze_risk_score"] == 15.0, "only the vacancy term survives"
    assert reread["risk_posture"] == "NORMAL"


def test_an_unknown_step_code_is_rejected(api):
    """PRD 3.8: "Anything else, or a `THERMOSTAT_SET` step with no `thermostat_f`, is
    rejected with `ERR_WINTERIZATION_STEP_INVALID`."

    Design: Corner/errors/err_winterization_step_invalid_for_unknown_step_code_returns_400
    """
    set_clock("2026-10-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="Step House", address_line="1 Step St",
                        travel_distance_miles=5.0)
    record = new_winterization_record(prop["id"])

    response = api.steps_winterization_record(record["id"], {"step_code": "ROOF_TARP"}, FIELD_TECH)
    validate_error(response, ApiErrorId.ERR_WINTERIZATION_STEP_INVALID.value)
    reread = refresh_winterization(record["id"])
    assert reread["status"] == "NOT_STARTED"
    assert reread["completeness_pct"] == 0.0


def test_the_shortcut_refuses_a_thermostat_below_fifty(api):
    """PRD 2.9: "`ERR_THERMOSTAT_BELOW_MINIMUM` when a `THERMOSTAT_SET` step supplies a
    `thermostat_f` below 50 on the `ALL_REQUIRED` shortcut"
    PRD 3.8: "The `ALL_REQUIRED` shortcut moves a record straight from `NOT_STARTED` to
    `COMPLETE`, requires a `thermostat_f` of at least 50 — a lower value is rejected with
    `ERR_THERMOSTAT_BELOW_MINIMUM` — and records all four required steps at once, stamping
    `completed_at` and setting `completeness_pct` to 100.0."

    Design: Corner/errors/err_thermostat_below_minimum_on_all_required_shortcut_returns_400
    """
    set_clock("2026-10-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="Cold House", address_line="50 Deg Dr",
                        travel_distance_miles=5.0)
    record = new_winterization_record(prop["id"])

    response = api.steps_winterization_record(
        record["id"], {"step_code": "ALL_REQUIRED", "thermostat_f": 45}, FIELD_TECH
    )
    validate_error(response, ApiErrorId.ERR_THERMOSTAT_BELOW_MINIMUM.value)
    reread = refresh_winterization(record["id"])
    assert reread["status"] == "NOT_STARTED"
    assert reread["completed_step_count"] == 0
    assert reread["thermostat_set_f"] is None


def test_repeating_a_recorded_step_is_rejected(api):
    """PRD 3.8: "From `PARTIAL` a further step keeps it in `PARTIAL` while the resulting
    count is still strictly below four, and requires that the submitted step is not
    already recorded as done — a repeat is rejected with `ERR_STEP_ALREADY_RECORDED`."

    Design: Corner/errors/err_step_already_recorded_on_duplicate_winterization_step_returns_409
    """
    set_clock("2026-10-01T00:00:00Z")
    owner = new_owner()
    prop = new_property(owner["id"], label="DupStep House", address_line="1 Again Ave",
                        travel_distance_miles=5.0)
    record = new_winterization_record(prop["id"])
    record_step(record["id"], "WATER_SHUTOFF")

    response = api.steps_winterization_record(record["id"], {"step_code": "WATER_SHUTOFF"},
                                              FIELD_TECH)
    validate_error(response, ApiErrorId.ERR_STEP_ALREADY_RECORDED.value)
    reread = refresh_winterization(record["id"])
    assert reread["completed_step_count"] == 1
    assert reread["completeness_pct"] == 25.0


# --------------------------------------------------------------------------
# The seasonal gate is re-evaluated at departure
# --------------------------------------------------------------------------

def test_departure_re_evaluates_the_seasonal_gate_after_the_close_was_aborted(api):
    """PRD 3.4: "Departure is the point at which the seasonal and occupancy bands are
    **re-evaluated** — they are not checked only at scheduling — and it stamps
    `departed_at` and copies the acting `X-User-ID` into `tech_user_id`."
    PRD 2.8: "A visit whose `visit_type` is `SEASONAL_CLOSE` requires the property's
    `seasonal_state` to be `CLOSING`. This applies both at visit scheduling and again at
    departure. Otherwise `ERR_SEASONAL_STATE_FORBIDS_VISIT`, HTTP 409."

    Design: Difficulty/cross_entity_state_dependency/seasonal_close_visit_depart_rejected_after_close_aborted
    """
    ctx = setup_subscribed_property(
        clock="2026-10-01T00:00:00Z", plan_overrides=SEASONAL_PLAN,
        property_overrides={"label": "Closing Cabin", "address_line": "31 Season St",
                            "travel_distance_miles": 8.0},
        started_on="2026-10-01T00:00:00Z",
    )
    template = new_template("SEASONAL_CLOSE", item_codes=["SHUTOFF", "DRAIN"],
                            critical_item_codes=[])
    run_seasonal(ctx["property_id"], "BEGIN_CLOSE")
    visit = new_visit(ctx["property_id"], template["id"], visit_type="SEASONAL_CLOSE",
                      scheduled_start_at="2026-10-02T13:00:00Z",
                      scheduled_end_at="2026-10-02T15:00:00Z")
    run_seasonal(ctx["property_id"], "ABORT_CLOSE")
    set_clock("2026-10-02T14:00:00Z")

    response = api.depart_visit(visit["id"], {}, FIELD_TECH)
    assert response.status_code == 409, f"expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_SEASONAL_STATE_FORBIDS_VISIT.value)
    reread = refresh_visit(visit["id"])
    assert reread["status"] == "SCHEDULED"
    assert reread["departed_at"] is None
    assert refresh_property(ctx)["seasonal_state"] == "OPEN"


def test_a_seasonal_close_visit_cannot_be_scheduled_while_the_home_is_open(api):
    """PRD 2.8: "A visit whose `visit_type` is `SEASONAL_CLOSE` requires the property's
    `seasonal_state` to be `CLOSING`. This applies both at visit scheduling and again at
    departure. Otherwise `ERR_SEASONAL_STATE_FORBIDS_VISIT`, HTTP 409."
    PRD 3.8: "`ABORT_CLOSE` returns the property from `CLOSING` to `OPEN` and requires the
    newest winterization record to be in `NOT_STARTED` or `PARTIAL`."

    Design: Difficulty/cross_entity_state_dependency/seasonal_close_visit_depart_rejected_after_close_aborted
    """
    ctx = setup_subscribed_property(
        clock="2026-10-01T00:00:00Z", plan_overrides=SEASONAL_PLAN,
        property_overrides={"label": "Open Cabin", "address_line": "32 Season St",
                            "travel_distance_miles": 8.0},
        started_on="2026-10-01T00:00:00Z",
    )
    template = new_template("SEASONAL_CLOSE", item_codes=["SHUTOFF"], critical_item_codes=[])
    assert refresh_property(ctx)["seasonal_state"] == "OPEN"

    from test_helpers import create_visit_payload
    response = api.create_visit(
        create_visit_payload(ctx["property_id"], template["id"], visit_type="SEASONAL_CLOSE",
                             scheduled_start_at="2026-10-02T13:00:00Z",
                             scheduled_end_at="2026-10-02T15:00:00Z"),
        DISPATCHER,
    )
    assert response.status_code == 409, f"expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_SEASONAL_STATE_FORBIDS_VISIT.value)
    _, meta = validate_paginated(
        api.list_visits(headers=AUDITOR, params={"property_id": ctx["property_id"]})
    )
    assert meta["total_count"] == 0
