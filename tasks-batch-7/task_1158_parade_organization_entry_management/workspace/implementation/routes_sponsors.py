"""SponsorPackage and AnnouncerScriptItem endpoints."""
from flask import Blueprint, request

from auth import guarded
from db import STORE, make_record, touch
from errors import api_err
from logic import (
    ITEM_TYPES,
    SPONSOR_TIERS,
    compute_duration_seconds,
    ensure_not_frozen,
    parade_or_404,
    script_item_or_404,
    ser_script_item,
    ser_sponsor,
    sponsor_or_404,
)
from util import body, paged, req_enum, req_int, req_num, req_str, respond_object

bp = Blueprint("sponsors", __name__)

CA = ("CommitteeAdmin",)
CA_AR = ("CommitteeAdmin", "AgencyReviewer")


def add(rule, methods, view):
    bp.add_url_rule(rule, view_func=view, methods=methods, strict_slashes=False)


# --- SponsorPackage --------------------------------------------------------------

def create_sponsor(uid, role, id):
    parade_or_404(id)
    data = body()
    sponsor_name = req_str(data, "sponsor_name")
    tier = req_enum(data, "tier", SPONSOR_TIERS)
    contribution_cents = req_int(data, "contribution_cents", minimum=1)
    rec = make_record()
    rec.update(
        {
            "parade_id": id,
            "sponsor_name": sponsor_name,
            "tier": tier,
            "contribution_cents": contribution_cents,
            "status": "PLEDGED",
        }
    )
    STORE.sponsors[rec["id"]] = rec
    return respond_object(ser_sponsor(rec), 201)


