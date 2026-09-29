"""Coordinated multistate examinations (§3.8)."""

from flask import Blueprint

from db import base_row, days, db, serialize, set_input_dt, touch
from errors import ApiError
from middleware import authorize, require_scope
from response import created, ok
from routes.common import (
    filter_rows,
    get_exam,
    get_jurisdiction,
    get_licensee,
    paginate,
)
from services import engine
from validators import (
    bad,
    get_body,
    pagination,
    q_enum,
    q_str,
    v_dt,
    v_enum,
    v_int,
    v_str,
    v_str_list,
)

bp = Blueprint("exams", __name__)

EXAM_STATUSES = ("SCHEDULED", "FIELDWORK", "REPORT_DRAFT", "REPORT_ISSUED", "CLOSED")
EXAM_EDGES = {
    "SCHEDULED": "FIELDWORK",
    "FIELDWORK": "REPORT_DRAFT",
    "REPORT_DRAFT": "REPORT_ISSUED",
    "REPORT_ISSUED": "CLOSED",
}
UNRESOLVED_ENFORCEMENT_STATUSES = ("ISSUED", "CONTESTED", "CONSENT_ORDER")
EXAM_BUFFER_DAYS = 30
FINDINGS_CASCADE_THRESHOLD = 3


def _invalid_state(detail):
    raise ApiError("ERR_EXAM_INVALID_STATE", detail)


@bp.post("/multistate-exams")
def create_exam():
    user_id, _ = authorize("StateRegulator")
    body = get_body()
    licensee_id = v_str(body, "licensee_id")
    lead_id = v_str(body, "lead_jurisdiction_id")
    participants = v_str_list(body, "participating_jurisdiction_ids")
    raw_start, start = v_dt(body, "fieldwork_start", required=True)
    raw_end, end = v_dt(body, "fieldwork_end", required=True)
    if end <= start:
        bad("fieldwork_end must be strictly later than fieldwork_start")

    get_licensee(licensee_id)
    get_jurisdiction(lead_id)
    for participant_id in participants:
        get_jurisdiction(participant_id)

    require_scope(user_id == lead_id, user_id, "examination lead %s" % lead_id)

    active_states = {
        lic["jurisdiction_id"]
        for lic in engine.licenses_of(licensee_id)
        if lic["license_status"] == "ACTIVE"
    }
    for participant_id in participants:
        jurisdiction = db.jurisdictions[participant_id]
        if not jurisdiction["participates_in_multistate"]:
            raise ApiError(
                "ERR_JURISDICTION_NOT_MULTISTATE",
                "Jurisdiction %s does not participate in multistate examinations"
                % participant_id,
            )
        if participant_id not in active_states:
            raise ApiError(
                "ERR_JURISDICTION_NOT_MULTISTATE",
                "The licensee holds no ACTIVE licence in jurisdiction %s" % participant_id,
            )

    buffer_delta = days(EXAM_BUFFER_DAYS)
    for other in db.exams.values():
        if other["licensee_id"] != licensee_id:
            continue
        other_start = other["_fieldwork_start"]
        other_end = other["_fieldwork_end"]
        if start < other_end + buffer_delta and other_start < end + buffer_delta:
            raise ApiError(
                "ERR_EXAM_WINDOW_CONFLICT",
                "Another examination of this licensee falls inside the thirty-day buffer",
            )

    row = base_row()
    row.update(
        {
            "licensee_id": licensee_id,
            "lead_jurisdiction_id": lead_id,
            "participating_jurisdiction_ids": list(participants),
            "status": "SCHEDULED",
            "participating_state_count": len(set(participants) | {lead_id}),
            "open_request_count": 0,
            "findings_count": 0,
        }
    )
    set_input_dt(row, "fieldwork_start", raw_start, start)
    set_input_dt(row, "fieldwork_end", raw_end, end)
    db.exams[row["id"]] = row
    return created(serialize(row))


@bp.get("/multistate-exams/<exam_id>")
def get_one(exam_id):
    authorize("StateRegulator", "LicensingManager")
    return ok(serialize(get_exam(exam_id)))


@bp.get("/multistate-exams")
def list_all():
    authorize("StateRegulator", "LicensingManager")
    limit, offset = pagination()
    filters = {
        "licensee_id": q_str("licensee_id"),
        "lead_jurisdiction_id": q_str("lead_jurisdiction_id"),
        "status": q_enum("status", EXAM_STATUSES),
    }
    return paginate(filter_rows(db.exams.values(), filters), limit, offset)


@bp.post("/multistate-exams/<exam_id>/status-changes")
def status_change(exam_id):
    user_id, _ = authorize("StateRegulator")
    body = get_body()
    to_status = v_enum(body, "to_status", EXAM_STATUSES)
    findings_count = v_int(body, "findings_count", required=False, minimum=0, default=None)

    row = get_exam(exam_id)
    licensee = get_licensee(row["licensee_id"])
    require_scope(
        user_id == row["lead_jurisdiction_id"], user_id, "examination %s" % exam_id
    )

    current = row["status"]
    if EXAM_EDGES.get(current) != to_status:
        _invalid_state(
            "Examination %s cannot move from %s to %s" % (exam_id, current, to_status)
        )

    if to_status == "REPORT_DRAFT":
        engine.recompute_open_request_count(row)
        if row["open_request_count"] != 0:
            _invalid_state(
                "Examination %s still has %d open information request(s)"
                % (exam_id, row["open_request_count"])
            )
    elif to_status == "CLOSED":
        for action in db.enforcements.values():
            if (
                action["originating_exam_id"] == exam_id
                and action["status"] in UNRESOLVED_ENFORCEMENT_STATUSES
            ):
                _invalid_state(
                    "Examination %s has an unresolved enforcement action" % exam_id
                )

    row["status"] = to_status
    if to_status == "REPORT_ISSUED":
        row["findings_count"] = findings_count or 0
    touch(row)

    if to_status == "REPORT_ISSUED" and row["findings_count"] >= FINDINGS_CASCADE_THRESHOLD:
        engine.apply_exam_findings(row, licensee)
    return ok(serialize(row))
