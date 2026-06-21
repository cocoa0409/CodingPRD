"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_container_model_payload(**overrides) -> dict:
    """C16 defaults (PRD §3.1)."""
    defaults = {
        "size_code": "C16",
        "cubic_feet": 800,
        "monthly_rate_cents": 19900,
        "delivery_fee_cents": 8900,
        "footprint_sqft": 160,
    }
    defaults.update(overrides)
    return defaults


def create_protection_plan_payload(**overrides) -> dict:
    """NONE-tier defaults (PRD §3.1)."""
    defaults = {
        "tier_code": "NONE",
        "base_premium_cents": 0,
        "rate_bps": 0,
        "min_premium_cents": 0,
        "coverage_cap_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_depot_payload(**overrides) -> dict:
    defaults = {
        "name": "LA Depot",
        "state_code": "CA",
        "service_radius_miles": 50,
    }
    defaults.update(overrides)
    return defaults


def create_depot_inventory_payload(depot_id: str, **overrides) -> dict:
    defaults = {
        "depot_id": depot_id,
        "size_code": "C16",
        "total_units": 1,
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(depot_id: str, **overrides) -> dict:
    defaults = {
        "depot_id": depot_id,
        "name": "Crew A",
        "setup_buffer_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_truck_payload(depot_id: str, **overrides) -> dict:
    defaults = {
        "depot_id": depot_id,
        "plate": "TRK-1",
        "max_concurrent_containers": 1,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": "customer@x.com",
        "full_name": "Test Customer",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_rental_agreement_payload(customer_id: str, depot_id: str, **overrides) -> dict:
    """Required: customer_id, depot_id, size_code, site_address, site_clearance_sqft.
    Optional (with PRD defaults): protection_tier_code, declared_value_cents, proration_method.
    """
    defaults = {
        "customer_id": customer_id,
        "depot_id": depot_id,
        "size_code": "C16",
        "protection_tier_code": "NONE",
        "declared_value_cents": 0,
        "proration_method": "CALENDAR_DAY",
        "site_address": "1 A St",
        "site_clearance_sqft": 400,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_job_payload(agreement_id, crew_id, container_unit_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "crew_id": crew_id,
        "container_unit_id": container_unit_id,
        "job_kind": "INITIAL_DELIVERY",
        "window_start": "2026-07-16T09:00:00Z",
        "window_end": "2026-07-16T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_move_order_payload(agreement_id, truck_id, container_unit_id, origin_depot_id,
                              **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "truck_id": truck_id,
        "container_unit_id": container_unit_id,
        "origin_depot_id": origin_depot_id,
        "destination_state_code": "CA",
        "distance_miles": 30,
        "window_start": "2026-07-20T09:00:00Z",
        "window_end": "2026-07-20T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_access_visit_payload(agreement_id, container_unit_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "container_unit_id": container_unit_id,
        "access_kind": "ON_SITE",
        "requested_for": "2026-07-18T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_packing_supply_order_payload(agreement_id, lines=None, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "lines": lines if lines is not None else [
            {"sku": "BUBBLE", "qty": 1, "unit_price_cents": 733, "bulk_threshold": 5, "bulk_pct": 0},
        ],
        "tax_rate_bps": 825,
    }
    defaults.update(overrides)
    return defaults


def reserve_payload(expected_agreement_version: int) -> dict:
    return {"expected_agreement_version": expected_agreement_version}


def payment_payload(amount_cents: int, expected_agreement_version: int) -> dict:
    return {"amount_cents": amount_cents, "expected_agreement_version": expected_agreement_version}
