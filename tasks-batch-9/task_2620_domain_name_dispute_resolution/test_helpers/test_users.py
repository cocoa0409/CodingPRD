"""Pre-built role headers for every role the PRD recognises.

Three roles resolve their identity against a persisted row: a Complainant's
X-User-ID is the id of the acting Complainant row, a Panelist's is the id of
the acting Panelist row, and a RegistrarAgent's is the id of the acting
Registrar row. Those three therefore always need a per-instance builder.
ProviderAdmin, CaseManager and Respondent carry opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Pinned opaque operator identifiers.
CASE_MANAGER_ONE = "cm-001"
CASE_MANAGER_TWO = "cm-002"
PROVIDER_ADMIN_ID = "pa-001"
RESPONDENT_ID = "resp-001"

# Shared constants. Safe for the opaque roles, and for tests that do not
# exercise an ownership or seat-holder check.
TEST_USERS = {
    "provider_admin_headers": build_user_headers(PROVIDER_ADMIN_ID, "ProviderAdmin"),
    "case_manager_headers": build_user_headers(CASE_MANAGER_ONE, "CaseManager"),
    "case_manager_two_headers": build_user_headers(CASE_MANAGER_TWO, "CaseManager"),
    "respondent_headers": build_user_headers(RESPONDENT_ID, "Respondent"),
    # Fallbacks for the identity-backed roles: use only where no ownership,
    # seat-holder or registrar-of-record check is being exercised.
    "complainant_headers": build_user_headers("test-complainant-1", "Complainant"),
    "panelist_headers": build_user_headers("test-panelist-1", "Panelist"),
    "registrar_agent_headers": build_user_headers("test-registrar-1", "RegistrarAgent"),
}

PROVIDER_ADMIN = TEST_USERS["provider_admin_headers"]
CASE_MANAGER = TEST_USERS["case_manager_headers"]
CASE_MANAGER_ALT = TEST_USERS["case_manager_two_headers"]
RESPONDENT = TEST_USERS["respondent_headers"]


def make_complainant_headers(complainant_id: str) -> dict:
    """For the Complainant role. Pass the acting Complainant row's id."""
    return build_user_headers(complainant_id, "Complainant")


def make_panelist_headers(panelist_id: str) -> dict:
    """For the Panelist role. Pass the acting Panelist row's id."""
    return build_user_headers(panelist_id, "Panelist")


def make_registrar_headers(registrar_id: str) -> dict:
    """For the RegistrarAgent role. Pass the acting Registrar row's id."""
    return build_user_headers(registrar_id, "RegistrarAgent")


def make_case_manager_headers(user_id: str) -> dict:
    """For the CaseManager role with a specific pinned operator identifier."""
    return build_user_headers(user_id, "CaseManager")


def make_respondent_headers(user_id: str = RESPONDENT_ID) -> dict:
    """For the Respondent role, whose X-User-ID is opaque."""
    return build_user_headers(user_id, "Respondent")


def make_provider_admin_headers(user_id: str = PROVIDER_ADMIN_ID) -> dict:
    """For the ProviderAdmin role, whose X-User-ID is opaque."""
    return build_user_headers(user_id, "ProviderAdmin")
