"""Pool endpoints (PRD §3.1) and the OCC-guarded visit-log (PRD §2.8)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_roles
from response import success, success_list
from services.common import (
    new_record,
    optional_str,
    paginate,
    require_int,
    require_json_object,
    require_str,
    serialize,
    sort_by_created,
    touch,
)
from services.lookup import get_customer_or_404, get_pool_or_404

bp = Blueprint("pools", __name__)

WATER_TYPES = {"CHLORINE", "SALTWATER", "BROMINE_SPA"}


@bp.post("/pools")
@require_roles("AccountManager")
def create_pool():
    with db.lock:
        body = require_json_object(request.get_json(silent=True))
        customer_id = require_str(body, "customer_id")
        label = require_str(body, "label")
        water_type = require_str(body, "water_type")
        if water_type not in WATER_TYPES:
            raise err("ERR_INVALID_REQUEST", "Invalid water_type")
        volume_gallons = require_int(body, "volume_gallons", minimum=100)
        # Existence of referenced customer (PRD §2.6).
        get_customer_or_404(customer_id)
        rec = new_record(
            {
                "customer_id": customer_id,
                "label": label,
                "water_type": water_type,
                "volume_gallons": volume_gallons,
                "service_status": "CLOSED",
                "open_work_order_count": 0,
                "balance_due_cents": 0,
            }
        )
        rec["_visit_logs"] = []
        db.pools[rec["id"]] = rec
        return success(serialize(rec), 201)


@bp.get("/pools/<pool_id>")
@require_roles("AccountManager", "RouteManager", "FieldTechnician", "Customer")
def get_pool(pool_id):
    with db.lock:
        pool = get_pool_or_404(pool_id)
        return success(serialize(pool), 200)


@bp.get("/pools")
@require_roles("AccountManager", "RouteManager")
def list_pools():
    with db.lock:
        limit, offset = paginate(request.args)
        customer_id = request.args.get("customer_id")
        items = list(db.pools.values())
        if customer_id is not None:
            items = [p for p in items if p["customer_id"] == customer_id]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([serialize(p) for p in page], limit, offset, total)


@bp.post("/pools/<pool_id>/visit-logs")
@require_roles("FieldTechnician")
def create_visit_log(pool_id):
    with db.lock:
        pool = get_pool_or_404(pool_id)
        body = require_json_object(request.get_json(silent=True))
        # OCC check (priority 16) comes before generic schema (priority 17), but
        # the field itself must be present/typed to compare. Required field.
        expected = require_int(body, "expected_pool_version")
        note = optional_str(body, "note")
        if expected != pool["version"]:
            raise err("ERR_STALE_VERSION", "expected_pool_version does not match current pool version")
        pool["_visit_logs"].append({"note": note})
        touch(pool)
        return success(serialize(pool), 201)
