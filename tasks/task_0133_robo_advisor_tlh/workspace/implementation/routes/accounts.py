"""Account endpoints + cash deposit + freeze/unfreeze + positions + drift."""
from __future__ import annotations

from flask import Blueprint, g, request

from config import MIN_HARVEST_THRESHOLD_CENTS
from db import store
from errors import (
    err_account_frozen,
    err_auth_forbidden,
    err_fk_not_found,
    err_harvest_threshold_not_met,
    err_invalid_state,
    err_resource_not_found,
)
from middleware import require_auth
from response import list_success, success
from routes._helpers import get_json, paginate, parse_pagination, sort_by_created_at
from services.calculations import recompute_account_drift
from services.engine import (
    credit_cash,
    detect_harvest_opportunity,
    recompute_position,
    stamp_create,
    stamp_update,
)
from services.serializers import (
    serialize_account,
    serialize_harvest_opportunity,
    serialize_position,
)

bp = Blueprint("accounts", __name__)


def get_account_or_404(account_id: str) -> dict:
    a = store.accounts.get(account_id)
    if a is None:
        raise err_resource_not_found("Account not found.")
    return a


def enforce_account_visible_to_caller(account: dict) -> None:
    if g.role == "ClientUser" and account["client_id"] != g.user_id:
        raise err_auth_forbidden("ClientUser may only access their own accounts.")


def enforce_account_active(account: dict) -> None:
    if account["compliance_status"] != "ACTIVE":
        raise err_account_frozen()


@bp.post("/accounts")
@require_auth(["ComplianceOfficer"])
def create_account():
    body = get_json()
    client_id = body.get("client_id")
    if not isinstance(client_id, str) or client_id not in store.clients:
        raise err_fk_not_found("client_id does not reference an existing Client.")
    with store.lock:
        a = {
            "client_id": client_id,
            "model_portfolio_id": None,
            "cash_balance_cents": 0,
            "compliance_status": "ACTIVE",
            "investment_status": "ACCUMULATING",
            "max_drift_pct": 0.00,
        }
        stamp_create(a)
        store.accounts[a["id"]] = a
    return success(serialize_account(a), 201)


@bp.get("/accounts/<account_id>")
@require_auth(["ComplianceOfficer", "Advisor", "ClientUser"])
def get_account(account_id):
    a = get_account_or_404(account_id)
    enforce_account_visible_to_caller(a)
    return success(serialize_account(a))


@bp.post("/accounts/<account_id>/freeze")
@require_auth(["ComplianceOfficer"])
def freeze_account(account_id):
    a = get_account_or_404(account_id)
    with store.lock:
        a["compliance_status"] = "FROZEN_DOC_REVIEW"
        stamp_update(a)
    return success(serialize_account(a))


@bp.post("/accounts/<account_id>/unfreeze")
@require_auth(["ComplianceOfficer"])
def unfreeze_account(account_id):
    a = get_account_or_404(account_id)
    with store.lock:
        a["compliance_status"] = "ACTIVE"
        stamp_update(a)
    return success(serialize_account(a))


@bp.post("/accounts/<account_id>/cash-deposit")
@require_auth(["Advisor", "ComplianceOfficer"])
def cash_deposit(account_id):
    a = get_account_or_404(account_id)
    enforce_account_active(a)
    body = get_json()
    amount = body.get("amount_cents")
    if amount is None or isinstance(amount, bool) or not isinstance(amount, int):
        raise err_invalid_state("amount_cents must be an integer.")
    if amount <= 0:
        raise err_invalid_state("amount_cents must be > 0.")
    with store.lock:
        credit_cash(a, amount)
    return success(serialize_account(a))


# ── Positions ──────────────────────────────────────────────────────────────


@bp.get("/accounts/<account_id>/positions")
@require_auth(["Advisor", "ComplianceOfficer", "ClientUser"])
def list_positions(account_id):
    a = get_account_or_404(account_id)
    enforce_account_visible_to_caller(a)
    limit, offset = parse_pagination()
    items = [p for p in store.positions.values() if p["account_id"] == account_id]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success(
        [serialize_position(p) for p in page], limit, offset, total
    )


@bp.post("/accounts/<account_id>/positions/recompute")
@require_auth(["Advisor", "system"])
def recompute_positions(account_id):
    a = get_account_or_404(account_id)
    enforce_account_active(a)
    body = get_json()
    intent = body.get("intent") or request.args.get("intent") or "refresh"
    if intent not in ("refresh", "detect"):
        raise err_invalid_state("intent must be 'refresh' or 'detect'.")
    with store.lock:
        positions = [p for p in store.positions.values() if p["account_id"] == account_id]
        for p in positions:
            recompute_position(p)
        if intent == "detect":
            # PRD §3.7: "a recompute call with intent=detect that finds
            # no position past the threshold returns
            # ERR_HARVEST_THRESHOLD_NOT_MET." The error is conditioned
            # on the threshold check, not on whether a new opp row was
            # created (a position that already has an outstanding
            # BLOCKED/DETECTED opp is still 'past the threshold').
            any_past_threshold = False
            for p in positions:
                unrealized = (p.get("market_value_cents") or 0) - (p.get("total_cost_basis_cents") or 0)
                if unrealized <= -MIN_HARVEST_THRESHOLD_CENTS:
                    any_past_threshold = True
                detect_harvest_opportunity(a, p)
            if not any_past_threshold:
                raise err_harvest_threshold_not_met()
        positions = [p for p in store.positions.values() if p["account_id"] == account_id]
    limit, offset = parse_pagination()
    positions = sort_by_created_at(positions)
    total = len(positions)
    page = paginate(positions, limit, offset)
    return list_success(
        [serialize_position(p) for p in page], limit, offset, total
    )


@bp.post("/accounts/<account_id>/drift/recompute")
@require_auth(["Advisor", "system"])
def drift_recompute(account_id):
    a = get_account_or_404(account_id)
    enforce_account_active(a)
    with store.lock:
        recompute_account_drift(store, a)
        stamp_update(a)
    return success(serialize_account(a))


# ── Harvest opportunities (list only here; actions in harvest.py) ──────────


@bp.get("/accounts/<account_id>/harvest-opportunities")
@require_auth(["Advisor", "ComplianceOfficer"])
def list_harvest_opportunities(account_id):
    get_account_or_404(account_id)
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = [h for h in store.harvest_opportunities.values() if h["account_id"] == account_id]
    if status_filter:
        items = [h for h in items if h["status"] == status_filter]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success(
        [serialize_harvest_opportunity(h) for h in page], limit, offset, total
    )
