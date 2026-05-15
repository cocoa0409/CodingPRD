"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- MedicalDirector, Consultant, AttendingPhysician, SeniorPhysician,
  Nurse, FinanceOfficer are OPAQUE — X-User-ID is an opaque operator
  identifier not tied to any persisted entity row. The server may
  record it (on Project.reviewer_id, TreatmentPlan.consultant_id,
  TreatmentPlan.attending_physician_id, TreatmentPlan.senior_physician_id,
  AuditEntry.actor_id) but does not look it up in any entity's
  primary-key index. For physician roles the opaque id is the
  qualifying doctor id and must match Project.qualified_doctor_ids
  and TreatmentPlan.attending_physician_id when ownership is required
  by a transition's preconditions.

- Customer is ENTITY-BACKED — PRD §2.1: "When X-User-Role is Customer,
  X-User-ID is the id of the acting Customer; ownership checks on any
  resource that references a Customer compare the resource's
  foreign-key field (for example, TreatmentPlan.customer_id ...) to
  X-User-ID." Therefore every Customer call whose success depends on
  owning the targeted Plan / FollowUp / InstallmentPlan (sign-consent,
  submit-feedback, pay-installment, patch-self, get-self) MUST mint
  headers via make_customer_headers(customer["id"]) — never via the
  CUSTOMER_FALLBACK_ID shared constant.

  The CUSTOMER_FALLBACK_ID shared constant below is ONLY safe for
  tests that DO NOT exercise ownership (header-missing, role-mismatch,
  NotFound paths, list endpoints that the customer is NOT permitted
  to invoke).

  Although the physician roles are technically "opaque", PRD §2.1
  requires that AttendingPhysician calls supply X-User-ID equal to
  TreatmentPlan.attending_physician_id, and SeniorPhysician calls
  must NOT equal the attending physician (segregation of duties).
  Per-instance builders are therefore also exposed for them.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — shared constants safe wherever
# the test is NOT exercising ownership matching.
# ---------------------------------------------------------------------------
MEDICAL_DIRECTOR_ID = "md-001"
MEDICAL_DIRECTOR_ID_ALT = "md-002"

CONSULTANT_ID = "consultant-001"
CONSULTANT_ID_ALT = "consultant-002"

# Physician opaque ids — these double as "doctor user ids" that may be
# placed in Project.qualified_doctor_ids and TreatmentPlan
# .attending_physician_id. Tests that need doctor qualification will
# wire these explicitly into the project's qualified_doctor_ids list.
ATTENDING_PHYSICIAN_ID = "doctor-attending-001"
ATTENDING_PHYSICIAN_ID_ALT = "doctor-attending-002"

SENIOR_PHYSICIAN_ID = "doctor-senior-001"
SENIOR_PHYSICIAN_ID_ALT = "doctor-senior-002"

NURSE_ID = "nurse-001"
NURSE_ID_ALT = "nurse-002"

FINANCE_OFFICER_ID = "finance-001"
FINANCE_OFFICER_ID_ALT = "finance-002"

