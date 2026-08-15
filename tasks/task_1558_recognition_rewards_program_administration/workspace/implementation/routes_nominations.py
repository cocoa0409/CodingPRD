"""Routes: nominations and awards (PRD sections 3.3-3.4)."""
from datetime import timedelta

import db
import serialize as ser
import services as svc
from db import now, touch
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_STALE_VERSION, ERR_PROGRAM_NOT_ACTIVE, ERR_EMPLOYEE_SUSPENDED,
    ERR_VELOCITY_LIMIT_EXCEEDED, ERR_SELF_NOMINATION, ERR_SELF_APPROVAL,
    ERR_NOMINEE_NOT_IN_SCOPE, ERR_NOMINATION_TYPE_DISABLED,
    ERR_DUPLICATE_NOMINATION, ERR_IDEMPOTENCY_CONFLICT,
    ERR_BUDGET_NOT_FOUND, ERR_FORBIDDEN_FOR_ROLE, ERR_NOT_FOUND,
)
from flask import Blueprint, request
from response import success, success_list
from validate import (
    auth_context, require_role, get_or_404, body, req_str, opt_str, req_int,
    opt_int, req_enum, pagination_params,
)
from routes_core import READ_ROLES, _sorted_rows, _paginate

bp = Blueprint("nominations", __name__)

REASON_CODES = {"TEAMWORK", "INNOVATION", "CUSTOMER_SAVE", "DELIVERY",
                "MENTORSHIP", "OTHER"}
NOMINATION_TYPES = {"PEER", "MANAGER"}


def _acting_employee(user_id):
    """Entity-backed identity: X-User-ID must resolve to an Employee."""
    emp = db.employees.get(user_id)
    if emp is None:
        raise_err(ERR_NOT_FOUND, "Acting employee not found: %s" % user_id)
    return emp


def _review_prechecks(nomination, user_id, role):
    """Shared pipeline for approve/reject/return-for-revision after state:
    self-dealing (stage 10) then manager scope (stage 11). HRAdmin is never
    scope-limited; the self-approval bar applies whatever the role."""
    if user_id == nomination["nominator_id"]:
        raise_err(ERR_SELF_APPROVAL, "Approver must differ from the nominator")
    if role == "Manager":
        nominee = db.employees.get(nomination["nominee_id"])
        if nominee is None or not svc.in_manager_chain(user_id, nominee):
            raise_err(ERR_NOMINEE_NOT_IN_SCOPE,
                      "Manager approver is not in the nominee's manager chain")


def _release_reservation(nomination):
    b = db.budgets.get(nomination["budget_id"])
    if b is not None and b["posture"] != "CLOSED":
        b["reserved_points"] = max(
            0, b["reserved_points"] - nomination["points_requested"])
        svc.budget_mutated(b)


# ---------------------------------------------------------------------------
# Nominations
# ---------------------------------------------------------------------------

