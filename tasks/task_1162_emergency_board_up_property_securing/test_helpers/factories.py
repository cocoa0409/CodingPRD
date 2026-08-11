"""Payload factories — one per creatable resource, input fields only."""

# Canonical market presets used across the suite. SEA exercises the full
# jurisdiction surface (permit + notification required); PDX is the
# no-permit/no-notification counterpart.
SEA_MARKET = {
    "name": "Seattle",
    "code": "SEA",
    "sla_minutes_p1": 120,
    "sla_minutes_p2": 480,
    "sla_minutes_p3": 1440,
    "permit_required": True,
    "notification_required": True,
    "notification_deadline_hours": 24,
    "late_notification_fee_cents": 15000,
    "board_rate_per_sheet_cents": 4500,
    "tarp_rate_per_sqft_cents": 85,
    "fence_rate_per_linear_ft_cents": 1200,
    "patrol_visit_fee_cents": 7499,
    "temp_power_daily_rate_cents": 18000,
    "temp_lighting_daily_rate_cents": 9000,
    "generator_pool_units": 2,
    "removal_flat_fee_cents": 25000,
}

PDX_MARKET = {
    "name": "Portland",
    "code": "PDX",
    "sla_minutes_p1": 120,
    "sla_minutes_p2": 480,
    "sla_minutes_p3": 1440,
    "permit_required": False,
    "notification_required": False,
    "notification_deadline_hours": 24,
    "late_notification_fee_cents": 15000,
    "board_rate_per_sheet_cents": 4000,
    "tarp_rate_per_sqft_cents": 85,
    "fence_rate_per_linear_ft_cents": 1200,
    "patrol_visit_fee_cents": 7499,
    "temp_power_daily_rate_cents": 18000,
    "temp_lighting_daily_rate_cents": 9000,
    "generator_pool_units": 2,
    "removal_flat_fee_cents": 25000,
}

TAC_MARKET = {
    "name": "Tacoma",
    "code": "TAC",
    "sla_minutes_p1": 90,
    "sla_minutes_p2": 360,
    "sla_minutes_p3": 1440,
    "permit_required": False,
    "notification_required": False,
    "notification_deadline_hours": 48,
    "late_notification_fee_cents": 9000,
    "board_rate_per_sheet_cents": 5000,
    "tarp_rate_per_sqft_cents": 90,
    "fence_rate_per_linear_ft_cents": 1100,
    "patrol_visit_fee_cents": 8000,
    "temp_power_daily_rate_cents": 19000,
    "temp_lighting_daily_rate_cents": 9500,
    "generator_pool_units": 1,
    "removal_flat_fee_cents": 22000,
}


def create_market_payload(**overrides) -> dict:
    defaults = dict(SEA_MARKET)
    defaults.update(overrides)
    return defaults


def create_pdx_market_payload(**overrides) -> dict:
    defaults = dict(PDX_MARKET)
    defaults.update(overrides)
    return defaults


def create_tac_market_payload(**overrides) -> dict:
    defaults = dict(TAC_MARKET)
    defaults.update(overrides)
    return defaults


def create_subcontractor_payload(**overrides) -> dict:
    defaults = {"legal_name": "Alpha Board"}
    defaults.update(overrides)
    return defaults


def create_coverage_payload(subcontractor_id: str, market_id: str, **overrides) -> dict:
    defaults = {
        "subcontractor_id": subcontractor_id,
        "market_id": market_id,
        "max_concurrent_jobs": 2,
        "rank": 1,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Otto Owner",
        "email": "otto@x.com",
        "kind": "OWNER",
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(customer_id: str, market_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "market_id": market_id,
        "address_line": "1 Pine St",
        "wind_zone": "LOW",
    }
    defaults.update(overrides)
    return defaults


def create_job_payload(property_id: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "incident_type": "FIRE",
        "priority": "P3",
    }
    defaults.update(overrides)
    return defaults


def board_scope_payload(opening_count=1, width_in=48, height_in=36, door_count=0, **overrides) -> dict:
    defaults = {
        "kind": "BOARD",
        "opening_count": opening_count,
        "width_in": width_in,
        "height_in": height_in,
        "door_count": door_count,
    }
    defaults.update(overrides)
    return defaults


def tarp_scope_payload(length_ft=10, width_ft=15, **overrides) -> dict:
    defaults = {
        "kind": "TARP",
        "length_ft": length_ft,
        "width_ft": width_ft,
    }
    defaults.update(overrides)
    return defaults


def fence_scope_payload(linear_ft=40, **overrides) -> dict:
    defaults = {
        "kind": "FENCE",
        "linear_ft": linear_ft,
    }
    defaults.update(overrides)
    return defaults


def create_service_payload(kind, starts_at, ends_at, **overrides) -> dict:
    defaults = {
        "kind": kind,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


def create_patrol_visit_payload(window_start, window_end, **overrides) -> dict:
    defaults = {
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults
