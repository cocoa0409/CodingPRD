"""Courier manifests: open, list, get, add-specimen, pickup (PRD 3.8)."""
from flask import Blueprint, request, g

import common
import errors
import serializers
from clock import clock, to_iso_z
from db import db, stamp_common, touch
from middleware import require_roles
from services import custody, cascade

bp = Blueprint("manifests", __name__)


@bp.post("/courier-manifests")
@require_roles("Dispatcher")
def create_manifest():
    body = common.get_body()
    lab_partner_id = common.require_str(body, "lab_partner_id")
    # Priority 4: lab_partner_id foreign key exists.
    if lab_partner_id not in db.lab_partners:
        errors.fail(errors.ERR_LAB_PARTNER_NOT_FOUND, "Lab partner not found.")
    territory_code = common.require_str(body, "territory_code")

    rec = {
        "lab_partner_id": lab_partner_id,
        "territory_code": territory_code,
        "picked_up_at_utc": None,
        "accession_due_utc": None,
        "specimen_count": 0,
        "status": "BUILDING",
    }
    stamp_common(rec)
    db.courier_manifests[rec["id"]] = rec
    return common.object_response_201(serializers.manifest(rec))


@bp.get("/courier-manifests")
@require_roles("Dispatcher", "LabOps")
def list_manifests():
    limit, offset = common.get_pagination()
    items = list(db.courier_manifests.values())
    lab_partner_id = request.args.get("lab_partner_id")
    if lab_partner_id is not None:
        items = [m for m in items if m["lab_partner_id"] == lab_partner_id]
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    items = common.sort_by_created(items)
    page, total = common.paginate(items, limit, offset)
    return common.array_response([serializers.manifest(m) for m in page], limit, offset, total)


@bp.get("/courier-manifests/<rid>")
@require_roles("Dispatcher", "LabOps")
def get_manifest(rid):
    rec = common.find_manifest(rid)
    return common.object_response(serializers.manifest(rec))


@bp.get("/courier-manifests/<rid>/specimens")
@require_roles("Dispatcher", "LabOps")
def list_manifest_specimens(rid):
    common.find_manifest(rid)
    limit, offset = common.get_pagination()
    items = [s for s in db.specimens.values() if s["courier_manifest_id"] == rid]
    items = common.sort_by_created(items)
    page, total = common.paginate(items, limit, offset)
    return common.array_response([serializers.specimen(s) for s in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Add specimen (PRD 3.8) — COLLECTED -> MANIFESTED
# ---------------------------------------------------------------------------
@bp.post("/courier-manifests/<manifest_id>/add-specimen")
@require_roles("Phlebotomist")
def add_specimen(manifest_id):
    manifest = common.find_manifest(manifest_id)
    body = common.get_body()
    specimen_id = common.require_str(body, "specimen_id")
    # Priority 4: specimen foreign key exists.
    specimen = db.specimens.get(specimen_id)
    if specimen is None:
        errors.fail(errors.ERR_SPECIMEN_NOT_FOUND, "Specimen not found.")

    # Priority 7: specimen state legality.
    if specimen["status"] != "COLLECTED":
        errors.fail(errors.ERR_SPECIMEN_NOT_MANIFESTABLE, "Specimen is not COLLECTED.")
    if manifest["status"] != "BUILDING":
        errors.fail(errors.ERR_MANIFEST_NOT_BUILDING, "Manifest is not BUILDING.")

    order = db.lab_orders.get(specimen["lab_order_id"])
    # Territory: manifest.territory_code must equal the specimen's order territory.
    if manifest["territory_code"] != order["patient_territory_code"]:
        errors.fail(errors.ERR_TERRITORY_MISMATCH,
                    "Manifest territory does not match the specimen's order territory.")
    # Lab partner: manifest.lab_partner_id must equal the order's lab_partner_id.
    if manifest["lab_partner_id"] != order["lab_partner_id"]:
        errors.fail(errors.ERR_LAB_PARTNER_MISMATCH,
                    "Manifest lab partner does not match the order's lab partner.")

    specimen["courier_manifest_id"] = manifest["id"]
    specimen["status"] = "MANIFESTED"
    touch(specimen)

    manifest["specimen_count"] = cascade.recompute_manifest_specimen_count(manifest)
    touch(manifest)

    custody.append_event(specimen["id"], "MANIFESTED", g.role, g.user_id)

    return common.object_response(serializers.specimen(specimen))


# ---------------------------------------------------------------------------
# Pickup (PRD 3.8) — BUILDING -> IN_TRANSIT
# ---------------------------------------------------------------------------
@bp.post("/courier-manifests/<manifest_id>/pickup")
@require_roles("Dispatcher")
def pickup(manifest_id):
    manifest = common.find_manifest(manifest_id)

    if manifest["status"] != "BUILDING":
        errors.fail(errors.ERR_MANIFEST_NOT_BUILDING, "Manifest is not BUILDING.")
    if manifest["specimen_count"] < 1:
        errors.fail(errors.ERR_MANIFEST_EMPTY, "Manifest holds no specimens.")

    partner = db.lab_partners.get(manifest["lab_partner_id"])
    if partner is None or partner["status"] != "ACTIVE":
        errors.fail(errors.ERR_LAB_PARTNER_SUSPENDED, "Routed lab partner is not ACTIVE.")

    picked_up = clock.now()
    manifest["picked_up_at_utc"] = to_iso_z(picked_up)
    # accession_due_utc = picked_up_at_utc + partner.courier_sla_hours whole hours.
    due = clock.plus_hours(partner["courier_sla_hours"])
    manifest["accession_due_utc"] = to_iso_z(due)
    manifest["status"] = "IN_TRANSIT"
    touch(manifest)

    return common.object_response(serializers.manifest(manifest))
