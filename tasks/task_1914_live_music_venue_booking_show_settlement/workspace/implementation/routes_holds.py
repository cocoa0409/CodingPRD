"""DateHolds: placement, challenge, confirm (OCC), release (PRD 3.2)."""

from datetime import timedelta

from flask import Blueprint, g, request

import store
from domain import (CHALLENGE_WINDOW_HOURS, HOLD_TTL_HOURS, PRIORITY_RANK,
                    can_confirm_active)
from envelope import created, ok
from errors import (already_terminal, biz, forbidden, invalid_state, not_found,
                    stale_version)
from helpers import (body, filter_eq, get_child, get_show, list_response,
                     lookup, req_enum, req_expected_show_version, req_str,
                     require_roles, ser_hold)

bp = Blueprint("holds", __name__)

READ_ROLES = ("VenueManager", "BookingAgent", "Promoter")
TERMINAL_HOLDS = {"CONFIRMED", "RELEASED", "EXPIRED"}


def _place_hold(show, priority, agent_id):
    h = store.new_common({
        "show_id": show["id"],
        "priority": priority,
        "status": "ACTIVE",
        "hold_expires_at_utc": store.mint_stamp() + timedelta(hours=HOLD_TTL_HOURS[priority]),
        "challenge_window_ends_at_utc": None,
        "booked_by_agent_id": agent_id,
    })
    store.date_holds[h["id"]] = h
    return h


@bp.get("/date-holds/<hid>")
def get_hold_top(hid):
    require_roles(*READ_ROLES)
    return ok(ser_hold(lookup(store.date_holds, hid, "DateHold")))


