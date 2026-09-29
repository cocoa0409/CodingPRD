"""Examination information requests (§3.8)."""

from flask import Blueprint

import calculations as calc
from db import base_row, days, db, now, serialize, set_dt, touch
from errors import ApiError
from middleware import authorize, require_scope
from response import created, ok
from routes.common import filter_rows, get_exam, get_info_request, get_jurisdiction, paginate
from services import engine
from validators import get_body, pagination, q_enum, q_str, v_enum, v_int, v_str

bp = Blueprint("info_requests", __name__)

INFO_REQUEST_STATUSES = ("OPEN", "RESPONDED", "OVERDUE", "ACCEPTED")


def _invalid_state(detail):
    raise ApiError("ERR_INFO_REQUEST_INVALID_STATE", detail)


def _require_fieldwork(exam):
    if exam["status"] != "FIELDWORK":
        raise ApiError(
            "ERR_EXAM_INVALID_STATE",
            "Examination %s is %s, not FIELDWORK" % (exam["id"], exam["status"]),
        )


@bp.post("/information-requests")
def create_request():
    user_id, _ = authorize("StateRegulator")
    body = get_body()
    exam_id = v_str(body, "exam_id")
    jurisdiction_id = v_str(body, "jurisdiction_id")
    subject = v_str(body, "subject")
    requested_item_count = v_int(body, "requested_item_count", minimum=1)

    jurisdiction = get_jurisdiction(jurisdiction_id)
    exam = get_exam(exam_id)

    require_scope(
        user_id == jurisdiction_id, user_id, "information requests for %s" % jurisdiction_id
    )
    _require_fieldwork(exam)

    if jurisdiction_id != exam["lead_jurisdiction_id"] and jurisdiction_id not in (
        exam["participating_jurisdiction_ids"] or []
    ):
        raise ApiError(
            "ERR_JURISDICTION_NOT_PARTICIPATING",
            "Jurisdiction %s is not part of examination %s" % (jurisdiction_id, exam_id),
        )

    row = base_row()
    row.update(
        {
            "exam_id": exam_id,
            "jurisdiction_id": jurisdiction_id,
            "subject": subject,
            "requested_item_count": requested_item_count,
            "status": "OPEN",
            "reopen_count": 0,
            "submitted_item_count": 0,
            "responded_at": None,
        }
    )
    set_dt(row, "due_at", now() + days(jurisdiction["response_window_days"]))
    db.info_requests[row["id"]] = row
    engine.recompute_open_request_count(exam)
    return created(serialize(row))


@bp.get("/information-requests/<request_id>")
def get_one(request_id):
    authorize("StateRegulator", "LicensingManager", "ComplianceOfficer")
    return ok(serialize(get_info_request(request_id)))


@bp.get("/information-requests")
def list_all():
    authorize("StateRegulator", "LicensingManager", "ComplianceOfficer")
    limit, offset = pagination()
    filters = {
        "exam_id": q_str("exam_id"),
        "jurisdiction_id": q_str("jurisdiction_id"),
        "status": q_enum("status", INFO_REQUEST_STATUSES),
    }
    return paginate(filter_rows(db.info_requests.values(), filters), limit, offset)


@bp.post("/information-requests/<request_id>/response")
def respond(request_id):
    authorize("LicensingManager", "ComplianceOfficer")
    body = get_body()
    submitted = v_int(body, "submitted_item_count", minimum=0)
    v_str(body, "narrative")

    row = get_info_request(request_id)
    exam = get_exam(row["exam_id"])

    _require_fieldwork(exam)
    if row["status"] not in ("OPEN", "OVERDUE"):
        _invalid_state(
            "Information request %s is %s and cannot be answered" % (request_id, row["status"])
        )
    if now() > row["_due_at"]:
        raise ApiError(
            "ERR_RESPONSE_WINDOW_CLOSED",
            "The response window for request %s closed at %s" % (request_id, row["due_at"]),
        )
    if submitted < row["requested_item_count"]:
        raise ApiError(
            "ERR_RESPONSE_INCOMPLETE",
            "The response delivers %d of %d demanded items"
            % (submitted, row["requested_item_count"]),
        )

    row["status"] = "RESPONDED"
    row["submitted_item_count"] = submitted
    set_dt(row, "responded_at", now())
    touch(row)
    engine.recompute_open_request_count(exam)
    return ok(serialize(row))


@bp.post("/information-requests/<request_id>/disposition")
def disposition(request_id):
    user_id, _ = authorize("StateRegulator")
    body = get_body()
    decision = v_enum(body, "decision", ("ACCEPTED", "REJECTED"))
    v_str(body, "rationale", required=False, allow_empty=True, default=None)

    row = get_info_request(request_id)
    exam = get_exam(row["exam_id"])
    require_scope(
        user_id == row["jurisdiction_id"], user_id, "information request %s" % request_id
    )

    if row["status"] not in ("OPEN", "RESPONDED"):
        _invalid_state(
            "Information request %s is %s and cannot be dispositioned"
            % (request_id, row["status"])
        )

    if decision == "ACCEPTED":
        if row["status"] != "RESPONDED":
            _invalid_state(
                "Information request %s is %s; acceptance requires RESPONDED"
                % (request_id, row["status"])
            )
        row["status"] = "ACCEPTED"
        touch(row)
    elif row["status"] == "RESPONDED":
        row["status"] = "OPEN"
        row["reopen_count"] += 1
        row["submitted_item_count"] = 0
        set_dt(row, "due_at", now() + days(calc.REOPEN_WINDOW_DAYS))
        touch(row)
    elif now() > row["_due_at"]:
        row["status"] = "OVERDUE"
        touch(row)

    engine.recompute_open_request_count(exam)
    return ok(serialize(row))
