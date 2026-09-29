"""Pre-built role headers for every role the PRD defines.

Five roles carry an opaque caller identity: any non-empty X-User-ID is accepted
and the shared constants below are the canonical form for them.

Two roles are entity-backed.  For TallyTeamLead the X-User-ID must equal the
TallyTeam.id the caller leads; for Observer it must equal the
ObserverCredential.id.  Ownership-gated calls MUST therefore be made with
make_tally_team_lead_headers(team["id"]) / make_observer_headers(credential["id"])
and never with the shared constant, which resolves to no entity at all.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# --- shared constants ------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # opaque identities
    "elections_director_headers": build_user_headers("dir-1", "ElectionsDirector"),
    "audit_manager_headers": build_user_headers("am-1", "AuditManager"),
    "custody_officer_headers": build_user_headers("co-1", "CustodyOfficer"),
    "canvassing_board_member_headers": build_user_headers(
        "u-board-1", "CanvassingBoardMember"
    ),
    "candidate_representative_headers": build_user_headers(
        "rep-davis", "CandidateRepresentative"
    ),
    # entity-backed identities: fallback for calls that resolve no ownership
    "tally_team_lead_headers": build_user_headers("tl-1", "TallyTeamLead"),
    "observer_headers": build_user_headers("obs-1", "Observer"),
}


# --- per-instance builders -------------------------------------------------
def make_elections_director_headers(user_id: str) -> Dict[str, str]:
    """ElectionsDirector with a caller-chosen user id."""
    return build_user_headers(user_id, "ElectionsDirector")


def make_audit_manager_headers(user_id: str) -> Dict[str, str]:
    """AuditManager with a caller-chosen user id."""
    return build_user_headers(user_id, "AuditManager")


def make_custody_officer_headers(user_id: str) -> Dict[str, str]:
    """CustodyOfficer with a caller-chosen user id."""
    return build_user_headers(user_id, "CustodyOfficer")


def make_canvassing_board_member_headers(user_id: str) -> Dict[str, str]:
    """CanvassingBoardMember; the user id identifies the individual board member."""
    return build_user_headers(user_id, "CanvassingBoardMember")


def make_candidate_representative_headers(user_id: str) -> Dict[str, str]:
    """CandidateRepresentative; the user id identifies the filing representative."""
    return build_user_headers(user_id, "CandidateRepresentative")


def make_tally_team_lead_headers(tally_team_id: str) -> Dict[str, str]:
    """TallyTeamLead.  Pass the TallyTeam.id whose count is being driven."""
    return build_user_headers(tally_team_id, "TallyTeamLead")


def make_observer_headers(observer_credential_id: str) -> Dict[str, str]:
    """Observer.  Pass the ObserverCredential.id granting the access."""
    return build_user_headers(observer_credential_id, "Observer")


ALL_ROLE_NAMES = [
    "ElectionsDirector",
    "AuditManager",
    "CustodyOfficer",
    "TallyTeamLead",
    "CanvassingBoardMember",
    "CandidateRepresentative",
    "Observer",
]
