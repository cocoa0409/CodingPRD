"""Blanket order endpoints (PRD 3.6): draft, confirm, cancel (cascade),
accept-substitution."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_CONTRACT_LINE_MISSING, ERR_CONTRACT_NOT_ACTIVE,
    ERR_INVALID_STATE_TRANSITION, ERR_PRODUCT_DISCONTINUED,
)
from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.calc import find_contract_line, price_at
from services.core import (
    cancel_release_effects, new_record, recompute_order_value, serialize, touch,
)
from util import parse_date
from validate import (
    get_body, req_int, req_str, require_fk, require_path_resource,
)

bp = Blueprint("blanket_orders", __name__)


@bp.post("/api/blanket-orders")
def create_blanket_order():
    authorized(["AccountManager"])
    body = get_body()
    contract_id = req_str(body, "contract_id")
    product_id = req_str(body, "product_id")
    committed_qty = req_int(body, "committed_qty", min_value=1)
    # Priority 4: body FK existence in canonical order (product before contract).
    require_fk("products", product_id, "product")
    require_fk("contracts", contract_id, "contract")
    rec = new_record("blanket_orders", {
        "contract_id": contract_id,
        "product_id": product_id,
        "committed_qty": committed_qty,
        "remaining_qty": None,  # NULL until confirm
        "substitution_status": "NONE",
        "provisional_unit_price_cents": None,
        "provisional_remaining_value_cents": None,
        "status": "DRAFT",
    })
    return success_object(serialize(rec), status=201)


@bp.get("/api/blanket-orders/<oid>")
def get_blanket_order(oid):
    return get_one("blanket_orders", oid, "blanket order")


@bp.get("/api/blanket-orders")
def list_blanket_orders():
    return list_response("blanket_orders", {
        "contract_id": arg("contract_id"),
        "product_id": arg("product_id"),
        "status": arg("status"),
    })


@bp.post("/api/blanket-orders/<oid>/confirm")
def confirm_blanket_order(oid):
    authorized(["ProgramAdmin"])
    order = require_path_resource("blanket_orders", oid, "blanket order")
    # Priority 6a: the order's own state — confirm only from DRAFT.
    if order["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE_TRANSITION, "only a DRAFT blanket order can be confirmed")
    # Priority 6b: cross-entity — governing contract must be ACTIVE.
    contract = db["contracts"].get(order["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise_error(ERR_CONTRACT_NOT_ACTIVE, "governing contract is not ACTIVE")
    # Priority 8: contract line for (contract, product), then product ACTIVE.
    line = find_contract_line(order["contract_id"], order["product_id"])
    if line is None:
        raise_error(ERR_CONTRACT_LINE_MISSING, "no contract line prices the order product")
    product = db["products"].get(order["product_id"])
    if product is None or product["status"] != "ACTIVE":
        raise_error(ERR_PRODUCT_DISCONTINUED, "order product is not ACTIVE")

    order["status"] = "OPEN"
    order["remaining_qty"] = order["committed_qty"]
    order["provisional_unit_price_cents"] = line["current_unit_price_cents"]
    order["provisional_remaining_value_cents"] = (
        order["remaining_qty"] * order["provisional_unit_price_cents"]
    )
    touch(order)
    return success_object(serialize(order))


@bp.post("/api/blanket-orders/<oid>/cancel")
def cancel_blanket_order(oid):
    authorized(["AccountManager"])
    order = require_path_resource("blanket_orders", oid, "blanket order")
    if order["status"] not in ("DRAFT", "OPEN"):
        raise_error(ERR_INVALID_STATE_TRANSITION, "only a DRAFT or OPEN blanket order can be cancelled")
    if order["status"] == "OPEN":
        # Cascade: every SCHEDULED|ON_HOLD|PICKED release -> CANCELLED with the
        # full per-state give-back behavior (PICKED restores lots).
        give_back_total = 0
        for rel in db["releases"].values():
            if rel["blanket_order_id"] == oid and rel["status"] in ("SCHEDULED", "ON_HOLD", "PICKED"):
                give_back_total += cancel_release_effects(rel)
        if order["remaining_qty"] is not None:
            order["remaining_qty"] += give_back_total
            recompute_order_value(order)
    order["status"] = "CANCELLED"
    touch(order)
    return success_object(serialize(order))


@bp.post("/api/blanket-orders/<oid>/accept-substitution")
def accept_substitution(oid):
    authorized(["AccountManager"])
    order = require_path_resource("blanket_orders", oid, "blanket order")
    # Acceptance is defined only on a PENDING order.
    if order["substitution_status"] != "PENDING":
        raise_error(ERR_INVALID_STATE_TRANSITION, "blanket order has no PENDING substitution")
    product = db["products"].get(order["product_id"])
    replacement_id = product.get("replacement_product_id") if product else None
    replacement = db["products"].get(replacement_id) if replacement_id else None
    if replacement is None:
        raise_error(ERR_INVALID_STATE_TRANSITION, "no replacement product is recorded")
    contract = db["contracts"].get(order["contract_id"])
    # Acceptance requires a contract line pricing the replacement product.
    line = find_contract_line(order["contract_id"], replacement_id)
    if line is None:
        raise_error(ERR_CONTRACT_LINE_MISSING, "no contract line prices the replacement product")

    order["product_id"] = replacement_id
    order["substitution_status"] = "ACCEPTED"
    order["provisional_unit_price_cents"] = line["current_unit_price_cents"]
    recompute_order_value(order)
    touch(order)
    # Each ON_HOLD release returns to SCHEDULED, re-stamped at its ship date
    # against the replacement product's line.
    for rel in db["releases"].values():
        if rel["blanket_order_id"] == oid and rel["status"] == "ON_HOLD":
            rel["status"] = "SCHEDULED"
            rel["provisional_unit_price_cents"] = price_at(
                parse_date(rel["scheduled_ship_date"]), line, contract
            )
            touch(rel)
    return success_object(serialize(order))
