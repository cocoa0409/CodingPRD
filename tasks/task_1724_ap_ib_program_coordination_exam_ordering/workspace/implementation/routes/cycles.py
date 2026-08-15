"""ExamCycle endpoints (PRD 3.1, 3.8) and bulk score release (PRD 3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_IRREGULARITY_OPEN,
    ERR_REFERENCE_NOT_FOUND,
    ERR_SCORES_NOT_YET_AVAILABLE,
)
from middleware import get_caller, require_roles
from response import success_object
from routes.helpers import list_response  # noqa: F401  (re-exported for symmetry)
from services import derived
from services.core import new_record, touch
from services.serialize import serialize_cycle
from util import CLOCK
from validate import (
    get_body, reject_unknown_fields, req_int, req_str, req_datetime,
    require_path_resource,
)

bp = Blueprint("cycles", __name__)

ALL_READ = ["ApCoordinator", "Registrar", "Teacher", "Student"]

CYCLE_FIELDS = {
    "name", "registration_deadline_at", "order_deadline_at", "score_release_at",
    "exam_window_start_at", "exam_window_end_at", "late_fee_cents",
    "unused_exam_penalty_cents", "fee_reduction_cents", "budget_cap_cents",
    "rebate_rate_bp",
}


@bp.post("/exam-cycles")
def create_cycle():
    require_roles(get_caller(), ["ApCoordinator"])
    body = get_body()
    reject_unknown_fields(body, CYCLE_FIELDS)
    rec = new_record("exam_cycles", {
        "name": req_str(body, "name"),
        "status": "SETUP",
        "registration_deadline_at": req_datetime(body, "registration_deadline_at"),
        "order_deadline_at": req_datetime(body, "order_deadline_at"),
        "score_release_at": req_datetime(body, "score_release_at"),
        "exam_window_start_at": req_datetime(body, "exam_window_start_at"),
        "exam_window_end_at": req_datetime(body, "exam_window_end_at"),
        "late_fee_cents": req_int(body, "late_fee_cents", non_negative=True),
        "unused_exam_penalty_cents": req_int(body, "unused_exam_penalty_cents", non_negative=True),
        "fee_reduction_cents": req_int(body, "fee_reduction_cents", non_negative=True),
        "budget_cap_cents": req_int(body, "budget_cap_cents", non_negative=True),
        "rebate_rate_bp": req_int(body, "rebate_rate_bp", minimum=0, maximum=10000),
    })
    return success_object(serialize_cycle(rec), status=201)


@bp.get("/exam-cycles/<rid>")
def get_cycle(rid):
    require_roles(get_caller(), ALL_READ)
    cycle = require_path_resource("exam_cycles", rid)
    return success_object(serialize_cycle(cycle))


@bp.post("/exam-cycles/<rid>/open")
def open_cycle(rid):
    require_roles(get_caller(), ["ApCoordinator"])
    body = get_body()
    reject_unknown_fields(body, set())
    cycle = require_path_resource("exam_cycles", rid)
    if cycle["status"] != "SETUP":
        raise_error(ERR_INVALID_STATE, f"cycle in {cycle['status']} cannot be opened")
    cycle["status"] = "OPEN"
    touch(cycle)
    return success_object(serialize_cycle(cycle))


@bp.get("/exam-cycles/<rid>/equity-report")
def equity_report(rid):
    require_roles(get_caller(), ["ApCoordinator"])
    cycle = require_path_resource("exam_cycles", rid)
    compare_id = request.args.get("compare_to_cycle_id")
    compare_cycle = None
    if compare_id is not None and compare_id != "":
        compare_cycle = db["exam_cycles"].get(compare_id)
        if compare_cycle is None:
            raise_error(ERR_REFERENCE_NOT_FOUND,
                        f"compare_to_cycle_id does not resolve: {compare_id}")
    return success_object(derived.equity_report(cycle, compare_cycle))


@bp.post("/exam-cycles/<rid>/release-scores")
def release_scores(rid):
    """Transactional bulk release (PRD 3.7): any rejection writes nothing."""
    require_roles(get_caller(), ["Registrar"])
    cycle = require_path_resource("exam_cycles", rid)
    body = get_body()
    reject_unknown_fields(body, {"scores"})
    scores = body.get("scores")
    if not isinstance(scores, list):
        raise_error(ERR_INVALID_REQUEST, "scores must be an array")
    entries = []
    for item in scores:
        if not isinstance(item, dict):
            raise_error(ERR_INVALID_REQUEST, "each scores entry must be an object")
        for key in item:
            if key not in ("registration_id", "score"):
                raise_error(ERR_INVALID_REQUEST, f"unexpected field in scores entry: {key}")
        reg_id = item.get("registration_id")
        if reg_id is None or not isinstance(reg_id, str):
            raise_error(ERR_INVALID_REQUEST, "scores entry requires registration_id (string)")
        score = item.get("score")
        if score is None or isinstance(score, bool) or not isinstance(score, int):
            raise_error(ERR_INVALID_REQUEST, "scores entry requires score (integer)")
        entries.append((reg_id, score))
    # Priority 5: every listed registration id must resolve.
    regs = []
    for reg_id, score in entries:
        reg = db["registrations"].get(reg_id)
        if reg is None:
            raise_error(ERR_REFERENCE_NOT_FOUND,
                        f"scores registration_id does not resolve: {reg_id}")
        regs.append((reg, score))
    # Priority 4 semantic: score within the course's program range.
    for reg, score in regs:
        course = db["courses"].get(reg["course_id"])
        hi = 5 if course["program"] == "AP" else 7
        if score < 1 or score > hi:
            raise_error(ERR_INVALID_REQUEST,
                        f"score {score} outside program range 1..{hi}")
    # Priority 8 temporal gate.
    if CLOCK.now() < cycle["score_release_at"]:
        raise_error(ERR_SCORES_NOT_YET_AVAILABLE,
                    "logical clock is before the cycle's score_release_at")
    # Priority 11 record gate: transactional — validate all, then write.
    if any(reg["score_status"] == "HELD" for reg, _ in regs):
        raise_error(ERR_IRREGULARITY_OPEN,
                    "a listed record has score_status HELD (open irregularity)")
    for reg, _ in regs:
        if reg["score_status"] != "PENDING":
            raise_error(ERR_INVALID_STATE,
                        f"registration {reg['id']} has score_status "
                        f"{reg['score_status']}, not PENDING")
    for reg, score in regs:
        reg["score"] = score
        reg["score_status"] = "RELEASED"
        touch(reg)
    return success_object({
        "released_count": len(regs),
        "released_registration_ids": [reg["id"] for reg, _ in regs],
    })
