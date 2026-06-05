"""Payload factories — one per entity, input fields only.

Only `source: input` fields appear here. System and computed fields (id, status,
version, all *_cents charge components, net_weight_lbs, etc.) are never supplied.
"""


def create_account_payload(**overrides) -> dict:
    """ServiceAccount inputs: service_address, rate_class, optional diversion_floor_pct."""
    defaults = {
        "service_address": "1 Test St",
        "rate_class": "RESIDENTIAL",
    }
    defaults.update(overrides)
    return defaults


def create_cart_payload(account_id, **overrides) -> dict:
    """Cart inputs: account_id, stream, size_gallons, optional tare_weight_lbs."""
    defaults = {
        "account_id": account_id,
        "stream": "TRASH",
        "size_gallons": 65,
    }
    defaults.update(overrides)
    return defaults


def create_service_plan_payload(account_id, **overrides) -> dict:
    """ServicePlan inputs: account_id, stream, frequency, base_monthly_fee_cents."""
    defaults = {
        "account_id": account_id,
        "stream": "TRASH",
        "frequency": "WEEKLY",
        "base_monthly_fee_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    """Route inputs: service_date, stream, optional assigned_driver_id."""
    defaults = {
        "service_date": "2026-05-04T00:00:00Z",
        "stream": "TRASH",
        "assigned_driver_id": "drv-1",
    }
    defaults.update(overrides)
    return defaults


def create_stop_payload(account_id, sequence, **overrides) -> dict:
    """Stop inputs: account_id, sequence."""
    defaults = {
        "account_id": account_id,
        "sequence": sequence,
    }
    defaults.update(overrides)
    return defaults


def create_pickup_payload(cart_id, **overrides) -> dict:
    """Pickup inputs: cart_id."""
    defaults = {
        "cart_id": cart_id,
    }
    defaults.update(overrides)
    return defaults


def complete_pickup_payload(expected_cart_version, **overrides) -> dict:
    """Pickup-complete inputs: expected_cart_version (OCC token)."""
    defaults = {
        "expected_cart_version": expected_cart_version,
    }
    defaults.update(overrides)
    return defaults


def miss_pickup_payload(miss_reason, **overrides) -> dict:
    """Pickup-miss inputs: miss_reason."""
    defaults = {
        "miss_reason": miss_reason,
    }
    defaults.update(overrides)
    return defaults


def create_weight_ticket_payload(gross_weight_lbs, diverted, **overrides) -> dict:
    """WeightTicket inputs: gross_weight_lbs, diverted."""
    defaults = {
        "gross_weight_lbs": gross_weight_lbs,
        "diverted": diverted,
    }
    defaults.update(overrides)
    return defaults


def create_contamination_tag_payload(severity, **overrides) -> dict:
    """ContaminationTag inputs: severity, optional note."""
    defaults = {
        "severity": severity,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(period_start, period_end, expected_account_version, **overrides) -> dict:
    """Invoice inputs: period_start, period_end, expected_account_version (OCC token)."""
    defaults = {
        "period_start": period_start,
        "period_end": period_end,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_special_pickup_payload(kind, requested_date, **overrides) -> dict:
    """SpecialPickup inputs: kind, requested_date, optional hazard_class."""
    defaults = {
        "kind": kind,
        "requested_date": requested_date,
    }
    defaults.update(overrides)
    return defaults


def create_diversion_period_payload(period_start, period_end, **overrides) -> dict:
    """DiversionPeriod inputs: period_start, period_end."""
    defaults = {
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults
