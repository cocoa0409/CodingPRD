"""DoorZone, AccessGrant and AccessEvent endpoints (PRD 3.8)."""

from flask import Blueprint, g, request

from db import store
from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE_TRANSITION, ERR_DUPLICATE_NATURAL_KEY,
    ERR_CARD_NOT_ACTIVE, ERR_GRANT_OVERLAP,
)
from middleware import (
    authenticate, require_roles, get_body, v_str, v_enum, v_dt, find_or_404,
    pub, paginate, fmt_dt,
)
from response import success, now_iso
from services.core import new_row, touch, clock, dt_of, lazy_expire_card, lazy_expire_grant

bp = Blueprint("access", __name__)

SECURITY_LEVELS = {"STANDARD", "ELEVATED", "RESTRICTED"}
LEVEL_ORDINAL = {"STANDARD": 1, "ELEVATED": 2, "RESTRICTED": 3}
DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _validate_windows(windows):
    if not isinstance(windows, list) or len(windows) == 0:
        err(ERR_VALIDATION, "access_windows must be a non-empty list")
    for w in windows:
        if not isinstance(w, dict):
            err(ERR_VALIDATION, "each access window must be an object")
        dow = w.get("day_of_week")
        if dow not in DAYS:
            err(ERR_VALIDATION, "day_of_week must be MON..SUN")
        start = w.get("start_minute")
        end = w.get("end_minute")
        if isinstance(start, bool) or not isinstance(start, int) \
                or start < 0 or start > 1439:
            err(ERR_VALIDATION, "start_minute must be an integer in 0..1439")
        if isinstance(end, bool) or not isinstance(end, int) \
                or end < 1 or end > 1440:
            err(ERR_VALIDATION, "end_minute must be an integer in 1..1440")
        if end <= start:
            err(ERR_VALIDATION, "end_minute must be greater than start_minute")


# ---------------------------------------------------------------- door zones
@bp.route("/api/door-zones", methods=["POST"])
def create_zone():
    authenticate()
    require_roles("SecurityOfficer")
    body = get_body()
    zone_code = v_str(body, "zone_code")
    building = v_str(body, "building")
    security_level = v_enum(body, "security_level", SECURITY_LEVELS)
    if "access_windows" not in body or body["access_windows"] is None:
        err(ERR_VALIDATION, "Missing required field: access_windows")
    _validate_windows(body["access_windows"])
    windows = [{
        "day_of_week": w["day_of_week"],
        "start_minute": w["start_minute"],
        "end_minute": w["end_minute"],
    } for w in body["access_windows"]]
    for z in store.zones.values():
        if z["zone_code"] == zone_code:
            err(ERR_DUPLICATE_NATURAL_KEY, "zone_code already exists")
    zone = new_row()
    zone.update({
        "zone_code": zone_code,
        "building": building,
        "security_level": security_level,
        "access_windows": windows,
        "status": "ACTIVE",
    })
    store.zones[zone["id"]] = zone
    return success(pub(zone), 201)


@bp.route("/api/door-zones", methods=["GET"])
def list_zones():
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "SecurityOfficer")
    rows = list(store.zones.values())
    level = request.args.get("security_level")
    status = request.args.get("status")
    if level is not None:
        rows = [z for z in rows if z["security_level"] == level]
    if status is not None:
        rows = [z for z in rows if z["status"] == status]
    data, page = paginate(rows)
    return success(data, 200, page)


@bp.route("/api/door-zones/<zid>", methods=["GET"])
def get_zone(zid):
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "SecurityOfficer")
    zone = find_or_404(store.zones, zid)
    return success(pub(zone), 200)


@bp.route("/api/door-zones/<zid>/decommission", methods=["POST"])
def decommission_zone(zid):
    authenticate()
    require_roles("SecurityOfficer")
    zone = find_or_404(store.zones, zid)
    if zone["status"] != "ACTIVE":
        err(ERR_INVALID_STATE_TRANSITION, "Only an ACTIVE zone can be decommissioned")
    zone["status"] = "DECOMMISSIONED"
    touch(zone)
    for gr in store.grants.values():
        if gr["zone_id"] == zone["id"] and gr["status"] in ("ACTIVE", "SUSPENDED"):
            gr["status"] = "REVOKED"
            touch(gr)
    return success(pub(zone), 200)


