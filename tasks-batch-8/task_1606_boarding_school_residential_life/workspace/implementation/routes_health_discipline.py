"""Routes: health center (medication orders/administrations), discipline cases,
break periods, break housing, and storage."""

from flask import request

from server import app
from db import STORE, now, bump
from errors import err
from helpers import (
    authenticate, require_roles, staff_identity, get_body, get_or_404, check_fk,
    req_string, opt_string, req_int, opt_int, req_bool, req_enum, req_number,
    req_datetime, req_date, success_object, list_response,
)
from services import (
    new_common, new_event, reevaluate_standing, storage_fee,
    break_housing_fee_breakdown, med_doses_remaining,
    APPEAL_WINDOW,
    ser_med_order, ser_med_admin, ser_case, ser_break_period,
    ser_break_housing, ser_storage_unit, ser_storage_reservation,
)

MED_SLOTS = {"MORNING", "NOON", "EVENING", "BEDTIME"}
MED_OUTCOMES = {"ADMINISTERED", "REFUSED", "OMITTED_HOLD"}
CASE_CATEGORIES = {"MINOR", "MAJOR"}
SANCTION_TYPES = {"NONE", "WARNING", "PROBATION", "SUSPENSION", "EXPULSION"}
BREAK_KINDS = {"THANKSGIVING", "WINTER", "SPRING", "SUMMER"}


# ---------------------------------------------------------------------------
# Medication orders
# ---------------------------------------------------------------------------

@app.post("/reslife/medication-orders")
def med_order_create():
    actor = authenticate()
    require_roles(actor, ["Nurse"])
    staff_identity(actor, "NURSE")
    body = get_body()
    check_fk(body, "student_id", "students")
    student_id = req_string(body, "student_id")
    medication_name = req_string(body, "medication_name")
    dose_mg = req_number(body, "dose_mg")
    slot = req_enum(body, "slot", MED_SLOTS)
    doses_total = req_int(body, "doses_total")
    refill_threshold = opt_int(body, "refill_threshold", 5)
    is_controlled = req_bool(body, "is_controlled")
    prescriber_name = req_string(body, "prescriber_name")
    if doses_total < 1:
        raise err("ERR_INVALID_FIELD_VALUE", "doses_total must be >= 1")
    student = STORE["students"][student_id]
    if student["enrollment_status"] != "ENROLLED":
        raise err("ERR_STUDENT_NOT_ENROLLED",
                  "Student must be ENROLLED for a medication order")
    for o in STORE["medication_orders"].values():
        if (o["student_id"] == student_id and o["medication_name"] == medication_name
                and o["slot"] == slot and o["status"] == "ACTIVE"):
            raise err("ERR_DUPLICATE_ACTIVE_ORDER",
                      "An ACTIVE order already exists for this student/medication/slot")
    o = new_common()
    o.update({
        "student_id": student_id, "medication_name": medication_name,
        "dose_mg": dose_mg, "slot": slot, "doses_total": doses_total,
        "refill_threshold": refill_threshold, "is_controlled": is_controlled,
        "prescriber_name": prescriber_name, "status": "ACTIVE", "hold_reason": None,
    })
    STORE["medication_orders"][o["id"]] = o
    return success_object(ser_med_order(o), 201)


@app.get("/reslife/medication-orders")
def med_order_list():
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "Nurse", "Dean"])
    items = list(STORE["medication_orders"].values())
    student_id = request.args.get("student_id")
    status = request.args.get("status")
    if student_id is not None:
        items = [o for o in items if o["student_id"] == student_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_response(items, ser_med_order)


@app.get("/reslife/medication-orders/<order_id>")
def med_order_get(order_id):
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "Nurse", "Dean"])
    return success_object(ser_med_order(get_or_404("medication_orders", order_id, "medication order")))


