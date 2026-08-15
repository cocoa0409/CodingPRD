"""Unit endpoints (PRD 3.1)."""
from flask import Blueprint, request

import store
from auth import authenticate, authorize, ALL_ROLES
from serializers import unit_out
from util import body_json, fk_ref, get_or_404, list_response, new_record, \
    req_enum, req_str, success_object

bp = Blueprint("units", __name__)

UNIT_TIERS = ["CRITICAL", "STANDARD"]


@bp.route("/units", methods=["POST"])
def create_unit():
    _, role = authenticate()
    authorize(role, ["LinenManager"])
    body = body_json()

    fac = fk_ref(body, "facility_id", store.facilities, "Facility")
    name = req_str(body, "name")
    tier = req_enum(body, "unit_tier", UNIT_TIERS)

    rec = new_record()
    rec.update({
        "facility_id": fac["id"],
        "name": name,
        "unit_tier": tier,
    })
    store.units[rec["id"]] = rec
    return success_object(unit_out(rec), 201)


@bp.route("/units/<unit_id>", methods=["GET"])
def get_unit(unit_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.units, unit_id, "Unit")
    return success_object(unit_out(rec))


@bp.route("/units", methods=["GET"])
def list_units():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.units.values())
    facility_id = request.args.get("facility_id")
    if facility_id is not None:
        records = [r for r in records if r["facility_id"] == facility_id]
    unit_tier = request.args.get("unit_tier")
    if unit_tier is not None:
        records = [r for r in records if r["unit_tier"] == unit_tier]
    return list_response(records, unit_out)
