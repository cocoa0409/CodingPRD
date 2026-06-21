"""Provisioning config: corporate accounts, affiliates, vehicle classes,
vehicles, chauffeurs, and the deterministic clock (PRD §3.1, §3.9)."""
from flask import Blueprint

import db
import views
from db import new_full, touch
from errors import (
    ERR_DUPLICATE_CLASS_CODE,
    ERR_DUPLICATE_PLATE,
    ERR_INVALID_STATE,
    ERR_VALIDATION_RANGE,
    err,
)
from helpers import (
    as_int,
    as_number,
    as_str,
    get_pagination,
    paginate,
    require_fields,
    serialize,
    sort_by_created,
)
from middleware import authenticate, require_role
from response import success
from routes.common import get_body, must_exist

bp = Blueprint("config", __name__)


def _opt_int(body, field, default):
    if body.get(field) is None:
        return default
    return as_int(body[field], field)


def _opt_number(body, field, default):
    if body.get(field) is None:
        return default
    return as_number(body[field], field)


def _check_nonneg(value, field):
    if value < 0:
        raise err(ERR_VALIDATION_RANGE, f"{field} must be zero or greater")


# --------------------------------------------------------------------------- #
# CorporateAccount
# --------------------------------------------------------------------------- #
@bp.route("/corporate-accounts", methods=["POST"])
def create_corporate_account():
    _, role = authenticate()
    require_role(role, ["DispatchAdmin"])
    body = get_body()
    require_fields(body, ["company_name", "billing_email"])
    company_name = as_str(body["company_name"], "company_name")
    billing_email = as_str(body["billing_email"], "billing_email")

    discount = _opt_number(body, "negotiated_discount_pct", 0)
    gratuity = _opt_number(body, "default_gratuity_pct", 20)
    grace = _opt_int(body, "cancellation_grace_minutes", 120)

    # Range checks (PRD §3.1, ERR_VALIDATION_RANGE).
    if not (0 <= discount <= 40):
        raise err(ERR_VALIDATION_RANGE, "negotiated_discount_pct must be between 0 and 40")
    if not (0 <= gratuity <= 30):
        raise err(ERR_VALIDATION_RANGE, "default_gratuity_pct must be between 0 and 30")
    if grace < 0:
        raise err(ERR_VALIDATION_RANGE, "cancellation_grace_minutes must be zero or greater")

    rec = new_full({
        "company_name": company_name,
        "billing_email": billing_email,
        "negotiated_discount_pct": discount,
        "default_gratuity_pct": gratuity,
        "cancellation_grace_minutes": grace,
        "status": "ACTIVE",
        "outstanding_balance_cents": 0,
    })
    db.corporate_accounts[rec["id"]] = rec
    return success(views.corporate_account(rec), status=201)


@bp.route("/corporate-accounts/<account_id>", methods=["GET"])
def get_corporate_account(account_id):
    _, role = authenticate()
    require_role(role, ["DispatchAdmin", "Dispatcher", "CorporateBooker"])
    rec = must_exist(db.corporate_accounts, account_id, "CorporateAccount")
    # Ownership: a CorporateBooker may only read their own account (PRD §2.1).
    _enforce_account_ownership(role, account_id)
    return success(views.corporate_account(rec))


def _enforce_account_ownership(role, account_id):
    from flask import request

    from errors import ERR_FORBIDDEN
    if role == "CorporateBooker":
        if request.headers.get("X-User-ID") != account_id:
            raise err(ERR_FORBIDDEN, "Booker may only act on its own account")


@bp.route("/corporate-accounts/<account_id>/suspend", methods=["POST"])
def suspend_corporate_account(account_id):
    _, role = authenticate()
    require_role(role, ["DispatchAdmin"])
    rec = must_exist(db.corporate_accounts, account_id, "CorporateAccount")
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Account is not ACTIVE")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success(views.corporate_account(rec))