@app.post("/reslife/medication-orders/<order_id>/hold")
def med_order_hold(order_id):
    actor = authenticate()
    require_roles(actor, ["Nurse"])
    staff_identity(actor, "NURSE")
    o = get_or_404("medication_orders", order_id, "medication order")
    body = get_body()
    reason = req_string(body, "reason")
    if o["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE order can be held")
    o["status"] = "HOLD"
    o["hold_reason"] = reason
    bump(o)
    return success_object(ser_med_order(o))


@app.post("/reslife/medication-orders/<order_id>/resume")
def med_order_resume(order_id):
    actor = authenticate()
    require_roles(actor, ["Nurse"])
    staff_identity(actor, "NURSE")
    o = get_or_404("medication_orders", order_id, "medication order")
    if o["status"] != "HOLD":
        raise err("ERR_INVALID_STATE", "Only a HOLD order can be resumed")
    o["status"] = "ACTIVE"
    o["hold_reason"] = None
    bump(o)
    return success_object(ser_med_order(o))


@app.post("/reslife/medication-orders/<order_id>/discontinue")
def med_order_discontinue(order_id):
    actor = authenticate()
    require_roles(actor, ["Nurse"])
    staff_identity(actor, "NURSE")
    o = get_or_404("medication_orders", order_id, "medication order")
    if o["status"] not in ("ACTIVE", "HOLD"):
        raise err("ERR_INVALID_STATE", "Only an ACTIVE or HOLD order can be discontinued")
    o["status"] = "DISCONTINUED"
    bump(o)
    return success_object(ser_med_order(o))


@app.post("/reslife/medication-orders/<order_id>/administrations")
def med_admin_create(order_id):
    actor = authenticate()
    require_roles(actor, ["Nurse"])
    staff_identity(actor, "NURSE")
    o = get_or_404("medication_orders", order_id, "medication order")
    body = get_body()
    check_fk(body, "witness_staff_id", "staff")
    scheduled_raw, _ = req_date(body, "scheduled_date")
    outcome = req_enum(body, "outcome", MED_OUTCOMES)
    witness_id = body.get("witness_staff_id")
    notes = opt_string(body, "notes", None)
    # Priority 10: terminal orders
    if o["status"] in ("DISCONTINUED", "COMPLETED"):
        raise err("ERR_ORDER_NOT_ACTIVE",
                  "Administrations are not allowed on a %s order" % o["status"])
    # Priority 11: hold safety stop (outranks duplicate-dose)
    if o["status"] == "HOLD":
        raise err("ERR_MEDICATION_ON_HOLD",
                  "Order is on HOLD; administrations are suspended")
    # Priority 12: controlled-substance witness
    if o["is_controlled"] and outcome == "ADMINISTERED":
        witness = STORE["staff"].get(witness_id) if witness_id else None
        if (witness is None or witness_id == actor.user_id
                or not witness.get("is_active")):
            raise err("ERR_WITNESS_REQUIRED",
                      "Controlled administrations require an active witness other than the nurse")
    # Priority 14: one administration per (order, scheduled_date)
    for a in STORE["medication_administrations"].values():
        if a["order_id"] == o["id"] and a["scheduled_date"] == scheduled_raw:
            raise err("ERR_DOSE_ALREADY_LOGGED",
                      "An administration already exists for that scheduled_date")
    a = new_event()
    a.update({
        "order_id": o["id"], "scheduled_date": scheduled_raw, "outcome": outcome,
        "administered_by_staff_id": actor.user_id,
        "witness_staff_id": witness_id, "notes": notes,
    })
    STORE["medication_administrations"][a["id"]] = a
    if outcome == "ADMINISTERED" and med_doses_remaining(o) == 0:
        o["status"] = "COMPLETED"
        bump(o)
    return success_object(ser_med_admin(a), 201)


