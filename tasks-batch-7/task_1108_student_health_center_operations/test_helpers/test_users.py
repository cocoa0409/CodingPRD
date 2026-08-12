"""Pre-built role headers for every role in the PRD (§2.1, §4).

Shared constants are safe for opaque roles and for tests that do not exercise
ownership. The Student role is entity-backed: when a Student call is
ownership-gated (booking or cancelling an appointment), fixtures MUST build
headers with the actual Student.id via make_student_headers().
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "student_headers": build_user_headers("test-student-1", "Student"),
    "front_desk_headers": build_user_headers("test-frontdesk-1", "FrontDeskStaff"),
    "nurse_headers": build_user_headers("test-nurse-1", "Nurse"),
    "clinician_headers": build_user_headers("test-clinician-1", "Clinician"),
    "pharmacist_headers": build_user_headers("test-pharmacist-1", "Pharmacist"),
    "billing_officer_headers": build_user_headers("test-billing-1", "BillingOfficer"),
    "health_admin_headers": build_user_headers("test-admin-1", "HealthAdmin"),
}

# Headers carrying no authentication context at all (PRD §2.1 rejection path).
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}


def make_student_headers(user_id: str) -> dict:
    """For the entity-backed Student role: pass the actual Student.id whenever
    the call is ownership-gated (book/cancel own appointments)."""
    return build_user_headers(user_id, "Student")


def make_front_desk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FrontDeskStaff")


def make_nurse_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Nurse")


def make_clinician_headers(user_id: str) -> dict:
    """Clinician X-User-ID is recorded on disease-case confirmations and
    referrals, so segregation-of-duties tests must pin it explicitly."""
    return build_user_headers(user_id, "Clinician")


def make_pharmacist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Pharmacist")


def make_billing_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingOfficer")


def make_health_admin_headers(user_id: str) -> dict:
    """HealthAdmin X-User-ID is recorded on disease-case reports, so
    segregation-of-duties tests must pin it explicitly."""
    return build_user_headers(user_id, "HealthAdmin")
