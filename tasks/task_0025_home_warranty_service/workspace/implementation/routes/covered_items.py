"""CoveredItem routes (PRD §3.3)."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_ITEM_LIMIT_EXCEEDED,
)
from middleware import require_auth, get_json_body, current_role, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_fields,
    require_int,
    require_string,
    require_enum,
    require_bool,
    lookup_or_404,
)
from services.ownership import assert_customer_owns_contract


bp = Blueprint("covered_items", __name__)


VIEW_ROLES = ["PlatformAdmin", "Customer", "Dispatcher"]
CATEGORY_CHOICES = {
    "HVAC", "WATER_HEATER", "REFRIGERATOR", "DISHWASHER",
    "WASHER", "DRYER", "OVEN",
}


@bp.post("/covered-items")
def create_covered_item():
    require_auth(["Customer", "PlatformAdmin"])()
    body = get_json_body()
    require_fields(body, ["contract_id", "category", "brand", "model", "install_year"])
    contract_id = body["contract_id"]
    require_string(contract_id, "contract_id")
    category = body["category"]
    require_enum(category, CATEGORY_CHOICES, "category")
    brand = body["brand"]
    require_string(brand, "brand")
    model = body["model"]
    require_string(model, "model")

    current_year = datetime.now(timezone.utc).year
    install_year = require_int(
        body["install_year"], "install_year", min_value=1900, max_value=current_year
    )

    pre_existing_flag = body.get("pre_existing_flag", False)
    if pre_existing_flag is None:
        pre_existing_flag = False
    require_bool(pre_existing_flag, "pre_existing_flag")

    # FK existence.
    contract = lookup_or_404(db.contracts, contract_id, "Contract")
    # Customer ownership.
    assert_customer_owns_contract(contract, current_role(), current_user_id())

    # Capacity check — count existing covered items on this contract.
    pkg = db.contract_packages.get(contract["package_id"])
    if pkg is None:
        from errors import ERR_NOT_FOUND
        raise APIError(ERR_NOT_FOUND, 404, "Package not found")
    existing = sum(1 for it in db.covered_items.values() if it["contract_id"] == contract_id)
    if existing + 1 > int(pkg["max_covered_items"]):
        raise APIError(
            ERR_ITEM_LIMIT_EXCEEDED,
            422,
            "Contract has reached covered-item capacity",
        )

    item = {
        "contract_id": contract_id,
        "category": category,
        "brand": brand,
        "model": model,
        "install_year": install_year,
        "pre_existing_flag": bool(pre_existing_flag),
        "last_dispatch_completed_utc": None,
        "last_dispatch_id": None,
    }
    db.stamp_common(item)
    db.covered_items[item["id"]] = item
    return ok_object(item, 201)


@bp.get("/covered-items/<iid>")
def get_covered_item(iid: str):
    require_auth(VIEW_ROLES)()
    item = lookup_or_404(db.covered_items, iid, "CoveredItem")
    # Customer ownership: must belong to a contract the customer owns.
    if current_role() == "Customer":
        contract = db.contracts.get(item["contract_id"])
        if contract is None:
            from errors import ERR_NOT_FOUND
            raise APIError(ERR_NOT_FOUND, 404, "CoveredItem's contract not found")
        assert_customer_owns_contract(contract, "Customer", current_user_id())
    return ok_object(item, 200)


@bp.get("/covered-items")
def list_covered_items():
    require_auth(VIEW_ROLES)()
    limit, offset = paginate_params(request.args)
    contract_filter = request.args.get("contract_id")
    last_dispatch_filter = request.args.get("last_dispatch_id")

    role = current_role()
    user_id = current_user_id()

    items = list(db.covered_items.values())
    if role == "Customer":
        # Restrict to items on customer's own contracts.
        own_contract_ids = {c["id"] for c in db.contracts.values() if c["customer_id"] == user_id}
        items = [it for it in items if it["contract_id"] in own_contract_ids]
    if contract_filter:
        items = [it for it in items if it["contract_id"] == contract_filter]
    if last_dispatch_filter:
        items = [it for it in items if it.get("last_dispatch_id") == last_dispatch_filter]
    items.sort(key=lambda it: it["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)
