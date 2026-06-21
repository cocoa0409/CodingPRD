"""Payload factories — one per entity, input fields only (PRD §3).

Each factory returns the minimal required input fields with sensible defaults
and merges **overrides last so any field can be controlled or omitted.
"""
from .constants import CANONICAL_RATE_SCHEDULE


def rate_schedule_payload(**overrides) -> dict:
    """POST /rate-schedules (PRD §3.1).

    Required: name, fixed_water_charge_cents, fixed_sewer_charge_cents,
    water_tiers, sewer_rate_cents_per_kgal. sewer_ratio_pct defaults to 100
    server-side; the remaining policy fields are optional with their own
    defaults. The canonical schedule supplies a non-default sewer_ratio_pct=90.
    """
    defaults = dict(CANONICAL_RATE_SCHEDULE)
    defaults.update(overrides)
    return defaults


def account_payload(rate_schedule_id, **overrides) -> dict:
    """POST /accounts (PRD §3.2). Required: rate_schedule_id, holder_name,
    service_address."""
    defaults = {
        "rate_schedule_id": rate_schedule_id,
        "holder_name": "Jane Holder",
        "service_address": "1 Main St",
    }
    defaults.update(overrides)
    return defaults


def meter_payload(meter_type="POTABLE", serial="P1", **overrides) -> dict:
    """POST /accounts/{id}/meters (PRD §3.2). Required: meter_type, serial."""
    defaults = {"meter_type": meter_type, "serial": serial}
    defaults.update(overrides)
    return defaults


def read_payload(reading_gallons, read_date, **overrides) -> dict:
    """POST /meters/{id}/reads (PRD §3.2). Required: reading_gallons,
    read_date. source defaults to AMI server-side."""
    defaults = {"reading_gallons": reading_gallons, "read_date": read_date}
    defaults.update(overrides)
    return defaults


def billing_cycle_payload(label, period_start, period_end, due_date, **overrides) -> dict:
    """POST /billing-cycles (PRD §3.3). Required: label, period_start,
    period_end, due_date."""
    defaults = {
        "label": label,
        "period_start": period_start,
        "period_end": period_end,
        "due_date": due_date,
    }
    defaults.update(overrides)
    return defaults


def bill_payload(account_id, billing_cycle_id, **overrides) -> dict:
    """POST /bills (PRD §3.4). Required: account_id, billing_cycle_id."""
    defaults = {"account_id": account_id, "billing_cycle_id": billing_cycle_id}
    defaults.update(overrides)
    return defaults


def budget_plan_payload(monthly_amount_cents, expected_account_version, **overrides) -> dict:
    """POST /accounts/{id}/budget-billing-plans (PRD §3.7, §2.7). Required:
    monthly_amount_cents, expected_account_version (non-optional)."""
    defaults = {
        "monthly_amount_cents": monthly_amount_cents,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def assistance_enrollment_payload(program_code="LIHWAP",
                                  certified_until="2027-01-01T00:00:00Z",
                                  **overrides) -> dict:
    """POST /accounts/{id}/assistance-enrollments (PRD §3.10). Required:
    program_code, certified_until. grants_shutoff_protection defaults to true
    server-side."""
    defaults = {"program_code": program_code, "certified_until": certified_until}
    defaults.update(overrides)
    return defaults


def leak_adjustment_payload(bill_id, baseline_gallons, repair_evidence_ref="doc://repair", **overrides) -> dict:
    """POST /leak-adjustments (PRD §3.8). Required: bill_id, baseline_gallons,
    repair_evidence_ref."""
    defaults = {
        "bill_id": bill_id,
        "baseline_gallons": baseline_gallons,
        "repair_evidence_ref": repair_evidence_ref,
    }
    defaults.update(overrides)
    return defaults


def shutoff_order_payload(account_id, triggering_bill_id, scheduled_for, **overrides) -> dict:
    """POST /shutoff-orders (PRD §3.9). Required: account_id,
    triggering_bill_id, scheduled_for."""
    defaults = {
        "account_id": account_id,
        "triggering_bill_id": triggering_bill_id,
        "scheduled_for": scheduled_for,
    }
    defaults.update(overrides)
    return defaults


def moratorium_payload(label, window_start, window_end, **overrides) -> dict:
    """POST /moratoriums (PRD §3.11). Required: label, window_start,
    window_end."""
    defaults = {"label": label, "window_start": window_start, "window_end": window_end}
    defaults.update(overrides)
    return defaults


def payment_payload(amount_cents, **overrides) -> dict:
    """POST /accounts/{id}/payments (PRD §3.6). Required: amount_cents.
    method defaults to ACH server-side."""
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
