"""Pre-built role headers for every role in the PRD (§2.1).

Three roles are opaque operator identities (ClinicManager, FrontDeskClerk,
TriageNurse) — X-User-ID is never compared to an entity id. Two roles are
entity-backed (Provider -> Provider.id, Patient -> Patient.id) — ownership
checks compare X-User-ID against the resource's foreign key. Anonymous is the
unauthenticated bootstrap caller for clinic creation and the clock/seed helpers.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that do not exercise
# resource ownership (e.g. 400/404/403/401 paths, or opaque-role calls).
TEST_USERS = {
    "clinic_manager_headers": build_user_headers("test-clinic-manager-1", "ClinicManager"),
    "front_desk_headers": build_user_headers("test-front-desk-1", "FrontDeskClerk"),
    "triage_nurse_headers": build_user_headers("test-triage-nurse-1", "TriageNurse"),
    # entity_backed fallbacks — only valid where ownership is NOT asserted.
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
    # Anonymous bootstrap caller (clinic creation, clock/seed).
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
}


# Per-instance builders — required for every entity_backed role. Pass the actual
# entity id so ownership-gated calls authenticate as the owning entity.
def make_provider_headers(provider_id: str) -> dict:
    """For Provider (entity_backed:Provider). Pass the acting Provider.id."""
    return build_user_headers(provider_id, "Provider")


def make_patient_headers(patient_id: str) -> dict:
    """For Patient (entity_backed:Patient). Pass the acting Patient.id."""
    return build_user_headers(patient_id, "Patient")
