"""Routes: logical clock, hosts, houses, rooms, members."""
import re

from flask import Blueprint, g

import helpers as h
import domain as d
import state
from state import S

bp = Blueprint("core", __name__)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/co-living/_clock/set_current_utc")
def set_clock():
    h.authorize("PlatformAdmin")
    b = h.body()
    raw = h.req_field(b, "to_iso8601")
    dt = h.parse_instant(raw)  # validates ISO 8601 UTC
    S.clock = dt
    S.clock_echo = raw if isinstance(raw, str) else h.fmt_instant(dt)
    return h.ok({"current_utc": S.clock_echo}, 200)


# ---------------------------------------------------------------------------
# Hosts
# ---------------------------------------------------------------------------
@bp.post("/co-living/hosts")
def create_host():
    h.authorize("PlatformAdmin")
    b = h.body()
    legal_name = h.req_str(b, "legal_name")
    if len(legal_name) > 200:
        raise h.ApiError("ERR_INVALID_REQUEST", "legal_name too long")
    payout_account_ref = h.req_str(b, "payout_account_ref")
    contact_email = h.req_str(b, "contact_email")
    if "@" not in contact_email:
        raise h.ApiError("ERR_INVALID_REQUEST", "contact_email must contain '@'")
    host = h.new_common()
    host.update({
        "legal_name": legal_name,
        "payout_account_ref": payout_account_ref,
        "contact_email": contact_email,
    })
    S.hosts[host["id"]] = host
    return h.ok(d.serialize(host), 201)


# ---------------------------------------------------------------------------
# Houses
# ---------------------------------------------------------------------------
def _init_house_counts(house):
    for f in ("total_room_count", "vacant_room_count", "reserved_room_count",
              "occupied_room_count", "notice_pending_room_count",
              "out_of_service_room_count"):
        house[f] = 0
    house["compliance_posture"] = "OPEN"


@bp.post("/co-living/houses")
def create_house():
    h.authorize("Host", "PlatformAdmin")
    b = h.body()
    # Priority 4: ownership for Host
    if g.role == "Host" and b.get("host_id") != g.user_id:
        raise h.ApiError("ERR_NOT_RESOURCE_OWNER", "host_id must equal caller")
    # Priority 5: shape
    host_id = h.req_str(b, "host_id")
    label = h.req_str(b, "label")
    address_line1 = h.req_str(b, "address_line1")
    city = h.req_str(b, "city")
    state_code = h.req_str(b, "state_code")
    if not re.match(r"^[A-Z]{2}$", state_code):
        raise h.ApiError("ERR_INVALID_REQUEST", "state_code must be two uppercase letters")
    budget = h.req_int_nonneg(b, "monthly_utility_budget_cents")
    # Priority 6: FK
    h.find_or_404(S.hosts, host_id, "ERR_HOST_NOT_FOUND")
    house = h.new_common()
    house.update({
        "host_id": host_id,
        "label": label,
        "address_line1": address_line1,
        "city": city,
        "state_code": state_code,
        "monthly_utility_budget_cents": budget,
    })
    _init_house_counts(house)
    S.houses[house["id"]] = house
    return h.ok(d.serialize(house), 201)


@bp.get("/co-living/houses/<hid>")
def get_house(hid):
    h.authorize(*h.ROLES)
    house = h.find_or_404(S.houses, hid, "ERR_HOUSE_NOT_FOUND")
    return h.ok(d.serialize_house(house), 200)


@bp.get("/co-living/houses")
def list_houses():
    h.authorize(*h.ROLES)
    limit, offset = h.parse_pagination()
    host_id = h.query_val("host_id")
    posture = h.query_val("compliance_posture")
    rows = []
    for house in S.houses.values():
        d.eval_posture(house)  # fresh re-evaluation before filtering
        if host_id is not None and house["host_id"] != host_id:
            continue
        if posture is not None and house["compliance_posture"] != posture:
            continue
        rows.append(house)
    rows = h.sort_created(rows)
    page, pag = h.paginate(rows, limit, offset)
    return h.ok([d.serialize(x) for x in page], 200, "array", pag)


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------
@bp.post("/co-living/rooms")
def create_room():
    h.authorize("Host", "PlatformAdmin")
    b = h.body()
    # Priority 4: ownership for Host (only fires when the house exists and is
    # owned by another host; a non-existent house_id defers to the step-6 FK
    # resolution below, which reports ERR_HOUSE_NOT_FOUND).
    if g.role == "Host":
        hid = b.get("house_id")
        house = S.houses.get(hid) if isinstance(hid, str) else None
        if house is not None and house["host_id"] != g.user_id:
            raise h.ApiError("ERR_NOT_RESOURCE_OWNER", "caller does not own the house")
    # Priority 5: shape
    house_id = h.req_str(b, "house_id")
    room_number = h.req_str(b, "room_number")
    weekly = h.req_int_pos(b, "weekly_rate_cents")
    monthly = h.req_int_pos(b, "monthly_rate_cents")
    private_bath = h.req_bool_opt(b, "private_bath", False)
    # Priority 6: FK
    house = h.find_or_404(S.houses, house_id, "ERR_HOUSE_NOT_FOUND")
    # Priority 8: uniqueness of room_number within house
    for r in S.rooms.values():
        if r["house_id"] == house_id and r["room_number"] == room_number:
            raise h.ApiError("ERR_DUPLICATE_ROOM_NUMBER", "room_number already used in house")
    room = h.new_common()
    room.update({
        "house_id": house_id,
        "room_number": room_number,
        "weekly_rate_cents": weekly,
        "monthly_rate_cents": monthly,
        "private_bath": private_bath,
        "occupancy_state": "VACANT",
        "available_from_date": None,
    })
    S.rooms[room["id"]] = room
    d.recompute_house_counts(house)
    return h.ok(d.serialize(room), 201)


