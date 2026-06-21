"""PlusOne routes: list, read, RSVP, delete."""
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
)
from middleware import require_auth, current_role, current_user_id, get_json_body
from response import ok_object, ok_array, ok_no_content, paginate
from services.pagination import parse_pagination, sort_by_created
from services.wedding import (
    get_plus_one_or_404,
    assert_couple_owns,
    assert_guest_self_binding,
    assert_not_archived,
    maybe_auto_close_rsvp,
    _remove_plus_one_seatings,
)
from services.meal import meal_count

bp = Blueprint("plus_ones", __name__)


@bp.route("/plus-ones", methods=["GET"])
def list_plus_ones():
    require_auth(["Couple", "PlatformAdmin"])()
    limit, offset = parse_pagination()
    w_id = request.args.get("wedding_id")
    meal_opt = request.args.get("meal_option_id")
    rows = list(db.plus_ones.values())
    if current_role() == "Couple":
        owned = {w["id"] for w in db.weddings.values()
                 if w.get("couple_user_id") == current_user_id()}
        rows = [p for p in rows if p.get("wedding_id") in owned]
    if w_id is not None:
        rows = [p for p in rows if p.get("wedding_id") == w_id]
    if meal_opt is not None:
        rows = [p for p in rows if p.get("meal_option_id") == meal_opt]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_array(page, limit, offset, total)


@bp.route("/plus-ones/<pid>", methods=["GET"])
def get_plus_one(pid):
    require_auth(["Couple", "GuestSelf", "PlatformAdmin"])()
    po = get_plus_one_or_404(pid)
    if current_role() == "Couple":
        w = db.weddings.get(po["wedding_id"])
        if w:
            assert_couple_owns(w)
    elif current_role() == "GuestSelf":
        # GuestSelf bound to the parent guest of this plus-one.
        parent = db.guests.get(po["guest_id"])
        if parent is None:
            raise APIError(ERR_FORBIDDEN, 403, "PlusOne parent guest not found")
        assert_guest_self_binding(parent)
    return ok_object(po)


@bp.route("/plus-ones/<pid>/rsvp", methods=["POST"])
def rsvp_plus_one(pid):
    require_auth(["Couple", "GuestSelf"])()
    po = get_plus_one_or_404(pid)
    w = db.weddings.get(po["wedding_id"])
    if w is None:
        raise APIError(ERR_INVALID_STATE, 409, "Wedding missing")
    if current_role() == "Couple":
        assert_couple_owns(w)
    else:
        parent = db.guests.get(po["guest_id"])
        if parent is None:
            raise APIError(ERR_FORBIDDEN, 403, "PlusOne parent guest not found")
        assert_guest_self_binding(parent)
    assert_not_archived(w)
    # PRD §3.1: auto-close fires on writes that hit the *wedding*; a child
    # plus-one RSVP write does not trigger it. PRD §3.2 carves out the
    # GuestSelf deadline-guard path.

    body = get_json_body()
    attending = body.get("attending")
    meal_id = body.get("meal_option_id")
    if not isinstance(attending, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "attending must be a boolean")

    cur_state = po.get("rsvp_status")
    w_state = w.get("status")

    if attending:
        # ATTENDING transition: valid sources by scaffold §1.2 — PlusOne starts
        # ATTENDING and only has ATTENDING->DECLINED. Re-setting an existing
        # ATTENDING plus-one to ATTENDING with a new meal is effectively a meal
        # change; we allow it like the guest endpoint.
        if cur_state == "DECLINED":
            # No DECLINED->ATTENDING transition defined; reject.
            raise APIError(ERR_INVALID_STATE, 409,
                           "PlusOne cannot transition from DECLINED to ATTENDING")
        # PlusOne ATTENDING set requires wedding RSVP_OPEN per the spirit of
        # the spec (the parent guest's RSVP gates this). Reject otherwise.
        if w_state != "RSVP_OPEN":
            raise APIError(ERR_INVALID_STATE, 409,
                           "Wedding must be RSVP_OPEN to set ATTENDING")
        cur = db.parse_iso(db.get_current_utc())
        deadline = db.parse_iso(w["rsvp_deadline_at"])
        if current_role() == "GuestSelf":
            if cur is None or deadline is None or not (cur < deadline):
                raise APIError(ERR_RSVP_DEADLINE_PASSED, 409, "RSVP deadline has passed")
        if not isinstance(meal_id, str) or not meal_id:
            raise APIError(ERR_INVALID_REQUEST, 400, "meal_option_id required when attending=true")
        meal = db.meal_options.get(meal_id)
        if meal is None:
            raise APIError(ERR_INVALID_REQUEST, 400, "meal_option_id refers to unknown MealOption")
        if meal.get("wedding_id") != po["wedding_id"]:
            raise APIError(ERR_CROSS_WEDDING_REFERENCE, 422,
                           "meal_option_id refers to a MealOption of a different wedding")
        if bool(po.get("is_child")) != bool(meal.get("is_kids")):
            raise APIError(ERR_KIDS_MEAL_PAIRING, 422, "kids-meal pairing violated")
        exclude_p = po["id"] if cur_state == "ATTENDING" else None
        if meal_count(po["wedding_id"], meal_id, exclude_plus_one_id=exclude_p) + 1 > int(meal["max_servings"]):
            raise APIError(ERR_MEAL_FULL, 422, "meal capacity exceeded")
        po["rsvp_status"] = "ATTENDING"
        po["meal_option_id"] = meal_id
        db.bump(po)
        return ok_object(po)

    # attending=false: -> DECLINED
    if cur_state == "DECLINED":
        raise APIError(ERR_INVALID_STATE, 409, "PlusOne is already DECLINED")
    if w_state not in ("RSVP_OPEN", "RSVP_CLOSED", "SEATED"):
        raise APIError(ERR_INVALID_STATE, 409,
                       "Wedding must be RSVP_OPEN/RSVP_CLOSED/SEATED to decline a plus-one")
    if current_role() == "GuestSelf":
        cur = db.parse_iso(db.get_current_utc())
        deadline = db.parse_iso(w["rsvp_deadline_at"])
        if cur is None or deadline is None or not (cur < deadline):
            raise APIError(ERR_RSVP_DEADLINE_PASSED, 409, "RSVP deadline has passed")
    po["rsvp_status"] = "DECLINED"
    po["meal_option_id"] = None
    db.bump(po)
    _remove_plus_one_seatings(po["id"])
    if w_state == "SEATED":
        w["status"] = "RSVP_CLOSED"
        w["seating_dirty"] = True
        db.bump(w)
    return ok_object(po)


@bp.route("/plus-ones/<pid>", methods=["DELETE"])
def delete_plus_one(pid):
    require_auth(["Couple"])()
    po = get_plus_one_or_404(pid)
    w = db.weddings.get(po["wedding_id"])
    if w is None:
        raise APIError(ERR_INVALID_STATE, 409, "Wedding missing")
    assert_couple_owns(w)
    assert_not_archived(w)
    w_state = w.get("status")
    _remove_plus_one_seatings(po["id"])
    del db.plus_ones[po["id"]]
    if w_state == "SEATED":
        w["status"] = "RSVP_CLOSED"
        w["seating_dirty"] = True
        db.bump(w)
    return ok_no_content()
