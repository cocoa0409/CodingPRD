"""Device orders, devices and inventory pools."""

from flask import Blueprint

import calc
import services as svc
from auth import (ADMIN, CARE_OPS, COMPLIANCE, FIRMWARE_ENG, PATIENT, REIMBURSEMENT,
                  REPAIR_TECH, authorize, require_owner)
from bodyspec import Body
from common import field, listed, patient_of_device
from errors import ApiError
from resp import created, ok
from store import bump, db, days, now, table_rows

bp = Blueprint("order", __name__)

MODELS = ("NEO", "LINK", "FLEX")
DOMES = ("S", "M", "L", "XL")
TIPS = ("OPEN", "CLOSED", "POWER")


# --------------------------------------------------------------- DeviceOrder
@bp.post("/patients/<patient_id>/device-orders")
def create_order(patient_id):
    actor = authorize(PATIENT, CARE_OPS)
    patient = svc.find(db.patients, patient_id)
    require_owner(actor, patient["id"])
    policy = svc.policy_of(patient)
    if policy is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    if policy.get("is_retired"):
        raise ApiError("ERR_STATE_POLICY_RETIRED")
    body = Body()
    model = body.enum("model", MODELS)
    dome = body.enum("dome_size", DOMES)
    tip = body.enum("tip_type", TIPS)
    list_price = body.integer("list_price_cents", minimum=1)
    discount = body.integer("discount_cents", required=False, default=0, minimum=0)
    accessories = body.integer("accessory_subtotal_cents", required=False, default=0, minimum=0)
    shipping = body.integer("shipping_cents", required=False, default=1495, minimum=0)
    body.finish()
    if discount > list_price:
        raise ApiError("ERR_VALIDATION", "discount_cents may not exceed list_price_cents")
    if not policy.get("otc_sales_permitted"):
        raise ApiError("ERR_OTC_SALES_PROHIBITED_IN_STATE")
    if int(patient["age_years"]) < int(policy.get("min_age_years") or 0):
        raise ApiError("ERR_AGE_BELOW_STATE_MINIMUM")
    if patient["status"] == "MEDICALLY_DISQUALIFIED":
        raise ApiError("ERR_PATIENT_MEDICALLY_DISQUALIFIED")
    order = svc.new_row(
        db.device_orders, patient_id=patient["id"], state_policy_id=policy["id"],
        pinned_state_policy_version=int(policy["version"]),
        pinned_trial_days=int(policy["trial_period_days"]),
        pinned_restocking_mode=policy["restocking_fee_mode"],
        payment_status="PENDING_AUTH", fulfillment_status="PENDING_FIT_CONFIRM",
        model=model, dome_size=dome, tip_type=tip, list_price_cents=list_price,
        discount_cents=discount, accessory_subtotal_cents=accessories,
        shipping_cents=shipping, tax_cents=0, total_cents=0, captured_cents=0,
        refunded_cents=0, retained_cents=0, open_balance_cents=0, delivered_at=None,
        medical_hold_reason=None, _pinned_policy=dict(policy), _reserved_pool_id=None,
    )
    calc.order_total_composition(order)
    return created(order)


@bp.get("/device-orders")
def list_orders():
    actor = authorize(PATIENT, CARE_OPS, REIMBURSEMENT, COMPLIANCE, ADMIN)
    return listed(table_rows(db.device_orders),
                  {"patient_id": field("patient_id"),
                   "state_policy_id": field("state_policy_id"),
                   "payment_status": field("payment_status"),
                   "fulfillment_status": field("fulfillment_status")},
                  actor=actor)


@bp.get("/device-orders/<order_id>")
def get_order(order_id):
    actor = authorize(PATIENT, CARE_OPS, REIMBURSEMENT, COMPLIANCE, ADMIN)
    order = svc.find(db.device_orders, order_id)
    require_owner(actor, order["patient_id"])
    return ok(order)


@bp.get("/device-orders/<order_id>/summary")
def order_summary(order_id):
    actor = authorize(PATIENT, CARE_OPS, COMPLIANCE, ADMIN)
    order = svc.find(db.device_orders, order_id)
    require_owner(actor, order["patient_id"])
    svc.recompute_order_cash(order)
    return ok(order)


