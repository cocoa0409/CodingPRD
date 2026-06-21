"""Customer, Pet, and Vaccination routes."""
from flask import Blueprint, request

import db
import models
import validate as V
from middleware import get_identity, require_role
from errors import err, ERR_INVALID_REQUEST, ERR_VALIDATION
import lookup
from response import object_response, array_response
from services import reconcile

bp = Blueprint("customers", __name__)

COAT_CONDITIONS = {"NORMAL", "MATTED"}
BEHAVIORAL_FLAGS = {"CALM", "NERVOUS", "AGGRESSIVE"}
VACCINE_TYPES = {"RABIES", "BORDETELLA", "DISTEMPER"}


def _check_unique(store, field, value):
    for r in store.values():
        if r.get(field) == value:
            raise err(ERR_INVALID_REQUEST, "%s must be unique: %s" % (field, value))


# ---- Customer ----
@bp.route("/customers", methods=["POST"])
def create_customer():
    _, role = get_identity()
    require_role(role, {"PlatformAdmin", "Customer"})
    body = V.require_body(request.get_json(silent=True))
    email = V.require_str(body, "email")
    full_name = V.require_str(body, "full_name")
    service_zip = V.require_zip(body, "service_zip")
    _check_unique(db.customers, "email", email)
    rec = models.base_versioned()
    rec.update({
        "email": email, "full_name": full_name, "service_zip": service_zip,
        "no_show_strikes": 0, "account_status": "ACTIVE", "outstanding_fee_cents": 0,
    })
    db.customers[rec["id"]] = rec
    return object_response(models.ser_customer(rec), 201)


@bp.route("/customers/<rid>", methods=["GET"])
def get_customer(rid):
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer"})
    rec = lookup.get_customer(rid)
    if role == "Customer":
        lookup.forbid_unless(uid == rec["id"])
    return object_response(models.ser_customer(rec), 200)


@bp.route("/customers/<rid>/pets", methods=["GET"])
def list_customer_pets(rid):
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer"})
    cust = lookup.get_customer(rid)
    if role == "Customer":
        lookup.forbid_unless(uid == cust["id"])
    limit, offset = V.parse_pagination(request.args)
    items = [p for p in db.pets.values() if p["customer_id"] == cust["id"]]
    page, total = V.paginate(items, limit, offset)
    return array_response([models.ser_pet(p) for p in page], limit, offset, total, 200)


@bp.route("/customers/<rid>/fee-charges", methods=["GET"])
def list_customer_fees(rid):
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer"})
    cust = lookup.get_customer(rid)
    if role == "Customer":
        lookup.forbid_unless(uid == cust["id"])
    limit, offset = V.parse_pagination(request.args)
    items = [f for f in db.fee_charges.values() if f["customer_id"] == cust["id"]]
    page, total = V.paginate(items, limit, offset)
    return array_response([models.ser_fee_charge(f) for f in page], limit, offset, total, 200)


# ---- Pet ----
@bp.route("/pets", methods=["POST"])
def create_pet():
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Customer"})
    body = V.require_body(request.get_json(silent=True))
    customer_id = V.require_str(body, "customer_id")
    breed_id = V.require_str(body, "breed_id")
    name = V.require_str(body, "name")
    weight_lbs = V.require_number(body, "weight_lbs", exclusive_min=0)
    coat_condition = V.opt_enum(body, "coat_condition", COAT_CONDITIONS, "NORMAL")
    behavioral_flag = V.opt_enum(body, "behavioral_flag", BEHAVIORAL_FLAGS, "CALM")
    # existence (FK body fields)
    cust = lookup.get_customer(customer_id)
    lookup.get_breed(breed_id)
    if role == "Customer":
        lookup.forbid_unless(uid == cust["id"])
    rec = models.base_versioned()
    rec.update({
        "customer_id": customer_id, "breed_id": breed_id, "name": name,
        "weight_lbs": weight_lbs, "coat_condition": coat_condition,
        "behavioral_flag": behavioral_flag,
        "muzzle_required": (behavioral_flag == "AGGRESSIVE"),
        "vaccination_status": "EXPIRED",
    })
    db.pets[rec["id"]] = rec
    return object_response(models.ser_pet(rec), 201)


