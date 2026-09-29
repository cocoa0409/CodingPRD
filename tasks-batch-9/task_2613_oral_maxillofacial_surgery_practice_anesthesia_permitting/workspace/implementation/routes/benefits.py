"""Benefit determinations and the coordination-of-benefits waterfall."""
from flask import Blueprint

from db import db, new_record, ordered, touch
from errors import ApiError
from middleware import authorize
from routes.helpers import ALL_ROLES, send, send_list
from services.benefit import recompute_determination, service_line_total
from services.domain import (BENEFIT_CLASSES, BENEFIT_ROUTES, DENIAL_REASONS,
                             DETERMINATION_STATUSES, PEND_REASONS,
                             SERVICE_LINE_MAX, evaluations_of_case, get_case,
                             get_patient, path_row, referenced_row)
from validation import q_enum, q_string, read_body, v_enum, v_id

bp = Blueprint("benefits", __name__)

LINE_KEYS = ("code", "charge_cents", "benefit_class")


def _read_service_lines(body):
    raw = body["service_lines"]
    if not isinstance(raw, list):
        raise ApiError("ERR_INVALID_FIELD_VALUE", "Field 'service_lines' must be an array.")
    if len(raw) < 1 or len(raw) > SERVICE_LINE_MAX:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'service_lines' must hold between 1 and %d entries." % SERVICE_LINE_MAX)
    for entry in raw:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Each service line must be a JSON object.")
        for key in entry.keys():
            if key not in LINE_KEYS:
                raise ApiError("ERR_INVALID_REQUEST", "Unknown service line field '%s'." % key)
        for key in LINE_KEYS:
            if key not in entry or entry[key] is None:
                raise ApiError("ERR_INVALID_REQUEST", "Service line field '%s' is required." % key)
    lines = []
    for entry in raw:
        code = entry["code"]
        charge = entry["charge_cents"]
        benefit_class = entry["benefit_class"]
        if not isinstance(code, str) or code.strip() == "":
            raise ApiError("ERR_INVALID_FIELD_VALUE", "Service line 'code' must be a string.")
        if isinstance(charge, bool) or not isinstance(charge, int) or charge < 0:
            raise ApiError("ERR_INVALID_FIELD_VALUE",
                           "Service line 'charge_cents' must be an integer >= 0.")
        if benefit_class not in BENEFIT_CLASSES:
            raise ApiError("ERR_INVALID_FIELD_VALUE",
                           "Service line 'benefit_class' must be MEDICAL or DENTAL.")
        lines.append({"code": code, "charge_cents": charge, "benefit_class": benefit_class})
    return lines


@bp.post("/benefit-determinations")
def create_determination():
    authorize("BenefitsSpecialist")
    body = read_body(required=("case_id", "service_lines"))
    case_id = v_id(body, "case_id")
    lines = _read_service_lines(body)

    case = referenced_row(db.cases, case_id)
    patient = get_patient(case["patient_id"])
    if service_line_total(lines) != int(case["total_charge_cents"]):
        raise ApiError("ERR_CHARGE_TOTAL_MISMATCH")

    determination = new_record({
        "case_id": case_id,
        "service_lines": lines,
        "route": None,
        "primary_payer": None,
        "status": "DRAFT",
        "submission_count": 0,
        "medical_allowed_cents": 0,
        "dental_allowed_cents": 0,
        "patient_responsibility_cents": 0,
        "dental_annual_remaining_snapshot_cents": int(patient["dental_annual_remaining_cents"]),
        "pend_reason": None,
        "denial_reason": None,
    })
    recompute_determination(determination, int(patient["dental_annual_remaining_cents"]))
    db.determinations[determination["id"]] = determination
    return send(determination, 201)


@bp.get("/benefit-determinations/<determination_id>")
def read_determination(determination_id):
    authorize(*ALL_ROLES)
    return send(path_row(db.determinations, determination_id))


@bp.get("/benefit-determinations")
def list_determinations():
    authorize(*ALL_ROLES)
    case_id = q_string("case_id")
    route = q_enum("route", BENEFIT_ROUTES)
    status = q_enum("status", DETERMINATION_STATUSES)
    rows = ordered([d for d in db.determinations.values()
                    if (case_id is None or d["case_id"] == case_id)
                    and (route is None or d["route"] == route)
                    and (status is None or d["status"] == status)])
    return send_list(rows)


@bp.post("/benefit-determinations/<determination_id>/submit")
def submit_determination(determination_id):
    authorize("BenefitsSpecialist")
    determination = path_row(db.determinations, determination_id)
    case = get_case(determination["case_id"])

    if determination["status"] not in ("DRAFT", "PENDED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    verified = [e for e in evaluations_of_case(determination["case_id"])
                if e["status"] == "VERIFIED"]
    if not verified:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if service_line_total(determination["service_lines"]) != int(case["total_charge_cents"]):
        raise ApiError("ERR_CHARGE_TOTAL_MISMATCH")

    patient = get_patient(case["patient_id"])
    determination["status"] = "SUBMITTED"
    determination["submission_count"] = int(determination["submission_count"]) + 1
    determination["pend_reason"] = None
    recompute_determination(determination, int(patient["dental_annual_remaining_cents"]))
    touch(determination)
    return send(determination)


@bp.post("/benefit-determinations/<determination_id>/payer-response")
def payer_response(determination_id):
    authorize("BenefitsSpecialist")
    determination = path_row(db.determinations, determination_id)
    body = read_body(required=("outcome",), optional=("pend_reason", "denial_reason"))
    outcome = v_enum(body, "outcome", ("APPROVED", "DENIED", "PENDED"))
    pend_reason = v_enum(body, "pend_reason", PEND_REASONS, default=None)
    denial_reason = v_enum(body, "denial_reason", DENIAL_REASONS, default=None)
    if outcome == "PENDED" and pend_reason is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'pend_reason' is required for a PENDED outcome.")
    if outcome == "DENIED" and denial_reason is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'denial_reason' is required for a DENIED outcome.")

    if determination["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    case = get_case(determination["case_id"])
    patient = get_patient(case["patient_id"]) if case is not None else None

    if outcome == "PENDED":
        determination["status"] = "PENDED"
        determination["pend_reason"] = pend_reason
    elif outcome == "APPROVED":
        determination["status"] = "APPROVED"
        determination["pend_reason"] = None
        if patient is not None:
            remaining = int(patient["dental_annual_remaining_cents"])
            patient["dental_annual_remaining_cents"] = max(
                0, remaining - int(determination["dental_allowed_cents"]))
            touch(patient)
    else:
        determination["status"] = "DENIED"
        determination["pend_reason"] = None
        determination["denial_reason"] = denial_reason
        determination["medical_allowed_cents"] = 0
        determination["dental_allowed_cents"] = 0
        determination["patient_responsibility_cents"] = int(case["total_charge_cents"])
    touch(determination)
    return send(determination)
