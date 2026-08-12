"""Spend-down plans endpoints."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CLIENT_NOT_ACTIVE,
    ERR_CLIENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SPEND_DOWN_NOT_FOUND,
    ERR_SPEND_DOWN_NOT_REQUIRED,
    err,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import serialize_spend_down
from services.calcs import compute_provisional_excess, compute_final_excess
from services.cascade import clock_now_iso, clock_date, clock_month_str
from util import (
    new_id,
    parse_month,
    parse_pagination,
    require_body,
    get_string,
    reject_unexpected,
)

bp = Blueprint("spend_down", __name__)

READ_ROLES = ("FiduciaryAdmin", "CaseManager", "FinancialOfficer", "ConservatorOfficer", "ComplianceAuditor")
SPEND_CATEGORIES = ("HOUSING", "FOOD", "CLOTHING", "PERSONAL", "MEDICAL", "EDUCATION")


@bp.route("/spend-down-plans", methods=["POST"])
def create_plan():
    require_roles("CaseManager")
    body = require_body()
    reject_unexpected(body, {"client_id", "target_month", "entries"})
    client_id = get_string(body, "client_id")
    target_month = parse_month(get_string(body, "target_month"), "target_month")
    entries = body.get("entries")
    if not isinstance(entries, list):
        raise err(ERR_INVALID_REQUEST, 400, "entries must be an array")
    seen = set()
    for e in entries:
        if not isinstance(e, dict) or set(e.keys()) != {"category", "planned_amount_cents"}:
            raise err(ERR_INVALID_REQUEST, 400, "each entry needs category and planned_amount_cents")
        if e["category"] not in SPEND_CATEGORIES:
            raise err(ERR_INVALID_REQUEST, 400, "invalid category")
        amt = e["planned_amount_cents"]
        if isinstance(amt, bool) or not isinstance(amt, int) or amt <= 0:
            raise err(ERR_INVALID_REQUEST, 400, "planned_amount_cents must be a positive integer")
        if e["category"] in seen:
            raise err(ERR_INVALID_REQUEST, 400, "duplicate category")
        seen.add(e["category"])

    c = store.clients.get(client_id)
    if not c:
        raise err(ERR_CLIENT_NOT_FOUND, 404, "client not found")
    if c["status"] == "TERMINATED":
        raise err(ERR_CLIENT_NOT_ACTIVE, 409, "Client is TERMINATED")
    if not c["medicaid_enrolled"]:
        raise err(ERR_INVALID_REQUEST, 400, "client is not medicaid_enrolled")

    provisional = compute_provisional_excess(c, target_month)

    now = clock_now_iso()
    sid = new_id()
    sp = {
        "id": sid,
        "client_id": client_id,
        "target_month": target_month,
        "entries": [{"category": e["category"], "planned_amount_cents": e["planned_amount_cents"]} for e in entries],
        "provisional_excess_cents": provisional,
        "final_excess_cents": None,
        "auto_created": False,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.spend_down_plans[sid] = sp
    return success_object(serialize_spend_down(sp), status=201)


@bp.route("/spend-down-plans", methods=["GET"])
def list_plans():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()
    client_id = request.args.get("client_id")
    target_month = request.args.get("target_month")
    status = request.args.get("status")
    items = list(store.spend_down_plans.values())
    if client_id is not None:
        items = [s for s in items if s["client_id"] == client_id]
    if target_month is not None:
        items = [s for s in items if s["target_month"] == target_month]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_spend_down(s) for s in page], limit, offset, total)


def _get_or_404(sid):
    s = store.spend_down_plans.get(sid)
    if not s:
        raise err(ERR_SPEND_DOWN_NOT_FOUND, 404, "spend-down plan not found")
    return s


@bp.route("/spend-down-plans/<sid>", methods=["GET"])
def get_plan(sid):
    require_roles(*READ_ROLES)
    s = _get_or_404(sid)
    return success_object(serialize_spend_down(s))


@bp.route("/spend-down-plans/<sid>/activate", methods=["POST"])
def activate_plan(sid):
    require_roles("CaseManager")
    s = _get_or_404(sid)
    if s["status"] in ("MET", "LAPSED"):
        raise err(ERR_ALREADY_TERMINAL, 409, "Plan is terminal")
    if s["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, 409, "Only DRAFT -> ACTIVE")
    c = store.clients[s["client_id"]]
    if not c["medicaid_enrolled"]:
        raise err(ERR_INVALID_REQUEST, 400, "client is not medicaid_enrolled")
    if s.get("provisional_excess_cents", 0) <= 0:
        raise err(ERR_SPEND_DOWN_NOT_REQUIRED, 422, "provisional_excess_cents must be > 0")
    now = clock_now_iso()
    s["status"] = "ACTIVE"
    s["updated_at"] = now
    s["version"] += 1
    return success_object(serialize_spend_down(s))


@bp.route("/spend-down-plans/<sid>/finalize", methods=["POST"])
def finalize_plan(sid):
    require_roles("CaseManager")
    s = _get_or_404(sid)
    if s["status"] in ("MET", "LAPSED"):
        raise err(ERR_ALREADY_TERMINAL, 409, "Plan is terminal")
    if s["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, 409, "Only ACTIVE -> MET/LAPSED")
    # clock date must be within target_month or later
    cm = clock_month_str()
    if cm < s["target_month"]:
        raise err(ERR_INVALID_STATE, 409, "clock date must be within target_month or later")
    c = store.clients[s["client_id"]]
    final = compute_final_excess(c)
    s["final_excess_cents"] = final
    now = clock_now_iso()
    s["status"] = "MET" if final == 0 else "LAPSED"
    s["updated_at"] = now
    s["version"] += 1
    return success_object(serialize_spend_down(s))
