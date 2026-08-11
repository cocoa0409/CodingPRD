"""Completing a visit: the entitlement decision, the two pricing branches and freeze risk."""

from test_helpers import (
    ACCOUNT_MANAGER,
    AUDITOR,
    DISPATCHER,
    FIELD_TECH,
    ApiErrorId,
    assert_same_instant,
    complete_visit,
    new_template,
    new_visit,
    new_winterization_record,
    record_step,
    refresh_cycle,
    refresh_property,
    refresh_subscription,
    refresh_visit,
    run_visit_to_in_progress,
    set_clock,
    setup_subscribed_property,
    validate_error,
    validate_paginated,
    validate_success,
)

STANDARD = {"tier": "STANDARD", "monthly_fee_cents": 19986, "included_visit_units": 4,
            "covered_visit_types": ["ROUTINE_WATCH"]}


# --------------------------------------------------------------------------
# The entitled branch versus the overage branch
# --------------------------------------------------------------------------

def test_entitled_and_overage_branches_price_the_same_visit_shape_differently(api):
    """PRD 3.4: "On the **entitled** branch the base fee and the expedite component are
    both waived and the billable amount is the travel surcharge alone; the after-hours
    multiplier is structurally absent from that expression, because there is no base for
    it to multiply."
    PRD 3.4: "A `SCHEDULED` visit has a base of 6500 cents and no expedite component, and
    this is the only branch that can ever consume entitlement. Any other trigger source
    has a base of 11000 cents, with an expedite component of 2500 cents added only when
    the trigger source is exactly `OWNER_REQUESTED` and zero for `ALARM_TRIGGERED` and
    `STORM`."

    Design: Difficulty/dual_variant_calc/visit_billable_entitled_versus_overage_same_visit_shape
    """
    ctx = setup_subscribed_property(
        plan_overrides={"tier": "STANDARD", "monthly_fee_cents": 19986,
                        "included_visit_units": 4,
                        "covered_visit_types": ["ROUTINE_WATCH", "SEASONAL_CLOSE",
                                                "SEASONAL_OPEN"]},
    )
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK", "INT_WALK",
                                                         "PLUMBING_CHECK"],
                            critical_item_codes=["PLUMBING_CHECK"],
                            default_finding_category="PLUMBING")
    scheduled = new_visit(ctx["property_id"], template["id"], trigger_source="SCHEDULED",
                          scheduled_start_at="2026-06-02T13:00:00Z",
                          scheduled_end_at="2026-06-02T15:00:00Z")
    owner_requested = new_visit(ctx["property_id"], template["id"],
                                trigger_source="OWNER_REQUESTED",
                                scheduled_start_at="2026-06-03T13:00:00Z",
                                scheduled_end_at="2026-06-03T15:00:00Z")

    items = ["EXT_WALK", "INT_WALK", "PLUMBING_CHECK"]
    run_visit_to_in_progress(scheduled["id"], "2026-06-02T14:00:00Z")
    entitled = complete_visit(scheduled["id"], items, [])
    run_visit_to_in_progress(owner_requested["id"], "2026-06-03T14:00:00Z")
    overage = complete_visit(owner_requested["id"], items, [])

    assert entitled["entitlement_applied"] is True
    assert entitled["billable_amount_cents"] == 1500, "the Z2 travel surcharge alone"
    assert overage["entitlement_applied"] is False
    assert overage["billable_amount_cents"] == 15000, "11000 + 2500 expedite + 1500 travel"
    assert overage["after_hours_flag"] is False
    cycle = refresh_cycle(ctx["cycle_id"])
    assert cycle["entitlement_consumed_units"] == 1
    assert cycle["entitlement_remaining_units"] == 3


