from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_roles
from response import success, list_response
from services.common import (parse_pagination, serialize_client, sort_by_created_at,
                              stamp_create, touch)
from services.validation import (PAYMENT_CYCLES, require_int, require_string,
                                  validate_email)

bp = Blueprint("clients", __name__)


@bp.post("/clients")
@require_roles("ProjectManager")
def create_client():
    body = request.get_json(silent=True) or {}
    name = require_string(body, "name", min_len=1, max_len=200)
    contact_email = validate_email(require_string(body, "contact_email", min_len=3))
    tax_rate_bps = require_int(body, "tax_rate_bps", min_val=0, max_val=3000)
    payment_cycle_days = require_int(body, "payment_cycle_days")
    if payment_cycle_days not in PAYMENT_CYCLES:
        raise err("ERR_VALIDATION_FAILED", "payment_cycle_days must be one of {0,7,15,30,45}.")
    c = {
        "name": name,
        "contact_email": contact_email,
        "tax_rate_bps": tax_rate_bps,
        "payment_cycle_days": payment_cycle_days,
        "status": "ACTIVE",
    }
    stamp_create(c)
    store.clients[c["id"]] = c
    return success(serialize_client(c), status=201)


@bp.get("/clients/<id>")
@require_roles("ProjectManager")
def get_client(id):
    c = store.clients.get(id)
    if not c:
        raise err("ERR_NOT_FOUND", "client not found")
    return success(serialize_client(c))


@bp.get("/clients")
@require_roles("ProjectManager")
def list_clients():
    limit, offset = parse_pagination(request.args)
    status_filter = request.args.get("status")
    items = list(store.clients.values())
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]
    items = sort_by_created_at(items)
    total = len(items)
    sliced = items[offset:offset + limit]
    return list_response([serialize_client(c) for c in sliced], total, limit, offset)