@app.get("/reslife/medication-administrations")
def med_admin_list():
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "Nurse", "Dean"])
    items = list(STORE["medication_administrations"].values())
    order_id = request.args.get("order_id")
    by = request.args.get("administered_by_staff_id")
    witness = request.args.get("witness_staff_id")
    if order_id is not None:
        items = [a for a in items if a["order_id"] == order_id]
    if by is not None:
        items = [a for a in items if a["administered_by_staff_id"] == by]
    if witness is not None:
        items = [a for a in items if a["witness_staff_id"] == witness]
    return list_response(items, ser_med_admin)


@app.get("/reslife/medication-administrations/<administration_id>")
def med_admin_get(administration_id):
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "Nurse", "Dean"])
    return success_object(
        ser_med_admin(get_or_404("medication_administrations", administration_id,
                                 "medication administration")))


@app.get("/reslife/medication-orders/<order_id>/administrations")
def med_order_admin_list(order_id):
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "Nurse", "Dean"])
    o = get_or_404("medication_orders", order_id, "medication order")
    items = [a for a in STORE["medication_administrations"].values()
             if a["order_id"] == o["id"]]
    return list_response(items, ser_med_admin)


# ---------------------------------------------------------------------------
# Discipline cases
# ---------------------------------------------------------------------------

@app.post("/reslife/discipline-cases")
def case_create():
    actor = authenticate()
    require_roles(actor, ["Dean", "DormParent"])
    staff_identity(actor, "DEAN" if actor.role == "Dean" else "DORM_PARENT")
    body = get_body()
    check_fk(body, "student_id", "students")
    student_id = req_string(body, "student_id")
    category = req_enum(body, "category", CASE_CATEGORIES)
    description = req_string(body, "description")
    points_proposed = req_int(body, "points_proposed")
    c = new_common()
    c.update({
        "student_id": student_id, "reported_by_staff_id": actor.user_id,
        "category": category, "description": description,
        "points_proposed": points_proposed, "status": "REPORTED",
        "hearing_officer_id": None, "hearing_at": None,
        "sanction_type": None, "points_assessed": 0, "decided_at": None,
        "appeal_count": 0,
    })
    STORE["discipline_cases"][c["id"]] = c
    return success_object(ser_case(c), 201)


@app.get("/reslife/discipline-cases")
def case_list():
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "Dean", "DormParent"])
    items = list(STORE["discipline_cases"].values())
    student_id = request.args.get("student_id")
    status = request.args.get("status")
    reporter = request.args.get("reported_by_staff_id")
    officer = request.args.get("hearing_officer_id")
    if student_id is not None:
        items = [c for c in items if c["student_id"] == student_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if reporter is not None:
        items = [c for c in items if c["reported_by_staff_id"] == reporter]
    if officer is not None:
        items = [c for c in items if c["hearing_officer_id"] == officer]
    return list_response(items, ser_case)


@app.get("/reslife/discipline-cases/<case_id>")
def case_get(case_id):
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "Dean", "DormParent", "Student"])
    c = get_or_404("discipline_cases", case_id, "discipline case")
    if actor.role == "Student" and c["student_id"] != actor.user_id:
        raise err("ERR_FORBIDDEN", "Students may only read their own cases")
    return success_object(ser_case(c))


@app.post("/reslife/discipline-cases/<case_id>/begin-review")
def case_begin_review(case_id):
    actor = authenticate()
    require_roles(actor, ["Dean"])
    staff_identity(actor, "DEAN")
    c = get_or_404("discipline_cases", case_id, "discipline case")
    if c["status"] != "REPORTED":
        raise err("ERR_INVALID_STATE", "Only a REPORTED case can move to UNDER_REVIEW")
    c["status"] = "UNDER_REVIEW"
    bump(c)
    return success_object(ser_case(c))


