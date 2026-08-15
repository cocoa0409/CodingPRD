"""Payload factories — one per entity, input fields only (PRD §3)."""
import uuid


def _uniq(prefix: str) -> str:
    """Unique token so multiple entities within one test never collide."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def create_producer_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Producer"),
        "license_number": _uniq("LIC"),
    }
    defaults.update(overrides)
    return defaults


def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Carrier"),
        "carrier_code": _uniq("CR"),
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(carrier_id: str, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "product_code": _uniq("PRD"),
        "name": _uniq("Product"),
        "line_of_business": "LIFE",
    }
    defaults.update(overrides)
    return defaults


def create_schedule_payload(
    *,
    tier: str = "STANDARD",
    commission_rate_bps: int = 5000,
    override_rate_bps: int = 0,
    advance_months: int = 12,
    effective_from: str = "2026-01-01",
    effective_to=None,
    supersede_existing=None,
    expected_product_version: int,
) -> dict:
    payload = {
        "tier": tier,
        "commission_rate_bps": commission_rate_bps,
        "override_rate_bps": override_rate_bps,
        "advance_months": advance_months,
        "effective_from": effective_from,
        "expected_product_version": expected_product_version,
    }
    if effective_to is not None:
        payload["effective_to"] = effective_to
    if supersede_existing is not None:
        payload["supersede_existing"] = supersede_existing
    return payload


def create_policy_payload(
    product_id: str,
    producer_id: str,
    *,
    policy_number=None,
    insured_name: str = "Test Insured",
    billing_type: str = "DIRECT_BILL",
    premium_annual_cents: int = 2400000,
    effective_date: str = "2026-08-01",
    **overrides,
) -> dict:
    defaults = {
        "policy_number": policy_number or _uniq("POL"),
        "product_id": product_id,
        "producer_id": producer_id,
        "insured_name": insured_name,
        "billing_type": billing_type,
        "premium_annual_cents": premium_annual_cents,
        "effective_date": effective_date,
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(
    carrier_id: str,
    lines: list,
    *,
    period_start: str = "2026-08-01",
    period_end: str = "2026-08-31",
    **overrides,
) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "period_start": period_start,
        "period_end": period_end,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults
