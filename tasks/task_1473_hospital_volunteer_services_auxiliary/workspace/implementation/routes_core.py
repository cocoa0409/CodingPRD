"""Routes: logical clock, volunteer applications, volunteers, clearances."""
from flask import request

from core import (
    db, now, today, iso_z, auth, require_role, body, ok_object, ok_list, page_list,
    pagination_params, get_or_404, raise_err, touch, new_rec, req_str, opt_str,
    req_enum, req_date, req_version, parse_datetime,
    ERR_INVALID_REQUEST, ERR_UNAUTHORIZED_ROLE, ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_STALE_VERSION, ERR_APPLICATION_NOT_ACTIONABLE, ERR_VOLUNTEER_INVALID_STATE,
    ERR_POSTURE_FROZEN, ERR_CLEARANCE_INVALID_STATE, ERR_SOD_CLEARANCE,
    ERR_ORIENTATION_INCOMPLETE, ERR_CLEARANCE_REQUIREMENTS_UNMET,
    ERR_NO_ACCEPTED_PLACEMENT, ERR_BADGE_INVALID_STATE, ERR_DUPLICATE_ACTIVE_CLEARANCE,
)
from domain import (
    CLEARANCE_TYPES, VALIDITY_MONTHS, compliance_posture, latest_clearance,
    total_service_hours, recognition_points, tier_for_points, current_service_year_start,
    service_year_hours, is_junior_at, live_badge, suspend_volunteer, separation_cascade,
    freeze_cascade, ser_application, ser_volunteer, ser_clearance,
)
from domain import most_recent_completed_year, parse_dob, age_on

APP_STATUS = ["SUBMITTED", "IN_REVIEW", "NEEDS_INFO", "APPROVED", "REJECTED", "WITHDRAWN"]
SERVICE_STATUS = ["ONBOARDING", "ACTIVE", "SUSPENDED", "SEPARATED"]
POSTURES = ["CLEAR", "RESTRICTED", "FROZEN"]
TIERS = ["NONE", "BRONZE", "SILVER", "GOLD", "PRESIDENT"]
CLEARANCE_STATUS = ["SUBMITTED", "CLEARED", "REJECTED", "EXPIRED", "REVOKED"]
SEPARATION_REASONS = ["VOLUNTARY", "INVOLUNTARY", "DECEASED", "MOVED", "OTHER"]
STAFF5 = ["VolunteerServicesDirector", "VolunteerCoordinator", "Screener",
          "DepartmentHead", "AuxiliaryTreasurer"]


def _filter_enum(value, allowed, field):
    if value is None:
        return None
    if value not in allowed:
        raise_err(ERR_INVALID_REQUEST, "Query parameter '%s' must be one of %s" % (field, allowed))
    return value


