"""ProbationCycle action endpoints (PRD §3.8)."""

from datetime import datetime, time as dtime, timedelta, timezone

from flask import Blueprint

from auth import require_roles
from db import store, clock
from errors import (ApiError, ERR_CYCLE_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
                    ERR_CYCLE_NOT_EVALUABLE, ERR_INVALID_CASE_PHASE,
                    ERR_MAX_EXTENSIONS_REACHED)
from helpers import new_record, touch, get_or_404, ser_cycle
from sweep import separate_case
from util import (success, get_body, req_present, as_enum, as_opt_str,
                  as_rating, fmt_dt)

bp = Blueprint("probation", __name__)

OUTCOMES = ("PASS", "EXTEND", "FAIL")


@bp.post("/api/probation-cycles/<cid>/evaluate")
def evaluate_cycle(cid):
    uid, _ = require_roles("HiringManager")
    body = get_body()
    outcome = as_enum(req_present(body, "outcome"), "outcome", OUTCOMES)
    rating = as_rating(req_present(body, "rating"), "rating")
    notes = as_opt_str(body.get("notes"), "notes")
    cycle = get_or_404("cycles", cid, ERR_CYCLE_NOT_FOUND, "ProbationCycle")
    case = store["cases"][cycle["case_id"]]
    # Stage 5: the caller must be the case's hiring manager
    if case["manager_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                       "Only the case's hiring manager may evaluate")
    # Stage 6: the cycle's own state gate, then the case phase gate
    if cycle["status"] != "EVALUATION_DUE":
        raise ApiError(ERR_CYCLE_NOT_EVALUABLE, 409,
                       "evaluate requires an EVALUATION_DUE cycle")
    if case["phase"] != "PROBATION":
        raise ApiError(ERR_INVALID_CASE_PHASE, 409,
                       "evaluate requires the case to be in PROBATION")
    # Stage 9: extension budget — cycle k may extend iff k <= budget
    prof = case["_profile"]
    if outcome == "EXTEND" and \
            cycle["cycle_index"] > prof["max_probation_extensions"]:
        raise ApiError(ERR_MAX_EXTENSIONS_REACHED, 409,
                       "Probation extension budget exhausted")

    now = clock.current
    cycle["outcome_rating"] = rating
    if notes is not None:
        cycle["notes"] = notes
    cycle["_evaluated_dt"] = now
    cycle["evaluated_at"] = fmt_dt(now)

    if outcome == "PASS":
        cycle["status"] = "EVALUATED_PASS"
        touch(cycle)
        # Automatic: PROBATION -> COMPLETED
        case["phase"] = "COMPLETED"
        touch(case)
    elif outcome == "EXTEND":
        cycle["status"] = "EVALUATED_EXTEND"
        touch(cycle)
        # Extension regeneration loop: successor cycle at prev due +
        # extension_days, 17:00:00Z.
        prev_due = cycle["_eval_due_dt"]
        new_due = datetime.combine(
            (prev_due + timedelta(days=prof["extension_days"])).date(),
            dtime(17, 0, 0), tzinfo=timezone.utc)
        new_record("cycles", {
            "case_id": case["id"], "cycle_index": cycle["cycle_index"] + 1,
            "evaluation_due_at": fmt_dt(new_due), "status": "ACTIVE",
            "outcome_rating": None, "notes": None, "evaluated_at": None,
            "_eval_due_dt": new_due, "_evaluated_dt": None,
        })
        touch(case)
    else:  # FAIL
        cycle["status"] = "EVALUATED_FAIL"
        touch(cycle)
        separate_case(case)
    return success(ser_cycle(cycle))
