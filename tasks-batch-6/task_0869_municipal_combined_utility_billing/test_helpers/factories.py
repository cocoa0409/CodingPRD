"""Payload factories — one per entity/operation, input fields only."""
from .constants import (
    WATER_TIERS,
    ELECTRIC_TIERS,
    WATER_FIXED_CHARGE_CENTS,
    SEWER_FIXED_CHARGE_CENTS,
    SEWER_RATE,
    SEWER_CAP_UNITS,
)

DEFAULT_EFFECTIVE_DATE = "2026-01-01T00:00:00Z"


def water_rate_schedule_payload(**overrides) -> dict:
    payload = {
        "service_type": "WATER",
        "unit": "GALLON",
        "fixed_charge_cents": WATER_FIXED_CHARGE_CENTS,
        "tiers": [dict(t) for t in WATER_TIERS],
        "effective_date": DEFAULT_EFFECTIVE_DATE,
    }
    payload.update(overrides)
    return payload


def electric_rate_schedule_payload(**overrides) -> dict:
    payload = {
        "service_type": "ELECTRIC",
        "unit": "KWH",
        "fixed_charge_cents": WATER_FIXED_CHARGE_CENTS,
        "tiers": [dict(t) for t in ELECTRIC_TIERS],
        "effective_date": DEFAULT_EFFECTIVE_DATE,
    }
    payload.update(overrides)
    return payload


def sewer_rate_schedule_payload(**overrides) -> dict:
    payload = {
        "service_type": "SEWER",
        "unit": "FLAT",
        "fixed_charge_cents": SEWER_FIXED_CHARGE_CENTS,
        "sewer_rate_cents_per_1000": SEWER_RATE,
        "sewer_cap_units": SEWER_CAP_UNITS,
        "effective_date": DEFAULT_EFFECTIVE_DATE,
    }
    payload.update(overrides)
    return payload


def account_payload(**overrides) -> dict:
    payload = {
        "account_holder_name": "Test Holder",
        "service_address": "1 Test St",
        "occupant_type": "RESIDENTIAL",
    }
    payload.update(overrides)
    return payload


def meter_payload(service_type="WATER", **overrides) -> dict:
    payload = {"service_type": service_type}
    payload.update(overrides)
    return payload


def reading_payload(reading_value, read_type="ACTUAL", read_date="2026-04-15T00:00:00Z", **overrides) -> dict:
    payload = {
        "read_date": read_date,
        "reading_value": reading_value,
        "read_type": read_type,
    }
    payload.update(overrides)
    return payload


def bill_payload(period_start, period_end, **overrides) -> dict:
    payload = {"period_start": period_start, "period_end": period_end}
    payload.update(overrides)
    return payload


def payment_payload(amount_cents, method="CASH", **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "method": method}
    payload.update(overrides)
    return payload


def budget_plan_payload(plan_year=2026, **overrides) -> dict:
    payload = {"plan_year": plan_year}
    payload.update(overrides)
    return payload


def deposit_payload(amount_cents, reason="NEW_SERVICE", **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "reason": reason}
    payload.update(overrides)
    return payload


def arrangement_payload(total_arranged_cents, installment_count, expected_account_version, **overrides) -> dict:
    payload = {
        "total_arranged_cents": total_arranged_cents,
        "installment_count": installment_count,
        "expected_account_version": expected_account_version,
    }
    payload.update(overrides)
    return payload


def adjustment_payload(adjustment_type, **overrides) -> dict:
    payload = {"adjustment_type": adjustment_type}
    payload.update(overrides)
    return payload


def shutoff_order_payload(scheduled_date, **overrides) -> dict:
    payload = {"scheduled_date": scheduled_date}
    payload.update(overrides)
    return payload


def lien_transfer_payload(tax_parcel_ref, **overrides) -> dict:
    payload = {"tax_parcel_ref": tax_parcel_ref}
    payload.update(overrides)
    return payload


def moratorium_window_payload(scope, start_date, end_date, reason="WEATHER", **overrides) -> dict:
    payload = {
        "scope": scope,
        "start_date": start_date,
        "end_date": end_date,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def assistance_payload(program, discount_pct, **overrides) -> dict:
    payload = {"program": program, "discount_pct": discount_pct}
    payload.update(overrides)
    return payload


def finalize_payload(period_start="2026-04-01T00:00:00Z", period_end="2026-05-01T00:00:00Z", **overrides) -> dict:
    payload = {"period_start": period_start, "period_end": period_end}
    payload.update(overrides)
    return payload
