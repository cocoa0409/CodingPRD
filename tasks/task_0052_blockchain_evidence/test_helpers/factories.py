"""Payload factories — one factory per input-bearing endpoint.

Each factory emits ONLY the fields PRD §3 declares as input (source: input)
for the relevant endpoint. Tests override via kwargs.

Field names mirror PRD prose exactly — no abbreviation, no guessing.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# ID / hash helpers
# ---------------------------------------------------------------------------
def unique_suffix() -> str:
    return uuid.uuid4().hex[:8]


def random_sha256_hex() -> str:
    """64-char lowercase hex digest, format-valid for SHA256 and SM3.
    PRD §2.7: 'Both SHA256 and SM3 produce 64-character lowercase hex
    strings'."""
    return uuid.uuid4().hex + uuid.uuid4().hex


def random_email(prefix: str = "user") -> str:
    return f"{prefix}-{unique_suffix()}@example.com"


def random_payment_ref(prefix: str = "pay") -> str:
    return f"{prefix}_{unique_suffix()}"


def random_case_number(prefix: str = "2026-CV") -> str:
    return f"{prefix}-{unique_suffix()}"


# ---------------------------------------------------------------------------
# Customer  POST /customers  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_customer_payload(
    *,
    email: Optional[str] = None,
    display_name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: customer payload carries email (RFC 5322; unique) and
    display_name."""
    payload: Dict[str, Any] = {
        "email": email or random_email(),
        "display_name": display_name or f"Test Customer {unique_suffix()}",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Recharge  POST /recharges  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_recharge_payload(
    *,
    customer_id: str,
    amount_cents: int = 1_000_000,
    external_payment_ref: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'the Customer opens a recharge by providing the target
    customer_id, the amount_cents (at least 100 cents and at most
    10 000 000 cents), and the external_payment_ref'."""
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "amount_cents": amount_cents,
        "external_payment_ref": (
            external_payment_ref or random_payment_ref()
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Evidence  POST /evidences  (PRD §3.2)
# ---------------------------------------------------------------------------
def create_evidence_payload(
    *,
    customer_id: str,
    evidence_type: str = "DOCUMENT",
    storage_period_days: int = 30,
    hash_algorithm: str = "SHA256",
    file_hash: Optional[str] = None,
    chain_id: str = "ETHEREUM",
    original_data_b64: Any = "__OMIT__",
    idempotency_key: Any = "__OMIT__",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'The customer chooses the evidence_type ..., the
    storage_period_days ..., the hash_algorithm (SHA256 or SM3), and
    submits the precomputed file_hash as a 64-character hex string. The
    target blockchain is selected through chain_id. The customer may
    optionally include the raw bytes through original_data_b64; when this
    field is null only the hash is retained. An optional idempotency_key
    makes the submission safe to retry on the wire.'

    Sentinel "__OMIT__" means: do not include the key in the payload.
    Pass `original_data_b64=None` to explicitly send a null value.
    """
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "evidence_type": evidence_type,
        "storage_period_days": storage_period_days,
        "hash_algorithm": hash_algorithm,
        "file_hash": file_hash or random_sha256_hex(),
        "chain_id": chain_id,
    }
    if original_data_b64 != "__OMIT__":
        payload["original_data_b64"] = original_data_b64
    if idempotency_key != "__OMIT__":
        payload["idempotency_key"] = idempotency_key
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TimestampNotarization  POST /timestamp-notarizations  (PRD §3.2)
# ---------------------------------------------------------------------------
def create_timestamp_notarization_payload(
    *,
    evidence_id: str,
    tsa_provider: str = "RFC3161_TSA_A",
    notary_office_id: Any = "__OMIT__",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'naming the evidence_id, choosing a tsa_provider from
    RFC3161_TSA_A, RFC3161_TSA_B, or NOTARY_OFFICE, and supplying a
    notary_office_id when, and only when, the provider is the notary
    office.'"""
    payload: Dict[str, Any] = {
        "evidence_id": evidence_id,
        "tsa_provider": tsa_provider,
    }
    if notary_office_id != "__OMIT__":
        payload["notary_office_id"] = notary_office_id
    elif tsa_provider == "NOTARY_OFFICE":
        payload["notary_office_id"] = f"NO-{unique_suffix()}"
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Batch  POST /batches  (PRD §3.5)
# ---------------------------------------------------------------------------
def create_batch_payload(
    *,
    customer_id: str,
    evidence_ids: List[str],
    chain_id: str = "ETHEREUM",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'the customer opens a batch by sending the customer_id,
    the target chain_id, and the ordered list of member evidence
    identifiers as evidence_ids.'"""
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "chain_id": chain_id,
        "evidence_ids": list(evidence_ids),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Certificate  POST /certificates  (PRD §3.6)
# ---------------------------------------------------------------------------
def create_certificate_payload(
    *,
    evidence_id: str,
    template_code: str = "STANDARD",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.6: 'the issuance payload carries the evidence_id and a
    template_code selecting the visual style — exactly one of STANDARD,
    PREMIUM, or JUDICIAL.'"""
    payload: Dict[str, Any] = {
        "evidence_id": evidence_id,
        "template_code": template_code,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Verification  POST /verifications  (PRD §3.8)
# ---------------------------------------------------------------------------
def create_verification_payload(
    *,
    evidence_id: str,
    file_hash: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: 'submitting the evidence_id together with a fresh
    file_hash derived from re-hashing the file under suspicion.'"""
    payload: Dict[str, Any] = {
        "evidence_id": evidence_id,
        "file_hash": file_hash or random_sha256_hex(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# JudicialPackage  POST /judicial-packages  (PRD §3.7)
# ---------------------------------------------------------------------------
def create_judicial_package_payload(
    *,
    evidence_id: str,
    case_number: Optional[str] = None,
    party_info: Optional[Dict[str, Any]] = None,
    authority_code: str = "COURT_BJ",
    include_original_data: Any = "__OMIT__",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: 'preparation payload carries the evidence_id, a
    court-assigned case_number (non-empty, at most 64 characters), a
    structured party_info JSON object with plaintiff and defendant
    records, an authority_code ..., and a boolean include_original_data
    (default false) selecting whether the evidence's original_data_b64
    payload is bundled into the issued package.'"""
    payload: Dict[str, Any] = {
        "evidence_id": evidence_id,
        "case_number": case_number or random_case_number(),
        "party_info": party_info or {
            "plaintiff": "Acme Corp",
            "defendant": "Beta LLC",
        },
        "authority_code": authority_code,
    }
    if include_original_data != "__OMIT__":
        payload["include_original_data"] = include_original_data
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Invoice  POST /invoices  (PRD §3.9)
# ---------------------------------------------------------------------------
def create_invoice_payload(
    *,
    customer_id: str,
    scope: str = "SINGLE_EVIDENCE",
    scope_ref_id: Any = "__OMIT__",
    period_start: Any = "__OMIT__",
    period_end: Any = "__OMIT__",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.9: scope is SINGLE_EVIDENCE / SINGLE_BATCH / BILLING_PERIOD;
    scope_ref_id is the target Evidence.id / Batch.id (omitted for
    BILLING_PERIOD); period_start / period_end are inclusive timestamps
    for BILLING_PERIOD only."""
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "scope": scope,
    }
    if scope_ref_id != "__OMIT__":
        payload["scope_ref_id"] = scope_ref_id
    if period_start != "__OMIT__":
        payload["period_start"] = period_start
    if period_end != "__OMIT__":
        payload["period_end"] = period_end
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-driving payloads (PRD §3.10)
# ---------------------------------------------------------------------------
def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    """PRD §3.10: 'the clock-advance capability writes the server's
    logical clock to a supplied to_iso8601 instant.'"""
    return {"to_iso8601": to_iso8601}


def chain_confirm_payload(
    *,
    tx_id: str,
    block_height: int = 1_000_000,
    confirmations: int = 12,
) -> Dict[str, Any]:
    """PRD §3.10: 'the chain-confirm capability simulates a chain
    callback, naming the affected tx_id and reporting the observed
    block_height and confirmations.'"""
    return {
        "tx_id": tx_id,
        "block_height": block_height,
        "confirmations": confirmations,
    }


def chain_fail_payload(
    *,
    tx_id: str,
    reason: str = "simulated chain failure",
) -> Dict[str, Any]:
    """PRD §3.10: 'the chain-fail capability simulates a chain rejection,
    naming the affected tx_id and a free-text reason.'"""
    return {"tx_id": tx_id, "reason": reason}


def payment_event_payload(
    *,
    external_payment_ref: str,
    status: str = "SUCCESS",
) -> Dict[str, Any]:
    """PRD §3.10 / §3.1: payment event body carries external_payment_ref
    and status (SUCCESS|FAILURE)."""
    return {
        "external_payment_ref": external_payment_ref,
        "status": status,
    }


def judicial_ack_payload(judicial_package_id: str) -> Dict[str, Any]:
    """PRD §3.10: 'the judicial acknowledgement capability drives a
    named JudicialPackage from SEALED to DELIVERED.'"""
    return {"judicial_package_id": judicial_package_id}


def notary_callback_payload(
    *,
    timestamp_notarization_id: str,
    trusted_time: str,
    tsa_token: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.10: 'the notary callback capability completes a named
    TimestampNotarization by supplying the values for trusted_time and
    tsa_token; the callback identifies the notarization to update via
    timestamp_notarization_id.'"""
    return {
        "timestamp_notarization_id": timestamp_notarization_id,
        "trusted_time": trusted_time,
        "tsa_token": tsa_token or f"tsa-token-{unique_suffix()}",
    }


__all__ = [
    "unique_suffix",
    "random_sha256_hex",
    "random_email",
    "random_payment_ref",
    "random_case_number",
    "create_customer_payload",
    "create_recharge_payload",
    "create_evidence_payload",
    "create_timestamp_notarization_payload",
    "create_batch_payload",
    "create_certificate_payload",
    "create_verification_payload",
    "create_judicial_package_payload",
    "create_invoice_payload",
    "clock_payload",
    "chain_confirm_payload",
    "chain_fail_payload",
    "payment_event_payload",
    "judicial_ack_payload",
    "notary_callback_payload",
]
