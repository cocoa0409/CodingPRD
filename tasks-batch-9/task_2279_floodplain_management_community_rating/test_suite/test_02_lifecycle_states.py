"""Lifecycle transitions: opening states, admitted moves, refused moves and the
side effects each transition is declared to execute.

Every test builds its own communities, panels, parcels, structures and
downstream records from scratch through the endpoints the PRD declares.
"""
from test_helpers import (
    CLOCK_START_UTC,
    TEST_USERS,
    activate_panel,
    add_property,
    add_structure,
    api_client,
    append_record,
    assert_audit_fields,
    assert_calendar_years_after,
    assert_days_after,
    ApiErrorId,
    create_permit_payload,
    determine_case,
    file_panel,
    get_success_data,
    make_property_owner_headers,
    parse_instant,
    read_certificate,
    read_permit,
    read_property,
    read_structure,
    record_delivery,
    register_community,
    review_permit,
    setup_accepted_certificate,
    setup_community_with_panel,
    setup_filed_certificate,
    setup_outreach_in_progress,
    setup_permit_under_review,
    setup_scheduled_inspection,
    setup_structure,
    start_permit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMINISTRATOR = TEST_USERS["administrator_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]

SWEEP_DR_4700 = {
    "declaration_code": "DR-4700",
    "event_date": "2026-07-15T00:00:00Z",
    "inspection_window_days": 30,
}


def _effective_panel_without_bfe(community_id, **overrides):
    """File and activate a panel whose base_flood_elevation_ft is never supplied."""
    payload = {
        "community_id": community_id,
        "panel_number": "48001C0400",
        "suffix": "H",
        "flood_zone": "A",
        "effective_date": "2020-01-01T00:00:00Z",
    }
    payload.update(overrides)
    panel = get_success_data(api_client.file_firm_panel(payload, COORDINATOR))
    return get_success_data(api_client.activate_firm_panel(panel["id"], COORDINATOR))


def _draft_permit_on_panel(panel_overrides=None, panel=None, community=None):
    """Community + EFFECTIVE panel + parcel + structure + DRAFT permit."""
    if panel is None:
        base = setup_community_with_panel(
            community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
            panel_overrides=panel_overrides,
        )
        community, panel = base["community"], base["panel"]
    prop = add_property(community["id"], panel["id"], parcel_id="P-0001")
    owner_headers = make_property_owner_headers(prop["id"])
    structure = add_structure(prop["id"], market_value_usd=200_000.00)
    permit = start_permit(
        prop["id"],
        structure["id"],
        owner_headers,
        project_type="NEW_CONSTRUCTION",
        declared_project_cost_usd=20_000.00,
        proposed_lowest_floor_elevation_ft=20.0,
    )
    return {
        "community": community,
        "panel": panel,
        "property": prop,
        "owner_headers": owner_headers,
        "structure": structure,
        "permit": permit,
    }


# ==========================================================================
# DevelopmentPermit: opening state and the DRAFT -> UNDER_REVIEW snapshot
# ==========================================================================

def test_permit_created_starts_in_draft_with_zero_revision_round(api):
    """PRD §3.4: "A draft permit has `revision_round` 0, every determination snapshot
    null, and `version` 1."

    PRD §3.4: "An optional `floodproofing_requested` flag, defaulting to false, records a
    request for dry-floodproofing credit in place of physical elevation."

    PRD §3.4: "The permit's `status` moves through `DRAFT`, `UNDER_REVIEW`,
    `REVISION_REQUIRED`, `APPROVED`, `ISSUED`, and one of the three terminal values
    `CLOSED_COMPLIANT`, `DENIED`, or `REVOKED`."

    Design: Corner/state_machines/permit_created_starts_in_draft_with_zero_revision_round
    """
    scenario = setup_structure(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={"market_value_usd": 200_000.00},
    )
    payload = create_permit_payload(
        scenario["property"]["id"],
        scenario["structure"]["id"],
        project_type="IMPROVEMENT",
        declared_project_cost_usd=30_000.00,
        proposed_lowest_floor_elevation_ft=20.0,
    )

    permit = validate_success(api.create_permit(payload, scenario["owner_headers"]), 201)

    assert permit["status"] == "DRAFT"
    assert permit["revision_round"] == 0
    assert permit["determined_zone"] is None
    assert permit["determined_bfe_ft"] is None
    assert permit["freeboard_applied_ft"] is None
    assert permit["required_lowest_floor_elevation_ft"] is None
    assert permit["si_determination_case_id"] is None
    assert permit["floodproofing_requested"] is False
    assert_audit_fields(permit, "DevelopmentPermit", expected_version=1)


def test_permit_submit_snapshots_zone_bfe_and_freeboard_at_review_entry(api):
    """PRD §3.4: "On a first submission out of `DRAFT`, the server snapshots
    `determined_zone` and `determined_bfe_ft` from the effective panel and
    `freeboard_applied_ft` from the community's current `freeboard_ft`, then computes
    `required_lowest_floor_elevation_ft`."

    PRD §2.6: "**The base** depends on the frozen zone: for `A`, `AE`, and `VE` the base
    is `determined_bfe_ft` directly; for `AO`, where `determined_bfe_ft` holds a depth
    rather than an elevation, the base is the structure's `highest_adjacent_grade_ft`
    plus `determined_bfe_ft`."

    PRD §2.6: "**The freeboard** is the larger of the permit's `freeboard_applied_ft` and
    the zone's own regulatory floor, which is 1.0 foot for zones `A`, `AE`, and `AO` and
    2.0 feet for zone `VE`."

    PRD §3.4: "Review is admitted only while the permit is `UNDER_REVIEW`, else
    `ERR_PERMIT_NOT_UNDER_REVIEW`."

    PRD §2.4: "`version` is an integer that starts at 1 when the row is created and
    increments by exactly one on every mutation, including mutations the server performs
    on its own initiative as part of a cascade, and including mutations that touch only
    computed fields such as a recomputed `sanction_risk_points` or a recomputed
    `cumulative_improvement_pct`."

    Design: Corner/state_machines/permit_submit_snapshots_zone_bfe_and_freeboard_at_review_entry
    """
    scenario = _draft_permit_on_panel(
        panel_overrides={
            "panel_number": "48001C0100",
            "suffix": "H",
            "flood_zone": "AE",
            "base_flood_elevation_ft": 12.0,
        }
    )

    permit = validate_success(
        api.submit_permit(scenario["permit"]["id"], scenario["owner_headers"]), 200
    )

    assert permit["status"] == "UNDER_REVIEW"
    assert permit["determined_zone"] == "AE"
    assert float(permit["determined_bfe_ft"]) == 12.0
    assert float(permit["freeboard_applied_ft"]) == 1.5
    assert float(permit["required_lowest_floor_elevation_ft"]) == 13.5
    assert permit["revision_round"] == 0
    assert permit["version"] == 2


def test_permit_submit_under_zone_x_panel_is_rejected(api):
    """PRD §2.8: "**Elevation determinability** — a permit submission requires a
    governing panel that supports an elevation determination. A panel whose `flood_zone`
    is `X` raises `ERR_OUTSIDE_FLOOD_HAZARD_AREA`; a panel whose
    `base_flood_elevation_ft` is null raises `ERR_BFE_UNDETERMINED`."

    PRD §3.4: "The property's governing panel must be `EFFECTIVE`
    (`ERR_PANEL_NOT_EFFECTIVE`), its `flood_zone` must not be `X`
    (`ERR_OUTSIDE_FLOOD_HAZARD_AREA`), and its `base_flood_elevation_ft` must not be null
    (`ERR_BFE_UNDETERMINED`)."

    PRD §3.4: "On a first submission out of `DRAFT`, the server snapshots
    `determined_zone` and `determined_bfe_ft` from the effective panel and
    `freeboard_applied_ft` from the community's current `freeboard_ft`, then computes
    `required_lowest_floor_elevation_ft`."

    Design: Corner/state_machines/permit_submit_under_zone_x_panel_is_rejected
    """
    scenario = _draft_permit_on_panel(
        panel_overrides={
            "panel_number": "48001C0300",
            "suffix": "H",
            "flood_zone": "X",
            "base_flood_elevation_ft": 12.0,
        }
    )

    validate_error(
        api.submit_permit(scenario["permit"]["id"], scenario["owner_headers"]),
        ApiErrorId.ERR_OUTSIDE_FLOOD_HAZARD_AREA,
    )

    permit = read_permit(scenario["permit"]["id"])
    assert permit["status"] == "DRAFT"
    assert permit["determined_zone"] is None


def test_permit_submit_under_unnumbered_zone_a_panel_is_rejected(api):
    """PRD §2.8: "**Elevation determinability** — a permit submission requires a
    governing panel that supports an elevation determination. A panel whose `flood_zone`
    is `X` raises `ERR_OUTSIDE_FLOOD_HAZARD_AREA`; a panel whose
    `base_flood_elevation_ft` is null raises `ERR_BFE_UNDETERMINED`."

    PRD §3.2: "For zones `A`, `AE`, and `VE`, `base_flood_elevation_ft` is an elevation
    in feet NAVD88; for zone `AO` the same field carries a flood *depth* in feet rather
    than an elevation, which matters materially to the requirement arithmetic in §3.4;
    and a null value is tolerated only for unnumbered zone `A` panels."

    PRD §3.4: "The property's governing panel must be `EFFECTIVE`
    (`ERR_PANEL_NOT_EFFECTIVE`), its `flood_zone` must not be `X`
    (`ERR_OUTSIDE_FLOOD_HAZARD_AREA`), and its `base_flood_elevation_ft` must not be null
    (`ERR_BFE_UNDETERMINED`)."

    Design: Corner/state_machines/permit_submit_under_unnumbered_zone_a_panel_is_rejected
    """
    community = register_community(freeboard_ft=1.5, cumulative_period_years=10)
    panel = _effective_panel_without_bfe(community["id"])
    assert panel["base_flood_elevation_ft"] is None
    scenario = _draft_permit_on_panel(panel=panel, community=community)

    validate_error(
        api.submit_permit(scenario["permit"]["id"], scenario["owner_headers"]),
        ApiErrorId.ERR_BFE_UNDETERMINED,
    )

    permit = read_permit(scenario["permit"]["id"])
    assert permit["status"] == "DRAFT"
    assert permit["determined_zone"] is None


def test_denied_permit_cannot_be_resubmitted(api):
    """PRD §3.4: "A submission is accepted from `DRAFT` or from `REVISION_REQUIRED`; from
    any other status it is rejected with `ERR_PERMIT_NOT_SUBMITTABLE`."

    PRD §3.4: "`DENY` moves the permit to the terminal `DENIED`."

    Design: Corner/state_machines/denied_permit_cannot_be_resubmitted
    """
    scenario = setup_permit_under_review(
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 20_000.00,
            "proposed_lowest_floor_elevation_ft": 20.0,
        },
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
    )
    denied = review_permit(scenario["permit"]["id"], "DENY")
    assert denied["status"] == "DENIED"

    validate_error(
        api.submit_permit(scenario["permit"]["id"], scenario["owner_headers"]),
        ApiErrorId.ERR_PERMIT_NOT_SUBMITTABLE,
    )

    permit = read_permit(scenario["permit"]["id"])
    assert permit["status"] == "DENIED"
    assert permit["revision_round"] == 0


# ==========================================================================
# ElevationCertificate: acceptance side effects and the amendment gate
# ==========================================================================

def test_certificate_acceptance_updates_structure_elevation_and_compliance(api):
    """PRD §3.5: "An accepted certificate moves to `ACCEPTED`, stamps `accepted_at` with
    the current logical clock, and sets `retention_review_due_at` to 5 calendar years
    after `accepted_at`, which is the date the record-retention audit for CRS Activity
    310 becomes due."

    PRD §3.5: "And when the accepted certificate's `certificate_type` is
    `FINISHED_CONSTRUCTION`, the structure's `lowest_floor_elevation_ft` is set to the
    certificate's `normalized_lowest_floor_ft` and the structure's `compliance_status`
    becomes `COMPLIANT` — unless the structure carries a violation whose `status` is
    `OPEN`, `ORDER_ISSUED`, or `ESCALATED`, in which case the elevation is recorded but
    the compliance status is left where enforcement put it."

    PRD §2.6: "The datum offset is added to `measured_lowest_floor_ft` first — the offset
    is 0.0 feet for `NAVD88` and negative 0.85 feet for `NGVD29` — and that sum is
    rounded half-up to one decimal place to yield `normalized_lowest_floor_ft`."

    PRD §2.6: "The permit's current `required_lowest_floor_elevation_ft` is then
    subtracted from that already-rounded normalized value, and the difference is rounded
    half-up to one decimal place again to yield `freeboard_margin_ft`."

    Design: Corner/state_machines/certificate_acceptance_updates_structure_elevation_and_compliance
    """
    scenario = setup_filed_certificate(
        certificate_overrides={
            "certificate_type": "FINISHED_CONSTRUCTION",
            "datum": "NAVD88",
            "measured_lowest_floor_ft": 14.0,
            "measured_bfe_ft": 12.0,
            "surveyor_license_no": "TX-5511",
        },
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 20_000.00,
            "proposed_lowest_floor_elevation_ft": 20.0,
        },
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
    )

    certificate = validate_success(
        api.review_certificate(
            scenario["certificate"]["id"], {"decision": "ACCEPT"}, ADMINISTRATOR
        ),
        200,
    )

    assert certificate["status"] == "ACCEPTED"
    assert float(certificate["normalized_lowest_floor_ft"]) == 14.0
    assert float(certificate["freeboard_margin_ft"]) == 0.5
    assert parse_instant(certificate["accepted_at"]) == parse_instant(CLOCK_START_UTC)
    assert parse_instant(certificate["retention_review_due_at"]) == parse_instant(
        "2031-08-01T00:00:00Z"
    )
    assert_calendar_years_after(
        certificate["retention_review_due_at"],
        certificate["accepted_at"],
        5,
        "retention_review_due_at",
    )

    structure = read_structure(scenario["structure"]["id"])
    assert float(structure["lowest_floor_elevation_ft"]) == 14.0
    assert structure["compliance_status"] == "COMPLIANT"
    assert structure["substantial_status"] == "NONE"


