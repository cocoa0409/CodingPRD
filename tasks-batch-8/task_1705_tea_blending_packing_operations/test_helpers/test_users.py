"""Pre-built role headers for every role in the PRD.

All nine roles are opaque (PRD §2.1: X-User-ID is an operator id, never an
entity id), so the shared constants below are the canonical form. Tests that
exercise segregation-of-duties rules build colliding-identity headers inline
with build_user_headers (e.g. build_user_headers("pl-1", "SensoryGrader")).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "procurement_lead_headers": build_user_headers("pl-1", "ProcurementLead"),
    "sensory_grader_headers": build_user_headers("gr-1", "SensoryGrader"),
    "qa_lab_analyst_headers": build_user_headers("an-1", "QALabAnalyst"),
    "qa_manager_headers": build_user_headers("qa-1", "QAManager"),
    "blend_master_headers": build_user_headers("bm-1", "BlendMaster"),
    "production_planner_headers": build_user_headers("pp-1", "ProductionPlanner"),
    "account_manager_headers": build_user_headers("am-1", "AccountManager"),
    "certification_officer_headers": build_user_headers(
        "co-1", "CertificationOfficer"),
    "platform_admin_headers": build_user_headers("adm-1", "PlatformAdmin"),
}
