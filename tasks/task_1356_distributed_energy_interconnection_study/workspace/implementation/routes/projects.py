"""Project endpoints: submission, deposits, milestone submissions, withdrawal,
commercial-operation declaration, curtailment limits, cost-share listing.

Validation categories run in the fixed pipeline order of PRD section 2.8:
auth headers -> role permission -> existence (left to right) -> Developer
ownership -> OCC -> state preconditions -> clock-relative deadlines ->
cross-entity state -> structural constraints (incl. ERR_INVALID_REQUEST) ->
deposit-ledger fiscal check."""
from decimal import Decimal

from flask import Blueprint

from clock import CLOCK, parse_iso
from db import (DB, new_id, next_seq, pub, sort_key, stamp_new,
                stamp_new_immutable, touch)
from errors import ApiError
from middleware import READ_ROLES, auth
from response import ok, ok_list
from services import (agreements_of, assess_deposit, cost_shares_of_project,
                      ledger_of, limits_of, members_of, post_ledger,
                      submissions_of, withdraw_project, maybe_close_cluster)
from util import (body, pagination_args, req_dt_str, req_enum, req_int, req_num,
                  req_str)

bp = Blueprint("projects", __name__)

TECHNOLOGIES = ("SOLAR", "WIND", "STORAGE", "HYBRID")
SERVICE_TYPES = ("ENERGY_ONLY", "CAPACITY")
MILESTONE_TYPES = ("SITE_CONTROL", "TECHNICAL_DATA")
LIMIT_TYPES = ("SEASONAL", "EMERGENCY", "ECONOMIC")


def _get_project(project_id):
    project = DB["projects"].get(project_id)
    if project is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND", 404, "Project id does not exist")
    return project


def _check_ownership(project, user_id):
    if project["developer_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN_RESOURCE_OWNERSHIP", 403,
            "Developer-role caller does not own the target project",
        )


# ---------------------------------------------------------------------------
# Project submission
# ---------------------------------------------------------------------------

@bp.route("/interconnection/projects", methods=["POST"])
def create_project():
    user_id, _role = auth(["Developer"])
    data = body()

    # Existence, body identifiers left to right: developer_id, cluster_group_id.
    developer_id = data.get("developer_id")
    if not isinstance(developer_id, str) or not developer_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "developer_id is required")
    developer = DB["developers"].get(developer_id)
    if developer is None:
        raise ApiError("ERR_DEVELOPER_NOT_FOUND", 404, "Developer id does not exist")
    cluster_group_id = data.get("cluster_group_id")
    if not isinstance(cluster_group_id, str) or not cluster_group_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "cluster_group_id is required")
    cluster = DB["cluster_groups"].get(cluster_group_id)
    if cluster is None:
        raise ApiError("ERR_CLUSTER_GROUP_NOT_FOUND", 404, "ClusterGroup id does not exist")

    # Ownership: the body developer_id must equal the caller's X-User-ID.
    if developer_id != user_id:
        raise ApiError(
            "ERR_FORBIDDEN_RESOURCE_OWNERSHIP", 403,
            "Developer-role caller does not own the target project",
        )

    # State: the cluster admits projects only while FORMING.
    if cluster["status"] != "FORMING":
        raise ApiError(
            "ERR_CLUSTER_NOT_ACCEPTING_PROJECTS", 409,
            "ClusterGroup is not accepting new projects",
        )

    # Structural constraints.
    project_name = req_str(data, "project_name")
    technology = req_enum(data, "technology", TECHNOLOGIES)
    capacity_mw = req_num(data, "capacity_mw")
    service_type = req_enum(data, "service_type", SERVICE_TYPES)
    poi = req_str(data, "point_of_interconnection")

    # Cluster capacity: committed_mw + capacity_mw must not exceed capacity_mw.
    if (Decimal(str(cluster["committed_mw"])) + Decimal(str(capacity_mw))
            > Decimal(str(cluster["capacity_mw"]))):
        raise ApiError(
            "ERR_CLUSTER_CAPACITY_EXCEEDED", 409,
            "committed_mw + capacity_mw would exceed the cluster capacity_mw",
        )
    if not (capacity_mw > 0) or capacity_mw > 500:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "capacity_mw must be greater than 0 and at most 500",
        )

    project = {
        "id": new_id(),
        "_seq": next_seq(),
        "developer_id": developer_id,
        "cluster_group_id": cluster_group_id,
        "project_name": project_name,
        "technology": technology,
        "capacity_mw": capacity_mw,
        "service_type": service_type,
        "point_of_interconnection": poi,
        "queue_position": None,
        "deposit_required_cents": assess_deposit(technology, capacity_mw, service_type),
        "deposit_posted_cents": 0,
        "readiness_satisfied": False,
        "status": "SUBMITTED",
    }
    stamp_new(project)
    DB["projects"][project["id"]] = project

    # committed_mw rises by the project's capacity_mw on creation.
    cluster["committed_mw"] = _num_add(cluster["committed_mw"], capacity_mw)
    touch(cluster)
    return ok(pub(project), 201)


