"""Rebalance run endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import store
from errors import err_invalid_state
from middleware import require_auth
from response import list_success, success
from routes._helpers import get_json, paginate, parse_pagination, sort_by_created_at
from routes.accounts import enforce_account_active, get_account_or_404
from services.engine import start_rebalance_run
from services.serializers import serialize_rebalance_run
from utils import parse_iso

bp = Blueprint("rebalance", __name__)


@bp.post("/accounts/<account_id>/rebalance/start")
@require_auth(["Advisor"])
def start(account_id):
    a = get_account_or_404(account_id)
    enforce_account_active(a)
    body = get_json()
    quarter_key = body.get("quarter_key")
    if not isinstance(quarter_key, str) or "Q" not in quarter_key:
        raise err_invalid_state("quarter_key must be 'YYYY-Qn'.")
    force = bool(body.get("force", False))
    with store.lock:
        run = start_rebalance_run(a, quarter_key, force)
    return success(serialize_rebalance_run(run), 201)


@bp.get("/accounts/<account_id>/rebalance-runs")
@require_auth(["Advisor", "ComplianceOfficer"])
def list_runs(account_id):
    get_account_or_404(account_id)
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    year_filter = request.args.get("year")
    items = [r for r in store.rebalance_runs.values() if r["account_id"] == account_id]
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    if year_filter:
        try:
            y = int(year_filter)
            items = [
                r for r in items
                if r.get("started_at") and parse_iso(r["started_at"]).year == y
            ]
        except (TypeError, ValueError):
            items = []
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success(
        [serialize_rebalance_run(r) for r in page], limit, offset, total
    )
