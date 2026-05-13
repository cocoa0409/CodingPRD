"""Payload factories — one per input-bearing endpoint.

Each factory emits ONLY the fields PRD declares as input (source: input).
Tests override via kwargs.

Field names mirror PRD prose exactly — no abbreviation, no guessing.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Unique-suffix helpers
# ---------------------------------------------------------------------------
def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


def unique_code(prefix: str) -> str:
    return f"{prefix}-{unique_suffix().upper()}"


def unique_email(prefix: str = "tenant") -> str:
    return f"{prefix}-{unique_suffix()}@example.com"


def unique_phone() -> str:
    return f"+1-555-{unique_suffix()[:4]}-{unique_suffix()[:4]}"


def unique_legal_name(prefix: str = "Tenant Co") -> str:
    return f"{prefix} {unique_suffix()}"


def unique_package_code(prefix: str = "PKG") -> str:
    return f"{prefix}_{unique_suffix().upper()}"


def unique_jurisdiction_code(prefix: str = "ZX") -> str:
    return f"{prefix}-{unique_suffix()[:4].upper()}"


def unique_idempotency_key(prefix: str = "idem") -> str:
    return f"{prefix}-{unique_suffix()}"


def unique_external_reference(prefix: str = "pay") -> str:
    return f"{prefix}-{unique_suffix()}"


# ---------------------------------------------------------------------------
# Tenant  POST /tenants  (PRD §3.2)
# ---------------------------------------------------------------------------
_OMIT = "__OMIT__"


def create_tenant_payload(
    *,
    legal_name: Optional[str] = None,
    contact_email: Optional[str] = None,
    contact_phone: Optional[str] = None,
    billing_entity_type: str = "INDEPENDENT",
    parent_tenant_id: Any = _OMIT,
    currency: str = "USD",
    jurisdiction_code: str = "US-CA",
    trial_expires_at: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'A PlatformAdmin creates a new tenant by supplying its
    legal_name, primary contact_email and contact_phone, a
    billing_entity_type, optionally a parent_tenant_id when the entity
    type is SUBSIDIARY, an ISO 4217 currency, the jurisdiction_code of an
    existing Jurisdiction, and optionally a trial_expires_at deadline.'
    """
    payload: Dict[str, Any] = {
        "legal_name": legal_name or unique_legal_name(),
        "contact_email": contact_email or unique_email(),
        "contact_phone": contact_phone or unique_phone(),
        "billing_entity_type": billing_entity_type,
        "currency": currency,
        "jurisdiction_code": jurisdiction_code,
    }
    if parent_tenant_id != _OMIT:
        payload["parent_tenant_id"] = parent_tenant_id
    if trial_expires_at != _OMIT:
        payload["trial_expires_at"] = trial_expires_at
    payload.update(overrides)
    return payload


