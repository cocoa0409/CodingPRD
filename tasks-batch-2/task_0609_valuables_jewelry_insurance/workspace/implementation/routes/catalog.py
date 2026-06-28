"""Clock + catalog routes: policyholders, risk-zones, repair-shops, appraisals."""
from flask import Blueprint, request

import calc
import clock
import db
import lookups
import reconcile
import response
import serializers
import validators as V
from errors import err
from middleware import get_identity, require_role
from routes.common import paginate_and_respond, assert_appraisal_access

bp = Blueprint("catalog", __name__)


# =============================== Logical clock ===========================
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster"})
    body = V.get_json(request)
    iso = V.require_str(body, "to_iso8601")
    try:
        dt = clock.parse_iso(iso)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO-8601 instant")
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO-8601 instant")
    clock.set_now(dt)
    reconcile.on_clock_advance()
    return response.success({}, status=200)


# =============================== Policyholders ===========================
@bp.route("/policyholders", methods=["POST"])
def create_policyholder():
    _, role = get_identity()
    require_role(role, {"Underwriter"})
    body = V.get_json(request)
    email = V.require_str(body, "email")
    full_name = V.require_str(body, "full_name")
    residence_zip = V.require_zip(body, "residence_zip")
    rec = {
        "id": db.new_id(),
        "email": email,
        "full_name": full_name,
        "residence_zip": residence_zip,
        "status": "ACTIVE",
    }
    db.stamp_create(rec)
    db.policyholders[rec["id"]] = rec
    return response.success(serializers.policyholder(rec), status=201)


@bp.route("/policyholders/<pid>", methods=["GET"])
def get_policyholder(pid):
    _, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster", "Policyholder"})
    rec = lookups.get_policyholder(pid)
    return response.success(serializers.policyholder(rec), status=200)


# =============================== Risk zones ==============================
@bp.route("/risk-zones", methods=["POST"])
def create_risk_zone():
    _, role = get_identity()
    require_role(role, {"Underwriter"})
    body = V.get_json(request)
    zip_prefix = V.require_prefix(body, "zip_prefix")
    risk_band = V.require_enum(body, "risk_band", {"LOW", "MODERATE", "HIGH", "SEVERE"})
    rate = V.require_positive_int(body, "rate_per_thousand_cents")
    cat_loaded = V.opt_bool(body, "catastrophe_loaded", default=False)
    rec = {
        "id": db.new_id(),
        "zip_prefix": zip_prefix,
        "risk_band": risk_band,
        "rate_per_thousand_cents": rate,
        "catastrophe_loaded": cat_loaded,
    }
    # RiskZone is immutable: only id + created_at (no updated_at/version).
    rec["created_at"] = db._wall_now_iso()
    rec["_seq"] = db.next_seq()
    db.risk_zones[rec["id"]] = rec
    return response.success(serializers.risk_zone(rec), status=201)


@bp.route("/risk-zones/<zid>", methods=["GET"])
def get_risk_zone(zid):
    _, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster"})
    rec = lookups.get_risk_zone(zid)
    return response.success(serializers.risk_zone(rec), status=200)


# =============================== Repair shops ============================
@bp.route("/repair-shops", methods=["POST"])
def create_repair_shop():
    _, role = get_identity()
    require_role(role, {"Underwriter"})
    body = V.get_json(request)
    name = V.require_str(body, "name")
    service_zip = V.require_zip(body, "service_zip")
    in_network = V.opt_bool(body, "in_network", default=True)
    rec = {
        "id": db.new_id(),
        "name": name,
        "service_zip": service_zip,
        "in_network": in_network,
        "status": "ACTIVE",
    }
    db.stamp_create(rec)
    db.repair_shops[rec["id"]] = rec
    return response.success(serializers.repair_shop(rec), status=201)


@bp.route("/repair-shops/<sid>", methods=["GET"])
def get_repair_shop(sid):
    _, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster", "RepairShop"})
    rec = lookups.get_repair_shop(sid)
    return response.success(serializers.repair_shop(rec), status=200)


@bp.route("/repair-shops/<sid>/suspend", methods=["POST"])
def suspend_repair_shop(sid):
    _, role = get_identity()
    require_role(role, {"Underwriter"})
    rec = lookups.get_repair_shop(sid)
    rec["status"] = "SUSPENDED"
    db.touch(rec)
    return response.success(serializers.repair_shop(rec), status=200)


# =============================== Appraisals ==============================
@bp.route("/appraisals", methods=["POST"])
def create_appraisal():
    user_id, role = get_identity()
    require_role(role, {"Appraiser", "Underwriter"})
    body = V.get_json(request)
    policyholder_id = V.require_str(body, "policyholder_id")
    appraised_value = V.require_positive_int(body, "appraised_value_cents")
    effective_date = V.require_str(body, "effective_date_iso")
    valid_months = V.opt_positive_int(body, "valid_months", default=36)
    lookups.get_policyholder(policyholder_id)
    rec = {
        "id": db.new_id(),
        "policyholder_id": policyholder_id,
        "appraiser_id": user_id,
        "appraised_value_cents": appraised_value,
        "effective_date_iso": effective_date,
        "valid_months": valid_months,
        "status": "VALID",
    }
    db.stamp_create(rec)
    db.appraisals[rec["id"]] = rec
    return response.success(serializers.appraisal(rec), status=201)


@bp.route("/appraisals/<aid>", methods=["GET"])
def get_appraisal(aid):
    user_id, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster", "Appraiser", "Policyholder"})
    rec = lookups.get_appraisal(aid)
    assert_appraisal_access(rec, user_id, role)
    return response.success(serializers.appraisal(rec), status=200)


@bp.route("/appraisals", methods=["GET"])
def list_appraisals():
    user_id, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster", "Appraiser", "Policyholder"})
    policyholder_id = request.args.get("policyholder_id")
    records = list(db.appraisals.values())
    if policyholder_id is not None:
        records = [r for r in records if r["policyholder_id"] == policyholder_id]
    if role == "Policyholder":
        records = [r for r in records if r["policyholder_id"] == user_id]
    return paginate_and_respond(records, serializers.appraisal)
