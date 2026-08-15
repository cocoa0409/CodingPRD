"""RunResult endpoints: record, list, get, verify/amend/void (PRD 3.4)."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    amend_compensate,
    get_or_404,
    rodeo_of_event,
    ser,
    sorted_created,
    stamp,
    touch,
    verify_cascade,
)
from util import as_bool, as_int, body, pagination_args, required

bp = Blueprint("run_results", __name__, url_prefix="/api")

_ACTIONS = {"VERIFY", "AMEND", "VOID"}
_VALID_FROM = {
    "VERIFY": {"RECORDED", "AMENDED"},
    "AMEND": {"VERIFIED"},
    "VOID": {"RECORDED", "AMENDED"},
}


def _judge_assigned(judge_id, performance_id):
    return any(
        a["judge_id"] == judge_id and a["performance_id"] == performance_id
        for a in DB["judge_assignments"].values()
    )


def _validate_discipline_payload(discipline, values):
    """Score/time domain rule (priority 18, ERR_SCORE_OUT_OF_RANGE).

    ROUGH_STOCK requires judge scores in 0..50 and forbids raw_time_ms; TIMED
    requires raw_time_ms >= 0 and forbids judge scores.
    """
    j1 = values.get("judge_1_score")
    j2 = values.get("judge_2_score")
    raw = values.get("raw_time_ms")
    if discipline == "ROUGH_STOCK":
        if raw is not None:
            raise ApiError(
                "ERR_SCORE_OUT_OF_RANGE", 400, "ROUGH_STOCK results carry no time"
            )
        for name, v in (("judge_1_score", j1), ("judge_2_score", j2)):
            if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 50:
                raise ApiError(
                    "ERR_SCORE_OUT_OF_RANGE",
                    400,
                    f"Field {name} must be an integer in 0..50",
                )
        total_score = j1 + j2
        total_time_ms = None
    else:
        if j1 is not None or j2 is not None:
            raise ApiError(
                "ERR_SCORE_OUT_OF_RANGE", 400, "TIMED results carry no judge scores"
            )
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
            raise ApiError(
                "ERR_SCORE_OUT_OF_RANGE",
                400,
                "Field raw_time_ms must be an integer >= 0",
            )
        total_score = None
        total_time_ms = raw + values.get("penalty_ms", 0)
    return total_score, total_time_ms


def _derive_outcome(discipline, qualified_flag, disqualified_flag):
    if disqualified_flag:
        return "DISQUALIFIED"
    if qualified_flag:
        return "QUALIFIED"
    return "NO_SCORE" if discipline == "ROUGH_STOCK" else "NO_TIME"


@bp.post("/run-results")
def create_run_result():
    user_id, role = auth(["Judge"])
    data = body()
    # Body FK existence.
    draw_assignment_id = data.get("draw_assignment_id")
    if draw_assignment_id is not None:
        get_or_404("draw_assignments", draw_assignment_id)
    if not isinstance(draw_assignment_id, str):
        raise ApiError(
            "ERR_VALIDATION", 400, "Missing required field: draw_assignment_id"
        )
    # Field shape.
    qualified_flag = as_bool(required(data, "qualified_flag"), "qualified_flag")
    disqualified_flag = data.get("disqualified_flag", False)
    as_bool(disqualified_flag, "disqualified_flag")
    penalty_ms = data.get("penalty_ms", 0)
    if not isinstance(penalty_ms, int) or isinstance(penalty_ms, bool) or penalty_ms < 0:
        raise ApiError("ERR_VALIDATION", 400, "Field penalty_ms must be >= 0")
    assignment = DB["draw_assignments"][draw_assignment_id]
    # State legality: results are recorded against a live (PENDING) out.
    if assignment["status"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Cannot record a result for a {assignment['status']} assignment",
        )
    event = DB["rodeo_events"][assignment["rodeo_event_id"]]
    rodeo = rodeo_of_event(event)
    # Posture gate: results only while the rodeo is IN_PROGRESS.
    if rodeo["posture"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_RODEO_NOT_OPEN",
            409,
            "Results require the rodeo to be IN_PROGRESS",
        )
    # The acting judge must hold an assignment for the result's performance.
    if not _judge_assigned(user_id, assignment["performance_id"]):
        raise ApiError(
            "ERR_JUDGE_NOT_ASSIGNED",
            409,
            "Judge holds no assignment for this performance",
        )
    # One live result per draw assignment.
    for r in DB["run_results"].values():
        if r["draw_assignment_id"] == draw_assignment_id and r["status"] != "VOIDED":
            raise ApiError(
                "ERR_DUPLICATE_RESULT",
                409,
                "A non-VOIDED result already exists for this assignment",
            )
    total_score, total_time_ms = _validate_discipline_payload(
        event["discipline"], data
    )
    rec = {
        "id": new_id(),
        "draw_assignment_id": draw_assignment_id,
        "entry_id": assignment["entry_id"],
        "rodeo_event_id": assignment["rodeo_event_id"],
        "judge_id": user_id,
        "judge_1_score": data.get("judge_1_score"),
        "judge_2_score": data.get("judge_2_score"),
        "raw_time_ms": data.get("raw_time_ms"),
        "penalty_ms": penalty_ms,
        "qualified_flag": qualified_flag,
        "disqualified_flag": disqualified_flag,
        "outcome": _derive_outcome(
            event["discipline"], qualified_flag, disqualified_flag
        ),
        "total_score": total_score,
        "total_time_ms": total_time_ms,
        "status": "RECORDED",
        "amendment_reason": None,
        "verified_at": None,
        "_verified_dt": None,
    }
    stamp(rec)
    DB["run_results"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@bp.get("/run-results")
def list_run_results():
    auth(ALL_ROLES)
    draw_assignment_id = request.args.get("draw_assignment_id")
    entry_id = request.args.get("entry_id")
    rodeo_event_id = request.args.get("rodeo_event_id")
    judge_id = request.args.get("judge_id")
    status = request.args.get("status")
    items = DB["run_results"].values()
    if draw_assignment_id is not None:
        items = [r for r in items if r["draw_assignment_id"] == draw_assignment_id]
    if entry_id is not None:
        items = [r for r in items if r["entry_id"] == entry_id]
    if rodeo_event_id is not None:
        items = [r for r in items if r["rodeo_event_id"] == rodeo_event_id]
    if judge_id is not None:
        items = [r for r in items if r["judge_id"] == judge_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sorted_created(items)
    limit, offset = pagination_args()
    return ok_list(
        [ser(r) for r in items[offset : offset + limit]], len(items), limit, offset
    )


@bp.get("/run-results/<result_id>")
def get_run_result(result_id):
    auth(ALL_ROLES)
    return ok(ser(get_or_404("run_results", result_id)))


@bp.post("/run-results/<result_id>/transition")
def transition_run_result(result_id):
    user_id, role = auth(["CommitteeAdmin", "Judge"])
    result = get_or_404("run_results", result_id)
    data = body()
    action = data.get("action")
    if action not in _ACTIONS:
        raise ApiError(
            "ERR_VALIDATION", 400, f"Field action must be one of {sorted(_ACTIONS)}"
        )
    if action in ("VERIFY", "VOID") and role != "CommitteeAdmin":
        raise ApiError(
            "ERR_FORBIDDEN", 403, f"Action {action} is restricted to CommitteeAdmin"
        )
    if action == "AMEND" and role != "Judge":
        raise ApiError("ERR_FORBIDDEN", 403, "Action AMEND is restricted to Judge")
    # AMEND shape: amendment_reason is required.
    amendment_reason = None
    if action == "AMEND":
        amendment_reason = data.get("amendment_reason")
        if not isinstance(amendment_reason, str) or not amendment_reason:
            raise ApiError(
                "ERR_VALIDATION", 400, "AMEND requires an amendment_reason"
            )
    if result["status"] not in _VALID_FROM[action]:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Action {action} is not valid from status {result['status']}",
        )
    if action == "VOID":
        result["status"] = "VOIDED"
        touch(result)
        return ok(ser(result))

    assignment = DB["draw_assignments"][result["draw_assignment_id"]]
    event = DB["rodeo_events"][result["rodeo_event_id"]]
    rodeo = rodeo_of_event(event)
    # Results freeze when the rodeo completes: verify/amend need IN_PROGRESS.
    if rodeo["posture"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_RODEO_NOT_OPEN",
            409,
            "Result verification and amendment require the rodeo IN_PROGRESS",
        )
    if action == "VERIFY":
        verify_cascade(result)
        return ok(ser(result))

    # AMEND: the acting judge must hold an assignment for the performance.
    if not _judge_assigned(user_id, assignment["performance_id"]):
        raise ApiError(
            "ERR_JUDGE_NOT_ASSIGNED",
            409,
            "Judge holds no assignment for this performance",
        )
    # Merge corrected fields over the stored values, then re-validate the
    # discipline payload on the merged result.
    merged = {
        "judge_1_score": data.get("judge_1_score", result["judge_1_score"]),
        "judge_2_score": data.get("judge_2_score", result["judge_2_score"]),
        "raw_time_ms": data.get("raw_time_ms", result["raw_time_ms"]),
        "penalty_ms": data.get("penalty_ms", result["penalty_ms"]),
        "qualified_flag": data.get("qualified_flag", result["qualified_flag"]),
        "disqualified_flag": data.get(
            "disqualified_flag", result["disqualified_flag"]
        ),
    }
    for flag in ("qualified_flag", "disqualified_flag"):
        as_bool(merged[flag], flag)
    if (
        not isinstance(merged["penalty_ms"], int)
        or isinstance(merged["penalty_ms"], bool)
        or merged["penalty_ms"] < 0
    ):
        raise ApiError("ERR_VALIDATION", 400, "Field penalty_ms must be >= 0")
    total_score, total_time_ms = _validate_discipline_payload(
        event["discipline"], merged
    )
    amend_compensate(result)
    result["judge_1_score"] = merged["judge_1_score"]
    result["judge_2_score"] = merged["judge_2_score"]
    result["raw_time_ms"] = merged["raw_time_ms"]
    result["penalty_ms"] = merged["penalty_ms"]
    result["qualified_flag"] = merged["qualified_flag"]
    result["disqualified_flag"] = merged["disqualified_flag"]
    result["total_score"] = total_score
    result["total_time_ms"] = total_time_ms
    result["outcome"] = _derive_outcome(
        event["discipline"], merged["qualified_flag"], merged["disqualified_flag"]
    )
    result["amendment_reason"] = amendment_reason
    result["status"] = "AMENDED"
    touch(result)
    return ok(ser(result))
