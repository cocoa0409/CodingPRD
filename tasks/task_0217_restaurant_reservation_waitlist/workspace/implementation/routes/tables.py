"""Table routes (PRD §3.1)."""
from flask import Blueprint, request

import db
from errors import err, ERR_VALIDATION
from middleware import require_roles
from response import object_response, array_response
from services.lookup import get_or_404
from services.cascades import run_table_freeing_cascade
from validators import (
    get_body, require_str, opt_int, require_int, paginate,
)

bp = Blueprint("tables", __name__)


@bp.post("/tables")
def create_table():
    require_roles({"Manager"})
    body = get_body()
    dining_area_id = require_str(body, "dining_area_id")
    area = get_or_404(db.dining_areas, dining_area_id)
    label = require_str(body, "label")
    min_party = opt_int(body, "min_party_size", 1, minimum=1)
    max_party = require_int(body, "max_party_size", minimum=1)
    if max_party < min_party:
        raise err(ERR_VALIDATION, "max_party_size must be >= min_party_size")
    turn = opt_int(body, "turn_time_minutes", None, minimum=30, maximum=360)
    # label unique within dining_area_id
    for t in db.tables.values():
        if t["dining_area_id"] == dining_area_id and t["label"] == label:
            raise err(ERR_VALIDATION, "label must be unique within the dining area")

    rec = db.base_fields()
    rec.update({
        "dining_area_id": dining_area_id,
        "label": label,
        "min_party_size": min_party,
        "max_party_size": max_party,
        "turn_time_minutes": turn,
        "status": "AVAILABLE",
    })
    db.tables[rec["id"]] = rec
    return object_response(db.serialize(rec), 201)


@bp.get("/tables/<tid>")
def read_table(tid):
    require_roles({"Manager", "Host", "Customer"})
    rec = get_or_404(db.tables, tid)
    return object_response(db.serialize(rec), 200)


@bp.get("/tables")
def list_tables():
    require_roles({"Manager", "Host", "Customer"})
    dining_area_id = request.args.get("dining_area_id")
    records = [t for t in db.tables.values()
               if dining_area_id is None or t["dining_area_id"] == dining_area_id]
    page, pagination = paginate(records)
    return array_response([db.serialize(r) for r in page], pagination, 200)


@bp.post("/tables/<tid>/out-of-service")
def out_of_service(tid):
    require_roles({"Manager"})
    rec = get_or_404(db.tables, tid)
    rec["status"] = "OUT_OF_SERVICE"
    db.touch(rec)
    return object_response(db.serialize(rec), 200)


@bp.post("/tables/<tid>/return-to-service")
def return_to_service(tid):
    require_roles({"Manager", "Host"})
    rec = get_or_404(db.tables, tid)
    rec["status"] = "AVAILABLE"
    db.touch(rec)
    return object_response(db.serialize(rec), 200)


@bp.post("/tables/<tid>/bus")
def bus_table(tid):
    require_roles({"Host"})
    rec = get_or_404(db.tables, tid)
    rec["status"] = "AVAILABLE"
    db.touch(rec)
    # table-freeing cascade: re-run waitlist promotion
    area = db.dining_areas.get(rec["dining_area_id"])
    if area is not None:
        run_table_freeing_cascade(area["restaurant_id"])
    return object_response(db.serialize(rec), 200)
