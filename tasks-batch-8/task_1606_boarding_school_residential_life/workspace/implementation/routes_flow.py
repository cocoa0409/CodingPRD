"""Routes: leave requests, sign events, duty shifts & night checks, health
center (medication orders & administrations), discipline, breaks & housing,
and storage."""

from datetime import datetime, timedelta, timezone

from flask import request

from server import app
from db import STORE, now, bump
from errors import err
from helpers import (
    authenticate, require_roles, staff_identity, get_body, get_or_404, check_fk,
    req_string, opt_string, req_int, opt_int, req_bool, req_enum, req_number,
    req_datetime, opt_datetime, req_date, success_object, list_response,
)
from services import (
    new_common, new_event, active_term, confirmed_assignment_in_term,
    weekend_leaves_used, weekend_leave_allowance, reevaluate_standing,
    late_points_ladder, whole_minutes_between, shift_slot_conflict,
    shift_bed_checks_complete, med_doses_remaining, storage_fee,
    break_housing_fee_breakdown, storage_unit_used_cuft,
    NIGHT_CHECK_POINTS, LEAVE_PENDING_STATUSES,
    APPEAL_WINDOW, SIGN_OUT_BEFORE, SIGN_OUT_AFTER,
    ser_leave, ser_sign_event, ser_shift, ser_night_check, ser_med_order,
    ser_med_admin, ser_case, ser_break_period, ser_break_housing,
    ser_storage_unit, ser_storage_reservation,
)

LEAVE_TYPES = {"WEEKEND_OVERNIGHT", "DAY_PASS", "BREAK_TRAVEL"}
LEAVE_NONTERMINAL = {"REQUESTED", "PARENT_APPROVED", "APPROVED", "SIGNED_OUT", "OVERDUE"}
CHECK_KINDS = {"BED_CHECK", "STUDY_HALL"}
CHECK_RESULTS = {"PRESENT", "LATE_ARRIVAL", "ABSENT_EXCUSED", "ABSENT_UNEXCUSED"}
SHIFT_SLOTS = {"WEEKDAY_NIGHT", "WEEKEND_DAY", "WEEKEND_NIGHT"}
MED_SLOTS = {"MORNING", "NOON", "EVENING", "BEDTIME"}
MED_OUTCOMES = {"ADMINISTERED", "REFUSED", "OMITTED_HOLD"}
CASE_CATEGORIES = {"MINOR", "MAJOR"}
SANCTION_TYPES = {"NONE", "WARNING", "PROBATION", "SUSPENSION", "EXPULSION"}
BREAK_KINDS = {"THANKSGIVING", "WINTER", "SPRING", "SUMMER"}
EVENT_TYPES = {"SIGN_OUT", "SIGN_IN"}


def _acting_student(actor):
    """The acting Student entity for Student-role subject-creating endpoints."""
    s = STORE["students"].get(actor.user_id)
    if s is None:
        raise err("ERR_NOT_FOUND", "Acting student does not exist")
    return s


def _append_sign_event(student_id, event_type, occurred_raw, occurred_dt,
                       leave_request_id, recorded_by, minutes_late):
    ev = new_event()
    ev.update({
        "student_id": student_id, "event_type": event_type,
        "occurred_at": occurred_raw, "_occurred_at": occurred_dt,
        "leave_request_id": leave_request_id,
        "recorded_by_staff_id": recorded_by, "minutes_late": minutes_late,
    })
    STORE["sign_events"][ev["id"]] = ev
    return ev


# ---------------------------------------------------------------------------
# Leave requests
# ---------------------------------------------------------------------------

def _visible_leave(actor, lv):
    if actor.role == "Student":
        return lv["student_id"] == actor.user_id
    if actor.role in ("Parent", "Guardian"):
        stu = STORE["students"].get(lv["student_id"])
        if stu is None:
            return False
        if actor.role == "Parent":
            return stu["parent_id"] == actor.user_id
        return stu.get("guardian_id") == actor.user_id
    return True