@bp.post("/device-orders/<order_id>/confirm-fit")
def confirm_fit(order_id):
    authorize(CARE_OPS)
    order = svc.find(db.device_orders, order_id)
    pool = svc.pool_for(order["model"], order["dome_size"], order["tip_type"])
    if pool is None:
        raise ApiError("ERR_INVENTORY_POOL_NOT_FOUND")
    svc.ensure_state(order, "fulfillment_status", ("PENDING_FIT_CONFIRM",), "device_orders")
    patient = svc.order_patient(order)
    policy = svc.pinned_policy(order)
    if int(patient["age_years"]) < int(policy.get("min_age_years") or 0):
        raise ApiError("ERR_AGE_BELOW_STATE_MINIMUM")
    if patient["status"] == "MEDICALLY_DISQUALIFIED":
        raise ApiError("ERR_PATIENT_MEDICALLY_DISQUALIFIED")
    if int(patient.get("open_mandatory_flag_count") or 0) > 0:
        raise ApiError("ERR_MANDATORY_REFERRAL_OPEN")
    if policy.get("waiver_required") and patient.get("waiver_acknowledged_at") is None:
        raise ApiError("ERR_WAIVER_NOT_ACKNOWLEDGED")
    if patient["status"] not in ("CANDIDATE_APPROVED", "PROVIDER_CLEARED"):
        raise ApiError("ERR_INVALID_STATE")
    if order["payment_status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE")
    if pool.get("is_discontinued"):
        raise ApiError("ERR_POOL_DISCONTINUED")
    if int(pool["on_hand_units"]) < 1:
        raise ApiError("ERR_INVENTORY_POOL_DEPLETED")
    pool["on_hand_units"] = int(pool["on_hand_units"]) - 1
    pool["reserved_units"] = int(pool["reserved_units"]) + 1
    bump(pool)
    order["_reserved_pool_id"] = pool["id"]
    for device in table_rows(db.devices):
        if device.get("status") == "IN_STOCK" and device.get("model") == order["model"]:
            device["status"] = "ASSIGNED"
            device["device_order_id"] = order["id"]
            bump(device)
            break
    order["fulfillment_status"] = "READY_TO_SHIP"
    bump(order)
    return ok(order)


@bp.post("/device-orders/<order_id>/ship")
def ship_order(order_id):
    authorize(CARE_OPS)
    order = svc.find(db.device_orders, order_id)
    svc.ensure_state(order, "fulfillment_status", ("READY_TO_SHIP",), "device_orders")
    patient = svc.order_patient(order)
    if patient is not None and int(patient.get("open_mandatory_flag_count") or 0) > 0:
        raise ApiError("ERR_MANDATORY_REFERRAL_OPEN")
    if order["payment_status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE")
    device = svc.device_for_order(order["id"])
    if device is None or device.get("status") != "ASSIGNED":
        raise ApiError("ERR_DEPENDENT_STATE_NOT_READY")
    order["payment_status"] = "CAPTURED"
    order["captured_cents"] = int(order["total_cents"])
    order["refunded_cents"] = 0
    order["retained_cents"] = 0
    order["fulfillment_status"] = "SHIPPED"
    svc.recompute_order_cash(order)
    bump(order)
    device["shipped_at"] = now()
    device["warranty_expires_at"] = now() + days(calc.WARRANTY_DAYS)
    bump(device)
    pool = db.inventory_pools.get(order.get("_reserved_pool_id"))
    if pool is not None:
        pool["reserved_units"] = max(0, int(pool["reserved_units"]) - 1)
        pool["dispatched_units"] = int(pool["dispatched_units"]) + 1
        bump(pool)
        order["_dispatched_pool_id"] = pool["id"]
        order["_reserved_pool_id"] = None
    return ok(order)


