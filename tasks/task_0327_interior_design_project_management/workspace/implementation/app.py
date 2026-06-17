"""Interior Design PM API — Flask entry point.

Route registration, error handling, and the full endpoint surface (PRD §4).
Validation order per request follows PRD §2.6:
  auth(401) -> authz role(403) -> existence(404) -> ownership(403)
  -> request well-formedness(422) -> state(409) -> business rules.
"""
import os
from datetime import datetime, timezone

from flask import Flask, request

import db
import lookup
import serializers as S
import services
from errors import ApiError, err
from middleware import get_identity, require_roles
from response import success, success_list, error_response
from validation import (
    get_json_body, require_str, optional_str, require_int, optional_int,
    require_number, optional_number, optional_bool, require_enum, optional_enum,
    require_datetime, parse_datetime, parse_pagination,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

# Enum domains (SCAFFOLD §1.1)
FFE_CATEGORIES = {"FURNITURE", "LIGHTING", "TEXTILE", "DECOR", "FIXTURE"}
VENDOR_TRADES = {"SUPPLIER", "UPHOLSTERY", "MILLWORK", "ELECTRICAL", "GENERAL"}
VENDOR_STANDINGS = {"ACTIVE", "SUSPENDED"}
FEE_MODELS = {"FLAT", "HOURLY", "MARKUP"}
REVISION_TARGET_KINDS = {"ROOM", "SELECTION"}
PUNCH_SEVERITIES = {"MINOR", "MAJOR", "BLOCKING"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found."), 404


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed."), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_VALIDATION", "Unexpected error: %s" % str(e)), 400


def _now_dt():
    return datetime.now(timezone.utc)


# ===========================================================================
# Client
# ===========================================================================
@app.route("/clients", methods=["POST"])
def create_client():
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin"})
    body = get_json_body()
    display_name = require_str(body, "display_name")
    email = require_str(body, "email")
    with db.LOCK:
        for c in db.clients.values():
            if c["email"] == email:
                raise err("ERR_DUPLICATE", "Client email already exists.")
        rec = db.new_common()
        rec.update({"display_name": display_name, "email": email})
        db.clients[rec["id"]] = rec
        return success(S.client(rec), status=201)


@app.route("/clients/<cid>", methods=["GET"])
def get_client_route(cid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Client"})
    rec = lookup.get_client(cid)
    if role == "Client" and rec["id"] != user_id:
        raise err("ERR_FORBIDDEN", "Client may only read its own record.")
    return success(S.client(rec))


# ===========================================================================
# Project
# ===========================================================================
@app.route("/projects", methods=["POST"])
def create_project():
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin"})
    body = get_json_body()
    client_name = require_str(body, "client_name")
    client_user_id = require_str(body, "client_user_id")
    brief_summary = require_str(body, "brief_summary")
    budget_cents = require_int(body, "budget_cents")
    if budget_cents <= 0:
        raise err("ERR_INVALID_REQUEST", "budget_cents must be > 0.")
    fee_model = require_enum(body, "fee_model", FEE_MODELS)

    flat_fee_cents = optional_int(body, "flat_fee_cents", 0)
    hourly_rate_cents = optional_int(body, "hourly_rate_cents", 0)
    markup_pct = optional_number(body, "markup_pct", 0)

    # fee_model field consistency (ERR_FEE_MODEL_FIELDS, 422) — PRD §3.2
    if fee_model == "FLAT":
        if not (flat_fee_cents > 0 and hourly_rate_cents == 0 and markup_pct == 0):
            raise err("ERR_FEE_MODEL_FIELDS", "FLAT requires flat_fee_cents>0 and other fee fields 0.")
    elif fee_model == "HOURLY":
        if not (hourly_rate_cents > 0 and flat_fee_cents == 0 and markup_pct == 0):
            raise err("ERR_FEE_MODEL_FIELDS", "HOURLY requires hourly_rate_cents>0 and other fee fields 0.")
    elif fee_model == "MARKUP":
        if not (0 < markup_pct < 1 and flat_fee_cents == 0 and hourly_rate_cents == 0):
            raise err("ERR_FEE_MODEL_FIELDS", "MARKUP requires 0<markup_pct<1 and other fee fields 0.")

    with db.LOCK:
        rec = db.new_common()
        rec.update({
            "client_name": client_name,
            "client_user_id": client_user_id,
            "brief_summary": brief_summary,
            "budget_cents": budget_cents,
            "fee_model": fee_model,
            "flat_fee_cents": flat_fee_cents,
            "hourly_rate_cents": hourly_rate_cents,
            "markup_pct": markup_pct,
            "status": "BRIEFING",
            "posture": "OPEN",
            "committed_cents": 0,
            "design_fee_cents": 0,
            "budget_remaining_cents": 0,
            "budget_status": "GREEN",
            "client_credit_cents": 0,
        })
        db.projects[rec["id"]] = rec
        # Initialize ledger from the zero starting point (no version bump beyond
        # creation): compute design_fee/budget_status/budget_remaining/posture.
        services.recompute_project(rec, bump_version=False)
        return success(S.project(rec), status=201)


@app.route("/projects/<pid>", methods=["GET"])
def get_project_route(pid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Designer", "ProcurementCoordinator", "Client"})
    rec = lookup.get_project(pid)
    lookup.check_client_owns_project(role, user_id, rec)
    return success(S.project(rec))


@app.route("/projects", methods=["GET"])
def list_projects():
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Designer", "ProcurementCoordinator", "Client"})
    limit, offset = parse_pagination()
    client_user_id = request.args.get("client_user_id")
    items = list(db.projects.values())
    if client_user_id is not None:
        items = [p for p in items if p["client_user_id"] == client_user_id]
    # Clients only see their own projects.
    if role == "Client":
        items = [p for p in items if p["client_user_id"] == user_id]
    page, total = lookup.paginate_sorted(items, limit, offset)
    return success_list([S.project(p) for p in page], limit, offset, total)


@app.route("/projects/<pid>/advance", methods=["POST"])
def advance_project(pid):
    user_id, role = get_identity()
    require_roles(role, {"Designer", "ProcurementCoordinator"})
    proj = lookup.get_project(pid)
    body = get_json_body()
    to = require_enum(body, "to", {"BRIEFING", "IN_DESIGN", "PROCUREMENT", "INSTALLATION", "CLOSED", "ON_HOLD"})

    with db.LOCK:
        cur = proj["status"]
        if cur == "BRIEFING" and to == "IN_DESIGN":
            rooms = [r for r in db.rooms.values() if r["project_id"] == pid]
            if len(rooms) < 1:
                raise err("ERR_INVALID_STATE", "At least one room must exist to advance to IN_DESIGN.")
            proj["status"] = "IN_DESIGN"
        elif cur == "IN_DESIGN" and to == "PROCUREMENT":
            rooms = [r for r in db.rooms.values() if r["project_id"] == pid]
            if any(r["status"] != "APPROVED" for r in rooms):
                raise err("ERR_ROOMS_NOT_APPROVED", "Every room must be APPROVED to advance to PROCUREMENT.")
            for r in db.revisions.values():
                if r["project_id"] == pid and r["status"] in ("SUBMITTED", "CHANGES_REQUESTED"):
                    raise err("ERR_OPEN_REVISION", "An open revision blocks advance to PROCUREMENT.")
            proj["status"] = "PROCUREMENT"
        elif cur == "PROCUREMENT" and to == "INSTALLATION":
            # FROZEN posture blocks advance-to-INSTALLATION (PRD §2.8).
            if proj["posture"] == "FROZEN":
                raise err("ERR_PROJECT_FROZEN", "Project is FROZEN; cannot advance to INSTALLATION.")
            in_flight = [
                o for o in db.orders.values()
                if o["project_id"] == pid and o["status"] in ("IN_TRANSIT", "DELIVERED")
            ]
            if len(in_flight) < 1:
                raise err("ERR_NO_ORDERS_IN_FLIGHT", "At least one order must be IN_TRANSIT or DELIVERED.")
            proj["status"] = "INSTALLATION"
        else:
            raise err("ERR_INVALID_STATE", "Illegal advance transition.")

        db.touch(proj)
        return success(S.project(proj))


@app.route("/projects/<pid>/hold", methods=["POST"])
def hold_project(pid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin"})
    proj = lookup.get_project(pid)
    with db.LOCK:
        if proj["status"] not in ("BRIEFING", "IN_DESIGN", "PROCUREMENT"):
            raise err("ERR_INVALID_STATE", "Project can only be held from BRIEFING, IN_DESIGN, or PROCUREMENT.")
        proj["status"] = "ON_HOLD"
        db.touch(proj)
        return success(S.project(proj))


@app.route("/projects/<pid>/resume", methods=["POST"])
def resume_project(pid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin"})
    proj = lookup.get_project(pid)
    with db.LOCK:
        if proj["status"] != "ON_HOLD":
            raise err("ERR_INVALID_STATE", "Only an ON_HOLD project can be resumed.")
        proj["status"] = "IN_DESIGN"
        db.touch(proj)
        return success(S.project(proj))


@app.route("/projects/<pid>/close", methods=["POST"])
def close_project(pid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin"})
    proj = lookup.get_project(pid)
    with db.LOCK:
        if proj["status"] != "INSTALLATION":
            raise err("ERR_INVALID_STATE", "Project can only be closed from INSTALLATION.")
        # First precondition: posture must not be FROZEN (PRD §3.2).
        if proj["posture"] == "FROZEN":
            raise err("ERR_PROJECT_FROZEN", "Project is FROZEN; cannot close.")
        # Second: every order in {CLOSED, CANCELLED, RETURNED, DELIVERED}.
        for o in db.orders.values():
            if o["project_id"] == pid and o["status"] not in ("CLOSED", "CANCELLED", "RETURNED", "DELIVERED"):
                raise err("ERR_ORDERS_OPEN", "All orders must be closed/cancelled/returned/delivered to close.")
        proj["status"] = "CLOSED"
        # design_fee finalized; budget recomputed against final fee; version bumps.
        services.recompute_project(proj, bump_version=True)
        return success(S.project(proj))


@app.route("/projects/<pid>/fee-quote", methods=["GET"])
def fee_quote(pid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Designer", "Client"})
    proj = lookup.get_project(pid)
    lookup.check_client_owns_project(role, user_id, proj)
    # Read-only: compute provisional & final without mutating (PRD §3.9).
    provisional = services.design_fee(proj, final=False)
    final = services.design_fee(proj, final=True)
    committed = services.committed_cents(proj)
    # Budget snapshot uses provisional fee while open per §3.8.
    open_fee = final if proj["status"] == "CLOSED" else provisional
    data = {
        "provisional_design_fee_cents": provisional,
        "final_design_fee_cents": final,
        "committed_cents": committed,
        "budget_cents": proj["budget_cents"],
        "budget_remaining_cents": proj["budget_cents"] - committed - open_fee,
        "budget_status": services.budget_status(committed, open_fee, proj["budget_cents"]),
        "client_credit_cents": proj["client_credit_cents"],
    }
    return success(data)


# ===========================================================================
# Payments
# ===========================================================================
@app.route("/projects/<pid>/payments", methods=["POST"])
def create_payment(pid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin"})
    proj = lookup.get_project(pid)
    body = get_json_body()
    amount_cents = require_int(body, "amount_cents")
    if amount_cents <= 0:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be > 0.")
    received_at_raw, _ = require_datetime(body, "received_at")
    memo = optional_str(body, "memo", "")
    expected_version = require_int(body, "expected_project_version")

    with db.LOCK:
        # OCC check first (PRD §2.10).
        if expected_version != proj["version"]:
            raise err("ERR_STALE_VERSION", "expected_project_version does not match current version.")
        rec = db.new_common()
        rec.update({
            "project_id": pid,
            "amount_cents": amount_cents,
            "received_at": received_at_raw,
            "memo": memo,
        })
        db.payments[rec["id"]] = rec
        # Re-run the waterfall and re-derive the ledger; bumps Project.version.
        services.recompute_project(proj, bump_version=True)
        return success(S.payment(rec), status=201)


@app.route("/payments/<pid>", methods=["GET"])
def get_payment_route(pid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Client"})
    rec = lookup.get_payment(pid)
    if role == "Client":
        proj = lookup.project_of_payment(rec)
        lookup.check_client_owns_project(role, user_id, proj)
    return success(S.payment(rec))


@app.route("/payments", methods=["GET"])
def list_payments():
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Client"})
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    items = list(db.payments.values())
    if project_id is not None:
        items = [p for p in items if p["project_id"] == project_id]
    if role == "Client":
        owned = {p["id"] for p in db.projects.values() if p["client_user_id"] == user_id}
        items = [p for p in items if p["project_id"] in owned]
    page, total = lookup.paginate_sorted(items, limit, offset)
    return success_list([S.payment(p) for p in page], limit, offset, total)


# ===========================================================================
# Room
# ===========================================================================
@app.route("/projects/<pid>/rooms", methods=["POST"])
def create_room(pid):
    user_id, role = get_identity()
    require_roles(role, {"Designer"})
    proj = lookup.get_project(pid)
    body = get_json_body()
    name = require_str(body, "name")
    scope_note = require_str(body, "scope_note")
    room_budget_cents = require_int(body, "room_budget_cents")
    if room_budget_cents < 0:
        raise err("ERR_INVALID_REQUEST", "room_budget_cents must be >= 0.")
    with db.LOCK:
        # Room.name unique within project, case-sensitive (PRD §3.3).
        for r in db.rooms.values():
            if r["project_id"] == pid and r["name"] == name:
                raise err("ERR_DUPLICATE", "Room name already exists in this project.")
        rec = db.new_common()
        rec.update({
            "project_id": pid,
            "name": name,
            "scope_note": scope_note,
            "room_budget_cents": room_budget_cents,
            "status": "SCOPING",
            "approved_moodboard_id": None,
        })
        db.rooms[rec["id"]] = rec
        return success(S.room(rec), status=201)


@app.route("/rooms/<rid>", methods=["GET"])
def get_room_route(rid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Designer", "ProcurementCoordinator", "Client"})
    rec = lookup.get_room(rid)
    if role == "Client":
        lookup.check_client_owns_project(role, user_id, lookup.project_of_room(rec))
    return success(S.room(rec))


@app.route("/rooms", methods=["GET"])
def list_rooms():
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Designer", "ProcurementCoordinator", "Client"})
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    approved_moodboard_id = request.args.get("approved_moodboard_id")
    items = list(db.rooms.values())
    if project_id is not None:
        items = [r for r in items if r["project_id"] == project_id]
    if approved_moodboard_id is not None:
        items = [r for r in items if r["approved_moodboard_id"] == approved_moodboard_id]
    if role == "Client":
        owned = {p["id"] for p in db.projects.values() if p["client_user_id"] == user_id}
        items = [r for r in items if r["project_id"] in owned]
    page, total = lookup.paginate_sorted(items, limit, offset)
    return success_list([S.room(r) for r in page], limit, offset, total)


@app.route("/rooms/<rid>/present-moodboard", methods=["POST"])
def present_moodboard_room(rid):
    user_id, role = get_identity()
    require_roles(role, {"Designer"})
    room = lookup.get_room(rid)
    with db.LOCK:
        if room["status"] != "SCOPING":
            raise err("ERR_INVALID_STATE", "Room must be SCOPING to mark MOODBOARD_READY.")
        presented = [m for m in db.moodboards.values() if m["room_id"] == rid and m["status"] == "PRESENTED"]
        if len(presented) < 1:
            raise err("ERR_NO_PRESENTED_MOODBOARD", "At least one mood board must be PRESENTED.")
        room["status"] = "MOODBOARD_READY"
        db.touch(room)
        return success(S.room(room))


@app.route("/rooms/<rid>/approve", methods=["POST"])
def approve_room(rid):
    user_id, role = get_identity()
    require_roles(role, {"Client"})
    room = lookup.get_room(rid)
    lookup.check_client_owns_project(role, user_id, lookup.project_of_room(room))
    with db.LOCK:
        if room["status"] != "MOODBOARD_READY":
            raise err("ERR_INVALID_STATE", "Room must be MOODBOARD_READY to approve.")
        presented = [m for m in db.moodboards.values() if m["room_id"] == rid and m["status"] == "PRESENTED"]
        if len(presented) != 1:
            raise err("ERR_NO_PRESENTED_MOODBOARD", "Exactly one mood board must be PRESENTED to approve.")
        accepted = presented[0]
        accepted["status"] = "ACCEPTED"
        db.touch(accepted)
        # all other DRAFT/PRESENTED boards for the room -> SUPERSEDED (cascade).
        for m in db.moodboards.values():
            if m["room_id"] == rid and m["id"] != accepted["id"] and m["status"] in ("DRAFT", "PRESENTED"):
                m["status"] = "SUPERSEDED"
                db.touch(m)
        room["status"] = "APPROVED"
        room["approved_moodboard_id"] = accepted["id"]
        db.touch(room)
        return success(S.room(room))


@app.route("/rooms/<rid>/request-rework", methods=["POST"])
def request_rework_room(rid):
    user_id, role = get_identity()
    require_roles(role, {"Client"})
    room = lookup.get_room(rid)
    lookup.check_client_owns_project(role, user_id, lookup.project_of_room(room))
    with db.LOCK:
        if room["status"] != "MOODBOARD_READY":
            raise err("ERR_INVALID_STATE", "Room must be MOODBOARD_READY to request rework.")
        for m in db.moodboards.values():
            if m["room_id"] == rid and m["status"] == "PRESENTED":
                m["status"] = "SUPERSEDED"
                db.touch(m)
        room["status"] = "REWORK"
        db.touch(room)
        return success(S.room(room))


@app.route("/rooms/<rid>/reopen-scope", methods=["POST"])
def reopen_scope_room(rid):
    user_id, role = get_identity()
    require_roles(role, {"Designer"})
    room = lookup.get_room(rid)
    with db.LOCK:
        if room["status"] != "REWORK":
            raise err("ERR_INVALID_STATE", "Room must be REWORK to reopen scope.")
        room["status"] = "SCOPING"
        db.touch(room)
        return success(S.room(room))


# ===========================================================================
# MoodBoard
# ===========================================================================
@app.route("/rooms/<rid>/moodboards", methods=["POST"])
def create_moodboard(rid):
    user_id, role = get_identity()
    require_roles(role, {"Designer"})
    room = lookup.get_room(rid)
    body = get_json_body()
    title = require_str(body, "title")
    palette = body.get("palette")
    if not isinstance(palette, list):
        raise err("ERR_INVALID_REQUEST", "palette must be an array.")
    with db.LOCK:
        rec = db.new_common()
        rec.update({
            "room_id": rid,
            "title": title,
            "palette": palette,
            "status": "DRAFT",
        })
        db.moodboards[rec["id"]] = rec
        return success(S.moodboard(rec), status=201)


@app.route("/moodboards/<mid>", methods=["GET"])
def get_moodboard_route(mid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Designer", "Client"})
    rec = lookup.get_moodboard(mid)
    if role == "Client":
        lookup.check_client_owns_project(role, user_id, lookup.project_of_moodboard(rec))
    return success(S.moodboard(rec))


@app.route("/moodboards", methods=["GET"])
def list_moodboards():
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Designer", "Client"})
    limit, offset = parse_pagination()
    room_id = request.args.get("room_id")
    items = list(db.moodboards.values())
    if room_id is not None:
        items = [m for m in items if m["room_id"] == room_id]
    if role == "Client":
        owned = {p["id"] for p in db.projects.values() if p["client_user_id"] == user_id}
        owned_rooms = {r["id"] for r in db.rooms.values() if r["project_id"] in owned}
        items = [m for m in items if m["room_id"] in owned_rooms]
    page, total = lookup.paginate_sorted(items, limit, offset)
    return success_list([S.moodboard(m) for m in page], limit, offset, total)


@app.route("/moodboards/<mid>/present", methods=["POST"])
def present_moodboard(mid):
    user_id, role = get_identity()
    require_roles(role, {"Designer"})
    mb = lookup.get_moodboard(mid)
    with db.LOCK:
        if mb["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Mood board must be DRAFT to present.")
        for m in db.moodboards.values():
            if m["room_id"] == mb["room_id"] and m["id"] != mid and m["status"] == "PRESENTED":
                raise err("ERR_MOODBOARD_ALREADY_PRESENTED", "Another mood board is already PRESENTED.")
        mb["status"] = "PRESENTED"
        db.touch(mb)
        return success(S.moodboard(mb))


# ===========================================================================
# FFEItem (catalog)
# ===========================================================================
@app.route("/ffe-items", methods=["POST"])
def create_ffe_item():
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Designer"})
    body = get_json_body()
    sku = require_str(body, "sku")
    name = require_str(body, "name")
    category = require_enum(body, "category", FFE_CATEGORIES)
    list_unit_cost_cents = require_int(body, "list_unit_cost_cents")
    if list_unit_cost_cents <= 0:
        raise err("ERR_INVALID_REQUEST", "list_unit_cost_cents must be > 0.")
    lead_time_days = require_int(body, "lead_time_days")
    if lead_time_days < 0:
        raise err("ERR_INVALID_REQUEST", "lead_time_days must be >= 0.")
    active = optional_bool(body, "active", True)
    with db.LOCK:
        for f in db.ffe_items.values():
            if f["sku"] == sku:
                raise err("ERR_DUPLICATE", "FFEItem sku already exists.")
        rec = db.new_common()
        rec.update({
            "sku": sku,
            "name": name,
            "category": category,
            "list_unit_cost_cents": list_unit_cost_cents,
            "lead_time_days": lead_time_days,
            "active": active,
        })
        db.ffe_items[rec["id"]] = rec
        return success(S.ffe_item(rec), status=201)


@app.route("/ffe-items/<fid>", methods=["GET"])
def get_ffe_item_route(fid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Designer", "ProcurementCoordinator"})
    rec = lookup.get_ffe_item(fid)
    return success(S.ffe_item(rec))


# ===========================================================================
# DesignSelection
# ===========================================================================
@app.route("/projects/<pid>/selections", methods=["POST"])
def create_selection(pid):
    user_id, role = get_identity()
    require_roles(role, {"Designer"})
    proj = lookup.get_project(pid)
    body = get_json_body()
    room_id = require_str(body, "room_id")
    ffe_item_id = require_str(body, "ffe_item_id")
    quantity = require_int(body, "quantity")
    if quantity < 1:
        raise err("ERR_INVALID_REQUEST", "quantity must be >= 1.")
    trade_discount_pct = optional_number(body, "trade_discount_pct", 0)
    if not (0 <= trade_discount_pct <= 0.5):
        raise err("ERR_INVALID_REQUEST", "trade_discount_pct must be in [0, 0.5].")
    spec_note = optional_str(body, "spec_note", "")

    with db.LOCK:
        room = db.rooms.get(room_id)
        if room is None or room["project_id"] != pid:
            raise err("ERR_NOT_FOUND", "Room not found in this project.")
        ffe = db.ffe_items.get(ffe_item_id)
        if ffe is None:
            raise err("ERR_NOT_FOUND", "FFEItem not found.")
        # FFEItem.active must be true (ERR_FFE_ITEM_INACTIVE) — PRD §3.4.
        if not ffe["active"]:
            raise err("ERR_FFE_ITEM_INACTIVE", "FFEItem is inactive; cannot select.")

        unit_cost_cents = ffe["list_unit_cost_cents"]
        line_net = services.selection_line_net(unit_cost_cents, quantity, trade_discount_pct)
        rec = db.new_common()
        rec.update({
            "project_id": pid,
            "room_id": room_id,
            "ffe_item_id": ffe_item_id,
            "quantity": quantity,
            "unit_cost_cents": unit_cost_cents,
            "trade_discount_pct": trade_discount_pct,
            "spec_note": spec_note,
            "status": "PROPOSED",
            "line_net_cents": line_net,
        })
        db.selections[rec["id"]] = rec
        return success(S.selection(rec), status=201)


@app.route("/selections/<sid>", methods=["GET"])
def get_selection_route(sid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Designer", "ProcurementCoordinator", "Client"})
    rec = lookup.get_selection(sid)
    if role == "Client":
        lookup.check_client_owns_project(role, user_id, lookup.project_of_selection(rec))
    return success(S.selection(rec))


@app.route("/selections", methods=["GET"])
def list_selections():
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Designer", "ProcurementCoordinator", "Client"})
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    room_id = request.args.get("room_id")
    ffe_item_id = request.args.get("ffe_item_id")
    items = list(db.selections.values())
    if project_id is not None:
        items = [s for s in items if s["project_id"] == project_id]
    if room_id is not None:
        items = [s for s in items if s["room_id"] == room_id]
    if ffe_item_id is not None:
        items = [s for s in items if s["ffe_item_id"] == ffe_item_id]
    if role == "Client":
        owned = {p["id"] for p in db.projects.values() if p["client_user_id"] == user_id}
        items = [s for s in items if s["project_id"] in owned]
    page, total = lookup.paginate_sorted(items, limit, offset)
    return success_list([S.selection(s) for s in page], limit, offset, total)


@app.route("/selections/<sid>/specify", methods=["POST"])
def specify_selection(sid):
    user_id, role = get_identity()
    require_roles(role, {"Designer"})
    sel = lookup.get_selection(sid)
    with db.LOCK:
        if sel["status"] != "PROPOSED":
            raise err("ERR_INVALID_STATE", "Selection must be PROPOSED to specify.")
        room = db.rooms.get(sel["room_id"])
        if room is None or room["status"] != "APPROVED":
            raise err("ERR_ROOM_NOT_APPROVED", "Selection's room must be APPROVED to specify.")
        if not sel["spec_note"]:
            raise err("ERR_SPEC_NOTE_REQUIRED", "spec_note must be non-empty to specify.")
        sel["status"] = "SPECIFIED"
        db.touch(sel)
        return success(S.selection(sel))


@app.route("/selections/<sid>/withdraw", methods=["POST"])
def withdraw_selection(sid):
    user_id, role = get_identity()
    require_roles(role, {"Designer"})
    sel = lookup.get_selection(sid)
    with db.LOCK:
        if sel["status"] not in ("PROPOSED", "SPECIFIED"):
            raise err("ERR_INVALID_STATE", "Selection must be PROPOSED or SPECIFIED to withdraw.")
        if sel["status"] == "SPECIFIED":
            # Must not be attached to any non-CANCELLED order (PRD §3.4).
            if _selection_on_non_cancelled_order(sid):
                raise err("ERR_SELECTION_ON_ORDER", "Selection is attached to a non-cancelled order.")
        sel["status"] = "WITHDRAWN"
        db.touch(sel)
        return success(S.selection(sel))


def _selection_on_non_cancelled_order(selection_id):
    for ol in db.order_lines.values():
        if ol["selection_id"] != selection_id:
            continue
        order = db.orders.get(ol["order_id"])
        if order and order["status"] != "CANCELLED":
            return True
    return False


# ===========================================================================
# Vendor
# ===========================================================================
@app.route("/vendors", methods=["POST"])
def create_vendor():
    user_id, role = get_identity()
    require_roles(role, {"ProcurementCoordinator", "StudioAdmin"})
    body = get_json_body()
    name = require_str(body, "name")
    trade = require_enum(body, "trade", VENDOR_TRADES)
    standing = optional_enum(body, "standing", VENDOR_STANDINGS, "ACTIVE")
    lead_time_buffer_days = optional_int(body, "lead_time_buffer_days", 0)
    if lead_time_buffer_days < 0:
        raise err("ERR_INVALID_REQUEST", "lead_time_buffer_days must be >= 0.")
    with db.LOCK:
        rec = db.new_common()
        rec.update({
            "name": name,
            "trade": trade,
            "standing": standing,
            "lead_time_buffer_days": lead_time_buffer_days,
        })
        db.vendors[rec["id"]] = rec
        return success(S.vendor(rec), status=201)


@app.route("/vendors/<vid>", methods=["GET"])
def get_vendor_route(vid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "ProcurementCoordinator"})
    rec = lookup.get_vendor(vid)
    return success(S.vendor(rec))


@app.route("/vendors/<vid>/suspend", methods=["POST"])
def suspend_vendor(vid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin"})
    vendor = lookup.get_vendor(vid)
    with db.LOCK:
        vendor["standing"] = "SUSPENDED"
        db.touch(vendor)
        return success(S.vendor(vendor))


# ===========================================================================
# ProcurementOrder
# ===========================================================================
@app.route("/projects/<pid>/orders", methods=["POST"])
def create_order(pid):
    user_id, role = get_identity()
    require_roles(role, {"ProcurementCoordinator"})
    proj = lookup.get_project(pid)
    body = get_json_body()
    vendor_id = require_str(body, "vendor_id")
    window_start_raw, window_start_dt = require_datetime(body, "window_start")
    window_end_raw, window_end_dt = require_datetime(body, "window_end")
    if not (window_end_dt > window_start_dt):
        raise err("ERR_INVALID_REQUEST", "window_end must be strictly later than window_start.")
    with db.LOCK:
        vendor = db.vendors.get(vendor_id)
        if vendor is None:
            raise err("ERR_NOT_FOUND", "Vendor not found.")
        rec = db.new_common()
        rec.update({
            "project_id": pid,
            "vendor_id": vendor_id,
            "window_start": window_start_raw,
            "window_end": window_end_raw,
            "status": "DRAFT",
            "order_subtotal_cents": 0,
            "amount_paid_cents": 0,
            "balance_due_cents": 0,
            "expected_delivery_at": None,
        })
        db.orders[rec["id"]] = rec
        return success(S.order(rec), status=201)


@app.route("/orders/<oid>", methods=["GET"])
def get_order_route(oid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "ProcurementCoordinator", "Designer", "Client"})
    rec = lookup.get_order(oid)
    if role == "Client":
        lookup.check_client_owns_project(role, user_id, lookup.project_of_order(rec))
    return success(S.order(rec))


@app.route("/orders", methods=["GET"])
def list_orders():
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "ProcurementCoordinator", "Designer", "Client"})
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    vendor_id = request.args.get("vendor_id")
    items = list(db.orders.values())
    if project_id is not None:
        items = [o for o in items if o["project_id"] == project_id]
    if vendor_id is not None:
        items = [o for o in items if o["vendor_id"] == vendor_id]
    if role == "Client":
        owned = {p["id"] for p in db.projects.values() if p["client_user_id"] == user_id}
        items = [o for o in items if o["project_id"] in owned]
    page, total = lookup.paginate_sorted(items, limit, offset)
    return success_list([S.order(o) for o in page], limit, offset, total)


@app.route("/orders/<oid>/lines", methods=["POST"])
def attach_order_line(oid):
    user_id, role = get_identity()
    require_roles(role, {"ProcurementCoordinator"})
    order = lookup.get_order(oid)
    body = get_json_body()
    selection_id = require_str(body, "selection_id")
    with db.LOCK:
        if order["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Order must be DRAFT to attach a line.")
        sel = db.selections.get(selection_id)
        if sel is None:
            raise err("ERR_NOT_FOUND", "Selection not found.")
        # Business rules (ERR_SELECTION_ALREADY_ORDERED, §3.5):
        #  - selection must be SPECIFIED
        #  - room must belong to the order's project
        #  - at most one non-CANCELLED order
        if sel["status"] != "SPECIFIED":
            raise err("ERR_SELECTION_ALREADY_ORDERED", "Selection must be SPECIFIED to attach.")
        room = db.rooms.get(sel["room_id"])
        if room is None or room["project_id"] != order["project_id"]:
            raise err("ERR_SELECTION_ALREADY_ORDERED", "Selection's room does not belong to the order's project.")
        if _selection_on_non_cancelled_order(selection_id):
            raise err("ERR_SELECTION_ALREADY_ORDERED", "Selection already attached to a non-cancelled order.")

        line = {
            "id": db.new_id(),
            "created_at": db.now_iso_for_line(),
            "_seq": db.next_seq(),
            "order_id": oid,
            "selection_id": selection_id,
            "line_net_cents_snapshot": sel["line_net_cents"],
        }
        db.order_lines[line["id"]] = line
        # Recompute order subtotal (round-then-sum of snapshots) — §3.5/§3.6.
        order["order_subtotal_cents"] = services.order_subtotal(order)
        order["balance_due_cents"] = order["order_subtotal_cents"] - order["amount_paid_cents"]
        db.touch(order)
        return success(S.order_line(line), status=201)


@app.route("/order-lines/<olid>", methods=["GET"])
def get_order_line_route(olid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "ProcurementCoordinator", "Designer"})
    rec = lookup.get_order_line(olid)
    return success(S.order_line(rec))


@app.route("/order-lines", methods=["GET"])
def list_order_lines():
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "ProcurementCoordinator", "Designer"})
    limit, offset = parse_pagination()
    order_id = request.args.get("order_id")
    selection_id = request.args.get("selection_id")
    items = list(db.order_lines.values())
    if order_id is not None:
        items = [ol for ol in items if ol["order_id"] == order_id]
    if selection_id is not None:
        items = [ol for ol in items if ol["selection_id"] == selection_id]
    page, total = lookup.paginate_sorted(items, limit, offset)
    return success_list([S.order_line(ol) for ol in page], limit, offset, total)


@app.route("/orders/<oid>/place", methods=["POST"])
def place_order(oid):
    user_id, role = get_identity()
    require_roles(role, {"ProcurementCoordinator"})
    order = lookup.get_order(oid)
    body = get_json_body()
    expected_version = require_int(body, "expected_project_version")
    proj = db.projects.get(order["project_id"])
    with db.LOCK:
        # State legality (§2.6 priority 5) before business gates.
        if order["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Order must be DRAFT to place.")
        # 1) OCC version match first (PRD §3.5).
        if expected_version != proj["version"]:
            raise err("ERR_STALE_VERSION", "expected_project_version does not match current version.")
        # 2) Posture gate (FROZEN -> ERR_PROJECT_FROZEN, BUDGET_REVIEW -> ERR_BUDGET_GATE).
        if proj["posture"] == "FROZEN":
            raise err("ERR_PROJECT_FROZEN", "Project is FROZEN; cannot place an order.")
        if proj["posture"] == "BUDGET_REVIEW":
            raise err("ERR_BUDGET_GATE", "Project is in BUDGET_REVIEW; cannot place a new order.")
        # 3) Vendor standing.
        vendor = db.vendors.get(order["vendor_id"])
        if vendor is None or vendor["standing"] != "ACTIVE":
            raise err("ERR_VENDOR_SUSPENDED", "Vendor is not ACTIVE.")
        # 4) Window overlap with another non-terminal order on the SAME vendor.
        if _vendor_window_conflict(order):
            raise err("ERR_VENDOR_WINDOW_CONFLICT", "Order window overlaps another order on this vendor.")
        # 5) At least one order line.
        lines = [ol for ol in db.order_lines.values() if ol["order_id"] == oid]
        if len(lines) < 1:
            raise err("ERR_ORDER_EMPTY", "Order must have at least one line to place.")

        # Cascade placement.
        ordered_dt = _now_dt()
        order["status"] = "ORDERED"
        order["expected_delivery_at"] = services.compute_expected_delivery(order, ordered_dt)
        for ol in lines:
            sel = db.selections.get(ol["selection_id"])
            if sel and sel["status"] == "SPECIFIED":
                sel["status"] = "ORDERED"
                db.touch(sel)
        db.touch(order)
        # Recompute committed/budget/posture; bump project version.
        services.recompute_project(proj, bump_version=True)
        return success(S.order(order))


def _windows_overlap(a_start, a_end, b_start, b_end):
    # half-open [start, end): overlap iff a_start < b_end and b_start < a_end.
    return a_start < b_end and b_start < a_end


def _vendor_window_conflict(order):
    a_start = parse_datetime(order["window_start"])
    a_end = parse_datetime(order["window_end"])
    for o in db.orders.values():
        if o["id"] == order["id"]:
            continue
        if o["vendor_id"] != order["vendor_id"]:
            continue
        if o["status"] not in services.NON_TERMINAL_ORDER_STATUSES:
            continue
        b_start = parse_datetime(o["window_start"])
        b_end = parse_datetime(o["window_end"])
        if _windows_overlap(a_start, a_end, b_start, b_end):
            return True
    return False


@app.route("/orders/<oid>/ship", methods=["POST"])
def ship_order(oid):
    user_id, role = get_identity()
    require_roles(role, {"ProcurementCoordinator"})
    order = lookup.get_order(oid)
    with db.LOCK:
        if order["status"] != "ORDERED":
            raise err("ERR_INVALID_STATE", "Order must be ORDERED to ship.")
        order["status"] = "IN_TRANSIT"
        db.touch(order)
        return success(S.order(order))


@app.route("/orders/<oid>/deliver", methods=["POST"])
def deliver_order(oid):
    user_id, role = get_identity()
    require_roles(role, {"ProcurementCoordinator"})
    order = lookup.get_order(oid)
    with db.LOCK:
        if order["status"] != "IN_TRANSIT":
            raise err("ERR_INVALID_STATE", "Order must be IN_TRANSIT to deliver.")
        order["status"] = "DELIVERED"
        db.touch(order)
        return success(S.order(order))


@app.route("/orders/<oid>/close-order", methods=["POST"])
def close_order(oid):
    user_id, role = get_identity()
    require_roles(role, {"ProcurementCoordinator"})
    order = lookup.get_order(oid)
    with db.LOCK:
        if order["status"] != "DELIVERED":
            raise err("ERR_INVALID_STATE", "Order must be DELIVERED to close.")
        for pi in db.punch_items.values():
            if pi["order_id"] == oid and pi["status"] == "OPEN":
                raise err("ERR_PUNCH_ITEMS_OPEN", "Cannot close an order with open punch items.")
        order["status"] = "CLOSED"
        db.touch(order)
        return success(S.order(order))


@app.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    user_id, role = get_identity()
    require_roles(role, {"ProcurementCoordinator"})
    order = lookup.get_order(oid)
    proj = db.projects.get(order["project_id"])
    with db.LOCK:
        if order["status"] not in ("ORDERED", "IN_TRANSIT"):
            raise err("ERR_INVALID_STATE", "Order must be ORDERED or IN_TRANSIT to cancel.")
        order["status"] = "CANCELLED"
        _revert_attached_selections(oid)
        db.touch(order)
        # committed/budget/posture recomputed; deposit re-allocated; project version bumps.
        services.recompute_project(proj, bump_version=True)
        return success(S.order(order))


@app.route("/orders/<oid>/return-order", methods=["POST"])
def return_order(oid):
    user_id, role = get_identity()
    require_roles(role, {"ProcurementCoordinator"})
    order = lookup.get_order(oid)
    proj = db.projects.get(order["project_id"])
    with db.LOCK:
        if order["status"] != "DELIVERED":
            raise err("ERR_INVALID_STATE", "Order must be DELIVERED to return.")
        has_blocking = any(
            pi["order_id"] == oid and pi["severity"] == "BLOCKING"
            for pi in db.punch_items.values()
        )
        if not has_blocking:
            raise err("ERR_RETURN_NOT_JUSTIFIED", "Return requires at least one BLOCKING punch item.")
        order["status"] = "RETURNED"
        _revert_attached_selections(oid)
        # all OPEN punch items on this order -> WAIVED (cascade).
        for pi in db.punch_items.values():
            if pi["order_id"] == oid and pi["status"] == "OPEN":
                pi["status"] = "WAIVED"
                db.touch(pi)
        db.touch(order)
        services.recompute_project(proj, bump_version=True)
        return success(S.order(order))


def _revert_attached_selections(order_id):
    """Every attached selection reverts ORDERED -> SPECIFIED (compensation)."""
    for ol in db.order_lines.values():
        if ol["order_id"] != order_id:
            continue
        sel = db.selections.get(ol["selection_id"])
        if sel and sel["status"] == "ORDERED":
            sel["status"] = "SPECIFIED"
            db.touch(sel)


# ===========================================================================
# RevisionRequest
# ===========================================================================
@app.route("/projects/<pid>/revisions", methods=["POST"])
def create_revision(pid):
    user_id, role = get_identity()
    require_roles(role, {"Client"})
    proj = lookup.get_project(pid)
    lookup.check_client_owns_project(role, user_id, proj)
    body = get_json_body()
    target_kind = require_enum(body, "target_kind", REVISION_TARGET_KINDS)
    target_id = require_str(body, "target_id")
    note = require_str(body, "note")
    with db.LOCK:
        rec = db.new_common()
        rec.update({
            "project_id": pid,
            "target_kind": target_kind,
            "target_id": target_id,
            "note": note,
            "round_no": 1,
            "status": "DRAFT",
        })
        db.revisions[rec["id"]] = rec
        return success(S.revision(rec), status=201)


@app.route("/revisions/<rid>", methods=["GET"])
def get_revision_route(rid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Designer", "Client"})
    rec = lookup.get_revision(rid)
    if role == "Client":
        lookup.check_client_owns_project(role, user_id, lookup.project_of_revision(rec))
    return success(S.revision(rec))


@app.route("/revisions", methods=["GET"])
def list_revisions():
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Designer", "Client"})
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    target_id = request.args.get("target_id")
    items = list(db.revisions.values())
    if project_id is not None:
        items = [r for r in items if r["project_id"] == project_id]
    if target_id is not None:
        items = [r for r in items if r["target_id"] == target_id]
    if role == "Client":
        owned = {p["id"] for p in db.projects.values() if p["client_user_id"] == user_id}
        items = [r for r in items if r["project_id"] in owned]
    page, total = lookup.paginate_sorted(items, limit, offset)
    return success_list([S.revision(r) for r in page], limit, offset, total)


@app.route("/revisions/<rid>/submit", methods=["POST"])
def submit_revision(rid):
    user_id, role = get_identity()
    require_roles(role, {"Client"})
    rev = lookup.get_revision(rid)
    proj = lookup.project_of_revision(rev)
    lookup.check_client_owns_project(role, user_id, proj)
    with db.LOCK:
        if rev["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
            raise err("ERR_INVALID_STATE", "Revision must be DRAFT or CHANGES_REQUESTED to submit.")
        if proj["status"] not in ("IN_DESIGN", "PROCUREMENT"):
            raise err("ERR_INVALID_STATE", "Project must be IN_DESIGN or PROCUREMENT to submit a revision.")
        resubmit = rev["status"] == "CHANGES_REQUESTED"
        rev["status"] = "SUBMITTED"
        if resubmit:
            rev["round_no"] += 1
        db.touch(rev)
        # Posture recomputed (an open revision pushes toward BUDGET_REVIEW).
        services.recompute_project(proj, bump_version=True)
        return success(S.revision(rev))


@app.route("/revisions/<rid>/request-changes", methods=["POST"])
def request_changes_revision(rid):
    user_id, role = get_identity()
    require_roles(role, {"Designer"})
    rev = lookup.get_revision(rid)
    with db.LOCK:
        if rev["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE", "Revision must be SUBMITTED to request changes.")
        rev["status"] = "CHANGES_REQUESTED"
        db.touch(rev)
        return success(S.revision(rev))


@app.route("/revisions/<rid>/resolve", methods=["POST"])
def resolve_revision(rid):
    user_id, role = get_identity()
    require_roles(role, {"Designer"})
    rev = lookup.get_revision(rid)
    proj = lookup.project_of_revision(rev)
    with db.LOCK:
        if rev["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE", "Revision must be SUBMITTED to resolve.")
        rev["status"] = "RESOLVED"
        db.touch(rev)
        # Compensation hop: ROOM target currently APPROVED reverts to REWORK.
        if rev["target_kind"] == "ROOM":
            room = db.rooms.get(rev["target_id"])
            if room and room["status"] == "APPROVED":
                _room_compensation_to_rework(room)
        services.recompute_project(proj, bump_version=True)
        return success(S.revision(rev))


def _room_compensation_to_rework(room):
    """APPROVED -> REWORK: clear approved_moodboard_id; ACCEPTED board -> SUPERSEDED."""
    accepted_id = room.get("approved_moodboard_id")
    room["status"] = "REWORK"
    room["approved_moodboard_id"] = None
    db.touch(room)
    if accepted_id:
        mb = db.moodboards.get(accepted_id)
        if mb and mb["status"] == "ACCEPTED":
            mb["status"] = "SUPERSEDED"
            db.touch(mb)


@app.route("/revisions/<rid>/dismiss", methods=["POST"])
def dismiss_revision(rid):
    user_id, role = get_identity()
    require_roles(role, {"Designer"})
    rev = lookup.get_revision(rid)
    proj = lookup.project_of_revision(rev)
    with db.LOCK:
        if rev["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE", "Revision must be SUBMITTED to dismiss.")
        rev["status"] = "DISMISSED"
        db.touch(rev)
        services.recompute_project(proj, bump_version=True)
        return success(S.revision(rev))


# ===========================================================================
# PunchListItem
# ===========================================================================
@app.route("/orders/<oid>/punch-items", methods=["POST"])
def create_punch_item(oid):
    user_id, role = get_identity()
    require_roles(role, {"ProcurementCoordinator", "Designer"})
    order = lookup.get_order(oid)
    body = get_json_body()
    description = require_str(body, "description")
    severity = require_enum(body, "severity", PUNCH_SEVERITIES)
    proj = db.projects.get(order["project_id"])
    with db.LOCK:
        if order["status"] != "DELIVERED":
            raise err("ERR_INVALID_STATE", "Punch item can only be logged on a DELIVERED order.")
        rec = db.new_common()
        rec.update({
            "order_id": oid,
            "description": description,
            "severity": severity,
            "status": "OPEN",
        })
        db.punch_items[rec["id"]] = rec
        # Posture recomputed (BLOCKING+OPEN -> FROZEN).
        services.recompute_project(proj, bump_version=True)
        return success(S.punch_item(rec), status=201)


@app.route("/punch-items/<pid>", methods=["GET"])
def get_punch_item_route(pid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "ProcurementCoordinator", "Designer", "Client"})
    rec = lookup.get_punch_item(pid)
    if role == "Client":
        lookup.check_client_owns_project(role, user_id, lookup.project_of_punch_item(rec))
    return success(S.punch_item(rec))


@app.route("/punch-items", methods=["GET"])
def list_punch_items():
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "ProcurementCoordinator", "Designer", "Client"})
    limit, offset = parse_pagination()
    order_id = request.args.get("order_id")
    items = list(db.punch_items.values())
    if order_id is not None:
        items = [pi for pi in items if pi["order_id"] == order_id]
    if role == "Client":
        owned = {p["id"] for p in db.projects.values() if p["client_user_id"] == user_id}
        owned_orders = {o["id"] for o in db.orders.values() if o["project_id"] in owned}
        items = [pi for pi in items if pi["order_id"] in owned_orders]
    page, total = lookup.paginate_sorted(items, limit, offset)
    return success_list([S.punch_item(pi) for pi in page], limit, offset, total)


@app.route("/punch-items/<pid>/resolve", methods=["POST"])
def resolve_punch_item(pid):
    user_id, role = get_identity()
    require_roles(role, {"ProcurementCoordinator"})
    pi = lookup.get_punch_item(pid)
    proj = lookup.project_of_punch_item(pi)
    with db.LOCK:
        if pi["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Punch item must be OPEN to resolve.")
        pi["status"] = "RESOLVED"
        db.touch(pi)
        services.recompute_project(proj, bump_version=True)
        return success(S.punch_item(pi))


@app.route("/punch-items/<pid>/waive", methods=["POST"])
def waive_punch_item(pid):
    user_id, role = get_identity()
    require_roles(role, {"Client"})
    pi = lookup.get_punch_item(pid)
    proj = lookup.project_of_punch_item(pi)
    lookup.check_client_owns_project(role, user_id, proj)
    with db.LOCK:
        if pi["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Punch item must be OPEN to waive.")
        pi["status"] = "WAIVED"
        db.touch(pi)
        services.recompute_project(proj, bump_version=True)
        return success(S.punch_item(pi))


# ===========================================================================
# TimeEntry
# ===========================================================================
@app.route("/projects/<pid>/time-entries", methods=["POST"])
def create_time_entry(pid):
    user_id, role = get_identity()
    require_roles(role, {"Designer"})
    proj = lookup.get_project(pid)
    body = get_json_body()
    designer_user_id = require_str(body, "designer_user_id")
    minutes = require_int(body, "minutes")
    if minutes < 1:
        raise err("ERR_INVALID_REQUEST", "minutes must be >= 1.")
    billable = optional_bool(body, "billable", True)
    with db.LOCK:
        rec = db.new_common()
        rec.update({
            "project_id": pid,
            "designer_user_id": designer_user_id,
            "minutes": minutes,
            "billable": billable,
            "status": "SUBMITTED",
        })
        db.time_entries[rec["id"]] = rec
        return success(S.time_entry(rec), status=201)


@app.route("/time-entries/<tid>", methods=["GET"])
def get_time_entry_route(tid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Designer"})
    rec = lookup.get_time_entry(tid)
    return success(S.time_entry(rec))


@app.route("/time-entries", methods=["GET"])
def list_time_entries():
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin", "Designer"})
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    items = list(db.time_entries.values())
    if project_id is not None:
        items = [t for t in items if t["project_id"] == project_id]
    page, total = lookup.paginate_sorted(items, limit, offset)
    return success_list([S.time_entry(t) for t in page], limit, offset, total)


@app.route("/time-entries/<tid>/approve", methods=["POST"])
def approve_time_entry(tid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin"})
    te = lookup.get_time_entry(tid)
    proj = lookup.project_of_time_entry(te)
    with db.LOCK:
        if te["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE", "Time entry must be SUBMITTED to approve.")
        if proj["fee_model"] != "HOURLY":
            raise err("ERR_FEE_MODEL_MISMATCH", "Approving a time entry requires fee_model=HOURLY.")
        te["status"] = "APPROVED"
        db.touch(te)
        # design_fee & budget_status & posture recomputed (cascade).
        services.recompute_project(proj, bump_version=True)
        return success(S.time_entry(te))


@app.route("/time-entries/<tid>/reject", methods=["POST"])
def reject_time_entry(tid):
    user_id, role = get_identity()
    require_roles(role, {"StudioAdmin"})
    te = lookup.get_time_entry(tid)
    with db.LOCK:
        if te["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE", "Time entry must be SUBMITTED to reject.")
        te["status"] = "REJECTED"
        db.touch(te)
        return success(S.time_entry(te))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
