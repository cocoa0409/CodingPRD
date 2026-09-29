"""Volunteers and certification records (PRD 3.1)."""

import response
from db import add_months, clock, db, new_row, ordered, plus_days, touch
from errors import ApiError
from middleware import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_TRAINING_COORDINATOR,
    ROLE_VOLUNTEER,
    ALL_ROLES,
    authenticate,
    body,
    bool_field,
    bool_query,
    date_field,
    enum_field,
    int_field,
    invalid,
    lookup,
    str_field,
    str_query,
)
from services import calc, domain
from services import serializers as ser
from services.calc import ZERO2

PASS_MARK = 80
RETAKE_COOLING_DAYS = 14
MAX_ATTEMPTS = 3


def _email_taken(email, exclude_id=None):
    for row in db.volunteers.values():
        if row["id"] == exclude_id:
            continue
        if row["email"] == email:
            return True
    return False


def grade_exam(cert, volunteer, score):
    cert["exam_score"] = score
    cert["attempt_count"] = cert["attempt_count"] + 1
    cert["last_attempt_at"] = clock.now
    if score >= PASS_MARK:
        cert["status"] = "PASSED"
        cert["issued_on"] = clock.now
        cert["expires_on"] = add_months(clock.now, 24)
        touch(cert)
        if volunteer is not None:
            domain.try_promote_to_certified(volunteer)
            # A record reaching PASSED is one of the five recompute triggers.
            domain.recompute_seniority(volunteer)
    else:
        cert["status"] = "FAILED"
        touch(cert)


