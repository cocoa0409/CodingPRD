"""Report snapshots & benchmark sets (PRD §3.5, §3.6)."""

from decimal import Decimal, InvalidOperation

from flask import Blueprint, request

from db import db, stamp_new, touch, public
from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_CONFIDENTIALITY,
    ERR_SNAPSHOT_NOT_PUBLISHED, ERR_BENCHMARK_TOO_SMALL, ERR_INVALID_STATE,
)
from middleware import (
    require_roles, parse_pagination, paginate, get_json_body, require_fields,
    optional_fields_present, as_non_empty_string, as_number,
)
from response import success_object, success_list
from services.domain import manager_subtree_ids, recompute_snapshot

bp = Blueprint("snapshots", __name__)


def _get_snapshot_or_404(snap_id):
    snap = db.report_snapshots.get(snap_id)
    if snap is None:
        raise err(ERR_NOT_FOUND, "report snapshot not found", 404)
    return snap


def _manager_gate(snap, user_id):
    """UnitManager confidentiality gate (PRD §2.6):

    - subtree restriction -> ERR_CONFIDENTIALITY
    - unpublished (cycle SCORING) -> ERR_SNAPSHOT_NOT_PUBLISHED
    - other pre-REPORTED states have no snapshots in practice; any manager
      read while the cycle has not reached REPORTED is refused with the
      publish-gate error when snapshots exist.
    """
    subtree = manager_subtree_ids(user_id)
    if snap["unit_id"] not in subtree:
        raise err(ERR_CONFIDENTIALITY,
                  "snapshot is outside the manager's unit subtree", 403)
    cycle = db.survey_cycles.get(snap["cycle_id"])
    if cycle is not None and cycle["status"] != "REPORTED" and cycle["status"] != "ARCHIVED":
        raise err(ERR_SNAPSHOT_NOT_PUBLISHED,
                  "snapshot is not yet published", 409)


@bp.get("/engagement/report-snapshots")
def list_snapshots():
    user_id, role = require_roles("HRAdmin", "PeopleAnalyst", "UnitManager", "Executive")
    limit, offset = parse_pagination({"cycle_id", "unit_id", "scope"})
    cycle_id = request.args.get("cycle_id")
    unit_id = request.args.get("unit_id")
    scope = request.args.get("scope")

    items = list(db.report_snapshots.values())
    if cycle_id is not None:
        items = [s for s in items if s["cycle_id"] == cycle_id]
    if unit_id is not None:
        items = [s for s in items if s["unit_id"] == unit_id]
    if scope is not None:
        items = [s for s in items if s["scope"] == scope]

    if role == "UnitManager":
        subtree = manager_subtree_ids(user_id)
        # Publish gate applies before confidentiality filtering reveals state.
        for s in items:
            if s["unit_id"] in subtree:
                cycle = db.survey_cycles.get(s["cycle_id"])
                if cycle is not None and cycle["status"] not in ("REPORTED", "ARCHIVED"):
                    raise err(ERR_SNAPSHOT_NOT_PUBLISHED,
                              "snapshots are not yet published", 409)
        items = [s for s in items if s["unit_id"] in subtree]

    page, total = paginate(items, limit, offset)
    return success_list([public(s) for s in page], limit, offset, total)


@bp.get("/engagement/report-snapshots/<snap_id>")
def get_snapshot(snap_id):
    user_id, role = require_roles("HRAdmin", "PeopleAnalyst", "UnitManager", "Executive")
    snap = _get_snapshot_or_404(snap_id)
    if role == "UnitManager":
        _manager_gate(snap, user_id)
    return success_object(public(snap))


@bp.post("/engagement/report-snapshots/<snap_id>/recompute")
def recompute_snapshot_endpoint(snap_id):
    require_roles("PeopleAnalyst")
    snap = _get_snapshot_or_404(snap_id)
    recompute_snapshot(snap)
    return success_object(public(snap))


@bp.get("/engagement/report-snapshots/<snap_id>/verbatims")
def list_verbatims(snap_id):
    user_id, role = require_roles("HRAdmin", "PeopleAnalyst", "UnitManager")
    snap = _get_snapshot_or_404(snap_id)
    if role == "UnitManager":
        _manager_gate(snap, user_id)
    limit, offset = parse_pagination(set())

    if snap["verbatim_suppressed"]:
        raise err(ERR_CONFIDENTIALITY,
                  "verbatim comments are suppressed for this snapshot", 403)

    # Collect comments from submitted responses attributed to this scope.
    from services.calculations import scope_unit_ids
    unit_ids = scope_unit_ids(snap)
    comments = []
    for iv in db.survey_invites.values():
        if iv["cycle_id"] != snap["cycle_id"] or iv["status"] != "SUBMITTED":
            continue
        if iv["unit_id_at_invite"] not in unit_ids:
            continue
        resp_id = db.responses_by_invite.get(iv["id"])
        if resp_id is None:
            continue
        resp = db.survey_responses.get(resp_id)
        for ans in resp["answers"]:
            c = ans.get("comment")
            if c:
                comments.append(c)
    page, total = paginate(comments, limit, offset)
    # Output shape: { comments: string[] } within the data envelope.
    body = {
        "comments": page,
    }
    resp = success_object(body)
    return resp


# ---------------------------------------------------------------------------
# Benchmark sets
# ---------------------------------------------------------------------------

@bp.post("/engagement/benchmark-sets")
def create_benchmark_set():
    require_roles("PeopleAnalyst")
    body = get_json_body()
    optional_fields_present(body, {"name", "dimension_scores"})
    require_fields(body, ["name", "dimension_scores"])
    name = as_non_empty_string(body["name"], "name")
    scores = body["dimension_scores"]
    if not isinstance(scores, list):
        raise err(ERR_VALIDATION, "dimension_scores must be an array", 400)
    parsed_scores = []
    for v in scores:
        as_number(v, "dimension_scores[]")
        try:
            d = Decimal(str(v))
        except InvalidOperation:
            raise err(ERR_VALIDATION, "dimension_scores entries must be numbers", 400)
        if d < 0 or d > 100:
            raise err(ERR_VALIDATION, "dimension_scores entries must be 0..100", 400)
        if -d.as_tuple().exponent > 2:
            raise err(ERR_VALIDATION, "dimension_scores entries carry at most 2 decimal places", 400)
        parsed_scores.append(float(d))
    if len(parsed_scores) < 5:
        raise err(ERR_BENCHMARK_TOO_SMALL,
                  "dimension_scores requires at least 5 entries", 422)

    bs = stamp_new({
        "name": name,
        "dimension_scores": parsed_scores,
        "status": "ACTIVE",
    })
    db.benchmark_sets[bs["id"]] = bs
    return success_object(public(bs), 201)


@bp.get("/engagement/benchmark-sets")
def list_benchmark_sets():
    require_roles("HRAdmin", "PeopleAnalyst", "Executive")
    limit, offset = parse_pagination({"status"})
    status = request.args.get("status")
    items = list(db.benchmark_sets.values())
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public(b) for b in page], limit, offset, total)


@bp.post("/engagement/benchmark-sets/<bs_id>/retire")
def retire_benchmark_set(bs_id):
    require_roles("PeopleAnalyst")
    bs = db.benchmark_sets.get(bs_id)
    if bs is None:
        raise err(ERR_NOT_FOUND, "benchmark set not found", 404)
    if bs["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE,
                  f"cannot retire benchmark set in status {bs['status']}", 409)
    bs["status"] = "RETIRED"
    touch(bs)
    return success_object(public(bs))
