"""Harvest opportunity action endpoints."""
from __future__ import annotations

from flask import Blueprint

from db import store
from errors import err_resource_not_found
from middleware import require_auth
from response import success
from routes.accounts import enforce_account_active, get_account_or_404
from services.engine import (
    approve_harvest,
    dismiss_harvest,
    execute_harvest,
)
from services.serializers import serialize_harvest_opportunity

bp = Blueprint("harvest", __name__)


def _get_opp_under_account_or_404(account_id, opp_id):
    h = store.harvest_opportunities.get(opp_id)
    if not h or h["account_id"] != account_id:
        raise err_resource_not_found("HarvestOpportunity not found under this account.")
    return h


@bp.post("/accounts/<account_id>/harvest-opportunities/<opp_id>/approve")
@require_auth(["Advisor"])
def approve(account_id, opp_id):
    a = get_account_or_404(account_id)
    enforce_account_active(a)
    h = _get_opp_under_account_or_404(account_id, opp_id)
    with store.lock:
        approve_harvest(a, h)
    return success(serialize_harvest_opportunity(h))


@bp.post("/accounts/<account_id>/harvest-opportunities/<opp_id>/dismiss")
@require_auth(["Advisor"])
def dismiss(account_id, opp_id):
    a = get_account_or_404(account_id)
    enforce_account_active(a)
    h = _get_opp_under_account_or_404(account_id, opp_id)
    with store.lock:
        dismiss_harvest(a, h)
    return success(serialize_harvest_opportunity(h))


@bp.post("/accounts/<account_id>/harvest-opportunities/<opp_id>/execute")
@require_auth(["Advisor"])
def execute(account_id, opp_id):
    a = get_account_or_404(account_id)
    enforce_account_active(a)
    h = _get_opp_under_account_or_404(account_id, opp_id)
    with store.lock:
        execute_harvest(a, h)
    return success(serialize_harvest_opportunity(h))
