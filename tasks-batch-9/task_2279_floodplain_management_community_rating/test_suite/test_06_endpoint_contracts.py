"""Endpoint contract tests.

Each test builds its own communities, panels, parcels, structures, permits and
ledger rows from scratch through the endpoints the PRD declares, then exercises
one endpoint contract: the non-retroactive standards amendment, the
post-disaster sweep, the two computed reads, the logical clock, the outreach
launch link step, and determination-case supersession.
"""
import pytest

from test_helpers import (
    ADMINISTRATOR,
    CLOCK_START_UTC,
    COORDINATOR,
    add_property,
    add_structure,
    determine_case,
    get_success_data,
    issue_violation,
    open_case,
    open_cycle,
    parse_instant,
    read_community,
    read_permit,
    read_structure,
    register_community,
    setup_designated_area,
    setup_issued_permit,
    setup_ledger,
    setup_structure,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------
# Module-private builders
# --------------------------------------------------------------------------

def _activate_zone_x_panel(api, community_id, panel_number="48001C0300"):
    """File and activate a panel mapped flood zone X, with no base flood
    elevation supplied at filing."""
    panel = get_success_data(
        api.file_firm_panel(
            {
                "community_id": community_id,
                "panel_number": panel_number,
                "suffix": "H",
                "flood_zone": "X",
                "effective_date": "2020-01-01T00:00:00Z",
            },
            COORDINATOR,
        )
    )
    return get_success_data(api.activate_firm_panel(panel["id"], COORDINATOR))


# --------------------------------------------------------------------------
# Communities
# --------------------------------------------------------------------------

def test_standards_amendment_leaves_an_issued_permit_on_its_snapshot(api):
    """PRD §3.1: "What the amendment deliberately does *not* touch is existing
    permits: each permit keeps the `freeboard_applied_ft` it snapshotted at
    submit, and no permit requirement is recomputed by a standards amendment."

    PRD §3.1: "The amendment restamps `standards_adopted_at` to the current
    logical clock and increments the community's `version`."

    Design: Corner/endpoints/patch_of_adopted_standards_leaves_issued_permits_on_their_snapshot
    """
    scenario = setup_issued_permit(
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 20_000.00,
            "proposed_lowest_floor_elevation_ft": 20.0,
        },
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
    )
    permit_id = scenario["permit"]["id"]

    response = api.amend_community_standards(
        scenario["community"]["id"], {"freeboard_ft": 2.5}, ADMINISTRATOR
    )

    community = validate_success(response, 200)
    assert float(community["freeboard_ft"]) == pytest.approx(2.5, abs=0.01)
    assert int(community["cumulative_period_years"]) == 10
    assert parse_instant(community["standards_adopted_at"]) == parse_instant(CLOCK_START_UTC)
    assert community["version"] == 2

    permit = read_permit(permit_id)
    assert float(permit["freeboard_applied_ft"]) == pytest.approx(1.5, abs=0.01)
    assert float(permit["required_lowest_floor_elevation_ft"]) == pytest.approx(13.5, abs=0.01)
    assert permit["status"] == "ISSUED"


def test_sweep_without_eligible_structures_creates_no_inspection(api):
    """PRD §3.7: "Eligibility is a conjunction: a property must belong to this
    community *and* its governing panel's `status` must be `EFFECTIVE` *and*
    that panel's `flood_zone` must be one of `A`, `AE`, `AO`, or `VE`."

    PRD §3.7: "The sweep response reports the `declaration_code`, the
    `event_date`, the computed `deadline_at`, the `inspections_created` count,
    and the `inspection_ids` that were created; when the eligible set is empty
    the count is 0 and the identifier list is empty."

    Design: Corner/endpoints/sweep_of_a_community_without_eligible_structures_creates_nothing
    """
    community = register_community(freeboard_ft=1.5, cumulative_period_years=10)
    panel_x = _activate_zone_x_panel(api, community["id"])
    dry_parcel = add_property(community["id"], panel_x["id"], mapped_area_code="RLA-9")
    dry_structure = add_structure(
        dry_parcel["id"], pre_firm=False, construction_year=2001,
        market_value_usd=150_000.00, highest_adjacent_grade_ft=30.0,
    )

    response = api.open_inspection_sweep(
        community["id"],
        {
            "declaration_code": "DR-4801",
            "event_date": "2026-07-15T00:00:00Z",
            "inspection_window_days": 30,
        },
        ADMINISTRATOR,
    )

    sweep = validate_success(response, 201)
    assert sweep["inspections_created"] == 0
    assert sweep["inspection_ids"] == []
    assert parse_instant(sweep["deadline_at"]) == parse_instant("2026-08-14T00:00:00Z")

    assert read_structure(dry_structure["id"])["compliance_status"] == "PENDING_CERTIFICATE"


