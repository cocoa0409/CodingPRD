"""Immunization doses and the compliance cascade (PRD 3.7)."""

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

bp = Blueprint("immunizations", __name__)


def _doses_of(student_id, series_code):
    rows = [
        d
        for d in store.DB["doses"].values()
        if d["student_id"] == student_id and d["series_code"] == series_code
    ]
    rows.sort(key=lambda d: (d["dose_number"], d["created_at"], d["_seq"]))
    return rows


@bp.post("/sbhc/students/<id>/immunization-doses")
def record_dose(id):
    op = Op("POST /sbhc/students/{id}/immunization-doses", ["Clinician"])
    op.path_id("student", "students", id, "ERR_STUDENT_NOT_FOUND")
    op.body_id("visit", "visits", "visit_id", "ERR_VISIT_NOT_FOUND")
    op.schema(
        [
            Field("series_code", "enum", required=True, values=config.REQUIRED_SERIES),
            Field("dose_number", "integer", required=True, minimum=1),
            Field("administered_date", "date", required=True),
            Field("visit_id", "string"),
        ]
    )

    def _dose_number_range(op):
        maximum = config.SERIES_REQUIRED_DOSES[op.body["series_code"]]
        if op.body["dose_number"] > maximum:
            raise ApiError(
                "ERR_VALIDATION",
                "dose_number must be between 1 and %d for %s."
                % (maximum, op.body["series_code"]),
            )

    def _enrollment(op):
        if helpers.active_enrollment(id, None, clock.current_school_year()) is None:
            raise ApiError(
                "ERR_ENROLLMENT_NOT_ACTIVE",
                "The student holds no ACTIVE enrollment for the current school year.",
            )

    def _sequence(op):
        series = op.body["series_code"]
        highest = 0
        for dose in _doses_of(id, series):
            if dose["status"] == "VALID" and dose["dose_number"] > highest:
                highest = dose["dose_number"]
        if op.body["dose_number"] != highest + 1:
            raise ApiError(
                "ERR_DOSE_SEQUENCE",
                "dose_number must be exactly one more than the highest VALID dose.",
            )

    def _duplicate(op):
        series = op.body["series_code"]
        for dose in _doses_of(id, series):
            if dose["status"] == "VALID" and dose["dose_number"] == op.body["dose_number"]:
                raise ApiError(
                    "ERR_DUPLICATE_DOSE",
                    "A VALID dose already exists for this series and dose number.",
                )

    def _not_future(op):
        given = clock.parse_date(op.body["administered_date"])
        if given > clock.now_date():
            raise ApiError(
                "ERR_VALIDATION", "administered_date must not be after the current clock date."
            )

    op.custom(_dose_number_range)
    op.hook(15, _enrollment)
    op.hook(22, _sequence)
    op.hook(23, _duplicate)
    op.hook(24, _not_future)
    op.run()

    student = op.get("student")
    series = op.body["series_code"]
    dose_number = op.body["dose_number"]
    administered_date = op.body["administered_date"]

    earliest, strict, status, reason = calc.dose_validity(
        student, series, dose_number, administered_date
    )

    dose = store.new_row(
        "doses",
        {
            "student_id": id,
            "visit_id": op.field("visit_id", None),
            "series_code": series,
            "dose_number": dose_number,
            "administered_date": administered_date,
            "earliest_valid_date": earliest,
            "strict_earliest_valid_date": strict,
            "status": status,
            "invalid_reason": reason,
            "void_reason": None,
        },
    )

    cascades.recompute_dose_counters(student)
    cascades.recompute_compliance(student, raise_events=True)
    store.touch(student)
    return envelope.created(serialize.dump(dose))


@bp.get("/sbhc/immunization-doses/<id>")
def read_dose(id):
    op = Op("GET /sbhc/immunization-doses/{id}", ["Clinician", "Registrar", "SbhcAdmin"])
    op.path_id("dose", "doses", id, "ERR_RESOURCE_NOT_FOUND")
    op.run()
    return envelope.ok(serialize.dump(op.get("dose")))


@bp.get("/sbhc/immunization-doses")
def list_doses():
    op = Op("GET /sbhc/immunization-doses", ["Clinician", "Registrar", "SbhcAdmin"])
    op.paginated()
    op.run()
    rows = store.all_rows("doses")
    rows = helpers.filter_eq(
        rows,
        op.args,
        {
            "student_id": "student_id",
            "visit_id": "visit_id",
            "series_code": "series_code",
            "status": "status",
        },
    )
    return helpers.list_response(rows, op)


@bp.post("/sbhc/immunization-doses/<id>/void")
def void_dose(id):
    op = Op("POST /sbhc/immunization-doses/{id}/void", ["Clinician"])
    op.path_id("dose", "doses", id, "ERR_RESOURCE_NOT_FOUND")
    op.schema([Field("reason", "string", required=True)])

    def _state(op):
        if op.get("dose")["status"] == "VOIDED":
            raise ApiError("ERR_INVALID_STATE", "This dose is already VOIDED.")

    op.hook(17, _state)
    op.run()

    dose = op.get("dose")
    student = store.get("students", dose["student_id"])

    # Link 1 — the dose itself stops counting.
    dose["status"] = "VOIDED"
    dose["void_reason"] = op.body["reason"]
    store.touch(dose)

    # Link 2 — every later dose that has lost its VALID predecessor follows.
    for later in _doses_of(dose["student_id"], dose["series_code"]):
        if later["dose_number"] <= dose["dose_number"]:
            continue
        if later["status"] != "VALID":
            continue
        predecessor = calc.find_predecessor(
            dose["student_id"], dose["series_code"], later["dose_number"]
        )
        if predecessor is None:
            later["status"] = "INVALID_TOO_EARLY"
            later["invalid_reason"] = "PREDECESSOR_VOIDED"
            store.touch(later)

    # Links 3-5 — counters, posture, clearance void and the two notifications.
    cascades.recompute_dose_counters(student)
    cascades.recompute_compliance(student, raise_events=True)
    store.touch(student)
    return envelope.ok(serialize.dump(dose))
