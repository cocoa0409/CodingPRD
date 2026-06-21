"""Pre-built role headers for every role in the PRD (§2.1).

FrontDesk and BillingSpecialist are operator identities (opaque X-User-ID) — the
shared constant is the canonical form. Clinician is entity_backed:Provider and
Patient is entity_backed:Patient — ownership checks compare X-User-ID to the
resource's provider/patient foreign key, so use the per-instance builders with
the real entity id whenever a call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — canonical shared constants.
    "front_desk_headers": build_user_headers("front-desk-1", "FrontDesk"),
    "billing_headers": build_user_headers("billing-1", "BillingSpecialist"),
    # entity_backed roles — shared constants are fallbacks for non-ownership tests
    # (e.g. 404-on-missing, 422-on-bad-payload). For ownership-gated calls, use the
    # per-instance builders below with the real Provider.id / Patient.id.
    "clinician_headers": build_user_headers("clinician-fallback-1", "Clinician"),
    "patient_headers": build_user_headers("patient-fallback-1", "Patient"),
}


def make_front_desk_headers(user_id: str = "front-desk-1") -> dict:
    """FrontDesk is opaque; user_id is an operator identifier, not an entity id."""
    return build_user_headers(user_id, "FrontDesk")


def make_billing_headers(user_id: str = "billing-1") -> dict:
    """BillingSpecialist is opaque; user_id is an operator identifier."""
    return build_user_headers(user_id, "BillingSpecialist")


def make_clinician_headers(provider_id: str) -> dict:
    """For Clinician (entity_backed:Provider). Pass the acting Provider.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(provider_id, "Clinician")


def make_patient_headers(patient_id: str) -> dict:
    """For Patient (entity_backed:Patient). Pass the acting Patient.id as user_id
    whenever the self-service read is ownership-gated."""
    return build_user_headers(patient_id, "Patient")


def make_unknown_role_headers(user_id: str = "nobody-1") -> dict:
    """An unrecognized role — drives ERR_UNAUTHENTICATED (PRD §2.1)."""
    return build_user_headers(user_id, "NotARole")
