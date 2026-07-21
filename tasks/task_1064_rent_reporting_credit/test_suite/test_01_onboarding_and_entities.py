"""Onboarding, entity creation, required/type validation, and authentication.

Covers entity creation, required/type validation, and request authentication.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_tenant_headers,
    create_tenant_payload, create_enrollment_payload, create_score_snapshot_payload,
    assert_tenant, assert_score_snapshot,
    reset_clock_default, create_tenant,
)

ADMIN = TEST_USERS["admin_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


def test_create_tenant_returns_201_with_system_fields(api):
    """PRD §2.4: "a `version`, an integer that starts at 1 and increments by one
    on each mutation."
    PRD §3.1: "A tenant is onboarded with a legal `full_name`, a contact `email`
    that must be unique per tenant, and an optional `phone` that defaults to null
    when omitted."

    Design: Corner/entities/tenant_create_returns_201_with_system_fields
    """
    reset_clock_default(api)
    resp = api.create_tenant(ADMIN, create_tenant_payload(full_name="Ana New", email="ana@x.com"))
    data = validate_success(resp, 201)
    assert data["full_name"] == "Ana New"
    assert data["version"] == 1
    assert_tenant(data)


def test_get_nonexistent_tenant_returns_not_found(api):
    """PRD §2.9: "the server validates existence left to right, in the order the
    identifiers appear, and rejects the first unresolved reference with the
    matching not-found error (`ERR_TENANT_NOT_FOUND`, `ERR_LANDLORD_NOT_FOUND`,
    `ERR_PLAN_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`,
    `ERR_PAYMENT_NOT_FOUND`, `ERR_REPORTED_ITEM_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_BACK_REPORT_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND`)."

    Design: Corner/entities/tenant_get_nonexistent_returns_not_found
    """
    reset_clock_default(api)
    resp = api.get_tenant(ADMIN, NON_EXISTENT)
    validate_error(resp, ApiErrorId.ERR_TENANT_NOT_FOUND.value, 404)


def test_enrollment_missing_plan_id_returns_invalid_request(api):
    """PRD §3.2: "A tenant subscribes by enrolling on a plan, supplying the
    `tenant_id` and the chosen `plan_id`."
    PRD §2.9: "structural request validity — required fields present, enum values
    in range, and numeric fields within bounds such as a score in the range 300 to
    850, a `monthly_due_day` from 1 to 28, cents values at or above zero, and
    well-formed `YYYY-MM` month and ISO-8601 date strings (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/enrollment_missing_plan_id_returns_invalid_request
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Rea Req", email="rea@x.com")
    th = make_tenant_headers(tenant["id"])
    resp = api.create_enrollment(th, {"tenant_id": tenant["id"]})
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_score_snapshot_out_of_range_returns_invalid_request(api):
    """PRD §3.1: "the `score` itself as an integer in the range 300 to 850".
    PRD §2.9: "numeric fields within bounds such as a score in the range 300 to
    850, a `monthly_due_day` from 1 to 28, cents values at or above zero, and
    well-formed `YYYY-MM` month and ISO-8601 date strings (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/score_snapshot_out_of_range_returns_invalid_request
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Sam Score", email="sam@x.com")
    resp = api.create_score_snapshot(
        ADMIN, create_score_snapshot_payload(tenant["id"], bureau="EQUIFAX", score=900, as_of_month="2026-06"))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_score_snapshot_is_append_only_no_version_field(api):
    """PRD §2.4: "The score snapshot is an append-only reading and is therefore
    an exception: it carries only `id` and `created_at`, and has neither an
    `updated_at` field nor a `version` field, because it is never modified after
    ingestion."

    Design: Corner/entities/score_snapshot_immutable_no_version_field
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Ima Immut", email="ima@x.com")
    resp = api.create_score_snapshot(
        ADMIN, create_score_snapshot_payload(tenant["id"], bureau="EXPERIAN", score=705, as_of_month="2026-06"))
    data = validate_success(resp, 201)
    assert data["score"] == 705
    assert "version" not in data, "append-only snapshot must not carry a version field"
    assert_score_snapshot(data)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing or `X-User-Role` is not one of these
    five known roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Ann Anon", email="annx@x.com")
    resp = api.get_tenant({}, tenant["id"])  # no X-User-ID / X-User-Role headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
