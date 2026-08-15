"""Property registry (PRD 3.1)."""
from flask import Blueprint

import resolve
from db import db
from middleware import SPONSOR, ALL_ROLES, endpoint
from response import success_list, success_object
from serializers import ser_property
from services.domain import stamp_new, sorted_items
from validate import get_body, req_int, req_str, pagination

bp = Blueprint("properties", __name__)
RS = {"strict_slashes": False}


@bp.route("/properties", methods=["POST"], **RS)
@endpoint(SPONSOR)
def create_property(caller):
    body = get_body()
    o = {
        "property_legal_name": req_str(body, "property_legal_name"),
        "street_address": req_str(body, "street_address"),
        "acquisition_price_cents": req_int(body, "acquisition_price_cents", minimum=0),
        "status": "OWNED",
    }
    stamp_new(o)
    db["properties"][o["id"]] = o
    return success_object(ser_property(o), 201)


@bp.route("/properties", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def list_properties(caller):
    limit, offset = pagination()
    items = sorted_items(db["properties"].values())
    page = items[offset:offset + limit]
    return success_list([ser_property(o) for o in page], len(items), limit, offset)


@bp.route("/properties/<propertyId>", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def get_property(caller, propertyId):
    return success_object(ser_property(resolve.property_(propertyId)))
