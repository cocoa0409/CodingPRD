"""Pre-built role headers for every role in the PRD.

Identity resolution differs by role. For NaturopathicDoctor, HealthCoach,
DispensaryTech and ClinicalDirector the X-User-ID is the acting Practitioner's
id; for Patient it is the acting Patient's id. PracticeAdmin and
BillingSpecialist carry an opaque operator identifier that is never compared to
any entity id.

Any ownership-, segregation- or authorship-sensitive call MUST use the
per-instance builder with the real entity id, never the shared constant.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the two opaque roles, and for calls by the
# entity-backed roles that do not depend on the caller owning the subject.
TEST_USERS = {
    "practice_admin_headers": build_user_headers("admin-op-1", "PracticeAdmin"),
    "billing_specialist_headers": build_user_headers(
        "billing-op-1", "BillingSpecialist"
    ),
    "naturopathic_doctor_headers": build_user_headers("test-nd-1", "NaturopathicDoctor"),
    "health_coach_headers": build_user_headers("test-coach-1", "HealthCoach"),
    "dispensary_tech_headers": build_user_headers("test-tech-1", "DispensaryTech"),
    "clinical_director_headers": build_user_headers("test-director-1", "ClinicalDirector"),
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
}

# Headers carrying no identity at all — used to exercise the authentication rung.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_practice_admin_headers(user_id: str = "admin-op-1") -> dict:
    """PracticeAdmin identities are opaque operator strings."""
    return build_user_headers(user_id, "PracticeAdmin")


def make_billing_specialist_headers(user_id: str = "billing-op-1") -> dict:
    """BillingSpecialist identities are opaque operator strings."""
    return build_user_headers(user_id, "BillingSpecialist")


def make_nd_headers(practitioner_id: str) -> dict:
    """Pass the acting Practitioner's id for a NaturopathicDoctor."""
    return build_user_headers(practitioner_id, "NaturopathicDoctor")


def make_coach_headers(practitioner_id: str) -> dict:
    """Pass the acting Practitioner's id for a HealthCoach."""
    return build_user_headers(practitioner_id, "HealthCoach")


def make_tech_headers(practitioner_id: str) -> dict:
    """Pass the acting Practitioner's id for a DispensaryTech."""
    return build_user_headers(practitioner_id, "DispensaryTech")


def make_director_headers(practitioner_id: str) -> dict:
    """Pass the acting Practitioner's id for a ClinicalDirector."""
    return build_user_headers(practitioner_id, "ClinicalDirector")


def make_patient_headers(patient_id: str) -> dict:
    """Pass the acting Patient's id."""
    return build_user_headers(patient_id, "Patient")
