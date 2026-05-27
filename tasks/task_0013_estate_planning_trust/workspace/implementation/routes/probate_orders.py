"""ProbateOrder routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from common import (
    get_body,
    pagination_params,
    require_enum,
    require_string,
    stamp_common_fields,
    touch,
)
from errors import (
    APIError,
    ERR_EXECUTOR_BENEFICIARY_CONFLICT,
    invalid_state,
    not_found,
)
from middleware import require_roles
from response import created, list_response, success
from services.cascades import (
    cascade_approve_inventory,
    cascade_close_estate,
    cascade_open_probate,
    cascade_supersede_confirm_executor,
)
from views import view_order


bp = Blueprint("probate_orders", __name__)

ORDER_TYPES = {
    "OPEN_PROBATE",
    "CONFIRM_EXECUTOR",
    "APPROVE_INVENTORY",
    "SETTLE_CREDITORS",
    "FINAL_DISTRIBUTION",
    "CLOSE_ESTATE",
}


@bp.post("/probate-orders")
@require_roles("Judge")
def create_order():
    body = get_body()
    estate_id = require_string(body, "estate_id")
    if estate_id not in db.estates:
        raise not_found("Estate")
    order_type = require_enum(body, "order_type", ORDER_TYPES)
    judge_user_id = require_string(body, "judge_user_id")

    now = db.now_utc()
    o = {
        "estate_id": estate_id,
        "order_type": order_type,
        "judge_user_id": judge_user_id,
        "status": "DRAFT",
        "entered_at": None,
    }
    stamp_common_fields(o, now)
    db.probate_orders[o["id"]] = o
    return created(view_order(o))


@bp.get("/probate-orders/<oid>")
@require_roles("EstatePlanner", "Executor", "Judge", "Beneficiary")
def get_order(oid: str):
    o = db.probate_orders.get(oid)
    if o is None:
        raise not_found("ProbateOrder")
    return success(view_order(o))


@bp.get("/probate-orders")
@require_roles("EstatePlanner", "Executor", "Judge", "Beneficiary")
def list_orders():
    limit, offset = pagination_params()
    estate_id = request.args.get("estate_id")
    order_type = request.args.get("order_type")
    status = request.args.get("status")

    items = list(db.probate_orders.values())
    if estate_id is not None:
        items = [o for o in items if o["estate_id"] == estate_id]
    if order_type is not None:
        items = [o for o in items if o["order_type"] == order_type]
    if status is not None:
        items = [o for o in items if o["status"] == status]

    items.sort(key=lambda o: o["created_at"])
    total = len(items)
    page = [view_order(o) for o in items[offset:offset + limit]]
    return list_response(page, limit=limit, offset=offset, total_count=total)


def _entered_order_exists(estate_id: str, order_type: str) -> bool:
    return any(
        o["estate_id"] == estate_id
        and o["order_type"] == order_type
        and o["status"] == "ENTERED"
        for o in db.probate_orders.values()
    )


@bp.post("/probate-orders/<oid>/enter")
@require_roles("Judge")
def enter_order(oid: str):
    o = db.probate_orders.get(oid)
    if o is None:
        raise not_found("ProbateOrder")
    if o["status"] != "DRAFT":
        raise invalid_state("ProbateOrder must be DRAFT to enter.")

    estate = db.estates.get(o["estate_id"])
    if estate is None:
        raise not_found("Estate")

    if estate["status"] not in ("PROBATE_PENDING", "PROBATE_OPEN", "ADMINISTRATION"):
        raise invalid_state("Estate must be PROBATE_PENDING, PROBATE_OPEN, or ADMINISTRATION to enter a court order.")

    order_type = o["order_type"]
    # Per-order-type preconditions
    if order_type == "OPEN_PROBATE":
        if estate["status"] != "PROBATE_PENDING":
            raise invalid_state("OPEN_PROBATE requires estate in PROBATE_PENDING.")
        # Identify the accepted executor
        accepted_executor = None
        for x in db.executors.values():
            if (
                x["estate_id"] == estate["id"]
                and x["role_type"] == "EXECUTOR"
                and x["status"] == "ACCEPTED"
            ):
                accepted_executor = x
                break
        if accepted_executor is None:
            raise invalid_state("No ACCEPTED executor on this estate.")
        if accepted_executor["is_also_beneficiary"]:
            if not _entered_order_exists(estate["id"], "CONFIRM_EXECUTOR"):
                raise APIError(
                    ERR_EXECUTOR_BENEFICIARY_CONFLICT,
                    "Executor is also a beneficiary; an ENTERED CONFIRM_EXECUTOR order is required.",
                    422,
                )
    elif order_type == "APPROVE_INVENTORY":
        if estate["status"] != "PROBATE_OPEN":
            raise invalid_state("APPROVE_INVENTORY requires estate in PROBATE_OPEN.")
        # No DRAFT assets
        for a in db.assets.values():
            if a["estate_id"] == estate["id"] and a["status"] == "DRAFT":
                raise invalid_state("APPROVE_INVENTORY requires no Asset in DRAFT.")
        if estate["gross_estate_value_cents"] <= 0:
            raise invalid_state("APPROVE_INVENTORY requires gross_estate_value_cents > 0.")
    elif order_type == "FINAL_DISTRIBUTION":
        if estate["status"] != "ADMINISTRATION":
            raise invalid_state("FINAL_DISTRIBUTION requires estate in ADMINISTRATION.")
        # Every ALLOWED claim must also be PAID -- meaning no remaining ALLOWED.
        for c in db.creditor_claims.values():
            if c["estate_id"] == estate["id"] and c["status"] == "ALLOWED":
                raise invalid_state("FINAL_DISTRIBUTION requires every ALLOWED claim to be PAID.")
    elif order_type == "CLOSE_ESTATE":
        if estate["status"] != "ADMINISTRATION":
            raise invalid_state("CLOSE_ESTATE requires estate in ADMINISTRATION.")
        # A FINAL_DISTRIBUTION order with status=ENTERED exists.
        if not _entered_order_exists(estate["id"], "FINAL_DISTRIBUTION"):
            raise invalid_state("CLOSE_ESTATE requires an ENTERED FINAL_DISTRIBUTION order.")
        for c in db.creditor_claims.values():
            if c["estate_id"] == estate["id"] and c["status"] == "ALLOWED":
                raise invalid_state("CLOSE_ESTATE requires every ALLOWED claim to be PAID.")
        if not estate.get("_net_taxable_has_run"):
            raise invalid_state("CLOSE_ESTATE requires that the net taxable estate has been computed at least once.")

    now = db.now_utc()
    o["entered_at"] = now
    o["status"] = "ENTERED"
    touch(o, now)

    # Cascade per order_type
    if order_type == "OPEN_PROBATE":
        cascade_open_probate(estate, o, now)
    elif order_type == "APPROVE_INVENTORY":
        cascade_approve_inventory(estate, now)
    elif order_type == "CLOSE_ESTATE":
        cascade_close_estate(estate, now)
    else:
        # CONFIRM_EXECUTOR, SETTLE_CREDITORS, FINAL_DISTRIBUTION: no estate cascade
        # but still bump estate.version per SCAFFOLD side_effect.
        touch(estate, now)

    return success(view_order(o))


@bp.post("/probate-orders/<oid>/supersede")
@require_roles("Judge")
def supersede_order(oid: str):
    o = db.probate_orders.get(oid)
    if o is None:
        raise not_found("ProbateOrder")
    if o["status"] != "ENTERED":
        raise invalid_state("ProbateOrder must be ENTERED to supersede.")

    body = get_body()
    require_string(body, "reason")

    now = db.now_utc()
    o["status"] = "SUPERSEDED"
    touch(o, now)

    if o["order_type"] == "CONFIRM_EXECUTOR":
        cascade_supersede_confirm_executor(o, now)
    return success(view_order(o))
