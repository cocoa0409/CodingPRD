"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract. They are intentionally permissive on optional fields —
when PRD prose is silent on a specific projection, the assertion does
not pin it.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields helpers — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    """PRD §2.4: "Every resource carries an id, which is a server-minted
    UUID. The id has no type prefix — it is the bare canonical UUID
    string. Resources also carry created_at, an ISO 8601 UTC timestamp
    with three fractional digits, captured at the moment of creation."
    """
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: "Most entities … additionally carry updated_at (also an
    ISO 8601 UTC timestamp with three fractional digits, refreshed on
    every state-changing mutation) and version (a non-negative integer
    initialised to 1 at creation and incremented by exactly one on each
    state-changing mutation)."
    """
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, "
        f"got {data.get('version')!r}"
    )


def _assert_no_updated_at_or_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: "The append-only BillingLedgerEntry is the single
    exception: each entry carries only id and created_at — it has no
    updated_at and no version, because ledger rows are immutable once
    written."
    """
    assert "updated_at" not in data, (
        "append-only ledger entry must not carry updated_at"
    )
    assert "version" not in data, (
        "append-only ledger entry must not carry version"
    )


# ---------------------------------------------------------------------------
# Clinic — PRD §3.1 / §2.5
# ---------------------------------------------------------------------------
def assert_clinic(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("name"), str) and data["name"]
    # PRD §2.5: "Each Clinic carries a logical clock field, now_ts".
    assert is_iso8601_timestamp(data.get("now_ts", "")), (
        f"now_ts must be ISO 8601, got {data.get('now_ts')!r}"
    )


# ---------------------------------------------------------------------------
# Patient — PRD §3.1
# ---------------------------------------------------------------------------
def assert_patient(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("clinic_id", ""))
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("date_of_birth"), str)
    assert isinstance(data.get("insurance_member_id"), str)
    # PRD §3.1: "Each patient also carries two computed score fields —
    # clinical_progress_score_provisional and
    # clinical_progress_score_adjudicated — both initialised to 0.0".
    assert "clinical_progress_score_provisional" in data
    assert isinstance(
        data["clinical_progress_score_provisional"], (int, float),
    )
    assert "clinical_progress_score_adjudicated" in data
    assert isinstance(
        data["clinical_progress_score_adjudicated"], (int, float),
    )
    # PRD §3.1: "a status of ACTIVE or DISCHARGED; patients are created
    # ACTIVE."
    assert data.get("status") in {"ACTIVE", "DISCHARGED"}


# ---------------------------------------------------------------------------
# Therapist — PRD §3.1
# ---------------------------------------------------------------------------
def assert_therapist(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("clinic_id", ""))
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    # PRD §3.1: "the therapist's credential (one of BCBA or RBT)".
    assert data.get("credential") in {"BCBA", "RBT"}
    assert isinstance(data.get("license_number"), str)
    # PRD §3.1: "Each therapist also carries a status of either ACTIVE
    # or SUSPENDED; therapists are created ACTIVE."
    assert data.get("status") in {"ACTIVE", "SUSPENDED"}


# ---------------------------------------------------------------------------
# DiagnosticEvaluation — PRD §3.2
# ---------------------------------------------------------------------------
EVALUATION_STATUSES = {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "VOID"}


