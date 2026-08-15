"""Routes: shifts, shift assignments, hour entries, badges, compliance annual review."""
from datetime import timedelta
from decimal import Decimal

from flask import request

from core import (
    db, now, today, auth, require_role, body, ok_object, page_list, get_or_404,
    raise_err, touch, new_rec, req_str, opt_str, req_int, opt_int, opt_bool,
    req_datetime, opt_datetime, req_enum, req_date, req_version,
    ERR_INVALID_REQUEST, ERR_NOT_RESOURCE_OWNER, ERR_STALE_VERSION,
    ERR_VOLUNTEER_INVALID_STATE, ERR_POSTURE_FROZEN, ERR_POSTURE_NOT_CLEAR,
    ERR_SHIFT_INVALID_STATE, ERR_ASSIGNMENT_INVALID_STATE,
    ERR_HOUR_ENTRY_INVALID_STATE, ERR_BADGE_INVALID_STATE,
    ERR_ROLE_MIN_AGE_NOT_MET, ERR_DEPARTMENT_JUNIOR_RESTRICTED,
    ERR_JUNIOR_WEEKLY_CAP, ERR_SUPERVISION_REQUIRED, ERR_SUPERVISOR_INELIGIBLE,
    ERR_SUPERVISOR_RATIO_EXCEEDED, ERR_TRAINING_REQUIREMENT_UNMET,
    ERR_DUPLICATE_SHIFT_ASSIGNMENT, ERR_SHIFT_TIME_OVERLAP, ERR_SHIFT_AT_CAPACITY,
    ERR_SHIFT_HAS_ASSIGNMENTS, ERR_HOURS_EXCEED_SHIFT, ERR_SIGNUP_WINDOW_CLOSED,
    ERR_CANCEL_WINDOW_CLOSED, ERR_SHIFT_NOT_ENDED, ERR_SERVICE_DATE_OUT_OF_RANGE,
    ERR_ASSIGNMENT_OWNERSHIP_MISMATCH, ERR_NOT_FOUND,
)
from domain import (
    compliance_posture, is_junior_at, parse_dob, age_on, shift_duration_hours,
    shift_duration_minutes, has_overlap, junior_weekly_projected_hours,
    run_waitlist_promotion, cancel_assignment, live_badge, suspend_volunteer,
    total_service_hours, recognition_points, tier_for_points, record_tier_change,
    most_recent_completed_year, service_year_hours,
    ser_shift, ser_assignment, ser_hour_entry, ser_badge,
)
from core import mint_badge_number

SHIFT_STATUS = ["SCHEDULED", "PUBLISHED", "COMPLETED", "CANCELLED"]
ASSIGNMENT_STATUS = ["WAITLISTED", "SIGNED_UP", "CONFIRMED", "COMPLETED", "NO_SHOW",
                     "CANCELLED"]
HOUR_STATUS = ["PENDING", "APPROVED", "REJECTED", "REVERSED"]
BADGE_STATUS = ["PENDING", "ISSUED", "SUSPENDED", "REVOKED"]
CATEGORIES = ["PATIENT_FACING", "GIFT_SHOP", "CLERICAL", "FUNDRAISING", "COMMUNITY"]
SHIFT_READERS = ["VolunteerServicesDirector", "VolunteerCoordinator", "DepartmentHead",
                 "Volunteer"]


