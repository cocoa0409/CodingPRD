"""Authentication / RBAC primitives — header parsing + role helpers."""
from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import request

from .errors import err_auth_required, err_forbidden

# Canonical role spelling per PRD §2.1.
ROLE_PATIENT_PORTAL = "PatientPortalUser"
ROLE_PROVIDER = "Provider"
ROLE_NURSE = "Nurse"
ROLE_RECEPTIONIST = "Receptionist"
ROLE_BILLING_CLERK = "BillingClerk"
ROLE_PHARMACIST = "Pharmacist"
ROLE_CLINIC_ADMIN = "ClinicAdmin"
ROLE_TEST_HARNESS = "TestHarness"

ALL_ROLES = {
    ROLE_PATIENT_PORTAL,
    ROLE_PROVIDER,
    ROLE_NURSE,
    ROLE_RECEPTIONIST,
    ROLE_BILLING_CLERK,
    ROLE_PHARMACIST,
    ROLE_CLINIC_ADMIN,
    ROLE_TEST_HARNESS,
}

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def get_caller() -> tuple[str, str]:
    """Extract and validate X-User-ID / X-User-Role. Raises ERR_AUTH_REQUIRED if missing/invalid."""
    user_id = request.headers.get(HEADER_USER_ID, "")
    user_role = request.headers.get(HEADER_USER_ROLE, "")
    if not user_id or not user_role:
        raise err_auth_required(f"Headers {HEADER_USER_ID} and {HEADER_USER_ROLE} are required")
    if user_role not in ALL_ROLES:
        raise err_auth_required(f"Unknown role: {user_role}")
    return user_id, user_role


def require_roles(*allowed: str) -> Callable:
    """Decorator: validate auth headers AND check role is in `allowed`. Order: AUTH -> FORBIDDEN."""
    allowed_set = set(allowed)

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, user_role = get_caller()
            if user_role not in allowed_set:
                raise err_forbidden(f"Role '{user_role}' is not authorized for this endpoint")
            kwargs["_caller_id"] = user_id
            kwargs["_caller_role"] = user_role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_test_harness() -> Callable:
    """Decorator for /_clock/advance and /_sweep/run — these are exempt from the auth header check
    per PRD §2.9 (TestHarness role is exempt from authentication header check)."""
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # Test-only endpoints; do not require X-User-* headers
            return fn(*args, **kwargs)

        return wrapper

    return decorator
