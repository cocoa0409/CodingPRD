"""Pre-built role headers for every role in the PRD (§2.1).

AccountHolder is entity-backed on DepositAccount: ownership-gated calls MUST
use make_account_holder_headers(account["id"]) so X-User-ID equals the account
id. The shared constant is a fallback only for tests that do not exercise
ownership (e.g., role-forbidden checks).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    "clerk_headers": build_user_headers("clerk-1", "OperationsClerk"),
    "teller_1_headers": build_user_headers("teller-1", "Teller"),
    "teller_2_headers": build_user_headers("teller-2", "Teller"),
    "teller_3_headers": build_user_headers("teller-3", "Teller"),
    "supervisor_1_headers": build_user_headers("sup-1", "Supervisor"),
    "supervisor_2_headers": build_user_headers("sup-2", "Supervisor"),
    "supervisor_7_headers": build_user_headers("sup-7", "Supervisor"),
    "supervisor_8_headers": build_user_headers("sup-8", "Supervisor"),
    "supervisor_9_headers": build_user_headers("sup-9", "Supervisor"),
    "manager_1_headers": build_user_headers("mgr-1", "Manager"),
    "compliance_1_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "compliance_2_headers": build_user_headers("co-2", "ComplianceOfficer"),
    "compliance_9_headers": build_user_headers("co-9", "ComplianceOfficer"),
    # Fallback for non-ownership tests only (PRD §2.1: entity-backed role).
    "account_holder_headers": build_user_headers("holder-opaque-1", "AccountHolder"),
}


def make_account_holder_headers(account_id: str) -> dict:
    """For AccountHolder (entity-backed on DepositAccount). Pass the actual
    DepositAccount.id whenever the call is ownership-gated (transactions,
    opt-in election create/revoke/reinstate, waiver create/appeal, offer
    accept/decline)."""
    return build_user_headers(account_id, "AccountHolder")


def make_supervisor_headers(user_id: str) -> dict:
    """Per-supervisor headers; segregation of duties compares X-User-ID."""
    return build_user_headers(user_id, "Supervisor")


def make_manager_headers(user_id: str) -> dict:
    """Per-manager headers; segregation of duties compares X-User-ID."""
    return build_user_headers(user_id, "Manager")


def make_compliance_headers(user_id: str) -> dict:
    """Per-officer headers; segregation of duties compares X-User-ID."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_teller_headers(user_id: str) -> dict:
    """Per-teller headers; segregation of duties compares X-User-ID."""
    return build_user_headers(user_id, "Teller")