def test_sweep_schedules_one_inspection_per_structure_of_the_hazard_parcel(api):
    """PRD §3.7: "Every `Structure` of every eligible property is swept in
    ascending `created_at` order, and each produces one
    `PostDisasterInspection` with `status` `SCHEDULED`, the sweep's
    `declaration_code`, `disaster_event_date` equal to the sweep's
    `event_date`, and `deadline_at` equal to that date plus
    `inspection_window_days`."

    PRD §3.7: "Eligibility is a conjunction: a property must belong to this
    community *and* its governing panel's `status` must be `EFFECTIVE` *and*
    that panel's `flood_zone` must be one of `A`, `AE`, `AO`, or `VE`."

    Design: Corner/endpoints/sweep_schedules_both_structures_of_the_hazard_area_property
    """
    scenario = setup_structure(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
    )
    community_id = scenario["community"]["id"]
    structure_a = scenario["structure"]
    structure_b = add_structure(
        scenario["property"]["id"], structure_use="NON_RESIDENTIAL", pre_firm=True,
        construction_year=1971, market_value_usd=90_000.00,
        highest_adjacent_grade_ft=10.0,
    )
    panel_x = _activate_zone_x_panel(api, community_id)
    dry_parcel = add_property(community_id, panel_x["id"], mapped_area_code="RLA-9")
    dry_structure = add_structure(
        dry_parcel["id"], pre_firm=False, construction_year=2001,
        market_value_usd=150_000.00, highest_adjacent_grade_ft=30.0,
    )

    response = api.open_inspection_sweep(
        community_id,
        {
            "declaration_code": "DR-4801",
            "event_date": "2026-07-15T00:00:00Z",
            "inspection_window_days": 30,
        },
        ADMINISTRATOR,
    )

    sweep = validate_success(response, 201)
    assert sweep["inspections_created"] == 2
    assert len(sweep["inspection_ids"]) == 2

    inspections = [
        validate_success(api.get_inspection(inspection_id, ADMINISTRATOR), 200)
        for inspection_id in sweep["inspection_ids"]
    ]
    assert [inspection["structure_id"] for inspection in inspections] == [
        structure_a["id"], structure_b["id"]
    ]
    for inspection in inspections:
        assert inspection["status"] == "SCHEDULED"
        assert inspection["declaration_code"] == "DR-4801"
        assert parse_instant(inspection["deadline_at"]) == parse_instant("2026-08-14T00:00:00Z")
        assert parse_instant(inspection["disaster_event_date"]) == parse_instant(
            "2026-07-15T00:00:00Z"
        )

    dry_rows, dry_meta = validate_paginated(
        api.list_inspections(ADMINISTRATOR, params={"structure_id": dry_structure["id"]})
    )
    assert dry_meta["total_count"] == 0
    assert dry_rows == []


def test_compliance_summary_reports_the_probation_tier_it_computes(api):
    """PRD §3.1: "A computed compliance summary is available to the
    `StateNfipCoordinator` and the `FloodplainAdministrator` and reports the
    community's enforcement and rating posture in one payload: `community_id`,
    the current `sanction_risk_points` and `compliance_posture`, the
    `counted_violation_count` of violations currently inside the counted set,
    the `defaulted_order_count` of defaulted orders currently carrying a
    penalty, the `a510_credit_applied` value actually subtracted by the
    probation credit rule, and the rating figures `crs_class`,
    `crs_credit_points_claimed`, `crs_credit_points_verified`, `freeboard_ft`,
    and `cumulative_period_years`."

    PRD §3.8: "The tier rule is inclusive on the worse side: a score of 25
    points or more is `SUSPENDED`, a score of 10 points or more is
    `ON_PROBATION`, and anything lower is `GOOD_STANDING`."

    Design: Corner/endpoints/compliance_summary_reports_the_probation_tier_it_computes
    """
    scenario = setup_structure(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
    )
    community_id = scenario["community"]["id"]
    property_id = scenario["property"]["id"]
    issue_violation(property_id, violation_type="MISSING_CERTIFICATE", severity="MINOR")
    issue_violation(property_id, violation_type="NO_PERMIT", severity="CRITICAL")

    response = api.get_compliance_summary(community_id, ADMINISTRATOR)

    summary = validate_success(response, 200)
    assert summary["community_id"] == community_id
    assert summary["sanction_risk_points"] == 14
    assert summary["compliance_posture"] == "ON_PROBATION"
    assert summary["counted_violation_count"] == 2
    assert summary["defaulted_order_count"] == 0
    assert summary["a510_credit_applied"] == 0
    assert summary["crs_class"] == 10
    assert float(summary["freeboard_ft"]) == pytest.approx(1.5, abs=0.01)
    assert int(summary["cumulative_period_years"]) == 10

    assert read_community(community_id)["compliance_posture"] == "ON_PROBATION"