@app.post("/reslife/leave-requests")
def leave_create():
    actor = authenticate()
    require_roles(actor, ["Student"])
    student = _acting_student(actor)
    body = get_body()
    leave_type = req_enum(body, "leave_type", LEAVE_TYPES)
    destination = req_string(body, "destination")
    dep_raw, dep = req_datetime(body, "departs_at")
    ret_raw, ret = req_datetime(body, "returns_at")
    if ret <= dep:
        raise err("ERR_INVALID_FIELD_VALUE", "returns_at must be strictly after departs_at")
    if active_term() is None:
        raise err("ERR_TERM_NOT_ACTIVE", "An ACTIVE term is required to file a leave")
    if student["enrollment_status"] != "ENROLLED":
        raise err("ERR_STUDENT_NOT_ENROLLED", "Student must be ENROLLED to file a leave")
    # Half-open interval overlap with other non-terminal leaves of this student
    for other in STORE["leave_requests"].values():
        if other["student_id"] == student["id"] and other["status"] in LEAVE_NONTERMINAL:
            if dep < other["_returns_at"] and other["_departs_at"] < ret:
                raise err("ERR_LEAVE_WINDOW_OVERLAP",
                          "Leave window overlaps another non-terminal leave")
    if dep <= now():
        raise err("ERR_LEAVE_IN_PAST", "departs_at must be in the future")
    if leave_type == "WEEKEND_OVERNIGHT":
        if weekend_leaves_used(student["id"]) >= weekend_leave_allowance(student):
            raise err("ERR_LEAVE_ALLOWANCE_EXHAUSTED",
                      "Weekend overnight allowance exhausted for the ACTIVE term")
    lv = new_common()
    lv.update({
        "student_id": student["id"], "leave_type": leave_type,
        "destination": destination,
        "departs_at": dep_raw, "returns_at": ret_raw,
        "_departs_at": dep, "_returns_at": ret,
        "status": "REQUESTED",
        "decided_by_parent_id": None, "decided_by_staff_id": None,
        "denial_reason": None, "signed_out_at": None, "returned_at": None,
        "late_return_minutes": 0,
    })
    STORE["leave_requests"][lv["id"]] = lv
    return success_object(ser_leave(lv), 201)


@app.get("/reslife/leave-requests")
def leave_list():
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "DormParent", "Dean", "Student", "Parent", "Guardian"])
    items = [lv for lv in STORE["leave_requests"].values() if _visible_leave(actor, lv)]
    student_id = request.args.get("student_id")
    status = request.args.get("status")
    leave_type = request.args.get("leave_type")
    if student_id is not None:
        items = [lv for lv in items if lv["student_id"] == student_id]
    if status is not None:
        items = [lv for lv in items if lv["status"] == status]
    if leave_type is not None:
        items = [lv for lv in items if lv["leave_type"] == leave_type]
    return list_response(items, ser_leave)


@app.get("/reslife/leave-requests/<leave_id>")
def leave_get(leave_id):
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "DormParent", "Dean", "Student", "Parent", "Guardian"])
    lv = get_or_404("leave_requests", leave_id, "leave request")
    if not _visible_leave(actor, lv):
        raise err("ERR_FORBIDDEN", "Not authorized to read this leave request")
    return success_object(ser_leave(lv))


@app.post("/reslife/leave-requests/<leave_id>/parent-decision")
def leave_parent_decision(leave_id):
    actor = authenticate()
    require_roles(actor, ["Parent", "Guardian", "Dean"])
    lv = get_or_404("leave_requests", leave_id, "leave request")
    student = STORE["students"].get(lv["student_id"])
    # Actor routing (ownership scoping)
    if actor.role == "Parent":
        if student is None or student.get("is_international") \
                or student["parent_id"] != actor.user_id:
            raise err("ERR_FORBIDDEN", "Parent may decide only for their own domestic child")
    elif actor.role == "Guardian":
        guardian = STORE["guardians"].get(actor.user_id)
        if (student is None or not student.get("is_international")
                or student.get("guardian_id") != actor.user_id
                or guardian is None or guardian["status"] != "APPROVED"):
            raise err("ERR_FORBIDDEN",
                      "Guardian may decide only for their own ward while APPROVED")
    else:  # Dean proxy
        staff_identity(actor, "DEAN")
        guardian = STORE["guardians"].get(student.get("guardian_id")) if student else None
        if (student is None or not student.get("is_international")
                or guardian is None or guardian["status"] != "SUSPENDED"):
            raise err("ERR_FORBIDDEN",
                      "A Dean may proxy only when the ward's guardian is SUSPENDED")
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVE", "DENY"})
    denial_reason = opt_string(body, "denial_reason", None)
    if lv["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Family decision requires status REQUESTED")
    lv["decided_by_parent_id"] = actor.user_id
    if decision == "APPROVE":
        lv["status"] = "PARENT_APPROVED"
    else:
        lv["status"] = "DENIED"
        lv["denial_reason"] = denial_reason
    bump(lv)
    return success_object(ser_leave(lv))


@app.post("/reslife/leave-requests/<leave_id>/dorm-decision")
def leave_dorm_decision(leave_id):
    actor = authenticate()
    require_roles(actor, ["DormParent"])
    member = staff_identity(actor, "DORM_PARENT")
    lv = get_or_404("leave_requests", leave_id, "leave request")
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVE", "DENY"})
    denial_reason = opt_string(body, "denial_reason", None)
    if lv["status"] != "PARENT_APPROVED":
        raise err("ERR_INVALID_STATE", "Dorm decision requires status PARENT_APPROVED")
    student = STORE["students"].get(lv["student_id"])
    residency = confirmed_assignment_in_term(lv["student_id"], active_term())
    if residency is None:
        raise err("ERR_NO_CONFIRMED_RESIDENCY",
                  "Student has no CONFIRMED assignment in the ACTIVE term")
    room = STORE["rooms"].get(residency["room_id"])
    if room is None or member.get("dorm_id") != room["dorm_id"]:
        raise err("ERR_FORBIDDEN",
                  "Dorm parent's dorm does not match the student's residency")
    if decision == "APPROVE":
        if student is not None and student["discipline_standing"] == "SUSPENDED":
            raise err("ERR_STUDENT_SUSPENDED",
                      "Student discipline standing is SUSPENDED")
        if lv["leave_type"] == "WEEKEND_OVERNIGHT" and student is not None:
            if weekend_leaves_used(student["id"]) >= weekend_leave_allowance(student):
                raise err("ERR_LEAVE_ALLOWANCE_EXHAUSTED",
                          "Weekend overnight allowance exhausted for the ACTIVE term")
        lv["status"] = "APPROVED"
        lv["decided_by_staff_id"] = actor.user_id
    else:
        lv["status"] = "DENIED"
        lv["decided_by_staff_id"] = actor.user_id
        lv["denial_reason"] = denial_reason
    bump(lv)
    return success_object(ser_leave(lv))


@app.post("/reslife/leave-requests/<leave_id>/cancel")
def leave_cancel(leave_id):
    actor = authenticate()
    require_roles(actor, ["Student"])
    lv = get_or_404("leave_requests", leave_id, "leave request")
    if lv["student_id"] != actor.user_id:
        raise err("ERR_FORBIDDEN", "Students may cancel only their own leave requests")
    if lv["status"] not in ("REQUESTED", "PARENT_APPROVED", "APPROVED"):
        raise err("ERR_INVALID_STATE",
                  "Leave cannot be cancelled from status %s" % lv["status"])
    lv["status"] = "CANCELLED"
    bump(lv)
    return success_object(ser_leave(lv))


