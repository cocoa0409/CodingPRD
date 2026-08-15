"""Shared store helpers: lookups, system fields, serializers, pagination.

Computed fields are reconciled on read (immediate consistency, PRD 2 intro):
LeagueSeason.rounds_completed / collected_fees_cents, EventEntry.tech_fail_count
and event_points are derived from the store at serialization time.
"""
from flask import request

from db import db
from errors import raise_error, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from util import new_id, now_ts

# --- domain constants (scaffold calculations / state machines) --------------
TECH_FAIL_DISQUALIFY_THRESHOLD = 2
FASTEST_LAP_MAX_POSITION = 10
TRACK_CAPACITY_KARTS = 4

CLASS_CODES = {"CADET", "JUNIOR", "SENIOR", "HEAVY"}
ENTRY_ACTIVE_STATES = {"ENTERED", "TECH_CHECK", "TECH_FAILED", "TECH_PASSED", "GRID_LOCKED"}
COUNTED_EVENT_STATES = {"COMPLETED", "FINALIZED"}
OPEN_INCIDENT_STATES = {"REPORTED", "UNDER_REVIEW", "APPEALED"}


# --- generic record helpers ---------------------------------------------------

def create_record(collection, fields, common=True):
    rec = {"id": new_id()}
    ts = now_ts()
    rec["created_at"] = ts
    if common:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec.update(fields)
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """PRD 2.4: every modification refreshes updated_at and advances version by 1."""
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


def find(collection, rid):
    if not isinstance(rid, str):
        return None
    return db[collection].get(rid)


def must_find(collection, rid, message="resource not found"):
    rec = find(collection, rid)
    if rec is None:
        raise_error(ERR_NOT_FOUND, message)
    return rec


# --- computed / derived fields -------------------------------------------------

def entry_tech_fail_count(entry):
    return sum(
        1
        for i in db["inspections"].values()
        if i["entry_id"] == entry["id"] and i["outcome"] == "FAIL"
    )


def entry_event_points(entry):
    """Sum of points_awarded over the entry's results in HEAT/MAIN sessions."""
    total = 0
    for r in db["results"].values():
        if r["entry_id"] != entry["id"]:
            continue
        sess = db["sessions"].get(r["session_id"])
        if sess is not None and sess["session_type"] in ("HEAT", "MAIN"):
            total += r["points_awarded"]
    return total


def season_events(season):
    return [e for e in db["events"].values() if e["season_id"] == season["id"]]


def season_rounds_completed(season):
    return sum(1 for e in season_events(season) if e["status"] in COUNTED_EVENT_STATES)


def season_collected_fees_cents(season):
    event_ids = {e["id"] for e in season_events(season)}
    return sum(
        en["entry_fee_cents"]
        for en in db["entries"].values()
        if en["event_id"] in event_ids and en["fee_status"] == "PAID"
    )


# --- serializers ---------------------------------------------------------------

def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def serialize_season(s):
    out = {
        "name": s["name"],
        "year": s["year"],
        "drop_rounds": s["drop_rounds"],
        "points_scheme": list(s["points_scheme"]),
        "fastest_lap_bonus_points": s["fastest_lap_bonus_points"],
        "status": s["status"],
        "rounds_completed": season_rounds_completed(s),
        "collected_fees_cents": season_collected_fees_cents(s),
    }
    out.update(_common(s))
    return out


def serialize_class(c):
    out = {
        "season_id": c["season_id"],
        "code": c["code"],
        "min_age": c["min_age"],
        "max_age": c["max_age"],
        "min_combined_weight_kg": c["min_combined_weight_kg"],
        "entry_fee_cents": c["entry_fee_cents"],
        "rental_kart_allowed": c["rental_kart_allowed"],
    }
    out.update(_common(c))
    return out


def serialize_driver(d):
    out = {
        "full_name": d["full_name"],
        "date_of_birth": d["date_of_birth"],
        "body_weight_kg": d["body_weight_kg"],
        "license_type": d["license_type"],
        "status": d["status"],
    }
    out.update(_common(d))
    return out


def serialize_kart(k):
    out = {
        "fleet_number": k["fleet_number"],
        "eligible_class_codes": list(k["eligible_class_codes"]),
        "status": k["status"],
    }
    out.update(_common(k))
    return out


def serialize_event(e):
    out = {
        "season_id": e["season_id"],
        "round_number": e["round_number"],
        "event_date": e["event_date"],
        "track_name": e["track_name"],
        "status": e["status"],
    }
    out.update(_common(e))
    return out


def serialize_entry(en):
    out = {
        "event_id": en["event_id"],
        "driver_id": en["driver_id"],
        "class_id": en["class_id"],
        "entry_type": en["entry_type"],
        "kart_id": en["kart_id"],
        "status": en["status"],
        "entry_fee_cents": en["entry_fee_cents"],
        "fee_status": en["fee_status"],
        "tech_fail_count": entry_tech_fail_count(en),
        "event_points": entry_event_points(en),
    }
    out.update(_common(en))
    return out


def serialize_session(s):
    out = {
        "event_id": s["event_id"],
        "session_type": s["session_type"],
        "sequence": s["sequence"],
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def serialize_result(r):
    out = {
        "session_id": r["session_id"],
        "entry_id": r["entry_id"],
        "finish_position": r["finish_position"],
        "best_lap_ms": r["best_lap_ms"],
        "total_time_ms": r["total_time_ms"],
        "penalty_seconds_applied": r["penalty_seconds_applied"],
        "is_fastest_lap": r["is_fastest_lap"],
        "points_awarded": r["points_awarded"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def serialize_inspection(i):
    # TechInspection is append-only (PRD 2.4): only id and created_at.
    return {
        "id": i["id"],
        "created_at": i["created_at"],
        "entry_id": i["entry_id"],
        "measured_combined_weight_kg": i["measured_combined_weight_kg"],
        "outcome": i["outcome"],
        "inspector_user_id": i["inspector_user_id"],
        "notes": i.get("notes"),
    }


def serialize_incident(inc):
    out = {
        "event_id": inc["event_id"],
        "entry_id": inc["entry_id"],
        "session_id": inc["session_id"],
        "description": inc["description"],
        "reporter_user_id": inc["reporter_user_id"],
        "status": inc["status"],
        "penalty_kind": inc["penalty_kind"],
        "penalty_seconds": inc["penalty_seconds"],
        "adjudicator_user_id": inc["adjudicator_user_id"],
        "appeal_count": inc["appeal_count"],
    }
    out.update(_common(inc))
    return out


def serialize_booking(b):
    out = {
        "driver_id": b["driver_id"],
        "kart_id": b["kart_id"],
        "start_time": b["start_time"],
        "end_time": b["end_time"],
        "pricing_mode": b["pricing_mode"],
        "status": b["status"],
        "minutes_used": b["minutes_used"],
        "fee_cents": b["fee_cents"],
    }
    out.update(_common(b))
    return out


# --- list helpers ---------------------------------------------------------------

def list_sorted(records):
    """PRD 2.3: default sort is created_at ascending."""
    return sorted(records, key=lambda r: (r["created_at"], r["id"]))


def pagination_params():
    """limit default 10 (min 1, max 100), offset default 0; out-of-range clamped."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def paginate(records):
    limit, offset = pagination_params()
    total = len(records)
    return records[offset:offset + limit], total, limit, offset
