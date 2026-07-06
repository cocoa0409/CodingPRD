"""Retainer endpoints (PRD §3.10)."""
from flask import Blueprint, request

from db import db
from middleware import authenticate
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_OPEN_CYCLE,
)
from helpers import (
    require_role, get_json_body, require_fields, as_int, require_nonneg_int,
    parse_pagination, paginate, get_studio, require_client_owns_client,
)
from response import success, success_list
from serialize import view

bp = Blueprint("retainers", __name__)


def _resolve_retainer(studio_id, retainer_id):
    studio = get_studio(studio_id)
    rt = db.retainers.get(retainer_id)
    if rt is None:
        raise err(ERR_NOT_FOUND, "Retainer not found")
    # Retainer is scoped to a client which is scoped to the studio.
    client = db.clients.get(rt["client_id"])
    if client is None or client["studio_id"] != studio_id:
        raise err(ERR_NOT_FOUND, "Retainer not found in this studio")
    return rt


def _has_open_cycle(retainer_id):
    return any(
        c["retainer_id"] == retainer_id and c["status"] == "OPEN"
        for c in db.care_cycles.values()
    )


@bp.route("/studios/<studio_id>/retainers", methods=["POST"])
def create_retainer(studio_id):
    caller = authenticate()
    require_role(caller, "StudioOps")
    get_studio(studio_id)
    body = get_json_body()
    require_fields(body, "client_id", "monthly_fee_cents",
                   "tier1_rate_cents", "tier2_rate_cents")
    client_id = body["client_id"]
    monthly_fee = require_nonneg_int(body["monthly_fee_cents"], "monthly_fee_cents")
    tier1 = as_int(body["tier1_rate_cents"], "tier1_rate_cents")
    tier2 = as_int(body["tier2_rate_cents"], "tier2_rate_cents")
    included = 10
    if "included_hours" in body and body["included_hours"] is not None:
        included = as_int(body["included_hours"], "included_hours")

    # Body-referenced client existence (§2.9).
    client = db.clients.get(client_id)
    if client is None or client["studio_id"] != studio_id:
        raise err(ERR_NOT_FOUND, "Client not found in this studio")

    rec = db.create(db.retainers, {
        "client_id": client_id,
        "monthly_fee_cents": monthly_fee,
        "included_hours": included,
        "tier1_rate_cents": tier1,
        "tier2_rate_cents": tier2,
        "status": "ACTIVE",
    })
    return success(view(rec), status=201)


@bp.route("/studios/<studio_id>/retainers/<retainer_id>", methods=["GET"])
def get_retainer(studio_id, retainer_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "BillingOps", "Client")
    rt = _resolve_retainer(studio_id, retainer_id)
    if caller.role == "Client":
        client = db.clients.get(rt["client_id"])
        require_client_owns_client(caller, client)
    return success(view(rt), status=200)


@bp.route("/studios/<studio_id>/retainers", methods=["GET"])
def list_retainers(studio_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "BillingOps", "Client")
    get_studio(studio_id)
    limit, offset = parse_pagination()

    studio_client_ids = {
        c["id"] for c in db.clients.values() if c["studio_id"] == studio_id
    }
    records = [rt for rt in db.retainers.values()
               if rt["client_id"] in studio_client_ids]
    filter_client = request.args.get("client_id")
    if filter_client is not None:
        records = [rt for rt in records if rt["client_id"] == filter_client]
    if caller.role == "Client":
        records = [rt for rt in records if rt["client_id"] == caller.user_id]

    window, total = paginate(records, limit, offset)
    return success_list([view(r) for r in window], limit, offset, total)


@bp.route("/studios/<studio_id>/retainers/<retainer_id>/pause", methods=["POST"])
def pause_retainer(studio_id, retainer_id):
    caller = authenticate()
    require_role(caller, "StudioOps")
    rt = _resolve_retainer(studio_id, retainer_id)
    # ACTIVE -> PAUSED.
    if rt["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Retainer is not ACTIVE")
    if _has_open_cycle(retainer_id):
        raise err(ERR_OPEN_CYCLE, "Retainer has an open care cycle")
    rt["status"] = "PAUSED"
    db.touch(rt)
    return success(view(rt), status=200)


@bp.route("/studios/<studio_id>/retainers/<retainer_id>/resume", methods=["POST"])
def resume_retainer(studio_id, retainer_id):
    caller = authenticate()
    require_role(caller, "StudioOps")
    rt = _resolve_retainer(studio_id, retainer_id)
    # PAUSED -> ACTIVE; no precondition.
    if rt["status"] != "PAUSED":
        raise err(ERR_INVALID_STATE, "Retainer is not PAUSED")
    rt["status"] = "ACTIVE"
    db.touch(rt)
    return success(view(rt), status=200)


@bp.route("/studios/<studio_id>/retainers/<retainer_id>/cancel", methods=["POST"])
def cancel_retainer(studio_id, retainer_id):
    caller = authenticate()
    require_role(caller, "StudioOps")
    rt = _resolve_retainer(studio_id, retainer_id)
    # ACTIVE/PAUSED -> CANCELLED.
    if rt["status"] not in ("ACTIVE", "PAUSED"):
        raise err(ERR_INVALID_STATE, "Retainer cannot be cancelled from current state")
    if _has_open_cycle(retainer_id):
        raise err(ERR_OPEN_CYCLE, "Retainer has an open care cycle")
    rt["status"] = "CANCELLED"
    db.touch(rt)
    return success(view(rt), status=200)