def _num_add(a, b):
    d = Decimal(str(a)) + Decimal(str(b))
    return int(d) if d == d.to_integral_value() else float(d)


@bp.route("/interconnection/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    auth(READ_ROLES)
    return ok(pub(_get_project(project_id)))


# ---------------------------------------------------------------------------
# Deposit ledger
# ---------------------------------------------------------------------------

@bp.route("/interconnection/projects/<project_id>/deposits", methods=["POST"])
def post_deposit(project_id):
    user_id, _role = auth(["Developer"])
    project = _get_project(project_id)
    _check_ownership(project, user_id)

    # State: deposits are accepted only in SUBMITTED or QUEUED.
    if project["status"] not in ("SUBMITTED", "QUEUED"):
        raise ApiError(
            "ERR_PROJECT_NOT_ACCEPTING_DEPOSITS", 409,
            "Deposit posted while project status is not SUBMITTED or QUEUED",
        )

    data = body()
    amount_cents = req_int(data, "amount_cents")
    if amount_cents <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "amount_cents must be positive")

    # Fiscal check (last in the pipeline): overpayment is never booked.
    if project["deposit_posted_cents"] + amount_cents > project["deposit_required_cents"]:
        raise ApiError(
            "ERR_DEPOSIT_OVERPAYMENT", 422,
            "Deposit would push deposit_posted_cents above deposit_required_cents",
        )

    tx = post_ledger(project, "DEPOSIT", amount_cents)

    # Auto-promotion: reaching the required amount while SUBMITTED assigns the
    # next dense queue position among non-withdrawn cluster members.
    if (project["status"] == "SUBMITTED"
            and project["deposit_posted_cents"] >= project["deposit_required_cents"]):
        project["status"] = "QUEUED"
        positions = [
            m["queue_position"]
            for m in members_of(project["cluster_group_id"])
            if m["status"] != "WITHDRAWN" and m["queue_position"] is not None
        ]
        project["queue_position"] = 1 + (max(positions) if positions else 0)
    touch(project)
    return ok(pub(tx), 201)


