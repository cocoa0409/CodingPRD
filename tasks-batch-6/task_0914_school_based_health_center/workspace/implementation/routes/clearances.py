"""Sports-physical clearance (PRD 3.9)."""

from flask import Blueprint

import clock
import config
import envelope
import helpers
import store
from errors import ApiError
from fields import Field
from ladder import Op
from services import calc, cascades, serialize
from services.notifications import raise_notification

bp = Blueprint("clearances", __name__)


def _restrictions_present(op):
    if op.body.get("outcome") == "CLEARED_WITH_RESTRICTIONS":
        restrictions = op.body.get("restrictions")
        if not isinstance(restrictions, str) or not restrictions:
            raise ApiError(
                "ERR_VALIDATION",
                "restrictions is required when outcome is CLEARED_WITH_RESTRICTIONS.",
            )


@bp.post("/sbhc/visits/<id>/sports-clearances")
def create_clearance(id):
    op = Op("POST /sbhc/visits/{id}/sports-clearances", ["Clinician"])
    op.path_id("visit", "visits", id, "ERR_VISIT_NOT_FOUND")
    op.schema(
        [
            Field("outcome", "enum", required=True, values=config.CLEARANCE_OUTCOMES),
            Field("expected_student_version", "integer", required=True),
            Field("restrictions", "string"),
        ]
    )
    op.custom(_restrictions_present)

    def _occ(op):
        student = store.get("students", op.get("visit")["student_id"])
        op.rows["student"] = student
        if op.body["expected_student_version"] != student["version"]:
            raise ApiError(
                "ERR_STALE_VERSION",
                "expected_student_version does not match the student's current version.",
            )

    def _state(op):
        visit = op.get("visit")
        if visit["visit_type"] != "SPORTS_PHYSICAL":
            raise ApiError(
                "ERR_INVALID_STATE", "Only a SPORTS_PHYSICAL encounter yields a clearance."
            )
        if visit["clinical_status"] not in ("IN_PROGRESS", "COMPLETED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                "The encounter must be IN_PROGRESS or COMPLETED.",
            )

    def _immunization(op):
        if op.get("student")["immunization_compliance_status"] == "NON_COMPLIANT":
            raise ApiError(
                "ERR_IMMUNIZATION_NON_COMPLIANT",
                "The student's immunization posture is NON_COMPLIANT.",
            )

    op.hook(10, _occ)
    op.hook(17, _state)
    op.hook(21, _immunization)
    op.run()

    visit = op.get("visit")
    student = op.get("student")
    outcome = op.body["outcome"]
    enrollment = store.get("enrollments", visit["enrollment_id"])
    school_year = helpers.school_year_of_enrollment(enrollment)
    determination_date = clock.now_date()

    cascades.supersede_clearances(student["id"], school_year)

    unrestricted, operative = calc.clearance_validity(outcome, determination_date, school_year)
    clearance = store.new_row(
        "clearances",
        {
            "visit_id": visit["id"],
            "student_id": student["id"],
            "school_year": school_year,
            "outcome": outcome,
            "restrictions": op.field("restrictions", None),
            "determination_date": clock.format_date(determination_date),
            "unrestricted_valid_until": unrestricted,
            "valid_until": operative,
            "reevaluation_count": 0,
            "status": "PENDING_REEVALUATION" if outcome == "DEFERRED" else "ACTIVE",
            "void_reason": None,
        },
    )
    store.touch(student)
    raise_notification("CLEARANCE_DETERMINED", student["id"], visit)
    return envelope.created(serialize.dump(clearance))


@bp.get("/sbhc/sports-clearances/<id>")
def read_clearance(id):
    op = Op("GET /sbhc/sports-clearances/{id}", ["Clinician", "Registrar", "SbhcAdmin"])
    op.path_id("clearance", "clearances", id, "ERR_RESOURCE_NOT_FOUND")
    op.run()
    return envelope.ok(serialize.dump(op.get("clearance")))


@bp.get("/sbhc/sports-clearances")
def list_clearances():
    op = Op("GET /sbhc/sports-clearances", ["Clinician", "Registrar", "SbhcAdmin"])
    op.paginated()
    op.run()
    rows = store.all_rows("clearances")
    rows = helpers.filter_eq(
        rows, op.args, {"student_id": "student_id", "visit_id": "visit_id", "status": "status"}
    )
    return helpers.list_response(rows, op)


@bp.post("/sbhc/sports-clearances/<id>/re-evaluate")
def reevaluate_clearance(id):
    op = Op("POST /sbhc/sports-clearances/{id}/re-evaluate", ["Clinician"])
    op.path_id("clearance", "clearances", id, "ERR_RESOURCE_NOT_FOUND")
    op.schema(
        [
            Field("outcome", "enum", required=True, values=config.CLEARANCE_OUTCOMES),
            Field("restrictions", "string"),
        ]
    )
    op.custom(_restrictions_present)

    def _state(op):
        clearance = op.get("clearance")
        if clearance["status"] != "PENDING_REEVALUATION":
            raise ApiError(
                "ERR_INVALID_STATE",
                "Only a PENDING_REEVALUATION clearance may be re-evaluated.",
            )
        deadline = clock.add_days(
            clock.parse_date(clearance["determination_date"]),
            config.DEFERRAL_REEVALUATION_WINDOW_DAYS,
        )
        if clock.now_date() > deadline:
            raise ApiError(
                "ERR_INVALID_STATE", "The 30-day deferral window has closed."
            )

    def _immunization(op):
        # PRD 3.9: only a non-DEFERRED re-evaluation re-checks the posture.
        if op.body["outcome"] == "DEFERRED":
            return
        student = store.get("students", op.get("clearance")["student_id"])
        if student is not None and student["immunization_compliance_status"] == "NON_COMPLIANT":
            raise ApiError(
                "ERR_IMMUNIZATION_NON_COMPLIANT",
                "The student's immunization posture is NON_COMPLIANT.",
            )

    def _cap(op):
        if op.get("clearance")["reevaluation_count"] >= config.MAX_DEFERRAL_REEVALUATIONS:
            raise ApiError(
                "ERR_REEVALUATION_LIMIT_EXCEEDED",
                "This clearance has already been re-evaluated twice.",
            )

    op.hook(17, _state)
    op.hook(21, _immunization)
    op.hook(29, _cap)
    op.run()

    clearance = op.get("clearance")
    outcome = op.body["outcome"]
    determination_date = clock.now_date()
    clearance["reevaluation_count"] = clearance["reevaluation_count"] + 1
    clearance["determination_date"] = clock.format_date(determination_date)

    if outcome == "DEFERRED":
        clearance["unrestricted_valid_until"] = None
        clearance["valid_until"] = None
    else:
        clearance["outcome"] = outcome
        clearance["restrictions"] = op.field("restrictions", clearance["restrictions"])
        unrestricted, operative = calc.clearance_validity(
            outcome, determination_date, clearance["school_year"]
        )
        clearance["unrestricted_valid_until"] = unrestricted
        clearance["valid_until"] = operative
        clearance["status"] = "ACTIVE"

    store.touch(clearance)
    return envelope.ok(serialize.dump(clearance))
