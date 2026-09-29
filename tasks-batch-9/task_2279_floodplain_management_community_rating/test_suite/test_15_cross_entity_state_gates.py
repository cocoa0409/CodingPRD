"""Cross-entity state gates.

Each test drives one write whose admission depends on the state of a *different*
aggregate — the community's enforcement posture, the referenced recertification
cycle, or the structure's determination history — and contrasts the refused
branch with the branch the PRD permits.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_days_after,
    assert_sanction_state,
    determine_case,
    draft_standard,
    open_case,
    open_cycle,
    raise_community_to_probation,
    read_area,
    read_community,
    read_permit,
    read_structure,
    review_permit,
    setup_approved_permit,
    setup_designated_area,
    setup_determined_case,
    setup_permit_under_review,
    setup_structure,
    start_permit,
    submit_cycle,
    submit_permit,
    submit_standard,
    validate_error,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["administrator_headers"]

_STRUCTURE_OVERRIDES = {
    "structure_use": "RESIDENTIAL",
    "pre_firm": True,
    "construction_year": 1966,
    "market_value_usd": 200_000.00,
    "highest_adjacent_grade_ft": 10.0,
}


# ==========================================================================
# Permit issuance reads the community's posture AND the structure's axis
# ==========================================================================

def test_probation_blocks_issuance_for_a_substantial_structure(api):
    """PRD §3.4: "A community merely `ON_PROBATION` may still issue permits for
    ordinary structures, but not for a structure whose `substantial_status` is
    anything other than `NONE` (`ERR_COMMUNITY_ON_PROBATION`)."

    PRD §3.8: "The tier rule is inclusive on the worse side: a score of 25 points
    or more is `SUSPENDED`, a score of 10 points or more is `ON_PROBATION`, and
    anything lower is `GOOD_STANDING`."

    Design: Difficulty/cross_entity_state_dependency/permit_issue_blocked_by_probation_only_for_substantial_structure
    """
    scenario = setup_determined_case(
        records=[{"record_type": "IMPROVEMENT", "event_date": "2026-04-01T00:00:00Z",
                  "cost_usd": 120_000.00}],
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides=dict(_STRUCTURE_OVERRIDES),
    )
    structure = read_structure(scenario["structure"]["id"])
    assert structure["substantial_status"] == "SUBSTANTIAL_IMPROVEMENT", (
        "A SUBSTANTIAL outcome sets the structure's substantial_status to the "
        f"case's determination_type, got {structure['substantial_status']}"
    )

    permit = start_permit(
        scenario["property"]["id"], scenario["structure"]["id"], scenario["owner_headers"],
        project_type="IMPROVEMENT", declared_project_cost_usd=20_000.00,
        proposed_lowest_floor_elevation_ft=20.0,
    )
    permit = submit_permit(permit["id"], scenario["owner_headers"])
    permit = review_permit(permit["id"], "APPROVE")
    assert float(permit["required_lowest_floor_elevation_ft"]) == 14.0
    assert permit["status"] == "APPROVED"

    raise_community_to_probation(scenario["property"]["id"])
    assert_sanction_state(read_community(scenario["community"]["id"]), 12, "ON_PROBATION")

    response = api.issue_permit(permit["id"], ADMIN_HEADERS)
    validate_error(response, ApiErrorId.ERR_COMMUNITY_ON_PROBATION)

    after = read_permit(permit["id"])
    assert after["status"] == "APPROVED"
    assert after.get("issued_at") is None
    assert float(after["required_lowest_floor_elevation_ft"]) == 14.0
    assert read_structure(scenario["structure"]["id"])["substantial_status"] == (
        "SUBSTANTIAL_IMPROVEMENT"
    )


def test_probation_still_issues_for_an_ordinary_structure(api):
    """PRD §3.4: "A community merely `ON_PROBATION` may still issue permits for
    ordinary structures, but not for a structure whose `substantial_status` is
    anything other than `NONE` (`ERR_COMMUNITY_ON_PROBATION`)."

    PRD §3.4: "Issuance moves the permit to `ISSUED`, stamps `issued_at` with the
    current logical clock, and sets `expires_at` to 365 days after `issued_at`."

    Design: Difficulty/cross_entity_state_dependency/permit_issue_blocked_by_probation_only_for_substantial_structure
    """
    scenario = setup_approved_permit(
        permit_overrides={"project_type": "NEW_CONSTRUCTION",
                          "declared_project_cost_usd": 20_000.00,
                          "proposed_lowest_floor_elevation_ft": 20.0},
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides=dict(_STRUCTURE_OVERRIDES),
    )
    assert read_structure(scenario["structure"]["id"])["substantial_status"] == "NONE"

    raise_community_to_probation(scenario["property"]["id"])
    assert_sanction_state(read_community(scenario["community"]["id"]), 12, "ON_PROBATION")

    response = api.issue_permit(scenario["permit"]["id"], ADMIN_HEADERS)
    permit = validate_success(response, 200)

    assert permit["status"] == "ISSUED"
    assert permit["issued_at"] is not None
    assert_days_after(permit["expires_at"], permit["issued_at"], 365, "expires_at")
    assert_sanction_state(read_community(scenario["community"]["id"]), 12, "ON_PROBATION")


# ==========================================================================
# Outreach launch reads the referenced recertification cycle's status
# ==========================================================================

def test_outreach_launch_refused_when_referenced_cycle_left_open(api):
    """PRD §3.9: "The `crs_cycle_id` supplied in the payload must name a cycle of
    the same community, else `ERR_CYCLE_COMMUNITY_MISMATCH`, and that cycle's
    `status` must be `OPEN`, else `ERR_CYCLE_NOT_OPEN`."

    PRD §2.8: "launching outreach requires the referenced cycle's `status` to be
    `OPEN`, else `ERR_CYCLE_NOT_OPEN`"

    Design: Difficulty/cross_entity_state_dependency/outreach_launch_requires_referenced_cycle_to_be_open
    """
    scenario = setup_designated_area(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
    )
    area = read_area(scenario["area"]["id"])
    assert area["status"] == "DESIGNATED"
    assert area["analysis_status"] == "ANALYZED"
    assert area["property_count"] == 1

    standard = draft_standard(
        scenario["community"]["id"], activity_code="A420_OPEN_SPACE",
        documentation_cycle_year=2026, claimed_points=50,
    )
    submit_standard(standard["id"])
    cycle = open_cycle(
        scenario["community"]["id"], cycle_year=2026,
        cycle_start_date="2026-01-01T00:00:00Z", cycle_end_date="2026-12-31T00:00:00Z",
        due_at="2026-09-30T00:00:00Z",
    )
    cycle = submit_cycle(cycle["id"])
    assert cycle["status"] == "SUBMITTED"

    response = api.launch_outreach(
        area["id"], {"crs_cycle_id": cycle["id"], "target_property_count": 12}, ADMIN_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_CYCLE_NOT_OPEN)

    after = read_area(area["id"])
    assert after["outreach_status"] == "NOT_STARTED"
    assert after["outreach_crs_cycle_id"] is None
    assert after["target_property_count"] == 0
    assert after["status"] == "DESIGNATED"
    assert after["analysis_status"] == "ANALYZED"
    assert after["property_count"] == 1


def test_outreach_launch_succeeds_against_an_open_cycle(api):
    """PRD §3.9: "The `crs_cycle_id` supplied in the payload must name a cycle of
    the same community, else `ERR_CYCLE_COMMUNITY_MISMATCH`, and that cycle's
    `status` must be `OPEN`, else `ERR_CYCLE_NOT_OPEN`."

    PRD §3.9: "A launch moves `outreach_status` to `IN_PROGRESS`, resets
    `delivered_count` to 0 and `coverage_pct` to 0, and snapshots
    `target_property_count` from the payload together with `outreach_crs_cycle_id`
    and `outreach_cycle_year` from the referenced cycle."

    Design: Difficulty/cross_entity_state_dependency/outreach_launch_requires_referenced_cycle_to_be_open
    """
    scenario = setup_designated_area(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
    )
    cycle = open_cycle(
        scenario["community"]["id"], cycle_year=2026,
        cycle_start_date="2026-01-01T00:00:00Z", cycle_end_date="2026-12-31T00:00:00Z",
        due_at="2026-09-30T00:00:00Z",
    )
    assert cycle["status"] == "OPEN"

    response = api.launch_outreach(
        scenario["area"]["id"],
        {"crs_cycle_id": cycle["id"], "target_property_count": 12},
        ADMIN_HEADERS,
    )
    area = validate_success(response, 200)

    assert area["outreach_status"] == "IN_PROGRESS"
    assert area["outreach_crs_cycle_id"] == cycle["id"]
    assert area["outreach_cycle_year"] == 2026
    assert area["target_property_count"] == 12
    assert area["delivered_count"] == 0
    assert float(area["coverage_pct"]) == 0.00
    assert area["status"] == "DESIGNATED"
    assert area["analysis_status"] == "ANALYZED"


# ==========================================================================
# Permit approval reads the structure's determination case history
# ==========================================================================

def test_approval_refused_at_exactly_fifty_percent_without_any_case(api):
    """PRD §3.4: "The substantial-improvement gate applies when `project_type` is
    `IMPROVEMENT` or `REPAIR` and the single-event ratio of
    `declared_project_cost_usd` to the structure's `market_value_usd`, expressed as
    a percentage, reaches 50 percent or more: in that case the structure must
    already carry a `DeterminationCase` whose `status` is `DETERMINED`,
    `APPEAL_SUSTAINED`, or `APPEAL_DENIED`, and if it does not the approval is
    refused with `ERR_DETERMINATION_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/permit_approval_requires_resolved_determination_case
    """
    scenario = setup_permit_under_review(
        permit_overrides={"project_type": "IMPROVEMENT",
                          "declared_project_cost_usd": 100_000.00,
                          "proposed_lowest_floor_elevation_ft": 20.0},
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides=dict(_STRUCTURE_OVERRIDES, construction_year=1959),
    )
    assert float(scenario["permit"]["required_lowest_floor_elevation_ft"]) == 13.5

    response = api.review_permit(
        scenario["permit"]["id"], {"decision": "APPROVE"}, ADMIN_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_DETERMINATION_REQUIRED)

    after = read_permit(scenario["permit"]["id"])
    assert after["status"] == "UNDER_REVIEW"
    assert after["si_determination_case_id"] is None
    assert float(after["required_lowest_floor_elevation_ft"]) == 13.5
    assert read_structure(scenario["structure"]["id"])["substantial_status"] == "NONE"


def test_approval_permitted_once_a_determined_case_exists(api):
    """PRD §3.4: "The substantial-improvement gate applies when `project_type` is
    `IMPROVEMENT` or `REPAIR` and the single-event ratio of
    `declared_project_cost_usd` to the structure's `market_value_usd`, expressed as
    a percentage, reaches 50 percent or more: in that case the structure must
    already carry a `DeterminationCase` whose `status` is `DETERMINED`,
    `APPEAL_SUSTAINED`, or `APPEAL_DENIED`, and if it does not the approval is
    refused with `ERR_DETERMINATION_REQUIRED`."

    PRD §3.4: "On a successful approval the permit becomes `APPROVED` and
    `si_determination_case_id` records the newest resolved case of the structure,
    ordered by `determined_at` descending and then by `created_at` descending, or
    null when no determination was required."

    Design: Difficulty/cross_entity_state_dependency/permit_approval_requires_resolved_determination_case
    """
    scenario = setup_structure(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides=dict(_STRUCTURE_OVERRIDES, construction_year=1959),
    )
    case = determine_case(open_case(scenario["structure"]["id"], method="CUMULATIVE")["id"])
    assert case["status"] == "DETERMINED"
    assert read_structure(scenario["structure"]["id"])["substantial_status"] == "NONE"

    permit = start_permit(
        scenario["property"]["id"], scenario["structure"]["id"], scenario["owner_headers"],
        project_type="IMPROVEMENT", declared_project_cost_usd=100_000.00,
        proposed_lowest_floor_elevation_ft=20.0,
    )
    permit = submit_permit(permit["id"], scenario["owner_headers"])
    assert float(permit["required_lowest_floor_elevation_ft"]) == 13.5

    response = api.review_permit(permit["id"], {"decision": "APPROVE"}, ADMIN_HEADERS)
    approved = validate_success(response, 200)

    assert approved["status"] == "APPROVED"
    assert approved["si_determination_case_id"] == case["id"]
    assert float(approved["required_lowest_floor_elevation_ft"]) == 13.5


def test_approval_below_fifty_percent_needs_no_case_at_all(api):
    """PRD §3.4: "The substantial-improvement gate applies when `project_type` is
    `IMPROVEMENT` or `REPAIR` and the single-event ratio of
    `declared_project_cost_usd` to the structure's `market_value_usd`, expressed as
    a percentage, reaches 50 percent or more: in that case the structure must
    already carry a `DeterminationCase` whose `status` is `DETERMINED`,
    `APPEAL_SUSTAINED`, or `APPEAL_DENIED`, and if it does not the approval is
    refused with `ERR_DETERMINATION_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/permit_approval_requires_resolved_determination_case
    """
    scenario = setup_permit_under_review(
        permit_overrides={"project_type": "IMPROVEMENT",
                          "declared_project_cost_usd": 99_980.00,
                          "proposed_lowest_floor_elevation_ft": 20.0},
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides=dict(_STRUCTURE_OVERRIDES, construction_year=1959),
    )

    response = api.review_permit(
        scenario["permit"]["id"], {"decision": "APPROVE"}, ADMIN_HEADERS
    )
    approved = validate_success(response, 200)

    assert approved["status"] == "APPROVED"
    assert approved["si_determination_case_id"] is None
    assert float(approved["required_lowest_floor_elevation_ft"]) == 13.5
