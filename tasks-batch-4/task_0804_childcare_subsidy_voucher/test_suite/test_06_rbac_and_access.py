"""Role-based access control and entity-backed ownership (PRD §2.1).

Breadth coverage for role-permission denials, entity-backed ownership denial, and
missing-authentication rejection.
"""
from test_helpers import (
    validate_error, ApiErrorId,
    create_family, setup_active_authorization, register_provider,
    create_determination_payload, create_provider_payload,
    create_income_standard_payload, create_attendance_payload,
    make_provider_headers, make_family_headers, TEST_USERS,
)

CW = TEST_USERS["caseworker_headers"]


def test_provider_cannot_open_determination(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/provider_cannot_open_determination_returns_403
    """
    family = create_family()
    resp = api.create_determination(
        create_determination_payload(family["id"], "INITIAL"),
        make_provider_headers("some-provider"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_caseworker_cannot_register_provider(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/caseworker_cannot_register_provider_returns_403
    """
    resp = api.create_provider(create_provider_payload(
        name="X", provider_type="CENTER", published_daily_rate_cents=6_000,
        license_expiry_date="2027-01-01T00:00:00Z", state_code="CA"), CW)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_family_cannot_publish_income_standard(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/family_cannot_publish_income_standard_returns_403
    """
    resp = api.create_income_standard(
        create_income_standard_payload(household_size=3, entry_monthly_limit_cents=400_000,
                                       exit_monthly_limit_cents=500_000, state_code="CA"),
        make_family_headers("some-family"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_provider_cannot_submit_attendance_for_another_providers_authorization(api):
    """PRD §2.1: "An entity-backed caller that targets another party's resource is
    rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/provider_foreign_attendance_ownership_returns_403
    """
    ctx = setup_active_authorization()  # authorization owned by Provider A
    provider_b = register_provider(name="Provider B", published=5_500)
    resp = api.create_attendance_record(
        create_attendance_payload(ctx["authorization"]["id"], service_month="2026-03",
                                  present_days=18, absent_days=3),
        make_provider_headers(provider_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_read_family_without_auth_headers_returns_401(api):
    """PRD §2.1: "If either header is missing or its value is not recognized, the
    request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/family_read_missing_auth_returns_401
    """
    family = create_family()
    resp = api.get_family(family["id"], {})  # no X-User-ID / X-User-Role headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
