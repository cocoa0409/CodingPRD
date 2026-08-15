"""Excursion lifecycle side effects (SCAFFOLD §1.2, PRD §3.3)."""

import db
from services.ledger import recompute_accountability_balance


def _bump(entity):
    entity["updated_at"] = db.now_ts()
    entity["version"] += 1


def open_excursion(unit, reading):
    """Open a new excursion on the unit and quarantine its AVAILABLE lots."""
    site = db.provider_sites[unit["provider_site_id"]]
    now = db.now_ts()
    excursion = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "storage_unit_id": unit["id"],
        "opened_at": reading["recorded_at"],
        "closed_at": None,
        "peak_temperature_c": reading["temperature_c"],
        "duration_minutes": 0,
        "status": "OPEN",
        "resolution_notes": None,
        "doses_written_off": 0,
        "public_doses_written_off": 0,
    }
    db.temperature_excursions[excursion["id"]] = excursion

    unit["active_excursion_id"] = excursion["id"]
    _bump(unit)

    for lot in db.lots.values():
        if lot["storage_unit_id"] == unit["id"] and lot["status"] == "AVAILABLE":
            lot["status"] = "QUARANTINED"
            _bump(lot)

    site["excursion_count_open"] = site.get("excursion_count_open", 0) + 1
    _bump(site)
    return excursion


def update_peak(unit, excursion, temperature_c):
    """Peak reconsideration per excursion_peak_temperature calc (PRD §3.3)."""
    if temperature_c > unit["max_temp_c"]:
        candidate_deviation = temperature_c - unit["max_temp_c"]
    elif temperature_c < unit["min_temp_c"]:
        candidate_deviation = unit["min_temp_c"] - temperature_c
    else:
        candidate_deviation = -1

    peak = excursion["peak_temperature_c"]
    if peak > unit["max_temp_c"]:
        existing_deviation = peak - unit["max_temp_c"]
    else:
        existing_deviation = unit["min_temp_c"] - peak

    if candidate_deviation > existing_deviation:
        excursion["peak_temperature_c"] = temperature_c
        _bump(excursion)


def close_excursion_on_in_range(excursion, reading):
    """First in-range reading closes the excursion and sets duration."""
    opened = db.parse_iso_datetime(excursion["opened_at"])
    closed = db.parse_iso_datetime(reading["recorded_at"])
    excursion["closed_at"] = reading["recorded_at"]
    excursion["duration_minutes"] = int((closed - opened).total_seconds() // 60)
    _bump(excursion)


def resolve_viable(unit, excursion, notes):
    site = db.provider_sites[unit["provider_site_id"]]
    excursion["status"] = "RESOLVED_VIABLE"
    excursion["resolution_notes"] = notes
    _bump(excursion)

    for lot in db.lots.values():
        if lot["storage_unit_id"] == unit["id"] and lot["status"] == "QUARANTINED":
            lot["status"] = "AVAILABLE"
            _bump(lot)

    unit["active_excursion_id"] = None
    _bump(unit)

    site["excursion_count_open"] = site.get("excursion_count_open", 0) - 1
    _bump(site)


def resolve_wasted(unit, excursion, notes):
    site = db.provider_sites[unit["provider_site_id"]]
    total_written_off = 0
    public_written_off = 0
    public_site_touched = False
    for lot in db.lots.values():
        if lot["storage_unit_id"] == unit["id"] and lot["status"] == "QUARANTINED":
            pre_zero = lot["quantity_on_hand"]
            total_written_off += pre_zero
            if lot["stock_type"] == "PUBLIC_VFC":
                public_written_off += pre_zero
                public_site_touched = True
            lot["quantity_on_hand"] = 0
            lot["status"] = "WASTED_CLOSED"
            _bump(lot)

    excursion["status"] = "RESOLVED_WASTED"
    excursion["resolution_notes"] = notes
    excursion["doses_written_off"] = total_written_off
    excursion["public_doses_written_off"] = public_written_off
    _bump(excursion)

    unit["active_excursion_id"] = None
    _bump(unit)

    site["excursion_count_open"] = site.get("excursion_count_open", 0) - 1
    _bump(site)

    if public_site_touched:
        recompute_accountability_balance(site["id"])
