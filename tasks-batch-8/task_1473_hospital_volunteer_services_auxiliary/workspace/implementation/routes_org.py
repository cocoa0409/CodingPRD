"""Routes: departments, volunteer roles, department requests, placements, training records."""
from flask import request

from core import (
    db, now, today, auth, require_role, body, ok_object, page_list, get_or_404,
    raise_err, touch, new_rec, req_str, opt_str, req_int, opt_bool, req_enum,
    ERR_INVALID_REQUEST, ERR_NOT_RESOURCE_OWNER, ERR_VOLUNTEER_INVALID_STATE,
    ERR_POSTURE_FROZEN, ERR_REQUEST_INVALID_STATE, ERR_REQUEST_NOT_OPEN,
    ERR_PLACEMENT_INVALID_STATE, ERR_ROLE_MIN_AGE_NOT_MET,
    ERR_DEPARTMENT_JUNIOR_RESTRICTED, ERR_DUPLICATE_PLACEMENT,
    ERR_PLACEMENT_LIMIT_EXCEEDED, ERR_COUNTER_ROUND_EXHAUSTED,
    ERR_TRAINING_RECORD_INVALID_STATE,
)
from core import add_months
from domain import (
    compliance_posture, is_junior_at, parse_dob, age_on, rescind_placement,
    ser_department, ser_role, ser_request, ser_placement, ser_training,
)

CATEGORIES = ["PATIENT_FACING", "GIFT_SHOP", "CLERICAL", "FUNDRAISING", "COMMUNITY"]
REQUEST_STATUS = ["DRAFT", "OPEN", "FILLED", "CLOSED", "CANCELLED"]
PLACEMENT_STATUS = ["OFFERED", "COUNTERED", "ACCEPTED", "DECLINED", "RESCINDED"]
TRAINING_STATUS = ["PENDING", "VALID", "EXPIRED"]
ALL6 = ["VolunteerServicesDirector", "VolunteerCoordinator", "Screener",
        "DepartmentHead", "AuxiliaryTreasurer", "Volunteer"]


def _owns_department(uid, dept):
    return dept["head_user_id"] == uid


def _request_dept(req):
    return db["departments"].get(req["department_id"])


def _check_age_and_junior(vol, role, dept, on_date):
    """Tier-9 minor protection gates evaluated at the given date."""
    dob = parse_dob(vol)
    if age_on(dob, on_date) < role["minimum_age"]:
        raise_err(ERR_ROLE_MIN_AGE_NOT_MET,
                  "Volunteer does not meet the role minimum age")
    if age_on(dob, on_date) < 18 and not dept["junior_allowed"]:
        raise_err(ERR_DEPARTMENT_JUNIOR_RESTRICTED,
                  "Department does not allow junior volunteers")