def register(app):
    # ----------------------------------------------------------------- roster
    @app.post("/volunteers")
    def create_volunteer():
        authenticate(ROLE_TRAINING_COORDINATOR)
        data = body()
        legal_name = str_field(data, "legal_name", non_empty=True)
        email = str_field(data, "email", non_empty=True)
        role_track = enum_field(data, "role_track", calc.ROLE_TRACKS)
        start_date = date_field(data, "seniority_start_date")
        committee_seat = bool_field(data, "committee_seat", required=False, default=False)
        if start_date > clock.now.date():
            invalid("Field 'seniority_start_date' may not fall after the current station date.")
        if _email_taken(email):
            raise ApiError("ERR_DUPLICATE_KEY", "A volunteer with that email already exists.")
        row = new_row(db.volunteers, {
            "legal_name": legal_name,
            "email": email,
            "role_track": role_track,
            "seniority_start_date": start_date,
            "committee_seat": committee_seat,
            "status": "PROSPECT",
            "strike_count": 0,
            # Stored, not derived: enrolment pins the score at 0.00 however long
            # the seniority_start_date reaches back.  It is recomputed only at
            # the five triggers PRD 3.2 names.
            "seniority_score": ZERO2,
        })
        return response.created(ser.volunteer(row))

    @app.get("/volunteers")
    def list_volunteers():
        authenticate(*ALL_ROLES)
        status = str_query("status")
        role_track = str_query("role_track")
        seat = bool_query("committee_seat")

        def keep(row):
            if status is not None and row["status"] != status:
                return False
            if role_track is not None and row["role_track"] != role_track:
                return False
            if seat is not None and row["committee_seat"] is not seat:
                return False
            return True

        return response.listing(ordered(db.volunteers, keep), ser.volunteer)

    @app.get("/volunteers/<volunteer_id>")
    def get_volunteer(volunteer_id):
        authenticate(*ALL_ROLES)
        row = lookup(db.volunteers, volunteer_id, "ERR_VOLUNTEER_NOT_FOUND")
        return response.obj(ser.volunteer(row))

    @app.patch("/volunteers/<volunteer_id>")
    def patch_volunteer(volunteer_id):
        authenticate(ROLE_TRAINING_COORDINATOR, ROLE_PROGRAM_DIRECTOR)
        data = body()
        legal_name = str_field(data, "legal_name", required=False, non_empty=True)
        email = str_field(data, "email", required=False, non_empty=True)
        committee_seat = bool_field(data, "committee_seat", required=False, default=None)
        row = lookup(db.volunteers, volunteer_id, "ERR_VOLUNTEER_NOT_FOUND")
        if email is not None and _email_taken(email, exclude_id=row["id"]):
            raise ApiError("ERR_DUPLICATE_KEY", "A volunteer with that email already exists.")
        if row["status"] == "RESIGNED":
            raise ApiError("ERR_NOT_EDITABLE", "A resigned volunteer's record is closed.")
        changed = False
        if legal_name is not None:
            row["legal_name"] = legal_name
            changed = True
        if email is not None:
            row["email"] = email
            changed = True
        if committee_seat is not None:
            row["committee_seat"] = committee_seat
            changed = True
        if changed:
            touch(row)
        return response.obj(ser.volunteer(row))

    # -------------------------------------------------------- certifications
    @app.post("/volunteers/<volunteer_id>/certifications")
    def open_certification(volunteer_id):
        authenticate(ROLE_TRAINING_COORDINATOR)
        data = body()
        cert_type = enum_field(data, "cert_type", calc.CERT_TYPES)
        exam_score = int_field(data, "exam_score", 0, 100, required=False, default=None)
        volunteer = lookup(db.volunteers, volunteer_id, "ERR_VOLUNTEER_NOT_FOUND")
        first_record = not calc.volunteer_certifications(volunteer["id"])
        row = new_row(db.certifications, {
            "volunteer_id": volunteer["id"],
            "cert_type": cert_type,
            "status": "PENDING_EXAM",
            "exam_score": None,
            "attempt_count": 0,
            "issued_on": None,
            "expires_on": None,
            "last_attempt_at": None,
            "revocation_reason": None,
        })
        if first_record and volunteer["status"] == "PROSPECT":
            domain.set_volunteer_status(volunteer, "IN_TRAINING")
        if exam_score is not None:
            grade_exam(row, volunteer, exam_score)
        return response.created(ser.certification(row))

    @app.get("/volunteers/<volunteer_id>/certifications")
    def list_volunteer_certifications(volunteer_id):
        authenticate(
            ROLE_PROGRAM_DIRECTOR,
            ROLE_COMPLIANCE_OFFICER,
            ROLE_TRAINING_COORDINATOR,
            ROLE_VOLUNTEER,
        )
        response.pagination()
        volunteer = lookup(db.volunteers, volunteer_id, "ERR_VOLUNTEER_NOT_FOUND")
        cert_type = str_query("cert_type")
        status = str_query("status")

        def keep(row):
            if row["volunteer_id"] != volunteer["id"]:
                return False
            if cert_type is not None and row["cert_type"] != cert_type:
                return False
            if status is not None and row["status"] != status:
                return False
            return True

        return response.listing(ordered(db.certifications, keep), ser.certification)

    @app.get("/certifications")
    def list_certifications():
        authenticate(ROLE_PROGRAM_DIRECTOR, ROLE_COMPLIANCE_OFFICER, ROLE_TRAINING_COORDINATOR)
        volunteer_id = str_query("volunteer_id")
        cert_type = str_query("cert_type")
        status = str_query("status")

        def keep(row):
            if volunteer_id is not None and row["volunteer_id"] != volunteer_id:
                return False
            if cert_type is not None and row["cert_type"] != cert_type:
                return False
            if status is not None and row["status"] != status:
                return False
            return True

        return response.listing(ordered(db.certifications, keep), ser.certification)

    @app.get("/certifications/<certification_id>")
    def get_certification(certification_id):
        authenticate(
            ROLE_PROGRAM_DIRECTOR,
            ROLE_COMPLIANCE_OFFICER,
            ROLE_TRAINING_COORDINATOR,
            ROLE_VOLUNTEER,
        )
        row = lookup(db.certifications, certification_id, "ERR_CERTIFICATION_NOT_FOUND")
        return response.obj(ser.certification(row))

    @app.post("/certifications/<certification_id>/exam-results")
    def record_exam_result(certification_id):
        authenticate(ROLE_TRAINING_COORDINATOR)
        data = body()
        exam_score = int_field(data, "exam_score", 0, 100)
        row = lookup(db.certifications, certification_id, "ERR_CERTIFICATION_NOT_FOUND")
        if row["status"] != "PENDING_EXAM":
            raise ApiError("ERR_INVALID_STATE", "Only a record awaiting examination can be graded.")
        grade_exam(row, db.volunteers.get(row["volunteer_id"]), exam_score)
        return response.obj(ser.certification(row))

    @app.post("/certifications/<certification_id>/retake")
    def schedule_retake(certification_id):
        authenticate(ROLE_TRAINING_COORDINATOR)
        row = lookup(db.certifications, certification_id, "ERR_CERTIFICATION_NOT_FOUND")
        if row["status"] != "FAILED":
            raise ApiError("ERR_INVALID_STATE", "Only a failed record can be re-entered for examination.")
        if row["last_attempt_at"] is not None and clock.now < plus_days(row["last_attempt_at"], RETAKE_COOLING_DAYS):
            raise ApiError("ERR_RETAKE_TOO_SOON")
        if row["attempt_count"] >= MAX_ATTEMPTS:
            raise ApiError("ERR_MAX_ATTEMPTS_REACHED")
        row["status"] = "PENDING_EXAM"
        row["exam_score"] = None
        touch(row)
        return response.obj(ser.certification(row))

    @app.post("/certifications/<certification_id>/revoke")
    def revoke_certification(certification_id):
        authenticate(ROLE_COMPLIANCE_OFFICER)
        data = body()
        incident_id = str_field(data, "incident_id")
        revocation_reason = str_field(data, "revocation_reason")
        row = lookup(db.certifications, certification_id, "ERR_CERTIFICATION_NOT_FOUND")
        incident = lookup(db.incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")
        if (
            incident["status"] != "SUBSTANTIATED"
            or incident.get("respondent_volunteer_id") != row["volunteer_id"]
        ):
            raise ApiError("ERR_REVOCATION_UNSUPPORTED")
        if row["status"] != "PASSED":
            raise ApiError("ERR_INVALID_STATE", "Only a passed certification can be revoked.")
        row["status"] = "REVOKED"
        row["revocation_reason"] = revocation_reason
        touch(row)
        volunteer = db.volunteers.get(row["volunteer_id"])
        if volunteer is not None:
            domain.suspend_volunteer(volunteer)
            # A record reaching REVOKED is a recompute trigger in its own right.
            domain.recompute_seniority(volunteer)
        return response.obj(ser.certification(row))
