"""Host registration and reads."""
from flask import Blueprint, request

from db import db, make_versioned
from errors import err, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import require_auth, require_role
from response import success, success_list
from serialize import host_view, ledger_entry_view
from util import require_body, require_str, optional_int, parse_pagination, paginate

bp = Blueprint("hosts", __name__)


@bp.post("/hosts")
def create_host():
    # Anonymous (open registration) — no auth required.
    data = require_body(request.get_json(silent=True))
    email = require_str(data, "email")
    display_name = require_str(data, "display_name")
    payout_account_ref = require_str(data, "payout_account_ref")
    platform_fee_bps = optional_int(data, "platform_fee_bps", 1500)
    if platform_fee_bps < 0 or platform_fee_bps > 5000:
        raise err(ERR_INVALID_REQUEST, "platform_fee_bps must be within 0..5000.")
    # Email unique across hosts.
    for h in db.hosts.values():
        if h["email"] == email:
            raise err(ERR_INVALID_REQUEST, "email must be unique across hosts.")

    rec = make_versioned(
        {
            "email": email,
            "display_name": display_name,
            "payout_account_ref": payout_account_ref,
            "platform_fee_bps": platform_fee_bps,
            "lifetime_payout_cents": 0,
        }
    )
    db.hosts[rec["id"]] = rec
    return success(host_view(rec), status=201)


@bp.get("/hosts/<host_id>")
def get_host(host_id):
    caller = require_auth()
    require_role(caller, "Host", "PlatformAdmin")
    rec = db.hosts.get(host_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Host not found.")
    return success(host_view(rec))


@bp.get("/hosts/<host_id>/ledger")
def list_host_ledger(host_id):
    caller = require_auth()
    require_role(caller, "Host", "PlatformAdmin")
    host = db.hosts.get(host_id)
    if host is None:
        raise err(ERR_NOT_FOUND, "Host not found.")
    # Ownership: a Host may read only their own ledger.
    if caller.role == "Host" and host["id"] != caller.user_id:
        from errors import ERR_NOT_RESOURCE_OWNER
        raise err(ERR_NOT_RESOURCE_OWNER, "Host may read only their own ledger.")
    limit, offset = parse_pagination(request.args)
    entries = [e for e in db.ledger_entries.values() if e["host_id"] == host_id]
    entries.sort(key=lambda e: e["_seq"])
    total = len(entries)
    page = paginate(entries, limit, offset)
    return success_list([ledger_entry_view(e) for e in page], limit, offset, total)
