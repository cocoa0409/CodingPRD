"""Medical exemptions."""
from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination
from models import stamp_create, serialize, touch
from response import success, success_list
from services import common

bp = Blueprint("exemptions", __name__)


@bp.route("/medical-exemptions", methods=["POST"])
def create_exemption():
    user_id, role = get_identity()
    require_role(role, {"Customer", "ComplianceOfficer"})
    body = get_json_body()
    vehicle_profile_id = common.require_string(body, "vehicle_profile_id")
    certificate_ref = common.require_string(body, "certificate_ref")
    exempt_min_vlt_pct = common.require_int(body, "exempt_min_vlt_pct")
    if exempt_min_vlt_pct < 0 or exempt_min_vlt_pct > 100:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "exempt_min_vlt_pct must be between 0 and 100.")

    vehicle = common.get_or_404(db.vehicle_profiles, vehicle_profile_id)
    common.check_customer_owns_vehicle(role, user_id, vehicle)

    rec = {
        "vehicle_profile_id": vehicle_profile_id,
        "certificate_ref": certificate_ref,
        "exempt_min_vlt_pct": exempt_min_vlt_pct,
        "status": "PENDING",
    }
    stamp_create(rec)
    db.medical_exemptions[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/medical-exemptions/<rid>", methods=["GET"])
def get_exemption(rid):
    user_id, role = get_identity()
    require_role(role, {"ComplianceOfficer", "Customer", "ShopManager"})
    rec = common.get_or_404(db.medical_exemptions, rid)
    if role == "Customer":
        vehicle = db.vehicle_profiles.get(rec["vehicle_profile_id"])
        common.check_customer_owns_vehicle(role, user_id, vehicle)
    return success(serialize(rec), 200)


@bp.route("/medical-exemptions/<rid>/approve", methods=["POST"])
def approve_exemption(rid):
    user_id, role = get_identity()
    require_role(role, {"ComplianceOfficer"})
    rec = common.get_or_404(db.medical_exemptions, rid)
    if rec["status"] != "PENDING":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Exemption is not PENDING.")
    rec["status"] = "APPROVED"
    touch(rec)
    return success(serialize(rec), 200)


@bp.route("/medical-exemptions/<rid>/reject", methods=["POST"])
def reject_exemption(rid):
    user_id, role = get_identity()
    require_role(role, {"ComplianceOfficer"})
    rec = common.get_or_404(db.medical_exemptions, rid)
    if rec["status"] != "PENDING":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Exemption is not PENDING.")
    rec["status"] = "REJECTED"
    touch(rec)
    return success(serialize(rec), 200)


@bp.route("/medical-exemptions", methods=["GET"])
def list_exemptions():
    user_id, role = get_identity()
    require_role(role, {"ComplianceOfficer", "Customer", "ShopManager"})
    limit, offset = parse_pagination()
    from flask import request
    vehicle_filter = request.args.get("vehicle_profile_id")

    items = list(db.medical_exemptions.values())
    if vehicle_filter is not None:
        items = [e for e in items if e["vehicle_profile_id"] == vehicle_filter]
    if role == "Customer":
        owned = {v["id"] for v in db.vehicle_profiles.values() if v["customer_user_id"] == user_id}
        items = [e for e in items if e["vehicle_profile_id"] in owned]

    items.sort(key=lambda e: (e["created_at"], e["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(e) for e in page], limit, offset, total, 200)
