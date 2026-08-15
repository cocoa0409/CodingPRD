"""Maintenance responsibility assignments and work orders (PRD §3.7)."""
import uuid

from flask import Blueprint

from db import now_iso, store
from errors import (
    ApiError,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_CROSSING_NOT_ACTIVE,
    ERR_CROSSING_NOT_FOUND,
    ERR_FLAGGING_NOT_CONFIRMED,
    ERR_FLAGGING_PLAN_REQUIRED,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NO_FALLBACK_ASSIGNMENT,
    ERR_OUTSIDE_WORK_WINDOW,
    ERR_RESPONSIBILITY_GAP,
    ERR_RESPONSIBILITY_MISMATCH,
    ERR_WORK_ORDER_NOT_FOUND,
    ERR_WORK_WINDOW_OVERLAP,
)
from helpers import (
    body_or_empty,
    get_or_404,
    paginate,
    query_filter,
    reject_unknown,
    req_bool,
    req_date,
    req_enum,
    req_instant,
    req_str,
)
from middleware import auth
from response import ok, ok_list
from services import calcs

bp = Blueprint("maintenance", __name__)

ALL_ROLES = ("ProgramAdministrator", "RailSafetyOfficer", "LocalAuthority", "RailroadMaintainer")

CATEGORIES = ("SIGNAL", "SURFACE", "VEGETATION", "STRIPING")
PARTIES = ("RAILROAD", "ROAD_AUTHORITY")
ASSIGNMENT_STATUSES = ("ACTIVE", "SUPERSEDED", "REVOKED")
WORK_ORDER_STATUSES = ("PLANNED", "FLAGGING_CONFIRMED", "IN_WORK", "COMPLETED", "CANCELLED")
NON_TERMINAL_ORDER_STATUSES = ("PLANNED", "FLAGGING_CONFIRMED", "IN_WORK")


# ---------------------------------------------------------------------------
# MaintenanceResponsibilityAssignment
# ---------------------------------------------------------------------------

