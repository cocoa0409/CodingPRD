"""GarmentOrder lifecycle + option lines + pickup."""
from flask import Blueprint, request

import errors
import serializers as S
import validation as V
from db import db, stamp_create, touch
from errors import fail
from lookups import get_customer, get_profile, get_fabric, get_order, get_group
from middleware import get_user_context, require_role, get_json_body
from response import success, list_response
from services import calculations as calc
from services import orders as osvc

bp = Blueprint("orders", __name__)

GARMENT_TYPES = {"SUIT", "JACKET", "TROUSERS", "SHIRT", "DRESS"}
OPTION_CODES = {"MONOGRAM", "CONTRAST_LINING", "WORKING_CUFFS", "PICK_STITCH", "EXTRA_TROUSER"}


def _has_pickup(order_id):
    return any(p["order_id"] == order_id for p in db.pickups.values())


# ---------------------------------------------------------------------------
# GarmentOrder CRUD
# ---------------------------------------------------------------------------

@bp.post("/orders")
def create_order():
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "Customer"})
    body = get_json_body()
    customer_id = V.req_str(body, "customer_id")
    profile_id = V.req_str(body, "measurement_profile_id")
    garment_type = V.req_enum(body, "garment_type", GARMENT_TYPES)
    base_labor = V.req_int(body, "base_labor_cents", minimum=1)
    meters = V.req_number(body, "fabric_meters_required", gt=0)
    promised_date = V.req_str(body, "promised_date")
    is_rush = V.req_bool(body, "is_rush", default=False)
    group_order_id = V.opt_str(body, "group_order_id", default=None)

    # FK existence (priority 4)
    customer = get_customer(customer_id)
    profile = get_profile(profile_id)
    group = None
    if group_order_id is not None:
        group = get_group(group_order_id)

    # business constraint (priority 5): profile belongs to same customer
    if profile["customer_id"] != customer_id:
        fail(errors.ERR_PROFILE_CUSTOMER_MISMATCH,
             "Measurement profile belongs to a different customer")

    rec = stamp_create()
    rec.update({
        "customer_id": customer_id,
        "measurement_profile_id": profile_id,
        "group_order_id": group_order_id,
        "garment_type": garment_type,
        "base_labor_cents": base_labor,
        "is_rush": is_rush,
        "promised_date": promised_date,
        "fabric_meters_required": meters,
        "quoted_total_cents": 0,
        "locked_total_cents": 0,
        "deposit_due_cents": 0,
        "amount_paid_cents": 0,
        "balance_due_cents": 0,
        "store_credit_applied_cents": 0,
        "remake_round": 0,
        "status": "DRAFT",
    })
    db.garment_orders[rec["id"]] = rec

    # If joining a group whose lead_order_id is null, become the lead; recompute.
    if group is not None:
        if group["lead_order_id"] is None:
            group["lead_order_id"] = rec["id"]
        osvc.recompute_group(group)

    return success(S.garment_order(rec), status=201)


@bp.get("/orders/<oid>")
def get_order_route(oid):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist", "Customer"})
    o = get_order(oid)
    return success(S.garment_order(o))


