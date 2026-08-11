"""Sales orders."""

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INSUFFICIENT_INVENTORY,
    ERR_LABEL_EXPIRED,
    ERR_LABEL_NOT_APPROVED,
    ERR_LICENSE_NOT_ACTIVE,
    ERR_PERMIT_EXPIRED,
    ERR_RETURN_WINDOW_EXPIRED,
    invalid_state,
    not_found,
    validation,
)
from middleware import require_roles
from response import paginate, success_object
from services import (
    INTERSTATE_CHANNELS,
    ORDER_CHANNELS,
    STATE_TO_MARKET,
    UNIT_LITERS,
    EXCISE_RATE_CENTS_PER_LITER,
    _d,
    emit_event,
    expired,
    q0,
    recompute_excise_report,
    reports_covering,
    ser_order,
)

bp = Blueprint("sales", __name__, url_prefix="/cidery")

ORDER_READ = ("SalesRep", "ComplianceOfficer", "PlatformAdmin")


def body():
    return request.get_json(silent=True) or {}


def _get_order(order_id):
    rec = db.store["orders"].get(order_id)
    if rec is None:
        raise not_found("order")
    return rec


def _scoped_active_licenses(state):
    return [
        lic for lic in db.store["licenses"].values()
        if lic["status"] == "ACTIVE" and state in (lic["scope_states"] or [])
    ]


def _check_interstate_license(state):
    """For CLUB_SUBSCRIPTION / WHOLESALE_DISTRIBUTION: an ACTIVE license whose
    scope_states includes the destination state must exist, and the permit
    must be unexpired."""
    scoped = _scoped_active_licenses(state)
    if not scoped:
        raise ApiError(
            ERR_LICENSE_NOT_ACTIVE,
            "no ACTIVE license scoped to the destination state",
            409,
        )
    if all(expired(lic) for lic in scoped):
        raise ApiError(ERR_PERMIT_EXPIRED, "license permit is expired", 409)


@bp.post("/orders")
@require_roles("SalesRep")
def create_order():
    b = body()
    product = db.store["products"].get(b.get("product_id"))
    if product is None:
        raise not_found("product")
    run = db.store["packaging_runs"].get(b.get("packaging_run_id"))
    if run is None:
        raise not_found("packaging run")
    channel = b.get("channel")
    if channel not in ORDER_CHANNELS:
        raise validation(f"channel must be one of {sorted(ORDER_CHANNELS)}")
    destination_state = b.get("destination_state")
    units = b.get("units")
    if not isinstance(units, int) or units <= 0:
        raise validation("units must be an integer greater than zero")
    unit_price_cents = b.get("unit_price_cents")
    if not isinstance(unit_price_cents, int) or unit_price_cents < 0:
        raise validation("unit_price_cents must be a non-negative integer")
    if channel in INTERSTATE_CHANNELS:
        _check_interstate_license(destination_state)
    rec = {
        "channel": channel,
        "destination_state": destination_state,
        "product_id": product["id"],
        "packaging_run_id": run["id"],
        "units": units,
        "unit_price_cents": unit_price_cents,
        "subtotal_cents": units * unit_price_cents,
        "excise_tax_cents": None,
        "total_cents": None,
        "shipped_at": None,
        "status": "DRAFT",
    }
    db.stamp_new(rec)
    db.store["orders"][rec["id"]] = rec
    return success_object(ser_order(rec), 201)


@bp.get("/orders/<id>")
@require_roles(*ORDER_READ)
def get_order(id):
    return success_object(ser_order(_get_order(id)))


@bp.get("/orders")
@require_roles(*ORDER_READ)
def list_orders():
    items = list(db.store["orders"].values())
    for param in (
        "status", "channel", "destination_state", "product_id", "packaging_run_id"
    ):
        val = request.args.get(param)
        if val is not None:
            items = [o for o in items if o.get(param) == val]
    return paginate(items, ser_order)