@app.post("/reslife/leave-requests/<leave_id>/sign-out")
def leave_sign_out(leave_id):
    actor = authenticate()
    require_roles(actor, ["FrontDesk", "DormParent"])
    staff_identity(actor, "FRONT_DESK" if actor.role == "FrontDesk" else "DORM_PARENT")
    lv = get_or_404("leave_requests", leave_id, "leave request")
    if lv["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Sign-out requires status APPROVED")
    now_dt = now()
    if not (lv["_departs_at"] - SIGN_OUT_BEFORE <= now_dt <= lv["_departs_at"] + SIGN_OUT_AFTER):
        raise err("ERR_SIGN_OUT_WINDOW",
                  "Sign-out is allowed only within [departs_at - 2h, departs_at + 6h]")
    lv["status"] = "SIGNED_OUT"
    lv["signed_out_at"] = now_dt
    bump(lv)
    from db import fmt_ts
    _append_sign_event(lv["student_id"], "SIGN_OUT", fmt_ts(now_dt), now_dt,
                       lv["id"], actor.user_id, 0)
    return success_object(ser_leave(lv))


@app.post("/reslife/leave-requests/<leave_id>/return")
def leave_return(leave_id):
    actor = authenticate()
    require_roles(actor, ["FrontDesk", "DormParent"])
    staff_identity(actor, "FRONT_DESK" if actor.role == "FrontDesk" else "DORM_PARENT")
    lv = get_or_404("leave_requests", leave_id, "leave request")
    if lv["status"] not in ("SIGNED_OUT", "OVERDUE"):
        raise err("ERR_INVALID_STATE",
                  "Return requires status SIGNED_OUT or OVERDUE")
    now_dt = now()
    late_minutes = whole_minutes_between(now_dt, lv["_returns_at"])
    lv["status"] = "RETURNED"
    lv["returned_at"] = now_dt
    lv["late_return_minutes"] = late_minutes
    bump(lv)
    from db import fmt_ts
    _append_sign_event(lv["student_id"], "SIGN_IN", fmt_ts(now_dt), now_dt,
                       lv["id"], actor.user_id, late_minutes)
    points = late_points_ladder(late_minutes)
    if points:
        student = STORE["students"].get(lv["student_id"])
        if student is not None:
            student["demerit_points"] += points
            reevaluate_standing(student)
    return success_object(ser_leave(lv))


# ---------------------------------------------------------------------------
# Sign events
# ---------------------------------------------------------------------------

@app.post("/reslife/sign-events")
def sign_event_create():
    actor = authenticate()
    require_roles(actor, ["FrontDesk", "DormParent"])
    staff_identity(actor, "FRONT_DESK" if actor.role == "FrontDesk" else "DORM_PARENT")
    body = get_body()
    check_fk(body, "student_id", "students")
    check_fk(body, "leave_request_id", "leave_requests")
    student_id = req_string(body, "student_id")
    event_type = req_enum(body, "event_type", EVENT_TYPES)
    occ_raw, occ_dt = opt_datetime(body, "occurred_at")
    if occ_dt is None:
        from db import fmt_ts
        occ_dt = now()
        occ_raw = fmt_ts(occ_dt)
    term = active_term()
    if term is None:
        raise err("ERR_TERM_NOT_ACTIVE", "An ACTIVE term is required for sign events")
    student = STORE["students"][student_id]
    if student["enrollment_status"] != "ENROLLED":
        raise err("ERR_STUDENT_NOT_ENROLLED", "Student must be ENROLLED for sign events")
    minutes_late = 0
    if event_type == "SIGN_IN":
        residency = confirmed_assignment_in_term(student_id, term)
        if residency is None:
            raise err("ERR_NOT_RESIDENT",
                      "Student holds no CONFIRMED assignment in the ACTIVE term")
        room = STORE["rooms"].get(residency["room_id"])
        dorm = STORE["dorms"].get(room["dorm_id"]) if room else None
        if dorm is not None and dorm["posture"] == "CLOSED_FOR_BREAK":
            has_break_housing = any(
                r["student_id"] == student_id and r["status"] in ("APPROVED", "CHECKED_IN")
                for r in STORE["break_housing_requests"].values())
            if not has_break_housing:
                raise err("ERR_DORM_CLOSED",
                          "Dorm is CLOSED_FOR_BREAK; sign-in requires break housing")
        curfew_str = (dorm["curfew_weekend"]
                      if occ_dt.weekday() in (4, 5) else dorm["curfew_weekday"])
        hh, mm = int(curfew_str[:2]), int(curfew_str[3:5])
        curfew_dt = datetime.combine(occ_dt.date(), datetime.min.time(),
                                     tzinfo=timezone.utc) + timedelta(hours=hh, minutes=mm)
        minutes_late = whole_minutes_between(occ_dt, curfew_dt)
        points = late_points_ladder(minutes_late)
        if points:
            student["demerit_points"] += points
            reevaluate_standing(student)
    ev = _append_sign_event(student_id, event_type, occ_raw, occ_dt,
                            body.get("leave_request_id"), actor.user_id, minutes_late)
    return success_object(ser_sign_event(ev), 201)


