"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact schema the PRD declares for the request
body. Tests pass overrides for the values they want to control.

PRD §2.4 timestamps are ISO 8601 UTC with three fractional digits
(e.g. "2025-05-24T10:30:00.123Z").

PRD §2.5 monetary fields are integer cents; PRD percentages are
basis-points (10000 = 100%).
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.4 format with three fractional digits.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_now() -> str:
    return iso_utc(utcnow())


def iso_offset(seconds: int = 0, *, days: int = 0, hours: int = 0,
               minutes: int = 0, base: Optional[datetime] = None) -> str:
    base = base or utcnow()
    return iso_utc(base + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds,
    ))


# ---------------------------------------------------------------------------
# Random suffix for uniqueness on shared-DB tests.
# ---------------------------------------------------------------------------
_ALPHA = string.ascii_lowercase + string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHA, k=n))


# ---------------------------------------------------------------------------
# Lot intake (PRD §3.1)
# ---------------------------------------------------------------------------
def create_lot_payload(**overrides: Any) -> Dict[str, Any]:
    """Build a registration payload for POST /lots.

    Per PRD §3.1 the required input fields are: court_order_no,
    asset_profile, assessment_value_cents, assessment_report_uri,
    auction_scheduled_start_at, inspection_window_start_at,
    inspection_window_end_at; encumbrances defaults to an empty list.

    Defaults pick an auction_scheduled_start_at well past the 15-day
    statutory notice horizon so announce() can succeed without a clock
    advance. The inspection window ends 1 hour before that start.
    """
    suffix = random_suffix()
    # auction starts 30 days from now (well past the 15-day notice).
    auction_start = utcnow() + timedelta(days=30)
    inspection_start = auction_start - timedelta(hours=5)
    inspection_end = auction_start - timedelta(hours=1)
    defaults: Dict[str, Any] = {
        "court_order_no": f"CO-{suffix}",
        "asset_profile": "VEHICLE",
        "assessment_value_cents": TEST_DEFAULTS["ASSESSMENT_VALUE_CENTS"],
        "assessment_report_uri": (
            f"s3://assess/{suffix}.pdf"
        ),
        "encumbrances": [],
        "auction_scheduled_start_at": iso_utc(auction_start),
        "inspection_window_start_at": iso_utc(inspection_start),
        "inspection_window_end_at": iso_utc(inspection_end),
        # PRD §3.4: the operator chooses deposit_mode and pins the
        # auction-config knobs at registration. The PRD does not
        # mandate the request path; the factory carries sensible
        # PERCENT-mode defaults so simple lots are announce-able.
        "deposit_mode": "PERCENT",
        "deposit_percent_bps": TEST_DEFAULTS["PERCENT_DEPOSIT_BPS"],
    }
    defaults.update(overrides)
    return defaults


def add_inspection_window_payload(start_at: str, end_at: str,
                                  **overrides: Any) -> Dict[str, Any]:
    """POST /lots/{id}/inspection-windows — PRD §3.1 second paragraph."""
    payload: Dict[str, Any] = {"start_at": start_at, "end_at": end_at}
    payload.update(overrides)
    return payload


