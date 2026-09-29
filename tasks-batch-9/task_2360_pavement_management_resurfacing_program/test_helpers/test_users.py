"""Role headers for the Pavement Management & Resurfacing Program API.

Every request carries ``X-User-ID`` and ``X-User-Role``. Five of the six roles
are opaque: any non-empty identifier is accepted. The Contractor role is
entity-backed, so its ``X-User-ID`` must equal the id of a registered contractor
row; ``make_contractor_headers`` threads that identity.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BUDGET_OFFICER,
    ROLE_CONTRACTOR,
    ROLE_INSPECTOR,
    ROLE_PAVEMENT_ENGINEER,
    ROLE_RESIDENT,
    ROLE_UTILITY_COORDINATOR,
)

# Default opaque user identifiers.
ENGINEER_USER_ID = "eng-1"
OFFICER_USER_ID = "officer-1"
COORDINATOR_USER_ID = "util-1"
INSPECTOR_USER_ID = "insp-1"
RESIDENT_USER_ID = "resident-1"

# Named users for the duty-segregation rules.
OFFICER_ADOPT_USER_ID = "officer-adopt-1"
OFFICER_AWARD_USER_ID = "officer-award-1"
INSPECTOR_WITNESS_USER_ID = "insp-witness-1"
INSPECTOR_WITNESS_2_USER_ID = "insp-witness-2"
INSPECTOR_DECIDER_USER_ID = "insp-decider-1"
INSPECTOR_DECIDER_2_USER_ID = "insp-decider-2"
INSPECTOR_ACCEPTOR_USER_ID = "insp-acceptor-1"


def make_engineer_headers(user_id: str = ENGINEER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PAVEMENT_ENGINEER)


def make_officer_headers(user_id: str = OFFICER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_BUDGET_OFFICER)


def make_coordinator_headers(user_id: str = COORDINATOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_UTILITY_COORDINATOR)


def make_inspector_headers(user_id: str = INSPECTOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_INSPECTOR)


def make_resident_headers(user_id: str = RESIDENT_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_RESIDENT)


def make_contractor_headers(contractor_id: str) -> Dict[str, str]:
    """Contractor headers whose X-User-ID IS the registered contractor's id."""
    return build_user_headers(contractor_id, ROLE_CONTRACTOR)


# Convenience pre-built header dicts for the common actors.
ENGINEER = make_engineer_headers()
OFFICER = make_officer_headers()
COORDINATOR = make_coordinator_headers()
INSPECTOR = make_inspector_headers()
RESIDENT = make_resident_headers()

OFFICER_ADOPTER = make_officer_headers(OFFICER_ADOPT_USER_ID)
OFFICER_AWARDER = make_officer_headers(OFFICER_AWARD_USER_ID)
INSPECTOR_WITNESS = make_inspector_headers(INSPECTOR_WITNESS_USER_ID)
INSPECTOR_WITNESS_2 = make_inspector_headers(INSPECTOR_WITNESS_2_USER_ID)
INSPECTOR_DECIDER = make_inspector_headers(INSPECTOR_DECIDER_USER_ID)
INSPECTOR_DECIDER_2 = make_inspector_headers(INSPECTOR_DECIDER_2_USER_ID)
INSPECTOR_ACCEPTOR = make_inspector_headers(INSPECTOR_ACCEPTOR_USER_ID)

ROLE_HEADER_BUILDERS = {
    ROLE_PAVEMENT_ENGINEER: make_engineer_headers,
    ROLE_BUDGET_OFFICER: make_officer_headers,
    ROLE_UTILITY_COORDINATOR: make_coordinator_headers,
    ROLE_INSPECTOR: make_inspector_headers,
    ROLE_RESIDENT: make_resident_headers,
}
