"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (Investigator, AnimalCareStaff, AttendingVeterinarian) get
per-instance builders: whenever a call is ownership-gated (protocol create /
submit / personnel attach, or any segregation-of-duties comparison against a
personnel foreign key) the builder MUST be called with the real entity id.
The shared constants for those roles are fallbacks for calls that never pass
an ownership gate. Opaque roles use the shared constants as the canonical
form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical form.
    "admin_headers": build_user_headers("test-admin-1", "IacucAdministrator"),
    "facility_headers": build_user_headers("test-facility-1", "FacilityManager"),
    "billing_headers": build_user_headers("test-billing-1", "BillingCoordinator"),
    "training_headers": build_user_headers("test-training-1", "TrainingCoordinator"),
    "occ_health_headers": build_user_headers("test-occnurse-1", "OccHealthNurse"),
    # Entity-backed roles — fallback ONLY for tests that never pass an
    # ownership/identity gate (e.g. unauthenticated-shape probes, 404 probes).
    "investigator_headers": build_user_headers("test-investigator-1", "Investigator"),
    "staff_headers": build_user_headers("test-staff-1", "AnimalCareStaff"),
    "vet_headers": build_user_headers("test-vet-1", "AttendingVeterinarian"),
}


def make_investigator_headers(investigator_id: str) -> dict:
    """Investigator headers whose X-User-ID is a real Investigator.id.

    Mandatory for ownership-gated calls: protocol create, submit, and
    personnel attach all compare X-User-ID to the protocol's investigator_id.
    """
    return build_user_headers(investigator_id, "Investigator")


def make_staff_headers(personnel_id: str) -> dict:
    """AnimalCareStaff headers whose X-User-ID is a real Personnel.id."""
    return build_user_headers(personnel_id, "AnimalCareStaff")


def make_vet_headers(personnel_id: str) -> dict:
    """AttendingVeterinarian headers whose X-User-ID is a real Personnel.id."""
    return build_user_headers(personnel_id, "AttendingVeterinarian")


def make_admin_headers(user_id: str) -> dict:
    """IacucAdministrator headers with a chosen operator id (opaque role).

    Used to exercise the segregation-of-duties rule on review-decisions,
    where the acting X-User-ID is compared to the protocol's investigator_id.
    """
    return build_user_headers(user_id, "IacucAdministrator")
