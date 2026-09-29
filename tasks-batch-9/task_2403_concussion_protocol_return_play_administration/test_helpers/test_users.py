"""
Role headers for the Concussion Protocol & Return-to-Play Administration API.

Per the PRD every request carries `X-User-ID` (the acting user) and
`X-User-Role` (the capacity in which that user acts).  The six role names are
`LeagueAdmin`, `ClubPhysician`, `UnaffiliatedObserver`, `IndependentConsultant`,
`ClubComplianceOfficer` and `LeagueAuditor`.

Two of those roles carry an **opaque** `X-User-ID` that the server never
compares to any entity id — `LeagueAdmin` and `LeagueAuditor` — so their headers
can be module-level constants.

The other four are identity-backed and their `X-User-ID` MUST be a real row id:

* `ClubPhysician`, `UnaffiliatedObserver`, `IndependentConsultant` — the id of
  the acting `Clinician`, whose `affiliation` must match the declared role.
* `ClubComplianceOfficer` — the id of the acting `Club` itself.

For those four, always use the `make_*_headers(...)` builders with an id
captured from a create response.  Passing a placeholder id yields
`ERR_ROLE_IDENTITY_MISMATCH` (403) rather than the behaviour under test.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# ─── Role names ──────────────────────────────────────────────────────────────

ROLE_LEAGUE_ADMIN = "LeagueAdmin"
ROLE_CLUB_PHYSICIAN = "ClubPhysician"
ROLE_UNAFFILIATED_OBSERVER = "UnaffiliatedObserver"
ROLE_INDEPENDENT_CONSULTANT = "IndependentConsultant"
ROLE_CLUB_COMPLIANCE_OFFICER = "ClubComplianceOfficer"
ROLE_LEAGUE_AUDITOR = "LeagueAuditor"

ALL_ROLES = [
    ROLE_LEAGUE_ADMIN,
    ROLE_CLUB_PHYSICIAN,
    ROLE_UNAFFILIATED_OBSERVER,
    ROLE_INDEPENDENT_CONSULTANT,
    ROLE_CLUB_COMPLIANCE_OFFICER,
    ROLE_LEAGUE_AUDITOR,
]

# The three clinician-backed roles.
CLINICIAN_BACKED_ROLES = [
    ROLE_CLUB_PHYSICIAN,
    ROLE_UNAFFILIATED_OBSERVER,
    ROLE_INDEPENDENT_CONSULTANT,
]

# ─── Opaque operator identifiers ─────────────────────────────────────────────

LEAGUE_ADMIN_USER_ID = "league-admin-ops"

# Segregation of duties splits open / issue-findings / close across three
# distinct opaque auditor identifiers.
AUDITOR_OPENER_USER_ID = "auditor-a"
AUDITOR_ISSUER_USER_ID = "auditor-b"
AUDITOR_CLOSER_USER_ID = "auditor-c"

# ─── Ready-made headers for the opaque roles ─────────────────────────────────

ADMIN = build_user_headers(LEAGUE_ADMIN_USER_ID, ROLE_LEAGUE_ADMIN)

AUDITOR_A = build_user_headers(AUDITOR_OPENER_USER_ID, ROLE_LEAGUE_AUDITOR)
AUDITOR_B = build_user_headers(AUDITOR_ISSUER_USER_ID, ROLE_LEAGUE_AUDITOR)
AUDITOR_C = build_user_headers(AUDITOR_CLOSER_USER_ID, ROLE_LEAGUE_AUDITOR)


# ─── Identity-backed header builders ─────────────────────────────────────────

def make_admin_headers(user_id: str = LEAGUE_ADMIN_USER_ID) -> Dict[str, str]:
    """LeagueAdmin headers; the identifier is opaque and never resolved."""
    return build_user_headers(user_id, ROLE_LEAGUE_ADMIN)


def make_auditor_headers(user_id: str) -> Dict[str, str]:
    """LeagueAuditor headers; the identifier is opaque but is recorded on audits."""
    return build_user_headers(user_id, ROLE_LEAGUE_AUDITOR)


def make_club_physician_headers(clinician_id: str) -> Dict[str, str]:
    """ClubPhysician headers; `clinician_id` must be a CLUB_AFFILIATED Clinician."""
    return build_user_headers(clinician_id, ROLE_CLUB_PHYSICIAN)


def make_observer_headers(clinician_id: str) -> Dict[str, str]:
    """UnaffiliatedObserver headers; must be an UNAFFILIATED_OBSERVER Clinician."""
    return build_user_headers(clinician_id, ROLE_UNAFFILIATED_OBSERVER)


def make_consultant_headers(clinician_id: str) -> Dict[str, str]:
    """IndependentConsultant headers; must be an INDEPENDENT_CONSULTANT Clinician."""
    return build_user_headers(clinician_id, ROLE_INDEPENDENT_CONSULTANT)


def make_compliance_officer_headers(club_id: str) -> Dict[str, str]:
    """ClubComplianceOfficer headers; `X-User-ID` is the acting Club's own id."""
    return build_user_headers(club_id, ROLE_CLUB_COMPLIANCE_OFFICER)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Generic builder for role-sweep tests."""
    return build_user_headers(user_id, role)


# ─── Malformed authentication headers ────────────────────────────────────────

def headers_without_role(user_id: str) -> Dict[str, str]:
    """`X-User-Role` absent — an `ERR_UNAUTHENTICATED` condition."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """`X-User-ID` absent — an `ERR_UNAUTHENTICATED` condition."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str) -> Dict[str, str]:
    """`X-User-Role` is not one of the six recognised names."""
    return build_user_headers(user_id, "TeamDoctor")


NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
