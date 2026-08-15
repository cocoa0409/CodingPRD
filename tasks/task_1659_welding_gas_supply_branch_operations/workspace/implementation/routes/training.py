"""Safety training classes, enrollment, and certification issuance."""
from datetime import timedelta
from flask import Blueprint, g

import db
from db import store, new_common, new_id, touch, is_int, parse_dt
from errors import ApiError
from middleware import require_roles, body
from response import ok, created, list_response, filter_param

bp = Blueprint("training", __name__)

_CLASS_ROLES = ("Trainer", "BranchManager")
_ENROLL_READ_ROLES = ("CounterRep", "BranchManager", "Trainer")
_ENROLL_TARGETS = ("ATTENDED", "NO_SHOW", "CANCELLED")


def get_class(cid):
    cls = store.training_classes.get(cid)
    if cls is None:
        raise ApiError("ERR_NOT_FOUND", 404, "TrainingClass not found")
    return cls


def get_enrollment(eid):
    en = store.enrollments.get(eid)
    if en is None:
        raise ApiError("ERR_NOT_FOUND", 404, "TrainingEnrollment not found")
    return en


def seats_booked(cls):
    return sum(1 for e in store.enrollments.values()
               if e["class_id"] == cls["id"]
               and e["status"] in ("ENROLLED", "ATTENDED", "NO_SHOW"))


def class_view(cls):
    cls["seats_booked"] = seats_booked(cls)
    return cls


@bp.route("/training-classes", methods=["POST"])
@require_roles(*_CLASS_ROLES)
def create_class():
    b = body()
    title = b.get("title")
    room = b.get("room")
    capacity = b.get("capacity")
    price = b.get("price_cents")
    # Priority 4: shape.
    if not isinstance(title, str) or not title:
        raise ApiError("ERR_VALIDATION", 400, "title is required")
    if room not in ("ROOM_A", "ROOM_B"):
        raise ApiError("ERR_VALIDATION", 400, "room must be ROOM_A or ROOM_B")
    try:
        start_at = parse_dt(b.get("start_at"))
        end_at = parse_dt(b.get("end_at"))
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400,
                       "start_at and end_at must be ISO 8601 datetimes")
    if not start_at < end_at:
        raise ApiError("ERR_VALIDATION", 400, "start_at must be earlier than end_at")
    if not is_int(capacity) or capacity <= 0:
        raise ApiError("ERR_VALIDATION", 400, "capacity must be an integer > 0")
    if not is_int(price) or price < 0:
        raise ApiError("ERR_VALIDATION", 400, "price_cents must be an integer >= 0")
    # Priority 9: no overlapping SCHEDULED class in the same room. Half-open
    # [start_at, end_at) — a class starting exactly when another ends is allowed.
    for other in store.training_classes.values():
        if other["room"] != room or other["status"] != "SCHEDULED":
            continue
        if start_at < other["_end"] and other["_start"] < end_at:
            raise ApiError("ERR_ROOM_DOUBLE_BOOKED", 409,
                           "Another SCHEDULED class overlaps this room window")
    cls = {
        "id": new_id(),
        "title": title,
        "room": room,
        "start_at": b.get("start_at"),
        "end_at": b.get("end_at"),
        "capacity": capacity,
        "price_cents": price,
        "status": "SCHEDULED",
        "_start": start_at,
        "_end": end_at,
    }
    new_common(cls)
    store.training_classes[cls["id"]] = cls
    return created(class_view(cls))


@bp.route("/training-classes/<cid>", methods=["GET"])
@require_roles(*_ENROLL_READ_ROLES)
def get_one_class(cid):
    return ok(class_view(get_class(cid)))


@bp.route("/training-classes/<cid>/advance", methods=["POST"])
@require_roles(*_CLASS_ROLES)
def advance_class(cid):
    cls = get_class(cid)
    b = body()
    to = b.get("to")
    if to not in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_VALIDATION", 400, "to must be COMPLETED or CANCELLED")
    # Priority 6: only a SCHEDULED class advances.
    if cls["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SCHEDULED class can advance")
    if to == "COMPLETED":
        # Priority 9: completion requires the clock to have reached end_at.
        if db.clock_now() < cls["_end"]:
            raise ApiError("ERR_CLASS_NOT_STARTED", 409,
                           "Class has not ended yet")
        cls["status"] = "COMPLETED"
    else:
        cls["status"] = "CANCELLED"
        # Cascade down: ENROLLED enrollments cancel; ATTENDED/NO_SHOW untouched.
        for e in store.enrollments.values():
            if e["class_id"] == cid and e["status"] == "ENROLLED":
                e["status"] = "CANCELLED"
                touch(e)
    touch(cls)
    return ok(class_view(cls))


