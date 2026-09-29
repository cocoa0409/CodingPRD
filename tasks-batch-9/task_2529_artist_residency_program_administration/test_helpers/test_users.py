"""Actor identities and header builders.

Five of the eight roles are opaque operator identifiers, so a fixed constant
header dict is enough for them. The other three roles resolve the caller's
``X-User-ID`` to a backing row, so their headers must be built per row after
that row exists: ``Applicant`` resolves to an Applicant, and both ``Panelist``
and ``PanelChair`` resolve to a Panelist. Passing a fixed constant identifier
for those roles would make every ownership-gated call fail.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_APPLICANT = "Applicant"
ROLE_PANELIST = "Panelist"
ROLE_PANEL_CHAIR = "PanelChair"
ROLE_FINANCE_OFFICER = "FinanceOfficer"
ROLE_VISA_COORDINATOR = "VisaCoordinator"
ROLE_FACILITIES_MANAGER = "FacilitiesManager"
ROLE_FUNDER = "Funder"

# ---------------------------------------------------------------------------
# Opaque operator identifiers
# ---------------------------------------------------------------------------
ADMIN_USER_ID = "admin-01"
ADMIN_USER_ID_ALT = "admin-02"
FACILITIES_USER_ID = "fac-01"
FACILITIES_USER_ID_ALT = "fac-02"
FINANCE_SCHEDULER_USER_ID = "fin-01"
FINANCE_PAYER_USER_ID = "fin-02"
FINANCE_REVERSER_USER_ID = "fin-03"
VISA_USER_ID = "visa-01"
FUNDER_USER_ID = "funder-01"

ADMIN_HEADERS: Dict[str, str] = build_user_headers(ADMIN_USER_ID, ROLE_PROGRAM_ADMIN)
ADMIN_HEADERS_ALT: Dict[str, str] = build_user_headers(
    ADMIN_USER_ID_ALT, ROLE_PROGRAM_ADMIN
)
FACILITIES_HEADERS: Dict[str, str] = build_user_headers(
    FACILITIES_USER_ID, ROLE_FACILITIES_MANAGER
)
FACILITIES_HEADERS_ALT: Dict[str, str] = build_user_headers(
    FACILITIES_USER_ID_ALT, ROLE_FACILITIES_MANAGER
)
FINANCE_SCHEDULER_HEADERS: Dict[str, str] = build_user_headers(
    FINANCE_SCHEDULER_USER_ID, ROLE_FINANCE_OFFICER
)
FINANCE_PAYER_HEADERS: Dict[str, str] = build_user_headers(
    FINANCE_PAYER_USER_ID, ROLE_FINANCE_OFFICER
)
FINANCE_REVERSER_HEADERS: Dict[str, str] = build_user_headers(
    FINANCE_REVERSER_USER_ID, ROLE_FINANCE_OFFICER
)
VISA_HEADERS: Dict[str, str] = build_user_headers(VISA_USER_ID, ROLE_VISA_COORDINATOR)
FUNDER_HEADERS: Dict[str, str] = build_user_headers(FUNDER_USER_ID, ROLE_FUNDER)

TEST_USERS = {
    ROLE_PROGRAM_ADMIN: ADMIN_HEADERS,
    ROLE_FACILITIES_MANAGER: FACILITIES_HEADERS,
    ROLE_FINANCE_OFFICER: FINANCE_SCHEDULER_HEADERS,
    ROLE_VISA_COORDINATOR: VISA_HEADERS,
    ROLE_FUNDER: FUNDER_HEADERS,
}


# ---------------------------------------------------------------------------
# Entity-backed identities
# ---------------------------------------------------------------------------
def make_applicant_headers(applicant_id: str) -> Dict[str, str]:
    """Headers for the artist whose Applicant row is ``applicant_id``."""
    return build_user_headers(applicant_id, ROLE_APPLICANT)


def make_panelist_headers(panelist_id: str) -> Dict[str, str]:
    """Headers for the reviewer whose Panelist row is ``panelist_id``."""
    return build_user_headers(panelist_id, ROLE_PANELIST)


def make_panel_chair_headers(panelist_id: str) -> Dict[str, str]:
    """Headers for a chair; the same Panelist row backs both reviewer roles."""
    return build_user_headers(panelist_id, ROLE_PANEL_CHAIR)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for tests that need an arbitrary identifier/role pairing."""
    return build_user_headers(user_id, role)


UNKNOWN_ENTITY_USER_ID = "11111111-1111-1111-1111-111111111111"
