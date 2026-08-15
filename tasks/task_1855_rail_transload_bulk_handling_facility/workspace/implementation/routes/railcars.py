"""Railcar endpoints: registry (advance consist), arrival, departure, safety
holds, cleaning loop, and release with its demurrage/PULL-move settlement."""

from datetime import timedelta

from flask import Blueprint, request

import domain
from db import STORE, new_entity, touch, public, now, iso
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_FACILITY_SUSPENDED, ERR_DERAIL_ENGAGED, ERR_CAR_HELD,
    ERR_UNPAID_CHARGES,
)
from middleware import auth_context, require_role, require_ownership, ALL_ROLES
from response import ok, paginated
from util import round3, tons_add
from validate import body, req_str, req_pos_num, req_enum

bp = Blueprint("railcars", __name__)

WASH_TYPES = ("RINSE", "DETERGENT", "STEAM")


def _get_car_or_404(railcar_id):
    car = STORE.railcars.get(railcar_id)
    if car is None:
        raise_err(ERR_NOT_FOUND, "railcar id does not exist")
    return car


@bp.route("/transload/railcars", methods=["POST"])
def register_railcar():
    _, role = auth_context()
    require_role(role, ["YardMaster"])
    data = body()
    # Priority 3: body FK ids resolve (before shape checks at priority 4).
    for field, table, label in (
        ("customer_id", STORE.customers, "customer"),
        ("product_id", STORE.products, "product"),
        ("lot_id", STORE.lots, "lot"),
    ):
        raw = data.get(field)
        if isinstance(raw, str) and raw not in table:
            raise_err(ERR_NOT_FOUND, "%s id does not exist" % label)
    customer_id = req_str(data, "customer_id")
    product_id = req_str(data, "product_id")
    lot_id = req_str(data, "lot_id")
    car_initials = req_str(data, "car_initials")
    car_number = req_str(data, "car_number")
    quantity_loaded_tons = round3(req_pos_num(data, "quantity_loaded_tons"))
    # Referential integrity: the lot must belong to the customer and hold the
    # same product.
    lot = STORE.lots[lot_id]
    if lot["customer_id"] != customer_id:
        raise_err(ERR_INVALID_REQUEST, "lot does not belong to the customer")
    if lot["product_id"] != product_id:
        raise_err(ERR_INVALID_REQUEST, "lot does not hold the product")
    car = new_entity(STORE.railcars, {
        "car_initials": car_initials,
        "car_number": car_number,
        "customer_id": customer_id,
        "product_id": product_id,
        "lot_id": lot_id,
        "quantity_loaded_tons": quantity_loaded_tons,
        "quantity_remaining_tons": None,
        "track_id": None,
        "spot_number": None,
        "placement_status": "REGISTERED",
        "hold_status": "NONE",
        "arrival_timestamp": None,
        "placed_timestamp": None,
        "released_timestamp": None,
        "departed_timestamp": None,
    })
    return ok(domain.car_view(car), status=201)


@bp.route("/transload/railcars/<rid>", methods=["GET"])
def get_railcar(rid):
    user_id, role = auth_context()
    require_role(role, ALL_ROLES)
    car = _get_car_or_404(rid)
    require_ownership(user_id, role, car["customer_id"])
    return ok(domain.car_view(car))


@bp.route("/transload/railcars", methods=["GET"])
def list_railcars():
    user_id, role = auth_context()
    require_role(role, ALL_ROLES)
    customer_id = request.args.get("customer_id")
    product_id = request.args.get("product_id")
    lot_id = request.args.get("lot_id")
    track_id = request.args.get("track_id")
    placement_status = request.args.get("placement_status")
    if role == "CustomerRep":
        if customer_id is not None and customer_id != user_id:
            require_ownership(user_id, role, customer_id)
        customer_id = user_id
    items = sorted(STORE.railcars.values(), key=lambda c: (c["created_at"], c["_seq"]))
    if customer_id is not None:
        items = [c for c in items if c["customer_id"] == customer_id]
    if product_id is not None:
        items = [c for c in items if c["product_id"] == product_id]
    if lot_id is not None:
        items = [c for c in items if c["lot_id"] == lot_id]
    if track_id is not None:
        items = [c for c in items if c["track_id"] == track_id]
    if placement_status is not None:
        items = [c for c in items if c["placement_status"] == placement_status]
    page, meta = paginated(items)
    return ok([domain.car_view(c) for c in page], pagination=meta)


@bp.route("/transload/railcars/<rid>/arrive", methods=["POST"])
def arrive(rid):
    _, role = auth_context()
    require_role(role, ["YardMaster"])
    car = _get_car_or_404(rid)
    if car["placement_status"] != "REGISTERED":
        raise_err(ERR_INVALID_STATE, "railcar is not REGISTERED")
    car["arrival_timestamp"] = iso(now())
    car["quantity_remaining_tons"] = car["quantity_loaded_tons"]
    car["placement_status"] = "ARRIVED"
    lot = STORE.lots[car["lot_id"]]
    lot["quantity_received_tons"] = tons_add(
        lot["quantity_received_tons"], car["quantity_loaded_tons"]
    )
    touch(lot)
    touch(car)
    return ok(domain.car_view(car))


