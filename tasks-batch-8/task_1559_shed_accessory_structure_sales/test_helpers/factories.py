"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

# Reference rule book and catalog row used across tests (PRD §3.1).
JURISDICTION_DEFAULTS = {
    "name": "Marion County, IN",
    "state_code": "IN",
    "county_name": "Marion",
    "permit_threshold_sqft": 120,
    "setback_front_ft": 10,
    "setback_side_ft": 5,
    "setback_rear_ft": 5,
    "max_building_height_ft": 12,
    "anchoring_required": True,
    "permit_base_fee_cents": 15000,
    "permit_per_sqft_cents": 50,
    "tax_rate_bp": 700,
}

MODEL_DEFAULTS = {
    "name": "GardenPro",
    "sku": "GP-01",
    "min_width_ft": 8,
    "max_width_ft": 16,
    "min_depth_ft": 8,
    "max_depth_ft": 24,
    "wall_height_ft": 8,
    "supported_delivery_modes": ["PRE_BUILT", "ON_SITE_BUILD"],
    "base_price_cents": 300000,
    "overage_rate_tier1_cents": 1500,
    "overage_rate_tier2_cents": 2000,
}

CUSTOMER_DEFAULTS = {
    "full_name": "Dana Reyes",
    "email": "dana@example.com",
    "phone": "317-555-0100",
    "street": "1200 Fern Ave",
    "city": "Indianapolis",
    "state_code": "IN",
    "zip": "46201",
}

ORDER_DEFAULTS = {
    "width_ft": 10,
    "depth_ft": 12,
    "delivery_mode": "PRE_BUILT",
    "foundation_type": "GRAVEL_PAD",
    "anchor_type": "AUGER_STRAP",
    "purchase_type": "CASH",
    "options": [],
}

# A passing report: access 140 in, slope 4%, setbacks 12/6/8, no prep (PRD §3.3).
REPORT_SUITABLE_DEFAULTS = {
    "measured_access_width_in": 140,
    "measured_slope_pct": 4,
    "setback_front_ft": 12,
    "setback_side_ft": 6,
    "setback_rear_ft": 8,
    "ground_prep_needed": False,
}


def create_jurisdiction_payload(**overrides) -> dict:
    defaults = dict(JURISDICTION_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_model_payload(**overrides) -> dict:
    defaults = dict(MODEL_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = dict(CUSTOMER_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id: str, model_id: str, jurisdiction_id: str, **overrides) -> dict:
    defaults = dict(ORDER_DEFAULTS)
    defaults.update(
        {
            "customer_id": customer_id,
            "model_id": model_id,
            "jurisdiction_id": jurisdiction_id,
        }
    )
    defaults.update(overrides)
    return defaults


def create_site_check_payload(**overrides) -> dict:
    defaults = {
        "assessor_id": "asr-1",
        "scheduled_date": "2026-08-02",
        "window_start_hour": 10,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = dict(REPORT_SUITABLE_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents: int, idempotency_key: str, method: str = "CARD") -> dict:
    return {
        "amount_cents": amount_cents,
        "method": method,
        "idempotency_key": idempotency_key,
    }


def create_schedule_payload(scheduled_date: str = "2026-08-01", crew_id: str = "crew-1") -> dict:
    return {"scheduled_date": scheduled_date, "crew_id": crew_id}


def create_service_ticket_payload(order_id: str, issue_description: str = "door hinge misaligned") -> dict:
    return {"order_id": order_id, "issue_description": issue_description}
