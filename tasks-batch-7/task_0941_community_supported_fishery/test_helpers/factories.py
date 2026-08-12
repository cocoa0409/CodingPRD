"""Payload factories — one per creatable resource, input fields only."""

from .constants import TEST_DEFAULTS


def create_season_payload(**overrides) -> dict:
    payload = {
        "season_code": TEST_DEFAULTS["SEASON_CODE"],
        "start_date": TEST_DEFAULTS["SEASON_START"],
        "end_date": TEST_DEFAULTS["SEASON_END"],
        "total_weeks": TEST_DEFAULTS["TOTAL_WEEKS"],
        "ambient_band": TEST_DEFAULTS["AMBIENT_BAND"],
        "offered_species": ["SALMON"],
        "landing_commit_lead_hours": TEST_DEFAULTS["LANDING_COMMIT_LEAD_HOURS"],
    }
    payload.update(overrides)
    return payload


def create_share_plan_payload(season_id: str, **overrides) -> dict:
    payload = {
        "season_id": season_id,
        "plan_code": "MED-PREM-W",
        "share_size": "MEDIUM",
        "delivery_frequency": "WEEKLY",
        "species_tier": "PREMIUM_FINFISH",
    }
    payload.update(overrides)
    return payload


def create_delivery_zone_payload(**overrides) -> dict:
    payload = {
        "zone_code": "ZONE-1",
        "fee_tier": "TIER_1",
        "transit_hours": 6.0,
        "is_serviceable": True,
    }
    payload.update(overrides)
    return payload


def create_pickup_hub_payload(**overrides) -> dict:
    payload = {"hub_code": "HUB-A", "cooler_slots_default": 4, "grace_minutes": 90}
    payload.update(overrides)
    return payload


def create_pickup_window_payload(season_id: str, week_index: int, **overrides) -> dict:
    payload = {
        "season_id": season_id,
        "week_index": week_index,
        "opens_at": "2026-05-04T12:00:00Z",
        "closes_at": "2026-05-04T18:00:00Z",
        "cooler_slots_total": 2,
    }
    payload.update(overrides)
    return payload


def create_member_payload(**overrides) -> dict:
    payload = {"full_name": "Mara One", "email": "m1@csf.test"}
    payload.update(overrides)
    return payload


def create_subscription_payload(
    member_id: str, share_plan_id: str, season_id: str, **overrides
) -> dict:
    payload = {
        "member_id": member_id,
        "share_plan_id": share_plan_id,
        "season_id": season_id,
        "fulfillment_mode": "HUB_PICKUP",
        "payment_basis": "INSTALLMENT",
        "join_week_index": 1,
    }
    payload.update(overrides)
    return payload


def create_vessel_payload(**overrides) -> dict:
    payload = {
        "vessel_name": "Northeaster",
        "permit_number": "P-100",
        "home_port": "Portland",
        "gear_types": ["HOOK_AND_LINE"],
    }
    payload.update(overrides)
    return payload


def create_quota_ledger_payload(vessel_id: str, season_id: str, **overrides) -> dict:
    payload = {
        "vessel_id": vessel_id,
        "season_id": season_id,
        "species": "SALMON",
        "management_area": "GOM-1",
        "entitlement_pounds": TEST_DEFAULTS["ENTITLEMENT_POUNDS"],
        "species_open_date": TEST_DEFAULTS["SPECIES_OPEN_DATE"],
        "species_close_date": TEST_DEFAULTS["SPECIES_CLOSE_DATE"],
        "permitted_gears": ["HOOK_AND_LINE"],
        "area_sensitivity_penalty": 0,
        "species_stock_adjustment": 0,
    }
    payload.update(overrides)
    return payload


def create_trip_payload(vessel_id: str, season_id: str, quota_ledger_id: str, **overrides) -> dict:
    payload = {
        "vessel_id": vessel_id,
        "season_id": season_id,
        "quota_ledger_id": quota_ledger_id,
        "gear_type": "HOOK_AND_LINE",
        "management_area": "GOM-1",
    }
    payload.update(overrides)
    return payload


def record_landing_payload(species: str, landed_pounds_gross: float, **overrides) -> dict:
    payload = {
        "species": species,
        "landed_pounds_gross": landed_pounds_gross,
        "ex_vessel_price_cents_per_lb": TEST_DEFAULTS["EX_VESSEL_PRICE_CENTS_PER_LB"],
        "offload_minutes": TEST_DEFAULTS["OFFLOAD_MINUTES"],
    }
    payload.update(overrides)
    return payload


def cold_chain_event_payload(
    landing_lot_id: str, custody_leg: str, minutes_above_threshold: int, peak_temp_c: float, **overrides
) -> dict:
    payload = {
        "landing_lot_id": landing_lot_id,
        "custody_leg": custody_leg,
        "minutes_above_threshold": minutes_above_threshold,
        "peak_temp_c": peak_temp_c,
    }
    payload.update(overrides)
    return payload


def substitution_payload(substitute_landing_lot_id: str, substitute_pounds: float, **overrides) -> dict:
    payload = {
        "substitute_landing_lot_id": substitute_landing_lot_id,
        "substitute_pounds": substitute_pounds,
    }
    payload.update(overrides)
    return payload


def share_transfer_payload(
    from_subscription_id: str,
    to_subscription_id: str,
    season_id: str,
    effective_week_index: int,
    expected_subscription_version: int,
    **overrides,
) -> dict:
    payload = {
        "from_subscription_id": from_subscription_id,
        "to_subscription_id": to_subscription_id,
        "season_id": season_id,
        "effective_week_index": effective_week_index,
        "expected_subscription_version": expected_subscription_version,
    }
    payload.update(overrides)
    return payload


def recall_notice_payload(landing_lot_id: str, reason: str = "PATHOGEN", **overrides) -> dict:
    payload = {"landing_lot_id": landing_lot_id, "reason": reason}
    payload.update(overrides)
    return payload
