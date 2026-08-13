"""Payer endpoints (PRD §3.1)."""

from flask import Blueprint, request

import db as _db
from errors import err_not_found, err_invalid_state, err_invalid_request
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.serializers import serialize_payer
from services.validation import body, reject_unknown, as_str, as_int, as_enum
from services.pricing import touch

bp = Blueprint("payers", __name__)

PAYER_TYPES = {"COMMERCIAL", "MEDICARE_ADVANTAGE", "MEDICAID_MCO", "WORKERS_COMP"}


@bp.post("/api/payers")
def create_payer():
    require_roles(["ContractManager"])
    data = body()
    reject_unknown(data, {"name", "payer_type", "appeal_deadline_days"})
    name = as_str(data, "name")
    payer_type = as_enum(data, "payer_type", PAYER_TYPES)
    deadline = as_int(data, "appeal_deadline_days", required=False, min_value=1)
    if deadline is None:
        deadline = 45
    now = _db.now_iso()
    payer = {
        "id": _db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": _db.store.next_seq(),
        "name": name,
        "payer_type": payer_type,
        "appeal_deadline_days": deadline,
        "status": "ACTIVE",
    }
    _db.store.payers[payer["id"]] = payer
    return success_object(serialize_payer(payer), status=201)


@bp.get("/api/payers/<pid>")
def get_payer(pid):
    require_roles(ALL_ROLES)
    payer = _db.store.payers.get(pid)
    if payer is None:
        raise err_not_found("Payer not found")
    return success_object(serialize_payer(payer))


@bp.get("/api/payers")
def list_payers():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    if status is not None and status not in {"ACTIVE", "INACTIVE"}:
        raise err_invalid_request("status filter invalid")
    items = [p for p in _db.store.payers.values() if status is None or p["status"] == status]
    items.sort(key=lambda p: p["seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_payer(p) for p in page], limit, offset, total)


@bp.post("/api/payers/<pid>/deactivate")
def deactivate_payer(pid):
    require_roles(["ContractManager"])
    payer = _db.store.payers.get(pid)
    if payer is None:
        raise err_not_found("Payer not found")
    if payer["status"] != "ACTIVE":
        raise err_invalid_state("Payer is not ACTIVE")
    payer["status"] = "INACTIVE"
    touch(payer)
    return success_object(serialize_payer(payer))