@bp.route("/api/nominations", methods=["POST"])
def create_nomination():
    user_id, role = auth_context()
    require_role(role, ["Employee", "Manager"])
    b = body()
    # Schema-critical fields first (needed for FK resolution).
    program_id = b.get("program_id")
    nominee_id = b.get("nominee_id")
    type_ = req_enum(b, "type", NOMINATION_TYPES)
    reason_code = req_enum(b, "reason_code", REASON_CODES)
    message = req_str(b, "message")
    idem_key = req_str(b, "idempotency_key")
    # Existence: program, nominee, acting (nominator) employee.
    if not isinstance(program_id, str) or program_id not in db.programs:
        raise_err(ERR_NOT_FOUND, "Program not found: %s" % program_id)
    program = db.programs[program_id]
    if not isinstance(nominee_id, str) or nominee_id not in db.employees:
        raise_err(ERR_NOT_FOUND, "Nominee not found: %s" % nominee_id)
    nominee = db.employees[nominee_id]
    nominator = _acting_employee(user_id)
    # Remaining schema: points range (1 .. program.max_points_per_nomination).
    points = req_int(b, "points_requested")
    if points < 1 or points > program["max_points_per_nomination"]:
        raise_err(ERR_INVALID_REQUEST,
                  "points_requested must be between 1 and %d"
                  % program["max_points_per_nomination"])
    # Program gate (stage 7).
    if program["status"] != "ACTIVE":
        raise_err(ERR_PROGRAM_NOT_ACTIVE, "Program is not ACTIVE")
    # Employee standing (stage 8).
    if nominator["program_status"] != "ELIGIBLE":
        raise_err(ERR_EMPLOYEE_SUSPENDED, "Nominator is SUSPENDED")
    # Velocity (stage 9): count non-CANCELLED nominations in the trailing
    # 7 days (inclusive lower bound); breach rejects AND raises an OPEN flag.
    window_start = now() - timedelta(days=7)
    count = sum(
        1 for n in db.nominations.values()
        if n["nominator_id"] == nominator["id"]
        and n["status"] != "CANCELLED"
        and n["created_at"] >= window_start)
    if count >= program["velocity_limit_per_7_days"]:
        svc.raise_system_flag(
            nominator["id"], program["id"], "VELOCITY_EXCEEDED",
            {"count": count, "limit": program["velocity_limit_per_7_days"],
             "window_days": 7})
        raise_err(ERR_VELOCITY_LIMIT_EXCEEDED,
                  "Nominator is at the velocity limit of %d per 7 days"
                  % program["velocity_limit_per_7_days"])
    # Self-dealing (stage 10).
    if nominee_id == nominator["id"]:
        raise_err(ERR_SELF_NOMINATION, "Cannot nominate oneself")
    # Referential scope (stage 11).
    if type_ == "PEER":
        if nominee["department_id"] != nominator["department_id"]:
            raise_err(ERR_NOMINEE_NOT_IN_SCOPE,
                      "PEER nomination requires the same department")
    else:  # MANAGER
        if not svc.in_manager_chain(nominator["id"], nominee):
            raise_err(ERR_NOMINEE_NOT_IN_SCOPE,
                      "MANAGER nomination requires the nominator in the "
                      "nominee's manager chain")
    # Duplicates (stage 12).
    payload = {
        "program_id": program_id, "nominee_id": nominee_id, "type": type_,
        "points_requested": points, "reason_code": reason_code,
        "message": message,
    }
    for n in db.nominations.values():
        if n["nominator_id"] == nominator["id"] \
                and n["idempotency_key"] == idem_key:
            if n["_payload"] == payload:
                return success(ser.nomination(n), 201)  # identical replay
            raise_err(ERR_IDEMPOTENCY_CONFLICT,
                      "idempotency_key reused with a different payload")
    dup_start = now() - timedelta(days=program["duplicate_window_days"])
    for n in db.nominations.values():
        if n["nominator_id"] == nominator["id"] \
                and n["nominee_id"] == nominee_id \
                and n["reason_code"] == reason_code \
                and n["status"] in svc.NON_TERMINAL_NOMINATION_STATUSES \
                and n["created_at"] >= dup_start:
            raise_err(ERR_DUPLICATE_NOMINATION,
                      "A non-terminal nomination with the same nominee and "
                      "reason_code exists in the duplicate window")
    # Temporal (stage 13): nomination type enabled.
    if type_ == "PEER" and not program["peer_nomination_enabled"]:
        raise_err(ERR_NOMINATION_TYPE_DISABLED,
                  "PEER nominations are disabled for this program")
    if type_ == "MANAGER" and not program["manager_nomination_enabled"]:
        raise_err(ERR_NOMINATION_TYPE_DISABLED,
                  "MANAGER nominations are disabled for this program")
    # Budget selection + gate (stages 15-16).
    budget = svc.select_budget(program_id, nominee["department_id"], now().date())
    if budget is None:
        raise_err(ERR_BUDGET_NOT_FOUND,
                  "No budget window contains the submission date")
    svc.budget_gate_check(budget, points)
    # Commit: nomination lands in PENDING_REVIEW; reserve points.
    n = {
        "id": db.new_id(),
        "program_id": program_id,
        "nominator_id": nominator["id"],
        "nominee_id": nominee_id,
        "type": type_,
        "points_requested": points,
        "reason_code": reason_code,
        "message": message,
        "idempotency_key": idem_key,
        "status": "PENDING_REVIEW",
        "revision_count": 0,
        "review_deadline": now() + timedelta(days=program["nomination_review_sla_days"]),
        "budget_id": budget["id"],
        "award_id": None,
        "reviewer_id": None,
        "decided_at": None,
        "_payload": payload,
    }
    db.stamp(n)
    db.nominations[n["id"]] = n
    budget["reserved_points"] += points
    svc.budget_mutated(budget)
    return success(ser.nomination(n), 201)


