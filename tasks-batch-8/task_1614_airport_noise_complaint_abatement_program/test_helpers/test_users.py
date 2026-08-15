"""Pre-built role headers for every role named in PRD 2.1.

`OperatorRep` carries the acting Operator's id in `X-User-ID`; `Complainant`
carries the acting Complainant's id. Those two roles therefore need
per-instance builders — the shared constants below are only safe for calls
whose success does not depend on the caller owning the subject resource. The
five staff roles carry opaque identifiers that are never compared to any
entity id.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Header set carrying no credentials at all (auth gate must reject it).
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque staff identities — the shared constant is the canonical form.
    "noise_office_admin_headers": build_user_headers("admin-op-1", "NoiseOfficeAdmin"),
    "noise_analyst_headers": build_user_headers("analyst-op-1", "NoiseAnalyst"),
    "community_liaison_headers": build_user_headers("liaison-op-1", "CommunityLiaison"),
    "study_coordinator_headers": build_user_headers("coordinator-op-1", "StudyCoordinator"),
    "board_member_headers": build_user_headers("board-op-1", "BoardMember"),
    # Entity-backed identities — fallbacks for non-ownership tests only.
    "operator_rep_headers": build_user_headers("test-operator-1", "OperatorRep"),
    "complainant_headers": build_user_headers("test-complainant-1", "Complainant"),
}


def make_operator_rep_headers(operator_id: str) -> Dict[str, str]:
    """For OperatorRep (entity-backed by Operator). Pass the acting Operator's id
    whenever the call is ownership-gated."""
    return build_user_headers(operator_id, "OperatorRep")


def make_complainant_headers(complainant_id: str) -> Dict[str, str]:
    """For Complainant (entity-backed by Complainant). Pass the acting
    Complainant's id whenever the call is ownership-gated."""
    return build_user_headers(complainant_id, "Complainant")


def make_noise_office_admin_headers(user_id: str = "admin-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "NoiseOfficeAdmin")


def make_noise_analyst_headers(user_id: str = "analyst-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "NoiseAnalyst")


def make_community_liaison_headers(user_id: str = "liaison-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "CommunityLiaison")


def make_study_coordinator_headers(user_id: str = "coordinator-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "StudyCoordinator")


def make_board_member_headers(user_id: str = "board-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "BoardMember")