def serialize_assignment(a):
    return {
        "id": a["id"],
        "crossing_id": a["crossing_id"],
        "category": a["category"],
        "responsible_party": a["responsible_party"],
        "effective_from": a["effective_from"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.post("/maintenance-assignments")
def create_assignment():
    auth(["ProgramAdministrator"])
    body = body_or_empty()

    # Priority 3: body FK crossing_id.
    crossing_id = body.get("crossing_id")
    if isinstance(crossing_id, str) and crossing_id and crossing_id not in store.crossings:
        raise ApiError(ERR_CROSSING_NOT_FOUND, 404, f"Crossing {crossing_id} does not exist")

    # Priority 4: the crossing must be ACTIVE.
    crossing = store.crossings.get(crossing_id) if isinstance(crossing_id, str) else None
    if crossing is not None and crossing["status"] != "ACTIVE":
        raise ApiError(ERR_CROSSING_NOT_ACTIVE, 409,
                       f"Crossing {crossing_id} is not ACTIVE (current: {crossing['status']})")

    # Priority 7: request shape.
    reject_unknown(body, ("crossing_id", "category", "responsible_party", "effective_from"))
    crossing_id = req_str(body, "crossing_id")
    if crossing_id not in store.crossings:
        raise ApiError(ERR_CROSSING_NOT_FOUND, 404, f"Crossing {crossing_id} does not exist")
    category = req_enum(body, "category", CATEGORIES)
    responsible_party = req_enum(body, "responsible_party", PARTIES)
    effective_from, _ = req_date(body, "effective_from")

    # Side effect: the pair's previous ACTIVE row is superseded (cascade: no
    # version bump, updated_at refreshed).
    for other in store.assignments.values():
        if (
            other["crossing_id"] == crossing_id
            and other["category"] == category
            and other["status"] == "ACTIVE"
        ):
            other["status"] = "SUPERSEDED"
            other["updated_at"] = now_iso()

    ts = now_iso()
    rec = {
        "id": str(uuid.uuid4()),
        "crossing_id": crossing_id,
        "category": category,
        "responsible_party": responsible_party,
        "effective_from": effective_from,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.assignments[rec["id"]] = rec
    return ok(serialize_assignment(rec), 201)


@bp.get("/maintenance-assignments")
def list_assignments():
    auth(ALL_ROLES)
    crossing_f = query_filter("crossing_id")
    category_f = query_filter("category")
    status_f = query_filter("status")
    items = []
    for a in store.assignments.values():
        if crossing_f is not None and a["crossing_id"] != crossing_f:
            continue
        if category_f is not None and a["category"] != category_f:
            continue
        if status_f is not None and a["status"] != status_f:
            continue
        items.append(a)
    items = sorted(items, key=lambda a: a["created_at"])
    page, meta = paginate([serialize_assignment(a) for a in items])
    return ok_list(page, meta)


@bp.get("/maintenance-assignments/<assignment_id>")
def get_assignment(assignment_id):
    auth(ALL_ROLES)
    rec = get_or_404(store.assignments, assignment_id, ERR_ASSIGNMENT_NOT_FOUND,
                     f"Maintenance assignment {assignment_id} does not exist")
    return ok(serialize_assignment(rec))


@bp.post("/maintenance-assignments/<assignment_id>/revoke")
def revoke_assignment(assignment_id):
    auth(["ProgramAdministrator"])
    rec = get_or_404(store.assignments, assignment_id, ERR_ASSIGNMENT_NOT_FOUND,
                     f"Maintenance assignment {assignment_id} does not exist")
    body_or_empty()
    if rec["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       f"Only an ACTIVE assignment may be revoked (current: {rec['status']})")
    # A fallback must exist: at least one SUPERSEDED row for the same pair.
    superseded = [
        a for a in store.assignments.values()
        if a["crossing_id"] == rec["crossing_id"]
        and a["category"] == rec["category"]
        and a["status"] == "SUPERSEDED"
    ]
    if not superseded:
        raise ApiError(ERR_NO_FALLBACK_ASSIGNMENT, 409,
                       "No SUPERSEDED assignment exists to reinstate for this crossing/category")

    rec["status"] = "REVOKED"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    # Fallback selector: most recently updated (tie: most recently created).
    fallback = max(superseded, key=lambda a: (a["updated_at"], a["created_at"]))
    fallback["status"] = "ACTIVE"
    fallback["updated_at"] = now_iso()
    return ok(serialize_assignment(rec))


# ---------------------------------------------------------------------------
# MaintenanceWorkOrder
# ---------------------------------------------------------------------------

def serialize_work_order(w):
    return {
        "id": w["id"],
        "crossing_id": w["crossing_id"],
        "category": w["category"],
        "window_start": w["window_start"],
        "window_end": w["window_end"],
        "fouls_track": w["fouls_track"],
        "flagging_vendor": w["flagging_vendor"],
        "responsible_party": w["responsible_party"],
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def _check_party_match(order, role, user_id, crossing):
    """The actor must match the order's responsible_party."""
    if order["responsible_party"] == "RAILROAD":
        if role != "RailroadMaintainer" or user_id != crossing["railroad_code"]:
            raise ApiError(ERR_RESPONSIBILITY_MISMATCH, 403,
                           "Railroad-responsible work requires the operating railroad")
    else:
        if role != "LocalAuthority" or user_id != crossing["road_authority_locality_id"]:
            raise ApiError(ERR_RESPONSIBILITY_MISMATCH, 403,
                           "Road-authority work requires the owning locality")


@bp.post("/maintenance-work-orders")
def create_work_order():
    user_id, role = auth(["RailroadMaintainer", "LocalAuthority"])
    body = body_or_empty()

    # Priority 3: body FK crossing_id.
    crossing_id = body.get("crossing_id")
    if isinstance(crossing_id, str) and crossing_id and crossing_id not in store.crossings:
        raise ApiError(ERR_CROSSING_NOT_FOUND, 404, f"Crossing {crossing_id} does not exist")

    # Priority 6 (business safety): fouling work requires a flagging plan.
    if body.get("fouls_track") is True and not body.get("flagging_vendor"):
        raise ApiError(ERR_FLAGGING_PLAN_REQUIRED, 422,
                       "fouls_track work requires a flagging_vendor reference")

    # Priority 7: request shape.
    reject_unknown(body, ("crossing_id", "category", "window_start", "window_end",
                          "fouls_track", "flagging_vendor"))
    crossing_id = req_str(body, "crossing_id")
    if crossing_id not in store.crossings:
        raise ApiError(ERR_CROSSING_NOT_FOUND, 404, f"Crossing {crossing_id} does not exist")
    category = req_enum(body, "category", CATEGORIES)
    window_start_raw, window_start = req_instant(body, "window_start")
    window_end_raw, window_end = req_instant(body, "window_end")
    if window_end <= window_start:
        raise ApiError(ERR_INVALID_REQUEST, 400, "window_end must be after window_start")
    fouls_track = req_bool(body, "fouls_track")
    flagging_vendor = body.get("flagging_vendor")
    if flagging_vendor is not None and not isinstance(flagging_vendor, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'flagging_vendor' must be a string")

    crossing = store.crossings[crossing_id]

    # Priority 8 (referential): an ACTIVE assignment must exist for the pair;
    # the responsible party is copied from it and the creator must match.
    assignment = next(
        (a for a in store.assignments.values()
         if a["crossing_id"] == crossing_id and a["category"] == category and a["status"] == "ACTIVE"),
        None,
    )
    if assignment is None:
        raise ApiError(ERR_RESPONSIBILITY_GAP, 409,
                       "No ACTIVE maintenance responsibility assignment for this crossing/category")
    probe = {"responsible_party": assignment["responsible_party"]}
    _check_party_match(probe, role, user_id, crossing)

    # Priority 9 (temporal): half-open window overlap with non-terminal orders
    # on the same crossing.
    for other in store.work_orders.values():
        if other["crossing_id"] != crossing_id or other["status"] not in NON_TERMINAL_ORDER_STATUSES:
            continue
        if calcs.windows_overlap(window_start, window_end, other["_window_start"], other["_window_end"]):
            raise ApiError(ERR_WORK_WINDOW_OVERLAP, 409,
                           "The work window overlaps an existing non-terminal work order")

    ts = now_iso()
    rec = {
        "id": str(uuid.uuid4()),
        "crossing_id": crossing_id,
        "category": category,
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "_window_start": window_start,
        "_window_end": window_end,
        "fouls_track": fouls_track,
        "flagging_vendor": flagging_vendor,
        "responsible_party": assignment["responsible_party"],
        "status": "PLANNED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.work_orders[rec["id"]] = rec
    return ok(serialize_work_order(rec), 201)


@bp.get("/maintenance-work-orders")
def list_work_orders():
    auth(ALL_ROLES)
    crossing_f = query_filter("crossing_id")
    status_f = query_filter("status")
    items = []
    for w in store.work_orders.values():
        if crossing_f is not None and w["crossing_id"] != crossing_f:
            continue
        if status_f is not None and w["status"] != status_f:
            continue
        items.append(w)
    items = sorted(items, key=lambda w: w["created_at"])
    page, meta = paginate([serialize_work_order(w) for w in items])
    return ok_list(page, meta)


@bp.get("/maintenance-work-orders/<work_order_id>")
def get_work_order(work_order_id):
    auth(ALL_ROLES)
    rec = get_or_404(store.work_orders, work_order_id, ERR_WORK_ORDER_NOT_FOUND,
                     f"Maintenance work order {work_order_id} does not exist")
    return ok(serialize_work_order(rec))


@bp.post("/maintenance-work-orders/<work_order_id>/transition")
def transition_work_order(work_order_id):
    user_id, role = auth(["RailroadMaintainer", "LocalAuthority"])
    body = body_or_empty()
    to_status = body.get("to_status")

    # Flagging confirmation is always railroad-provided (fixed per-target role).
    if to_status == "FLAGGING_CONFIRMED" and role != "RailroadMaintainer":
        raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                       "Only a RailroadMaintainer may confirm flagging")

    rec = get_or_404(store.work_orders, work_order_id, ERR_WORK_ORDER_NOT_FOUND,
                     f"Maintenance work order {work_order_id} does not exist")
    reject_unknown(body, ("to_status",))
    if not isinstance(to_status, str) or to_status not in WORK_ORDER_STATUSES:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"to_status must be one of: {', '.join(WORK_ORDER_STATUSES)}")
    crossing = store.crossings.get(rec["crossing_id"])

    if to_status == "FLAGGING_CONFIRMED":
        if rec["status"] != "PLANNED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot confirm flagging from {rec['status']}")
        if user_id != crossing["railroad_code"]:
            raise ApiError(ERR_RESPONSIBILITY_MISMATCH, 403,
                           "Flagging is always provided by the operating railroad")
        rec["status"] = "FLAGGING_CONFIRMED"
    elif to_status == "IN_WORK":
        if rec["status"] not in ("PLANNED", "FLAGGING_CONFIRMED"):
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot begin work from {rec['status']}")
        if crossing is None or crossing["status"] != "ACTIVE":
            raise ApiError(ERR_CROSSING_NOT_ACTIVE, 409,
                           "The crossing is not ACTIVE")
        if rec["fouls_track"] and rec["status"] != "FLAGGING_CONFIRMED":
            raise ApiError(ERR_FLAGGING_NOT_CONFIRMED, 409,
                           "Fouling work requires flagging confirmation before starting")
        _check_party_match(rec, role, user_id, crossing)
        if not (rec["_window_start"] <= store.clock < rec["_window_end"]):
            raise ApiError(ERR_OUTSIDE_WORK_WINDOW, 409,
                           "The logical clock is outside the work window")
        rec["status"] = "IN_WORK"
    elif to_status == "COMPLETED":
        if rec["status"] != "IN_WORK":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot complete from {rec['status']}")
        _check_party_match(rec, role, user_id, crossing)
        rec["status"] = "COMPLETED"
    elif to_status == "CANCELLED":
        if rec["status"] not in ("PLANNED", "FLAGGING_CONFIRMED"):
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot cancel from {rec['status']}")
        _check_party_match(rec, role, user_id, crossing)
        rec["status"] = "CANCELLED"
    else:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       f"Cannot move to {to_status} from {rec['status']}")

    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return ok(serialize_work_order(rec))
