"""TourProduct catalogue endpoints (PRD §3.1)."""
from flask import Blueprint, request
import errors
import validate
import serialize
from db import db
from middleware import require_auth, resolve_reader
from records import new_record, touch
from response import object_response, array_response

bp = Blueprint("tour_products", __name__)

READ_ROLES = {"Operator", "Guide", "PartnerVenue", "Guest", "Anonymous"}


@bp.post("/tour-products")
def create():
    require_auth({"Operator"})
    body = validate.get_json_body()
    validate.require_fields(body, ["name", "theme", "base_price_per_person_cents"])
    name = validate.require_str(body, "name")
    theme = body["theme"]
    if not isinstance(theme, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "theme must be a string")
    base_price = validate.require_int(body, "base_price_per_person_cents")

    # optional inputs
    gratuity_pct = validate.opt_number(body, "gratuity_pct", default=0.18)
    charter_fee = validate.opt_int(body, "charter_fee_cents", default=0)
    min_guest_age = validate.opt_int(body, "min_guest_age", default=21)

    # enum check (priority 6) before range check (priority 7)
    validate.check_enum(theme, validate.THEME_VALUES, "theme")

    # range checks (priority 7)
    if base_price <= 0:
        validate.out_of_range()
    if not (0.0 <= float(gratuity_pct) <= 0.30):
        validate.out_of_range()
    if charter_fee < 0:
        validate.out_of_range()

    rec = new_record({
        "name": name,
        "theme": theme,
        "base_price_per_person_cents": base_price,
        "gratuity_pct": gratuity_pct,
        "charter_fee_cents": charter_fee,
        "min_guest_age": min_guest_age,
        "status": "DRAFT",
    })
    db.tour_products[rec["id"]] = rec
    return object_response(serialize.tour_product(rec), status=201)


@bp.get("/tour-products")
def list_products():
    resolve_reader(READ_ROLES)
    limit, offset = validate.parse_pagination()
    status = request.args.get("status")
    theme = request.args.get("theme")
    records = list(db.tour_products.values())
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if theme is not None:
        records = [r for r in records if r["theme"] == theme]
    items, total = validate.paginate(records, limit, offset, serialize.tour_product)
    return array_response(items, limit, offset, total)


@bp.get("/tour-products/<pid>")
def get_product(pid):
    resolve_reader(READ_ROLES)
    rec = db.tour_products.get(pid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Tour product not found")
    return object_response(serialize.tour_product(rec), status=200)


@bp.post("/tour-products/<pid>/publish")
def publish(pid):
    require_auth({"Operator"})
    rec = db.tour_products.get(pid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Tour product not found")
    if rec["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a DRAFT product can be published")
    rec["status"] = "PUBLISHED"
    touch(rec)
    return object_response(serialize.tour_product(rec), status=200)


@bp.post("/tour-products/<pid>/retire")
def retire(pid):
    require_auth({"Operator"})
    rec = db.tour_products.get(pid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Tour product not found")
    if rec["status"] != "PUBLISHED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a PUBLISHED product can be retired")
    # No live departure (SCHEDULED/CONFIRMED/DEPARTED) of this product.
    live = {"SCHEDULED", "CONFIRMED", "DEPARTED"}
    for d in db.departures.values():
        if d["tour_product_id"] == pid and d["status"] in live:
            raise errors.err(errors.ERR_PRODUCT_HAS_ACTIVE_DEPARTURES,
                             "Product has active departures")
    rec["status"] = "RETIRED"
    touch(rec)
    return object_response(serialize.tour_product(rec), status=200)
