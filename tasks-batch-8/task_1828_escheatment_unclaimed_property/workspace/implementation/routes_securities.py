"""Securities detail endpoints (PRD 3.5)."""

from flask import Blueprint

import db
import errors
from errors import raise_error
import middleware as mw
import response as resp
from helpers import new_entity, get_property_or_404

bp = Blueprint("securities", __name__)


def securities_detail_view(d):
    return {
        "id": d["id"],
        "property_id": d["property_id"],
        "cusip": d["cusip"],
        "shares_quantity": d["shares_quantity"],
        "last_close_price_cents": d["last_close_price_cents"],
        "accrued_dividends_cents": d["accrued_dividends_cents"],
        "pending_execution_price_cents": d["pending_execution_price_cents"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


@bp.post("/escheatment/properties/<propertyId>/securities-detail")
def create_securities_detail(propertyId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer",))
    data = mw.body_json()
    cusip = mw.req_string(data, "cusip")
    shares = mw.req_int(data, "shares_quantity", min_value=1)
    close_price = mw.req_int(data, "last_close_price_cents", min_value=0)
    dividends = mw.req_int(data, "accrued_dividends_cents", min_value=0)
    prop = get_property_or_404(propertyId)
    if prop["property_type"] != "BROKERAGE_SHARES":
        raise_error(
            errors.ERR_NOT_SECURITIES_PROPERTY,
            "Securities detail requires a BROKERAGE_SHARES property",
        )
    for existing in db.securities_details.values():
        if existing["property_id"] == prop["id"]:
            raise_error(
                errors.ERR_SECURITIES_DETAIL_EXISTS,
                "The property already has a securities detail",
            )
    detail = new_entity({
        "property_id": prop["id"],
        "cusip": cusip,
        "shares_quantity": shares,
        "last_close_price_cents": close_price,
        "accrued_dividends_cents": dividends,
        "pending_execution_price_cents": None,
        "status": "REGISTERED",
    })
    db.securities_details[detail["id"]] = detail
    return resp.success(securities_detail_view(detail), "object", 201)


@bp.get("/escheatment/properties/<propertyId>/securities-detail")
def get_securities_detail(propertyId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    prop = get_property_or_404(propertyId)
    items = [d for d in db.securities_details.values() if d["property_id"] == prop["id"]]
    # Always an array of zero or one element, never a bare object.
    return resp.success([securities_detail_view(d) for d in items], "array", 200)