@app.post("/reslife/discipline-cases/<case_id>/schedule-hearing")
def case_schedule_hearing(case_id):
    actor = authenticate()
    require_roles(actor, ["Dean"])
    staff_identity(actor, "DEAN")
    c = get_or_404("discipline_cases", case_id, "discipline case")
    body = get_body()
    check_fk(body, "hearing_officer_id", "staff")
    hearing_raw, hearing_dt = req_datetime(body, "hearing_at")
    officer_id = req_string(body, "hearing_officer_id")
    if c["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE",
                  "Hearings are scheduled only from UNDER_REVIEW")
    officer = STORE["staff"][officer_id]
    if officer["staff_role"] != "DEAN" or not officer.get("is_active"):
        raise err("ERR_INVALID_FIELD_VALUE",
                  "hearing_officer_id must name an active DEAN")
    if officer_id == c["reported_by_staff_id"]:
        raise err("ERR_REPORTER_CANNOT_ADJUDICATE",
                  "The hearing officer must not be the reporter")
    if hearing_dt <= now():
        raise err("ERR_HEARING_IN_PAST", "hearing_at must be in the future")
    c["hearing_officer_id"] = officer_id
    c["hearing_at"] = hearing_raw
    c["status"] = "HEARING_SCHEDULED"
    bump(c)
    return success_object(ser_case(c))


@app.post("/reslife/discipline-cases/<case_id>/record-outcome")
def case_record_outcome(case_id):
    actor = authenticate()
    require_roles(actor, ["Dean"])
    staff_identity(actor, "DEAN")
    c = get_or_404("discipline_cases", case_id, "discipline case")
    body = get_body()
    outcome = req_enum(body, "outcome", {"SANCTIONED", "DISMISSED"})
    sanction_type = body.get("sanction_type")
    if sanction_type is not None:
        if not isinstance(sanction_type, str) or sanction_type not in SANCTION_TYPES:
            raise err("ERR_INVALID_FIELD_VALUE",
                      "sanction_type must be one of %s" % sorted(SANCTION_TYPES))
    points_assessed = opt_int(body, "points_assessed", None)
    if c["status"] == "HEARING_SCHEDULED":
        if c["hearing_officer_id"] != actor.user_id:
            raise err("ERR_FORBIDDEN",
                      "Only the named hearing officer may record the outcome")
    elif c["status"] == "UNDER_REVIEW":
        if actor.user_id == c["reported_by_staff_id"]:
            raise err("ERR_REPORTER_CANNOT_ADJUDICATE",
                      "The reporter may not adjudicate the case")
        if c["category"] == "MAJOR":
            raise err("ERR_HEARING_REQUIRED",
                      "MAJOR cases require a hearing before outcome")
    else:
        raise err("ERR_INVALID_STATE",
                  "Outcomes are recorded only from UNDER_REVIEW or HEARING_SCHEDULED")
    if outcome == "SANCTIONED":
        applied = points_assessed if points_assessed is not None else c["points_proposed"]
        c["points_assessed"] = applied
        c["sanction_type"] = sanction_type
        c["decided_at"] = now()
        c["status"] = "SANCTIONED"
        bump(c)
        student = STORE["students"].get(c["student_id"])
        if student is not None and applied:
            student["demerit_points"] += applied
            reevaluate_standing(student)
    else:
        c["decided_at"] = now()
        c["status"] = "DISMISSED"
        bump(c)
    return success_object(ser_case(c))


@app.post("/reslife/discipline-cases/<case_id>/appeal")
def case_appeal(case_id):
    actor = authenticate()
    require_roles(actor, ["Student"])
    c = get_or_404("discipline_cases", case_id, "discipline case")
    if c["student_id"] != actor.user_id:
        raise err("ERR_FORBIDDEN", "Only the case subject may appeal")
    if c["status"] != "SANCTIONED":
        raise err("ERR_INVALID_STATE", "Only a SANCTIONED case can be appealed")
    if c["appeal_count"] != 0:
        raise err("ERR_APPEAL_LIMIT_REACHED", "The single appeal has already been used")
    if c["decided_at"] is not None and now() > c["decided_at"] + APPEAL_WINDOW:
        raise err("ERR_APPEAL_WINDOW_CLOSED",
                  "Appeals must be filed within 168h of decided_at")
    c["status"] = "APPEALED"
    c["appeal_count"] = 1
    bump(c)
    return success_object(ser_case(c))


