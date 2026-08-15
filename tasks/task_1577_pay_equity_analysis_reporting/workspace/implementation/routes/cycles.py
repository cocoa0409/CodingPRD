"""MonitoringCycle endpoints (PRD §3.7): schedule, start, complete."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_WINDOW,
    ERR_INVALID_DUE_DATE,
    ERR_STUDY_NOT_MONITORING,
    ERR_MONITOR_WINDOW_OVERLAP,
    ERR_CYCLE_INVALID_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import new_record, touch, cycles_of_study
from util import parse_date
from validate import get_body, req_date, require_path_resource, require_fk

bp = Blueprint("cycles", __name__)

RETEST_RESULTS = {"GAPS_CLOSED", "GAPS_PERSIST", "INCONCLUSIVE"}


@bp.post("/monitoring-cycles")
def create_cycle():
    authorized(["CompAnalyst"])
    body = get_body()
    study_id = body.get("study_id")
    if study_id is None or not isinstance(study_id, str) or study_id.strip() == "":
        raise_error(ERR_INVALID_REQUEST, "missing or invalid field: study_id")
    # Priority 3: body FK existence
    study = require_fk("pay_equity_studies", study_id, "study_id")
    # Priority 3.7: shape
    window_start = req_date(body, "window_start")
    window_end = req_date(body, "window_end")
    due_date = req_date(body, "due_date")
    ws, we, dd = parse_date(window_start), parse_date(window_end), parse_date(due_date)
    if we <= ws:
        raise_error(ERR_INVALID_WINDOW, "window_end must be > window_start")
    if dd < we:
        raise_error(ERR_INVALID_DUE_DATE, "due_date must be >= window_end")
    # Priority 4: state
    if study["status"] != "MONITORING":
        raise_error(ERR_STUDY_NOT_MONITORING,
                    "cycle creation requires the study to be MONITORING")
    # Priority 6: HALF-OPEN window overlap — touching boundaries allowed (PRD §2.9)
    for cyc in cycles_of_study(study_id):
        ex_start, ex_end = parse_date(cyc["window_start"]), parse_date(cyc["window_end"])
        if ws < ex_end and ex_start < we:
            raise_error(ERR_MONITOR_WINDOW_OVERLAP,
                        "window overlaps an existing cycle of the same study")

    cycle_index = len(cycles_of_study(study_id)) + 1
    rec = new_record("monitoring_cycles", {
        "study_id": study_id,
        "window_start": window_start,
        "window_end": window_end,
        "due_date": due_date,
        "cycle_index": cycle_index,
        "retest_result": None,
        "status": "SCHEDULED",
    })
    return success_object(public(rec), status=201)


@bp.get("/monitoring-cycles")
def list_cycles():
    return list_response("monitoring_cycles", {
        "study_id": request.args.get("study_id"),
        "status": request.args.get("status"),
    })


@bp.get("/monitoring-cycles/<rid>")
def get_cycle(rid):
    return get_one("monitoring_cycles", rid)


@bp.post("/monitoring-cycles/<rid>/start")
def start_cycle(rid):
    authorized(["CompAnalyst"])
    cycle = require_path_resource("monitoring_cycles", rid)
    if cycle["status"] != "DUE":
        raise_error(ERR_CYCLE_INVALID_STATE, "start requires a DUE cycle")
    cycle["status"] = "RE_TESTING"
    touch(cycle)
    return success_object(public(cycle))


@bp.post("/monitoring-cycles/<rid>/complete")
def complete_cycle(rid):
    authorized(["CompAnalyst"])
    cycle = require_path_resource("monitoring_cycles", rid)
    body = get_body()
    # Priority 3.7 (shape) before priority 4 (state)
    retest_result = body.get("retest_result")
    if retest_result not in RETEST_RESULTS:
        raise_error(ERR_INVALID_REQUEST,
                    "retest_result must be GAPS_CLOSED, GAPS_PERSIST, or INCONCLUSIVE")
    if cycle["status"] != "RE_TESTING":
        raise_error(ERR_CYCLE_INVALID_STATE, "complete requires a RE_TESTING cycle")
    cycle["retest_result"] = retest_result
    cycle["status"] = "COMPLETED"
    touch(cycle)
    # Re-test failure reopens remediation (PRD §3.7)
    if retest_result == "GAPS_PERSIST":
        study = db["pay_equity_studies"].get(cycle["study_id"])
        if study is not None and study["status"] == "MONITORING":
            study["status"] = "REMEDIATION_OPEN"
            touch(study)
    return success_object(public(cycle))
