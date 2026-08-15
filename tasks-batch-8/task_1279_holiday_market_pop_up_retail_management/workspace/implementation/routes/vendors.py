"""Vendor endpoints."""
from flask import Blueprint

import db
from middleware import auth, require_roles
from response import success
from services.core import (
    arg,
    as_enum,
    as_str,
    base_record,
    body,
    get_vendor,
    list_response,
    required,
    serialize,
    CATEGORIES,
)

bp = Blueprint("vendors", __name__)

MO = ("MarketOperator",)
GET_ONE = ("MarketOperator", "VendorRole", "JuryChair", "FinanceOfficer")
GET_LIST = ("MarketOperator", "JuryChair", "FinanceOfficer")


@bp.post("/vendors")
def create_vendor():
    user = auth()
    require_roles(user, MO)
    data = body()
    legal_name = as_str(required(data, "legal_name"), "legal_name")
    contact_email = as_str(required(data, "contact_email"), "contact_email")
    category = as_enum(required(data, "category"), "category", CATEGORIES)
    rec = base_record()
    rec.update(
        {
            "legal_name": legal_name,
            "contact_email": contact_email,
            "category": category,
            "status": "PROSPECT",
            "no_show_strikes": 0,
            "lifetime_gross_sales_cents": 0,
            "renewal_score": 0,
        }
    )
    db.STORES["vendors"][rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/vendors/<vendorId>")
def get_vendor_endpoint(vendorId):
    user = auth()
    require_roles(user, GET_ONE)
    return success(serialize(get_vendor(vendorId)))


@bp.get("/vendors")
def list_vendors():
    user = auth()
    require_roles(user, GET_LIST)
    category = arg("category")
    status = arg("status")
    records = []
    for v in db.STORES["vendors"].values():
        if category is not None and v["category"] != category:
            continue
        if status is not None and v["status"] != status:
            continue
        records.append(v)
    return list_response(records)
