"""Payload factories — one per entity, input fields only (PRD §3/§4).

Every factory accepts **overrides so tests can drive boundary values without
rewriting the whole payload.
"""

_ITERS = {"n": 0}


def _uniq(tag: str) -> str:
    _ITERS["n"] += 1
    return f"{tag}-{_ITERS['n']:04d}"


def create_flock_payload(**overrides) -> dict:
    defaults = {
        "flock_name": _uniq("Flock"),
        "species": "SHEEP",
        "baseline_headcount": 500,
    }
    defaults.update(overrides)
    return defaults


def create_breeding_season_payload(**overrides) -> dict:
    defaults = {
        "season_label": "2026-fall",
        "ewes_bred": 200,
        "breeding_start_date": "2026-08-05T00:00:00Z",
        "breeding_end_date": "2026-09-19T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_birth_record_payload(**overrides) -> dict:
    defaults = {
        "birth_date": "2026-12-30T06:00:00Z",
        "births_reported": 10,
        "born_alive": 9,
        "born_dead": 1,
    }
    defaults.update(overrides)
    return defaults


def create_pasture_payload(**overrides) -> dict:
    defaults = {
        "pasture_name": _uniq("Pasture"),
        "acres": 100.0,
        "carrying_capacity_head": 500,
    }
    defaults.update(overrides)
    return defaults


def create_grazing_move_payload(**overrides) -> dict:
    defaults = {
        "move_start": "2026-09-01T00:00:00Z",
        "move_end": "2026-09-10T00:00:00Z",
        "head_count": 100,
    }
    defaults.update(overrides)
    return defaults


def create_parasite_treatment_payload(**overrides) -> dict:
    defaults = {
        "product_name": "Moxidectin",
        "treatment_date": "2026-08-05T00:00:00Z",
        "withdrawal_days": 7,
        "fecal_egg_count_before": 500,
    }
    defaults.update(overrides)
    return defaults


def create_shearing_crew_payload(**overrides) -> dict:
    defaults = {
        "crew_name": _uniq("Crew"),
        "head_per_day_capacity": 300,
        "daily_rate_cents": 40000,
    }
    defaults.update(overrides)
    return defaults


def create_shearing_event_payload(**overrides) -> dict:
    defaults = {
        "scheduled_start": "2026-08-03T00:00:00Z",
        "scheduled_end": "2026-08-05T00:00:00Z",
        "expected_head": 400,
    }
    defaults.update(overrides)
    return defaults


def create_wool_lot_payload(**overrides) -> dict:
    defaults = {
        "lot_code": _uniq("LOT"),
        "weight_lbs": 100.0,
    }
    defaults.update(overrides)
    return defaults


def create_core_test_payload(**overrides) -> dict:
    defaults = {
        "lab_ref": _uniq("LAB"),
    }
    defaults.update(overrides)
    return defaults


def create_core_test_results_payload(**overrides) -> dict:
    defaults = {
        "measured_micron": 19.0,
        "clean_yield_pct": 62.0,
        "vegetable_matter_pct": 1.2,
    }
    defaults.update(overrides)
    return defaults


def create_consignment_payload(**overrides) -> dict:
    defaults = {
        "pool_ref": _uniq("WWPA"),
    }
    defaults.update(overrides)
    return defaults


def create_holiday_window_payload(**overrides) -> dict:
    defaults = {
        "holiday_name": _uniq("HOLIDAY"),
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-09-15T00:00:00Z",
        "premium_pct": 22.0,
        "min_head": 50,
    }
    defaults.update(overrides)
    return defaults


def create_livestock_sale_payload(**overrides) -> dict:
    defaults = {
        "sale_type": "MEAT",
        "channel": "DIRECT",
        "head_count": 10,
        "avg_weight_lbs": 100.0,
        "base_price_per_cwt_cents": 20000,
        "scheduled_date": "2026-09-20T00:00:00Z",
    }
    defaults.update(overrides)
    # PRD §2.8/§3.6 conditional shape: a BREEDING sale carries
    # per_head_price_cents and must not carry the meat pair; a MEAT sale
    # carries the meat pair and must not carry per_head_price_cents.
    if defaults.get("sale_type") == "BREEDING":
        defaults.pop("avg_weight_lbs", None)
        defaults.pop("base_price_per_cwt_cents", None)
    else:
        defaults.pop("per_head_price_cents", None)
    return defaults


def create_loss_report_payload(**overrides) -> dict:
    defaults = {
        "loss_date": "2026-08-10T00:00:00Z",
        "head_lost": 6,
        "predator_type": "COYOTE",
        "guardian_on_duty": True,
    }
    defaults.update(overrides)
    return defaults


def create_grazing_contract_payload(**overrides) -> dict:
    defaults = {
        "client_org_name": _uniq("Client"),
        "parcel_name": "Parcel 1",
        "service_window_start": "2026-09-01T00:00:00Z",
        "service_window_end": "2026-09-30T00:00:00Z",
        "rate_per_head_day_cents": 90,
        "min_head": 50,
        "max_head": 600,
        "target_cover_reduction_pct": 60.0,
    }
    defaults.update(overrides)
    return defaults
