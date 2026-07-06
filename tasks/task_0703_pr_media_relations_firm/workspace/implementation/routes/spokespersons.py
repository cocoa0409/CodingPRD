"""Spokesperson endpoints (PRD 3.6)."""
from flask import Blueprint, request

import db
from common import (get_json_body, get_or_404, new_record, paginate,
                    parse_pagination, ref_or_404, require_int, require_str, touch)
from errors import err
from middleware import authorize
from response import success
from services.cascades import deactivate_spokesperson_cascade
from services.serialize import spokesperson_out

bp = Blueprint("spokespersons", __name__)

SPOKESPERSON_STATUSES = {"ACTIVE", "INACTIVE"}


@bp.post("/agency/spokespersons")
@authorize(["AccountManager"])
def create_spokesperson():
    body = get_json_body()
    client_id = body.get("client_id")
    ref_or_404(db.clients, client_id, "client_id")
    full_name = require_str(body, "full_name")
    title = require_str(body, "title")
    if "prep_buffer_minutes" in body and body.get("prep_buffer_minutes") is not None:
        prep_buffer_minutes = require_int(body, "prep_buffer_minutes", minimum=0)
    else:
        prep_buffer_minutes = 30

    rec = new_record({
        "client_id": client_id,
        "full_name": full_name,
        "title": title,
        "prep_buffer_minutes": prep_buffer_minutes,
        "status": "ACTIVE",
    })
    db.spokespersons[rec["id"]] = rec
    return success(spokesperson_out(rec), status=201)


@bp.get("/agency/spokespersons/<spokesperson_id>")
@authorize(["AccountManager", "SchedulingCoordinator", "PlatformAdmin"])
def get_spokesperson(spokesperson_id):
    rec = get_or_404(db.spokespersons, spokesperson_id)
    return success(spokesperson_out(rec))


@bp.get("/agency/spokespersons")
@authorize(["AccountManager", "SchedulingCoordinator", "PlatformAdmin"])
def list_spokespersons():
    limit, offset = parse_pagination()
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    if status is not None and status not in SPOKESPERSON_STATUSES:
        raise err("ERR_INVALID_REQUEST", "status filter invalid")
    records = []
    for r in db.spokespersons.values():
        if client_id is not None and r["client_id"] != client_id:
            continue
        if status is not None and r["status"] != status:
            continue
        records.append(r)
    page, meta = paginate(records, limit, offset)
    return success([spokesperson_out(r) for r in page], pagination=meta)


@bp.post("/agency/spokespersons/<spokesperson_id>/deactivate")
@authorize(["AccountManager"])
def deactivate_spokesperson(spokesperson_id):
    rec = get_or_404(db.spokespersons, spokesperson_id)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Spokesperson is not ACTIVE")
    rec["status"] = "INACTIVE"
    touch(rec)
    deactivate_spokesperson_cascade(rec)
    return success(spokesperson_out(rec))
