"""Stems, cue sheets and performance-royalty registration (PRD 3.8)."""

from flask import Blueprint, request

import clock
import cue
import db
import ledger
import licensing
import response
import validators as v
from auth import ALL_ROLES, endpoint, require_project_owner
from errors import ApiError

bp = Blueprint("delivery", __name__)


def _project_of(deliverable):
    deal = db.license_deals[deliverable["license_deal_id"]]
    return db.projects[deal["project_id"]], deal


@bp.get("/deliverables/<deliverable_id>")
@endpoint(ALL_ROLES)
def get_deliverable(deliverable_id):
    deliverable = v.path_lookup(db.deliverables, deliverable_id, "ERR_DELIVERABLE_NOT_FOUND")
    return response.ok(db.serialize(deliverable))


@bp.post("/deliverables/<deliverable_id>/stems")
@endpoint(["MusicHouseProducer"])
def deliver_stems(deliverable_id):
    deliverable = v.path_lookup(db.deliverables, deliverable_id, "ERR_DELIVERABLE_NOT_FOUND")
    project, _deal = _project_of(deliverable)

    body = v.get_body()
    stem_names = v.v_array(body, "stem_names", item="string")
    lengths_seconds = v.v_array(body, "lengths_seconds", item="integer")

    if deliverable["master_status"] != "PENDING":
        raise ApiError("ERR_DELIVERABLE_INVALID_STATE")

    brief = licensing.approved_brief(project["id"])
    required_lengths = set(brief["required_lengths"]) if brief else set()
    if set(lengths_seconds) != required_lengths:
        raise ApiError("ERR_ALTERNATE_LENGTHS_INCOMPLETE")
    if not set(cue.REQUIRED_STEM_NAMES).issubset(set(stem_names)):
        raise ApiError("ERR_STEM_MANIFEST_INCOMPLETE")

    deliverable["master_status"] = "STEMS_DELIVERED"
    deliverable["delivered_lengths"] = sorted(lengths_seconds, reverse=True)
    deliverable["stem_manifest"] = sorted(stem_names)
    db.touch(deliverable)
    return response.ok(db.serialize(deliverable))


@bp.post("/deliverables/<deliverable_id>/approve-master")
@endpoint(["ClientRep"])
def approve_master(deliverable_id):
    deliverable = v.path_lookup(db.deliverables, deliverable_id, "ERR_DELIVERABLE_NOT_FOUND")
    project, _deal = _project_of(deliverable)
    require_project_owner(project)

    if deliverable["master_status"] != "STEMS_DELIVERED":
        raise ApiError("ERR_DELIVERABLE_INVALID_STATE")

    deliverable["master_status"] = "CLIENT_APPROVED"
    db.touch(deliverable)

    if project["status"] == "IN_PRODUCTION":
        project["status"] = "DELIVERED"
        ledger.recompute_posture(project)
        db.touch(project)

    return response.ok(db.serialize(deliverable))


@bp.post("/deliverables/<deliverable_id>/reject-master")
@endpoint(["ClientRep"])
def reject_master(deliverable_id):
    deliverable = v.path_lookup(db.deliverables, deliverable_id, "ERR_DELIVERABLE_NOT_FOUND")
    project, _deal = _project_of(deliverable)
    require_project_owner(project)

    body = v.get_body()
    v.v_string(body, "rejection_note")

    if deliverable["master_status"] != "STEMS_DELIVERED":
        raise ApiError("ERR_DELIVERABLE_INVALID_STATE")

    deliverable["master_status"] = "PENDING"
    deliverable["delivered_lengths"] = []
    deliverable["stem_manifest"] = []
    db.touch(deliverable)
    return response.ok(db.serialize(deliverable))


