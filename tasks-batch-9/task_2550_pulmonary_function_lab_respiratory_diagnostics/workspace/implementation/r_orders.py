"""Test orders, indication gates and pre-test medication holds."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import services as svc
from auth import (authenticate, ALL_ROLES, LAB_MANAGER, TECHNOLOGIST,
                  ORDERING_PHYSICIAN)
from errors import ApiError
from responses import object_response, paginate
from store import db, iso, parse_iso, stamp_new, touch
import validation as v

bp = Blueprint("orders", __name__)

ORDER_TERMINAL = ("COMPLETED", "CANCELLED")
HOLD_STATUSES = ["PENDING", "ATTESTED", "VIOLATED", "SUPERSEDED"]


def _require_owner(actor, order):
    """Only the physician recorded in ordering_staff_id may submit, revise or
    cancel; a LabManager acts on the shared cancellation surface."""
    if actor.role != ORDERING_PHYSICIAN:
        return
    if order.get("ordering_staff_id") != actor.staff_id:
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "Only the ordering physician who owns this order may "
                       "perform this operation.")


# ---------------------------------------------------------------- test orders

@bp.route("/test-orders", methods=["POST"])
def create_order():
    actor = authenticate([ORDERING_PHYSICIAN])
    body = v.get_body()
    patient = None
    if body.get("patient_id") is not None:
        patient = svc.get_patient(body.get("patient_id"))
    if patient is None:
        v.v_str(body, "patient_id")
    indication = v.v_enum(body, "indication_code", calc.INDICATION_CODES)
    modalities = v.v_enum_array(body, "requested_modalities", calc.MODALITIES)
    test_context = v.v_enum(body, "test_context", calc.TEST_CONTEXTS)
    bronchodilator = v.v_bool(body, "bronchodilator_requested",
                              required=False, default=False)
    challenge_type = v.v_enum(body, "challenge_type", calc.CHALLENGE_TYPES,
                              required=False) or "NONE"
    medications = v.v_optional_enum_array(body, "current_medication_classes",
                                          calc.MEDICATION_CLASSES, default=[])
    record = {
        "patient_id": patient["id"],
        "ordering_staff_id": actor.staff_id,
        "indication_code": indication,
        "requested_modalities": modalities,
        "test_context": test_context,
        "bronchodilator_requested": bool(bronchodilator),
        "challenge_type": challenge_type,
        "current_medication_classes": medications,
        "status": "DRAFT",
        "rejection_reason": None,
        "hold_release_at": None,
        "abort_count": 0,
        "cancellation_reason": None,
    }
    stamp_new(record)
    db.orders[record["id"]] = record
    return object_response(svc.ser_order(record), 201)


@bp.route("/test-orders/<order_id>", methods=["GET"])
def read_order(order_id):
    authenticate(ALL_ROLES)
    return object_response(svc.ser_order(svc.get_order(order_id)))


@bp.route("/test-orders", methods=["GET"])
def list_orders():
    authenticate(ALL_ROLES)
    patient_id = request.args.get("patient_id")
    ordering_staff_id = request.args.get("ordering_staff_id")
    status = request.args.get("status")
    records = []
    for order in db.orders.values():
        if patient_id is not None and order["patient_id"] != patient_id:
            continue
        if ordering_staff_id is not None and \
                order["ordering_staff_id"] != ordering_staff_id:
            continue
        if status is not None and order["status"] != status:
            continue
        records.append(order)
    return paginate(records, svc.ser_order)


@bp.route("/test-orders/<order_id>", methods=["PATCH"])
def revise_order(order_id):
    actor = authenticate([ORDERING_PHYSICIAN])
    order = svc.get_order(order_id)
    _require_owner(actor, order)
    body = v.get_body()
    indication = v.v_enum(body, "indication_code", calc.INDICATION_CODES,
                          required=False)
    modalities = v.v_enum_array(body, "requested_modalities", calc.MODALITIES,
                                required=False)
    bronchodilator = v.v_bool(body, "bronchodilator_requested",
                              required=False, default=None)
    challenge_type = v.v_enum(body, "challenge_type", calc.CHALLENGE_TYPES,
                              required=False)
    if order["status"] not in ("DRAFT", "INDICATION_REJECTED"):
        raise ApiError("ERR_ORDER_STATE_INVALID",
                       "Only a DRAFT or INDICATION_REJECTED order may be "
                       "revised.")
    if indication is not None:
        order["indication_code"] = indication
    if modalities is not None:
        order["requested_modalities"] = modalities
    if bronchodilator is not None:
        order["bronchodilator_requested"] = bool(bronchodilator)
    if challenge_type is not None:
        order["challenge_type"] = challenge_type
    order["status"] = "DRAFT"
    order["rejection_reason"] = None
    touch(order)
    return object_response(svc.ser_order(order), 200)


@bp.route("/test-orders/<order_id>/submit", methods=["POST"])
def submit_order(order_id):
    actor = authenticate([ORDERING_PHYSICIAN])
    order = svc.get_order(order_id)
    _require_owner(actor, order)
    v.get_body()
    if order["status"] not in ("DRAFT", "INDICATION_REJECTED"):
        raise ApiError("ERR_ORDER_STATE_INVALID",
                       "Only a DRAFT or INDICATION_REJECTED order may be "
                       "submitted.")
    admitted = calc.CONTEXT_INDICATIONS[order["test_context"]]
    if order["indication_code"] not in admitted:
        raise ApiError("ERR_INDICATION_CONTEXT_MISMATCH",
                       "indication_code %s is not admissible for test_context "
                       "%s." % (order["indication_code"],
                                order["test_context"]))
    approved = calc.APPROVED_INDICATION_MODALITIES[order["indication_code"]]
    unapproved = [m for m in order["requested_modalities"]
                  if m not in approved]
    challenge_ok = (order["challenge_type"] == "NONE"
                    or order["indication_code"] == "ASTHMA_DIAGNOSIS")
    if unapproved or not challenge_ok:
        order["status"] = "INDICATION_REJECTED"
        order["rejection_reason"] = ("MODALITY_NOT_APPROVED_FOR_INDICATION"
                                     if unapproved
                                     else "CHALLENGE_INDICATION_MISMATCH")
        touch(order)
        return object_response(svc.ser_order(order), 200)
    order["rejection_reason"] = None
    if order["current_medication_classes"]:
        order["status"] = "SUBMITTED"
    else:
        order["status"] = "READY"
        order["hold_release_at"] = None
    touch(order)
    return object_response(svc.ser_order(order), 200)


@bp.route("/test-orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    actor = authenticate([ORDERING_PHYSICIAN, LAB_MANAGER])
    order = svc.get_order(order_id)
    _require_owner(actor, order)
    body = v.get_body()
    reason = v.v_str(body, "cancellation_reason")
    if order["status"] in ORDER_TERMINAL:
        raise ApiError("ERR_ORDER_STATE_INVALID",
                       "A COMPLETED or CANCELLED order may not be cancelled.")
    order["status"] = "CANCELLED"
    order["cancellation_reason"] = reason
    order["hold_release_at"] = None
    touch(order)
    for hold in svc.by_created(svc.order_holds(order["id"])):
        if hold["status"] == "PENDING":
            hold["status"] = "SUPERSEDED"
            touch(hold)
    live = [s for s in db.sessions.values()
            if s["order_id"] == order["id"]
            and s["session_status"] in ("SCHEDULED", "IN_PROGRESS")]
    for session in svc.by_created(live):
        svc.abort_session(session, "ORDER_CANCELLED")
    return object_response(svc.ser_order(order), 200)


# ----------------------------------------------------------- medication holds

@bp.route("/test-orders/<order_id>/medication-holds", methods=["POST"])
def issue_hold(order_id):
    authenticate([TECHNOLOGIST])
    order = svc.get_order(order_id)
    body = v.get_body()
    medication_class = v.v_enum(body, "medication_class",
                                calc.MEDICATION_CLASSES)
    expected_version = v.v_int(body, "expected_order_version")
    if medication_class not in (order.get("current_medication_classes") or []):
        raise v.bad("medication_class %s is not among the order's "
                    "current_medication_classes." % medication_class)
    if expected_version != int(order["version"]):
        raise ApiError("ERR_STALE_ORDER_VERSION",
                       "The order has moved on since it was read.")
    if order["status"] not in ("SUBMITTED", "MED_HOLD_ISSUED", "READY"):
        raise ApiError("ERR_ORDER_STATE_INVALID",
                       "A medication hold may only be issued on a SUBMITTED, "
                       "MED_HOLD_ISSUED or READY order.")
    hours = calc.HOLD_HOURS_BY_CLASS[medication_class]
    instructed_at = db.clock
    record = {
        "order_id": order["id"],
        "medication_class": medication_class,
        "required_hold_hours": hours,
        "instructed_at": iso(instructed_at),
        "release_at": iso(instructed_at + timedelta(hours=hours)),
        "attestation_result": None,
        "attested_at": None,
        "status": "PENDING",
    }
    stamp_new(record)
    for hold in svc.by_created(svc.order_holds(order["id"])):
        if hold["medication_class"] == medication_class and \
                hold["status"] in ("PENDING", "VIOLATED"):
            hold["status"] = "SUPERSEDED"
            touch(hold)
    db.holds[record["id"]] = record
    svc.recompute_hold_release(order)
    order["status"] = "MED_HOLD_ISSUED"
    touch(order)
    return object_response(svc.ser_hold(record), 201)


@bp.route("/test-orders/<order_id>/medication-holds", methods=["GET"])
def list_order_holds(order_id):
    authenticate(ALL_ROLES)
    order = svc.get_order(order_id)
    status = request.args.get("status")
    records = [h for h in svc.order_holds(order["id"])
               if status is None or h["status"] == status]
    return paginate(records, svc.ser_hold)


@bp.route("/medication-holds/<hold_id>", methods=["GET"])
def read_hold(hold_id):
    authenticate(ALL_ROLES)
    return object_response(svc.ser_hold(svc.get_hold(hold_id)))


@bp.route("/medication-holds", methods=["GET"])
def list_holds():
    authenticate(ALL_ROLES)
    order_id = request.args.get("order_id")
    medication_class = request.args.get("medication_class")
    status = request.args.get("status")
    records = []
    for hold in db.holds.values():
        if order_id is not None and hold["order_id"] != order_id:
            continue
        if medication_class is not None and \
                hold["medication_class"] != medication_class:
            continue
        if status is not None and hold["status"] != status:
            continue
        records.append(hold)
    return paginate(records, svc.ser_hold)


@bp.route("/medication-holds/<hold_id>/attest", methods=["POST"])
def attest_hold(hold_id):
    authenticate([TECHNOLOGIST])
    hold = svc.get_hold(hold_id)
    body = v.get_body()
    result = v.v_enum(body, "attestation_result", ["WITHHELD", "TAKEN"])
    if hold["status"] != "PENDING":
        raise ApiError("ERR_HOLD_STATE_INVALID",
                       "Only a PENDING hold may be attested.")
    hold["attestation_result"] = result
    hold["attested_at"] = iso(db.clock)
    hold["status"] = "ATTESTED" if result == "WITHHELD" else "VIOLATED"
    touch(hold)
    order = db.orders.get(hold["order_id"])
    if order is not None:
        before = (order["status"], order.get("hold_release_at"))
        svc.recompute_hold_release(order)
        still_pending = [h for h in svc.order_holds(order["id"])
                         if h["status"] == "PENDING"]
        if not still_pending and order["status"] == "MED_HOLD_ISSUED":
            order["status"] = "READY"
        if (order["status"], order.get("hold_release_at")) != before:
            touch(order)
    return object_response(svc.ser_hold(hold), 200)
