from flask import Blueprint, g, request

from auth import auth, check_own
from envelope import created, list_response, success
from errors import err
from services import damage_charge_cents, recompute_standing
from store import db, new_entity, pub, touch
from validate import SEVERITIES, body, get_or_404, opt_int, opt_str, req_enum, req_str

bp = Blueprint("damage", __name__)

ALL_ROLES = ("Customer", "FrontDesk", "Technician", "Manager")


def _owner_of(assessment):
    return db.reservations[assessment["reservation_id"]]["customer_id"]


@bp.post("/shop/damage-assessments")
def create_damage_assessment():
    auth("Technician", "Manager")
    b = body()
    res_id = b.get("reservation_id")
    unit_id = b.get("equipment_item_id")
    if res_id is not None:
        get_or_404(db.reservations, res_id, "Reservation")
    if unit_id is not None:
        get_or_404(db.equipment_items, unit_id, "Equipment item")
    res_id = req_str(b, "reservation_id")
    unit_id = req_str(b, "equipment_item_id")
    res = db.reservations[res_id]
    if res["fulfillment_status"] != "RETURNED":
        raise err("ERR_INVALID_STATE",
                  "Damage can only be assessed while the reservation is "
                  "RETURNED (not yet CLOSED)")
    severity = req_enum(b, "severity", SEVERITIES)
    notes = opt_str(b, "notes")
    unit = db.equipment_items[unit_id]
    was_item = any(
        i["reservation_id"] == res_id and i["equipment_item_id"] == unit_id
        for i in db.reservation_items.values()
    )
    if not was_item:
        raise err("ERR_ITEM_NOT_IN_RESERVATION",
                  "The unit was never an item of the given reservation")
    charge = damage_charge_cents(unit, severity)
    assessment = new_entity({
        "reservation_id": res_id,
        "equipment_item_id": unit_id,
        "severity": severity,
        "notes": notes,
        "charge_cents": charge,
        "deposit_captured_cents": 0,
        "remainder_due_cents": charge,
        "status": "DRAFT",
    })
    db.damage_assessments[assessment["id"]] = assessment
    return created(pub(assessment))


@bp.get("/shop/damage-assessments/<aid>")
def get_damage_assessment(aid):
    auth(*ALL_ROLES)
    assessment = get_or_404(db.damage_assessments, aid, "Damage assessment")
    check_own(_owner_of(assessment))
    return success(pub(assessment))


@bp.get("/shop/damage-assessments")
def list_damage_assessments():
    auth(*ALL_ROLES)
    items = list(db.damage_assessments.values())
    if g.user_role == "Customer":
        items = [a for a in items if _owner_of(a) == g.user_id]
    reservation_id = request.args.get("reservation_id")
    equipment_item_id = request.args.get("equipment_item_id")
    status = request.args.get("status")
    if reservation_id is not None:
        items = [a for a in items if a["reservation_id"] == reservation_id]
    if equipment_item_id is not None:
        items = [a for a in items if a["equipment_item_id"] == equipment_item_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items)


@bp.post("/shop/damage-assessments/<aid>/invoice")
def invoice_damage_assessment(aid):
    auth("FrontDesk", "Manager")
    a = get_or_404(db.damage_assessments, aid, "Damage assessment")
    if a["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT assessment can be invoiced")
    res = db.reservations[a["reservation_id"]]
    if res["fulfillment_status"] != "RETURNED":
        raise err("ERR_INVALID_STATE",
                  "Invoicing requires the reservation still RETURNED")
    # Link 1: capture from the deposit hold
    capture = min(a["charge_cents"],
                  res["deposit_authorized_cents"] - res["deposit_captured_cents"])
    res["deposit_captured_cents"] += capture
    touch(res)
    a["deposit_captured_cents"] = capture
    a["remainder_due_cents"] = a["charge_cents"] - capture
    a["status"] = "INVOICED"
    touch(a)
    # Link 2 + 3: standing recompute; BARRED suspends active leases
    recompute_standing(res["customer_id"])
    # Fan-out: TOTAL_LOSS pulls the unit out of the fleet
    if a["severity"] == "TOTAL_LOSS":
        unit = db.equipment_items[a["equipment_item_id"]]
        if unit["status"] == "AWAITING_INSPECTION":
            unit["status"] = "LOST"
            touch(unit)
    return success(pub(a))


@bp.post("/shop/damage-assessments/<aid>/pay")
def pay_damage_assessment(aid):
    auth("Customer", "FrontDesk", "Manager")
    a = get_or_404(db.damage_assessments, aid, "Damage assessment")
    check_own(_owner_of(a))
    if a["status"] != "INVOICED":
        raise err("ERR_INVALID_STATE", "Only an INVOICED assessment can be paid")
    a["status"] = "PAID"
    touch(a)
    recompute_standing(_owner_of(a))
    return success(pub(a))


@bp.post("/shop/damage-assessments/<aid>/dispute")
def dispute_damage_assessment(aid):
    auth("Customer", "Manager")
    a = get_or_404(db.damage_assessments, aid, "Damage assessment")
    check_own(_owner_of(a))
    if a["status"] != "INVOICED":
        raise err("ERR_INVALID_STATE",
                  "Only an INVOICED assessment can be disputed")
    a["status"] = "DISPUTED"
    touch(a)
    return success(pub(a))


@bp.post("/shop/damage-assessments/<aid>/resolve")
def resolve_damage_assessment(aid):
    auth("Manager")
    a = get_or_404(db.damage_assessments, aid, "Damage assessment")
    if a["status"] != "DISPUTED":
        raise err("ERR_INVALID_STATE", "Only a DISPUTED assessment can be resolved")
    b = body()
    resolution = req_enum(b, "resolution", ("UPHELD", "WAIVED"))
    res = db.reservations[a["reservation_id"]]
    if resolution == "UPHELD":
        adjusted = opt_int(b, "adjusted_charge_cents", minimum=0)
        if adjusted is not None:
            # compensation: recompute this assessment's capture against the
            # hold net of what it previously captured
            res["deposit_captured_cents"] -= a["deposit_captured_cents"]
            a["charge_cents"] = adjusted
            new_capture = min(
                adjusted,
                res["deposit_authorized_cents"] - res["deposit_captured_cents"])
            res["deposit_captured_cents"] += new_capture
            touch(res)
            a["deposit_captured_cents"] = new_capture
            a["remainder_due_cents"] = adjusted - new_capture
        a["status"] = "INVOICED"
    else:  # WAIVED
        res["deposit_captured_cents"] -= a["deposit_captured_cents"]
        touch(res)
        a["remainder_due_cents"] = 0
        a["status"] = "WAIVED"
    touch(a)
    recompute_standing(res["customer_id"])
    return success(pub(a))
