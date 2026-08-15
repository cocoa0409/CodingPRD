"""Routes: logical clock, terms, dorms, rooms, parents, guardians, staff,
students, and dorm assignments."""

from flask import request

from server import app
from db import STORE, now, fmt_ts, set_clock, parse_dt, parse_time_hhmm, bump
from errors import err
from helpers import (
    authenticate, require_roles, get_body, get_or_404, check_fk,
    req_string, opt_string, req_int, opt_int, req_bool, opt_bool,
    req_enum, req_date, success_object, list_response,
)
from services import (
    new_common, active_term, recompute_room_status, end_assignment,
    supersede_assignment, term_close_cascade, withdraw_cascade,
    compatibility_score, clear_roommate_link, run_sweeps,
    ser_term, ser_dorm, ser_room, ser_parent, ser_guardian, ser_staff,
    ser_student, ser_assignment, guardian_wards_assigned,
)

ADMIN = ["SchoolAdmin"]
STAFF_READ = ["SchoolAdmin", "DormParent", "Nurse", "Dean", "FrontDesk"]

GENDER_POLICIES = {"MALE_ONLY", "FEMALE_ONLY", "ANY"}
STAFF_ROLES = {"DORM_PARENT", "NURSE", "DEAN", "FRONT_DESK"}
ENROLLMENT_STATUSES = {"ENROLLED", "ON_LEAVE", "WITHDRAWN", "GRADUATED"}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@app.post("/reslife/_clock/set_current_utc")
def clock_set():
    actor = authenticate()
    require_roles(actor, ADMIN)
    body = get_body()
    raw = body.get("to_iso8601")
    if raw is None:
        raise err("ERR_MISSING_REQUIRED_FIELD", "Missing required field: to_iso8601")
    dt = parse_dt(raw)
    if dt is None:
        raise err("ERR_MISSING_REQUIRED_FIELD",
                  "Field to_iso8601 must be an ISO 8601 datetime")
    set_clock(dt)
    run_sweeps()
    return success_object({"current_utc": fmt_ts(now())})


# ---------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------

@app.post("/reslife/terms")
def term_create():
    actor = authenticate()
    require_roles(actor, ADMIN)
    body = get_body()
    name = req_string(body, "name")
    starts_raw, starts = req_date(body, "starts_on")
    ends_raw, ends = req_date(body, "ends_on")
    if ends <= starts:
        raise err("ERR_INVALID_FIELD_VALUE", "ends_on must be strictly after starts_on")
    t = new_common()
    t.update({"name": name, "starts_on": starts_raw, "ends_on": ends_raw,
              "_starts_on": starts, "_ends_on": ends, "status": "UPCOMING"})
    STORE["terms"][t["id"]] = t
    return success_object(ser_term(t), 201)


@app.get("/reslife/terms")
def term_list():
    actor = authenticate()
    require_roles(actor, STAFF_READ)
    items = list(STORE["terms"].values())
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return list_response(items, ser_term)


@app.get("/reslife/terms/<term_id>")
def term_get(term_id):
    actor = authenticate()
    require_roles(actor, STAFF_READ)
    return success_object(ser_term(get_or_404("terms", term_id, "term")))


@app.post("/reslife/terms/<term_id>/activate")
def term_activate(term_id):
    actor = authenticate()
    require_roles(actor, ADMIN)
    t = get_or_404("terms", term_id, "term")
    if t["status"] != "UPCOMING":
        raise err("ERR_INVALID_STATE", "Only an UPCOMING term can be activated")
    if active_term() is not None:
        raise err("ERR_ACTIVE_TERM_EXISTS", "Another term is already ACTIVE")
    t["status"] = "ACTIVE"
    bump(t)
    return success_object(ser_term(t))


@app.post("/reslife/terms/<term_id>/close")
def term_close(term_id):
    actor = authenticate()
    require_roles(actor, ADMIN)
    t = get_or_404("terms", term_id, "term")
    if t["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE term can be closed")
    term_close_cascade(t)
    t["status"] = "CLOSED"
    bump(t)
    return success_object(ser_term(t))