@app.post("/reslife/discipline-cases/<case_id>/appeal-decision")
def case_appeal_decision(case_id):
    actor = authenticate()
    require_roles(actor, ["Dean"])
    staff_identity(actor, "DEAN")
    c = get_or_404("discipline_cases", case_id, "discipline case")
    body = get_body()
    decision = req_enum(body, "decision", {"UPHOLD", "OVERTURN"})
    adjusted = opt_int(body, "adjusted_points", None)
    if c["status"] != "APPEALED":
        raise err("ERR_INVALID_STATE", "Appeal decisions require status APPEALED")
    if actor.user_id == c["reported_by_staff_id"]:
        raise err("ERR_REPORTER_CANNOT_ADJUDICATE",
                  "The reporter may not decide the appeal")
    student = STORE["students"].get(c["student_id"])
    if decision == "UPHOLD":
        if adjusted is not None and adjusted != c["points_assessed"]:
            delta = adjusted - c["points_assessed"]
            c["points_assessed"] = adjusted
            if student is not None and delta:
                student["demerit_points"] += delta
        c["status"] = "SANCTIONED"
        bump(c)
        if student is not None:
            reevaluate_standing(student)
    else:
        if student is not None and c["points_assessed"]:
            student["demerit_points"] -= c["points_assessed"]
        c["points_assessed"] = 0
        c["status"] = "DISMISSED"
        bump(c)
        if student is not None:
            reevaluate_standing(student)
    return success_object(ser_case(c))


@app.post("/reslife/discipline-cases/<case_id>/close")
def case_close(case_id):
    actor = authenticate()
    require_roles(actor, ["Dean"])
    staff_identity(actor, "DEAN")
    c = get_or_404("discipline_cases", case_id, "discipline case")
    if c["status"] != "SANCTIONED":
        raise err("ERR_INVALID_STATE", "Only a SANCTIONED case can be closed")
    window_passed = c["decided_at"] is not None and now() > c["decided_at"] + APPEAL_WINDOW
    if not (window_passed or c["appeal_count"] == 1):
        raise err("ERR_INVALID_STATE",
                  "The appeal window must pass or the single appeal be filed before close")
    c["status"] = "CLOSED"
    bump(c)
    return success_object(ser_case(c))


# ---------------------------------------------------------------------------
# Break periods
# ---------------------------------------------------------------------------

@app.post("/reslife/break-periods")
def break_create():
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin"])
    body = get_body()
    name = req_string(body, "name")
    kind = req_enum(body, "kind", BREAK_KINDS)
    starts_raw, starts = req_date(body, "starts_on")
    ends_raw, ends = req_date(body, "ends_on")
    housing_available = req_bool(body, "housing_available")
    if ends <= starts:
        raise err("ERR_INVALID_FIELD_VALUE", "ends_on must be strictly after starts_on")
    bp = new_common()
    bp.update({
        "name": name, "kind": kind, "starts_on": starts_raw, "ends_on": ends_raw,
        "_starts_on": starts, "_ends_on": ends,
        "housing_available": housing_available, "status": "UPCOMING",
    })
    STORE["break_periods"][bp["id"]] = bp
    return success_object(ser_break_period(bp), 201)


@app.get("/reslife/break-periods")
def break_list():
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "DormParent", "Nurse", "Dean", "FrontDesk", "Student"])
    items = list(STORE["break_periods"].values())
    status = request.args.get("status")
    kind = request.args.get("kind")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    if kind is not None:
        items = [b for b in items if b["kind"] == kind]
    return list_response(items, ser_break_period)


@app.get("/reslife/break-periods/<break_id>")
def break_get(break_id):
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "DormParent", "Nurse", "Dean", "FrontDesk", "Student"])
    return success_object(ser_break_period(get_or_404("break_periods", break_id, "break period")))


