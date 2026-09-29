"""Acting identities and the header builders that carry them.

Five roles are opaque: any stable identifier works, so a canonical constant is
provided for each. Three roles are entity-backed -- `InsurerRep` acts as an
`Insurer`, `Participant` acts as a `ParticipantRecord`, and
`IndependentExpertUser` acts as an `IndependentExpert` -- so for those the
acting `X-User-ID` must be the owning entity's `id`. Never reuse a shared
constant for an entity-backed role: build the headers from the entity id with
the per-instance builders below.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole


# ---------------------------------------------------------------------------
# Opaque identities
# ---------------------------------------------------------------------------

SPONSOR_USER_ID = "sponsor-treasury-01"
FIDUCIARY_USER_ID = "fiduciary-01"
ACTUARY_USER_ID = "actuary-01"
#: A second actuary, for flows that need two distinct submitters.
ACTUARY_ALT_USER_ID = "actuary-02"
ADMINISTRATOR_USER_ID = "tpa-ops-01"
REGULATOR_USER_ID = "regulator-01"

#: A second fiduciary, for flows that need a reviewer distinct from a proposer.
FIDUCIARY_ALT_USER_ID = "fiduciary-02"
#: A second sponsor identity, for segregation-of-duties contrasts.
SPONSOR_ALT_USER_ID = "sponsor-treasury-02"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "sponsor": {"user_id": SPONSOR_USER_ID, "role": UserRole.PLAN_SPONSOR.value},
    "sponsor_alt": {"user_id": SPONSOR_ALT_USER_ID, "role": UserRole.PLAN_SPONSOR.value},
    "fiduciary": {"user_id": FIDUCIARY_USER_ID, "role": UserRole.PLAN_FIDUCIARY.value},
    "fiduciary_alt": {
        "user_id": FIDUCIARY_ALT_USER_ID,
        "role": UserRole.PLAN_FIDUCIARY.value,
    },
    "actuary": {"user_id": ACTUARY_USER_ID, "role": UserRole.ACTUARY.value},
    "actuary_alt": {"user_id": ACTUARY_ALT_USER_ID, "role": UserRole.ACTUARY.value},
    "administrator": {
        "user_id": ADMINISTRATOR_USER_ID,
        "role": UserRole.PLAN_ADMINISTRATOR.value,
    },
    "regulator": {"user_id": REGULATOR_USER_ID, "role": UserRole.REGULATOR.value},
}


def _headers(key: str) -> Dict[str, str]:
    spec = TEST_USERS[key]
    return build_user_headers(spec["user_id"], spec["role"])


def sponsor_headers() -> Dict[str, str]:
    return _headers("sponsor")


def sponsor_alt_headers() -> Dict[str, str]:
    return _headers("sponsor_alt")


def fiduciary_headers() -> Dict[str, str]:
    return _headers("fiduciary")


def fiduciary_alt_headers() -> Dict[str, str]:
    return _headers("fiduciary_alt")


def actuary_headers() -> Dict[str, str]:
    return _headers("actuary")


def actuary_alt_headers() -> Dict[str, str]:
    return _headers("actuary_alt")


def administrator_headers() -> Dict[str, str]:
    return _headers("administrator")


def regulator_headers() -> Dict[str, str]:
    return _headers("regulator")


def opaque_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary opaque-identity role and user id."""
    return build_user_headers(user_id, role)


# ---------------------------------------------------------------------------
# Entity-backed identities: one builder per instance
# ---------------------------------------------------------------------------


def make_insurer_rep_headers(insurer_id: str) -> Dict[str, str]:
    """Headers for the representative of the insurer identified by `insurer_id`."""
    return build_user_headers(insurer_id, UserRole.INSURER_REP.value)


def make_participant_headers(participant_id: str) -> Dict[str, str]:
    """Headers for the participant identified by `participant_id`."""
    return build_user_headers(participant_id, UserRole.PARTICIPANT.value)


def make_expert_headers(expert_id: str) -> Dict[str, str]:
    """Headers for the independent expert identified by `expert_id`."""
    return build_user_headers(expert_id, UserRole.INDEPENDENT_EXPERT_USER.value)


ALL_ROLE_NAMES = [role.value for role in UserRole]
OPAQUE_ROLE_NAMES = [
    UserRole.PLAN_SPONSOR.value,
    UserRole.PLAN_FIDUCIARY.value,
    UserRole.ACTUARY.value,
    UserRole.PLAN_ADMINISTRATOR.value,
    UserRole.REGULATOR.value,
]
