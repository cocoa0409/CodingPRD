"""GearUnit endpoints: create, get, list, repair."""
from flask import Blueprint, request

import db
import errors
import store
import serializers as S
import middleware as M
from response import ok, created, ok_list

bp = Blueprint("gear_units", __name__)


@bp.post("/rental/gear-units")
def create_gear_unit():
    body = M.get_json_body()
    gear_type_id = M.require_str(body, "gear_type_id")
    rate_card_id = M.require_str(body, "rate_card_id")
    asset_tag = M.require_str(body, "asset_tag")
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin"})
    # existence, validated left to right
    if gear_type_id not in db.gear_types:
        raise errors.not_found("gear type not found")
    if rate_card_id not in db.rate_cards:
        raise errors.not_found("rate card not found")
    rec = store.create_gear_unit(gear_type_id, rate_card_id, asset_tag)
    return created(S.gear_unit(rec))


@bp.get("/rental/gear-units/<id>")
def get_gear_unit(id):
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    rec = db.gear_units.get(id)
    if not rec:
        raise errors.not_found("gear unit not found")
    return ok(S.gear_unit(rec))


@bp.get("/rental/gear-units")
def list_gear_units():
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    limit, offset = M.parse_pagination()
    items = list(db.gear_units.values())
    gear_type_id = request.args.get("gear_type_id")
    rate_card_id = request.args.get("rate_card_id")
    availability = request.args.get("availability")
    if gear_type_id is not None:
        items = [r for r in items if r["gear_type_id"] == gear_type_id]
    if rate_card_id is not None:
        items = [r for r in items if r["rate_card_id"] == rate_card_id]
    if availability is not None:
        items = [r for r in items if r["availability"] == availability]
    page, total = store.paginate(items, limit, offset)
    return ok_list([S.gear_unit(r) for r in page], limit, offset, total)


@bp.post("/rental/gear-units/<id>/repair")
def repair_gear_unit(id):
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin"})
    rec = db.gear_units.get(id)
    if not rec:
        raise errors.not_found("gear unit not found")
    # state precondition: availability == MAINTENANCE
    if rec["availability"] != "MAINTENANCE":
        raise errors.invalid_state("unit is not in MAINTENANCE")
    rec["availability"] = "AVAILABLE"
    # condition: DAMAGED -> WORN
    if rec["condition"] == "DAMAGED":
        rec["condition"] = "WORN"
    store.touch(rec)
    return ok(S.gear_unit(rec))
