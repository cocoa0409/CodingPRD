"""Appointments: kit, dispatch, recall, arrive, collect specimens, complete-draw
(PRD 3.5, 3.6)."""
from flask import Blueprint, request, g

import common
import errors
import serializers
from clock import clock, to_iso_z
from db import db, stamp_common, touch
from middleware import require_roles
from services import custody, cascade

bp = Blueprint("appointments", __name__)


@bp.get("/appointments/<rid>")
@require_roles("OrderingProvider", "Dispatcher", "Phlebotomist", "LabOps")
def get_appointment(rid):
    rec = common.find_appointment(rid)
    return common.object_response(serializers.appointment(rec))


# ---------------------------------------------------------------------------
# Kit (PRD 3.5)
# ---------------------------------------------------------------------------
@bp.post("/appointments/<appt_id>/kit")
@require_roles("Dispatcher")
def assign_kit(appt_id):
    appt = common.find_appointment(appt_id)
    body = common.get_body()
    kit_lot_number = common.require_str(body, "kit_lot_number")
    tube_count = common.require_int_min(body, "tube_count", 1)

    rec = {
        "appointment_id": appt["id"],
        "kit_lot_number": kit_lot_number,
        "tube_count": tube_count,
        "status": "ASSIGNED",
    }
    stamp_common(rec)
    db.draw_kits[rec["id"]] = rec
    return common.object_response_201(serializers.draw_kit(rec))


