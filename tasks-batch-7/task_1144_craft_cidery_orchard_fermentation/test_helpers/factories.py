"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter):04d}"


def create_variety_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("VAR"),
        "tannin_g_per_l": 1.0,
        "brix_at_harvest": 13.0,
        "acidity_g_per_l": 6.0,
        "is_bittersweet": False,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "grower_name": _uniq("Grower"),
        "region_code": "NY",
        "season_year": 2026,
        "committed_weight_lbs": 1000,
        "price_per_lb_cents": 85,
    }
    defaults.update(overrides)
    return defaults


def create_harvest_lot_payload(variety_id: str, **overrides) -> dict:
    defaults = {
        "variety_id": variety_id,
        "received_at": "2026-09-15T10:00:00Z",
        "weight_lbs": 1000,
        "measured_brix": 13.0,
        "measured_tannin_g_per_l": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_blend_line(harvest_lot_id: str, weight_lbs: int, position: int = 1) -> dict:
    return {
        "harvest_lot_id": harvest_lot_id,
        "weight_lbs": weight_lbs,
        "position": position,
    }


def create_press_batch_payload(blend_lines=None, **overrides) -> dict:
    defaults = {
        "scheduled_press_date": "2026-09-16T08:00:00Z",
        "press_window_minutes": 120,
        "blend_lines": blend_lines if blend_lines is not None else [],
    }
    defaults.update(overrides)
    return defaults


def create_tank_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("T"),
        "capacity_liters": 500,
        "material": "STAINLESS",
        "temperature_controlled": True,
    }
    defaults.update(overrides)
    return defaults


def create_yeast_program_payload(**overrides) -> dict:
    """Default attenuation 50 keeps terminal-gravity thresholds generous so a
    batch at a test-chosen gravity reading satisfies the aging precondition
    (current <= original * (1 - attenuation/100) + 0.5) for typical readings."""
    defaults = {
        "code": _uniq("Y"),
        "kind": "CULTURED",
        "attenuation_pct": 50,
        "temp_min_f": 60,
        "temp_max_f": 72,
        "nutrient_required": False,
    }
    defaults.update(overrides)
    return defaults


def create_fermentation_batch_payload(press_batch_id: str, tank_id: str,
                                      yeast_program_id: str, **overrides) -> dict:
    defaults = {
        "press_batch_id": press_batch_id,
        "tank_id": tank_id,
        "yeast_program_id": yeast_program_id,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": _uniq("SKU"),
        "name": _uniq("Cider"),
        "style": "DRY",
        "target_abv_pct": 5.0,
        "vintage_year": 2026,
    }
    defaults.update(overrides)
    return defaults


def create_label_approval_payload(**overrides) -> dict:
    defaults = {
        "market": "FEDERAL_TTB",
        "application_number": _uniq("TTB"),
        "expires_at": "2099-12-31T23:59:59Z",
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(**overrides) -> dict:
    defaults = {
        "kind": "NY_FARM_CIDERY",
        "license_number": _uniq("LIC"),
        "issued_at": "2026-01-01T00:00:00Z",
        "expires_at": "2027-12-31T23:59:59Z",
        "scope_states": ["NY"],
        "annual_volume_cap_liters": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_packaging_run_payload(product_id: str, fermentation_batch_id: str,
                                 label_approval_id: str, license_id: str,
                                 **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "fermentation_batch_id": fermentation_batch_id,
        "package_format": "BOTTLE_500ML",
        "volume_liters": 50,
        "label_approval_id": label_approval_id,
        "license_id": license_id,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(product_id: str, packaging_run_id: str, **overrides) -> dict:
    defaults = {
        "channel": "TASTING_ROOM",
        "destination_state": "NY",
        "product_id": product_id,
        "packaging_run_id": packaging_run_id,
        "units": 5,
        "unit_price_cents": 1200,
    }
    defaults.update(overrides)
    return defaults


def create_excise_report_payload(**overrides) -> dict:
    defaults = {
        "period_year": 2026,
        "period_month": 10,
        "regulator": "TTB",
    }
    defaults.update(overrides)
    return defaults
