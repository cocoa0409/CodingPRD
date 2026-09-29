"""
Request-payload builders carrying PRD-legal defaults.

Every default here is a value the specification admits, so a test overrides only
the one field it is about. Money is always an integer number of cents and points
are always integers — never strings — because §2.5 makes both integral.
"""

from typing import Any, Dict, List, Optional

from .types import (
    BENEFIT_LOUNGE_ACCESS,
    CASE_ACCOUNT_TAKEOVER,
    CATEGORY_OTHER,
    CHANNEL_STATEMENT_CREDIT,
    CHANGE_TRANSFER_RATIO_CHANGE,
    METHOD_COST_BASIS,
    PRODUCT_CORE,
    SIGNAL_DEVICE_CHANGE,
)


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the sentinel `None`, leaving omitted fields out."""
    return {key: value for key, value in payload.items() if value is not None}


# ─── The logical clock (§2.4) ─────────────────────────────────────────


def clock_payload(current_utc: str) -> Dict[str, Any]:
    """"An administrative test-driving capability accepts a `current_utc` instant"."""
    return {"current_utc": current_utc}


# ─── Accounts (§3.1) ─────────────────────────────────────────────────


def account_payload(
    cardholder_name: str = "Dana Cardholder",
    email: str = "dana@example.com",
    card_product_code: str = PRODUCT_CORE,
    enrolled_at: str = "2026-01-15T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """The four supplied fields of an enrolment: name, email, product, join instant."""
    payload = {
        "cardholder_name": cardholder_name,
        "email": email,
        "card_product_code": card_product_code,
        "enrolled_at": enrolled_at,
    }
    payload.update(overrides)
    return _prune(payload)


# ─── Merchant categories (§3.2) ──────────────────────────────────────


def merchant_category_payload(
    mcc_code: str = "5999",
    display_name: str = "General Merchandise",
    base_category: str = CATEGORY_OTHER,
    base_multiplier: float = 1.0,
    is_fallback: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A mapping row; `is_fallback` is omitted unless a test names it."""
    payload = {
        "mcc_code": mcc_code,
        "display_name": display_name,
        "base_category": base_category,
        "base_multiplier": base_multiplier,
        "is_fallback": is_fallback,
    }
    payload.update(overrides)
    return _prune(payload)


# ─── Bonus category rotations (§3.2) ─────────────────────────────────


