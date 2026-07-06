"""Authentication and role-based authorization (precedence steps 1 and 2)."""
import pytest
from test_helpers import (
    validate_error,
    ApiErrorId,
    create_dwelling_payload,
    create_job_payload,
    new_dwelling,
    new_job,
)

NONEXISTENT = "00000000-0000-4000-8000-000000000000"


def test_missing_x_user_role_returns_unauthenticated(api, anonymous_headers):
    """PRD 2.1: "A request that omits `X-User-Role` or presents a value that is
    not one of the recognized roles is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    Design: Corner/validations/missing_x_user_role_returns_unauthenticated
    """
    res = api.create_dwelling(create_dwelling_payload(), anonymous_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_installer_cannot_create_job_returns_forbidden(api, installer_headers):
    """PRD 2.1: "A request whose role is recognized but is not permitted to
    perform the requested operation is rejected with `ERR_FORBIDDEN` (HTTP
    403)."

    Design: Corner/validations/installer_cannot_create_job_returns_forbidden
    """
    dwelling = new_dwelling()
    res = api.create_job(
        create_job_payload(dwelling["id"], program_track="UTILITY", rebate_budget_cap_cents=100_000),
        installer_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_homeowner_cannot_verify_returns_forbidden(api, homeowner_headers):
    """PRD 2.1: "A request whose role is recognized but is not permitted to
    perform the requested operation is rejected with `ERR_FORBIDDEN` (HTTP
    403)."

    Design: Corner/rbac/homeowner_cannot_verify_returns_forbidden
    """
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    res = api.verify_job(job["id"], {"post_test_id": NONEXISTENT}, homeowner_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
