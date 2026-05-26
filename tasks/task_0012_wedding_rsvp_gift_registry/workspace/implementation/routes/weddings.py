"""Wedding routes: CRUD + lifecycle transitions + reports."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_FORBIDDEN,
)
from middleware import require_auth, current_role, current_user_id, get_json_body
from response import ok_object, ok_array, paginate
from services.pagination import parse_pagination, sort_by_created
from services.wedding import (
    get_wedding_or_404,
    assert_couple_owns,
    assert_not_archived,
    maybe_auto_close_rsvp,
    _do_close_rsvp,
    _compute_seating_dirty,
    recompute_total_capacity,
)
from services.meal import meal_summary
from services.seating import auto_seat_plan
from services.thankyou import thank_you_report


bp = Blueprint("weddings", __name__)


# -------- POST /weddings ------------------------------------------------------

@bp.route("/weddings", methods=["POST"])
def create_wedding():
    require_auth(["Couple"])()
    body = get_json_body()
    couple_user_id = body.get("couple_user_id")
    title = body.get("title")
    ceremony_at = body.get("ceremony_at")
    rsvp_deadline_at = body.get("rsvp_deadline_at")

    if not isinstance(couple_user_id, str) or not couple_user_id:
        raise APIError(ERR_INVALID_REQUEST, 400, "couple_user_id is required")
    if not isinstance(title, str) or not title:
        raise APIError(ERR_INVALID_REQUEST, 400, "title is required")
    if not isinstance(ceremony_at, str) or not ceremony_at:
        raise APIError(ERR_INVALID_REQUEST, 400, "ceremony_at is required")
    if not isinstance(rsvp_deadline_at, str) or not rsvp_deadline_at:
        raise APIError(ERR_INVALID_REQUEST, 400, "rsvp_deadline_at is required")
    try:
        c_dt = db.parse_iso(ceremony_at)
        r_dt = db.parse_iso(rsvp_deadline_at)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400, "ceremony_at/rsvp_deadline_at must be ISO-8601")
    if c_dt is None or r_dt is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "ceremony_at/rsvp_deadline_at must be ISO-8601")
    if not (r_dt < c_dt):
        raise APIError(ERR_INVALID_REQUEST, 400, "rsvp_deadline_at must be strictly before ceremony_at")

    # Couple ownership: the value goes in as-is, but the field becomes the
    # ownership marker (compared to X-User-ID on subsequent writes).
    wedding = {
        "couple_user_id": couple_user_id,
        "title": title,
        "ceremony_at": ceremony_at,
        "rsvp_deadline_at": rsvp_deadline_at,
        "status": "DRAFT",
        "seating_dirty": False,
        "total_capacity": 0,
    }
    db.stamp_common(wedding)
    db.weddings[wedding["id"]] = wedding
    return ok_object(wedding, 201)


# -------- GET /weddings/{id} -------------------------------------------------

@bp.route("/weddings/<wid>", methods=["GET"])
def get_wedding(wid):
    require_auth(["Couple", "PlatformAdmin"])()
    w = get_wedding_or_404(wid)
    if current_role() == "Couple":
        assert_couple_owns(w)
    return ok_object(w)


# -------- GET /weddings ------------------------------------------------------

@bp.route("/weddings", methods=["GET"])
def list_weddings():
    require_auth(["Couple", "PlatformAdmin"])()
    limit, offset = parse_pagination()
    rows = list(db.weddings.values())
    couple_filter = request.args.get("couple_user_id")
    if couple_filter is not None:
        rows = [r for r in rows if r.get("couple_user_id") == couple_filter]
    if current_role() == "Couple":
        rows = [r for r in rows if r.get("couple_user_id") == current_user_id()]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_array(page, limit, offset, total)


# -------- POST /weddings/{id}/open-rsvp --------------------------------------

@bp.route("/weddings/<wid>/open-rsvp", methods=["POST"])
def open_rsvp(wid):
    require_auth(["Couple"])()
    w = get_wedding_or_404(wid)
    assert_couple_owns(w)
    assert_not_archived(w)
    if w.get("status") != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Wedding must be in DRAFT to open RSVPs")
    cur = db.parse_iso(db.get_current_utc())
    c_at = db.parse_iso(w["ceremony_at"])
    r_at = db.parse_iso(w["rsvp_deadline_at"])
    if cur is None or not (c_at > cur):
        raise APIError(ERR_INVALID_STATE, 409, "ceremony_at must be strictly after current_utc")
    if not (r_at > cur and r_at < c_at):
        raise APIError(
            ERR_INVALID_STATE, 409,
            "rsvp_deadline_at must be strictly after current_utc and strictly before ceremony_at",
        )
    # >=1 adult MealOption required (is_kids=false).
    has_adult_meal = any(
        m.get("wedding_id") == w["id"] and not m.get("is_kids")
        for m in db.meal_options.values()
    )
    if not has_adult_meal:
        raise APIError(ERR_INVALID_STATE, 409, "wedding must have at least one adult MealOption")
    w["status"] = "RSVP_OPEN"
    db.bump(w)
    return ok_object(w)


# -------- POST /weddings/{id}/close-rsvp --------------------------------------

@bp.route("/weddings/<wid>/close-rsvp", methods=["POST"])
def close_rsvp(wid):
    require_auth(["Couple"])()
    w = get_wedding_or_404(wid)
    assert_couple_owns(w)
    assert_not_archived(w)
    if w.get("status") != "RSVP_OPEN":
        raise APIError(ERR_INVALID_STATE, 409, "Wedding must be in RSVP_OPEN to close")
    _do_close_rsvp(w)
    return ok_object(w)


# -------- POST /weddings/{id}/finalize-seating -------------------------------

@bp.route("/weddings/<wid>/finalize-seating", methods=["POST"])
def finalize_seating(wid):
    require_auth(["Couple"])()
    w = get_wedding_or_404(wid)
    assert_couple_owns(w)
    assert_not_archived(w)
    body = get_json_body()
    expected = body.get("expected_wedding_version")
    if expected is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "expected_wedding_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "expected_wedding_version must be an integer")

    # Auto-close if deadline crossed (note: opens may be RSVP_OPEN still).
    maybe_auto_close_rsvp(w)
    if w.get("status") != "RSVP_CLOSED":
        raise APIError(ERR_INVALID_STATE, 409, "Wedding must be in RSVP_CLOSED to finalize seating")

    # Preconditions: every ATTENDING guest/plus-one referenced exactly once,
    # no table over capacity, no kids_only violations.
    attendees = []
    for gst in db.guests.values():
        if gst.get("wedding_id") == w["id"] and gst.get("rsvp_status") == "ATTENDING":
            attendees.append(("GUEST", gst["id"], gst.get("is_child", False)))
    for po in db.plus_ones.values():
        if po.get("wedding_id") == w["id"] and po.get("rsvp_status") == "ATTENDING":
            attendees.append(("PLUS_ONE", po["id"], po.get("is_child", False)))

    # Group seating assignments by attendee.
    sa_for_wedding = [sa for sa in db.seating_assignments.values() if sa.get("wedding_id") == w["id"]]
    sa_index = {}
    for sa in sa_for_wedding:
        k = (sa["assignee_type"], sa["assignee_id"])
        sa_index.setdefault(k, []).append(sa)

    for atype, aid, _ in attendees:
        rows = sa_index.get((atype, aid), [])
        if len(rows) != 1:
            raise APIError(ERR_INVALID_STATE, 409, f"{atype} {aid} is not seated exactly once")

    # OCC check.
    if expected != w.get("version"):
        from errors import ERR_STALE_VERSION
        raise APIError(ERR_STALE_VERSION, 412, "expected_wedding_version mismatch")

    # Table-capacity and kids_only checks.
    per_table_count = {}
    for sa in sa_for_wedding:
        per_table_count[sa["table_id"]] = per_table_count.get(sa["table_id"], 0) + 1
    for t in db.tables.values():
        if t.get("wedding_id") != w["id"]:
            continue
        if per_table_count.get(t["id"], 0) > int(t["capacity"]):
            raise APIError(ERR_INVALID_STATE, 409, f"Table {t['id']} is over capacity")
        if t.get("kids_only"):
            for sa in sa_for_wedding:
                if sa["table_id"] != t["id"]:
                    continue
                # Check assignee is_child.
                if sa["assignee_type"] == "GUEST":
                    a = db.guests.get(sa["assignee_id"])
                else:
                    a = db.plus_ones.get(sa["assignee_id"])
                if not (a and a.get("is_child")):
                    raise APIError(ERR_INVALID_STATE, 409, "kids_only table has non-child assignee")

    w["status"] = "SEATED"
    w["seating_dirty"] = False
    db.bump(w)
    return ok_object(w)


# -------- POST /weddings/{id}/archive ----------------------------------------

@bp.route("/weddings/<wid>/archive", methods=["POST"])
def archive_wedding(wid):
    require_auth(["Couple", "PlatformAdmin"])()
    w = get_wedding_or_404(wid)
    if current_role() == "Couple":
        assert_couple_owns(w)
    if w.get("status") != "SEATED":
        raise APIError(ERR_INVALID_STATE, 409, "Wedding must be in SEATED to archive")
    cur = db.parse_iso(db.get_current_utc())
    c_at = db.parse_iso(w["ceremony_at"])
    if cur is None or not (cur > c_at):
        raise APIError(ERR_INVALID_STATE, 409, "current_utc must be strictly after ceremony_at")
    w["status"] = "ARCHIVED"
    db.bump(w)
    # Cascade: every OPEN/FULFILLED RegistryItem of this wedding -> ARCHIVED.
    for ri in db.registry_items.values():
        if ri.get("wedding_id") != w["id"]:
            continue
        if ri.get("status") in ("OPEN", "FULFILLED"):
            ri["status"] = "ARCHIVED"
            db.bump(ri)
    return ok_object(w)


# -------- GET /weddings/{id}/meal-summary ------------------------------------

@bp.route("/weddings/<wid>/meal-summary", methods=["GET"])
def get_meal_summary(wid):
    require_auth(["Couple", "PlatformAdmin"])()
    w = get_wedding_or_404(wid)
    if current_role() == "Couple":
        assert_couple_owns(w)
    return ok_object(meal_summary(wid))


# -------- GET /weddings/{id}/auto-seat (dry-run) -----------------------------

@bp.route("/weddings/<wid>/auto-seat", methods=["GET"])
def auto_seat_dry_run(wid):
    require_auth(["Couple"])()
    w = get_wedding_or_404(wid)
    assert_couple_owns(w)
    plan = auto_seat_plan(wid)
    return ok_object(plan)


# -------- POST /weddings/{id}/auto-seat (commit) -----------------------------

@bp.route("/weddings/<wid>/auto-seat", methods=["POST"])
def auto_seat_commit(wid):
    require_auth(["Couple"])()
    w = get_wedding_or_404(wid)
    assert_couple_owns(w)
    assert_not_archived(w)
    if w.get("status") not in ("RSVP_CLOSED", "SEATED"):
        raise APIError(ERR_INVALID_STATE, 409,
                       "auto-seat commit requires wedding in RSVP_CLOSED or SEATED")
    plan = auto_seat_plan(wid)
    # Delete every existing SeatingAssignment for this wedding.
    for sa_id, sa in list(db.seating_assignments.items()):
        if sa.get("wedding_id") == wid:
            del db.seating_assignments[sa_id]
    # Create rows from the plan.
    for entry in plan["plan"]:
        sa = {
            "wedding_id": wid,
            "table_id": entry["table_id"],
            "assignee_type": entry["assignee_type"],
            "assignee_id": entry["assignee_id"],
        }
        db.stamp_common(sa)
        db.seating_assignments[sa["id"]] = sa
    # If wedding was SEATED, revert to RSVP_CLOSED.
    if w.get("status") == "SEATED":
        w["status"] = "RSVP_CLOSED"
    w["seating_dirty"] = True
    db.bump(w)
    return ok_object(plan)


# -------- GET /weddings/{id}/thank-you-report -------------------------------

@bp.route("/weddings/<wid>/thank-you-report", methods=["GET"])
def get_thank_you_report(wid):
    require_auth(["Couple"])()
    w = get_wedding_or_404(wid)
    assert_couple_owns(w)
    return ok_object(thank_you_report(wid))


# =============================================================================
# MealOption routes (scoped under /weddings/{id})
# =============================================================================

@bp.route("/weddings/<wid>/meal-options", methods=["POST"])
def create_meal_option(wid):
    require_auth(["Couple"])()
    w = get_wedding_or_404(wid)
    assert_couple_owns(w)
    assert_not_archived(w)
    body = get_json_body()
    code = body.get("code")
    label = body.get("label")
    is_kids = body.get("is_kids", False)
    max_servings = body.get("max_servings")
    if not isinstance(code, str) or not code:
        raise APIError(ERR_INVALID_REQUEST, 400, "code is required")
    if not isinstance(label, str) or not label:
        raise APIError(ERR_INVALID_REQUEST, 400, "label is required")
    if not isinstance(is_kids, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "is_kids must be a boolean")
    if not isinstance(max_servings, int) or isinstance(max_servings, bool) or max_servings < 1:
        raise APIError(ERR_INVALID_REQUEST, 400, "max_servings must be an integer >= 1")
    # Uniqueness of code within wedding.
    for m in db.meal_options.values():
        if m.get("wedding_id") == wid and m.get("code") == code:
            raise APIError(ERR_INVALID_REQUEST, 400, "MealOption code must be unique within the wedding")
    meal = {
        "wedding_id": wid,
        "code": code,
        "label": label,
        "is_kids": is_kids,
        "max_servings": max_servings,
    }
    db.stamp_common(meal)
    db.meal_options[meal["id"]] = meal
    return ok_object(meal, 201)


@bp.route("/weddings/<wid>/meal-options", methods=["GET"])
def list_meal_options(wid):
    require_auth(["Couple", "GuestSelf", "PlatformAdmin"])()
    w = get_wedding_or_404(wid)
    if current_role() == "Couple":
        assert_couple_owns(w)
    elif current_role() == "GuestSelf":
        # The token-bound guest must belong to this wedding.
        gst = db.guests.get(current_user_id())
        if gst is None or gst.get("wedding_id") != wid:
            raise APIError(ERR_FORBIDDEN, 403, "GuestSelf not bound to this wedding")
        from services.wedding import assert_guest_self_binding
        assert_guest_self_binding(gst)
    limit, offset = parse_pagination()
    rows = [m for m in db.meal_options.values() if m.get("wedding_id") == wid]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_array(page, limit, offset, total)


# =============================================================================
# Table routes
# =============================================================================

@bp.route("/weddings/<wid>/tables", methods=["POST"])
def create_table(wid):
    require_auth(["Couple"])()
    w = get_wedding_or_404(wid)
    assert_couple_owns(w)
    assert_not_archived(w)
    body = get_json_body()
    table_number = body.get("table_number")
    capacity = body.get("capacity")
    kids_only = body.get("kids_only", False)
    if not isinstance(table_number, int) or isinstance(table_number, bool) or table_number < 1:
        raise APIError(ERR_INVALID_REQUEST, 400, "table_number must be an integer >= 1")
    if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
        raise APIError(ERR_INVALID_REQUEST, 400, "capacity must be an integer >= 1")
    if not isinstance(kids_only, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "kids_only must be a boolean")
    # Uniqueness of table_number within wedding.
    for t in db.tables.values():
        if t.get("wedding_id") == wid and t.get("table_number") == table_number:
            raise APIError(ERR_INVALID_REQUEST, 400, "table_number must be unique within the wedding")
    tbl = {
        "wedding_id": wid,
        "table_number": table_number,
        "capacity": capacity,
        "kids_only": kids_only,
    }
    db.stamp_common(tbl)
    db.tables[tbl["id"]] = tbl
    # Recompute wedding.total_capacity; bump version.
    w["total_capacity"] = recompute_total_capacity(wid)
    db.bump(w)
    return ok_object(tbl, 201)


@bp.route("/weddings/<wid>/tables", methods=["GET"])
def list_tables(wid):
    require_auth(["Couple", "PlatformAdmin"])()
    w = get_wedding_or_404(wid)
    if current_role() == "Couple":
        assert_couple_owns(w)
    limit, offset = parse_pagination()
    rows = [t for t in db.tables.values() if t.get("wedding_id") == wid]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_array(page, limit, offset, total)


# =============================================================================
# Guest creation/list scoped under /weddings/{id}
# =============================================================================

@bp.route("/weddings/<wid>/guests", methods=["POST"])
def create_guest(wid):
    require_auth(["Couple"])()
    w = get_wedding_or_404(wid)
    assert_couple_owns(w)
    assert_not_archived(w)
    body = get_json_body()
    full_name = body.get("full_name")
    email = body.get("email")
    is_child = body.get("is_child", False)
    plus_one_allowed = body.get("plus_one_allowed", False)
    if not isinstance(full_name, str) or not full_name:
        raise APIError(ERR_INVALID_REQUEST, 400, "full_name is required")
    if not isinstance(email, str) or not email:
        raise APIError(ERR_INVALID_REQUEST, 400, "email is required")
    if not isinstance(is_child, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "is_child must be a boolean")
    if not isinstance(plus_one_allowed, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "plus_one_allowed must be a boolean")
    # Case-insensitive email uniqueness within wedding.
    el = email.lower()
    for x in db.guests.values():
        if x.get("wedding_id") == wid and x.get("email", "").lower() == el:
            raise APIError(ERR_INVALID_REQUEST, 400, "email must be unique within the wedding (case-insensitive)")
    gst = {
        "wedding_id": wid,
        "full_name": full_name,
        "email": email,
        "is_child": is_child,
        "plus_one_allowed": plus_one_allowed,
        "rsvp_status": "INVITED",
        "meal_option_id": None,
        "invitation_token": db.new_token(),
    }
    db.stamp_common(gst)
    db.guests[gst["id"]] = gst
    return ok_object(gst, 201)


@bp.route("/weddings/<wid>/guests", methods=["GET"])
def list_guests_of_wedding(wid):
    require_auth(["Couple", "PlatformAdmin"])()
    w = get_wedding_or_404(wid)
    if current_role() == "Couple":
        assert_couple_owns(w)
    limit, offset = parse_pagination()
    status_filter = request.args.get("rsvp_status")
    rows = [g for g in db.guests.values() if g.get("wedding_id") == wid]
    if status_filter is not None:
        rows = [g for g in rows if g.get("rsvp_status") == status_filter]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_array(page, limit, offset, total)


# =============================================================================
# RegistryItem creation/list scoped under /weddings/{id}
# =============================================================================

@bp.route("/weddings/<wid>/registry-items", methods=["POST"])
def create_registry_item(wid):
    require_auth(["Couple"])()
    w = get_wedding_or_404(wid)
    assert_couple_owns(w)
    assert_not_archived(w)
    body = get_json_body()
    sku = body.get("sku")
    title = body.get("title")
    target_quantity = body.get("target_quantity")
    unit_price_cents = body.get("unit_price_cents")
    if not isinstance(sku, str) or not sku:
        raise APIError(ERR_INVALID_REQUEST, 400, "sku is required")
    if not isinstance(title, str) or not title:
        raise APIError(ERR_INVALID_REQUEST, 400, "title is required")
    if not isinstance(target_quantity, int) or isinstance(target_quantity, bool) or target_quantity < 1:
        raise APIError(ERR_INVALID_REQUEST, 400, "target_quantity must be an integer >= 1")
    if not isinstance(unit_price_cents, int) or isinstance(unit_price_cents, bool) or unit_price_cents < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "unit_price_cents must be an integer >= 0")
    # Uniqueness of sku within wedding.
    for r in db.registry_items.values():
        if r.get("wedding_id") == wid and r.get("sku") == sku:
            raise APIError(ERR_INVALID_REQUEST, 400, "sku must be unique within the wedding")
    ri = {
        "wedding_id": wid,
        "sku": sku,
        "title": title,
        "target_quantity": target_quantity,
        "unit_price_cents": unit_price_cents,
        "status": "OPEN",
        "fulfilled_quantity": 0,
        "pending_quantity": 0,
    }
    db.stamp_common(ri)
    db.registry_items[ri["id"]] = ri
    return ok_object(ri, 201)


@bp.route("/weddings/<wid>/registry-items", methods=["GET"])
def list_registry_items(wid):
    require_auth(["Couple", "PlatformIntegration", "PlatformAdmin"])()
    w = get_wedding_or_404(wid)
    if current_role() == "Couple":
        assert_couple_owns(w)
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    rows = [r for r in db.registry_items.values() if r.get("wedding_id") == wid]
    if status_filter is not None:
        rows = [r for r in rows if r.get("status") == status_filter]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_array(page, limit, offset, total)
