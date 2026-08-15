"""Pre-built role headers for every role in the PRD (§2.1).

All seven roles carry an opaque identity — X-User-ID is an opaque operator
identifier, never compared to a persisted entity id. Segregation-of-duties
checks compare one operator's X-User-ID against another's, so tests that
exercise those checks build headers with explicit user ids via
``make_role_headers``.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles in non-segregation contexts.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "intake_specialist_headers": build_user_headers("test-intake-1", "IntakeSpecialist"),
    "case_analyst_headers": build_user_headers("test-analyst-1", "CaseAnalyst"),
    "medical_director_headers": build_user_headers("test-md-1", "MedicalDirector"),
    "member_services_rep_headers": build_user_headers("test-msr-1", "MemberServicesRep"),
    "compliance_officer_headers": build_user_headers("test-co-1", "ComplianceOfficer"),
    "claims_processor_headers": build_user_headers("test-cp-1", "ClaimsProcessor"),
}


# Per-instance builders — required whenever a test needs a specific X-User-ID
# (e.g. segregation-of-duties scenarios, assignee-gated draft/finalize calls).
def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_intake_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeSpecialist")


def make_case_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CaseAnalyst")


def make_medical_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MedicalDirector")


def make_member_services_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MemberServicesRep")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_claims_processor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsProcessor")
