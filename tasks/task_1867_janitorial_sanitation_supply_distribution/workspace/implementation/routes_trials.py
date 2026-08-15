"""Trial program endpoints."""
from flask import Blueprint, request

import clock
import db
import services as svc
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_VALIDATION, ERR_TRIAL_ALREADY_ACTIVE,
    ERR_FACILITY_INACTIVE, not_found,
)
from middleware import require_roles, check_facility_ownership
from response import success_object, success_list
from routes_facilities import get_facility_or_404
from routes_products import get_product_or_404
from routes_orders import create_order_record

bp = Blueprint("trial_programs", __name__)

READ_ROLES = ("DistributorAdmin", "SalesRep", "FacilityManager")


def _pagination():
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise ApiError(ERR_VALIDATION, "limit/offset must be integers", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(ERR_VALIDATION, "limit must be 1..100, offset >= 0", 400)
    return limit, offset


@bp.post("/jansan/trial-programs")
def create_trial():
    require_roles("SalesRep")
    body = request.get_json(silent=True) or {}
    facility_id = svc.as_str(svc.require_field(body, "facility_id"), "facility_id")
    product_id = svc.as_str(svc.require_field(body, "product_id"), "product_id")
    get_facility_or_404(facility_id)
    get_product_or_404(product_id)
    ts = svc.as_datetime(svc.require_field(body, "trial_start"), "trial_start")
    te = svc.as_datetime(svc.require_field(body, "trial_end"), "trial_end")
    if te < ts:
        raise ApiError(ERR_VALIDATION, "trial_end must be >= trial_start", 400)
    sample_value = svc.as_int(svc.require_field(body, "sample_value_cents"), "sample_value_cents", minimum=0)
    # single ACTIVE trial per (facility, product)
    for t in db.trial_programs.values():
        if (t["facility_id"] == facility_id and t["product_id"] == product_id
                and t["status"] == "ACTIVE"):
            raise ApiError(ERR_TRIAL_ALREADY_ACTIVE,
                           "An ACTIVE trial already exists for this facility+product", 409)
    t = svc.base_resource()
    t.update({
        "facility_id": facility_id,
        "product_id": product_id,
        "trial_start": clock.iso_format(ts),
        "trial_end": clock.iso_format(te),
        "sample_value_cents": sample_value,
        "status": "ACTIVE",
        "conversion_order_id": None,
        "conversion_credit_cents": 0,
    })
    db.trial_programs[t["id"]] = t
    return success_object(dict(t), 201)


def get_trial_or_404(trial_id):
    t = db.trial_programs.get(trial_id)
    if t is None:
        raise not_found("Trial program not found")
    return t


@bp.get("/jansan/trial-programs/<trial_program_id>")
def get_trial(trial_program_id):
    user_id, role = require_roles(*READ_ROLES)
    t = get_trial_or_404(trial_program_id)
    check_facility_ownership(user_id, role, t["facility_id"])
    return success_object(dict(t))


@bp.get("/jansan/trial-programs")
def list_trials():
    user_id, role = require_roles(*READ_ROLES)
    facility_id = request.args.get("facility_id")
    product_id = request.args.get("product_id")
    conversion_order_id = request.args.get("conversion_order_id")
    status = request.args.get("status")
    limit, offset = _pagination()
    items = list(db.trial_programs.values())
    if role == "FacilityManager":
        items = [t for t in items if t["facility_id"] == user_id]
    if facility_id:
        items = [t for t in items if t["facility_id"] == facility_id]
    if product_id:
        items = [t for t in items if t["product_id"] == product_id]
    if conversion_order_id:
        items = [t for t in items if t["conversion_order_id"] == conversion_order_id]
    if status:
        items = [t for t in items if t["status"] == status]
    items.sort(key=lambda t: clock.parse_iso(t["created_at"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([dict(t) for t in page], limit, offset, total)


@bp.post("/jansan/trial-programs/<trial_program_id>/convert")
def convert_trial(trial_program_id):
    user_id, role = require_roles("FacilityManager")
    t = get_trial_or_404(trial_program_id)
    # ownership (priority 3)
    check_facility_ownership(user_id, role, t["facility_id"])
    body = request.get_json(silent=True) or {}
    qty = svc.as_int(svc.require_field(body, "qty"), "qty", minimum=1)
    delivery_date = svc.as_datetime(svc.require_field(body, "delivery_date"), "delivery_date")
    fuel_index = svc.as_number(svc.require_field(body, "fuel_index"), "fuel_index")
    # state (priority 7)
    if t["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Trial is not ACTIVE", 409)
    # conversion window: now <= trial_end (exact end allowed)
    if clock.now() > clock.parse_iso(t["trial_end"]):
        raise ApiError(ERR_INVALID_STATE, "Trial window has ended", 409)
    # facility gate (priority 8)
    facility = db.facilities.get(t["facility_id"])
    if facility is None or facility["status"] != "ACTIVE":
        raise ApiError(ERR_FACILITY_INACTIVE, "Facility is not ACTIVE", 409)

    # Build conversion order
    order = create_order_record(
        t["facility_id"],
        [{"product_id": t["product_id"], "qty": qty, "discount_pct": 0}],
        delivery_date,
        fuel_index,
        source="TRIAL_CONVERSION",
        standing_order_id=None,
    )
    # Trial credit: min(sample_value_cents, merchandise_subtotal_cents)
    # Need subtotal first — freeze price on the single line and compute subtotal
    product = db.products.get(t["product_id"])
    for line in svc.order_lines_of(order):
        line["unit_price_cents"] = svc.effective_unit_price(facility, product, clock.now())
        line["line_total_cents"] = svc.compute_line_total(line)
    subtotal = sum(l["line_total_cents"] for l in svc.order_lines_of(order)
                   if l["status"] != "CANCELLED")
    credit = min(t["sample_value_cents"], subtotal)
    order["trial_credit_cents"] = credit
    # Run normal placement pipeline (place_order recomputes money incl. credit)
    svc.place_order(order, from_trial=True)

    t["status"] = "CONVERTED"
    t["conversion_order_id"] = order["id"]
    t["conversion_credit_cents"] = credit
    svc.touch(t)
    return success_object(dict(t))
