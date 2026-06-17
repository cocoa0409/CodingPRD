"""Payload factories — one per entity, input fields only (PRD-exact names)."""


def create_dealership_payload(**overrides) -> dict:
    """Required: name, state_code, doc_fee_cents, sales_tax_rate_bps."""
    payload = {
        "name": "Test RV",
        "state_code": "TX",
        "doc_fee_cents": 0,
        "sales_tax_rate_bps": 0,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(dealership_id, **overrides) -> dict:
    """Required: dealership_id, full_name, email. Optional: credit_tier (default STANDARD)."""
    payload = {
        "dealership_id": dealership_id,
        "full_name": "Test Customer",
        "email": "customer@x.com",
    }
    payload.update(overrides)
    return payload


def create_unit_payload(dealership_id, **overrides) -> dict:
    """Required: dealership_id, vin, model_year, class_type, list_price_cents.
    Optional: acquisition (default STOCK), consignor_customer_id,
    consignment_floor_cents, consignment_fee_bps."""
    payload = {
        "dealership_id": dealership_id,
        "vin": "VIN-TEST-1",
        "model_year": 2024,
        "class_type": "CLASS_C",
        "acquisition": "STOCK",
        "list_price_cents": 7000000,
    }
    payload.update(overrides)
    return payload


def create_deal_payload(dealership_id, unit_id, customer_id, sale_price_cents,
                        expected_unit_version, **overrides) -> dict:
    """Required: dealership_id, unit_id, customer_id, sale_price_cents,
    expected_unit_version. Optional: down_payment_cents (default 0), term_months."""
    payload = {
        "dealership_id": dealership_id,
        "unit_id": unit_id,
        "customer_id": customer_id,
        "sale_price_cents": sale_price_cents,
        "expected_unit_version": expected_unit_version,
    }
    payload.update(overrides)
    return payload


def appraise_trade_payload(**overrides) -> dict:
    """Required: vin, model_year, class_type, list_price_cents, trade_allowance_cents.
    Optional: trade_payoff_cents, trade_recon_cost_cents."""
    payload = {
        "vin": "VIN-TRADE-1",
        "model_year": 2018,
        "class_type": "TRAVEL_TRAILER",
        "list_price_cents": 2000000,
        "trade_allowance_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_pdi_inspection_payload(dealership_id, deal_id, defects_found, **overrides) -> dict:
    """Required: dealership_id, deal_id, defects_found."""
    payload = {
        "dealership_id": dealership_id,
        "deal_id": deal_id,
        "defects_found": defects_found,
    }
    payload.update(overrides)
    return payload


def create_service_bay_payload(dealership_id, **overrides) -> dict:
    """Required: dealership_id, name, bay_kind. Optional: cleanup_buffer_minutes (default 0)."""
    payload = {
        "dealership_id": dealership_id,
        "name": "Bay-1",
        "bay_kind": "REPAIR",
    }
    payload.update(overrides)
    return payload


def create_service_order_payload(dealership_id, unit_id, customer_id, **overrides) -> dict:
    """Required: dealership_id, unit_id, customer_id, labor_hours, labor_rate_cents.
    Optional: is_warranty (default false), warranty_plan_id."""
    payload = {
        "dealership_id": dealership_id,
        "unit_id": unit_id,
        "customer_id": customer_id,
        "labor_hours": 1.0,
        "labor_rate_cents": 10000,
    }
    payload.update(overrides)
    return payload


def create_part_item_payload(dealership_id, **overrides) -> dict:
    """Required: dealership_id, sku, name, unit_price_cents, qty_on_hand."""
    payload = {
        "dealership_id": dealership_id,
        "sku": "PART-1",
        "name": "Test Part",
        "unit_price_cents": 10000,
        "qty_on_hand": 10,
    }
    payload.update(overrides)
    return payload


def create_part_reservation_payload(service_order_id, part_item_id, quantity, **overrides) -> dict:
    """Required: service_order_id, part_item_id, quantity."""
    payload = {
        "service_order_id": service_order_id,
        "part_item_id": part_item_id,
        "quantity": quantity,
    }
    payload.update(overrides)
    return payload


def create_warranty_plan_payload(dealership_id, unit_id, customer_id, **overrides) -> dict:
    """Required: dealership_id, unit_id, customer_id, plan_kind, coverage_cap_cents.
    Optional: deductible_cents (default 0)."""
    payload = {
        "dealership_id": dealership_id,
        "unit_id": unit_id,
        "customer_id": customer_id,
        "plan_kind": "EXTENDED",
        "coverage_cap_cents": 300000,
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(dealership_id, service_bay_id, appt_kind,
                               start_utc, end_utc, **overrides) -> dict:
    """Required: dealership_id, service_bay_id, appt_kind, start_utc, end_utc.
    Optional: service_order_id (REPAIR), deal_id (PDI)."""
    payload = {
        "dealership_id": dealership_id,
        "service_bay_id": service_bay_id,
        "appt_kind": appt_kind,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    payload.update(overrides)
    return payload


def create_storage_slot_payload(dealership_id, unit_id, customer_id,
                                start_utc, end_utc, expected_unit_version, **overrides) -> dict:
    """Required: dealership_id, unit_id, customer_id, daily_rate_cents,
    start_utc, end_utc, expected_unit_version. Optional: winterized (default false)."""
    payload = {
        "dealership_id": dealership_id,
        "unit_id": unit_id,
        "customer_id": customer_id,
        "daily_rate_cents": 5000,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "expected_unit_version": expected_unit_version,
    }
    payload.update(overrides)
    return payload


def create_recall_campaign_payload(dealership_id, **overrides) -> dict:
    """Required: dealership_id, campaign_code, target_class_type, target_model_year, severity."""
    payload = {
        "dealership_id": dealership_id,
        "campaign_code": "RC-1",
        "target_class_type": "CLASS_C",
        "target_model_year": 2024,
        "severity": "ADVISORY",
    }
    payload.update(overrides)
    return payload
