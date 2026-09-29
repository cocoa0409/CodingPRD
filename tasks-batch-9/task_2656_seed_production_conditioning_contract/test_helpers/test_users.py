"""Canonical caller identities and per-role header builders."""

from __future__ import annotations

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Five of the six roles are opaque: any stable user id works. Grower is
# entity-backed, so a Grower caller's X-User-ID must be the grower's own id and
# has to be threaded in per test.
TEST_USERS: dict[str, dict[str, str]] = {
    "program_admin": {"user_id": "admin-1", "role": UserRole.PROGRAM_ADMIN.value},
    "program_admin_2": {"user_id": "admin-2", "role": UserRole.PROGRAM_ADMIN.value},
    "field_officer": {"user_id": "fo-1", "role": UserRole.FIELD_OFFICER.value},
    "field_officer_2": {"user_id": "fo-2", "role": UserRole.FIELD_OFFICER.value},
    "conditioning_manager": {"user_id": "cm-1", "role": UserRole.CONDITIONING_MANAGER.value},
    "conditioning_manager_2": {"user_id": "cm-2", "role": UserRole.CONDITIONING_MANAGER.value},
    "certification_agency": {"user_id": "agency-1", "role": UserRole.CERTIFICATION_AGENCY.value},
    "certification_agency_2": {"user_id": "agency-2", "role": UserRole.CERTIFICATION_AGENCY.value},
    "settlement_accountant": {"user_id": "acct-1", "role": UserRole.SETTLEMENT_ACCOUNTANT.value},
    "settlement_accountant_2": {"user_id": "acct-2", "role": UserRole.SETTLEMENT_ACCOUNTANT.value},
}

PROGRAM_ADMIN_ID = TEST_USERS["program_admin"]["user_id"]
PROGRAM_ADMIN_2_ID = TEST_USERS["program_admin_2"]["user_id"]
FIELD_OFFICER_ID = TEST_USERS["field_officer"]["user_id"]
FIELD_OFFICER_2_ID = TEST_USERS["field_officer_2"]["user_id"]
CONDITIONING_MANAGER_ID = TEST_USERS["conditioning_manager"]["user_id"]
CONDITIONING_MANAGER_2_ID = TEST_USERS["conditioning_manager_2"]["user_id"]
CERTIFICATION_AGENCY_ID = TEST_USERS["certification_agency"]["user_id"]
CERTIFICATION_AGENCY_2_ID = TEST_USERS["certification_agency_2"]["user_id"]
SETTLEMENT_ACCOUNTANT_ID = TEST_USERS["settlement_accountant"]["user_id"]
SETTLEMENT_ACCOUNTANT_2_ID = TEST_USERS["settlement_accountant_2"]["user_id"]


def make_headers(user_id: str, role: str) -> dict[str, str]:
    """Build request headers for an arbitrary user id / role pair."""
    return build_user_headers(user_id, role)


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_ID) -> dict[str, str]:
    return build_user_headers(user_id, UserRole.PROGRAM_ADMIN.value)


def make_field_officer_headers(user_id: str = FIELD_OFFICER_ID) -> dict[str, str]:
    return build_user_headers(user_id, UserRole.FIELD_OFFICER.value)


def make_conditioning_manager_headers(user_id: str = CONDITIONING_MANAGER_ID) -> dict[str, str]:
    return build_user_headers(user_id, UserRole.CONDITIONING_MANAGER.value)


def make_certification_agency_headers(user_id: str = CERTIFICATION_AGENCY_ID) -> dict[str, str]:
    return build_user_headers(user_id, UserRole.CERTIFICATION_AGENCY.value)


def make_settlement_accountant_headers(user_id: str = SETTLEMENT_ACCOUNTANT_ID) -> dict[str, str]:
    return build_user_headers(user_id, UserRole.SETTLEMENT_ACCOUNTANT.value)


def make_grower_headers(grower_id: str) -> dict[str, str]:
    """Grower callers are entity-backed: X-User-ID must be the grower's own id."""
    return build_user_headers(grower_id, UserRole.GROWER.value)


ROLE_HEADER_BUILDERS = {
    UserRole.PROGRAM_ADMIN.value: make_program_admin_headers,
    UserRole.FIELD_OFFICER.value: make_field_officer_headers,
    UserRole.CONDITIONING_MANAGER.value: make_conditioning_manager_headers,
    UserRole.CERTIFICATION_AGENCY.value: make_certification_agency_headers,
    UserRole.SETTLEMENT_ACCOUNTANT.value: make_settlement_accountant_headers,
    UserRole.GROWER.value: make_grower_headers,
}
