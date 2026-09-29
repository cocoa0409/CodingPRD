"""Biometric custody and digital replica construction."""

from flask import Blueprint, g

import calc
import guards
import services
from core import (
    ALL_ROLES, authorize, body_json, collection, db, fail, new_id, now, public,
    respond, touch, want_enum, want_id_list, want_str,
)

bp = Blueprint("assets", __name__)

ASSET_KINDS = ("FACE_SCAN", "VOICE_SAMPLE", "MOTION_CAPTURE")
STORAGE_CLASSES = ("ENCRYPTED_VAULT", "COLD_ARCHIVE")
REPLICA_KINDS = ("FACE", "VOICE", "FULL_PERFORMANCE")
READ_ASSETS = ("RightsAdministrator", "ComplianceOfficer",
               "TalentRepresentative", "EstateRepresentative")


# -------------------------------------------------------------- biometric assets

@bp.post("/biometric-assets")
def register_biometric_asset():
    authorize("RightsAdministrator")
    body = body_json()
    talent_id = want_str(body, "talent_id", 1, None)
    consent_grant_id = want_str(body, "consent_grant_id", 1, None)
    asset_kind = want_enum(body, "asset_kind", ASSET_KINDS)
    capture_ref = want_str(body, "capture_ref", 1, 120)
    storage_class = want_enum(body, "storage_class", STORAGE_CLASSES,
                              required=False, default="ENCRYPTED_VAULT")
    payload_digest = want_str(body, "payload_digest", 1, 128)

    talent = guards.need_talent(talent_id)
    grant = guards.need_grant(consent_grant_id)
    profile = guards.need_profile(talent["domicile_state_code"])
    if grant["status"] != "ACTIVE":
        fail("ERR_CONSENT_NOT_ACTIVE", "the named consent grant is not ACTIVE")

    stamp = now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "talent_id": talent["id"],
        "consent_grant_id": grant["id"],
        "asset_kind": asset_kind,
        "capture_ref": capture_ref,
        "storage_class": storage_class,
        "payload_digest": payload_digest,
        "status": "STORED",
        "retention_until": calc.biometric_retention_deadline(stamp, grant, profile),
        "purge_due_at": None,
        "purged_at": None,
        "held_from_status": None,
        "_seq": db.next_seq(),
    }
    db.biometric_assets[row["id"]] = row
    return respond(public(row), 201)


@bp.get("/biometric-assets/<row_id>")
def read_biometric_asset(row_id):
    authorize(*READ_ASSETS)
    return respond(public(guards.need_asset(row_id)))


@bp.get("/biometric-assets")
def list_biometric_assets():
    authorize(*READ_ASSETS)
    return collection(db.biometric_assets.values(), {
        "talent_id": "talent_id",
        "consent_grant_id": "consent_grant_id",
        "status": "status",
        "asset_kind": "asset_kind",
    })


@bp.post("/biometric-assets/<row_id>/purge")
def purge_biometric_asset(row_id):
    authorize("RightsAdministrator")
    body = body_json()
    want_str(body, "purge_note", 1, None)
    asset = guards.need_asset(row_id)
    # The asset-state rung deliberately admits LEGAL_HOLD so the safety rung can
    # report the more informative refusal; it refuses only an already-PURGED asset.
    if asset["status"] == "PURGED":
        fail("ERR_INVALID_ASSET_STATE", "this asset is already PURGED")
    if asset["status"] == "LEGAL_HOLD":
        fail("ERR_ASSET_UNDER_LEGAL_HOLD", "impounded material may not be destroyed")
    for replica in db.digital_replicas.values():
        if replica["status"] in ("BUILT", "APPROVED_FOR_USE") \
                and asset["id"] in replica["source_asset_ids"]:
            fail("ERR_ASSET_BOUND_TO_ACTIVE_REPLICA",
                 "this asset still backs a live replica's provenance")
    asset["status"] = "PURGED"
    asset["payload_digest"] = None
    asset["purged_at"] = now()
    touch(asset)
    return respond(public(asset))


# -------------------------------------------------------------- digital replicas

@bp.post("/digital-replicas")
def build_digital_replica():
    authorize("RightsAdministrator")
    body = body_json()
    talent_id = want_str(body, "talent_id", 1, None)
    consent_grant_id = want_str(body, "consent_grant_id", 1, None)
    replica_kind = want_enum(body, "replica_kind", REPLICA_KINDS)
    source_asset_ids = want_id_list(body, "source_asset_ids", 10)
    build_ref = want_str(body, "build_ref", 1, 120)

    talent = guards.need_talent(talent_id)
    grant = guards.need_grant(consent_grant_id)
    assets = [guards.need_asset(asset_id) for asset_id in source_asset_ids]

    if grant["status"] != "ACTIVE":
        fail("ERR_CONSENT_NOT_ACTIVE", "the named consent grant is not ACTIVE")

    for asset in assets:
        if asset["status"] == "LEGAL_HOLD":
            fail("ERR_REPLICA_SOURCE_UNDER_LEGAL_HOLD",
                 "a source asset is impounded under legal hold")
    for asset in assets:
        if asset["consent_grant_id"] != grant["id"] or asset["talent_id"] != talent["id"]:
            fail("ERR_ASSET_CONSENT_MISMATCH",
                 "every source asset must belong to this talent under this grant")
    if not source_asset_ids or len(set(source_asset_ids)) != len(source_asset_ids):
        fail("ERR_NO_SOURCE_ASSETS",
             "source_asset_ids must be non-empty and free of duplicates")

    stamp = now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "talent_id": talent["id"],
        "consent_grant_id": grant["id"],
        "replica_kind": replica_kind,
        "source_asset_ids": list(source_asset_ids),
        "build_ref": build_ref,
        "status": "BUILT",
        "approved_at": None,
        "approved_by_user_id": None,
        "quarantine_reason": None,
        "held_from_status": None,
        "open_license_count": 0,
        "_seq": db.next_seq(),
    }
    db.digital_replicas[row["id"]] = row
    return respond(public(row), 201)


@bp.get("/digital-replicas/<row_id>")
def read_digital_replica(row_id):
    authorize(*ALL_ROLES)
    return respond(public(guards.need_replica(row_id)))


@bp.get("/digital-replicas")
def list_digital_replicas():
    authorize(*ALL_ROLES)
    return collection(db.digital_replicas.values(), {
        "talent_id": "talent_id",
        "consent_grant_id": "consent_grant_id",
        "status": "status",
        "replica_kind": "replica_kind",
    })


@bp.post("/digital-replicas/<row_id>/approve-for-use")
def approve_for_use(row_id):
    authorize("TalentRepresentative", "EstateRepresentative")
    body = body_json()
    want_str(body, "approval_note", 1, None, required=False, default=None)
    replica = guards.need_replica(row_id)
    talent = db.talents[replica["talent_id"]]
    grant = db.consent_grants[replica["consent_grant_id"]]
    guards.talent_side_ownership(talent, g.role, g.user_id)
    if grant["status"] != "ACTIVE":
        fail("ERR_CONSENT_NOT_ACTIVE", "the governing consent grant is not ACTIVE")
    if replica["status"] != "BUILT":
        fail("ERR_INVALID_REPLICA_STATE", "only a BUILT replica may be approved for use")
    guards.block_frozen(talent)
    guards.need_verified_estate(talent)
    replica["status"] = "APPROVED_FOR_USE"
    replica["approved_at"] = now()
    replica["approved_by_user_id"] = g.user_id
    touch(replica)
    return respond(public(replica))
