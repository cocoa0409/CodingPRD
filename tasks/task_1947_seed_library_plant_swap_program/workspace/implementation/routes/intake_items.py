"""SwapIntakeItem endpoints: submit/list/get/screen/withdraw."""

from flask import Blueprint, request
from db import db
from middleware import require_roles
from validate import get_body, req_string, opt_enum, parse_pagination
from response import success_object, success_list
from errors import (not_found, invalid_state, already_terminal, invalid_enum,
                    invalid_request, self_service_forbidden, ApiError)
from services.core import (per_item_credit, earned_at_event, recompute_member,
                           MAX_CREDITS_PER_MEMBER_EVENT)

bp = Blueprint("intake_items", __name__)

ITEM_TYPES = {"SEED_PACKET", "PLANT_START", "CUTTING"}
CONDITIONS = {"EXCELLENT", "GOOD", "FAIR"}
ITEM_STATUSES = {"SUBMITTED", "ACCEPTED", "REJECTED", "WITHDRAWN",
                 "RETURNED_TO_OWNER", "SWAPPED"}
ITEM_TERMINAL = {"REJECTED", "WITHDRAWN", "RETURNED_TO_OWNER", "SWAPPED"}
EVENT_TERMINAL = {"COMPLETED", "CANCELLED"}


def item_view(item):
    return {k: v for k, v in item.items() if not k.startswith("_")}


def get_item_or_404(item_id):
    item = db.intake_items.get(item_id)
    if item is None:
        raise not_found("Intake item not found.")
    return item


@bp.post("/api/swap-events/<event_id>/intake-items")
def submit_intake_item(event_id):
    user_id, role = require_roles("Member", "ProgramAdmin")
    ev = db.events.get(event_id)
    if ev is None:
        raise not_found("Swap event not found.")
    body = get_body()
    member_id = req_string(body, "member_id")
    variety_id = req_string(body, "variety_id")
    item_type = opt_enum(body, "item_type", ITEM_TYPES)
    if item_type is None:
        raise invalid_request("Missing required field: item_type")
    condition = opt_enum(body, "condition", CONDITIONS)
    if condition is None:
        raise invalid_request("Missing required field: condition")
    # band 5: FK existence
    member = db.members.get(member_id)
    if member is None:
        raise not_found("member_id does not resolve to an existing member.")
    variety = db.varieties.get(variety_id)
    if variety is None:
        raise not_found("variety_id does not resolve to an existing variety.")
    # band 6.3 (non-terminal only): event INTAKE_OPEN
    if ev["status"] not in EVENT_TERMINAL and ev["status"] != "INTAKE_OPEN":
        raise ApiError("ERR_EVENT_NOT_INTAKE_OPEN", 409,
                       "Event is not INTAKE_OPEN.")
    # band 6 (generic): retired variety blocks intake items
    if variety["status"] == "RETIRED":
        raise invalid_state("Variety is RETIRED; new intake items are blocked.")
    # band 7: invasive
    if variety["invasive_flag"]:
        raise ApiError("ERR_INVASIVE_SPECIES_BLOCKED", 422,
                       "Variety is flagged invasive.")
    # band 7.1: regional appropriateness vs event site's zone
    site = db.sites.get(ev["site_id"])
    if site is not None and site["region_zone"] not in variety["approved_zones"]:
        raise ApiError("ERR_REGION_NOT_APPROVED", 422,
                       "Variety is not approved for the event site's region zone.")
    # band 8.1: duplicate intake item (non-terminal twin)
    for item in db.intake_items.values():
        if (item["event_id"] == ev["id"] and item["member_id"] == member_id
                and item["variety_id"] == variety_id
                and item["item_type"] == item_type
                and item["status"] in ("SUBMITTED", "ACCEPTED")):
            raise ApiError("ERR_DUPLICATE_INTAKE_ITEM", 409,
                           "A non-terminal twin intake item exists.")
    # compute per-item credit (per-item rounding pinned)
    credit_value = per_item_credit(item_type, condition, variety["rarity_flag"])
    # band 11.2: event credit cap (single item per call -> submission_total = credit_value)
    if earned_at_event(member_id, ev["id"]) + credit_value > MAX_CREDITS_PER_MEMBER_EVENT:
        raise ApiError("ERR_EVENT_CREDIT_CAP_EXCEEDED", 422,
                       "Submission would exceed the per-member event credit cap.")
    # band 12: ownership
    if role == "Member" and member_id != user_id:
        raise self_service_forbidden("Member may submit only its own intake items.")
    # band 14: terminal lockdown (terminal event rejects intake submission)
    if ev["status"] in EVENT_TERMINAL:
        raise already_terminal("Swap event is in a terminal state.")
    item = {
        "event_id": ev["id"],
        "member_id": member_id,
        "variety_id": variety_id,
        "item_type": item_type,
        "condition": condition,
        "credit_value": credit_value,
        "status": "SUBMITTED",
    }
    db.stamp_new(item)
    db.intake_items[item["id"]] = item
    return success_object(item_view(item), 201)


