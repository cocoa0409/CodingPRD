"""Existence lookups (priority 3: ERR_*_NOT_FOUND, 404)."""
from db import db
from errors import ApiError


def get_service(sid):
    svc = db.services.get(sid)
    if svc is None:
        raise ApiError("ERR_SERVICE_NOT_FOUND", "Service not found.")
    return svc


def get_responder(rid):
    r = db.responders.get(rid)
    if r is None:
        raise ApiError("ERR_RESPONDER_NOT_FOUND", "Responder not found.")
    return r


def get_schedule(sid):
    s = db.schedules.get(sid)
    if s is None:
        raise ApiError("ERR_SCHEDULE_NOT_FOUND", "On-call schedule not found.")
    return s


def get_policy(pid):
    p = db.policies.get(pid)
    if p is None:
        raise ApiError("ERR_POLICY_NOT_FOUND", "Escalation policy not found.")
    return p


def get_tier(tid):
    # No dedicated tier not-found code in the catalog (PRD 2.7 / Section 5);
    # a missing single tier read is a plain 404.
    t = db.tiers.get(tid)
    if t is None:
        raise ApiError("ERR_TIER_NOT_FOUND", "Escalation tier not found.")
    return t


def get_window(wid):
    w = db.windows.get(wid)
    if w is None:
        raise ApiError("ERR_WINDOW_NOT_FOUND", "Maintenance window not found.")
    return w


def get_incident(iid):
    inc = db.incidents.get(iid)
    if inc is None:
        raise ApiError("ERR_INCIDENT_NOT_FOUND", "Incident not found.")
    return inc


def get_page_attempt(pid):
    # No dedicated page-attempt not-found code in the catalog; plain 404.
    pa = db.page_attempts.get(pid)
    if pa is None:
        raise ApiError("ERR_PAGE_ATTEMPT_NOT_FOUND", "Page attempt not found.")
    return pa


def get_war_room(wid):
    wr = db.war_rooms.get(wid)
    if wr is None:
        raise ApiError("ERR_WAR_ROOM_NOT_FOUND", "War room not found.")
    return wr


def get_postmortem(pid):
    pm = db.postmortems.get(pid)
    if pm is None:
        raise ApiError("ERR_POSTMORTEM_NOT_FOUND", "Postmortem not found.")
    return pm


def get_action_item(aid):
    ai = db.action_items.get(aid)
    if ai is None:
        raise ApiError("ERR_ACTION_ITEM_NOT_FOUND", "Action item not found.")
    return ai
