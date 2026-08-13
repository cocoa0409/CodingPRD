"""Pre-built role headers for every role in the PRD.

All seven roles are opaque (X-User-ID is an operator identifier, never compared
to an entity id), so shared constants are the canonical form. Named per-instance
builders are still provided for readability at call sites that exercise
segregation-of-duties (the comparison is X-User-ID vs a recorded operator id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "oncologist_headers": build_user_headers("onc_a", "RadiationOncologist"),
    "oncologist_b_headers": build_user_headers("onc_b", "RadiationOncologist"),
    "dosimetrist_headers": build_user_headers("dos_a", "MedicalDosimetrist"),
    "dosimetrist_b_headers": build_user_headers("dos_b", "MedicalDosimetrist"),
    "physicist_headers": build_user_headers("phys_a", "MedicalPhysicist"),
    "physicist_b_headers": build_user_headers("phys_b", "MedicalPhysicist"),
    "therapist_headers": build_user_headers("rtt_a", "RadiationTherapist"),
    "scheduler_headers": build_user_headers("sched_a", "Scheduler"),
    "billing_headers": build_user_headers("bill_a", "BillingCoordinator"),
    "admin_headers": build_user_headers("admin_a", "SystemAdmin"),
}


def make_oncologist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RadiationOncologist")


def make_dosimetrist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MedicalDosimetrist")


def make_physicist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MedicalPhysicist")


def make_therapist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RadiationTherapist")


def make_scheduler_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Scheduler")


def make_billing_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingCoordinator")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")