# Customer fallback — ONLY for tests that do not exercise ownership
# (e.g. header-missing, role-mismatch, NotFound paths). Ownership-
# gated calls MUST instead mint headers via
# make_customer_headers(customer["id"]).
CUSTOMER_FALLBACK_ID = "fallback-customer-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — shared constants are canonical (subject to the
    # physician-equality rules called out above).
    "medical_director_headers": build_user_headers(
        MEDICAL_DIRECTOR_ID, "MedicalDirector",
    ),
    "medical_director_headers_alt": build_user_headers(
        MEDICAL_DIRECTOR_ID_ALT, "MedicalDirector",
    ),
    "consultant_headers": build_user_headers(CONSULTANT_ID, "Consultant"),
    "consultant_headers_alt": build_user_headers(
        CONSULTANT_ID_ALT, "Consultant",
    ),
    "attending_physician_headers": build_user_headers(
        ATTENDING_PHYSICIAN_ID, "AttendingPhysician",
    ),
    "attending_physician_headers_alt": build_user_headers(
        ATTENDING_PHYSICIAN_ID_ALT, "AttendingPhysician",
    ),
    "senior_physician_headers": build_user_headers(
        SENIOR_PHYSICIAN_ID, "SeniorPhysician",
    ),
    "senior_physician_headers_alt": build_user_headers(
        SENIOR_PHYSICIAN_ID_ALT, "SeniorPhysician",
    ),
    "nurse_headers": build_user_headers(NURSE_ID, "Nurse"),
    "nurse_headers_alt": build_user_headers(NURSE_ID_ALT, "Nurse"),
    "finance_officer_headers": build_user_headers(
        FINANCE_OFFICER_ID, "FinanceOfficer",
    ),
    "finance_officer_headers_alt": build_user_headers(
        FINANCE_OFFICER_ID_ALT, "FinanceOfficer",
    ),
    # Entity-backed Customer fallback — DO NOT use for ownership-gated
    # calls. Use make_customer_headers(customer["id"]).
    "customer_headers": build_user_headers(
        CUSTOMER_FALLBACK_ID, "Customer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for Customer ownership-gated calls,
# and convenient for physician roles when a test needs a specific
# doctor id (qualified_doctor_ids matching, segregation of duties).
# ---------------------------------------------------------------------------
def make_customer_headers(customer_id: str) -> Dict[str, str]:
    """For Customer (entity_backed:Customer). Pass the Customer.id of
    the acting customer. Every Customer call whose success depends on
    owning the targeted TreatmentPlan / FollowUp / InstallmentPlan
    (sign-consent, submit-feedback, pay-installment, patch-self, get-
    self) MUST use this builder, not the CUSTOMER_FALLBACK_ID
    shared constant.
    """
    return build_user_headers(customer_id, "Customer")


def make_medical_director_headers(actor_id: str) -> Dict[str, str]:
    return build_user_headers(actor_id, "MedicalDirector")


def make_consultant_headers(actor_id: str) -> Dict[str, str]:
    return build_user_headers(actor_id, "Consultant")


def make_attending_physician_headers(doctor_id: str) -> Dict[str, str]:
    """For AttendingPhysician. The doctor_id MUST equal
    TreatmentPlan.attending_physician_id and must appear in
    Project.qualified_doctor_ids when the call is ownership-gated
    (POST /plans/{id}/approve, POST /appointments/{id}/op-records/*).
    """
    return build_user_headers(doctor_id, "AttendingPhysician")


def make_senior_physician_headers(doctor_id: str) -> Dict[str, str]:
    """For SeniorPhysician. The doctor_id MUST be different from
    TreatmentPlan.attending_physician_id when the call is the
    countersign action (segregation of duties).
    """
    return build_user_headers(doctor_id, "SeniorPhysician")


def make_nurse_headers(nurse_id: str) -> Dict[str, str]:
    return build_user_headers(nurse_id, "Nurse")


def make_finance_officer_headers(officer_id: str) -> Dict[str, str]:
    return build_user_headers(officer_id, "FinanceOfficer")


__all__ = [
    "MEDICAL_DIRECTOR_ID",
    "MEDICAL_DIRECTOR_ID_ALT",
    "CONSULTANT_ID",
    "CONSULTANT_ID_ALT",
    "ATTENDING_PHYSICIAN_ID",
    "ATTENDING_PHYSICIAN_ID_ALT",
    "SENIOR_PHYSICIAN_ID",
    "SENIOR_PHYSICIAN_ID_ALT",
    "NURSE_ID",
    "NURSE_ID_ALT",
    "FINANCE_OFFICER_ID",
    "FINANCE_OFFICER_ID_ALT",
    "CUSTOMER_FALLBACK_ID",
    "TEST_USERS",
    "make_customer_headers",
    "make_medical_director_headers",
    "make_consultant_headers",
    "make_attending_physician_headers",
    "make_senior_physician_headers",
    "make_nurse_headers",
    "make_finance_officer_headers",
]
