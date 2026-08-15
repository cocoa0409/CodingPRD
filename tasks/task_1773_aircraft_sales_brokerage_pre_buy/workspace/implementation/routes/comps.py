"""Comparable sale endpoints (PRD 3.2).

Manually recorded comps carry a null source_listing_id; comp_status defaults
to UNVERIFIED and only VERIFIED comps enter valuation input sets.
"""
from flask import Blueprint

import db as dbmod
from errors import ERR_COMPARABLE_SALE_NOT_FOUND, raise_error
from middleware import ALL_ROLES, require_roles
from response import success_object
from services.core import list_page, new_record, serialize
from validate import (
    body,
    opt_enum,
    req_date_str,
    req_int,
    req_money,
    req_str,
)

bp = Blueprint("comps", __name__)


@bp.post("/api/comparable-sales")
@require_roles(["ListingAgent"])
def create_comp():
    b = body()
    rec = new_record(
        "comps",
        {
            "make": req_str(b, "make"),
            "model": req_str(b, "model"),
            "year": req_int(b, "year"),
            "sale_price_usd": req_money(b, "sale_price_usd"),
            "sale_date": req_date_str(b, "sale_date"),
            "total_time_hours": req_int(b, "total_time_hours", min_value=0),
            "comp_status": opt_enum(
                b, "comp_status", ["VERIFIED", "UNVERIFIED"],
                default="UNVERIFIED",
            ),
            "source_listing_id": None,
        },
    )
    return success_object(serialize("comps", rec), 201)


@bp.get("/api/comparable-sales")
@require_roles(ALL_ROLES)
def list_comps():
    return list_page("comps", ["make", "model", "source_listing_id"])


@bp.get("/api/comparable-sales/<comp_id>")
@require_roles(ALL_ROLES)
def get_comp(comp_id):
    rec = dbmod.db["comps"].get(comp_id)
    if rec is None:
        raise_error(ERR_COMPARABLE_SALE_NOT_FOUND,
                    "comparable sale id does not exist")
    return success_object(serialize("comps", rec))
