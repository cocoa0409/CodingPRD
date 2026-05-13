"""Vehicle routes."""

from flask import Blueprint, request

from clock import clock
from db import db, new_id
from errors import err
from middleware import require_roles
from response import object_response, array_response
from serializers import vehicle as ser_vehicle
from validators import (
    get_pagination,
    paginate,
    require_dict,
    require_int,
    require_str,
)


bp = Blueprint("vehicles", __name__)


@bp.post("/vehicles")
@require_roles("CARRIER")
def create_vehicle():
    body = require_dict(request.get_json(silent=True) or {})
    vehicle_no = require_str(body.get("vehicle_no"), field="vehicle_no", min_len=1, max_len=32)
    compartment_count = require_int(
        body.get("compartment_count"), field="compartment_count", min_val=1, max_val=6
    )
    insured_cap_cents = require_int(
        body.get("insured_cap_cents"), field="insured_cap_cents", min_val=1
    )
    if vehicle_no in db.vehicle_no_index:
        err("ERR_VALIDATION", "vehicle_no already exists.")
    now_iso = clock.now_iso()
    row = {
        "id": new_id(),
        "vehicle_no": vehicle_no,
        "compartment_count": compartment_count,
        "insured_cap_cents": insured_cap_cents,
        "status": "AVAILABLE",
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.vehicles.put(row)
    db.vehicle_no_index[vehicle_no] = row["id"]
    return object_response(ser_vehicle(row), status_code=201)


@bp.get("/vehicles/<vehicle_id>")
@require_roles("CARRIER", "DISPATCHER", "COMPLIANCE_OFFICER", "INSURANCE_ADJUSTER")
def get_vehicle(vehicle_id):
    row = db.vehicles.get(vehicle_id)
    if row is None:
        err("ERR_NOT_FOUND", "Vehicle not found.")
    return object_response(ser_vehicle(row))


@bp.get("/vehicles")
@require_roles("CARRIER", "DISPATCHER", "COMPLIANCE_OFFICER")
def list_vehicles():
    limit, offset = get_pagination(request.args)
    status_filter = request.args.get("status")
    rows = db.vehicles.all()
    if status_filter is not None:
        rows = [v for v in rows if v["status"] == status_filter]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return array_response(
        [ser_vehicle(r) for r in page],
        limit=limit,
        offset=offset,
        total_count=total,
    )
