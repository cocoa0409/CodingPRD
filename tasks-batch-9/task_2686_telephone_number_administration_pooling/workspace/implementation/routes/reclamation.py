"""The reclamation sweep and the reclamation-order machine (PRD 3.7)."""

from flask import Blueprint

from db import by_created, days, db, fmt_instant, now, touch
from errors import fail
from middleware import (
    ROLE_ADMIN,
    ROLE_APPROVER,
    ROLE_CARRIER,
    body,
    check_action_role,
    opt_enum,
    opt_id,
    opt_str,
    req_enum,
    require_roles,
)
from response import object_response, paginate
from routes.common import field, filter_rows
from services import constants as C
from services import core, serialize, workflows

bp = Blueprint("reclamation", __name__)

READERS = (ROLE_ADMIN, ROLE_APPROVER, ROLE_CARRIER)

ORDER_ACTION_ROLES = {
    "SURRENDER": (ROLE_CARRIER,),
    "APPEAL": (ROLE_CARRIER,),
    "EXECUTE": (ROLE_ADMIN,),
    "WITHDRAW": (ROLE_ADMIN,),
}


@bp.route("/numbering/reclamation-sweeps", methods=["POST"])
def run_sweep():
    require_roles(ROLE_ADMIN)
    payload = body()
    rate_center_id = opt_id(payload, "rate_center_id")
    reason_filter = opt_enum(payload, "reason_filter", C.RECLAMATION_REASONS)

    if rate_center_id is not None:
        core.get_rate_center(rate_center_id)

    summary = workflows.run_sweep(rate_center_id, reason_filter)
    return object_response(
        {
            "orders_issued": summary["orders_issued"],
            "blocks_released": summary["blocks_released"],
            "routing_activated": summary["routing_activated"],
            "swept_at": fmt_instant(summary["swept_at"]),
        }
    )


@bp.route("/numbering/reclamation-orders", methods=["GET"])
def list_orders():
    require_roles(*READERS)
    rows = by_created(db.orders.values())
    rows = filter_rows(
        rows,
        [
            ("carrier_id", field("carrier_id")),
            ("number_block_id", field("number_block_id")),
            ("reason", field("reason")),
            ("status", field("status")),
        ],
    )
    return paginate(rows, serialize.order)


@bp.route("/numbering/reclamation-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    require_roles(*READERS)
    return object_response(serialize.order(core.get_order(order_id)))


@bp.route("/numbering/reclamation-orders/<order_id>/transitions", methods=["POST"])
def transition_order(order_id):
    actor = require_roles(ROLE_CARRIER, ROLE_ADMIN)
    payload = body()
    action = req_enum(payload, "action", C.RECLAMATION_ACTIONS)
    appeal_note = opt_str(payload, "appeal_note", 1, 1000)

    order = core.get_order(order_id)

    if actor.role == ROLE_CARRIER and actor.user_id != order["carrier_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "only the served carrier may respond")

    check_action_role(actor, action, ORDER_ACTION_ROLES)

    if order["status"] in ("EXECUTED", "WITHDRAWN"):
        fail("ERR_TERMINAL_STATE", "the order is already closed")

    status = order["status"]
    instant = now()

    if action == "SURRENDER":
        if status != "ISSUED":
            fail("ERR_INVALID_STATE_TRANSITION", "SURRENDER is not available")
        order["status"] = "SURRENDER_ACKNOWLEDGED"
        touch(order)
    elif action == "APPEAL":
        if status != "ISSUED":
            fail("ERR_INVALID_STATE_TRANSITION", "APPEAL is not available")
        if order["response_due_at"] is not None and instant > order["response_due_at"]:
            fail("ERR_ACTIVATION_WINDOW_EXPIRED", "the appeal window has elapsed")
        order["status"] = "APPEAL_PENDING"
        if appeal_note is not None:
            order["appeal_note"] = appeal_note
        touch(order)
    elif action == "EXECUTE":
        if status not in ("ISSUED", "SURRENDER_ACKNOWLEDGED", "APPEAL_PENDING"):
            fail("ERR_INVALID_STATE_TRANSITION", "EXECUTE is not available")
        if status == "ISSUED":
            if order["response_due_at"] is None or instant <= order["response_due_at"]:
                fail(
                    "ERR_INVALID_STATE_TRANSITION",
                    "the response period has not elapsed",
                )
        _execute(order, instant)
    else:
        if status not in ("ISSUED", "APPEAL_PENDING"):
            fail("ERR_INVALID_STATE_TRANSITION", "WITHDRAW is not available")
        _withdraw(order)

    return object_response(serialize.order(order))


def _execute(order, instant):
    order["status"] = "EXECUTED"
    order["executed_at"] = instant
    order["strike_applied"] = True
    touch(order)

    block = db.blocks.get(order["number_block_id"])
    carrier = db.carriers.get(order["carrier_id"])

    if block is not None:
        if block["allocation_status"] == "RECLAMATION_PENDING":
            block["allocation_status"] = "AGING"
            block["aging_release_at"] = instant + days(C.AGING_PERIOD_DAYS)
            workflows.clear_holder_stamps(block)
        workflows.withdraw_routing(block)
        touch(block)

    if carrier is not None:
        carrier["reclamation_strike_count"] += 1
        if carrier["reclamation_strike_count"] >= C.RECLAMATION_PROBATION_STRIKES:
            # Step three: two strikes put the carrier on probation.
            carrier["probation_until"] = instant + days(C.PROBATION_DAYS)
            touch(carrier)
            # Step four fires only *because* the carrier entered probation, so a
            # first strike leaves the pending queue exactly where it was.
            core.push_pending_growth_requests_to_info(carrier["id"])
        else:
            touch(carrier)

    if block is not None:
        rate_center = db.rate_centers.get(block["rate_center_id"])
        if rate_center is not None:
            touch(rate_center)
        npa = db.npas.get(block["npa_id"])
        if npa is not None:
            if not core.recompute_npa_posture(npa):
                touch(npa)


def _withdraw(order):
    order["status"] = "WITHDRAWN"
    touch(order)

    block = db.blocks.get(order["number_block_id"])
    carrier = db.carriers.get(order["carrier_id"])

    if block is not None:
        if block["allocation_status"] == "RECLAMATION_PENDING":
            block["allocation_status"] = (
                "ASSIGNED" if block["activated_at"] is not None else "RESERVED"
            )
        touch(block)
        rate_center = db.rate_centers.get(block["rate_center_id"])
        if rate_center is not None:
            touch(rate_center)

    if carrier is not None:
        touch(carrier)
