"""Pre-built role headers for every role in the PRD (§2.1).

- Dispatcher and ComplianceOfficer are opaque: X-User-ID is an operator
  identifier not tied to any entity, so a shared constant is the canonical form.
- Clinician is entity_backed: X-User-ID must be the acting Clinician entity's id
  for ownership checks. Use make_clinician_headers(clinician_id) with the real id
  whenever the call is ownership-gated (arrive, complete-visit, refer, estimates,
  payments, euthanasia-log, specimens).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque roles — shared constant is canonical
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "compliance_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    # entity_backed fallback — only for non-ownership tests (e.g. 404/400/403-role)
    "clinician_headers": build_user_headers("test-clinician-1", "Clinician"),
}


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_compliance_headers(user_id: str = "test-compliance-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_clinician_headers(clinician_id: str) -> dict:
    """For the Clinician role (entity_backed:Clinician). Pass the actual Clinician.id
    as clinician_id whenever the call is ownership-gated."""
    return build_user_headers(clinician_id, "Clinician")