def test_certificate_amend_on_accepted_certificate_is_rejected(api):
    """PRD §3.5: "A `PropertyOwner` whose identifier matches the `property_id` of the
    certificate's permit may amend a `DEFICIENT` certificate — amending any other status
    is rejected with `ERR_CERTIFICATE_NOT_DEFICIENT` — by resupplying `datum`,
    `measured_lowest_floor_ft`, `measured_bfe_ft`, and, where required,
    `surveyor_license_no`."

    PRD §3.5: "An accepted certificate moves to `ACCEPTED`, stamps `accepted_at` with the
    current logical clock, and sets `retention_review_due_at` to 5 calendar years after
    `accepted_at`, which is the date the record-retention audit for CRS Activity 310
    becomes due."

    Design: Corner/state_machines/certificate_amend_on_accepted_certificate_is_rejected
    """
    scenario = setup_accepted_certificate(
        certificate_overrides={
            "certificate_type": "FINISHED_CONSTRUCTION",
            "datum": "NAVD88",
            "measured_lowest_floor_ft": 14.0,
            "measured_bfe_ft": 12.0,
            "surveyor_license_no": "TX-5511",
        },
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 20_000.00,
            "proposed_lowest_floor_elevation_ft": 20.0,
        },
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
    )
    amendment = {
        "datum": "NAVD88",
        "measured_lowest_floor_ft": 16.0,
        "measured_bfe_ft": 12.0,
        "surveyor_license_no": "TX-5511",
    }

    validate_error(
        api.amend_certificate(
            scenario["certificate"]["id"], amendment, scenario["owner_headers"]
        ),
        ApiErrorId.ERR_CERTIFICATE_NOT_DEFICIENT,
    )

    certificate = read_certificate(scenario["certificate"]["id"])
    assert certificate["status"] == "ACCEPTED"
    assert float(certificate["normalized_lowest_floor_ft"]) == 14.0


