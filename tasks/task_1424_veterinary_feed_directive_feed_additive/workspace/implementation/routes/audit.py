"""Audit bundle routes."""

from flask import Blueprint, request

import errors
import util
from db import store
from middleware import require_roles
from response import success_object
from services import core
from routes.onboarding import _paginate

bp = Blueprint("audit", __name__)


@bp.post("/vfd/producers/<pid>/audit-bundles")
def create_audit_bundle(pid):
    require_roles("Inspector")
    producer = core.get_producer(pid)
    body = util.get_json_body()
    window_start = util.require_field(body, "window_start")
    window_end = util.require_field(body, "window_end")
    ws = util.parse_iso(window_start, "window_start")
    we = util.parse_iso(window_end, "window_end")
    required = core.compute_required_record_count(producer["id"], ws, we)
    bundle = util.new_entity({
        "producer_id": producer["id"],
        "opened_at": util.logical_now_iso(),
        "window_start": window_start,
        "window_end": window_end,
        "required_record_count": required,
        "produced_record_count": 0,
        "status": "OPEN",
    })
    store.audit_bundles[bundle["id"]] = bundle
    return success_object(bundle, 201)


@bp.get("/vfd/audit-bundles/<aid>")
def get_audit_bundle(aid):
    require_roles("Inspector", "Producer")
    return success_object(core.get_audit_bundle(aid))


@bp.get("/vfd/producers/<pid>/audit-bundles")
def list_audit_bundles_for_producer(pid):
    require_roles("Inspector", "Producer")
    core.get_producer(pid)
    items = [b for b in store.audit_bundles.values() if b.get("producer_id") == pid]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b.get("status") == status]
    return _paginate(items)


@bp.post("/vfd/audit-bundles/<aid>/record-produced")
def record_produced(aid):
    user_id, _ = require_roles("Producer")
    bundle = core.get_audit_bundle(aid)
    if user_id != bundle.get("producer_id"):
        raise errors.forbidden("X-User-ID must equal audit bundle's producer_id")
    if bundle["status"] != "OPEN":
        raise errors.invalid_state("AuditBundle must be OPEN")
    bundle["produced_record_count"] = bundle.get("produced_record_count", 0) + 1
    util.touch(bundle)
    return success_object(bundle)


@bp.post("/vfd/audit-bundles/<aid>/close")
def close_audit_bundle(aid):
    require_roles("Inspector")
    bundle = core.get_audit_bundle(aid)
    if bundle["status"] != "OPEN":
        raise errors.invalid_state("AuditBundle must be OPEN to close")
    if bundle["produced_record_count"] != bundle["required_record_count"]:
        raise errors.ApiError(errors.ERR_AUDIT_INCOMPLETE,
                              "produced_record_count < required_record_count on audit close", 409)
    bundle["status"] = "COMPLETE"
    util.touch(bundle)
    return success_object(bundle)


@bp.post("/vfd/audit-bundles/<aid>/mark-deficient")
def mark_deficient(aid):
    require_roles("Inspector")
    bundle = core.get_audit_bundle(aid)
    if bundle["status"] != "OPEN":
        raise errors.invalid_state("AuditBundle must be OPEN to mark deficient")
    bundle["status"] = "DEFICIENT"
    util.touch(bundle)
    producer = core.get_producer(bundle["producer_id"])
    producer["status"] = "SUSPENDED"
    util.touch(producer)
    core.expire_vfds_for_producer(producer["id"])
    return success_object(bundle)
