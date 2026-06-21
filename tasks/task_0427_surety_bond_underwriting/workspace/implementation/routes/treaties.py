"""ReinsuranceTreaty endpoints (PRD §3.1, §2.8). Senior creates/closes; UW reads."""

from flask import Blueprint

import errors
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_treaty
from services.domain import touch
from helpers import (
    get_body, require_str, require_int,
    parse_pagination, paginate, sort_by_created,
)

bp = Blueprint("treaties", __name__)


@bp.route("/surety/treaties", methods=["POST"])
@require_roles("SeniorUnderwriter")
def create_treaty():
    body = get_body()
    name = require_str(body, "name")
    cession_pct_bps = require_int(body, "cession_pct_bps")
    treaty_capacity_cents = require_int(body, "treaty_capacity_cents")

    ts = now_ts()
    tid = new_id()
    record = {
        "id": tid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "name": name,
        "cession_pct_bps": cession_pct_bps,
        "treaty_capacity_cents": treaty_capacity_cents,
        "ceded_committed_cents": 0,
        "status": "OPEN",
    }
    db.treaties[tid] = record
    return success(serialize_treaty(record), status=201)


@bp.route("/surety/treaties/<tid>", methods=["GET"])
@require_roles("Underwriter", "SeniorUnderwriter")
def get_treaty(tid):
    record = db.treaties.get(tid)
    if record is None:
        raise errors.not_found("Treaty not found")
    return success(serialize_treaty(record), status=200)


@bp.route("/surety/treaties", methods=["GET"])
@require_roles("Underwriter", "SeniorUnderwriter")
def list_treaties():
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.treaties.values()))
    page, total = paginate(items, limit, offset)
    return list_success([serialize_treaty(t) for t in page], limit, offset, total)


@bp.route("/surety/treaties/<tid>/close", methods=["POST"])
@require_roles("SeniorUnderwriter")
def close_treaty(tid):
    record = db.treaties.get(tid)
    if record is None:
        raise errors.not_found("Treaty not found")
    if record["status"] != "OPEN":
        raise errors.invalid_state("Treaty is not OPEN")
    record["status"] = "CLOSED"
    touch(record)
    return success(serialize_treaty(record), status=200)