@bp.post("/orders/<id>/confirm")
@require_roles("SalesRep")
def confirm_order(id):
    order = _get_order(id)
    if order["status"] != "DRAFT":
        raise invalid_state("order is not DRAFT")
    run = db.store["packaging_runs"].get(order["packaging_run_id"])
    if run is None or run["status"] != "COMPLETED":
        raise invalid_state("referenced packaging run is not COMPLETED")
    # label gates for the product and the destination state's regulator market
    market = STATE_TO_MARKET.get(order["destination_state"])
    if market is not None:
        approval = next(
            (la for la in db.store["label_approvals"].values()
             if la["product_id"] == order["product_id"] and la["market"] == market),
            None,
        )
        if approval is None or approval["status"] != "APPROVED":
            raise ApiError(
                ERR_LABEL_NOT_APPROVED,
                "label approval for the destination market is not APPROVED",
                409,
            )
        if approval["market"] != "FEDERAL_TTB" and expired(approval):
            raise ApiError(ERR_LABEL_EXPIRED, "label approval is expired", 409)
    if order["channel"] in INTERSTATE_CHANNELS:
        _check_interstate_license(order["destination_state"])
    # inventory is checked last: units_produced minus prior SHIPPED/DELIVERED
    committed = sum(
        o["units"] for o in db.store["orders"].values()
        if o["packaging_run_id"] == run["id"]
        and o["status"] in ("SHIPPED", "DELIVERED")
    )
    if run["units_produced"] - committed < order["units"]:
        raise ApiError(
            ERR_INSUFFICIENT_INVENTORY,
            "order units exceed remaining packaging run inventory",
            409,
        )
    # excise attaches at confirmation: per-line round-half-up to whole cents.
    # PRD 3.6 defines excise_tax_cents completely: "the `excise_tax_cents` is
    # that liter figure times 22.6, rounded half up to whole cents on the line",
    # and total_cents = subtotal_cents + excise_tax_cents. The NY on-premise
    # 4% tax ("may additionally owe") names no response field, so it does not
    # alter either figure.
    line_liters = _d(order["units"]) * UNIT_LITERS[run["package_format"]]
    excise = q0(line_liters * EXCISE_RATE_CENTS_PER_LITER)
    order["excise_tax_cents"] = excise
    order["total_cents"] = order["subtotal_cents"] + excise
    order["status"] = "CONFIRMED"
    db.bump(order)
    return success_object(ser_order(order))


@bp.post("/orders/<id>/ship")
@require_roles("SalesRep")
def ship_order(id):
    order = _get_order(id)
    if order["status"] != "CONFIRMED":
        raise invalid_state("order is not CONFIRMED")
    order["status"] = "SHIPPED"
    order["shipped_at"] = db.now()
    db.bump(order)
    for rep in reports_covering(order["shipped_at"]):
        if rep["status"] == "OPEN":
            recompute_excise_report(rep)
    return success_object(ser_order(order))


@bp.post("/orders/<id>/deliver")
@require_roles("SalesRep")
def deliver_order(id):
    order = _get_order(id)
    if order["status"] != "SHIPPED":
        raise invalid_state("order is not SHIPPED")
    order["status"] = "DELIVERED"
    db.bump(order)
    return success_object(ser_order(order))


@bp.post("/orders/<id>/return")
@require_roles("SalesRep")
def return_order(id):
    order = _get_order(id)
    if order["status"] != "SHIPPED":
        raise invalid_state("order is not SHIPPED")
    if db.now() - order["shipped_at"] > timedelta(days=30):
        raise ApiError(
            ERR_RETURN_WINDOW_EXPIRED,
            "return attempted more than 30 days after shipped_at",
            409,
        )
    order["status"] = "RETURNED"
    db.bump(order)
    covering = reports_covering(order["shipped_at"])
    late = False
    for rep in covering:
        if rep["status"] == "OPEN":
            recompute_excise_report(rep)
        elif rep["status"] in ("FILED", "AMENDED"):
            late = True
    if late:
        emit_event(
            "SalesOrder", order["id"], "LATE_RETURN",
            {"status": "SHIPPED"}, {"status": "RETURNED"},
        )
    return success_object(ser_order(order))


@bp.post("/orders/<id>/cancel")
@require_roles("SalesRep")
def cancel_order(id):
    order = _get_order(id)
    if order["status"] not in ("DRAFT", "CONFIRMED"):
        raise invalid_state("order cannot be cancelled from its current state")
    order["status"] = "CANCELLED"
    db.bump(order)
    return success_object(ser_order(order))
