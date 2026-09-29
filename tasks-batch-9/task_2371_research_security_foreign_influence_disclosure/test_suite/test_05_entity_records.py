"""Entity records: stored inputs, declared defaults, derived fields at create time,
per-entity not-found codes, request-shape rejections and the ownership-graph guards.

Every test builds its own world from scratch: the server is restarted before each
test, so the database is empty and the logical clock sits at its mandatory startup
default of 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    ADMIN,
    LIAISON,
    NON_EXISTENT_UUID,
    RSO,
    ApiErrorId,
    add_disclosure_item,
    assert_disclosure,
    assert_disclosure_item,
    assert_foreign_organization,
    assert_investigator,
    assert_project,
    create_disclosure,
    create_disclosure_item_payload,
    create_foreign_organization_payload,
    create_investigator,
    create_investigator_payload,
    create_organization,
    create_personnel_payload,
    create_project,
    create_project_payload,
    make_investigator_headers,
    read_disclosure,
    read_investigator,
    read_organization,
    set_clock,
    set_item_status,
    setup_ownership_chain,
    submit_disclosure,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_investigator_registration_returns_the_declared_and_computed_record(api):
    """PRD §3.1: "A freshly registered investigator starts with `committed_effort_pct`
    at 0, `outside_effort_pct` at 0, a `total_commitment_pct` equal to their
    `institutional_base_effort_pct`, `overcommitment_pct` at 0, `risk_score` at 0,
    `substantiated_incident_count` at 0, `material_discrepancy_count` at 0,
    `training_compliant` true, and a `disclosure_posture` of `CLEAR`."

    Design: Corner/entities/investigator_create_returns_201_with_declared_fields
    """
    response = api.create_investigator(
        create_investigator_payload(
            full_name="Ada Reyes",
            email="ada.reyes@uni.edu",
            appointment_type="FACULTY",
            home_department="Bioinformatics",
            institutional_base_effort_pct=90,
        ),
        ADMIN,
    )
    investigator = validate_success(response, expected_status=201)
    assert_investigator(investigator)

    assert investigator["full_name"] == "Ada Reyes"
    assert investigator["email"] == "ada.reyes@uni.edu"
    assert investigator["appointment_type"] == "FACULTY"
    assert investigator["home_department"] == "Bioinformatics"

    assert investigator["institutional_base_effort_pct"] == pytest.approx(90, abs=0.01)
    assert investigator["committed_effort_pct"] == pytest.approx(0.00, abs=0.01)
    assert investigator["outside_effort_pct"] == pytest.approx(0.00, abs=0.01)
    assert investigator["total_commitment_pct"] == pytest.approx(90.00, abs=0.01)
    assert investigator["overcommitment_pct"] == pytest.approx(0.00, abs=0.01)

    assert investigator["risk_score"] == 0
    assert investigator["substantiated_incident_count"] == 0
    assert investigator["material_discrepancy_count"] == 0
    assert investigator["training_compliant"] is True
    assert investigator["disclosure_posture"] == "CLEAR"
    assert investigator["version"] == 1


def test_investigator_base_effort_defaults_to_a_full_year(api):
    """PRD §3.1: "Registration takes the investigator's `full_name`, their
    institutional `email`, an `appointment_type` of `FACULTY`, `RESEARCH_STAFF` or
    `POSTDOC`, their `home_department`, and optionally an
    `institutional_base_effort_pct` — the share of a full year the investigator
    already owes the institution, which must be between 0 and 100 inclusive and
    defaults to 100 when omitted."

    Design: Corner/entities/investigator_default_institutional_base_effort_pct_is_100
    """
    response = api.create_investigator(
        create_investigator_payload(
            full_name="Ben Solano",
            email="ben.solano@uni.edu",
            appointment_type="POSTDOC",
            home_department="Neuroscience",
        ),
        ADMIN,
    )
    investigator = validate_success(response, expected_status=201)
    assert_investigator(investigator)

    assert investigator["institutional_base_effort_pct"] == pytest.approx(100, abs=0.01)
    assert investigator["total_commitment_pct"] == pytest.approx(100.00, abs=0.01)
    assert investigator["overcommitment_pct"] == pytest.approx(0.00, abs=0.01)
    # A fully committed base effort is not by itself a posture trigger.
    assert investigator["disclosure_posture"] == "CLEAR"


def test_opening_a_disclosure_advances_the_investigator_version(api):
    """PRD §3.3: "The parent investigator's `version` increments by one."

    Design: Corner/entities/investigator_version_and_updated_at_advance_on_every_mutation
    """
    set_clock()
    created = create_investigator(
        full_name="Cleo Danforth",
        email="cleo.danforth@uni.edu",
        appointment_type="FACULTY",
        home_department="Linguistics",
    )
    before = read_investigator(created["id"])
    assert before["version"] == 1

    disclosure = create_disclosure(created["id"])
    assert_disclosure(disclosure)
    assert disclosure["version"] == 1

    after = read_investigator(created["id"])
    assert after["version"] == 2
    assert after["created_at"] == created["created_at"]
    assert after["updated_at"] >= after["created_at"]


def test_reading_a_new_project_exposes_its_derived_readiness_state(api):
    """PRD §3.2: "A new project computes its `activation_blockers` and its
    `controlled_area_posture` immediately, starts with `active_grant_count` at 0 and
    `open_incident_count` at 0, and — because a capacity of 0 means there is no
    controlled area to enter — a default-capacity project is `LOCKED_DOWN` from birth."

    Design: Corner/entities/project_get_returns_stored_and_derived_fields
    """
    project = create_project(
        title="Coastal Sensor Network",
        agency_code="NSF",
        sensitivity_level="STANDARD",
        award_amount_cents=30_000_000,
        period_start="2026-09-01T00:00:00Z",
        period_end="2028-08-31T00:00:00Z",
        controlled_area_capacity=2,
    )

    fetched = validate_success(api.get_project(project["id"], LIAISON))
    assert_project(fetched)

    assert fetched["title"] == "Coastal Sensor Network"
    assert fetched["agency_code"] == "NSF"
    assert fetched["sensitivity_level"] == "STANDARD"
    assert fetched["award_amount_cents"] == 30_000_000
    assert fetched["award_status"] == "PROPOSED"
    assert fetched["security_status"] == "PENDING_CLEARANCE"
    assert fetched["security_status_reason"] == "NONE"

    assert fetched["activation_blockers"] == [
        "SECURITY_NOT_CLEARED",
        "PERSONNEL_MISSING_PI",
    ]
    assert fetched["active_grant_count"] == 0
    assert fetched["controlled_area_posture"] == "OPEN"
    assert fetched["open_incident_count"] == 0


def test_disclosure_item_roster_filters_by_disclosure_and_status(api):
    """PRD §3.3: "Items can be read individually and listed with filters on
    `disclosure_id`, `foreign_organization_id` and `status`; an unresolvable `item_id`
    yields `ERR_DISCLOSURE_ITEM_NOT_FOUND`."

    Design: Corner/entities/disclosure_items_list_filters_and_paginates
    """
    investigator = create_investigator(
        full_name="Dara Eze",
        email="dara.eze@uni.edu",
        appointment_type="FACULTY",
        home_department="Sociology",
    )
    organization = create_organization(
        legal_name="Neutral Academy",
        country_code="SG",
        org_type="UNIVERSITY",
        own_designation="NONE",
    )
    disclosure = create_disclosure(investigator["id"])
    declared_item = add_disclosure_item(
        disclosure["id"],
        organization["id"],
        investigator_id=investigator["id"],
        item_type="FOREIGN_APPOINTMENT",
        start_date="2025-01-05T00:00:00Z",
        annual_effort_hours=0,
        is_paid=False,
    )
    disputed_item = add_disclosure_item(
        disclosure["id"],
        organization["id"],
        investigator_id=investigator["id"],
        item_type="OUTSIDE_SUPPORT",
        start_date="2025-02-05T00:00:00Z",
        annual_effort_hours=0,
        is_paid=False,
    )
    submit_disclosure(disclosure["id"], investigator["id"])
    set_item_status(disputed_item["id"], "DISPUTED")

    items, meta = validate_paginated(
        api.list_disclosure_items(
            RSO,
            params={
                "disclosure_id": disclosure["id"],
                "status": "DECLARED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert len(items) == 1
    assert items[0]["id"] == declared_item["id"]
    assert items[0]["status"] == "DECLARED"

    # A DISPUTED item still counts toward the parent's item_count.
    assert read_disclosure(disclosure["id"])["item_count"] == 2


def test_reading_an_unknown_access_grant_reports_the_grant_not_found(api):
    """PRD §3.7: "Grants can be read individually — exposing `status`, `status_reason`
    and `peak_concurrency_at_request` — and listed by `project_id`, `investigator_id`
    and `status`; an unresolvable `grant_id` yields `ERR_ACCESS_GRANT_NOT_FOUND`."

    Design: Corner/entities/access_grant_get_unknown_id_returns_404_not_found
    """
    response = api.get_access_grant(NON_EXISTENT_UUID, RSO)
    validate_error(
        response, ApiErrorId.ERR_ACCESS_GRANT_NOT_FOUND.value, expected_status=404
    )

    _items, meta = validate_paginated(api.list_access_grants(RSO))
    assert meta["total_count"] == 0


def test_disclosure_without_a_cycle_label_is_rejected(api):
    """PRD §2.8: "Request shape — required fields present, enum values inside their
    declared member sets, numeric ranges honoured (`parent_ownership_pct` between 0
    and 100 inclusive, `committed_person_months` greater than 0 and at most 12,
    `annual_effort_hours` between 0 and 2,080 inclusive, `amount_cents` strictly
    greater than 0, `controlled_area_capacity` at least 0), and `limit` within 1 to
    100. Applies to every endpoint; failure is `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/disclosure_create_missing_required_cycle_label_returns_400
    """
    investigator = create_investigator(
        full_name="Emre Falk",
        email="emre.falk@uni.edu",
        appointment_type="FACULTY",
        home_department="Geology",
    )
    current = read_investigator(investigator["id"])
    assert current["version"] == 1

    response = api.create_disclosure(
        {
            "investigator_id": investigator["id"],
            "disclosure_type": "ANNUAL",
            "expected_investigator_version": current["version"],
        },
        make_investigator_headers(investigator["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    _items, meta = validate_paginated(
        api.list_disclosures(ADMIN, params={"investigator_id": investigator["id"]})
    )
    assert meta["total_count"] == 0
    # The rejected create never touched the parent investigator.
    assert read_investigator(investigator["id"])["version"] == 1


def test_item_risk_points_are_computed_from_type_and_designation(api):
    """PRD §3.3: "Start from the base weight of the `item_type`: 12 for
    `FOREIGN_APPOINTMENT`, 30 for `TALENT_PROGRAM`, 8 for `OUTSIDE_SUPPORT`, 6 for
    `IN_KIND_RESOURCE` and 10 for `VISITING_SCHOLAR`. Multiply that base by the
    counterparty's exposure multiplier, read from the referenced organization's
    `effective_designation`: 1.0 for `NONE`, 1.5 for `UNVERIFIED_END_USER`, 2.0 for
    `ENTITY_LIST`, 2.5 for `FOREIGN_MILITARY`, and 3.0 for both
    `MALIGN_TALENT_PROGRAM` and `SDN`."

    Design: Corner/entities/disclosure_item_risk_points_computed_on_create
    """
    set_clock()
    organization = create_organization(
        legal_name="Listed Systems Institute",
        country_code="CN",
        org_type="INSTITUTE",
        own_designation="ENTITY_LIST",
        designated_on="2025-05-01T00:00:00Z",
    )
    investigator = create_investigator(
        full_name="Gita Halim",
        email="gita.halim@uni.edu",
        appointment_type="FACULTY",
        home_department="Computer Science",
    )
    disclosure = create_disclosure(investigator["id"])

    response = api.create_disclosure_item(
        disclosure["id"],
        create_disclosure_item_payload(
            organization["id"],
            item_type="FOREIGN_APPOINTMENT",
            start_date="2025-01-05T00:00:00Z",
            annual_effort_hours=0,
            is_paid=False,
        ),
        make_investigator_headers(investigator["id"]),
    )
    item = validate_success(response, expected_status=201)
    assert_disclosure_item(item)

    # 12 for FOREIGN_APPOINTMENT multiplied by 2.0 for ENTITY_LIST, unpaid.
    assert item["item_risk_points"] == 24
    assert item["status"] == "DECLARED"
    assert item["source"] == "SELF_REPORTED"

    parent = read_disclosure(disclosure["id"])
    assert parent["item_count"] == 1
    assert parent["late_item_count"] == 0
    assert parent["undisclosed_item_count"] == 0
    assert parent["completeness_score"] == 100
    assert parent["completeness_tier"] == "A"

    # Only VERIFIED items enter the risk and outside-effort input sets.
    subject = read_investigator(investigator["id"])
    assert subject["risk_score"] == 0
    assert subject["outside_effort_pct"] == pytest.approx(0.00, abs=0.01)


def test_project_with_an_unlisted_agency_code_is_rejected(api):
    """PRD §3.2: "A sponsored project is created by a `SystemAdmin` with a `title`, an
    `agency_code` of `NIH`, `NSF`, `DOD`, `DOE` or `NASA`, a `sensitivity_level` of
    `STANDARD`, `CONTROLLED` or `RESTRICTED`, a total obligated `award_amount_cents`
    of at least 0, a `period_start`, a `period_end` that must fall strictly after
    `period_start` (otherwise `ERR_INVALID_PERIOD`, HTTP 422), and optionally a
    `controlled_area_capacity` — the maximum number of investigators allowed
    concurrent access to the project's controlled research area, at least 0 and
    defaulting to 0."

    Design: Corner/entities/project_create_invalid_enum_agency_code_rejected
    """
    response = api.create_project(
        create_project_payload(
            title="Unsponsored Study",
            agency_code="ONR",
            sensitivity_level="STANDARD",
            award_amount_cents=10_000_000,
            period_start="2026-09-01T00:00:00Z",
            period_end="2028-08-31T00:00:00Z",
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    _items, meta = validate_paginated(api.list_projects(ADMIN))
    assert meta["total_count"] == 0


def test_project_period_must_end_after_it_starts(api):
    """PRD §3.2: "A sponsored project is created by a `SystemAdmin` with a `title`, an
    `agency_code` of `NIH`, `NSF`, `DOD`, `DOE` or `NASA`, a `sensitivity_level` of
    `STANDARD`, `CONTROLLED` or `RESTRICTED`, a total obligated `award_amount_cents`
    of at least 0, a `period_start`, a `period_end` that must fall strictly after
    `period_start` (otherwise `ERR_INVALID_PERIOD`, HTTP 422), and optionally a
    `controlled_area_capacity` — the maximum number of investigators allowed
    concurrent access to the project's controlled research area, at least 0 and
    defaulting to 0."

    Design: Corner/entities/project_period_end_before_start_rejected
    """
    response = api.create_project(
        create_project_payload(
            title="Backwards Award",
            agency_code="NIH",
            sensitivity_level="STANDARD",
            award_amount_cents=10_000_000,
            period_start="2027-09-01T00:00:00Z",
            period_end="2027-09-01T00:00:00Z",
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_PERIOD.value, expected_status=422)

    _items, meta = validate_paginated(api.list_projects(ADMIN))
    assert meta["total_count"] == 0


def test_personnel_added_under_an_unknown_project_reports_project_not_found(api):
    """PRD §2.8: "Foreign keys carried in a request body are resolved after the path,
    in the order the fields are declared in that endpoint's input list. The not-found
    codes are `ERR_INVESTIGATOR_NOT_FOUND`, `ERR_ORGANIZATION_NOT_FOUND` (covering
    `organization_id`, `parent_organization_id`, `foreign_organization_id` and
    `host_organization_id`), `ERR_PROJECT_NOT_FOUND` (covering `project_id` and
    `required_for_project_id`), `ERR_PERSONNEL_NOT_FOUND`,
    `ERR_DISCLOSURE_NOT_FOUND`, `ERR_DISCLOSURE_ITEM_NOT_FOUND`,
    `ERR_SUPPORT_STATEMENT_NOT_FOUND`, `ERR_TRAVEL_REGISTRATION_NOT_FOUND`,
    `ERR_ACCESS_GRANT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
    `ERR_TRAINING_ASSIGNMENT_NOT_FOUND` and `ERR_SUBAWARD_NOT_FOUND` — all HTTP 404."

    Design: Corner/entities/personnel_create_under_unknown_project_returns_404_not_found
    """
    response = api.create_personnel(
        NON_EXISTENT_UUID,
        create_personnel_payload(
            "11111111-1111-1111-1111-111111111111",
            role_on_project="PI",
            committed_person_months=1.00,
        ),
        ADMIN,
    )
    validate_error(
        response, ApiErrorId.ERR_PROJECT_NOT_FOUND.value, expected_status=404
    )

    _items, meta = validate_paginated(api.list_personnel(ADMIN))
    assert meta["total_count"] == 0


def test_ownership_edge_that_closes_a_loop_is_refused(api):
    """PRD §2.10: "If that parent is already on the visited set, the graph is cyclic
    and the write is rejected with `ERR_OWNERSHIP_CYCLE` (HTTP 422)."

    Design: Corner/entities/organization_ownership_cycle_rejected
    """
    owner = create_organization(
        legal_name="Circular Holdings",
        country_code="CN",
        org_type="COMPANY",
        own_designation="NONE",
    )
    subsidiary = create_organization(
        legal_name="Circular Subsidiary",
        country_code="CN",
        org_type="COMPANY",
        own_designation="NONE",
        parent_organization_id=owner["id"],
        parent_ownership_pct=100.00,
    )

    response = api.set_organization_ownership(
        owner["id"],
        {
            "parent_organization_id": subsidiary["id"],
            "parent_ownership_pct": 100.00,
        },
        RSO,
    )
    validate_error(response, ApiErrorId.ERR_OWNERSHIP_CYCLE.value, expected_status=422)

    unchanged_owner = read_organization(owner["id"])
    assert_foreign_organization(unchanged_owner)
    assert unchanged_owner["parent_organization_id"] is None

    unchanged_subsidiary = read_organization(subsidiary["id"])
    assert unchanged_subsidiary["effective_designation"] == "NONE"
    assert unchanged_subsidiary["effective_designation_depth"] == 0


def test_ownership_chain_of_nine_controlling_hops_is_refused(api):
    """PRD §2.10: "Add the parent to the visited set and increase the hop count by
    one; if the hop count now exceeds eight, the chain is too deep and the write is
    rejected with `ERR_OWNERSHIP_DEPTH_EXCEEDED` (HTTP 422)."

    Design: Corner/entities/organization_ownership_depth_beyond_eight_hops_rejected
    """
    chain = setup_ownership_chain(8, top_designation="NONE", ownership_pct=100.00)
    assert len(chain) == 9
    deepest = chain[-1]
    assert_foreign_organization(deepest)
    assert deepest["effective_designation"] == "NONE"
    assert deepest["effective_designation_depth"] == 0

    response = api.create_foreign_organization(
        create_foreign_organization_payload(
            legal_name="Chain Level 9",
            country_code="RU",
            org_type="COMPANY",
            own_designation="NONE",
            parent_organization_id=deepest["id"],
            parent_ownership_pct=100.00,
        ),
        RSO,
    )
    validate_error(
        response, ApiErrorId.ERR_OWNERSHIP_DEPTH_EXCEEDED.value, expected_status=422
    )

    _items, meta = validate_paginated(
        api.list_foreign_organizations(RSO, params={"limit": 100})
    )
    assert meta["total_count"] == 9