# ==========================================================================
# PostDisasterInspection: the finalization gate
# ==========================================================================

def test_inspection_finalize_before_assessment_is_rejected(api):
    """PRD §3.7: "Finalization is admitted only from `ASSESSED`
    (`ERR_INSPECTION_NOT_ASSESSED`) and is where the post-disaster cascade of §2.10 runs
    in full."

    PRD §3.7: "Every `Structure` of every eligible property is swept in ascending
    `created_at` order, and each produces one `PostDisasterInspection` with `status`
    `SCHEDULED`, the sweep's `declaration_code`, `disaster_event_date` equal to the
    sweep's `event_date`, and `deadline_at` equal to that date plus
    `inspection_window_days`."

    PRD §3.3: "A new structure has `lowest_floor_elevation_ft` null, `substantial_status`
    `NONE`, `anchor_record_id` null, `cumulative_counted_cost_usd`,
    `cumulative_improvement_pct` and `single_event_improvement_pct` all 0, and `version`
    1."

    Design: Corner/state_machines/inspection_finalize_before_assessment_is_rejected
    """
    scenario = setup_scheduled_inspection(
        sweep_overrides=dict(SWEEP_DR_4700),
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={"market_value_usd": 200_000.00},
    )
    inspections, _meta = validate_paginated(
        api.list_inspections(ADMINISTRATOR, params={"structure_id": scenario["structure"]["id"]})
    )
    inspection_id = inspections[0]["id"]
    assert inspections[0]["status"] == "SCHEDULED"

    validate_error(
        api.finalize_inspection(inspection_id, ADMINISTRATOR),
        ApiErrorId.ERR_INSPECTION_NOT_ASSESSED,
    )

    inspection = validate_success(api.get_inspection(inspection_id, ADMINISTRATOR), 200)
    assert inspection["status"] == "SCHEDULED"
    assert inspection["declaration_code"] == "DR-4700"
    assert parse_instant(inspection["deadline_at"]) == parse_instant("2026-08-14T00:00:00Z")
    assert_days_after(
        inspection["deadline_at"], inspection["disaster_event_date"], 30, "deadline_at"
    )

    structure = read_structure(scenario["structure"]["id"])
    assert structure["anchor_record_id"] is None
    assert float(structure["cumulative_counted_cost_usd"]) == 0