def update_tenant_payload(
    *,
    legal_name: Any = _OMIT,
    contact_email: Any = _OMIT,
    contact_phone: Any = _OMIT,
    version: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: 'PATCH /tenants/{id} — Update tenant profile and contact
    fields.' PRD §2.5 supports optional version for OCC."""
    payload: Dict[str, Any] = {}
    if legal_name != _OMIT:
        payload["legal_name"] = legal_name
    if contact_email != _OMIT:
        payload["contact_email"] = contact_email
    if contact_phone != _OMIT:
        payload["contact_phone"] = contact_phone
    if version != _OMIT:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Jurisdiction  POST /jurisdictions  (PRD §3.13)
# ---------------------------------------------------------------------------
def create_jurisdiction_payload(
    *,
    jurisdiction_code: Optional[str] = None,
    tax_rate_bps: int = 0,
    rounding_mode: str = "TOTAL",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.13: 'A jurisdiction record is configuration data declaring a
    unique jurisdiction_code... a tax_rate_bps in basis points, and a
    rounding_mode of PER_LINE or TOTAL.'"""
    payload: Dict[str, Any] = {
        "jurisdiction_code": (
            jurisdiction_code or unique_jurisdiction_code()
        ),
        "tax_rate_bps": tax_rate_bps,
        "rounding_mode": rounding_mode,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Package version  POST /packages  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_package_payload(
    *,
    package_code: Optional[str] = None,
    version_number: int = 1,
    package_type: str = "TIERED",
    # Default effective_from must be in the past so the package is
    # immediately resolvable by PRD §3.1's selection rule ('the
    # PackageVersion with the largest effective_from less than or equal
    # to the request's timestamp'). 2020-01-01 is well before any test
    # clock the harness starts from.
    effective_from: str = "2020-01-01T00:00:00.000Z",
    base_price_cents: int = 3000,
    currency: str = "USD",
    billing_cycle: str = "MONTHLY",
    pricing_model: str = "PREPAID",
    included_quotas: Optional[Dict[str, int]] = None,
    tiered_brackets: Optional[List[Dict[str, Any]]] = None,
    overage_rates: Optional[Dict[str, int]] = None,
    addons: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: package version payload — package_code, version_number,
    package_type, effective_from, base_price_cents, currency,
    billing_cycle, pricing_model, included_quotas, tiered_brackets,
    overage_rates, addons."""
    payload: Dict[str, Any] = {
        "package_code": package_code or unique_package_code(),
        "version_number": version_number,
        "package_type": package_type,
        "effective_from": effective_from,
        "base_price_cents": base_price_cents,
        "currency": currency,
        "billing_cycle": billing_cycle,
        "pricing_model": pricing_model,
        "included_quotas": (
            included_quotas if included_quotas is not None else {}
        ),
        "tiered_brackets": (
            tiered_brackets if tiered_brackets is not None else []
        ),
        "overage_rates": (
            overage_rates if overage_rates is not None else {}
        ),
        "addons": addons if addons is not None else [],
    }
    payload.update(overrides)
    return payload


def make_tiered_bracket(
    *,
    metric: str = "API_CALL",
    upper_bound: Any = None,
    unit_price_cents: int = 1,
) -> Dict[str, Any]:
    """PRD §3.1: 'tiered_brackets field is an ordered list of {metric,
    upper_bound, unit_price_cents} entries... the last bracket in the
    list per metric has its upper_bound set to null to mean "no upper
    limit".'"""
    return {
        "metric": metric,
        "upper_bound": upper_bound,
        "unit_price_cents": unit_price_cents,
    }


def make_addon(*, code: str, monthly_price_cents: int) -> Dict[str, Any]:
    """PRD §3.1: 'The addons field lists optional purchases each with a
    code and a monthly_price_cents.'"""
    return {"code": code, "monthly_price_cents": monthly_price_cents}


# ---------------------------------------------------------------------------
# Subscription  POST /tenants/{tenant_id}/subscriptions (PRD §3.3)
# ---------------------------------------------------------------------------
def create_subscription_payload(
    *,
    package_code: str,
    selected_addons: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'The create payload supplies a package_code and
    optionally a selected_addons array.'"""
    payload: Dict[str, Any] = {"package_code": package_code}
    if selected_addons != _OMIT:
        payload["selected_addons"] = selected_addons
    payload.update(overrides)
    return payload


def convert_subscription_payload(
    *,
    version: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'The conversion endpoint accepts an optional version for
    OCC.'"""
    payload: Dict[str, Any] = {}
    if version != _OMIT:
        payload["version"] = version
    payload.update(overrides)
    return payload


def upgrade_subscription_payload(
    *,
    target_package_code: str,
    version: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'Both upgrade and downgrade carry an optional version
    for OCC and require a target_package_code naming the destination
    package.'"""
    payload: Dict[str, Any] = {"target_package_code": target_package_code}
    if version != _OMIT:
        payload["version"] = version
    payload.update(overrides)
    return payload


def downgrade_subscription_payload(
    *,
    target_package_code: str,
    mode: str,
    version: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'The downgrade endpoint additionally takes a mode query
    parameter whose value is either END_OF_CYCLE or IMMEDIATE_REFUND.'"""
    payload: Dict[str, Any] = {
        "target_package_code": target_package_code,
        "mode": mode,
    }
    if version != _OMIT:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Usage  POST /tenants/{tenant_id}/subscriptions/{id}/usage  (PRD §3.7)
# ---------------------------------------------------------------------------
def ingest_usage_payload(
    *,
    idempotency_key: Optional[str] = None,
    metric: str = "API_CALL",
    quantity: int = 1,
    event_timestamp: str = "2030-01-15T00:00:00.000Z",
    ingestion_mode: str = "REALTIME",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: 'Each usage submission carries a caller-supplied
    idempotency_key... a metric... a non-negative integer quantity... an
    event_timestamp in ISO 8601 UTC reflecting when the metered event
    actually occurred... and an ingestion_mode of REALTIME or BATCH.'"""
    payload: Dict[str, Any] = {
        "idempotency_key": idempotency_key or unique_idempotency_key(),
        "metric": metric,
        "quantity": quantity,
        "event_timestamp": event_timestamp,
        "ingestion_mode": ingestion_mode,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Invoice patch (discount)  PATCH /tenants/{tenant_id}/invoices/{id} (PRD §3.9)
# ---------------------------------------------------------------------------
def update_invoice_payload(
    *,
    discount_cents: Any = _OMIT,
    version: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.9: 'a PlatformAdmin or BillingOperator may apply a
    discount_cents value through a patch... The patch accepts an
    optional version for OCC.'"""
    payload: Dict[str, Any] = {}
    if discount_cents != _OMIT:
        payload["discount_cents"] = discount_cents
    if version != _OMIT:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Payment  POST /tenants/{tenant_id}/invoices/{id}/payments  (PRD §3.11)
# ---------------------------------------------------------------------------
def create_payment_payload(
    *,
    amount_cents: int,
    currency: str = "USD",
    external_reference: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.11: 'The payload carries the targeted invoice_id, a
    positive integer amount_cents... a currency that must equal the
    invoice's currency... and a caller-supplied external_reference that
    is globally unique per tenant.'

    Note: invoice_id is part of the URL path (PRD §4), not the payload.
    """
    payload: Dict[str, Any] = {
        "amount_cents": amount_cents,
        "currency": currency,
        "external_reference": (
            external_reference or unique_external_reference()
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Credit note  POST /tenants/{tenant_id}/credit-notes  (PRD §3.11)
# ---------------------------------------------------------------------------
def create_credit_note_payload(
    *,
    origin: str = "MANUAL_ADJUSTMENT",
    amount_cents: int = 1000,
    applied_to_invoice_id: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.11: 'the payload supplies origin, amount_cents (positive),
    and optionally an applied_to_invoice_id naming the invoice to consume
    the credit against.'"""
    payload: Dict[str, Any] = {
        "origin": origin,
        "amount_cents": amount_cents,
    }
    if applied_to_invoice_id != _OMIT:
        payload["applied_to_invoice_id"] = applied_to_invoice_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-harness drivers (PRD §3.14)
# ---------------------------------------------------------------------------
def clock_advance_payload(*, seconds: int, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.14: 'A clock-advance capability accepts a seconds delta in
    its body and advances the logical clock by that delta.'"""
    payload: Dict[str, Any] = {"seconds": seconds}
    payload.update(overrides)
    return payload


def archive_run_payload(*, cutoff_iso: str,
                        **overrides: Any) -> Dict[str, Any]:
    """PRD §3.14: 'An archive sweep capability accepts a cutoff_iso ISO
    8601 timestamp.'"""
    payload: Dict[str, Any] = {"cutoff_iso": cutoff_iso}
    payload.update(overrides)
    return payload


__all__ = [
    "unique_suffix", "unique_code", "unique_email", "unique_phone",
    "unique_legal_name", "unique_package_code",
    "unique_jurisdiction_code",
    "unique_idempotency_key", "unique_external_reference",
    "create_tenant_payload", "update_tenant_payload",
    "create_jurisdiction_payload",
    "create_package_payload", "make_tiered_bracket", "make_addon",
    "create_subscription_payload", "convert_subscription_payload",
    "upgrade_subscription_payload", "downgrade_subscription_payload",
    "ingest_usage_payload",
    "update_invoice_payload",
    "create_payment_payload",
    "create_credit_note_payload",
    "clock_advance_payload", "archive_run_payload",
]
