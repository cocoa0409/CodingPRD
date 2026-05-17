"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Provider is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Provider,
  X-User-ID is the id of the acting Provider; ownership checks on
  resources that reference a provider (for instance, the provider_id on
  an Encounter, Prescription, or Referral, or the
  referring_provider_id / referred_to_provider_id on a Referral)
  compare the relevant foreign key to X-User-ID."

  Every Provider-driven call whose success depends on the caller owning
  the targeted resource MUST mint headers via
  make_provider_headers(provider["id"]) — never via the shared fallback
  constant below. Examples: signing the prescription whose
  provider_id == X-User-ID, accepting the referral whose
  referred_to_provider_id == X-User-ID, completing the encounter whose
  provider_id == X-User-ID.

- PatientPortalUser is ENTITY-BACKED. PRD §2.1: "When X-User-Role is
  PatientPortalUser, X-User-ID is the id of the acting Patient;
  ownership checks on any resource that references a patient compare
  the resource's patient_id (or, for the patient record itself, its id)
  to X-User-ID."

  Every PatientPortalUser-driven call whose success depends on the
  caller owning the targeted patient resource MUST mint headers via
  make_patient_portal_headers(patient["id"]) — never via the shared
  fallback constant below.

- Nurse, Receptionist, BillingClerk, Pharmacist, ClinicAdmin,
  TestHarness are OPAQUE. PRD §2.1: "X-User-ID is an opaque operator
  identifier not tied to any persisted entity." Shared headers in
  TEST_USERS are canonical for these roles.

  EXCEPTION — Pharmacist segregation-of-duties: PRD §2.12 / §3.4: "if
  the dispenser's X-User-ID matches the prescription's recorded
  provider_id, the request is rejected with ERR_SEGREGATION_OF_DUTIES."
  The shared pharmacist constant below is deliberately distinct from
  any Provider id; tests that PROVOKE the SoD violation MUST mint a
  pharmacist header with the signing Provider's id via
  make_pharmacist_headers(provider["id"]).

Falling back to a shared constant for entity-backed roles reproduces
the canonical bug: a literal "fallback" string never equals any real
entity id, so every ownership check rejects every request, cascading
"Setup failed" into dozens of tests downstream.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
RECEPTIONIST_ID = "receptionist-001"
NURSE_ID = "nurse-001"
BILLING_CLERK_ID = "billing-clerk-001"
PHARMACIST_ID = "pharmacist-001"
PHARMACIST_ID_ALT = "pharmacist-002"
CLINIC_ADMIN_ID = "clinic-admin-001"
TEST_HARNESS_ID = "test-harness-001"

# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
PROVIDER_FALLBACK_ID = "fallback-provider-1"
PATIENT_PORTAL_FALLBACK_ID = "fallback-patient-portal-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # ---------------- Opaque roles (shared constants canonical) ----------
    "receptionist_headers": build_user_headers(
        RECEPTIONIST_ID, "Receptionist",
    ),
    "nurse_headers": build_user_headers(NURSE_ID, "Nurse"),
    "billing_clerk_headers": build_user_headers(
        BILLING_CLERK_ID, "BillingClerk",
    ),
    # Pharmacist — opaque BUT the SoD check (PRD §2.12) compares
    # X-User-ID to prescription.provider_id. The shared constant
    # PHARMACIST_ID is distinct from any real Provider id by
    # construction, so it satisfies SoD by default. Tests that want to
    # PROVOKE the violation MUST mint pharmacist headers with the
    # signing Provider's id via make_pharmacist_headers.
    "pharmacist_headers": build_user_headers(PHARMACIST_ID, "Pharmacist"),
    "pharmacist_headers_alt": build_user_headers(
        PHARMACIST_ID_ALT, "Pharmacist",
    ),
    "clinic_admin_headers": build_user_headers(
        CLINIC_ADMIN_ID, "ClinicAdmin",
    ),
    # TestHarness — PRD §2.9 / §3.9: "Both are exempt from the
    # authentication header check"; we still emit a header pair so the
    # request path stays uniform across the helpers.
    "test_harness_headers": build_user_headers(
        TEST_HARNESS_ID, "TestHarness",
    ),
    # ---------------- Entity-backed FALLBACK constants ------------------
    # Safe ONLY for auth/role-mismatch tests and tests that DO NOT
    # exercise ownership. Ownership-gated calls MUST use the per-instance
    # builders below.
    "provider_fallback_headers": build_user_headers(
        PROVIDER_FALLBACK_ID, "Provider",
    ),
    "patient_portal_fallback_headers": build_user_headers(
        PATIENT_PORTAL_FALLBACK_ID, "PatientPortalUser",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed roles.
# ---------------------------------------------------------------------------
def make_provider_headers(provider_id: str) -> Dict[str, str]:
    """For Provider (entity_backed:Provider). Pass the actual Provider.id
    of the acting clinician.

    PRD §2.1: "When X-User-Role is Provider, X-User-ID is the id of the
    acting Provider; ownership checks on resources that reference a
    provider ... compare the relevant foreign key to X-User-ID."

    Every Provider call whose success depends on owning the targeted
    resource (signing a prescription whose provider_id matches,
    accepting a referral whose referred_to_provider_id matches,
    completing an encounter whose provider_id matches, issuing a
    referral whose referring_provider_id matches) MUST use this builder,
    not the shared PROVIDER_FALLBACK_ID constant.
    """
    return build_user_headers(provider_id, "Provider")


def make_patient_portal_headers(patient_id: str) -> Dict[str, str]:
    """For PatientPortalUser (entity_backed:Patient). Pass the actual
    Patient.id of the acting patient.

    PRD §2.1: "When X-User-Role is PatientPortalUser, X-User-ID is the
    id of the acting Patient; ownership checks on any resource that
    references a patient compare the resource's patient_id (or, for the
    patient record itself, its id) to X-User-ID."

    Every PatientPortalUser call whose success depends on owning the
    targeted patient resource (reading their own patient record, posting
    a portal message about themselves, reading their own encounter or
    prescription or referral) MUST use this builder, not the shared
    PATIENT_PORTAL_FALLBACK_ID constant.
    """
    return build_user_headers(patient_id, "PatientPortalUser")


def make_pharmacist_headers(user_id: str) -> Dict[str, str]:
    """For Pharmacist (opaque). PRD §2.12 / §3.4 segregation-of-duties:
    "if the dispenser's X-User-ID matches the prescription's recorded
    provider_id, the request is rejected with ERR_SEGREGATION_OF_DUTIES."

    Use this builder when a test needs a SPECIFIC pharmacist id — most
    notably, to PROVOKE the SoD violation by deliberately reusing the
    signing Provider's id as the dispenser's id.
    """
    return build_user_headers(user_id, "Pharmacist")


def make_receptionist_headers(user_id: str) -> Dict[str, str]:
    """For Receptionist (opaque). Any non-empty operator id works."""
    return build_user_headers(user_id, "Receptionist")


def make_nurse_headers(user_id: str) -> Dict[str, str]:
    """For Nurse (opaque). Any non-empty operator id works."""
    return build_user_headers(user_id, "Nurse")


def make_billing_clerk_headers(user_id: str) -> Dict[str, str]:
    """For BillingClerk (opaque). Any non-empty operator id works."""
    return build_user_headers(user_id, "BillingClerk")


def make_clinic_admin_headers(user_id: str) -> Dict[str, str]:
    """For ClinicAdmin (opaque). Any non-empty operator id works."""
    return build_user_headers(user_id, "ClinicAdmin")


def make_test_harness_headers(user_id: str = TEST_HARNESS_ID
                              ) -> Dict[str, str]:
    """For TestHarness (opaque). PRD §2.9: "Both are reserved to the
    TestHarness role and are exempt from the authentication header
    check"; this builder is provided for symmetry only."""
    return build_user_headers(user_id, "TestHarness")


__all__ = [
    "RECEPTIONIST_ID",
    "NURSE_ID",
    "BILLING_CLERK_ID",
    "PHARMACIST_ID",
    "PHARMACIST_ID_ALT",
    "CLINIC_ADMIN_ID",
    "TEST_HARNESS_ID",
    "PROVIDER_FALLBACK_ID",
    "PATIENT_PORTAL_FALLBACK_ID",
    "TEST_USERS",
    "make_provider_headers",
    "make_patient_portal_headers",
    "make_pharmacist_headers",
    "make_receptionist_headers",
    "make_nurse_headers",
    "make_billing_clerk_headers",
    "make_clinic_admin_headers",
    "make_test_harness_headers",
]
