"""Assignment routes: create, get, list, accept, decline, terminate."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PLAN_NOT_PUBLISHED,
    ERR_ASSIGNMENT_WINDOW_OVERLAP,
    ERR_QUOTA_INVALID,
)
from middleware import authorized, check_rep_ownership
from response import success_object, success_list
from util import new_entity, touch, serialize
from validate import (
    get_body, req_str, opt_str, req_int, opt_int,
    opt_bool, req_date, opt_nullable_date,
    parse_pagination, require_path_resource,
)
from services.crediting import (
    accept_assignment_cascade,
    reverse_assignment_credits,
    get_program_for_assignment,
)
from services.calculations import recompute_assignment_indicators

bp = Blueprint("assignments", __name__)

ADMIN_ONLY = ["CompAdmin"]
REP_ONLY = ["Rep"]
ALL_ROLES = ["CompAdmin", "CompAnalyst", "CompManager", "Rep"]


def _check_assignment_window_overlap(rep_id, start_date, end_date, exclude_id=None):
    """Half-open [start, end) overlap per rep; adjacency allowed; null end = open-ended."""
    for a in db["assignments"].values():
        if a["rep_id"] != rep_id:
            continue
        if a["status"] == "TERMINATED":
            continue
        if exclude_id and a["id"] == exclude_id:
            continue
        a_start = a["effective_start_date"]
        a_end = a["effective_end_date"]  # None = open-ended

        # Half-open overlap: [s1, e1) intersects [s2, e2) iff s1 < e2 AND s2 < e1
        # With null end treated as +infinity
        e1 = end_date if end_date is not None else "9999-12-31"
        e2 = a_end if a_end is not None else "9999-12-31"

        if start_date < e2 and a_start < e1:
            raise_error(ERR_ASSIGNMENT_WINDOW_OVERLAP,
                        f"assignment window [{start_date}, {end_date}) overlaps with existing assignment {a['id']}")


@bp.route("/assignments", methods=["POST"])
def create_assignment():
    caller = authorized(ADMIN_ONLY)
    body = get_body()

    # Basic field validation
    program_id = req_str(body, "program_id")
    rep_id = req_str(body, "rep_id")
    plan_id = req_str(body, "plan_id")
    quota_cents = req_int(body, "quota_cents")
    draw_amount = opt_int(body, "draw_amount_cents_per_period", 0)
    draw_recoverable = opt_bool(body, "draw_recoverable", True)
    guarantee_amount = opt_int(body, "guarantee_amount_cents_per_period", 0)
    start_date = req_date(body, "effective_start_date")
    end_date = opt_nullable_date(body, "effective_end_date", None)

    if draw_amount < 0:
        raise_error(ERR_INVALID_REQUEST, "draw_amount_cents_per_period must be >= 0")
    if guarantee_amount < 0:
        raise_error(ERR_INVALID_REQUEST, "guarantee_amount_cents_per_period must be >= 0")

    # Priority 3: existence (left-to-right: program, rep, plan)
    program = db["programs"].get(program_id)
    if program is None:
        raise_error(ERR_NOT_FOUND, f"program not found: {program_id}")
    rep = db["reps"].get(rep_id)
    if rep is None:
        raise_error(ERR_NOT_FOUND, f"rep not found: {rep_id}")
    plan = db["plans"].get(plan_id)
    if plan is None:
        raise_error(ERR_NOT_FOUND, f"plan not found: {plan_id}")

    # Priority 4: plan must be PUBLISHED
    if plan["status"] != "PUBLISHED":
        raise_error(ERR_PLAN_NOT_PUBLISHED,
                    f"plan is {plan['status']}, must be PUBLISHED")

    # Priority 6: temporal — end > start when present
    if end_date is not None and end_date <= start_date:
        raise_error(ERR_INVALID_REQUEST,
                    "effective_end_date must be > effective_start_date")

    # Priority 7: window overlap
    _check_assignment_window_overlap(rep_id, start_date, end_date)

    # Priority 9: quota > 0
    if quota_cents <= 0:
        raise_error(ERR_QUOTA_INVALID, "quota_cents must be > 0")

    assignment = new_entity({
        "program_id": program_id,
        "rep_id": rep_id,
        "plan_id": plan_id,
        "quota_cents": quota_cents,
        "draw_amount_cents_per_period": draw_amount,
        "draw_recoverable": draw_recoverable,
        "guarantee_amount_cents_per_period": guarantee_amount,
        "effective_start_date": start_date,
        "effective_end_date": end_date,
        "status": "ACTIVE",
        "acceptance_status": "OFFERED",
        "accepted_document_version": None,
        "draw_outstanding_cents": 0,
        "draw_forgiven_cents": 0,
        "current_period_earned_cents": 0,
        "current_attainment_bps": 0,
        "provisional_period_payout_cents": 0,
        "lifetime_earned_cents": 0,
        "lifetime_paid_cents": 0,
        "_rollup_earned_cents": 0,
    })
    db["assignments"][assignment["id"]] = assignment
    return success_object(serialize(assignment), 201)


@bp.route("/assignments/<assignmentId>", methods=["GET"])
def get_assignment(assignmentId):
    caller = authorized(ALL_ROLES)
    assignment = require_path_resource("assignments", assignmentId)
    check_rep_ownership(caller, assignment["rep_id"])
    return success_object(serialize(assignment))


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    caller = authorized(ALL_ROLES)
    limit, offset = parse_pagination()

    items = list(db["assignments"].values())

    # Rep callers: own assignments only
    if caller.role == "Rep":
        items = [a for a in items if a["rep_id"] == caller.user_id]

    # Filters
    program_id = request.args.get("program_id")
    rep_id = request.args.get("rep_id")
    plan_id = request.args.get("plan_id")
    status_filter = request.args.get("status")
    acceptance_filter = request.args.get("acceptance_status")

    if program_id:
        items = [a for a in items if a["program_id"] == program_id]
    if rep_id:
        items = [a for a in items if a["rep_id"] == rep_id]
    if plan_id:
        items = [a for a in items if a["plan_id"] == plan_id]
    if status_filter:
        items = [a for a in items if a["status"] == status_filter]
    if acceptance_filter:
        items = [a for a in items if a["acceptance_status"] == acceptance_filter]

    items.sort(key=lambda a: (a["created_at"], a["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(a) for a in page], total, limit, offset)


@bp.route("/assignments/<assignmentId>/accept", methods=["POST"])
def accept_assignment(assignmentId):
    caller = authorized(REP_ONLY)
    assignment = require_path_resource("assignments", assignmentId)
    check_rep_ownership(caller, assignment["rep_id"])

    # Priority 4: state — must be OFFERED or DECLINED
    if assignment["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"assignment is {assignment['status']}")
    if assignment["acceptance_status"] not in ("OFFERED", "DECLINED"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"acceptance_status is {assignment['acceptance_status']}")

    # Priority 4: plan must be PUBLISHED
    plan = db["plans"][assignment["plan_id"]]
    if plan["status"] != "PUBLISHED":
        raise_error(ERR_PLAN_NOT_PUBLISHED,
                    f"plan is {plan['status']}")

    # Side effects
    assignment["acceptance_status"] = "ACCEPTED"
    assignment["accepted_document_version"] = plan["document_version"]
    touch(assignment)

    # Cascade: PENDING credits -> POSTED
    program = get_program_for_assignment(assignment)
    accept_assignment_cascade(assignment, program)

    return success_object(serialize(assignment))


@bp.route("/assignments/<assignmentId>/decline", methods=["POST"])
def decline_assignment(assignmentId):
    caller = authorized(REP_ONLY)
    assignment = require_path_resource("assignments", assignmentId)
    check_rep_ownership(caller, assignment["rep_id"])

    # Priority 4: state — must be OFFERED
    if assignment["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"assignment is {assignment['status']}")
    if assignment["acceptance_status"] != "OFFERED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"acceptance_status is {assignment['acceptance_status']}, must be OFFERED")

    assignment["acceptance_status"] = "DECLINED"
    touch(assignment)
    return success_object(serialize(assignment))


@bp.route("/assignments/<assignmentId>/terminate", methods=["POST"])
def terminate_assignment(assignmentId):
    caller = authorized(ADMIN_ONLY)
    assignment = require_path_resource("assignments", assignmentId)

    # Priority 4: state — must be ACTIVE
    if assignment["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"assignment is {assignment['status']}")

    program = get_program_for_assignment(assignment)

    # Reverse credits
    reverse_assignment_credits(assignment, program)

    # Draw forgiveness
    if assignment["draw_recoverable"]:
        assignment["draw_forgiven_cents"] = (
            assignment.get("draw_forgiven_cents", 0)
            + assignment.get("draw_outstanding_cents", 0)
        )
        assignment["draw_outstanding_cents"] = 0

    assignment["status"] = "TERMINATED"
    touch(assignment)

    return success_object(serialize(assignment))