# --------------------------------------------------------------------------
# Structures
# --------------------------------------------------------------------------

def test_improvement_summary_reports_the_window_bounds_and_both_ratios(api):
    """PRD §3.3: "A computed improvement summary is available for any structure
    and reports `structure_id`, the current `anchor_record_id`, the
    `window_start_date` and `window_end_date` of the closed anchored cumulative
    window — both null when no counted record exists — the
    `counted_record_count` of counted, non-reversed records lying inside that
    window, and the three aggregates `cumulative_counted_cost_usd`,
    `cumulative_improvement_pct`, and `single_event_improvement_pct`."

    PRD §3.6: "The **cumulative window** is closed on both ends: it starts at
    the anchor's `event_date` minus the community's `cumulative_period_years`
    counted in whole calendar years (with 29 February clamped to 28 February)
    and ends at the anchor's `event_date` itself, so a record dated exactly on
    either endpoint is inside the window."

    Design: Corner/endpoints/improvement_summary_reports_the_window_bounds_and_both_ratios
    """
    scenario = setup_ledger(
        [
            {"record_type": "IMPROVEMENT", "event_date": "2019-06-01T00:00:00Z",
             "cost_usd": 60_000.00},
            {"record_type": "IMPROVEMENT", "event_date": "2026-06-01T00:00:00Z",
             "cost_usd": 45_000.00},
        ],
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
        structure_overrides={"market_value_usd": 200_000.00},
    )
    newest_record = scenario["records"][1]

    response = api.get_improvement_summary(
        scenario["structure"]["id"], scenario["owner_headers"]
    )

    summary = validate_success(response, 200)
    assert summary["structure_id"] == scenario["structure"]["id"]
    assert summary["anchor_record_id"] == newest_record["id"]
    assert parse_instant(summary["window_start_date"]) == parse_instant("2016-06-01T00:00:00Z")
    assert parse_instant(summary["window_end_date"]) == parse_instant("2026-06-01T00:00:00Z")
    assert summary["counted_record_count"] == 2
    assert float(summary["cumulative_counted_cost_usd"]) == pytest.approx(105_000.00, abs=0.01)
    assert float(summary["cumulative_improvement_pct"]) == pytest.approx(52.50, abs=0.01)
    assert float(summary["single_event_improvement_pct"]) == pytest.approx(22.50, abs=0.01)


# --------------------------------------------------------------------------
# The logical clock
# --------------------------------------------------------------------------

def test_clock_advance_returns_the_previous_instant_and_mutates_nothing(api):
    """PRD §2.5: "It maintains a logical UTC clock whose startup value is
    exactly `2026-08-01T00:00:00Z`, and every timestamp it stamps, every
    deadline it computes, and every window comparison it makes reads that
    logical clock."

    PRD §2.5: "A test-driving capability lets a `StateNfipCoordinator` or a
    `FloodplainAdministrator` move the clock forward by supplying the target
    instant as `to_iso8601`; the response reports the new `current_utc` and the
    `previous_utc` it replaced."

    PRD §2.5: "Advancing the clock mutates no entity and fires no deferred
    action — nothing expires merely because time passed; expiry is evaluated by
    the write that reads it."

    Design: Corner/endpoints/clock_advance_returns_the_previous_instant_and_mutates_nothing
    """
    scenario = setup_issued_permit(
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 20_000.00,
            "proposed_lowest_floor_elevation_ft": 20.0,
        },
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
    )
    issued_permit = scenario["permit"]

    response = api.set_clock("2027-09-01T00:00:00Z", ADMINISTRATOR)

    clock = validate_success(response, 200)
    assert parse_instant(clock["previous_utc"]) == parse_instant("2026-08-01T00:00:00Z")
    assert parse_instant(clock["current_utc"]) == parse_instant("2027-09-01T00:00:00Z")

    permit = read_permit(issued_permit["id"])
    assert permit["status"] == "ISSUED"
    assert parse_instant(permit["issued_at"]) == parse_instant("2026-08-01T00:00:00Z")
    assert parse_instant(permit["expires_at"]) == parse_instant("2027-08-01T00:00:00Z")
    assert permit["version"] == issued_permit["version"]