def test_the_entitled_branch_ignores_the_after_hours_multiplier(api):
    """PRD 3.4: "On the **entitled** branch the base fee and the expedite component are
    both waived and the billable amount is the travel surcharge alone; the after-hours
    multiplier is structurally absent from that expression, because there is no base for
    it to multiply."
    PRD 3.4: "That flag reads the UTC hour field of `arrived_at` alone, ignoring minutes
    and seconds, and is true when the hour is 22 or later or strictly earlier than 6: an
    arrival at 21:59 is not after hours, one at 22:00 is, one at 05:59 is, and one at
    06:00 is not."

    Design: Difficulty/dual_variant_calc/visit_billable_entitled_versus_overage_same_visit_shape
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    visit = new_visit(ctx["property_id"], template["id"], trigger_source="SCHEDULED",
                      scheduled_start_at="2026-06-02T21:00:00Z",
                      scheduled_end_at="2026-06-02T23:00:00Z")
    run_visit_to_in_progress(visit["id"], "2026-06-02T22:00:00Z")
    completed = complete_visit(visit["id"], ["EXT_WALK"], [])

    assert completed["after_hours_flag"] is True
    assert completed["entitlement_applied"] is True
    assert completed["billable_amount_cents"] == 1500, (
        "an entitled visit bills the travel surcharge alone, after hours or not"
    )


def test_the_entitled_branch_still_bills_the_zone_three_travel_surcharge(api):
    """PRD 3.1: "The zone carries a flat travel surcharge used later in visit pricing:
    nothing at all in `Z1`, 1500 cents in `Z2`, 3800 cents in `Z3`."
    PRD 3.4: "Because the combined length is forced to equal `required_item_count`,
    `checklist_completion_pct` — one hundred multiplied by the combined length of the two
    arrays and divided by `required_item_count`, rounded to one decimal place — always
    lands on exactly 100.0 for a successful completion."

    Design: Corner/calculations/entitled_visit_still_pays_the_zone_three_travel_surcharge
    """
    ctx = setup_subscribed_property(
        plan_overrides=STANDARD,
        property_overrides={"label": "Far House", "address_line": "45 Long Rd",
                            "travel_distance_miles": 45.0},
    )
    assert ctx["property"]["travel_zone"] == "Z3"
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    visit = new_visit(ctx["property_id"], template["id"])
    run_visit_to_in_progress(visit["id"], "2026-06-02T14:00:00Z")
    completed = complete_visit(visit["id"], ["EXT_WALK"], [])

    assert completed["entitlement_applied"] is True
    assert completed["billable_amount_cents"] == 3800
    assert completed["checklist_completion_pct"] == 100.0


def test_after_hours_multiplier_touches_the_base_fee_only(api):
    """PRD 3.4: "On the **overage** branch the after-hours multiplier of 1.35 is applied
    **to the base fee only** — never to the expedite component and never to the travel
    surcharge — when `after_hours_flag` is true, with the product rounded to whole cents;
    the multiplied-or-plain base, the expedite component and the travel surcharge are then
    added as flat addends."
    PRD 3.4: "an arrival at 21:59 is not after hours, one at 22:00 is, one at 05:59 is,
    and one at 06:00 is not."

    Design: Corner/calculations/after_hours_boundary_2159_versus_2200_on_owner_requested_visit
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    early = new_visit(ctx["property_id"], template["id"], trigger_source="OWNER_REQUESTED",
                      scheduled_start_at="2026-06-02T21:00:00Z",
                      scheduled_end_at="2026-06-02T23:00:00Z")
    late = new_visit(ctx["property_id"], template["id"], trigger_source="OWNER_REQUESTED",
                     scheduled_start_at="2026-06-03T21:00:00Z",
                     scheduled_end_at="2026-06-03T23:00:00Z")

    run_visit_to_in_progress(early["id"], "2026-06-02T21:59:00Z")
    early_done = complete_visit(early["id"], ["EXT_WALK"], [])
    run_visit_to_in_progress(late["id"], "2026-06-03T22:00:00Z")
    late_done = complete_visit(late["id"], ["EXT_WALK"], [])

    assert early_done["after_hours_flag"] is False
    assert early_done["billable_amount_cents"] == 15000
    assert late_done["after_hours_flag"] is True
    assert late_done["billable_amount_cents"] == 18850, (
        "round_half_up(11000 * 1.35) == 14850, plus 2500 expedite, plus 1500 travel"
    )
    assert early_done["entitlement_applied"] is False
    assert late_done["entitlement_applied"] is False


