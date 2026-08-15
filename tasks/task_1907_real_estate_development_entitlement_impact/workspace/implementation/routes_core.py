"""Routes: clock, fee schedules, registries, projects, application lifecycle."""

from flask import request

import store
from store import CLOCK, touch
from auth import authenticate, authorize, require_owner
from envelope import success, paginate
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_ALREADY_TERMINAL,
    ERR_INCOMPLETE_PACKAGE, ERR_PROJECT_NOT_ACTIVE, ERR_NO_ADOPTED_FEE_SCHEDULE,
    ERR_STALE_PROJECT_VERSION, ERR_BLOCKING_COMMENTS_OPEN, ERR_HEARING_REQUIRED,
    ERR_HEARING_PENDING, ERR_NOT_FOUND,
)
from validate import (
    body_or_empty, require_fields, reject_version_fields, req_str, req_enum,
    req_int, req_number, req_datetime, req_str_list, opt_category_amount_map,
)
import domain
from domain import get_or_404

ALL_ROLES = ("PlatformAdmin", "Applicant", "StaffReviewer", "DecisionAuthority")

RATE_FIELDS = (
    "rate_transportation_res", "rate_parks_res", "rate_fire_res",
    "rate_water_res", "rate_sewer_res",
    "rate_transportation_com", "rate_parks_com", "rate_fire_com",
    "rate_water_com", "rate_sewer_com",
)


def _json():
    return request.get_json(silent=True)


