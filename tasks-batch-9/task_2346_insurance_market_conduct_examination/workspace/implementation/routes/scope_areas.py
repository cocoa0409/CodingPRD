"""Scope-area reads and data-call issuance (PRD §3.4)."""

from flask import Blueprint

import validation as v
from db import day_diff, db, new_record, today_str
from errors import ApiError
from middleware import ROLE_EXAMINER_IN_CHARGE, authorize
from response import paginated, success
from routes.common import filter_equals, str_query
from routes.examinations import EXAM_RECORD_READ_ROLES
from services import calculations as calc
from services import derive, serialize
from services.guards import ensure_exam_subject, ensure_exam_writable, get_area

bp = Blueprint("scope_areas", __name__)

SAMPLING_METHODS = ("SYSTEMATIC_INTERVAL",)
LIVE_DATA_CALL_STATUSES = ("ISSUED", "OVERDUE", "RESPONDED", "ACCEPTED")


@bp.get("/scope-areas/<area_id>")
@authorize(*EXAM_RECORD_READ_ROLES)
def read_scope_area(area_id):
    area = get_area(area_id)
    ensure_exam_subject(derive.exam_of_area(area))
    return success(serialize.scope_area(area))


@bp.post("/scope-areas/<area_id>/data-calls")
@authorize(ROLE_EXAMINER_IN_CHARGE)
def create_data_call(area_id):
    area = get_area(area_id)
    exam = derive.exam_of_area(area)
    payload = v.body()
    records_requested = v.get_int(payload, "records_requested", minimum=1)
    response_due_date = v.get_date(payload, "response_due_date")
    sampling_method = v.get_enum(
        payload,
        "sampling_method",
        SAMPLING_METHODS,
        required=False,
        default="SYSTEMATIC_INTERVAL",
    )

    ensure_exam_writable(exam)
    if exam is not None and exam["status"] == "SCOPING":
        raise ApiError(
            "ERR_SCOPE_NOT_LOCKED",
            "A data call may only be issued once the scope has been locked.",
        )

    issued_date = today_str()
    if response_due_date < issued_date or (
        exam is not None and response_due_date > exam["fieldwork_end_date"]
    ):
        raise ApiError(
            "ERR_DUE_DATE_OUT_OF_WINDOW",
            "response_due_date must fall between the current date and the "
            "examination's fieldwork_end_date.",
        )
    for existing in derive.data_calls_of_area(area["id"]):
        if existing["status"] in ("REJECTED", "CANCELLED"):
            continue
        if abs(day_diff(existing["response_due_date"], response_due_date)) < (
            calc.DATA_CALL_BUFFER_DAYS
        ):
            raise ApiError(
                "ERR_DATA_CALL_WINDOW_CONFLICT",
                "Live data calls on one scope area must be at least three days apart.",
            )
    if records_requested > area["population_size"]:
        raise ApiError(
            "ERR_SAMPLE_EXCEEDS_POPULATION",
            "records_requested may not exceed the scope area's population_size.",
        )

    call = new_record(
        {
            "scope_area_id": area["id"],
            "records_requested": records_requested,
            "issued_date": issued_date,
            "response_due_date": response_due_date,
            "sampling_method": sampling_method,
            "status": "ISSUED",
            "records_received": 0,
            "submitted_by_contact": None,
            "responded_at": None,
            "is_late": False,
            "days_late": 0,
            "completeness_pct": calc.round_half_up(0, 2),
            "effective_completeness_pct": calc.round_half_up(0, 2),
            "disposition_reason": None,
            "sample_draw_interval": 0,
        }
    )
    db.data_calls[call["id"]] = call
    return success(serialize.data_call(call), 201)


@bp.get("/scope-areas/<area_id>/data-calls")
@authorize(*EXAM_RECORD_READ_ROLES)
def list_data_calls(area_id):
    area = get_area(area_id)
    ensure_exam_subject(derive.exam_of_area(area))
    rows = derive.data_calls_of_area(area["id"])
    rows = filter_equals(rows, "status", str_query("status"))
    return paginated(rows, serialize.data_call)