@bp.post("/device-orders/<order_id>/cancel")
def cancel_order(order_id):
    authorize(CARE_OPS)
    order = svc.find(db.device_orders, order_id)
    Body().string("reason_note", required=False, min_len=1)
    svc.ensure_state(order, "fulfillment_status",
                     ("PENDING_FIT_CONFIRM", "READY_TO_SHIP", "MEDICAL_HOLD"), "device_orders")
    if order["payment_status"] not in ("PENDING_AUTH", "AUTHORIZED", "CAPTURED"):
        raise ApiError("ERR_INVALID_STATE")
    if order["fulfillment_status"] == "READY_TO_SHIP":
        svc.release_reservation(order)
        svc.unassign_device(order)
    svc.cancel_order_regulatory(order)
    return ok(order)


# -------------------------------------------------------------------- Device
@bp.post("/devices")
def create_device():
    authorize(ADMIN)
    body = Body()
    serial = body.string("serial_number", min_len=1)
    model = body.enum("model", MODELS)
    firmware = body.string("firmware_version", required=False, default="4.0.0", min_len=1)
    body.finish()
    for row in db.devices.values():
        if row["serial_number"] == serial:
            raise ApiError("ERR_DUPLICATE_KEY")
    device = svc.new_row(db.devices, serial_number=serial, device_order_id=None, model=model,
                         firmware_version=firmware, status="IN_STOCK", shipped_at=None,
                         warranty_expires_at=None, age_months_at_last_claim=0,
                         loss_damage_claims_approved=0, replaced_by_device_id=None)
    return created(device)


@bp.get("/devices")
def list_devices():
    actor = authorize(CARE_OPS, REPAIR_TECH, FIRMWARE_ENG, ADMIN, PATIENT)
    rows = table_rows(db.devices)
    if actor.is_patient:
        rows = [d for d in rows if patient_of_device(d["id"]) == actor.user_id]
    return listed(rows,
                  {"device_order_id": field("device_order_id"),
                   "replaced_by_device_id": field("replaced_by_device_id"),
                   "status": field("status"), "model": field("model"),
                   "firmware_version": field("firmware_version")},
                  owner_field=None)


@bp.get("/devices/<device_id>")
def get_device(device_id):
    actor = authorize(PATIENT, CARE_OPS, REPAIR_TECH, FIRMWARE_ENG, COMPLIANCE, ADMIN)
    device = svc.find(db.devices, device_id)
    if actor.is_patient:
        require_owner(actor, patient_of_device(device["id"]))
    return ok(device)


# ------------------------------------------------------------- InventoryPool
@bp.post("/inventory-pools")
def create_pool():
    authorize(ADMIN)
    body = Body()
    sku = body.string("sku", min_len=1)
    model = body.enum("model", MODELS)
    dome = body.enum("dome_size", DOMES)
    tip = body.enum("tip_type", TIPS)
    body.finish()
    for row in db.inventory_pools.values():
        if row["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_KEY")
    pool = svc.new_row(db.inventory_pools, sku=sku, model=model, dome_size=dome, tip_type=tip,
                       on_hand_units=0, reserved_units=0, dispatched_units=0,
                       total_units_received=0, is_discontinued=False)
    return created(pool)


@bp.get("/inventory-pools")
def list_pools():
    authorize(CARE_OPS, ADMIN, PATIENT)
    return listed(table_rows(db.inventory_pools),
                  {"model": field("model"), "dome_size": field("dome_size"),
                   "tip_type": field("tip_type"), "is_discontinued": field("is_discontinued")},
                  owner_field=None)


@bp.post("/inventory-pools/<pool_id>/restock")
def restock_pool(pool_id):
    authorize(ADMIN)
    pool = svc.find(db.inventory_pools, pool_id)
    body = Body()
    units = body.integer("units", minimum=1)
    body.finish()
    pool["on_hand_units"] = int(pool["on_hand_units"]) + units
    pool["total_units_received"] = int(pool["total_units_received"]) + units
    bump(pool)
    return ok(pool)


@bp.delete("/inventory-pools/<pool_id>")
def discontinue_pool(pool_id):
    authorize(ADMIN)
    pool = svc.find(db.inventory_pools, pool_id)
    pool["is_discontinued"] = True
    bump(pool)
    return ok(pool)
