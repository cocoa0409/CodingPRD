"""Onboarding, CRUD defaults, computed fields, not-found and RBAC gates.

Translates Corner (breadth) instances from the entities, errors, rbac and
cross_cutting_complexity_layers sections.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    is_valid_uuid,
    create_applicant_payload, create_support_structure_payload,
    create_node_payload,
    assert_applicant, assert_support_structure,
    TEST_USERS, make_applicant_headers, build_user_headers,
    register_applicant, create_structure, create_segment, open_application,
    submit, add_node,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


def test_create_applicant_returns_201_and_defaults(api):
    """PRD §3.1: "the new applicant record is created with a `certification_status`
    of `REGISTERED` (the only standing this benchmark uses), with
    `master_agreement_signed` set to false and `master_agreement_signed_at` left null."
    PRD §2.4: "a `version`, an integer that begins at 1 and increments by one on each mutation."

    Design: Corner/entities/create_applicant_returns_201_and_defaults
    """
    res = api.create_applicant(
        create_applicant_payload(company_name="Acme Wireless", contact_email="ops@acme.example"),
        ADMIN,
    )
    data = validate_success(res, 201)
    assert_applicant(data)
    assert data["certification_status"] == "REGISTERED"
    assert data["master_agreement_signed"] is False
    assert data["version"] == 1
    assert is_valid_uuid(data["id"]) and "_" not in data["id"]


def test_get_applicant_not_found(api):
    """PRD §2.5: "The server validates those identifiers left to right and rejects
    the request at the first identifier that does not resolve, returning the
    not-found error specific to that resource kind: `ERR_APPLICANT_NOT_FOUND`,"

    Design: Corner/entities/get_applicant_not_found
    """
    res = api.get_applicant(UNKNOWN_UUID, ADMIN)
    validate_error(res, "ERR_APPLICANT_NOT_FOUND", 404)


def test_create_application_records_owner_and_starts_draft(api):
    """PRD §3.2: "the new application's `applicant_id` is taken from `X-User-ID`,
    and it begins life in `DRAFT`."

    Design: Corner/entities/create_application_missing_no_required_fields_but_records_owner
    """
    applicant = register_applicant(sign=False)
    res = api.create_application({"project_name": "Job"}, make_applicant_headers(applicant["id"]))
    data = validate_success(res, 201)
    assert data["status"] == "DRAFT"
    assert data["applicant_id"] == applicant["id"]


def test_node_computed_available_collocations(api):
    """PRD §2.7: "The computed `available_collocations` is always `max_collocations`
    minus `reserved_collocations` minus `active_collocations`. Both
    `reserved_collocations` and `active_collocations` start at 0."

    Design: Corner/entities/node_computed_available_collocations
    """
    res = api.create_support_structure(
        create_support_structure_payload(
            structure_type="EXISTING_UTILITY", max_collocations=3, in_design_district="NONE"
        ),
        ADMIN,
    )
    data = validate_success(res, 201)
    assert_support_structure(data)
    assert data["available_collocations"] == 3
    assert data["reserved_collocations"] == 0
    assert data["active_collocations"] == 0


def test_create_support_structure_invalid_enum(api):
    """PRD §2.10: "A malformed body — a missing required field, an invalid enum
    member, or a non-positive integer where a positive one is required — is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_support_structure_invalid_enum
    """
    res = api.create_support_structure(
        {"structure_type": "WOODEN", "max_collocations": 2}, ADMIN
    )
    validate_error(res, "ERR_INVALID_REQUEST", 422)


def test_add_node_missing_required_field(api):
    """PRD §2.10: "A malformed body — a missing required field, an invalid enum
    member, or a non-positive integer where a positive one is required — is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/add_node_missing_required_field
    """
    applicant = register_applicant(sign=False)
    segment = create_segment(corridor_code="K-1")
    app = open_application(applicant["id"])
    # support_structure_id omitted entirely.
    res = api.add_node(
        app["id"],
        {
            "facility_type": "COLLOCATION",
            "row_segment_id": segment["id"],
            "proposed_construction_date": "2026-06-15T00:00:00Z",
        },
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, "ERR_INVALID_REQUEST", 422)


def test_list_applications_paginated(api):
    """PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_applications_paginated
    """
    applicant = register_applicant(sign=False)
    open_application(applicant["id"])
    res = api.list_applications(
        make_applicant_headers(applicant["id"]), params={"applicant_id": applicant["id"]}
    )
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_node_not_found_on_design_review(api):
    """PRD §2.5: "The server validates those identifiers left to right and rejects
    the request at the first identifier that does not resolve, returning the
    not-found error specific to that resource kind: ... `ERR_NODE_NOT_FOUND`,"

    Design: Corner/errors/node_not_found_on_design_review
    """
    structure = create_structure(max_collocations=2)
    res = api.design_review(
        "11111111-1111-4111-8111-111111111111",
        {"outcome": "PASS", "expected_support_structure_version": structure["version"]},
        TEST_USERS["row_reviewer_headers"],
    )
    validate_error(res, "ERR_NODE_NOT_FOUND", 404)


def test_applicant_cannot_issue_decision(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/applicant_cannot_issue_decision
    """
    applicant = register_applicant()
    structure = create_structure(max_collocations=2)
    segment = create_segment(corridor_code="K-13")
    app = open_application(applicant["id"])
    add_node(app["id"], applicant["id"], structure["id"], segment["id"])
    submit(app["id"], applicant["id"])
    res = api.decide_application(app["id"], {}, make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", 403)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request missing either header, or presenting an `X-User-Role`
    that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    headers = build_user_headers("z-user", "NotARole")
    res = api.create_applicant(
        create_applicant_payload(company_name="Z", contact_email="z@z.example"), headers
    )
    validate_error(res, "ERR_UNAUTHENTICATED", 401)


def test_version_increments_on_signing_master_agreement(api):
    """PRD §3.1: "Executing the ROW master license agreement is an applicant-only
    act on the provider's own record: it sets `master_agreement_signed` to true
    and stamps `master_agreement_signed_at` with the current clock value,
    advancing the applicant's version."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_signing_master_agreement
    """
    res = api.create_applicant(
        create_applicant_payload(company_name="Chi", contact_email="c@c.example"), ADMIN
    )
    applicant = validate_success(res, 201)
    assert applicant["version"] == 1
    signed = validate_success(
        api.sign_master_agreement(applicant["id"], make_applicant_headers(applicant["id"])), 200
    )
    assert signed["master_agreement_signed"] is True
    assert signed["version"] == 2
