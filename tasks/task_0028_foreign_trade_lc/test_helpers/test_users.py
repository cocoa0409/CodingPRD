"""Pre-built role headers for every role in the PRD.

PRD §2.1: 'For the Applicant role, X-User-ID is the id of the acting
Applicant entity; ownership checks on any resource that references an
applicant compare the resource's applicant_id to X-User-ID. For the
Beneficiary role, X-User-ID is the id of the acting Beneficiary entity
... For the four bank roles ... X-User-ID is the id of the acting Bank
entity ... For Operator and Auditor, X-User-ID is an opaque operator
identifier not tied to any persisted entity.'

Six of the eight roles are entity_backed (Applicant, Beneficiary,
IssuingBank, AdvisingBank, ConfirmingBank, NegotiatingBank). Tests that
exercise an ownership-gated endpoint MUST mint the headers from the
actual entity id via the per-instance builder; the shared TEST_USERS
constants for these roles are reserved for tests that do NOT depend on
ownership (e.g., 400-on-bad-payload, 404-on-missing-resource, RBAC
forbidden-role checks where no entity has been created yet).

Operator and Auditor are opaque — the shared constant is canonical.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# --- Shared constants — for non-ownership tests and opaque roles ---------
# Tests that exercise ownership-gated calls MUST use the make_<role>_headers
# builder with the actual entity id; using the shared constant for an
# entity_backed role on an ownership-gated call would fail every legit
# implementation (X-User-ID = "test-applicant-1" never equals any real
# applicant entity's UUID id).
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    "beneficiary_headers": build_user_headers("test-beneficiary-1", "Beneficiary"),
    "issuing_bank_headers": build_user_headers("test-issuing-bank-1", "IssuingBank"),
    "advising_bank_headers": build_user_headers("test-advising-bank-1", "AdvisingBank"),
    "confirming_bank_headers": build_user_headers("test-confirming-bank-1", "ConfirmingBank"),
    "negotiating_bank_headers": build_user_headers("test-negotiating-bank-1", "NegotiatingBank"),
    # Opaque roles — canonical (PRD §2.1).
    "operator_headers": build_user_headers("op-001", "Operator"),
    "operator_headers_alt": build_user_headers("op-002", "Operator"),
    "operator_headers_alt2": build_user_headers("op-003", "Operator"),
    "auditor_headers": build_user_headers("auditor-001", "Auditor"),
}


# --- Per-instance builders — REQUIRED for entity_backed roles ------------
# After a fixture creates an Applicant entity, downstream Applicant calls
# must use make_applicant_headers(applicant["id"]) so the request's
# X-User-ID equals the Applicant.id and ownership checks succeed.

def make_applicant_headers(applicant_id: str) -> Dict[str, str]:
    """Headers for the Applicant role.

    PRD §2.1: 'For the Applicant role, X-User-ID is the id of the acting
    Applicant entity; ownership checks on any resource that references
    an applicant compare the resource's applicant_id to X-User-ID.'
    Pass the actual Applicant.id whenever the call is ownership-gated.
    """
    return build_user_headers(applicant_id, "Applicant")


def make_beneficiary_headers(beneficiary_id: str) -> Dict[str, str]:
    """Headers for the Beneficiary role.

    PRD §2.1: 'For the Beneficiary role, X-User-ID is the id of the
    acting Beneficiary entity; ownership checks on any resource that
    references a beneficiary compare the resource's beneficiary_id to
    X-User-ID.' Pass the actual Beneficiary.id for ownership-gated calls.
    """
    return build_user_headers(beneficiary_id, "Beneficiary")


def make_issuing_bank_headers(bank_id: str) -> Dict[str, str]:
    """Headers for the IssuingBank role.

    PRD §2.1: 'For the four bank roles ... X-User-ID is the id of the
    acting Bank entity; ownership checks on any LC, amendment,
    presentation, settlement or reimbursement claim compare the relevant
    per-role bank foreign key (issuing_bank_id, advising_bank_id,
    confirming_bank_id, or the negotiating bank reference on the
    corresponding settlement) to X-User-ID.'
    """
    return build_user_headers(bank_id, "IssuingBank")


def make_advising_bank_headers(bank_id: str) -> Dict[str, str]:
    """Headers for the AdvisingBank role. Pass the Bank.id of the
    advising bank named on the LC."""
    return build_user_headers(bank_id, "AdvisingBank")


def make_confirming_bank_headers(bank_id: str) -> Dict[str, str]:
    """Headers for the ConfirmingBank role. Pass the Bank.id of the
    confirming bank named on the LC."""
    return build_user_headers(bank_id, "ConfirmingBank")


def make_negotiating_bank_headers(bank_id: str) -> Dict[str, str]:
    """Headers for the NegotiatingBank role. Pass the Bank.id of the
    negotiating bank initiating the advance."""
    return build_user_headers(bank_id, "NegotiatingBank")


def make_operator_headers(operator_id: str = "op-001") -> Dict[str, str]:
    """Headers for the Operator role. PRD §2.1: 'For Operator and Auditor,
    X-User-ID is an opaque operator identifier not tied to any persisted
    entity.' Distinct ids matter for the reviewer-segregation rule
    (PRD §3.5: 'the secondary must differ from the primary')."""
    return build_user_headers(operator_id, "Operator")


def make_auditor_headers(auditor_id: str = "auditor-001") -> Dict[str, str]:
    """Headers for the Auditor role (read-only)."""
    return build_user_headers(auditor_id, "Auditor")


__all__ = [
    "TEST_USERS",
    "make_applicant_headers",
    "make_beneficiary_headers",
    "make_issuing_bank_headers",
    "make_advising_bank_headers",
    "make_confirming_bank_headers",
    "make_negotiating_bank_headers",
    "make_operator_headers",
    "make_auditor_headers",
]
