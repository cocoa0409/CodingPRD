"""Pre-built role headers for every role in the PRD.

Identity semantics (PRD "User and Role-Based Access Control"):
- QaTechnician and Auditor are entity-backed: X-User-ID must be the id of the
  acting QaTechnician entity. Use the per-instance builders for any call whose
  ownership/identity is checked (swab recording, audit finding creation).
- QaManager, QaSupervisor, LineOperator carry opaque X-User-ID values; the
  shared constants are canonical for them.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "qa_manager_headers": build_user_headers("test-qa-manager-1", "QaManager"),
    "qa_supervisor_headers": build_user_headers("test-qa-supervisor-1", "QaSupervisor"),
    "line_operator_headers": build_user_headers("test-line-operator-1", "LineOperator"),
    # Entity-backed roles — fallback for calls that do not exercise identity checks.
    "qa_technician_headers": build_user_headers("test-qa-technician-1", "QaTechnician"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
}


def make_qa_technician_headers(user_id: str) -> dict:
    """For QaTechnician (entity-backed by QaTechnician). Pass the actual
    QaTechnician.id whenever the call references a technician identity
    (e.g., recording a swab whose recorded_by_id is the caller)."""
    return build_user_headers(user_id, "QaTechnician")


def make_auditor_headers(user_id: str) -> dict:
    """For Auditor (entity-backed by QaTechnician as auditor of record). Pass
    the actual QaTechnician.id that the audit finding's auditor_id names."""
    return build_user_headers(user_id, "Auditor")
