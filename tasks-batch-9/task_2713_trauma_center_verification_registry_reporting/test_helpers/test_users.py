"""Acting identities and the header builders that thread them onto requests.

Identity binding is not uniform. A ``TraumaProgramManager`` acts as a center: its
``X-User-ID`` is the ``id`` of the acting ``TraumaCenter``, and ownership checks
compare a resource's center reference against it. Every other role carries an opaque
operator identifier that the server records for attribution but never compares to an
entity ``id``. That is why ``make_trauma_program_manager_headers`` takes a center id
while every other builder takes an operator string.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# ─── Opaque operator identifiers ──────────────────────────

TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin": {"user_id": "u_admin", "role": Role.SYSTEM_ADMIN},
    "abstractor_1": {"user_id": "u_abstractor_1", "role": Role.REGISTRY_ABSTRACTOR},
    "abstractor_2": {"user_id": "u_abstractor_2", "role": Role.REGISTRY_ABSTRACTOR},
    "validator_1": {"user_id": "u_validator_1", "role": Role.REGISTRY_VALIDATOR},
    "validator_2": {"user_id": "u_validator_2", "role": Role.REGISTRY_VALIDATOR},
    "director_1": {"user_id": "u_director_1", "role": Role.TRAUMA_MEDICAL_DIRECTOR},
    "director_2": {"user_id": "u_director_2", "role": Role.TRAUMA_MEDICAL_DIRECTOR},
    "reviewer_1": {"user_id": "u_reviewer_1", "role": Role.VERIFICATION_REVIEWER},
    "reviewer_2": {"user_id": "u_reviewer_2", "role": Role.VERIFICATION_REVIEWER},
    "officer_1": {"user_id": "u_officer_1", "role": Role.STATE_DESIGNATION_OFFICER},
}

# Identifiers that are only ever payload values, never acting identities.
SURVEYOR_1 = "u_surveyor_1"
SURVEYOR_2 = "u_surveyor_2"
SURGEON_1 = "u_surgeon_1"
OWNER_1 = "u_owner_1"
PM_1 = "u_pm_1"

ADMIN_USER_ID = TEST_USERS["admin"]["user_id"]
ABSTRACTOR_1_USER_ID = TEST_USERS["abstractor_1"]["user_id"]
ABSTRACTOR_2_USER_ID = TEST_USERS["abstractor_2"]["user_id"]
VALIDATOR_1_USER_ID = TEST_USERS["validator_1"]["user_id"]
VALIDATOR_2_USER_ID = TEST_USERS["validator_2"]["user_id"]
DIRECTOR_1_USER_ID = TEST_USERS["director_1"]["user_id"]
DIRECTOR_2_USER_ID = TEST_USERS["director_2"]["user_id"]
REVIEWER_1_USER_ID = TEST_USERS["reviewer_1"]["user_id"]
REVIEWER_2_USER_ID = TEST_USERS["reviewer_2"]["user_id"]
OFFICER_1_USER_ID = TEST_USERS["officer_1"]["user_id"]


# ─── Header builders ──────────────────────────────────────


def make_system_admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for the platform operator."""
    return build_user_headers(user_id, Role.SYSTEM_ADMIN)


def make_trauma_program_manager_headers(center_id: str) -> Dict[str, str]:
    """Headers for the manager of one center.

    ``center_id`` must be the ``id`` of the ``TraumaCenter`` being acted for: every
    ownership check compares the addressed resource's center reference against it.
    """
    return build_user_headers(center_id, Role.TRAUMA_PROGRAM_MANAGER)


def make_registry_abstractor_headers(
    user_id: str = ABSTRACTOR_1_USER_ID,
) -> Dict[str, str]:
    """Headers for the abstractor who writes the registry record."""
    return build_user_headers(user_id, Role.REGISTRY_ABSTRACTOR)


def make_registry_validator_headers(
    user_id: str = VALIDATOR_1_USER_ID,
) -> Dict[str, str]:
    """Headers for the validator who adjudicates a submitted abstraction."""
    return build_user_headers(user_id, Role.REGISTRY_VALIDATOR)


def make_trauma_medical_director_headers(
    user_id: str = DIRECTOR_1_USER_ID,
) -> Dict[str, str]:
    """Headers for the director who owns triage, the loop and outreach review."""
    return build_user_headers(user_id, Role.TRAUMA_MEDICAL_DIRECTOR)


def make_verification_reviewer_headers(
    user_id: str = REVIEWER_1_USER_ID,
) -> Dict[str, str]:
    """Headers for the national verification authority."""
    return build_user_headers(user_id, Role.VERIFICATION_REVIEWER)


def make_state_designation_officer_headers(
    user_id: str = OFFICER_1_USER_ID,
) -> Dict[str, str]:
    """Headers for the state designation authority."""
    return build_user_headers(user_id, Role.STATE_DESIGNATION_OFFICER)


def make_headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary declared role, for role-matrix style checks."""
    return build_user_headers(user_id, role)


# ─── Malformed identity headers ───────────────────────────

NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

HEADERS_WITHOUT_USER_ID: Dict[str, str] = {
    "X-User-Role": Role.SYSTEM_ADMIN,
    "Content-Type": "application/json",
}

HEADERS_WITHOUT_ROLE: Dict[str, str] = {
    "X-User-ID": ADMIN_USER_ID,
    "Content-Type": "application/json",
}

HEADERS_WITH_UNKNOWN_ROLE: Dict[str, str] = {
    "X-User-ID": ADMIN_USER_ID,
    "X-User-Role": "TraumaOverlord",
    "Content-Type": "application/json",
}