def test_a_one_unit_plan_prices_the_second_visit_on_the_overage_branch(api):
    """PRD 3.4: "The boundary is inclusive, so a cycle with exactly one unit left still
    consumes."
    PRD 3.4: "When all of that holds, `entitlement_applied` is set true, the cycle's
    `entitlement_consumed_units` rises by one and its `entitlement_remaining_units` falls
    by one. Otherwise `entitlement_applied` is set false and no counter moves."

    Design: Corner/calculations/entitlement_exhausted_on_second_visit_of_a_one_unit_plan
    """
    ctx = setup_subscribed_property(
        plan_overrides={"tier": "BASIC", "monthly_fee_cents": 9986, "included_visit_units": 1,
                        "covered_visit_types": ["ROUTINE_WATCH"]},
    )
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    first = new_visit(ctx["property_id"], template["id"],
                      scheduled_start_at="2026-06-02T13:00:00Z",
                      scheduled_end_at="2026-06-02T15:00:00Z")
    second = new_visit(ctx["property_id"], template["id"],
                       scheduled_start_at="2026-06-09T13:00:00Z",
                       scheduled_end_at="2026-06-09T15:00:00Z")
    run_visit_to_in_progress(first["id"], "2026-06-02T14:00:00Z")
    first_done = complete_visit(first["id"], ["EXT_WALK"], [])
    run_visit_to_in_progress(second["id"], "2026-06-09T14:00:00Z")
    second_done = complete_visit(second["id"], ["EXT_WALK"], [])

    assert first_done["entitlement_applied"] is True
    assert first_done["billable_amount_cents"] == 1500
    assert second_done["entitlement_applied"] is False
    assert second_done["billable_amount_cents"] == 8000, "6500 base plus 1500 travel"
    cycle = refresh_cycle(ctx["cycle_id"])
    assert cycle["entitlement_consumed_units"] == 1
    assert cycle["entitlement_remaining_units"] == 0


# --------------------------------------------------------------------------
# Checklist submission
# --------------------------------------------------------------------------

