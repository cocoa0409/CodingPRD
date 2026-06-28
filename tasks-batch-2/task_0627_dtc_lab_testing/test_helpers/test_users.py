"""Pre-built role headers for every role in the PRD.

Per PRD Section 2.1, only the Patient role is entity-backed: X-User-ID is the
acting Patient's id, and ownership checks compare a resource's patient_id to it.
CatalogAdmin, OrderingPhysician, PhlebotomyTech, and LabTech all carry opaque
operator identifiers that the server never compares to any entity id (it only
records them, e.g. reviewing_physician_id / collected_by_user_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - Opaque roles: shared constant is the canonical form.
#  - Patient (entity-backed): shared constant is a fallback for tests that do
#    NOT exercise ownership; ownership-gated calls MUST use make_patient_headers.
TEST_USERS = {
    "catalog_admin_headers": build_user_headers("test-admin-1", "CatalogAdmin"),
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
    "ordering_physician_headers": build_user_headers("test-physician-1", "OrderingPhysician"),
    "phlebotomy_tech_headers": build_user_headers("test-phleb-1", "PhlebotomyTech"),
    "lab_tech_headers": build_user_headers("test-labtech-1", "LabTech"),
    # A second LabTech identity, useful for segregation-of-duties scenarios where
    # the releaser must differ from the collector.
    "lab_tech_2_headers": build_user_headers("test-labtech-2", "LabTech"),
}


def make_patient_headers(patient_id: str) -> dict:
    """For the Patient role (entity_backed:Patient). Pass the actual Patient.id
    as X-User-ID whenever the call is ownership-gated (carts, cart-lines, orders,
    capture/cancel, resubmit, appointments, home-kits, schedule)."""
    return build_user_headers(patient_id, "Patient")


def make_catalog_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "CatalogAdmin")


def make_ordering_physician_headers(user_id: str = "test-physician-1") -> dict:
    return build_user_headers(user_id, "OrderingPhysician")


def make_phlebotomy_tech_headers(user_id: str = "test-phleb-1") -> dict:
    return build_user_headers(user_id, "PhlebotomyTech")


def make_lab_tech_headers(user_id: str = "test-labtech-1") -> dict:
    return build_user_headers(user_id, "LabTech")
