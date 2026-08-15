"""Checkout endpoints: create/return/verify/dispute/resolve."""

from datetime import timedelta
from flask import Blueprint, request
from db import db, iso_z
from middleware import require_roles
from validate import get_body, req_string, opt_string, opt_enum, parse_pagination
from response import success_object, success_list
from errors import (not_found, invalid_state, already_terminal, invalid_enum,
                    invalid_request, self_service_forbidden, ApiError)
from services.core import (recompute_member, LOAN_DAYS)

bp = Blueprint("checkouts", __name__)

CHECKOUT_STATUSES = {"ACTIVE", "OVERDUE", "RETURNED", "DISPUTED", "VERIFIED", "WRITTEN_OFF"}
CHECKOUT_TERMINAL = {"VERIFIED", "WRITTEN_OFF"}


def checkout_view(c):
    out = {k: v for k, v in c.items() if not k.startswith("_")}
    return out


def get_checkout_or_404(checkout_id):
    c = db.checkouts.get(checkout_id)
    if c is None:
        raise not_found("Checkout not found.")
    return c


@bp.post("/api/checkouts")
def create_checkout():
    user_id, role = require_roles("Member", "ProgramAdmin")
    body = get_body()
    member_id = req_string(body, "member_id")
    packet_id = req_string(body, "packet_id")
    # band 5: body FK existence
    member = db.members.get(member_id)
    if member is None:
        raise not_found("member_id does not resolve to an existing member.")
    packet = db.packets.get(packet_id)
    if packet is None:
        raise not_found("packet_id does not resolve to an existing packet.")
    # band 6: packet must be AVAILABLE
    if packet["status"] != "AVAILABLE":
        raise ApiError("ERR_PACKET_NOT_AVAILABLE", 409,
                       "Checkout targets a packet not in AVAILABLE.")
    # band 6.1: member ACTIVE for borrowing
    recompute_member(member)
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_SUSPENDED", 409,
                       "Borrowing member is SUSPENDED or CLOSED.")
    # band 6.2: packet's lot must be ACTIVE
    lot = db.lots.get(packet["lot_id"])
    if lot is None or lot["status"] != "ACTIVE":
        raise ApiError("ERR_LOT_NOT_ACTIVE", 409,
                       "Packet's lot is not ACTIVE.")
    # variety retired blocks checkout under generic state rule
    variety = db.varieties.get(lot["variety_id"])
    if variety is not None and variety["status"] == "RETIRED":
        raise invalid_state("Variety is RETIRED; new checkouts are blocked.")
    # band 7: invasive screen
    if variety is not None and variety["invasive_flag"]:
        raise ApiError("ERR_INVASIVE_SPECIES_BLOCKED", 422,
                       "Variety is flagged invasive.")
    # band 7.1: regional appropriateness vs member home site zone
    home_site = db.sites.get(member["home_site_id"])
    if variety is not None and home_site is not None:
        if home_site["region_zone"] not in variety["approved_zones"]:
            raise ApiError("ERR_REGION_NOT_APPROVED", 422,
                           "Variety is not approved for the member's home region zone.")
    # band 11: borrow limit (evaluated before the new checkout is counted)
    if member["active_checkout_count"] >= member["effective_borrow_limit"]:
        raise ApiError("ERR_BORROW_LIMIT_EXCEEDED", 422,
                       "Member is at the effective borrow limit.")
    # band 12: ownership
    if role == "Member" and member_id != user_id:
        raise self_service_forbidden("Member may borrow only for itself.")
    # create
    now = db.now()
    due = now + timedelta(days=LOAN_DAYS)
    checkout = {
        "member_id": member_id,
        "packet_id": packet_id,
        "checked_out_at": iso_z(now),
        "due_at": iso_z(due),
        "returned_at": None,
        "recall_required": False,
        "status": "ACTIVE",
        "_due_at_dt": due,
        "_was_overdue": False,
    }
    db.stamp_new(checkout)
    db.checkouts[checkout["id"]] = checkout
    packet["status"] = "CHECKED_OUT"
    db.touch(packet)
    recompute_member(member)
    db.touch(member)
    return success_object(checkout_view(checkout), 201)


