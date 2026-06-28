"""Specimens, custody events, accession, QNS rejection (PRD 3.7, 3.8, 3.9)."""
from flask import Blueprint, request, g

import common
import errors
import serializers
from db import db, touch
from middleware import require_roles
from services import custody, cascade

bp = Blueprint("specimens", __name__)


@bp.get("/specimens/<rid>")
@require_roles("Dispatcher", "Phlebotomist", "LabOps")
def get_specimen(rid):
    rec = common.find_specimen(rid)
    return common.object_response(serializers.specimen(rec))


@bp.get("/specimens/<rid>/custody-events")
@require_roles("Dispatcher", "Phlebotomist", "LabOps", "OrderingProvider")
def list_specimen_custody(rid):
    common.find_specimen(rid)
    limit, offset = common.get_pagination()
    items = [e for e in db.custody_events.values() if e["specimen_id"] == rid]
    items = common.sort_by_created(items)
    page, total = common.paginate(items, limit, offset)
    return common.array_response([serializers.custody_event(e) for e in page], limit, offset, total)


@bp.get("/custody-events/<rid>")
@require_roles("Dispatcher", "Phlebotomist", "LabOps", "OrderingProvider")
def get_custody_event(rid):
    rec = common.find_custody_event(rid)
    return common.object_response(serializers.custody_event(rec))


@bp.get("/custody-events")
@require_roles("Dispatcher", "Phlebotomist", "LabOps", "OrderingProvider")
def list_custody_events():
    limit, offset = common.get_pagination()
    items = list(db.custody_events.values())
    specimen_id = request.args.get("specimen_id")
    if specimen_id is not None:
        items = [e for e in items if e["specimen_id"] == specimen_id]
    prior_event_id = request.args.get("prior_event_id")
    if prior_event_id is not None:
        items = [e for e in items if e["prior_event_id"] == prior_event_id]
    items = common.sort_by_created(items)
    page, total = common.paginate(items, limit, offset)
    return common.array_response([serializers.custody_event(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Accession (PRD 3.8) — MANIFESTED -> ACCESSIONED
# ---------------------------------------------------------------------------
@bp.post("/specimens/<rid>/accession")
@require_roles("LabOps")
def accession(rid):
    specimen = common.find_specimen(rid)
    if specimen["status"] != "MANIFESTED":
        errors.fail(errors.ERR_SPECIMEN_NOT_ACCESSIONABLE, "Specimen is not MANIFESTED.")

    manifest = db.courier_manifests.get(specimen["courier_manifest_id"])
    if manifest is None or manifest["status"] != "IN_TRANSIT":
        errors.fail(errors.ERR_MANIFEST_NOT_IN_TRANSIT, "Parent manifest is not IN_TRANSIT.")

    specimen["status"] = "ACCESSIONED"
    touch(specimen)

    order = db.lab_orders.get(specimen["lab_order_id"])
    if order is not None:
        order["specimens_accessioned_count"] = cascade.recompute_accessioned_count(order)
        touch(order)

    custody.append_event(specimen["id"], "ACCESSIONED", g.role, g.user_id)

    # Bubble-up: if all manifest specimens terminal, manifest -> DELIVERED.
    cascade.maybe_deliver_manifest(manifest)

    return common.object_response(serializers.specimen(specimen))


# ---------------------------------------------------------------------------
# QNS rejection (PRD 3.8, 3.9) — MANIFESTED -> QNS_REJECTED, drives redraw cascade
# ---------------------------------------------------------------------------
@bp.post("/specimens/<rid>/reject-qns")
@require_roles("LabOps")
def reject_qns(rid):
    specimen = common.find_specimen(rid)
    if specimen["status"] != "MANIFESTED":
        errors.fail(errors.ERR_SPECIMEN_NOT_REJECTABLE, "Specimen is not MANIFESTED.")

    manifest = db.courier_manifests.get(specimen["courier_manifest_id"])
    if manifest is None or manifest["status"] != "IN_TRANSIT":
        errors.fail(errors.ERR_MANIFEST_NOT_IN_TRANSIT, "Parent manifest is not IN_TRANSIT.")

    specimen["status"] = "QNS_REJECTED"
    touch(specimen)

    custody.append_event(specimen["id"], "REJECTED_QNS", g.role, g.user_id)

    # Redraw cascade when the owning order has already completed its draw.
    order = db.lab_orders.get(specimen["lab_order_id"])
    if order is not None and order["status"] == "DRAW_COMPLETED":
        cascade.redraw_cascade(order)
    elif order is not None:
        # Keep accessioned count reconciled even outside the redraw cascade
        # (a QNS following a prior accession reduces the count — PRD 2.5).
        order["specimens_accessioned_count"] = cascade.recompute_accessioned_count(order)
        touch(order)

    # Bubble-up: if all manifest specimens terminal, manifest -> DELIVERED.
    cascade.maybe_deliver_manifest(manifest)

    return common.object_response(serializers.specimen(specimen))