# ---------------------------------------------------------------------------
# Break housing requests
# ---------------------------------------------------------------------------

BREAK_HOUSING_NONTERMINAL = {"REQUESTED", "APPROVED", "CHECKED_IN"}


@app.post("/reslife/break-housing-requests")
def break_housing_create():
    actor = authenticate()
    require_roles(actor, ["Student"])
    student = STORE["students"].get(actor.user_id)
    if student is None:
        raise err("ERR_NOT_FOUND", "Acting student does not exist")
    body = get_body()
    check_fk(body, "break_period_id", "break_periods")
    break_period_id = req_string(body, "break_period_id")
    reason = opt_string(body, "reason", None)
    for r in STORE["break_housing_requests"].values():
        if (r["student_id"] == student["id"] and r["break_period_id"] == break_period_id
                and r["status"] in BREAK_HOUSING_NONTERMINAL):
            raise err("ERR_DUPLICATE_BREAK_REQUEST",
                      "A non-terminal request already exists for this student and break")
    if not student.get("is_international"):
        raise err("ERR_NOT_ELIGIBLE_BREAK_HOUSING",
                  "Only international students may request break housing")
    r = new_common()
    r.update({
        "student_id": student["id"], "break_period_id": break_period_id,
        "reason": reason, "status": "REQUESTED", "room_id": None,
        "room_charge_cents": 0, "storage_total_cents": 0,
        "deposit_credit_cents": 0, "fee_cents": 0,
    })
    STORE["break_housing_requests"][r["id"]] = r
    return success_object(ser_break_housing(r), 201)


@app.get("/reslife/break-housing-requests")
def break_housing_list():
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "Dean", "DormParent", "Student"])
    items = list(STORE["break_housing_requests"].values())
    if actor.role == "Student":
        items = [r for r in items if r["student_id"] == actor.user_id]
    student_id = request.args.get("student_id")
    break_period_id = request.args.get("break_period_id")
    status = request.args.get("status")
    room_id = request.args.get("room_id")
    if student_id is not None:
        items = [r for r in items if r["student_id"] == student_id]
    if break_period_id is not None:
        items = [r for r in items if r["break_period_id"] == break_period_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if room_id is not None:
        items = [r for r in items if r["room_id"] == room_id]
    return list_response(items, ser_break_housing)


@app.get("/reslife/break-housing-requests/<request_id>")
def break_housing_get(request_id):
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "Dean", "DormParent", "Student"])
    r = get_or_404("break_housing_requests", request_id, "break housing request")
    if actor.role == "Student" and r["student_id"] != actor.user_id:
        raise err("ERR_FORBIDDEN", "Students may only read their own requests")
    return success_object(ser_break_housing(r))


@app.post("/reslife/break-housing-requests/<request_id>/decide")
def break_housing_decide(request_id):
    actor = authenticate()
    require_roles(actor, ["Dean", "SchoolAdmin"])
    if actor.role == "Dean":
        staff_identity(actor, "DEAN")
    r = get_or_404("break_housing_requests", request_id, "break housing request")
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVE", "DENY"})
    if r["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Decision requires status REQUESTED")
    if decision == "APPROVE":
        bp = STORE["break_periods"].get(r["break_period_id"])
        if bp is None or bp["status"] not in ("UPCOMING", "ACTIVE"):
            raise err("ERR_INVALID_STATE",
                      "Approval requires the break to be UPCOMING or ACTIVE")
        room_charge, storage_total, deposit, fee = break_housing_fee_breakdown(
            r["student_id"], r["break_period_id"])
        r["room_charge_cents"] = room_charge
        r["storage_total_cents"] = storage_total
        r["deposit_credit_cents"] = deposit
        r["fee_cents"] = fee
        r["status"] = "APPROVED"
    else:
        r["status"] = "DENIED"
    bump(r)
    return success_object(ser_break_housing(r))


