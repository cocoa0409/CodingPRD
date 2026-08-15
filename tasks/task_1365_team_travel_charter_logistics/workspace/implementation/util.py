"""Auth, path resolution, body validation, pagination, clock sweep, finalize."""
from datetime import timedelta

from flask import g, request

import calc
from state import (
    STORE,
    ApiError,
    bump,
    clock_now,
    fmt_ts,
    parse_date,
    parse_dt,
)


# ---------------------------------------------------------------------------
# Error shortcuts
# ---------------------------------------------------------------------------
def e400(msg="Malformed or missing user context header"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def e403(msg="Role not permitted for operation"):
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, msg)


def invalid(msg="Invalid request body"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


NOT_FOUND = {
    "team": ("ERR_TEAM_NOT_FOUND", "teamId does not exist"),
    "season": ("ERR_SEASON_NOT_FOUND", "seasonId does not exist within team"),
    "trip": ("ERR_TRIP_NOT_FOUND", "tripId does not exist within team"),
    "leg": ("ERR_LEG_NOT_FOUND", "legId does not exist within trip"),
    "contract": ("ERR_CONTRACT_NOT_FOUND", "contractId does not exist within trip"),
    "block": ("ERR_BLOCK_NOT_FOUND", "blockId does not exist within trip"),
    "member": ("ERR_MEMBER_NOT_FOUND", "memberId does not exist within trip"),
    "entry": ("ERR_ENTRY_NOT_FOUND", "entryId does not exist within leg manifest"),
    "ledger": ("ERR_LEDGER_NOT_FOUND", "ledgerId does not exist within member"),
    "shipment": ("ERR_SHIPMENT_NOT_FOUND", "shipmentId does not exist within trip"),
    "event": ("ERR_EVENT_NOT_FOUND", "eventId does not exist within trip"),
    "credential": ("ERR_CREDENTIAL_NOT_FOUND", "credId does not exist within trip"),
    "room": ("ERR_ROOM_NOT_FOUND", "roomId does not exist within hotel block"),
}


def not_found(kind):
    eid, msg = NOT_FOUND[kind]
    return ApiError(eid, 404, msg)


# ---------------------------------------------------------------------------
# Auth (validation priority 1-2)
# ---------------------------------------------------------------------------
ROLES = {
    "TravelOpsAdmin",
    "TravelManager",
    "TravelCoordinator",
    "TravelFinanceLead",
    "EquipmentManager",
    "SecurityOfficer",
    "VenueCredentialApprover",
    "VendorRep",
    "TeamMember",
    "Any",
}


def authenticate():
    """Priority 1: header presence/shape. Populates g.user_id / g.user_role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip():
        raise e400()
    if not role or not isinstance(role, str) or role not in ROLES:
        raise e400()
    g.user_id = uid
    g.user_role = role


def require_role(*allowed):
    """Priority 2: role authorization."""
    if g.user_role not in allowed:
        raise e403()


def check_team_member_owns(member_id):
    """TeamMember identity: X-User-ID is the acting TravelPartyMember id."""
    if g.user_role == "TeamMember" and g.user_id != member_id:
        raise e403()


def team_member_read_guard(res):
    """TeamMember read access limited to own resources: any resource that
    references a TravelPartyMember must match the caller's id."""
    if g.user_role != "TeamMember":
        return
    mid = res.get("member_id")
    if mid is not None and mid != g.user_id:
        raise e403()
    if res.get("_kind") == "member" and res.get("id") != g.user_id:
        raise e403()


# ---------------------------------------------------------------------------
# Path resolvers (priority 3, left to right)
# ---------------------------------------------------------------------------
def resolve_team(team_id):
    t = STORE["teams"].get(team_id)
    if t is None:
        raise not_found("team")
    return t


def resolve_season(team, season_id):
    s = STORE["seasons"].get(season_id)
    if s is None or s["team_id"] != team["id"]:
        raise not_found("season")
    return s


def resolve_trip(team, trip_id):
    t = STORE["trips"].get(trip_id)
    if t is None or t["team_id"] != team["id"]:
        raise not_found("trip")
    return t


def resolve_member(trip, member_id):
    m = STORE["members"].get(member_id)
    if m is None or m["trip_id"] != trip["id"]:
        raise not_found("member")
    return m


def resolve_contract(trip, contract_id):
    c = STORE["contracts"].get(contract_id)
    if c is None or c["trip_id"] != trip["id"]:
        raise not_found("contract")
    return c


def resolve_leg(trip, leg_id):
    l = STORE["legs"].get(leg_id)
    if l is None or l["trip_id"] != trip["id"]:
        raise not_found("leg")
    return l


def resolve_entry(leg, entry_id):
    e = STORE["entries"].get(entry_id)
    if e is None or e["flight_leg_id"] != leg["id"]:
        raise not_found("entry")
    return e


def resolve_block(trip, block_id):
    b = STORE["blocks"].get(block_id)
    if b is None or b["trip_id"] != trip["id"]:
        raise not_found("block")
    return b


def resolve_room(block, room_id):
    r = STORE["rooms"].get(room_id)
    if r is None or r["hotel_block_id"] != block["id"]:
        raise not_found("room")
    return r


def resolve_ledger(member, ledger_id):
    l = STORE["ledgers"].get(ledger_id)
    if l is None or l["member_id"] != member["id"]:
        raise not_found("ledger")
    return l


def resolve_shipment(trip, shipment_id):
    s = STORE["shipments"].get(shipment_id)
    if s is None or s["trip_id"] != trip["id"]:
        raise not_found("shipment")
    return s


def resolve_event(trip, event_id):
    e = STORE["events"].get(event_id)
    if e is None or e["trip_id"] != trip["id"]:
        raise not_found("event")
    return e


def resolve_credential(trip, cred_id):
    c = STORE["credentials"].get(cred_id)
    if c is None or c["trip_id"] != trip["id"]:
        raise not_found("credential")
    return c


# ---------------------------------------------------------------------------
# Body validation (priority between existence and OCC; per-diem input last)
# ---------------------------------------------------------------------------
def body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise invalid("Request body must be a JSON object")
    return data


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v:
        raise invalid("Missing or invalid field: %s" % field)
    return v


def opt_str(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, str):
        raise invalid("Invalid field: %s" % field)
    return v


def req_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid("Missing or invalid field: %s" % field)
    return v


def opt_int(data, field, default=None):
    v = data.get(field, default)
    if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
        raise invalid("Invalid field: %s" % field)
    return v


def opt_bool(data, field, default=False):
    v = data.get(field, default)
    if not isinstance(v, bool):
        raise invalid("Invalid field: %s" % field)
    return v


def req_dt(data, field):
    raw = req_str(data, field)
    dt = parse_dt(raw)
    if dt is None:
        raise invalid("Invalid datetime: %s" % field)
    return raw, dt


def req_date(data, field):
    raw = req_str(data, field)
    d = parse_date(raw)
    if d is None:
        raise invalid("Invalid date: %s" % field)
    return raw, d


def req_enum(data, field, values, error=None):
    v = data.get(field)
    if not isinstance(v, str) or v not in values:
        if error is not None:
            raise error
        raise invalid("Invalid value for %s" % field)
    return v


def req_version(data, field):
    """Mandatory optimistic-concurrency field (PRD §2.7)."""
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid("Missing or invalid field: %s" % field)
    return v


def check_version(res, supplied):
    """Priority 4: optimistic concurrency."""
    if supplied != res["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected version does not match current version")


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def pagination_params():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid("Invalid limit")
        if limit < 1 or limit > 100:
            raise invalid("limit out of range")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid("Invalid offset")
        if offset < 0:
            raise invalid("offset out of range")
    return limit, offset


def paginate(items):
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset : offset + limit]
    return page, total, limit, offset


