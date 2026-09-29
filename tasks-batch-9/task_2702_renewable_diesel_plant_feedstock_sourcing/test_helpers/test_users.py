"""Pre-built auth headers for every role.

Five of the six roles carry an opaque `X-User-ID`; only `Supplier` is
entity-backed, so supplier-scoped calls MUST use `make_supplier_headers(id)`
with the id of the supplier row the caller is acting as.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_FEEDSTOCK_TRADER,
    ROLE_INDEPENDENT_VERIFIER,
    ROLE_PLANT_OPERATOR,
    ROLE_QUALITY_ANALYST,
    ROLE_SUPPLIER,
)

# --- opaque-identity roles ---------------------------------------------------
OPERATOR_HEADERS = build_user_headers("operator-1", ROLE_PLANT_OPERATOR)
OPERATOR_B_HEADERS = build_user_headers("operator-2", ROLE_PLANT_OPERATOR)
TRADER_HEADERS = build_user_headers("trader-1", ROLE_FEEDSTOCK_TRADER)
TRADER_B_HEADERS = build_user_headers("trader-2", ROLE_FEEDSTOCK_TRADER)
ANALYST_HEADERS = build_user_headers("analyst-1", ROLE_QUALITY_ANALYST)
OFFICER_A_HEADERS = build_user_headers("officer-a", ROLE_COMPLIANCE_OFFICER)
OFFICER_B_HEADERS = build_user_headers("officer-b", ROLE_COMPLIANCE_OFFICER)
VERIFIER_HEADERS = build_user_headers("verifier-1", ROLE_INDEPENDENT_VERIFIER)
VERIFIER_B_HEADERS = build_user_headers("verifier-2", ROLE_INDEPENDENT_VERIFIER)

OFFICER_A_USER_ID = "officer-a"
OFFICER_B_USER_ID = "officer-b"
VERIFIER_USER_ID = "verifier-1"

TEST_USERS = {
    ROLE_PLANT_OPERATOR: OPERATOR_HEADERS,
    ROLE_FEEDSTOCK_TRADER: TRADER_HEADERS,
    ROLE_QUALITY_ANALYST: ANALYST_HEADERS,
    ROLE_COMPLIANCE_OFFICER: OFFICER_A_HEADERS,
    ROLE_INDEPENDENT_VERIFIER: VERIFIER_HEADERS,
}


def make_operator_headers(user_id: str) -> dict:
    """Headers for a PlantOperator with a chosen opaque user id."""
    return build_user_headers(user_id, ROLE_PLANT_OPERATOR)


def make_trader_headers(user_id: str) -> dict:
    """Headers for a FeedstockTrader with a chosen opaque user id."""
    return build_user_headers(user_id, ROLE_FEEDSTOCK_TRADER)


def make_analyst_headers(user_id: str) -> dict:
    """Headers for a QualityAnalyst with a chosen opaque user id."""
    return build_user_headers(user_id, ROLE_QUALITY_ANALYST)


def make_officer_headers(user_id: str) -> dict:
    """Headers for a ComplianceOfficer with a chosen opaque user id.

    Segregation-of-duties rules compare acting user ids, so credit-block and
    pathway flows need at least two distinct officers.
    """
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_verifier_headers(user_id: str) -> dict:
    """Headers for an IndependentVerifier with a chosen opaque user id."""
    return build_user_headers(user_id, ROLE_INDEPENDENT_VERIFIER)


def make_supplier_headers(supplier_id: str) -> dict:
    """Headers for the entity-backed Supplier role.

    `X-User-ID` must equal the id of the supplier record being acted upon.
    """
    return build_user_headers(supplier_id, ROLE_SUPPLIER)