@app.post("/reslife/break-housing-requests/<request_id>/check-in")
def break_housing_check_in(request_id):
    actor = authenticate()
    require_roles(actor, ["DormParent"])
    staff_identity(actor, "DORM_PARENT")
    r = get_or_404("break_housing_requests", request_id, "break housing request")
    if r["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Check-in requires status APPROVED")
    bp = STORE["break_periods"].get(r["break_period_id"])
    if bp is None or bp["status"] != "ACTIVE":
        raise err("ERR_BREAK_NOT_ACTIVE", "Break period is not ACTIVE")
    r["status"] = "CHECKED_IN"
    bump(r)
    return success_object(ser_break_housing(r))


@app.post("/reslife/break-housing-requests/<request_id>/check-out")
def break_housing_check_out(request_id):
    actor = authenticate()
    require_roles(actor, ["DormParent"])
    staff_identity(actor, "DORM_PARENT")
    r = get_or_404("break_housing_requests", request_id, "break housing request")
    if r["status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", "Check-out requires status CHECKED_IN")
    r["status"] = "CHECKED_OUT"
    bump(r)
    return success_object(ser_break_housing(r))


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

@app.post("/reslife/storage-units")
def storage_unit_create():
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin"])
    body = get_body()
    label = req_string(body, "label")
    capacity = req_int(body, "capacity_cuft")
    if capacity < 1:
        raise err("ERR_INVALID_FIELD_VALUE", "capacity_cuft must be >= 1")
    u = new_common()
    u.update({"label": label, "capacity_cuft": capacity, "status": "OPEN"})
    STORE["storage_units"][u["id"]] = u
    return success_object(ser_storage_unit(u), 201)


@app.get("/reslife/storage-units")
def storage_unit_list():
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "DormParent", "FrontDesk", "Dean", "Student"])
    items = list(STORE["storage_units"].values())
    status = request.args.get("status")
    if status is not None:
        items = [u for u in items if u["status"] == status]
    return list_response(items, ser_storage_unit)


@app.get("/reslife/storage-units/<unit_id>")
def storage_unit_get(unit_id):
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "DormParent", "FrontDesk", "Dean", "Student"])
    return success_object(ser_storage_unit(get_or_404("storage_units", unit_id, "storage unit")))


@app.post("/reslife/storage-reservations")
def storage_reservation_create():
    actor = authenticate()
    require_roles(actor, ["Student"])
    student = STORE["students"].get(actor.user_id)
    if student is None:
        raise err("ERR_NOT_FOUND", "Acting student does not exist")
    body = get_body()
    check_fk(body, "storage_unit_id", "storage_units")
    check_fk(body, "break_period_id", "break_periods")
    unit_id = req_string(body, "storage_unit_id")
    break_period_id = req_string(body, "break_period_id")
    volume = req_int(body, "volume_cuft")
    weeks = req_int(body, "weeks")
    items_description = req_string(body, "items_description")
    if volume < 1:
        raise err("ERR_INVALID_FIELD_VALUE", "volume_cuft must be >= 1")
    if weeks < 1:
        raise err("ERR_INVALID_FIELD_VALUE", "weeks must be >= 1")
    if student["enrollment_status"] != "ENROLLED":
        raise err("ERR_STUDENT_NOT_ENROLLED",
                  "Student must be ENROLLED to reserve storage")
    unit = STORE["storage_units"][unit_id]
    bp = STORE["break_periods"][break_period_id]
    # Aggregate capacity for the unit and break
    used_for_break = 0
    for r in STORE["storage_reservations"].values():
        if (r["storage_unit_id"] == unit_id and r["break_period_id"] == break_period_id
                and r["status"] in ("RESERVED", "CHECKED_IN")):
            used_for_break += r["volume_cuft"]
    if used_for_break + volume > unit["capacity_cuft"]:
        raise err("ERR_STORAGE_CAPACITY_EXCEEDED",
                  "Aggregate reservation volume would exceed capacity_cuft")
    if unit["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Storage unit is SEALED")
    # Early bird: created at least 30 days before the break starts_on
    from datetime import datetime, timedelta, timezone
    starts_dt = datetime.combine(bp["_starts_on"], datetime.min.time(), tzinfo=timezone.utc)
    early_bird = now() <= starts_dt - timedelta(days=30)
    fee = storage_fee(volume, weeks, early_bird)
    r = new_common()
    r.update({
        "storage_unit_id": unit_id, "student_id": student["id"],
        "break_period_id": break_period_id, "volume_cuft": volume, "weeks": weeks,
        "items_description": items_description, "early_bird": early_bird,
        "fee_cents": fee, "status": "RESERVED",
    })
    STORE["storage_reservations"][r["id"]] = r
    return success_object(ser_storage_reservation(r), 201)


