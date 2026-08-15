"""DepositProduct endpoints."""

from flask import Blueprint, request

from db import STORE
from errors import bad_request
from middleware import get_body, paginate, query_enum, require_roles
from response import ok_object
from serialize import serialize, serialize_many
from utils import req_bool, req_enum, req_int, req_str, stamp_new

bp = Blueprint("products", __name__)

PRODUCT_CLASSES = ("SAVINGS", "MONEY_MARKET", "CD", "INTEREST_CHECKING")
TIER_APPLICATIONS = ("MARGINAL", "WHOLE_BALANCE")


@bp.post("/deposit-products")
@require_roles("OperationsAdmin")
def create_product():
    data = get_body()
    product_code = req_str(data, "product_code")
    product_class = req_enum(data, "product_class", PRODUCT_CLASSES)
    term_months = req_int(data, "term_months", minimum=0)
    tier_application = req_enum(data, "tier_application", TIER_APPLICATIONS)
    rate_cap_bp = req_int(data, "rate_cap_bp", minimum=0)
    allows_promos = req_bool(data, "allows_promos")
    allows_exceptions = req_bool(data, "allows_exceptions")
    for p in STORE["products"].values():
        if p["product_code"] == product_code:
            raise bad_request("product_code must be unique across all products")
    row = {
        "product_code": product_code,
        "product_class": product_class,
        "term_months": term_months,
        "tier_application": tier_application,
        "rate_cap_bp": rate_cap_bp,
        "allows_promos": allows_promos,
        "allows_exceptions": allows_exceptions,
    }
    stamp_new(row)
    STORE["products"][row["id"]] = row
    return ok_object(serialize("products", row), 201)


@bp.get("/deposit-products")
@require_roles("OperationsAdmin", "PricingAnalyst", "PricingCommittee", "BranchBanker")
def list_products():
    pclass = query_enum("product_class", PRODUCT_CLASSES)
    rows = list(STORE["products"].values())
    if pclass is not None:
        rows = [r for r in rows if r["product_class"] == pclass]
    return paginate(serialize_many("products", rows))
