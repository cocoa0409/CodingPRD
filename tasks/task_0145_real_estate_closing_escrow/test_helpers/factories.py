"""Payload factories — one per entity, input fields only.

Each factory builds a payload that satisfies all PRD constraints for
the targeted endpoint by default. Tests override individual fields via
**overrides; the merged payload is returned.

PRD §2.7: every POST and state-transition requires an Idempotency-Key
HTTP header. Tests that exercise idempotent replay get a fresh key per
call via fresh_idempotency_key().
"""
from __future__ import annotations

import hashlib
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def fresh_idempotency_key() -> str:
    """Fresh idempotency key value. PRD §2.7 — POST/state-transitions
    require Idempotency-Key header; same key + same body = replay; same
    key + different body = ERR_IDEMPOTENCY_REPLAY_MISMATCH."""
    return f"idem-{uuid.uuid4().hex}"


def with_idempotency(headers: Dict[str, str],
                     key: Optional[str] = None) -> Dict[str, str]:
    """Return a copy of `headers` with an Idempotency-Key set."""
    new = dict(headers)
    new["Idempotency-Key"] = key or fresh_idempotency_key()
    return new


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_utc(dt: datetime) -> str:
    """ISO 8601 UTC instant with milliseconds — PRD §2.4."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_offset(*, days: int = 0, hours: int = 0,
               minutes: int = 0, seconds: int = 0) -> str:
    return iso_utc(
        utcnow() + timedelta(
            days=days, hours=hours, minutes=minutes, seconds=seconds,
        ),
    )


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 instant, tolerating trailing 'Z' suffix and
    optional fractional seconds.
    """
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Party — PRD §3.1
# ---------------------------------------------------------------------------
def party_payload(
    *,
    full_name: Optional[str] = None,
    party_kind: str = "BUYER",
    contact_email: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: full_name, party_kind in {BUYER, SELLER, LENDER,
    QUALIFIED_INTERMEDIARY}, contact_email."""
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Test {party_kind} {random_suffix(4)}",
        "party_kind": party_kind,
        "contact_email":
            contact_email or f"{party_kind.lower()}-{random_suffix(4)}@example.com",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Property — PRD §3.1
# ---------------------------------------------------------------------------
def property_payload(
    *,
    street_address: Optional[str] = None,
    parcel_id: Optional[str] = None,
    hoa_annual_dues: float = TEST_DEFAULTS["HOA_ANNUAL_DUES"],
    tax_annual: float = TEST_DEFAULTS["TAX_ANNUAL"],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "street_address": street_address or f"{random.randint(100, 9999)} Test St",
        "parcel_id": parcel_id or f"PCL-{random_suffix(6)}",
        "hoa_annual_dues": hoa_annual_dues,
        "tax_annual": tax_annual,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Escrow file — PRD §3.2
# ---------------------------------------------------------------------------
def escrow_file_payload(
    *,
    property_id: str,
    buyer_party_id: str,
    seller_party_id: str,
    lender_party_id: Optional[str] = None,
    qi_party_id: Optional[str] = None,
    purchase_price: float = TEST_DEFAULTS["PURCHASE_PRICE"],
    loan_amount: float = TEST_DEFAULTS["LOAN_AMOUNT"],
    closing_date_planned: str = TEST_DEFAULTS["CLOSING_DATE_PLANNED"],
    is_1031_exchange: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "property_id": property_id,
        "buyer_party_id": buyer_party_id,
        "seller_party_id": seller_party_id,
        "purchase_price": purchase_price,
        "loan_amount": loan_amount,
        "closing_date_planned": closing_date_planned,
        "is_1031_exchange": is_1031_exchange,
    }
    if lender_party_id is not None:
        payload["lender_party_id"] = lender_party_id
    if qi_party_id is not None:
        payload["qi_party_id"] = qi_party_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# EMD — PRD §3.2
# ---------------------------------------------------------------------------
def emd_payload(
    *,
    escrow_file_id: str,
    amount: float = TEST_DEFAULTS["EMD_AMOUNT"],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "escrow_file_id": escrow_file_id,
        "amount": amount,
    }
    payload.update(overrides)
    return payload


def emd_release_payload(
    *,
    reason: str = "BUYER_DEFAULT",
    split_buyer_share: Optional[float] = None,
    split_seller_share: Optional[float] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: reason ∈ {BUYER_DEFAULT, SELLER_DEFAULT, TITLE_DEFECT,
    MUTUAL_RELEASE}. MUTUAL_RELEASE requires split shares whose sum
    equals amount exactly."""
    payload: Dict[str, Any] = {"reason": reason}
    if split_buyer_share is not None:
        payload["split_buyer_share"] = split_buyer_share
    if split_seller_share is not None:
        payload["split_seller_share"] = split_seller_share
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Title search — PRD §3.3
# ---------------------------------------------------------------------------
def title_search_payload(
    *,
    escrow_file_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"escrow_file_id": escrow_file_id}
    payload.update(overrides)
    return payload


def title_search_findings_payload(
    *,
    chain_of_title_clean: bool = True,
    open_liens_total: float = 0.0,
    encumbrance_count: int = 0,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: PATCH submits findings — chain_of_title_clean,
    open_liens_total, encumbrance_count."""
    payload: Dict[str, Any] = {
        "chain_of_title_clean": chain_of_title_clean,
        "open_liens_total": open_liens_total,
        "encumbrance_count": encumbrance_count,
    }
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Title policy — PRD §3.3
# ---------------------------------------------------------------------------
def title_policy_payload(
    *,
    escrow_file_id: str,
    policy_kind: str = "OWNERS",
    insured_amount: float = TEST_DEFAULTS["INSURED_AMOUNT_OWNERS"],
    simultaneous_issue: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "escrow_file_id": escrow_file_id,
        "policy_kind": policy_kind,
        "insured_amount": insured_amount,
    }
    if simultaneous_issue is not None:
        payload["simultaneous_issue"] = simultaneous_issue
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CCR disclosure — PRD §3.4
# ---------------------------------------------------------------------------
def ccr_disclosure_payload(
    *,
    escrow_file_id: str,
    ccr_document_hash: Optional[str] = None,
    material_restrictions: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "escrow_file_id": escrow_file_id,
        "ccr_document_hash": ccr_document_hash or sha256_hex(
            f"ccr-{random_suffix(8)}",
        ),
        "material_restrictions": (
            material_restrictions
            if material_restrictions is not None
            else ["RENTAL_BAN", "ARCHITECTURAL_REVIEW"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Closing disclosure — PRD §3.5
# ---------------------------------------------------------------------------
def closing_disclosure_payload(
    *,
    escrow_file_id: str,
    total_loan_costs: float = TEST_DEFAULTS["TOTAL_LOAN_COSTS"],
    seller_credits: float = TEST_DEFAULTS["SELLER_CREDITS"],
    seller_days_owned: int = TEST_DEFAULTS["SELLER_DAYS_OWNED"],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "escrow_file_id": escrow_file_id,
        "total_loan_costs": total_loan_costs,
        "seller_credits": seller_credits,
        "seller_days_owned": seller_days_owned,
    }
    payload.update(overrides)
    return payload


def revise_cd_payload(
    *,
    triggering_change_kind: str,
    total_loan_costs: Optional[float] = None,
    seller_credits: Optional[float] = None,
    seller_days_owned: Optional[int] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "triggering_change_kind": triggering_change_kind,
    }
    if total_loan_costs is not None:
        payload["total_loan_costs"] = total_loan_costs
    if seller_credits is not None:
        payload["seller_credits"] = seller_credits
    if seller_days_owned is not None:
        payload["seller_days_owned"] = seller_days_owned
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Wire instruction — PRD §3.6
# ---------------------------------------------------------------------------
def wire_instruction_payload(
    *,
    escrow_file_id: str,
    beneficiary_kind: str,
    beneficiary_party_id: str,
    routing_number: str = TEST_DEFAULTS["ROUTING_NUMBER"],
    account_number_last4: str = TEST_DEFAULTS["ACCOUNT_LAST4"],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "escrow_file_id": escrow_file_id,
        "beneficiary_kind": beneficiary_kind,
        "beneficiary_party_id": beneficiary_party_id,
        "routing_number": routing_number,
        "account_number_last4": account_number_last4,
    }
    payload.update(overrides)
    return payload


def confirm_callback_payload(
    *,
    callback_completed: bool = True,
    callback_channel: str = "VOICE_VERIFIED",
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "callback_completed": callback_completed,
        "callback_channel": callback_channel,
    }
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Disbursement — PRD §3.7
# ---------------------------------------------------------------------------
def disbursement_payload(
    *,
    escrow_file_id: str,
    wire_instruction_id: str,
    amount: float,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "escrow_file_id": escrow_file_id,
        "wire_instruction_id": wire_instruction_id,
        "amount": amount,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# §1031 Exchange — PRD §3.8
# ---------------------------------------------------------------------------
def exchange_payload(
    *,
    escrow_file_id: str,
    relinquished_basis: float = 200000.00,
    relinquished_sale_price: float = 500000.00,
    cash_boot_received: float = 50000.00,
    mortgage_relief: float = 20000.00,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "escrow_file_id": escrow_file_id,
        "relinquished_basis": relinquished_basis,
        "relinquished_sale_price": relinquished_sale_price,
        "cash_boot_received": cash_boot_received,
        "mortgage_relief": mortgage_relief,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Version-only / cancel payloads
# ---------------------------------------------------------------------------
def version_only_payload(version: Optional[int] = None,
                         **overrides: Any) -> Dict[str, Any]:
    """Common shape for state-transition endpoints that take only
    optional `version` for OCC."""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def cancel_escrow_payload(
    *,
    cancel_reason: str = "BUYER_DEFAULT",
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.9: cancel_reason ∈ {BUYER_DEFAULT, SELLER_DEFAULT,
    TITLE_DEFECT, MUTUAL_RELEASE}."""
    payload: Dict[str, Any] = {"cancel_reason": cancel_reason}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def clock_advance_payload(to_iso: str) -> Dict[str, Any]:
    """PRD §2.10: clock-advance accepts a single body field `to` —
    an ISO 8601 UTC instant."""
    return {"to": to_iso}


__all__ = [
    "random_suffix",
    "fresh_idempotency_key",
    "with_idempotency",
    "utcnow",
    "iso_utc",
    "iso_offset",
    "parse_iso",
    "sha256_hex",
    "party_payload",
    "property_payload",
    "escrow_file_payload",
    "emd_payload",
    "emd_release_payload",
    "title_search_payload",
    "title_search_findings_payload",
    "title_policy_payload",
    "ccr_disclosure_payload",
    "closing_disclosure_payload",
    "revise_cd_payload",
    "wire_instruction_payload",
    "confirm_callback_payload",
    "disbursement_payload",
    "exchange_payload",
    "version_only_payload",
    "cancel_escrow_payload",
    "clock_advance_payload",
]
