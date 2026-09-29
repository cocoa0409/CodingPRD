"""Pre-built role headers for every role in the PRD (§2.1).

`FacilityOperator` is the only entity-backed role: its `X-User-ID` must equal
the `operator_org` of the facility reached through the request path or body,
so ownership-gated calls MUST use `make_facility_operator_headers(operator_org)`.
The other five roles carry an opaque operator identifier that the server never
compares to any entity's id.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import TEST_DEFAULTS
from .types import UserRole

# Shared constants — safe for the five opaque roles, and for FacilityOperator
# only in tests that do not exercise the facility scope check.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "regulatory_reviewer_headers": build_user_headers(
        "reviewer_1", UserRole.REGULATORY_REVIEWER.value
    ),
    "facility_operator_headers": build_user_headers(
        TEST_DEFAULTS["OPERATOR_ORG"], UserRole.FACILITY_OPERATOR.value
    ),
    "qa_analyst_headers": build_user_headers("qa_1", UserRole.QA_ANALYST.value),
    "preparer_headers": build_user_headers(
        TEST_DEFAULTS["PREPARER_ONE"], UserRole.EMISSIONS_REPORT_PREPARER.value
    ),
    "second_preparer_headers": build_user_headers(
        TEST_DEFAULTS["PREPARER_TWO"], UserRole.EMISSIONS_REPORT_PREPARER.value
    ),
    "representative_headers": build_user_headers(
        TEST_DEFAULTS["REPRESENTATIVE_ONE"], UserRole.DESIGNATED_REPRESENTATIVE.value
    ),
    "second_representative_headers": build_user_headers(
        TEST_DEFAULTS["REPRESENTATIVE_TWO"], UserRole.DESIGNATED_REPRESENTATIVE.value
    ),
    "allowance_trader_headers": build_user_headers(
        "trader_1", UserRole.ALLOWANCE_TRADER.value
    ),
}


def make_facility_operator_headers(operator_org: str) -> Dict[str, str]:
    """Headers for the FacilityOperator of the facility whose `operator_org`
    equals `operator_org`. Required on every scope-checked write."""
    return build_user_headers(operator_org, UserRole.FACILITY_OPERATOR.value)


def make_regulatory_reviewer_headers(user_id: str = "reviewer_1") -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.REGULATORY_REVIEWER.value)


def make_qa_analyst_headers(user_id: str = "qa_1") -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.QA_ANALYST.value)


def make_preparer_headers(
    user_id: str = TEST_DEFAULTS["PREPARER_ONE"],
) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.EMISSIONS_REPORT_PREPARER.value)


def make_representative_headers(
    user_id: str = TEST_DEFAULTS["REPRESENTATIVE_ONE"],
) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.DESIGNATED_REPRESENTATIVE.value)


def make_allowance_trader_headers(user_id: str = "trader_1") -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.ALLOWANCE_TRADER.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identity/role pair — used by authentication tests."""
    return build_user_headers(user_id, role)


ROLE_HEADER_BUILDERS = {
    UserRole.REGULATORY_REVIEWER.value: make_regulatory_reviewer_headers,
    UserRole.FACILITY_OPERATOR.value: make_facility_operator_headers,
    UserRole.QA_ANALYST.value: make_qa_analyst_headers,
    UserRole.EMISSIONS_REPORT_PREPARER.value: make_preparer_headers,
    UserRole.DESIGNATED_REPRESENTATIVE.value: make_representative_headers,
    UserRole.ALLOWANCE_TRADER.value: make_allowance_trader_headers,
}