def assert_evaluation(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("evaluator_therapist_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_at", ""))
    assert data.get("status") in EVALUATION_STATUSES, (
        f"unexpected evaluation status {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# TreatmentPlan — PRD §3.3
# ---------------------------------------------------------------------------
PLAN_STATUSES = {"DRAFT", "ACTIVE", "SUPERSEDED", "EXPIRED"}


def assert_treatment_plan(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("source_evaluation_id", ""))
    assert isinstance(data.get("weekly_direct_hours_target"), int)
    assert isinstance(
        data.get("weekly_supervision_hours_target"), (int, float),
    )
    assert isinstance(
        data.get("weekly_parent_training_hours_target"), (int, float),
    )
    # PRD §3.3: "the plan's plan_version is set to 1."
    assert isinstance(data.get("plan_version"), int)
    assert data["plan_version"] >= 1
    assert data.get("status") in PLAN_STATUSES, (
        f"unexpected plan status {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Authorization — PRD §3.4 / §2.9
# ---------------------------------------------------------------------------
AUTHORIZATION_STATUSES = {
    "PENDING", "APPROVED", "ACTIVE",
    "EXHAUSTED", "EXPIRED", "RENEWED", "DENIED",
}
ALLOWED_CPT_CODES = {"97151", "97153", "97155", "97156"}


def assert_authorization(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("treatment_plan_id", ""))
    assert isinstance(data.get("payer_name"), str) and data["payer_name"]
    # PRD §3.4: cpt_code is "one of 97151 for evaluation, 97153 for direct
    # RBT therapy, 97155 for BCBA supervision, or 97156 for parent
    # training".
    assert data.get("cpt_code") in ALLOWED_CPT_CODES, (
        f"unexpected cpt_code {data.get('cpt_code')!r}"
    )
    assert isinstance(data.get("approved_units"), int)
    assert is_iso8601_timestamp(data.get("effective_start", ""))
    assert is_iso8601_timestamp(data.get("effective_end", ""))
    # PRD §2.9: "exposed on every read of the Authorization as
    # provisional_units_consumed and adjudicated_units_consumed."
    assert isinstance(data.get("provisional_units_consumed"), int)
    assert isinstance(data.get("adjudicated_units_consumed"), int)
    assert data.get("status") in AUTHORIZATION_STATUSES, (
        f"unexpected authorization status {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# TherapySession — PRD §3.5
# ---------------------------------------------------------------------------
SESSION_STATUSES = {
    "SCHEDULED", "IN_PROGRESS", "COMPLETED", "BILLED",
    "DISPUTED", "CANCELLED",
}
SESSION_TYPES = {"DIRECT_RBT", "BCBA_SUPERVISION", "PARENT_TRAINING"}


def assert_therapy_session(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("authorization_id", ""))
    assert is_valid_uuid(data.get("therapist_id", ""))
    # PRD §3.5: session_type is one of DIRECT_RBT | BCBA_SUPERVISION |
    # PARENT_TRAINING.
    assert data.get("session_type") in SESSION_TYPES
    assert is_iso8601_timestamp(data.get("planned_start", ""))
    assert is_iso8601_timestamp(data.get("planned_end", ""))
    # PRD §3.5: "The system computes planned_units by dividing the
    # minute-count by 15 and rounding up to the next whole unit."
    assert isinstance(data.get("planned_units"), int)
    assert data["planned_units"] >= 1
    assert data.get("status") in SESSION_STATUSES, (
        f"unexpected session status {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# InsuranceClaim — PRD §3.6
# ---------------------------------------------------------------------------
CLAIM_STATUSES = {
    "DRAFT", "SUBMITTED", "ADJUDICATED",
    "PAID", "DENIED", "APPEALED",
}
DENIAL_REASONS = {
    "SUPERVISION_RATIO_BREACH", "UNITS_OUT_OF_AUTH",
    "MISSING_PROGRESS_NOTE", "DUPLICATE_LINE",
}


def assert_insurance_claim(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("authorization_id", ""))
    session_ids = data.get("session_ids")
    assert isinstance(session_ids, list)
    for sid in session_ids:
        assert is_valid_uuid(sid)
    # PRD §3.6: "At creation, appeal_round is 0, submitted_amount_cents
    # and reimbursed_amount_cents are 0".
    assert isinstance(data.get("appeal_round"), int)
    assert data["appeal_round"] >= 0
    assert isinstance(data.get("submitted_amount_cents"), int)
    assert isinstance(data.get("reimbursed_amount_cents"), int)
    assert data.get("status") in CLAIM_STATUSES, (
        f"unexpected claim status {data.get('status')!r}"
    )
    dr = data.get("denial_reason")
    if dr is not None:
        assert dr in DENIAL_REASONS, (
            f"unexpected denial_reason {dr!r}"
        )


# ---------------------------------------------------------------------------
# BillingLedgerEntry — PRD §2.11 (append-only)
# ---------------------------------------------------------------------------
LEDGER_ENTRY_TYPES = {
    "PROVISIONAL_DEBIT", "PROVISIONAL_CREDIT",
    "ADJUDICATED_DEBIT", "ADJUDICATED_CREDIT",
}
LEDGER_REASON_CODES = {
    "SESSION_COMPLETED", "SESSION_CANCELLED", "SESSION_DISPUTED",
    "CLAIM_PAID", "CLAIM_DENIED", "CLAIM_APPEAL_PAID",
}


def assert_billing_ledger_entry(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert is_valid_uuid(data.get("authorization_id", ""))
    # PRD §2.11: "each entry's entry_type is one of PROVISIONAL_DEBIT,
    # PROVISIONAL_CREDIT, ADJUDICATED_DEBIT, or ADJUDICATED_CREDIT".
    assert data.get("entry_type") in LEDGER_ENTRY_TYPES
    # PRD §2.11: "its reason_code is one of SESSION_COMPLETED,
    # SESSION_CANCELLED, SESSION_DISPUTED, CLAIM_PAID, CLAIM_DENIED, or
    # CLAIM_APPEAL_PAID".
    assert data.get("reason_code") in LEDGER_REASON_CODES
    # PRD §2.11: "its units_delta carries the signed unit movement
    # (negative for debits, positive for credits)."
    assert isinstance(data.get("units_delta"), int)
    et = data["entry_type"]
    if et.endswith("DEBIT"):
        assert data["units_delta"] < 0, (
            f"DEBIT must have negative units_delta, "
            f"got {data['units_delta']}"
        )
    else:
        assert data["units_delta"] > 0, (
            f"CREDIT must have positive units_delta, "
            f"got {data['units_delta']}"
        )


# ---------------------------------------------------------------------------
# Supervision-ratio snapshot — PRD §2.10 / §3.4
# ---------------------------------------------------------------------------
def assert_supervision_ratio_snapshot(data: Dict[str, Any]) -> None:
    """PRD §2.10: "the read capability simply returns the computed
    ratio, the boolean compliant, the rbt_minutes, the
    bcba_supervision_minutes, the window_start, and the window_end."
    """
    assert "ratio" in data
    assert isinstance(data["ratio"], (int, float))
    assert "compliant" in data
    assert isinstance(data["compliant"], bool)
    assert "rbt_minutes" in data
    assert isinstance(data["rbt_minutes"], (int, float))
    assert "bcba_supervision_minutes" in data
    assert isinstance(data["bcba_supervision_minutes"], (int, float))
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))


# ---------------------------------------------------------------------------
# Version-bump invariant — PRD §2.4 / §2.6
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(after: Dict[str, Any],
                                      before_version: int) -> None:
    """PRD §2.4: "a non-negative integer initialised to 1 at creation
    and incremented by exactly one on each state-changing mutation."
    """
    assert after["version"] == before_version + 1, (
        f"expected version {before_version + 1}, "
        f"got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Progress-score precision — PRD §2.12
# ---------------------------------------------------------------------------
def assert_progress_score_precision(score: float) -> None:
    """PRD §2.12: "The patient clinical progress score, conversely, is
    stored to two decimal places and is also rounded half up."
    """
    rounded = round(score + 1e-9, 2)
    assert abs(score - rounded) < 1e-6, (
        f"progress score {score} must be at two decimal places"
    )


__all__ = [
    "assert_clinic",
    "assert_patient",
    "assert_therapist",
    "assert_evaluation",
    "assert_treatment_plan",
    "assert_authorization",
    "assert_therapy_session",
    "assert_insurance_claim",
    "assert_billing_ledger_entry",
    "assert_supervision_ratio_snapshot",
    "assert_version_incremented_by_one",
    "assert_progress_score_precision",
    "EVALUATION_STATUSES",
    "PLAN_STATUSES",
    "AUTHORIZATION_STATUSES",
    "ALLOWED_CPT_CODES",
    "SESSION_STATUSES",
    "SESSION_TYPES",
    "CLAIM_STATUSES",
    "DENIAL_REASONS",
    "LEDGER_ENTRY_TYPES",
    "LEDGER_REASON_CODES",
]
