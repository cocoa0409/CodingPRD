"""Furnaces (PRD 3.5)."""

from flask import Blueprint, g

from db import db, new_record
from middleware import ANY_ROLE, endpoint
from response import created, ok
from services.lookup import furnace_or_404, require_unique
from validate import field_int, field_num, field_str

bp = Blueprint("furnaces", __name__)

CREATE_ROLES = ("ProcessEngineer", "PlantAdmin")


@bp.post("/furnaces")
@endpoint(CREATE_ROLES)
def create_furnace():
    body = g.body
    furnace_code = field_str(body, "furnace_code")
    max_charge_mass_kg = field_num(body, "max_charge_mass_kg", exclusive_min=0)
    cooldown_minutes = field_int(
        body, "cooldown_minutes", required=False, default=None, minimum=0
    )
    if cooldown_minutes is None:
        cooldown_minutes = 30

    require_unique("furnaces", "furnace_code", furnace_code)

    furnace = new_record(
        {
            "furnace_code": furnace_code,
            "max_charge_mass_kg": max_charge_mass_kg,
            "cooldown_minutes": cooldown_minutes,
            "status": "IDLE",
            "last_run_end_at": None,
        }
    )
    db.furnaces[furnace["id"]] = furnace
    return created(furnace)


@bp.get("/furnaces/<furnace_id>")
@endpoint(ANY_ROLE)
def get_furnace(furnace_id):
    return ok(furnace_or_404(furnace_id))
