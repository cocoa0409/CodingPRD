"""Homeowner + AutopayMandate + reverse-reachability listings."""

from flask import Blueprint, request

import db
from auth import require_role
from clock import get_now_iso, sweep_time_transitions
from entities import (bump, new_homeowner, new_autopay_mandate)
from errors import raise_error
from response import success, no_content
from utils import (paginate, require_fields, require_str, require_int,
                   optional_bool, require_json)

bp = Blueprint("homeowners", __name__)


# ---------------- Homeowners ---------------- #

@bp.route("/homeowners", methods=["POST"])
@require_role("HOAManager")
def create_homeowner():
    body = require_json(request)
    require_fields(body, "email", "full_name")
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    is_board_member = optional_bool(body, "is_board_member", default=False)

    # Uniqueness — case-insensitive.
    email_ci = email.lower()
    for h in db.homeowners.values():
        if h["email"].lower() == email_ci:
            raise_error("ERR_UNIQUE_VIOLATION", "duplicate homeowner email")
    now_iso = get_now_iso()
    row = new_homeowner(email, full_name, is_board_member, now_iso)
    db.homeowners[row["id"]] = row
    return success(row, status=201)


@bp.route("/homeowners/<hid>", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager", "ComplianceOfficer")
def get_homeowner(hid):
    sweep_time_transitions()
    h = db.homeowners.get(hid)
    if not h:
        raise_error("ERR_NOT_FOUND", "homeowner not found")
    return success(h)


@bp.route("/homeowners/<hid>/properties", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def list_homeowner_properties(hid):
    if hid not in db.homeowners:
        raise_error("ERR_NOT_FOUND", "homeowner not found")
    items = [p for p in db.properties.values() if p["homeowner_id"] == hid]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, request)
    return success(page, is_array=True, pagination=meta)


@bp.route("/homeowners/<hid>/arc-requests", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def list_homeowner_arc_requests(hid):
    if hid not in db.homeowners:
        raise_error("ERR_NOT_FOUND", "homeowner not found")
    items = [r for r in db.arc_requests.values() if r["submitter_homeowner_id"] == hid]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, request)
    return success(page, is_array=True, pagination=meta)


@bp.route("/homeowners/<hid>/arc-reviews", methods=["GET"])
@require_role("BoardMember", "HOAManager")
def list_homeowner_arc_reviews(hid):
    if hid not in db.homeowners:
        raise_error("ERR_NOT_FOUND", "homeowner not found")
    items = [r for r in db.arc_reviews.values() if r["reviewer_homeowner_id"] == hid]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, request)
    return success(page, is_array=True, pagination=meta)


# ---------------- Autopay mandate ---------------- #

@bp.route("/homeowners/<hid>/autopay-mandate", methods=["POST"])
@require_role("Homeowner", "HOAManager")
def create_autopay_mandate(hid):
    body = require_json(request)
    # PRD §2.8: malformed payloads are 400 before the priority sequence begins.
    require_fields(body, "expected_homeowner_version", "max_charge_cents")
    expected = require_int(body, "expected_homeowner_version")
    max_charge = require_int(body, "max_charge_cents", minimum=1)

    h = db.homeowners.get(hid)
    if not h:
        raise_error("ERR_NOT_FOUND", "homeowner not found")

    # OCC check per PRD §2.10.
    if h.get("version", 1) != expected:
        raise_error("ERR_STALE_VERSION", "expected_homeowner_version does not match current version")

    now_iso = get_now_iso()

    # Supersede prior ACTIVE mandate.
    for m in db.autopay_mandates.values():
        if m["homeowner_id"] == hid and m["status"] == "ACTIVE":
            m["status"] = "SUPERSEDED"
            bump(m, now_iso)

    row = new_autopay_mandate(hid, max_charge, now_iso)
    db.autopay_mandates[row["id"]] = row

    # Increment homeowner version.
    bump(h, now_iso)
    return success(row, status=201)


@bp.route("/homeowners/<hid>/autopay-mandate", methods=["DELETE"])
@require_role("Homeowner", "HOAManager")
def cancel_autopay_mandate(hid):
    if hid not in db.homeowners:
        raise_error("ERR_NOT_FOUND", "homeowner not found")
    now_iso = get_now_iso()
    # Cancel the current ACTIVE mandate for this homeowner (if any).
    for m in db.autopay_mandates.values():
        if m["homeowner_id"] == hid and m["status"] == "ACTIVE":
            m["status"] = "CANCELLED"
            bump(m, now_iso)
    return no_content()


@bp.route("/homeowners/<hid>/autopay-mandate", methods=["GET"])
@require_role("Homeowner", "HOAManager")
def list_autopay_mandates(hid):
    if hid not in db.homeowners:
        raise_error("ERR_NOT_FOUND", "homeowner not found")
    items = [m for m in db.autopay_mandates.values() if m["homeowner_id"] == hid]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, request)
    return success(page, is_array=True, pagination=meta)