def register(app):

    # ------------------------------------------------------------------ clock
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        uid, role = auth()
        data = body()
        raw = req_str(data, "to_iso8601")
        dt = parse_datetime(raw)
        if dt is None:
            raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 datetime")
        require_role(role, STAFF5)
        from core import set_now
        set_now(dt)
        return ok_object({"current_utc": iso_z(dt)})

    # ---------------------------------------------------------- applications
    @app.route("/auxiliary/volunteer-applications", methods=["POST"])
    def create_application():
        uid, role = auth()
        data = body()
        full_name = req_str(data, "full_name")
        dob = req_date(data, "date_of_birth")
        email = req_str(data, "email")
        phone = req_str(data, "phone")
        notes = opt_str(data, "notes")
        require_role(role, ["VolunteerCoordinator", "VolunteerServicesDirector"])
        rec = new_rec()
        rec.update({
            "full_name": full_name,
            "date_of_birth": dob.isoformat(),
            "email": email,
            "phone": phone,
            "notes": notes,
            "status": "SUBMITTED",
            "volunteer_id": None,
            "decided_by_user_id": None,
            "decided_at": None,
            "rejection_reason": None,
            "info_request_note": None,
        })
        db["applications"][rec["id"]] = rec
        return ok_object(ser_application(rec), 201)

    @app.route("/auxiliary/volunteer-applications", methods=["GET"])
    def list_applications():
        uid, role = auth()
        require_role(role, ["VolunteerServicesDirector", "VolunteerCoordinator", "Screener"])
        status = _filter_enum(request.args.get("status"), APP_STATUS, "status")
        volunteer_id = request.args.get("volunteer_id")
        return page_list(db["applications"].values(), ser_application,
                         filters={"status": status, "volunteer_id": volunteer_id})

    @app.route("/auxiliary/volunteer-applications/<rid>", methods=["GET"])
    def get_application(rid):
        uid, role = auth()
        require_role(role, ["VolunteerServicesDirector", "VolunteerCoordinator", "Screener"])
        rec = get_or_404("applications", rid, "VolunteerApplication")
        return ok_object(ser_application(rec))

    @app.route("/auxiliary/volunteer-applications/<rid>/start-review", methods=["POST"])
    def start_review(rid):
        uid, role = auth()
        body()
        require_role(role, ["VolunteerCoordinator"])
        rec = get_or_404("applications", rid, "VolunteerApplication")
        if rec["status"] != "SUBMITTED":
            raise_err(ERR_APPLICATION_NOT_ACTIONABLE, "Application is not SUBMITTED")
        rec["status"] = "IN_REVIEW"
        touch(rec)
        return ok_object(ser_application(rec))

    @app.route("/auxiliary/volunteer-applications/<rid>/request-info", methods=["POST"])
    def request_info(rid):
        uid, role = auth()
        data = body()
        note = req_str(data, "info_request_note", nonempty=True)
        require_role(role, ["VolunteerCoordinator"])
        rec = get_or_404("applications", rid, "VolunteerApplication")
        if rec["status"] != "IN_REVIEW":
            raise_err(ERR_APPLICATION_NOT_ACTIONABLE, "Application is not IN_REVIEW")
        rec["status"] = "NEEDS_INFO"
        rec["info_request_note"] = note
        touch(rec)
        return ok_object(ser_application(rec))

    @app.route("/auxiliary/volunteer-applications/<rid>/resubmit", methods=["POST"])
    def resubmit_application(rid):
        uid, role = auth()
        data = body()
        notes = opt_str(data, "notes")
        require_role(role, ["VolunteerCoordinator"])
        rec = get_or_404("applications", rid, "VolunteerApplication")
        if rec["status"] != "NEEDS_INFO":
            raise_err(ERR_APPLICATION_NOT_ACTIONABLE, "Application is not NEEDS_INFO")
        rec["status"] = "IN_REVIEW"
        if notes is not None:
            rec["notes"] = notes
        touch(rec)
        return ok_object(ser_application(rec))

    @app.route("/auxiliary/volunteer-applications/<rid>/decide", methods=["POST"])
    def decide_application(rid):
        uid, role = auth()
        data = body()
        decision = req_enum(data, "decision", ["APPROVE", "REJECT"])
        rejection_reason = None
        if decision == "REJECT":
            rejection_reason = req_str(data, "rejection_reason", nonempty=True)
        else:
            rejection_reason = opt_str(data, "rejection_reason")
        require_role(role, ["VolunteerServicesDirector"])
        rec = get_or_404("applications", rid, "VolunteerApplication")
        if rec["status"] != "IN_REVIEW":
            raise_err(ERR_APPLICATION_NOT_ACTIONABLE, "Application is not IN_REVIEW")
        n = now()
        rec["decided_by_user_id"] = uid
        rec["decided_at"] = n
        if decision == "REJECT":
            rec["status"] = "REJECTED"
            rec["rejection_reason"] = rejection_reason
            touch(rec)
            return ok_object(ser_application(rec))
        # APPROVE
        if rec["volunteer_id"] is None:
            vol = new_rec()
            vol.update({
                "full_name": rec["full_name"],
                "date_of_birth": rec["date_of_birth"],
                "email": rec["email"],
                "phone": rec["phone"],
                "notes": rec["notes"],
                "service_status": "ONBOARDING",
                "joined_at": n,
                "separated_at": None,
                "separation_reason": None,
                "suspension_reason": None,
                "_tier": "NONE",
            })
            db["volunteers"][vol["id"]] = vol
            rec["volunteer_id"] = vol["id"]
        else:
            vol = db["volunteers"].get(rec["volunteer_id"])
            if vol is None:
                raise_err(ERR_NOT_FOUND, "Linked volunteer not found")
            if vol["service_status"] != "SEPARATED":
                raise_err(ERR_VOLUNTEER_INVALID_STATE,
                          "Reapply approval requires a SEPARATED volunteer")
            vol["service_status"] = "ONBOARDING"
            vol["joined_at"] = n
            vol["separated_at"] = None
            vol["separation_reason"] = None
            vol["suspension_reason"] = None
            touch(vol)
        # badge + orientation training record
        badge = new_rec()
        from core import mint_badge_number
        badge.update({
            "volunteer_id": vol["id"],
            "badge_number": mint_badge_number(),
            "status": "PENDING",
            "issued_at": None,
            "revoked_at": None,
            "revoke_reason": None,
        })
        db["badges"][badge["id"]] = badge
        tr = new_rec()
        tr.update({
            "volunteer_id": vol["id"],
            "training_code": "ORIENTATION",
            "recurrence": "ONE_TIME",
            "status": "PENDING",
            "completed_at": None,
            "expires_at": None,
        })
        db["training"][tr["id"]] = tr
        rec["status"] = "APPROVED"
        touch(rec)
        return ok_object(ser_application(rec))

    @app.route("/auxiliary/volunteer-applications/<rid>/withdraw", methods=["POST"])
    def withdraw_application(rid):
        uid, role = auth()
        body()
        require_role(role, ["VolunteerCoordinator"])
        rec = get_or_404("applications", rid, "VolunteerApplication")
        if rec["status"] not in ("SUBMITTED", "IN_REVIEW", "NEEDS_INFO"):
            raise_err(ERR_APPLICATION_NOT_ACTIONABLE,
                      "Application cannot be withdrawn from its current state")
        rec["status"] = "WITHDRAWN"
        touch(rec)
        return ok_object(ser_application(rec))

    # ------------------------------------------------------------- volunteers
    @app.route("/auxiliary/volunteers", methods=["GET"])
    def list_volunteers():
        uid, role = auth()
        require_role(role, STAFF5)
        service_status = _filter_enum(request.args.get("service_status"), SERVICE_STATUS,
                                      "service_status")
        posture = _filter_enum(request.args.get("compliance_posture"), POSTURES,
                               "compliance_posture")
        tier = _filter_enum(request.args.get("recognition_tier"), TIERS, "recognition_tier")
        rows = list(db["volunteers"].values())
        if service_status is not None:
            rows = [v for v in rows if v["service_status"] == service_status]
        if posture is not None:
            rows = [v for v in rows if compliance_posture(v) == posture]
        if tier is not None:
            rows = [v for v in rows if tier_for_points(recognition_points(v["id"])) == tier]
        return page_list(rows, ser_volunteer)

    @app.route("/auxiliary/volunteers/<rid>", methods=["GET"])
    def get_volunteer(rid):
        uid, role = auth()
        require_role(role, STAFF5 + ["Volunteer"])
        vol = get_or_404("volunteers", rid, "Volunteer")
        if role == "Volunteer" and uid != rid:
            raise_err(ERR_NOT_RESOURCE_OWNER, "Volunteers may only read their own record")
        return ok_object(ser_volunteer(vol))

    @app.route("/auxiliary/volunteers/<rid>/summary", methods=["GET"])
    def volunteer_summary(rid):
        uid, role = auth()
        require_role(role, ["VolunteerServicesDirector", "VolunteerCoordinator", "Volunteer"])
        vol = get_or_404("volunteers", rid, "Volunteer")
        if role == "Volunteer" and uid != rid:
            raise_err(ERR_NOT_RESOURCE_OWNER, "Volunteers may only read their own summary")
        points = recognition_points(vol["id"])
        year_start = current_service_year_start(vol)
        from domain import add_years_date
        year_end = add_years_date(year_start, 1)
        accepted = sum(1 for p in db["placements"].values()
                       if p["volunteer_id"] == vol["id"] and p["status"] == "ACCEPTED")
        badge = live_badge(vol)
        data = {
            "compliance_posture": compliance_posture(vol),
            "total_service_hours": float(total_service_hours(vol["id"])),
            "service_year_hours": float(service_year_hours(vol, year_start, year_end)),
            "recognition_points": float(points),
            "recognition_tier": tier_for_points(points),
            "is_junior_today": is_junior_at(vol, today()),
            "accepted_placement_count": accepted,
            "live_badge_status": badge["status"] if badge else None,
        }
        return ok_object(data)

    @app.route("/auxiliary/volunteers/<rid>", methods=["PUT"])
    def update_volunteer(rid):
        uid, role = auth()
        data = body()
        full_name = opt_str(data, "full_name")
        email = opt_str(data, "email")
        phone = opt_str(data, "phone")
        notes = opt_str(data, "notes")
        expected = req_version(data, "expected_volunteer_version")
        require_role(role, ["VolunteerCoordinator"])
        vol = get_or_404("volunteers", rid, "Volunteer")
        if expected != vol["version"]:
            raise_err(ERR_STALE_VERSION, "Volunteer version is stale")
        if full_name is not None:
            vol["full_name"] = full_name
        if email is not None:
            vol["email"] = email
        if phone is not None:
            vol["phone"] = phone
        if notes is not None:
            vol["notes"] = notes
        touch(vol)
        return ok_object(ser_volunteer(vol))

    @app.route("/auxiliary/volunteers/<rid>/activate", methods=["POST"])
    def activate_volunteer(rid):
        uid, role = auth()
        body()
        require_role(role, ["VolunteerCoordinator"])
        vol = get_or_404("volunteers", rid, "Volunteer")
        if vol["service_status"] != "ONBOARDING":
            raise_err(ERR_VOLUNTEER_INVALID_STATE, "Volunteer is not ONBOARDING")
        # ORIENTATION VALID
        orient_ok = any(t["volunteer_id"] == vol["id"] and t["training_code"] == "ORIENTATION"
                        and t["status"] == "VALID" for t in db["training"].values())
        if not orient_ok:
            raise_err(ERR_ORIENTATION_INCOMPLETE,
                      "ORIENTATION training record is not VALID")
        n = now()
        for ctype in CLEARANCE_TYPES:
            c = latest_clearance(vol["id"], ctype)
            if c is None or c["status"] != "CLEARED" or c["expires_at"] is None \
                    or not (c["expires_at"] > n):
                raise_err(ERR_CLEARANCE_REQUIREMENTS_UNMET,
                          "Clearance requirements unmet for %s" % ctype)
        has_accepted = any(p["volunteer_id"] == vol["id"] and p["status"] == "ACCEPTED"
                           for p in db["placements"].values())
        if not has_accepted:
            raise_err(ERR_NO_ACCEPTED_PLACEMENT, "No ACCEPTED placement exists")
        badge = live_badge(vol)
        if badge is None or badge["status"] != "PENDING":
            raise_err(ERR_BADGE_INVALID_STATE, "No PENDING badge exists")
        badge["status"] = "ISSUED"
        badge["issued_at"] = n
        touch(badge)
        vol["service_status"] = "ACTIVE"
        touch(vol)
        return ok_object(ser_volunteer(vol))

    @app.route("/auxiliary/volunteers/<rid>/suspend", methods=["POST"])
    def suspend_volunteer_ep(rid):
        uid, role = auth()
        data = body()
        req_str(data, "reason", nonempty=True)
        require_role(role, ["VolunteerCoordinator", "VolunteerServicesDirector"])
        vol = get_or_404("volunteers", rid, "Volunteer")
        if vol["service_status"] != "ACTIVE":
            raise_err(ERR_VOLUNTEER_INVALID_STATE, "Volunteer is not ACTIVE")
        suspend_volunteer(vol, "MANUAL")
        return ok_object(ser_volunteer(vol))

    @app.route("/auxiliary/volunteers/<rid>/reinstate", methods=["POST"])
    def reinstate_volunteer(rid):
        uid, role = auth()
        body()
        require_role(role, ["VolunteerCoordinator", "VolunteerServicesDirector"])
        vol = get_or_404("volunteers", rid, "Volunteer")
        if vol["service_status"] != "SUSPENDED":
            raise_err(ERR_VOLUNTEER_INVALID_STATE, "Volunteer is not SUSPENDED")
        if compliance_posture(vol) == "FROZEN":
            raise_err(ERR_POSTURE_FROZEN, "Volunteer compliance posture is FROZEN")
        badge = live_badge(vol)
        if badge is not None and badge["status"] == "SUSPENDED":
            badge["status"] = "ISSUED"
            touch(badge)
        vol["service_status"] = "ACTIVE"
        vol["suspension_reason"] = None
        touch(vol)
        return ok_object(ser_volunteer(vol))

    @app.route("/auxiliary/volunteers/<rid>/separate", methods=["POST"])
    def separate_volunteer(rid):
        uid, role = auth()
        data = body()
        reason = req_enum(data, "separation_reason", SEPARATION_REASONS)
        opt_str(data, "notes")
        require_role(role, ["VolunteerServicesDirector"])
        vol = get_or_404("volunteers", rid, "Volunteer")
        if vol["service_status"] not in ("ONBOARDING", "ACTIVE", "SUSPENDED"):
            raise_err(ERR_VOLUNTEER_INVALID_STATE,
                      "Volunteer cannot be separated from its current state")
        separation_cascade(vol)
        vol["separated_at"] = now()
        vol["separation_reason"] = reason
        touch(vol)
        return ok_object(ser_volunteer(vol))

    @app.route("/auxiliary/volunteers/<rid>/reapply", methods=["POST"])
    def reapply_volunteer(rid):
        uid, role = auth()
        data = body()
        notes = opt_str(data, "notes")
        require_role(role, ["VolunteerCoordinator"])
        vol = get_or_404("volunteers", rid, "Volunteer")
        if vol["service_status"] != "SEPARATED":
            raise_err(ERR_VOLUNTEER_INVALID_STATE, "Volunteer is not SEPARATED")
        rec = new_rec()
        rec.update({
            "full_name": vol["full_name"],
            "date_of_birth": vol["date_of_birth"],
            "email": vol["email"],
            "phone": vol["phone"],
            "notes": notes,
            "status": "SUBMITTED",
            "volunteer_id": vol["id"],
            "decided_by_user_id": None,
            "decided_at": None,
            "rejection_reason": None,
            "info_request_note": None,
        })
        db["applications"][rec["id"]] = rec
        return ok_object(ser_application(rec), 201)

    # ------------------------------------------------------------- clearances
    @app.route("/auxiliary/clearances", methods=["POST"])
    def create_clearance():
        uid, role = auth()
        data = body()
        volunteer_id = req_str(data, "volunteer_id")
        ctype = req_enum(data, "clearance_type", list(CLEARANCE_TYPES))
        document_ref = req_str(data, "document_ref")
        require_role(role, ["Screener", "VolunteerCoordinator"])
        get_or_404("volunteers", volunteer_id, "Volunteer")
        for c in db["clearances"].values():
            if c["volunteer_id"] == volunteer_id and c["clearance_type"] == ctype \
                    and c["status"] != "REVOKED":
                raise_err(ERR_DUPLICATE_ACTIVE_CLEARANCE,
                          "A non-terminal clearance already exists for this volunteer and type")
        rec = new_rec()
        rec.update({
            "volunteer_id": volunteer_id,
            "clearance_type": ctype,
            "document_ref": document_ref,
            "status": "SUBMITTED",
            "submitted_by_user_id": uid,
            "adjudicated_by_user_id": None,
            "adjudicated_at": None,
            "expires_at": None,
            "adjudication_notes": None,
        })
        db["clearances"][rec["id"]] = rec
        return ok_object(ser_clearance(rec), 201)

    @app.route("/auxiliary/clearances", methods=["GET"])
    def list_clearances():
        uid, role = auth()
        require_role(role, ["VolunteerServicesDirector", "VolunteerCoordinator", "Screener",
                            "Volunteer"])
        volunteer_id = request.args.get("volunteer_id")
        ctype = _filter_enum(request.args.get("clearance_type"), list(CLEARANCE_TYPES),
                             "clearance_type")
        status = _filter_enum(request.args.get("status"), CLEARANCE_STATUS, "status")
        rows = list(db["clearances"].values())
        if role == "Volunteer":
            if volunteer_id is not None and volunteer_id != uid:
                raise_err(ERR_NOT_RESOURCE_OWNER,
                          "Volunteers may only list their own clearances")
            rows = [c for c in rows if c["volunteer_id"] == uid]
        return page_list(rows, ser_clearance,
                         filters={"volunteer_id": volunteer_id if role != "Volunteer" else None,
                                  "clearance_type": ctype, "status": status})

    @app.route("/auxiliary/clearances/<rid>", methods=["GET"])
    def get_clearance(rid):
        uid, role = auth()
        require_role(role, ["VolunteerServicesDirector", "VolunteerCoordinator", "Screener"])
        rec = get_or_404("clearances", rid, "Clearance")
        return ok_object(ser_clearance(rec))

    @app.route("/auxiliary/clearances/<rid>/adjudicate", methods=["POST"])
    def adjudicate_clearance(rid):
        uid, role = auth()
        data = body()
        decision = req_enum(data, "decision", ["CLEARED", "REJECTED"])
        notes = opt_str(data, "adjudication_notes")
        require_role(role, ["Screener"])
        rec = get_or_404("clearances", rid, "Clearance")
        if uid == rec["submitted_by_user_id"]:
            raise_err(ERR_SOD_CLEARANCE, "Adjudicator must differ from the submitter")
        if rec["status"] != "SUBMITTED":
            raise_err(ERR_CLEARANCE_INVALID_STATE, "Clearance is not SUBMITTED")
        n = now()
        rec["adjudicated_by_user_id"] = uid
        rec["adjudicated_at"] = n
        if notes is not None:
            rec["adjudication_notes"] = notes
        if decision == "CLEARED":
            from core import add_months
            rec["status"] = "CLEARED"
            rec["expires_at"] = add_months(n, VALIDITY_MONTHS[rec["clearance_type"]])
        else:
            rec["status"] = "REJECTED"
            rec["expires_at"] = None
        touch(rec)
        return ok_object(ser_clearance(rec))

    @app.route("/auxiliary/clearances/<rid>/resubmit", methods=["POST"])
    def resubmit_clearance(rid):
        uid, role = auth()
        data = body()
        document_ref = req_str(data, "document_ref")
        require_role(role, ["Screener", "VolunteerCoordinator"])
        rec = get_or_404("clearances", rid, "Clearance")
        if rec["status"] not in ("REJECTED", "EXPIRED"):
            raise_err(ERR_CLEARANCE_INVALID_STATE, "Clearance is not REJECTED or EXPIRED")
        rec["status"] = "SUBMITTED"
        rec["document_ref"] = document_ref
        rec["submitted_by_user_id"] = uid
        rec["adjudicated_by_user_id"] = None
        rec["adjudicated_at"] = None
        rec["expires_at"] = None
        touch(rec)
        return ok_object(ser_clearance(rec))

    @app.route("/auxiliary/clearances/<rid>/revoke", methods=["POST"])
    def revoke_clearance(rid):
        uid, role = auth()
        data = body()
        req_str(data, "reason", nonempty=True)
        require_role(role, ["Screener", "VolunteerServicesDirector"])
        rec = get_or_404("clearances", rid, "Clearance")
        if rec["status"] != "CLEARED":
            raise_err(ERR_CLEARANCE_INVALID_STATE, "Clearance is not CLEARED")
        vol = db["volunteers"].get(rec["volunteer_id"])
        posture_before = compliance_posture(vol) if vol else None
        rec["status"] = "REVOKED"
        touch(rec)
        if vol is not None:
            freeze_cascade(vol, posture_before)
        return ok_object(ser_clearance(rec))
