"""Pre-built role headers for the seven PRD roles (§2.1).

All seven roles use opaque operator identifiers: the server never compares
X-User-ID to any entity id, so shared constants are the canonical form.
Distinct user ids per role keep the segregation-of-duties check (drafter may
not accept/reject the same response) satisfied in composite flows.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "claims_analyst_headers": build_user_headers("analyst-1", "ClaimsAnalyst"),
    "claims_analyst_b_headers": build_user_headers("analyst-2", "ClaimsAnalyst"),
    "tpa_agent_headers": build_user_headers("tpa-agent-1", "TpaAgent"),
    "agency_liaison_headers": build_user_headers("liaison-1", "AgencyLiaison"),
    "charge_auditor_headers": build_user_headers("auditor-1", "ChargeAuditor"),
    "rating_analyst_headers": build_user_headers("rater-1", "RatingAnalyst"),
    "tpa_manager_headers": build_user_headers("tpa-mgr-1", "TpaManager"),
}
