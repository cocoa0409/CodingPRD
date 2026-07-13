"""Escalation acknowledgement and resolution."""

from flask import Blueprint, g

import store
from auth import endpoint, resolve_escalation
from envelope import ok
from errors import err
from services import assert_not_frozen, recompute_location, touch

bp = Blueprint("escalations", __name__)


@bp.post("/reputation/escalations/<escalation_id>/acknowledge")
@endpoint(["PlatformAdmin", "LocationManager"])
def acknowledge(escalation_id):
    esc, _review, loc = resolve_escalation(escalation_id)
    assert_not_frozen(loc)
    if esc["state"] != "OPEN":
        raise err("ERR_INVALID_STATE")

    esc["state"] = "ACKNOWLEDGED"
    esc["acknowledged_by_user_id"] = g.user_id
    touch(esc)

    # ACKNOWLEDGED still counts as open: open_escalation_count is unchanged.
    recompute_location(loc)
    return ok(store.escalation_out(esc))


@bp.post("/reputation/escalations/<escalation_id>/resolve")
@endpoint(["PlatformAdmin", "LocationManager"])
def resolve(escalation_id):
    esc, review, loc = resolve_escalation(escalation_id)
    assert_not_frozen(loc)
    if esc["state"] not in ("OPEN", "ACKNOWLEDGED"):
        raise err("ERR_INVALID_STATE")
    if review["response_state"] != "RESPONDED":
        raise err("ERR_REVIEW_NOT_RESPONDED")

    esc["state"] = "RESOLVED"
    esc["resolved_at"] = store.now()
    touch(esc)

    recompute_location(loc)
    return ok(store.escalation_out(esc))