@bp.route("/api/nominations/<nominationId>", methods=["GET"])
def get_nomination(nominationId):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    n = get_or_404(db.nominations, nominationId, "Nomination")
    return success(ser.nomination(n))


@bp.route("/api/nominations", methods=["GET"])
def list_nominations():
    _, role = auth_context()
    require_role(role, READ_ROLES)
    rows = _sorted_rows(db.nominations.values())
    for param, field in (("program_id", "program_id"),
                         ("nominator_id", "nominator_id"),
                         ("nominee_id", "nominee_id"),
                         ("status", "status"),
                         ("budget_id", "budget_id"),
                         ("award_id", "award_id"),
                         ("reviewer_id", "reviewer_id")):
        v = request.args.get(param)
        if v is not None:
            rows = [n for n in rows if n[field] == v]
    return _paginate(rows, ser.nomination)


@bp.route("/api/nominations/<nominationId>/approve", methods=["POST"])
def approve_nomination(nominationId):
    user_id, role = auth_context()
    require_role(role, ["Manager", "HRAdmin"])
    n = get_or_404(db.nominations, nominationId, "Nomination")
    b = body()
    expected = req_int(b, "expected_nomination_version")
    if n["status"] != "PENDING_REVIEW":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only PENDING_REVIEW nominations can be approved")
    if expected != n["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_nomination_version %s does not match current "
                  "version %s" % (expected, n["version"]))
    _review_prechecks(n, user_id, role)
    # Side effects: award + ledger + budget commit + tier recompute.
    nominee = db.employees[n["nominee_id"]]
    award = svc.create_award(n["program_id"], nominee, n["points_requested"],
                             "NOMINATION", nomination_id=n["id"])
    svc.post_ledger(nominee, "GRANT_NOMINATION", n["points_requested"],
                    "AWARD", award["id"],
                    "%s:GRANT_NOMINATION:%s" % (n["idempotency_key"], award["id"]),
                    "Nomination %s approved: +%d points"
                    % (n["id"], n["points_requested"]))
    svc.emp_grant(nominee, n["points_requested"])
    budget = db.budgets.get(n["budget_id"])
    if budget is not None and budget["posture"] != "CLOSED":
        budget["reserved_points"] = max(0, budget["reserved_points"] - n["points_requested"])
        budget["committed_points"] += n["points_requested"]
        svc.budget_mutated(budget)
    n["status"] = "APPROVED"
    n["award_id"] = award["id"]
    n["decided_at"] = now()
    n["reviewer_id"] = user_id
    touch(n)
    return success(ser.nomination(n))


@bp.route("/api/nominations/<nominationId>/reject", methods=["POST"])
def reject_nomination(nominationId):
    user_id, role = auth_context()
    require_role(role, ["Manager", "HRAdmin"])
    n = get_or_404(db.nominations, nominationId, "Nomination")
    body()  # optional reason
    if n["status"] != "PENDING_REVIEW":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only PENDING_REVIEW nominations can be rejected")
    _review_prechecks(n, user_id, role)
    _release_reservation(n)
    n["status"] = "REJECTED"
    n["decided_at"] = now()
    n["reviewer_id"] = user_id
    touch(n)
    return success(ser.nomination(n))


@bp.route("/api/nominations/<nominationId>/return-for-revision", methods=["POST"])
def return_for_revision(nominationId):
    user_id, role = auth_context()
    require_role(role, ["Manager", "HRAdmin"])
    n = get_or_404(db.nominations, nominationId, "Nomination")
    b = body()
    req_str(b, "feedback")
    if n["status"] != "PENDING_REVIEW":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only PENDING_REVIEW nominations can be returned")
    _review_prechecks(n, user_id, role)
    # Dual outcome (always 200): third return auto-rejects instead.
    if n["revision_count"] >= 2:
        _release_reservation(n)
        n["status"] = "REJECTED"
    else:
        n["status"] = "RETURNED_FOR_REVISION"
        n["revision_count"] += 1
        n["review_deadline"] = now() + timedelta(
            days=db.programs[n["program_id"]]["nomination_review_sla_days"])
    n["decided_at"] = now()
    n["reviewer_id"] = user_id
    touch(n)
    return success(ser.nomination(n))


