"""Header builders for the seven roles the PRD declares (PRD 2.1).

Five roles are operator roles whose `X-User-ID` is opaque and never compared to
any entity id, so a fixed identifier is safe for them.  The remaining two are
entity-backed: a `Bidder`'s `X-User-ID` is the id of the acting `Bidder` row and
a `Depositor`'s is the id of the acting `DepositorRecord`, so headers for those
two roles are always built from a real row id through the `make_*` builders.
"""
from prd_bench_local_runner.testing import build_user_headers

from . import constants as C
from .types import UserRole

# Opaque operator identities.
CLOSING_MANAGER_USER_ID = "closing-manager-001"
CLAIMS_AGENT_USER_ID = C.PREPARER_USER_ID
CLAIMS_CERTIFIER_USER_ID = C.CERTIFIER_USER_ID
RESOLUTION_ANALYST_USER_ID = "analyst-001"
RECEIVERSHIP_TRUSTEE_USER_ID = "trustee-001"

# Placeholder identifiers for the two entity-backed roles, usable only where the
# operation performs no ownership comparison at all (every read in PRD 4).
PLACEHOLDER_BIDDER_USER_ID = "00000000-0000-4000-8000-0000000000b1"
PLACEHOLDER_DEPOSITOR_USER_ID = "00000000-0000-4000-8000-0000000000d1"

TEST_USERS = {
    "closing_manager": build_user_headers(
        CLOSING_MANAGER_USER_ID, UserRole.CLOSING_MANAGER.value
    ),
    "claims_agent": build_user_headers(
        CLAIMS_AGENT_USER_ID, UserRole.CLAIMS_AGENT.value
    ),
    "claims_certifier": build_user_headers(
        CLAIMS_CERTIFIER_USER_ID, UserRole.CLAIMS_CERTIFIER.value
    ),
    "resolution_analyst": build_user_headers(
        RESOLUTION_ANALYST_USER_ID, UserRole.RESOLUTION_ANALYST.value
    ),
    "receivership_trustee": build_user_headers(
        RECEIVERSHIP_TRUSTEE_USER_ID, UserRole.RECEIVERSHIP_TRUSTEE.value
    ),
    "bidder": build_user_headers(PLACEHOLDER_BIDDER_USER_ID, UserRole.BIDDER.value),
    "depositor": build_user_headers(
        PLACEHOLDER_DEPOSITOR_USER_ID, UserRole.DEPOSITOR.value
    ),
}

CLOSING_MANAGER = TEST_USERS["closing_manager"]
CLAIMS_AGENT = TEST_USERS["claims_agent"]
CLAIMS_CERTIFIER = TEST_USERS["claims_certifier"]
RESOLUTION_ANALYST = TEST_USERS["resolution_analyst"]
RECEIVERSHIP_TRUSTEE = TEST_USERS["receivership_trustee"]

# Read-only headers for all seven roles; safe because no read compares identity.
READER_HEADERS = {
    UserRole.CLOSING_MANAGER: CLOSING_MANAGER,
    UserRole.CLAIMS_AGENT: CLAIMS_AGENT,
    UserRole.CLAIMS_CERTIFIER: CLAIMS_CERTIFIER,
    UserRole.RESOLUTION_ANALYST: RESOLUTION_ANALYST,
    UserRole.RECEIVERSHIP_TRUSTEE: RECEIVERSHIP_TRUSTEE,
    UserRole.BIDDER: TEST_USERS["bidder"],
    UserRole.DEPOSITOR: TEST_USERS["depositor"],
}


def make_headers(role, subject_id):
    """Headers for any role, given the identifier that role's `X-User-ID` takes."""
    value = role.value if isinstance(role, UserRole) else role
    return build_user_headers(subject_id, value)


def make_closing_manager_headers(user_id=CLOSING_MANAGER_USER_ID):
    """Headers for a `ClosingManager` under a caller-chosen operator identifier."""
    return build_user_headers(user_id, UserRole.CLOSING_MANAGER.value)


def make_claims_agent_headers(user_id=CLAIMS_AGENT_USER_ID):
    """Headers for a `ClaimsAgent`; the identifier lands in `prepared_by_user_id`."""
    return build_user_headers(user_id, UserRole.CLAIMS_AGENT.value)


def make_claims_certifier_headers(user_id=CLAIMS_CERTIFIER_USER_ID):
    """Headers for a `ClaimsCertifier`; the identifier lands in `certified_by_user_id`."""
    return build_user_headers(user_id, UserRole.CLAIMS_CERTIFIER.value)


def make_resolution_analyst_headers(user_id=RESOLUTION_ANALYST_USER_ID):
    """Headers for a `ResolutionAnalyst` under a caller-chosen operator identifier."""
    return build_user_headers(user_id, UserRole.RESOLUTION_ANALYST.value)


def make_receivership_trustee_headers(user_id=RECEIVERSHIP_TRUSTEE_USER_ID):
    """Headers for a `ReceivershipTrustee` under a caller-chosen operator identifier."""
    return build_user_headers(user_id, UserRole.RECEIVERSHIP_TRUSTEE.value)


def make_bidder_headers(bidder_id):
    """Headers for a `Bidder` acting as the given `Bidder` row."""
    return build_user_headers(bidder_id, UserRole.BIDDER.value)


def make_depositor_headers(depositor_record_id):
    """Headers for a `Depositor` acting on the given `DepositorRecord`."""
    return build_user_headers(depositor_record_id, UserRole.DEPOSITOR.value)


# ---------------------------------------------------------------------------
# Header shapes that must fail authentication (PRD 2.1)
# ---------------------------------------------------------------------------
def headers_missing_role(user_id=CLOSING_MANAGER_USER_ID):
    """A request that omits `X-User-Role` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_missing_user_id(role=UserRole.CLOSING_MANAGER):
    """A request that omits `X-User-ID` entirely."""
    value = role.value if isinstance(role, UserRole) else role
    return {"X-User-Role": value, "Content-Type": "application/json"}


def headers_empty_role(user_id=CLOSING_MANAGER_USER_ID):
    """A request whose `X-User-Role` is present but empty."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_empty_user_id(role=UserRole.CLOSING_MANAGER):
    """A request whose `X-User-ID` is present but empty."""
    value = role.value if isinstance(role, UserRole) else role
    return {"X-User-ID": "", "X-User-Role": value, "Content-Type": "application/json"}


def headers_undeclared_role(user_id=CLOSING_MANAGER_USER_ID):
    """A request declaring a role string that is not one of the seven."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "ReceivershipAuditor",
        "Content-Type": "application/json",
    }


def headers_no_headers():
    """A request carrying neither identity header."""
    return {"Content-Type": "application/json"}
