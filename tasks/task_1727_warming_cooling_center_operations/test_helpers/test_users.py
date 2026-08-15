"""Pre-built role headers for every role in the PRD (§2.1).

Identity semantics (PRD §2.1): for SiteLead / IntakeStaff / OutreachWorker /
MedicalResponder the X-User-ID is the id of the acting StaffMember; for
EOCManager / TransportCoordinator it is an opaque operator identifier.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for entity-backed roles in
# tests that do not exercise ownership or segregation comparisons.
TEST_USERS = {
    # opaque roles: shared constants are the canonical form.
    "eoc_manager_headers": build_user_headers("test-eoc-manager-1", "EOCManager"),
    "transport_coordinator_headers": build_user_headers(
        "test-transport-coordinator-1", "TransportCoordinator"),
    # entity-backed roles: fallback for non-ownership tests only.
    "site_lead_headers": build_user_headers("test-site-lead-1", "SiteLead"),
    "intake_staff_headers": build_user_headers("test-intake-staff-1", "IntakeStaff"),
    "outreach_worker_headers": build_user_headers(
        "test-outreach-worker-1", "OutreachWorker"),
    "medical_responder_headers": build_user_headers(
        "test-medical-responder-1", "MedicalResponder"),
}


# Per-instance builders — required for entity-backed roles whenever a call is
# ownership- or segregation-gated (pass the actual StaffMember.id).
def make_site_lead_headers(user_id: str) -> dict:
    """SiteLead is entity-backed by StaffMember: pass the real StaffMember.id
    whenever the call is compared against a staff foreign key."""
    return build_user_headers(user_id, "SiteLead")


def make_intake_staff_headers(user_id: str) -> dict:
    """IntakeStaff is entity-backed by StaffMember: pass the real
    StaffMember.id whenever the caller identity is recorded or compared."""
    return build_user_headers(user_id, "IntakeStaff")


def make_outreach_worker_headers(user_id: str) -> dict:
    """OutreachWorker is entity-backed by StaffMember: pass the real
    StaffMember.id whenever the caller identity is recorded or compared."""
    return build_user_headers(user_id, "OutreachWorker")


def make_medical_responder_headers(user_id: str) -> dict:
    """MedicalResponder is entity-backed by StaffMember: pass the real
    StaffMember.id whenever the caller identity is recorded or compared."""
    return build_user_headers(user_id, "MedicalResponder")


def make_eoc_manager_headers(user_id: str) -> dict:
    """EOCManager is opaque; a per-instance id still matters wherever the PRD
    compares it later (e.g. after-action approval vs. episode activator)."""
    return build_user_headers(user_id, "EOCManager")


def make_transport_coordinator_headers(user_id: str) -> dict:
    """TransportCoordinator is opaque."""
    return build_user_headers(user_id, "TransportCoordinator")
