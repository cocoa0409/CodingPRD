"""TrainingAssignment action endpoints (PRD §3.7)."""

from flask import Blueprint

from auth import require_roles
from db import store, clock
from errors import (ApiError, ERR_TRAINING_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
                    ERR_INVALID_TRAINING_STATE)
from helpers import touch, get_or_404, ser_training
from sweep import refresh_health, reeval_probation_gate
from util import success, get_body, as_num, fmt_dt

bp = Blueprint("training", __name__)


@bp.post("/api/training-assignments/<tid>/complete")
def complete_training(tid):
    uid, _ = require_roles("NewHire")
    body = get_body()
    score = body.get("score")
    if score is not None:
        score = as_num(score, "score")
    tr = get_or_404("trainings", tid, ERR_TRAINING_NOT_FOUND,
                    "TrainingAssignment")
    case = store["cases"][tr["case_id"]]
    # Stage 5: ownership
    if case["new_hire_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                       "NewHire may only complete trainings of its own case")
    # Stage 6: ASSIGNED or OVERDUE (late completion allowed, flagged)
    if tr["status"] not in ("ASSIGNED", "OVERDUE"):
        raise ApiError(ERR_INVALID_TRAINING_STATE, 409,
                       "complete requires an ASSIGNED or OVERDUE training")
    now = clock.current
    tr["status"] = "COMPLETED"
    tr["_completed_dt"] = now
    tr["completed_at"] = fmt_dt(now)
    tr["completed_late"] = now > tr["_due_dt"]
    if score is not None:
        tr["score"] = score
    touch(tr)
    refresh_health(case)
    reeval_probation_gate(case)
    touch(case)
    return success(ser_training(tr))
