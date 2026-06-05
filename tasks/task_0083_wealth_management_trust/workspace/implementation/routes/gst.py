"""GST exemption allocations + GST events (PRD §3.8)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_role, parse_pagination, paginate
from response import success
from services import serialize
from services.helpers import get_json_body, require_str, require_int, must_exist
from services.ledger import recompute_inclusion_ratio, recompute_grantor_remaining

bp = Blueprint("gst", __name__)


@bp.route("/trusts/<tid>/gst-exemption-allocations", methods=["POST"])
def allocate_exemption(tid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    t = must_exist(db.trusts, tid)
    body = get_json_body()
    grantor_id = require_str(body, "grantor_id")
    amount_cents = require_int(body, "amount_cents")
    expected_trust_version = require_int(body, "expected_trust_version")
    grantor = must_exist(db.grantors, grantor_id)

    with db.LOCK:
        # Business-rule order (PRD §2.10): grantor mismatch, amount, exemption pool, OCC.
        if grantor_id != t["grantor_id"]:
            raise err("ERR_GRANTOR_MISMATCH")
        if amount_cents <= 0:
            raise err("ERR_INVALID_AMOUNT")
        if amount_cents > grantor["gst_exemption_remaining_cents"]:
            raise err("ERR_GST_EXEMPTION_EXCEEDED")
        if expected_trust_version != t["version"]:
            raise err("ERR_STALE_TRUST_VERSION")

        alloc = db.base_fields()
        alloc.update({
            "trust_id": tid,
            "grantor_id": grantor_id,
            "amount_cents": amount_cents,
            "status": "ALLOCATED",
        })
        db.gst_allocations[alloc["id"]] = alloc

        t["gst_exemption_allocated_cents"] += amount_cents
        recompute_inclusion_ratio(t)
        recompute_grantor_remaining(grantor)
        db.touch(grantor)
        db.touch(t)
    return success(serialize.gst_allocation(alloc), status=201)


@bp.route("/trusts/<tid>/gst-exemption-allocations", methods=["GET"])
def list_trust_allocations(tid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    must_exist(db.trusts, tid)
    limit, offset = parse_pagination()
    items = [a for a in db.gst_allocations.values() if a["trust_id"] == tid]
    page, meta = paginate(items, limit, offset)
    return success([serialize.gst_allocation(a) for a in page], pagination=meta)


@bp.route("/gst-exemption-allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    a = must_exist(db.gst_allocations, aid)
    return success(serialize.gst_allocation(a))


@bp.route("/gst-exemption-allocations", methods=["GET"])
def list_allocations():
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    limit, offset = parse_pagination()
    grantor_id = request.args.get("grantor_id")
    items = list(db.gst_allocations.values())
    if grantor_id is not None:
        items = [a for a in items if a["grantor_id"] == grantor_id]
    page, meta = paginate(items, limit, offset)
    return success([serialize.gst_allocation(a) for a in page], pagination=meta)


@bp.route("/trusts/<tid>/gst-exemption-allocations/<alloc_id>", methods=["DELETE"])
def release_allocation(tid, alloc_id):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    t = must_exist(db.trusts, tid)
    alloc = must_exist(db.gst_allocations, alloc_id)
    if alloc["trust_id"] != tid:
        raise err("ERR_NOT_FOUND")
    with db.LOCK:
        if alloc["status"] != "ALLOCATED":
            raise err("ERR_INVALID_STATE")
        # Cannot release if a GstEvent on the trust has already consumed exemption.
        if any(ev["trust_id"] == tid for ev in db.gst_events.values()):
            raise err("ERR_ALLOCATION_CONSUMED")
        grantor = db.grantors[alloc["grantor_id"]]
        alloc["status"] = "RELEASED"
        db.touch(alloc)
        t["gst_exemption_allocated_cents"] -= alloc["amount_cents"]
        recompute_inclusion_ratio(t)
        recompute_grantor_remaining(grantor)
        db.touch(grantor)
        db.touch(t)
    return success(serialize.gst_allocation(alloc))


# ---- GST events (read-only satellite) ----
@bp.route("/trusts/<tid>/gst-events", methods=["GET"])
def list_trust_gst_events(tid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    must_exist(db.trusts, tid)
    limit, offset = parse_pagination()
    beneficiary_id = request.args.get("beneficiary_id")
    items = [ev for ev in db.gst_events.values() if ev["trust_id"] == tid]
    if beneficiary_id is not None:
        items = [ev for ev in items if ev["beneficiary_id"] == beneficiary_id]
    page, meta = paginate(items, limit, offset)
    return success([serialize.gst_event(ev) for ev in page], pagination=meta)


@bp.route("/gst-events/<eid>", methods=["GET"])
def get_gst_event(eid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    ev = must_exist(db.gst_events, eid)
    return success(serialize.gst_event(ev))


@bp.route("/gst-events", methods=["GET"])
def list_gst_events():
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    limit, offset = parse_pagination()
    beneficiary_id = request.args.get("beneficiary_id")
    distribution_id = request.args.get("distribution_id")
    items = list(db.gst_events.values())
    if beneficiary_id is not None:
        items = [ev for ev in items if ev["beneficiary_id"] == beneficiary_id]
    if distribution_id is not None:
        items = [ev for ev in items if ev["distribution_id"] == distribution_id]
    page, meta = paginate(items, limit, offset)
    return success([serialize.gst_event(ev) for ev in page], pagination=meta)