@bp.get("/orders")
def list_orders():
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist", "Customer"})
    limit, offset = V.parse_pagination()
    customer_id = request.args.get("customer_id")
    profile_id = request.args.get("measurement_profile_id")
    group_id = request.args.get("group_order_id")
    status = request.args.get("status")

    def pred(o):
        if customer_id is not None and o["customer_id"] != customer_id:
            return False
        if profile_id is not None and o["measurement_profile_id"] != profile_id:
            return False
        if group_id is not None and o["group_order_id"] != group_id:
            return False
        if status is not None and o["status"] != status:
            return False
        return True

    items = [o for o in db.garment_orders.values() if pred(o)]
    items.sort(key=lambda o: o["created_at"])
    page = V.paginate(items, limit, offset)
    return list_response([S.garment_order(o) for o in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# Confirm (DRAFT -> CONFIRMED), PRD §3.3
# ---------------------------------------------------------------------------

@bp.post("/orders/<oid>/confirm")
def confirm_order(oid):
    _, role = get_user_context()
    require_role(role, {"SalesAssociate", "ShopManager"})
    o = get_order(oid)

    # state precondition (priority 7)
    if o["status"] != "DRAFT":
        fail(errors.ERR_ORDER_INVALID_STATE, "Order is not DRAFT")

    lines = osvc.order_option_lines(oid)
    # at least one option line
    if not lines:
        fail(errors.ERR_NO_OPTION_LINES, "Order has no option lines")

    # linked profile not SUPERSEDED
    profile = db.measurement_profiles.get(o["measurement_profile_id"])
    if profile is not None and profile["status"] == "SUPERSEDED":
        fail(errors.ERR_PROFILE_SUPERSEDED, "Measurement profile is superseded")

    # fabric sufficiency: the order's fabric = first option line's fabric
    first = lines[0]
    fabric = db.fabrics.get(first["fabric_id"])
    if fabric is not None and fabric["bolt_meters_remaining"] < o["fabric_meters_required"]:
        fail(errors.ERR_FABRIC_INSUFFICIENT, "Insufficient fabric on the bolt")

    # group must be FORMING
    group = None
    if o["group_order_id"]:
        group = db.group_orders.get(o["group_order_id"])
        if group is not None and group["status"] != "FORMING":
            fail(errors.ERR_GROUP_NOT_FORMING, "Group order is not FORMING")

    # --- side effects ---
    snapshot_price = first["fabric_price_per_meter_cents"]
    locked = calc.order_final_invoice(
        o["base_labor_cents"], o["fabric_meters_required"],
        snapshot_price, lines, o["is_rush"],
    )
    o["locked_total_cents"] = locked
    o["deposit_due_cents"] = calc.deposit_due(locked, o["is_rush"])
    o["status"] = "CONFIRMED"
    osvc.recompute_balance(o)  # nothing paid yet -> balance = locked

    # reserve fabric
    if fabric is not None:
        fabric["bolt_meters_remaining"] -= o["fabric_meters_required"]
        touch(fabric)

    # lock profile
    if profile is not None and profile["status"] == "DRAFT":
        profile["status"] = "LOCKED"
        touch(profile)

    touch(o)

    if group is not None:
        osvc.recompute_group(group)

    return success(S.garment_order(o))


# ---------------------------------------------------------------------------
# Cancel (PRD §3.8)
# ---------------------------------------------------------------------------

@bp.post("/orders/<oid>/cancel")
def cancel_order_route(oid):
    _, role = get_user_context()
    require_role(role, {"ShopManager"})
    o = get_order(oid)

    if _has_pickup(oid):
        fail(errors.ERR_ALREADY_PICKED_UP, "Order already has a pickup record")

    # valid from-states: DRAFT, CONFIRMED, IN_FITTING, REMAKE
    if o["status"] not in ("DRAFT", "CONFIRMED", "IN_FITTING", "REMAKE"):
        fail(errors.ERR_ORDER_INVALID_STATE, "Order cannot be cancelled from its current state")

    osvc.cancel_order(o)
    return success(S.garment_order(o))


# ---------------------------------------------------------------------------
# Pickup (READY -> PICKED_UP), PRD §3.7
# ---------------------------------------------------------------------------

@bp.post("/orders/<oid>/pickup")
def create_pickup(oid):
    _, role = get_user_context()
    require_role(role, {"SalesAssociate", "ShopManager"})
    o = get_order(oid)
    body = get_json_body()
    released_to_name = V.req_str(body, "released_to_name")

    if o["status"] != "READY":
        fail(errors.ERR_ORDER_INVALID_STATE, "Order is not READY for pickup")

    if o["balance_due_cents"] != 0:
        fail(errors.ERR_BALANCE_OUTSTANDING, "Outstanding balance must be settled")

    open_alt = any(
        t["order_id"] == oid and t["status"] == "OPEN"
        for t in db.alteration_tickets.values()
    )
    if open_alt:
        fail(errors.ERR_OPEN_ALTERATION_BLOCKS_PICKUP, "An open alteration ticket blocks pickup")

    rec = stamp_create()
    from response import now_iso
    rec.update({
        "order_id": oid,
        "released_to_name": released_to_name,
        "picked_up_at": now_iso(),
    })
    db.pickups[rec["id"]] = rec

    o["status"] = "PICKED_UP"
    touch(o)

    customer = db.customers.get(o["customer_id"])
    if customer is not None:
        customer["completed_order_count"] += 1
        touch(customer)

    # group FULFILLED if all non-cancelled members PICKED_UP
    if o["group_order_id"]:
        group = db.group_orders.get(o["group_order_id"])
        if group is not None and group["status"] == "LOCKED":
            members = osvc.group_members(group["id"])  # non-cancelled
            if members and all(m["status"] == "PICKED_UP" for m in members):
                group["status"] = "FULFILLED"
                touch(group)

    return success(S.pickup(rec), status=201)


@bp.get("/orders/<oid>/pickup")
def get_pickup(oid):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist", "Customer"})
    get_order(oid)
    limit, offset = V.parse_pagination()
    items = [p for p in db.pickups.values() if p["order_id"] == oid]
    items.sort(key=lambda p: p["created_at"])
    page = V.paginate(items, limit, offset)
    return list_response([S.pickup(p) for p in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# Option lines (PRD §3.2)
# ---------------------------------------------------------------------------

@bp.post("/orders/<oid>/option-lines")
def add_option_line(oid):
    _, role = get_user_context()
    require_role(role, {"SalesAssociate", "ShopManager", "Customer"})
    o = get_order(oid)
    body = get_json_body()
    fabric_id = V.req_str(body, "fabric_id")
    option_code = V.req_enum(body, "option_code", OPTION_CODES)

    # FK existence (priority 4)
    fabric = get_fabric(fabric_id)

    # state: only on DRAFT orders
    if o["status"] != "DRAFT":
        fail(errors.ERR_ORDER_INVALID_STATE, "Option lines can only be added to a DRAFT order")

    # fabric must be AVAILABLE (priority 8)
    if fabric["status"] != "AVAILABLE":
        fail(errors.ERR_FABRIC_DISCONTINUED, "Fabric is discontinued")

    rec = stamp_create()
    rec.update({
        "order_id": oid,
        "fabric_id": fabric_id,
        "option_code": option_code,
        "upcharge_cents": calc.option_upcharge(option_code),
        "fabric_price_per_meter_cents": fabric["price_per_meter_cents"],
    })
    db.option_lines[rec["id"]] = rec

    osvc.recompute_quote(o)
    touch(o)
    return success(S.option_line(rec), status=201)


@bp.get("/orders/<oid>/option-lines")
def list_option_lines(oid):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist", "Customer"})
    get_order(oid)
    limit, offset = V.parse_pagination()
    items = osvc.order_option_lines(oid)
    page = V.paginate(items, limit, offset)
    return list_response([S.option_line(l) for l in page], len(items), limit, offset)


@bp.delete("/orders/<oid>/option-lines/<lid>")
def delete_option_line(oid, lid):
    _, role = get_user_context()
    require_role(role, {"SalesAssociate", "ShopManager", "Customer"})
    o = get_order(oid)
    line = db.option_lines.get(lid)
    if line is None or line["order_id"] != oid:
        # No dedicated option-line not-found code in the catalog; 404 is the
        # correct status family for an unresolvable nested identifier (§2.6).
        from errors import ApiError
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "Option line not found")

    if o["status"] != "DRAFT":
        fail(errors.ERR_ORDER_INVALID_STATE, "Option lines can only be removed from a DRAFT order")

    del db.option_lines[lid]
    osvc.recompute_quote(o)
    touch(o)
    return success(S.garment_order(o))