# --------------------------------------------------------------------------- #
# Affiliate
# --------------------------------------------------------------------------- #
@bp.route("/affiliates", methods=["POST"])
def create_affiliate():
    _, role = authenticate()
    require_role(role, ["DispatchAdmin"])
    body = get_body()
    require_fields(body, ["name", "market_code", "payout_share_pct"])
    name = as_str(body["name"], "name")
    market_code = as_str(body["market_code"], "market_code")
    payout = as_number(body["payout_share_pct"], "payout_share_pct")
    if not (0 <= payout <= 90):
        raise err(ERR_VALIDATION_RANGE, "payout_share_pct must be between 0 and 90")
    rec = new_full({
        "name": name,
        "market_code": market_code,
        "payout_share_pct": payout,
        "status": "ACTIVE",
        "open_farmouts": 0,
    })
    db.affiliates[rec["id"]] = rec
    return success(views.affiliate(rec), status=201)


@bp.route("/affiliates/<affiliate_id>", methods=["GET"])
def get_affiliate(affiliate_id):
    _, role = authenticate()
    require_role(role, ["DispatchAdmin", "Dispatcher", "AffiliatePartner"])
    rec = must_exist(db.affiliates, affiliate_id, "Affiliate")
    from flask import request

    from errors import ERR_FORBIDDEN
    if role == "AffiliatePartner" and request.headers.get("X-User-ID") != affiliate_id:
        raise err(ERR_FORBIDDEN, "Partner may only act on its own affiliate")
    return success(views.affiliate(rec))


@bp.route("/affiliates/<affiliate_id>/suspend", methods=["POST"])
def suspend_affiliate(affiliate_id):
    _, role = authenticate()
    require_role(role, ["DispatchAdmin"])
    rec = must_exist(db.affiliates, affiliate_id, "Affiliate")
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Affiliate is not ACTIVE")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success(views.affiliate(rec))


# --------------------------------------------------------------------------- #
# VehicleClass
# --------------------------------------------------------------------------- #
@bp.route("/vehicle-classes", methods=["POST"])
def create_vehicle_class():
    _, role = authenticate()
    require_role(role, ["DispatchAdmin"])
    body = get_body()
    require_fields(body, ["code", "base_fare_cents", "per_mile_cents",
                          "hourly_rate_cents", "wait_per_minute_cents"])
    code = as_str(body["code"], "code")
    base_fare = as_int(body["base_fare_cents"], "base_fare_cents")
    per_mile = as_int(body["per_mile_cents"], "per_mile_cents")
    hourly = as_int(body["hourly_rate_cents"], "hourly_rate_cents")
    wait_per_min = as_int(body["wait_per_minute_cents"], "wait_per_minute_cents")
    included_wait = _opt_int(body, "included_wait_minutes", 15)

    # All four rate fields and the wait grace must be zero or greater (PRD §3.1).
    for value, field in [(base_fare, "base_fare_cents"), (per_mile, "per_mile_cents"),
                         (hourly, "hourly_rate_cents"), (wait_per_min, "wait_per_minute_cents"),
                         (included_wait, "included_wait_minutes")]:
        _check_nonneg(value, field)

    # code unique among non-SUSPENDED classes (PRD §3.1, ERR_DUPLICATE_CLASS_CODE).
    for existing in db.vehicle_classes.values():
        if existing["status"] != "SUSPENDED" and existing["code"] == code:
            raise err(ERR_DUPLICATE_CLASS_CODE, "VehicleClass code already in use")

    rec = new_full({
        "code": code,
        "base_fare_cents": base_fare,
        "per_mile_cents": per_mile,
        "hourly_rate_cents": hourly,
        "included_wait_minutes": included_wait,
        "wait_per_minute_cents": wait_per_min,
        "status": "ACTIVE",
    })
    db.vehicle_classes[rec["id"]] = rec
    return success(views.vehicle_class(rec), status=201)


