"""AddOn endpoints (PRD §3.1)."""
from flask import Blueprint, request
import errors
import validate
import serialize
from db import db
from middleware import require_auth, resolve_reader
from records import new_record
from response import object_response, array_response

bp = Blueprint("add_ons", __name__)

READ_ROLES = {"Operator", "Guest", "Anonymous"}


@bp.post("/add-ons")
def create():
    require_auth({"Operator"})
    body = validate.get_json_body()
    validate.require_fields(body, ["tour_product_id", "name", "price_per_person_cents"])
    tour_product_id = body["tour_product_id"]
    if not isinstance(tour_product_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "tour_product_id must be a string")
    # FK existence (priority 4)
    if tour_product_id not in db.tour_products:
        raise errors.err(errors.ERR_FK_NOT_FOUND, "tour_product_id references a non-existent product")
    name = validate.require_str(body, "name")
    price = validate.require_int(body, "price_per_person_cents")
    # price_per_person_cents may not be negative
    if price < 0:
        validate.out_of_range()

    rec = new_record({
        "tour_product_id": tour_product_id,
        "name": name,
        "price_per_person_cents": price,
        "status": "ACTIVE",
    })
    db.add_ons[rec["id"]] = rec
    return object_response(serialize.add_on(rec), status=201)


@bp.get("/add-ons")
def list_add_ons():
    resolve_reader(READ_ROLES)
    limit, offset = validate.parse_pagination()
    tour_product_id = request.args.get("tour_product_id")
    records = list(db.add_ons.values())
    if tour_product_id is not None:
        records = [r for r in records if r["tour_product_id"] == tour_product_id]
    items, total = validate.paginate(records, limit, offset, serialize.add_on)
    return array_response(items, limit, offset, total)


@bp.get("/add-ons/<aid>")
def get_add_on(aid):
    resolve_reader(READ_ROLES)
    rec = db.add_ons.get(aid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Add-on not found")
    return object_response(serialize.add_on(rec), status=200)
