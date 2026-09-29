"""Request-payload builders.

Each factory returns the payload for one write endpoint with defaults that pass
the shape rules, so a test only names the fields its scenario actually turns on.
Overrides are applied last and a value of ``None`` is sent as JSON null rather
than dropped, which is what the tests exercising required fields rely on.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_PROOF_TYPE,
    MONTHLY_COST_CENTS,
)
from .types import Json

# Distinct census identities: ``work_email`` must be unique across all employees.
EMPLOYEE_IDENTITIES = (
    ("Dana Reyes", "dana.reyes@acme.test"),
    ("Rowan Ellis", "rowan.ellis@acme.test"),
    ("Priya Nandi", "priya.nandi@acme.test"),
    ("Marco Silva", "marco.silva@acme.test"),
    ("Ingrid Holm", "ingrid.holm@acme.test"),
    ("Tobias Kern", "tobias.kern@acme.test"),
    ("Selma Aziz", "selma.aziz@acme.test"),
    ("Victor Oneal", "victor.oneal@acme.test"),
)

DEPENDENT_NAMES = (
    "Marta Reyes",
    "Ivo Reyes",
    "Lena Reyes",
    "Tomas Reyes",
    "Nadia Reyes",
    "Emil Reyes",
    "Sonia Reyes",
    "Karl Reyes",
)

# A plausible date of birth per relationship class.
DATE_OF_BIRTH: Dict[str, str] = {
    "SPOUSE": "1988-04-12",
    "DOMESTIC_PARTNER": "1986-11-03",
    "CHILD_BIOLOGICAL": "2014-02-02",
    "STEPCHILD": "2012-07-19",
    "ADOPTED_CHILD": "2013-09-05",
    "DISABLED_ADULT_CHILD": "1999-01-24",
    "LEGAL_GUARDIANSHIP": "2011-03-30",
}

# The document date printed on each proof class. The two recency-scoped classes
# carry a recent date so they clear the recency floor by default.
DOCUMENT_DATE: Dict[str, str] = {
    "MARRIAGE_CERTIFICATE": "2010-05-22",
    "JOINT_TAX_RETURN": "2026-06-30",
    "JOINT_ACCOUNT_STATEMENT": "2026-07-15",
    "DOMESTIC_PARTNER_AFFIDAVIT": "2021-08-14",
    "SHARED_RESIDENCE_PROOF": "2025-12-01",
    "BIRTH_CERTIFICATE": "2014-02-08",
    "ADOPTION_DECREE": "2016-06-17",
    "COURT_ORDER": "2018-10-02",
    "DISABILITY_CERTIFICATION": "2025-05-20",
    "TAX_DEPENDENCY_PROOF": "2026-04-10",
}

DOCUMENT_REFERENCE: Dict[str, str] = {
    "MARRIAGE_CERTIFICATE": "s3://raw/marriage-cert.pdf",
    "JOINT_TAX_RETURN": "s3://redacted/1040-2025-masked.pdf",
    "JOINT_ACCOUNT_STATEMENT": "s3://redacted/joint-account-masked.pdf",
    "DOMESTIC_PARTNER_AFFIDAVIT": "s3://raw/dp-affidavit.pdf",
    "SHARED_RESIDENCE_PROOF": "s3://raw/lease.pdf",
    "BIRTH_CERTIFICATE": "s3://raw/birth-cert.pdf",
    "ADOPTION_DECREE": "s3://raw/adoption-decree.pdf",
    "COURT_ORDER": "s3://raw/guardianship-order.pdf",
    "DISABILITY_CERTIFICATION": "s3://redacted/disability-cert-masked.pdf",
    "TAX_DEPENDENCY_PROOF": "s3://redacted/dependency-proof-masked.pdf",
}

# Which proof classes a relationship rule accepts by default.
ACCEPTABLE_PROOF_TYPES: Dict[str, List[str]] = {
    "SPOUSE": ["MARRIAGE_CERTIFICATE"],
    "DOMESTIC_PARTNER": ["DOMESTIC_PARTNER_AFFIDAVIT", "SHARED_RESIDENCE_PROOF"],
    "CHILD_BIOLOGICAL": ["BIRTH_CERTIFICATE"],
    "STEPCHILD": ["BIRTH_CERTIFICATE", "MARRIAGE_CERTIFICATE"],
    "ADOPTED_CHILD": ["ADOPTION_DECREE"],
    "DISABLED_ADULT_CHILD": ["DISABILITY_CERTIFICATION"],
    "LEGAL_GUARDIANSHIP": ["COURT_ORDER"],
}


def _merge(base: Json, overrides: Dict[str, Any]) -> Json:
    base.update(overrides)
    return base


# ------------------------------------------------------------------ logical clock
def clock_payload(to_iso8601: str) -> Json:
    return {"to_iso8601": to_iso8601}


# ----------------------------------------------------------------------- employees
def employee_payload(index: int = 0, **overrides: Any) -> Json:
    full_name, work_email = EMPLOYEE_IDENTITIES[index % len(EMPLOYEE_IDENTITIES)]
    if index >= len(EMPLOYEE_IDENTITIES):
        work_email = f"employee.{index}@acme.test"
    return _merge(
        {
            "full_name": full_name,
            "work_email": work_email,
            "coverage_tier": "FAMILY",
            "employer_monthly_premium_cents": 148000,
            "hire_date": "2019-03-04",
        },
        overrides,
    )


def dependent_payload(
    relationship_type: str = "SPOUSE", index: int = 0, **overrides: Any
) -> Json:
    return _merge(
        {
            "relationship_type": relationship_type,
            "full_name": DEPENDENT_NAMES[index % len(DEPENDENT_NAMES)],
            "date_of_birth": DATE_OF_BIRTH.get(relationship_type, "2010-01-01"),
            "monthly_cost_cents": MONTHLY_COST_CENTS.get(relationship_type, 30500),
        },
        overrides,
    )


def paid_claim_payload(
    service_date: str = "2026-09-20",
    paid_cents: int = 150000,
    index: int = 1,
    **overrides: Any,
) -> Json:
    return _merge(
        {
            "service_date": service_date,
            "paid_cents": paid_cents,
            "employee_premium_offset_cents": 0,
            "claim_reference": f"CLM-{6000 + index}",
            "provider_type": "MEDICAL",
        },
        overrides,
    )


# ------------------------------------------------------------------ audit programs
def program_payload(**overrides: Any) -> Json:
    return _merge(
        {
            "program_name": "PY2026 Dependent Eligibility Audit",
            "plan_year": 2026,
            "amnesty_days": 21,
            "response_days": 45,
            "reminder_min_gap_days": 7,
            "max_reminders": 3,
            "poe_verification_enabled": False,
        },
        overrides,
    )


def documentation_rule_payload(
    relationship_type: str = "SPOUSE", phase: str = "AUDIT", **overrides: Any
) -> Json:
    payload: Json = {
        "relationship_type": relationship_type,
        "phase": phase,
        "acceptable_proof_types": list(
            ACCEPTABLE_PROOF_TYPES.get(
                relationship_type, [DEFAULT_PROOF_TYPE.get(relationship_type, "COURT_ORDER")]
            )
        ),
        "min_accepted_documents": 1,
        "affidavit_allowed": False,
        "requires_recency_days": 365,
        "auto_terminate_on_lapse": False,
    }
    if phase == "POINT_OF_ENROLLMENT":
        payload["grace_days"] = 30
    return _merge(payload, overrides)


def scope_payload(
    expected_program_version: int, scope_type: str = "FULL_CENSUS", **overrides: Any
) -> Json:
    payload: Json = {
        "expected_program_version": expected_program_version,
        "scope_type": scope_type,
    }
    return _merge(payload, overrides)


def communicate_payload(**overrides: Any) -> Json:
    return _merge({"channel": "EMAIL", "template_code": "AUDIT_ANNOUNCE_V1"}, overrides)


def reminder_payload(**overrides: Any) -> Json:
    return _merge({"channel": "EMAIL", "template_code": "AUDIT_REMINDER_V1"}, overrides)


def savings_payload(variant: str = "PROVISIONAL", **overrides: Any) -> Json:
    return _merge({"variant": variant}, overrides)


# ------------------------------------------------------------- proof submissions
def proof_submission_payload(
    case_id: str,
    dependent_id: str,
    proof_type: str = "MARRIAGE_CERTIFICATE",
    **overrides: Any,
) -> Json:
    return _merge(
        {
            "case_id": case_id,
            "dependent_id": dependent_id,
            "proof_type": proof_type,
            "document_reference": DOCUMENT_REFERENCE.get(
                proof_type, "s3://raw/document.pdf"
            ),
            "document_date": DOCUMENT_DATE.get(proof_type, "2020-01-01"),
            "redaction_applied": False,
        },
        overrides,
    )


def decision_payload(
    decision: str = "ACCEPT", reason_code: Optional[str] = None, **overrides: Any
) -> Json:
    payload: Json = {"decision": decision}
    if reason_code is not None:
        payload["reason_code"] = reason_code
    return _merge(payload, overrides)


def redaction_payload(
    redacted_document_reference: str = "s3://redacted/replacement-masked.pdf",
    **overrides: Any,
) -> Json:
    return _merge(
        {"redacted_document_reference": redacted_document_reference}, overrides
    )


# --------------------------------------------------------------- amnesty removals
def amnesty_removal_payload(
    dependent_id: str, case_id: str, **overrides: Any
) -> Json:
    return _merge(
        {
            "dependent_id": dependent_id,
            "case_id": case_id,
            "reason_code": "NO_LONGER_ELIGIBLE",
            "attestation_signed": True,
        },
        overrides,
    )


# ----------------------------------------------------------------------- appeals
def appeal_payload(
    case_id: str,
    dependent_id: str,
    grounds: str = "ADMINISTRATIVE_ERROR",
    **overrides: Any,
) -> Json:
    payload: Json = {
        "case_id": case_id,
        "dependent_id": dependent_id,
        "grounds": grounds,
        "statement": (
            "Termination issued in error; eligibility documentation was already on file."
        ),
    }
    if grounds == "DOMESTIC_PARTNERSHIP_AFFIDAVIT":
        payload["affidavit_reference"] = "s3://raw/dp-affidavit-signed.pdf"
    if grounds == "CUSTODY_ARRANGEMENT":
        payload["custody_order_reference"] = "s3://raw/custody-order.pdf"
    return _merge(payload, overrides)


def appeal_decision_payload(decision: str = "GRANT", **overrides: Any) -> Json:
    payload: Json = {"decision": decision}
    if decision == "GRANT":
        payload["decision_rationale"] = (
            "Eligibility documentation predates the audit; the termination is reversed."
        )
    elif decision == "DENY":
        payload["decision_rationale"] = (
            "No acceptable documentation was produced within the response window."
        )
    else:
        payload["remand_reason"] = "A certified copy of the underlying document is required."
    return _merge(payload, overrides)


def appeal_resubmit_payload(**overrides: Any) -> Json:
    return _merge(
        {
            "statement": (
                "The certified copy requested on remand is attached for review."
            )
        },
        overrides,
    )


# ------------------------------------------------------------ continuation rights
def continuation_election_payload(election: str = "ELECT", **overrides: Any) -> Json:
    return _merge({"election": election}, overrides)


# --------------------------------------------------------------- claim recoveries
def claim_recovery_payload(
    dependent_id: str,
    termination_notice_id: str,
    expected_dependent_version: int,
    recovery_variant: str = "STRICT",
    ineligibility_onset_date: str = "2026-09-01",
    **overrides: Any,
) -> Json:
    return _merge(
        {
            "dependent_id": dependent_id,
            "termination_notice_id": termination_notice_id,
            "recovery_variant": recovery_variant,
            "ineligibility_onset_date": ineligibility_onset_date,
            "expected_dependent_version": expected_dependent_version,
        },
        overrides,
    )


def issue_demand_payload(waiver_credit_cents: int = 0, **overrides: Any) -> Json:
    return _merge({"waiver_credit_cents": waiver_credit_cents}, overrides)


def payment_payload(
    amount_cents: int, received_date: str = "2026-11-02", **overrides: Any
) -> Json:
    return _merge(
        {"amount_cents": amount_cents, "received_date": received_date}, overrides
    )
