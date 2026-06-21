"""WorkOrder state machine transitions and their side effects (PRD 3.3-3.7).

Each transition function assumes existence/role/ownership/field validation has
already passed. They enforce state preconditions (ERR_INVALID_STATE) and the
business-rule validations in their declared priority order, then apply side
effects. Version bumps and cascades follow scaffold 1.2.
"""
import db
import errors
from errors import ApiError
from services import calculations as C
from services import helpers as H


def accept_assessment(work_order, assessment):
    """OPEN -> ASSESSED. Freeze service_decision and quote price (PRD 3.3)."""
    if work_order["status"] != "OPEN":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Work order is not OPEN.")
    if assessment["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Assessment is not in DRAFT.")

    decision = assessment["recommendation"]
    # Supersede any other already-ACCEPTED assessment on this work order.
    for a in db.damage_assessments.values():
        if a["work_order_id"] == work_order["id"] and a["status"] == "ACCEPTED" and a["id"] != assessment["id"]:
            a["status"] = "SUPERSEDED"
            db.touch(a)
    assessment["status"] = "ACCEPTED"
    db.touch(assessment)

    vehicle = db.vehicles[work_order["vehicle_id"]]
    work_order["service_decision"] = decision
    work_order["assessment_version"] += 1
    work_order["total_charge_cents"] = C.price_quote(decision, vehicle["adas_equipped"])
    work_order["status"] = "ASSESSED"
    db.touch(work_order)
    return work_order


def schedule(work_order, appointment):
    """ASSESSED -> SCHEDULED. Link appointment, apply trip fee (PRD 3.4)."""
    if work_order["status"] != "ASSESSED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Work order is not ASSESSED.")

    decision = work_order["service_decision"]
    vehicle = db.vehicles[work_order["vehicle_id"]]
    recal_required = (decision == "REPLACE" and vehicle["adas_equipped"])

    # Priority-ordered business rules (PRD 2.8 + validations 8 then 14).
    # ERR_MOBILE_NOT_ELIGIBLE (priority 8) before ERR_PART_NOT_READY (priority 14).
    if recal_required and appointment["service_location"] == "MOBILE":
        raise ApiError(errors.ERR_MOBILE_NOT_ELIGIBLE, 422,
                       "ADAS REPLACE cannot be scheduled mobile.")
    if decision == "REPLACE":
        reserved = H.reserved_part_order_for(work_order["id"])
        if reserved is None:
            raise ApiError(errors.ERR_PART_NOT_READY, 409,
                           "No RESERVED part order for this REPLACE work order.")

    work_order["service_location"] = appointment["service_location"]
    work_order["recalibration_required"] = recal_required

    customer = db.customers[work_order["customer_id"]]
    trip_fee = C.schedule_trip_fee(
        work_order["total_charge_cents"],
        appointment["service_location"],
        customer["service_address_state"],
    )
    work_order["total_charge_cents"] += trip_fee
    work_order["status"] = "SCHEDULED"
    db.touch(work_order)
    return work_order


def start_service(work_order, appointment):
    """SCHEDULED -> IN_SERVICE (PRD 3.5)."""
    if work_order["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Work order is not SCHEDULED.")
    if appointment is None or appointment["status"] != "CHECKED_IN":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Linked appointment is not CHECKED_IN.")
    work_order["status"] = "IN_SERVICE"
    db.touch(work_order)
    return work_order


def finish_install(work_order, temp_c, humidity_pct):
    """IN_SERVICE -> CURING or AWAITING_RECALIBRATION (REPLACE only) (PRD 3.5)."""
    if work_order["status"] != "IN_SERVICE":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Work order is not IN_SERVICE.")
    if work_order["service_decision"] != "REPLACE":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "finish-install is only for REPLACE jobs.")

    now = db.current_utc()
    sdat = C.safe_drive_away_at(now, temp_c, humidity_pct)
    from validation import to_iso
    work_order["safe_drive_away_at"] = to_iso(sdat)

    # Consume the reserved part order, decrement reserved_qty.
    reserved = H.reserved_part_order_for(work_order["id"])
    if reserved is not None:
        part = db.glass_parts[reserved["glass_part_id"]]
        part["reserved_qty"] -= reserved["quantity"]
        db.touch(part)
        reserved["status"] = "CONSUMED"
        db.touch(reserved)

    if work_order["recalibration_required"]:
        work_order["status"] = "AWAITING_RECALIBRATION"
    else:
        work_order["status"] = "CURING"
    db.touch(work_order)
    return work_order


