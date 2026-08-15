"""Intake batch endpoints: donation intake lifecycle (PRD §3.2)."""

from flask import request

from db import store, base_fields, touch, now
from errors import (ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_BATCH_STATE,
                    ERR_INSUFFICIENT_STOCK, raise_err)
from middleware import authenticate, require_role
from response import success_object, get_body, paginate
from serialize import batch_json
from services.calc import intake_valuation_cents
from validate import req_str, req_quantity_lines
from . import make_blueprint

bp = make_blueprint("intake")

WM = ["WarehouseManager"]
READ_ROLES = ["WarehouseManager", "BankAdmin", "FinanceManager"]


def _get_batch_or_404(batch_id):
    b = store.intake_batches.get(batch_id)
    if b is None:
        raise_err(ERR_NOT_FOUND, "Intake batch not found.")
    return b


def _require_inventory():
    inv = store.inventory
    if inv is None or not inv["initialized"]:
        raise_err(ERR_VALIDATION, "Inventory has not been initialized.")
    return inv


@bp.route("/intake-batches", methods=["POST"])
def create_batch():
    _, role = authenticate()
    require_role(role, WM)
    body = get_body()
    donor = req_str(body, "donor_name")
    lines = req_quantity_lines(body, "lines")
    b = base_fields()
    b.update({
        "source_type": "DONATION",
        "donor_name": donor,
        "purchase_order_id": None,
        "lines": lines,
        "valued_total_cents": intake_valuation_cents(lines, "DONATION"),
        "status": "COUNTED",
        "posted_at": None,
    })
    store.intake_batches[b["id"]] = b
    return success_object(batch_json(b), status=201)


@bp.route("/intake-batches", methods=["GET"])
def list_batches():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    source_type = request.args.get("source_type")
    status = request.args.get("status")
    po_id = request.args.get("purchase_order_id")
    items = [b for b in store.intake_batches.values()
             if (source_type is None or b["source_type"] == source_type)
             and (status is None or b["status"] == status)
             and (po_id is None or b["purchase_order_id"] == po_id)]
    items.sort(key=lambda b: b["created_at"])
    return paginate([batch_json(b) for b in items])


@bp.route("/intake-batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    return success_object(batch_json(_get_batch_or_404(batch_id)))


@bp.route("/intake-batches/<batch_id>/post", methods=["POST"])
def post_batch(batch_id):
    _, role = authenticate()
    require_role(role, WM)
    b = _get_batch_or_404(batch_id)
    if b["status"] != "COUNTED":
        raise_err(ERR_INVALID_BATCH_STATE,
                  "Only a COUNTED batch can be posted.")
    inv = _require_inventory()
    for ln in b["lines"]:
        inv["sizes"][ln["size_code"]]["on_hand_units"] += ln["quantity"]
    b["status"] = "POSTED"
    b["posted_at"] = now()
    touch(b)
    touch(inv)
    return success_object(batch_json(b))


@bp.route("/intake-batches/<batch_id>/recount", methods=["POST"])
def recount_batch(batch_id):
    _, role = authenticate()
    require_role(role, WM)
    b = _get_batch_or_404(batch_id)
    if b["status"] != "POSTED":
        raise_err(ERR_INVALID_BATCH_STATE,
                  "Only a POSTED batch can be recounted.")
    inv = _require_inventory()
    # Stock check against the CURRENT lines before any withdrawal (atomicity).
    for ln in b["lines"]:
        if inv["sizes"][ln["size_code"]]["on_hand_units"] - ln["quantity"] < 0:
            raise_err(ERR_INSUFFICIENT_STOCK,
                      "Recount would drive on-hand negative for %s." % ln["size_code"])
    new_lines = req_quantity_lines(get_body(), "lines")
    for ln in b["lines"]:
        inv["sizes"][ln["size_code"]]["on_hand_units"] -= ln["quantity"]
    b["lines"] = new_lines
    b["valued_total_cents"] = intake_valuation_cents(
        new_lines, b["source_type"],
        store.purchase_orders.get(b["purchase_order_id"]))
    b["status"] = "COUNTED"
    touch(b)
    touch(inv)
    return success_object(batch_json(b))


@bp.route("/intake-batches/<batch_id>/void", methods=["POST"])
def void_batch(batch_id):
    _, role = authenticate()
    require_role(role, WM)
    b = _get_batch_or_404(batch_id)
    if b["status"] == "COUNTED":
        # Never posted: no inventory effect, batch version only.
        b["status"] = "VOIDED"
        touch(b)
        return success_object(batch_json(b))
    if b["status"] != "POSTED":
        raise_err(ERR_INVALID_BATCH_STATE,
                  "A VOIDED batch cannot be voided again.")
    inv = _require_inventory()
    for ln in b["lines"]:
        if inv["sizes"][ln["size_code"]]["on_hand_units"] - ln["quantity"] < 0:
            raise_err(ERR_INSUFFICIENT_STOCK,
                      "Void would drive on-hand negative for %s." % ln["size_code"])
    for ln in b["lines"]:
        inv["sizes"][ln["size_code"]]["on_hand_units"] -= ln["quantity"]
    b["status"] = "VOIDED"
    touch(b)
    touch(inv)
    return success_object(batch_json(b))