# ---------------------------------------------------------------------------
# Dorms
# ---------------------------------------------------------------------------

def _validate_curfew(body, field):
    v = req_string(body, field)
    if parse_time_hhmm(v) is None:
        raise err("ERR_INVALID_FIELD_VALUE", "Field %s must be HH:MM 24h" % field)
    return v


@app.post("/reslife/dorms")
def dorm_create():
    actor = authenticate()
    require_roles(actor, ADMIN)
    body = get_body()
    name = req_string(body, "name")
    gender_policy = req_enum(body, "gender_policy", GENDER_POLICIES)
    curfew_weekday = _validate_curfew(body, "curfew_weekday")
    curfew_weekend = _validate_curfew(body, "curfew_weekend")
    d = new_common()
    d.update({"name": name, "gender_policy": gender_policy,
              "curfew_weekday": curfew_weekday, "curfew_weekend": curfew_weekend,
              "posture": "OPEN"})
    STORE["dorms"][d["id"]] = d
    return success_object(ser_dorm(d), 201)


@app.get("/reslife/dorms")
def dorm_list():
    actor = authenticate()
    require_roles(actor, STAFF_READ + ["Student"])
    items = list(STORE["dorms"].values())
    posture = request.args.get("posture")
    if posture is not None:
        items = [d for d in items if d["posture"] == posture]
    return list_response(items, ser_dorm)


@app.get("/reslife/dorms/<dorm_id>")
def dorm_get(dorm_id):
    actor = authenticate()
    require_roles(actor, STAFF_READ + ["Student"])
    return success_object(ser_dorm(get_or_404("dorms", dorm_id, "dorm")))


@app.post("/reslife/dorms/<dorm_id>/close-for-break")
def dorm_close_for_break(dorm_id):
    actor = authenticate()
    require_roles(actor, ADMIN)
    d = get_or_404("dorms", dorm_id, "dorm")
    if d["posture"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Dorm is not OPEN")
    if not any(bp["status"] == "ACTIVE" for bp in STORE["break_periods"].values()):
        raise err("ERR_INVALID_STATE",
                  "A BreakPeriod with status ACTIVE must exist to close a dorm for break")
    d["posture"] = "CLOSED_FOR_BREAK"
    bump(d)
    return success_object(ser_dorm(d))


@app.post("/reslife/dorms/<dorm_id>/reopen")
def dorm_reopen(dorm_id):
    actor = authenticate()
    require_roles(actor, ADMIN)
    d = get_or_404("dorms", dorm_id, "dorm")
    if d["posture"] != "CLOSED_FOR_BREAK":
        raise err("ERR_INVALID_STATE", "Dorm is not CLOSED_FOR_BREAK")
    d["posture"] = "OPEN"
    bump(d)
    return success_object(ser_dorm(d))


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------

@app.post("/reslife/rooms")
def room_create():
    actor = authenticate()
    require_roles(actor, ADMIN)
    body = get_body()
    check_fk(body, "dorm_id", "dorms")
    dorm_id = req_string(body, "dorm_id")
    room_number = req_string(body, "room_number")
    beds = req_int(body, "beds")
    if beds < 1 or beds > 4:
        raise err("ERR_INVALID_FIELD_VALUE", "beds must be in 1..4")
    r = new_common()
    r.update({"dorm_id": dorm_id, "room_number": room_number, "beds": beds,
              "status": "AVAILABLE"})
    STORE["rooms"][r["id"]] = r
    return success_object(ser_room(r), 201)


@app.get("/reslife/rooms")
def room_list():
    actor = authenticate()
    require_roles(actor, STAFF_READ)
    items = list(STORE["rooms"].values())
    dorm_id = request.args.get("dorm_id")
    status = request.args.get("status")
    if dorm_id is not None:
        items = [r for r in items if r["dorm_id"] == dorm_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items, ser_room)


@app.get("/reslife/rooms/<room_id>")
def room_get(room_id):
    actor = authenticate()
    require_roles(actor, STAFF_READ)
    return success_object(ser_room(get_or_404("rooms", room_id, "room")))


@app.post("/reslife/rooms/<room_id>/block")
def room_block(room_id):
    from services import room_beds_assigned
    actor = authenticate()
    require_roles(actor, ADMIN)
    r = get_or_404("rooms", room_id, "room")
    if room_beds_assigned(r["id"]) > 0:
        raise err("ERR_ROOM_OCCUPIED", "Cannot block a room with current occupants")
    if r["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Only an AVAILABLE room can be blocked")
    r["status"] = "BLOCKED"
    bump(r)
    return success_object(ser_room(r))


@app.post("/reslife/rooms/<room_id>/unblock")
def room_unblock(room_id):
    actor = authenticate()
    require_roles(actor, ADMIN)
    r = get_or_404("rooms", room_id, "room")
    if r["status"] != "BLOCKED":
        raise err("ERR_INVALID_STATE", "Only a BLOCKED room can be unblocked")
    r["status"] = "AVAILABLE"
    bump(r)
    recompute_room_status(r)
    return success_object(ser_room(r))


# ---------------------------------------------------------------------------
# Parents / Guardians / Staff
# ---------------------------------------------------------------------------

@app.post("/reslife/parents")
def parent_create():
    actor = authenticate()
    require_roles(actor, ADMIN)
    body = get_body()
    p = new_common()
    p.update({"full_name": req_string(body, "full_name"),
              "email": req_string(body, "email")})
    STORE["parents"][p["id"]] = p
    return success_object(ser_parent(p), 201)


@app.get("/reslife/parents/<parent_id>")
def parent_get(parent_id):
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "Dean", "DormParent"])
    return success_object(ser_parent(get_or_404("parents", parent_id, "parent")))


