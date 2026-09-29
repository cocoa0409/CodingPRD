"""Logical clock and the four trading-partner collections (PRD 3.1)."""
from flask import Blueprint

import domain
from envelope import array_response, object_response, paginate
from guards import (
    ANY_ROLE,
    actor_id,
    apply_filters,
    filters,
    lookup,
    pagination,
    roles,
    validate,
)
from store import base_row, db, format_instant, parse_instant, sorted_rows

bp = Blueprint("partners", __name__)


def list_response(rows, serializer):
    limit, offset = pagination()
    window, total = paginate(sorted_rows(rows), limit, offset)
    return array_response([serializer(row) for row in window], limit, offset, total)


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.6)
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@roles("NetworkAdmin")
def set_current_utc():
    body = validate([{"name": "current_utc", "type": "datetime", "required": True}])
    moment = parse_instant(body["current_utc"])
    db.set_clock(moment)
    return object_response({"current_utc": body["current_utc"]})


# ---------------------------------------------------------------------------
# Plant
# ---------------------------------------------------------------------------
@bp.post("/installations/plants")
@roles("NetworkAdmin")
def create_plant():
    body = validate(
        [
            {"name": "name", "type": "string", "required": True},
            {"name": "state_code", "type": "state_code", "required": True},
            {"name": "hud_plant_code", "type": "string", "required": True},
        ]
    )
    row = base_row()
    row.update(
        {
            "name": body["name"],
            "state_code": body["state_code"],
            "hud_plant_code": body["hud_plant_code"],
            "chargeback_balance_cents": 0,
            "status": "ACTIVE",
        }
    )
    db.plants[row["id"]] = row
    return object_response(domain.pub_plant(row), 201)


@bp.get("/installations/plants/<row_id>")
@roles(*ANY_ROLE)
def read_plant(row_id):
    row = lookup("plants", row_id, "ERR_PLANT_NOT_FOUND")
    return object_response(domain.pub_plant(row))


@bp.get("/installations/plants")
@roles(*ANY_ROLE)
def list_plants():
    active = filters({"status": ["ACTIVE", "PROBATION"], "state_code": None})
    rows = apply_filters(list(db.plants.values()), active)
    return list_response(rows, domain.pub_plant)


# ---------------------------------------------------------------------------
# Hauler
# ---------------------------------------------------------------------------
@bp.post("/installations/haulers")
@roles("NetworkAdmin")
def create_hauler():
    body = validate(
        [
            {"name": "name", "type": "string", "required": True},
            {"name": "dot_number", "type": "string", "required": True},
            {"name": "insurance_expiry_date", "type": "date", "required": True},
            {"name": "endorsed_states", "type": "state_array", "required": True},
        ]
    )
    row = base_row()
    row.update(
        {
            "name": body["name"],
            "dot_number": body["dot_number"],
            "insurance_expiry_date": body["insurance_expiry_date"],
            "endorsed_states": body["endorsed_states"],
            "chargeback_balance_cents": 0,
            "status": "ACTIVE",
        }
    )
    db.haulers[row["id"]] = row
    return object_response(domain.pub_hauler(row), 201)


@bp.get("/installations/haulers/<row_id>")
@roles(*ANY_ROLE)
def read_hauler(row_id):
    row = lookup("haulers", row_id, "ERR_HAULER_NOT_FOUND")
    return object_response(domain.pub_hauler(row))


@bp.get("/installations/haulers")
@roles(*ANY_ROLE)
def list_haulers():
    active = filters({"status": ["ACTIVE", "SUSPENDED"]})
    rows = apply_filters(list(db.haulers.values()), active)
    return list_response(rows, domain.pub_hauler)


# ---------------------------------------------------------------------------
# EscortCrew
# ---------------------------------------------------------------------------
@bp.post("/installations/escort-crews")
@roles("NetworkAdmin")
def create_escort_crew():
    body = validate(
        [
            {"name": "vendor_name", "type": "string", "required": True},
            {"name": "endorsed_states", "type": "state_array", "required": True},
            {
                "name": "certified_roles",
                "type": "enum_array",
                "required": True,
                "values": ["ESCORT", "PILOT_CAR"],
            },
            {
                "name": "endorsement_class",
                "type": "enum",
                "required": True,
                "values": ["STANDARD", "OVERSIZE", "SUPERLOAD"],
            },
            {
                "name": "buffer_minutes",
                "type": "integer",
                "required": False,
                "min": 0,
                "max": 240,
            },
            {
                "name": "max_reserved_minutes",
                "type": "integer",
                "required": False,
                "min": 1,
            },
        ]
    )
    row = base_row()
    row.update(
        {
            "vendor_name": body["vendor_name"],
            "endorsed_states": body["endorsed_states"],
            "certified_roles": body["certified_roles"],
            "endorsement_class": body["endorsement_class"],
            "buffer_minutes": body.get("buffer_minutes", 45),
            "max_reserved_minutes": body.get("max_reserved_minutes", 600),
            "reserved_minutes": 0,
            "status": "AVAILABLE",
        }
    )
    db.escort_crews[row["id"]] = row
    return object_response(domain.pub_escort_crew(row), 201)


@bp.get("/installations/escort-crews/<row_id>")
@roles(*ANY_ROLE)
def read_escort_crew(row_id):
    row = lookup("escort_crews", row_id, "ERR_ESCORT_CREW_NOT_FOUND")
    return object_response(domain.pub_escort_crew(row))


@bp.get("/installations/escort-crews")
@roles(*ANY_ROLE)
def list_escort_crews():
    active = filters({"status": ["AVAILABLE", "OVERBOOKED"]})
    rows = apply_filters(list(db.escort_crews.values()), active)
    return list_response(rows, domain.pub_escort_crew)


# ---------------------------------------------------------------------------
# SetCrew
# ---------------------------------------------------------------------------
@bp.post("/installations/set-crews")
@roles("NetworkAdmin")
def create_set_crew():
    body = validate(
        [
            {"name": "company_name", "type": "string", "required": True},
            {"name": "hud_installer_license_no", "type": "string", "required": True},
            {"name": "license_state", "type": "state_code", "required": True},
            {"name": "license_expiry_date", "type": "date", "required": True},
            {
                "name": "daily_capacity",
                "type": "integer",
                "required": False,
                "min": 1,
                "max": 4,
            },
        ]
    )
    row = base_row()
    row.update(
        {
            "company_name": body["company_name"],
            "hud_installer_license_no": body["hud_installer_license_no"],
            "license_state": body["license_state"],
            "license_expiry_date": body["license_expiry_date"],
            "daily_capacity": body.get("daily_capacity", 1),
            "chargeback_balance_cents": 0,
        }
    )
    db.set_crews[row["id"]] = row
    return object_response(domain.pub_set_crew(row), 201)


@bp.get("/installations/set-crews/<row_id>")
@roles(*ANY_ROLE)
def read_set_crew(row_id):
    row = lookup("set_crews", row_id, "ERR_SET_CREW_NOT_FOUND")
    return object_response(domain.pub_set_crew(row))


@bp.get("/installations/set-crews")
@roles(*ANY_ROLE)
def list_set_crews():
    active = filters({"status": ["ACTIVE", "LICENSE_EXPIRED"]})
    rows = list(db.set_crews.values())
    wanted = active.get("status")
    if wanted is not None:
        rows = [r for r in rows if domain.set_crew_status(r) == wanted]
    return list_response(rows, domain.pub_set_crew)