def withdraw_lot_payload(reason: Optional[str] = None,
                        **overrides: Any) -> Dict[str, Any]:
    """POST /lots/{id}/withdraw — PRD §3.1."""
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Bidder account (PRD §3.2)
# ---------------------------------------------------------------------------
def create_bidder_account_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /bidder-accounts — PRD §3.2.

    Required fields per PRD §3.2: real_name, id_document_no.
    ip_fingerprint is optional.
    """
    suffix = random_suffix()
    defaults: Dict[str, Any] = {
        "real_name": f"Bidder {suffix}",
        "id_document_no": f"ID-{suffix}",
        "ip_fingerprint": f"fp-{suffix}",
    }
    defaults.update(overrides)
    return defaults


def clear_bidder_account_payload(
    investigation_resolved: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /bidder-accounts/{id}/clear — PRD §3.6."""
    payload: Dict[str, Any] = {
        "investigation_resolved": investigation_resolved,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Auction lifecycle (PRD §3.5)
# ---------------------------------------------------------------------------
def cancel_auction_payload(reason: str = "Court-ordered cancellation",
                          **overrides: Any) -> Dict[str, Any]:
    """POST /auctions/{id}/cancel — PRD §3.5."""
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


def system_rollback_payload(last_n_bids: int = 1,
                            fault_reason: str = "Network partition",
                            **overrides: Any) -> Dict[str, Any]:
    """POST /auctions/{id}/system-rollback — PRD §3.7."""
    payload: Dict[str, Any] = {
        "last_n_bids": last_n_bids,
        "fault_reason": fault_reason,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Deposit (PRD §3.4, §3.10)
# ---------------------------------------------------------------------------
def create_deposit_payload(auction_id: str, bidder_account_id: str,
                          **overrides: Any) -> Dict[str, Any]:
    """POST /deposits — PRD §3.4."""
    payload: Dict[str, Any] = {
        "auction_id": auction_id,
        "bidder_account_id": bidder_account_id,
    }
    payload.update(overrides)
    return payload


def raise_dispute_payload(
    dispute_note: Optional[str] = "Refund not received",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /deposits/{id}/raise-dispute — PRD §3.10."""
    payload: Dict[str, Any] = {}
    if dispute_note is not None:
        payload["dispute_note"] = dispute_note
    payload.update(overrides)
    return payload


def resolve_dispute_payload(
    resolution_note: Optional[str] = "Refund issued via clerk override",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /deposits/{id}/resolve-dispute — PRD §3.10."""
    payload: Dict[str, Any] = {}
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Bid (PRD §3.5)
# ---------------------------------------------------------------------------
def create_bid_payload(auction_id: str, amount_cents: int,
                      client_seq_no: int = 1,
                      **overrides: Any) -> Dict[str, Any]:
    """POST /bids — PRD §3.5."""
    payload: Dict[str, Any] = {
        "auction_id": auction_id,
        "amount_cents": amount_cents,
        "client_seq_no": client_seq_no,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Confirmation (PRD §3.8)
# ---------------------------------------------------------------------------
def create_confirmation_payload(
    auction_id: str,
    ruling_document_uri: Optional[str] = None,
    use_second_bidder: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /confirmations — PRD §3.8."""
    payload: Dict[str, Any] = {
        "auction_id": auction_id,
        "ruling_document_uri": (
            ruling_document_uri or f"s3://ruling/{random_suffix()}.pdf"
        ),
    }
    if use_second_bidder is not None:
        payload["use_second_bidder"] = use_second_bidder
    payload.update(overrides)
    return payload


def fail_confirmation_payload(
    failure_reason: str = "COURT_OVERRIDE",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /confirmations/{id}/fail — PRD §3.8."""
    payload: Dict[str, Any] = {"failure_reason": failure_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Payment (PRD §3.9)
# ---------------------------------------------------------------------------
def settle_payment_payload(amount_cents: int,
                          **overrides: Any) -> Dict[str, Any]:
    """POST /payments/{id}/settle — PRD §3.9."""
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def extend_payment_payload(extension_days: int = 7,
                          **overrides: Any) -> Dict[str, Any]:
    """POST /payments/{id}/extend — PRD §3.9."""
    payload: Dict[str, Any] = {"extension_days": extension_days}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Transfer order (PRD §3.11)
# ---------------------------------------------------------------------------
def create_transfer_order_payload(
    confirmation_id: str,
    handover_scheduled_at: str,
    transfer_instrument_uri: Optional[str] = None,
    tenancy_cleared: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /transfer-orders — PRD §3.11."""
    payload: Dict[str, Any] = {
        "confirmation_id": confirmation_id,
        "handover_scheduled_at": handover_scheduled_at,
        "transfer_instrument_uri": (
            transfer_instrument_uri
            or f"s3://transfer-instrument/{random_suffix()}.pdf"
        ),
    }
    if tenancy_cleared is not None:
        payload["tenancy_cleared"] = tenancy_cleared
    payload.update(overrides)
    return payload


def complete_handover_payload(
    tenancy_cleared: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /transfer-orders/{id}/complete-handover — PRD §3.11."""
    payload: Dict[str, Any] = {}
    if tenancy_cleared is not None:
        payload["tenancy_cleared"] = tenancy_cleared
    payload.update(overrides)
    return payload


def block_transfer_payload(
    blocked_reason: str = "Counterpart agency rejected transfer",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /transfer-orders/{id}/block — PRD §3.11."""
    payload: Dict[str, Any] = {"blocked_reason": blocked_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-driver endpoints (PRD §3.5, §3.10, §3.12)
# ---------------------------------------------------------------------------
def clock_advance_payload(to: str, **overrides: Any) -> Dict[str, Any]:
    """POST /_clock/advance — PRD §3.5 admin-only test capability."""
    payload: Dict[str, Any] = {"to": to}
    payload.update(overrides)
    return payload


def events_emit_payload(source: str, kind: str,
                       payload_data: Optional[Dict[str, Any]] = None,
                       **overrides: Any) -> Dict[str, Any]:
    """POST /_events/emit — PRD §3.12 external-event ingestion.

    The PRD spells the body field as `payload`; the Python keyword
    `payload_data` is used only inside this helper to avoid shadowing
    the function-parameter name.
    """
    payload: Dict[str, Any] = {
        "source": source,
        "kind": kind,
        "payload": payload_data or {},
    }
    payload.update(overrides)
    return payload


__all__ = [
    "iso_utc",
    "iso_now",
    "iso_offset",
    "utcnow",
    "random_suffix",
    # Lots
    "create_lot_payload",
    "add_inspection_window_payload",
    "withdraw_lot_payload",
    # Bidder accounts
    "create_bidder_account_payload",
    "clear_bidder_account_payload",
    # Auctions
    "cancel_auction_payload",
    "system_rollback_payload",
    # Deposits
    "create_deposit_payload",
    "raise_dispute_payload",
    "resolve_dispute_payload",
    # Bids
    "create_bid_payload",
    # Confirmations
    "create_confirmation_payload",
    "fail_confirmation_payload",
    # Payments
    "settle_payment_payload",
    "extend_payment_payload",
    # Transfer orders
    "create_transfer_order_payload",
    "complete_handover_payload",
    "block_transfer_payload",
    # Test driver
    "clock_advance_payload",
    "events_emit_payload",
]