@bp.get("/appointments/<appt_id>/kit")
@require_roles("Dispatcher", "Phlebotomist", "LabOps")
def list_kits(appt_id):
    common.find_appointment(appt_id)
    items = [k for k in db.draw_kits.values() if k["appointment_id"] == appt_id]
    items = common.sort_by_created(items)
    # No pagination params declared for this endpoint, but envelope still needs them.
    limit, offset = common.get_pagination()
    page, total = common.paginate(items, limit, offset)
    return common.array_response([serializers.draw_kit(k) for k in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Dispatch (PRD 3.5)
# ---------------------------------------------------------------------------
@bp.post("/appointments/<appt_id>/dispatch")
@require_roles("Dispatcher")
def dispatch(appt_id):
    appt = common.find_appointment(appt_id)

    # Priority 7: state legality.
    if appt["status"] != "SCHEDULED":
        errors.fail(errors.ERR_APPOINTMENT_NOT_DISPATCHABLE, "Appointment is not SCHEDULED.")

    # Priority 9: assigned phlebotomist eligibility.
    phleb = db.phlebotomists.get(appt["phlebotomist_id"])
    if phleb is None or not phleb["certification_active"] or phleb["status"] != "AVAILABLE":
        errors.fail(errors.ERR_PHLEBOTOMIST_UNAVAILABLE, "Assigned phlebotomist is unavailable.")

    # Kit guard: a kit with tube_count >= order.specimens_required_count must be assigned.
    order = db.lab_orders.get(appt["lab_order_id"])
    required = order["specimens_required_count"]
    has_kit = any(
        k["appointment_id"] == appt["id"] and k["tube_count"] >= required
        for k in db.draw_kits.values()
    )
    if not has_kit:
        errors.fail(errors.ERR_KIT_NOT_ASSIGNED,
                    "No assigned kit covers specimens_required_count.")

    appt["status"] = "DISPATCHED"
    touch(appt)
    return common.object_response(serializers.appointment(appt))


# ---------------------------------------------------------------------------
# Recall (PRD 3.5) — DISPATCHED -> SCHEDULED
# ---------------------------------------------------------------------------
@bp.post("/appointments/<appt_id>/recall")
@require_roles("Dispatcher")
def recall(appt_id):
    appt = common.find_appointment(appt_id)
    if appt["status"] != "DISPATCHED":
        errors.fail(errors.ERR_APPOINTMENT_NOT_RECALLABLE, "Appointment is not DISPATCHED.")
    appt["status"] = "SCHEDULED"
    touch(appt)
    return common.object_response(serializers.appointment(appt))


# ---------------------------------------------------------------------------
# Arrive (PRD 3.6) — DISPATCHED -> ARRIVED, gated by phlebotomist identity
# ---------------------------------------------------------------------------
@bp.post("/appointments/<appt_id>/arrive")
@require_roles("Phlebotomist")
def arrive(appt_id):
    appt = common.find_appointment(appt_id)
    if appt["status"] != "DISPATCHED":
        errors.fail(errors.ERR_APPOINTMENT_NOT_ARRIVABLE, "Appointment is not DISPATCHED.")
    # X-User-ID must equal the appointment's assigned phlebotomist_id.
    if g.user_id != appt["phlebotomist_id"]:
        errors.fail(errors.ERR_NOT_ASSIGNED_PHLEBOTOMIST,
                    "Acting phlebotomist is not the appointment's assigned phlebotomist.")
    appt["status"] = "ARRIVED"
    touch(appt)
    return common.object_response(serializers.appointment(appt))


# ---------------------------------------------------------------------------
# Collect a specimen tube (PRD 3.6, 3.7)
# ---------------------------------------------------------------------------
@bp.post("/appointments/<appt_id>/specimens")
@require_roles("Phlebotomist")
def collect_specimen(appt_id):
    appt = common.find_appointment(appt_id)
    body = common.get_body()
    tube_label = common.require_str(body, "tube_label")

    order = db.lab_orders.get(appt["lab_order_id"])

    # ERR_DUPLICATE_TUBE_LABEL: label unique within the lab order.
    for s in db.specimens.values():
        if s["lab_order_id"] == order["id"] and s["tube_label"] == tube_label:
            errors.fail(errors.ERR_DUPLICATE_TUBE_LABEL, "tube_label already used within this order.")

    rec = {
        "lab_order_id": order["id"],
        "appointment_id": appt["id"],
        "tube_label": tube_label,
        "collected_at_utc": to_iso_z(clock.now()),
        "courier_manifest_id": None,
        "status": "COLLECTED",
    }
    stamp_common(rec)
    db.specimens[rec["id"]] = rec

    # First custody event: COLLECTED, sequence_index 0.
    custody.append_event(rec["id"], "COLLECTED", g.role, g.user_id)

    return common.object_response_201(serializers.specimen(rec))


@bp.get("/appointments/<appt_id>/specimens")
@require_roles("Dispatcher", "Phlebotomist", "LabOps")
def list_appointment_specimens(appt_id):
    common.find_appointment(appt_id)
    limit, offset = common.get_pagination()
    items = [s for s in db.specimens.values() if s["appointment_id"] == appt_id]
    items = common.sort_by_created(items)
    page, total = common.paginate(items, limit, offset)
    return common.array_response([serializers.specimen(s) for s in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Complete draw (PRD 3.6) — ARRIVED -> DRAW_COMPLETED
# ---------------------------------------------------------------------------
@bp.post("/appointments/<appt_id>/complete-draw")
@require_roles("Phlebotomist")
def complete_draw(appt_id):
    appt = common.find_appointment(appt_id)
    if appt["status"] != "ARRIVED":
        errors.fail(errors.ERR_APPOINTMENT_NOT_ARRIVED, "Appointment is not ARRIVED.")

    order = db.lab_orders.get(appt["lab_order_id"])
    required = order["specimens_required_count"]
    collected = [s for s in db.specimens.values()
                 if s["lab_order_id"] == order["id"] and s["status"] == "COLLECTED"]
    if len(collected) != required:
        errors.fail(errors.ERR_SPECIMEN_COUNT_MISMATCH,
                    "Collected specimen count does not equal specimens_required_count.")

    appt["status"] = "DRAW_COMPLETED"
    touch(appt)

    # Mark the appointment's draw kit(s) CONSUMED.
    for k in db.draw_kits.values():
        if k["appointment_id"] == appt["id"] and k["status"] == "ASSIGNED":
            k["status"] = "CONSUMED"
            touch(k)

    order["status"] = "DRAW_COMPLETED"
    touch(order)

    return common.object_response(serializers.appointment(appt))
