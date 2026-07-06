"""Client endpoints (PRD 3.1)."""
from flask import Blueprint, request

import db
from common import (get_json_body, get_or_404, new_record, paginate,
                    parse_pagination, require_enum, require_int, require_number,
                    require_str, optional_enum, touch)
from middleware import authorize
from response import success
from errors import err
from services.serialize import client_out

bp = Blueprint("clients", __name__)

INDUSTRIES = {"TECH", "HEALTH", "FINANCE", "CONSUMER", "NONPROFIT"}
ACCOUNT_TIERS = {"STANDARD", "PREMIUM", "ENTERPRISE"}
CLIENT_STATUSES = {"ACTIVE", "SUSPENDED"}


@bp.post("/agency/clients")
@authorize(["AccountManager", "PlatformAdmin"])
def create_client():
    body = get_json_body()
    name = require_str(body, "name")
    industry = require_enum(body, "industry", INDUSTRIES)
    monthly_retainer_cents = require_int(body, "monthly_retainer_cents", minimum=0)
    monthly_hours_cap = require_number(body, "monthly_hours_cap", exclusive_min=0)
    overage_rate_cents = require_int(body, "overage_rate_cents", minimum=0)
    account_tier = optional_enum(body, "account_tier", ACCOUNT_TIERS, "STANDARD")

    rec = new_record({
        "name": name,
        "industry": industry,
        "monthly_retainer_cents": monthly_retainer_cents,
        "monthly_hours_cap": monthly_hours_cap,
        "overage_rate_cents": overage_rate_cents,
        "account_tier": account_tier,
        "status": "ACTIVE",
        "lifetime_earned_media_cents": 0,
    })
    db.clients[rec["id"]] = rec
    return success(client_out(rec), status=201)


@bp.get("/agency/clients/<client_id>")
@authorize(["AccountManager", "MediaSpecialist", "SchedulingCoordinator", "PlatformAdmin"])
def get_client(client_id):
    rec = get_or_404(db.clients, client_id)
    return success(client_out(rec))


@bp.get("/agency/clients")
@authorize(["AccountManager", "MediaSpecialist", "SchedulingCoordinator", "PlatformAdmin"])
def list_clients():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    if status is not None and status not in CLIENT_STATUSES:
        raise err("ERR_INVALID_REQUEST", "status filter invalid")
    records = [r for r in db.clients.values()
               if status is None or r["status"] == status]
    page, meta = paginate(records, limit, offset)
    return success([client_out(r) for r in page], pagination=meta)


@bp.post("/agency/clients/<client_id>/suspend")
@authorize(["PlatformAdmin"])
def suspend_client(client_id):
    rec = get_or_404(db.clients, client_id)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Client is not ACTIVE")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success(client_out(rec))