@app.post("/reslife/guardians")
def guardian_create():
    actor = authenticate()
    require_roles(actor, ADMIN)
    body = get_body()
    max_wards = opt_int(body, "max_wards", 3)
    if max_wards < 1 or max_wards > 10:
        raise err("ERR_INVALID_FIELD_VALUE", "max_wards must be in 1..10")
    g = new_common()
    g.update({"full_name": req_string(body, "full_name"),
              "email": req_string(body, "email"),
              "city": req_string(body, "city"),
              "max_wards": max_wards, "status": "PENDING"})
    STORE["guardians"][g["id"]] = g
    return success_object(ser_guardian(g), 201)


@app.get("/reslife/guardians")
def guardian_list():
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "Dean", "DormParent"])
    items = list(STORE["guardians"].values())
    status = request.args.get("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    return list_response(items, ser_guardian)


@app.get("/reslife/guardians/<guardian_id>")
def guardian_get(guardian_id):
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "Dean", "DormParent"])
    return success_object(ser_guardian(get_or_404("guardians", guardian_id, "guardian")))


@app.post("/reslife/guardians/<guardian_id>/approve")
def guardian_approve(guardian_id):
    actor = authenticate()
    require_roles(actor, ADMIN)
    g = get_or_404("guardians", guardian_id, "guardian")
    if g["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Only a PENDING guardian can be approved")
    g["status"] = "APPROVED"
    bump(g)
    return success_object(ser_guardian(g))


@app.post("/reslife/guardians/<guardian_id>/suspend")
def guardian_suspend(guardian_id):
    actor = authenticate()
    require_roles(actor, ADMIN)
    g = get_or_404("guardians", guardian_id, "guardian")
    if g["status"] not in ("PENDING", "APPROVED"):
        raise err("ERR_INVALID_STATE", "Guardian cannot be suspended from %s" % g["status"])
    g["status"] = "SUSPENDED"
    bump(g)
    # Auto-deny each ward's still-REQUESTED leaves.
    ward_ids = {s["id"] for s in STORE["students"].values()
                if s.get("guardian_id") == guardian_id}
    for lv in STORE["leave_requests"].values():
        if lv["student_id"] in ward_ids and lv["status"] == "REQUESTED":
            lv["status"] = "DENIED"
            lv["denial_reason"] = "GUARDIAN_SUSPENDED"
            bump(lv)
    return success_object(ser_guardian(g))


