"""Pre-built role headers for the five PRD roles (PRD §2.1).

All five roles are opaque: X-User-ID is never compared to any entity id, only
to recorded user ids on prior-stage records (segregation of duties). Shared
constants below use fixed operator ids; segregation-sensitive flows build
headers with explicit user ids via make_user_headers().
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Primary operator per role.
    "admin_headers": build_user_headers("admin-1", "EndowmentAdmin"),
    "io_headers": build_user_headers("io-1", "InvestmentOfficer"),
    "dev_headers": build_user_headers("dev-1", "DevelopmentOfficer"),
    "board_headers": build_user_headers("bm-1", "BoardMember"),
    "program_headers": build_user_headers("pm-1", "ProgramManager"),
    # Secondary operators — segregation-of-duties counterparties.
    "io2_headers": build_user_headers("io-2", "InvestmentOfficer"),
    "dev2_headers": build_user_headers("dev-2", "DevelopmentOfficer"),
    "board2_headers": build_user_headers("bm-2", "BoardMember"),
}


def make_user_headers(user_id: str, role: str) -> dict:
    """Build headers for an arbitrary operator id (all roles are opaque per PRD §2.1)."""
    return build_user_headers(user_id, role)


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EndowmentAdmin")


def make_investment_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "InvestmentOfficer")


def make_development_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DevelopmentOfficer")


def make_board_member_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BoardMember")


def make_program_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramManager")
