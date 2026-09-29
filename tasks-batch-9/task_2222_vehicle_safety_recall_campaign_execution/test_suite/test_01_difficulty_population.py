"""
Population derivation from build records: the two bounding conventions and the
overlap rule that governs INCLUDE windows.
"""

from test_helpers import (
    ApiErrorId,
    assert_population_rule,
    factories as f,
    fixtures as fx,
    read_list,
    validate_error,
    validate_success,
)
from test_helpers.test_users import SAFETY_ENGINEER_1

# The three build records that straddle the default rule's boundaries.
BUILD_INSIDE_WINDOW = {
    "vin": "1HGCM82633A004352",
    "production_date": "2024-06-30",
    "suspect_part_number": 1500,
    "owner_name": "Last In Window",
}
BUILD_ON_END_DATE = {
    "vin": "1HGCM82633A004353",
    "production_date": "2024-07-01",
    "suspect_part_number": 1500,
    "owner_name": "On End Date",
}
BUILD_ON_LOW_PART = {
    "vin": "1HGCM82633A004354",
    "production_date": "2024-03-01",
    "suspect_part_number": 1000,
    "owner_name": "Low Part Boundary",
}


def _population_at_the_boundaries(api):
    """One campaign, one INCLUDE rule, and three builds sitting on its edges."""
    return fx.campaign_with_population(
        api,
        vehicles=[BUILD_INSIDE_WINDOW, BUILD_ON_END_DATE, BUILD_ON_LOW_PART],
    )


def test_population_run_counts_only_the_builds_inside_the_half_open_window(api):
    """
    The matching pass reports two matches, not three: the build on the window's
    end date is outside a half-open window while the build sitting exactly on
    `part_number_low` is inside a closed part range.

    PRD §3.2: "**the build window is half-open**, so a vehicle matches when its
    `production_date` is on or after `production_start_date` and strictly before
    `production_end_date`".

    PRD §3.2: "**the part range is closed**, so a vehicle matches when its
    `suspect_part_number` is greater than or equal to `part_number_low` and less
    than or equal to `part_number_high`".

    Design: Difficulty/boundary_precision_check/population_match_excludes_build_on_production_end_date_boundary
    """
    state = _population_at_the_boundaries(api)
    run = state["population_run"]

    assert run["matched_count"] == 2, (
        "the 2024-06-30 and part-1000 builds match; the 2024-07-01 build does not"
    )
    assert run["excluded_count"] == 0
    assert run["removed_count"] == 0
    assert run["affected_vehicle_count"] == 2
    assert run["recall_population_count"] == 2


def test_build_on_the_production_end_date_gets_no_affected_vehicle_row(api):
    """
    Only the two matching builds receive affected-vehicle rows, the rule is
    credited with exactly those two, and the campaign's own counter agrees.

    PRD §3.2: "**the build window is half-open**, so a vehicle matches when its
    `production_date` is on or after `production_start_date` and strictly before
    `production_end_date`".

    PRD §3.2: "The run then refreshes the campaign's `affected_vehicle_count` to
    the total number of affected-vehicle rows in any status".

    Design: Difficulty/boundary_precision_check/population_match_excludes_build_on_production_end_date_boundary
    """
    state = _population_at_the_boundaries(api)
    campaign_id = state["campaign_id"]
    inside, edge, low_part = state["vehicles"]

    _, meta_edge = read_list(
        api.list_affected_vehicles(
            SAFETY_ENGINEER_1, {"campaign_id": campaign_id, "vehicle_id": edge["id"]}
        ),
        expected_total=0,
    )
    assert meta_edge["total_count"] == 0

    for vehicle in (inside, low_part):
        read_list(
            api.list_affected_vehicles(
                SAFETY_ENGINEER_1, {"campaign_id": campaign_id, "vehicle_id": vehicle["id"]}
            ),
            expected_total=1,
        )

    rules, _ = read_list(
        api.list_population_rules(campaign_id, SAFETY_ENGINEER_1), expected_total=1
    )
    assert rules[0]["matched_vehicle_count"] == 2

    campaign = fx.read_campaign(api, campaign_id)
    assert campaign["affected_vehicle_count"] == 2
    assert campaign["recall_population_count"] == 2


def test_include_rule_starting_on_a_siblings_end_date_is_accepted(api):
    """
    A second INCLUDE rule for the same plant, model and year whose
    `production_start_date` equals the first rule's `production_end_date` merely
    touches it, so it is accepted.

    PRD §3.2: "because the windows are half-open, windows that merely touch —
    where the existing rule's `production_end_date` equals the new rule's
    `production_start_date` — do not intersect and are permitted, while any
    genuine overlap is rejected with `ERR_POPULATION_RULE_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/population_rule_half_open_window_allows_touch_rejects_intersection
    """
    state = fx.draft_campaign(api)
    campaign_id = state["campaign_id"]
    rule_a = fx.add_population_rule(api, campaign_id)

    response = api.create_population_rule(
        campaign_id,
        f.population_rule_payload(
            production_start_date="2024-07-01", production_end_date="2025-01-01"
        ),
        SAFETY_ENGINEER_1,
    )
    rule_b = validate_success(response, 201)
    assert_population_rule(rule_b)
    assert rule_b["production_start_date"] == rule_a["production_end_date"] == "2024-07-01"
    assert rule_b["production_end_date"] == "2025-01-01"
    assert rule_b["matched_vehicle_count"] == 0

    read_list(api.list_population_rules(campaign_id, SAFETY_ENGINEER_1), expected_total=2)


def test_include_rule_intersecting_a_sibling_window_is_refused(api):
    """
    A third INCLUDE rule whose window genuinely intersects an existing one is
    refused, and the rule it collided with keeps its original window.

    PRD §3.2: "Two `INCLUDE` rules with the same `plant_code`, `model_code` and
    `model_year` may not have intersecting half-open build windows".

    PRD §3.2: "while any genuine overlap is rejected with
    `ERR_POPULATION_RULE_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/population_rule_half_open_window_allows_touch_rejects_intersection
    """
    state = fx.draft_campaign(api)
    campaign_id = state["campaign_id"]
    rule_a = fx.add_population_rule(api, campaign_id)
    fx.add_population_rule(
        api,
        campaign_id,
        production_start_date="2024-07-01",
        production_end_date="2025-01-01",
    )

    response = api.create_population_rule(
        campaign_id,
        f.population_rule_payload(
            production_start_date="2024-06-15", production_end_date="2024-09-01"
        ),
        SAFETY_ENGINEER_1,
    )
    validate_error(response, ApiErrorId.POPULATION_RULE_OVERLAP, 409)

    rules, _ = read_list(
        api.list_population_rules(campaign_id, SAFETY_ENGINEER_1), expected_total=2
    )
    stored_a = next(r for r in rules if r["id"] == rule_a["id"])
    assert stored_a["production_end_date"] == "2024-07-01"
    assert stored_a["production_start_date"] == "2024-01-01"