@bp.get("/api/intake-items")
def list_intake_items():
    require_roles("ProgramAdmin", "Member", "Volunteer")
    limit, offset = parse_pagination()
    event_id = request.args.get("event_id")
    member_id = request.args.get("member_id")
    variety_id = request.args.get("variety_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in ITEM_STATUSES:
        raise invalid_enum("status filter not in declared set.")
    items = sorted(db.intake_items.values(), key=lambda i: i["_seq"])
    if event_id:
        items = [i for i in items if i["event_id"] == event_id]
    if member_id:
        items = [i for i in items if i["member_id"] == member_id]
    if variety_id:
        items = [i for i in items if i["variety_id"] == variety_id]
    if status_f:
        items = [i for i in items if i["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([item_view(i) for i in page], limit, offset, total)


@bp.get("/api/intake-items/<item_id>")
def get_intake_item(item_id):
    require_roles("ProgramAdmin", "Member", "Volunteer")
    item = get_item_or_404(item_id)
    return success_object(item_view(item))


@bp.post("/api/intake-items/<item_id>/screen")
def screen_item(item_id):
    require_roles("ProgramAdmin")
    item = get_item_or_404(item_id)
    body = get_body()
    outcome = opt_enum(body, "outcome", {"ACCEPT", "REJECT"})
    if outcome is None:
        raise invalid_request("Missing required field: outcome")
    if item["status"] in ITEM_TERMINAL:
        raise already_terminal("Intake item is in a terminal state.")
    if item["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED item can be screened.")
    ev = db.events.get(item["event_id"])
    if outcome == "ACCEPT":
        if ev is None or ev["status"] != "INTAKE_OPEN":
            raise invalid_state("Accept requires the event to be INTAKE_OPEN.")
        item["status"] = "ACCEPTED"
        db.touch(item)
        # pay credits
        entry = {
            "member_id": item["member_id"],
            "event_id": item["event_id"],
            "entry_type": "EARNED",
            "credits": item["credit_value"],
            "note": f"intake item {item['id']} accepted",
        }
        db.stamp_ledger(entry)
        db.credit_entries[entry["id"]] = entry
        member = db.members.get(item["member_id"])
        if member is not None:
            recompute_member(member)
            db.touch(member)
    else:  # REJECT
        if ev is None or ev["status"] not in ("INTAKE_OPEN", "INTAKE_CLOSED"):
            raise invalid_state(
                "Reject requires the event to be INTAKE_OPEN or INTAKE_CLOSED.")
        item["status"] = "REJECTED"
        db.touch(item)
    return success_object(item_view(item))


@bp.post("/api/intake-items/<item_id>/withdraw")
def withdraw_item(item_id):
    user_id, role = require_roles("Member", "ProgramAdmin")
    item = get_item_or_404(item_id)
    # band 6 (non-terminal only): must be SUBMITTED
    if item["status"] not in ITEM_TERMINAL and item["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED item can be withdrawn.")
    # band 12: ownership (before terminal lockdown per band ordering)
    if role == "Member" and item["member_id"] != user_id:
        raise self_service_forbidden("Member may withdraw only its own items.")
    # band 14: terminal lockdown
    if item["status"] in ITEM_TERMINAL:
        raise already_terminal("Intake item is in a terminal state.")
    item["status"] = "WITHDRAWN"
    db.touch(item)
    return success_object(item_view(item))


# ---------------- CreditEntry (append-only ledger) ----------------

@bp.get("/api/credit-entries")
def list_credit_entries():
    require_roles("ProgramAdmin", "Member", "Volunteer")
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    event_id = request.args.get("event_id")
    entry_type = request.args.get("entry_type")
    if entry_type is not None and entry_type not in (
            "EARNED", "REDEEMED", "EXPIRED", "REVOKED"):
        raise invalid_enum("entry_type filter not in declared set.")
    items = sorted(db.credit_entries.values(), key=lambda e: e["_seq"])
    if member_id:
        items = [e for e in items if e["member_id"] == member_id]
    if event_id:
        items = [e for e in items if e["event_id"] == event_id]
    if entry_type:
        items = [e for e in items if e["entry_type"] == entry_type]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_entry_view(e) for e in page], limit, offset, total)


def _entry_view(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


@bp.get("/api/credit-entries/<entry_id>")
def get_credit_entry(entry_id):
    require_roles("ProgramAdmin", "Member", "Volunteer")
    e = db.credit_entries.get(entry_id)
    if e is None:
        raise not_found("Credit entry not found.")
    return success_object(_entry_view(e))
