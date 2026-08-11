"""Pre-built role headers for every role in the PRD (Section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests whose success does not
# depend on the caller owning the subject resource. FieldContractor is
# entity-backed by Contractor; use make_field_contractor_headers(contractor_id)
# for any ownership-gated call.
TEST_USERS = {
    "program_manager_headers": build_user_headers("test-pm-1", "ProgramManager"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "field_contractor_headers": build_user_headers("test-contractor-1", "FieldContractor"),
    "quality_auditor_headers": build_user_headers("test-auditor-1", "QualityAuditor"),
    "ami_operator_headers": build_user_headers("test-ami-1", "AmiOperator"),
    "customer_service_headers": build_user_headers("test-cs-1", "CustomerService"),
}


def make_field_contractor_headers(user_id: str) -> dict:
    """FieldContractor is entity-backed by Contractor: pass the actual
    Contractor.id whenever the call is ownership-gated (complete/no-access on
    an appointment, swap/reconcile/submit-rework on a work order, invoice
    create/submit)."""
    return build_user_headers(user_id, "FieldContractor")
