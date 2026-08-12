"""ExamRequirement and ExamWindow endpoints."""
from datetime import timedelta

from flask import Blueprint

from db import store
from middleware import auth
from common import (
    body, get_or_404, fk_or_404, required, require_enum, new_entity, touch,
    serialize, list_page,
)
from response import success_obj, success_list
from errors import (
    err_duplicate, err_invalid_state, err_invalid_request, err_temporal,
    err_referential,
)
from timeutil import now, parse_dt
from services import EXAM_CREDIT_DAYS

bp = Blueprint("exams", __name__)

READ_ROLES = ("SystemOperator", "ComplianceOfficer", "RegistrationPrincipal", "Regulator")
EXAM_CODES = {"SIE", "S7", "S63", "S66", "S24"}


# ------------------------------------------------------------- requirements
@bp.post("/registration-desk/exam-requirements")
def create_requirement():
    auth("RegistrationPrincipal")
    data = body()
    req = fk_or_404(store.registration_requests, data.get("registration_request_id"))
    # Priority 4: one row per (request, exam_code).
    code = data.get("exam_code")
    if isinstance(code, str) and any(
        er["registration_request_id"] == (req["id"] if req else None) and er["exam_code"] == code
        for er in store.exam_requirements.values()
    ):
        raise err_duplicate("an exam requirement with this exam_code already exists for the request")
    required(data, "registration_request_id")
    code = require_enum(required(data, "exam_code"), EXAM_CODES, "exam_code")
    er = new_entity()
    er.update({
        "registration_request_id": req["id"],
        "exam_code": code,
        "status": "REQUIRED",
        "pass_recorded_at": None,
        "credit_expiry_at": None,
    })
    store.exam_requirements[er["id"]] = er
    return success_obj(serialize(er), 201)


@bp.get("/registration-desk/exam-requirements")
def list_requirements():
    auth(*READ_ROLES)
    page, limit, offset, total = list_page(
        store.exam_requirements,
        (
            ("registration_request_id", "registration_request_id", str),
            ("status", "status", str),
            ("exam_code", "exam_code", str),
        ),
    )
    return success_list([serialize(e) for e in page], limit, offset, total)


@bp.get("/registration-desk/exam-requirements/<id>")
def get_requirement(id):
    auth(*READ_ROLES)
    er = get_or_404(store.exam_requirements, id)
    return success_obj(serialize(er), 200)


@bp.post("/registration-desk/exam-requirements/<id>/waive")
def waive_requirement(id):
    auth("ComplianceOfficer")
    er = get_or_404(store.exam_requirements, id)
    if er["status"] != "REQUIRED":
        raise err_invalid_state("only a REQUIRED exam requirement may be waived")
    parent = get_or_404(store.registration_requests, er["registration_request_id"])
    if parent["status"] not in ("DRAFT", "DEFICIENT"):
        raise err_invalid_state("waive requires the parent request in DRAFT or DEFICIENT")
    er["status"] = "WAIVED"
    touch(er)
    return success_obj(serialize(er), 200)


# ------------------------------------------------------------------ windows
@bp.post("/registration-desk/exam-windows")
def create_window():
    auth("RegistrationPrincipal")
    data = body()
    er = fk_or_404(store.exam_requirements, data.get("exam_requirement_id"))
    # Priority 4: at most one SCHEDULED or OPEN window per requirement.
    if er is not None and any(
        w["exam_requirement_id"] == er["id"] and w["status"] in ("SCHEDULED", "OPEN")
        for w in store.exam_windows.values()
    ):
        raise err_duplicate("an OPEN or SCHEDULED window already exists for this requirement")
    # Priority 5: scheduling only while the requirement is REQUIRED.
    if er is not None and er["status"] != "REQUIRED":
        raise err_invalid_state("exam windows may be scheduled only while the requirement is REQUIRED")
    # Priority 9: window shape.
    required(data, "exam_requirement_id")
    ws_raw = required(data, "window_start")
    we_raw = required(data, "window_end")
    ws = parse_dt(ws_raw)
    we = parse_dt(we_raw)
    if ws is None or we is None:
        raise err_invalid_request("window_start and window_end must be ISO 8601 UTC timestamps")
    if not (we > ws):
        raise err_invalid_request("window_end must be strictly after window_start")
    # Priority 11: non-SIE exams require SIE satisfied or in progress.
    if er["exam_code"] != "SIE":
        sie_ok = any(
            other["registration_request_id"] == er["registration_request_id"]
            and other["exam_code"] == "SIE"
            and other["status"] in ("SCHEDULED", "PASSED", "WAIVED")
            for other in store.exam_requirements.values()
        )
        if not sie_ok:
            raise err_referential("SIE must be SCHEDULED, PASSED, or WAIVED before scheduling a top-off exam")
    w = new_entity()
    w.update({
        "exam_requirement_id": er["id"],
        "window_start": ws_raw,
        "window_end": we_raw,
        "status": "SCHEDULED",
        "result_recorded": None,
        "_ws": ws,
        "_we": we,
    })
    store.exam_windows[w["id"]] = w
    er["status"] = "SCHEDULED"
    touch(er)
    return success_obj(serialize(w), 201)


@bp.get("/registration-desk/exam-windows")
def list_windows():
    auth(*READ_ROLES)
    page, limit, offset, total = list_page(
        store.exam_windows,
        (
            ("exam_requirement_id", "exam_requirement_id", str),
            ("status", "status", str),
        ),
    )
    return success_list([serialize(w) for w in page], limit, offset, total)


@bp.get("/registration-desk/exam-windows/<id>")
def get_window(id):
    auth(*READ_ROLES)
    w = get_or_404(store.exam_windows, id)
    return success_obj(serialize(w), 200)


@bp.post("/registration-desk/exam-windows/<id>/record-result")
def record_result(id):
    auth("SystemOperator")
    w = get_or_404(store.exam_windows, id)
    # Priority 5: window must be SCHEDULED or OPEN.
    if w["status"] not in ("SCHEDULED", "OPEN"):
        raise err_invalid_state("only a SCHEDULED or OPEN window may record a result")
    # Priority 9: result field shape.
    data = body()
    result = require_enum(required(data, "result"), {"PASS", "FAIL", "NO_SHOW"}, "result")
    er = get_or_404(store.exam_requirements, w["exam_requirement_id"])
    if result == "PASS":
        # Priority 10: PASS requires server time within [window_start, window_end).
        now_dt = now()
        if not (w["_ws"] <= now_dt < w["_we"]):
            raise err_temporal("a PASS result requires the server clock within [window_start, window_end)")
        w["status"] = "USED"
        w["result_recorded"] = "PASS"
        er["status"] = "PASSED"
        er["pass_recorded_at"] = now_dt
        er["credit_expiry_at"] = now_dt + timedelta(days=EXAM_CREDIT_DAYS)
    else:
        w["status"] = "USED"
        w["result_recorded"] = result
        er["status"] = "REQUIRED"
    touch(w)
    touch(er)
    return success_obj(serialize(w), 200)


@bp.post("/registration-desk/exam-windows/<id>/cancel")
def cancel_window(id):
    auth("RegistrationPrincipal")
    w = get_or_404(store.exam_windows, id)
    if w["status"] != "SCHEDULED":
        raise err_invalid_state("only a SCHEDULED window may be cancelled")
    w["status"] = "CANCELLED"
    touch(w)
    er = get_or_404(store.exam_requirements, w["exam_requirement_id"])
    if er["status"] == "SCHEDULED":
        er["status"] = "REQUIRED"
        touch(er)
    return success_obj(serialize(w), 200)
