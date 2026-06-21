"""Pre-built role headers for every role in the PRD (§2.1).

All four roles use an opaque X-User-ID that is never compared to a stored
entity id (PRD §2.1): "X-User-ID is an opaque operator identifier that is not
tied to any persisted entity." Authorization is purely role-based, so a shared
constant per role is the canonical form — there are no entity_backed roles.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "system_admin_headers": build_user_headers("test-system-admin-1", "SystemAdmin"),
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "financial_aid_officer_headers": build_user_headers("test-faid-1", "FinancialAidOfficer"),
    "academic_advisor_headers": build_user_headers("test-advisor-1", "AcademicAdvisor"),
}