@app.get("/reslife/sign-events")
def sign_event_list():
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "DormParent", "Dean", "FrontDesk", "Student"])
    items = list(STORE["sign_events"].values())
    if actor.role == "Student":
        items = [e for e in items if e["student_id"] == actor.user_id]
    student_id = request.args.get("student_id")
    leave_request_id = request.args.get("leave_request_id")
    recorded_by = request.args.get("recorded_by_staff_id")
    event_type = request.args.get("event_type")
    if student_id is not None:
        items = [e for e in items if e["student_id"] == student_id]
    if leave_request_id is not None:
        items = [e for e in items if e["leave_request_id"] == leave_request_id]
    if recorded_by is not None:
        items = [e for e in items if e["recorded_by_staff_id"] == recorded_by]
    if event_type is not None:
        items = [e for e in items if e["event_type"] == event_type]
    return list_response(items, ser_sign_event)


@app.get("/reslife/sign-events/<event_id>")
def sign_event_get(event_id):
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "DormParent", "Dean", "FrontDesk", "Student"])
    ev = get_or_404("sign_events", event_id, "sign event")
    if actor.role == "Student" and ev["student_id"] != actor.user_id:
        raise err("ERR_FORBIDDEN", "Students may only read their own sign events")
    return success_object(ser_sign_event(ev))


# ---------------------------------------------------------------------------
# Duty shifts & night checks
# ---------------------------------------------------------------------------

@app.post("/reslife/duty-shifts")
def shift_create():
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin"])
    body = get_body()
    check_fk(body, "dorm_id", "dorms")
    check_fk(body, "staff_id", "staff")
    dorm_id = req_string(body, "dorm_id")
    staff_id = req_string(body, "staff_id")
    duty_raw, duty_date = req_date(body, "duty_date")
    shift_slot = req_enum(body, "shift_slot", SHIFT_SLOTS)
    expected = req_int(body, "expected_dorm_version")
    dorm = STORE["dorms"][dorm_id]
    # OCC before the conflict rule
    if expected != dorm["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_dorm_version does not match the dorm's current version")
    superseded = None
    for sh in STORE["duty_shifts"].values():
        if (sh["dorm_id"] == dorm_id and sh["_duty_date"] == duty_date
                and sh["shift_slot"] == shift_slot and sh["status"] == "SCHEDULED"):
            superseded = sh
            break
    exclude = (superseded["id"],) if superseded else ()
    if shift_slot_conflict(staff_id, duty_date, shift_slot, exclude):
        raise err("ERR_SHIFT_CONFLICT",
                  "Staff member holds a conflicting shift on that date")
    if superseded is not None:
        superseded["status"] = "CANCELLED"
        superseded["cancel_reason"] = "SUPERSEDED"
        bump(superseded)
    sh = new_common()
    sh.update({
        "dorm_id": dorm_id, "staff_id": staff_id,
        "duty_date": duty_raw, "_duty_date": duty_date, "shift_slot": shift_slot,
        "status": "SCHEDULED", "swap_requested_to_id": None, "cancel_reason": None,
    })
    STORE["duty_shifts"][sh["id"]] = sh
    bump(dorm)
    return success_object(ser_shift(sh), 201)


