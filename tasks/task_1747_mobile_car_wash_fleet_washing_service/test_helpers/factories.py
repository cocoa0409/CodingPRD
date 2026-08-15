"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

from .constants import TEST_DEFAULTS

_plate_counter = itertools.count(1)
_email_counter = itertools.count(1)
_name_counter = itertools.count(1)


def _seq(counter):
    return next(counter)


def create_customer_payload(**overrides) -> dict:
    n = _seq(_email_counter)
    defaults = {
        "name": f"Customer {n}",
        "email": f"customer{n}@example.com",
        "customer_type": "RETAIL",
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(customer_id, **overrides) -> dict:
    n = _seq(_name_counter)
    defaults = {
        "customer_id": customer_id,
        "name": f"Site {n}",
        "lot_size_sqft": TEST_DEFAULTS["LOT_SIZE_SQFT"],
        "containment_type": "VACUUM_RECOVERY",
        "water_reclaim_required": False,
        "max_discharge_gal": TEST_DEFAULTS["MAX_DISCHARGE_GAL"],
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(customer_id, site_id, **overrides) -> dict:
    n = _seq(_plate_counter)
    defaults = {
        "customer_id": customer_id,
        "site_id": site_id,
        "plate": f"PLATE-{n:04d}",
        "vehicle_class": "SEDAN",
    }
    defaults.update(overrides)
    return defaults


def create_van_payload(**overrides) -> dict:
    n = _seq(_name_counter)
    defaults = {
        "name": f"VAN-{n}",
        "tank_capacity_gal": TEST_DEFAULTS["VAN_TANK_GAL"],
        "reclaim_system": "BASIC",
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    n = _seq(_name_counter)
    defaults = {
        "name": f"Tech {n}",
        "water_reclaim_certified": False,
    }
    defaults.update(overrides)
    return defaults


def create_fleet_contract_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "monthly_minimum_cents": TEST_DEFAULTS["MONTHLY_MINIMUM_CENTS"],
        "sedan_rate_cents": 3000,
        "suv_pickup_rate_cents": 4000,
        "van_boxtruck_rate_cents": 6000,
        "heavy_fleet_rate_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(customer_id, vehicle_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "cadence": "MONTHLY",
        "next_service_date": "2026-08-20",
    }
    defaults.update(overrides)
    return defaults


def create_wash_order_payload(customer_id, site_id, vehicle_ids, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "site_id": site_id,
        "vehicle_ids": vehicle_ids,
        "scheduled_window_start": "2026-08-05T13:00:00Z",
        "scheduled_window_end": "2026-08-05T14:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(route_date, van_id, lead_technician_id, **overrides) -> dict:
    defaults = {
        "route_date": route_date,
        "van_id": van_id,
        "lead_technician_id": lead_technician_id,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_report_payload(wash_order_id, **overrides) -> dict:
    defaults = {
        "wash_order_id": wash_order_id,
        "areas": [
            {"area": "EXTERIOR_BODY", "pre_existing_damage": False, "notes": "no visible damage"},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_damage_claim_payload(wash_order_id, **overrides) -> dict:
    defaults = {
        "wash_order_id": wash_order_id,
        "area": "EXTERIOR_BODY",
        "claimed_amount_cents": 10000,
        "description": "damage observed after wash",
    }
    defaults.update(overrides)
    return defaults


def create_quality_audit_payload(wash_order_id, **overrides) -> dict:
    defaults = {
        "wash_order_id": wash_order_id,
        "exterior_score": 20,
        "wheels_score": 20,
        "glass_score": 20,
        "trim_score": 20,
        "water_spotting_score": 20,
    }
    defaults.update(overrides)
    return defaults


def create_compliance_incident_payload(site_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "incident_type": "SPILL",
        "notes": "incident observed on site",
    }
    defaults.update(overrides)
    return defaults


def generate_invoice_payload(fleet_contract_id, period_month, variant, **overrides) -> dict:
    defaults = {
        "fleet_contract_id": fleet_contract_id,
        "period_month": period_month,
        "variant": variant,
    }
    defaults.update(overrides)
    return defaults


def weather_evaluation_payload(evaluation_date, forecast_low_f, precip_probability_pct) -> dict:
    return {
        "evaluation_date": evaluation_date,
        "forecast_low_f": forecast_low_f,
        "precip_probability_pct": precip_probability_pct,
    }
