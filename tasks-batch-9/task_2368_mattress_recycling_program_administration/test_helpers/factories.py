"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    # Program forecast that yields a 1075-cent recommended rate and an
    # [860, 1290] proposal band at an opening reserve of 5,000,000 cents.
    "FORECAST_ANNUAL_COST_CENTS": 60_000_000,
    "FORECAST_ANNUAL_UNITS": 60_000,
    "FORECAST_OTHER_REVENUE_CENTS": 3_000_000,
    "RESERVE_TARGET_MONTHS": 3,
    "RESERVE_OPENING_CENTS": 5_000_000,
    "SITE_CREDIT_CENTS_PER_UNIT": 305,
    "VOLUME_BONUS_THRESHOLD_UNITS": 500,
    "DELINQUENCY_ALERT_THRESHOLD": 1,
    "REGION_CODE": "NORTH",
    "PER_UNIT_RATE_CENTS": 450,
    "PER_KM_RATE_CENTS": 180,
    "MAX_ROUTE_PAYMENT_CENTS": 200_000,
    "MAX_CONCURRENT_ROUTES": 2,
}


def create_state_program_payload(**overrides) -> dict:
    payload = {
        "state_code": "CA",
        "program_name": "California Mattress Recycling Program",
        "forecast_annual_cost_cents": DEFAULTS["FORECAST_ANNUAL_COST_CENTS"],
        "forecast_annual_units": DEFAULTS["FORECAST_ANNUAL_UNITS"],
        "forecast_other_revenue_cents": DEFAULTS["FORECAST_OTHER_REVENUE_CENTS"],
        "reserve_target_months": DEFAULTS["RESERVE_TARGET_MONTHS"],
        "reserve_opening_cents": DEFAULTS["RESERVE_OPENING_CENTS"],
        "site_credit_cents_per_unit": DEFAULTS["SITE_CREDIT_CENTS_PER_UNIT"],
        "volume_bonus_threshold_units": DEFAULTS["VOLUME_BONUS_THRESHOLD_UNITS"],
        "delinquency_alert_threshold": DEFAULTS["DELINQUENCY_ALERT_THRESHOLD"],
    }
    payload.update(overrides)
    return payload


def ca_program_payload(**overrides) -> dict:
    """The California program used throughout the fee / remittance workflows."""
    return create_state_program_payload(
        state_code="CA",
        program_name="California Mattress Recycling Program",
        **overrides,
    )


def wa_program_payload(**overrides) -> dict:
    """The Washington program used throughout the logistics workflows."""
    return create_state_program_payload(
        state_code="WA",
        program_name="Washington Mattress Stewardship Program",
        **overrides,
    )


def create_fee_rate_schedule_payload(
    state_program_id, expected_state_program_version, **overrides
) -> dict:
    payload = {
        "state_program_id": state_program_id,
        "unit_class": "MATTRESS",
        "fee_cents_per_unit": 1100,
        "effective_from": "2026-01-01T00:00:00Z",
        "expected_state_program_version": expected_state_program_version,
    }
    payload.update(overrides)
    return payload


def create_registrant_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Pacific Bedding Retail LLC",
        "registrant_type": "RETAILER",
        "home_state_code": "CA",
    }
    payload.update(overrides)
    return payload


def create_sales_remittance_payload(registrant_id, state_program_id, **overrides) -> dict:
    payload = {
        "registrant_id": registrant_id,
        "state_program_id": state_program_id,
        "period_code": "2026Q2",
        "units_sold_mattress": 500,
        "units_sold_foundation": 0,
    }
    payload.update(overrides)
    return payload


def create_exemption_claim_payload(**overrides) -> dict:
    payload = {
        "claim_type": "OUT_OF_STATE_SHIPMENT",
        "unit_class": "MATTRESS",
        "units": 40,
        "documentation_reference": "BOL-2026-0412",
    }
    payload.update(overrides)
    return payload


def create_collection_site_payload(state_program_id, **overrides) -> dict:
    payload = {
        "state_program_id": state_program_id,
        "operator_name": "Puget Transfer Station",
        "site_type": "TRANSFER_STATION",
        "region_code": DEFAULTS["REGION_CODE"],
    }
    payload.update(overrides)
    return payload


def create_volume_report_payload(**overrides) -> dict:
    payload = {
        "period_month": "2026-08",
        "units_mattress": 320,
        "units_foundation": 190,
    }
    payload.update(overrides)
    return payload


def create_hauler_payload(state_program_id, **overrides) -> dict:
    payload = {
        "state_program_id": state_program_id,
        "company_name": "Sound Hauling Co",
        "service_regions": [DEFAULTS["REGION_CODE"]],
        "per_unit_rate_cents": DEFAULTS["PER_UNIT_RATE_CENTS"],
        "per_km_rate_cents": DEFAULTS["PER_KM_RATE_CENTS"],
        "max_route_payment_cents": DEFAULTS["MAX_ROUTE_PAYMENT_CENTS"],
        "max_concurrent_routes": DEFAULTS["MAX_CONCURRENT_ROUTES"],
    }
    payload.update(overrides)
    return payload


def create_recycler_payload(state_program_id, **overrides) -> dict:
    payload = {
        "state_program_id": state_program_id,
        "facility_name": "Cascade Fiber Recovery",
        "accepted_unit_classes": ["MATTRESS", "FOUNDATION"],
    }
    payload.update(overrides)
    return payload


def create_commodity_output_record_payload(**overrides) -> dict:
    payload = {
        "commodity": "STEEL",
        "output_weight_kg": 1200.5,
        "source_period_month": "2026-08",
    }
    payload.update(overrides)
    return payload


def create_pickup_order_payload(collection_site_id, recycler_id, **overrides) -> dict:
    payload = {
        "collection_site_id": collection_site_id,
        "recycler_id": recycler_id,
        "units_manifested": 240,
        "route_distance_km": 62.5,
        "pickup_window_start": "2026-08-05T09:00:00Z",
        "pickup_window_end": "2026-08-05T11:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_load_inspection_payload(**overrides) -> dict:
    payload = {
        "contaminated_unit_count": 12,
        "infestation_finding": "NONE",
    }
    payload.update(overrides)
    return payload


def create_take_back_delivery_payload(
    registrant_id, collection_site_id, **overrides
) -> dict:
    payload = {
        "registrant_id": registrant_id,
        "collection_site_id": collection_site_id,
        "delivery_reference": "DEL-1001",
        "units_delivered_new": 10,
        "units_takeback_offered": 10,
    }
    payload.update(overrides)
    return payload
