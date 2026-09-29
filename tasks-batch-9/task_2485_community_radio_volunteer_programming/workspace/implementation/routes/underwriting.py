"""Underwriting copy and compliance incidents (PRD 3.6, 3.7)."""

import response
from db import clock, db, new_row, ordered, plus_days, touch
from errors import ApiError
from middleware import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DEVELOPMENT_COORDINATOR,
    ROLE_PROGRAM_DIRECTOR,
    authenticate,
    body,
    caller_id,
    datetime_field,
    enum_field,
    invalid,
    lookup,
    optional_lookup,
    str_field,
    str_query,
)
from services import calc, domain
from services import serializers as ser
from services.records import create_incident_row

FINDINGS = ("SUBSTANTIATED", "UNFOUNDED")
PUBLIC_FILE_CLASSES = ("POLITICAL_CANDIDATE", "ISSUE_ADVOCACY")
APPROVED_SPOT_STATUSES = ("APPROVED", "APPROVED_WITH_EDITS")

SPOT_READ_ROLES = (ROLE_PROGRAM_DIRECTOR, ROLE_COMPLIANCE_OFFICER, ROLE_DEVELOPMENT_COORDINATOR)
INCIDENT_READ_ROLES = (ROLE_PROGRAM_DIRECTOR, ROLE_COMPLIANCE_OFFICER)


