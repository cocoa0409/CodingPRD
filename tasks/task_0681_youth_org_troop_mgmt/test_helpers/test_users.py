"""Pre-built role headers for every role in the PRD.

Both roles are opaque operator identities — the X-User-ID is never compared to
any entity id for ownership (PRD §2.1). The shared constants below are therefore
the canonical form for ordinary calls. Segregation-of-duties workflows (background
check resolve, advancement approve) DO compare X-User-ID against a recorded
operator id, so those scenarios use the per-id builders to control who acts.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    LEADER_USER_ID,
    REGISTRAR_USER_ID,
    OTHER_REGISTRAR_USER_ID,
)

# Shared constants — canonical for opaque roles.
TEST_USERS = {
    "registrar_headers": build_user_headers(REGISTRAR_USER_ID, "CouncilRegistrar"),
    "leader_headers": build_user_headers(LEADER_USER_ID, "TroopLeader"),
    # A second distinct registrar identity for segregation-of-duties resolvers.
    "other_registrar_headers": build_user_headers(OTHER_REGISTRAR_USER_ID, "CouncilRegistrar"),
}


def make_registrar_headers(user_id: str) -> dict:
    """CouncilRegistrar headers for a specific operator id. Use to control the
    acting identity in segregation-of-duties scenarios."""
    return build_user_headers(user_id, "CouncilRegistrar")


def make_leader_headers(user_id: str) -> dict:
    """TroopLeader headers for a specific operator id. Use to control the acting
    identity in segregation-of-duties scenarios (e.g. advancement submit/approve)."""
    return build_user_headers(user_id, "TroopLeader")
