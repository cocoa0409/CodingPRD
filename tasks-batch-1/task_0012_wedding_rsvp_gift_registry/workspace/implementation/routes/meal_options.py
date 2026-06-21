"""GET /meal-options/{id} — read a meal option directly."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_FORBIDDEN
from middleware import require_auth, current_role, current_user_id
from response import ok_object
from services.wedding import (
    get_meal_option_or_404,
    get_wedding_or_404,
    assert_couple_owns,
    assert_guest_self_binding,
)

bp = Blueprint("meal_options", __name__)


@bp.route("/meal-options/<mid>", methods=["GET"])
def get_meal_option(mid):
    require_auth(["Couple", "GuestSelf", "PlatformAdmin"])()
    m = get_meal_option_or_404(mid)
    w = db.weddings.get(m["wedding_id"])
    if current_role() == "Couple":
        if w:
            assert_couple_owns(w)
    elif current_role() == "GuestSelf":
        # GuestSelf must be bound to a Guest in the same wedding.
        gst = db.guests.get(current_user_id())
        if gst is None or gst.get("wedding_id") != m["wedding_id"]:
            raise APIError(ERR_FORBIDDEN, 403, "GuestSelf not bound to this wedding")
        assert_guest_self_binding(gst)
    return ok_object(m)