# ==========================================================================
# FirmPanel: activation, its refusal, and the map-revision cascade
# ==========================================================================

def test_second_activation_of_the_same_panel_is_rejected(api):
    """PRD §3.2: "Activation is refused with `ERR_PANEL_NOT_PENDING` when the panel is
    not `PENDING_REVISION`, and with `ERR_PANEL_EFFECTIVE_DATE_OVERLAP` when an
    `EFFECTIVE` sibling panel already holds an `effective_date` at or after the
    candidate's, per §2.11."

    PRD §3.2: "Activation moves the panel from `PENDING_REVISION` to `EFFECTIVE`, stamps
    `activated_at` with the current logical clock, and records in `supersedes_panel_id`
    the identifier of the panel that was `EFFECTIVE` for the same `community_id` and
    `panel_number` at that moment — null when this is the community's first panel for
    that number."

    Design: Corner/state_machines/second_activation_of_the_same_panel_is_rejected
    """
    community = register_community(freeboard_ft=1.5, cumulative_period_years=10)
    filed = file_panel(
        community["id"],
        panel_number="48001C0100",
        suffix="H",
        flood_zone="AE",
        effective_date="2020-01-01T00:00:00Z",
        base_flood_elevation_ft=12.0,
    )
    activated = activate_panel(filed["id"])
    assert activated["status"] == "EFFECTIVE"

    validate_error(
        api.activate_firm_panel(filed["id"], COORDINATOR), ApiErrorId.ERR_PANEL_NOT_PENDING
    )

    panel = validate_success(api.get_firm_panel(filed["id"], ADMINISTRATOR), 200)
    assert panel["status"] == "EFFECTIVE"
    assert panel["supersedes_panel_id"] is None
    assert parse_instant(panel["activated_at"]) == parse_instant(CLOCK_START_UTC)


