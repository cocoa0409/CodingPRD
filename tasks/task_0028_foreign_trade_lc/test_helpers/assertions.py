"""Per-entity assertions and domain invariant checkers (PRD §2.4, §3).

Field-shape and value-range assertions stick to PRD prose. Common-fields
discipline is split between full (id+created_at+updated_at+version) and
bare (id+created_at only) per PRD §2.4 ('Two entity classes are
immutable event records and therefore omit both updated_at and version:
SwiftMessage, ExpiryAlert, ExternalEvent, AuditLogEntry, and the
singleton Clock row. Each of these carries only id and created_at.').
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    DOCUMENT_TYPE_VALUES,
    DISCREPANCY_CODE_VALUES,
)


# ---------------------------------------------------------------------------
# Common-field shape (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_common_fields_full(data: Dict[str, Any], label: str) -> None:
    """Persistent entities — id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 with three fractional digits, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 with three fractional digits, "
        f"got {data.get('updated_at')!r}"
    )
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"{label}.version must be a positive integer, got {version!r}"
    )


def _assert_common_fields_bare(data: Dict[str, Any], label: str) -> None:
    """Append-only / event entities — id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Bank / Applicant / Beneficiary (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_bank(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Bank")
    assert data.get("bank_role") in {"ISSUING", "ADVISING", "CONFIRMING", "NEGOTIATING"}, (
        f"Bank.bank_role unexpected: {data.get('bank_role')!r}"
    )
    assert isinstance(data.get("swift_bic"), str)
    bic = data["swift_bic"]
    assert len(bic) in (8, 11), f"swift_bic must be 8 or 11 chars, got {bic!r}"
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("country_code"), str) and len(data["country_code"]) == 2
    assert data.get("status") in {"ACTIVE", "SUSPENDED"}


def assert_applicant(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Applicant")
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("country_code"), str) and len(data["country_code"]) == 2
    assert data.get("status") in {"ACTIVE", "SUSPENDED"}


def assert_beneficiary(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Beneficiary")
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("country_code"), str) and len(data["country_code"]) == 2
    assert data.get("status") in {"ACTIVE", "SUSPENDED"}


# ---------------------------------------------------------------------------
# LetterOfCredit (PRD §3.2)
# ---------------------------------------------------------------------------
LC_LIFECYCLE_STATUSES = {
    "DRAFT", "UNDER_REVIEW", "ISSUED", "ADVISED", "ACTIVE",
    "EXPIRED", "CANCELLED", "CLOSED",
}
LC_AMENDMENT_CONSENT_STATUSES = {
    "NONE", "PENDING_APPLICANT", "PENDING_BENEFICIARY",
    "PENDING_CONFIRMING_BANK", "CONSENTED", "REJECTED",
}
LC_CONFIRMATION_STATUSES = {
    "NOT_REQUIRED", "PENDING", "CONFIRMED", "DECLINED",
}


def assert_letter_of_credit(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "LetterOfCredit")
    assert isinstance(data.get("applicant_id"), str)
    assert isinstance(data.get("beneficiary_id"), str)
    assert isinstance(data.get("issuing_bank_id"), str)
    assert isinstance(data.get("advising_bank_id"), str)
    # confirming_bank_id may be None
    cfb = data.get("confirming_bank_id", None)
    assert cfb is None or isinstance(cfb, str)

    assert data.get("lc_type") in {"SIGHT", "USANCE"}
    if data["lc_type"] == "USANCE":
        assert data.get("usance_tenor_days") in {30, 60, 90, 120, 180}, (
            f"USANCE LC must carry usance_tenor_days in 30/60/90/120/180; "
            f"got {data.get('usance_tenor_days')!r}"
        )

    assert isinstance(data.get("currency"), str) and len(data["currency"]) == 3
    assert isinstance(data.get("amount_minor_units"), int)
    assert data["amount_minor_units"] >= 0
    tol = data.get("tolerance_pct")
    assert isinstance(tol, (int, float)) and 0 <= float(tol) <= 10

    assert isinstance(data.get("drawn_amount_minor_units"), int)
    assert data["drawn_amount_minor_units"] >= 0
    assert isinstance(data.get("available_amount_minor_units"), int)
    assert data["available_amount_minor_units"] >= 0

    assert isinstance(data.get("latest_shipment_date"), str)
    assert isinstance(data.get("expiry_date"), str)
    assert isinstance(data.get("required_documents"), list)
    assert isinstance(data.get("confirmation_required"), bool)

    assert data.get("lifecycle_status") in LC_LIFECYCLE_STATUSES
    assert data.get("amendment_consent_status") in LC_AMENDMENT_CONSENT_STATUSES
    assert data.get("confirmation_status") in LC_CONFIRMATION_STATUSES


def assert_lc_invariants(data: Dict[str, Any]) -> None:
    """Domain invariants that hold on any LC snapshot (PRD §2.5, §2.6, §3.5).

    PRD §2.5 / §3.5: cap = floor(amount * (100 + tolerance_pct) / 100);
    drawn is the sum of {ACCEPTED, PAID} settlements; available = max(0, cap - drawn).
    """
    cap = (data["amount_minor_units"] * (100 + data["tolerance_pct"])) // 100
    drawn = data["drawn_amount_minor_units"]
    available = data["available_amount_minor_units"]
    assert available == max(0, cap - drawn), (
        f"available_amount must equal max(0, cap - drawn): "
        f"cap={cap}, drawn={drawn}, available={available}"
    )


# ---------------------------------------------------------------------------
# LcAmendment (PRD §3.4)
# ---------------------------------------------------------------------------
AMENDMENT_STATUSES = {"PENDING", "CONSENTED", "REJECTED", "WITHDRAWN"}
CONSENT_VALUES = {"PENDING", "CONSENTED", "REJECTED", "NOT_REQUIRED"}
REJECTED_BY_ROLES = {"APPLICANT", "BENEFICIARY", "CONFIRMING_BANK"}


def assert_lc_amendment(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "LcAmendment")
    assert isinstance(data.get("lc_id"), str)
    assert isinstance(data.get("amendment_seq"), int) and data["amendment_seq"] >= 1
    assert isinstance(data.get("changes"), dict)
    assert data.get("applicant_consent") in CONSENT_VALUES
    assert data.get("beneficiary_consent") in CONSENT_VALUES
    assert data.get("confirming_bank_consent") in CONSENT_VALUES
    assert data.get("status") in AMENDMENT_STATUSES
    rbr = data.get("rejected_by_role", None)
    assert rbr is None or rbr in REJECTED_BY_ROLES


# ---------------------------------------------------------------------------
# Presentation (PRD §3.5)
# ---------------------------------------------------------------------------
PRESENTATION_STATUSES = {
    "SUBMITTED", "UNDER_EXAMINATION", "EXAMINED_CLEAN", "EXAMINED_DISCREPANT",
    "ACCEPTED_BY_APPLICANT", "REFUSED", "RETURNED", "SETTLED",
}


def assert_presentation(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Presentation")
    assert isinstance(data.get("lc_id"), str)
    assert isinstance(data.get("presentation_seq"), int) and data["presentation_seq"] >= 1
    assert isinstance(data.get("shipment_date"), str)
    assert isinstance(data.get("presented_at"), str)
    assert isinstance(data.get("drawing_amount_minor_units"), int)
    assert data["drawing_amount_minor_units"] > 0
    assert data.get("status") in PRESENTATION_STATUSES


# ---------------------------------------------------------------------------
# Document (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_document(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Document")
    assert isinstance(data.get("presentation_id"), str)
    assert data.get("document_type") in DOCUMENT_TYPE_VALUES, (
        f"document_type must be one of {DOCUMENT_TYPE_VALUES}; "
        f"got {data.get('document_type')!r}"
    )
    assert isinstance(data.get("issuer"), str)
    assert isinstance(data.get("document_date"), str)


# ---------------------------------------------------------------------------
# ExaminationReport (PRD §3.5, §3.6)
# ---------------------------------------------------------------------------
EXAMINATION_STATUSES = {
    "IN_PROGRESS", "PRIMARY_DONE", "CROSS_CHECK_DONE", "CONFLICT", "FINALIZED",
}
REVIEW_OUTCOMES = {"CLEAN", "DISCREPANT"}


def assert_examination_report(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "ExaminationReport")
    assert isinstance(data.get("presentation_id"), str)
    assert isinstance(data.get("primary_reviewer_id"), str)
    assert isinstance(data.get("secondary_reviewer_id"), str)
    assert data["primary_reviewer_id"] != data["secondary_reviewer_id"], (
        "PRD §3.5: 'the secondary must differ from the primary'"
    )
    assert data.get("status") in EXAMINATION_STATUSES
    primary = data.get("primary_outcome", None)
    secondary = data.get("secondary_outcome", None)
    assert primary is None or primary in REVIEW_OUTCOMES
    assert secondary is None or secondary in REVIEW_OUTCOMES
    final = data.get("final_outcome", None)
    assert final is None or final in REVIEW_OUTCOMES
    assert isinstance(data.get("deadline_at"), str)


# ---------------------------------------------------------------------------
# Discrepancy (PRD §3.6)
# ---------------------------------------------------------------------------
def assert_discrepancy(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Discrepancy")
    assert isinstance(data.get("examination_report_id"), str)
    assert data.get("discrepancy_code") in DISCREPANCY_CODE_VALUES
    assert isinstance(data.get("description"), str)
    cited = data.get("cited_document_id", None)
    assert cited is None or isinstance(cited, str)
    assert data.get("applicant_action") in {"PENDING", "ACCEPTED", "REJECTED", "TIMED_OUT"}


# ---------------------------------------------------------------------------
# PaymentSettlement (PRD §3.8)
# ---------------------------------------------------------------------------
SETTLEMENT_TYPES = {"SIGHT_PAYMENT", "USANCE_ACCEPTANCE", "NEGOTIATION"}
SETTLEMENT_STATUSES = {"PENDING", "ACCEPTED", "PAID", "COMPENSATED"}


def assert_payment_settlement(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "PaymentSettlement")
    assert isinstance(data.get("presentation_id"), str)
    assert isinstance(data.get("lc_id"), str)
    assert data.get("settlement_type") in SETTLEMENT_TYPES
    assert isinstance(data.get("principal_minor_units"), int)
    assert data["principal_minor_units"] > 0
    assert data.get("status") in SETTLEMENT_STATUSES


# ---------------------------------------------------------------------------
# ReimbursementClaim (PRD §3.9)
# ---------------------------------------------------------------------------
REIMBURSEMENT_STATUSES = {"SUBMITTED", "HONORED", "DISPUTED", "EXTINGUISHED"}


def assert_reimbursement_claim(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "ReimbursementClaim")
    assert isinstance(data.get("payment_settlement_id"), str)
    assert isinstance(data.get("claimed_amount_minor_units"), int)
    assert data["claimed_amount_minor_units"] > 0
    assert data.get("status") in REIMBURSEMENT_STATUSES
    honored = data.get("honored_amount_minor_units", 0)
    assert isinstance(honored, int) and honored >= 0


# ---------------------------------------------------------------------------
# Append-only entities (PRD §2.4)
# ---------------------------------------------------------------------------
def assert_swift_message(data: Dict[str, Any]) -> None:
    _assert_common_fields_bare(data, "SwiftMessage")
    assert data.get("message_type") in {"MT700", "MT707", "MT710"}
    assert data.get("subject_type") in {"LC", "AMENDMENT"}
    assert isinstance(data.get("subject_id"), str)
    assert isinstance(data.get("lc_id"), str)
    assert isinstance(data.get("idempotency_key"), str)
    # PRD §3.10: payload is never null.
    assert data.get("payload") is not None, (
        "SwiftMessage.payload is never null per PRD §3.10"
    )


def assert_expiry_alert(data: Dict[str, Any]) -> None:
    _assert_common_fields_bare(data, "ExpiryAlert")
    assert isinstance(data.get("lc_id"), str)
    assert data.get("alert_kind") in {
        "T_MINUS_15", "T_MINUS_5", "EXPIRED", "PRESENTATION_PERIOD_LAPSED",
    }
    assert isinstance(data.get("triggered_at"), str)


def assert_external_event(data: Dict[str, Any]) -> None:
    _assert_common_fields_bare(data, "ExternalEvent")
    assert data.get("source_system") in {"BANKING", "CUSTOMS", "LOGISTICS", "SWIFT"}
    assert data.get("event_type") in {
        "BANK_PAYMENT_CONFIRMED", "CUSTOMS_DECLARATION_FILED",
        "SHIPMENT_DEPARTED", "SHIPMENT_DELIVERED",
        "SWIFT_ACK", "SWIFT_NAK",
    }
    assert isinstance(data.get("idempotency_key"), str)


def assert_audit_log_entry(data: Dict[str, Any]) -> None:
    _assert_common_fields_bare(data, "AuditLogEntry")
    assert isinstance(data.get("action"), str)
    assert isinstance(data.get("subject_type"), str)
    assert isinstance(data.get("subject_id"), str)
    assert isinstance(data.get("lc_id"), str)


def assert_clock(data: Dict[str, Any]) -> None:
    """Clock has only id + created_at + now (PRD §2.4)."""
    assert isinstance(data.get("now"), str)
    assert is_iso8601_timestamp(data["now"])


# ---------------------------------------------------------------------------
# Helpers — collection-level lookups
# ---------------------------------------------------------------------------
def find_swift_message_of_type(
    messages: Iterable[Dict[str, Any]], message_type: str
) -> Optional[Dict[str, Any]]:
    for m in messages:
        if m.get("message_type") == message_type:
            return m
    return None


def count_alerts_of_kind(alerts: Iterable[Dict[str, Any]], alert_kind: str) -> int:
    return sum(1 for a in alerts if a.get("alert_kind") == alert_kind)


def find_audit_log_action(
    entries: Iterable[Dict[str, Any]], action: str
) -> Optional[Dict[str, Any]]:
    for e in entries:
        if e.get("action") == action:
            return e
    return None


__all__ = [
    "assert_bank",
    "assert_applicant",
    "assert_beneficiary",
    "assert_letter_of_credit",
    "assert_lc_invariants",
    "assert_lc_amendment",
    "assert_presentation",
    "assert_document",
    "assert_examination_report",
    "assert_discrepancy",
    "assert_payment_settlement",
    "assert_reimbursement_claim",
    "assert_swift_message",
    "assert_expiry_alert",
    "assert_external_event",
    "assert_audit_log_entry",
    "assert_clock",
    "find_swift_message_of_type",
    "count_alerts_of_kind",
    "find_audit_log_action",
    "LC_LIFECYCLE_STATUSES",
    "LC_AMENDMENT_CONSENT_STATUSES",
    "PRESENTATION_STATUSES",
    "EXAMINATION_STATUSES",
    "SETTLEMENT_STATUSES",
    "REIMBURSEMENT_STATUSES",
]
