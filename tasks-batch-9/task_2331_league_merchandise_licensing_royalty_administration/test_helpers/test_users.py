"""Role headers.

The PRD identifies a caller by two headers: the role name in `X-User-Role` and the
acting user in `X-User-ID`. Three of the seven roles are scoped to the entity they
speak for — a Licensee acts for its own licensee record, a ClubRepresentative for its
own club and a PlayerAgent for its own player — so those callers must be built with
the real resource id, never with a shared placeholder.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque operator user ids used across the suite.
OPS_USER_ID = "u_ops_1"
MCO_USER_ID = "u_mco_1"
FIN_USER_ID = "u_fin_1"
FIN_USER_ID_ALT = "u_fin_2"
AUDITOR_USER_ID = "u_aud_1"
AUDITOR_USER_ID_ALT = "u_aud_2"


TEST_USERS = {
    "league_licensing_manager_headers": build_user_headers(
        OPS_USER_ID, Role.LEAGUE_LICENSING_MANAGER.value
    ),
    "mark_compliance_officer_headers": build_user_headers(
        MCO_USER_ID, Role.MARK_COMPLIANCE_OFFICER.value
    ),
    "finance_controller_headers": build_user_headers(
        FIN_USER_ID, Role.FINANCE_CONTROLLER.value
    ),
    "finance_controller_alt_headers": build_user_headers(
        FIN_USER_ID_ALT, Role.FINANCE_CONTROLLER.value
    ),
    "royalty_auditor_headers": build_user_headers(AUDITOR_USER_ID, Role.ROYALTY_AUDITOR.value),
    "royalty_auditor_alt_headers": build_user_headers(
        AUDITOR_USER_ID_ALT, Role.ROYALTY_AUDITOR.value
    ),
}


# ---------------------------------------------------------------------------
# Operator-role builders (any opaque user id is acceptable)
# ---------------------------------------------------------------------------


def make_league_licensing_manager_headers(user_id: str = OPS_USER_ID) -> dict:
    return build_user_headers(user_id, Role.LEAGUE_LICENSING_MANAGER.value)


def make_mark_compliance_officer_headers(user_id: str = MCO_USER_ID) -> dict:
    return build_user_headers(user_id, Role.MARK_COMPLIANCE_OFFICER.value)


def make_finance_controller_headers(user_id: str = FIN_USER_ID) -> dict:
    return build_user_headers(user_id, Role.FINANCE_CONTROLLER.value)


def make_royalty_auditor_headers(user_id: str = AUDITOR_USER_ID) -> dict:
    return build_user_headers(user_id, Role.ROYALTY_AUDITOR.value)


# ---------------------------------------------------------------------------
# Entity-scoped builders — pass the real resource id
# ---------------------------------------------------------------------------


def make_licensee_headers(licensee_id: str) -> dict:
    """Headers for the Licensee role acting for its own licensee record."""
    return build_user_headers(licensee_id, Role.LICENSEE.value)


def make_club_representative_headers(club_id: str) -> dict:
    """Headers for the ClubRepresentative role acting for its own club."""
    return build_user_headers(club_id, Role.CLUB_REPRESENTATIVE.value)


def make_player_agent_headers(player_id: str) -> dict:
    """Headers for the PlayerAgent role acting for its own player."""
    return build_user_headers(player_id, Role.PLAYER_AGENT.value)


# ---------------------------------------------------------------------------
# Deliberately malformed identity headers
# ---------------------------------------------------------------------------


def make_headers_with_role(role_name: str, user_id: str = "u_any_1") -> dict:
    """Headers naming an arbitrary role string, including names the PRD does not recognise."""
    return build_user_headers(user_id, role_name)


def make_headers_without_user_id(role_name: str) -> dict:
    """A recognised role header with no `X-User-ID` at all."""
    return {"X-User-Role": role_name, "Content-Type": "application/json"}


def make_headers_with_empty_user_id(role_name: str) -> dict:
    """A recognised role header whose `X-User-ID` is present but empty."""
    return {"X-User-Role": role_name, "X-User-ID": "", "Content-Type": "application/json"}


def make_headers_without_role(user_id: str = "u_any_1") -> dict:
    """Identity headers with no role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
