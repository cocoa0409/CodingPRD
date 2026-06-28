"""Fabrication lab orders (PRD §3.7)."""

from flask import Blueprint, request

import calculations as calc
import db
import errors
import middleware as mw
import response as resp
import services
import validate as v

bp = Blueprint("lab_orders", __name__)

ALL_ROLES = {"PracticeAdmin", "Podiatrist", "BillingSpecialist", "FrontDesk", "PayerAgent"}


def _bad_state(msg="LabOrder not in a legal state for the requested transition."):
    return errors.ApiError(errors.ERR_LAB_ORDER_BAD_STATE, 409, msg)


def _validate_line_items(line_items):
    if not isinstance(line_items, list) or len(line_items) == 0:
        raise errors.invalid_request("line_items must be a non-empty array.")
    for item in line_items:
        if not isinstance(item, dict):
            raise errors.invalid_request("Each line item must be an object.")
        if not isinstance(item.get("description"), str) or item["description"] == "":
            raise errors.invalid_request("line item description must be a non-empty string.")
        if not isinstance(item.get("l_code"), str) or item["l_code"] == "":
            raise errors.invalid_request("line item l_code must be a non-empty string.")
        unit_price = item.get("unit_price_cents")
        if isinstance(unit_price, bool) or not isinstance(unit_price, int):
            raise errors.invalid_request("line item unit_price_cents must be an integer.")
        quantity = item.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise errors.invalid_request("line item quantity must be an integer >= 1.")
        discount = item.get("discount_pct")
        if isinstance(discount, bool) or not isinstance(discount, (int, float)):
            raise errors.invalid_request("line item discount_pct must be a number.")
        if discount < 0 or discount > 1:
            raise errors.invalid_request("line item discount_pct must be in [0, 1].")


@bp.route("/podiatry/lab-orders", methods=["POST"])
def create_lab_order():
    _, role = mw.authenticate()
    mw.require_role(role, {"BillingSpecialist"})
    body = mw.get_body()
    with db.lock():
        orthotic_rx_id = v.as_str(body, "orthotic_rx_id", required=True)
        rx = db.orthotic_rxs.get(orthotic_rx_id)
        if rx is None:
            raise errors.fk_not_found("orthotic_rx_id references a non-existent Rx.")
        lab_name = v.as_str(body, "lab_name", required=True)
        line_items = body.get("line_items")
        _validate_line_items(line_items)
        units_drawn = v.as_int(body, "units_drawn", required=True, minimum=1)

        # Draw against the Rx's linked PA (PRD §3.7) using the §2.11 ordered chain.
        pa = db.prior_authorizations[rx["prior_authorization_id"]]
        services.check_pa_drawable(pa, "ORTHOTIC", units_drawn)

        total_cents = calc.lab_order_total(line_items)
        entity = {
            "orthotic_rx_id": orthotic_rx_id,
            "lab_name": lab_name,
            "line_items": line_items,
            "total_cents": total_cents,
            "units_drawn": units_drawn,
            "status": "QUEUED",
        }
        db.stamp_common(entity)
        db.lab_orders[entity["id"]] = entity
        services.draw_pa_units(pa, units_drawn)
        return resp.success(entity, 201)


@bp.route("/podiatry/lab-orders", methods=["GET"])
def list_lab_orders():
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    rx_id = request.args.get("orthotic_rx_id")
    items = [lo for lo in db.lab_orders.values()
             if rx_id is None or lo["orthotic_rx_id"] == rx_id]
    page, meta = mw.paginate(items)
    return resp.success(page, 200, pagination=meta)


@bp.route("/podiatry/lab-orders/<lab_order_id>", methods=["GET"])
def get_lab_order(lab_order_id):
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    entity = db.lab_orders.get(lab_order_id)
    if entity is None:
        raise errors.not_found("Lab order not found.")
    return resp.success(entity, 200)


def _load(lab_order_id):
    entity = db.lab_orders.get(lab_order_id)
    if entity is None:
        raise errors.not_found("Lab order not found.")
    return entity


@bp.route("/podiatry/lab-orders/<lab_order_id>/ship", methods=["POST"])
def ship_lab_order(lab_order_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"BillingSpecialist"})
    with db.lock():
        lo = _load(lab_order_id)
        if lo["status"] != "QUEUED":
            raise _bad_state("ship requires status QUEUED.")
        lo["status"] = "SHIPPED"
        db.touch(lo)
        return resp.success(lo, 200)


@bp.route("/podiatry/lab-orders/<lab_order_id>/receive", methods=["POST"])
def receive_lab_order(lab_order_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"FrontDesk"})
    with db.lock():
        lo = _load(lab_order_id)
        if lo["status"] != "SHIPPED":
            raise _bad_state("receive requires status SHIPPED.")
        lo["status"] = "RECEIVED"
        db.touch(lo)
        # Cascade B: bubble parent OrthoticRx -> FULFILLED (terminal).
        rx = db.orthotic_rxs.get(lo["orthotic_rx_id"])
        if rx is not None:
            rx["status"] = "FULFILLED"
            db.touch(rx)
        return resp.success(lo, 200)


@bp.route("/podiatry/lab-orders/<lab_order_id>/cancel", methods=["POST"])
def cancel_lab_order(lab_order_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"BillingSpecialist"})
    with db.lock():
        lo = _load(lab_order_id)
        if lo["status"] != "QUEUED":
            raise _bad_state("cancel requires status QUEUED.")
        lo["status"] = "CANCELLED"
        db.touch(lo)
        # Compensation: restore units to the linked PA (PRD §3.7).
        rx = db.orthotic_rxs.get(lo["orthotic_rx_id"])
        if rx is not None:
            pa = db.prior_authorizations.get(rx["prior_authorization_id"])
            if pa is not None:
                services.restore_pa_units(pa, lo["units_drawn"])
        return resp.success(lo, 200)
