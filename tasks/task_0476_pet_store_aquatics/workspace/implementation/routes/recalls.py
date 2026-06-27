"""Recall endpoints and the cross-store cascade (PRD §3.9)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from db import stamp_create, touch
from clock import clock
from middleware import require_auth, require_role
from response import object_response, array_response
from errors import err
from services.common import (
    get_body, lookup, parse_pagination, paginate,
    require_present, as_str, as_enum,
)
from services.derive import (
    recall_covers_lot, recall_covers_subscription, compute_recall_state,
)
from services.serialize import recall_out

bp = Blueprint("recalls", __name__)

READ_ROLES = ["InventoryManager", "LivestockKeeper", "ClinicVet", "StoreClerk", "Customer"]
SEVERITIES = {"ADVISORY", "MANDATORY"}


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@bp.route("/recalls", methods=["POST"])
def issue_recall():
    _, role = require_auth()
    require_role(role, ["InventoryManager"])
    body = get_body()
    product_id = as_str(require_present(body, "product_id"), "product_id")
    product = lookup("products", product_id)
    severity = as_enum(require_present(body, "severity"), "severity", SEVERITIES)
    lot_code = None
    if "lot_code" in body and body["lot_code"] is not None:
        lot_code = as_str(body["lot_code"], "lot_code")
    scope_state_code = None
    if "scope_state_code" in body and body["scope_state_code"] is not None:
        scope_state_code = as_str(body["scope_state_code"], "scope_state_code")

    record = {
        "product_id": product_id,
        "lot_code": lot_code,
        "severity": severity,
        "scope_state_code": scope_state_code,
        "affected_lot_count": 0,
        "halted_subscription_count": 0,
        "status": "OPEN",
        "_quarantined_lot_ids": [],
        "_halted_subscription_ids": [],
    }
    stamp_create(record)
    db.recalls[record["id"]] = record

    # Hop 1: quarantine in-scope AVAILABLE lots for the product.
    affected = 0
    for lot in db.inventory_lots.values():
        if lot["status"] != "AVAILABLE":
            continue
        if recall_covers_lot(record, lot, product):
            lot["status"] = "QUARANTINED"
            touch(lot)
            record["_quarantined_lot_ids"].append(lot["id"])
            affected += 1
    record["affected_lot_count"] = affected

    # Hop 2: product.recall_state recomputed -> RECALLED (derived; OPEN recall present).

    # Hop 3: halt in-scope ACTIVE/PAUSED subscriptions whose product is now RECALLED.
    halted = 0
    for sub in db.subscriptions.values():
        if sub["status"] not in ("ACTIVE", "PAUSED"):
            continue
        if recall_covers_subscription(record, sub):
            sub["status"] = "HALTED"
            touch(sub)
            record["_halted_subscription_ids"].append(sub["id"])
            halted += 1
    record["halted_subscription_count"] = halted

    return object_response(recall_out(record), 201)


@bp.route("/recalls", methods=["GET"])
def list_recalls():
    _, role = require_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.recalls.values())
    product_id = request.args.get("product_id")
    if product_id is not None:
        records = [r for r in records if r["product_id"] == product_id]
    page, total = paginate(records, limit, offset)
    return array_response([recall_out(r) for r in page], limit, offset, total)


@bp.route("/recalls/<recall_id>", methods=["GET"])
def get_recall(recall_id):
    _, role = require_auth()
    require_role(role, READ_ROLES)
    record = lookup("recalls", recall_id)
    return object_response(recall_out(record))


def _another_open_recall_covers_lot(this_recall, lot, product):
    for other in db.recalls.values():
        if other["id"] == this_recall["id"]:
            continue
        if other["status"] != "OPEN":
            continue
        if recall_covers_lot(other, lot, product):
            return True
    return False


@bp.route("/recalls/<recall_id>/resolve", methods=["POST"])
def resolve_recall(recall_id):
    _, role = require_auth()
    require_role(role, ["InventoryManager"])
    recall = lookup("recalls", recall_id)
    if recall["status"] != "OPEN":
        raise err("ERR_RECALL_STATE_INVALID")

    product = db.products.get(recall["product_id"])

    # Un-quarantine each lot this recall quarantined that is not still covered by
    # another OPEN recall.
    for lot_id in recall["_quarantined_lot_ids"]:
        lot = db.inventory_lots.get(lot_id)
        if lot is None:
            continue
        if lot["status"] != "QUARANTINED":
            continue
        if product is not None and _another_open_recall_covers_lot(recall, lot, product):
            continue
        lot["status"] = "AVAILABLE"
        touch(lot)

    # Mark this recall RESOLVED before recomputing product recall_state, so the
    # derivation reflects only still-OPEN recalls.
    recall["status"] = "RESOLVED"

    # For each subscription this recall halted whose product is now CLEAR,
    # reactivate it.
    if product is not None:
        product_clear = compute_recall_state(product) == "CLEAR"
        if product_clear:
            for sub_id in recall["_halted_subscription_ids"]:
                sub = db.subscriptions.get(sub_id)
                if sub is None:
                    continue
                if sub["status"] != "HALTED":
                    continue
                sub["status"] = "ACTIVE"
                sub["next_ship_at"] = _iso(clock.now() + timedelta(days=sub["cycle_days"]))
                touch(sub)

    touch(recall)
    return object_response(recall_out(recall))
