"""Pre-built role headers for every role in the Blood Donation Center PRD.

Four roles (CenterAdmin, IntakeNurse, LabTechnician, InventoryManager) are opaque
operator identifiers — per PRD §2.1 the X-User-ID is not tied to any persisted
entity, so the shared-constant form is canonical for them.

The Donor role is entity-backed: when X-User-Role is Donor, X-User-ID must be the
acting Donor entity's id, and ownership checks compare a resource's donor foreign
key to X-User-ID. Any Donor-role call that is ownership-gated (booking, cancelling
the donor's own appointment) MUST use make_donor_headers(donor_id) with the real id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles use these everywhere; the donor_headers constant
# is only a fallback for Donor-role tests whose success does not depend on the
# X-User-ID matching a real Donor id (e.g., a 403 RBAC rejection).
TEST_USERS = {
    "center_admin_headers": build_user_headers("test-center-admin-1", "CenterAdmin"),
    "intake_nurse_headers": build_user_headers("test-intake-nurse-1", "IntakeNurse"),
    "lab_technician_headers": build_user_headers("test-lab-technician-1", "LabTechnician"),
    "inventory_manager_headers": build_user_headers("test-inventory-manager-1", "InventoryManager"),
    "donor_headers": build_user_headers("test-donor-1", "Donor"),
}


def make_donor_headers(donor_id: str) -> dict:
    """For the Donor role (entity_backed:Donor). Pass the actual Donor.id as user_id
    whenever the call is ownership-gated (booking or cancelling the donor's own
    appointment)."""
    return build_user_headers(donor_id, "Donor")
