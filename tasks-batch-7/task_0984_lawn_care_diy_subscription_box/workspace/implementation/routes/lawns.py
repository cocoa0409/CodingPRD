from flask import Blueprint, request

from db import store, now, next_seq, new_id, touch, Rec
from errors import (
    raise_err, ERR_CUSTOMER_NOT_FOUND, ERR_LAWN_NOT_FOUND, ERR_CUSTOMER_SUSPENDED,
    ERR_LAWN_ARCHIVED, ERR_LAWN_HAS_OPEN_APPLICATIONS, ERR_INVALID_REQUEST,
)
from middleware import get_body, authenticate, check_ownership, paginate, sort_items
from response import ok, ok_list
from serializers import ser_lawn
from util import req_str, req_int, req_enum, fmt_dt3

bp = Blueprint("lawns", __name__)

READ_ROLES = ["Customer", "Agronomist", "FulfillmentOps", "PlatformAdmin"]
GRASS_TYPES = {"COOL_SEASON", "WARM_SEASON", "MIXED"}


def _require_active_customer(customer_id):
    cust = store.customers.get(customer_id)
    if cust is None:
        raise_err(ERR_CUSTOMER_NOT_FOUND, "Customer not found")
    if cust.status == "SUSPENDED":
        raise_err(ERR_CUSTOMER_SUSPENDED, "Customer is SUSPENDED; creates are blocked")
    return cust


@bp.route("/api/lawns", methods=["POST"])
def create_lawn():
    body = get_body()
    customer_id = req_str(body, "customer_id")
    label = req_str(body, "label")
    lawn_size_sqm = req_int(body, "lawn_size_sqm")
    if lawn_size_sqm <= 0:
        raise_err(ERR_INVALID_REQUEST, "Field 'lawn_size_sqm' must be greater than zero")
    grass_type = req_enum(body, "grass_type", GRASS_TYPES)
    region = req_str(body, "region")

    uid, role = authenticate(["Customer"])
    check_ownership(uid, role, customer_id)
    _require_active_customer(customer_id)

    ts = now()
    rec = Rec(
        id=new_id(), created_at=ts, updated_at=ts, version=1, seq=next_seq(),
        customer_id=customer_id, label=label, lawn_size_sqm=lawn_size_sqm,
        grass_type=grass_type, region=region, status="ACTIVE",
    )
    rec.raw["created_at"] = fmt_dt3(ts)
    rec.raw["updated_at"] = fmt_dt3(ts)
    store.lawns[rec.id] = rec
    return ok(ser_lawn(rec), 201)


@bp.route("/api/lawns/<lid>", methods=["GET"])
def get_lawn(lid):
    uid, role = authenticate(READ_ROLES)
    rec = store.lawns.get(lid)
    if rec is None:
        raise_err(ERR_LAWN_NOT_FOUND, "Lawn not found")
    check_ownership(uid, role, rec.customer_id)
    return ok(ser_lawn(rec))


@bp.route("/api/lawns", methods=["GET"])
def list_lawns():
    uid, role = authenticate(READ_ROLES)
    items = list(store.lawns.values())
    if role == "Customer":
        items = [l for l in items if l.customer_id == uid]
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        items = [l for l in items if l.customer_id == customer_id]
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l.status == status]
    items = sort_items(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_lawn(l) for l in page], total, limit, offset)


@bp.route("/api/lawns/<lid>", methods=["PATCH"])
def patch_lawn(lid):
    body = get_body()
    label = body.get("label")
    if label is not None and (not isinstance(label, str) or not label.strip()):
        raise_err(ERR_INVALID_REQUEST, "Field 'label' must be a non-empty string")
    region = body.get("region")
    if region is not None and (not isinstance(region, str) or not region.strip()):
        raise_err(ERR_INVALID_REQUEST, "Field 'region' must be a non-empty string")
    status = body.get("status")
    if status is not None and status != "ARCHIVED":
        raise_err(ERR_INVALID_REQUEST, "Field 'status' may only be set to ARCHIVED")

    uid, role = authenticate(["Customer"])
    rec = store.lawns.get(lid)
    if rec is None:
        raise_err(ERR_LAWN_NOT_FOUND, "Lawn not found")
    check_ownership(uid, role, rec.customer_id)

    if status == "ARCHIVED":
        if rec.status != "ACTIVE":
            raise_err(ERR_LAWN_ARCHIVED, "Operation requires an ACTIVE lawn")
        open_tasks = [
            t for t in store.applications.values()
            if t.lawn_id == lid and t.status in ("SCHEDULED", "FROZEN", "AWAITING_DELIVERY")
        ]
        if open_tasks:
            raise_err(ERR_LAWN_HAS_OPEN_APPLICATIONS,
                      "Archive blocked by open application tasks on this lawn")
        rec.status = "ARCHIVED"
    if label is not None:
        rec.label = label.strip()
    if region is not None:
        rec.region = region.strip()
    touch(rec)
    return ok(ser_lawn(rec))
