"""Exact boundaries: equality on a ceiling, equality on a threshold, and an empty pool."""

from test_helpers import (
    ASSIGN_ASSIGNED,
    ASSIGN_INSPECTED_PASS,
    ASSIGN_RECLEAN_REQUIRED,
    CLEAN_INSPECTED_PASS,
    CLEAN_RECLEAN_REQUIRED,
    COMPLIANCE_AT_LIMIT,
    COMPLIANCE_BREACH_BLOCKED,
    COMPLIANCE_COMPLIANT,
    INSPECTION_FAIL,
    INSPECTION_PASS,
    ORDINANCE_NONE,
    SERVICE_CHECKOUT,
    SERVICE_DEEP_CLEAN,
    assert_credits,
    assert_is_null,
    assert_score_pct,
    build_scenario,
    read_assignment,
    read_room,
    read_roster,
    read_sample_plan,
    validate_success,
)


def _one_deep_clean_of_two(api):
    """A 4.00-credit ceiling with one 2.00-credit deep clean already allocated."""
    scenario = build_scenario(
        api,
        property_overrides={
            "ordinance_profile": ORDINANCE_NONE,
            "max_daily_credits": 4.00,
        },
        rooms=["103", "104"],
        linen={"total_owned_sets": 20},
    )
    scenario.assign("103", SERVICE_DEEP_CLEAN)
    return scenario


def test_credits_landing_exactly_on_the_cap_are_accepted_and_report_at_limit(api):
    """The second deep clean lands exactly on 4.00 credits and is admitted at the limit.

    PRD 3.4: "Landing exactly on the cap is permitted and moves the roster's
    compliance dimension `COMPLIANT → AT_LIMIT`; only exceeding it is refused."

    Design: Difficulty/boundary_precision_check/assigned_credits_exactly_equal_to_cap_lands_at_limit_and_is_accepted
    """
    scenario = _one_deep_clean_of_two(api)

    response = scenario.assign_raw(
        "104", SERVICE_DEEP_CLEAN, headers=scenario.supervisor_headers()
    )

    assignment = validate_success(response, 201)
    assert assignment["status"] == ASSIGN_ASSIGNED
    assert_credits(assignment["credits"], 2.00, "assignment credits")
    roster = read_roster(api, scenario.roster_id)
    assert_credits(roster["assigned_credits"], 4.00, "assigned_credits")
    assert_credits(roster["effective_credit_cap"], 4.00, "effective_credit_cap")
    assert roster["compliance_state"] == COMPLIANCE_AT_LIMIT, (
        f"equality must land on AT_LIMIT, got {roster['compliance_state']}"
    )
    assert roster["compliance_state"] != COMPLIANCE_BREACH_BLOCKED
    assert roster["compliance_state"] != COMPLIANCE_COMPLIANT


def test_no_square_foot_ceiling_applies_under_the_none_ordinance_profile(api):
    """With no square-foot ceiling in force, 840 cleaned square feet decide nothing.

    PRD 2.8: "`effective_sqft_cap` is `Property.max_daily_square_feet` when the
    property's `ordinance_profile` is `SQFT_CAP_2200`, and is null under the
    `NONE` and `CREDIT_CAP_STRICT` profiles, in which case no square-foot ceiling
    applies at all."

    Design: Difficulty/boundary_precision_check/assigned_credits_exactly_equal_to_cap_lands_at_limit_and_is_accepted
    """
    scenario = _one_deep_clean_of_two(api)

    scenario.assign("104", SERVICE_DEEP_CLEAN, headers=scenario.supervisor_headers())

    roster = read_roster(api, scenario.roster_id)
    assert_is_null(roster["effective_sqft_cap"], "effective_sqft_cap")
    assert roster["assigned_square_feet"] == 840, (
        f"assigned_square_feet should be 840, got {roster['assigned_square_feet']}"
    )
    assert roster["compliance_state"] == COMPLIANCE_AT_LIMIT


def _two_departure_cleans(api):
    """Two departure cleans finished by one attendant on separate rooms."""
    scenario = build_scenario(
        api,
        rooms=[
            {"number": "101", "occupancy_state": "DUE_OUT"},
            {"number": "102", "occupancy_state": "DUE_OUT"},
        ],
        linen={"total_owned_sets": 20},
    )
    first = scenario.clean(
        "101",
        SERVICE_CHECKOUT,
        "2026-08-03T10:00:00.000Z",
        "2026-08-03T10:30:00.000Z",
    )
    second = scenario.clean(
        "102",
        SERVICE_CHECKOUT,
        "2026-08-03T10:50:00.000Z",
        "2026-08-03T11:20:00.000Z",
    )
    return scenario, first, second


