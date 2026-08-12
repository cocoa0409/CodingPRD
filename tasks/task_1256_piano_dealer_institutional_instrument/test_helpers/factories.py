"""Payload factories — one per creatable resource, input fields only (PRD §3)."""


def create_consignor_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Consignor",
        "email": "consignor@example.com",
        "commission_pct": 0.20,
        "split_mode": "GROSS_SPLIT",
        "payout_method": "ACH",
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": "customer@example.com",
        "customer_type": "INDIVIDUAL",
    }
    defaults.update(overrides)
    return defaults


def create_instrument_payload(**overrides) -> dict:
    defaults = {
        "serial_number": "SN-DEFAULT-1",
        "category": "UPRIGHT",
        "manufacturer": "Yamaha",
        "model": "U1",
        "year_built": 2024,
        "condition_grade": "EXCELLENT",
        "acquisition_type": "NEW",
        "list_price_cents": 500_000,
        "floor_price_cents": 300_000,
    }
    defaults.update(overrides)
    return defaults


def create_appraisal_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "category": "UPRIGHT",
        "manufacturer": "Kawai",
        "model": "K300",
        "year_built": 2016,
        "condition_grade": "EXCELLENT",
    }
    defaults.update(overrides)
    return defaults


def evaluate_appraisal_payload(**overrides) -> dict:
    defaults = {
        "reconditioning_cost_cents": 0,
        "market_adjustment_pct": 0.0,
    }
    defaults.update(overrides)
    return defaults


def counter_appraisal_payload(counter_value_cents: int, **overrides) -> dict:
    defaults = {"counter_value_cents": counter_value_cents}
    defaults.update(overrides)
    return defaults


def bid_line(instrument_id: str, unit_price_cents: int) -> dict:
    return {"instrument_id": instrument_id, "unit_price_cents": unit_price_cents}


def create_bid_package_payload(customer_id: str, lines: list, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "lines": lines}
    defaults.update(overrides)
    return defaults


def bid_revision_payload(expected_bid_version: int, lines: list, **overrides) -> dict:
    defaults = {"expected_bid_version": expected_bid_version, "lines": lines}
    defaults.update(overrides)
    return defaults


def order_line(instrument_id: str, unit_price_cents: int, discount_pct: float = 0.0) -> dict:
    return {
        "instrument_id": instrument_id,
        "unit_price_cents": unit_price_cents,
        "discount_pct": discount_pct,
    }


def create_order_payload(customer_id: str, items: list, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "items": items,
        "tax_rate": 0.0,
        "distance_miles": 10,
        "stairs_count": 0,
        "climate_controlled_required": False,
    }
    defaults.update(overrides)
    return defaults


def payment_payload(amount_cents: int, method: str = "CARD") -> dict:
    return {"amount_cents": amount_cents, "method": method}


def create_delivery_crew_payload(**overrides) -> dict:
    defaults = {"crew_name": "Test Crew", "climate_certified": False}
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Technician", "certification_level": "STANDARD"}
    defaults.update(overrides)
    return defaults


def create_delivery_job_payload(order_id: str, crew_id: str, window_start: str, window_end: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "crew_id": crew_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_service_plan_payload(order_id: str, tier: str = "STANDARD", **overrides) -> dict:
    defaults = {"order_id": order_id, "tier": tier}
    defaults.update(overrides)
    return defaults


def create_service_visit_payload(plan_id: str, technician_id: str, window_start: str, window_end: str, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "technician_id": technician_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_financing_agreement_payload(order_id: str, program: str, principal_cents: int, term_months: int, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "program": program,
        "principal_cents": principal_cents,
        "term_months": term_months,
    }
    defaults.update(overrides)
    return defaults


def financing_payment_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def create_warranty_registration_payload(order_id: str, instrument_id: str, **overrides) -> dict:
    defaults = {"order_id": order_id, "instrument_id": instrument_id}
    defaults.update(overrides)
    return defaults


def create_referral_payload(instrument_id: str, **overrides) -> dict:
    defaults = {"instrument_id": instrument_id, "shop_name": "Golden Era Restorations"}
    defaults.update(overrides)
    return defaults


def assess_referral_payload(**overrides) -> dict:
    defaults = {
        "condition_score": 50,
        "estimate_low_cents": 200_000,
        "estimate_high_cents": 400_000,
    }
    defaults.update(overrides)
    return defaults


def create_showroom_event_payload(**overrides) -> dict:
    defaults = {
        "room": "MAIN_SHOWROOM",
        "title": "Artist Series",
        "start_at": "2026-06-02T18:00:00Z",
        "end_at": "2026-06-02T20:00:00Z",
        "capacity": 50,
        "artist_guarantee_cents": 200_000,
        "split_pct": 0.70,
    }
    defaults.update(overrides)
    return defaults