@bp.route("/pets/<rid>", methods=["GET"])
def get_pet(rid):
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer", "Groomer"})
    rec = lookup.get_pet(rid)
    if role == "Customer":
        lookup.forbid_unless(uid == rec["customer_id"])
    return object_response(models.ser_pet(rec), 200)


@bp.route("/pets", methods=["GET"])
def list_pets():
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer"})
    limit, offset = V.parse_pagination(request.args)
    customer_id = request.args.get("customer_id")
    breed_id = request.args.get("breed_id")
    items = list(db.pets.values())
    if customer_id:
        items = [p for p in items if p["customer_id"] == customer_id]
    if breed_id:
        items = [p for p in items if p["breed_id"] == breed_id]
    if role == "Customer":
        items = [p for p in items if p["customer_id"] == uid]
    page, total = V.paginate(items, limit, offset)
    return array_response([models.ser_pet(p) for p in page], limit, offset, total, 200)


@bp.route("/pets/<rid>", methods=["PATCH"])
def update_pet(rid):
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Customer"})
    rec = lookup.get_pet(rid)
    if role == "Customer":
        lookup.forbid_unless(uid == rec["customer_id"])
    body = V.require_body(request.get_json(silent=True))
    if "coat_condition" in body and body["coat_condition"] is not None:
        rec["coat_condition"] = V.require_enum(body, "coat_condition", COAT_CONDITIONS)
    if "behavioral_flag" in body and body["behavioral_flag"] is not None:
        rec["behavioral_flag"] = V.require_enum(body, "behavioral_flag", BEHAVIORAL_FLAGS)
        reconcile.reconcile_muzzle(rec)
    if "weight_lbs" in body and body["weight_lbs"] is not None:
        rec["weight_lbs"] = V.require_number(body, "weight_lbs", exclusive_min=0)
    models.touch(rec)
    return object_response(models.ser_pet(rec), 200)


# ---- Vaccination ----
@bp.route("/pets/<rid>/vaccinations", methods=["GET"])
def list_vaccinations(rid):
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer"})
    pet = lookup.get_pet(rid)
    if role == "Customer":
        lookup.forbid_unless(uid == pet["customer_id"])
    limit, offset = V.parse_pagination(request.args)
    items = [v for v in db.vaccination_records.values() if v["pet_id"] == pet["id"]]
    page, total = V.paginate(items, limit, offset)
    return array_response([models.ser_vaccination(v) for v in page], limit, offset, total, 200)


@bp.route("/pets/<rid>/vaccinations", methods=["POST"])
def create_vaccination(rid):
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Customer"})
    pet = lookup.get_pet(rid)
    if role == "Customer":
        lookup.forbid_unless(uid == pet["customer_id"])
    body = V.require_body(request.get_json(silent=True))
    vaccine_type = V.require_enum(body, "vaccine_type", VACCINE_TYPES)
    issued_raw = V.require_field(body, "issued_on")
    expires_raw = V.require_field(body, "expires_on")
    from util import parse_dt
    issued_on = parse_dt(issued_raw, "issued_on")
    expires_on = parse_dt(expires_raw, "expires_on")
    # field-relationship invariant: expires strictly after issued -> ERR_VALIDATION
    if not (expires_on > issued_on):
        raise err(ERR_VALIDATION, "expires_on must be strictly after issued_on")
    rec = models.base_immutable()
    rec.update({
        "pet_id": pet["id"], "vaccine_type": vaccine_type,
        "issued_on": issued_on, "expires_on": expires_on,
    })
    db.vaccination_records[rec["id"]] = rec
    # reconcile pet vaccination_status + bump pet version
    reconcile.recompute_vaccination_status(pet)
    models.touch(pet)
    return object_response(models.ser_vaccination(rec), 201)