# --------------------------------------------------------------------------- #
# Vehicle
# --------------------------------------------------------------------------- #
@bp.route("/vehicles", methods=["POST"])
def create_vehicle():
    _, role = authenticate()
    require_role(role, ["DispatchAdmin"])
    body = get_body()
    require_fields(body, ["vehicle_class_id", "plate"])
    vehicle_class_id = as_str(body["vehicle_class_id"], "vehicle_class_id")
    plate = as_str(body["plate"], "plate")
    turnaround = _opt_int(body, "turnaround_minutes", 30)

    # Existence of body FK (PRD §2.5).
    must_exist(db.vehicle_classes, vehicle_class_id, "VehicleClass")
    _check_nonneg(turnaround, "turnaround_minutes")

    # plate unique across all vehicles (PRD §3.1, ERR_DUPLICATE_PLATE).
    for existing in db.vehicles.values():
        if existing["plate"] == plate:
            raise err(ERR_DUPLICATE_PLATE, "Vehicle plate already in use")

    rec = new_full({
        "vehicle_class_id": vehicle_class_id,
        "plate": plate,
        "turnaround_minutes": turnaround,
        "status": "AVAILABLE",
    })
    db.vehicles[rec["id"]] = rec
    return success(views.vehicle(rec), status=201)


@bp.route("/vehicles/<vehicle_id>", methods=["GET"])
def get_vehicle(vehicle_id):
    _, role = authenticate()
    require_role(role, ["DispatchAdmin", "Dispatcher"])
    rec = must_exist(db.vehicles, vehicle_id, "Vehicle")
    return success(views.vehicle(rec))


@bp.route("/vehicles", methods=["GET"])
def list_vehicles():
    from flask import request
    _, role = authenticate()
    require_role(role, ["DispatchAdmin", "Dispatcher"])
    limit, offset = get_pagination(request.args)
    vclass = request.args.get("vehicle_class_id")
    items = list(db.vehicles.values())
    if vclass is not None:
        items = [v for v in items if v["vehicle_class_id"] == vclass]
    items = sort_by_created(items)
    window, pagination = paginate(items, limit, offset)
    return success([views.vehicle(v) for v in window], pagination=pagination)


# --------------------------------------------------------------------------- #
# Chauffeur
# --------------------------------------------------------------------------- #
@bp.route("/chauffeurs", methods=["POST"])
def create_chauffeur():
    _, role = authenticate()
    require_role(role, ["DispatchAdmin"])
    body = get_body()
    require_fields(body, ["full_name", "home_market_code"])
    full_name = as_str(body["full_name"], "full_name")
    home_market = as_str(body["home_market_code"], "home_market_code")
    rest_buffer = _opt_int(body, "rest_buffer_minutes", 20)
    _check_nonneg(rest_buffer, "rest_buffer_minutes")
    rec = new_full({
        "full_name": full_name,
        "home_market_code": home_market,
        "rest_buffer_minutes": rest_buffer,
        "status": "OFF_DUTY",
        "active_assignment_id": None,
    })
    db.chauffeurs[rec["id"]] = rec
    return success(views.chauffeur(rec), status=201)


@bp.route("/chauffeurs/<chauffeur_id>", methods=["GET"])
def get_chauffeur(chauffeur_id):
    from flask import request

    from errors import ERR_FORBIDDEN
    _, role = authenticate()
    require_role(role, ["DispatchAdmin", "Dispatcher", "Chauffeur"])
    rec = must_exist(db.chauffeurs, chauffeur_id, "Chauffeur")
    if role == "Chauffeur" and request.headers.get("X-User-ID") != chauffeur_id:
        raise err(ERR_FORBIDDEN, "Chauffeur may only read their own record")
    return success(views.chauffeur(rec))


# --------------------------------------------------------------------------- #
# Clock
# --------------------------------------------------------------------------- #
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, ["DispatchAdmin"])
    body = get_body()
    require_fields(body, ["to_iso8601"])
    from helpers import parse_dt
    to_iso = as_str(body["to_iso8601"], "to_iso8601")
    parse_dt(to_iso, "to_iso8601")  # validate shape
    db.clock["current_utc"] = to_iso
    return success(views.clock_state(db.clock))
