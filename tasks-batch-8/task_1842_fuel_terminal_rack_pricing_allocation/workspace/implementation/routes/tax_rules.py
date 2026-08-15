from flask import Blueprint, request

from db import db
from errors import not_found
from helpers import get_body, list_query, new_entity, ser_tax_rule
from middleware import require_roles
from response import success_list, success_object

bp = Blueprint("tax_rules", __name__)

_ROLES = ["PlatformAdmin", "RackPriceAnalyst", "TerminalOperator"]


@bp.post("/rack/tax-rules")
def create_tax_rule():
    require_roles(["PlatformAdmin"])
    body = get_body()
    r = new_entity({
        "jurisdiction_level": body.get("jurisdiction_level"),
        "jurisdiction_code": body.get("jurisdiction_code"),
        "product_family": body.get("product_family"),
        "rate_cents_per_gal": body.get("rate_cents_per_gal", 0),
        "effective_start_date": body.get("effective_start_date"),
        "effective_end_date": body.get("effective_end_date"),
        "status": "ACTIVE",
    })
    db.tax_rules[r["id"]] = r
    return success_object(ser_tax_rule(r), 201)


@bp.get("/rack/tax-rules/<ruleId>")
def get_tax_rule(ruleId):
    require_roles(_ROLES)
    r = db.tax_rules.get(ruleId)
    if r is None:
        raise not_found("TaxJurisdictionRule {} does not exist".format(ruleId))
    return success_object(ser_tax_rule(r))


@bp.get("/rack/tax-rules")
def list_tax_rules():
    require_roles(_ROLES)
    page, total, limit, offset = list_query(
        db.tax_rules.values(), request.args,
        ["jurisdiction_level", "jurisdiction_code", "product_family", "status"],
    )
    return success_list([ser_tax_rule(r) for r in page], total, limit, offset)
