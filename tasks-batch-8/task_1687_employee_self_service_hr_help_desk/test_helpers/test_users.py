"""Pre-built role headers for every role in the PRD (§2.1).

Identity binding is contractual:
- Employee / HelpDeskAgent / SpecialistAgent / SensitiveCaseManager are
  entity-backed: X-User-ID must be the id of an existing Employee/Agent row.
  Use the per-instance builders below for any call made in those roles.
- KnowledgeManager / HRDataSteward / WorkforcePlanner / HRServicesAdmin are
  opaque: X-User-ID is an operator identifier never compared to entity ids,
  so shared constants are canonical for them.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles (never ownership-gated against entity ids).
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "HRServicesAdmin"),
    "steward_headers": build_user_headers("steward-1", "HRDataSteward"),
    "steward2_headers": build_user_headers("steward-2", "HRDataSteward"),
    "planner_headers": build_user_headers("planner-1", "WorkforcePlanner"),
    "km1_headers": build_user_headers("km-1", "KnowledgeManager"),
    "km2_headers": build_user_headers("km-2", "KnowledgeManager"),
    # Fallbacks for entity-backed roles — ONLY safe where the call is not
    # ownership-gated (no matching Employee/Agent row exists, so most calls
    # with these fail authentication by design).
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
    "helpdesk_agent_headers": build_user_headers("test-agent-1", "HelpDeskAgent"),
}


# Per-instance builders — required for the entity-backed roles. Pass the
# actual Employee.id / Agent.id whenever the call is ownership-gated.

def make_employee_headers(user_id: str) -> dict:
    """Employee role: X-User-ID must be the acting employee's id (PRD §2.1)."""
    return build_user_headers(user_id, "Employee")


def make_helpdesk_agent_headers(user_id: str) -> dict:
    """HelpDeskAgent role: X-User-ID must be an existing Agent's id (PRD §2.1)."""
    return build_user_headers(user_id, "HelpDeskAgent")


def make_specialist_agent_headers(user_id: str) -> dict:
    """SpecialistAgent role: X-User-ID must be an existing Agent's id (PRD §2.1)."""
    return build_user_headers(user_id, "SpecialistAgent")


def make_sensitive_case_manager_headers(user_id: str) -> dict:
    """SensitiveCaseManager role: X-User-ID must be an existing Agent's id (PRD §2.1)."""
    return build_user_headers(user_id, "SensitiveCaseManager")


def make_knowledge_manager_headers(user_id: str) -> dict:
    """KnowledgeManager role (opaque): a distinct operator id per persona."""
    return build_user_headers(user_id, "KnowledgeManager")


def make_steward_headers(user_id: str) -> dict:
    """HRDataSteward role (opaque): a distinct operator id per persona."""
    return build_user_headers(user_id, "HRDataSteward")
