"""Distributor service."""

from common import (
    get_json_body,
    paginate,
    parse_pagination,
    require_field,
    sort_by_created_at,
    stamp_create,
)
from db import db
from errors import ERR_NOT_FOUND, ERR_VALIDATION, raise_error


def _serialize(d: dict) -> dict:
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "name": d["name"],
        "contact_email": d["contact_email"],
        "tier": d["tier"],
        "notification_endpoint": d["notification_endpoint"],
    }


def get_distributor_or_404(did):
    d = db.distributors.get(did)
    if d is None:
        raise_error(ERR_NOT_FOUND, f"distributor {did} not found")
    return d


def create_distributor():
    body = get_json_body()
    name = require_field(body, "name", str)
    contact_email = require_field(body, "contact_email", str)
    tier = require_field(body, "tier", str)
    notification_endpoint = require_field(body, "notification_endpoint", str)
    if tier not in {"WHOLESALE", "RETAIL"}:
        raise_error(ERR_VALIDATION, "tier must be WHOLESALE or RETAIL")
    with db.lock:
        d = {
            "id": db.new_id(),
            "name": name,
            "contact_email": contact_email,
            "tier": tier,
            "notification_endpoint": notification_endpoint,
        }
        stamp_create(d)
        db.distributors[d["id"]] = d
    return _serialize(d)


def list_distributors(args):
    limit, offset = parse_pagination()
    items = list(db.distributors.values())
    tier = args.get("tier")
    if tier is not None:
        items = [d for d in items if d["tier"] == tier]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return [_serialize(d) for d in page], limit, offset, total
