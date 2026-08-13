"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (PlatformAdmin, DocketingClerk, DocketingManager, RecordsSpecialist,
FinanceOfficer) may use the shared constants freely. Entity-backed roles
(ClientApprover -> ClientContact, OutsideCounsel -> CounselFirm) MUST be built
with the backing entity's real id via the make_* builders whenever the call is
scope-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "clerk_headers": build_user_headers("clerk-1", "DocketingClerk"),
    "manager_headers": build_user_headers("mgr-1", "DocketingManager"),
    "manager2_headers": build_user_headers("mgr-2", "DocketingManager"),
    "records_headers": build_user_headers("rec-1", "RecordsSpecialist"),
    "records2_headers": build_user_headers("rec-2", "RecordsSpecialist"),
    "finance_headers": build_user_headers("fin-1", "FinanceOfficer"),
    # Fallbacks for non-ownership tests only; scope-gated calls must use the builders below.
    "client_approver_headers": build_user_headers("test-approver-1", "ClientApprover"),
    "outside_counsel_headers": build_user_headers("test-counsel-1", "OutsideCounsel"),
    # Read-only shared surface: any authenticated caller may use Any endpoints.
    "any_headers": build_user_headers("reader-1", "PlatformAdmin"),
}


def make_client_approver_headers(contact_id: str) -> dict:
    """ClientApprover is entity-backed by ClientContact: pass the contact's id."""
    return build_user_headers(contact_id, "ClientApprover")


def make_outside_counsel_headers(counsel_firm_id: str) -> dict:
    """OutsideCounsel is entity-backed by CounselFirm: pass the firm's id."""
    return build_user_headers(counsel_firm_id, "OutsideCounsel")


def make_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DocketingManager")


def make_records_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RecordsSpecialist")
