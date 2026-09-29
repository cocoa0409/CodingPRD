"""
Identity headers for the six declared roles.

Four roles carry opaque identity, so a single shared constant per role is
enough. Two roles are entity-backed — an Artist's `X-User-ID` must resolve to
an `Artist` row and a Panelist's to a `Panelist` row — so those callers must be
built per entity with `make_artist_headers()` / `make_panelist_headers()`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# --- opaque-identity roles -------------------------------------------------
PROGRAM_OFFICER_ID = "officer-1"
PROGRAM_OFFICER_2_ID = "officer-2"
BOARD_MEMBER_ID = "board-1"
BOARD_MEMBER_2_ID = "board-2"
APPEALS_OFFICER_ID = "appeals-1"
APPEALS_OFFICER_2_ID = "appeals-2"
FISCAL_OFFICER_ID = "fiscal-1"
FISCAL_OFFICER_2_ID = "fiscal-2"

PROGRAM_OFFICER = build_user_headers(PROGRAM_OFFICER_ID, "ProgramOfficer")
PROGRAM_OFFICER_2 = build_user_headers(PROGRAM_OFFICER_2_ID, "ProgramOfficer")
BOARD_MEMBER = build_user_headers(BOARD_MEMBER_ID, "CouncilBoardMember")
BOARD_MEMBER_2 = build_user_headers(BOARD_MEMBER_2_ID, "CouncilBoardMember")
APPEALS_OFFICER = build_user_headers(APPEALS_OFFICER_ID, "AppealsOfficer")
APPEALS_OFFICER_2 = build_user_headers(APPEALS_OFFICER_2_ID, "AppealsOfficer")
FISCAL_OFFICER = build_user_headers(FISCAL_OFFICER_ID, "FiscalOfficer")
FISCAL_OFFICER_2 = build_user_headers(FISCAL_OFFICER_2_ID, "FiscalOfficer")

TEST_USERS: Dict[str, Dict[str, str]] = {
    "ProgramOfficer": PROGRAM_OFFICER,
    "CouncilBoardMember": BOARD_MEMBER,
    "AppealsOfficer": APPEALS_OFFICER,
    "FiscalOfficer": FISCAL_OFFICER,
}


# --- entity-backed roles ---------------------------------------------------
def make_artist_headers(artist_id: str) -> Dict[str, str]:
    """Headers for an `Artist` caller; `X-User-ID` is the Artist row's id."""
    return build_user_headers(artist_id, "Artist")


def make_panelist_headers(panelist_id: str) -> Dict[str, str]:
    """Headers for a `Panelist` caller; `X-User-ID` is the Panelist row's id."""
    return build_user_headers(panelist_id, "Panelist")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for identity-negative tests (unknown ids, unknown roles)."""
    return build_user_headers(user_id, role)


def headers_missing_user_id(role: str = "ProgramOfficer") -> Dict[str, str]:
    """Headers with no `X-User-ID` at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str = PROGRAM_OFFICER_ID) -> Dict[str, str]:
    """Headers with no `X-User-Role` at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
