"""Enrollment lifecycle (PRD 3.3)."""

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

bp = Blueprint("enrollments", __name__)


def _occ_student(op):
    student = op.get("student")
    if op.body.get("expected_student_version") != student["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_student_version does not match the student's current version.",
        )


def _school_active(school):
    if school["program_status"] != "ACTIVE":
        raise ApiError("ERR_SCHOOL_SUSPENDED", "The site's program is suspended.")


@bp.post("/sbhc/students/<id>/enrollments")
def create_enrollment(id):
    op = Op("POST /sbhc/students/{id}/enrollments", ["Registrar"])
    op.path_id("student", "students", id, "ERR_STUDENT_NOT_FOUND")
    op.body_id("school", "schools", "school_id", "ERR_SCHOOL_NOT_FOUND")
    op.schema(
        [
            Field("school_id", "string", required=True),
            Field(
                "school_year", "enum", required=True, values=config.SUPPORTED_SCHOOL_YEARS
            ),
            Field("expected_student_version", "integer", required=True),
        ]
    )
    op.hook(10, _occ_student)
    op.hook(14, lambda o: _school_active(o.get("school")))
    op.run()

    student = op.get("student")
    school_year = op.body["school_year"]

    for existing in store.all_rows("enrollments"):
        if existing["student_id"] != id or existing["school_year"] != school_year:
            continue
        if existing["status"] in ("PENDING", "ACTIVE"):
            existing["status"] = "TRANSFERRED"
            existing["withdrawn_at"] = clock.now_iso()
            store.touch(existing)

    enrollment = store.new_row(
        "enrollments",
        {
            "student_id": id,
            "school_id": op.body["school_id"],
            "school_year": school_year,
            "status": "PENDING",
            "activated_at": None,
            "withdrawn_at": None,
            "withdrawal_reason": None,
            "reinstated_count": 0,
        },
    )
    store.touch(student)
    return envelope.created(serialize.dump(enrollment))


@bp.get("/sbhc/enrollments/<id>")
def read_enrollment(id):
    op = Op("GET /sbhc/enrollments/{id}", ["Registrar", "Clinician", "SbhcAdmin"])
    op.path_id("enrollment", "enrollments", id, "ERR_RESOURCE_NOT_FOUND")
    op.run()
    return envelope.ok(serialize.dump(op.get("enrollment")))


@bp.get("/sbhc/enrollments")
def list_enrollments():
    op = Op("GET /sbhc/enrollments", ["Registrar", "SbhcAdmin", "Clinician"])
    op.paginated()
    op.run()
    rows = store.all_rows("enrollments")
    rows = helpers.filter_eq(
        rows,
        op.args,
        {
            "student_id": "student_id",
            "school_id": "school_id",
            "school_year": "school_year",
            "status": "status",
        },
    )
    return helpers.list_response(rows, op)


@bp.post("/sbhc/enrollments/<id>/activate")
def activate_enrollment(id):
    op = Op("POST /sbhc/enrollments/{id}/activate", ["Registrar"])
    op.path_id("enrollment", "enrollments", id, "ERR_RESOURCE_NOT_FOUND")
    op.hook(14, lambda o: _school_active(store.get("schools", o.get("enrollment")["school_id"])))

    def _state(op):
        if op.get("enrollment")["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Only a PENDING enrollment may be activated.")

    op.hook(17, _state)
    op.run()

    enrollment = op.get("enrollment")
    enrollment["status"] = "ACTIVE"
    enrollment["activated_at"] = clock.now_iso()
    store.touch(enrollment)

    student = store.get("students", enrollment["student_id"])
    cascades.recompute_compliance(student, raise_events=True)
    store.touch(student)
    return envelope.ok(serialize.dump(enrollment))


@bp.post("/sbhc/enrollments/<id>/withdraw")
def withdraw_enrollment(id):
    op = Op("POST /sbhc/enrollments/{id}/withdraw", ["Registrar"])
    op.path_id("enrollment", "enrollments", id, "ERR_RESOURCE_NOT_FOUND")
    op.schema([Field("reason", "string", required=True)])

    def _state(op):
        if op.get("enrollment")["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE enrollment may be withdrawn.")

    op.hook(17, _state)
    op.run()

    enrollment = op.get("enrollment")
    enrollment["status"] = "WITHDRAWN"
    enrollment["withdrawn_at"] = clock.now_iso()
    enrollment["withdrawal_reason"] = op.body["reason"]
    store.touch(enrollment)

    for visit in store.all_rows("visits"):
        if visit["enrollment_id"] != enrollment["id"]:
            continue
        if visit["clinical_status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        visit["clinical_status"] = "CANCELLED"
        store.touch(visit)
        cascades.cancel_sessions_for_visit(visit, "CANCELLED")

    student = store.get("students", enrollment["student_id"])
    cascades.recompute_compliance(student, raise_events=True)
    store.touch(student)
    return envelope.ok(serialize.dump(enrollment))


@bp.post("/sbhc/enrollments/<id>/reinstate")
def reinstate_enrollment(id):
    op = Op("POST /sbhc/enrollments/{id}/reinstate", ["Registrar"])
    op.path_id("enrollment", "enrollments", id, "ERR_RESOURCE_NOT_FOUND")
    op.hook(14, lambda o: _school_active(store.get("schools", o.get("enrollment")["school_id"])))

    def _state(op):
        if op.get("enrollment")["status"] != "WITHDRAWN":
            raise ApiError("ERR_INVALID_STATE", "Only a WITHDRAWN enrollment may be reinstated.")

    def _cap(op):
        if op.get("enrollment")["reinstated_count"] >= config.MAX_ENROLLMENT_REINSTATEMENTS:
            raise ApiError(
                "ERR_REINSTATEMENT_LIMIT_EXCEEDED",
                "This enrollment has already been reinstated twice.",
            )

    op.hook(17, _state)
    op.hook(28, _cap)
    op.run()

    enrollment = op.get("enrollment")
    enrollment["status"] = "ACTIVE"
    enrollment["reinstated_count"] = enrollment["reinstated_count"] + 1
    enrollment["activated_at"] = clock.now_iso()
    enrollment["withdrawn_at"] = None
    store.touch(enrollment)

    student = store.get("students", enrollment["student_id"])
    cascades.recompute_compliance(student, raise_events=True)
    store.touch(student)
    return envelope.ok(serialize.dump(enrollment))
