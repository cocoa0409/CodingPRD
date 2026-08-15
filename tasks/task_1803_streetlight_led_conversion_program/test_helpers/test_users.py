"""Pre-built role headers for every role in the PRD.

FieldSupervisor is entity_backed by Crew (PRD section 2.1): ownership-gated
calls (dispatch/complete/fail work orders, resolve tickets) MUST use
make_field_supervisor_headers(crew_id) with the actual Crew.id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not
# exercise entity ownership.
TEST_USERS = {
    "program_manager_headers": build_user_headers("pm-user-1", "ProgramManager"),
    "program_manager_2_headers": build_user_headers("pm-user-2", "ProgramManager"),
    "qa_inspector_headers": build_user_headers("qa-1", "QaInspector"),
    "qa_inspector_2_headers": build_user_headers("qa-77", "QaInspector"),
    "billing_analyst_headers": build_user_headers("ba-1", "BillingAnalyst"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "citizen_reporter_headers": build_user_headers("citizen-1", "CitizenReporter"),
    "citizen_reporter_2_headers": build_user_headers("citizen-2", "CitizenReporter"),
    "citizen_reporter_3_headers": build_user_headers("citizen-3", "CitizenReporter"),
    "citizen_reporter_4_headers": build_user_headers("citizen-4", "CitizenReporter"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
    "auditor_2_headers": build_user_headers("auditor-9", "Auditor"),
    # Fallback for non-ownership FieldSupervisor calls only (e.g. audit submit
    # where no crew-specific gate exists). Never use for dispatch/complete/fail/resolve.
    "field_supervisor_headers": build_user_headers("fs-user-1", "FieldSupervisor"),
}


def make_field_supervisor_headers(crew_id: str) -> dict:
    """FieldSupervisor is entity_backed:Crew — pass the actual Crew.id as
    user_id whenever the call is ownership-gated (dispatch, complete, fail
    a work order; resolve an assigned ticket)."""
    return build_user_headers(crew_id, "FieldSupervisor")


def make_program_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramManager")


def make_qa_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QaInspector")


def make_billing_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingAnalyst")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_citizen_reporter_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CitizenReporter")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")