@app.get("/reslife/duty-shifts")
def shift_list():
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "DormParent", "Dean"])
    items = list(STORE["duty_shifts"].values())
    dorm_id = request.args.get("dorm_id")
    staff_id = request.args.get("staff_id")
    duty_date = request.args.get("duty_date")
    status = request.args.get("status")
    swap_to = request.args.get("swap_requested_to_id")
    if dorm_id is not None:
        items = [s for s in items if s["dorm_id"] == dorm_id]
    if staff_id is not None:
        items = [s for s in items if s["staff_id"] == staff_id]
    if duty_date is not None:
        items = [s for s in items if s["duty_date"] == duty_date]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if swap_to is not None:
        items = [s for s in items if s["swap_requested_to_id"] == swap_to]
    return list_response(items, ser_shift)


@app.get("/reslife/duty-shifts/<shift_id>")
def shift_get(shift_id):
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "DormParent", "Dean"])
    return success_object(ser_shift(get_or_404("duty_shifts", shift_id, "duty shift")))


@app.post("/reslife/duty-shifts/<shift_id>/request-swap")
def shift_request_swap(shift_id):
    actor = authenticate()
    require_roles(actor, ["DormParent"])
    staff_identity(actor, "DORM_PARENT")
    sh = get_or_404("duty_shifts", shift_id, "duty shift")
    if sh["staff_id"] != actor.user_id:
        raise err("ERR_FORBIDDEN", "Only the current assignee may request a swap")
    body = get_body()
    check_fk(body, "target_staff_id", "staff")
    target_id = req_string(body, "target_staff_id")
    if sh["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Swap can be requested only from SCHEDULED")
    target = STORE["staff"][target_id]
    if (not target.get("is_active") or target["staff_role"] != "DORM_PARENT"
            or target_id == sh["staff_id"]
            or shift_slot_conflict(target_id, sh["_duty_date"], sh["shift_slot"])):
        raise err("ERR_SWAP_TARGET_INELIGIBLE", "Swap target is not eligible")
    sh["status"] = "SWAP_PENDING"
    sh["swap_requested_to_id"] = target_id
    bump(sh)
    return success_object(ser_shift(sh))


@app.post("/reslife/duty-shifts/<shift_id>/swap-respond")
def shift_swap_respond(shift_id):
    actor = authenticate()
    require_roles(actor, ["DormParent"])
    staff_identity(actor, "DORM_PARENT")
    sh = get_or_404("duty_shifts", shift_id, "duty shift")
    body = get_body()
    accept = req_bool(body, "accept")
    if sh["status"] != "SWAP_PENDING":
        raise err("ERR_INVALID_STATE", "No swap is pending on this shift")
    if sh["swap_requested_to_id"] != actor.user_id:
        raise err("ERR_FORBIDDEN", "Only the named swap target may respond")
    if accept:
        sh["staff_id"] = sh["swap_requested_to_id"]
    sh["swap_requested_to_id"] = None
    sh["status"] = "SCHEDULED"
    bump(sh)
    return success_object(ser_shift(sh))