@bp.route("/api/nominations/<nominationId>/resubmit", methods=["POST"])
def resubmit_nomination(nominationId):
    user_id, role = auth_context()
    require_role(role, ["Employee", "Manager"])
    n = get_or_404(db.nominations, nominationId, "Nomination")
    if user_id != n["nominator_id"]:
        raise_err(ERR_FORBIDDEN_FOR_ROLE,
                  "Only the original nominator may resubmit")
    b = body()
    new_points = None
    if "points_requested" in b and b["points_requested"] is not None:
        new_points = req_int(b, "points_requested")
    new_message = opt_str(b, "message")
    if n["status"] != "RETURNED_FOR_REVISION":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only RETURNED_FOR_REVISION nominations can be resubmitted")
    program = db.programs[n["program_id"]]
    if program["status"] != "ACTIVE":
        raise_err(ERR_PROGRAM_NOT_ACTIVE, "Program is not ACTIVE")
    if new_points is not None:
        if new_points < 1 or new_points > program["max_points_per_nomination"]:
            raise_err(ERR_INVALID_REQUEST,
                      "points_requested must be between 1 and %d"
                      % program["max_points_per_nomination"])
    if new_points is not None and new_points != n["points_requested"]:
        # Re-run the budget gate against the nomination's own budget.
        budget = db.budgets.get(n["budget_id"])
        if budget is None or budget["posture"] == "CLOSED" or not (
                budget["period_start_date"] <= now().date()
                < budget["period_end_date"]):
            raise_err(ERR_BUDGET_NOT_FOUND,
                      "The nomination's budget window no longer applies")
        svc.budget_gate_check(budget, new_points, nomination=n)
        budget["reserved_points"] += new_points - n["points_requested"]
        svc.budget_mutated(budget)
        n["points_requested"] = new_points
        n["_payload"]["points_requested"] = new_points
    if new_message is not None:
        n["message"] = new_message
        n["_payload"]["message"] = new_message
    n["status"] = "PENDING_REVIEW"
    n["review_deadline"] = now() + timedelta(
        days=program["nomination_review_sla_days"])
    touch(n)
    return success(ser.nomination(n))


@bp.route("/api/nominations/<nominationId>/cancel", methods=["POST"])
def cancel_nomination(nominationId):
    user_id, role = auth_context()
    require_role(role, ["Employee", "Manager"])
    n = get_or_404(db.nominations, nominationId, "Nomination")
    if user_id != n["nominator_id"]:
        raise_err(ERR_FORBIDDEN_FOR_ROLE,
                  "Only the nominator may cancel the nomination")
    if n["status"] not in ("PENDING_REVIEW", "RETURNED_FOR_REVISION"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only PENDING_REVIEW or RETURNED_FOR_REVISION nominations "
                  "can be cancelled")
    _release_reservation(n)
    n["status"] = "CANCELLED"
    touch(n)
    return success(ser.nomination(n))


# ---------------------------------------------------------------------------
# Awards
# ---------------------------------------------------------------------------

@bp.route("/api/awards/<awardId>", methods=["GET"])
def get_award(awardId):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    a = get_or_404(db.awards, awardId, "Award")
    return success(ser.award(a))


@bp.route("/api/awards", methods=["GET"])
def list_awards():
    _, role = auth_context()
    require_role(role, READ_ROLES)
    rows = _sorted_rows(db.awards.values())
    for param, field in (("employee_id", "employee_id"),
                         ("program_id", "program_id"),
                         ("nomination_id", "nomination_id"),
                         ("source", "source"),
                         ("status", "status"),
                         ("revoked_by_flag_id", "revoked_by_flag_id")):
        v = request.args.get(param)
        if v is not None:
            rows = [a for a in rows if a[field] == v]
    return _paginate(rows, ser.award)


@bp.route("/api/awards/<awardId>/revoke", methods=["POST"])
def revoke_award(awardId):
    _, role = auth_context()
    require_role(role, ["HRAdmin"])
    a = get_or_404(db.awards, awardId, "Award")
    body()  # optional reason
    if a["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only ACTIVE awards can be revoked")
    emp = db.employees[a["employee_id"]]
    svc.revoke_award(a, emp, flag_id=None)
    return success(ser.award(a))