def register_core_routes(app):

    # --- logical clock ------------------------------------------------------
    @app.post("/entitlement/_clock/set_current_utc")
    def set_clock():
        p = authenticate()
        authorize(p, ("PlatformAdmin",))
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["to_iso8601"])
        target = req_datetime(body, "to_iso8601")
        CLOCK.set(store.fmt_dt(target))
        domain.advance_system_transitions()
        return success({"current_utc": store.fmt_dt(CLOCK.now())}, 200)

    # --- fee schedules ------------------------------------------------------
    @app.post("/entitlement/fee-schedules")
    def create_fee_schedule():
        p = authenticate()
        authorize(p, ("PlatformAdmin",))
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["schedule_label", "effective_date"] +
                       list(RATE_FIELDS))
        label = req_str(body, "schedule_label")
        eff = req_datetime(body, "effective_date")
        rates = {f: req_number(body, f) for f in RATE_FIELDS}
        rec = store.new_record("fee_schedules")
        rec.update({"schedule_label": label,
                    "effective_date": store.fmt_dt(eff),
                    "status": "DRAFT"})
        rec.update(rates)
        return success(rec, 201)

    @app.post("/entitlement/fee-schedules/<fsId>/adopt")
    def adopt_fee_schedule(fsId):
        p = authenticate()
        authorize(p, ("PlatformAdmin",))
        reject_version_fields(body_or_empty(_json()))
        fs = get_or_404("fee_schedules", fsId, "FeeSchedule")
        if fs["status"] == "SUPERSEDED":
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "FeeSchedule is SUPERSEDED; no further transitions",
                           409)
        if fs["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE,
                           "Only a DRAFT fee schedule can be adopted", 409)
        for other in store.all_records("fee_schedules"):
            if other["id"] != fs["id"] and other["status"] == "ADOPTED":
                other["status"] = "SUPERSEDED"
                touch(other)
        fs["status"] = "ADOPTED"
        touch(fs)
        return success(fs, 200)

    @app.get("/entitlement/fee-schedules/<fsId>")
    def get_fee_schedule(fsId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        return success(get_or_404("fee_schedules", fsId, "FeeSchedule"), 200)

    @app.get("/entitlement/fee-schedules")
    def list_fee_schedules():
        p = authenticate()
        authorize(p, ALL_ROLES)
        recs = store.all_records("fee_schedules")
        status = request.args.get("status")
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    # --- registries: applicants / staff reviewers / decision authorities ----
    @app.post("/entitlement/applicants")
    def create_applicant():
        p = authenticate()
        authorize(p, ("PlatformAdmin",))
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["legal_name", "contact_email"])
        rec = store.new_record("applicants")
        rec.update({"legal_name": req_str(body, "legal_name"),
                    "contact_email": req_str(body, "contact_email")})
        return success(rec, 201)

    @app.get("/entitlement/applicants/<applicantId>")
    def get_applicant(applicantId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        return success(get_or_404("applicants", applicantId, "Applicant"), 200)

    @app.post("/entitlement/staff-reviewers")
    def create_reviewer():
        p = authenticate()
        authorize(p, ("PlatformAdmin",))
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["full_name", "disciplines"])
        rec = store.new_record("staff_reviewers")
        rec.update({"full_name": req_str(body, "full_name"),
                    "disciplines": req_str_list(body, "disciplines")})
        return success(rec, 201)

    @app.get("/entitlement/staff-reviewers/<reviewerId>")
    def get_reviewer(reviewerId):
        p = authenticate()
        authorize(p, ("PlatformAdmin", "StaffReviewer", "DecisionAuthority"))
        return success(get_or_404("staff_reviewers", reviewerId,
                                  "StaffReviewer"), 200)

    @app.post("/entitlement/decision-authorities")
    def create_authority():
        p = authenticate()
        authorize(p, ("PlatformAdmin",))
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["full_name", "body"])
        rec = store.new_record("decision_authorities")
        rec.update({"full_name": req_str(body, "full_name"),
                    "body": req_enum(body, "body",
                                     ("PLANNING_COMMISSION", "CITY_COUNCIL",
                                      "STAFF_DIRECTOR"))})
        return success(rec, 201)

    @app.get("/entitlement/decision-authorities/<authorityId>")
    def get_authority(authorityId):
        p = authenticate()
        authorize(p, ("PlatformAdmin", "StaffReviewer", "DecisionAuthority"))
        return success(get_or_404("decision_authorities", authorityId,
                                  "DecisionAuthority"), 200)

    # --- projects -------------------------------------------------------------
    @app.post("/entitlement/projects")
    def create_project():
        p = authenticate()
        authorize(p, ("Applicant", "PlatformAdmin"))
        body = body_or_empty(_json())
        reject_version_fields(body)
        require_fields(body, ["project_name", "applicant_id", "land_use_type",
                              "dwelling_units", "affordable_units",
                              "floor_area_sqft"])
        name = req_str(body, "project_name")
        applicant_id = req_str(body, "applicant_id")
        land_use = req_enum(body, "land_use_type", ("RESIDENTIAL", "COMMERCIAL"))
        dwelling = req_int(body, "dwelling_units")
        affordable = req_int(body, "affordable_units")
        floor_area = req_int(body, "floor_area_sqft")
        prior_use = opt_category_amount_map(body, "prior_use_basis")
        if dwelling < 0:
            raise ApiError(ERR_INVALID_REQUEST, "dwelling_units must be >= 0",
                           400)
        if floor_area < 0:
            raise ApiError(ERR_INVALID_REQUEST, "floor_area_sqft must be >= 0",
                           400)
        if affordable < 0 or affordable > dwelling:
            raise ApiError(ERR_INVALID_REQUEST,
                           "affordable_units must satisfy "
                           "0 <= affordable_units <= dwelling_units", 400)
        get_or_404("applicants", applicant_id, "Applicant")
        if p.is_applicant and p.user_id != applicant_id:
            from errors import ERR_NOT_PROJECT_OWNER
            raise ApiError(ERR_NOT_PROJECT_OWNER,
                           "An Applicant may create projects only for itself",
                           403)
        rec = store.new_record("projects")
        rec.update({"project_name": name, "applicant_id": applicant_id,
                    "land_use_type": land_use, "dwelling_units": dwelling,
                    "affordable_units": affordable,
                    "floor_area_sqft": floor_area,
                    "prior_use_basis": prior_use, "status": "ACTIVE"})
        return success(rec, 201)

    @app.get("/entitlement/projects/<projectId>")
    def get_project(projectId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        return success(get_or_404("projects", projectId, "EntitlementProject"),
                       200)

    @app.get("/entitlement/projects")
    def list_projects():
        p = authenticate()
        authorize(p, ALL_ROLES)
        recs = store.all_records("projects")
        applicant_id = request.args.get("applicant_id")
        if applicant_id is not None:
            recs = [r for r in recs if r.get("applicant_id") == applicant_id]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    # --- applications ---------------------------------------------------------
    @app.post("/entitlement/applications")
    def create_application():
        p = authenticate()
        authorize(p, ("Applicant",))
        body = body_or_empty(_json())
        reject_version_fields(body, allowed=("expected_project_version",))
        require_fields(body, ["project_id", "application_type",
                              "submittal_package", "expected_project_version"])
        project_id = req_str(body, "project_id")
        app_type = req_enum(body, "application_type",
                            ("REZONE", "CONDITIONAL_USE", "PLANNED_DEVELOPMENT"))
        package = req_str_list(body, "submittal_package")
        credits = opt_category_amount_map(body, "improvement_credits")
        expected = req_int(body, "expected_project_version")
        project = get_or_404("projects", project_id, "EntitlementProject")
        if expected != project["version"]:
            raise ApiError(ERR_STALE_PROJECT_VERSION,
                           "expected_project_version does not match the "
                           "current project version", 412)
        require_owner(p, project)
        rec = store.new_record("applications")
        rec.update({
            "project_id": project["id"],
            "application_type": app_type,
            "submittal_package": package,
            "improvement_credits": credits,
            "pinned_fee_schedule_id": None,
            "provisional_fee_total": None,
            "final_fee_total": None,
            "opposition_score": None,
            "opposition_posture": None,
            "submitted_at": None,
            "decision_due_date": None,
            "status": "DRAFT",
        })
        # Adding an application is itself a modification of the project.
        touch(project)
        return success(rec, 201)

    @app.get("/entitlement/applications/<appId>")
    def get_application(appId):
        p = authenticate()
        authorize(p, ALL_ROLES)
        return success(get_or_404("applications", appId,
                                  "EntitlementApplication"), 200)

    @app.get("/entitlement/applications")
    def list_applications():
        p = authenticate()
        authorize(p, ALL_ROLES)
        recs = store.all_records("applications")
        for param, field in (("project_id", "project_id"),
                             ("status", "status"),
                             ("pinned_fee_schedule_id",
                              "pinned_fee_schedule_id")):
            v = request.args.get(param)
            if v is not None:
                recs = [r for r in recs if r.get(field) == v]
        page, meta = paginate(recs, request.args)
        return success(page, 200, "array", meta)

    @app.post("/entitlement/applications/<appId>/submit")
    def submit_application(appId):
        p = authenticate()
        authorize(p, ("Applicant",))
        reject_version_fields(body_or_empty(_json()))
        app_rec = get_or_404("applications", appId, "EntitlementApplication")
        if app_rec["status"] in ("APPROVED", "DENIED", "WITHDRAWN"):
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "Application is in a terminal state", 409)
        if app_rec["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE,
                           "Only a DRAFT application can be submitted", 409)
        if not app_rec.get("submittal_package"):
            raise ApiError(ERR_INCOMPLETE_PACKAGE,
                           "submittal_package is empty or missing required "
                           "document keys", 422)
        project = domain.project_for(app_rec)
        if project is None or project["status"] != "ACTIVE":
            raise ApiError(ERR_PROJECT_NOT_ACTIVE,
                           "Parent project must be ACTIVE", 409)
        schedule = domain.adopted_schedule_now()
        if schedule is None:
            raise ApiError(ERR_NO_ADOPTED_FEE_SCHEDULE,
                           "No ADOPTED FeeSchedule exists at submit time", 422)
        require_owner(p, project)

        now = CLOCK.now()
        app_rec["pinned_fee_schedule_id"] = schedule["id"]
        app_rec["submitted_at"] = store.fmt_dt(now)
        from datetime import timedelta
        app_rec["decision_due_date"] = store.fmt_dt(
            now + timedelta(days=domain.PERMIT_STREAMLINING_DAYS))
        app_rec["opposition_score"] = 0
        app_rec["opposition_posture"] = "LOW"
        assessment = domain.create_assessment(app_rec, project, schedule,
                                              "PROVISIONAL", now)
        app_rec["provisional_fee_total"] = assessment["net_total"]
        app_rec["status"] = "SUBMITTED"
        touch(app_rec)
        return success(app_rec, 200)

    @app.post("/entitlement/applications/<appId>/open-review")
    def open_review(appId):
        p = authenticate()
        authorize(p, ("StaffReviewer",))
        reject_version_fields(body_or_empty(_json()))
        app_rec = get_or_404("applications", appId, "EntitlementApplication")
        if app_rec["status"] in ("APPROVED", "DENIED", "WITHDRAWN"):
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "Application is in a terminal state", 409)
        if app_rec["status"] != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE,
                           "Only a SUBMITTED application can open review", 409)
        app_rec["status"] = "UNDER_REVIEW"
        touch(app_rec)
        return success(app_rec, 200)

    @app.post("/entitlement/applications/<appId>/advance-to-decision")
    def advance_to_decision(appId):
        p = authenticate()
        authorize(p, ("StaffReviewer",))
        reject_version_fields(body_or_empty(_json()))
        app_rec = get_or_404("applications", appId, "EntitlementApplication")
        if app_rec["status"] in ("APPROVED", "DENIED", "WITHDRAWN"):
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "Application is in a terminal state", 409)
        if app_rec["status"] not in ("UNDER_REVIEW", "HEARING_SCHEDULED"):
            raise ApiError(ERR_INVALID_STATE,
                           "Advancement requires UNDER_REVIEW or "
                           "HEARING_SCHEDULED", 409)
        open_blocking = [c for c in store.all_records("review_comments")
                         if c.get("application_id") == appId
                         and c["severity"] == "BLOCKING"
                         and c["status"] in ("OPEN", "ADDRESSED")]
        if open_blocking:
            raise ApiError(ERR_BLOCKING_COMMENTS_OPEN,
                           "One or more BLOCKING review comments are still "
                           "OPEN or ADDRESSED-not-VERIFIED", 409)
        scheduled = [h for h in store.all_records("hearings")
                     if h.get("application_id") == appId
                     and h["status"] == "SCHEDULED"]
        if scheduled:
            raise ApiError(ERR_HEARING_PENDING,
                           "A SCHEDULED hearing exists; it must be HELD or "
                           "CANCELLED first", 409)
        if app_rec.get("opposition_posture") == "HIGH":
            held = [h for h in store.all_records("hearings")
                    if h.get("application_id") == appId
                    and h["status"] == "HELD"]
            if not held:
                raise ApiError(ERR_HEARING_REQUIRED,
                               "opposition_posture HIGH requires a HELD "
                               "hearing before decision", 409)
        app_rec["status"] = "DECISION_PENDING"
        touch(app_rec)
        return success(app_rec, 200)

    @app.post("/entitlement/applications/<appId>/withdraw")
    def withdraw_application(appId):
        p = authenticate()
        authorize(p, ("Applicant",))
        reject_version_fields(body_or_empty(_json()))
        app_rec = get_or_404("applications", appId, "EntitlementApplication")
        if app_rec["status"] in ("APPROVED", "DENIED", "WITHDRAWN"):
            raise ApiError(ERR_ALREADY_TERMINAL,
                           "Application is in a terminal state", 409)
        if app_rec["status"] not in ("SUBMITTED", "UNDER_REVIEW",
                                     "HEARING_SCHEDULED", "DECISION_PENDING"):
            raise ApiError(ERR_INVALID_STATE,
                           "Application cannot be withdrawn from its current "
                           "state", 409)
        project = domain.project_for(app_rec)
        if project is not None:
            require_owner(p, project)
        app_rec["status"] = "WITHDRAWN"
        touch(app_rec)
        domain.refund_open_assessments(app_rec)
        for h in store.all_records("hearings"):
            if h.get("application_id") == appId and h["status"] == "SCHEDULED":
                h["status"] = "CANCELLED"
                touch(h)
        for c in store.all_records("conditions"):
            if c.get("application_id") == appId and c["status"] == "PENDING":
                c["status"] = "WAIVED"
                touch(c)
        return success(app_rec, 200)