def list_sponsors(uid, role, id):
    parade_or_404(id)
    items = [s for s in STORE.sponsors.values() if s["parade_id"] == id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paged(items, ser_sponsor)


def get_sponsor(uid, role, id):
    return respond_object(ser_sponsor(sponsor_or_404(id)))


def activate_sponsor(uid, role, id):
    sponsor = sponsor_or_404(id)
    if sponsor["status"] != "PLEDGED":
        raise api_err("ERR_INVALID_STATE", "Sponsor must be in PLEDGED to activate")
    ensure_not_frozen(parade_or_404(sponsor["parade_id"]))
    sponsor["status"] = "ACTIVE"
    touch(sponsor)
    return respond_object(ser_sponsor(sponsor))


add("/parades/<id>/sponsors", ["POST"], guarded(CA)(create_sponsor))
add("/parades/<id>/sponsors", ["GET"], guarded(CA_AR)(list_sponsors))
add("/sponsors/<id>", ["GET"], guarded(CA_AR)(get_sponsor))
add("/sponsors/<id>/activate", ["POST"], guarded(CA)(activate_sponsor))


# --- AnnouncerScriptItem -----------------------------------------------------------

def create_script_item(uid, role, id):
    parade_or_404(id)
    data = body()
    item_type = req_enum(data, "item_type", ITEM_TYPES)
    sequence_index = req_int(data, "sequence_index")
    duration_minutes = req_num(data, "duration_minutes", minimum=0, exclusive_min=True)
    sponsor_id = data.get("sponsor_id")
    entry_id = data.get("entry_id")
    # Conditional references: presence is a schema concern.
    if item_type == "SPONSOR_READ" and not isinstance(sponsor_id, str):
        raise api_err("ERR_VALIDATION", "sponsor_id is required when item_type is SPONSOR_READ")
    if item_type == "ENTRY_INTRO" and not isinstance(entry_id, str):
        raise api_err("ERR_VALIDATION", "entry_id is required when item_type is ENTRY_INTRO")
    # Referential-pool rules: the reference must point at a live resource of
    # the same parade (an ACTIVE sponsor for SPONSOR_READ, an entry of the
    # parade for ENTRY_INTRO), surfaced as ERR_INVALID_STATE.
    if item_type == "SPONSOR_READ":
        sponsor = STORE.sponsors.get(sponsor_id)
        if sponsor is None or sponsor["parade_id"] != id or sponsor["status"] != "ACTIVE":
            raise api_err(
                "ERR_INVALID_STATE",
                "SPONSOR_READ must reference an ACTIVE sponsor of the same parade",
            )
    if item_type == "ENTRY_INTRO":
        entry = STORE.entries.get(entry_id)
        if entry is None or entry["parade_id"] != id:
            raise api_err(
                "ERR_INVALID_STATE", "ENTRY_INTRO must reference an entry of the same parade"
            )
    rec = make_record()
    rec.update(
        {
            "parade_id": id,
            "item_type": item_type,
            "sponsor_id": sponsor_id if isinstance(sponsor_id, str) else None,
            "entry_id": entry_id if isinstance(entry_id, str) else None,
            "sequence_index": sequence_index,
            "duration_minutes": duration_minutes,
            "duration_seconds": compute_duration_seconds(duration_minutes),
            "status": "DRAFT",
        }
    )
    STORE.script_items[rec["id"]] = rec
    return respond_object(ser_script_item(rec), 201)


def list_parade_script_items(uid, role, id):
    parade_or_404(id)
    items = [it for it in STORE.script_items.values() if it["parade_id"] == id]
    status = request.args.get("status")
    item_type = request.args.get("item_type")
    if status is not None:
        items = [it for it in items if it["status"] == status]
    if item_type is not None:
        items = [it for it in items if it["item_type"] == item_type]
    return paged(items, ser_script_item)


def list_script_items(uid, role):
    items = list(STORE.script_items.values())
    parade_id = request.args.get("parade_id")
    sponsor_id = request.args.get("sponsor_id")
    entry_id = request.args.get("entry_id")
    status = request.args.get("status")
    if parade_id is not None:
        items = [it for it in items if it["parade_id"] == parade_id]
    if sponsor_id is not None:
        items = [it for it in items if it.get("sponsor_id") == sponsor_id]
    if entry_id is not None:
        items = [it for it in items if it.get("entry_id") == entry_id]
    if status is not None:
        items = [it for it in items if it["status"] == status]
    return paged(items, ser_script_item)


def get_script_item(uid, role, id):
    return respond_object(ser_script_item(script_item_or_404(id)))


def approve_script_item(uid, role, id):
    item = script_item_or_404(id)
    if item["status"] != "DRAFT":
        raise api_err("ERR_INVALID_STATE", "Script item must be in DRAFT to approve")
    ensure_not_frozen(parade_or_404(item["parade_id"]))
    item["status"] = "APPROVED"
    touch(item)
    return respond_object(ser_script_item(item))


def reopen_script_item(uid, role, id):
    item = script_item_or_404(id)
    if item["status"] != "APPROVED":
        raise api_err("ERR_INVALID_STATE", "Script item must be in APPROVED to reopen")
    parade = parade_or_404(item["parade_id"])
    if parade["status"] in ("LINEUP_PUBLISHED", "COMPLETED"):
        raise api_err("ERR_INVALID_STATE", "Reopening is refused once the lineup is published")
    item["status"] = "DRAFT"
    touch(item)
    return respond_object(ser_script_item(item))


def cancel_script_item(uid, role, id):
    item = script_item_or_404(id)
    if item["status"] not in ("DRAFT", "APPROVED"):
        raise api_err("ERR_INVALID_STATE", "Script item must be in DRAFT or APPROVED to cancel")
    item["status"] = "CANCELLED"
    touch(item)
    return respond_object(ser_script_item(item))


add("/parades/<id>/script-items", ["POST"], guarded(CA)(create_script_item))
add("/parades/<id>/script-items", ["GET"], guarded(CA_AR)(list_parade_script_items))
add("/script-items", ["GET"], guarded(CA_AR)(list_script_items))
add("/script-items/<id>", ["GET"], guarded(CA_AR)(get_script_item))
add("/script-items/<id>/approve", ["POST"], guarded(CA)(approve_script_item))
add("/script-items/<id>/reopen", ["POST"], guarded(CA)(reopen_script_item))
add("/script-items/<id>/cancel", ["POST"], guarded(CA)(cancel_script_item))