@app.post("/reslife/staff")
def staff_create():
    actor = authenticate()
    require_roles(actor, ADMIN)
    body = get_body()
    check_fk(body, "dorm_id", "dorms")
    s = new_common()
    s.update({"full_name": req_string(body, "full_name"),
              "staff_role": req_enum(body, "staff_role", STAFF_ROLES),
              "dorm_id": body.get("dorm_id"),
              "is_active": opt_bool(body, "is_active", True)})
    STORE["staff"][s["id"]] = s
    return success_object(ser_staff(s), 201)


@app.get("/reslife/staff")
def staff_list():
    actor = authenticate()
    require_roles(actor, STAFF_READ)
    items = list(STORE["staff"].values())
    dorm_id = request.args.get("dorm_id")
    staff_role = request.args.get("staff_role")
    is_active = request.args.get("is_active")
    if dorm_id is not None:
        items = [s for s in items if s["dorm_id"] == dorm_id]
    if staff_role is not None:
        items = [s for s in items if s["staff_role"] == staff_role]
    if is_active is not None:
        flag = is_active.lower() in ("true", "1", "yes")
        items = [s for s in items if s["is_active"] == flag]
    return list_response(items, ser_staff)


@app.get("/reslife/staff/<staff_id>")
def staff_get(staff_id):
    actor = authenticate()
    require_roles(actor, STAFF_READ)
    return success_object(ser_staff(get_or_404("staff", staff_id, "staff member")))


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

def _questionnaire(body, field, required=True):
    if required:
        v = req_int(body, field)
    else:
        v = opt_int(body, field, None)
        if v is None:
            return None
    if v < 1 or v > 5:
        raise err("ERR_INVALID_FIELD_VALUE", "Field %s must be in 1..5" % field)
    return v


@app.post("/reslife/students")
def student_create():
    actor = authenticate()
    require_roles(actor, ADMIN)
    body = get_body()
    # Priority 3: body FK resolution
    check_fk(body, "parent_id", "parents")
    check_fk(body, "guardian_id", "guardians")
    # Priority 4: presence / types
    legal_name = req_string(body, "legal_name")
    grade = req_int(body, "grade")
    gender = req_string(body, "gender")
    is_international = req_bool(body, "is_international")
    parent_id = req_string(body, "parent_id")
    guardian_id = body.get("guardian_id")
    sleep_schedule = _questionnaire(body, "sleep_schedule")
    cleanliness = _questionnaire(body, "cleanliness")
    noise_tolerance = _questionnaire(body, "noise_tolerance")
    guests_comfort = _questionnaire(body, "guests_comfort")
    # Priority 5: domains
    if grade < 9 or grade > 12:
        raise err("ERR_INVALID_FIELD_VALUE", "grade must be in 9..12")
    if gender not in ("MALE", "FEMALE"):
        raise err("ERR_INVALID_FIELD_VALUE", "gender must be MALE or FEMALE")
    if not is_international and guardian_id is not None:
        raise err("ERR_INVALID_FIELD_VALUE",
                  "guardian_id must be null for a domestic student")
    # Business: guardian required / approved / capacity
    guardian = None
    if is_international:
        if guardian_id is None:
            raise err("ERR_GUARDIAN_REQUIRED",
                      "International student requires a guardian_id")
        guardian = STORE["guardians"][guardian_id]
        if guardian["status"] != "APPROVED":
            raise err("ERR_GUARDIAN_NOT_APPROVED",
                      "Guardian status must be APPROVED")
        if guardian_wards_assigned(guardian_id) >= guardian["max_wards"]:
            raise err("ERR_GUARDIAN_AT_CAPACITY",
                      "Guardian has reached max_wards")
    s = new_common()
    s.update({
        "legal_name": legal_name, "grade": grade, "gender": gender,
        "is_international": is_international, "parent_id": parent_id,
        "guardian_id": guardian_id if is_international else None,
        "sleep_schedule": sleep_schedule, "cleanliness": cleanliness,
        "noise_tolerance": noise_tolerance, "guests_comfort": guests_comfort,
        "enrollment_status": "ENROLLED", "discipline_standing": "GOOD",
        "demerit_points": 0,
    })
    STORE["students"][s["id"]] = s
    return success_object(ser_student(s), 201)


