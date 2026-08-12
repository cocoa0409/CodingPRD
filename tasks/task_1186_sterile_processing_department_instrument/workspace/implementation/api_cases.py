"""OR cases and tray reservations (temporal bookings, OCC-guarded)."""
from flask import Blueprint

import domain
import store
import views
from common import (
    ANY, ApiError, auth, created, get_body, invalid_request, logical_now, ok,
    ok_list, paginate, pagination, query_str, req_datetime, req_enum, req_fk,
    req_int, req_string,
)

bp = Blueprint("cases", __name__)

PRIORITIES = ("ELECTIVE", "URGENT", "EMERGENCY")
RESERVABLE_STATUSES = ("SCHEDULED", "TRAYS_RESERVED", "AT_RISK")


@bp.post("/spd/or-cases")
def create_or_case():
    auth(("OrScheduler",))
    body = get_body()
    case_number = req_string(body, "case_number")
    surgeon = req_string(body, "surgeon")
    scheduled_start_at = req_datetime(body, "scheduled_start_at")
    scheduled_end_at = req_datetime(body, "scheduled_end_at")
    priority = req_enum(body, "priority", PRIORITIES)

    # an inverted or touching window is rejected
    if not scheduled_start_at < scheduled_end_at:
        raise invalid_request(
            "scheduled_start_at must be strictly before scheduled_end_at.")
    for existing in store.OR_CASES.values():
        if existing["case_number"] == case_number:
            raise invalid_request("case_number is already registered.")

    record = store.new_record()
    record.update({
        "case_number": case_number,
        "surgeon": surgeon,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
        "priority": priority,
        "status": "SCHEDULED",
        "completed_at": None,
    })
    store.OR_CASES[record["id"]] = record
    return created(views.or_case_view(record))


@bp.get("/spd/or-cases")
def list_or_cases():
    auth(ANY)
    limit, offset = pagination()
    status = query_str("status")
    priority = query_str("priority")
    rows = [r for r in store.OR_CASES.values()
            if (status is None or r["status"] == status)
            and (priority is None or r["priority"] == priority)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.or_case_view(r) for r in page], limit, offset, total)


@bp.get("/spd/or-cases/<case_id>")
def get_or_case(case_id):
    auth(ANY)
    record = store.fetch(store.OR_CASES, case_id)
    return ok(views.or_case_view(record))


@bp.post("/spd/or-cases/<case_id>/reservations")
def create_reservation(case_id):
    auth(("OrScheduler",))
    case = store.fetch(store.OR_CASES, case_id)
    body = get_body()
    tray = req_fk(body, "tray_id", store.TRAYS, "Tray")
    # OCC field is a non-optional input (PRD section 2.7)
    expected = req_int(body, "expected_or_case_version")

    # p5 optimistic concurrency — checked BEFORE any business rule
    if expected != case["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_or_case_version does not equal the case's "
                       "current version.")

    # p6 state gates: own (case) first, then the linked tray (observed as
    # stored — linked entities are NOT swept transitively, PRD section 2.4)
    if case["status"] not in RESERVABLE_STATUSES:
        raise ApiError("ERR_CASE_NOT_RESERVABLE", 409,
                       "reservation requires case SCHEDULED, TRAYS_RESERVED "
                       "or AT_RISK.")
    if tray["status"] != "STERILE":
        raise ApiError("ERR_TRAY_NOT_STERILE", 409,
                       "reservation requires tray STERILE.")

    # p7 patient-safety gate: strict sterility expiry for the case window,
    # evaluated before any temporal-overlap check
    if (tray["sterility_expires_at"] is None
            or not tray["sterility_expires_at"] > case["scheduled_start_at"]):
        raise ApiError("ERR_STERILITY_EXPIRED_FOR_CASE", 409,
                       "sterility_expires_at must be strictly later than "
                       "scheduled_start_at.")

    # p8 temporal gate: the new case's window expanded by 45 minutes on both
    # sides must not intersect another RESERVED reservation's case window
    # for the same tray; a gap of exactly 45 minutes is allowed
    new_start = case["scheduled_start_at"] - domain.TURNOVER_BUFFER
    new_end = case["scheduled_end_at"] + domain.TURNOVER_BUFFER
    for other in store.TRAY_RESERVATIONS.values():
        if other["tray_id"] != tray["id"] or other["status"] != "RESERVED":
            continue
        other_case = store.OR_CASES.get(other["case_id"])
        if other_case is None:
            continue
        other_start = other_case["scheduled_start_at"]
        other_end = other_case["scheduled_end_at"]
        if new_start < other_end and other_start < new_end:
            raise ApiError("ERR_TRAY_RESERVATION_TIME_CONFLICT", 409,
                           "The buffered case window intersects another "
                           "RESERVED reservation for this tray.")

    record = store.new_record()
    record.update({
        "case_id": case["id"],
        "tray_id": tray["id"],
        "status": "RESERVED",
        "reserved_at": logical_now(),
    })
    store.TRAY_RESERVATIONS[record["id"]] = record

    # every successful reservation creation bumps the case version
    if case["status"] in ("SCHEDULED", "AT_RISK"):
        case["status"] = "TRAYS_RESERVED"
    store.touch(case)
    return created(views.reservation_view(record))