def test_panel_activation_supersedes_only_the_incumbent_of_the_same_panel_number(api):
    """PRD §3.2: "Activation moves the panel from `PENDING_REVISION` to `EFFECTIVE`,
    stamps `activated_at` with the current logical clock, and records in
    `supersedes_panel_id` the identifier of the panel that was `EFFECTIVE` for the same
    `community_id` and `panel_number` at that moment — null when this is the community's
    first panel for that number."

    PRD §3.2: "First, the superseded incumbent moves to `SUPERSEDED`, which is terminal —
    an effective panel is retired only by the activation of its successor, and a
    `PENDING_REVISION` panel is never superseded directly."

    PRD §3.2: "Second, caused by the first hop, every `Property` whose `firm_panel_id`
    pointed at the superseded panel is repointed to the newly effective panel."

    Design: Corner/state_machines/panel_activation_supersedes_only_the_incumbent_of_the_same_panel_number
    """
    community = register_community(freeboard_ft=1.5, cumulative_period_years=10)
    panel_h = activate_panel(
        file_panel(
            community["id"],
            panel_number="48001C0100",
            suffix="H",
            flood_zone="AE",
            effective_date="2020-01-01T00:00:00Z",
            base_flood_elevation_ft=12.0,
        )["id"]
    )
    panel_g = activate_panel(
        file_panel(
            community["id"],
            panel_number="48001C0200",
            suffix="G",
            flood_zone="AE",
            effective_date="2020-01-01T00:00:00Z",
            base_flood_elevation_ft=13.0,
        )["id"]
    )
    property_h = add_property(
        community["id"], panel_h["id"], parcel_id="P-0001", mapped_area_code="RLA-1"
    )
    property_g = add_property(
        community["id"],
        panel_g["id"],
        parcel_id="P-0002",
        mapped_area_code="RLA-2",
        owner_name="B Owner",
        owner_email="b@example.com",
    )
    panel_j = file_panel(
        community["id"],
        panel_number="48001C0100",
        suffix="J",
        flood_zone="AE",
        effective_date="2026-06-01T00:00:00Z",
        base_flood_elevation_ft=14.0,
    )

    activated = validate_success(api.activate_firm_panel(panel_j["id"], COORDINATOR), 200)

    assert activated["status"] == "EFFECTIVE"
    assert activated["supersedes_panel_id"] == panel_h["id"]

    assert validate_success(api.get_firm_panel(panel_h["id"], ADMINISTRATOR), 200)[
        "status"
    ] == "SUPERSEDED"
    reread_g = validate_success(api.get_firm_panel(panel_g["id"], ADMINISTRATOR), 200)
    assert reread_g["status"] == "EFFECTIVE"
    assert reread_g["supersedes_panel_id"] is None
    assert read_property(property_h["id"])["firm_panel_id"] == panel_j["id"]
    assert read_property(property_g["id"])["firm_panel_id"] == panel_g["id"]


