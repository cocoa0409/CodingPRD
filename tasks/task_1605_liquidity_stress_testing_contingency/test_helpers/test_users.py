"""Pre-built role headers for every role in the PRD (§2.1).

All five roles are opaque: PRD §2.1 states "X-User-ID is an opaque operator
identifier not tied to any persisted entity ... it never compares X-User-ID
to any entity's id". The segregation-of-duties checks compare X-User-ID only
against recorded audit fields (created_by_user_id, acknowledged_by_user_id),
so the per-test user-id strings below ARE the audit anchors — fixtures pass
these exact ids when creating playbooks or acknowledging breaches so that
approvals and remediations by a different user satisfy the SoD gate.
"""
from prd_bench_local_runner.testing import build_user_headers

# Named operator ids used across fixtures and tests. These strings become the
# recorded created_by_user_id / acknowledged_by_user_id values that the SoD
# gates compare against (PRD §2.1, §3.9, §3.7).
USER_ANALYST_1 = "ta_1"        # canonical playbook drafter
USER_ANALYST_9 = "ta_9"        # a second analyst (RBAC denial probes)
USER_OFFICER_1 = "ro_1"        # canonical breach acknowledger
USER_OFFICER_2 = "ro_2"        # canonical playbook approver / remediator
USER_OFFICER_3 = "ro_3"        # officer probing the ESCALATED-remediate gate
USER_COMMITTEE_1 = "lc_1"      # canonical committee actor
USER_COMMITTEE_9 = "lc_9"      # committee escalator
USER_OPS_1 = "to_1"            # treasury operations actor
USER_ADMIN_1 = "pa_1"          # platform admin (clock only)

TEST_USERS = {
    "analyst_headers": build_user_headers(USER_ANALYST_1, "TreasuryAnalyst"),
    "analyst_9_headers": build_user_headers(USER_ANALYST_9, "TreasuryAnalyst"),
    "officer_headers": build_user_headers(USER_OFFICER_1, "RiskOfficer"),
    "officer_2_headers": build_user_headers(USER_OFFICER_2, "RiskOfficer"),
    "officer_3_headers": build_user_headers(USER_OFFICER_3, "RiskOfficer"),
    "committee_headers": build_user_headers(USER_COMMITTEE_1, "LiquidityCommittee"),
    "committee_9_headers": build_user_headers(USER_COMMITTEE_9, "LiquidityCommittee"),
    "ops_headers": build_user_headers(USER_OPS_1, "TreasuryOps"),
    "admin_headers": build_user_headers(USER_ADMIN_1, "PlatformAdmin"),
}


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TreasuryAnalyst")


def make_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RiskOfficer")


def make_ops_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TreasuryOps")


def make_committee_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LiquidityCommittee")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