# --------------------------------------------------------------------------
# Repetitive loss areas
# --------------------------------------------------------------------------

def test_outreach_launch_links_the_area_to_the_cycle_at_zero_coverage(api):
    """PRD §3.9: "A launch moves `outreach_status` to `IN_PROGRESS`, resets
    `delivered_count` to 0 and `coverage_pct` to 0, and snapshots
    `target_property_count` from the payload together with
    `outreach_crs_cycle_id` and `outreach_cycle_year` from the referenced
    cycle."

    PRD §3.9: "An area advances along three independent axes, and no axis reads
    another."

    Design: Corner/endpoints/outreach_launch_links_the_area_to_the_cycle_at_zero_coverage
    """
    scenario = setup_designated_area(
        area_overrides={"area_code": "RLA-1", "boundary_description": "Bayou bend north bank"},
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
        property_overrides={"mapped_area_code": "RLA-1"},
    )
    cycle = open_cycle(
        scenario["community"]["id"], cycle_year=2026,
        cycle_start_date="2026-01-01T00:00:00Z", cycle_end_date="2026-12-31T00:00:00Z",
        due_at="2027-03-01T00:00:00Z",
    )

    response = api.launch_outreach(
        scenario["area"]["id"],
        {"crs_cycle_id": cycle["id"], "target_property_count": 1},
        ADMINISTRATOR,
    )

    area = validate_success(response, 200)
    assert area["outreach_status"] == "IN_PROGRESS"
    assert area["outreach_crs_cycle_id"] == cycle["id"]
    assert area["outreach_cycle_year"] == 2026
    assert area["target_property_count"] == 1
    assert area["delivered_count"] == 0
    assert float(area["coverage_pct"]) == pytest.approx(0.00, abs=0.01)
    assert area["status"] == "DESIGNATED"
    assert area["analysis_status"] == "ANALYZED"


# --------------------------------------------------------------------------
# Determination cases
# --------------------------------------------------------------------------

def test_superseding_determination_case_withdraws_and_reverts_the_first(api):
    """PRD §3.7: "Opening a case supersedes the structure's determination
    history: any case of that structure whose `status` is `OPEN` or
    `DETERMINED` moves to the terminal `WITHDRAWN`, and if the withdrawn case
    had been `DETERMINED` the structure's `substantial_status` reverts to `NONE`
    in compensation."

    PRD §3.7: "The new case begins with `status` `OPEN`, `trigger_source`
    `ADMIN`, `anchor_record_id` copied from the structure's current
    `anchor_record_id` (null when the structure has no counted record),
    `threshold_pct` 50.0, `outcome` null, and the structure's `version`
    incremented by one."

    Design: Corner/endpoints/superseding_determination_case_withdraws_and_reverts_the_first
    """
    scenario = setup_ledger(
        [{"record_type": "IMPROVEMENT", "event_date": "2026-06-01T00:00:00Z",
          "cost_usd": 105_000.00}],
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
        structure_overrides={"market_value_usd": 200_000.00},
    )
    structure_id = scenario["structure"]["id"]
    record_id = scenario["records"][0]["id"]
    first_case = open_case(structure_id, method="CUMULATIVE")
    determine_case(first_case["id"])
    structure_version = read_structure(structure_id)["version"]

    response = api.open_determination_case(
        {
            "structure_id": structure_id,
            "method": "SINGLE_EVENT",
            "expected_structure_version": structure_version,
        },
        ADMINISTRATOR,
    )

    second_case = validate_success(response, 201)
    assert second_case["status"] == "OPEN"
    assert second_case["method"] == "SINGLE_EVENT"
    assert second_case["anchor_record_id"] == record_id
    assert second_case["determination_type"] == "SUBSTANTIAL_IMPROVEMENT"
    assert float(second_case["threshold_pct"]) == pytest.approx(50.00, abs=0.01)
    assert second_case["outcome"] is None
    assert second_case["computed_ratio_pct"] is None

    withdrawn = validate_success(
        api.get_determination_case(first_case["id"], ADMINISTRATOR), 200
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert read_structure(structure_id)["substantial_status"] == "NONE"