# ==========================================================================
# Structure: two independent status axes
# ==========================================================================

def test_structure_compliance_and_substantial_axes_advance_independently(api):
    """PRD §3.3: "A structure carries two status dimensions that advance independently
    and never read each other."

    PRD §3.7: "`threshold_pct` is set to 50.00 and the `outcome` is `SUBSTANTIAL` when
    `computed_ratio_pct` is at least `threshold_pct` and `NOT_SUBSTANTIAL` otherwise."

    PRD §3.7: "A `SUBSTANTIAL` outcome sets the structure's `substantial_status` to the
    case's `determination_type`; a `NOT_SUBSTANTIAL` outcome sets it to `NONE`."

    PRD §3.7: "Its `determination_type` is derived from the anchor record's
    `record_type`: an `IMPROVEMENT` anchor yields `SUBSTANTIAL_IMPROVEMENT` and a
    `DAMAGE` anchor yields `SUBSTANTIAL_DAMAGE`, and when the anchor is null the type is
    `SUBSTANTIAL_IMPROVEMENT`."

    PRD §3.8: "A new violation opens with `status` `OPEN`, `opened_at` stamped from the
    logical clock, `sanction_points_contributed` set to its severity weight, and
    `version` 1."

    PRD §3.8: "Issuing a violation immediately recomputes the community's sanction risk,
    and when the `violation_type` is `ELEVATION_DEFICIENT` and a `structure_id` was
    supplied, that structure's `compliance_status` becomes `NON_COMPLIANT`."

    PRD §2.7: "The tier rule is inclusive on the worse side: a score of 25 points or more
    is `SUSPENDED`, a score of 10 points or more is `ON_PROBATION`, and anything lower is
    `GOOD_STANDING`."

    PRD §2.6: "`cumulative_improvement_pct` is that windowed sum divided by the
    denominator, multiplied by 100, rounded half-up to two decimals;
    `single_event_improvement_pct` is the anchor's own `cost_usd` divided by the same
    denominator, multiplied by 100, rounded half-up to two decimals."

    Design: Corner/state_machines/structure_compliance_and_substantial_axes_advance_independently
    """
    scenario = setup_structure(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={"market_value_usd": 200_000.00},
    )
    structure_id = scenario["structure"]["id"]
    append_record(
        structure_id,
        record_type="IMPROVEMENT",
        event_date="2026-03-01T00:00:00Z",
        cost_usd=105_000.00,
    )
    cases, _meta = validate_paginated(
        api.list_determination_cases(ADMINISTRATOR, params={"structure_id": structure_id})
    )
    assert len(cases) == 1
    case = determine_case(cases[0]["id"])
    assert case["outcome"] == "SUBSTANTIAL"
    assert case["determination_type"] == "SUBSTANTIAL_IMPROVEMENT"

    violation = validate_success(
        api.create_violation(
            {
                "property_id": scenario["property"]["id"],
                "structure_id": structure_id,
                "violation_type": "ELEVATION_DEFICIENT",
                "severity": "MINOR",
            },
            ADMINISTRATOR,
        ),
        201,
    )

    assert violation["status"] == "OPEN"
    assert violation["sanction_points_contributed"] == 2

    structure = read_structure(structure_id)
    assert structure["compliance_status"] == "NON_COMPLIANT"
    assert structure["substantial_status"] == "SUBSTANTIAL_IMPROVEMENT"
    assert float(structure["cumulative_improvement_pct"]) == 52.50
    assert float(structure["single_event_improvement_pct"]) == 52.50

    community = validate_success(
        api.get_community(scenario["community"]["id"], ADMINISTRATOR), 200
    )
    assert community["sanction_risk_points"] == 2
    assert community["compliance_posture"] == "GOOD_STANDING"