# -------------------------------------------------------------- access grants
@bp.route("/api/cards/<cid>/access-grants", methods=["POST"])
def create_grant(cid):
    authenticate()
    require_roles("SecurityOfficer")
    body = get_body()
    zone_id = v_str(body, "zone_id")
    clearance = v_enum(body, "clearance", SECURITY_LEVELS)
    valid_from = v_dt(body, "valid_from")
    valid_until = v_dt(body, "valid_until")
    card = find_or_404(store.cards, cid)
    find_or_404(store.zones, zone_id)
    if not valid_until > valid_from:
        err(ERR_VALIDATION, "valid_until must be strictly after valid_from")
    if card["lifecycle_status"] != "ACTIVE":
        err(ERR_CARD_NOT_ACTIVE, "Access grants require an ACTIVE card")
    # Lazy expiry of the grants this action touches before overlap evaluation.
    for gr in store.grants.values():
        if gr["card_id"] == card["id"] and gr["zone_id"] == zone_id:
            lazy_expire_grant(gr)
    for gr in store.grants.values():
        if (gr["card_id"] == card["id"] and gr["zone_id"] == zone_id
                and gr["status"] in ("ACTIVE", "SUSPENDED")):
            # Half-open interval intersection; adjacency is permitted.
            if valid_from < dt_of(gr, "valid_until") \
                    and dt_of(gr, "valid_from") < valid_until:
                err(ERR_GRANT_OVERLAP,
                    "The grant interval intersects an existing live grant")
    grant = new_row()
    grant.update({
        "card_id": card["id"],
        "zone_id": zone_id,
        "clearance": clearance,
        "valid_from": fmt_dt(valid_from),
        "valid_until": fmt_dt(valid_until),
        "status": "ACTIVE",
        "suspended_reason": None,
        "granted_by": g.user_id,
    })
    store.grants[grant["id"]] = grant
    return success(pub(grant), 201)


def _own_grant_or_403(grant):
    if g.role == "CardHolder":
        card = store.cards.get(grant["card_id"])
        if card is None or card["holder_id"] != g.user_id:
            err(ERR_NOT_RESOURCE_OWNER, "CardHolder may read only its own grants")


@bp.route("/api/access-grants", methods=["GET"])
def list_grants():
    authenticate()
    require_roles("PlatformAdmin", "SecurityOfficer", "CardHolder")
    rows = list(store.grants.values())
    if g.role == "CardHolder":
        own_cards = {c["id"] for c in store.cards.values()
                     if c["holder_id"] == g.user_id}
        rows = [gr for gr in rows if gr["card_id"] in own_cards]
    card_id = request.args.get("card_id")
    zone_id = request.args.get("zone_id")
    status = request.args.get("status")
    if card_id is not None:
        if g.role == "CardHolder":
            target = store.cards.get(card_id)
            if target is not None and target["holder_id"] != g.user_id:
                err(ERR_NOT_RESOURCE_OWNER, "Cannot filter by another holder's card")
        rows = [gr for gr in rows if gr["card_id"] == card_id]
    if zone_id is not None:
        rows = [gr for gr in rows if gr["zone_id"] == zone_id]
    if status is not None:
        rows = [gr for gr in rows if gr["status"] == status]
    data, page = paginate(rows)
    return success(data, 200, page)


@bp.route("/api/access-grants/<gid>", methods=["GET"])
def get_grant(gid):
    authenticate()
    require_roles("PlatformAdmin", "SecurityOfficer", "CardHolder")
    grant = store.grants.get(gid)
    if grant is not None:
        _own_grant_or_403(grant)
    if grant is None:
        err(ERR_NOT_FOUND, "Access grant not found")
    return success(pub(grant), 200)


@bp.route("/api/access-grants/<gid>/suspend", methods=["POST"])
def suspend_grant(gid):
    authenticate()
    require_roles("SecurityOfficer")
    grant = find_or_404(store.grants, gid)
    lazy_expire_grant(grant)
    if grant["status"] != "ACTIVE":
        err(ERR_INVALID_STATE_TRANSITION, "Only an ACTIVE grant can be suspended")
    grant["status"] = "SUSPENDED"
    grant["suspended_reason"] = "MANUAL"
    touch(grant)
    return success(pub(grant), 200)


@bp.route("/api/access-grants/<gid>/reinstate", methods=["POST"])
def reinstate_grant(gid):
    authenticate()
    require_roles("SecurityOfficer")
    grant = find_or_404(store.grants, gid)
    lazy_expire_grant(grant)
    if grant["status"] != "SUSPENDED":
        err(ERR_INVALID_STATE_TRANSITION, "Only a SUSPENDED grant can be reinstated")
    card = store.cards[grant["card_id"]]
    if card["lifecycle_status"] != "ACTIVE":
        err(ERR_CARD_NOT_ACTIVE, "The grant's card is not ACTIVE")
    grant["status"] = "ACTIVE"
    grant["suspended_reason"] = None
    touch(grant)
    return success(pub(grant), 200)