@bp.post("/deliverables/<deliverable_id>/cue-entries")
@endpoint(["RightsAdmin"])
def create_cue_entry(deliverable_id):
    deliverable = v.path_lookup(db.deliverables, deliverable_id, "ERR_DELIVERABLE_NOT_FOUND")
    body = v.get_body()
    composer = None
    if v.present(body, "composer_id"):
        composer = v.body_lookup(db.composers, body["composer_id"], "ERR_COMPOSER_NOT_FOUND")
    v.v_string(body, "composer_id")
    role = v.v_enum(body, "role", ("COMPOSER", "ARRANGER", "PUBLISHER"))
    declared_weight = v.v_int(body, "declared_weight", minimum=1)

    if deliverable["cuesheet_status"] == "REGISTERED":
        raise ApiError("ERR_DELIVERABLE_INVALID_STATE")

    record = db.create(db.cue_entries, {
        "deliverable_id": deliverable["id"],
        "composer_id": composer["id"],
        "role": role,
        "declared_weight": declared_weight,
        "share_bps": 0,
        "status": "ALLOCATED",
    })
    cue.allocate(deliverable)
    return response.created(db.serialize(record))


@bp.get("/cue-entries/<entry_id>")
@endpoint(ALL_ROLES)
def get_cue_entry(entry_id):
    entry = v.path_lookup(db.cue_entries, entry_id, "ERR_CUE_ENTRY_NOT_FOUND")
    return response.ok(db.serialize(entry))


@bp.get("/cue-entries")
@endpoint(ALL_ROLES)
def list_cue_entries():
    rows = list(db.cue_entries.values())
    deliverable_id = request.args.get("deliverable_id")
    composer_id = request.args.get("composer_id")
    status = request.args.get("status")
    if deliverable_id:
        rows = [r for r in rows if r["deliverable_id"] == deliverable_id]
    if composer_id:
        rows = [r for r in rows if r["composer_id"] == composer_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    items, meta = v.paginate(db.by_created(rows))
    return response.ok_list(items, meta)


@bp.post("/cue-entries/<entry_id>/void")
@endpoint(["RightsAdmin"])
def void_cue_entry(entry_id):
    entry = v.path_lookup(db.cue_entries, entry_id, "ERR_CUE_ENTRY_NOT_FOUND")
    deliverable = db.deliverables[entry["deliverable_id"]]

    if entry["status"] != "ALLOCATED" or deliverable["cuesheet_status"] == "REGISTERED":
        raise ApiError("ERR_CUE_ENTRY_ALREADY_VOIDED")

    entry["status"] = "VOIDED"
    entry["share_bps"] = 0
    db.touch(entry)

    cue.allocate(deliverable)

    if not cue.deliverable_entries(deliverable["id"], "ALLOCATED"):
        if deliverable["cuesheet_status"] == "FILED":
            deliverable["cuesheet_status"] = "NOT_FILED"
            db.touch(deliverable)

    return response.ok(db.serialize(entry))


@bp.post("/deliverables/<deliverable_id>/file-cue-sheet")
@endpoint(["RightsAdmin"])
def file_cue_sheet(deliverable_id):
    deliverable = v.path_lookup(db.deliverables, deliverable_id, "ERR_DELIVERABLE_NOT_FOUND")

    if deliverable["cuesheet_status"] != "NOT_FILED":
        raise ApiError("ERR_DELIVERABLE_INVALID_STATE")
    if not cue.deliverable_entries(deliverable["id"], "ALLOCATED"):
        raise ApiError("ERR_CUE_SHEET_EMPTY")

    deliverable["cuesheet_status"] = "FILED"
    db.touch(deliverable)
    return response.ok(db.serialize(deliverable))


@bp.post("/deliverables/<deliverable_id>/register-cue-sheet")
@endpoint(["RightsAdmin"])
def register_cue_sheet(deliverable_id):
    deliverable = v.path_lookup(db.deliverables, deliverable_id, "ERR_DELIVERABLE_NOT_FOUND")
    project, deal = _project_of(deliverable)

    if deliverable["cuesheet_status"] != "FILED":
        raise ApiError("ERR_DELIVERABLE_INVALID_STATE")
    if deal["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_ACTIVE")
    if not cue.deliverable_entries(deliverable["id"], "ALLOCATED"):
        raise ApiError("ERR_CUE_SHEET_EMPTY")

    deliverable["cuesheet_status"] = "REGISTERED"
    deliverable["registered_at"] = clock.now_iso()
    db.touch(deliverable)

    if project["status"] == "DELIVERED":
        project["status"] = "CLOSED"
        ledger.recompute_posture(project)
        db.touch(project)

    return response.ok(db.serialize(deliverable))
