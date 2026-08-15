"""Absence case endpoints: report, cover (version-guarded), declare-uncovered, close."""
from flask import request, Blueprint

from db import db, mint, touch, ser
from errors import (
    ApiError,
    forbidden,
    invalid_state,
    validation,
    ERR_DATE_OUT_OF_RANGE,
    ERR_NO_COVER_AVAILABLE,
    ERR_STALE_VERSION,
)
from helpers import (
    body_json,
    req_date,
    req_enum,
    req_field,
    is_int,
    get_absence_or_404,
    ref_operator_or_404,
    paginated,
)
from middleware import authenticate, require_roles, READ_SO_OP_UR
from response import ok_obj
from services.workflow import create_assignment

bp = Blueprint("absences", __name__)

SO = ["SchedulingOfficer"]
REASON_CODES = ("SICK", "PERSONAL", "VACATION", "UNEXCUSED")


def _absent_assignment(case):
    """The absent operator's SCHEDULED assignment on the absence date with a run."""
    candidates = [
        a
        for a in db.daily_assignments.values()
        if a["operator_id"] == case["operator_id"]
        and a["service_date"] == case["absence_date"]
        and a["run_id"] is not None
    ]
    scheduled = [a for a in candidates if a["status"] == "SCHEDULED"]
    if scheduled:
        return sorted(scheduled, key=lambda a: (a["created_at"], a["_seq"]))[0]
    if candidates:
        return sorted(candidates, key=lambda a: (a["created_at"], a["_seq"]))[0]
    return None


def _board_candidates(case):
    return [
        o
        for o in db.operators.values()
        if o["status"] == "EXTRA_BOARD" and o["id"] != case["operator_id"]
    ]


def _ot_candidates(case):
    return [
        o
        for o in db.operators.values()
        if o["status"] == "ACTIVE" and o["id"] != case["operator_id"]
    ]


@bp.post("/api/absence-cases")
def report_absence():
    auth = authenticate()
    require_roles(auth, ["SchedulingOfficer", "Operator"])
    body = body_json()
    operator_id = req_field(body, "operator_id")
    if not isinstance(operator_id, str):
        raise validation("operator_id must be a string")
    absence_date = req_date(body, "absence_date")
    reason_code = req_enum(body, "reason_code", REASON_CODES)
    # An Operator reports only their own absence
    if auth["role"] == "Operator" and operator_id != auth["user_id"]:
        raise forbidden("Operators may report only their own absence")
    ref_operator_or_404(operator_id)

    # The absence_date must fall within the sign-up window of the operator's
    # affected assignment. The operator's assignments determine the referenced
    # sign-up window(s); a date outside every such window is rejected. When the
    # operator holds no assignments at all, no window is referenced and the
    # report is accepted.
    op_assignments = [
        a for a in db.daily_assignments.values() if a["operator_id"] == operator_id
    ]
    windows = set()
    for a in op_assignments:
        period = db.sign_up_periods.get(a["sign_up_period_id"])
        if period is not None:
            windows.add((period["effective_start_date"], period["effective_end_date"]))
    if windows and not any(lo <= absence_date <= hi for lo, hi in windows):
        raise ApiError(
            ERR_DATE_OUT_OF_RANGE,
            "absence_date outside the sign-up window of the affected assignment",
            422,
        )

    case = mint()
    case.update(
        {
            "operator_id": operator_id,
            "absence_date": absence_date,
            "reason_code": reason_code,
            "status": "REPORTED",
            "covering_assignment_id": None,
        }
    )
    db.absence_cases[case["id"]] = case
    return ok_obj(ser(case), 201)


@bp.get("/api/absence-cases")
def list_absences():
    auth = authenticate()
    require_roles(auth, READ_SO_OP_UR)
    items = list(db.absence_cases.values())
    for param in ("operator_id", "status", "covering_assignment_id"):
        raw = request.args.get(param)
        if raw is not None:
            items = [a for a in items if a[param] == raw]
    return paginated(items)


@bp.get("/api/absence-cases/<aid>")
def get_absence(aid):
    auth = authenticate()
    require_roles(auth, READ_SO_OP_UR)
    return ok_obj(ser(get_absence_or_404(aid)))


