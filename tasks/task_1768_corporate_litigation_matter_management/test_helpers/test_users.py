"""Pre-built role headers for every role in the PRD.

Every role except BoardCommittee is identity-bound to the staff directory
(PRD §2.1): whenever a call is ownership- or SoD-gated, fixtures MUST build
headers with the acting staff user's real id via the make_* builders below.
The shared constants are only for calls whose success cannot depend on the
caller's identity (directory administration, clock, vendor/firm registry).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for non-ownership calls and opaque roles.
TEST_USERS = {
    "counsel_headers": build_user_headers("test-counsel-1", "LitigationCounsel"),
    "dgc_headers": build_user_headers("test-dgc-1", "DeputyGeneralCounsel"),
    "gc_headers": build_user_headers("test-gc-1", "GeneralCounsel"),
    "cfo_headers": build_user_headers("test-cfo-1", "ChiefFinancialOfficer"),
    "ops_headers": build_user_headers("test-ops-1", "LegalOperationsAnalyst"),
    "fin_headers": build_user_headers("test-fin-1", "FinanceBusinessPartner"),
    "staff_headers": build_user_headers("test-staff-1", "StaffUser"),
    # Opaque role: X-User-ID is never compared to any entity id.
    "board_headers": build_user_headers("board-session-1", "BoardCommittee"),
}


def make_counsel_headers(user_id: str) -> dict:
    """LitigationCounsel acting as a specific staff user (entity-bound)."""
    return build_user_headers(user_id, "LitigationCounsel")


def make_dgc_headers(user_id: str) -> dict:
    """DeputyGeneralCounsel acting as a specific staff user (entity-bound)."""
    return build_user_headers(user_id, "DeputyGeneralCounsel")


def make_gc_headers(user_id: str) -> dict:
    """GeneralCounsel acting as a specific staff user (entity-bound)."""
    return build_user_headers(user_id, "GeneralCounsel")


def make_cfo_headers(user_id: str) -> dict:
    """ChiefFinancialOfficer acting as a specific staff user (entity-bound)."""
    return build_user_headers(user_id, "ChiefFinancialOfficer")


def make_ops_headers(user_id: str) -> dict:
    """LegalOperationsAnalyst acting as a specific staff user (entity-bound)."""
    return build_user_headers(user_id, "LegalOperationsAnalyst")


def make_fin_headers(user_id: str) -> dict:
    """FinanceBusinessPartner acting as a specific staff user (entity-bound)."""
    return build_user_headers(user_id, "FinanceBusinessPartner")


def make_staff_headers(user_id: str) -> dict:
    """StaffUser self-acknowledgement headers (entity-bound)."""
    return build_user_headers(user_id, "StaffUser")
