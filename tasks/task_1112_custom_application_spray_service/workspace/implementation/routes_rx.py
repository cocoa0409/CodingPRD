"""Prescription routes: create (DRAFT), read, list, approve (OCC on Field.version,
supersede cascade)."""

from flask import Blueprint, request

from store import store
from util import (require_roles, get_body, req_str, req_int, req_pos_num, req_dt,
                  ok, paginate, validation_error, not_found, invalid_state,
                  ApiError)
from domain import (new_mutable, serialize, touch, validate_prescription_lines,
                    tank_mix_verdicts)

bp = Blueprint("prescriptions", __name__, url_prefix="/api")

RX_STATUSES = {"DRAFT", "APPROVED", "SUPERSEDED"}


@bp.post("/prescriptions")
def create_prescription():
    uid, _role = require_roles("Agronomist")
    body = get_body()
    field_id = req_str(body, "field_id")
    season_year = req_int(body, "season_year")
    valid_from = req_dt(body, "valid_from")
    valid_to = req_dt(body, "valid_to")
    carrier_gpa = req_pos_num(body, "carrier_gpa")
    lines = validate_prescription_lines(body.get("lines"))
    if valid_from > valid_to:
        raise validation_error("valid_from must be on or before valid_to")
    if field_id not in store.fields:
        raise not_found("field not found")
    for line in lines:
        if line["product_id"] not in store.products:
            raise not_found("product not found: %s" % line["product_id"])
    rx = new_mutable({
        "field_id": field_id,
        "season_year": season_year,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "carrier_gpa": carrier_gpa,
        "lines": lines,
        "status": "DRAFT",
        "created_by_user_id": uid,
    })
    store.prescriptions[rx["id"]] = rx
    return ok(serialize("prescription", rx), 201)


@bp.get("/prescriptions/<rx_id>")
def get_prescription(rx_id):
    require_roles("Agronomist", "Dispatcher", "Grower", "CoopAdmin", "ComplianceOfficer")
    rx = store.prescriptions.get(rx_id)
    if rx is None:
        raise not_found("prescription not found")
    return ok(serialize("prescription", rx))


@bp.get("/prescriptions")
def list_prescriptions():
    require_roles("Agronomist", "Dispatcher", "Grower", "CoopAdmin", "ComplianceOfficer")
    items = sorted(store.prescriptions.values(), key=lambda r: (r["created_at"], r["_seq"]))
    fid = request.args.get("field_id")
    if fid is not None:
        items = [r for r in items if r["field_id"] == fid]
    sy = request.args.get("season_year")
    if sy is not None:
        try:
            syi = int(sy)
        except (TypeError, ValueError):
            syi = None
        items = [r for r in items if syi is not None and r["season_year"] == syi]
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    return paginate([serialize("prescription", r) for r in items])


@bp.post("/prescriptions/<rx_id>/approve")
def approve_prescription(rx_id):
    require_roles("Agronomist")
    body = get_body()
    expected_field_version = req_int(body, "expected_field_version")
    rx = store.prescriptions.get(rx_id)
    if rx is None:
        raise not_found("prescription not found")
    if rx["status"] != "DRAFT":
        raise invalid_state("only a DRAFT prescription can be approved")
    field = store.fields[rx["field_id"]]
    # OCC: stale view of the field's governing prescription -> 412
    if expected_field_version != field["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_field_version does not match the field's current version", 412)
    # Label gates: buffer compliance, then tank-mix compatibility
    for line in rx["lines"]:
        p = store.products[line["product_id"]]
        if p["required_buffer_ft"] > field["buffer_clearance_ft"]:
            raise ApiError("ERR_BUFFER_VIOLATION",
                           "product %s requires a larger buffer than the field allows" % p["id"], 409)
    has_incompatible, _ = tank_mix_verdicts([l["product_id"] for l in rx["lines"]])
    if has_incompatible:
        raise ApiError("ERR_INCOMPATIBLE_TANK_MIX",
                       "a line pair carries verdict INCOMPATIBLE", 409)
    # Side effects: supersede the previously APPROVED rx for same field+season
    for other in store.prescriptions.values():
        if (other["id"] != rx["id"]
                and other["field_id"] == rx["field_id"]
                and other["season_year"] == rx["season_year"]
                and other["status"] == "APPROVED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    # Approval changes the field's governing prescription
    touch(field)
    rx["status"] = "APPROVED"
    touch(rx)
    return ok(serialize("prescription", rx))
