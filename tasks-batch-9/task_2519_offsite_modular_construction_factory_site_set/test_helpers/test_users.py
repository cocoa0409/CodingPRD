"""Actor header bundles for the ten declared roles.

Seven of the ten roles are opaque: their ``X-User-ID`` is an operator string
that the server never compares against a stored row, so a module-level constant
is safe. Three roles are entity-backed — ``FactoryProductionManager`` carries a
``Factory`` id, ``ThirdPartyInspector`` carries an ``InspectionAgency`` id and
``SiteSuperintendent`` carries a ``Project`` id — so those three must be built
per test from the identifier of the row that was actually created.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# ─── Role names ───────────────────────────────────────────────────────────────
ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_DESIGN_ENGINEER = "DesignEngineer"
ROLE_FACTORY_PRODUCTION_MANAGER = "FactoryProductionManager"
ROLE_THIRD_PARTY_INSPECTOR = "ThirdPartyInspector"
ROLE_TRANSPORT_COORDINATOR = "TransportCoordinator"
ROLE_SITE_SUPERINTENDENT = "SiteSuperintendent"
ROLE_STATE_PROGRAM_OFFICER = "StateProgramOfficer"
ROLE_AUTHORITY_HAVING_JURISDICTION = "AuthorityHavingJurisdiction"
ROLE_WARRANTY_ADJUDICATOR = "WarrantyAdjudicator"
ROLE_LENDER_DRAW_ADMINISTRATOR = "LenderDrawAdministrator"

ALL_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_DESIGN_ENGINEER,
    ROLE_FACTORY_PRODUCTION_MANAGER,
    ROLE_THIRD_PARTY_INSPECTOR,
    ROLE_TRANSPORT_COORDINATOR,
    ROLE_SITE_SUPERINTENDENT,
    ROLE_STATE_PROGRAM_OFFICER,
    ROLE_AUTHORITY_HAVING_JURISDICTION,
    ROLE_WARRANTY_ADJUDICATOR,
    ROLE_LENDER_DRAW_ADMINISTRATOR,
)

# ─── Opaque operator identifiers ──────────────────────────────────────────────
PROGRAM_ADMIN_USER_ID = "admin-001"
DESIGN_ENGINEER_SUBMITTER_USER_ID = "eng-001"
DESIGN_ENGINEER_REVIEWER_USER_ID = "eng-002"
TRANSPORT_COORDINATOR_USER_ID = "transport-001"
STATE_PROGRAM_OFFICER_USER_ID = "state-001"
AUTHORITY_HAVING_JURISDICTION_USER_ID = "ahj-001"
WARRANTY_ADJUDICATOR_USER_ID = "warranty-001"
LENDER_DRAW_ADMINISTRATOR_USER_ID = "lender-001"

# ─── Ready-made header bundles for the seven opaque roles ─────────────────────
PROGRAM_ADMIN = build_user_headers(PROGRAM_ADMIN_USER_ID, ROLE_PROGRAM_ADMIN)
DESIGN_ENGINEER_SUBMITTER = build_user_headers(
    DESIGN_ENGINEER_SUBMITTER_USER_ID, ROLE_DESIGN_ENGINEER
)
DESIGN_ENGINEER_REVIEWER = build_user_headers(
    DESIGN_ENGINEER_REVIEWER_USER_ID, ROLE_DESIGN_ENGINEER
)
TRANSPORT_COORDINATOR = build_user_headers(
    TRANSPORT_COORDINATOR_USER_ID, ROLE_TRANSPORT_COORDINATOR
)
STATE_PROGRAM_OFFICER = build_user_headers(
    STATE_PROGRAM_OFFICER_USER_ID, ROLE_STATE_PROGRAM_OFFICER
)
AUTHORITY_HAVING_JURISDICTION = build_user_headers(
    AUTHORITY_HAVING_JURISDICTION_USER_ID, ROLE_AUTHORITY_HAVING_JURISDICTION
)
WARRANTY_ADJUDICATOR = build_user_headers(
    WARRANTY_ADJUDICATOR_USER_ID, ROLE_WARRANTY_ADJUDICATOR
)
LENDER_DRAW_ADMINISTRATOR = build_user_headers(
    LENDER_DRAW_ADMINISTRATOR_USER_ID, ROLE_LENDER_DRAW_ADMINISTRATOR
)


# ─── Entity-backed identity builders ─────────────────────────────────────────
def make_factory_manager_headers(factory_id: str) -> Dict[str, str]:
    """Headers for the plant manager of the ``Factory`` with this id."""
    return build_user_headers(factory_id, ROLE_FACTORY_PRODUCTION_MANAGER)


def make_inspector_headers(agency_id: str) -> Dict[str, str]:
    """Headers for the inspector of the ``InspectionAgency`` with this id."""
    return build_user_headers(agency_id, ROLE_THIRD_PARTY_INSPECTOR)


def make_site_superintendent_headers(project_id: str) -> Dict[str, str]:
    """Headers for the field superintendent of the ``Project`` with this id."""
    return build_user_headers(project_id, ROLE_SITE_SUPERINTENDENT)


def make_design_engineer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named design engineer, for segregation-of-duties cases."""
    return build_user_headers(user_id, ROLE_DESIGN_ENGINEER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for role-authorisation probes needing an arbitrary pair."""
    return build_user_headers(user_id, role)
