"""CRUD creation, system fields, not-found, required/type validation, RBAC,
auth, pagination, and immutability of append-only records.

Queue B (Corner) translations from sections: entities, endpoints, rbac.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    constants,
    factories as f,
    fixtures,
    build_user_headers,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]
MEMBER_FALLBACK = TEST_USERS["member_headers"]

RANDOM_UUID = "00000000-0000-4000-8000-000000000000"


def test_create_program_returns_201_with_system_fields(api):
    """PRD §2.4: "a `version`, an integer that begins at its initial value and
    increments by one on every mutation of the resource."
    PRD §2.4: "every `Program` owns a deterministic clock exposed as `current_utc`,
    which is initialized to the Unix epoch instant `1970-01-01T00:00:00.000Z` at
    program creation."
    PRD §3.1: "if the administrator does not supply this cap it defaults to 50."

    Design: Corner/entities/create_program_returns_201_with_system_fields
    """
    resp = api.create_program(f.create_program_payload(name="Prog"), ADMIN)
    data = validate_success(resp, 201)
    assert data["version"] == 1, f"new program version must be 1, got {data['version']}"
    assert data["current_utc"] == constants.EPOCH_UTC, (
        f"current_utc must be epoch, got {data['current_utc']}"
    )
    assert data["coach_max_active_members"] == 50, (
        f"default cap must be 50, got {data['coach_max_active_members']}"
    )


def test_get_member_nonexistent_returns_not_found(api):
    """PRD §2.5: "an unresolved member reference (path or body `member_id`) yields
    `ERR_MEMBER_NOT_FOUND`."

    Design: Corner/entities/get_member_nonexistent_returns_not_found
    """
    resp = api.get_member(RANDOM_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND.value, 404)


def test_create_member_missing_height_returns_invalid_request(api):
    """PRD §3.2: "A member is registered ... with an owning `program_id`, a
    `full_name`, an `email`, and a `height_cm` that must be strictly greater than
    zero."
    PRD §2.9: "any request supplying a value outside the permitted set for its
    field is malformed and rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_member_missing_height_returns_invalid_request
    """
    program = fixtures.create_program()
    payload = {"program_id": program["id"], "full_name": "M", "email": f.unique_email()}
    resp = api.create_member(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_create_plan_invalid_tier_returns_invalid_request(api):
    """PRD §2.9: "Plans are categorized by `tier`, which is exactly one of
    `COACHING`, `RX`, or `MEAL`."
    PRD §2.9: "These enumerations are fixed; any request supplying a value outside
    the permitted set for its field is malformed and rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_member_invalid_email_type_constraint
    """
    program = fixtures.create_program()
    payload = f.create_plan_payload(program["id"], tier="PREMIUM", name="X")
    resp = api.create_plan(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_weighin_immutable_no_version_field(api):
    """PRD §2.4: "Two entity types are append-only event records and deliberately
    carry **only** `id` and `created_at` — they have neither an `updated_at` nor a
    `version` field. The first is the weigh-in: once recorded, a weigh-in is never
    modified."

    Design: Corner/entities/weighin_immutable_no_version_field
    """
    ctx = fixtures.create_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    wi = fixtures.record_counted_weighin(enr_id, 92)
    resp = api.get_weighin(wi["id"], ADMIN)
    data = validate_success(resp, 200)
    assert "id" in data and "created_at" in data
    assert "version" not in data, "weigh-in must not carry a version field"
    assert "updated_at" not in data, "weigh-in must not carry an updated_at field"


def test_list_enrollments_pagination_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_enrollments_pagination_envelope
    """
    ctx = fixtures.create_pending_enrollment()
    member_id = ctx["member"]["id"]
    resp = api.list_enrollments(CLINICIAN, params={"member_id": member_id})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1, "at least one enrollment expected"
    assert meta["has_more"] is False, "single page must report has_more false"


def test_member_cannot_approve_intake(api):
    """PRD §4: the `approve` intake endpoint is authorized for `Clinician` only.
    PRD §2.1: "When the headers are valid but the role is not permitted to perform
    the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/member_cannot_approve_intake
    """
    program = fixtures.create_program()
    member = fixtures.create_member(program["id"])
    intake = fixtures.create_intake_under_review(member["id"])
    resp = api.approve_intake(intake["id"], fixtures.make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, 403)
    after = validate_success(api.get_intake(intake["id"], CLINICIAN), 200)
    assert after["status"] == "UNDER_REVIEW", "rejected call must not change state"


def test_clinician_cannot_create_enrollment(api):
    """PRD §4: `POST /wm/enrollments` is authorized for `ProgramAdmin` only.
    PRD §2.1: "When the headers are valid but the role is not permitted to perform
    the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/clinician_cannot_create_enrollment
    """
    program = fixtures.create_program()
    plan = fixtures.create_plan(program["id"])
    member = fixtures.create_member(program["id"])
    intake = fixtures.create_approved_intake(member["id"])
    resp = api.create_enrollment(
        f.create_enrollment_payload(member["id"], plan["id"], intake["id"]), CLINICIAN
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, 403)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "If either header is missing or invalid, the request is rejected
    with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    bad_headers = build_user_headers("someone", "NotARole")
    resp = api.create_program(f.create_program_payload(name="P"), bad_headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value, 401)
