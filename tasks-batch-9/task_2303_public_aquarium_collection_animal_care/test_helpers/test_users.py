"""Identity headers for the six roles of PRD §2.1.

Every request carries `X-User-ID` and `X-User-Role`. For a
`PartnerInstitutionLiaison` the `X-User-ID` *is* the id of the institution the
liaison speaks for, so liaison headers must always be built from a real
institution id — hence `make_liaison_headers`.

Several rules pair two steps that must be performed by different people, so the
module also publishes distinct named user ids for each side of those pairs.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --------------------------------------------------------------------------
# Default actor ids
# --------------------------------------------------------------------------
CURATOR_ID = "user-curator-01"
DIRECTOR_ID = "user-director-01"
VET_ID = "user-vet-01"
AQUARIST_ID = "user-aquarist-01"
PERMIT_OFFICER_ID = "user-permit-officer-01"

# Second identities for the segregation-of-duties pairs
DIRECTOR_SECOND_ID = "user-director-02"
DIRECTOR_THIRD_ID = "user-director-03"
VET_SECOND_ID = "user-vet-02"
VET_THIRD_ID = "user-vet-03"
CURATOR_SECOND_ID = "user-curator-02"
AQUARIST_SECOND_ID = "user-aquarist-02"
PERMIT_OFFICER_SECOND_ID = "user-permit-officer-02"

# Readable aliases for the specific paired steps named in the PRD
PLAN_APPROVER_ID = DIRECTOR_ID
CLEARANCE_OFFICER_ID = DIRECTOR_SECOND_ID
AUDIT_OPENER_ID = DIRECTOR_ID
AUDIT_CLOSER_ID = DIRECTOR_SECOND_ID
NECROPSY_OPENER_ID = VET_ID
NECROPSY_FINALIZER_ID = VET_SECOND_ID


# --------------------------------------------------------------------------
# Header builders
# --------------------------------------------------------------------------
def make_curator_headers(user_id: str = CURATOR_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.CURATOR_OF_COLLECTIONS.value)


def make_director_headers(user_id: str = DIRECTOR_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.COMPLIANCE_DIRECTOR.value)


def make_vet_headers(user_id: str = VET_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.VETERINARY_OFFICER.value)


def make_aquarist_headers(user_id: str = AQUARIST_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.AQUARIST_TECHNICIAN.value)


def make_permit_officer_headers(user_id: str = PERMIT_OFFICER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.PERMIT_OFFICER.value)


def make_liaison_headers(institution_id: str) -> Dict[str, str]:
    """Liaison identity: the user id is the institution id it represents."""
    return build_user_headers(institution_id, UserRole.PARTNER_INSTITUTION_LIAISON.value)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Free-form builder for role/identity combinations a test wants to vary."""
    return build_user_headers(user_id, role)


# --------------------------------------------------------------------------
# Ready-made header dicts for the common actors
# --------------------------------------------------------------------------
CURATOR_HEADERS = make_curator_headers()
DIRECTOR_HEADERS = make_director_headers()
DIRECTOR_SECOND_HEADERS = make_director_headers(DIRECTOR_SECOND_ID)
VET_HEADERS = make_vet_headers()
VET_SECOND_HEADERS = make_vet_headers(VET_SECOND_ID)
AQUARIST_HEADERS = make_aquarist_headers()
PERMIT_OFFICER_HEADERS = make_permit_officer_headers()

TEST_USERS = {
    "curator": CURATOR_HEADERS,
    "curator_second": make_curator_headers(CURATOR_SECOND_ID),
    "director": DIRECTOR_HEADERS,
    "director_second": DIRECTOR_SECOND_HEADERS,
    "director_third": make_director_headers(DIRECTOR_THIRD_ID),
    "vet": VET_HEADERS,
    "vet_second": VET_SECOND_HEADERS,
    "vet_third": make_vet_headers(VET_THIRD_ID),
    "aquarist": AQUARIST_HEADERS,
    "aquarist_second": make_aquarist_headers(AQUARIST_SECOND_ID),
    "permit_officer": PERMIT_OFFICER_HEADERS,
    "permit_officer_second": make_permit_officer_headers(PERMIT_OFFICER_SECOND_ID),
}

ALL_ROLE_VALUES = [r.value for r in UserRole]
