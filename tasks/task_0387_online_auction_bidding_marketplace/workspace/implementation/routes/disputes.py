"""Dispute endpoints. PRD §3.10."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import response
import constants as C
import middleware as mw
from services import core, sales
from routes.helpers import get_json_body, paginate_list

bp = Blueprint("disputes", __name__)

VALID_REASONS = {"ITEM_NOT_RECEIVED", "NOT_AS_DESCRIBED", "DAMAGED"}


@bp.route("/orders/<order_id>/disputes", methods=["POST"])
def open_dispute(order_id):
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"Buyer"})          # priority 2
    body = get_json_body()
    order = db.orders.get(order_id)             # existence (priority 4)
    if order is None:
        raise errors.not_found("Order not found.")

    opener_account_id = body.get("opener_account_id")
    if not isinstance(opener_account_id, str) or opener_account_id == "":
        raise errors.invalid_request("opener_account_id is required.")
    # Ownership (priority 3): the opener is the order's buyer and acting account.
    if opener_account_id != caller.user_id:
        raise errors.not_owner("opener_account_id must be the acting account.")
    if order["buyer_account_id"] != opener_account_id:
        raise errors.not_owner("Only the order's buyer may open a dispute.")
    opener = db.accounts.get(opener_account_id)
    if opener is None:
        raise errors.not_found("Opener account not found.")
    mw.check_account_not_closed(caller)

    reason = body.get("reason")
    requested_amount_cents = body.get("requested_amount_cents", None)

    # Dispute eligibility (priority 16, ERR_DISPUTE_NOT_ELIGIBLE).
    if order["payment_status"] != "PAID":
        raise errors.dispute_not_eligible("Only a PAID order may be disputed.")
    # One OPEN dispute per order.
    for d in db.disputes.values():
        if d["order_id"] == order_id and d["status"] == "OPEN":
            raise errors.dispute_not_eligible("An OPEN dispute already exists for this order.")
    # requested_amount within paid.
    if requested_amount_cents is None:
        raise errors.invalid_request("requested_amount_cents is required.")
    if isinstance(requested_amount_cents, bool) or not isinstance(requested_amount_cents, int):
        raise errors.invalid_request("requested_amount_cents must be an integer.")
    if requested_amount_cents < 1:
        raise errors.dispute_not_eligible("requested_amount_cents must be >= 1.")
    if requested_amount_cents > order["paid_amount_cents"]:
        raise errors.dispute_not_eligible("requested_amount_cents exceeds the order's paid amount.")

    # Field-shape (priority 17): reason enum.
    if reason not in VALID_REASONS:
        raise errors.invalid_request("reason must be ITEM_NOT_RECEIVED, NOT_AS_DESCRIBED, or DAMAGED.")

    did = db.new_id()
    dispute = {
        "id": did,
        "order_id": order_id,
        "opener_account_id": opener_account_id,
        "reason": reason,
        "requested_amount_cents": requested_amount_cents,
        "resolved_amount_cents": 0,
        "status": "OPEN",
    }
    core.stamp_new(dispute)
    db.disputes[did] = dispute
    return response.success(core.ser_dispute(dispute), status=201)


@bp.route("/disputes/<dispute_id>", methods=["GET"])
def get_dispute(dispute_id):
    caller = mw.require_auth()
    mw.require_role(caller, {"Buyer", "Seller", "PlatformAdmin"})
    dispute = db.disputes.get(dispute_id)
    if dispute is None:
        raise errors.not_found("Dispute not found.")
    return response.success(core.ser_dispute(dispute), status=200)


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    caller = mw.require_auth()
    mw.require_role(caller, {"Buyer", "Seller", "PlatformAdmin"})
    order_id = request.args.get("order_id")
    opener_account_id = request.args.get("opener_account_id")
    items = list(db.disputes.values())
    if order_id is not None:
        items = [d for d in items if d["order_id"] == order_id]
    if opener_account_id is not None:
        items = [d for d in items if d["opener_account_id"] == opener_account_id]
    return paginate_list(items, core.ser_dispute)


@bp.route("/disputes/<dispute_id>/respond", methods=["POST"])
def respond_dispute(dispute_id):
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"Seller"})         # priority 2
    dispute = db.disputes.get(dispute_id)       # existence (priority 4)
    if dispute is None:
        raise errors.not_found("Dispute not found.")
    order = db.orders.get(dispute["order_id"])
    if order is None:
        raise errors.not_found("Order not found.")
    # Ownership (priority 3): the acting seller is the order's seller.
    if order["seller_account_id"] != caller.user_id:
        raise errors.not_owner("Only the order's seller may respond.")
    mw.check_account_not_closed(caller)

    # State (priority 6): respond defined only from OPEN.
    if dispute["status"] != "OPEN":
        raise errors.invalid_state("Only an OPEN dispute may be responded to.")

    dispute["status"] = "SELLER_RESPONDED"
    core.touch(dispute)
    return response.success(core.ser_dispute(dispute), status=200)


@bp.route("/disputes/<dispute_id>/escalate", methods=["POST"])
def escalate_dispute(dispute_id):
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"Buyer"})          # priority 2
    dispute = db.disputes.get(dispute_id)       # existence (priority 4)
    if dispute is None:
        raise errors.not_found("Dispute not found.")
    # Ownership (priority 3): the acting buyer is the dispute opener.
    if dispute["opener_account_id"] != caller.user_id:
        raise errors.not_owner("Only the dispute opener may escalate.")
    mw.check_account_not_closed(caller)

    # State (priority 6): escalate defined from OPEN or SELLER_RESPONDED.
    if dispute["status"] not in ("OPEN", "SELLER_RESPONDED"):
        raise errors.invalid_state("Only an OPEN or SELLER_RESPONDED dispute may be escalated.")

    # Dispute window (priority 8): from OPEN, only after DISPUTE_RESPONSE_SECONDS.
    if dispute["status"] == "OPEN":
        deadline = db.parse_iso(dispute["created_at"]) + timedelta(seconds=C.DISPUTE_RESPONSE_SECONDS)
        if db.now_dt() < deadline:
            raise errors.window_expired("A buyer may escalate an OPEN dispute only after the seller-response window.")

    dispute["status"] = "ESCALATED"
    core.touch(dispute)
    return response.success(core.ser_dispute(dispute), status=200)


@bp.route("/disputes/<dispute_id>/close", methods=["POST"])
def close_dispute(dispute_id):
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"Buyer"})          # priority 2
    dispute = db.disputes.get(dispute_id)       # existence (priority 4)
    if dispute is None:
        raise errors.not_found("Dispute not found.")
    # Ownership (priority 3): the acting buyer is the dispute opener.
    if dispute["opener_account_id"] != caller.user_id:
        raise errors.not_owner("Only the dispute opener may close it.")
    mw.check_account_not_closed(caller)

    # State (priority 6): close defined only from SELLER_RESPONDED.
    if dispute["status"] != "SELLER_RESPONDED":
        raise errors.invalid_state("Only a SELLER_RESPONDED dispute may be closed.")

    dispute["status"] = "CLOSED"
    core.touch(dispute)
    return response.success(core.ser_dispute(dispute), status=200)


@bp.route("/disputes/<dispute_id>/resolve", methods=["POST"])
def resolve_dispute(dispute_id):
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"PlatformAdmin"})  # priority 2
    body = get_json_body()
    dispute = db.disputes.get(dispute_id)       # existence (priority 4)
    if dispute is None:
        raise errors.not_found("Dispute not found.")
    order = db.orders.get(dispute["order_id"])
    if order is None:
        raise errors.not_found("Order not found.")

    # State (priority 6): resolve defined only from ESCALATED.
    if dispute["status"] != "ESCALATED":
        raise errors.invalid_state("Only an ESCALATED dispute may be resolved.")

    approved_amount_cents = body.get("approved_amount_cents", None)
    if approved_amount_cents is None:
        raise errors.invalid_request("approved_amount_cents is required.")
    if isinstance(approved_amount_cents, bool) or not isinstance(approved_amount_cents, int):
        raise errors.invalid_request("approved_amount_cents must be an integer.")
    if approved_amount_cents < 0:
        raise errors.invalid_request("approved_amount_cents must be >= 0.")
    # Approved amount must not exceed paid_amount_cents (ERR_REFUND_EXCEEDS_PAID).
    if approved_amount_cents > order["paid_amount_cents"]:
        raise errors.refund_exceeds_paid()

    if approved_amount_cents > 0:
        dispute["status"] = "RESOLVED_REFUND"
        dispute["resolved_amount_cents"] = approved_amount_cents
        core.touch(dispute)
        # Refund cascade (depth-3): dispute -> order payment -> fee invoice.
        sales.apply_refund(order, approved_amount_cents)
    else:
        # approved == 0: no refund; order payment and fee invoice untouched.
        dispute["status"] = "RESOLVED_NO_REFUND"
        dispute["resolved_amount_cents"] = 0
        core.touch(dispute)

    return response.success(core.ser_dispute(dispute), status=200)