def test_score_exactly_at_the_reclean_threshold_passes(api):
    """Item scores of 9, 8, 8, 8 and 10 give exactly 85.0 and pass at the boundary.

    PRD 3.6: "Under the default threshold of 85.0, item scores of 9, 8, 8, 8 and
    10 give a score of 85.0 and pass at the exact boundary; the same set with 9
    instead of 10 on the floor item gives 84.0 and fails; and 6, 10, 10, 10, 10
    gives 88.0, comfortably above the threshold, yet fails anyway on the
    critical-item rule."

    Design: Difficulty/boundary_precision_check/quality_score_exactly_at_reclean_threshold_passes_while_one_tenth_below_fails
    """
    scenario, first, _ = _two_departure_cleans(api)

    inspection = scenario.inspect(
        first["id"],
        bathroom_points=9,
        linen_points=8,
        dust_points=8,
        amenity_points=8,
        floor_points=10,
    )

    assert_score_pct(inspection["score_pct"], 85.0)
    assert inspection["critical_fail"] is False
    assert inspection["result"] == INSPECTION_PASS
    assert read_assignment(api, first["id"])["status"] == ASSIGN_INSPECTED_PASS
    assert read_room(api, scenario.room_id("101"))["cleanliness_status"] == (
        CLEAN_INSPECTED_PASS
    )


def test_score_one_tenth_below_the_threshold_fails(api):
    """The same item set with 9 on the floor gives 84.0 and condemns the clean.

    PRD 3.6: "The `result` is then `FAIL` when `critical_fail` is true, or when
    `score_pct` is strictly below the property's `reclean_threshold_score`, and
    `PASS` otherwise; the pass comparison is inclusive, so a score exactly equal
    to the threshold passes."

    Design: Difficulty/boundary_precision_check/quality_score_exactly_at_reclean_threshold_passes_while_one_tenth_below_fails
    """
    scenario, _, second = _two_departure_cleans(api)

    inspection = scenario.inspect(
        second["id"],
        bathroom_points=9,
        linen_points=8,
        dust_points=8,
        amenity_points=8,
        floor_points=9,
    )

    assert_score_pct(inspection["score_pct"], 84.0)
    assert inspection["critical_fail"] is False, (
        "no item score is at or below 6, so this is a threshold failure only"
    )
    assert inspection["result"] == INSPECTION_FAIL
    assert read_assignment(api, second["id"])["status"] == ASSIGN_RECLEAN_REQUIRED
    assert read_room(api, scenario.room_id("102"))["cleanliness_status"] == (
        CLEAN_RECLEAN_REQUIRED
    )


def _roster_without_work(api):
    """A clocked-in roster that has been given no rooms at all."""
    return build_scenario(api, rooms=["101"], linen={"total_owned_sets": 20})


def test_sampling_plan_on_an_empty_pool_owes_no_samples(api):
    """With nothing performed the obligation is zero, not the floor of one.

    PRD 3.6: "When the performed count is zero the obligation is zero."

    Design: Difficulty/boundary_precision_check/sampling_plan_on_empty_eligible_pool_reports_zero_samples_and_empty_selection
    """
    scenario = _roster_without_work(api)

    plan = validate_success(
        api.get_sample_plan(scenario.roster_id, scenario.supervisor_headers()), 200
    )

    assert plan["roster_id"] == scenario.roster_id
    assert plan["completed_count"] == 0
    assert plan["sample_rate"] == 0.20, (
        f"the baseline sampling rate should be 0.20, got {plan['sample_rate']}"
    )
    assert plan["required_samples"] == 0, (
        f"required_samples should be 0, got {plan['required_samples']}"
    )
    assert plan["remaining_samples"] == 0


def test_sampling_plan_on_an_empty_pool_returns_an_empty_selection(api):
    """The selection list comes back empty rather than null, with no error.

    PRD 3.6: "When the pool is empty the list comes back empty with no error, and
    `required_samples` is still reported so the caller can see the outstanding
    obligation."

    Design: Difficulty/boundary_precision_check/sampling_plan_on_empty_eligible_pool_reports_zero_samples_and_empty_selection
    """
    scenario = _roster_without_work(api)

    plan = read_sample_plan(api, scenario.roster_id)

    assert plan["selected_assignment_ids"] == [], (
        f"selected_assignment_ids should be an empty list, got "
        f"{plan['selected_assignment_ids']!r}"
    )
    roster = read_roster(api, scenario.roster_id)
    assert roster["required_inspection_samples"] == 0
    assert roster["inspections_completed"] == 0