@app.post("/reslife/duty-shifts/<shift_id>/complete")
def shift_complete(shift_id):
    actor = authenticate()
    require_roles(actor, ["DormParent"])
    staff_identity(actor, "DORM_PARENT")
    sh = get_or_404("duty_shifts", shift_id, "duty shift")
    if sh["staff_id"] != actor.user_id:
        raise err("ERR_FORBIDDEN", "Only the current assignee may complete the shift")
    if sh["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Only a SCHEDULED shift can be completed")
    if not shift_bed_checks_complete(sh):
        raise err("ERR_CHECKS_OUTSTANDING",
                  "Every ENROLLED resident needs a BED_CHECK before completion")
    sh["status"] = "COMPLETED"
    bump(sh)
    return success_object(ser_shift(sh))


@app.post("/reslife/duty-shifts/<shift_id>/night-checks")
def night_check_create(shift_id):
    actor = authenticate()
    require_roles(actor, ["DormParent"])
    staff_identity(actor, "DORM_PARENT")
    sh = get_or_404("duty_shifts", shift_id, "duty shift")
    if sh["staff_id"] != actor.user_id:
        raise err("ERR_FORBIDDEN", "Night checks are recorded by the shift assignee")
    body = get_body()
    check_fk(body, "student_id", "students")
    student_id = req_string(body, "student_id")
    check_kind = req_enum(body, "check_kind", CHECK_KINDS)
    result = req_enum(body, "result", CHECK_RESULTS)
    if sh["status"] in ("COMPLETED", "MISSED", "CANCELLED"):
        raise err("ERR_INVALID_STATE",
                  "Night checks cannot be recorded on a %s shift" % sh["status"])
    term = active_term()
    if term is None:
        raise err("ERR_TERM_NOT_ACTIVE", "An ACTIVE term is required for night checks")
    student = STORE["students"][student_id]
    if student["enrollment_status"] != "ENROLLED":
        raise err("ERR_STUDENT_NOT_ENROLLED", "Student must be ENROLLED for night checks")
    for nc in STORE["night_checks"].values():
        if (nc["duty_shift_id"] == sh["id"] and nc["student_id"] == student_id
                and nc["check_kind"] == check_kind):
            raise err("ERR_CHECK_ALREADY_RECORDED",
                      "A check already exists for this shift, student, and kind")
    residency = confirmed_assignment_in_term(student_id, term)
    if residency is None:
        raise err("ERR_NOT_RESIDENT",
                  "Student holds no CONFIRMED assignment in the ACTIVE term")
    room = STORE["rooms"].get(residency["room_id"])
    if room is None or room["dorm_id"] != sh["dorm_id"]:
        raise err("ERR_NOT_RESIDENT",
                  "Student is not a confirmed resident of this shift's dorm")
    points = NIGHT_CHECK_POINTS[check_kind][result]
    nc = new_event()
    nc.update({
        "duty_shift_id": sh["id"], "student_id": student_id,
        "check_kind": check_kind, "result": result,
        "checked_at": now(), "points_assessed": points,
    })
    STORE["night_checks"][nc["id"]] = nc
    if points:
        student["demerit_points"] += points
        reevaluate_standing(student)
    return success_object(ser_night_check(nc), 201)


@app.get("/reslife/night-checks")
def night_check_list():
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "DormParent", "Dean"])
    items = list(STORE["night_checks"].values())
    duty_shift_id = request.args.get("duty_shift_id")
    student_id = request.args.get("student_id")
    check_kind = request.args.get("check_kind")
    result = request.args.get("result")
    if duty_shift_id is not None:
        items = [n for n in items if n["duty_shift_id"] == duty_shift_id]
    if student_id is not None:
        items = [n for n in items if n["student_id"] == student_id]
    if check_kind is not None:
        items = [n for n in items if n["check_kind"] == check_kind]
    if result is not None:
        items = [n for n in items if n["result"] == result]
    return list_response(items, ser_night_check)


@app.get("/reslife/night-checks/<check_id>")
def night_check_get(check_id):
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "DormParent", "Dean"])
    return success_object(ser_night_check(get_or_404("night_checks", check_id, "night check")))
