"""Farm-out offer creation, reads, and decision events (PRD §3.5, §2.8)."""
from flask import Blueprint, request

import db
import views
from db import new_full, touch
from errors import (
    ERR_AFFILIATE_INELIGIBLE,
    ERR_FORBIDDEN,
    ERR_FULFILLMENT_CONFLICT,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    err,
)
from helpers import (
    as_int,
    as_str,
    get_pagination,
    paginate,
    require_fields,
    sort_by_created,
)
from middleware import authenticate, require_role
from response import success
from routes.common import get_body, must_exist
from services import calc
from services.aggregates import recompute_open_farmouts
from services.reservation_logic import (
    active_assignment_for,
    open_farmout_for,
    run_final_settlement,
)

bp = Blueprint("farmouts", __name__)

DECISION_ACTIONS = {"ACCEPT", "REJECT", "RECALL"}


@bp.route("/farm-out-orders", methods=["POST"])
def create_farm_out_order():
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    body = get_body()
    require_fields(body, ["reservation_id", "affiliate_id", "expected_reservation_version"])
    reservation_id = as_str(body["reservation_id"], "reservation_id")
    affiliate_id = as_str(body["affiliate_id"], "affiliate_id")
    expected_version = as_int(body["expected_reservation_version"], "expected_reservation_version")

    # Existence of body FKs, left-to-right (PRD §2.5).
    reservation = must_exist(db.reservations, reservation_id, "Reservation")
    affiliate = must_exist(db.affiliates, affiliate_id, "Affiliate")

    # Version guard first (PRD §2.8): a stale view after an in-house assignment
    # advanced the reservation must surface ERR_STALE_VERSION.
    if expected_version != reservation["version"]:
        raise err(ERR_STALE_VERSION, "Stale reservation version")

    # Fulfillment-exclusivity (PRD §3.5, ERR_FULFILLMENT_CONFLICT).
    if active_assignment_for(reservation_id) is not None or open_farmout_for(reservation_id) is not None:
        raise err(ERR_FULFILLMENT_CONFLICT, "Reservation already has a fulfillment commitment")

    # Affiliate must be ACTIVE (PRD §3.5, ERR_AFFILIATE_INELIGIBLE).
    if affiliate["status"] != "ACTIVE":
        raise err(ERR_AFFILIATE_INELIGIBLE, "Affiliate is not eligible")

    vclass = db.vehicle_classes[reservation["vehicle_class_id"]]
    payout = calc.affiliate_payout(reservation, vclass, affiliate)

    order = new_full({
        "reservation_id": reservation_id,
        "affiliate_id": affiliate_id,
        "offered_payout_cents": payout,
        "status": "OFFERED",
        "decline_reason": None,
    })
    db.farm_out_orders[order["id"]] = order

    # Side effects (PRD §3.5): bump reservation.version; refresh open_farmouts.
    touch(reservation)
    recompute_open_farmouts(affiliate_id)

    return success(views.farm_out_order(order), status=201)


@bp.route("/farm-out-orders/<order_id>", methods=["GET"])
def get_farm_out_order(order_id):
    user_id, role = authenticate()
    require_role(role, ["DispatchAdmin", "Dispatcher", "AffiliatePartner"])
    rec = must_exist(db.farm_out_orders, order_id, "FarmOutOrder")
    if role == "AffiliatePartner" and rec["affiliate_id"] != user_id:
        raise err(ERR_FORBIDDEN, "Partner may only read their own offers")
    return success(views.farm_out_order(rec))


@bp.route("/farm-out-orders", methods=["GET"])
def list_farm_out_orders():
    user_id, role = authenticate()
    require_role(role, ["DispatchAdmin", "Dispatcher", "AffiliatePartner"])
    limit, offset = get_pagination(request.args)
    items = list(db.farm_out_orders.values())
    res_filter = request.args.get("reservation_id")
    aff_filter = request.args.get("affiliate_id")
    if res_filter is not None:
        items = [o for o in items if o["reservation_id"] == res_filter]
    if aff_filter is not None:
        items = [o for o in items if o["affiliate_id"] == aff_filter]
    # A partner only sees their own offers (PRD §2.1).
    if role == "AffiliatePartner":
        items = [o for o in items if o["affiliate_id"] == user_id]
    items = sort_by_created(items)
    window, pagination = paginate(items, limit, offset)
    return success([views.farm_out_order(o) for o in window], pagination=pagination)


@bp.route("/farm-out-orders/<order_id>/decision-events", methods=["POST"])
def decision_events(order_id):
    user_id, role = authenticate()
    require_role(role, ["AffiliatePartner", "Dispatcher"])
    order = must_exist(db.farm_out_orders, order_id, "FarmOutOrder")
    body = get_body()
    require_fields(body, ["action"])
    from helpers import as_enum
    action = as_enum(body["action"], "action", DECISION_ACTIONS)

    if action in ("ACCEPT", "REJECT"):
        # ACCEPT/REJECT: AffiliatePartner owning the offer (PRD §3.5).
        if role != "AffiliatePartner":
            raise err(ERR_FORBIDDEN, "Only the affiliate partner may accept or reject")
        if order["affiliate_id"] != user_id:
            raise err(ERR_FORBIDDEN, "Partner may only decide their own offers")
    else:  # RECALL
        if role != "Dispatcher":
            raise err(ERR_FORBIDDEN, "Only a Dispatcher may recall an offer")

    if action == "ACCEPT":
        return _accept(order)
    if action == "REJECT":
        return _reject(order, body)
    return _recall(order)


def _accept(order):
    # Preconditions (PRD §3.5).
    if order["status"] != "OFFERED":
        raise err(ERR_INVALID_STATE, "Farm-out order is not OFFERED")
    affiliate = db.affiliates[order["affiliate_id"]]
    if affiliate["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Affiliate is not ACTIVE")
    reservation = db.reservations[order["reservation_id"]]
    if reservation["trip_status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Reservation is not CONFIRMED")

    order["status"] = "ACCEPTED"
    touch(order)

    # Three-hop cascade (PRD §3.5): fulfillment_mode, trip_status, final settlement.
    reservation["fulfillment_mode"] = "FARMED_OUT"
    reservation["trip_status"] = "COMPLETED"
    # chargeable_wait_minutes is 0 on a farm-out accept (no in-house wait events).
    run_final_settlement(reservation)
    touch(reservation)

    recompute_open_farmouts(order["affiliate_id"])
    return success(views.farm_out_order(order))


def _reject(order, body):
    if order["status"] != "OFFERED":
        raise err(ERR_INVALID_STATE, "Farm-out order is not OFFERED")
    decline_reason = body.get("decline_reason")
    if decline_reason is not None:
        decline_reason = as_str(decline_reason, "decline_reason")
    order["status"] = "REJECTED"
    order["decline_reason"] = decline_reason
    touch(order)
    # Reservation stays CONFIRMED / IN_HOUSE (PRD §3.5).
    recompute_open_farmouts(order["affiliate_id"])
    return success(views.farm_out_order(order))


def _recall(order):
    if order["status"] != "OFFERED":
        raise err(ERR_INVALID_STATE, "Farm-out order is not OFFERED")
    order["status"] = "RECALLED"
    touch(order)
    # Reservation stays CONFIRMED / IN_HOUSE (PRD §3.5).
    recompute_open_farmouts(order["affiliate_id"])
    return success(views.farm_out_order(order))