@app.get("/reslife/students")
def student_list():
    actor = authenticate()
    require_roles(actor, STAFF_READ)
    items = list(STORE["students"].values())
    parent_id = request.args.get("parent_id")
    guardian_id = request.args.get("guardian_id")
    grade = request.args.get("grade")
    standing = request.args.get("discipline_standing")
    enrollment = request.args.get("enrollment_status")
    if parent_id is not None:
        items = [s for s in items if s["parent_id"] == parent_id]
    if guardian_id is not None:
        items = [s for s in items if s.get("guardian_id") == guardian_id]
    if grade is not None:
        try:
            g = int(grade)
            items = [s for s in items if s["grade"] == g]
        except ValueError:
            items = []
    if standing is not None:
        items = [s for s in items if s["discipline_standing"] == standing]
    if enrollment is not None:
        items = [s for s in items if s["enrollment_status"] == enrollment]
    return list_response(items, ser_student)


@app.get("/reslife/students/<student_id>")
def student_get(student_id):
    actor = authenticate()
    require_roles(actor, STAFF_READ + ["Student", "Parent", "Guardian"])
    s = get_or_404("students", student_id, "student")
    if actor.role == "Student" and actor.user_id != student_id:
        raise err("ERR_FORBIDDEN", "Students may only read their own record")
    if actor.role == "Parent" and s["parent_id"] != actor.user_id:
        raise err("ERR_FORBIDDEN", "Parents may only read their own children")
    if actor.role == "Guardian" and s.get("guardian_id") != actor.user_id:
        raise err("ERR_FORBIDDEN", "Guardians may only read their own wards")
    return success_object(ser_student(s))


@app.patch("/reslife/students/<student_id>")
def student_patch(student_id):
    actor = authenticate()
    require_roles(actor, ADMIN)
    s = get_or_404("students", student_id, "student")
    body = get_body()
    changed = False
    questionnaire_changed = False
    if "grade" in body:
        g = req_int(body, "grade")
        if g < 9 or g > 12:
            raise err("ERR_INVALID_FIELD_VALUE", "grade must be in 9..12")
        if g != s["grade"]:
            s["grade"] = g
            changed = True
    for f in ("sleep_schedule", "cleanliness", "noise_tolerance", "guests_comfort"):
        if f in body:
            v = _questionnaire(body, f, required=False)
            if v is not None and v != s[f]:
                s[f] = v
                changed = True
                questionnaire_changed = True
    if questionnaire_changed:
        # Recompute compatibility on a linked assignment pair (derived field:
        # recomputation does not bump assignment versions).
        for a in STORE["dorm_assignments"].values():
            if a["student_id"] == s["id"] and a.get("roommate_assignment_id"):
                partner = STORE["dorm_assignments"].get(a["roommate_assignment_id"])
                if partner is not None:
                    other = STORE["students"].get(partner["student_id"])
                    if other is not None:
                        score = compatibility_score(s, other)
                        a["compatibility_score"] = score
                        partner["compatibility_score"] = score
                break
    if changed:
        bump(s)
    return success_object(ser_student(s))


@app.post("/reslife/students/<student_id>/enrollment")
def student_enrollment(student_id):
    actor = authenticate()
    require_roles(actor, ADMIN)
    s = get_or_404("students", student_id, "student")
    body = get_body()
    to_status = req_enum(body, "to_status", ENROLLMENT_STATUSES)
    cur = s["enrollment_status"]
    allowed = {
        ("ENROLLED", "ON_LEAVE"), ("ON_LEAVE", "ENROLLED"),
        ("ENROLLED", "WITHDRAWN"), ("ON_LEAVE", "WITHDRAWN"),
        ("ENROLLED", "GRADUATED"),
    }
    if (cur, to_status) not in allowed:
        raise err("ERR_INVALID_STATE",
                  "Enrollment transition %s -> %s is not allowed" % (cur, to_status))
    if to_status == "GRADUATED":
        term = active_term()
        if term is not None:
            for a in STORE["dorm_assignments"].values():
                if (a["student_id"] == s["id"] and a["term_id"] == term["id"]
                        and a["status"] == "CONFIRMED"):
                    raise err("ERR_ACTIVE_ASSIGNMENT_EXISTS",
                              "Student holds a CONFIRMED assignment in the ACTIVE term")
    if to_status == "WITHDRAWN":
        withdraw_cascade(s)
    s["enrollment_status"] = to_status
    bump(s)
    return success_object(ser_student(s))


