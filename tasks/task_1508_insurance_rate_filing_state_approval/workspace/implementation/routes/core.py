"""Logical clock, Products, StateRegulatoryProfiles."""
from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from envelope import list_response, serialize, success
from errors import err, ERR_DUPLICATE_PROFILE, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from fields import PRODUCT, STATE_PROFILE
from store import db
from timeutil import fmt_ts
from validate import (
    apply_filters, get_json_body, paginate, v_enum, v_int, v_nonneg_int,
    v_nonneg_number, v_state_code, v_string, v_timestamp, validate_body,
)
from workflows import base_entity, get_or_404, run_sweep
from store import touch

bp = Blueprint("core", __name__)


# --- logical clock -------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate({"PlatformAdmin"})
    body = get_json_body(required=True)
    data = validate_body(body, {"to_iso8601": (True, v_timestamp)})
    with db.lock:
        db.clock = data["to_iso8601"]
        run_sweep()
    return success({"current_utc": fmt_ts(db.clock)}, code=200)


# --- products -------------------------------------------------------------------

@bp.route("/products", methods=["POST"])
def create_product():
    authenticate({"ProductActuary"})
    body = get_json_body(required=True)
    data = validate_body(body, {
        "product_code": (True, v_string),
        "name": (True, v_string),
    })
    with db.lock:
        for p in db.products.values():
            if p["product_code"] == data["product_code"]:
                raise err(ERR_INVALID_REQUEST)
        product = base_entity()
        product.update({
            "product_code": data["product_code"],
            "name": data["name"],
            "current_locked_indication_id": None,
        })
        db.products[product["id"]] = product
    return success(serialize(product, PRODUCT), code=201)


@bp.route("/products/<productId>", methods=["GET"])
def get_product(productId):
    authenticate(ALL_ROLES)
    product = get_or_404(db.products, productId)
    return success(serialize(product, PRODUCT), code=200)


# --- state regulatory profiles ---------------------------------------------------

FILING_METHODS = {"PRIOR_APPROVAL", "FILE_AND_USE", "USE_AND_FILE"}


@bp.route("/state-profiles", methods=["POST"])
def create_profile():
    authenticate({"ComplianceOfficer"})
    body = get_json_body(required=True)
    data = validate_body(body, {
        "product_id": (True, v_string),
        "state_code": (True, v_state_code),
        "filing_method": (True, v_enum(FILING_METHODS)),
        "min_effective_lead_days": (True, v_nonneg_int),
        "objection_response_sla_days": (True, v_nonneg_int),
        "deemer_days": (True, v_nonneg_int),
        "max_single_change_pct": (True, v_nonneg_number),
        "renewal_notice_days": (True, v_nonneg_int),
        "disapproval_window_days": (True, v_nonneg_int),
    })
    with db.lock:
        # existence: body FK product_id
        get_or_404(db.products, data["product_id"])
        # structural: one profile per (product_id, state_code)
        for p in db.state_profiles.values():
            if p["product_id"] == data["product_id"] and p["state_code"] == data["state_code"]:
                raise err(ERR_DUPLICATE_PROFILE)
        profile = base_entity()
        profile.update({
            "product_id": data["product_id"],
            "state_code": data["state_code"],
            "filing_method": data["filing_method"],
            "min_effective_lead_days": data["min_effective_lead_days"],
            "objection_response_sla_days": data["objection_response_sla_days"],
            "deemer_days": data["deemer_days"],
            "max_single_change_pct": data["max_single_change_pct"],
            "renewal_notice_days": data["renewal_notice_days"],
            "disapproval_window_days": data["disapproval_window_days"],
            "status": "ACTIVE",
        })
        db.state_profiles[profile["id"]] = profile
    return success(serialize(profile, STATE_PROFILE), code=201)


@bp.route("/state-profiles/<profileId>", methods=["GET"])
def get_profile(profileId):
    authenticate(ALL_ROLES)
    profile = get_or_404(db.state_profiles, profileId)
    return success(serialize(profile, STATE_PROFILE), code=200)


@bp.route("/state-profiles", methods=["GET"])
def list_profiles():
    authenticate(ALL_ROLES)
    filters = {
        "product_id": request.args.get("product_id"),
        "state_code": request.args.get("state_code"),
        "status": request.args.get("status"),
    }
    items = apply_filters(list(db.state_profiles.values()), filters)
    page, total, limit, offset = paginate(items)
    return list_response([serialize(p, STATE_PROFILE) for p in page], total, limit, offset)


@bp.route("/state-profiles/<profileId>/suspend", methods=["POST"])
def suspend_profile(profileId):
    authenticate({"ComplianceOfficer"})
    with db.lock:
        profile = get_or_404(db.state_profiles, profileId)
        if profile["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE)
        profile["status"] = "SUSPENDED"
        touch(profile)
    return success(serialize(profile, STATE_PROFILE), code=200)


@bp.route("/state-profiles/<profileId>/reactivate", methods=["POST"])
def reactivate_profile(profileId):
    authenticate({"ComplianceOfficer"})
    with db.lock:
        profile = get_or_404(db.state_profiles, profileId)
        if profile["status"] != "SUSPENDED":
            raise err(ERR_INVALID_STATE)
        profile["status"] = "ACTIVE"
        touch(profile)
    return success(serialize(profile, STATE_PROFILE), code=200)
