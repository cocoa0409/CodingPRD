"""NightFlowAssessment endpoints."""

from datetime import timedelta

import db
import errors
from errors import ApiError
from middleware import get_body, require_roles
from response import success_object
from routes import make_bp
from services import calc
from util import canon, v_dt, v_num

bp = make_bp("night_flow")

BUFFER = timedelta(hours=1)
MIN_DUR = timedelta(hours=2)
MAX_DUR = timedelta(hours=6)


def _get_or_404(nfa_id):
    rec = db.store["night_flow_assessments"].get(nfa_id)
    if rec is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "night-flow assessment not found")
    return rec


@bp.route("/nrw/night-flow-assessments", methods=["POST"])
def create_assessment():
    uid, role = require_roles({"UtilityAnalyst"})
    body = get_body()
    # priority 3: existence of body FK
    dma_id = body.get("dma_id")
    dma = db.store["dmas"].get(dma_id) if isinstance(dma_id, str) else None
    if dma is None:
        if not isinstance(dma_id, str):
            raise ApiError(errors.ERR_VALIDATION, 422, "dma_id must be a string")
        raise ApiError(errors.ERR_NOT_FOUND, 404, "DMA not found")
    # priority 8: interval arithmetic — duration bounds + 1h-buffer non-overlap
    start = db.parse_dt(body.get("window_start"))
    end = db.parse_dt(body.get("window_end"))
    if start is not None and end is not None:
        dur = end - start
        if dur < MIN_DUR or dur > MAX_DUR:
            raise ApiError(errors.ERR_WINDOW_CONFLICT, 409,
                           "window duration must be between 2 and 6 hours")
        for other in db.store["night_flow_assessments"].values():
            if other["dma_id"] != dma_id or other["status"] == "VOID":
                continue
            o_start = db.parse_dt(other["window_start"])
            o_end = db.parse_dt(other["window_end"])
            # one-hour buffer between consecutive windows (inclusive boundary)
            if not (start >= o_end + BUFFER or o_start >= end + BUFFER):
                raise ApiError(errors.ERR_WINDOW_CONFLICT, 409,
                               "window overlaps or violates the 1-hour buffer")
    # priority 9: scalar constraints
    v_dt(body, "window_start")
    v_dt(body, "window_end")
    measured = v_num(body, "measured_mnf_lps", ge=0)
    expected = v_num(body, "expected_legitimate_night_use_lps", ge=0)

    rec = db.new_record()
    rec.update({
        "dma_id": dma_id,
        "window_start": canon(start),
        "window_end": canon(end),
        "measured_mnf_lps": measured,
        "expected_legitimate_night_use_lps": expected,
        "status": "RECORDED",
        "net_night_flow_lps": None,
        "net_night_flow_pct": None,
        "leak_signal": None,
    })
    db.store["night_flow_assessments"][rec["id"]] = rec
    db.append_audit("NightFlowAssessment", rec["id"], "CREATE", uid, role,
                    {"before": None, "after": db.serialize(rec)})
    return success_object(db.serialize(rec), status=201)


@bp.route("/nrw/night-flow-assessments/<nfa_id>", methods=["GET"])
def get_assessment(nfa_id):
    require_roles({"ProgramDirector", "UtilityAnalyst"})
    rec = _get_or_404(nfa_id)
    return success_object(db.serialize(rec))


@bp.route("/nrw/night-flow-assessments/<nfa_id>/analyze", methods=["POST"])
def analyze(nfa_id):
    uid, role = require_roles({"UtilityAnalyst"})
    rec = _get_or_404(nfa_id)
    if rec["status"] != "RECORDED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a RECORDED assessment can be analyzed")
    calc.compute_night_flow(rec)
    rec["status"] = "ANALYZED"
    db.touch(rec)
    db.append_audit("NightFlowAssessment", rec["id"], "ANALYZE", uid, role,
                    {"before": {"status": "RECORDED"},
                     "after": {"status": "ANALYZED"}})
    return success_object(db.serialize(rec))


@bp.route("/nrw/night-flow-assessments/<nfa_id>/void", methods=["POST"])
def void(nfa_id):
    uid, role = require_roles({"UtilityAnalyst"})
    rec = _get_or_404(nfa_id)
    if rec["status"] != "RECORDED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a RECORDED assessment can be voided")
    rec["status"] = "VOID"
    db.touch(rec)
    db.append_audit("NightFlowAssessment", rec["id"], "VOID", uid, role,
                    {"before": {"status": "RECORDED"}, "after": {"status": "VOID"}})
    return success_object(db.serialize(rec))
