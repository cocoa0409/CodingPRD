"""ArchiveItem endpoints (PRD §3.9): cold-store, restore, rearchive, purge,
legal hold."""
from datetime import timedelta
from flask import Blueprint, request

import serialize
from auth import ALL_ROLES, body, guarded
from db import DB, now, touch
from errors import (
    ApiError,
    ERR_ARCHIVE_LEGAL_HOLD,
    ERR_COMPLAINTS_STILL_OPEN,
    ERR_RETENTION_NOT_ELAPSED,
    invalid_transition,
    not_found,
)
from respond import list_response, ok_object
from services import workflow
from util import req_bool

bp = Blueprint("archive_items", __name__)


def get_item(item_id):
    i = DB.archive_items.get(item_id)
    if i is None:
        raise not_found("Archive item not found")
    return i


@bp.get("/caption-ad/archive-items")
@guarded(set(ALL_ROLES))
def list_archive_items(_user_id, _role):
    records = list(DB.archive_items.values())
    for param in ("caption_track_id", "audio_description_track_id", "live_event_id", "archive_status"):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[param] == v]
    return list_response(records, serialize.archive_item)


@bp.get("/caption-ad/archive-items/<archiveItemId>")
@guarded(set(ALL_ROLES))
def get_one_archive_item(archiveItemId, _user_id, _role):
    return ok_object(serialize.archive_item(get_item(archiveItemId)))


@bp.post("/caption-ad/archive-items/<archiveItemId>/cold-store")
@guarded({"OperationsManager"})
def cold_store(archiveItemId, _user_id, _role):
    i = get_item(archiveItemId)
    if i["archive_status"] != "ACTIVE_HOLD" or i["dispute_freeze"]:
        raise invalid_transition("Only an unfrozen ACTIVE_HOLD item can move to cold storage")
    t = now()
    # Pin the retention clock once: archived_at now, purge_after computed once
    # from the retention class and never recomputed afterward.
    i["archive_status"] = "COLD_STORE"
    i["archived_at"] = t
    i["purge_after"] = t + timedelta(days=workflow.RETENTION_DAYS[i["retention_class"]])
    touch(i)
    return ok_object(serialize.archive_item(i))


@bp.post("/caption-ad/archive-items/<archiveItemId>/request-restore")
@guarded({"OperationsManager"})
def request_restore(archiveItemId, _user_id, _role):
    i = get_item(archiveItemId)
    if i["archive_status"] != "COLD_STORE":
        raise invalid_transition("Only a COLD_STORE item can request restore")
    i["archive_status"] = "RESTORE_PENDING"
    touch(i)
    return ok_object(serialize.archive_item(i))


@bp.post("/caption-ad/archive-items/<archiveItemId>/complete-restore")
@guarded({"OperationsManager"})
def complete_restore(archiveItemId, _user_id, _role):
    i = get_item(archiveItemId)
    if i["archive_status"] != "RESTORE_PENDING":
        raise invalid_transition("Only a RESTORE_PENDING item can complete restore")
    i["archive_status"] = "RESTORED_HOT"
    touch(i)
    return ok_object(serialize.archive_item(i))


@bp.post("/caption-ad/archive-items/<archiveItemId>/rearchive")
@guarded({"OperationsManager"})
def rearchive(archiveItemId, _user_id, _role):
    i = get_item(archiveItemId)
    if i["archive_status"] != "RESTORED_HOT":
        raise invalid_transition("Only a RESTORED_HOT item can be rearchived")
    # The retention clock keeps the original archived_at; purge_after is NOT
    # recomputed.
    i["archive_status"] = "COLD_STORE"
    touch(i)
    return ok_object(serialize.archive_item(i))


@bp.post("/caption-ad/archive-items/<archiveItemId>/purge")
@guarded({"OperationsManager"})
def purge(archiveItemId, _user_id, _role):
    i = get_item(archiveItemId)
    if i["archive_status"] != "COLD_STORE":
        raise invalid_transition("Only a COLD_STORE item can be purged")
    t = now()
    # Gates evaluated in prose order: retention elapsed (inclusive), then
    # legal hold, then dispute freeze / open complaints.
    if t < i["purge_after"]:
        raise ApiError(ERR_RETENTION_NOT_ELAPSED, 409, "Purge attempted before purge_after")
    if i["legal_hold"]:
        raise ApiError(ERR_ARCHIVE_LEGAL_HOLD, 409, "Purge attempted while legal_hold is true")
    if i["dispute_freeze"] or workflow.has_open_complaint(
        caption_track_id=i["caption_track_id"],
        ad_track_id=i["audio_description_track_id"],
        live_event_id=i["live_event_id"],
    ):
        raise ApiError(ERR_COMPLAINTS_STILL_OPEN, 409, "Non-terminal complaints reference the subject")
    i["archive_status"] = "PURGED"
    touch(i)
    return ok_object(serialize.archive_item(i))


@bp.post("/caption-ad/archive-items/<archiveItemId>/set-legal-hold")
@guarded({"OperationsManager"})
def set_legal_hold(archiveItemId, _user_id, _role):
    i = get_item(archiveItemId)
    i["legal_hold"] = req_bool(body(), "legal_hold")
    touch(i)
    return ok_object(serialize.archive_item(i))
