"""Pre-built role headers for every role in the PRD (PRD §2.1)."""
from prd_bench_local_runner.testing import build_user_headers


# All eight roles are documented as opaque operator identifiers (PRD §2.1):
# X-User-ID is NOT the primary key of any persisted entity. The server compares
# X-User-ID only to stamped fields (submitter_user_id, comp_approver_user_id,
# referrer_user_id, panelist_user_id, etc.), never to any entity's `id`.
# Therefore shared constants are the canonical form for all roles in this PRD.

TEST_USERS = {
    "platform_admin_headers":     build_user_headers("admin_alice",   "PlatformAdmin"),
    "recruiter_headers":          build_user_headers("rec_alice",     "Recruiter"),
    "recruiter_2_headers":        build_user_headers("rec_bob",       "Recruiter"),
    "hiring_manager_headers":     build_user_headers("hm_bob",        "HiringManager"),
    "hiring_manager_2_headers":   build_user_headers("hm_carol",      "HiringManager"),
    "comp_approver_headers":      build_user_headers("comp_carol",    "CompApprover"),
    "comp_approver_2_headers":    build_user_headers("comp_dave",     "CompApprover"),
    "vp_headers":                 build_user_headers("vp_dave",       "VP"),
    "vp_2_headers":               build_user_headers("vp_eve",        "VP"),
    "compliance_officer_headers": build_user_headers("co_frank",      "ComplianceOfficer"),
    "compliance_officer_2_headers": build_user_headers("co_grace",    "ComplianceOfficer"),
    "payroll_officer_headers":    build_user_headers("pay_eve",       "PayrollOfficer"),
    "candidate_headers":          build_user_headers("cand_user_x",   "Candidate"),
}


def make_headers(user_id: str, role: str) -> dict:
    """Build a header set with a specific X-User-ID — used for SoD and independence checks
    where the calling identity must match (or differ from) a stamped field."""
    return build_user_headers(user_id, role)


def make_unauthenticated_headers() -> dict:
    """Empty headers — used for the priority-1 authentication test (PRD §2.1)."""
    return {}
