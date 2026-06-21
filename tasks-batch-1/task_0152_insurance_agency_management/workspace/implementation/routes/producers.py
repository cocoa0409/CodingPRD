"""Producer endpoints (PRD §3.2)."""
from flask import Blueprint, request

import serialize
from db import store, new_common, touch
from errors import err, ERR_DUPLICATE, ERR_INVALID_STATE
from middleware import auth, get_json_body, lookup, check_version, paginate
from response import object_response, array_response
from util import require_str, require_fraction

bp = Blueprint("producers", __name__)

ALL_ROLES = {"AgencyAdmin", "Producer", "AccountManager", "TrustAccountant"}


@bp.post("/producers")
def create_producer():
    auth({"AgencyAdmin"})
    body = get_json_body()
    full_name = require_str(body, "full_name")
    npn = require_str(body, "npn")  # non-empty
    split_pct = require_fraction(body, "default_split_pct")
    with store.lock:
        for p in store.producers.values():
            if p["npn"] == npn:
                raise err(ERR_DUPLICATE, "npn already exists")
        rec = new_common()
        rec.update(
            full_name=full_name,
            npn=npn,
            status="ACTIVE",
            default_split_pct=split_pct,
        )
        store.producers[rec["id"]] = rec
        return object_response(serialize.producer(rec), 201)


@bp.get("/producers/<pid>")
def get_producer(pid):
    auth(ALL_ROLES)
    rec = lookup(store.producers, pid)
    return object_response(serialize.producer(rec))


@bp.get("/producers")
def list_producers():
    auth(ALL_ROLES)
    status = request.args.get("status")
    recs = [p for p in store.producers.values() if status is None or p["status"] == status]
    page, limit, offset, total = paginate(recs)
    return array_response([serialize.producer(p) for p in page], limit, offset, total)


@bp.post("/producers/<pid>/deactivate")
def deactivate_producer(pid):
    auth({"AgencyAdmin"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.producers, pid)
        if rec["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "only an ACTIVE producer may be deactivated")
        check_version(rec, body.get("expected_producer_version"), "expected_producer_version")
        rec["status"] = "INACTIVE"
        touch(rec)
        return object_response(serialize.producer(rec))
