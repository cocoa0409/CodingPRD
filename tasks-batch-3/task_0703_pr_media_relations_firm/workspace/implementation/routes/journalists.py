"""Journalist endpoints (PRD 3.2)."""
from flask import Blueprint, request

import db
from common import (get_json_body, get_or_404, new_record, paginate,
                    parse_pagination, ref_or_404, require_enum, require_str, touch)
from errors import err
from middleware import authorize
from response import success
from services.serialize import journalist_out

bp = Blueprint("journalists", __name__)

BEATS = {"TECH", "HEALTH", "FINANCE", "CONSUMER", "POLITICS"}
JOURNALIST_STATUSES = {"ACTIVE", "BLOCKLISTED"}


@bp.post("/agency/journalists")
@authorize(["MediaSpecialist", "PlatformAdmin"])
def create_journalist():
    body = get_json_body()
    outlet_id = body.get("outlet_id")
    # FK existence (priority 4) before field shape on the other fields.
    ref_or_404(db.outlets, outlet_id, "outlet_id")
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    beat = require_enum(body, "beat", BEATS)

    # email must be unique across all journalists (business well-formedness).
    for j in db.journalists.values():
        if j["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email must be unique across journalists")

    rec = new_record({
        "outlet_id": outlet_id,
        "full_name": full_name,
        "email": email,
        "beat": beat,
        "status": "ACTIVE",
    })
    db.journalists[rec["id"]] = rec
    return success(journalist_out(rec), status=201)


@bp.get("/agency/journalists/<journalist_id>")
@authorize(["AccountManager", "MediaSpecialist", "SchedulingCoordinator", "PlatformAdmin"])
def get_journalist(journalist_id):
    rec = get_or_404(db.journalists, journalist_id)
    return success(journalist_out(rec))


@bp.get("/agency/journalists")
@authorize(["AccountManager", "MediaSpecialist", "SchedulingCoordinator", "PlatformAdmin"])
def list_journalists():
    limit, offset = parse_pagination()
    outlet_id = request.args.get("outlet_id")
    beat = request.args.get("beat")
    status = request.args.get("status")
    if beat is not None and beat not in BEATS:
        raise err("ERR_INVALID_REQUEST", "beat filter invalid")
    if status is not None and status not in JOURNALIST_STATUSES:
        raise err("ERR_INVALID_REQUEST", "status filter invalid")

    records = []
    for r in db.journalists.values():
        if outlet_id is not None and r["outlet_id"] != outlet_id:
            continue
        if beat is not None and r["beat"] != beat:
            continue
        if status is not None and r["status"] != status:
            continue
        records.append(r)
    page, meta = paginate(records, limit, offset)
    return success([journalist_out(r) for r in page], pagination=meta)


@bp.post("/agency/journalists/<journalist_id>/blocklist")
@authorize(["MediaSpecialist", "PlatformAdmin"])
def blocklist_journalist(journalist_id):
    rec = get_or_404(db.journalists, journalist_id)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Journalist is not ACTIVE")
    rec["status"] = "BLOCKLISTED"
    touch(rec)
    return success(journalist_out(rec))
