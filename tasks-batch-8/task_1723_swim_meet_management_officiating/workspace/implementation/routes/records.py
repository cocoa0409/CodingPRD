"""MeetRecord endpoints (challenge lifecycle; standing creation lives in events.py)."""

from flask import Blueprint, request

from db import STORE
from errors import ERR_RECORD_INVALID_STATE, ERR_RECORD_NOT_FOUND, raise_err
from middleware import ctx, require_role
from response import ok_list, ok_object
from services import bump, get_or_404, paginate, pub_record, sort_created

bp = Blueprint("records", __name__)


@bp.get("/records/<rid>")
def get_record(rid):
    ctx()
    rec = get_or_404("records", rid, ERR_RECORD_NOT_FOUND)
    return ok_object(pub_record(rec))


@bp.get("/records")
def list_records():
    ctx()
    items = list(STORE["records"].values())
    event_id = request.args.get("event_id")
    challenger_entry_id = request.args.get("challenger_entry_id")
    if event_id is not None:
        items = [r for r in items if r["event_id"] == event_id]
    if challenger_entry_id is not None:
        items = [r for r in items if r["challenger_entry_id"] == challenger_entry_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([pub_record(r) for r in page], limit, offset, total)


@bp.post("/records/<rid>/verify")
def verify_record(rid):
    _, role = ctx()
    require_role(role, "RecordsOfficer")
    rec = get_or_404("records", rid, ERR_RECORD_NOT_FOUND)
    if rec["status"] != "PENDING_VERIFICATION":
        raise_err(ERR_RECORD_INVALID_STATE, "verify requires status PENDING_VERIFICATION")
    rec["status"] = "SUBMITTED"
    bump(rec)
    return ok_object(pub_record(rec))


@bp.post("/records/<rid>/ratify")
def ratify_record(rid):
    _, role = ctx()
    require_role(role, "RecordsOfficer")
    rec = get_or_404("records", rid, ERR_RECORD_NOT_FOUND)
    if rec["status"] != "SUBMITTED":
        raise_err(ERR_RECORD_INVALID_STATE, "ratify requires status SUBMITTED")
    rec["status"] = "CURRENT"
    bump(rec)
    for other in STORE["records"].values():
        if other["id"] == rec["id"] or other["event_id"] != rec["event_id"]:
            continue
        if other["status"] == "CURRENT":
            other["status"] = "SUPERSEDED"
            bump(other)
        elif other["status"] in ("PENDING_VERIFICATION", "SUBMITTED") and (
            other["record_time_cs"] > rec["record_time_cs"]
        ):
            # Slower still-pending challenges are auto-rejected.
            other["status"] = "REJECTED"
            bump(other)
    return ok_object(pub_record(rec))


@bp.post("/records/<rid>/reject")
def reject_record(rid):
    _, role = ctx()
    require_role(role, "RecordsOfficer")
    rec = get_or_404("records", rid, ERR_RECORD_NOT_FOUND)
    if rec["status"] not in ("PENDING_VERIFICATION", "SUBMITTED"):
        raise_err(
            ERR_RECORD_INVALID_STATE,
            "reject requires status PENDING_VERIFICATION or SUBMITTED",
        )
    rec["status"] = "REJECTED"
    bump(rec)
    return ok_object(pub_record(rec))
