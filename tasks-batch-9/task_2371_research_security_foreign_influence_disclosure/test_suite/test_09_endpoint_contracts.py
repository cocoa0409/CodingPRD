"""Endpoint contracts: collection filters, pagination bounds, pure reads and the
immediacy of the designation cascade.

Every test builds its own data from scratch. The harness restarts the server before
each test, so the database is empty and the logical clock sits at its mandatory
startup default of 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    ADMIN,
    DEFAULT_CLOCK,
    LIAISON,
    RSO,
    ApiErrorId,
    add_personnel,
    create_access_grant,
    create_disclosure,
    create_incident,
    create_investigator,
    create_organization,
    create_project,
    create_subaward,
    create_support_statement,
    create_travel,
    assign_training,
    read_investigator,
    read_organization,
    screen_subaward,
    set_clock,
    setup_owned_organization_pair,
    validate_error,
    validate_paginated,
    validate_success,
)

PAGE = {"limit": 10, "offset": 0}


# --------------------------------------------------------------------------- #
# Local setup helpers for the collection-filter family
# --------------------------------------------------------------------------- #

def _setup_investigator_and_project():
    """One investigator and one CONTROLLED project with room in its controlled area."""
    investigator = create_investigator()
    project = create_project(
        title="Seismic Retrofit Study",
        agency_code="NSF",
        sensitivity_level="CONTROLLED",
        controlled_area_capacity=2,
    )
    return investigator, project


# --------------------------------------------------------------------------- #
# Ownership-graph link endpoint
# --------------------------------------------------------------------------- #

def test_subsidiaries_listing_returns_only_direct_children(api):
    """PRD §3.1: "Organizations can be listed and filtered by `country_code`, by
    `own_designation`, by `effective_designation` and by `parent_organization_id` — that
    last filter narrowing the list to one owner's direct holdings — and a dedicated read
    returns the direct children of a given organization in the ownership graph."

    Design: Corner/endpoints/subsidiaries_listing_returns_only_direct_children
    """
    root = create_organization(legal_name="Root Holdings", org_type="COMPANY")
    child_one = create_organization(
        legal_name="Child One",
        org_type="COMPANY",
        parent_organization_id=root["id"],
        parent_ownership_pct=100.00,
    )
    child_two = create_organization(
        legal_name="Child Two",
        org_type="COMPANY",
        parent_organization_id=root["id"],
        parent_ownership_pct=30.00,
    )
    grandchild = create_organization(
        legal_name="Grandchild Unit",
        org_type="INSTITUTE",
        parent_organization_id=child_one["id"],
        parent_ownership_pct=100.00,
    )

    items, meta = validate_paginated(
        api.list_subsidiaries(root["id"], LIAISON, params=dict(PAGE))
    )

    # One hop only: the grandchild is reachable through ownership imputation but is
    # not a direct child of the root.
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert [row["id"] for row in items] == [child_one["id"], child_two["id"]]
    assert grandchild["id"] not in [row["id"] for row in items]


# --------------------------------------------------------------------------- #
# Investigator roster filtering and pagination
# --------------------------------------------------------------------------- #

def test_investigator_roster_narrows_by_disclosure_posture(api):
    """PRD §3.1: "Reading an investigator returns all of those computed commitment, risk
    and posture fields; the roster of investigators can be narrowed by `appointment_type`
    and by `disclosure_posture`."

    Design: Corner/endpoints/investigators_list_filters_by_posture_and_paginates
    """
    first = create_investigator(full_name="Ines Prado", appointment_type="FACULTY")
    second = create_investigator(full_name="Jae Roh", appointment_type="POSTDOC")

    items, meta = validate_paginated(
        api.list_investigators(
            LIAISON, params={"disclosure_posture": "CLEAR", "limit": 1, "offset": 0}
        )
    )
    # limit truncates the page; total_count still counts the whole filtered set.
    assert len(items) == 1
    assert meta["total_count"] == 2
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["has_more"] is True
    assert items[0]["id"] == first["id"]
    assert items[0]["disclosure_posture"] == "CLEAR"

    empty, empty_meta = validate_paginated(
        api.list_investigators(
            LIAISON, params={"disclosure_posture": "RESTRICTED", **PAGE}
        )
    )
    assert empty == []
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False
    assert second["disclosure_posture"] == "CLEAR"


# --------------------------------------------------------------------------- #
# Pagination bounds
# --------------------------------------------------------------------------- #

def test_listing_limit_above_one_hundred_is_rejected(api):
    """PRD §2.3: "A `limit` outside the range 1 to 100 inclusive is a malformed request
    and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/endpoints/listing_limit_above_one_hundred_rejected
    """
    response = api.list_projects(LIAISON, params={"limit": 101, "offset": 0})
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


# --------------------------------------------------------------------------- #
# The logical clock and read-time derivation
# --------------------------------------------------------------------------- #

def test_clock_move_flips_training_status_without_writing_the_row(api):
    """PRD §2.4: "Moving the clock changes no stored field. In particular a security
    incident's frozen `notification_due_on` is untouched by a clock move, and a
    management plan's stored `plan_expires_on` is untouched. What does change is every
    value that is derived at read time — most visibly the computed `status` of a training
    assignment, which is re-evaluated against the clock on the next read of that
    assignment and on every rule that consults training compliance."

    Design: Corner/endpoints/clock_endpoint_moves_derived_training_status_without_touching_rows
    """
    set_clock(DEFAULT_CLOCK)
    investigator = create_investigator(full_name="Kofi Solberg", appointment_type="RESEARCH_STAFF")
    assignment = assign_training(
        investigator["id"], course_code="INSIDER_THREAT", due_on="2026-08-15T00:00:00Z"
    )

    before = validate_success(api.get_training_assignment(assignment["id"], ADMIN))
    assert before["status"] == "ASSIGNED"
    assert before["completed_on"] is None
    assert before["waived_on"] is None

    validate_success(
        api.set_clock({"current_utc": "2026-08-20T00:00:00Z"}, ADMIN), expected_status=200
    )

    after = validate_success(api.get_training_assignment(assignment["id"], ADMIN))
    assert after["status"] == "EXPIRED"
    assert after["completed_on"] is None
    assert after["waived_on"] is None
    # No write occurred, so the clock move left the stored row exactly as it was.
    assert after["version"] == before["version"]
    assert after["updated_at"] == before["updated_at"]

    # An institution-wide assignment reading EXPIRED breaks the investigator's compliance.
    assert read_investigator(investigator["id"])["training_compliant"] is False


# --------------------------------------------------------------------------- #
# Reads do not recompute-and-write
# --------------------------------------------------------------------------- #

def test_project_read_is_pure_and_repeatable(api):
    """PRD §3.9: "A project's `activation_blockers` list is recomputed on every change to
    its personnel, subawards, disclosures, support statements, training assignments or
    `security_status`, and is returned with the project on read."

    Design: Corner/endpoints/project_read_is_pure_and_repeatable
    """
    project = create_project(
        title="Idempotent Read Award",
        agency_code="NIH",
        controlled_area_capacity=2,
    )

    first = validate_success(api.get_project(project["id"], ADMIN))
    second = validate_success(api.get_project(project["id"], ADMIN))

    assert first["activation_blockers"] == ["SECURITY_NOT_CLEARED", "PERSONNEL_MISSING_PI"]
    assert second["activation_blockers"] == first["activation_blockers"]
    assert second["version"] == first["version"]
    assert second["updated_at"] == first["updated_at"]
    assert second == first


# --------------------------------------------------------------------------- #
# A conditionally required field on an action endpoint
# --------------------------------------------------------------------------- #

def test_subaward_mitigation_requires_a_justification(api):
    """PRD §3.6: "Mitigation is admissible from `FLAGGED → MITIGATED` and from `BLOCKED →
    MITIGATED`, and both paths carry exactly the same two conditions:
    `screening_designation` must not be `SDN`, else `ERR_RESTRICTED_ENTITY_BLOCKED` — a
    specially designated national is never mitigable, only terminated — and a
    `mitigation_justification` must be supplied, else `ERR_INVALID_REQUEST`."

    Design: Corner/endpoints/subaward_mitigation_requires_a_justification
    """
    organization = create_organization(
        legal_name="Ambiguous End User Ltd",
        country_code="MY",
        org_type="COMPANY",
        own_designation="UNVERIFIED_END_USER",
        designated_on="2025-08-01T00:00:00Z",
    )
    project = create_project(
        title="Instrumentation Buy", agency_code="DOE", award_amount_cents=22_000_000
    )
    subaward = create_subaward(
        project["id"], organization["id"], scope="Detector assembly", amount_cents=3_000_000
    )

    screened = screen_subaward(subaward["id"], "DIRECT_MATCH")
    assert screened["status"] == "FLAGGED"
    assert screened["screening_designation"] == "UNVERIFIED_END_USER"
    assert screened["screening_risk_points"] == 20
    assert screened["screening_match_depth"] == 0

    without_justification = api.set_subaward_status(
        subaward["id"], {"to_status": "MITIGATED"}, RSO
    )
    validate_error(
        without_justification, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
    )
    assert validate_success(api.get_subaward(subaward["id"], RSO))["status"] == "FLAGGED"

    justification = "End-use certificate obtained and export licence on file."
    mitigated = validate_success(
        api.set_subaward_status(
            subaward["id"],
            {"to_status": "MITIGATED", "mitigation_justification": justification},
            RSO,
        )
    )
    assert mitigated["status"] == "MITIGATED"
    assert mitigated["mitigation_justification"] == justification

    # A mitigated subaward is no longer PENDING, FLAGGED or BLOCKED.
    project_after = validate_success(api.get_project(project["id"], RSO))
    assert "SUBAWARD_BLOCKED" not in project_after["activation_blockers"]


# --------------------------------------------------------------------------- #
# Every collection endpoint filters by its declared query fields
# --------------------------------------------------------------------------- #

def test_organization_list_filters_by_country_code(api):
    """PRD §3.1: "Organizations can be listed and filtered by `country_code`, by
    `own_designation`, by `effective_designation` and by `parent_organization_id` — that
    last filter narrowing the list to one owner's direct holdings — and a dedicated read
    returns the direct children of a given organization in the ownership graph."

    Design: Corner/endpoints/every_collection_endpoint_filters_by_its_declared_query_fields
    """
    match = create_organization(
        legal_name="Pune Structures Ltd", country_code="IN", org_type="COMPANY"
    )
    create_organization(legal_name="Off-Filter Institute", country_code="CN")

    items, meta = validate_paginated(
        api.list_foreign_organizations(LIAISON, params={"country_code": "IN", **PAGE})
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert [row["id"] for row in items] == [match["id"]]


def test_personnel_list_filters_by_project_and_status(api):
    """PRD §3.2: "Personnel rows can be read individually and listed with filters on
    `project_id`, `investigator_id` and `status`; a `personnel_id` that does not resolve
    yields `ERR_PERSONNEL_NOT_FOUND`."

    Design: Corner/endpoints/every_collection_endpoint_filters_by_its_declared_query_fields
    """
    investigator, project = _setup_investigator_and_project()
    row = add_personnel(
        project["id"], investigator["id"], committed_person_months=2.00, activate=False
    )

    items, meta = validate_paginated(
        api.list_personnel(
            LIAISON, params={"project_id": project["id"], "status": "PROPOSED", **PAGE}
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [item["id"] for item in items] == [row["id"]]

    _, absent_meta = validate_paginated(
        api.list_personnel(
            LIAISON, params={"project_id": project["id"], "status": "ACTIVE", **PAGE}
        )
    )
    assert absent_meta["total_count"] == 0


def test_disclosure_list_filters_by_investigator_and_review_status(api):
    """PRD §3.3: "Disclosures can be read individually — exposing `review_status`,
    `plan_status`, `completeness_score` and `completeness_tier` — and listed with filters
    on `investigator_id`, `review_status` and `plan_status`."

    Design: Corner/endpoints/every_collection_endpoint_filters_by_its_declared_query_fields
    """
    investigator = create_investigator()
    disclosure = create_disclosure(investigator["id"])

    items, meta = validate_paginated(
        api.list_disclosures(
            LIAISON,
            params={
                "investigator_id": investigator["id"],
                "review_status": "DRAFT",
                **PAGE,
            },
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [item["id"] for item in items] == [disclosure["id"]]

    _, absent_meta = validate_paginated(
        api.list_disclosures(
            LIAISON,
            params={
                "investigator_id": investigator["id"],
                "review_status": "CERTIFIED",
                **PAGE,
            },
        )
    )
    assert absent_meta["total_count"] == 0


def test_support_statement_list_filters_by_investigator_and_status(api):
    """PRD §3.5: "Statements can be read individually — exposing the reconciliation
    verdict — and listed by `investigator_id`, `project_id` and `status`; an unresolvable
    `statement_id` yields `ERR_SUPPORT_STATEMENT_NOT_FOUND`."

    Design: Corner/endpoints/every_collection_endpoint_filters_by_its_declared_query_fields
    """
    investigator, project = _setup_investigator_and_project()
    statement = create_support_statement(
        investigator["id"],
        project["id"],
        agency_code="NSF",
        declared_person_months=2.00,
    )

    items, meta = validate_paginated(
        api.list_support_statements(
            LIAISON,
            params={
                "investigator_id": investigator["id"],
                "status": "SUBMITTED",
                **PAGE,
            },
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [item["id"] for item in items] == [statement["id"]]

    _, absent_meta = validate_paginated(
        api.list_support_statements(
            LIAISON,
            params={
                "investigator_id": investigator["id"],
                "status": "RECONCILED",
                **PAGE,
            },
        )
    )
    assert absent_meta["total_count"] == 0


def test_travel_registration_list_filters_by_investigator_and_status(api):
    """PRD §3.7: "Registrations can be read individually and listed by `investigator_id`,
    `project_id`, `host_organization_id` and `status`; an unresolvable `registration_id`
    yields `ERR_TRAVEL_REGISTRATION_NOT_FOUND`."

    Design: Corner/endpoints/every_collection_endpoint_filters_by_its_declared_query_fields
    """
    investigator = create_investigator()
    registration = create_travel(
        investigator["id"],
        destination_country_code="IN",
        depart_on="2026-11-02T00:00:00Z",
        return_on="2026-11-09T00:00:00Z",
    )

    items, meta = validate_paginated(
        api.list_travel_registrations(
            LIAISON,
            params={"investigator_id": investigator["id"], "status": "DRAFT", **PAGE},
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [item["id"] for item in items] == [registration["id"]]

    _, absent_meta = validate_paginated(
        api.list_travel_registrations(
            LIAISON,
            params={
                "investigator_id": investigator["id"],
                "status": "APPROVED",
                **PAGE,
            },
        )
    )
    assert absent_meta["total_count"] == 0


def test_access_grant_list_filters_by_project_and_status(api):
    """PRD §3.7: "Grants can be read individually — exposing `status`, `status_reason` and
    `peak_concurrency_at_request` — and listed by `project_id`, `investigator_id` and
    `status`; an unresolvable `grant_id` yields `ERR_ACCESS_GRANT_NOT_FOUND`."

    Design: Corner/endpoints/every_collection_endpoint_filters_by_its_declared_query_fields
    """
    investigator, project = _setup_investigator_and_project()
    grant = create_access_grant(project["id"], investigator["id"])

    items, meta = validate_paginated(
        api.list_access_grants(
            LIAISON, params={"project_id": project["id"], "status": "REQUESTED", **PAGE}
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [item["id"] for item in items] == [grant["id"]]

    _, absent_meta = validate_paginated(
        api.list_access_grants(
            LIAISON, params={"project_id": project["id"], "status": "ACTIVE", **PAGE}
        )
    )
    assert absent_meta["total_count"] == 0


def test_incident_list_filters_by_project_and_status(api):
    """PRD §3.8: "Incidents can be read individually, exposing `finding`, `severity`,
    `notification_due_on` and `notified_late`, and listed with filters on
    `investigator_id`, `disclosure_id`, `project_id` and `status`; an unresolvable
    `incident_id` yields `ERR_INCIDENT_NOT_FOUND`."

    Design: Corner/endpoints/every_collection_endpoint_filters_by_its_declared_query_fields
    """
    investigator, project = _setup_investigator_and_project()
    incident = create_incident(
        investigator["id"],
        incident_type="UNREPORTED_TRAVEL",
        discovered_on="2026-07-30T00:00:00Z",
        summary="Trip mentioned in a newsletter but never registered.",
        project_id=project["id"],
    )

    items, meta = validate_paginated(
        api.list_security_incidents(
            LIAISON, params={"project_id": project["id"], "status": "REPORTED", **PAGE}
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [item["id"] for item in items] == [incident["id"]]

    _, absent_meta = validate_paginated(
        api.list_security_incidents(
            LIAISON,
            params={"project_id": project["id"], "status": "INVESTIGATING", **PAGE},
        )
    )
    assert absent_meta["total_count"] == 0


def test_training_assignment_list_filters_by_investigator_and_course(api):
    """PRD §3.9: "Assignments can be read individually and listed by `investigator_id`,
    `required_for_project_id` and `course_code`; an unresolvable `assignment_id` yields
    `ERR_TRAINING_ASSIGNMENT_NOT_FOUND`."

    Design: Corner/endpoints/every_collection_endpoint_filters_by_its_declared_query_fields
    """
    investigator = create_investigator()
    assignment = assign_training(
        investigator["id"], course_code="EXPORT_CONTROL", due_on="2026-12-01T00:00:00Z"
    )
    assign_training(
        investigator["id"], course_code="INSIDER_THREAT", due_on="2026-12-01T00:00:00Z"
    )

    items, meta = validate_paginated(
        api.list_training_assignments(
            LIAISON,
            params={
                "investigator_id": investigator["id"],
                "course_code": "EXPORT_CONTROL",
                **PAGE,
            },
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [item["id"] for item in items] == [assignment["id"]]


def test_subaward_list_filters_by_project_and_status(api):
    """PRD §3.6: "Subawards can be read individually and listed by `project_id`,
    `organization_id` and `status`; an unresolvable `subaward_id` yields
    `ERR_SUBAWARD_NOT_FOUND`."

    Design: Corner/endpoints/every_collection_endpoint_filters_by_its_declared_query_fields
    """
    organization = create_organization(
        legal_name="Pune Structures Ltd", country_code="IN", org_type="COMPANY"
    )
    project = create_project(
        title="Seismic Retrofit Study", agency_code="NSF", sensitivity_level="CONTROLLED"
    )
    subaward = create_subaward(
        project["id"],
        organization["id"],
        scope="Field instrumentation",
        amount_cents=1_500_000,
    )

    items, meta = validate_paginated(
        api.list_subawards(
            LIAISON, params={"project_id": project["id"], "status": "PENDING", **PAGE}
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [item["id"] for item in items] == [subaward["id"]]

    # The status filter is applied rather than ignored.
    absent, absent_meta = validate_paginated(
        api.list_subawards(
            LIAISON, params={"project_id": project["id"], "status": "EXECUTED", **PAGE}
        )
    )
    assert absent == []
    assert absent_meta["total_count"] == 0
    assert absent_meta["has_more"] is False


# --------------------------------------------------------------------------- #
# Cascade immediacy
# --------------------------------------------------------------------------- #

def test_designation_cascade_is_visible_in_the_same_request(api):
    """PRD §3.1: "Because the organization's designation changed, `effective_designation`
    and `effective_designation_depth` are recomputed for every descendant reachable
    through hops of at least 50 percent ownership."

    Design: Corner/consistency_model/designation_cascade_is_visible_in_the_same_request
    """
    parent, child = setup_owned_organization_pair(
        parent_designation="NONE", child_designation="NONE", ownership_pct=100.00
    )
    for record in (parent, child):
        assert record["effective_designation"] == "NONE"
        assert record["effective_designation_depth"] == 0

    current = read_organization(parent["id"])
    designated = validate_success(
        api.designate_organization(
            parent["id"],
            {
                "own_designation": "ENTITY_LIST",
                "designated_on": DEFAULT_CLOCK,
                "expected_organization_version": current["version"],
            },
            RSO,
        )
    )
    # The write response already carries the parent's resolved designation.
    assert designated["own_designation"] == "ENTITY_LIST"
    assert designated["effective_designation"] == "ENTITY_LIST"
    assert designated["effective_designation_depth"] == 0

    # The very next read of the child converges with no intervening write or retry.
    child_after = validate_success(api.get_foreign_organization(child["id"], LIAISON))
    assert child_after["own_designation"] == "NONE"
    assert child_after["effective_designation"] == "ENTITY_LIST"
    assert child_after["effective_designation_depth"] == 1
