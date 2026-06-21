"""Payload factories — one per entity, input fields only.

Each factory supplies sensible defaults for the PRD's `source: input` fields and
accepts **overrides for the values a given test needs to control.
"""

_VIN_COUNTER = [0]


def unique_vin() -> str:
    """Produce a unique, valid 17-char uppercase-alphanumeric VIN.

    The PRD requires exactly 17 chars of uppercase alphanumerics. We build an
    11-char fixed prefix and append a zero-padded 6-digit counter so the full
    string is always exactly 17 chars and every counter value yields a distinct
    VIN (no truncation that would collide consecutive counters).
    """
    _VIN_COUNTER[0] += 1
    suffix = f"{_VIN_COUNTER[0]:06d}"
    prefix = "1HD1KB4197Y"  # 11 chars
    return (prefix + suffix).upper()


_EMAIL_COUNTER = [0]


def unique_email() -> str:
    _EMAIL_COUNTER[0] += 1
    return f"cust{_EMAIL_COUNTER[0]}@example.com"


_SKU_COUNTER = [0]


def unique_sku() -> str:
    _SKU_COUNTER[0] += 1
    return f"SKU-{_SKU_COUNTER[0]:05d}"


_LABEL_COUNTER = [0]


def unique_label() -> str:
    _LABEL_COUNTER[0] += 1
    return f"BAY-{_LABEL_COUNTER[0]:05d}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": unique_email(),
        "phone": "555-0100",
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(**overrides) -> dict:
    defaults = {
        "vin": unique_vin(),
        "category": "MOTORCYCLE",
        "model_year": 2024,
        "msrp_cents": 1_500_000,
        "dealer_cost_cents": 1_100_000,
        "acquisition_kind": "CASH_OWNED",
    }
    defaults.update(overrides)
    return defaults


def create_floor_plan_loan_payload(unit_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "opened_on": "2026-01-01T00:00:00.000Z",
        "apr_bps": 900,
    }
    defaults.update(overrides)
    return defaults


def create_curtailment_payload(floor_plan_loan_id, principal_cents,
                               expected_floor_plan_loan_version, **overrides) -> dict:
    defaults = {
        "floor_plan_loan_id": floor_plan_loan_id,
        "principal_cents": principal_cents,
        "reason": "SCHEDULED",
        "expected_floor_plan_loan_version": expected_floor_plan_loan_version,
    }
    defaults.update(overrides)
    return defaults


def create_trade_in_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "vin": unique_vin(),
        "category": "MOTORCYCLE",
        "appraised_value_cents": 600_000,
        "estimated_payoff_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_deal_payload(customer_id, unit_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "unit_id": unit_id,
        "sale_price_cents": 1_400_000,
        "tax_rate_bps": 800,
        "down_payment_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Technician",
        "hourly_cost_cents": 4000,
        "cleanup_buffer_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_repair_order_payload(unit_id, customer_id, technician_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "customer_id": customer_id,
        "technician_id": technician_id,
        "appointment_start": "2026-06-02T09:00:00.000Z",
        "appointment_end": "2026-06-02T12:00:00.000Z",
        "is_warranty": False,
        "authorized_amount_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_service_line_payload(repair_order_id, **overrides) -> dict:
    defaults = {
        "repair_order_id": repair_order_id,
        "operation_code": "OP-1",
        "flat_rate_hours": 2.0,
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(**overrides) -> dict:
    defaults = {
        "sku": unique_sku(),
        "description": "Test Part",
        "unit_price_cents": 4500,
        "on_hand_qty": 10,
    }
    defaults.update(overrides)
    return defaults


def create_part_line_payload(repair_order_id, part_id, quantity,
                             expected_part_version, **overrides) -> dict:
    defaults = {
        "repair_order_id": repair_order_id,
        "part_id": part_id,
        "quantity": quantity,
        "expected_part_version": expected_part_version,
    }
    defaults.update(overrides)
    return defaults


def create_storage_bay_payload(**overrides) -> dict:
    defaults = {"label": unique_label()}
    defaults.update(overrides)
    return defaults


def create_storage_agreement_payload(unit_id, customer_id, storage_bay_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "customer_id": customer_id,
        "storage_bay_id": storage_bay_id,
        "period_start": "2026-01-01T00:00:00.000Z",
        "period_end": "2026-03-01T00:00:00.000Z",
        "monthly_rate_cents": 12000,
        "includes_winterization": False,
    }
    defaults.update(overrides)
    return defaults


def create_test_ride_waiver_payload(customer_id, unit_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "unit_id": unit_id,
        "signed_at": "2026-06-01T00:00:00.000Z",
        "valid_until": "2026-06-30T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(unit_id, kind, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "kind": kind,
    }
    defaults.update(overrides)
    return defaults