def test_checklist_arrays_must_cover_the_whole_template(api):
    """PRD 3.4: "The two arrays must be disjoint, every member of each must appear in the
    bound template's `item_codes`, and their combined length must equal the template's
    `required_item_count`; any violation is `ERR_CHECKLIST_MISMATCH`."

    Design: Corner/validations/checklist_arrays_must_partition_the_template_item_codes
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    template = new_template("ROUTINE_WATCH",
                            item_codes=["EXT_WALK", "INT_WALK", "PLUMBING_CHECK"],
                            critical_item_codes=["PLUMBING_CHECK"])
    visit = new_visit(ctx["property_id"], template["id"])
    run_visit_to_in_progress(visit["id"], "2026-06-02T14:00:00Z")

    response = api.complete_visit(
        visit["id"],
        {"completed_item_codes": ["EXT_WALK"], "failed_item_codes": ["INT_WALK"]},
        FIELD_TECH,
    )
    validate_error(response, ApiErrorId.ERR_CHECKLIST_MISMATCH.value)
    reread = refresh_visit(visit["id"])
    assert reread["status"] == "IN_PROGRESS"
    assert reread["completed_at"] is None
    assert refresh_cycle(ctx["cycle_id"])["entitlement_consumed_units"] == 0


def test_completing_a_visit_that_never_departed_is_rejected(api):
    """PRD 2.8: "The target entity's current status is a declared source state for the
    requested transition. This applies to every action endpoint that drives a state
    machine. Otherwise `ERR_INVALID_STATE_TRANSITION`, HTTP 409."
    PRD 3.4: "Completion is refused with `ERR_VISIT_NOT_ARRIVED` if either `departed_at`
    or `arrived_at` is missing."

    Design: Corner/state_machines/visit_complete_without_arrival_rejected
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    visit = new_visit(ctx["property_id"], template["id"])

    response = api.complete_visit(
        visit["id"], {"completed_item_codes": ["EXT_WALK"], "failed_item_codes": []}, FIELD_TECH
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    reread = refresh_visit(visit["id"])
    assert reread["status"] == "SCHEDULED"
    assert reread["completed_at"] is None
    cycle = refresh_cycle(ctx["cycle_id"])
    assert cycle["entitlement_consumed_units"] == 0
    assert cycle["entitlement_remaining_units"] == 4


# --------------------------------------------------------------------------
# Freeze risk and the temperature breach
# --------------------------------------------------------------------------

def test_freeze_risk_adds_three_weighted_terms_on_an_unwinterized_vacant_home(api):
    """PRD 3.1: "The first term reads `last_interior_temp_f`, the most recent interior
    reading stamped from a completing visit alongside the `last_temp_reading_at` instant
    of that reading; if no reading exists the term is 0.0, and otherwise the shortfall is
    the property's `freeze_setpoint_f` minus that reading, floored at zero, multiplied by
    6.0, and then capped at 60.0."
    PRD 3.1: "a score of at least 60.0 is `CRITICAL`, otherwise a score of at least 30.0
    is `ELEVATED`, otherwise the posture is `NORMAL`."
    PRD 3.4: "A breach creates a security incident with `incident_type` `FREEZE_ALARM`,
    `severity` `HIGH` and `status` `REPORTED`."

    Design: Difficulty/combinatorial_formula/freeze_risk_score_three_input_nested_min_max_mode_a
    """
    ctx = setup_subscribed_property(
        plan_overrides=STANDARD,
        property_overrides={"label": "Cold Cabin", "address_line": "77 Pine Rd",
                            "travel_distance_miles": 18.0, "freeze_setpoint_f": 55},
    )
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK", "INT_WALK"],
                            critical_item_codes=[])
    visit = new_visit(ctx["property_id"], template["id"])
    run_visit_to_in_progress(visit["id"], "2026-06-02T14:00:00Z")
    complete_visit(visit["id"], ["EXT_WALK", "INT_WALK"], [], interior_temp_f=48.0)

    prop = refresh_property(ctx)
    assert prop["last_interior_temp_f"] == 48.0
    assert prop["winterization_completeness_pct"] == 0.0
    assert prop["freeze_risk_score"] == 82.0, "42.0 + 25.0 + 15.0 == 82.0"
    assert prop["risk_posture"] == "CRITICAL"

    incidents, meta = validate_paginated(
        api.list_security_incidents(headers=AUDITOR, params={"property_id": ctx["property_id"]})
    )
    assert meta["total_count"] == 1, "48.0 is strictly below 55 - 3 == 52.0, so a breach fires"
    assert incidents[0]["incident_type"] == "FREEZE_ALARM"
    assert incidents[0]["severity"] == "HIGH"
    assert incidents[0]["status"] == "REPORTED"


def test_freeze_risk_worked_example_with_half_finished_winterization(api):
    """PRD 3.1: "The second term reads `winterization_completeness_pct`: if that
    percentage is 100.0 or greater the term is 0.0, and otherwise it is 25.0 multiplied by
    one minus the percentage divided by one hundred."
    PRD 3.1: "Worked: a setpoint of 55 with a reading of 48, a winterization completeness
    of 50.0 percent and a vacant home gives a shortfall of 7.0, a first term of 42.0 after
    the cap comparison, a second term of 12.5, a third term of 15.0, and a score of 69.5."

    Design: Difficulty/combinatorial_formula/freeze_risk_score_three_input_nested_min_max_mode_a
    """
    ctx = setup_subscribed_property(
        plan_overrides=STANDARD,
        property_overrides={"label": "Half Winterized", "address_line": "50 Pine Rd",
                            "travel_distance_miles": 18.0, "freeze_setpoint_f": 55},
    )
    record = new_winterization_record(ctx["property_id"])
    record_step(record["id"], "WATER_SHUTOFF")
    record = record_step(record["id"], "LINES_DRAINED")
    assert record["completeness_pct"] == 50.0
    assert refresh_property(ctx)["winterization_completeness_pct"] == 50.0

    template = new_template("ROUTINE_WATCH", item_codes=["INT_WALK"], critical_item_codes=[])
    visit = new_visit(ctx["property_id"], template["id"])
    run_visit_to_in_progress(visit["id"], "2026-06-02T14:00:00Z")
    complete_visit(visit["id"], ["INT_WALK"], [], interior_temp_f=48.0)

    prop = refresh_property(ctx)
    assert prop["freeze_risk_score"] == 69.5, "42.0 + 12.5 + 15.0 == 69.5"
    assert prop["risk_posture"] == "CRITICAL"


def test_reading_exactly_at_the_trip_point_raises_no_freeze_alarm(api):
    """PRD 3.4: "A temperature breach is detected by a **strict** comparison: the reading
    is a breach when it is strictly less than the property's `freeze_setpoint_f` minus a
    tolerance band of 3 degrees. With a setpoint of 55 the trip point is 52.0, so 52.0 is
    not a breach and 51.9 is."
    PRD 3.1: "Both comparisons include the boundary, so exactly 30.0 is `ELEVATED` and
    exactly 60.0 is `CRITICAL`."

    Design: Difficulty/boundary_precision_check/interior_temperature_exactly_at_trip_point_raises_no_incident
    """
    ctx = setup_subscribed_property(
        plan_overrides=STANDARD,
        property_overrides={"label": "Trip Point Place", "address_line": "52 Frost Rd",
                            "travel_distance_miles": 18.0, "freeze_setpoint_f": 55},
    )
    template = new_template("ROUTINE_WATCH", item_codes=["INT_WALK"], critical_item_codes=[])
    visit = new_visit(ctx["property_id"], template["id"])
    run_visit_to_in_progress(visit["id"], "2026-06-02T14:00:00Z")
    complete_visit(visit["id"], ["INT_WALK"], [], interior_temp_f=52.0)

    prop = refresh_property(ctx)
    assert prop["last_interior_temp_f"] == 52.0
    assert prop["freeze_risk_score"] == 58.0, "18.0 + 25.0 + 15.0 == 58.0"
    assert prop["risk_posture"] == "ELEVATED"
    _, meta = validate_paginated(
        api.list_security_incidents(headers=AUDITOR, params={"property_id": ctx["property_id"]})
    )
    assert meta["total_count"] == 0, "exactly at the trip point is not a breach"


