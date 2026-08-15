"""Bottling lines and preform deliveries (OCC-guarded ledger writes)."""
from flask import Blueprint, request

from db import store, new_resource, touch, by_creation
from errors import ApiError, err_invalid_state
from middleware import auth, ALL_ROLES
from response import ok_object, ok_list
from services import as_int, get_body, get_or_404, line_json, delivery_json, raise_shape

bp = Blueprint("lines", __name__)


@bp.post("/api/plants/<plant_id>/bottling-lines")
@auth(["PlantAdmin"])
def create_line(plant_id):
    plant = get_or_404(store.plants, plant_id, "plant")
    body = get_body()
    errs = []
    line_code = body.get("line_code")
    if not isinstance(line_code, str) or not line_code:
        errs.append("line_code is required")
    capacity, ok = as_int(body.get("daily_capacity_units"))
    if not ok or capacity <= 0:
        errs.append("daily_capacity_units must be a positive integer")
    raise_shape(errs)

    line = new_resource(
        {
            "plant_id": plant["id"],
            "line_code": line_code,
            "daily_capacity_units": capacity,
            "preform_on_hand_units": 0,
            "preform_reserved_units": 0,
        }
    )
    store.lines[line["id"]] = line
    return ok_object(line_json(line), 201)


@bp.get("/api/bottling-lines")
@auth(ALL_ROLES)
def list_lines():
    items = list(store.lines.values())
    plant_id = request.args.get("plant_id")
    if plant_id is not None:
        items = [l for l in items if l["plant_id"] == plant_id]
    return ok_list([line_json(l) for l in by_creation(items)])


@bp.get("/api/bottling-lines/<line_id>")
@auth(ALL_ROLES)
def get_line(line_id):
    line = get_or_404(store.lines, line_id, "bottling line")
    return ok_object(line_json(line))


@bp.get("/api/bottling-lines/<line_id>/preform-deliveries")
@auth(ALL_ROLES)
def list_line_deliveries(line_id):
    get_or_404(store.lines, line_id, "bottling line")
    items = [d for d in store.deliveries.values() if d["line_id"] == line_id]
    return ok_list([delivery_json(d) for d in by_creation(items)])


@bp.post("/api/bottling-lines/<line_id>/preform-deliveries")
@auth(["ProductionLead"])
def create_delivery(line_id):
    line = get_or_404(store.lines, line_id, "bottling line")
    body = get_body()

    # Rung 4 — OCC on the line.
    expected, ok_exp = as_int(body.get("expected_line_version"))
    if ok_exp and expected != line["version"]:
        raise ApiError(
            "ERR_STALE_LINE_VERSION",
            "expected_line_version does not match the line's current version",
            412,
        )

    # Rung 11 — input shape.
    errs = []
    supplier = body.get("supplier")
    if not isinstance(supplier, str) or not supplier:
        errs.append("supplier is required")
    delivered, ok_d = as_int(body.get("delivered_units"))
    if not ok_d or delivered <= 0:
        errs.append("delivered_units must be a positive integer")
    if not ok_exp:
        errs.append("expected_line_version is required")
    raise_shape(errs)

    delivery = new_resource(
        {
            "line_id": line["id"],
            "supplier": supplier,
            "delivered_units": delivered,
            "accepted_units": None,
            "status": "PENDING_QC",
        }
    )
    store.deliveries[delivery["id"]] = delivery
    touch(line)
    return ok_object(delivery_json(delivery), 201)


@bp.get("/api/preform-deliveries")
@auth(ALL_ROLES)
def list_deliveries():
    items = list(store.deliveries.values())
    line_id = request.args.get("line_id")
    status = request.args.get("status")
    if line_id is not None:
        items = [d for d in items if d["line_id"] == line_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return ok_list([delivery_json(d) for d in by_creation(items)])


@bp.get("/api/preform-deliveries/<delivery_id>")
@auth(ALL_ROLES)
def get_delivery(delivery_id):
    delivery = get_or_404(store.deliveries, delivery_id, "preform delivery")
    return ok_object(delivery_json(delivery))


@bp.post("/api/preform-deliveries/<delivery_id>/qc-verdict")
@auth(["QAOfficer"])
def qc_verdict(delivery_id):
    delivery = get_or_404(store.deliveries, delivery_id, "preform delivery")
    if delivery["status"] != "PENDING_QC":
        raise err_invalid_state("the delivery has already received its QC verdict")
    body = get_body()

    verdict = body.get("verdict")
    accepted, ok_a = as_int(body.get("accepted_units"))
    errs = []
    if verdict not in ("ACCEPTED", "REJECTED"):
        errs.append("verdict must be ACCEPTED or REJECTED")
    elif verdict == "ACCEPTED":
        if not ok_a or accepted <= 0 or accepted > delivery["delivered_units"]:
            errs.append("accepted_units must be greater than zero and no greater than delivered_units")
    raise_shape(errs)

    line = store.lines.get(delivery["line_id"])
    if verdict == "ACCEPTED":
        delivery["accepted_units"] = accepted
        if line is not None:
            line["preform_on_hand_units"] += accepted
    else:
        delivery["accepted_units"] = 0
    delivery["status"] = verdict
    touch(delivery)
    if line is not None:
        touch(line)
    return ok_object(delivery_json(delivery))
