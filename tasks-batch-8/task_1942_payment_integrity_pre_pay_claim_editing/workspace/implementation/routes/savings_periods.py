"""SavingsPeriod endpoints per PRD 3.9."""

from flask import Blueprint, request

import db
from errors import raise_err
from middleware import (
    get_body,
    pagination_params,
    require_auth,
    require_role,
    validate_body,
)
from response import success_list, success_object
from serializers import serialize
from services import core

bp = Blueprint("savings_periods", __name__)
PREFIX = "/payment-integrity"

PERIOD_STATUSES = {"OPEN", "RECONCILING", "FINALIZED"}
RESOLVED_FOR_FINALIZED = {"CONFIRMED", "OVERRIDDEN", "RELEASED_FALSE_POSITIVE", "SUPERSEDED"}
RELEASED_STATUSES = {"OVERRIDDEN", "RELEASED_FALSE_POSITIVE", "SUPERSEDED"}


def _in_period(dt, period_key: str) -> bool:
    """True iff dt falls in the YYYY-MM calendar month of period_key."""
    if dt is None:
        return False
    return dt.strftime("%Y-%m") == period_key


@bp.route(PREFIX + "/savings-periods", methods=["POST"])
def create_period():
    user_id, role = require_auth()
    require_role(role, ["PlanAdmin"])
    body = get_body()
    vals = validate_body(body, {"period_key": (True, "string", None)})
    key = vals["period_key"]
    # Format check YYYY-MM
    parts = key.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2 or not key.replace("-", "").isdigit():
        raise_err("ERR_INVALID_REQUEST", "period_key must be in YYYY-MM format")
    month = int(parts[1])
    if month < 1 or month > 12:
        raise_err("ERR_INVALID_REQUEST", "period_key must be in YYYY-MM format")
    for p in db.all_records("savings_periods"):
        if p["period_key"] == key:
            raise_err("ERR_DUPLICATE_PERIOD_KEY", "period_key must be unique")
    period = db.create_resource(
        "savings_periods",
        {
            "period_key": key,
            "status": "OPEN",
            "provisional_savings_cents": 0,
            "finalized_savings_cents": 0,
            "pending_pipeline_cents": 0,
            "reversed_cents": 0,
            "finalized_at": None,
        },
    )
    return success_object(serialize(period), status=201)


@bp.route(PREFIX + "/savings-periods", methods=["GET"])
def list_periods():
    require_auth()
    limit, offset = pagination_params()
    status = request.args.get("status")
    rows = db.all_records("savings_periods")
    if status is not None:
        if status not in PERIOD_STATUSES:
            raise_err("ERR_INVALID_ENUM", "status filter carries undeclared member")
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return success_list([serialize(r) for r in rows[offset : offset + limit]], limit, offset, total)


def _get_period_or_404(pid):
    period = db.get("savings_periods", pid)
    if period is None:
        raise_err("ERR_SAVINGS_PERIOD_NOT_FOUND", "Savings period not found")
    return period


@bp.route(PREFIX + "/savings-periods/<pid>", methods=["GET"])
def get_period(pid):
    require_auth()
    return success_object(serialize(_get_period_or_404(pid)))


@bp.route(PREFIX + "/savings-periods/<pid>/begin-reconciliation", methods=["POST"])
def begin_reconciliation(pid):
    user_id, role = require_auth()
    require_role(role, ["PlanAdmin"])
    body = get_body()
    validate_body(body, {})
    period = _get_period_or_404(pid)
    if period["status"] != "OPEN":
        raise_err("ERR_PERIOD_NOT_FINALIZABLE", "begin-reconciliation requires OPEN")
    period["status"] = "RECONCILING"
    db.touch(period)
    return success_object(serialize(period))


@bp.route(PREFIX + "/savings-periods/<pid>/finalize", methods=["POST"])
def finalize_period(pid):
    user_id, role = require_auth()
    require_role(role, ["PlanAdmin"])
    body = get_body()
    validate_body(body, {})
    period = _get_period_or_404(pid)
    if period["status"] != "RECONCILING":
        raise_err("ERR_PERIOD_NOT_FINALIZABLE", "finalize requires RECONCILING")
    key = period["period_key"]
    provisional = 0
    finalized = 0
    pending = 0
    reversed_cents = 0
    for hit in db.all_records("edit_hits"):
        if _in_period(hit["created_at"], key):
            provisional += hit.get("attributed_savings_cents", 0)
            if hit["status"] == "FIRED":
                pending += hit.get("attributed_savings_cents", 0)
        if hit["status"] in RESOLVED_FOR_FINALIZED and _in_period(hit.get("resolved_at"), key):
            finalized += hit.get("attributed_savings_cents", 0) - hit.get("released_cents", 0)
        if hit["status"] in RELEASED_STATUSES and _in_period(hit.get("resolved_at"), key):
            reversed_cents += hit.get("released_cents", 0)
    period["provisional_savings_cents"] = provisional
    period["finalized_savings_cents"] = finalized
    period["pending_pipeline_cents"] = pending
    period["reversed_cents"] = reversed_cents
    period["status"] = "FINALIZED"
    period["finalized_at"] = db.now()
    db.touch(period)
    # Ops-run checkpoint: re-evaluate auto-suspension for every ACTIVE version
    for version in db.all_records("edit_versions"):
        if version["status"] == "ACTIVE":
            core.recompute_version_stats(version)
            core.maybe_auto_suspend(version)
    return success_object(serialize(period))
