"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


DEFAULTS = {
    "SPECIES": "SOUTHERN_PINE",
    "ORIGINAL_CLASS": "3",
    "INSTALL_DATE": "1990-01-01",
    "GIS_LAT": 45.0,
    "GIS_LON": -122.0,
    "GIS_TAG": "URBAN",
    "HEIGHT_FT": 40,
    "DUE_WINDOW_START": "2026-08-10T00:00:00Z",
    "DUE_WINDOW_END": "2026-08-20T00:00:00Z",
    "WORK_START_DATE": "2026-08-10",
    "WORK_END_DATE": "2026-08-12",
    "TAKEN_AT": "2026-08-11T00:00:00Z",
}


def photo(photo_type, url=None, taken_at=None) -> dict:
    """One photo-evidence object (PRD §3.3)."""
    return {
        "photo_type": photo_type,
        "url": url or f"https://ev/{photo_type.lower()}-{_seq()}.jpg",
        "taken_at": taken_at or DEFAULTS["TAKEN_AT"],
    }


def default_photos(*types):
    """GROUNDLINE + TAG by default; pass extra types (e.g. DECAY_POCKET)."""
    wanted = list(types) if types else ["GROUNDLINE", "TAG"]
    return [photo(t) for t in wanted]


def create_budget_payload(**overrides) -> dict:
    defaults = {"fiscal_year": 2026, "total_cents": 1_000_000}
    defaults.update(overrides)
    return defaults


def create_cycle_payload(**overrides) -> dict:
    defaults = {
        "year": 2026,
        "cycle_length_years": 10,
        "sample_pct": 0,
        "strength_variant_policy": "CONSERVATIVE",
    }
    defaults.update(overrides)
    return defaults


def create_pole_payload(**overrides) -> dict:
    defaults = {
        "pole_number": f"P-{_seq():05d}",
        "species": DEFAULTS["SPECIES"],
        "original_class": DEFAULTS["ORIGINAL_CLASS"],
        "install_date": DEFAULTS["INSTALL_DATE"],
        "gis_lat": DEFAULTS["GIS_LAT"],
        "gis_lon": DEFAULTS["GIS_LON"],
        "gis_tag": DEFAULTS["GIS_TAG"],
        "height_ft": DEFAULTS["HEIGHT_FT"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_task_payload(cycle_id, pole_id, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "pole_id": pole_id,
        "due_window_start": DEFAULTS["DUE_WINDOW_START"],
        "due_window_end": DEFAULTS["DUE_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def submit_task_payload(**overrides) -> dict:
    """Field readings + photo evidence (PRD §3.3)."""
    defaults = {
        "shell_thickness_in": 2.50,
        "sound_wood_pct": 90,
        "decay_pocket_depth_in": 0.0,
        "moisture_pct": 20,
        "photos": default_photos(),
    }
    defaults.update(overrides)
    return defaults


def create_treatment_order_payload(pole_id, **overrides) -> dict:
    defaults = {
        "pole_id": pole_id,
        "product_code": "CCA_WRAP",
        "cost_cents": 17500,
    }
    defaults.update(overrides)
    return defaults


def schedule_treatment_payload(crew_id, **overrides) -> dict:
    defaults = {
        "crew_id": crew_id,
        "work_start_date": DEFAULTS["WORK_START_DATE"],
        "work_end_date": DEFAULTS["WORK_END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {"crew_code": f"CR-{_seq():05d}", "region": "NW"}
    defaults.update(overrides)
    return defaults


def create_replacement_order_payload(pole_id, **overrides) -> dict:
    defaults = {"pole_id": pole_id, "estimated_cost_cents": 200000}
    defaults.update(overrides)
    return defaults


def fund_order_payload(budget_id, expected_budget_version) -> dict:
    return {"budget_id": budget_id, "expected_budget_version": expected_budget_version}


def create_warranty_claim_payload(treatment_order_id, **overrides) -> dict:
    defaults = {"treatment_order_id": treatment_order_id, "claim_reason": "DECAY_RECURRENCE"}
    defaults.update(overrides)
    return defaults


def adjudicate_claim_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def gis_patch_payload(expected_pole_version, **overrides) -> dict:
    defaults = {
        "gis_lat": 46.9,
        "gis_lon": -121.9,
        "gis_tag": "COASTAL",
        "expected_pole_version": expected_pole_version,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