def register(app):

    # ------------------------------------------------------------ departments
    @app.route("/auxiliary/departments", methods=["POST"])
    def create_department():
        uid, role = auth()
        data = body()
        name = req_str(data, "name")
        head_user_id = req_str(data, "head_user_id")
        junior_allowed = opt_bool(data, "junior_allowed", True)
        require_role(role, ["VolunteerServicesDirector"])
        rec = new_rec()
        rec.update({"name": name, "head_user_id": head_user_id,
                    "junior_allowed": junior_allowed})
        db["departments"][rec["id"]] = rec
        return ok_object(ser_department(rec), 201)

    @app.route("/auxiliary/departments", methods=["GET"])
    def list_departments():
        uid, role = auth()
        require_role(role, ALL6)
        return page_list(db["departments"].values(), ser_department)

    @app.route("/auxiliary/departments/<rid>", methods=["GET"])
    def get_department(rid):
        uid, role = auth()
        require_role(role, ALL6)
        return ok_object(ser_department(get_or_404("departments", rid, "Department")))

    # ------------------------------------------------------------------ roles
    @app.route("/auxiliary/volunteer-roles", methods=["POST"])
    def create_role():
        uid, role = auth()
        data = body()
        name = req_str(data, "name")
        category = req_enum(data, "category", CATEGORIES)
        minimum_age = 16
        if "minimum_age" in data and data["minimum_age"] is not None:
            minimum_age = req_int(data, "minimum_age", minimum=0)
        can_supervise = opt_bool(data, "can_supervise_juniors", False)
        codes = data.get("required_training_codes", None)
        if codes is None:
            codes = []
        if not isinstance(codes, list) or any(not isinstance(c, str) for c in codes):
            raise_err(ERR_INVALID_REQUEST,
                      "required_training_codes must be an array of strings")
        require_role(role, ["VolunteerServicesDirector"])
        rec = new_rec()
        rec.update({"name": name, "category": category, "minimum_age": minimum_age,
                    "can_supervise_juniors": can_supervise,
                    "required_training_codes": list(codes)})
        db["roles"][rec["id"]] = rec
        return ok_object(ser_role(rec), 201)

    @app.route("/auxiliary/volunteer-roles", methods=["GET"])
    def list_roles():
        uid, role = auth()
        require_role(role, ALL6)
        return page_list(db["roles"].values(), ser_role)

    @app.route("/auxiliary/volunteer-roles/<rid>", methods=["GET"])
    def get_role(rid):
        uid, role = auth()
        require_role(role, ALL6)
        return ok_object(ser_role(get_or_404("roles", rid, "VolunteerRole")))

    # -------------------------------------------------------- department requests
    @app.route("/auxiliary/department-requests", methods=["POST"])
    def create_request():
        uid, role = auth()
        data = body()
        department_id = req_str(data, "department_id")
        role_id = req_str(data, "role_id")
        slots_needed = req_int(data, "slots_needed", minimum=1)
        notes = opt_str(data, "notes")
        require_role(role, ["DepartmentHead"])
        dept = get_or_404("departments", department_id, "Department")
        get_or_404("roles", role_id, "VolunteerRole")
        if not _owns_department(uid, dept):
            raise_err(ERR_NOT_RESOURCE_OWNER,
                      "DepartmentHead may only create requests for their own department")
        rec = new_rec()
        rec.update({"department_id": department_id, "role_id": role_id,
                    "slots_needed": slots_needed, "slots_filled": 0,
                    "notes": notes, "status": "DRAFT", "filled_at": None})
        db["requests"][rec["id"]] = rec
        return ok_object(ser_request(rec), 201)

    @app.route("/auxiliary/department-requests", methods=["GET"])
    def list_requests():
        uid, role = auth()
        require_role(role, ["VolunteerServicesDirector", "VolunteerCoordinator",
                            "DepartmentHead"])
        status = request.args.get("status")
        if status is not None and status not in REQUEST_STATUS:
            raise_err(ERR_INVALID_REQUEST, "Invalid status filter")
        return page_list(db["requests"].values(), ser_request,
                         filters={"department_id": request.args.get("department_id"),
                                  "role_id": request.args.get("role_id"),
                                  "status": status})

    @app.route("/auxiliary/department-requests/<rid>", methods=["GET"])
    def get_request(rid):
        uid, role = auth()
        require_role(role, ["VolunteerServicesDirector", "VolunteerCoordinator",
                            "DepartmentHead"])
        return ok_object(ser_request(get_or_404("requests", rid, "DepartmentRequest")))

    def _load_request_for_head(rid, uid, role, allow_director=False):
        req = get_or_404("requests", rid, "DepartmentRequest")
        if role == "DepartmentHead":
            dept = _request_dept(req)
            if dept is None or not _owns_department(uid, dept):
                raise_err(ERR_NOT_RESOURCE_OWNER,
                          "DepartmentHead may only manage their own department's requests")
        return req

    @app.route("/auxiliary/department-requests/<rid>/open", methods=["POST"])
    def open_request(rid):
        uid, role = auth()
        body()
        require_role(role, ["DepartmentHead"])
        req = _load_request_for_head(rid, uid, role)
        if req["status"] != "DRAFT":
            raise_err(ERR_REQUEST_INVALID_STATE, "Request is not DRAFT")
        req["status"] = "OPEN"
        touch(req)
        return ok_object(ser_request(req))

    @app.route("/auxiliary/department-requests/<rid>/close", methods=["POST"])
    def close_request(rid):
        uid, role = auth()
        body()
        require_role(role, ["DepartmentHead"])
        req = _load_request_for_head(rid, uid, role)
        if req["status"] not in ("OPEN", "FILLED"):
            raise_err(ERR_REQUEST_INVALID_STATE, "Request is not OPEN or FILLED")
        for p in sorted(db["placements"].values(), key=lambda x: x["_seq"]):
            if p["request_id"] == req["id"] and p["status"] in ("OFFERED", "COUNTERED"):
                rescind_placement(p)
        req["status"] = "CLOSED"
        touch(req)
        return ok_object(ser_request(req))

    @app.route("/auxiliary/department-requests/<rid>/cancel", methods=["POST"])
    def cancel_request(rid):
        uid, role = auth()
        body()
        require_role(role, ["DepartmentHead", "VolunteerServicesDirector"])
        req = _load_request_for_head(rid, uid, role)
        if req["status"] not in ("OPEN", "FILLED"):
            raise_err(ERR_REQUEST_INVALID_STATE, "Request is not OPEN or FILLED")
        for p in sorted(db["placements"].values(), key=lambda x: x["_seq"]):
            if p["request_id"] == req["id"] \
                    and p["status"] in ("OFFERED", "COUNTERED", "ACCEPTED"):
                rescind_placement(p, via_request_cancel=True)
        req["status"] = "CANCELLED"
        touch(req)
        return ok_object(ser_request(req))

    # -------------------------------------------------------------- placements
    @app.route("/auxiliary/placements", methods=["POST"])
    def create_placement():
        uid, role = auth()
        data = body()
        request_id = req_str(data, "request_id")
        volunteer_id = req_str(data, "volunteer_id")
        offer_note = opt_str(data, "offer_note")
        require_role(role, ["VolunteerCoordinator"])
        req = get_or_404("requests", request_id, "DepartmentRequest")
        vol = get_or_404("volunteers", volunteer_id, "Volunteer")
        # tier 8: volunteer state, posture, request open
        if vol["service_status"] not in ("ONBOARDING", "ACTIVE"):
            raise_err(ERR_VOLUNTEER_INVALID_STATE,
                      "Volunteer must be ONBOARDING or ACTIVE")
        if compliance_posture(vol) == "FROZEN":
            raise_err(ERR_POSTURE_FROZEN, "Volunteer compliance posture is FROZEN")
        if req["status"] != "OPEN":
            raise_err(ERR_REQUEST_NOT_OPEN, "Request is not OPEN")
        # tier 9: minor protection at the offer date
        role_rec = db["roles"].get(req["role_id"])
        dept = db["departments"].get(req["department_id"])
        _check_age_and_junior(vol, role_rec, dept, today())
        # tier 10: duplicate live placement
        for p in db["placements"].values():
            if p["volunteer_id"] == volunteer_id and p["request_id"] == request_id \
                    and p["status"] in ("OFFERED", "COUNTERED", "ACCEPTED"):
                raise_err(ERR_DUPLICATE_PLACEMENT,
                          "A live placement already exists for this volunteer and request")
        rec = new_rec()
        rec.update({"request_id": request_id, "volunteer_id": volunteer_id,
                    "offer_note": offer_note, "counter_note": None,
                    "counter_rounds": 0, "status": "OFFERED",
                    "accepted_at": None, "rescinded_at": None})
        db["placements"][rec["id"]] = rec
        return ok_object(ser_placement(rec), 201)

    @app.route("/auxiliary/placements", methods=["GET"])
    def list_placements():
        uid, role = auth()
        require_role(role, ["VolunteerServicesDirector", "VolunteerCoordinator",
                            "DepartmentHead", "Volunteer"])
        status = request.args.get("status")
        if status is not None and status not in PLACEMENT_STATUS:
            raise_err(ERR_INVALID_REQUEST, "Invalid status filter")
        volunteer_id = request.args.get("volunteer_id")
        rows = list(db["placements"].values())
        if role == "Volunteer":
            if volunteer_id is not None and volunteer_id != uid:
                raise_err(ERR_NOT_RESOURCE_OWNER,
                          "Volunteers may only list their own placements")
            rows = [p for p in rows if p["volunteer_id"] == uid]
            volunteer_id = None
        return page_list(rows, ser_placement,
                         filters={"request_id": request.args.get("request_id"),
                                  "volunteer_id": volunteer_id, "status": status})

    @app.route("/auxiliary/placements/<rid>", methods=["GET"])
    def get_placement(rid):
        uid, role = auth()
        require_role(role, ["VolunteerServicesDirector", "VolunteerCoordinator",
                            "DepartmentHead", "Volunteer"])
        rec = get_or_404("placements", rid, "Placement")
        if role == "Volunteer" and rec["volunteer_id"] != uid:
            raise_err(ERR_NOT_RESOURCE_OWNER, "Volunteers may only read their own placements")
        return ok_object(ser_placement(rec))

    def _volunteer_owns(uid, role, rec):
        if role == "Volunteer" and rec["volunteer_id"] != uid:
            raise_err(ERR_NOT_RESOURCE_OWNER,
                      "Volunteers may only act on their own placements")

    @app.route("/auxiliary/placements/<rid>/accept", methods=["POST"])
    def accept_placement(rid):
        uid, role = auth()
        body()
        require_role(role, ["Volunteer", "VolunteerCoordinator"])
        rec = get_or_404("placements", rid, "Placement")
        _volunteer_owns(uid, role, rec)
        if rec["status"] != "OFFERED":
            raise_err(ERR_PLACEMENT_INVALID_STATE, "Placement is not OFFERED")
        vol = db["volunteers"].get(rec["volunteer_id"])
        if vol is None or vol["service_status"] not in ("ONBOARDING", "ACTIVE"):
            raise_err(ERR_VOLUNTEER_INVALID_STATE,
                      "Volunteer must be ONBOARDING or ACTIVE")
        if compliance_posture(vol) == "FROZEN":
            raise_err(ERR_POSTURE_FROZEN, "Volunteer compliance posture is FROZEN")
        req = db["requests"].get(rec["request_id"])
        if req is None or req["status"] != "OPEN":
            raise_err(ERR_REQUEST_NOT_OPEN, "Request is not OPEN")
        # tier 9: minor gates re-evaluated at acceptance
        role_rec = db["roles"].get(req["role_id"])
        dept = db["departments"].get(req["department_id"])
        _check_age_and_junior(vol, role_rec, dept, today())
        # tier 10: fewer than 2 ACCEPTED placements
        accepted = sum(1 for p in db["placements"].values()
                       if p["volunteer_id"] == vol["id"] and p["status"] == "ACCEPTED")
        if accepted >= 2:
            raise_err(ERR_PLACEMENT_LIMIT_EXCEEDED,
                      "Volunteer already holds 2 ACCEPTED placements")
        n = now()
        rec["status"] = "ACCEPTED"
        rec["accepted_at"] = n
        touch(rec)
        req["slots_filled"] += 1
        if req["slots_filled"] == req["slots_needed"]:
            req["status"] = "FILLED"
            req["filled_at"] = n
        touch(req)
        return ok_object(ser_placement(rec))

    @app.route("/auxiliary/placements/<rid>/decline", methods=["POST"])
    def decline_placement(rid):
        uid, role = auth()
        body()
        require_role(role, ["Volunteer", "VolunteerCoordinator"])
        rec = get_or_404("placements", rid, "Placement")
        _volunteer_owns(uid, role, rec)
        if rec["status"] not in ("OFFERED", "COUNTERED"):
            raise_err(ERR_PLACEMENT_INVALID_STATE,
                      "Placement is not OFFERED or COUNTERED")
        rec["status"] = "DECLINED"
        touch(rec)
        return ok_object(ser_placement(rec))

    @app.route("/auxiliary/placements/<rid>/counter", methods=["POST"])
    def counter_placement(rid):
        uid, role = auth()
        data = body()
        note = req_str(data, "counter_note", nonempty=True)
        require_role(role, ["Volunteer"])
        rec = get_or_404("placements", rid, "Placement")
        _volunteer_owns(uid, role, rec)
        if rec["status"] != "OFFERED":
            raise_err(ERR_PLACEMENT_INVALID_STATE, "Placement is not OFFERED")
        if rec["counter_rounds"] >= 2:
            raise_err(ERR_COUNTER_ROUND_EXHAUSTED, "Counter rounds exhausted")
        rec["status"] = "COUNTERED"
        rec["counter_rounds"] += 1
        rec["counter_note"] = note
        touch(rec)
        return ok_object(ser_placement(rec))

    @app.route("/auxiliary/placements/<rid>/reoffer", methods=["POST"])
    def reoffer_placement(rid):
        uid, role = auth()
        data = body()
        offer_note = opt_str(data, "offer_note")
        require_role(role, ["DepartmentHead"])
        rec = get_or_404("placements", rid, "Placement")
        req = db["requests"].get(rec["request_id"])
        if req is not None and role == "DepartmentHead":
            dept = _request_dept(req)
            if dept is None or not _owns_department(uid, dept):
                raise_err(ERR_NOT_RESOURCE_OWNER,
                          "DepartmentHead may only reoffer their own department's placements")
        if rec["status"] != "COUNTERED":
            raise_err(ERR_PLACEMENT_INVALID_STATE, "Placement is not COUNTERED")
        if req is None or req["status"] != "OPEN":
            raise_err(ERR_REQUEST_NOT_OPEN, "Request is not OPEN")
        rec["status"] = "OFFERED"
        if offer_note is not None:
            rec["offer_note"] = offer_note
        touch(rec)
        return ok_object(ser_placement(rec))

    @app.route("/auxiliary/placements/<rid>/rescind", methods=["POST"])
    def rescind_placement_ep(rid):
        uid, role = auth()
        body()
        require_role(role, ["VolunteerCoordinator", "DepartmentHead"])
        rec = get_or_404("placements", rid, "Placement")
        if role == "DepartmentHead":
            req = db["requests"].get(rec["request_id"])
            dept = _request_dept(req) if req else None
            if dept is None or not _owns_department(uid, dept):
                raise_err(ERR_NOT_RESOURCE_OWNER,
                          "DepartmentHead may only rescind their own department's placements")
        if rec["status"] not in ("OFFERED", "COUNTERED", "ACCEPTED"):
            raise_err(ERR_PLACEMENT_INVALID_STATE, "Placement is already terminal")
        rescind_placement(rec)
        return ok_object(ser_placement(rec))

    # --------------------------------------------------------- training records
    @app.route("/auxiliary/training-records", methods=["POST"])
    def create_training():
        uid, role = auth()
        data = body()
        volunteer_id = req_str(data, "volunteer_id")
        training_code = req_str(data, "training_code")
        recurrence = req_enum(data, "recurrence", ["ONE_TIME", "ANNUAL"])
        require_role(role, ["VolunteerCoordinator"])
        get_or_404("volunteers", volunteer_id, "Volunteer")
        rec = new_rec()
        rec.update({"volunteer_id": volunteer_id, "training_code": training_code,
                    "recurrence": recurrence, "status": "PENDING",
                    "completed_at": None, "expires_at": None})
        db["training"][rec["id"]] = rec
        return ok_object(ser_training(rec), 201)

    @app.route("/auxiliary/training-records", methods=["GET"])
    def list_training():
        uid, role = auth()
        require_role(role, ["VolunteerServicesDirector", "VolunteerCoordinator", "Volunteer"])
        status = request.args.get("status")
        if status is not None and status not in TRAINING_STATUS:
            raise_err(ERR_INVALID_REQUEST, "Invalid status filter")
        volunteer_id = request.args.get("volunteer_id")
        rows = list(db["training"].values())
        if role == "Volunteer":
            if volunteer_id is not None and volunteer_id != uid:
                raise_err(ERR_NOT_RESOURCE_OWNER,
                          "Volunteers may only list their own training records")
            rows = [t for t in rows if t["volunteer_id"] == uid]
            volunteer_id = None
        return page_list(rows, ser_training,
                         filters={"volunteer_id": volunteer_id, "status": status})

    @app.route("/auxiliary/training-records/<rid>", methods=["GET"])
    def get_training(rid):
        uid, role = auth()
        require_role(role, ["VolunteerServicesDirector", "VolunteerCoordinator"])
        return ok_object(ser_training(get_or_404("training", rid, "TrainingRecord")))

    @app.route("/auxiliary/training-records/<rid>/complete", methods=["POST"])
    def complete_training(rid):
        uid, role = auth()
        body()
        require_role(role, ["VolunteerCoordinator"])
        rec = get_or_404("training", rid, "TrainingRecord")
        if rec["status"] not in ("PENDING", "EXPIRED"):
            raise_err(ERR_TRAINING_RECORD_INVALID_STATE,
                      "Training record is not PENDING or EXPIRED")
        n = now()
        rec["status"] = "VALID"
        rec["completed_at"] = n
        if rec["recurrence"] == "ANNUAL":
            rec["expires_at"] = add_months(n, 12)
        else:
            rec["expires_at"] = None
        touch(rec)
        return ok_object(ser_training(rec))
