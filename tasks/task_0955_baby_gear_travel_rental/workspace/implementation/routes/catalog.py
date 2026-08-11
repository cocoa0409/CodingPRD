from flask import Blueprint, request

import calc
from db import bump, create_rec, sorted_ords, store
from errors import ApiError
from middleware import body, require_roles
from response import ok_obj, paginate
from serialize import ser_catalog_item, ser_recall
from util import parse_date
from validate import opt_enum, opt_int, opt_num, opt_str, req_enum, req_int, req_num, req_str

bp = Blueprint("catalog", __name__)

CATEGORIES = ("CRIB", "STROLLER", "CARSEAT")


def _get_item(iid):
    i = store.catalog_items.get(iid)
    if i is None:
        raise ApiError("ERR_CATALOG_ITEM_NOT_FOUND", 404, "Catalog item not found")
    return i


def _validate_spec(b, partial):
    """Returns dict of validated fields. Non-positive rate/deposit/weight is a
    shape violation -> ERR_INVALID_REQUEST (400) per PRD section 3.1."""
    out = {}
    get_str = opt_str if partial else req_str
    get_enum = opt_enum if partial else req_enum
    get_int = opt_int if partial else req_int
    get_num = opt_num if partial else req_num
    name = get_str(b, "name")
    if name is not None:
        out["name"] = name
    if not partial or "category" in b:
        out["category"] = get_enum(b, "category", CATEGORIES)
    rate = get_int(b, "daily_rate_cents")
    if rate is not None:
        if rate <= 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "daily_rate_cents must be > 0")
        out["daily_rate_cents"] = rate
    dep = get_int(b, "deposit_amount_cents")
    if dep is not None:
        if dep <= 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "deposit_amount_cents must be > 0")
        out["deposit_amount_cents"] = dep
    weight = get_num(b, "weight_kg")
    if weight is not None:
        if weight <= 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "weight_kg must be > 0")
        out["weight_kg"] = weight
    cth = get_int(b, "cleaning_turnaround_hours")
    if cth is not None:
        if cth < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "cleaning_turnaround_hours must be >= 0")
        out["cleaning_turnaround_hours"] = cth
    dec = get_int(b, "deep_clean_every_cycles")
    if dec is not None:
        if dec < 1:
            raise ApiError("ERR_INVALID_REQUEST", 400, "deep_clean_every_cycles must be >= 1")
        out["deep_clean_every_cycles"] = dec
    return out


@bp.post("/catalog-items")
def create_item():
    require_roles("OperationsAdmin")
    spec = _validate_spec(body(), partial=False)
    rec = create_rec(store.catalog_items, {**spec, "status": "LISTED"})
    return ok_obj(ser_catalog_item(rec), 201)


@bp.get("/catalog-items/<iid>")
def get_item(iid):
    require_roles("Customer", "HotelPartner", "Inspector", "OperationsAdmin")
    return ok_obj(ser_catalog_item(_get_item(iid)))


@bp.get("/catalog-items")
def list_items():
    require_roles("Customer", "HotelPartner", "Inspector", "OperationsAdmin")
    recs = sorted_ords(list(store.catalog_items.values()))
    category = request.args.get("category")
    if category is not None:
        recs = [i for i in recs if i["category"] == category]
    status = request.args.get("status")
    if status is not None:
        recs = [i for i in recs if i["status"] == status]
    return paginate(recs, ser_catalog_item)


@bp.patch("/catalog-items/<iid>")
def patch_item(iid):
    require_roles("OperationsAdmin")
    item = _get_item(iid)
    spec = _validate_spec(body(), partial=True)
    status = opt_enum(body(), "status", ("LISTED", "DELISTED"))
    if status is not None:
        spec["status"] = status
    item.update(spec)
    bump(item)
    return ok_obj(ser_catalog_item(item))


@bp.get("/catalog-items/<iid>/availability")
def availability(iid):
    require_roles("Customer", "HotelPartner", "OperationsAdmin")
    item = _get_item(iid)
    start = parse_date(request.args.get("start_date"))
    end = parse_date(request.args.get("end_date"))
    if start is None or end is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "start_date and end_date (YYYY-MM-DD) are required")
    if end <= start:
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "end_date must be after start_date")
    return ok_obj({
        "catalog_item_id": item["id"],
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "available_count": calc.availability_count(item["id"], start, end),
    })


@bp.get("/catalog-items/<iid>/recalls")
def item_recalls(iid):
    require_roles("Inspector", "OperationsAdmin")
    item = _get_item(iid)
    recs = sorted_ords([r for r in store.recalls.values()
                        if r["catalog_item_id"] == item["id"]])
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_recall)
