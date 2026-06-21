"""Guest routes: read, RSVP state machine, revoke, plus-ones scope."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_FORBIDDEN,
    ERR_CROSS_WEDDING_REFERENCE,
    ERR_KIDS_MEAL_PAIRING,
    ERR_MEAL_FULL,
    ERR_RSVP_DEADLINE_PASSED,
    ERR_PLUS_ONE_NOT_ALLOWED,
)
from middleware import require_auth, current_role, current_user_id, get_json_body
from response import ok_object, ok_array, paginate
from services.pagination import parse_pagination, sort_by_created
from services.wedding import (
    get_guest_or_404,
    get_wedding_or_404,
    get_meal_option_or_404,
    assert_couple_owns,
    assert_guest_self_binding,
    assert_not_archived,
    maybe_auto_close_rsvp,
    _remove_guest_seatings,
    _remove_plus_one_seatings,
)
from services.meal import meal_count

bp = Blueprint("guests", __name__)


# -------- GET /guests --------------------------------------------------------

@bp.route("/guests", methods=["GET"])
def list_guests():
    require_auth(["Couple", "PlatformAdmin"])()
    limit, offset = parse_pagination()
    meal_opt = request.args.get("meal_option_id")
    status_f = request.args.get("rsvp_status")
    rows = list(db.guests.values())
    if current_role() == "Couple":
        # Scope to weddings owned by this couple.
        owned = {w["id"] for w in db.weddings.values()
                 if w.get("couple_user_id") == current_user_id()}
        rows = [g for g in rows if g.get("wedding_id") in owned]
    if meal_opt is not None:
        rows = [g for g in rows if g.get("meal_option_id") == meal_opt]
    if status_f is not None:
        rows = [g for g in rows if g.get("rsvp_status") == status_f]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_array(page, limit, offset, total)


# -------- GET /guests/{id} ---------------------------------------------------

@bp.route("/guests/<gid>", methods=["GET"])
def get_guest(gid):
    require_auth(["Couple", "GuestSelf", "PlatformAdmin"])()
    g_row = get_guest_or_404(gid)
    w = db.weddings.get(g_row["wedding_id"])
    if current_role() == "Couple" and w:
        assert_couple_owns(w)
    elif current_role() == "GuestSelf":
        assert_guest_self_binding(g_row)
    return ok_object(g_row)


# -------- POST /guests/{id}/rsvp --------------------------------------------

@bp.route("/guests/<gid>/rsvp", methods=["POST"])
def rsvp_guest(gid):
    require_auth(["Couple", "GuestSelf"])()
    g_row = get_guest_or_404(gid)
    w = db.weddings.get(g_row["wedding_id"])
    if w is None:
        raise APIError(ERR_INVALID_STATE, 409, "Wedding missing")
    # Auth/binding by role.
    if current_role() == "Couple":
        assert_couple_owns(w)
    else:
        assert_guest_self_binding(g_row)
    assert_not_archived(w)
    # PRD §3.1: auto-close fires on writes that hit the *wedding*; a child
    # RSVP write does not trigger it. PRD §3.2 explicitly carves out the
    # GuestSelf deadline-guard path (ERR_RSVP_DEADLINE_PASSED) which would
    # be pre-empted to ERR_INVALID_STATE if we auto-closed the wedding here.

    body = get_json_body()
    attending = body.get("attending")
    meal_id = body.get("meal_option_id")
    if not isinstance(attending, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "attending must be a boolean")

    # State-machine: which transition is this?
    cur_state = g_row.get("rsvp_status")
    w_state = w.get("status")

    if attending:
        # ATTENDING transition. Valid sources: INVITED.
        # We treat ATTENDING -> ATTENDING with a possibly different meal as
        # a meal change (allowed only via PATCH per scaffold §1.4 priority 6
        # 'PATCH /guests/{id}/meal'; that PATCH endpoint isn't in §1.5 so
        # we'll accept an attending=true on an already-ATTENDING guest as a
        # meal change too, since the only way to change a meal after RSVP is
        # through this endpoint).
        if cur_state == "DECLINED":
            # Can a Couple flip a DECLINED guest to ATTENDING directly?
            # Per scaffold §1.2 Guest state machine, transitions are:
            # INVITED->ATTENDING, INVITED->DECLINED, ATTENDING->DECLINED,
            # ATTENDING->INVITED, DECLINED->INVITED. So DECLINED->ATTENDING
            # must go via revoke-rsvp first.
            raise APIError(ERR_INVALID_STATE, 409,
                           "Guest must be revoked to INVITED before attending again")

        # Required wedding state for ATTENDING transition: RSVP_OPEN (per §1.2).
        if w_state != "RSVP_OPEN":
            raise APIError(ERR_INVALID_STATE, 409,
                           "Wedding must be in RSVP_OPEN to set ATTENDING")
        # PRD §3.2: "The `Couple` is not subject to that deadline check; they
        # may RSVP a guest by proxy after the deadline up until the close
        # transition fires." The GuestSelf-specific deadline guard fires at
        # priority 13 per §2.9.
        cur = db.parse_iso(db.get_current_utc())
        deadline = db.parse_iso(w["rsvp_deadline_at"])
        if current_role() == "GuestSelf":
            if cur is None or deadline is None or not (cur < deadline):
                raise APIError(ERR_RSVP_DEADLINE_PASSED, 409,
                               "GuestSelf RSVP after rsvp_deadline_at")

        # meal_option_id required for ATTENDING.
        if not isinstance(meal_id, str) or not meal_id:
            raise APIError(ERR_INVALID_REQUEST, 400, "meal_option_id is required when attending=true")
        meal = db.meal_options.get(meal_id)
        if meal is None:
            raise APIError(ERR_INVALID_REQUEST, 400, "meal_option_id refers to unknown MealOption")
        # Cross-wedding check (priority 9).
        if meal.get("wedding_id") != g_row["wedding_id"]:
            raise APIError(ERR_CROSS_WEDDING_REFERENCE, 422,
                           "meal_option_id refers to a MealOption of a different wedding")
        # Kids-meal pairing (priority 6).
        if bool(g_row.get("is_child")) != bool(meal.get("is_kids")):
            raise APIError(ERR_KIDS_MEAL_PAIRING, 422, "kids-meal pairing violated")
        # Meal capacity (priority 10).
        # If guest is already ATTENDING with same meal, count exclusion.
        exclude_g = g_row["id"] if cur_state == "ATTENDING" else None
        if meal_count(g_row["wedding_id"], meal_id, exclude_guest_id=exclude_g) + 1 > int(meal["max_servings"]):
            raise APIError(ERR_MEAL_FULL, 422, "meal capacity exceeded")
        # Apply transition.
        g_row["rsvp_status"] = "ATTENDING"
        g_row["meal_option_id"] = meal_id
        db.bump(g_row)
        return ok_object(g_row)

    # attending=false branch: -> DECLINED
    # Per §1.2, valid wedding states for INVITED->DECLINED: RSVP_OPEN, RSVP_CLOSED.
    # For ATTENDING->DECLINED: RSVP_OPEN, RSVP_CLOSED, SEATED.
    if cur_state == "DECLINED":
        # No-op? PRD doesn't explicitly say; we treat as invalid state.
        raise APIError(ERR_INVALID_STATE, 409, "Guest is already DECLINED")
    if cur_state == "INVITED":
        if w_state not in ("RSVP_OPEN", "RSVP_CLOSED"):
            raise APIError(ERR_INVALID_STATE, 409,
                           "Wedding must be RSVP_OPEN or RSVP_CLOSED to decline an INVITED guest")
    elif cur_state == "ATTENDING":
        if w_state not in ("RSVP_OPEN", "RSVP_CLOSED", "SEATED"):
            raise APIError(ERR_INVALID_STATE, 409,
                           "Wedding must be RSVP_OPEN/RSVP_CLOSED/SEATED to decline an ATTENDING guest")

    # GuestSelf deadline check (priority 13).
    if current_role() == "GuestSelf":
        cur = db.parse_iso(db.get_current_utc())
        deadline = db.parse_iso(w["rsvp_deadline_at"])
        if cur is None or deadline is None or not (cur < deadline):
            raise APIError(ERR_RSVP_DEADLINE_PASSED, 409, "RSVP deadline has passed")

    # Apply decline + cascade.
    g_row["rsvp_status"] = "DECLINED"
    g_row["meal_option_id"] = None
    db.bump(g_row)

    # Cascade: every PlusOne under this guest -> DECLINED.
    for po in list(db.plus_ones.values()):
        if po.get("guest_id") != g_row["id"]:
            continue
        if po.get("rsvp_status") == "ATTENDING":
            po["rsvp_status"] = "DECLINED"
            po["meal_option_id"] = None
            db.bump(po)
            _remove_plus_one_seatings(po["id"])

    # If wedding was SEATED, remove this guest's seating + auto-revert.
    if w_state == "SEATED":
        _remove_guest_seatings(g_row["id"])
        w["status"] = "RSVP_CLOSED"
        w["seating_dirty"] = True
        db.bump(w)
    return ok_object(g_row)


# -------- POST /guests/{id}/revoke-rsvp --------------------------------------

@bp.route("/guests/<gid>/revoke-rsvp", methods=["POST"])
def revoke_rsvp(gid):
    require_auth(["Couple"])()
    g_row = get_guest_or_404(gid)
    w = db.weddings.get(g_row["wedding_id"])
    if w is None:
        raise APIError(ERR_INVALID_STATE, 409, "Wedding missing")
    assert_couple_owns(w)
    assert_not_archived(w)
    maybe_auto_close_rsvp(w)
    if w.get("status") != "RSVP_OPEN":
        raise APIError(ERR_INVALID_STATE, 409, "Wedding must be RSVP_OPEN to revoke RSVP")
    cur = db.parse_iso(db.get_current_utc())
    deadline = db.parse_iso(w["rsvp_deadline_at"])
    if cur is None or deadline is None or not (cur < deadline):
        raise APIError(ERR_INVALID_STATE, 409,
                       "current_utc must be strictly before rsvp_deadline_at to revoke")

    cur_state = g_row.get("rsvp_status")
    if cur_state == "INVITED":
        raise APIError(ERR_INVALID_STATE, 409, "Guest is already INVITED")
    if cur_state == "ATTENDING":
        # Reject if any PlusOne under this guest is non-INVITED.
        for po in db.plus_ones.values():
            if po.get("guest_id") == g_row["id"] and po.get("rsvp_status") != "INVITED":
                raise APIError(ERR_INVALID_STATE, 409,
                               "Delete the PlusOne first before revoking this guest's RSVP")
        g_row["rsvp_status"] = "INVITED"
        g_row["meal_option_id"] = None
        db.bump(g_row)
        return ok_object(g_row)
    if cur_state == "DECLINED":
        g_row["rsvp_status"] = "INVITED"
        db.bump(g_row)
        return ok_object(g_row)
    raise APIError(ERR_INVALID_STATE, 409, "Invalid guest state")


# -------- POST /guests/{id}/plus-ones (create) -------------------------------

@bp.route("/guests/<gid>/plus-ones", methods=["POST"])
def create_plus_one(gid):
    require_auth(["Couple"])()
    g_row = get_guest_or_404(gid)
    w = db.weddings.get(g_row["wedding_id"])
    if w is None:
        raise APIError(ERR_INVALID_STATE, 409, "Wedding missing")
    assert_couple_owns(w)
    assert_not_archived(w)
    body = get_json_body()
    full_name = body.get("full_name")
    is_child = body.get("is_child", False)
    meal_id = body.get("meal_option_id")
    if not isinstance(full_name, str) or not full_name:
        raise APIError(ERR_INVALID_REQUEST, 400, "full_name is required")
    if not isinstance(is_child, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "is_child must be a boolean")

    # Plus-one eligibility (priority 8).
    if not g_row.get("plus_one_allowed"):
        raise APIError(ERR_PLUS_ONE_NOT_ALLOWED, 422, "Guest is not allowed a plus-one")
    for po in db.plus_ones.values():
        if po.get("guest_id") == g_row["id"]:
            raise APIError(ERR_PLUS_ONE_NOT_ALLOWED, 422,
                           "Guest already has a PlusOne (one-shot)")

    # Optional meal_option_id checks.
    if meal_id is not None:
        if not isinstance(meal_id, str) or not meal_id:
            raise APIError(ERR_INVALID_REQUEST, 400, "meal_option_id must be a non-empty string when provided")
        meal = db.meal_options.get(meal_id)
        if meal is None:
            raise APIError(ERR_INVALID_REQUEST, 400, "meal_option_id refers to unknown MealOption")
        if meal.get("wedding_id") != g_row["wedding_id"]:
            raise APIError(ERR_CROSS_WEDDING_REFERENCE, 422,
                           "meal_option_id refers to a MealOption of a different wedding")
        if bool(is_child) != bool(meal.get("is_kids")):
            raise APIError(ERR_KIDS_MEAL_PAIRING, 422, "kids-meal pairing violated")
        # Meal capacity: plus-one starts in ATTENDING by default.
        if meal_count(g_row["wedding_id"], meal_id) + 1 > int(meal["max_servings"]):
            raise APIError(ERR_MEAL_FULL, 422, "meal capacity exceeded")

    po = {
        "guest_id": g_row["id"],
        "wedding_id": g_row["wedding_id"],
        "full_name": full_name,
        "is_child": is_child,
        "rsvp_status": "ATTENDING",
        "meal_option_id": meal_id if meal_id else None,
    }
    db.stamp_common(po)
    db.plus_ones[po["id"]] = po
    return ok_object(po, 201)


# -------- GET /guests/{id}/plus-ones (list) ---------------------------------

@bp.route("/guests/<gid>/plus-ones", methods=["GET"])
def list_plus_ones_of_guest(gid):
    require_auth(["Couple", "GuestSelf", "PlatformAdmin"])()
    g_row = get_guest_or_404(gid)
    if current_role() == "Couple":
        w = db.weddings.get(g_row["wedding_id"])
        if w:
            assert_couple_owns(w)
    elif current_role() == "GuestSelf":
        assert_guest_self_binding(g_row)
    limit, offset = parse_pagination()
    rows = [p for p in db.plus_ones.values() if p.get("guest_id") == g_row["id"]]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_array(page, limit, offset, total)