def register(app):
    # ------------------------------------------------------- underwriting copy
    @app.post("/underwriting-spots")
    def create_spot():
        authenticate(ROLE_DEVELOPMENT_COORDINATOR)
        data = body()
        underwriter_name = str_field(data, "underwriter_name", non_empty=True)
        spot_class = enum_field(data, "spot_class", calc.SPOT_CLASSES)
        copy_text = str_field(data, "copy_text", non_empty=True)
        flight_start = datetime_field(data, "flight_start")
        flight_end = datetime_field(data, "flight_end")
        assigned_program_id = str_field(data, "assigned_program_id", required=False, default=None)
        if flight_end <= flight_start:
            raise ApiError("ERR_INVALID_INTERVAL")
        optional_lookup(db.programs, assigned_program_id, "ERR_PROGRAM_NOT_FOUND")
        spot = new_row(db.spots, {
            "underwriter_name": underwriter_name,
            "spot_class": spot_class,
            "copy_text": copy_text,
            "approved_copy_text": None,
            "assigned_program_id": assigned_program_id,
            "flight_start": flight_start,
            "flight_end": flight_end,
            "status": "DRAFT",
            "noncommercial_risk_score": 0,
            "compliance_flags": [],
            "reviewed_by_user_id": None,
            "public_file_status": "NOT_REQUIRED",
            "public_file_due_at": None,
            "public_file_posted_at": None,
            "public_file_reference": None,
        })
        return response.created(ser.spot(spot))

    @app.get("/underwriting-spots")
    def list_spots():
        authenticate(*SPOT_READ_ROLES)
        status = str_query("status")
        spot_class = str_query("spot_class")
        public_file_status = str_query("public_file_status")
        assigned_program_id = str_query("assigned_program_id")

        def keep(row):
            if status is not None and row["status"] != status:
                return False
            if spot_class is not None and row["spot_class"] != spot_class:
                return False
            if public_file_status is not None and row["public_file_status"] != public_file_status:
                return False
            if assigned_program_id is not None and row["assigned_program_id"] != assigned_program_id:
                return False
            return True

        return response.listing(ordered(db.spots, keep), ser.spot)

    @app.get("/underwriting-spots/<spot_id>")
    def get_spot(spot_id):
        authenticate(*SPOT_READ_ROLES)
        spot = lookup(db.spots, spot_id, "ERR_SPOT_NOT_FOUND")
        return response.obj(ser.spot(spot))

    @app.patch("/underwriting-spots/<spot_id>")
    def patch_spot(spot_id):
        authenticate(ROLE_DEVELOPMENT_COORDINATOR)
        data = body()
        copy_text = str_field(data, "copy_text", required=False, non_empty=True)
        flight_start = datetime_field(data, "flight_start", required=False)
        flight_end = datetime_field(data, "flight_end", required=False)
        assigned_program_id = str_field(data, "assigned_program_id", required=False, default=None)

        existing = db.spots.get(spot_id)
        if existing is not None:
            effective_start = flight_start or existing["flight_start"]
            effective_end = flight_end or existing["flight_end"]
            if effective_end <= effective_start:
                raise ApiError("ERR_INVALID_INTERVAL")
        spot = lookup(db.spots, spot_id, "ERR_SPOT_NOT_FOUND")
        optional_lookup(db.programs, assigned_program_id, "ERR_PROGRAM_NOT_FOUND")
        if spot["status"] != "DRAFT":
            raise ApiError("ERR_NOT_EDITABLE", "Only draft copy can be revised.")
        changed = False
        for field, value in (
            ("copy_text", copy_text),
            ("flight_start", flight_start),
            ("flight_end", flight_end),
            ("assigned_program_id", assigned_program_id),
        ):
            if value is not None:
                spot[field] = value
                changed = True
        if changed:
            touch(spot)
        return response.obj(ser.spot(spot))

    @app.post("/underwriting-spots/<spot_id>/submit-for-review")
    def submit_spot(spot_id):
        authenticate(ROLE_DEVELOPMENT_COORDINATOR)
        spot = lookup(db.spots, spot_id, "ERR_SPOT_NOT_FOUND")
        if spot["spot_class"] in PUBLIC_FILE_CLASSES and not spot["assigned_program_id"]:
            invalid("Field 'assigned_program_id' is required for political and issue advocacy copy.")
        if spot["flight_end"] <= spot["flight_start"]:
            raise ApiError("ERR_INVALID_INTERVAL")
        if spot["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Only draft copy can be sent for review.")
        spot["status"] = "UNDER_REVIEW"
        touch(spot)
        return response.obj(ser.spot(spot))

    @app.post("/underwriting-spots/<spot_id>/review")
    def review_spot(spot_id):
        authenticate(ROLE_COMPLIANCE_OFFICER)
        data = body()
        edited_copy_text = str_field(data, "edited_copy_text", required=False, default=None)
        spot = lookup(db.spots, spot_id, "ERR_SPOT_NOT_FOUND")
        if spot["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "Only copy under review can be resolved.")
        if edited_copy_text is not None:
            if calc.edited_copy_score(edited_copy_text, spot["underwriter_name"]) >= 25:
                raise ApiError("ERR_EDITED_COPY_STILL_NONCOMPLIANT")
            if spot["spot_class"] == "POLITICAL_CANDIDATE":
                raise ApiError("ERR_POLITICAL_COPY_UNCENSORABLE")

        score, flags = calc.risk_screen(spot["copy_text"], spot["underwriter_name"], spot["spot_class"])
        # The stored screen always describes the copy as drafted.
        spot["noncommercial_risk_score"] = score
        spot["compliance_flags"] = flags
        spot["reviewed_by_user_id"] = caller_id()

        if spot["spot_class"] == "POLITICAL_CANDIDATE" or score < 25:
            spot["status"] = "APPROVED"
            spot["approved_copy_text"] = spot["copy_text"]
        elif score >= 60:
            spot["status"] = "REJECTED"
            spot["approved_copy_text"] = None
            spot["public_file_status"] = "NOT_REQUIRED"
        elif edited_copy_text is not None:
            spot["status"] = "APPROVED_WITH_EDITS"
            spot["approved_copy_text"] = edited_copy_text
        else:
            spot["status"] = "REJECTED"
            spot["approved_copy_text"] = None
            spot["public_file_status"] = "NOT_REQUIRED"

        if spot["status"] in APPROVED_SPOT_STATUSES and spot["spot_class"] in PUBLIC_FILE_CLASSES:
            spot["public_file_status"] = "REQUIRED"
            spot["public_file_due_at"] = plus_days(clock.now, 7)
        touch(spot)
        return response.obj(ser.spot(spot))

    @app.post("/underwriting-spots/<spot_id>/public-file-posting")
    def post_public_file(spot_id):
        authenticate(ROLE_COMPLIANCE_OFFICER)
        data = body()
        reference = str_field(data, "public_file_reference", non_empty=True)
        spot = lookup(db.spots, spot_id, "ERR_SPOT_NOT_FOUND")
        if spot["public_file_status"] not in ("REQUIRED", "MISSING"):
            raise ApiError("ERR_PUBLIC_FILE_NOT_REQUIRED")
        if spot["public_file_status"] == "REQUIRED" and (
            spot["public_file_due_at"] is None or clock.now < spot["public_file_due_at"]
        ):
            spot["public_file_status"] = "POSTED"
        else:
            spot["public_file_status"] = "LATE_POSTED"
        spot["public_file_posted_at"] = clock.now
        spot["public_file_reference"] = reference
        touch(spot)
        return response.obj(ser.spot(spot))

    # --------------------------------------------------------------- incidents
    @app.post("/compliance-incidents")
    def create_incident():
        authenticate(ROLE_COMPLIANCE_OFFICER, ROLE_PROGRAM_DIRECTOR)
        data = body()
        category = enum_field(data, "category", calc.INCIDENT_CATEGORIES)
        severity = enum_field(data, "severity", calc.SEVERITIES)
        sanction = enum_field(data, "sanction", calc.SANCTIONS, required=False, default="NONE")
        complainant_note = str_field(data, "complainant_note")
        occurred_at = datetime_field(data, "occurred_at")
        program_id = str_field(data, "program_id", required=False, default=None)
        episode_id = str_field(data, "episode_id", required=False, default=None)
        spot_id = str_field(data, "underwriting_spot_id", required=False, default=None)
        respondent_id = str_field(data, "respondent_volunteer_id", required=False, default=None)

        optional_lookup(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
        optional_lookup(db.episodes, episode_id, "ERR_EPISODE_NOT_FOUND")
        optional_lookup(db.spots, spot_id, "ERR_SPOT_NOT_FOUND")
        respondent = optional_lookup(db.volunteers, respondent_id, "ERR_VOLUNTEER_NOT_FOUND")

        if category != "VOLUNTEER_CONFLICT" and not program_id:
            raise ApiError("ERR_INCIDENT_TARGET_REQUIRED", "This category must name the show it touches.")
        if category == "INDECENCY" and not episode_id:
            raise ApiError("ERR_INCIDENT_TARGET_REQUIRED", "An indecency complaint must name the airing.")
        if category in ("SPONSOR_ID", "PUBLIC_FILE") and not spot_id:
            raise ApiError("ERR_INCIDENT_TARGET_REQUIRED", "This category must name the underwriting spot.")
        if category == "VOLUNTEER_CONFLICT" and not respondent_id:
            raise ApiError("ERR_INCIDENT_TARGET_REQUIRED", "A conflict complaint must name the respondent.")
        if sanction != "NONE" and not respondent_id:
            raise ApiError("ERR_INCIDENT_TARGET_REQUIRED", "A sanction requires a named respondent.")

        safe_harbor = calc.safe_harbor_violation(category, occurred_at)
        points = calc.penalty_points(category, severity, safe_harbor)
        incident = create_incident_row(
            category=category,
            severity=severity,
            program_id=program_id,
            episode_id=episode_id,
            underwriting_spot_id=spot_id,
            respondent_volunteer_id=respondent_id,
            complainant_note=complainant_note,
            occurred_at=occurred_at,
            sanction=sanction,
            status="OPEN",
            safe_harbor=safe_harbor,
            points=points,
        )
        return response.created(ser.incident(incident))

    @app.get("/compliance-incidents")
    def list_incidents():
        authenticate(*INCIDENT_READ_ROLES)
        category = str_query("category")
        status = str_query("status")
        program_id = str_query("program_id")
        episode_id = str_query("episode_id")
        spot_id = str_query("underwriting_spot_id")
        respondent_id = str_query("respondent_volunteer_id")
        severity = str_query("severity")

        def keep(row):
            if category is not None and row["category"] != category:
                return False
            if status is not None and row["status"] != status:
                return False
            if program_id is not None and row["program_id"] != program_id:
                return False
            if episode_id is not None and row["episode_id"] != episode_id:
                return False
            if spot_id is not None and row["underwriting_spot_id"] != spot_id:
                return False
            if respondent_id is not None and row["respondent_volunteer_id"] != respondent_id:
                return False
            if severity is not None and row["severity"] != severity:
                return False
            return True

        return response.listing(ordered(db.incidents, keep), ser.incident)

    @app.get("/compliance-incidents/<incident_id>")
    def get_incident(incident_id):
        authenticate(*INCIDENT_READ_ROLES)
        incident = lookup(db.incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")
        return response.obj(ser.incident(incident))

    @app.post("/compliance-incidents/<incident_id>/adjudicate")
    def adjudicate_incident(incident_id):
        authenticate(ROLE_COMPLIANCE_OFFICER)
        data = body()
        finding = enum_field(data, "finding", FINDINGS)
        incident = lookup(db.incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")

        spot = db.spots.get(incident.get("underwriting_spot_id")) if incident.get("underwriting_spot_id") else None
        if spot is not None and spot["reviewed_by_user_id"] and spot["reviewed_by_user_id"] == caller_id():
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        if incident["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Only an open incident can be adjudicated.")

        incident["adjudicated_by_user_id"] = caller_id()
        if finding == "UNFOUNDED":
            incident["status"] = "UNFOUNDED"
            touch(incident)
            return response.obj(ser.incident(incident))

        program = db.programs.get(incident.get("program_id")) if incident.get("program_id") else None
        standing_before = domain.program_standing(program) if program is not None else None
        incident["status"] = "SUBSTANTIATED"
        touch(incident)
        if program is not None:
            domain.resettle_standing(program, standing_before)
        if spot is not None and spot["status"] in APPROVED_SPOT_STATUSES:
            spot["status"] = "SUSPENDED"
            touch(spot)
        respondent = db.volunteers.get(incident.get("respondent_volunteer_id")) if incident.get("respondent_volunteer_id") else None
        domain.apply_sanction(incident, respondent)
        return response.obj(ser.incident(incident))

    @app.post("/compliance-incidents/<incident_id>/remediate")
    def remediate_incident(incident_id):
        authenticate(ROLE_COMPLIANCE_OFFICER)
        data = body()
        remediation_note = str_field(data, "remediation_note", non_empty=True)
        incident = lookup(db.incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")
        if incident["status"] != "SUBSTANTIATED":
            raise ApiError("ERR_INVALID_STATE", "Only a substantiated incident can be remediated.")

        program = db.programs.get(incident.get("program_id")) if incident.get("program_id") else None
        standing_before = domain.program_standing(program) if program is not None else None
        incident["status"] = "REMEDIATED"
        incident["remediation_note"] = remediation_note
        touch(incident)
        if program is not None:
            # Exactly the frozen charge comes back off; preempted airtime and
            # cancelled airings stay exactly as the restriction left them.
            domain.resettle_standing(program, standing_before)
        if incident["sanction"] == "SUSPENSION":
            respondent = db.volunteers.get(incident.get("respondent_volunteer_id")) if incident.get("respondent_volunteer_id") else None
            if respondent is not None and respondent["status"] == "SUSPENDED":
                domain.set_volunteer_status(respondent, "PROBATION")
        return response.obj(ser.incident(incident))