@bp.get("/spd/tray-reservations")
def list_reservations():
    auth(ANY)
    limit, offset = pagination()
    case_id = query_str("case_id")
    tray_id = query_str("tray_id")
    status = query_str("status")
    rows = [r for r in store.TRAY_RESERVATIONS.values()
            if (case_id is None or r["case_id"] == case_id)
            and (tray_id is None or r["tray_id"] == tray_id)
            and (status is None or r["status"] == status)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.reservation_view(r) for r in page], limit, offset, total)


@bp.get("/spd/tray-reservations/<reservation_id>")
def get_reservation(reservation_id):
    auth(ANY)
    record = store.fetch(store.TRAY_RESERVATIONS, reservation_id)
    return ok(views.reservation_view(record))


@bp.post("/spd/tray-reservations/<reservation_id>/release")
def release_reservation(reservation_id):
    auth(("OrScheduler",))
    reservation = store.fetch(store.TRAY_RESERVATIONS, reservation_id)
    if reservation["status"] != "RESERVED":
        raise ApiError("ERR_RESERVATION_NOT_ACTIVE", 409,
                       "release requires reservation RESERVED.")
    reservation["status"] = "RELEASED"
    store.touch(reservation)
    # the tray is untouched (stays STERILE); the owning case recomputes
    domain.recompute_case_after_release(reservation["case_id"])
    return ok(views.reservation_view(reservation))


# --------------------------------------------------------------------------
# Case lifecycle
# --------------------------------------------------------------------------