@app.get("/reslife/storage-reservations")
def storage_reservation_list():
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "DormParent", "FrontDesk", "Student"])
    items = list(STORE["storage_reservations"].values())
    if actor.role == "Student":
        items = [r for r in items if r["student_id"] == actor.user_id]
    unit_id = request.args.get("storage_unit_id")
    student_id = request.args.get("student_id")
    break_period_id = request.args.get("break_period_id")
    status = request.args.get("status")
    if unit_id is not None:
        items = [r for r in items if r["storage_unit_id"] == unit_id]
    if student_id is not None:
        items = [r for r in items if r["student_id"] == student_id]
    if break_period_id is not None:
        items = [r for r in items if r["break_period_id"] == break_period_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items, ser_storage_reservation)


@app.get("/reslife/storage-reservations/<reservation_id>")
def storage_reservation_get(reservation_id):
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "DormParent", "FrontDesk", "Student"])
    r = get_or_404("storage_reservations", reservation_id, "storage reservation")
    if actor.role == "Student" and r["student_id"] != actor.user_id:
        raise err("ERR_FORBIDDEN", "Students may only read their own reservations")
    return success_object(ser_storage_reservation(r))


@app.post("/reslife/storage-reservations/<reservation_id>/check-in")
def storage_reservation_check_in(reservation_id):
    actor = authenticate()
    require_roles(actor, ["DormParent", "FrontDesk"])
    staff_identity(actor, "DORM_PARENT" if actor.role == "DormParent" else "FRONT_DESK")
    r = get_or_404("storage_reservations", reservation_id, "storage reservation")
    if r["status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "Check-in requires status RESERVED")
    bp = STORE["break_periods"].get(r["break_period_id"])
    if bp is None or bp["status"] != "ACTIVE":
        raise err("ERR_BREAK_NOT_ACTIVE", "Break period is not ACTIVE")
    r["status"] = "CHECKED_IN"
    bump(r)
    return success_object(ser_storage_reservation(r))


@app.post("/reslife/storage-reservations/<reservation_id>/retrieve")
def storage_reservation_retrieve(reservation_id):
    actor = authenticate()
    require_roles(actor, ["DormParent", "FrontDesk"])
    staff_identity(actor, "DORM_PARENT" if actor.role == "DormParent" else "FRONT_DESK")
    r = get_or_404("storage_reservations", reservation_id, "storage reservation")
    if r["status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", "Retrieve requires status CHECKED_IN")
    r["status"] = "RETRIEVED"
    bump(r)
    return success_object(ser_storage_reservation(r))


@app.post("/reslife/storage-reservations/<reservation_id>/cancel")
def storage_reservation_cancel(reservation_id):
    actor = authenticate()
    require_roles(actor, ["Student"])
    r = get_or_404("storage_reservations", reservation_id, "storage reservation")
    if r["student_id"] != actor.user_id:
        raise err("ERR_FORBIDDEN", "Students may cancel only their own reservations")
    if r["status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "Only a RESERVED reservation can be cancelled")
    r["status"] = "CANCELLED"
    bump(r)
    return success_object(ser_storage_reservation(r))
