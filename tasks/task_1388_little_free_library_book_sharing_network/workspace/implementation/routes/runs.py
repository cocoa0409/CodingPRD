"""Distribution run endpoints (PRD §3.8)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_RUN_NOT_FOUND,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from services.serializers import serialize_allocation, serialize_run
from util import (
    apply_filters,
    paginate,
    parse_pagination,
    sort_by_created_at,
)

bp = Blueprint("runs", __name__)


def _load_run(run_id: str) -> dict:
    run = db.distribution_runs.get(run_id)
    if run is None:
        raise_err(ERR_RUN_NOT_FOUND, "No distribution run with the given id")
    return run


@bp.route("/library-network/distribution-runs", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def list_runs(_user_id, _role):
    limit, offset = parse_pagination()
    items = [serialize_run(r) for r in sort_by_created_at(list(db.distribution_runs.values()))]
    items = apply_filters(items, ["batch_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/library-network/distribution-runs/<run_id>", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def get_run(run_id: str, _user_id, _role):
    return success_object(serialize_run(_load_run(run_id)))


@bp.route("/library-network/distribution-runs/<run_id>/allocations", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def list_run_allocations(run_id: str, _user_id, _role):
    _load_run(run_id)
    limit, offset = parse_pagination()
    items = [
        serialize_allocation(a)
        for a in sort_by_created_at(list(db.allocations.values()))
        if a["run_id"] == run_id
    ]
    items = apply_filters(items, ["status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/library-network/distribution-runs/<run_id>/confirm", methods=["POST"])
@require_roles("HubCoordinator", "NetworkAdmin")
def confirm_run(run_id: str, _user_id, _role):
    run = _load_run(run_id)
    if run["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Run is not in DRAFT status")
    # Confirm-time re-validation of the frozen plan (ERR_PLAN_STALE, 409).
    domain.validate_plan_fresh(run)
    domain.materialize_allocations(run)
    run["status"] = "CONFIRMED"
    db.touch(run)
    return success_object(serialize_run(run))


@bp.route("/library-network/distribution-runs/<run_id>/dispatch", methods=["POST"])
@require_roles("HubCoordinator", "NetworkAdmin")
def dispatch_run(run_id: str, _user_id, _role):
    run = _load_run(run_id)
    if run["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, "Run is not in CONFIRMED status")
    for alloc in list(db.allocations.values()):
        if alloc["run_id"] == run_id and alloc["status"] == "RESERVED":
            alloc["status"] = "DISPATCHED"
            db.touch(alloc)
            item = db.book_items.get(alloc["book_item_id"])
            if item is not None and item["status"] == "ALLOCATED":
                item["status"] = "DISPATCHED"
                db.touch(item)
    run["status"] = "DISPATCHED"
    db.touch(run)
    return success_object(serialize_run(run))