# ---------------------------------------------------------------------------
# Dorm assignments
# ---------------------------------------------------------------------------

def _validate_roommate_link(assignment_fields, target):
    """Shared checks for create-time and link-roommate mutual linking."""
    if target["student_id"] == assignment_fields["student_id"]:
        raise err("ERR_SELF_ROOMMATE",
                  "Roommate link target belongs to the same student")
    if (target["room_id"] != assignment_fields["room_id"]
            or target["term_id"] != assignment_fields["term_id"]
            or target["status"] not in ("PROPOSED", "CONFIRMED")):
        raise err("ERR_ROOMMATE_NOT_IN_ROOM",
                  "Roommate link target must be PROPOSED/CONFIRMED in the same room and term")


@app.post("/reslife/dorm-assignments")
def assignment_create():
    actor = authenticate()
    require_roles(actor, ADMIN)
    body = get_body()
    # Priority 3: body FKs
    check_fk(body, "student_id", "students")
    check_fk(body, "room_id", "rooms")
    check_fk(body, "term_id", "terms")
    check_fk(body, "roommate_assignment_id", "dorm_assignments")
    # Priority 4: presence/types
    student_id = req_string(body, "student_id")
    room_id = req_string(body, "room_id")
    term_id = req_string(body, "term_id")
    expected = req_int(body, "expected_student_version")
    student = STORE["students"][student_id]
    # OCC (before state/business rules)
    if expected != student["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_student_version does not match the student's current version")
    # Priority 7: assignment's term must be ACTIVE
    term = STORE["terms"][term_id]
    if term["status"] != "ACTIVE":
        raise err("ERR_TERM_NOT_ACTIVE", "The assignment's term is not ACTIVE")
    # Roommate checks
    roommate_id = body.get("roommate_assignment_id")
    if roommate_id is not None:
        _validate_roommate_link(
            {"student_id": student_id, "room_id": room_id, "term_id": term_id},
            STORE["dorm_assignments"][roommate_id])
    # Supersede existing PROPOSED assignments of this student in this term
    for a in list(STORE["dorm_assignments"].values()):
        if (a["student_id"] == student_id and a["term_id"] == term_id
                and a["status"] == "PROPOSED"):
            supersede_assignment(a)
    a = new_common()
    a.update({
        "student_id": student_id, "room_id": room_id, "term_id": term_id,
        "roommate_assignment_id": None, "status": "PROPOSED",
        "compatibility_score": None, "check_in_at": None, "check_out_at": None,
    })
    STORE["dorm_assignments"][a["id"]] = a
    if roommate_id is not None:
        target = STORE["dorm_assignments"][roommate_id]
        clear_roommate_link(target)
        other = STORE["students"][target["student_id"]]
        score = compatibility_score(student, other)
        a["roommate_assignment_id"] = target["id"]
        a["compatibility_score"] = score
        target["roommate_assignment_id"] = a["id"]
        target["compatibility_score"] = score
        bump(target)
    bump(student)
    return success_object(ser_assignment(a), 201)


