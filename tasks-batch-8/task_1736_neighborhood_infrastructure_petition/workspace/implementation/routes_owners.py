"""PropertyOwner and Parcel endpoints."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import Blueprint, request

import errors
import shape
from envelope import ok_object
from helpers import (get_or_404, list_response, sort_created,
                     sort_parcel_number)
from security import (ALL_ROLES, OWNER_READ_ROLES, STAFF_ROLES, authenticate,
                      require_role)
from serializers import (ser_assessment, ser_objection, ser_owner, ser_parcel,
                         ser_signature)
from store import STORE, new_id, now, touch

bp = Blueprint("owners_parcels", __name__)


def _owner_or_404(oid):
    return get_or_404("owners", oid, errors.OWNER_NOT_FOUND, "Owner not found")


def _parcel_or_404(pid):
    return get_or_404("parcels", pid, errors.PARCEL_NOT_FOUND, "Parcel not found")


# --- owners ---

@bp.route("/owners", methods=["POST"])
def create_owner():
    body = shape.get_body()
    full_name = shape.req_str(body, "full_name")
    email = shape.req_str(body, "email")
    mailing_address = shape.req_str(body, "mailing_address")
    ctx = authenticate()
    require_role(ctx, ["CityClerk"])
    if any(o["email"] == email for o in STORE.owners.values()):
        errors.raise_err(errors.DUPLICATE_OWNER_EMAIL, "Email already registered")
    ts = now()
    o = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "mailing_address": mailing_address,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    STORE.put("owners", o)
    return ok_object(ser_owner(o), 201)


@bp.route("/owners", methods=["GET"])
def list_owners():
    ctx = authenticate()
    require_role(ctx, STAFF_ROLES)
    records = sort_created(list(STORE.owners.values()))
    return list_response(records, ser_owner, paginated=True)


@bp.route("/owners/<oid>", methods=["GET"])
def get_owner(oid):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    o = _owner_or_404(oid)
    return ok_object(ser_owner(o))


@bp.route("/owners/<oid>/parcels", methods=["GET"])
def owner_parcels(oid):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    _owner_or_404(oid)
    records = [p for p in STORE.parcels.values() if p["owner_id"] == oid]
    return list_response(sort_parcel_number(records), ser_parcel, paginated=False)


@bp.route("/owners/<oid>/signatures", methods=["GET"])
def owner_signatures(oid):
    ctx = authenticate()
    require_role(ctx, OWNER_READ_ROLES)
    _owner_or_404(oid)
    records = [s for s in STORE.signatures.values() if s["owner_id"] == oid]
    return list_response(sort_created(records), ser_signature, paginated=False)


@bp.route("/owners/<oid>/objections", methods=["GET"])
def owner_objections(oid):
    ctx = authenticate()
    require_role(ctx, OWNER_READ_ROLES)
    _owner_or_404(oid)
    records = [o for o in STORE.objections.values() if o["owner_id"] == oid]
    return list_response(sort_created(records), ser_objection, paginated=False)


# --- parcels ---

@bp.route("/parcels", methods=["POST"])
def create_parcel():
    body = shape.get_body()
    district_id = shape.req_str(body, "district_id")
    owner_id = shape.req_str(body, "owner_id")
    parcel_number = shape.req_str(body, "parcel_number")
    frontage_raw = shape.req_number(body, "frontage_ft")
    exempt = shape.opt_bool(body, "exempt", False)
    try:
        frontage = Decimal(str(frontage_raw)).quantize(Decimal("0.01"),
                                                       rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        errors.raise_err(errors.INVALID_REQUEST, "frontage_ft must be a number")
    if frontage <= 0:
        errors.raise_err(errors.INVALID_REQUEST, "frontage_ft must be > 0")
    ctx = authenticate()
    require_role(ctx, ["CityClerk"])
    d = get_or_404("districts", district_id, errors.DISTRICT_NOT_FOUND,
                   "District not found")
    _owner_or_404(owner_id)
    if d["status"] != "DRAFT":
        errors.raise_err(errors.DISTRICT_NOT_DRAFT,
                         "Parcels may only be added while the district is DRAFT")
    if any(p["district_id"] == district_id and p["parcel_number"] == parcel_number
           for p in STORE.parcels.values()):
        errors.raise_err(errors.DUPLICATE_PARCEL_NUMBER,
                         "parcel_number already exists within the district")
    ts = now()
    p = {
        "id": new_id(),
        "district_id": district_id,
        "owner_id": owner_id,
        "parcel_number": parcel_number,
        "frontage_ft": str(frontage),
        "exempt": exempt,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    STORE.put("parcels", p)
    touch(d)  # roll totals recomputed (derived at read); district version advances
    return ok_object(ser_parcel(p), 201)


@bp.route("/parcels", methods=["GET"])
def list_parcels():
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    records = list(STORE.parcels.values())
    district_id = request.args.get("district_id")
    owner_id = request.args.get("owner_id")
    if district_id:
        records = [p for p in records if p["district_id"] == district_id]
    if owner_id:
        records = [p for p in records if p["owner_id"] == owner_id]
    return list_response(sort_parcel_number(records), ser_parcel, paginated=True)


@bp.route("/parcels/<pid>", methods=["GET"])
def get_parcel(pid):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    p = _parcel_or_404(pid)
    return ok_object(ser_parcel(p))


@bp.route("/parcels/<pid>/signatures", methods=["GET"])
def parcel_signatures(pid):
    ctx = authenticate()
    require_role(ctx, OWNER_READ_ROLES)
    _parcel_or_404(pid)
    records = [s for s in STORE.signatures.values() if s["parcel_id"] == pid]
    return list_response(sort_created(records), ser_signature, paginated=False)


@bp.route("/parcels/<pid>/assessments", methods=["GET"])
def parcel_assessments(pid):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    _parcel_or_404(pid)
    records = [a for a in STORE.assessments.values() if a["parcel_id"] == pid]
    return list_response(sort_created(records), ser_assessment, paginated=False)


@bp.route("/parcels/<pid>/objections", methods=["GET"])
def parcel_objections(pid):
    ctx = authenticate()
    require_role(ctx, OWNER_READ_ROLES)
    _parcel_or_404(pid)
    records = [o for o in STORE.objections.values() if o["parcel_id"] == pid]
    return list_response(sort_created(records), ser_objection, paginated=False)