@bp.put("/co-living/rooms/<rid>")
def update_room(rid):
    h.authorize("Host", "PlatformAdmin")
    # Priority 3: path
    room = h.find_or_404(S.rooms, rid, "ERR_ROOM_NOT_FOUND")
    house = S.houses[room["house_id"]]
    # Priority 4: ownership
    if g.role == "Host" and house["host_id"] != g.user_id:
        raise h.ApiError("ERR_NOT_RESOURCE_OWNER", "caller does not own the room")
    # Priority 5: shape
    b = h.body()
    expected = h.req_int_nonneg(b, "expected_room_version")
    weekly = h.opt_int_nonneg(b, "weekly_rate_cents")
    monthly = h.opt_int_nonneg(b, "monthly_rate_cents")
    if weekly is not None and weekly <= 0:
        raise h.ApiError("ERR_INVALID_REQUEST", "weekly_rate_cents must be > 0")
    if monthly is not None and monthly <= 0:
        raise h.ApiError("ERR_INVALID_REQUEST", "monthly_rate_cents must be > 0")
    private_bath = None
    if "private_bath" in b and b["private_bath"] is not None:
        private_bath = h.req_bool_opt(b, "private_bath")
    # Priority 13: OCC
    if expected != room["version"]:
        raise h.ApiError("ERR_STALE_ROOM_VERSION", "expected_room_version is stale")
    if weekly is not None:
        room["weekly_rate_cents"] = weekly
    if monthly is not None:
        room["monthly_rate_cents"] = monthly
    if private_bath is not None:
        room["private_bath"] = private_bath
    h.touch(room)
    return h.ok(d.serialize(room), 200)


@bp.get("/co-living/rooms/<rid>")
def get_room(rid):
    h.authorize(*h.ROLES)
    room = h.find_or_404(S.rooms, rid, "ERR_ROOM_NOT_FOUND")
    return h.ok(d.serialize(room), 200)


@bp.get("/co-living/rooms")
def list_rooms():
    h.authorize(*h.ROLES)
    limit, offset = h.parse_pagination()
    house_id = h.query_val("house_id")
    occ = h.query_val("occupancy_state")
    rows = []
    for r in S.rooms.values():
        if house_id is not None and r["house_id"] != house_id:
            continue
        if occ is not None and r["occupancy_state"] != occ:
            continue
        rows.append(r)
    rows = h.sort_created(rows)
    page, pag = h.paginate(rows, limit, offset)
    return h.ok([d.serialize(x) for x in page], 200, "array", pag)


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
@bp.post("/co-living/members")
def create_member():
    h.authorize("PlatformAdmin")
    b = h.body()
    full_name = h.req_str(b, "full_name")
    email = h.req_str(b, "email")
    if "@" not in email:
        raise h.ApiError("ERR_INVALID_REQUEST", "email must contain '@'")
    income = h.req_int_nonneg(b, "declared_monthly_income_cents")
    for m in S.members.values():
        if m["email"] == email:
            raise h.ApiError("ERR_DUPLICATE_EMAIL", "email already registered")
    member = h.new_common()
    member.update({
        "full_name": full_name,
        "email": email,
        "declared_monthly_income_cents": income,
        "strike_points": 0,
        "standing_band": "GOOD",
    })
    S.members[member["id"]] = member
    return h.ok(d.serialize(member), 201)


@bp.get("/co-living/members/<mid>")
def get_member(mid):
    h.authorize(*h.ROLES)
    member = h.find_or_404(S.members, mid, "ERR_MEMBER_NOT_FOUND")
    return h.ok(d.serialize_member(member), 200)
