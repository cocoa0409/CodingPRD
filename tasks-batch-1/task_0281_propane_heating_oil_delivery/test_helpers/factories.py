"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the fields a client supplies; system/computed
fields are never included. Conditional/optional fields are only set when the
caller passes them via **overrides (or are present in the factory default where
the PRD names a default).
"""


def create_account_payload(**overrides) -> dict:
    """POST /accounts — customer_name, region_code, fuel_type are all required."""
    defaults = {
        "customer_name": "Test Customer",
        "region_code": "NE_01",
        "fuel_type": "PROPANE",
    }
    defaults.update(overrides)
    return defaults


def create_price_plan_payload(plan_type="FIXED", **overrides) -> dict:
    """POST /accounts/{id}/price-plans — plan_type required; locked/cap conditional."""
    payload = {"plan_type": plan_type}
    payload.update(overrides)
    return payload


def create_tank_payload(**overrides) -> dict:
    """POST /accounts/{id}/tanks — capacity_gallons, k_factor required.

    reorder_threshold_pct / delivery_mode / monitor_installed / current_gallons
    are optional with server-side defaults; only set them when overridden.
    """
    defaults = {
        "capacity_gallons": 500,
        "k_factor": 1500,
    }
    defaults.update(overrides)
    return defaults


def create_reading_payload(reading_gallons=200, read_at="2026-01-01T00:00:00Z",
                           **overrides) -> dict:
    """POST /tanks/{id}/readings — reading_gallons, read_at required."""
    payload = {"reading_gallons": reading_gallons, "read_at": read_at}
    payload.update(overrides)
    return payload


def create_degree_day_reading_payload(region_code="NE_01",
                                      reading_date="2026-01-01T00:00:00Z",
                                      heating_degree_days=50, **overrides) -> dict:
    """POST /degree-day-readings — region_code, reading_date, heating_degree_days required."""
    payload = {
        "region_code": region_code,
        "reading_date": reading_date,
        "heating_degree_days": heating_degree_days,
    }
    payload.update(overrides)
    return payload


def create_market_price_payload(region_code="NE_01", fuel_type="PROPANE",
                                market_price_cents_per_gallon=350, **overrides) -> dict:
    """POST /market-prices — region_code, fuel_type, market_price_cents_per_gallon required."""
    payload = {
        "region_code": region_code,
        "fuel_type": fuel_type,
        "market_price_cents_per_gallon": market_price_cents_per_gallon,
    }
    payload.update(overrides)
    return payload


def create_lease_payload(monthly_rent_cents=5000,
                         lease_start="2026-01-01T00:00:00Z",
                         lease_end="2026-04-01T00:00:00Z", **overrides) -> dict:
    """POST /tanks/{id}/leases — monthly_rent_cents, lease_start, lease_end required."""
    payload = {
        "monthly_rent_cents": monthly_rent_cents,
        "lease_start": lease_start,
        "lease_end": lease_end,
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(result="PASSED", inspected_at="2026-01-01T00:00:00Z",
                              **overrides) -> dict:
    """POST /tanks/{id}/inspections — result, inspected_at required; notes optional."""
    payload = {"result": result, "inspected_at": inspected_at}
    payload.update(overrides)
    return payload


def create_truck_payload(region_code="NE_01", daily_capacity_gallons=1000,
                         **overrides) -> dict:
    """POST /trucks — region_code, daily_capacity_gallons required; buffer optional."""
    payload = {
        "region_code": region_code,
        "daily_capacity_gallons": daily_capacity_gallons,
    }
    payload.update(overrides)
    return payload


def create_route_payload(route_date="2026-02-01T00:00:00Z",
                         window_start="2026-02-01T09:00:00Z",
                         window_end="2026-02-01T12:00:00Z", **overrides) -> dict:
    """POST /trucks/{id}/routes — route_date, window_start, window_end required."""
    payload = {
        "route_date": route_date,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_order_payload(tank_id, requested_gallons=200, **overrides) -> dict:
    """POST /accounts/{id}/delivery-orders — tank_id, requested_gallons required; priority optional."""
    payload = {"tank_id": tank_id, "requested_gallons": requested_gallons}
    payload.update(overrides)
    return payload


def assign_order_payload(route_id, **overrides) -> dict:
    """POST .../assign — route_id required."""
    payload = {"route_id": route_id}
    payload.update(overrides)
    return payload


def deliver_order_payload(delivered_gallons, expected_account_version, **overrides) -> dict:
    """POST .../deliver — delivered_gallons, expected_account_version required."""
    payload = {
        "delivered_gallons": delivered_gallons,
        "expected_account_version": expected_account_version,
    }
    payload.update(overrides)
    return payload


def reverse_order_payload(expected_account_version, **overrides) -> dict:
    """POST .../reverse — expected_account_version required."""
    payload = {"expected_account_version": expected_account_version}
    payload.update(overrides)
    return payload


def create_budget_plan_payload(plan_year_start="2026-01-01T00:00:00Z",
                               estimated_annual_gallons=1200,
                               estimated_price_cents_per_gallon=300, **overrides) -> dict:
    """POST /accounts/{id}/budget-plans — all three required."""
    payload = {
        "plan_year_start": plan_year_start,
        "estimated_annual_gallons": estimated_annual_gallons,
        "estimated_price_cents_per_gallon": estimated_price_cents_per_gallon,
    }
    payload.update(overrides)
    return payload