# ==========================================================================
# RepetitiveLossArea: the outreach coverage branch
# ==========================================================================

def test_outreach_completion_takes_the_insufficient_branch_below_the_partial_tier(api):
    """PRD §3.9: "Closing the effort is also admitted only from `IN_PROGRESS`, and the
    coverage tier decides the branch: a `coverage_pct` of at least 75.00 moves
    `outreach_status` to `COMPLETED`, and a `coverage_pct` below 75.00 moves it to
    `INSUFFICIENT`."

    PRD §3.9: "`coverage_pct` is then recomputed as 0.00 when `target_property_count` is
    0, and otherwise as `delivered_count` divided by `target_property_count`, multiplied
    by 100, rounded half-up to two decimal places."

    PRD §3.9: "A launch moves `outreach_status` to `IN_PROGRESS`, resets `delivered_count`
    to 0 and `coverage_pct` to 0, and snapshots `target_property_count` from the payload
    together with `outreach_crs_cycle_id` and `outreach_cycle_year` from the referenced
    cycle."

    PRD §3.9: "Designation moves `status` to the terminal `DESIGNATED`."

    Design: Corner/state_machines/outreach_completion_takes_the_insufficient_branch_below_the_partial_tier
    """
    scenario = setup_outreach_in_progress(
        target_property_count=4,
        cycle_overrides={
            "cycle_year": 2026,
            "cycle_start_date": "2026-01-01T00:00:00Z",
            "cycle_end_date": "2026-12-31T00:00:00Z",
            "due_at": "2027-03-01T00:00:00Z",
        },
        area_overrides={"area_code": "RLA-1", "boundary_description": "Bayou bend north bank"},
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        property_overrides={"parcel_id": "P-0001", "mapped_area_code": "RLA-1"},
    )
    record_delivery(scenario["area"]["id"], 2)

    area = validate_success(api.complete_outreach(scenario["area"]["id"], ADMINISTRATOR), 200)

    assert area["outreach_status"] == "INSUFFICIENT"
    assert float(area["coverage_pct"]) == 50.00
    assert area["delivered_count"] == 2
    assert area["target_property_count"] == 4
    assert area["outreach_cycle_year"] == 2026
    assert area["outreach_crs_cycle_id"] == scenario["cycle"]["id"]
    assert area["status"] == "DESIGNATED"
    assert area["analysis_status"] == "ANALYZED"
