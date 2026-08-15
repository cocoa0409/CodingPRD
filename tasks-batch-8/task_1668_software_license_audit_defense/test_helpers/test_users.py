"""Pre-built role headers for every role in the PRD (§2.1).

All six roles are opaque: `X-User-ID` is not tied to any persisted entity, so the
shared constants are the canonical form. The `make_*_headers` builders exist for
segregation-of-duties scenarios, where a specific user id must be threaded
(e.g., the approver must differ from `prepared_by_user_id`).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "SAMPlatformAdmin"),
    "sam_manager_headers": build_user_headers("sam-mgr-1", "SAMManager"),
    "it_analyst_headers": build_user_headers("it-1", "ITAnalyst"),
    "legal_counsel_headers": build_user_headers("counsel-1", "LegalCounsel"),
    "procurement_lead_headers": build_user_headers("proc-1", "ProcurementLead"),
    "vendor_auditor_headers": build_user_headers("aud-1", "VendorAuditor"),
}


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SAMPlatformAdmin")


def make_sam_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SAMManager")


def make_it_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ITAnalyst")


def make_legal_counsel_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LegalCounsel")


def make_procurement_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProcurementLead")


def make_vendor_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "VendorAuditor")
