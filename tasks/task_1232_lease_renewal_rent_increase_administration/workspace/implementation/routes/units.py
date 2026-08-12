from flask import Blueprint, request

from db import store
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_UNIT_NOT_FOUND, ERR_PROPERTY_NOT_FOUND,
    ERR_DUPLICATE_UNIT_NUMBER,
)
from middleware import require_roles
from response import success_object, success_list
from services.common import new_entity

bp = Blueprint("units", __name__)


def _serialize(u):
    return {
        "id": u["id"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
        "property_id": u["property_id"],
        "unit_number": u["unit_number"],
        "bedrooms": u["bedrooms"],
        "current_market_rent_cents": u["current_market_rent_cents"],
    }


def _get_pagination():
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "limit/offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


@bp.route("/units", methods=["POST"])
def create_unit():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    property_id = body.get("property_id")
    unit_number = body.get("unit_number")
    bedrooms = body.get("bedrooms")
    market_rent = body.get("current_market_rent_cents")
    if not property_id or not isinstance(property_id, str):
        raise_err(ERR_INVALID_REQUEST, "property_id required")
    if not unit_number or not isinstance(unit_number, str):
        raise_err(ERR_INVALID_REQUEST, "unit_number required")
    if not isinstance(bedrooms, int) or isinstance(bedrooms, bool) or bedrooms < 0:
        raise_err(ERR_INVALID_REQUEST, "bedrooms must be >= 0")
    if not isinstance(market_rent, int) or isinstance(market_rent, bool) or market_rent < 0:
        raise_err(ERR_INVALID_REQUEST, "current_market_rent_cents must be >= 0")
    # Existence
    if property_id not in store.properties:
        raise_err(ERR_PROPERTY_NOT_FOUND, "property not found")
    # Uniqueness
    for u in store.units.values():
        if u["property_id"] == property_id and u["unit_number"] == unit_number:
            raise_err(ERR_DUPLICATE_UNIT_NUMBER, "unit number exists")
    rec = new_entity()
    rec.update({
        "property_id": property_id,
        "unit_number": unit_number,
        "bedrooms": bedrooms,
        "current_market_rent_cents": market_rent,
    })
    store.units[rec["id"]] = rec
    return success_object(_serialize(rec), status_code=201)


@bp.route("/units", methods=["GET"])
def list_units():
    require_roles("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent")
    limit, offset = _get_pagination()
    prop = request.args.get("property_id")
    items = list(store.units.values())
    if prop:
        items = [u for u in items if u["property_id"] == prop]
    items.sort(key=lambda u: u["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_serialize(u) for u in page], limit, offset, total)


@bp.route("/units/<uid>", methods=["GET"])
def get_unit(uid):
    require_roles("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent")
    u = store.units.get(uid)
    if u is None:
        raise_err(ERR_UNIT_NOT_FOUND, "unit not found")
    return success_object(_serialize(u))
