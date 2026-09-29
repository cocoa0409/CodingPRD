"""
Actor headers for every role on the transfer desk.

Six roles are opaque: their X-User-ID is an arbitrary stable string and the
canonical desk operators are pinned here so a segregation-of-duties assertion
can name who acted. The selling and acquiring servicers are backed by a
Counterparty row, so their headers can only be built once that row exists and
must carry the counterparty's own identifier.
"""

from prd_bench_local_runner.testing import build_user_headers

from . import constants as C
from .types import Headers

# ---------------------------------------------------------------------------
# Role names, exactly as X-User-Role must spell them
# ---------------------------------------------------------------------------
VALUATION_ANALYST = "ValuationAnalyst"
TRANSACTION_MANAGER = "TransactionManager"
SELLER_SERVICER = "SellerServicer"
BUYER_SERVICER = "BuyerServicer"
AGENCY_APPROVER = "AgencyApprover"
COMPLIANCE_OFFICER = "ComplianceOfficer"
HEDGE_DESK = "HedgeDesk"
PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = [
    VALUATION_ANALYST,
    TRANSACTION_MANAGER,
    SELLER_SERVICER,
    BUYER_SERVICER,
    AGENCY_APPROVER,
    COMPLIANCE_OFFICER,
    HEDGE_DESK,
    PLATFORM_ADMIN,
]

OPAQUE_ROLES = [
    VALUATION_ANALYST,
    TRANSACTION_MANAGER,
    AGENCY_APPROVER,
    COMPLIANCE_OFFICER,
    HEDGE_DESK,
    PLATFORM_ADMIN,
]

ENTITY_BACKED_ROLES = [SELLER_SERVICER, BUYER_SERVICER]

# ---------------------------------------------------------------------------
# Canonical opaque operators
# ---------------------------------------------------------------------------
ADMIN = build_user_headers(C.ADMIN_ID, PLATFORM_ADMIN)
ANALYST = build_user_headers(C.ANALYST_ID, VALUATION_ANALYST)
MANAGER = build_user_headers(C.MANAGER_ID, TRANSACTION_MANAGER)
APPROVER = build_user_headers(C.AGENCY_ID, AGENCY_APPROVER)
APPROVER_2 = build_user_headers(C.AGENCY_ID_2, AGENCY_APPROVER)
COMPLIANCE = build_user_headers(C.COMPLIANCE_ID, COMPLIANCE_OFFICER)
COMPLIANCE_2 = build_user_headers(C.COMPLIANCE_ID_2, COMPLIANCE_OFFICER)
HEDGE = build_user_headers(C.HEDGE_ID, HEDGE_DESK)


def make_analyst_headers(user_id: str) -> Headers:
    """A ValuationAnalyst acting under an explicit opaque identifier."""
    return build_user_headers(user_id, VALUATION_ANALYST)


def make_manager_headers(user_id: str) -> Headers:
    """A TransactionManager acting under an explicit opaque identifier."""
    return build_user_headers(user_id, TRANSACTION_MANAGER)


def make_approver_headers(user_id: str) -> Headers:
    """An AgencyApprover acting under an explicit opaque identifier."""
    return build_user_headers(user_id, AGENCY_APPROVER)


def make_compliance_headers(user_id: str) -> Headers:
    """A ComplianceOfficer acting under an explicit opaque identifier."""
    return build_user_headers(user_id, COMPLIANCE_OFFICER)


def make_hedge_headers(user_id: str) -> Headers:
    """A HedgeDesk operator acting under an explicit opaque identifier."""
    return build_user_headers(user_id, HEDGE_DESK)


def make_admin_headers(user_id: str) -> Headers:
    """A PlatformAdmin acting under an explicit opaque identifier."""
    return build_user_headers(user_id, PLATFORM_ADMIN)


def make_seller_headers(counterparty_id: str) -> Headers:
    """The selling servicer, identified by its own Counterparty row."""
    return build_user_headers(counterparty_id, SELLER_SERVICER)


def make_buyer_headers(counterparty_id: str) -> Headers:
    """The acquiring servicer, identified by its own Counterparty row."""
    return build_user_headers(counterparty_id, BUYER_SERVICER)


def make_headers(role: str, user_id: str) -> Headers:
    """Headers for an arbitrary role/identifier pair."""
    return build_user_headers(user_id, role)


# ---------------------------------------------------------------------------
# Malformed authentication headers
# ---------------------------------------------------------------------------
def headers_without_user_id(role: str = PLATFORM_ADMIN) -> Headers:
    """A request that carries a role but no caller identity at all."""
    return {"X-User-Role": role}


def headers_with_empty_user_id(role: str = PLATFORM_ADMIN) -> Headers:
    """A request whose caller identity is present but blank."""
    return {"X-User-ID": "", "X-User-Role": role}


def headers_without_role(user_id: str = C.ADMIN_ID) -> Headers:
    """A request that identifies the caller but declares no role."""
    return {"X-User-ID": user_id}


def headers_with_unknown_role(user_id: str = C.ADMIN_ID) -> Headers:
    """A request that declares a role name the desk does not define."""
    return build_user_headers(user_id, "ChiefExecutive")


NO_HEADERS: Headers = {}
