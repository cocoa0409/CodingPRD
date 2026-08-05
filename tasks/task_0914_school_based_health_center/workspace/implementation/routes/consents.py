"""Consent lifecycle (PRD 3.4)."""

from flask import Blueprint

import clock
import config
import envelope
import helpers
import store
from errors import ApiError
from fields import Field
from ladder import Op
from services import cascades, serialize

bp = Blueprint("consents", __name__)


@bp.post("/sbhc/students/<id>/consents")
def create_consent(id):
    op = Op("POST /sbhc/students/{id}/consents", ["Registrar", "Student"])
    op.path_id("student", "students", id, "ERR_STUDENT_NOT_FOUND")
    op.schema(
        [
            Field("category", "enum", required=True, values=config.CONSENT_CATEGORIES),
            Field("school_year", "enum", required=True, values=config.SUPPORTED_SCHOOL_YEARS),
            Field("granted_by", "enum", required=True, values=config.GRANTED_BY_VALUES),
            Field("granted_by_user_id", "string", required=True, min_len=1),
            Field("expected_student_version", "integer", required=True),
        ]
    )

    def _grantor_resolves(op):
        # PRD 3.4: a GUARDIAN grantor must be a guardian row of THIS student.
        # Ladder rung 5 does not cover this endpoint, so the failure is a
        # body-well-formedness failure at rung 6.
        if op.body["granted_by"] != "GUARDIAN":
            return
        guardian = store.get("guardians", op.body["granted_by_user_id"])
        if guardian is None or guardian["student_id"] != id:
            raise ApiError(
                "ERR_VALIDATION",
                "granted_by_user_id must name a guardian of this student.",
            )

    def _occ(op):
        if op.body["expected_student_version"] != op.get("student")["version"]:
            raise ApiError(
                "ERR_STALE_VERSION",
                "expected_student_version does not match the student's current version.",
            )

    def _ownership(op):
        if op.role == "Student" and op.user_id != id:
            raise ApiError(
                "ERR_OWNERSHIP_VIOLATION",
                "A student may only record a consent on their own record.",
            )

    def _self_consent(op):
        if op.body["granted_by"] != "STUDENT_SELF":
            return
        if op.body["category"] not in config.SELF_CONSENTABLE_CATEGORIES:
            raise ApiError(
                "ERR_SELF_CONSENT_NOT_PERMITTED",
                "This category may not be self-consented.",
            )
        student = op.get("student")
        born = clock.parse_date(student["date_of_birth"])
        age = clock.whole_years_between(born, clock.now_date())
        if age < config.SELF_CONSENT_MIN_AGE_YEARS:
            raise ApiError(
                "ERR_SELF_CONSENT_NOT_PERMITTED",
                "The student is below the minor-consent age threshold.",
            )

    op.custom(_grantor_resolves)
    op.hook(10, _occ)
    op.hook(11, _ownership)
    op.hook(12, _self_consent)
    op.run()

    student = op.get("student")
    category = op.body["category"]
    school_year = op.body["school_year"]

    for existing in store.all_rows("consents"):
        if (
            existing["student_id"] == id
            and existing["category"] == category
            and existing["school_year"] == school_year
            and existing["status"] == "ACTIVE"
        ):
            existing["status"] = "SUPERSEDED"
            store.touch(existing)

    consent = store.new_row(
        "consents",
        {
            "student_id": id,
            "category": category,
            "school_year": school_year,
            "granted_by": op.body["granted_by"],
            "granted_by_user_id": op.body["granted_by_user_id"],
            "status": "ACTIVE",
            "effective_at": clock.now_iso(),
            "expires_at": clock.school_year_end_instant(school_year),
            "revoked_at": None,
            "revocation_reason": None,
        },
    )
    store.touch(student)
    return envelope.created(serialize.dump(consent))


@bp.get("/sbhc/students/<id>/consents")
def list_consents(id):
    op = Op(
        "GET /sbhc/students/{id}/consents",
        ["Registrar", "Clinician", "SbhcAdmin", "Student"],
    )
    op.path_id("student", "students", id, "ERR_STUDENT_NOT_FOUND")
    op.paginated()
    op.run()
    rows = [c for c in store.all_rows("consents") if c["student_id"] == id]
    rows = helpers.filter_eq(
        rows,
        op.args,
        {"category": "category", "status": "status", "school_year": "school_year"},
    )
    return helpers.list_response(rows, op)


@bp.post("/sbhc/consents/<id>/revoke")
def revoke_consent(id):
    op = Op("POST /sbhc/consents/{id}/revoke", ["Registrar", "Guardian", "Student"])
    op.path_id("consent", "consents", id, "ERR_RESOURCE_NOT_FOUND")
    op.schema([Field("reason", "string", required=True)])

    def _ownership(op):
        if op.role in ("Guardian", "Student"):
            if op.user_id != op.get("consent")["granted_by_user_id"]:
                raise ApiError(
                    "ERR_OWNERSHIP_VIOLATION",
                    "Only the grantor may revoke this consent.",
                )

    def _state(op):
        if op.get("consent")["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE consent may be revoked.")

    op.hook(11, _ownership)
    op.hook(17, _state)
    op.run()

    consent = op.get("consent")
    consent["status"] = "REVOKED"
    consent["revoked_at"] = clock.now_iso()
    consent["revocation_reason"] = op.body["reason"]
    store.touch(consent)

    if consent["category"] == "TELEHEALTH":
        for session in store.all_rows("sessions"):
            if session["status"] != "SCHEDULED":
                continue
            visit = store.get("visits", session["visit_id"])
            if visit is None or visit["student_id"] != consent["student_id"]:
                continue
            cascades.move_session(session, "CANCELLED")
            if visit["clinical_status"] in ("SCHEDULED", "IN_PROGRESS"):
                visit["clinical_status"] = "CANCELLED"
                store.touch(visit)

    return envelope.ok(serialize.dump(consent))
