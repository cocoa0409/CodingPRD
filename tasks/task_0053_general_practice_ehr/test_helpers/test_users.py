"""Pre-built role headers for every role in the PRD.

Two of the five roles are entity-backed: Provider's X-User-ID is the acting
Provider.id, and Patient's X-User-ID is the acting Patient.id. Ownership-gated
calls MUST use the per-instance builders below with the real entity id. The
shared TEST_USERS constants are safe only for the three opaque roles
(FrontDesk, Biller, QualityAnalyst) and for tests that never exercise an
entity-backed ownership check (e.g. 401/403/404/422 negative paths).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "frontdesk_headers": build_user_headers("test-frontdesk-1", "FrontDesk"),
    "biller_headers": build_user_headers("test-biller-1", "Biller"),
    "quality_headers": build_user_headers("test-quality-1", "QualityAnalyst"),
    # Entity-backed roles — shared constant is a fallback for NON-ownership tests only.
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
}


def make_provider_headers(provider_id: str) -> dict:
    """For the Provider role (entity_backed:Provider). Pass the actual
    Provider.id whenever the call is ownership-gated (start/code/reopen a visit,
    sign a prescription, cancel a referral)."""
    return build_user_headers(provider_id, "Provider")


def make_patient_headers(patient_id: str) -> dict:
    """For the Patient role (entity_backed:Patient). Pass the actual Patient.id
    whenever the call is ownership-gated (activate own portal account, read own
    records)."""
    return build_user_headers(patient_id, "Patient")