@app.get("/reslife/dorm-assignments")
def assignment_list():
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "DormParent", "Dean"])
    items = list(STORE["dorm_assignments"].values())
    for f in ("student_id", "room_id", "term_id", "status", "roommate_assignment_id"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    return list_response(items, ser_assignment)


@app.get("/reslife/dorm-assignments/<assignment_id>")
def assignment_get(assignment_id):
    actor = authenticate()
    require_roles(actor, ["SchoolAdmin", "DormParent", "Dean", "Student"])
    a = get_or_404("dorm_assignments", assignment_id, "dorm assignment")
    if actor.role == "Student" and a["student_id"] != actor.user_id:
        raise err("ERR_FORBIDDEN", "Students may only read their own assignments")
    return success_object(ser_assignment(a))


@app.post("/reslife/dorm-assignments/<assignment_id>/confirm")
def assignment_confirm(assignment_id):
    from services import room_beds_assigned
    actor = authenticate()
    require_roles(actor, ADMIN)
    a = get_or_404("dorm_assignments", assignment_id, "dorm assignment")
    if a["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Only a PROPOSED assignment can be confirmed")
    term = STORE["terms"].get(a["term_id"])
    if term is None or term["status"] != "ACTIVE":
        raise err("ERR_TERM_NOT_ACTIVE", "The assignment's term is not ACTIVE")
    student = STORE["students"][a["student_id"]]
    if student["enrollment_status"] != "ENROLLED":
        raise err("ERR_STUDENT_NOT_ENROLLED", "Student must be ENROLLED to confirm")
    room = STORE["rooms"][a["room_id"]]
    dorm = STORE["dorms"][room["dorm_id"]]
    if dorm["posture"] != "OPEN":
        raise err("ERR_DORM_CLOSED", "Dorm is CLOSED_FOR_BREAK")
    if room["status"] == "BLOCKED":
        raise err("ERR_INVALID_STATE", "Room is BLOCKED")
    if room["beds"] - room_beds_assigned(room["id"]) < 1:
        raise err("ERR_ROOM_FULL", "Room has no beds available")
    policy = dorm["gender_policy"]
    if not (policy == "ANY"
            or (policy == "MALE_ONLY" and student["gender"] == "MALE")
            or (policy == "FEMALE_ONLY" and student["gender"] == "FEMALE")):
        raise err("ERR_DORM_GENDER_MISMATCH",
                  "Dorm gender_policy does not accept the student's gender")
    if student.get("is_international"):
        guardian = STORE["guardians"].get(student.get("guardian_id"))
        if guardian is None or guardian["status"] != "APPROVED":
            raise err("ERR_GUARDIAN_NOT_APPROVED",
                      "International student's guardian must be APPROVED")
    for other in STORE["dorm_assignments"].values():
        if (other["id"] != a["id"] and other["student_id"] == student["id"]
                and other["term_id"] == term["id"] and other["status"] == "CONFIRMED"):
            raise err("ERR_ACTIVE_ASSIGNMENT_EXISTS",
                      "Student already holds a CONFIRMED assignment in this term")
    a["status"] = "CONFIRMED"
    a["check_in_at"] = now()
    bump(a)
    recompute_room_status(room)
    return success_object(ser_assignment(a))


@app.post("/reslife/dorm-assignments/<assignment_id>/end")
def assignment_end(assignment_id):
    actor = authenticate()
    require_roles(actor, ADMIN)
    a = get_or_404("dorm_assignments", assignment_id, "dorm assignment")
    if a["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Only a CONFIRMED assignment can be ended")
    end_assignment(a)
    return success_object(ser_assignment(a))


@app.post("/reslife/dorm-assignments/<assignment_id>/link-roommate")
def assignment_link_roommate(assignment_id):
    actor = authenticate()
    require_roles(actor, ADMIN)
    a = get_or_404("dorm_assignments", assignment_id, "dorm assignment")
    body = get_body()
    check_fk(body, "roommate_assignment_id", "dorm_assignments")
    roommate_id = req_string(body, "roommate_assignment_id")
    target = STORE["dorm_assignments"][roommate_id]
    if target["id"] == a["id"] or target["student_id"] == a["student_id"]:
        raise err("ERR_SELF_ROOMMATE",
                  "Roommate link target belongs to the same student")
    _validate_roommate_link(a, target)
    # Dissolve any pre-existing links on both sides.
    clear_roommate_link(a)
    clear_roommate_link(target)
    sa = STORE["students"][a["student_id"]]
    sb = STORE["students"][target["student_id"]]
    score = compatibility_score(sa, sb)
    a["roommate_assignment_id"] = target["id"]
    a["compatibility_score"] = score
    target["roommate_assignment_id"] = a["id"]
    target["compatibility_score"] = score
    bump(a)
    bump(target)
    return success_object(ser_assignment(a))