@bp.post("/api/absence-cases/<aid>/cover")
def cover_absence(aid):
    auth = authenticate()
    require_roles(auth, SO)
    case = get_absence_or_404(aid)
    body = body_json()
    expected_version = req_field(body, "expected_absence_case_version")
    if not is_int(expected_version):
        raise validation("expected_absence_case_version must be an integer")
    allow_overtime = body.get("allow_overtime") is True

    if case["status"] != "REPORTED":
        raise invalid_state("Only a REPORTED absence case may be covered")

    # Precondition: the absent operator must hold a SCHEDULED assignment with
    # a run on the absence date.
    assignment = _absent_assignment(case)
    if assignment is None or assignment["status"] != "SCHEDULED":
        raise invalid_state(
            "The absent operator holds no SCHEDULED assignment with a run on the absence date"
        )

    # Selection: board path first; overtime path only when the board is empty
    # and allow_overtime is true.
    board = _board_candidates(case)
    cover_op = None
    source = None
    if board:
        cover_op = min(
            board,
            key=lambda o: (
                o["board_position"] if o["board_position"] is not None else 1 << 30,
                o["hire_date"],
            ),
        )
        source = "EXTRA_BOARD_FILL"
    elif allow_overtime:
        ot_pool = _ot_candidates(case)
        if ot_pool:
            cover_op = min(
                ot_pool,
                key=lambda o: (o["weekly_ot_minutes_accum"], o["seniority_rank"]),
            )
            source = "OVERTIME_OFFER"
    if cover_op is None:
        raise ApiError(
            ERR_NO_COVER_AVAILABLE,
            "No eligible extra-board or overtime candidate to cover the absence",
            409,
        )

    # Optimistic concurrency closes the ladder
    if expected_version != case["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_absence_case_version does not match the case's current version",
            412,
        )

    period = db.sign_up_periods.get(assignment["sign_up_period_id"])
    run = db.runs.get(assignment["run_id"])
    scheduled_minutes = run["paid_minutes"] if run is not None else 0
    covering = create_assignment(
        period,
        cover_op["id"],
        assignment["run_id"],
        assignment["service_date"],
        source,
        scheduled_minutes,
    )

    # Board-held runs handed to a covering operator become awarded to them
    if run is not None and run["status"] == "EXTRA_BOARD_HELD":
        run["status"] = "AWARDED"
        run["awarded_operator_id"] = cover_op["id"]
        touch(run)

    assignment["status"] = "NO_SHOW"
    touch(assignment)

    case["status"] = "COVERED"
    case["covering_assignment_id"] = covering["id"]
    touch(case)
    return ok_obj(ser(case))


@bp.post("/api/absence-cases/<aid>/declare-uncovered")
def declare_uncovered(aid):
    auth = authenticate()
    require_roles(auth, SO)
    case = get_absence_or_404(aid)
    if case["status"] != "REPORTED":
        raise invalid_state("Only a REPORTED absence case may be declared uncovered")
    # Permitted only when no eligible covering operator exists: board empty
    # and the overtime path exhausted.
    if _board_candidates(case) or _ot_candidates(case):
        raise invalid_state("An eligible covering operator exists")
    assignment = _absent_assignment(case)
    if assignment is not None and assignment["status"] == "SCHEDULED":
        assignment["status"] = "CANCELLED"
        touch(assignment)
    case["status"] = "UNCOVERED"
    touch(case)
    return ok_obj(ser(case))


@bp.post("/api/absence-cases/<aid>/close")
def close_absence(aid):
    auth = authenticate()
    require_roles(auth, SO)
    case = get_absence_or_404(aid)
    if case["status"] == "COVERED":
        covering = db.daily_assignments.get(case["covering_assignment_id"] or "")
        if covering is None or covering["status"] not in ("WORKED", "CANCELLED"):
            raise invalid_state(
                "A COVERED case closes only once the covering assignment is WORKED or CANCELLED"
            )
    elif case["status"] == "UNCOVERED":
        pass
    else:
        raise invalid_state("Only a COVERED or UNCOVERED absence case may be closed")
    case["status"] = "CLOSED"
    touch(case)
    return ok_obj(ser(case))