@bp.route("/enrollments", methods=["POST"])
@require_roles("CounterRep", "Trainer", "BranchManager")
def create_enrollment():
    b = body()
    class_id = b.get("class_id")
    cust_id = b.get("customer_id")
    attendee = b.get("attendee_name")
    # Priority 3: referenced ids exist.
    if class_id is not None and class_id not in store.training_classes:
        raise ApiError("ERR_NOT_FOUND", 404, "TrainingClass not found")
    if cust_id is not None and cust_id not in store.customers:
        raise ApiError("ERR_NOT_FOUND", 404, "Customer not found")
    # Priority 4: shape.
    if not isinstance(class_id, str) or not class_id:
        raise ApiError("ERR_VALIDATION", 400, "class_id is required")
    if not isinstance(cust_id, str) or not cust_id:
        raise ApiError("ERR_VALIDATION", 400, "customer_id is required")
    if not isinstance(attendee, str) or not attendee:
        raise ApiError("ERR_VALIDATION", 400, "attendee_name is required")
    cust = store.customers[cust_id]
    cls = store.training_classes[class_id]
    # Priority 8: customer ACTIVE, class SCHEDULED.
    if cust["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_ON_HOLD", 409, "Customer is %s" % cust["status"])
    if cls["status"] != "SCHEDULED":
        raise ApiError("ERR_CLASS_NOT_SCHEDULED", 409,
                       "Class is %s" % cls["status"])
    # Priority 10: duplicate enrollment, then capacity.
    for e in store.enrollments.values():
        if e["class_id"] == class_id and e["customer_id"] == cust_id \
                and e["attendee_name"] == attendee and e["status"] != "CANCELLED":
            raise ApiError("ERR_DUPLICATE_ENROLLMENT", 409,
                           "Attendee is already enrolled in this class")
    if seats_booked(cls) >= cls["capacity"]:
        raise ApiError("ERR_CLASS_FULL", 409, "Class is full")
    en = {
        "id": new_id(),
        "class_id": class_id,
        "customer_id": cust_id,
        "attendee_name": attendee,
        "status": "ENROLLED",
        "cert_code": None,
        "cert_expires_at": None,
    }
    new_common(en)
    store.enrollments[en["id"]] = en
    return created(en)


@bp.route("/enrollments", methods=["GET"])
@require_roles(*_ENROLL_READ_ROLES)
def list_enrollments():
    rows = list(store.enrollments.values())
    rows = filter_param(rows, "class_id")
    rows = filter_param(rows, "customer_id")
    rows = filter_param(rows, "status")
    return list_response(rows)


@bp.route("/enrollments/<eid>", methods=["GET"])
@require_roles(*_ENROLL_READ_ROLES)
def get_one_enrollment(eid):
    return ok(get_enrollment(eid))


@bp.route("/enrollments/<eid>/advance", methods=["POST"])
@require_roles("CounterRep", "Trainer", "BranchManager")
def advance_enrollment(eid):
    role = g.user_role
    b = body()
    to = b.get("to")
    # Priority 2 (per-target): ATTENDED/NO_SHOW require Trainer or
    # BranchManager; CANCELLED additionally allows CounterRep.
    if to in ("ATTENDED", "NO_SHOW") and role not in ("Trainer", "BranchManager"):
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Target %s requires Trainer or BranchManager" % to)
    en = get_enrollment(eid)
    # Priority 4: valid advance target.
    if to not in _ENROLL_TARGETS:
        raise ApiError("ERR_VALIDATION", 400,
                       "to must be ATTENDED, NO_SHOW or CANCELLED")
    # Priority 6: enrollment advances only from ENROLLED.
    if en["status"] != "ENROLLED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ENROLLED enrollment can advance")
    cls = store.training_classes[en["class_id"]]
    if to in ("ATTENDED", "NO_SHOW"):
        # Priority 8: class must still be SCHEDULED.
        if cls["status"] != "SCHEDULED":
            raise ApiError("ERR_CLASS_NOT_SCHEDULED", 409,
                           "Class is %s" % cls["status"])
    if to == "ATTENDED":
        # Priority 9: attendance only at/after class start.
        if db.clock_now() < cls["_start"]:
            raise ApiError("ERR_CLASS_NOT_STARTED", 409,
                           "Class has not started yet")
        en["cert_code"] = "CERT-" + en["id"]
        en["cert_expires_at"] = db.iso_logical(
            db.clock_now() + timedelta(days=db.CERT_VALIDITY_DAYS))
    en["status"] = to
    touch(en)
    return ok(en)
