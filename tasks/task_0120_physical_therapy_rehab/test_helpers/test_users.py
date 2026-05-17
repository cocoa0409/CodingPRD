"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Therapist is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Therapist,
  X-User-ID is the id of the acting Therapist row; ownership and
  capability checks on any clinical operation that references a
  Therapist (evaluations, plan certifications, visit sign-off, HEP
  issuance, discharge creation) compare the resource's clinician_id,
  prescribing_clinician_id, or discharging_clinician_id foreign-key
  field to X-User-ID."

  Every Therapist-driven call whose success depends on the acting
  therapist's id matching the resource's clinician_id MUST mint headers
  via make_therapist_headers(therapist["id"]) — never via the shared
  fallback constant below. Examples: signing a visit whose clinician_id
  == X-User-ID, finalizing/amending an evaluation whose clinician_id ==
  X-User-ID, signing a discharge whose discharging_clinician_id ==
  X-User-ID. The licensing check ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE
  (PRD §3.2) and segregation-of-duties check ERR_SEGREGATION_OF_DUTIES
  (PRD §3.9) likewise both compare X-User-ID to a real Therapist.id.

- Patient is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Patient,
  X-User-ID is the id of the acting Patient row; the patient can read
  only their own Patient record and acknowledge HEPs whose anchoring
  episode belongs to that patient."

  Every Patient-driven call (HEP acknowledge, reading the patient's own
  Patient row) whose success depends on the acting patient's id
  matching the targeted resource MUST mint headers via
  make_patient_headers(patient["id"]).

- ClinicAdmin and Biller are OPAQUE. PRD §2.1: "X-User-ID is an opaque
  operator identifier not tied to any persisted entity; the server may
  log it but does not compare it to any entity's id."

  Shared constants in TEST_USERS are canonical for these roles.

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
CLINIC_ADMIN_ID = "clinic-admin-001"
BILLER_ID = "biller-001"
BILLER_ID_ALT = "biller-002"

# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
THERAPIST_FALLBACK_ID = "fallback-therapist-1"
PATIENT_FALLBACK_ID = "fallback-patient-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # ---------------- Opaque roles (shared constants canonical) ----------
    "clinic_admin_headers": build_user_headers(
        CLINIC_ADMIN_ID, "ClinicAdmin",
    ),
    "biller_headers": build_user_headers(BILLER_ID, "Biller"),
    "biller_headers_alt": build_user_headers(BILLER_ID_ALT, "Biller"),
    # ---------------- Entity-backed FALLBACK constants ------------------
    # Safe ONLY for auth/role-mismatch tests and tests that DO NOT
    # exercise ownership. Ownership-gated calls MUST use the per-instance
    # builders below.
    "therapist_fallback_headers": build_user_headers(
        THERAPIST_FALLBACK_ID, "Therapist",
    ),
    "patient_fallback_headers": build_user_headers(
        PATIENT_FALLBACK_ID, "Patient",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed roles.
# ---------------------------------------------------------------------------
def make_therapist_headers(therapist_id: str) -> Dict[str, str]:
    """For Therapist (entity_backed:Therapist). Pass the actual
    Therapist.id of the acting clinician.

    PRD §2.1: "When X-User-Role is Therapist, X-User-ID is the id of
    the acting Therapist row; ownership and capability checks on any
    clinical operation that references a Therapist ... compare the
    resource's clinician_id, prescribing_clinician_id, or
    discharging_clinician_id foreign-key field to X-User-ID."

    Every Therapist-driven call whose success depends on the acting
    therapist's id matching the targeted resource MUST use this
    builder, not the shared THERAPIST_FALLBACK_ID constant.
    """
    return build_user_headers(therapist_id, "Therapist")


def make_patient_headers(patient_id: str) -> Dict[str, str]:
    """For Patient (entity_backed:Patient). Pass the actual Patient.id
    of the acting patient.

    PRD §2.1: "When X-User-Role is Patient, X-User-ID is the id of the
    acting Patient row; the patient can read only their own Patient
    record and acknowledge HEPs whose anchoring episode belongs to
    that patient."
    """
    return build_user_headers(patient_id, "Patient")


def make_clinic_admin_headers(user_id: str = CLINIC_ADMIN_ID
                              ) -> Dict[str, str]:
    """For ClinicAdmin (opaque). Any non-empty operator id works."""
    return build_user_headers(user_id, "ClinicAdmin")


def make_biller_headers(user_id: str = BILLER_ID) -> Dict[str, str]:
    """For Biller (opaque). Any non-empty operator id works."""
    return build_user_headers(user_id, "Biller")


__all__ = [
    "CLINIC_ADMIN_ID",
    "BILLER_ID",
    "BILLER_ID_ALT",
    "THERAPIST_FALLBACK_ID",
    "PATIENT_FALLBACK_ID",
    "TEST_USERS",
    "make_therapist_headers",
    "make_patient_headers",
    "make_clinic_admin_headers",
    "make_biller_headers",
]
