"""Pre-built auth headers per role, plus per-instance identity builders.

PRD 2.1: when `X-User-Role` is `AffiliateOperator`, `X-User-ID` is the `id` of
the acting `Affiliate`, so an operator's headers can only be built once the
affiliate exists.  For the other four roles `X-User-ID` is an opaque operator
identifier not tied to any persisted entity.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

FARM_DIRECTOR_USER_ID = "u-farm-1"
FARM_DIRECTOR_ALT_USER_ID = "u-farm-2"
MEDICAL_DIRECTOR_USER_ID = "u-med-1"
COMPLIANCE_OFFICER_USER_ID = "u-comp-1"
COMPLIANCE_OFFICER_ALT_USER_ID = "u-comp-2"
INTERNATIONAL_SCOUT_USER_ID = "u-scout-1"

# Shared headers for the four roles whose identity is opaque.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "farm_director": build_user_headers(FARM_DIRECTOR_USER_ID, Role.FARM_DIRECTOR.value),
    "farm_director_alt": build_user_headers(FARM_DIRECTOR_ALT_USER_ID, Role.FARM_DIRECTOR.value),
    "medical_director": build_user_headers(MEDICAL_DIRECTOR_USER_ID, Role.MEDICAL_DIRECTOR.value),
    "compliance_officer": build_user_headers(COMPLIANCE_OFFICER_USER_ID, Role.COMPLIANCE_OFFICER.value),
    "compliance_officer_alt": build_user_headers(COMPLIANCE_OFFICER_ALT_USER_ID, Role.COMPLIANCE_OFFICER.value),
    "international_scout": build_user_headers(INTERNATIONAL_SCOUT_USER_ID, Role.INTERNATIONAL_SCOUT.value),
}

FARM_DIRECTOR_HEADERS = TEST_USERS["farm_director"]
FARM_DIRECTOR_ALT_HEADERS = TEST_USERS["farm_director_alt"]
MEDICAL_DIRECTOR_HEADERS = TEST_USERS["medical_director"]
COMPLIANCE_OFFICER_HEADERS = TEST_USERS["compliance_officer"]
COMPLIANCE_OFFICER_ALT_HEADERS = TEST_USERS["compliance_officer_alt"]
INTERNATIONAL_SCOUT_HEADERS = TEST_USERS["international_scout"]


def make_farm_director_headers(user_id: str = FARM_DIRECTOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.FARM_DIRECTOR.value)


def make_medical_director_headers(user_id: str = MEDICAL_DIRECTOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.MEDICAL_DIRECTOR.value)


def make_compliance_officer_headers(user_id: str = COMPLIANCE_OFFICER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.COMPLIANCE_OFFICER.value)


def make_international_scout_headers(user_id: str = INTERNATIONAL_SCOUT_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.INTERNATIONAL_SCOUT.value)


def make_affiliate_operator_headers(affiliate_id: str) -> Dict[str, str]:
    """Headers for the operator of one specific club (identity is the club id)."""
    return build_user_headers(affiliate_id, Role.AFFILIATE_OPERATOR.value)


def headers_without_role(user_id: str = FARM_DIRECTOR_USER_ID) -> Dict[str, str]:
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = Role.FARM_DIRECTOR.value) -> Dict[str, str]:
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str = FARM_DIRECTOR_USER_ID) -> Dict[str, str]:
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = Role.FARM_DIRECTOR.value) -> Dict[str, str]:
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = FARM_DIRECTOR_USER_ID, role: str = "GeneralManager") -> Dict[str, str]:
    return build_user_headers(user_id, role)
