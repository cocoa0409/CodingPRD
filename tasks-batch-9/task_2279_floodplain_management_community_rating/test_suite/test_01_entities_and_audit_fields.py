"""Entity shape, declared defaults, audit fields and referential integrity.

Every test builds its own communities, panels, parcels, structures, permits and
ledger rows from scratch through the endpoints the PRD declares.
"""
from test_helpers import (
    CLOCK_START_UTC,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_property,
    add_structure,
    append_record,
    assert_audit_fields,
    assert_community,
    assert_days_after,
    assert_identity_fields,
    assert_improvement_record,
    assert_structure,
    ApiErrorId,
    create_community_payload,
    create_permit_payload,
    create_property_payload,
    create_structure_payload,
    file_certificate,
    make_property_owner_headers,
    parse_instant,
    review_certificate,
    setup_approved_permit,
    setup_community_with_panel,
    setup_issued_permit,
    setup_parcel,
    setup_structure,
    start_permit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMINISTRATOR = TEST_USERS["administrator_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


# ==========================================================================
# Community registration: declared inputs and computed openers
# ==========================================================================

def test_community_creation_returns_declared_and_computed_fields(api):
    """PRD §3.1: "A freshly registered community starts with `sanction_risk_points` at 0,
    `compliance_posture` at `GOOD_STANDING`, `crs_credit_points_claimed` and
    `crs_credit_points_verified` at 0, `crs_class` at 10, `standards_adopted_at` set to
    the current logical clock, and `version` at 1."

    PRD §3.1: "A `StateNfipCoordinator` registers one by supplying the municipality's
    `name`, its two-letter `state_code`, and its NFIP `cid_number`, which must be unique
    across every community in the system — a repeat is rejected with
    `ERR_DUPLICATE_CID_NUMBER`."

    PRD §2.5: "It maintains a logical UTC clock whose startup value is exactly
    `2026-08-01T00:00:00Z`, and every timestamp it stamps, every deadline it computes,
    and every window comparison it makes reads that logical clock."

    Design: Corner/entities/community_creation_returns_declared_and_computed_fields
    """
    payload = create_community_payload(
        name="Bayou City",
        state_code="TX",
        cid_number="480001",
        freeboard_ft=2.0,
        cumulative_period_years=15,
    )

    community = validate_success(api.create_community(payload, COORDINATOR), 201)

    assert_community(community)
    assert community["name"] == "Bayou City"
    assert community["state_code"] == "TX"
    assert community["cid_number"] == "480001"
    assert float(community["freeboard_ft"]) == 2.0
    assert community["cumulative_period_years"] == 15
    assert community["sanction_risk_points"] == 0
    assert community["compliance_posture"] == "GOOD_STANDING"
    assert community["crs_class"] == 10
    assert community["crs_credit_points_claimed"] == 0
    assert community["crs_credit_points_verified"] == 0
    assert parse_instant(community["standards_adopted_at"]) == parse_instant(CLOCK_START_UTC)
    assert_audit_fields(community, "Community", expected_version=1)


def test_community_omitted_optional_fields_take_declared_defaults(api):
    """PRD §3.1: "Two adopted standards may be supplied at registration and both have
    defaults: `freeboard_ft`, the vertical margin the community requires above the base
    flood elevation, defaults to 1.0 and must lie between 0.0 and 6.0 inclusive with at
    most two decimal places; `cumulative_period_years`, the look-back window in whole
    years used by the cumulative substantial-improvement method, defaults to 10 and must
    lie between 0 and 25 inclusive, where 0 disables cumulative tracking entirely."

    PRD §3.1: "A freshly registered community starts with `sanction_risk_points` at 0,
    `compliance_posture` at `GOOD_STANDING`, `crs_credit_points_claimed` and
    `crs_credit_points_verified` at 0, `crs_class` at 10, `standards_adopted_at` set to
    the current logical clock, and `version` at 1."

    Design: Corner/entities/community_omitted_optional_fields_take_declared_defaults
    """
    payload = {"name": "Default Ville", "state_code": "LA", "cid_number": "220001"}

    community = validate_success(api.create_community(payload, COORDINATOR), 201)

    assert float(community["freeboard_ft"]) == 1.0
    assert community["cumulative_period_years"] == 10
    assert community["crs_class"] == 10


def test_community_freeboard_above_declared_maximum_is_rejected(api):
    """PRD §3.1: "Two adopted standards may be supplied at registration and both have
    defaults: `freeboard_ft`, the vertical margin the community requires above the base
    flood elevation, defaults to 1.0 and must lie between 0.0 and 6.0 inclusive with at
    most two decimal places; `cumulative_period_years`, the look-back window in whole
    years used by the cumulative substantial-improvement method, defaults to 10 and must
    lie between 0 and 25 inclusive, where 0 disables cumulative tracking entirely."

    PRD §2.8: "Any violation is `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/community_freeboard_above_declared_maximum_is_rejected
    """
    payload = {
        "name": "Too High",
        "state_code": "MS",
        "cid_number": "280001",
        "freeboard_ft": 6.5,
    }

    validate_error(api.create_community(payload, COORDINATOR), ApiErrorId.ERR_INVALID_REQUEST)


# ==========================================================================
# Structures: stored inputs, zeroed aggregates, and the two opening axes
# ==========================================================================

def test_structure_retrieval_returns_stored_and_zeroed_aggregate_fields(api):
    """PRD §3.3: "A new structure has `lowest_floor_elevation_ft` null,
    `substantial_status` `NONE`, `anchor_record_id` null, `cumulative_counted_cost_usd`,
    `cumulative_improvement_pct` and `single_event_improvement_pct` all 0, and `version`
    1."

    PRD §3.3: "At creation the axis starts at `PRE_FIRM_EXISTING` when `pre_firm` is
    true and at `PENDING_CERTIFICATE` otherwise."

    Design: Corner/entities/structure_retrieval_returns_stored_and_zeroed_aggregate_fields
    """
    scenario = setup_structure(
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={
            "structure_use": "RESIDENTIAL",
            "pre_firm": False,
            "construction_year": 1998,
            "market_value_usd": 200_000.00,
            "highest_adjacent_grade_ft": 10.0,
        },
    )

    structure = validate_success(
        api.get_structure(scenario["structure"]["id"], ADMINISTRATOR), 200
    )

    assert_structure(structure)
    assert structure["property_id"] == scenario["property"]["id"]
    assert structure["structure_use"] == "RESIDENTIAL"
    assert structure["pre_firm"] is False
    assert float(structure["market_value_usd"]) == 200_000.00
    assert float(structure["highest_adjacent_grade_ft"]) == 10.0
    assert structure["lowest_floor_elevation_ft"] is None
    assert structure["compliance_status"] == "PENDING_CERTIFICATE"
    assert structure["substantial_status"] == "NONE"
    assert structure["anchor_record_id"] is None
    assert float(structure["cumulative_counted_cost_usd"]) == 0
    assert float(structure["cumulative_improvement_pct"]) == 0.00
    assert float(structure["single_event_improvement_pct"]) == 0.00
    assert_audit_fields(structure, "Structure", expected_version=1)


def test_pre_firm_structure_starts_on_the_pre_firm_existing_branch(api):
    """PRD §3.3: "At creation the axis starts at `PRE_FIRM_EXISTING` when `pre_firm` is
    true and at `PENDING_CERTIFICATE` otherwise."

    PRD §3.3: "A new structure has `lowest_floor_elevation_ft` null,
    `substantial_status` `NONE`, `anchor_record_id` null, `cumulative_counted_cost_usd`,
    `cumulative_improvement_pct` and `single_event_improvement_pct` all 0, and `version`
    1."

    Design: Corner/entities/pre_firm_structure_starts_on_the_pre_firm_existing_branch
    """
    scenario = setup_parcel(community_overrides={"freeboard_ft": 1.5})

    payload = create_structure_payload(
        scenario["property"]["id"],
        structure_use="NON_RESIDENTIAL",
        pre_firm=True,
        construction_year=1962,
        market_value_usd=150_000.00,
        highest_adjacent_grade_ft=9.5,
    )
    structure = validate_success(api.create_structure(payload, ADMINISTRATOR), 201)

    assert structure["compliance_status"] == "PRE_FIRM_EXISTING"
    assert structure["substantial_status"] == "NONE"
    assert structure["lowest_floor_elevation_ft"] is None
    assert_audit_fields(structure, "Structure", expected_version=1)


def test_structure_create_without_market_value_is_rejected(api):
    """PRD §3.3: "On a parcel sit one or more `Structure` records, each created by the
    administrator with the parent `property_id`, a `structure_use` of `RESIDENTIAL`,
    `NON_RESIDENTIAL`, or `ACCESSORY`, a `pre_firm` flag that is true when construction
    predates the community's first FIRM, the `construction_year` of original
    construction, the `market_value_usd` of the structure excluding land — which must be
    strictly greater than 0 — and `highest_adjacent_grade_ft`, the highest adjacent
    grade in feet NAVD88 that serves as the datum for zone `AO` requirements."

    PRD §2.8: "Any violation is `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/structure_create_without_market_value_is_rejected
    """
    scenario = setup_parcel(community_overrides={"freeboard_ft": 1.5})

    payload = {
        "property_id": scenario["property"]["id"],
        "structure_use": "RESIDENTIAL",
        "pre_firm": False,
        "construction_year": 1998,
        "highest_adjacent_grade_ft": 10.0,
    }

    validate_error(
        api.create_structure(payload, ADMINISTRATOR), ApiErrorId.ERR_INVALID_REQUEST
    )


def test_structure_get_with_unknown_id_not_found(api):
    """PRD §2.8: "**Path existence** — each identifier in the URL is resolved left to
    right, and the first one that does not resolve determines the error: `communityId`
    raises `ERR_COMMUNITY_NOT_FOUND`, `panelId` raises `ERR_FIRM_PANEL_NOT_FOUND`,
    `propertyId` raises `ERR_PROPERTY_NOT_FOUND`, `structureId` raises
    `ERR_STRUCTURE_NOT_FOUND`, `permitId` raises `ERR_PERMIT_NOT_FOUND`,
    `certificateId` raises `ERR_CERTIFICATE_NOT_FOUND`, `recordId` raises
    `ERR_IMPROVEMENT_RECORD_NOT_FOUND`, `caseId` raises
    `ERR_DETERMINATION_CASE_NOT_FOUND`, `inspectionId` raises
    `ERR_INSPECTION_NOT_FOUND`, `violationId` raises `ERR_VIOLATION_NOT_FOUND`,
    `orderId` raises `ERR_ORDER_NOT_FOUND`, `areaId` raises `ERR_LOSS_AREA_NOT_FOUND`,
    `standardId` raises `ERR_HIGHER_STANDARD_NOT_FOUND`, and `cycleId` raises
    `ERR_CRS_CYCLE_NOT_FOUND`. All of these are HTTP 404."

    Design: Corner/entities/structure_get_with_unknown_id_not_found
    """
    validate_error(
        api.get_structure(NON_EXISTENT_UUID, ADMINISTRATOR),
        ApiErrorId.ERR_STRUCTURE_NOT_FOUND,
    )


# ==========================================================================
# List envelopes: pagination arithmetic and conjunctive filters
# ==========================================================================

def test_permit_listing_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "The four pagination fields `limit`, `offset`, `total_count`, and
    `has_more` appear in the `meta` object of every list response, where `total_count`
    counts the matching rows before the page window is applied and `has_more` indicates
    whether rows remain beyond the current window."

    PRD §2.2: The `response_type` is either "object" for a single resource or "array" for
    a list of resources.

    Design: Corner/entities/permit_listing_paginates_with_total_count_and_has_more
    """
    scenario = setup_structure(community_overrides={"freeboard_ft": 1.5})
    property_id = scenario["property"]["id"]
    structure_id = scenario["structure"]["id"]
    owner_headers = scenario["owner_headers"]

    for project_type, cost in (
        ("NEW_CONSTRUCTION", 20_000.00),
        ("IMPROVEMENT", 30_000.00),
        ("REPAIR", 40_000.00),
    ):
        start_permit(
            property_id,
            structure_id,
            owner_headers,
            project_type=project_type,
            declared_project_cost_usd=cost,
            proposed_lowest_floor_elevation_ft=20.0,
        )

    response = api.list_permits(
        ADMINISTRATOR, params={"property_id": property_id, "limit": 2, "offset": 0}
    )
    permits, meta = validate_paginated(response)

    assert len(permits) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert response.json()["response_type"] == "array"


def test_certificate_list_filter_by_status_excludes_other_statuses(api):
    """PRD §3.5: "The certificate list view doubles as the community's record-retention
    inventory, which is why it filters on `certificate_type` and `status` as well as on
    `permit_id` and `structure_id`."

    PRD §2.9: "Every filter is optional and combines conjunctively with the others and
    with `limit` and `offset`."

    PRD §3.5: "A `DEFICIENT` decision moves the certificate to `DEFICIENT` and records
    the supplied `deficiency_codes` verbatim."

    Design: Corner/entities/certificate_list_filter_by_status_excludes_other_statuses
    """
    scenario = setup_issued_permit(community_overrides={"freeboard_ft": 1.5})
    permit_id = scenario["permit"]["id"]
    structure_id = scenario["structure"]["id"]

    certificate_a = file_certificate(
        permit_id,
        structure_id,
        scenario["owner_headers"],
        certificate_type="BUILDING_UNDER_CONSTRUCTION",
        datum="NAVD88",
        measured_lowest_floor_ft=12.0,
        measured_bfe_ft=12.0,
    )
    review_certificate(certificate_a["id"], "DEFICIENT", deficiency_codes=["LOW_FLOOR"])
    file_certificate(
        permit_id,
        structure_id,
        scenario["owner_headers"],
        certificate_type="FINISHED_CONSTRUCTION",
        datum="NAVD88",
        measured_lowest_floor_ft=14.0,
        measured_bfe_ft=12.0,
        surveyor_license_no="TX-5511",
    )

    certificates, meta = validate_paginated(
        api.list_certificates(ADMINISTRATOR, params={"permit_id": permit_id, "status": "DEFICIENT"})
    )

    assert len(certificates) == 1
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert certificates[0]["id"] == certificate_a["id"]
    assert certificates[0]["status"] == "DEFICIENT"
    assert certificates[0]["deficiency_codes"] == ["LOW_FLOOR"]


# ==========================================================================
# System-stamped fields and the immutable ledger row
# ==========================================================================

def test_permit_issue_stamps_system_timestamps_and_derived_expiry(api):
    """PRD §3.4: "Issuance moves the permit to `ISSUED`, stamps `issued_at` with the
    current logical clock, and sets `expires_at` to 365 days after `issued_at`."

    PRD §2.5: "A permit's `expires_at` is its `issued_at` plus 365 days."

    PRD §2.5: "It maintains a logical UTC clock whose startup value is exactly
    `2026-08-01T00:00:00Z`, and every timestamp it stamps, every deadline it computes,
    and every window comparison it makes reads that logical clock."

    Design: Corner/entities/permit_issue_stamps_system_timestamps_and_derived_expiry
    """
    scenario = setup_approved_permit(
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 20_000.00,
            "proposed_lowest_floor_elevation_ft": 20.0,
        },
        community_overrides={"freeboard_ft": 1.5},
    )

    permit = validate_success(api.issue_permit(scenario["permit"]["id"], ADMINISTRATOR), 200)

    assert permit["status"] == "ISSUED"
    assert parse_instant(permit["issued_at"]) == parse_instant(CLOCK_START_UTC)
    assert parse_instant(permit["expires_at"]) == parse_instant("2027-08-01T00:00:00Z")
    assert_days_after(permit["expires_at"], permit["issued_at"], 365, "expires_at")


def test_improvement_record_is_immutable_and_carries_no_version(api):
    """PRD §2.4: "An `ImprovementRecord` is append-only and immutable in the eyes of
    clients: it carries `id` and `created_at` only." "It has no `updated_at` and no
    `version` field at all."

    PRD §3.6: "For a direct administrative append, `source` is `ADMIN_ADJUSTMENT` for an
    `IMPROVEMENT` or `DAMAGE` row and `REVERSAL_ADJUSTMENT` for a `REVERSAL`;
    `permit_id` and `inspection_id` are set only on the routes named above and are null
    otherwise."

    PRD §3.6: "Whether a row counts toward cumulative tracking is recorded on the row
    itself as `counted_in_cumulative`, and the rule is a conjunction of three
    conditions: the `record_type` must be `IMPROVEMENT` or `DAMAGE`,
    `is_code_compliance_only` must be false, and `cost_usd` must be at least 500.00."

    PRD §3.6: "Every other row carries `reversed` as false until that happens."

    PRD §3.6: "The record also carries `cost_usd`, the cost of the work or the damage;
    `market_value_at_event_usd`, a snapshot of the structure's `market_value_usd` taken
    at record creation, which is the denominator of both ratio methods;
    `claim_paid_amount_usd`, the NFIP claim paid for the event, defaulting to 0; and the
    optional `is_code_compliance_only` flag, defaulting to false, which marks work
    required solely to correct previously cited health and safety code violations."

    Design: Corner/entities/improvement_record_is_immutable_and_carries_no_version
    """
    scenario = setup_structure(
        community_overrides={"freeboard_ft": 1.5},
        structure_overrides={"market_value_usd": 200_000.00},
    )
    appended = append_record(
        scenario["structure"]["id"],
        record_type="IMPROVEMENT",
        event_date="2019-03-01T00:00:00Z",
        cost_usd=60_000.00,
    )

    record = validate_success(api.get_improvement_record(appended["id"], ADMINISTRATOR), 200)

    assert_improvement_record(record)
    assert_identity_fields(record, "ImprovementRecord")
    assert record["id"] == appended["id"]
    assert "version" not in record
    assert "updated_at" not in record
    assert record["source"] == "ADMIN_ADJUSTMENT"
    assert record["counted_in_cumulative"] is True
    assert record["reversed"] is False
    assert float(record["market_value_at_event_usd"]) == 200_000.00
    assert float(record["claim_paid_amount_usd"]) == 0
    assert record["is_code_compliance_only"] is False


# ==========================================================================
# Flat topology: body foreign keys and referential consistency
# ==========================================================================

def test_property_create_with_unknown_community_id_not_found(api):
    """PRD §2.8: "**Body foreign-key existence** — every identifier supplied in the body
    must resolve, raising that entity's own 404: `community_id`, `firm_panel_id`,
    `property_id`, `structure_id`, `permit_id`, `violation_id`, and `crs_cycle_id` raise
    their respective not-found errors, and a `reverses_record_id` that does not resolve
    raises `ERR_IMPROVEMENT_RECORD_NOT_FOUND`."

    Design: Corner/entities/property_create_with_unknown_community_id_not_found
    """
    base = setup_community_with_panel(community_overrides={"freeboard_ft": 1.5})

    payload = create_property_payload(
        NON_EXISTENT_UUID,
        base["panel"]["id"],
        parcel_id="P-0001",
        mapped_area_code="RLA-1",
        owner_name="A Owner",
        owner_email="a@example.com",
    )

    validate_error(
        api.create_property(payload, ADMINISTRATOR), ApiErrorId.ERR_COMMUNITY_NOT_FOUND
    )


def test_permit_create_with_structure_of_another_property_is_rejected(api):
    """PRD §3.4: "A `PropertyOwner` opens a `DevelopmentPermit` in `DRAFT` by naming the
    `property_id` it owns, the `structure_id` the work targets — which must belong to
    that property, else `ERR_STRUCTURE_PROPERTY_MISMATCH` — a `project_type` of
    `NEW_CONSTRUCTION`, `IMPROVEMENT`, or `REPAIR`, the `declared_project_cost_usd` of
    the work (at least 0), and the `proposed_lowest_floor_elevation_ft` the applicant
    intends to build to."

    PRD §2.8: "**Referential consistency of resolved references** (HTTP 422) — a
    permit's `structure_id` must belong to the supplied `property_id`, else
    `ERR_STRUCTURE_PROPERTY_MISMATCH`; a certificate's `structure_id` must equal its
    permit's `structure_id`, else `ERR_CERTIFICATE_STRUCTURE_MISMATCH`; a
    `reverses_record_id` must target a record of the same structure and must be present
    for a reversal and absent otherwise, else `ERR_REVERSAL_TARGET_INVALID`; and a
    `crs_cycle_id` supplied at outreach launch must belong to the same community as the
    area, else `ERR_CYCLE_COMMUNITY_MISMATCH`."

    Design: Corner/entities/permit_create_with_structure_of_another_property_is_rejected
    """
    scenario = setup_parcel(
        community_overrides={"freeboard_ft": 1.5}, property_overrides={"parcel_id": "P-0001"}
    )
    property_a = scenario["property"]
    property_b = add_property(
        scenario["community"]["id"],
        scenario["panel"]["id"],
        parcel_id="P-0002",
        owner_name="B Owner",
        owner_email="b@example.com",
    )
    structure_b = add_structure(property_b["id"], market_value_usd=200_000.00)

    payload = create_permit_payload(
        property_a["id"],
        structure_b["id"],
        project_type="NEW_CONSTRUCTION",
        declared_project_cost_usd=20_000.00,
        proposed_lowest_floor_elevation_ft=20.0,
    )

    validate_error(
        api.create_permit(payload, make_property_owner_headers(property_a["id"])),
        ApiErrorId.ERR_STRUCTURE_PROPERTY_MISMATCH,
    )