@bp.route("/transload/railcars/<rid>/depart", methods=["POST"])
def depart(rid):
    _, role = auth_context()
    require_role(role, ["YardMaster"])
    car = _get_car_or_404(rid)
    if car["placement_status"] != "RELEASED":
        raise_err(ERR_INVALID_STATE, "railcar is not RELEASED")
    car["departed_timestamp"] = iso(now())
    car["placement_status"] = "DEPARTED"
    for sw in STORE.switch_orders.values():
        if (sw["railcar_id"] == car["id"] and sw["move_type"] == "PULL"
                and sw["status"] == "SCHEDULED"):
            sw["status"] = "COMPLETED"
    touch(car)
    return ok(domain.car_view(car))


@bp.route("/transload/railcars/<rid>/place-hold", methods=["POST"])
def place_hold(rid):
    _, role = auth_context()
    require_role(role, ["SafetyOfficer"])
    car = _get_car_or_404(rid)
    data = body()
    req_str(data, "reason")
    if car["placement_status"] == "DEPARTED" or car["hold_status"] != "NONE":
        raise_err(ERR_INVALID_STATE, "railcar cannot be placed on hold from its current state")
    car["hold_status"] = "SAFETY_HOLD"
    touch(car)
    return ok(domain.car_view(car))


@bp.route("/transload/railcars/<rid>/lift-hold", methods=["POST"])
def lift_hold(rid):
    _, role = auth_context()
    require_role(role, ["SafetyOfficer"])
    car = _get_car_or_404(rid)
    if car["hold_status"] != "SAFETY_HOLD":
        raise_err(ERR_INVALID_STATE, "railcar is not on SAFETY_HOLD")
    car["hold_status"] = "NONE"
    touch(car)
    return ok(domain.car_view(car))


@bp.route("/transload/railcars/<rid>/start-cleaning", methods=["POST"])
def start_cleaning(rid):
    _, role = auth_context()
    require_role(role, ["TransferOperator"])
    car = _get_car_or_404(rid)
    data = body()
    wash_type = req_enum(data, "wash_type", WASH_TYPES)
    if car["placement_status"] != "EMPTY_AWAITING_CLEANING":
        raise_err(ERR_INVALID_STATE, "railcar is not EMPTY_AWAITING_CLEANING")
    product = STORE.products[car["product_id"]]
    if not product["requires_full_clean"]:
        raise_err(ERR_INVALID_STATE, "product does not require a full clean")
    domain.make_charge(
        car["customer_id"], car["id"], "CLEANING", 1,
        domain.CLEANING_FEES[wash_type],
    )
    car["placement_status"] = "CLEANING"
    touch(car)
    return ok(domain.car_view(car))


@bp.route("/transload/railcars/<rid>/pass-cleaning", methods=["POST"])
def pass_cleaning(rid):
    _, role = auth_context()
    require_role(role, ["TransferOperator"])
    car = _get_car_or_404(rid)
    if car["placement_status"] != "CLEANING":
        raise_err(ERR_INVALID_STATE, "railcar is not CLEANING")
    car["placement_status"] = "READY_FOR_RELEASE"
    touch(car)
    return ok(domain.car_view(car))


@bp.route("/transload/railcars/<rid>/fail-cleaning", methods=["POST"])
def fail_cleaning(rid):
    _, role = auth_context()
    require_role(role, ["TransferOperator"])
    car = _get_car_or_404(rid)
    if car["placement_status"] != "CLEANING":
        raise_err(ERR_INVALID_STATE, "railcar is not CLEANING")
    car["placement_status"] = "EMPTY_AWAITING_CLEANING"
    touch(car)
    return ok(domain.car_view(car))


@bp.route("/transload/railcars/<rid>/release", methods=["POST"])
def release(rid):
    _, role = auth_context()
    require_role(role, ["YardMaster"])
    car = _get_car_or_404(rid)
    # Priority 5: state.
    if car["placement_status"] != "READY_FOR_RELEASE":
        raise_err(ERR_INVALID_STATE, "railcar is not READY_FOR_RELEASE")
    # Priority 7: facility posture and derail gates.
    if STORE.posture == "SUSPENDED":
        raise_err(ERR_FACILITY_SUSPENDED, "facility safety posture is SUSPENDED")
    track = STORE.tracks[car["track_id"]]
    if track["derail_protection"] != "DISENGAGED":
        raise_err(ERR_DERAIL_ENGAGED, "track derail protection is ENGAGED")
    # Priority 8: car-level safety hold.
    if car["hold_status"] != "NONE":
        raise_err(ERR_CAR_HELD, "railcar is on SAFETY_HOLD")
    # Priority 13: no ISSUED (unpaid) invoice on the customer.
    for inv in STORE.invoices.values():
        if inv["customer_id"] == car["customer_id"] and inv["status"] == "ISSUED":
            raise_err(ERR_UNPAID_CHARGES, "customer has an unpaid ISSUED invoice")
    now_dt = now()
    car["released_timestamp"] = iso(now_dt)
    # Final demurrage, computed with the release timestamp as its end; the
    # charge is created even when the amount is zero.
    days, cents = domain.demurrage_accrual(car)
    domain.make_charge(car["customer_id"], car["id"], "DEMURRAGE", days, cents)
    # The PULL crew move with its switching fee.
    domain.create_switch_move(
        car["customer_id"], car["track_id"], car["id"], "PULL",
        now_dt, now_dt + timedelta(minutes=domain.PULL_WINDOW_MINUTES),
    )
    track["occupied_spots"] -= 1
    touch(track)
    for so in STORE.spot_orders.values():
        if so["railcar_id"] == car["id"] and so["status"] == "EXECUTED":
            so["status"] = "CLOSED"
            touch(so)
    car["placement_status"] = "RELEASED"
    touch(car)
    return ok(domain.car_view(car))