@bp.post("/spd/or-cases/<case_id>/start")
def start_case(case_id):
    auth(("OrScheduler",))
    case = store.fetch(store.OR_CASES, case_id)
    now = logical_now()

    reserved = [r for r in store.TRAY_RESERVATIONS.values()
                if r["case_id"] == case["id"] and r["status"] == "RESERVED"]
    reservation_path = False

    # p6 own-status gate
    if case["status"] in ("TRAYS_RESERVED", "AT_RISK"):
        if len(reserved) < 1:
            raise ApiError("ERR_CASE_NOT_STARTABLE", 409,
                           "start requires at least one RESERVED reservation.")
        reservation_path = True
    elif case["status"] == "SCHEDULED":
        iuss = [e for e in store.IUSS_EXCEPTIONS.values()
                if e["case_id"] == case["id"]]
        if len(iuss) < 1:
            raise ApiError("ERR_CASE_NOT_STARTABLE", 409,
                           "SCHEDULED start requires at least one IUSS "
                           "exception for the case.")
    else:
        raise ApiError("ERR_CASE_NOT_STARTABLE", 409,
                       "case is not startable from its current status.")

    # p6 linked state gate: every linked loaner set must be READY
    for loaner in store.LOANER_SETS.values():
        if loaner["case_id"] == case["id"] and loaner["status"] != "READY":
            raise ApiError("ERR_LOANER_NOT_READY", 409,
                           "A loaner set booked for this case is not READY.")

    # p7 patient-safety gate: reserved trays observed as stored (NOT swept)
    if reservation_path:
        for res in reserved:
            tray = store.TRAYS.get(res["tray_id"])
            if (tray is None or tray["status"] != "STERILE"
                    or tray["sterility_expires_at"] is None
                    or not tray["sterility_expires_at"] > now):
                raise ApiError("ERR_RESERVED_TRAY_EXPIRED", 409,
                               "A reserved tray is not STERILE or its "
                               "sterility has lapsed.")

    case["status"] = "IN_PROGRESS"
    store.touch(case)
    if reservation_path:
        for res in reserved:
            tray = store.TRAYS.get(res["tray_id"])
            if tray is not None and tray["status"] == "STERILE":
                tray["status"] = "IN_USE"
                store.touch(tray)
    for loaner in store.LOANER_SETS.values():
        if loaner["case_id"] == case["id"] and loaner["status"] == "READY":
            loaner["status"] = "IN_USE"
            store.touch(loaner)
    return ok(views.or_case_view(case))


@bp.post("/spd/or-cases/<case_id>/complete")
def complete_case(case_id):
    auth(("OrScheduler",))
    case = store.fetch(store.OR_CASES, case_id)
    if case["status"] != "IN_PROGRESS":
        raise ApiError("ERR_CASE_NOT_COMPLETABLE", 409,
                       "complete requires case IN_PROGRESS.")

    case["status"] = "COMPLETED"
    case["completed_at"] = logical_now()
    store.touch(case)

    for res in list(store.TRAY_RESERVATIONS.values()):
        if res["case_id"] == case["id"] and res["status"] == "RESERVED":
            res["status"] = "USED"
            store.touch(res)
            tray = store.TRAYS.get(res["tray_id"])
            if tray is not None and tray["status"] == "IN_USE":
                tray["status"] = "AWAITING_DECONTAMINATION"
                tray["sterility_expires_at"] = None
                store.touch(tray)

    # trays flashed for this case via IUSS also cycle back
    for exc in store.IUSS_EXCEPTIONS.values():
        if exc["case_id"] != case["id"]:
            continue
        tray = store.TRAYS.get(exc["tray_id"])
        if tray is not None and tray["status"] == "IN_USE":
            tray["status"] = "AWAITING_DECONTAMINATION"
            tray["sterility_expires_at"] = None
            store.touch(tray)

    for loaner in store.LOANER_SETS.values():
        if loaner["case_id"] == case["id"] and loaner["status"] == "IN_USE":
            loaner["status"] = "RETURNED"
            store.touch(loaner)
    return ok(views.or_case_view(case))


@bp.post("/spd/or-cases/<case_id>/cancel")
def cancel_case(case_id):
    auth(("OrScheduler",))
    case = store.fetch(store.OR_CASES, case_id)
    if case["status"] not in RESERVABLE_STATUSES:
        raise ApiError("ERR_CASE_NOT_CANCELLABLE", 409,
                       "cancel requires case SCHEDULED, TRAYS_RESERVED or "
                       "AT_RISK.")

    case["status"] = "CANCELLED"
    store.touch(case)
    # RESERVED reservations are released; the trays remain STERILE, untouched
    for res in list(store.TRAY_RESERVATIONS.values()):
        if res["case_id"] == case["id"] and res["status"] == "RESERVED":
            res["status"] = "RELEASED"
            store.touch(res)
    return ok(views.or_case_view(case))
