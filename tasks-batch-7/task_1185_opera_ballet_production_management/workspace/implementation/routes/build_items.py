"""BuildItem routes (PRD 3.2) — build budget discipline."""

from flask import Blueprint

from db import store
from errors import (ApiError, ERR_BUDGET_EXCEEDED, ERR_INVALID_STATE, conflict)
from middleware import require_roles
from response import ok_object
from routes.common import get_or_404, list_response
from services import recompute_build_balance
from util import (json_body, new_record, req_enum, req_int, req_str, to_public,
                  touch)

bp = Blueprint("build_items", __name__)

ITEM_KINDS = ("SET", "COSTUME", "PROP")
TARGET_STATES = ("BUILT", "ORDERED", "DELIVERED", "IN_USE", "CANCELLED")


@bp.post("/opera/build-items")
def create_build_item():
    require_roles("ProductionManager")
    body = json_body()
    production_id = req_str(body, "production_id")
    item_kind = req_enum(body, "item_kind", ITEM_KINDS)
    name = req_str(body, "name")
    quoted = req_int(body, "quoted_cost_cents", min_value=1)
    prod = get_or_404(store.productions, production_id, "Production")
    # Pipeline step 14 (fiscal): quoted cost must fit the remaining balance.
    if quoted > prod["build_cost_balance_cents"]:
        raise ApiError(ERR_BUDGET_EXCEEDED, 402,
                       "Quoted cost exceeds the production build cost balance")
    rec = new_record(
        production_id=production_id,
        item_kind=item_kind,
        name=name,
        quoted_cost_cents=quoted,
        actual_cost_cents=None,
        status="ORDERED",
    )
    store.build_items[rec["id"]] = rec
    recompute_build_balance(prod)
    return ok_object(to_public(rec), 201)


@bp.get("/opera/build-items")
def list_build_items():
    require_roles("Any")
    return list_response(
        store.build_items.values(),
        [("production_id", "production_id"), ("status", "status")],
    )


@bp.get("/opera/build-items/<bid>")
def get_build_item(bid):
    require_roles("Any")
    return ok_object(to_public(get_or_404(store.build_items, bid, "BuildItem")))


@bp.post("/opera/build-items/<bid>/transition")
def transition_build_item(bid):
    require_roles("ProductionManager")
    body = json_body()
    to_state = req_enum(body, "to_state", TARGET_STATES)
    actual = None
    if to_state == "BUILT":
        # Shape rule tied to the BUILT target: actual cost present and > 0.
        actual = req_int(body, "actual_cost_cents", min_value=1)
    item = get_or_404(store.build_items, bid, "BuildItem")
    prod = store.productions[item["production_id"]]
    cur = item["status"]

    if cur == "ORDERED" and to_state == "BUILT":
        # Fiscal check: balance must cover the actual-over-quoted delta.
        if prod["build_cost_balance_cents"] < actual - item["quoted_cost_cents"]:
            raise ApiError(ERR_BUDGET_EXCEEDED, 402,
                           "Actual cost delta exceeds the production build balance")
        item["actual_cost_cents"] = actual
        item["status"] = "BUILT"
        touch(item)
        recompute_build_balance(prod)
        # Cascade touch (PRD 2.4): an item reaching BUILT bumps Production.version.
        touch(prod)
    elif cur == "BUILT" and to_state == "ORDERED":
        # Rework loop: release the actual-cost basis back to quoted.
        item["status"] = "ORDERED"
        touch(item)
        recompute_build_balance(prod)
    elif cur == "BUILT" and to_state == "DELIVERED":
        item["status"] = "DELIVERED"
        touch(item)
    elif cur == "DELIVERED" and to_state == "IN_USE":
        item["status"] = "IN_USE"
        touch(item)
    elif cur == "ORDERED" and to_state == "CANCELLED":
        item["status"] = "CANCELLED"
        touch(item)
        recompute_build_balance(prod)
    else:
        raise conflict(ERR_INVALID_STATE,
                       f"BuildItem cannot transition {cur} -> {to_state}")

    return ok_object(to_public(item))
