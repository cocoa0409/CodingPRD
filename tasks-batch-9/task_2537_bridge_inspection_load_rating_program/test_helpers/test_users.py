"""
Identity headers for the seven roles of PRD §2.1.

PRD §2.1 splits the roles into two identity families and the split decides how a
header is built:

* Four roles are entity-backed against the `Personnel` roster — `BridgeInspector`,
  `QaReviewer`, `RatingEngineer` and `DistrictEngineer`. For these, `X-User-ID`
  is the `id` of the acting `Personnel` record, so a header can only be built
  after that roster row exists. The `make_*_headers` builders below take the
  roster id the caller just created.
* Three roles are opaque operators — `ProgramAdmin`, `PermitOfficer` and
  `FhwaReviewer`. For these, `X-User-ID` is "an opaque operator identifier that
  is not tied to any persisted entity", so a fixed literal is enough and this
  module supplies one per role.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BRIDGE_INSPECTOR,
    ROLE_DISTRICT_ENGINEER,
    ROLE_FHWA_REVIEWER,
    ROLE_PERMIT_OFFICER,
    ROLE_PROGRAM_ADMIN,
    ROLE_QA_REVIEWER,
    ROLE_RATING_ENGINEER,
)

# ─── Opaque operator identifiers (PRD §2.1) ────────────────────────────────
# These are never compared against a Personnel row, so any stable string works.
PROGRAM_ADMIN_USER_ID = "pa-1"
PERMIT_OFFICER_USER_ID = "po-4"
FHWA_REVIEWER_USER_ID = "fr-9"

# A second FhwaReviewer identity, for the self-review segregation-of-duties rule
# of PRD §2.10 where the reviewer's identifier "must differ from
# `submitted_by_user_id`".
FHWA_REVIEWER_ALT_USER_ID = "fr-10"

# A second ProgramAdmin identity, for the case where the submitting
# administrator and some other administrator must be told apart.
PROGRAM_ADMIN_ALT_USER_ID = "pa-2"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "program_admin": {"user_id": PROGRAM_ADMIN_USER_ID, "role": ROLE_PROGRAM_ADMIN},
    "program_admin_alt": {
        "user_id": PROGRAM_ADMIN_ALT_USER_ID,
        "role": ROLE_PROGRAM_ADMIN,
    },
    "permit_officer": {"user_id": PERMIT_OFFICER_USER_ID, "role": ROLE_PERMIT_OFFICER},
    "fhwa_reviewer": {"user_id": FHWA_REVIEWER_USER_ID, "role": ROLE_FHWA_REVIEWER},
    "fhwa_reviewer_alt": {
        "user_id": FHWA_REVIEWER_ALT_USER_ID,
        "role": ROLE_FHWA_REVIEWER,
    },
}


# ─── Opaque-operator header builders ───────────────────────────────────────
def program_admin_headers(user_id: str = PROGRAM_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for the `ProgramAdmin` opaque operator."""
    return build_user_headers(user_id, ROLE_PROGRAM_ADMIN)


def permit_officer_headers(user_id: str = PERMIT_OFFICER_USER_ID) -> Dict[str, str]:
    """Headers for the `PermitOfficer` opaque operator."""
    return build_user_headers(user_id, ROLE_PERMIT_OFFICER)


def fhwa_reviewer_headers(user_id: str = FHWA_REVIEWER_USER_ID) -> Dict[str, str]:
    """Headers for the `FhwaReviewer` opaque operator."""
    return build_user_headers(user_id, ROLE_FHWA_REVIEWER)


# ─── Entity-backed header builders ─────────────────────────────────────────
def make_bridge_inspector_headers(personnel_id: str) -> Dict[str, str]:
    """Headers for a `BridgeInspector`; `personnel_id` is the acting roster row."""
    return build_user_headers(personnel_id, ROLE_BRIDGE_INSPECTOR)


def make_qa_reviewer_headers(personnel_id: str) -> Dict[str, str]:
    """Headers for a `QaReviewer`; `personnel_id` is the acting roster row."""
    return build_user_headers(personnel_id, ROLE_QA_REVIEWER)


def make_rating_engineer_headers(personnel_id: str) -> Dict[str, str]:
    """Headers for a `RatingEngineer`; `personnel_id` is the acting roster row."""
    return build_user_headers(personnel_id, ROLE_RATING_ENGINEER)


def make_district_engineer_headers(personnel_id: str) -> Dict[str, str]:
    """Headers for a `DistrictEngineer`; `personnel_id` is the acting roster row."""
    return build_user_headers(personnel_id, ROLE_DISTRICT_ENGINEER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Generic builder, for tests that sweep the role list of PRD §2.1."""
    return build_user_headers(user_id, role)
