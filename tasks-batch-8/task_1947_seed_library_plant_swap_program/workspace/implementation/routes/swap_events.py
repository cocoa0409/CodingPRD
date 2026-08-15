"""SwapEvent endpoints + credit redemption + event lifecycle cascades."""

from flask import Blueprint, request
from db import db, iso_z
from middleware import require_roles
from validate import (get_body, req_string, opt_string, req_datetime,
                      opt_datetime, req_int, parse_pagination)
from response import success_object, success_list
from errors import (not_found, invalid_state, already_terminal, invalid_enum,
                    invalid_request, self_service_forbidden, ApiError)
from services.core import (event_buffered_overlap, recompute_member,
                           earned_at_event, redeemed_at_event,
                           MAX_CREDITS_PER_MEMBER_EVENT)

bp = Blueprint("swap_events", __name__)

EVENT_STATUSES = {"DRAFT", "SCHEDULED", "INTAKE_OPEN", "INTAKE_CLOSED", "COMPLETED", "CANCELLED"}
EVENT_TERMINAL = {"COMPLETED", "CANCELLED"}


def event_view(ev):
    out = {k: v for k, v in ev.items() if not k.startswith("_")}
    out["start_at"] = iso_z(ev["_start_dt"])
    out["end_at"] = iso_z(ev["_end_dt"])
    return out


def get_event_or_404(event_id):
    ev = db.events.get(event_id)
    if ev is None:
        raise not_found("Swap event not found.")
    return ev


def _check_overlap(ev_site_id, start_dt, end_dt, exclude_id=None):
    if event_buffered_overlap(ev_site_id, start_dt, end_dt, exclude_id):
        raise ApiError("ERR_EVENT_WINDOW_OVERLAP", 409,
                       "Buffered event window intersects another event at this site.")


@bp.post("/api/swap-events")
def create_event():
    require_roles("ProgramAdmin")
    body = get_body()
    site_id = req_string(body, "site_id")
    title = req_string(body, "title")
    start_dt = req_datetime(body, "start_at")
    end_dt = req_datetime(body, "end_at")
    if end_dt <= start_dt:
        raise invalid_request("end_at must be strictly after start_at.")
    # band 5: FK existence
    if site_id not in db.sites:
        raise not_found("site_id does not resolve to an existing site.")
    # band 9: buffered overlap at creation
    _check_overlap(site_id, start_dt, end_dt)
    ev = {
        "site_id": site_id,
        "title": title,
        "status": "DRAFT",
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    }
    db.stamp_new(ev)
    db.events[ev["id"]] = ev
    return success_object(event_view(ev), 201)