@bp.route("/api/access-grants/<gid>/revoke", methods=["POST"])
def revoke_grant(gid):
    authenticate()
    require_roles("SecurityOfficer")
    grant = find_or_404(store.grants, gid)
    lazy_expire_grant(grant)
    if grant["status"] not in ("ACTIVE", "SUSPENDED"):
        err(ERR_INVALID_STATE_TRANSITION, "Only a non-terminal grant can be revoked")
    grant["status"] = "REVOKED"
    touch(grant)
    return success(pub(grant), 200)


# -------------------------------------------------------------- access events
@bp.route("/api/access-events", methods=["POST"])
def create_access_event():
    authenticate()
    require_roles("DoorController")
    body = get_body()
    card_id = v_str(body, "card_id")
    zone_id = v_str(body, "zone_id")
    card = find_or_404(store.cards, card_id)
    zone = find_or_404(store.zones, zone_id)
    now = clock()
    # Lazy expiry evaluation on touch.
    lazy_expire_card(card)
    for gr in store.grants.values():
        if gr["card_id"] == card["id"] and gr["zone_id"] == zone["id"]:
            lazy_expire_grant(gr)
    # access_decision_selector: the first failing check pins the outcome.
    decision = "GRANTED"
    deny_reason = None
    grant_id = None
    if zone["status"] != "ACTIVE":
        decision, deny_reason = "DENIED", "ZONE_DECOMMISSIONED"
    elif card["lifecycle_status"] != "ACTIVE":
        decision, deny_reason = "DENIED", "CARD_NOT_ACTIVE"
    elif card["is_provisional"]:
        decision, deny_reason = "DENIED", "CARD_PROVISIONAL"
    else:
        candidates = [gr for gr in store.grants.values()
                      if gr["card_id"] == card["id"] and gr["zone_id"] == zone["id"]
                      and gr["status"] == "ACTIVE"
                      and dt_of(gr, "valid_from") <= now < dt_of(gr, "valid_until")]
        candidates.sort(key=lambda gr: (gr["created_at"], gr["_seq"]))
        candidates.sort(key=lambda gr: dt_of(gr, "valid_from"), reverse=True)
        if not candidates:
            decision, deny_reason = "DENIED", "NO_ACTIVE_GRANT"
        else:
            selected = candidates[0]
            grant_id = selected["id"]
            if LEVEL_ORDINAL[selected["clearance"]] < LEVEL_ORDINAL[zone["security_level"]]:
                decision, deny_reason = "DENIED", "INSUFFICIENT_CLEARANCE"
            else:
                dow = DAYS[now.weekday()]
                minute = now.hour * 60 + now.minute
                in_window = any(
                    w["day_of_week"] == dow
                    and w["start_minute"] <= minute < w["end_minute"]
                    for w in zone["access_windows"])
                if not in_window:
                    decision, deny_reason = "DENIED", "OUTSIDE_SCHEDULE"
    event = new_row(immutable=True)
    event.update({
        "card_id": card["id"],
        "zone_id": zone["id"],
        "grant_id": grant_id,
        "decision": decision,
        "deny_reason": deny_reason,
        "attempted_at": now_iso(),
    })
    store.access_events[event["id"]] = event
    return success(pub(event), 201)


@bp.route("/api/access-events", methods=["GET"])
def list_access_events():
    authenticate()
    require_roles("PlatformAdmin", "SecurityOfficer", "CardOfficeAdmin")
    rows = list(store.access_events.values())
    card_id = request.args.get("card_id")
    zone_id = request.args.get("zone_id")
    grant_id = request.args.get("grant_id")
    decision = request.args.get("decision")
    if card_id is not None:
        rows = [e for e in rows if e["card_id"] == card_id]
    if zone_id is not None:
        rows = [e for e in rows if e["zone_id"] == zone_id]
    if grant_id is not None:
        rows = [e for e in rows if e.get("grant_id") == grant_id]
    if decision is not None:
        rows = [e for e in rows if e["decision"] == decision]
    data, page = paginate(rows)
    return success(data, 200, page)


@bp.route("/api/access-events/<eid>", methods=["GET"])
def get_access_event(eid):
    authenticate()
    require_roles("PlatformAdmin", "SecurityOfficer", "CardOfficeAdmin")
    event = find_or_404(store.access_events, eid)
    return success(pub(event), 200)