def register(app):

    # ----------------------------------------------------------------- shifts
    @app.route("/auxiliary/shifts", methods=["POST"])
    def create_shift():
        uid, role = auth()
        data = body()
        department_id = req_str(data, "department_id")
        role_id = req_str(data, "role_id")
        start_at = req_datetime(data, "start_at")
        end_at = req_datetime(data, "end_at")
        capacity = req_int(data, "capacity", minimum=1)
        allow_waitlist = opt_bool(data, "allow_waitlist", False)
        if not (start_at < end_at):
            raise_err(ERR_INVALID_REQUEST, "start_at must be strictly before end_at")
        require_role(role, ["VolunteerCoordinator"])
        get_or_404("departments", department_id, "Department")
        get_or_404("roles", role_id, "VolunteerRole")
        rec = new_rec()
        rec.update({"department_id": department_id, "role_id": role_id,
                    "start_at": start_at, "end_at": end_at, "capacity": capacity,
                    "allow_waitlist": allow_waitlist, "filled_count": 0,
                    "status": "SCHEDULED"})
        db["shifts"][rec["id"]] = rec
        return ok_object(ser_shift(rec), 201)

    @app.route("/auxiliary/shifts", methods=["GET"])
    def list_shifts():
        uid, role = auth()
        require_role(role, SHIFT_READERS)
        status = request.args.get("status")
        if status is not None and status not in SHIFT_STATUS:
            raise_err(ERR_INVALID_REQUEST, "Invalid status filter")
        return page_list(db["shifts"].values(), ser_shift,
                         filters={"department_id": request.args.get("department_id"),
                                  "role_id": request.args.get("role_id"),
                                  "status": status})

    @app.route("/auxiliary/shifts/<rid>", methods=["GET"])
    def get_shift(rid):
        uid, role = auth()
        require_role(role, SHIFT_READERS)
        return ok_object(ser_shift(get_or_404("shifts", rid, "Shift")))

    @app.route("/auxiliary/shifts/<rid>", methods=["PUT"])
    def update_shift(rid):
        uid, role = auth()
        data = body()
        start_at = opt_datetime(data, "start_at")
        end_at = opt_datetime(data, "end_at")
        capacity = opt_int(data, "capacity", minimum=1)
        expected = req_version(data, "expected_shift_version")
        require_role(role, ["VolunteerCoordinator"])
        rec = get_or_404("shifts", rid, "Shift")
        if expected != rec["version"]:
            raise_err(ERR_STALE_VERSION, "Shift version is stale")
        if rec["status"] not in ("SCHEDULED", "PUBLISHED"):
            raise_err(ERR_SHIFT_INVALID_STATE, "Shift is not SCHEDULED or PUBLISHED")
        live = [a for a in db["assignments"].values()
                if a["shift_id"] == rec["id"]
                and a["status"] in ("WAITLISTED", "SIGNED_UP", "CONFIRMED")]
        if live:
            raise_err(ERR_SHIFT_HAS_ASSIGNMENTS, "Shift has live assignments")
        new_start = start_at if start_at is not None else rec["start_at"]
        new_end = end_at if end_at is not None else rec["end_at"]
        if not (new_start < new_end):
            raise_err(ERR_INVALID_REQUEST, "start_at must be strictly before end_at")
        rec["start_at"] = new_start
        rec["end_at"] = new_end
        if capacity is not None:
            rec["capacity"] = capacity
        touch(rec)
        return ok_object(ser_shift(rec))

    @app.route("/auxiliary/shifts/<rid>/publish", methods=["POST"])
    def publish_shift(rid):
        uid, role = auth()
        body()
        require_role(role, ["VolunteerCoordinator"])
        rec = get_or_404("shifts", rid, "Shift")
        if rec["status"] != "SCHEDULED":
            raise_err(ERR_SHIFT_INVALID_STATE, "Shift is not SCHEDULED")
        rec["status"] = "PUBLISHED"
        touch(rec)
        return ok_object(ser_shift(rec))

    @app.route("/auxiliary/shifts/<rid>/cancel", methods=["POST"])
    def cancel_shift(rid):
        uid, role = auth()
        body()
        require_role(role, ["VolunteerCoordinator"])
        rec = get_or_404("shifts", rid, "Shift")
        if rec["status"] not in ("SCHEDULED", "PUBLISHED"):
            raise_err(ERR_SHIFT_INVALID_STATE, "Shift is not SCHEDULED or PUBLISHED")
        for a in sorted(db["assignments"].values(), key=lambda x: x["_seq"]):
            if a["shift_id"] == rec["id"] \
                    and a["status"] in ("WAITLISTED", "SIGNED_UP", "CONFIRMED"):
                cancel_assignment(a, promote=False)
        rec["status"] = "CANCELLED"
        touch(rec)
        return ok_object(ser_shift(rec))

    @app.route("/auxiliary/shifts/<rid>/complete", methods=["POST"])
    def complete_shift(rid):
        uid, role = auth()
        body()
        require_role(role, ["VolunteerCoordinator"])
        rec = get_or_404("shifts", rid, "Shift")
        if rec["status"] != "PUBLISHED":
            raise_err(ERR_SHIFT_INVALID_STATE, "Shift is not PUBLISHED")
        if now() < rec["end_at"]:
            raise_err(ERR_SHIFT_NOT_ENDED, "Shift has not ended yet")
        for a in sorted(db["assignments"].values(), key=lambda x: x["_seq"]):
            if a["shift_id"] != rec["id"]:
                continue
            if a["status"] == "CONFIRMED":
                has_approved = any(
                    e["shift_assignment_id"] == a["id"] and e["status"] == "APPROVED"
                    for e in db["hours"].values())
                if not has_approved:
                    a["status"] = "NO_SHOW"
                    rec["filled_count"] -= 1
                    touch(a)
            elif a["status"] in ("SIGNED_UP", "WAITLISTED"):
                was_live = a["status"] == "SIGNED_UP"
                a["status"] = "CANCELLED"
                touch(a)
                if was_live:
                    rec["filled_count"] -= 1
        rec["status"] = "COMPLETED"
        touch(rec)
        return ok_object(ser_shift(rec))

    # --------------------------------------------------------- shift assignments
    @app.route("/auxiliary/shift-assignments", methods=["POST"])
    def create_assignment():
        uid, role = auth()
        data = body()
        shift_id = req_str(data, "shift_id")
        volunteer_id = req_str(data, "volunteer_id")
        require_role(role, ["Volunteer", "VolunteerCoordinator"])
        shift = get_or_404("shifts", shift_id, "Shift")
        vol = get_or_404("volunteers", volunteer_id, "Volunteer")
        if role == "Volunteer" and uid != volunteer_id:
            raise_err(ERR_NOT_RESOURCE_OWNER, "Volunteers may only sign themselves up")
        # tier 8: state gates
        if shift["status"] != "PUBLISHED":
            raise_err(ERR_SHIFT_INVALID_STATE, "Shift is not PUBLISHED")
        if vol["service_status"] != "ACTIVE":
            raise_err(ERR_VOLUNTEER_INVALID_STATE, "Volunteer is not ACTIVE")
        if compliance_posture(vol) == "FROZEN":
            raise_err(ERR_POSTURE_FROZEN, "Volunteer compliance posture is FROZEN")
        # tier 9: minor protection at the shift start date
        role_rec = db["roles"].get(shift["role_id"])
        dept = db["departments"].get(shift["department_id"])
        shift_date = shift["start_at"].date()
        dob = parse_dob(vol)
        if age_on(dob, shift_date) < role_rec["minimum_age"]:
            raise_err(ERR_ROLE_MIN_AGE_NOT_MET,
                      "Volunteer does not meet the role minimum age")
        junior = age_on(dob, shift_date) < 18
        if junior and not dept["junior_allowed"]:
            raise_err(ERR_DEPARTMENT_JUNIOR_RESTRICTED,
                      "Department does not allow junior volunteers")
        if junior:
            projected = junior_weekly_projected_hours(vol, shift)
            if projected > Decimal("16.0"):
                raise_err(ERR_JUNIOR_WEEKLY_CAP,
                          "Junior weekly projected hours would exceed 16.0")
        # tier 10: duplicate, overlap, capacity
        for a in db["assignments"].values():
            if a["shift_id"] == shift_id and a["volunteer_id"] == volunteer_id \
                    and a["status"] in ("WAITLISTED", "SIGNED_UP", "CONFIRMED"):
                raise_err(ERR_DUPLICATE_SHIFT_ASSIGNMENT,
                          "A live assignment already exists for this volunteer and shift")
        if has_overlap(volunteer_id, shift):
            raise_err(ERR_SHIFT_TIME_OVERLAP,
                      "Shift overlaps another signed-up or confirmed shift")
        full = shift["filled_count"] >= shift["capacity"]
        if full and not shift["allow_waitlist"]:
            raise_err(ERR_SHIFT_AT_CAPACITY, "Shift is at capacity")
        # tier 11: signup window
        if not (now() < shift["start_at"] - timedelta(hours=24)):
            raise_err(ERR_SIGNUP_WINDOW_CLOSED, "Signup window is closed")
        rec = new_rec()
        if full:
            status = "WAITLISTED"
        else:
            status = "SIGNED_UP"
            shift["filled_count"] += 1
            touch(shift)
        rec.update({"shift_id": shift_id, "volunteer_id": volunteer_id,
                    "status": status, "supervisor_assignment_id": None,
                    "signed_up_at": now(), "confirmed_at": None})
        db["assignments"][rec["id"]] = rec
        return ok_object(ser_assignment(rec), 201)

    @app.route("/auxiliary/shift-assignments", methods=["GET"])
    def list_assignments():
        uid, role = auth()
        require_role(role, SHIFT_READERS)
        status = request.args.get("status")
        if status is not None and status not in ASSIGNMENT_STATUS:
            raise_err(ERR_INVALID_REQUEST, "Invalid status filter")
        volunteer_id = request.args.get("volunteer_id")
        rows = list(db["assignments"].values())
        if role == "Volunteer":
            if volunteer_id is not None and volunteer_id != uid:
                raise_err(ERR_NOT_RESOURCE_OWNER,
                          "Volunteers may only list their own assignments")
            rows = [a for a in rows if a["volunteer_id"] == uid]
            volunteer_id = None
        return page_list(rows, ser_assignment,
                         filters={"shift_id": request.args.get("shift_id"),
                                  "volunteer_id": volunteer_id,
                                  "supervisor_assignment_id":
                                      request.args.get("supervisor_assignment_id"),
                                  "status": status})

    @app.route("/auxiliary/shift-assignments/<rid>", methods=["GET"])
    def get_assignment(rid):
        uid, role = auth()
        require_role(role, SHIFT_READERS)
        rec = get_or_404("assignments", rid, "ShiftAssignment")
        if role == "Volunteer" and rec["volunteer_id"] != uid:
            raise_err(ERR_NOT_RESOURCE_OWNER,
                      "Volunteers may only read their own assignments")
        return ok_object(ser_assignment(rec))

    @app.route("/auxiliary/shift-assignments/<rid>/confirm", methods=["POST"])
    def confirm_assignment(rid):
        uid, role = auth()
        data = body()
        sup_id = opt_str(data, "supervisor_assignment_id")
        require_role(role, ["VolunteerCoordinator"])
        rec = get_or_404("assignments", rid, "ShiftAssignment")
        sup = None
        if sup_id is not None:
            sup = get_or_404("assignments", sup_id, "ShiftAssignment")
        # tier 8
        if rec["status"] != "SIGNED_UP":
            raise_err(ERR_ASSIGNMENT_INVALID_STATE, "Assignment is not SIGNED_UP")
        vol = db["volunteers"].get(rec["volunteer_id"])
        if vol is None or vol["service_status"] != "ACTIVE":
            raise_err(ERR_VOLUNTEER_INVALID_STATE, "Volunteer is not ACTIVE")
        if compliance_posture(vol) != "CLEAR":
            raise_err(ERR_POSTURE_NOT_CLEAR, "Volunteer compliance posture is not CLEAR")
        badge = live_badge(vol)
        if badge is None or badge["status"] != "ISSUED":
            raise_err(ERR_BADGE_INVALID_STATE, "Volunteer has no ISSUED badge")
        # tier 9: trainings then junior supervision
        shift = db["shifts"].get(rec["shift_id"])
        role_rec = db["roles"].get(shift["role_id"]) if shift else None
        for code in (role_rec["required_training_codes"] if role_rec else []):
            ok = any(t["volunteer_id"] == vol["id"] and t["training_code"] == code
                     and t["status"] == "VALID" for t in db["training"].values())
            if not ok:
                raise_err(ERR_TRAINING_REQUIREMENT_UNMET,
                          "Required training %s is not VALID" % code)
        shift_date = shift["start_at"].date()
        if is_junior_at(vol, shift_date):
            if sup_id is None:
                raise_err(ERR_SUPERVISION_REQUIRED,
                          "Junior confirm requires supervisor_assignment_id")
            if sup["shift_id"] != shift["id"] or sup["status"] != "CONFIRMED":
                raise_err(ERR_SUPERVISOR_INELIGIBLE,
                          "Supervisor assignment is not CONFIRMED on the same shift")
            sup_vol = db["volunteers"].get(sup["volunteer_id"])
            if sup_vol is None or age_on(parse_dob(sup_vol), shift_date) < 21:
                raise_err(ERR_SUPERVISOR_INELIGIBLE,
                          "Supervisor must be at least 21 at the shift date")
            if not role_rec["can_supervise_juniors"]:
                raise_err(ERR_SUPERVISOR_INELIGIBLE,
                          "Shift role does not allow supervising juniors")
            juniors = sum(1 for a in db["assignments"].values()
                          if a["supervisor_assignment_id"] == sup["id"]
                          and a["shift_id"] == shift["id"] and a["status"] == "CONFIRMED"
                          and a["id"] != rec["id"])
            if juniors + 1 > 3:
                raise_err(ERR_SUPERVISOR_RATIO_EXCEEDED,
                          "Supervisor would exceed 3 junior supervisees")
        rec["status"] = "CONFIRMED"
        rec["confirmed_at"] = now()
        if sup_id is not None:
            rec["supervisor_assignment_id"] = sup_id
        touch(rec)
        return ok_object(ser_assignment(rec))

    @app.route("/auxiliary/shift-assignments/<rid>/cancel", methods=["POST"])
    def cancel_assignment_ep(rid):
        uid, role = auth()
        body()
        require_role(role, ["Volunteer", "VolunteerCoordinator",
                            "VolunteerServicesDirector"])
        rec = get_or_404("assignments", rid, "ShiftAssignment")
        if role == "Volunteer" and rec["volunteer_id"] != uid:
            raise_err(ERR_NOT_RESOURCE_OWNER,
                      "Volunteers may only cancel their own assignments")
        if rec["status"] not in ("SIGNED_UP", "CONFIRMED", "WAITLISTED"):
            raise_err(ERR_ASSIGNMENT_INVALID_STATE,
                      "Assignment is not in a cancellable state")
        shift = db["shifts"].get(rec["shift_id"])
        if role == "Volunteer":
            if not (now() < shift["start_at"] - timedelta(hours=24)):
                raise_err(ERR_CANCEL_WINDOW_CLOSED, "Cancel window is closed")
        cancel_assignment(rec, promote=True)
        return ok_object(ser_assignment(rec))

    # -------------------------------------------------------------- hour entries
    @app.route("/auxiliary/hour-entries", methods=["POST"])
    def create_hour_entry():
        uid, role = auth()
        data = body()
        volunteer_id = req_str(data, "volunteer_id")
        assignment_id = opt_str(data, "shift_assignment_id")
        service_date = req_date(data, "service_date")
        minutes = req_int(data, "minutes", minimum=1, maximum=960)
        category = req_enum(data, "service_category", CATEGORIES)
        notes = opt_str(data, "notes")
        require_role(role, ["Volunteer", "VolunteerCoordinator"])
        vol = get_or_404("volunteers", volunteer_id, "Volunteer")
        assignment = None
        if assignment_id is not None:
            assignment = get_or_404("assignments", assignment_id, "ShiftAssignment")
        if role == "Volunteer" and uid != volunteer_id:
            raise_err(ERR_NOT_RESOURCE_OWNER, "Volunteers may only log their own hours")
        # tier 8
        if vol["service_status"] not in ("ACTIVE", "SUSPENDED"):
            raise_err(ERR_VOLUNTEER_INVALID_STATE,
                      "Volunteer must be ACTIVE or SUSPENDED")
        # tier 10: minutes vs linked shift duration
        shift = None
        if assignment is not None:
            shift = db["shifts"].get(assignment["shift_id"])
            if shift is not None and minutes > shift_duration_minutes(shift):
                raise_err(ERR_HOURS_EXCEED_SHIFT, "Minutes exceed the shift duration")
        # tier 11: service date range
        if service_date > today() or service_date < vol["joined_at"].date():
            raise_err(ERR_SERVICE_DATE_OUT_OF_RANGE,
                      "service_date is out of range")
        if assignment is not None and shift is not None \
                and service_date != shift["start_at"].date():
            raise_err(ERR_SERVICE_DATE_OUT_OF_RANGE,
                      "service_date must equal the linked shift's calendar date")
        # tier 12: assignment ownership
        if assignment is not None and assignment["volunteer_id"] != volunteer_id:
            raise_err(ERR_ASSIGNMENT_OWNERSHIP_MISMATCH,
                      "Linked assignment belongs to a different volunteer")
        if assignment is not None and shift is not None:
            role_rec = db["roles"].get(shift["role_id"])
            if role_rec is not None:
                category = role_rec["category"]
        rec = new_rec()
        rec.update({"volunteer_id": volunteer_id, "shift_assignment_id": assignment_id,
                    "service_date": service_date, "minutes": minutes,
                    "service_category": category, "notes": notes,
                    "status": "PENDING", "approved_at": None, "decision_reason": None})
        db["hours"][rec["id"]] = rec
        return ok_object(ser_hour_entry(rec), 201)

    @app.route("/auxiliary/hour-entries", methods=["GET"])
    def list_hour_entries():
        uid, role = auth()
        require_role(role, ["VolunteerServicesDirector", "VolunteerCoordinator",
                            "Volunteer"])
        status = request.args.get("status")
        if status is not None and status not in HOUR_STATUS:
            raise_err(ERR_INVALID_REQUEST, "Invalid status filter")
        volunteer_id = request.args.get("volunteer_id")
        rows = list(db["hours"].values())
        if role == "Volunteer":
            if volunteer_id is not None and volunteer_id != uid:
                raise_err(ERR_NOT_RESOURCE_OWNER,
                          "Volunteers may only list their own hour entries")
            rows = [e for e in rows if e["volunteer_id"] == uid]
            volunteer_id = None
        return page_list(rows, ser_hour_entry,
                         filters={"volunteer_id": volunteer_id,
                                  "shift_assignment_id":
                                      request.args.get("shift_assignment_id"),
                                  "status": status})

    @app.route("/auxiliary/hour-entries/<rid>", methods=["GET"])
    def get_hour_entry(rid):
        uid, role = auth()
        require_role(role, ["VolunteerServicesDirector", "VolunteerCoordinator",
                            "Volunteer"])
        rec = get_or_404("hours", rid, "HourEntry")
        if role == "Volunteer" and rec["volunteer_id"] != uid:
            raise_err(ERR_NOT_RESOURCE_OWNER,
                      "Volunteers may only read their own hour entries")
        return ok_object(ser_hour_entry(rec))

    @app.route("/auxiliary/hour-entries/<rid>/approve", methods=["POST"])
    def approve_hour_entry(rid):
        uid, role = auth()
        data = body()
        expected = req_version(data, "expected_volunteer_version")
        require_role(role, ["VolunteerCoordinator"])
        rec = get_or_404("hours", rid, "HourEntry")
        vol = db["volunteers"].get(rec["volunteer_id"])
        if vol is None:
            raise_err(ERR_NOT_FOUND, "Volunteer not found")
        if expected != vol["version"]:
            raise_err(ERR_STALE_VERSION, "Volunteer version is stale")
        if rec["status"] != "PENDING":
            raise_err(ERR_HOUR_ENTRY_INVALID_STATE, "Hour entry is not PENDING")
        before_tier = tier_for_points(recognition_points(vol["id"]))
        rec["status"] = "APPROVED"
        rec["approved_at"] = now()
        touch(rec)
        after_points = recognition_points(vol["id"])
        after_tier = tier_for_points(after_points)
        record_tier_change(vol, before_tier, after_tier, after_points)
        touch(vol)
        if rec["shift_assignment_id"] is not None:
            a = db["assignments"].get(rec["shift_assignment_id"])
            if a is not None and a["status"] == "CONFIRMED":
                a["status"] = "COMPLETED"
                touch(a)
                shift = db["shifts"].get(a["shift_id"])
                if shift is not None:
                    shift["filled_count"] -= 1
                    touch(shift)
        return ok_object(ser_hour_entry(rec))

    @app.route("/auxiliary/hour-entries/<rid>/reject", methods=["POST"])
    def reject_hour_entry(rid):
        uid, role = auth()
        data = body()
        reason = req_str(data, "decision_reason", nonempty=True)
        require_role(role, ["VolunteerCoordinator"])
        rec = get_or_404("hours", rid, "HourEntry")
        if rec["status"] != "PENDING":
            raise_err(ERR_HOUR_ENTRY_INVALID_STATE, "Hour entry is not PENDING")
        rec["status"] = "REJECTED"
        rec["decision_reason"] = reason
        touch(rec)
        return ok_object(ser_hour_entry(rec))

    @app.route("/auxiliary/hour-entries/<rid>/reverse", methods=["POST"])
    def reverse_hour_entry(rid):
        uid, role = auth()
        data = body()
        reason = req_str(data, "decision_reason", nonempty=True)
        require_role(role, ["VolunteerCoordinator"])
        rec = get_or_404("hours", rid, "HourEntry")
        if rec["status"] != "APPROVED":
            raise_err(ERR_HOUR_ENTRY_INVALID_STATE, "Hour entry is not APPROVED")
        vol = db["volunteers"].get(rec["volunteer_id"])
        before_tier = tier_for_points(recognition_points(vol["id"]))
        rec["status"] = "REVERSED"
        rec["decision_reason"] = reason
        touch(rec)
        after_points = recognition_points(vol["id"])
        after_tier = tier_for_points(after_points)
        record_tier_change(vol, before_tier, after_tier, after_points)
        touch(vol)
        return ok_object(ser_hour_entry(rec))

    # ------------------------------------------------------------------- badges
    @app.route("/auxiliary/badges", methods=["GET"])
    def list_badges():
        uid, role = auth()
        require_role(role, ["VolunteerServicesDirector", "VolunteerCoordinator",
                            "Volunteer"])
        status = request.args.get("status")
        if status is not None and status not in BADGE_STATUS:
            raise_err(ERR_INVALID_REQUEST, "Invalid status filter")
        volunteer_id = request.args.get("volunteer_id")
        rows = list(db["badges"].values())
        if role == "Volunteer":
            if volunteer_id is not None and volunteer_id != uid:
                raise_err(ERR_NOT_RESOURCE_OWNER,
                          "Volunteers may only list their own badges")
            rows = [b for b in rows if b["volunteer_id"] == uid]
            volunteer_id = None
        return page_list(rows, ser_badge,
                         filters={"volunteer_id": volunteer_id, "status": status})

    @app.route("/auxiliary/badges/<rid>", methods=["GET"])
    def get_badge(rid):
        uid, role = auth()
        require_role(role, ["VolunteerServicesDirector", "VolunteerCoordinator",
                            "Volunteer"])
        rec = get_or_404("badges", rid, "Badge")
        if role == "Volunteer" and rec["volunteer_id"] != uid:
            raise_err(ERR_NOT_RESOURCE_OWNER, "Volunteers may only read their own badges")
        return ok_object(ser_badge(rec))

    @app.route("/auxiliary/badges/<rid>/revoke", methods=["POST"])
    def revoke_badge(rid):
        uid, role = auth()
        data = body()
        req_str(data, "reason", nonempty=True)
        require_role(role, ["VolunteerCoordinator"])
        rec = get_or_404("badges", rid, "Badge")
        if rec["status"] not in ("PENDING", "ISSUED", "SUSPENDED"):
            raise_err(ERR_BADGE_INVALID_STATE, "Badge is not in a live state")
        rec["status"] = "REVOKED"
        rec["revoked_at"] = now()
        rec["revoke_reason"] = "MANUAL"
        touch(rec)
        return ok_object(ser_badge(rec))

    @app.route("/auxiliary/badges/<rid>/replace", methods=["POST"])
    def replace_badge(rid):
        uid, role = auth()
        data = body()
        req_str(data, "reason", nonempty=True)
        require_role(role, ["VolunteerCoordinator"])
        rec = get_or_404("badges", rid, "Badge")
        if rec["status"] not in ("ISSUED", "SUSPENDED"):
            raise_err(ERR_BADGE_INVALID_STATE, "Badge is not ISSUED or SUSPENDED")
        vol = db["volunteers"].get(rec["volunteer_id"])
        if vol is None or vol["service_status"] != "ACTIVE":
            raise_err(ERR_VOLUNTEER_INVALID_STATE, "Volunteer is not ACTIVE")
        n = now()
        rec["status"] = "REVOKED"
        rec["revoked_at"] = n
        rec["revoke_reason"] = "LOST_REPLACED"
        touch(rec)
        new = new_rec()
        new.update({"volunteer_id": vol["id"], "badge_number": mint_badge_number(),
                    "status": "ISSUED", "issued_at": n, "revoked_at": None,
                    "revoke_reason": None})
        db["badges"][new["id"]] = new
        return ok_object(ser_badge(new))

    # ---------------------------------------------------------- annual review
    @app.route("/auxiliary/compliance/annual-review", methods=["POST"])
    def annual_review():
        uid, role = auth()
        body()
        require_role(role, ["VolunteerServicesDirector"])
        n = now()
        clearances_expired = 0
        for c in sorted(db["clearances"].values(), key=lambda x: x["_seq"]):
            if c["status"] == "CLEARED" and c["expires_at"] is not None \
                    and c["expires_at"] <= n:
                c["status"] = "EXPIRED"
                touch(c)
                clearances_expired += 1
        trainings_expired = 0
        for t in sorted(db["training"].values(), key=lambda x: x["_seq"]):
            if t["status"] == "VALID" and t["recurrence"] == "ANNUAL" \
                    and t["expires_at"] is not None and t["expires_at"] <= n:
                t["status"] = "EXPIRED"
                touch(t)
                trainings_expired += 1
        volunteers_suspended = 0
        for v in sorted(db["volunteers"].values(), key=lambda x: x["_seq"]):
            if v["service_status"] != "ACTIVE":
                continue
            if compliance_posture(v) == "FROZEN":
                suspend_volunteer(v, "COMPLIANCE_LAPSE")
                volunteers_suspended += 1
                continue
            year = most_recent_completed_year(v)
            if year is not None:
                start_d, end_d = year
                hours = service_year_hours(v, start_d, end_d)
                age = age_on(parse_dob(v), end_d)
                minimum = Decimal("40.0") if age < 18 else Decimal("100.0")
                if hours < minimum:
                    suspend_volunteer(v, "HOURS_SHORTFALL")
                    volunteers_suspended += 1
        recognition_events_created = 0
        for v in sorted(db["volunteers"].values(), key=lambda x: x["_seq"]):
            points = recognition_points(v["id"])
            implied = tier_for_points(points)
            stored = v.get("_tier")
            if stored is None:
                v["_tier"] = implied
                continue
            if stored != implied:
                ev = record_tier_change(v, stored, implied, points)
                if ev is not None:
                    recognition_events_created += 1
                v["_tier"] = implied
        return ok_object({
            "clearances_expired": clearances_expired,
            "trainings_expired": trainings_expired,
            "volunteers_suspended": volunteers_suspended,
            "recognition_events_created": recognition_events_created,
        })
