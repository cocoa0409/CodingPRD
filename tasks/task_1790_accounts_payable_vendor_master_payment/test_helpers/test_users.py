"""Pre-built role headers for every role in the PRD (§2.1).

All twelve roles are opaque operator identities: the X-User-ID is recorded on
resources the caller creates or mutates (created_by_user_id, submitted_by_user_id,
requested_by_user_id, approved_by_user_id, ...) and compared only against those
recorded anchors by the segregation-of-duties rules — never against an entity id.
Shared per-user constants below are therefore the canonical form for every role.
"""
from prd_bench_local_runner.testing import build_user_headers

# --- Operator ids used across the suite (kept stable so SoD anchors are legible) ---
USER_SYS_ADMIN = "u-sys-01"
USER_SPECIALIST_1 = "u-vs-01"
USER_SPECIALIST_2 = "u-vs-02"
USER_VENDOR_MANAGER_1 = "u-vm-01"
USER_VENDOR_MANAGER_2 = "u-vm-02"
USER_COMPLIANCE = "u-co-01"
USER_AP_CLERK = "u-ap-01"
USER_SUPERVISOR_1 = "u-sup-01"
USER_SUPERVISOR_2 = "u-sup-02"
USER_AP_MANAGER = "u-mgr-01"
USER_CONTROLLER = "u-ctl-01"
USER_TREASURY_ANALYST = "u-ta-01"
USER_TREASURY_MANAGER_1 = "u-tm-01"
USER_TREASURY_MANAGER_2 = "u-tm-02"
USER_BANK_PROCESSOR = "u-bfp-01"
USER_AUDITOR = "u-aud-01"
USER_FLOATER = "u-float-01"

TEST_USERS = {
    "system_admin_headers": build_user_headers(USER_SYS_ADMIN, "SystemAdmin"),
    "vendor_specialist_headers": build_user_headers(USER_SPECIALIST_1, "VendorSpecialist"),
    "vendor_specialist_2_headers": build_user_headers(USER_SPECIALIST_2, "VendorSpecialist"),
    "vendor_manager_headers": build_user_headers(USER_VENDOR_MANAGER_1, "VendorManager"),
    "vendor_manager_2_headers": build_user_headers(USER_VENDOR_MANAGER_2, "VendorManager"),
    "compliance_officer_headers": build_user_headers(USER_COMPLIANCE, "ComplianceOfficer"),
    "ap_clerk_headers": build_user_headers(USER_AP_CLERK, "APClerk"),
    "ap_supervisor_headers": build_user_headers(USER_SUPERVISOR_1, "APSupervisor"),
    "ap_supervisor_2_headers": build_user_headers(USER_SUPERVISOR_2, "APSupervisor"),
    "ap_manager_headers": build_user_headers(USER_AP_MANAGER, "APManager"),
    "controller_headers": build_user_headers(USER_CONTROLLER, "Controller"),
    "treasury_analyst_headers": build_user_headers(USER_TREASURY_ANALYST, "TreasuryAnalyst"),
    "treasury_manager_headers": build_user_headers(USER_TREASURY_MANAGER_1, "TreasuryManager"),
    "treasury_manager_2_headers": build_user_headers(USER_TREASURY_MANAGER_2, "TreasuryManager"),
    "bank_file_processor_headers": build_user_headers(USER_BANK_PROCESSOR, "BankFileProcessor"),
    "auditor_headers": build_user_headers(USER_AUDITOR, "Auditor"),
}

# Fixed per-tier approver headers for the happy-path approval chain: tier 1 belongs
# to an APSupervisor, tier 2 to an APManager, tier 3 to a Controller (PRD §3.5),
# and the three operators are distinct so one user never approves two tiers (§2.6).
TIER_APPROVER_HEADERS = {
    1: TEST_USERS["ap_supervisor_headers"],
    2: TEST_USERS["ap_manager_headers"],
    3: TEST_USERS["controller_headers"],
}


def make_role_headers(user_id: str, role: str) -> dict:
    """Build headers for an arbitrary operator id in any declared role."""
    return build_user_headers(user_id, role)