def apply_filters(items, allowed):
    """Exact-match query filters; only whitelisted keys."""
    out = items
    for key in allowed:
        raw = request.args.get(key)
        if raw is None:
            continue
        out = [r for r in out if str(r.get(key)) == raw]
    return out


# ---------------------------------------------------------------------------
# Trip mutation finalization: recompute rollups, single version bump/request
# ---------------------------------------------------------------------------
def _bumped():
    if not hasattr(g, "_bumped_trips"):
        g._bumped_trips = set()
    return g._bumped_trips


def finalize_trip(trip, enumerated=False):
    """Recompute party size + estimated cost; bump trip version at most once
    per request when the mutation is enumerated or the estimate changed."""
    calc.recalc_party_size(trip)
    old = trip["estimated_cost_cents"]
    new = calc.compute_estimate(trip)
    changed = new != old
    trip["estimated_cost_cents"] = new
    if (enumerated or changed) and trip["id"] not in _bumped():
        bump(trip)
        _bumped().add(trip["id"])


def reconcile_trip_posture(trip, season):
    """DISRUPTED -> LOCKED when all events resolved/closed and no leg REBOOKING."""
    if trip["posture"] != "DISRUPTED":
        return
    open_ev = any(
        e["status"] in ("OPEN", "MITIGATING") for e in calc.trip_events(trip)
    )
    rebooking = any(l["status"] == "REBOOKING" for l in calc.trip_legs(trip))
    if not open_ev and not rebooking:
        trip["posture"] = "LOCKED"
        bump(trip)
        _bumped().add(trip["id"])
        bump(season)


# ---------------------------------------------------------------------------
# Clock sweep: time-driven transitions (PRD §2.8, §3.3, §3.6)
# ---------------------------------------------------------------------------
def sweep_clock():
    now = clock_now()
    today = now.date()
    for block in list(STORE["blocks"].values()):
        trip = STORE["trips"].get(block["trip_id"])
        cutoff = parse_date(block["cutoff_date"])
        changed = False
        if block["posture"] == "HOLDING" and cutoff is not None:
            if today >= cutoff - timedelta(days=7):
                block["posture"] = "NAME_LIST_DUE"
                changed = True
        if block["posture"] == "NAME_LIST_DUE" and cutoff is not None:
            if today >= cutoff:
                penalty = calc.attrition_penalty_cents(block)
                if penalty > 0:
                    block["posture"] = "ATTRITION_EXPOSED"
                    block["_attrition_penalty_cents"] = penalty
                    block["_attrition_at"] = fmt_ts(now)
                    if trip is not None:
                        calc.log_financial_event(trip, fmt_ts(now), penalty)
                        finalize_trip(trip)
                    changed = True
        if block["posture"] in ("LOCKED", "ATTRITION_EXPOSED"):
            check_in = parse_date(block["check_in_date"])
            if check_in is not None:
                checkout = check_in + timedelta(days=block["night_count"])
                if today > checkout:
                    block["posture"] = "CLOSED"
                    changed = True
        if changed:
            bump(block)
    for contract in list(STORE["contracts"].values()):
        if contract["status"] != "DRAFT":
            continue
        trip = STORE["trips"].get(contract["trip_id"])
        if trip is None:
            continue
        tipoff = trip["_tipoff"]
        if now > tipoff - timedelta(days=30):
            contract["status"] = "EXPIRED"
            bump(contract)
