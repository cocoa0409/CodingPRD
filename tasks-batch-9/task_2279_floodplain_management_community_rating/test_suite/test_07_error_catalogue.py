"""Error catalogue tests.

One test per rejection condition: the authentication gate, the referential
consistency checks of §2.8 step 7, the cross-entity state guards of step 10, the
own-state transition gate of step 9, and the uniqueness family of step 18.
Each test also proves the rejected write left the target state untouched.
"""
import pytest

from test_helpers import (
    ADMINISTRATOR,
    CLOCK_START_UTC,
    COORDINATOR,
    ApiErrorId,
    add_structure,
    create_community_payload,
    create_loss_area_payload,
    delineate_area,
    draft_standard,
    file_certificate_payload,
    file_firm_panel_payload,
    file_panel,
    higher_standard_payload,
    issue_violation,
    open_cycle,
    parse_instant,
    read_area,
    read_community,
    read_property,
    read_standard,
    read_structure,
    record_delivery,
    register_community,
    resolve_violation,
    setup_designated_area,
    setup_issued_permit,
    setup_ledger,
    setup_outreach_in_progress,
    setup_parcel,
    submit_standard,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------

def test_read_without_a_role_header_is_unauthorized(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, naming the role that user is acting in."

    PRD §2.1: "If either header is missing, blank, or `X-User-Role` is not one of
    those four strings, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/errors/read_without_a_role_header_is_unauthorized
    """
    community = register_community(freeboard_ft=1.5, cumulative_period_years=10)

    response = api.get_community(
        community["id"], {"X-User-ID": "snc-01", "Content-Type": "application/json"}
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


# --------------------------------------------------------------------------
# Referential consistency of resolved references (§2.8 step 7)
# --------------------------------------------------------------------------

def test_certificate_naming_a_structure_outside_its_permit_is_rejected(api):
    """PRD §3.5: "A filing names the `permit_id`, the `structure_id` — which must
    equal the permit's `structure_id`, else `ERR_CERTIFICATE_STRUCTURE_MISMATCH`
    — the `certificate_type`, the `datum` the surveyor worked in, the surveyed
    `measured_lowest_floor_ft`, and the `measured_bfe_ft` the surveyor read off
    the map, both expressed in the submitted datum."

    Design: Corner/errors/certificate_naming_a_structure_outside_its_permit_is_rejected
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
    other_structure = add_structure(
        scenario["property"]["id"], structure_use="NON_RESIDENTIAL", pre_firm=False,
        construction_year=2004, market_value_usd=120_000.00,
        highest_adjacent_grade_ft=10.0,
    )

    response = api.file_certificate(
        file_certificate_payload(
            permit_id, other_structure["id"], certificate_type="FINISHED_CONSTRUCTION",
            datum="NAVD88", measured_lowest_floor_ft=14.0, measured_bfe_ft=12.0,
            surveyor_license_no="TX-12345",
        ),
        scenario["owner_headers"],
    )

    validate_error(response, ApiErrorId.ERR_CERTIFICATE_STRUCTURE_MISMATCH)

    rows, meta = validate_paginated(
        api.list_certificates(ADMINISTRATOR, params={"permit_id": permit_id})
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert read_structure(other_structure["id"])["lowest_floor_elevation_ft"] is None
    assert validate_success(api.get_permit(permit_id, ADMINISTRATOR), 200)["status"] == "ISSUED"


def test_reversal_record_without_a_target_is_rejected(api):
    """PRD §3.6: "A `REVERSAL` record must name the row it cancels in
    `reverses_record_id`, and that field must be absent on any non-reversal row
    and must target a record of the same structure — a missing, superfluous, or
    cross-structure target is rejected with `ERR_REVERSAL_TARGET_INVALID`."

    Design: Corner/errors/reversal_record_without_a_target_is_rejected
    """
    scenario = setup_ledger(
        [{"record_type": "IMPROVEMENT", "event_date": "2026-06-01T00:00:00Z",
          "cost_usd": 60_000.00}],
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
        structure_overrides={"market_value_usd": 200_000.00},
    )
    structure_id = scenario["structure"]["id"]
    target_record = scenario["records"][0]

    response = api.append_improvement_record(
        {
            "structure_id": structure_id,
            "record_type": "REVERSAL",
            "event_date": "2026-07-01T00:00:00Z",
        },
        ADMINISTRATOR,
    )

    validate_error(response, ApiErrorId.ERR_REVERSAL_TARGET_INVALID)

    assert validate_success(
        api.get_improvement_record(target_record["id"], ADMINISTRATOR), 200
    )["reversed"] is False
    structure = read_structure(structure_id)
    assert float(structure["cumulative_counted_cost_usd"]) == pytest.approx(60_000.00, abs=0.01)
    assert float(structure["cumulative_improvement_pct"]) == pytest.approx(30.00, abs=0.01)


def test_outreach_against_another_communitys_cycle_is_rejected(api):
    """PRD §3.9: "The `crs_cycle_id` supplied in the payload must name a cycle of
    the same community, else `ERR_CYCLE_COMMUNITY_MISMATCH`, and that cycle's
    `status` must be `OPEN`, else `ERR_CYCLE_NOT_OPEN`."

    Design: Corner/errors/outreach_against_another_communitys_cycle_is_rejected
    """
    scenario = setup_designated_area(
        area_overrides={"area_code": "RLA-1"},
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
        property_overrides={"mapped_area_code": "RLA-1"},
    )
    other_community = register_community()
    foreign_cycle = open_cycle(
        other_community["id"], cycle_year=2026,
        cycle_start_date="2026-01-01T00:00:00Z", cycle_end_date="2026-12-31T00:00:00Z",
        due_at="2027-03-01T00:00:00Z",
    )

    response = api.launch_outreach(
        scenario["area"]["id"],
        {"crs_cycle_id": foreign_cycle["id"], "target_property_count": 1},
        ADMINISTRATOR,
    )

    validate_error(response, ApiErrorId.ERR_CYCLE_COMMUNITY_MISMATCH)

    area = read_area(scenario["area"]["id"])
    assert area["outreach_status"] == "NOT_STARTED"
    assert area["outreach_crs_cycle_id"] is None
    assert validate_success(
        api.get_crs_cycle(foreign_cycle["id"], ADMINISTRATOR), 200
    )["status"] == "OPEN"


# --------------------------------------------------------------------------
# Cross-entity state guard (§2.8 step 10)
# --------------------------------------------------------------------------

def test_designation_before_the_first_analysis_is_rejected(api):
    """PRD §3.9: "Designation requires two things: `status` must be `DRAFT`, and
    `analysis_status` must be `ANALYZED`."

    PRD §3.9: "An area already `DESIGNATED` fails the own-state gate of §2.8
    step 9 with `ERR_LOSS_AREA_NOT_DESIGNATED`; an area whose analysis is
    `PENDING_ANALYSIS` or has gone `STALE` fails the cross-axis guard of step 10
    with `ERR_LOSS_AREA_ANALYSIS_STALE`."

    Design: Corner/errors/designation_before_the_first_analysis_is_rejected
    """
    scenario = setup_parcel(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
        property_overrides={"mapped_area_code": "RLA-1"},
    )
    area = delineate_area(scenario["community"]["id"], area_code="RLA-1")

    response = api.designate_loss_area(area["id"], ADMINISTRATOR)

    validate_error(response, ApiErrorId.ERR_LOSS_AREA_ANALYSIS_STALE)

    unchanged = read_area(area["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["analysis_status"] == "PENDING_ANALYSIS"
    assert unchanged["property_count"] == 0
    assert read_property(scenario["property"]["id"])["repetitive_loss_area_id"] is None


# --------------------------------------------------------------------------
# Own-state transition gate (§2.8 step 9)
# --------------------------------------------------------------------------

def test_relaunching_outreach_while_one_is_in_progress_is_rejected(api):
    """PRD §3.9: "Its `outreach_status` must be `NOT_STARTED`, `COMPLETED`, or
    `INSUFFICIENT` — a relaunch over an in-flight effort is rejected with
    `ERR_OUTREACH_ALREADY_IN_PROGRESS`."

    Design: Corner/errors/relaunching_outreach_while_one_is_in_progress_is_rejected
    """
    scenario = setup_outreach_in_progress(
        target_property_count=2,
        cycle_overrides={"cycle_year": 2026, "due_at": "2027-03-01T00:00:00Z"},
        area_overrides={"area_code": "RLA-1"},
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
        property_overrides={"mapped_area_code": "RLA-1"},
    )
    area_id = scenario["area"]["id"]
    record_delivery(area_id, 1)

    response = api.launch_outreach(
        area_id,
        {"crs_cycle_id": scenario["cycle"]["id"], "target_property_count": 4},
        ADMINISTRATOR,
    )

    validate_error(response, ApiErrorId.ERR_OUTREACH_ALREADY_IN_PROGRESS)

    area = read_area(area_id)
    assert area["outreach_status"] == "IN_PROGRESS"
    assert area["target_property_count"] == 2
    assert area["delivered_count"] == 1
    assert float(area["coverage_pct"]) == pytest.approx(50.00, abs=0.01)


def test_resolving_an_already_remediated_violation_is_rejected(api):
    """PRD §3.8: "Resolving the violation itself carries a `resolution` of
    `REMEDIATED` or `CLOSED_UNRESOLVED` and an optional `resolution_note`, and is
    admitted from `OPEN`, `ORDER_ISSUED`, or `ESCALATED` alike; attempting it on
    a violation already `REMEDIATED` or `CLOSED_UNRESOLVED` is rejected with
    `ERR_VIOLATION_NOT_ACTIONABLE`."

    Design: Corner/errors/resolving_an_already_remediated_violation_is_rejected
    """
    scenario = setup_parcel(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        panel_overrides={"flood_zone": "AE", "base_flood_elevation_ft": 12.0},
    )
    violation = issue_violation(
        scenario["property"]["id"], violation_type="UNPERMITTED_FILL", severity="MAJOR"
    )
    resolve_violation(violation["id"], "REMEDIATED", resolution_note="Fill removed")

    response = api.resolve_violation(
        violation["id"], {"resolution": "CLOSED_UNRESOLVED"}, ADMINISTRATOR
    )

    validate_error(response, ApiErrorId.ERR_VIOLATION_NOT_ACTIONABLE)

    unchanged = validate_success(api.get_violation(violation["id"], ADMINISTRATOR), 200)
    assert unchanged["status"] == "REMEDIATED"
    assert parse_instant(unchanged["resolved_at"]) == parse_instant(CLOCK_START_UTC)
    assert unchanged["sanction_points_contributed"] == 0
    community = read_community(scenario["community"]["id"])
    assert community["sanction_risk_points"] == 0
    assert community["compliance_posture"] == "GOOD_STANDING"


# --------------------------------------------------------------------------
# The uniqueness family (§2.8 step 18)
# --------------------------------------------------------------------------

def test_duplicate_cid_number_in_another_state_is_rejected(api):
    """PRD §3.1: "A `StateNfipCoordinator` registers one by supplying the
    municipality's `name`, its two-letter `state_code`, and its NFIP
    `cid_number`, which must be unique across every community in the system — a
    repeat is rejected with `ERR_DUPLICATE_CID_NUMBER`."

    Design: Corner/errors/duplicate_cid_number_in_another_state_is_rejected
    """
    first = register_community(
        name="Bayou City", state_code="TX", cid_number="480001",
        freeboard_ft=1.5, cumulative_period_years=10,
    )

    response = api.create_community(
        create_community_payload(
            name="Riverbend Parish", state_code="LA", cid_number="480001"
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_CID_NUMBER)

    survivor = read_community(first["id"])
    assert survivor["state_code"] == "TX"
    assert survivor["cid_number"] == "480001"
    assert survivor["name"] == "Bayou City"


def test_second_pending_revision_of_one_panel_number_is_rejected(api):
    """PRD §3.2: "At most one `PENDING_REVISION` panel may exist for a given
    `community_id` and `panel_number` pair; a second is rejected with
    `ERR_DUPLICATE_PANEL_REVISION`."

    PRD §3.2: "A filed panel begins with `status` at `PENDING_REVISION`,
    `supersedes_panel_id` null, and `version` at 1."

    Design: Corner/errors/second_pending_revision_of_one_panel_number_is_rejected
    """
    community = register_community(freeboard_ft=1.5, cumulative_period_years=10)
    incumbent = file_panel(
        community["id"], panel_number="48001C0100", suffix="H", flood_zone="AE",
        base_flood_elevation_ft=12.0, effective_date="2020-01-01T00:00:00Z",
    )

    response = api.file_firm_panel(
        file_firm_panel_payload(
            community["id"], panel_number="48001C0100", suffix="J", flood_zone="AE",
            base_flood_elevation_ft=13.0, effective_date="2026-01-01T00:00:00Z",
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_PANEL_REVISION)

    unchanged = validate_success(api.get_firm_panel(incumbent["id"], COORDINATOR), 200)
    assert unchanged["status"] == "PENDING_REVISION"
    assert unchanged["suffix"] == "H"
    assert unchanged["supersedes_panel_id"] is None
    rows, meta = validate_paginated(
        api.list_firm_panels(
            COORDINATOR,
            params={"community_id": community["id"], "panel_number": "48001C0100"},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [incumbent["id"]]


def test_duplicate_area_code_inside_one_community_is_rejected(api):
    """PRD §3.9: "A `RepetitiveLossArea` is delineated by a
    `FloodplainAdministrator` with its `community_id`, its `area_code` — unique
    per community, else `ERR_DUPLICATE_AREA_CODE` — and a narrative
    `boundary_description`."

    Design: Corner/errors/duplicate_area_code_inside_one_community_is_rejected
    """
    community = register_community(freeboard_ft=1.5, cumulative_period_years=10)
    first_area = delineate_area(
        community["id"], area_code="RLA-1", boundary_description="Bayou bend north bank"
    )

    response = api.create_loss_area(
        create_loss_area_payload(
            community["id"], area_code="RLA-1",
            boundary_description="Second delineation of the same code",
        ),
        ADMINISTRATOR,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_AREA_CODE)

    unchanged = read_area(first_area["id"])
    assert unchanged["boundary_description"] == "Bayou bend north bank"
    assert unchanged["status"] == "DRAFT"
    rows, meta = validate_paginated(
        api.list_loss_areas(ADMINISTRATOR, params={"community_id": community["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [first_area["id"]]


def test_second_standard_for_one_activity_and_cycle_year_is_rejected(api):
    """PRD §3.9: "Drafting supersedes any submission of the same `community_id`,
    `activity_code`, and `documentation_cycle_year` whose `documentation_status`
    is `DRAFT` or `REJECTED`, moving it to the terminal `EXPIRED`; but a
    submission for that same triple whose `documentation_status` is `SUBMITTED`
    or `VERIFIED` blocks the draft outright with
    `ERR_DUPLICATE_STANDARD_ACTIVITY`."

    Design: Corner/errors/second_standard_for_one_activity_and_cycle_year_is_rejected
    """
    community = register_community(freeboard_ft=1.5, cumulative_period_years=10)
    incumbent = draft_standard(
        community["id"], activity_code="A430_FREEBOARD",
        documentation_cycle_year=2026, claimed_points=100,
    )
    submit_standard(incumbent["id"])
    community_version = read_community(community["id"])["version"]

    response = api.draft_higher_standard(
        higher_standard_payload(
            community["id"], community_version, activity_code="A430_FREEBOARD",
            documentation_cycle_year=2026, claimed_points=150,
        ),
        ADMINISTRATOR,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_STANDARD_ACTIVITY)

    unchanged = read_standard(incumbent["id"])
    assert unchanged["documentation_status"] == "SUBMITTED"
    assert unchanged["claimed_points"] == 100
    rows, meta = validate_paginated(
        api.list_higher_standards(
            ADMINISTRATOR,
            params={
                "community_id": community["id"],
                "activity_code": "A430_FREEBOARD",
                "documentation_cycle_year": 2026,
            },
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [incumbent["id"]]
