"""DamageLine endpoints (PRD §3.5). Damage lines carry only id and created_at."""

from flask import Blueprint

import serializers
from db import base_row, db
from errors import api_error
from middleware import authenticate
from response import list_response, object_response
from routes.common import get_vehicle
from services import aggregates
from services import posture as posture_service
from services.constants import DENT_SIZE_CLASSES, PANEL_CODES
from validation import (
    json_body,
    opt_int,
    opt_number,
    pagination,
    paginate,
    query_filter,
    req_bool,
    req_enum,
    req_int,
    req_number,
    req_string,
)

bp = Blueprint("damage_lines", __name__)

READ_ROLES = (
    "CatastropheDirector",
    "ShopEstimator",
    "IntakeAdvisor",
    "PdrTechnician",
    "QualityInspector",
    "InsurerAdjuster",
)


@bp.post("/hail-ops/damage-lines")
def create_damage_line():
    authenticate(("IntakeAdvisor",))
    body = json_body()
    vehicle_id = req_string(body, "vehicle_id")
    panel_code = req_enum(body, "panel_code", PANEL_CODES)
    dent_count = req_int(body, "dent_count", minimum=1)
    dent_size_class = req_enum(body, "dent_size_class", DENT_SIZE_CLASSES)
    aluminum = req_bool(body, "aluminum")
    conventional_labor_hours = req_number(body, "conventional_labor_hours", minimum=0)
    conventional_paint_materials_cents = req_int(
        body, "conventional_paint_materials_cents", minimum=0
    )
    r_and_i_hours = opt_number(body, "r_and_i_hours", default=0, minimum=0)
    oversize_dent_count = opt_int(body, "oversize_dent_count", default=0, minimum=0)

    vehicle = get_vehicle(vehicle_id)
    posture_service.recompute_for_vehicle(vehicle)

    if vehicle["repair_status"] not in ("INTAKE", "ESTIMATED"):
        raise api_error(
            "ERR_INVALID_VEHICLE_REPAIR_STATE",
            "The damage matrix is settled once the vehicle leaves INTAKE/ESTIMATED.",
        )

    row = base_row(versioned=False)
    row.update({
        "vehicle_id": vehicle_id,
        "panel_code": panel_code,
        "dent_count": dent_count,
        "dent_size_class": dent_size_class,
        "aluminum": aluminum,
        "r_and_i_hours": r_and_i_hours,
        "oversize_dent_count": oversize_dent_count,
        "conventional_labor_hours": conventional_labor_hours,
        "conventional_paint_materials_cents": conventional_paint_materials_cents,
        "pdr_line_cents": None,
        "conventional_line_cents": None,
        "capped": False,
        "routed_to": None,
    })
    db.damage_lines[row["id"]] = row
    return object_response(serializers.damage_line(row), 201)


@bp.get("/hail-ops/vehicles/<identifier>/damage-lines")
def list_vehicle_damage_lines(identifier):
    authenticate(READ_ROLES)
    limit, offset = pagination()
    vehicle = get_vehicle(identifier)

    rows = aggregates.damage_lines_of_vehicle(vehicle["id"])
    routed_to = query_filter("routed_to")
    if routed_to is not None:
        rows = [r for r in rows if r["routed_to"] == routed_to]

    page = paginate(rows, limit, offset)
    return list_response([serializers.damage_line(r) for r in page], limit, offset, len(rows))
