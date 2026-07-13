"""Registration, defaults, computed fields, reads, listing, and RBAC.

Translates queue-B (corner) instances from the entities, errors, endpoints,
consistency_model, and rbac sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS, make_defendant_headers,
    create_defendant_payload, create_case_payload, create_charge_payload,
    create_diversion_payload, plea_payload,
    setup_arraigned_case, fetch_ledger,
)


def test_register_defendant_defaults_and_version(api, court_clerk_headers):
    """PRD §2.4: "an integer version that starts at 1 and increments by 1 on
    each mutation of that resource."
    PRD §3.2: "The clerk may also seed a known prior_diversion_count; when omitted
    it defaults to 0, and it may never be negative."

    Design: Corner/entities/defendant_creation_success
    """
    resp = api.create_defendant(
        create_defendant_payload(full_name="Val Create", email="val@x.com"),
        court_clerk_headers,
    )
    data = validate_success(resp, 201)
    assert is_valid_uuid(data["id"])
    assert data["prior_diversion_count"] == 0
    assert data["version"] == 1


def test_docket_case_missing_defendant_id_rejected(api, court_clerk_headers):
    """PRD §3.2: "The clerk dockets a citation by creating a case, supplying the
    defendant_id of the cited person, the issuing agency's citation_number, and
    the offense_date on which the cited offense occurred."
    PRD §2.9: "Body validation — required fields present, correct types, valid
    enum values, else ERR_VALIDATION (400)."

    Design: Corner/entities/case_create_missing_required_field_returns_400
    """
    resp = api._request(
        "POST", "/cases",
        {"citation_number": "C-9001", "offense_date": "2026-03-01"},
        court_clerk_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


def test_get_unknown_defendant_not_found(api, court_clerk_headers):
    """PRD §2.6: "Each resource type has its own not-found error: a missing case
    yields ERR_CASE_NOT_FOUND, a missing defendant ERR_DEFENDANT_NOT_FOUND"
    PRD §2.6: "All not-found errors carry HTTP 404."

    Design: Corner/entities/defendant_not_found_on_get
    """
    resp = api.get_defendant(NON_EXISTENT_UUID, court_clerk_headers)
    validate_error(resp, ApiErrorId.ERR_DEFENDANT_NOT_FOUND, 404)


def test_charge_defaults_diversion_eligible_true(api, court_clerk_headers):
    """PRD §3.2: "an is_diversion_eligible flag that defaults to true when omitted."

    Design: Corner/entities/charge_default_is_diversion_eligible_applied
    """
    defendant = validate_success(
        api.create_defendant(create_defendant_payload(email="deb@x.com"), court_clerk_headers), 201)
    case = validate_success(
        api.create_case(create_case_payload(defendant["id"], citation_number="C-9002"), court_clerk_headers), 201)
    resp = api.create_charge(
        case["id"],
        {"offense_code": "MC-14", "severity": "INFRACTION", "base_fine_amount": 50},
        court_clerk_headers,
    )
    charge = validate_success(resp, 201)
    assert charge["is_diversion_eligible"] is True


def test_case_arraignment_deadline_computed(api, court_clerk_headers):
    """PRD §3.2: "At docket time the system computes the case's
    arraignment_deadline: it takes the offense_date at midnight UTC (00:00:00Z)
    and adds the arraignment window of 30 days."

    Design: Corner/entities/case_arraignment_deadline_computed
    """
    defendant = validate_success(
        api.create_defendant(create_defendant_payload(email="cal@x.com"), court_clerk_headers), 201)
    resp = api.create_case(
        create_case_payload(defendant["id"], citation_number="C-9003", offense_date="2026-03-01"),
        court_clerk_headers,
    )
    case = validate_success(resp, 201)
    assert case["arraignment_deadline"].startswith("2026-03-31T00:00:00"), (
        f"expected deadline 2026-03-31T00:00:00Z, got {case['arraignment_deadline']}"
    )


def test_charge_invalid_severity_rejected(api, court_clerk_headers):
    """PRD §3.2: "a severity of either INFRACTION or MISDEMEANOR."
    PRD §2.9: "Body validation — required fields present, correct types, valid
    enum values, else ERR_VALIDATION (400)."

    Design: Corner/entities/charge_invalid_severity_returns_400
    """
    defendant = validate_success(
        api.create_defendant(create_defendant_payload(email="eve@x.com"), court_clerk_headers), 201)
    case = validate_success(
        api.create_case(create_case_payload(defendant["id"], citation_number="C-9004"), court_clerk_headers), 201)
    resp = api.create_charge(
        case["id"],
        {"offense_code": "MC-14", "severity": "FELONY", "base_fine_amount": 200},
        court_clerk_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


def test_list_charges_pagination_envelope(api, court_clerk_headers):
    """PRD §2.3: "total_count reports the total number of matching records across
    all pages, and has_more is true when records remain beyond the current page."

    Design: Corner/endpoints/charges_list_pagination_envelope
    """
    defendant = validate_success(
        api.create_defendant(create_defendant_payload(email="lis@x.com"), court_clerk_headers), 201)
    case = validate_success(
        api.create_case(create_case_payload(defendant["id"], citation_number="C-9016"), court_clerk_headers), 201)
    validate_success(api.create_charge(case["id"], create_charge_payload(), court_clerk_headers), 201)
    validate_success(
        api.create_charge(case["id"], create_charge_payload(offense_code="MC-15", severity="INFRACTION", base_fine_amount=30), court_clerk_headers), 201)

    resp = api.list_charges(case["id"], court_clerk_headers)
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_defendant_cases_reverse_lookup(api, court_clerk_headers):
    """PRD §3.2: "a defendant's cases can be listed through the reverse of the
    case's defendant_id relationship."

    Design: Corner/endpoints/cases_by_defendant_reverse_lookup
    """
    defendant = validate_success(
        api.create_defendant(create_defendant_payload(email="fk@x.com"), court_clerk_headers), 201)
    case = validate_success(
        api.create_case(create_case_payload(defendant["id"], citation_number="C-9017"), court_clerk_headers), 201)
    resp = api.list_defendant_cases(defendant["id"], court_clerk_headers)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == case["id"]
    assert data[0]["defendant_id"] == defendant["id"]


def test_get_unknown_case_not_found(api, court_clerk_headers):
    """PRD §2.6: "Each resource type has its own not-found error: a missing case
    yields ERR_CASE_NOT_FOUND, a missing defendant ERR_DEFENDANT_NOT_FOUND"
    PRD §2.6: "All not-found errors carry HTTP 404."

    Design: Corner/errors/case_not_found_on_get
    """
    resp = api.get_case(NON_EXISTENT_UUID, court_clerk_headers)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND, 404)


def test_created_case_immediately_visible(api, court_clerk_headers):
    """PRD §3.2: "A new case opens in DOCKETED status."
    PRD §2.2: "The response_type is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/consistency_model/immediate_visibility_of_created_case
    """
    defendant = validate_success(
        api.create_defendant(create_defendant_payload(email="imm@x.com"), court_clerk_headers), 201)
    resp = api.create_case(
        create_case_payload(defendant["id"], citation_number="C-9021"), court_clerk_headers)
    data = validate_success(resp, 201)
    assert resp.json()["response_type"] == "object"
    assert is_valid_uuid(data["id"])
    assert data["status"] == "DOCKETED"


def test_clerk_cannot_grant_diversion(api):
    """PRD §2.1: "If both headers are present but the named role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/clerk_cannot_grant_diversion_unauthorized
    """
    ctx = setup_arraigned_case(api, plea="GUILTY", citation_number="C-9018")
    # Granting diversion is a Judge-exclusive operation; the clerk is not authorized.
    resp = api.grant_diversion(
        ctx["case"]["id"], create_diversion_payload(mandated_service_hours=0),
        TEST_USERS["court_clerk_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_defendant_cannot_issue_warrant(api):
    """PRD §2.1: "If both headers are present but the named role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/defendant_cannot_issue_warrant_unauthorized
    """
    ctx = setup_arraigned_case(api, plea="GUILTY", citation_number="C-9019")
    judge = TEST_USERS["judge_headers"]
    validate_success(
        api.grant_diversion(ctx["case"]["id"], create_diversion_payload(mandated_service_hours=0), judge), 201)
    api.set_clock("2026-07-01T00:00:00Z", TEST_USERS["court_admin_headers"])
    # Issuing a warrant is Judge-exclusive; the defendant is not authorized.
    resp = api.issue_warrant(ctx["case"]["id"], ctx["def_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