def rotation_payload(
    merchant_category_id: str,
    rotation_code: str = "ROT-Q3",
    bonus_multiplier: float = 2.0,
    capped_spend_cents: int = 150000,
    window_start: str = "2026-09-01T00:00:00.000Z",
    window_end: str = "2026-10-01T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """A half-open rotation window on exactly one merchant category."""
    payload = {
        "merchant_category_id": merchant_category_id,
        "rotation_code": rotation_code,
        "bonus_multiplier": bonus_multiplier,
        "capped_spend_cents": capped_spend_cents,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return _prune(payload)


# ─── Purchases (§3.3, §3.4) ──────────────────────────────────────────


def transaction_payload(
    account_id: str,
    mcc_code: str = "5999",
    amount_cents: int = 10000,
    posted_at: str = "2026-08-01T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """A posted purchase: account, raw MCC, positive amount, posting instant."""
    payload = {
        "account_id": account_id,
        "mcc_code": mcc_code,
        "amount_cents": amount_cents,
        "posted_at": posted_at,
    }
    payload.update(overrides)
    return _prune(payload)


def reversal_payload(
    reversal_reason: str = "Merchant credit issued", **overrides: Any
) -> Dict[str, Any]:
    """"Reversal is a `ProgramAdmin` action taking a free-text `reversal_reason`"."""
    payload = {"reversal_reason": reversal_reason}
    payload.update(overrides)
    return _prune(payload)


# ─── Travel agency partners (§3.5) ───────────────────────────────────


def agency_payload(
    name: str = "Meridian Travel",
    contracted_markup_bps: int = 1000,
    parity_tolerance_bps: int = 500,
    invoice_terms_days: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """An onboarding payload; `invoice_terms_days` defaults to 30 when omitted."""
    payload = {
        "name": name,
        "contracted_markup_bps": contracted_markup_bps,
        "parity_tolerance_bps": parity_tolerance_bps,
        "invoice_terms_days": invoice_terms_days,
    }
    payload.update(overrides)
    return _prune(payload)


def suspend_payload(
    suspended_reason: str = "Contract breach", **overrides: Any
) -> Dict[str, Any]:
    """The reason an agency suspension records."""
    payload = {"suspended_reason": suspended_reason}
    payload.update(overrides)
    return _prune(payload)


# ─── Portal inventory offers (§3.5) ──────────────────────────────────


def offer_payload(
    agency_partner_id: str,
    itinerary_code: str = "ITIN-001",
    depart_at: str = "2026-12-01T09:00:00.000Z",
    return_at: Optional[str] = None,
    net_rate_cents: int = 40000,
    agency_public_price_cents: int = 45000,
    agency_public_seats: int = 5,
    portal_seats: int = 2,
    tax_cents: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    An itinerary published to the portal. `portal_price_cents` is deliberately
    absent: "The portal price is computed, never supplied."
    """
    payload = {
        "agency_partner_id": agency_partner_id,
        "itinerary_code": itinerary_code,
        "depart_at": depart_at,
        "return_at": return_at,
        "net_rate_cents": net_rate_cents,
        "agency_public_price_cents": agency_public_price_cents,
        "agency_public_seats": agency_public_seats,
        "portal_seats": portal_seats,
        "tax_cents": tax_cents,
    }
    payload.update(overrides)
    return _prune(payload)


def resync_payload(
    net_rate_cents: int = 40000,
    agency_public_price_cents: int = 45000,
    agency_public_seats: int = 5,
    portal_seats: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    """"a fresh snapshot of `net_rate_cents`, `agency_public_price_cents`,
    `agency_public_seats`, and `portal_seats`"."""
    payload = {
        "net_rate_cents": net_rate_cents,
        "agency_public_price_cents": agency_public_price_cents,
        "agency_public_seats": agency_public_seats,
        "portal_seats": portal_seats,
    }
    payload.update(overrides)
    return _prune(payload)


def offer_suspend_payload(
    suspension_reason: str = "Schedule change", **overrides: Any
) -> Dict[str, Any]:
    """The reason a single-offer suspension records."""
    payload = {"suspension_reason": suspension_reason}
    payload.update(overrides)
    return _prune(payload)


# ─── Redemption orders (§3.6) ────────────────────────────────────────


def book_payload(
    account_id: str,
    expected_offer_version: int,
    traveler_name: str = "Dana Cardholder",
    **overrides: Any,
) -> Dict[str, Any]:
    """"the cardholder supplies its own `account_id`, the `traveler_name` ... and
    `expected_offer_version`"."""
    payload = {
        "account_id": account_id,
        "traveler_name": traveler_name,
        "expected_offer_version": expected_offer_version,
    }
    payload.update(overrides)
    return _prune(payload)


def statement_credit_payload(
    account_id: str,
    points_requested: int = 2500,
    channel: str = CHANNEL_STATEMENT_CREDIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """"the cardholder supplies `account_id`, `channel`, and `points_requested`"."""
    payload = {
        "account_id": account_id,
        "channel": channel,
        "points_requested": points_requested,
    }
    payload.update(overrides)
    return _prune(payload)


def cancel_payload(
    closed_reason: str = "Plans changed", **overrides: Any
) -> Dict[str, Any]:
    """"The cardholder supplies a `closed_reason`"."""
    payload = {"closed_reason": closed_reason}
    payload.update(overrides)
    return _prune(payload)


def ticket_payload(ticket_number: str = "TKT-0001", **overrides: Any) -> Dict[str, Any]:
    """"The supplier posts a `ticket_number`"."""
    payload = {"ticket_number": ticket_number}
    payload.update(overrides)
    return _prune(payload)


def settle_payload(
    invoice_amount_cents: int,
    settlement_adjustment_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """"the `invoice_amount_cents` the agency billed and an optional signed
    `settlement_adjustment_cents` that defaults to 0"."""
    payload = {
        "invoice_amount_cents": invoice_amount_cents,
        "settlement_adjustment_cents": settlement_adjustment_cents,
    }
    payload.update(overrides)
    return _prune(payload)


# ─── Transfer partner agreements (§3.7) ──────────────────────────────


def agreement_payload(
    partner_name: str = "SkyMiles Alliance",
    partner_program_code: str = "SKY",
    ratio_points_out: int = 1000,
    ratio_partner_units_in: int = 1000,
    min_transfer_points: int = 1000,
    transfer_increment_points: int = 1000,
    transfer_latency_hours: int = 0,
    reversal_window_hours: int = 24,
    settlement_cost_cents_per_1k: int = 1000,
    **overrides: Any,
) -> Dict[str, Any]:
    """The seven commercial terms of a drafted agreement, plus name and code."""
    payload = {
        "partner_name": partner_name,
        "partner_program_code": partner_program_code,
        "ratio_points_out": ratio_points_out,
        "ratio_partner_units_in": ratio_partner_units_in,
        "min_transfer_points": min_transfer_points,
        "transfer_increment_points": transfer_increment_points,
        "transfer_latency_hours": transfer_latency_hours,
        "reversal_window_hours": reversal_window_hours,
        "settlement_cost_cents_per_1k": settlement_cost_cents_per_1k,
    }
    payload.update(overrides)
    return _prune(payload)


def bonus_event_payload(
    partner_agreement_id: str,
    event_code: str = "PROMO-1",
    bonus_bps: int = 2000,
    window_start: str = "2026-08-05T00:00:00.000Z",
    window_end: str = "2026-08-10T00:00:00.000Z",
    cap_points_per_account: int = 100000,
    **overrides: Any,
) -> Dict[str, Any]:
    """A promotional window, closed at both ends, on one agreement."""
    payload = {
        "partner_agreement_id": partner_agreement_id,
        "event_code": event_code,
        "bonus_bps": bonus_bps,
        "window_start": window_start,
        "window_end": window_end,
        "cap_points_per_account": cap_points_per_account,
    }
    payload.update(overrides)
    return _prune(payload)


def cancel_event_payload(
    cancelled_reason: str = "Promotion pulled", **overrides: Any
) -> Dict[str, Any]:
    """The reason a cancelled promotion records."""
    payload = {"cancelled_reason": cancelled_reason}
    payload.update(overrides)
    return _prune(payload)


# ─── Transfer requests (§3.8) ────────────────────────────────────────


def transfer_payload(
    account_id: str,
    partner_agreement_id: str,
    points_out: int,
    expected_account_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """"naming its own `account_id`, the `partner_agreement_id` ..., the
    `points_out` to burn, and `expected_account_version`"."""
    payload = {
        "account_id": account_id,
        "partner_agreement_id": partner_agreement_id,
        "points_out": points_out,
        "expected_account_version": expected_account_version,
    }
    payload.update(overrides)
    return _prune(payload)


def hold_payload(hold_reason: str = "MANUAL_REVIEW", **overrides: Any) -> Dict[str, Any]:
    """One of the three declared `hold_reason` members."""
    payload = {"hold_reason": hold_reason}
    payload.update(overrides)
    return _prune(payload)


def resolution_payload(
    resolution_reason: str = "Analyst rejected", **overrides: Any
) -> Dict[str, Any]:
    """The reason a rejection or a reversal records."""
    payload = {"resolution_reason": resolution_reason}
    payload.update(overrides)
    return _prune(payload)


# ─── Fraud cases (§3.9) ──────────────────────────────────────────────


def fraud_case_payload(
    account_id: str,
    case_type: str = CASE_ACCOUNT_TAKEOVER,
    signals: Optional[List[str]] = None,
    device_fingerprint_changed: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """An investigation with a non-empty `signals` array and a device flag."""
    payload = {
        "account_id": account_id,
        "case_type": case_type,
        "signals": [SIGNAL_DEVICE_CHANGE] if signals is None else signals,
        "device_fingerprint_changed": device_fingerprint_changed,
    }
    payload.update(overrides)
    return _prune(payload)


def resolution_note_payload(
    resolution_note: str = "Reviewed with the cardholder", **overrides: Any
) -> Dict[str, Any]:
    """"the approver supplies a `resolution_note`"."""
    payload = {"resolution_note": resolution_note}
    payload.update(overrides)
    return _prune(payload)


# ─── Benefit entitlements (§3.9) ─────────────────────────────────────


def entitlement_payload(
    account_id: str,
    benefit_type: str = BENEFIT_LOUNGE_ACCESS,
    annual_allowance: int = 2,
    expires_at: str = "2027-01-01T00:00:00.000Z",
    requires_portal_booking: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A granted benefit with an allowance and an expiry instant."""
    payload = {
        "account_id": account_id,
        "benefit_type": benefit_type,
        "annual_allowance": annual_allowance,
        "expires_at": expires_at,
        "requires_portal_booking": requires_portal_booking,
    }
    payload.update(overrides)
    return _prune(payload)


def consume_payload(
    redemption_order_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """"a cardholder action taking an optional `redemption_order_id`"."""
    payload = {"redemption_order_id": redemption_order_id}
    payload.update(overrides)
    return _prune(payload)


# ─── Programme change notices (§3.10) ────────────────────────────────


def notice_payload(
    notice_code: str = "NOTICE-1",
    change_type: str = CHANGE_TRANSFER_RATIO_CHANGE,
    effective_at: str = "2026-10-01T00:00:00.000Z",
    grandfather_window_days: int = 30,
    cohort_enrolled_before: str = "2026-06-01T00:00:00.000Z",
    target_agreement_id: Optional[str] = None,
    new_ratio_points_out: Optional[int] = None,
    new_ratio_partner_units_in: Optional[int] = None,
    supersedes_notice_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A drafted notice; the ratio triple is present only for a ratio change."""
    payload = {
        "notice_code": notice_code,
        "change_type": change_type,
        "effective_at": effective_at,
        "grandfather_window_days": grandfather_window_days,
        "cohort_enrolled_before": cohort_enrolled_before,
        "target_agreement_id": target_agreement_id,
        "new_ratio_points_out": new_ratio_points_out,
        "new_ratio_partner_units_in": new_ratio_partner_units_in,
        "supersedes_notice_id": supersedes_notice_id,
    }
    payload.update(overrides)
    return _prune(payload)


def withdraw_notice_payload(
    withdrawn_reason: str = "Superseded by negotiation", **overrides: Any
) -> Dict[str, Any]:
    """"an explicit `withdrawn_reason`"."""
    payload = {"withdrawn_reason": withdrawn_reason}
    payload.update(overrides)
    return _prune(payload)


# ─── Liability snapshots (§3.11) ─────────────────────────────────────


def snapshot_payload(
    as_of: str, method: str = METHOD_COST_BASIS, **overrides: Any
) -> Dict[str, Any]:
    """"supplying an `as_of` cut-off instant and a `method`"."""
    payload = {"as_of": as_of, "method": method}
    payload.update(overrides)
    return _prune(payload)
