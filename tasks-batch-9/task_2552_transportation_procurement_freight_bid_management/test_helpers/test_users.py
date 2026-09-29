"""Pre-built role headers for every role the PRD recognises (PRD §2.1).

Four of the five roles are opaque operator identities, so a shared constant
identifier is the canonical form for them.  ``CarrierRep`` is entity-backed:
its ``X-User-ID`` is the ``id`` of the acting ``Carrier``, so ownership-gated
calls MUST use :func:`make_carrier_rep_headers` with the real carrier id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identifiers used throughout the suite.
ANALYST_USER_ID = "pa-001"
COMPLIANCE_USER_ID = "co-001"
CATEGORY_MANAGER_USER_ID = "cm-001"
CATEGORY_MANAGER_ALT_USER_ID = "cm-002"
CONTRACT_ADMIN_USER_ID = "ca-001"
CONTRACT_ADMIN_ALT_USER_ID = "ca-002"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "analyst_headers": build_user_headers(
        ANALYST_USER_ID, UserRole.PROCUREMENT_ANALYST.value
    ),
    "compliance_headers": build_user_headers(
        COMPLIANCE_USER_ID, UserRole.COMPLIANCE_OFFICER.value
    ),
    "category_manager_headers": build_user_headers(
        CATEGORY_MANAGER_USER_ID, UserRole.CATEGORY_MANAGER.value
    ),
    "category_manager_alt_headers": build_user_headers(
        CATEGORY_MANAGER_ALT_USER_ID, UserRole.CATEGORY_MANAGER.value
    ),
    "contract_admin_headers": build_user_headers(
        CONTRACT_ADMIN_USER_ID, UserRole.CONTRACT_ADMIN.value
    ),
    "contract_admin_alt_headers": build_user_headers(
        CONTRACT_ADMIN_ALT_USER_ID, UserRole.CONTRACT_ADMIN.value
    ),
    # Fallback only for CarrierRep tests that do not exercise ownership.
    "carrier_rep_headers": build_user_headers(
        "carrier-rep-unowned", UserRole.CARRIER_REP.value
    ),
}


def make_carrier_rep_headers(carrier_id: str) -> Dict[str, str]:
    """Headers for ``CarrierRep`` acting as the carrier whose ``id`` is given.

    ``CarrierRep`` is entity-backed: pass the real ``Carrier.id`` whenever the
    call is ownership-gated (invitation response, lane-bid submission or
    withdrawal, carrier signature, scorecard dispute, mini-bid proposal).
    """
    return build_user_headers(carrier_id, UserRole.CARRIER_REP.value)


def make_analyst_headers(user_id: str = ANALYST_USER_ID) -> Dict[str, str]:
    """Headers for an opaque ``ProcurementAnalyst`` operator identity."""
    return build_user_headers(user_id, UserRole.PROCUREMENT_ANALYST.value)


def make_compliance_headers(user_id: str = COMPLIANCE_USER_ID) -> Dict[str, str]:
    """Headers for an opaque ``ComplianceOfficer`` operator identity."""
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def make_category_manager_headers(
    user_id: str = CATEGORY_MANAGER_USER_ID,
) -> Dict[str, str]:
    """Headers for an opaque ``CategoryManager`` operator identity."""
    return build_user_headers(user_id, UserRole.CATEGORY_MANAGER.value)


def make_contract_admin_headers(
    user_id: str = CONTRACT_ADMIN_USER_ID,
) -> Dict[str, str]:
    """Headers for an opaque ``ContractAdmin`` operator identity."""
    return build_user_headers(user_id, UserRole.CONTRACT_ADMIN.value)
