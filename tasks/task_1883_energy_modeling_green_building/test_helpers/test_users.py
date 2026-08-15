"""Pre-built role headers for every role in the PRD (§2.1).

ProgramAdmin and CertificationReviewer carry opaque operator identifiers never
compared to any entity id, and reads are open to the Any label.
ProjectAdministrator, EnergyModeler, DocumentationSpecialist, and
CommissioningAgent are entity-backed by TeamMember: when the call is
ownership-gated, X-User-ID must be the acting TeamMember's id — use the
make_*_headers builders with the real member id for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, the Any reader, and for tests that
# do not exercise ownership (400-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "CertificationReviewer"),
    "any_headers": build_user_headers("test-reader-1", "Any"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "project_admin_headers": build_user_headers("test-pa-fallback", "ProjectAdministrator"),
    "modeler_headers": build_user_headers("test-em-fallback", "EnergyModeler"),
    "doc_specialist_headers": build_user_headers("test-ds-fallback", "DocumentationSpecialist"),
    "cx_agent_headers": build_user_headers("test-cx-fallback", "CommissioningAgent"),
}


def make_program_admin_headers(user_id: str = "test-program-admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_reviewer_headers(user_id: str = "test-reviewer-1") -> dict:
    return build_user_headers(user_id, "CertificationReviewer")


def make_any_headers(user_id: str = "test-reader-1") -> dict:
    return build_user_headers(user_id, "Any")


def make_project_administrator_headers(user_id: str) -> dict:
    """For ProjectAdministrator (entity-backed by TeamMember). Pass the actual
    TeamMember.id whenever the call records or checks the administrator."""
    return build_user_headers(user_id, "ProjectAdministrator")


def make_energy_modeler_headers(user_id: str) -> dict:
    """For EnergyModeler (entity-backed by TeamMember). Pass the actual
    TeamMember.id — the model's created_by is stamped from X-User-ID."""
    return build_user_headers(user_id, "EnergyModeler")


def make_documentation_specialist_headers(user_id: str) -> dict:
    """For DocumentationSpecialist (entity-backed by TeamMember). Pass the
    attempt's documentation_owner_id for owner-only actions."""
    return build_user_headers(user_id, "DocumentationSpecialist")


def make_commissioning_agent_headers(user_id: str) -> dict:
    """For CommissioningAgent (entity-backed by TeamMember). Pass the task's
    agent_id for start/complete."""
    return build_user_headers(user_id, "CommissioningAgent")