def test_reading_below_the_trip_point_does_raise_a_freeze_alarm(api):
    """PRD 3.4: "A temperature breach is detected by a **strict** comparison: the reading
    is a breach when it is strictly less than the property's `freeze_setpoint_f` minus a
    tolerance band of 3 degrees. With a setpoint of 55 the trip point is 52.0, so 52.0 is
    not a breach and 51.9 is."
    PRD 3.4: "When `interior_temp_f` is supplied, the property's `last_interior_temp_f`
    and `last_temp_reading_at` are stamped from it and the freeze-risk score and posture
    are re-derived."

    Design: Difficulty/boundary_precision_check/interior_temperature_exactly_at_trip_point_raises_no_incident
    """
    ctx = setup_subscribed_property(
        plan_overrides=STANDARD,
        property_overrides={"label": "Below Trip Point", "address_line": "51 Frost Rd",
                            "travel_distance_miles": 18.0, "freeze_setpoint_f": 55},
    )
    template = new_template("ROUTINE_WATCH", item_codes=["INT_WALK"], critical_item_codes=[])
    visit = new_visit(ctx["property_id"], template["id"])
    run_visit_to_in_progress(visit["id"], "2026-06-02T14:00:00Z")
    complete_visit(visit["id"], ["INT_WALK"], [], interior_temp_f=51.0)

    prop = refresh_property(ctx)
    assert prop["last_interior_temp_f"] == 51.0
    assert_same_instant(prop["last_temp_reading_at"], "2026-06-02T14:00:00Z",
                        "last_temp_reading_at")
    assert prop["freeze_risk_score"] == 64.0, "24.0 + 25.0 + 15.0 == 64.0"
    assert prop["risk_posture"] == "CRITICAL"
    incidents, meta = validate_paginated(
        api.list_security_incidents(headers=AUDITOR, params={"property_id": ctx["property_id"]})
    )
    assert meta["total_count"] == 1
    assert incidents[0]["incident_type"] == "FREEZE_ALARM"


def test_risk_posture_read_exposes_the_whole_decomposition(api):
    """PRD 3.1: "A dedicated computed read exposes the risk decomposition as an object
    carrying `freeze_risk_score`, `risk_posture`, `winterization_completeness_pct`,
    `open_critical_finding_count`, `false_alarm_count_window` and `last_interior_temp_f`."

    Design: Corner/endpoints/risk_posture_computed_read_returns_the_full_decomposition
    """
    ctx = setup_subscribed_property(
        plan_overrides=STANDARD,
        property_overrides={"label": "Risk House", "address_line": "82 Score St",
                            "travel_distance_miles": 18.0},
    )
    template = new_template("ROUTINE_WATCH", item_codes=["INT_WALK"], critical_item_codes=[])
    visit = new_visit(ctx["property_id"], template["id"])
    run_visit_to_in_progress(visit["id"], "2026-06-02T14:00:00Z")
    complete_visit(visit["id"], ["INT_WALK"], [], interior_temp_f=48.0)

    data = validate_success(api.get_risk_posture(ctx["property_id"], ctx["owner_headers"]))
    assert data["freeze_risk_score"] == 82.0
    assert data["risk_posture"] == "CRITICAL"
    assert data["winterization_completeness_pct"] == 0.0
    assert data["open_critical_finding_count"] == 0
    assert data["false_alarm_count_window"] == 0
    assert data["last_interior_temp_f"] == 48.0


# --------------------------------------------------------------------------
# A live visit blocks the commercial edges
# --------------------------------------------------------------------------

def test_subscription_cannot_be_cancelled_while_a_visit_is_en_route(api):
    """PRD 3.2: "A subscription may be cancelled from `ACTIVE`, from `PAUSED` or from
    `DELINQUENT`, and in all three cases the precondition is the same: no visit on the
    property may be `EN_ROUTE` or `IN_PROGRESS`, a live visit being rejected with
    `ERR_VISIT_IN_FLIGHT`."

    Design: Corner/errors/err_visit_in_flight_blocks_subscription_cancel_returns_409
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    visit = new_visit(ctx["property_id"], template["id"])
    set_clock("2026-06-02T13:30:00Z")
    validate_success(api.depart_visit(visit["id"], {}, FIELD_TECH))
    assert refresh_visit(visit["id"])["status"] == "EN_ROUTE"

    response = api.cancel_subscription(ctx["subscription_id"], {}, ACCOUNT_MANAGER)
    validate_error(response, ApiErrorId.ERR_VISIT_IN_FLIGHT.value)
    subscription = refresh_subscription(ctx["subscription_id"])
    assert subscription["status"] == "ACTIVE"
    assert subscription["cancelled_at"] is None
    assert refresh_cycle(ctx["cycle_id"])["status"] == "OPEN"