@bp.get("/api/swap-events")
def list_events():
    require_roles("ProgramAdmin", "Member", "Volunteer")
    limit, offset = parse_pagination()
    site_id = request.args.get("site_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in EVENT_STATUSES:
        raise invalid_enum("status filter not in declared set.")
    items = sorted(db.events.values(), key=lambda e: e["_seq"])
    if site_id:
        items = [e for e in items if e["site_id"] == site_id]
    if status_f:
        items = [e for e in items if e["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([event_view(e) for e in page], limit, offset, total)


@bp.get("/api/swap-events/<event_id>")
def get_event(event_id):
    require_roles("ProgramAdmin", "Member", "Volunteer")
    ev = get_event_or_404(event_id)
    return success_object(event_view(ev))


@bp.patch("/api/swap-events/<event_id>")
def patch_event(event_id):
    require_roles("ProgramAdmin")
    ev = get_event_or_404(event_id)
    body = get_body()
    expected = req_int(body, "expected_swap_event_version")
    title = opt_string(body, "title")
    start_dt = opt_datetime(body, "start_at", default=None)
    end_dt = opt_datetime(body, "end_at", default=None)
    new_start = start_dt if start_dt is not None else ev["_start_dt"]
    new_end = end_dt if end_dt is not None else ev["_end_dt"]
    if end_dt is not None or start_dt is not None:
        if new_end <= new_start:
            raise invalid_request("end_at must be strictly after start_at.")
    # band 6 (non-terminal only): DRAFT or SCHEDULED only
    if ev["status"] not in EVENT_TERMINAL and ev["status"] not in ("DRAFT", "SCHEDULED"):
        raise invalid_state("Only DRAFT or SCHEDULED events may be edited.")
    # band 9: overlap check when times change
    if start_dt is not None or end_dt is not None:
        _check_overlap(ev["site_id"], new_start, new_end, exclude_id=ev["id"])
    # band 13: OCC
    if expected != ev["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_swap_event_version does not match current version.")
    # band 14: terminal lockdown
    if ev["status"] in EVENT_TERMINAL:
        raise already_terminal("Swap event is in a terminal state.")
    if title is not None:
        ev["title"] = title
    ev["_start_dt"] = new_start
    ev["_end_dt"] = new_end
    db.touch(ev)
    return success_object(event_view(ev))


@bp.post("/api/swap-events/<event_id>/publish")
def publish_event(event_id):
    require_roles("ProgramAdmin")
    ev = get_event_or_404(event_id)
    if ev["status"] in EVENT_TERMINAL:
        raise already_terminal("Swap event is in a terminal state.")
    if ev["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT event can be published.")
    _check_overlap(ev["site_id"], ev["_start_dt"], ev["_end_dt"], exclude_id=ev["id"])
    ev["status"] = "SCHEDULED"
    db.touch(ev)
    return success_object(event_view(ev))


@bp.post("/api/swap-events/<event_id>/open-intake")
def open_intake(event_id):
    require_roles("ProgramAdmin")
    ev = get_event_or_404(event_id)
    if ev["status"] in EVENT_TERMINAL:
        raise already_terminal("Swap event is in a terminal state.")
    if ev["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED event can open intake.")
    site = db.sites.get(ev["site_id"])
    if site is None or site["status"] != "ACTIVE":
        raise invalid_state("Hosting site must be ACTIVE to open intake.")
    ev["status"] = "INTAKE_OPEN"
    db.touch(ev)
    return success_object(event_view(ev))


@bp.post("/api/swap-events/<event_id>/close-intake")
def close_intake(event_id):
    require_roles("ProgramAdmin")
    ev = get_event_or_404(event_id)
    if ev["status"] in EVENT_TERMINAL:
        raise already_terminal("Swap event is in a terminal state.")
    if ev["status"] != "INTAKE_OPEN":
        raise invalid_state("Only an INTAKE_OPEN event can close intake.")
    # unscreened SUBMITTED items auto-rejected
    for item in db.intake_items.values():
        if item["event_id"] == ev["id"] and item["status"] == "SUBMITTED":
            item["status"] = "REJECTED"
            db.touch(item)
    ev["status"] = "INTAKE_CLOSED"
    db.touch(ev)
    return success_object(event_view(ev))


@bp.post("/api/swap-events/<event_id>/complete")
def complete_event(event_id):
    require_roles("ProgramAdmin")
    ev = get_event_or_404(event_id)
    if ev["status"] in EVENT_TERMINAL:
        raise already_terminal("Swap event is in a terminal state.")
    if ev["status"] != "INTAKE_CLOSED":
        raise invalid_state("Only an INTAKE_CLOSED event can be completed.")
    # ACCEPTED items -> SWAPPED
    for item in db.intake_items.values():
        if item["event_id"] == ev["id"] and item["status"] == "ACCEPTED":
            item["status"] = "SWAPPED"
            db.touch(item)
    # credit expiry per member
    member_ids = {e["member_id"] for e in db.credit_entries.values()
                  if e["event_id"] == ev["id"] and e["entry_type"] == "EARNED"}
    for mid in sorted(member_ids):
        earned = earned_at_event(mid, ev["id"])
        redeemed = redeemed_at_event(mid, ev["id"])
        expired_inc = max(0, earned - redeemed)
        if expired_inc > 0:
            entry = {
                "member_id": mid,
                "event_id": ev["id"],
                "entry_type": "EXPIRED",
                "credits": expired_inc,
                "note": f"event completion {ev['id']}",
            }
            db.stamp_ledger(entry)
            db.credit_entries[entry["id"]] = entry
            member = db.members.get(mid)
            if member is not None:
                recompute_member(member)
                db.touch(member)
    ev["status"] = "COMPLETED"
    db.touch(ev)
    return success_object(event_view(ev))


@bp.post("/api/swap-events/<event_id>/cancel")
def cancel_event(event_id):
    require_roles("ProgramAdmin")
    ev = get_event_or_404(event_id)
    if ev["status"] in EVENT_TERMINAL:
        raise already_terminal("Swap event is in a terminal state.")
    if ev["status"] not in ("SCHEDULED", "INTAKE_OPEN"):
        raise invalid_state("Only a SCHEDULED or INTAKE_OPEN event can be cancelled.")
    # band 10.1: cancellable only if zero REDEEMED entries for the event
    for e in db.credit_entries.values():
        if e["event_id"] == ev["id"] and e["entry_type"] == "REDEEMED":
            raise ApiError("ERR_EVENT_NOT_CANCELLABLE", 409,
                           "Event has redeemed credits; cannot cancel.")
    # hop 1: SUBMITTED/ACCEPTED items -> RETURNED_TO_OWNER
    for item in db.intake_items.values():
        if item["event_id"] == ev["id"] and item["status"] in ("SUBMITTED", "ACCEPTED"):
            item["status"] = "RETURNED_TO_OWNER"
            db.touch(item)
    # hop 2: REVOKED entries per member equal to earned_at_event
    member_ids = {e["member_id"] for e in db.credit_entries.values()
                  if e["event_id"] == ev["id"] and e["entry_type"] == "EARNED"}
    for mid in sorted(member_ids):
        earned = earned_at_event(mid, ev["id"])
        if earned > 0:
            entry = {
                "member_id": mid,
                "event_id": ev["id"],
                "entry_type": "REVOKED",
                "credits": earned,
                "note": f"event cancellation {ev['id']}",
            }
            db.stamp_ledger(entry)
            db.credit_entries[entry["id"]] = entry
            member = db.members.get(mid)
            if member is not None:
                recompute_member(member)
                db.touch(member)
    ev["status"] = "CANCELLED"
    db.touch(ev)
    return success_object(event_view(ev))


@bp.post("/api/swap-events/<event_id>/redeem-credits")
def redeem_credits(event_id):
    user_id, role = require_roles("Member", "ProgramAdmin")
    ev = get_event_or_404(event_id)
    body = get_body()
    member_id = req_string(body, "member_id")
    credits = req_int(body, "credits", min_v=1)
    # band 5: FK
    member = db.members.get(member_id)
    if member is None:
        raise not_found("member_id does not resolve to an existing member.")
    # band 6.3 (non-terminal only): event must be INTAKE_OPEN
    if ev["status"] not in EVENT_TERMINAL and ev["status"] != "INTAKE_OPEN":
        raise ApiError("ERR_EVENT_NOT_INTAKE_OPEN", 409,
                       "Event is not INTAKE_OPEN.")
    # band 11.3: redemption ceilings
    recompute_member(member)
    earned = earned_at_event(member_id, ev["id"])
    redeemed = redeemed_at_event(member_id, ev["id"])
    event_remainder = earned - redeemed
    if credits > member["credits_balance"] or credits > event_remainder:
        raise ApiError("ERR_INSUFFICIENT_CREDITS", 422,
                       "Redemption exceeds balance or event-scoped remainder.")
    # band 12: ownership
    if role == "Member" and member_id != user_id:
        raise self_service_forbidden("Member may redeem only its own credits.")
    # band 14: terminal lockdown
    if ev["status"] in EVENT_TERMINAL:
        raise already_terminal("Swap event is in a terminal state.")
    entry = {
        "member_id": member_id,
        "event_id": ev["id"],
        "entry_type": "REDEEMED",
        "credits": credits,
        "note": f"redemption at event {ev['id']}",
    }
    db.stamp_ledger(entry)
    db.credit_entries[entry["id"]] = entry
    recompute_member(member)
    db.touch(member)
    return success_object({
        "member_id": member_id,
        "credits_redeemed": credits,
        "credits_balance": member["credits_balance"],
    })
