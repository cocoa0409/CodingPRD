"""Drivers endpoints."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_auth, get_pagination, get_json_body
from response import success, success_list
from services.util import parse_dt


bp = Blueprint("drivers", __name__)


def _serialize(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def _employee_code_unique_active(code: str, exclude_id=None) -> bool:
    for d in db.drivers.values():
        if exclude_id and d["id"] == exclude_id:
            continue
        if d.get("status") == "ACTIVE" and d.get("employee_code") == code:
            return False
    return True


@bp.route("/shuttle/drivers", methods=["POST"])
@require_auth(roles={"Dispatcher"})
def create_driver():
    body = get_json_body()
    ec = body.get("employee_code")
    fn = body.get("full_name")
    led = body.get("license_expiry_date")

    if not isinstance(ec, str) or not ec.strip():
        raise err("ERR_VALIDATION", "employee_code is required")
    if not isinstance(fn, str) or not fn.strip():
        raise err("ERR_VALIDATION", "full_name is required")
    if not isinstance(led, str) or not led.strip():
        raise err("ERR_VALIDATION", "license_expiry_date is required")
    # Parse to validate ISO; keep stored string as supplied (normalized to iso below)
    parsed = parse_dt(led, "license_expiry_date")

    if not _employee_code_unique_active(ec):
        raise err("ERR_INVALID_STATE",
                  "employee_code already used by an active driver")

    from clock import iso
    d = {
        "employee_code": ec,
        "full_name": fn,
        "license_expiry_date": iso(parsed),
        "status": "ACTIVE",
    }
    db.stamp_create(d)
    db.drivers[d["id"]] = d
    return success(_serialize(d), status=201)


@bp.route("/shuttle/drivers", methods=["GET"])
@require_auth(roles={"Dispatcher", "Auditor"})
def list_drivers():
    limit, offset = get_pagination()
    status_filter = request.args.get("status")
    items = list(db.drivers.values())
    if status_filter:
        items = [d for d in items if d.get("status") == status_filter]
    items.sort(key=lambda d: d.get("_seq", 0))
    page = items[offset:offset + limit]
    return success_list([_serialize(d) for d in page], limit, offset, len(items))
