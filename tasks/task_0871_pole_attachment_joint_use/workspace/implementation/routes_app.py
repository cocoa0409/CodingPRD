"""Routes: attachment applications lifecycle + make-ready surveys (read)."""

from flask import request

import constants as C
from clock import LOGICAL_CLOCK, add_days
from store import DB, touch
from errors import ApiError
from response import object_response, array_response
import serializers as S
import domain
import common as X

APP_READ = ["JointUseCoordinator", "Engineer", "PermitOfficer", "Attacher"]
SURVEY_READ = ["JointUseCoordinator", "Engineer"]


def _page(records, serializer):
    limit, offset = X.paginate()
    ordered = X.apply_pagination(records)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return array_response([serializer(r) for r in window], limit, offset, total)


def _owner_of(app):
    pole = DB.poles[app["pole_id"]]
    return DB.pole_owners[pole["pole_owner_id"]], pole


def register(app):

    # --- create application --------------------------------------------------
    @app.route("/joint-use/applications", methods=["POST"])
    def create_application():
        user_id, role = X.current_actor()
        X.authorize(role, ["Attacher"])
        body = X.get_body()
        # Ownership (priority 2): the named attacher must be the caller.
        aid = body.get("attacher_id")
        if isinstance(aid, str) and aid != user_id:
            raise ApiError("ERR_UNAUTHORIZED", "Attacher may only file its own applications.")
        # Existence (priority 3), left-to-right: pole_id then attacher_id.
        pole = X.get_pole(X.req_str(body, "pole_id"))
        attacher = X.get_attacher(X.req_str(body, "attacher_id"))
        X.require_owner(attacher["id"], user_id)
        # Body validation (priority 4).
        space = X.req_int_positive(body, "requested_space_inches")
        position = X.req_int_positive(body, "requested_position_inches")
        purpose = X.req_enum(body, "purpose", C.PURPOSES)
        now = LOGICAL_CLOCK.now()
        rec = DB.new_record({
            "pole_id": pole["id"],
            "attacher_id": attacher["id"],
            "requested_space_inches": space,
            "requested_position_inches": position,
            "purpose": purpose,
            "reserved_space_inches": 0,
            "submitted_at": now,
            "surveyed_at": None,
            "estimate_issued_at": None,
            "estimate_expires_at": None,
            "estimate_accepted_at": None,
            "survey_deadline": add_days(now, C.SURVEY_SHOT_CLOCK_DAYS),
            "estimate_deadline": None,
            "permit_deadline": None,
            "make_ready_required": None,
            "make_ready_fee_estimate_cents": None,
            "make_ready_fee_final_cents": None,
            "annual_rental_fee_cents": None,
            "surveyor_user_id": None,
            "permit_officer_user_id": None,
            "permit_decision": None,
            "permit_issued_at": None,
            "shot_clock_status": None,
            "make_ready_invoice_id": None,
            "status": "SUBMITTED",
            "_survey_id": None,
        })
        DB.applications[rec["id"]] = rec
        return object_response(S.application_json(rec), 201)

    @app.route("/joint-use/applications", methods=["GET"])
    def list_applications():
        _, role = X.current_actor()
        X.authorize(role, APP_READ)
        pole_id = request.args.get("pole_id")
        attacher_id = request.args.get("attacher_id")
        recs = [a for a in DB.applications.values()
                if (pole_id is None or a["pole_id"] == pole_id)
                and (attacher_id is None or a["attacher_id"] == attacher_id)]
        return _page(recs, S.application_json)

    @app.route("/joint-use/applications/<app_id>", methods=["GET"])
    def get_application(app_id):
        _, role = X.current_actor()
        X.authorize(role, APP_READ)
        rec = X.get_application(app_id)
        return object_response(S.application_json(rec), 200)

    # --- survey (SUBMITTED -> SURVEYED) --------------------------------------
    @app.route("/joint-use/applications/<app_id>/survey", methods=["POST"])
    def submit_survey(app_id):
        user_id, role = X.current_actor()
        X.authorize(role, ["Engineer"])
        appn = X.get_application(app_id)
        pole = DB.poles[appn["pole_id"]]
        body = X.get_body()
        crew = X.get_crew(X.req_str(body, "crew_id"))
        if crew["pole_owner_id"] != pole["pole_owner_id"]:
            raise ApiError("ERR_CREW_NOT_FOUND", "Crew does not belong to the pole's owner.")
        # Body validation.
        ws_raw, ws = X.req_datetime(body, "window_start")
        we_raw, we = X.req_datetime(body, "window_end")
        hours = X.req_number(body, "estimated_labor_hours", minimum=0)
        mr_required = X.req_bool(body, "make_ready_required")
        existing = X.req_int_min(body, "existing_attacher_count", 0)
        complexity = X.req_enum(body, "complexity_class", C.COMPLEXITY_CLASSES)
        findings = X.req_str(body, "findings")
        if we <= ws:
            raise ApiError("ERR_INVALID_WINDOW", "window_end must be after window_start.")
        # State.
        if appn["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Application is not SUBMITTED.")
        # Cross-entity guard.
        if pole["status"] != "ACTIVE":
            raise ApiError("ERR_POLE_NOT_ACTIVE", "Pole is not ACTIVE.")
        # Crew double-booking (half-open [start, end); adjacency allowed).
        for sv in DB.surveys.values():
            if sv["crew_id"] != crew["id"]:
                continue
            if ws < sv["_window_end_dt"] and sv["_window_start_dt"] < we:
                raise ApiError("ERR_CREW_DOUBLE_BOOKED", "Crew window overlaps an existing booking.")
        now = LOGICAL_CLOCK.now()
        survey = DB.new_record({
            "application_id": appn["id"],
            "crew_id": crew["id"],
            "surveyor_user_id": user_id,
            "window_start": ws_raw,
            "window_end": we_raw,
            "estimated_labor_hours": hours,
            "make_ready_required": mr_required,
            "existing_attacher_count": existing,
            "complexity_class": complexity,
            "findings": findings,
            "_window_start_dt": ws,
            "_window_end_dt": we,
        })
        DB.surveys[survey["id"]] = survey
        appn["status"] = "SURVEYED"
        appn["surveyor_user_id"] = user_id
        appn["make_ready_required"] = mr_required
        appn["surveyed_at"] = now
        appn["estimate_deadline"] = add_days(now, C.ESTIMATE_SHOT_CLOCK_DAYS)
        appn["_survey_id"] = survey["id"]
        touch(appn)
        return object_response(S.survey_json(survey), 201)

    # --- estimate issue / re-issue ------------------------------------------
    @app.route("/joint-use/applications/<app_id>/estimate", methods=["POST"])
    def issue_estimate(app_id):
        _, role = X.current_actor()
        X.authorize(role, ["Engineer"])
        appn = X.get_application(app_id)
        body = X.get_body()
        expected = X.req_int(body, "expected_application_version")
        if appn["status"] not in ("SURVEYED", "ESTIMATE_ISSUED"):
            raise ApiError("ERR_INVALID_STATE", "Application is not SURVEYED / ESTIMATE_ISSUED.")
        if expected != appn["version"]:
            raise ApiError("ERR_STALE_VERSION", "expected_application_version is stale.")
        owner, pole = _owner_of(appn)
        survey = DB.surveys[appn["_survey_id"]]
        now = LOGICAL_CLOCK.now()
        appn["make_ready_fee_estimate_cents"] = domain.make_ready_fee(
            owner, survey, survey["estimated_labor_hours"], "ESTIMATE")
        appn["annual_rental_fee_cents"] = domain.annual_line_cents(
            owner, appn["requested_space_inches"])
        appn["estimate_issued_at"] = now
        appn["estimate_expires_at"] = add_days(now, C.ESTIMATE_VALIDITY_DAYS)
        appn["status"] = "ESTIMATE_ISSUED"
        touch(appn)
        return object_response(S.application_json(appn), 200)

    # --- estimate decision (accept / reject) --------------------------------
    @app.route("/joint-use/applications/<app_id>/estimate-decision", methods=["POST"])
    def estimate_decision(app_id):
        user_id, role = X.current_actor()
        X.authorize(role, ["Attacher"])
        appn = X.get_application(app_id)
        X.require_owner(appn["attacher_id"], user_id)
        body = X.get_body()
        decision = X.req_enum(body, "decision", {"ACCEPT", "REJECT"})
        now = LOGICAL_CLOCK.now()
        # State.
        if appn["status"] == "ESTIMATE_EXPIRED" or (
                appn["status"] == "ESTIMATE_ISSUED"
                and appn["estimate_expires_at"] is not None
                and now > appn["estimate_expires_at"]):
            raise ApiError("ERR_ESTIMATE_EXPIRED", "The estimate has expired.")
        if appn["status"] != "ESTIMATE_ISSUED":
            raise ApiError("ERR_INVALID_STATE", "Application is not ESTIMATE_ISSUED.")
        if decision == "REJECT":
            appn["status"] = "ESTIMATE_REJECTED"
            touch(appn)
            return object_response(S.application_json(appn), 200)
        # ACCEPT
        owner, pole = _owner_of(appn)
        attacher = DB.attachers[appn["attacher_id"]]
        available = (pole["usable_communication_space_inches"]
                     - pole["occupied_space_inches"] - pole["reserved_space_inches"])
        if appn["requested_space_inches"] > available:
            raise ApiError("ERR_INSUFFICIENT_POLE_SPACE", "Not enough communication space.")
        fee = appn["make_ready_fee_estimate_cents"] or 0
        if attacher["account_balance_cents"] + fee > attacher["credit_limit_cents"]:
            raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", "Credit limit exceeded.")
        appn["reserved_space_inches"] = appn["requested_space_inches"]
        appn["estimate_accepted_at"] = now
        appn["permit_deadline"] = add_days(now, C.PERMIT_SHOT_CLOCK_DAYS)
        appn["status"] = "ESTIMATE_ACCEPTED"
        inv = domain.issue_invoice(attacher, "MAKE_READY", fee, [], application_id=appn["id"])
        appn["make_ready_invoice_id"] = inv["id"]
        touch(appn)
        domain.recompute_pole(pole)
        return object_response(S.application_json(appn), 200)

    # --- permit (grant / deny) ----------------------------------------------
    @app.route("/joint-use/applications/<app_id>/permit", methods=["POST"])
    def decide_permit(app_id):
        user_id, role = X.current_actor()
        X.authorize(role, ["PermitOfficer"])
        appn = X.get_application(app_id)
        body = X.get_body()
        decision = X.req_enum(body, "decision", {"GRANTED", "DENIED"})
        actual_hours = None
        if decision == "GRANTED":
            actual_hours = X.req_number(body, "actual_labor_hours", minimum=0)
        if appn["status"] != "ESTIMATE_ACCEPTED":
            raise ApiError("ERR_INVALID_STATE", "Application is not ESTIMATE_ACCEPTED.")
        if user_id == appn["surveyor_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", "Permit officer must differ from surveyor.")
        owner, pole = _owner_of(appn)
        attacher = DB.attachers[appn["attacher_id"]]
        now = LOGICAL_CLOCK.now()

        if decision == "DENIED":
            appn["permit_officer_user_id"] = user_id
            appn["permit_decision"] = "DENIED"
            appn["permit_issued_at"] = now
            appn["shot_clock_status"] = domain.compute_shot_clock_status(now, appn["permit_deadline"])
            appn["reserved_space_inches"] = 0
            appn["status"] = "PERMIT_DENIED"
            touch(appn)
            mr_inv = DB.invoices.get(appn["make_ready_invoice_id"])
            if mr_inv is not None and mr_inv["status"] in ("ISSUED", "OVERDUE"):
                domain.void_invoice(mr_inv)
            domain.recompute_pole(pole)
            return object_response(S.application_json(appn), 200)

        # GRANTED: clearance check.
        new_start = appn["requested_position_inches"]
        new_end = new_start + appn["requested_space_inches"]
        for att in DB.attachments.values():
            if att["pole_id"] != pole["id"] or att["status"] != "ACTIVE":
                continue
            ex_start = att["position_inches"]
            ex_end = ex_start + att["allotted_space_inches"]
            gap = max(ex_start - new_end, new_start - ex_end)
            if gap < C.CLEARANCE_INCHES:
                raise ApiError("ERR_CLEARANCE_VIOLATION", "Attachment violates vertical clearance.")

        appn["permit_officer_user_id"] = user_id
        appn["permit_decision"] = "GRANTED"
        appn["permit_issued_at"] = now
        appn["shot_clock_status"] = domain.compute_shot_clock_status(now, appn["permit_deadline"])
        survey = DB.surveys[appn["_survey_id"]]
        final_fee = domain.make_ready_fee(owner, survey, actual_hours, "FINAL")
        appn["make_ready_fee_final_cents"] = final_fee
        mr_inv = DB.invoices.get(appn["make_ready_invoice_id"])
        if mr_inv is not None:
            mr_inv["amount_cents"] = final_fee
            touch(mr_inv)
            domain.recompute_balance(attacher)
        # Create the attachment; convert reservation to occupancy.
        attachment = DB.new_record({
            "pole_id": pole["id"],
            "attacher_id": appn["attacher_id"],
            "application_id": appn["id"],
            "allotted_space_inches": appn["requested_space_inches"],
            "position_inches": appn["requested_position_inches"],
            "authorized": True,
            "transferred_from_attacher_id": None,
            "status": "ACTIVE",
        })
        DB.attachments[attachment["id"]] = attachment
        appn["reserved_space_inches"] = 0
        # First-year proration + ANNUAL_RENTAL invoice.
        rent = domain.first_year_proration_cents(owner, attachment["allotted_space_inches"], now)
        appn["annual_rental_fee_cents"] = rent
        appn["status"] = "PERMIT_GRANTED"
        touch(appn)
        domain.recompute_pole(pole)
        domain.issue_invoice(attacher, "ANNUAL_RENTAL", rent, [],
                             application_id=appn["id"])
        return object_response(S.application_json(appn), 200)

    # --- withdraw ------------------------------------------------------------
    @app.route("/joint-use/applications/<app_id>/withdraw", methods=["POST"])
    def withdraw_application(app_id):
        user_id, role = X.current_actor()
        X.authorize(role, ["Attacher"])
        appn = X.get_application(app_id)
        X.require_owner(appn["attacher_id"], user_id)
        if appn["status"] not in ("SUBMITTED", "SURVEYED", "ESTIMATE_ISSUED", "ESTIMATE_ACCEPTED"):
            raise ApiError("ERR_INVALID_STATE", "Application is terminal.")
        was_accepted = appn["status"] == "ESTIMATE_ACCEPTED"
        appn["status"] = "WITHDRAWN"
        if was_accepted:
            appn["reserved_space_inches"] = 0
        touch(appn)
        if was_accepted:
            _, pole = _owner_of(appn)
            mr_inv = DB.invoices.get(appn["make_ready_invoice_id"])
            if mr_inv is not None and mr_inv["status"] in ("ISSUED", "OVERDUE"):
                domain.void_invoice(mr_inv)
            domain.recompute_pole(pole)
        return object_response(S.application_json(appn), 200)

    # --- surveys read --------------------------------------------------------
    @app.route("/joint-use/surveys", methods=["GET"])
    def list_surveys():
        _, role = X.current_actor()
        X.authorize(role, SURVEY_READ)
        application_id = request.args.get("application_id")
        crew_id = request.args.get("crew_id")
        recs = [s for s in DB.surveys.values()
                if (application_id is None or s["application_id"] == application_id)
                and (crew_id is None or s["crew_id"] == crew_id)]
        return _page(recs, S.survey_json)

    @app.route("/joint-use/surveys/<survey_id>", methods=["GET"])
    def get_survey(survey_id):
        _, role = X.current_actor()
        X.authorize(role, SURVEY_READ)
        rec = X.get_survey(survey_id)
        return object_response(S.survey_json(rec), 200)