def complete(work_order):
    """CURING -> COMPLETED (REPLACE) or IN_SERVICE -> COMPLETED (REPAIR) (PRD 3.7).

    Validation order: state, then cure-elapsed (422), then balance (402).
    """
    status = work_order["status"]
    decision = work_order["service_decision"]

    if status == "CURING":
        # REPLACE completion path.
        now = db.current_utc()
        from validation import parse_iso
        sdat_raw = work_order["safe_drive_away_at"]
        sdat = parse_iso(sdat_raw)
        if now < sdat:
            raise ApiError(errors.ERR_CURE_NOT_ELAPSED, 422, "Cure interval has not elapsed.")
        if work_order["amount_paid_cents"] < work_order["total_charge_cents"]:
            raise ApiError(errors.ERR_BALANCE_UNPAID, 402, "Work order is not fully paid.")
    elif status == "IN_SERVICE" and decision == "REPAIR":
        # REPAIR completion path (direct, no cure).
        if work_order["amount_paid_cents"] < work_order["total_charge_cents"]:
            raise ApiError(errors.ERR_BALANCE_UNPAID, 402, "Work order is not fully paid.")
    else:
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Work order cannot be completed from its current state.")

    # Issue warranty.
    coverage = "CHIP_REPAIR" if decision == "REPAIR" else "LIFETIME_LEAK"
    now_iso_str = db_now_iso()
    warranty = db.stamp_new({
        "work_order_id": work_order["id"],
        "coverage_type": coverage,
        "issued_at": now_iso_str,
        "status": "ACTIVE",
    })
    db.warranties[warranty["id"]] = warranty

    # Release the linked CHECKED_IN appointment.
    appt = _checked_in_appointment_for(work_order["id"])
    if appt is not None:
        appt["status"] = "RELEASED"
        db.touch(appt)

    work_order["status"] = "COMPLETED"
    db.touch(work_order)
    return work_order


def cancel(work_order):
    """OPEN/ASSESSED/SCHEDULED -> CANCELLED with satellite cascade (PRD 3.7)."""
    if work_order["status"] not in {"OPEN", "ASSESSED", "SCHEDULED"}:
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Work order can only be cancelled from OPEN, ASSESSED, or SCHEDULED.")
    wid = work_order["id"]
    # Cascade: BOOKED appointments -> CANCELLED.
    for appt in db.service_appointments.values():
        if appt["work_order_id"] == wid and appt["status"] == "BOOKED":
            appt["status"] = "CANCELLED"
            db.touch(appt)
    # Cascade: RESERVED part orders -> CANCELLED, release stock.
    for po in db.part_orders.values():
        if po["work_order_id"] == wid and po["status"] == "RESERVED":
            part = db.glass_parts[po["glass_part_id"]]
            part["on_hand_qty"] += po["quantity"]
            part["reserved_qty"] -= po["quantity"]
            db.touch(part)
            po["status"] = "CANCELLED"
            db.touch(po)
    work_order["status"] = "CANCELLED"
    db.touch(work_order)
    return work_order


# --- helpers ---
def db_now_iso():
    from validation import to_iso
    return to_iso(db.current_utc())


def _checked_in_appointment_for(work_order_id):
    for appt in db.service_appointments.values():
        if appt["work_order_id"] == work_order_id and appt["status"] == "CHECKED_IN":
            return appt
    return None


def linked_appointment_for(work_order_id):
    """The most relevant non-cancelled appointment for start-service checks.

    A work order is started once its appointment is CHECKED_IN; return a
    CHECKED_IN one if present, otherwise any non-cancelled one.
    """
    checked = _checked_in_appointment_for(work_order_id)
    if checked is not None:
        return checked
    for appt in db.service_appointments.values():
        if appt["work_order_id"] == work_order_id and appt["status"] not in {"CANCELLED", "RELEASED"}:
            return appt
    return None
