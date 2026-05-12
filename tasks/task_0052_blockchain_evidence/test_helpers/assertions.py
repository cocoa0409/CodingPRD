"""Per-entity assertions for the Blockchain Evidence Preservation API.

PRD §2.4 splits entities into two field-shapes:
- Versioned (id + created_at + updated_at + version):
  Customer, Evidence, OnChainTx, Batch, Certificate, JudicialPackage,
  Invoice.
- Append-only (id + created_at only; no updated_at, no version):
  FeeAccount, TimestampNotarization, VerificationReport, Recharge,
  AuditLog.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Shared shape checkers
# ---------------------------------------------------------------------------
def _check_versioned_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4 versioned shape: id, created_at, updated_at, version."""
    assert "id" in data, f"{entity} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity}.id must be UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(
        data["created_at"]
    ), f"{entity}.created_at must be ISO 8601 UTC"
    assert "updated_at" in data and is_iso8601_timestamp(
        data["updated_at"]
    ), f"{entity}.updated_at must be ISO 8601 UTC"
    assert "version" in data, f"{entity} missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"{entity}.version must be >= 1, got {data.get('version')!r}"
    )


def _check_append_only_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4 append-only shape: id + created_at ONLY."""
    assert "id" in data, f"{entity} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity}.id must be UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(
        data["created_at"]
    ), f"{entity}.created_at must be ISO 8601 UTC"


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------
CUSTOMER_STATES = {"ACTIVE", "SUSPENDED"}


def assert_customer(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Customer")
    assert isinstance(data.get("email"), str)
    assert isinstance(data.get("display_name"), str)
    assert isinstance(data.get("wallet_balance_cents"), int)
    # PRD §2.7: 'wallet_balance_cents is a non-negative integer'.
    assert data["wallet_balance_cents"] >= 0, (
        f"wallet_balance_cents must be >= 0, got "
        f"{data['wallet_balance_cents']}"
    )
    assert data.get("status") in CUSTOMER_STATES, (
        f"Customer.status must be ACTIVE or SUSPENDED, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------
EVIDENCE_STATES = {
    "PENDING", "SUBMITTING", "CONFIRMED", "FAILED", "EXPIRED",
}
EVIDENCE_TYPES = {
    "DOCUMENT", "IMAGE", "VIDEO", "CODE_REPOSITORY", "DATASET",
}
CHAIN_IDS = {"ETHEREUM", "FABRIC", "BSN", "COSMOS"}
HASH_ALGOS = {"SHA256", "SM3"}
STORAGE_PERIODS = {30, 90, 365, 1095}


def assert_evidence(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Evidence")
    assert is_valid_uuid(data.get("customer_id", "")), (
        f"Evidence.customer_id must be UUID, got {data.get('customer_id')!r}"
    )
    assert data.get("evidence_type") in EVIDENCE_TYPES
    assert data.get("storage_period_days") in STORAGE_PERIODS
    assert data.get("hash_algorithm") in HASH_ALGOS
    fh = data.get("file_hash", "")
    assert isinstance(fh, str) and len(fh) == 64, (
        f"Evidence.file_hash must be 64 chars, got len={len(fh)}"
    )
    # PRD §2.7: 'both SHA256 and SM3 produce 64-character lowercase hex
    # strings'.
    assert all(c in "0123456789abcdef" for c in fh), (
        f"Evidence.file_hash must be lowercase hex, got {fh!r}"
    )
    assert data.get("chain_id") in CHAIN_IDS
    assert data.get("status") in EVIDENCE_STATES
    assert isinstance(data.get("submission_attempts"), int)
    assert data["submission_attempts"] >= 0
    # per_evidence_fee_cents, batch_id, confirmed_at, expires_at,
    # idempotency_key, original_data_b64 may be null.


# ---------------------------------------------------------------------------
# OnChainTx
# ---------------------------------------------------------------------------
ONCHAIN_TX_STATES = {"SUBMITTED", "CONFIRMED", "FAILED"}


def assert_onchain_tx(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "OnChainTx")
    # PRD §3.3 / §3.5: evidence_id and batch_id are mutually exclusive
    # — at least one is set, but not both.
    has_ev = bool(data.get("evidence_id"))
    has_b = bool(data.get("batch_id"))
    assert has_ev ^ has_b, (
        f"OnChainTx must anchor exactly one of evidence_id or batch_id, "
        f"got evidence_id={data.get('evidence_id')!r}, "
        f"batch_id={data.get('batch_id')!r}"
    )
    assert data.get("chain_id") in CHAIN_IDS
    ah = data.get("anchored_hash", "")
    assert isinstance(ah, str) and len(ah) == 64, (
        f"OnChainTx.anchored_hash must be 64 hex chars, got len={len(ah)}"
    )
    assert data.get("status") in ONCHAIN_TX_STATES
    assert isinstance(data.get("attempt_index"), int)
    assert data["attempt_index"] >= 1, (
        f"OnChainTx.attempt_index must be >= 1, got {data['attempt_index']}"
    )
    assert isinstance(data.get("confirmations", 0), int)


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------
BATCH_STATES = {"PENDING", "SUBMITTING", "CONFIRMED", "FAILED"}


def assert_batch(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Batch")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data.get("chain_id") in CHAIN_IDS
    ec = data.get("evidence_count")
    assert isinstance(ec, int) and 2 <= ec <= 1000, (
        f"Batch.evidence_count must be in [2,1000], got {ec}"
    )
    mr = data.get("merkle_root", "")
    assert isinstance(mr, str) and len(mr) == 64, (
        f"Batch.merkle_root must be 64 hex chars, got len={len(mr)}"
    )
    assert data.get("status") in BATCH_STATES
    assert isinstance(data.get("submission_attempts"), int)


# ---------------------------------------------------------------------------
# Certificate
# ---------------------------------------------------------------------------
CERTIFICATE_STATES = {"ISSUED", "REVOKED"}
TEMPLATE_CODES = {"STANDARD", "PREMIUM", "JUDICIAL"}


def assert_certificate(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Certificate")
    assert is_valid_uuid(data.get("evidence_id", ""))
    assert data.get("template_code") in TEMPLATE_CODES
    vc = data.get("verification_code", "")
    # PRD §3.6: '12-character uppercase alphanumeric handle, globally
    # unique'.
    assert isinstance(vc, str) and len(vc) == 12, (
        f"Certificate.verification_code must be 12 chars, "
        f"got len={len(vc)} ({vc!r})"
    )
    assert vc.isalnum() and vc.upper() == vc, (
        f"Certificate.verification_code must be uppercase alphanumeric, "
        f"got {vc!r}"
    )
    assert is_iso8601_timestamp(data.get("embedded_timestamp", "")), (
        f"Certificate.embedded_timestamp must be ISO 8601"
    )
    hs = data.get("hash_snapshot", "")
    assert isinstance(hs, str) and len(hs) == 64
    assert data.get("chain_id") in CHAIN_IDS
    assert data.get("status") in CERTIFICATE_STATES


# ---------------------------------------------------------------------------
# JudicialPackage
# ---------------------------------------------------------------------------
JUDICIAL_PACKAGE_STATES = {"DRAFT", "SEALED", "DELIVERED", "REJECTED"}
AUTHORITY_CODES = {
    "COURT_BJ", "COURT_SH", "COURT_GZ", "COURT_SZ",
    "PROCURATORATE", "ARBITRATION",
}


def assert_judicial_package(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "JudicialPackage")
    assert is_valid_uuid(data.get("evidence_id", ""))
    cn = data.get("case_number", "")
    assert isinstance(cn, str) and 1 <= len(cn) <= 64, (
        f"JudicialPackage.case_number must be 1..64 chars, got len={len(cn)}"
    )
    assert isinstance(data.get("party_info"), dict)
    assert data.get("authority_code") in AUTHORITY_CODES
    assert isinstance(data.get("include_original_data"), bool)
    assert data.get("status") in JUDICIAL_PACKAGE_STATES


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------
INVOICE_STATES = {"ISSUED", "VOIDED"}
INVOICE_SCOPES = {"SINGLE_EVIDENCE", "SINGLE_BATCH", "BILLING_PERIOD"}


def assert_invoice(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Invoice")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data.get("scope") in INVOICE_SCOPES
    assert isinstance(data.get("total_cents"), int)
    assert data["total_cents"] >= 0
    assert data.get("status") in INVOICE_STATES


# ---------------------------------------------------------------------------
# Append-only entities
# ---------------------------------------------------------------------------
RECHARGE_STATES = {"PENDING", "COMPLETED", "FAILED"}
TSA_PROVIDERS = {"RFC3161_TSA_A", "RFC3161_TSA_B", "NOTARY_OFFICE"}
VERIFICATION_OUTCOMES = {
    "VERIFIED", "TAMPERED", "EXPIRED", "REVOKED", "UNAVAILABLE",
}


def assert_recharge(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "Recharge")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] >= 100
    assert isinstance(data.get("external_payment_ref"), str)
    assert data.get("status") in RECHARGE_STATES


def assert_fee_account(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "FeeAccount")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data.get("lifetime_recharge_cents"), int)
    assert isinstance(data.get("lifetime_deduction_cents"), int)
    assert data["lifetime_recharge_cents"] >= 0
    assert data["lifetime_deduction_cents"] >= 0


def assert_timestamp_notarization(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "TimestampNotarization")
    assert is_valid_uuid(data.get("evidence_id", ""))
    assert data.get("tsa_provider") in TSA_PROVIDERS


def assert_verification_report(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "VerificationReport")
    assert is_valid_uuid(data.get("evidence_id", ""))
    assert isinstance(data.get("recomputed_hash"), str)
    assert isinstance(data.get("on_chain_hash"), str) or (
        data.get("on_chain_hash") is None
    )
    assert isinstance(data.get("certificate_valid"), bool)
    assert isinstance(data.get("tamper_detected"), bool)
    assert data.get("outcome") in VERIFICATION_OUTCOMES


def assert_audit_log(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "AuditLog")
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("event_type"), str)
    assert isinstance(data.get("target_entity"), str)
    assert isinstance(data.get("target_id"), str)


# ---------------------------------------------------------------------------
# Search helpers for audit-log assertions
# ---------------------------------------------------------------------------
def find_audit_logs(
    rows: Iterable[Dict[str, Any]],
    *,
    event_type: Optional[str] = None,
    target_entity: Optional[str] = None,
    target_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        if event_type and r.get("event_type") != event_type:
            continue
        if target_entity and r.get("target_entity") != target_entity:
            continue
        if target_id and r.get("target_id") != target_id:
            continue
        out.append(r)
    return out


__all__ = [
    "assert_customer",
    "assert_evidence",
    "assert_onchain_tx",
    "assert_batch",
    "assert_certificate",
    "assert_judicial_package",
    "assert_invoice",
    "assert_recharge",
    "assert_fee_account",
    "assert_timestamp_notarization",
    "assert_verification_report",
    "assert_audit_log",
    "find_audit_logs",
    "CUSTOMER_STATES",
    "EVIDENCE_STATES",
    "ONCHAIN_TX_STATES",
    "BATCH_STATES",
    "CERTIFICATE_STATES",
    "JUDICIAL_PACKAGE_STATES",
    "INVOICE_STATES",
    "INVOICE_SCOPES",
    "RECHARGE_STATES",
    "TSA_PROVIDERS",
    "VERIFICATION_OUTCOMES",
    "EVIDENCE_TYPES",
    "CHAIN_IDS",
    "HASH_ALGOS",
    "STORAGE_PERIODS",
    "TEMPLATE_CODES",
    "AUTHORITY_CODES",
]
