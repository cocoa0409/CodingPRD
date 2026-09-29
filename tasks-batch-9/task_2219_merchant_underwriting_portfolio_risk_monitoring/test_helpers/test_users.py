"""Role headers for the six declared roles.

Two roles are entity-backed and their ``X-User-ID`` is *not* free-form:

* ``Applicant`` - ``X-User-ID`` must equal the MerchantApplication's own id.
* ``MerchantUser`` - ``X-User-ID`` must equal the Merchant's own id.

Any call that touches a resource owned by one of those two roles must be made
with the matching per-entity builder, never with a shared constant. The other
four roles are opaque: their user id is an arbitrary staff identifier, and only
the identifier's *equality* matters (segregation-of-duties rules compare user
ids, not roles).
"""

from __future__ import annotations

from prd_bench_local_runner.testing import build_user_headers

# ---------------------------------------------------------------------------
# Role names
# ---------------------------------------------------------------------------

ROLE_APPLICANT = "Applicant"
ROLE_MERCHANT_USER = "MerchantUser"
ROLE_UNDERWRITING_OFFICER = "UnderwritingOfficer"
ROLE_RISK_ANALYST = "RiskAnalyst"
ROLE_RISK_COMMITTEE_APPROVER = "RiskCommitteeApprover"
ROLE_PORTFOLIO_CONTROLLER = "PortfolioController"

ALL_ROLES = (
    ROLE_APPLICANT,
    ROLE_MERCHANT_USER,
    ROLE_UNDERWRITING_OFFICER,
    ROLE_RISK_ANALYST,
    ROLE_RISK_COMMITTEE_APPROVER,
    ROLE_PORTFOLIO_CONTROLLER,
)

# ---------------------------------------------------------------------------
# Named staff identities (opaque roles)
# ---------------------------------------------------------------------------

USER_OFFICER_01 = "user-officer-01"
USER_OFFICER_02 = "user-officer-02"
USER_ANALYST_01 = "user-analyst-01"
USER_ANALYST_02 = "user-analyst-02"
USER_COMMITTEE_01 = "user-committee-01"
USER_COMMITTEE_02 = "user-committee-02"
USER_COMMITTEE_03 = "user-committee-03"
USER_TREASURY_01 = "user-treasury-01"
USER_TREASURY_02 = "user-treasury-02"


# ---------------------------------------------------------------------------
# Per-role header builders
# ---------------------------------------------------------------------------


def make_applicant_headers(application_id: str) -> dict[str, str]:
    """Applicant headers for a specific application (X-User-ID == its id)."""
    return build_user_headers(application_id, ROLE_APPLICANT)


def make_merchant_user_headers(merchant_id: str) -> dict[str, str]:
    """MerchantUser headers for a specific merchant (X-User-ID == its id)."""
    return build_user_headers(merchant_id, ROLE_MERCHANT_USER)


def make_underwriting_officer_headers(user_id: str = USER_OFFICER_01) -> dict[str, str]:
    return build_user_headers(user_id, ROLE_UNDERWRITING_OFFICER)


def make_risk_analyst_headers(user_id: str = USER_ANALYST_01) -> dict[str, str]:
    return build_user_headers(user_id, ROLE_RISK_ANALYST)


def make_risk_committee_headers(user_id: str = USER_COMMITTEE_01) -> dict[str, str]:
    return build_user_headers(user_id, ROLE_RISK_COMMITTEE_APPROVER)


def make_portfolio_controller_headers(user_id: str = USER_TREASURY_01) -> dict[str, str]:
    return build_user_headers(user_id, ROLE_PORTFOLIO_CONTROLLER)


def make_headers(role: str, user_id: str) -> dict[str, str]:
    """Arbitrary role/user pair - used by role-matrix probes."""
    return build_user_headers(user_id, role)


# ---------------------------------------------------------------------------
# Shared constants for the four opaque roles
# ---------------------------------------------------------------------------

#: Ready-made headers for the opaque roles. Never use APPLICANT / MERCHANT_USER
#: entries from here for an ownership-gated call - build them per entity.
TEST_USERS: dict[str, dict[str, str]] = {
    ROLE_UNDERWRITING_OFFICER: make_underwriting_officer_headers(),
    ROLE_RISK_ANALYST: make_risk_analyst_headers(),
    ROLE_RISK_COMMITTEE_APPROVER: make_risk_committee_headers(),
    ROLE_PORTFOLIO_CONTROLLER: make_portfolio_controller_headers(),
}

#: Headers with no X-User-Role at all.
NO_ROLE_HEADERS: dict[str, str] = {"X-User-ID": USER_ANALYST_01, "Content-Type": "application/json"}

#: Headers with no X-User-ID at all.
NO_USER_ID_HEADERS: dict[str, str] = {
    "X-User-Role": ROLE_RISK_ANALYST,
    "Content-Type": "application/json",
}

#: Headers naming a role the contract does not declare.
UNKNOWN_ROLE_HEADERS: dict[str, str] = build_user_headers(USER_ANALYST_01, "ChiefRiskOfficer")