@bp.route("/interconnection/projects/<project_id>/deposits", methods=["GET"])
def list_deposits(project_id):
    auth(READ_ROLES)
    _get_project(project_id)
    limit, offset = pagination_args()
    items = ledger_of(project_id)
    page = items[offset:offset + limit]
    return ok_list([pub(t) for t in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# Milestone submissions (create + list; review/resubmit live in milestones.py)
# ---------------------------------------------------------------------------

@bp.route("/interconnection/projects/<project_id>/milestone-submissions", methods=["POST"])
def create_milestone_submission(project_id):
    user_id, _role = auth(["Developer"])
    project = _get_project(project_id)
    _check_ownership(project, user_id)

    # State: submissions are accepted only in SUBMITTED or QUEUED.
    if project["status"] not in ("SUBMITTED", "QUEUED"):
        raise ApiError(
            "ERR_PROJECT_NOT_ACCEPTING_MILESTONES", 409,
            "Milestone submission while project status is not SUBMITTED or QUEUED",
        )

    data = body()
    milestone_type = req_enum(data, "milestone_type", MILESTONE_TYPES)
    evidence_uri = req_str(data, "evidence_uri")

    # At most one live (PENDING_REVIEW or ACCEPTED) submission per
    # (project, milestone_type).
    for existing in submissions_of(project_id):
        if (existing["milestone_type"] == milestone_type
                and existing["status"] in ("PENDING_REVIEW", "ACCEPTED")):
            raise ApiError(
                "ERR_MILESTONE_SUBMISSION_CONFLICT", 409,
                "A PENDING_REVIEW or ACCEPTED submission already exists for "
                "this project and milestone_type",
            )

    submission = {
        "id": new_id(),
        "_seq": next_seq(),
        "project_id": project_id,
        "milestone_type": milestone_type,
        "evidence_uri": evidence_uri,
        "status": "PENDING_REVIEW",
        "review_note": None,
    }
    stamp_new(submission)
    DB["milestone_submissions"][submission["id"]] = submission
    return ok(pub(submission), 201)


@bp.route("/interconnection/projects/<project_id>/milestone-submissions", methods=["GET"])
def list_milestone_submissions(project_id):
    auth(READ_ROLES)
    _get_project(project_id)
    limit, offset = pagination_args()
    items = submissions_of(project_id)
    page = items[offset:offset + limit]
    return ok_list([pub(s) for s in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# Withdrawal / commercial operation
# ---------------------------------------------------------------------------

@bp.route("/interconnection/projects/<project_id>/withdraw", methods=["POST"])
def withdraw(project_id):
    user_id, role = auth(["Developer", "QueueAdministrator"])
    project = _get_project(project_id)
    if role == "Developer":
        _check_ownership(project, user_id)

    # State: withdrawal is not permitted from a terminal state.
    if project["status"] in ("WITHDRAWN", "COMMERCIAL_OPERATION"):
        raise ApiError(
            "ERR_PROJECT_NOT_WITHDRAWABLE", 409,
            "Withdraw not allowed from COMMERCIAL_OPERATION or WITHDRAWN",
        )

    withdraw_project(project, scoping=False)
    return ok(pub(project), 200)


@bp.route("/interconnection/projects/<project_id>/declare-commercial-operation",
          methods=["POST"])
def declare_commercial_operation(project_id):
    user_id, _role = auth(["Developer"])
    project = _get_project(project_id)
    _check_ownership(project, user_id)

    # State: the project must be AGREEMENT_EXECUTED.
    if project["status"] != "AGREEMENT_EXECUTED":
        raise ApiError(
            "ERR_PROJECT_NOT_READY_FOR_OPERATION", 409,
            "declare-commercial-operation requires project AGREEMENT_EXECUTED",
        )

    # Clock: declaration no later than the (extended) target_cod; the boundary
    # timestamp itself is permitted.
    executed = next(
        (a for a in reversed(agreements_of(project_id)) if a["status"] == "EXECUTED"),
        None,
    )
    target_cod = parse_iso(executed["target_cod"]) if executed is not None else None
    if target_cod is None or CLOCK.now() > target_cod:
        raise ApiError(
            "ERR_COD_DEADLINE_PASSED", 409,
            "Commercial operation declared after the (extended) target_cod",
        )

    project["status"] = "COMMERCIAL_OPERATION"
    touch(project)

    # Bubble-up: the cluster closes when, counting this declaration, every
    # member sits in a terminal state.
    cluster = DB["cluster_groups"][project["cluster_group_id"]]
    maybe_close_cluster(cluster)
    return ok(pub(project), 200)


# ---------------------------------------------------------------------------
# Curtailment / operating limits
# ---------------------------------------------------------------------------

@bp.route("/interconnection/projects/<project_id>/curtailment-limits", methods=["POST"])
def create_curtailment_limit(project_id):
    auth(["QueueAdministrator"])
    project = _get_project(project_id)

    # State: limits are recorded once the project is AGREEMENT_EXECUTED or in
    # COMMERCIAL_OPERATION.
    if project["status"] not in ("AGREEMENT_EXECUTED", "COMMERCIAL_OPERATION"):
        raise ApiError(
            "ERR_PROJECT_NOT_ACCEPTING_CURTAILMENT_LIMITS", 409,
            "Curtailment limit requires project AGREEMENT_EXECUTED or "
            "COMMERCIAL_OPERATION",
        )

    data = body()
    limit_type = req_enum(data, "limit_type", LIMIT_TYPES)
    max_output_mw = req_num(data, "max_output_mw")
    effective_start_raw = req_dt_str(data, "effective_start")
    effective_end_raw = req_dt_str(data, "effective_end")
    hours = req_int(data, "curtailment_hours_per_year")
    if not (max_output_mw > 0) or max_output_mw > project["capacity_mw"]:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "max_output_mw must be greater than 0 and no more than the project "
            "capacity_mw",
        )
    if hours < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "curtailment_hours_per_year must be at least 0",
        )

    # The effective interval is CLOSED [start, end]; end strictly after start.
    effective_start = parse_iso(effective_start_raw)
    effective_end = parse_iso(effective_end_raw)
    if effective_end <= effective_start:
        raise ApiError(
            "ERR_INVALID_WINDOW", 400,
            "effective_end must be strictly after effective_start",
        )

    # Disjointness per (project, limit_type); closed intervals, so touching
    # endpoints count as overlap.
    for existing in limits_of(project_id):
        if existing["limit_type"] != limit_type:
            continue
        ex_start = parse_iso(existing["effective_start"])
        ex_end = parse_iso(existing["effective_end"])
        if effective_start <= ex_end and ex_start <= effective_end:
            raise ApiError(
                "ERR_CURTAILMENT_WINDOW_OVERLAP", 409,
                "Effective interval overlaps an existing limit of the same "
                "project and limit_type",
            )

    limit = {
        "id": new_id(),
        "_seq": next_seq(),
        "project_id": project_id,
        "limit_type": limit_type,
        "max_output_mw": max_output_mw,
        "effective_start": effective_start_raw,
        "effective_end": effective_end_raw,
        "curtailment_hours_per_year": hours,
    }
    stamp_new_immutable(limit)
    DB["curtailment_limits"][limit["id"]] = limit
    return ok(pub(limit), 201)


@bp.route("/interconnection/projects/<project_id>/curtailment-limits", methods=["GET"])
def list_curtailment_limits(project_id):
    auth(READ_ROLES)
    _get_project(project_id)
    limit, offset = pagination_args()
    items = limits_of(project_id)
    page = items[offset:offset + limit]
    return ok_list([pub(c) for c in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# Cost shares borne by a project
# ---------------------------------------------------------------------------

@bp.route("/interconnection/projects/<project_id>/cost-shares", methods=["GET"])
def list_project_cost_shares(project_id):
    auth(READ_ROLES)
    _get_project(project_id)
    limit, offset = pagination_args()
    items = cost_shares_of_project(project_id)
    page = items[offset:offset + limit]
    return ok_list([pub(c) for c in page], len(items), limit, offset)
