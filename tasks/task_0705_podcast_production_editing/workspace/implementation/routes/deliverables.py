"""Deliverable & AssetVersion endpoints (PRD §3.4, §2.10)."""
from flask import Blueprint, request

import errors
import middleware as mw
from constants import DELIVERABLE_KINDS, LOUDNESS_TOLERANCE_LUFS
from db import db
from response import array_response, object_response
from routes.common import assert_show_owner, get_or_404
from serialize import serialize, serialize_list

bp = Blueprint("deliverables", __name__)


# ---- Deliverable ----
@bp.post("/deliverables")
def create_deliverable():
    auth = mw.authenticate()
    mw.require_role(auth, {"ProducerEng"})
    body = mw.get_json_body()
    episode_id = mw.require_string(body, "episode_id")
    get_or_404(db.episodes, episode_id)
    kind = mw.require_enum(body, "kind", DELIVERABLE_KINDS)
    rec = db.deliverables.create({
        "episode_id": episode_id,
        "kind": kind,
        "current_version_no": 0,
        "status": "PENDING",
    })
    return object_response(serialize(rec), status=201)


@bp.get("/deliverables")
def list_deliverables():
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ProducerEng", "ShowOwner"})
    limit, offset = mw.parse_pagination()
    records = db.deliverables.all()
    episode_id = request.args.get("episode_id")
    kind = request.args.get("kind")
    status = request.args.get("status")
    if episode_id is not None:
        records = [r for r in records if r["episode_id"] == episode_id]
    if kind is not None:
        records = [r for r in records if r["kind"] == kind]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if auth.role == "ShowOwner":
        records = [r for r in records if _show_of_episode(r["episode_id"]) == auth.user_id]
    page, meta = mw.paginate(records, limit, offset)
    return array_response(serialize_list(page), meta)


@bp.get("/deliverables/<rid>")
def get_deliverable(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ProducerEng", "ShowOwner"})
    rec = get_or_404(db.deliverables, rid)
    if auth.role == "ShowOwner":
        assert_show_owner(auth, _show_of_episode(rec["episode_id"]))
    return object_response(serialize(rec))


def _show_of_episode(episode_id):
    ep = db.episodes.get(episode_id)
    return ep["show_id"] if ep else None


# ---- AssetVersion ----
@bp.post("/asset-versions")
def create_asset_version():
    auth = mw.authenticate()
    mw.require_role(auth, {"ProducerEng"})
    body = mw.get_json_body()
    deliverable_id = mw.require_string(body, "deliverable_id")
    deliverable = get_or_404(db.deliverables, deliverable_id)
    supersedes_id = body.get("supersedes_version_id")
    superseded = None
    if supersedes_id is not None:
        if not isinstance(supersedes_id, str):
            raise errors.err(errors.ERR_INVALID_REQUEST, "supersedes_version_id must be a string")
        superseded = get_or_404(db.asset_versions, supersedes_id)
    loudness = body.get("integrated_loudness_lufs")
    if loudness is not None and (isinstance(loudness, bool) or not isinstance(loudness, (int, float))):
        raise errors.err(errors.ERR_INVALID_REQUEST, "integrated_loudness_lufs must be a number")
    # referential rule (priority 21): supersedes must be ACCEPTED version of same deliverable
    if superseded is not None:
        if superseded["deliverable_id"] != deliverable_id or superseded["status"] != "ACCEPTED":
            raise errors.err(errors.ERR_INVALID_SUPERSEDE,
                             "supersedes_version_id is not an ACCEPTED version of the same deliverable")
    version_no = (superseded["version_no"] + 1) if superseded is not None else 1
    rec = db.asset_versions.create({
        "deliverable_id": deliverable_id,
        "supersedes_version_id": supersedes_id,
        "version_no": version_no,
        "integrated_loudness_lufs": float(loudness) if loudness is not None else None,
        "status": "SUBMITTED",
    })
    return object_response(serialize(rec), status=201)


@bp.get("/asset-versions")
def list_asset_versions():
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ProducerEng", "ShowOwner"})
    limit, offset = mw.parse_pagination()
    records = db.asset_versions.all()
    deliverable_id = request.args.get("deliverable_id")
    supersedes_id = request.args.get("supersedes_version_id")
    status = request.args.get("status")
    if deliverable_id is not None:
        records = [r for r in records if r["deliverable_id"] == deliverable_id]
    if supersedes_id is not None:
        records = [r for r in records if r["supersedes_version_id"] == supersedes_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, meta = mw.paginate(records, limit, offset)
    return array_response(serialize_list(page), meta)


@bp.get("/asset-versions/<rid>")
def get_asset_version(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ProducerEng", "ShowOwner"})
    rec = get_or_404(db.asset_versions, rid)
    return object_response(serialize(rec))


@bp.post("/asset-versions/<rid>/accept")
def accept_asset_version(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"ShowOwner", "ProducerEng"})
    rec = get_or_404(db.asset_versions, rid)
    deliverable = db.deliverables.get(rec["deliverable_id"])
    # state legality first (PRD §2.8)
    if rec["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Asset version is not SUBMITTED")
    # MASTER_AUDIO loudness conformance (priority 23)
    if deliverable is not None and deliverable["kind"] == "MASTER_AUDIO":
        episode = db.episodes.get(deliverable["episode_id"])
        show = db.shows.get(episode["show_id"]) if episode else None
        if show is not None and rec.get("integrated_loudness_lufs") is not None:
            diff = abs(rec["integrated_loudness_lufs"] - show["target_loudness_lufs"])
            if diff > LOUDNESS_TOLERANCE_LUFS:
                raise errors.err(errors.ERR_LOUDNESS_OUT_OF_SPEC, "Master loudness out of spec")
    rec["status"] = "ACCEPTED"
    db.asset_versions.touch(rec)
    # deliverable -> READY; current_version_no = accepted version_no (PRD §3.4)
    if deliverable is not None:
        deliverable["status"] = "READY"
        deliverable["current_version_no"] = rec["version_no"]
        db.deliverables.touch(deliverable)
    return object_response(serialize(rec))


@bp.post("/asset-versions/<rid>/reject")
def reject_asset_version(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"ShowOwner"})
    rec = get_or_404(db.asset_versions, rid)
    if rec["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Asset version is not SUBMITTED")
    rec["status"] = "REJECTED"
    db.asset_versions.touch(rec)
    return object_response(serialize(rec))
