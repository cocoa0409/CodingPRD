"""Pre-built role headers for every role in the PRD (§2.1).

Five roles: Doctor (entity_backed:Doctor), LabTech, Scheduler, Billing,
LabAdmin (all four opaque). For ownership-gated Doctor operations (cancel,
tryin-verdict), X-User-ID must equal the target case's doctor_id, so those
calls must use make_doctor_headers(<doctor.id>) — never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - opaque roles (LabTech, Scheduler, Billing, LabAdmin): the canonical form;
#     X-User-ID is never compared to any entity id.
#   - doctor: a fallback ONLY for non-ownership tests (e.g. a forbidden-role
#     probe where the verdict never reaches the ownership check). Ownership-
#     gated Doctor calls MUST use make_doctor_headers(doctor_id) instead.
TEST_USERS = {
    "doctor_headers": build_user_headers("test-doctor-1", "Doctor"),
    "labtech_headers": build_user_headers("test-labtech-1", "LabTech"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "billing_headers": build_user_headers("test-billing-1", "Billing"),
    "labadmin_headers": build_user_headers("test-labadmin-1", "LabAdmin"),
}


def make_doctor_headers(user_id: str) -> dict:
    """For the Doctor role (entity_backed:Doctor). Pass the actual Doctor.id as
    user_id whenever the call is ownership-gated (cancel, tryin-verdict,
    remake-requests)."""
    return build_user_headers(user_id, "Doctor")
