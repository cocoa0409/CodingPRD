"""
Pre-built request headers for the seven chartering participants.

PRD 2.1 requires every request to carry `X-User-ID`, identifying the acting
principal, and `X-User-Role`, naming the capacity in which that principal is
acting. Identity semantics differ by role: for `CharterCounsel`,
`CharteringExaminer`, `InsuranceExaminer`, `EscrowAgent` and `PlatformAdmin`
the `X-User-ID` is an opaque operator identifier not tied to any persisted
entity, so a fixed literal is used. For `LeadOrganizer` and
`IndependentDirector` the `X-User-ID` must be the id of an existing Organizer
row of the group in scope, so those headers are built per test from an
organizer id returned by the API.
"""

from prd_bench_local_runner.testing import build_user_headers

# --- The seven declared roles (PRD 2.1) ------------------------------------
ROLE_CHARTER_COUNSEL = "CharterCounsel"
ROLE_LEAD_ORGANIZER = "LeadOrganizer"
ROLE_INDEPENDENT_DIRECTOR = "IndependentDirector"
ROLE_CHARTERING_EXAMINER = "CharteringExaminer"
ROLE_INSURANCE_EXAMINER = "InsuranceExaminer"
ROLE_ESCROW_AGENT = "EscrowAgent"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = (
    ROLE_CHARTER_COUNSEL,
    ROLE_LEAD_ORGANIZER,
    ROLE_INDEPENDENT_DIRECTOR,
    ROLE_CHARTERING_EXAMINER,
    ROLE_INSURANCE_EXAMINER,
    ROLE_ESCROW_AGENT,
    ROLE_PLATFORM_ADMIN,
)

# Opaque operator identifiers for the five roles whose X-User-ID is never
# compared against any entity id.
COUNSEL_USER_ID = "op-charter-counsel-001"
CHARTERING_EXAMINER_USER_ID = "op-chartering-examiner-001"
INSURANCE_EXAMINER_USER_ID = "op-insurance-examiner-001"
ESCROW_AGENT_USER_ID = "op-escrow-agent-001"
PLATFORM_ADMIN_USER_ID = "op-platform-admin-001"

COUNSEL_HEADERS = build_user_headers(COUNSEL_USER_ID, ROLE_CHARTER_COUNSEL)
CHARTERING_EXAMINER_HEADERS = build_user_headers(
    CHARTERING_EXAMINER_USER_ID, ROLE_CHARTERING_EXAMINER
)
INSURANCE_EXAMINER_HEADERS = build_user_headers(
    INSURANCE_EXAMINER_USER_ID, ROLE_INSURANCE_EXAMINER
)
ESCROW_AGENT_HEADERS = build_user_headers(ESCROW_AGENT_USER_ID, ROLE_ESCROW_AGENT)
PLATFORM_ADMIN_HEADERS = build_user_headers(
    PLATFORM_ADMIN_USER_ID, ROLE_PLATFORM_ADMIN
)


def make_lead_organizer_headers(organizer_id: str) -> dict:
    """Headers for a LeadOrganizer acting as the given Organizer row."""
    return build_user_headers(organizer_id, ROLE_LEAD_ORGANIZER)


def make_independent_director_headers(organizer_id: str) -> dict:
    """Headers for an IndependentDirector acting as the given Organizer row."""
    return build_user_headers(organizer_id, ROLE_INDEPENDENT_DIRECTOR)


def make_headers(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role/id pair."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = COUNSEL_USER_ID) -> dict:
    """Headers that omit `X-User-Role` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_CHARTER_COUNSEL) -> dict:
    """Headers that omit `X-User-ID` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