@bp.get("/date-holds")
def list_holds_top():
    require_roles(*READ_ROLES)
    items = list(store.date_holds.values())
    items = filter_eq(items, "show_id", request.args.get("show_id"))
    items = filter_eq(items, "booked_by_agent_id", request.args.get("booked_by_agent_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    items = filter_eq(items, "priority", request.args.get("priority"))
    return list_response(items, ser_hold)


@bp.post("/shows/<sid>/date-holds")
def place_hold(sid):
    require_roles("BookingAgent")
    show = get_show(sid)
    b = body()
    priority = req_enum(b, "priority", ("P1", "P2", "COURTESY"))
    agent_id = req_str(b, "booked_by_agent_id")
    h = _place_hold(show, priority, agent_id)
    return created(ser_hold(h))


@bp.get("/shows/<sid>/date-holds")
def list_holds(sid):
    require_roles(*READ_ROLES)
    show = get_show(sid)
    items = [h for h in store.date_holds.values() if h["show_id"] == show["id"]]
    items = filter_eq(items, "status", request.args.get("status"))
    return list_response(items, ser_hold)


@bp.get("/shows/<sid>/date-holds/<hid>")
def get_hold(sid, hid):
    require_roles(*READ_ROLES)
    show = get_show(sid)
    return ok(ser_hold(get_child(store.date_holds, show, hid, "DateHold")))


@bp.post("/shows/<sid>/date-holds/<hid>/challenge")
def challenge_hold(sid, hid):
    require_roles("BookingAgent")
    show = get_show(sid)
    hold = get_child(store.date_holds, show, hid, "DateHold")
    b = body()
    challenger_id = req_str(b, "challenger_agent_id")
    challenger_priority = req_enum(b, "challenger_priority", ("P1", "P2", "COURTESY"))
    # From-state (challenge is defined only from ACTIVE)
    if hold["status"] != "ACTIVE":
        if hold["status"] in TERMINAL_HOLDS:
            raise already_terminal("Hold is already in a terminal state")
        raise invalid_state("Only an ACTIVE hold can be challenged")
    # Ownership: the caller must be the named challenger (PRD 2.1)
    if g.user_id != challenger_id:
        raise forbidden("challenger_agent_id must match the caller's X-User-ID")
    # The challenger must be a different agent than the hold's owner
    if challenger_id == hold["booked_by_agent_id"]:
        raise invalid_state("A hold cannot be challenged by the agent that placed it")
    # Rule 10: strictly higher priority
    if PRIORITY_RANK[challenger_priority] <= PRIORITY_RANK[hold["priority"]]:
        raise biz("ERR_CHALLENGE_PRIORITY_TOO_LOW",
                  "Challenge priority must be strictly higher than the target hold's priority")
    hold["status"] = "CHALLENGED"
    hold["challenge_window_ends_at_utc"] = store.mint_stamp() + timedelta(hours=CHALLENGE_WINDOW_HOURS)
    store.touch(hold)
    new_hold = _place_hold(show, challenger_priority, challenger_id)
    return created(ser_hold(new_hold))


@bp.post("/shows/<sid>/date-holds/<hid>/confirm")
def confirm_hold(sid, hid):
    require_roles("BookingAgent")
    show = get_show(sid)
    hold = get_child(store.date_holds, show, hid, "DateHold")
    # From-state: CONFIRMED/RELEASED are terminal with no defined transitions;
    # an EXPIRED hold is one whose deadline has already passed — confirming it
    # is "confirming at or past the applicable deadline" (PRD 3.2), so it flows
    # to the rule-9 expiry check below rather than the terminal-state branch.
    if hold["status"] in ("CONFIRMED", "RELEASED"):
        raise already_terminal("Hold is already in a terminal state")
    if hold["status"] not in ("ACTIVE", "CHALLENGED", "EXPIRED"):
        raise invalid_state("Hold is not in a confirmable state")
    # Ownership: only the placing agent confirms
    if g.user_id != hold["booked_by_agent_id"]:
        raise forbidden("Only the agent that placed the hold may confirm it")
    # Competing-hold precondition (unchallenged flavor only)
    if hold["status"] == "ACTIVE" and not can_confirm_active(hold, show):
        raise invalid_state("A competing hold with higher or equal-earlier priority blocks confirmation")
    # OCC (rule 6) — precedes expiry timing (rule 9)
    expected = req_expected_show_version(body())
    if expected != show["version"]:
        raise stale_version()
    # Rule 9: expiry timing (challenge window for CHALLENGED, TTL for ACTIVE;
    # a hold already swept to EXPIRED by the lazy clock has by definition
    # passed its applicable deadline)
    now = store.now()
    if hold["status"] == "EXPIRED":
        raise biz("ERR_HOLD_EXPIRED", "Hold has expired")
    if hold["status"] == "CHALLENGED":
        if now >= hold["challenge_window_ends_at_utc"]:
            raise biz("ERR_HOLD_EXPIRED", "Challenge window has closed")
    else:
        if now >= hold["hold_expires_at_utc"]:
            raise biz("ERR_HOLD_EXPIRED", "Hold has expired")
    # Cascade: confirm hold, confirm show, release all competitors on the slot
    hold["status"] = "CONFIRMED"
    store.touch(hold)
    show["status"] = "CONFIRMED"
    show["hold_priority"] = hold["priority"]
    store.bump_show(show)
    from domain import holds_on_slot
    for other in holds_on_slot(show):
        if other["id"] != hold["id"] and other["status"] in ("ACTIVE", "CHALLENGED"):
            other["status"] = "RELEASED"
            store.touch(other)
    return ok(ser_hold(hold))


@bp.post("/shows/<sid>/date-holds/<hid>/release")
def release_hold(sid, hid):
    require_roles("BookingAgent")
    show = get_show(sid)
    hold = get_child(store.date_holds, show, hid, "DateHold")
    if hold["status"] not in ("ACTIVE", "CHALLENGED"):
        raise already_terminal("Hold is already in a terminal state")
    if g.user_id != hold["booked_by_agent_id"]:
        raise forbidden("Only the agent that placed the hold may release it")
    hold["status"] = "RELEASED"
    store.touch(hold)
    return ok(ser_hold(hold))