@bp.get("/api/checkouts")
def list_checkouts():
    require_roles("ProgramAdmin", "Member", "Volunteer")
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    packet_id = request.args.get("packet_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in CHECKOUT_STATUSES:
        raise invalid_enum("status filter not in declared set.")
    items = sorted(db.checkouts.values(), key=lambda c: c["_seq"])
    if member_id:
        items = [c for c in items if c["member_id"] == member_id]
    if packet_id:
        items = [c for c in items if c["packet_id"] == packet_id]
    if status_f:
        items = [c for c in items if c["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([checkout_view(c) for c in page], limit, offset, total)


@bp.get("/api/checkouts/<checkout_id>")
def get_checkout(checkout_id):
    require_roles("ProgramAdmin", "Member", "Volunteer")
    c = get_checkout_or_404(checkout_id)
    return success_object(checkout_view(c))


@bp.post("/api/checkouts/<checkout_id>/return")
def return_checkout(checkout_id):
    user_id, role = require_roles("Member", "ProgramAdmin")
    c = get_checkout_or_404(checkout_id)
    # band 6 (non-terminal only): returnable state
    if c["status"] not in CHECKOUT_TERMINAL and c["status"] not in ("ACTIVE", "OVERDUE"):
        raise invalid_state("Checkout is not in a returnable state.")
    # band 12: ownership (before terminal lockdown per band ordering)
    if role == "Member" and c["member_id"] != user_id:
        raise self_service_forbidden("Member may return only its own checkouts.")
    # band 14: terminal lockdown
    if c["status"] in CHECKOUT_TERMINAL:
        raise already_terminal("Checkout is in a terminal state.")
    packet = db.packets.get(c["packet_id"])
    was_overdue = c["status"] == "OVERDUE"
    c["status"] = "RETURNED"
    c["returned_at"] = db.now_iso()
    if was_overdue:
        c["_was_overdue"] = True
    db.touch(c)
    if packet is not None and packet["status"] == "CHECKED_OUT":
        packet["status"] = "RETURNED"
        db.touch(packet)
    member = db.members.get(c["member_id"])
    if member is not None:
        recompute_member(member)
        db.touch(member)
    return success_object(checkout_view(c))


@bp.post("/api/checkouts/<checkout_id>/verify-return")
def verify_return(checkout_id):
    require_roles("ProgramAdmin")
    c = get_checkout_or_404(checkout_id)
    if c["status"] in CHECKOUT_TERMINAL:
        raise already_terminal("Checkout is in a terminal state.")
    if c["status"] != "RETURNED":
        raise invalid_state("Only a RETURNED checkout can be verified.")
    packet = db.packets.get(c["packet_id"])
    lot = db.lots.get(packet["lot_id"]) if packet else None
    c["status"] = "VERIFIED"
    db.touch(c)
    if packet is not None:
        if packet["status"] == "RETURNED":
            if lot is not None and lot["status"] == "ACTIVE":
                packet["status"] = "AVAILABLE"
                db.touch(packet)
            else:
                packet["status"] = "DISCARDED"
                db.touch(packet)
                if lot is not None:
                    lot["seeds_in_packets"] -= packet["seeds_count"]
                    lot["seeds_discarded"] += packet["seeds_count"]
                    db.touch(lot)
    member = db.members.get(c["member_id"])
    if member is not None:
        recompute_member(member)
        # auto-reinstate
        if member["status"] == "SUSPENDED" and member["overdue_checkout_count"] <= 2:
            member["status"] = "ACTIVE"
        db.touch(member)
    return success_object(checkout_view(c))


@bp.post("/api/checkouts/<checkout_id>/dispute")
def dispute_checkout(checkout_id):
    user_id, role = require_roles("Member", "ProgramAdmin")
    c = get_checkout_or_404(checkout_id)
    get_body()  # optional reason; shape-validated but otherwise unused
    # band 6 (non-terminal only): disputable state
    if c["status"] not in CHECKOUT_TERMINAL:
        if c["status"] == "RETURNED":
            # staff-only per state machine (ProgramAdmin); Member role forbidden
            if role != "ProgramAdmin":
                raise invalid_state("Dispute from RETURNED is staff-only.")
        elif c["status"] == "OVERDUE":
            pass  # ownership checked at band 12 below
        else:
            raise invalid_state("Checkout is not in a disputable state.")
    # band 12: ownership for member-initiated dispute from OVERDUE
    if c["status"] == "OVERDUE" and role == "Member" and c["member_id"] != user_id:
        raise self_service_forbidden("Member may dispute only its own checkouts.")
    # band 14: terminal lockdown
    if c["status"] in CHECKOUT_TERMINAL:
        raise already_terminal("Checkout is in a terminal state.")
    c["status"] = "DISPUTED"
    db.touch(c)
    return success_object(checkout_view(c))


@bp.post("/api/checkouts/<checkout_id>/resolve-dispute")
def resolve_dispute(checkout_id):
    require_roles("ProgramAdmin")
    c = get_checkout_or_404(checkout_id)
    body = get_body()
    outcome = opt_enum(body, "outcome", {"RETURN_ACCEPTED", "WRITE_OFF"})
    if outcome is None:
        raise invalid_request("Missing required field: outcome")
    if c["status"] in CHECKOUT_TERMINAL:
        raise already_terminal("Checkout is in a terminal state.")
    if c["status"] != "DISPUTED":
        raise invalid_state("Only a DISPUTED checkout can be resolved.")
    if outcome == "RETURN_ACCEPTED":
        c["status"] = "RETURNED"
        db.touch(c)
        return success_object(checkout_view(c))
    # WRITE_OFF cascade
    packet = db.packets.get(c["packet_id"])
    lot = db.lots.get(packet["lot_id"]) if packet else None
    c["status"] = "WRITTEN_OFF"
    db.touch(c)
    if packet is not None and packet["status"] in ("CHECKED_OUT", "RETURNED"):
        packet["status"] = "DISCARDED"
        db.touch(packet)
        if lot is not None:
            lot["seeds_in_packets"] -= packet["seeds_count"]
            lot["seeds_discarded"] += packet["seeds_count"]
            db.touch(lot)
    member = db.members.get(c["member_id"])
    if member is not None:
        recompute_member(member)
        if member["status"] == "SUSPENDED" and member["overdue_checkout_count"] <= 2:
            member["status"] = "ACTIVE"
        db.touch(member)
    return success_object(checkout_view(c))
