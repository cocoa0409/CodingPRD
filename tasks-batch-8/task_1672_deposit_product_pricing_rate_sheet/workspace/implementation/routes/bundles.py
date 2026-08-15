"""RelationshipBundle endpoints."""

from flask import Blueprint

from db import STORE
from errors import bad_request
from middleware import get_body, paginate, require_roles
from response import ok_object
from serialize import serialize, serialize_many
from utils import req_int, req_list, req_str, stamp_new

bp = Blueprint("bundles", __name__)

PRODUCT_CLASSES = ("SAVINGS", "MONEY_MARKET", "CD", "INTEREST_CHECKING")


def _class_list(data, field):
    v = req_list(data, field, allow_empty=False)
    for item in v:
        if item not in PRODUCT_CLASSES:
            raise bad_request(f"{field} entries must be valid product classes")
    return v


@bp.post("/relationship-bundles")
@require_roles("OperationsAdmin")
def create_bundle():
    data = get_body()
    bundle_code = req_str(data, "bundle_code")
    bonus_bp = req_int(data, "bonus_bp", minimum=0)
    min_combined = req_int(data, "min_combined_balance_cents", minimum=0)
    required = _class_list(data, "required_product_classes")
    eligible = _class_list(data, "eligible_product_classes")
    for b in STORE["bundles"].values():
        if b["bundle_code"] == bundle_code:
            raise bad_request("bundle_code must be unique")
    row = {
        "bundle_code": bundle_code,
        "bonus_bp": bonus_bp,
        "min_combined_balance_cents": min_combined,
        "required_product_classes": required,
        "eligible_product_classes": eligible,
    }
    stamp_new(row)
    STORE["bundles"][row["id"]] = row
    return ok_object(serialize("bundles", row), 201)


@bp.get("/relationship-bundles")
@require_roles("OperationsAdmin", "PricingAnalyst", "BranchBanker")
def list_bundles():
    return paginate(serialize_many("bundles", list(STORE["bundles"].values())))
