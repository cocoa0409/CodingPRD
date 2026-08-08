"""Routes: memberships and their lifecycle (convert, move-in, notice, move-out, cancel)."""
from datetime import timedelta

from flask import Blueprint, g

import helpers as h
import domain as d
from state import S, clock_date

bp = Blueprint("memberships", __name__)

_LIVE = {"PENDING_MOVE_IN", "ACTIVE", "NOTICE_GIVEN"}


def _recompute_house_for_room(room):
    house = S.houses[room["house_id"]]
    d.eval_posture(house)


# ---------------------------------------------------------------------------
# Convert application -> membership
# ---------------------------------------------------------------------------
@bp.post("/co-living/memberships")
def create_membership():
    h.authorize("CommunityManager")
    b = h.body()
    application_id = h.req_str(b, "application_id")
    move_in = h.req_date(b, "move_in_date")
    # Priority 6: FK
    app = h.find_or_404(S.applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    # Priority 9: one tenancy per member
    for m in S.memberships.values():
        if m["member_id"] == app["member_id"] and m["tenancy_status"] in _LIVE:
            raise h.ApiError("ERR_MEMBER_ALREADY_HOUSED", "member already holds a live tenancy")
    # Priority 10: application state
    if app["status"] not in ("APPROVED", "CONDITIONAL"):
        raise h.ApiError("ERR_APPLICATION_NOT_PENDING", "application is not APPROVED/CONDITIONAL")
    # Priority 11: room availability
    room = S.rooms[app["room_id"]]
    if room["occupancy_state"] != "VACANT":
        raise h.ApiError("ERR_ROOM_NOT_AVAILABLE", "room is not VACANT")
    # Priority 19: move-in date not in the past
    if move_in < clock_date():
        raise h.ApiError("ERR_MOVE_IN_DATE_IN_PAST", "move_in_date is in the past")
    # Priority 26: room turnover spacing
    for m in S.memberships.values():
        if m["room_id"] != app["room_id"]:
            continue
        if m["tenancy_status"] not in ("MOVED_OUT", "NOTICE_GIVEN"):
            continue
        eff = m["effective_end_date"]
        if eff is None:
            continue
        buffered = h.parse_date(eff) + timedelta(days=d.TURNOVER_BUFFER_DAYS)
        if move_in <= buffered:
            raise h.ApiError("ERR_ROOM_TURNOVER_CONFLICT", "move_in_date within turnover buffer")

    billing_cycle = app["billing_cycle"]
    period_days = 7 if billing_cycle == "WEEKLY" else 30
    base_rate = room["weekly_rate_cents"] if billing_cycle == "WEEKLY" else room["monthly_rate_cents"]

    membership = h.new_common()
    membership.update({
        "application_id": application_id,
        "member_id": app["member_id"],
        "room_id": app["room_id"],
        "house_id": room["house_id"],
        "billing_cycle": billing_cycle,
        "period_days": period_days,
        "base_period_rate_cents": base_rate,
        "deposit_cents": app["required_deposit_cents"],
        "move_in_date": b["move_in_date"],
        "tenancy_status": "PENDING_MOVE_IN",
        "billing_status": "CURRENT",
        "notice_reason": None,
        "scheduled_move_out_date": None,
        "actual_move_out_date": None,
        "effective_end_date": None,
        "provisional_final_charge_cents": None,
        "final_charge_cents": None,
        "balance_due_cents": 0,
    })
    S.memberships[membership["id"]] = membership
    app["status"] = "CONVERTED"
    h.touch(app)
    room["occupancy_state"] = "RESERVED"
    h.touch(room)
    _recompute_house_for_room(room)
    return h.ok(d.serialize(membership), 201)


@bp.get("/co-living/memberships/<mid>")
def get_membership(mid):
    h.authorize(*h.ROLES)
    m = h.find_or_404(S.memberships, mid, "ERR_MEMBERSHIP_NOT_FOUND")
    return h.ok(d.serialize_membership(m), 200)


@bp.get("/co-living/memberships")
def list_memberships():
    h.authorize(*h.ROLES)
    limit, offset = h.parse_pagination()
    f = {k: h.query_val(k) for k in
         ("member_id", "room_id", "house_id", "application_id",
          "tenancy_status", "billing_status")}
    rows = []
    for m in S.memberships.values():
        if any(v is not None and m[k] != v for k, v in f.items()):
            continue
        rows.append(m)
    rows = h.sort_created(rows)
    page, pag = h.paginate(rows, limit, offset)
    return h.ok([d.serialize(x) for x in page], 200, "array", pag)


# ---------------------------------------------------------------------------
# Move-in
# ---------------------------------------------------------------------------
@bp.post("/co-living/memberships/<mid>/move-in")
def move_in(mid):
    h.authorize("CommunityManager")
    m = h.find_or_404(S.memberships, mid, "ERR_MEMBERSHIP_NOT_FOUND")
    # Priority 10: state
    if m["tenancy_status"] != "PENDING_MOVE_IN":
        raise h.ApiError("ERR_INVALID_MEMBERSHIP_STATE", "membership is not PENDING_MOVE_IN")
    # Move-in may not run early
    if clock_date() < h.parse_date(m["move_in_date"]):
        raise h.ApiError("ERR_INVALID_MEMBERSHIP_STATE", "move-in date not yet reached")
    # Priority 15: house posture must be OPEN (fresh)
    room = S.rooms[m["room_id"]]
    house = S.houses[m["house_id"]]
    if d.eval_posture(house) != "OPEN":
        raise h.ApiError("ERR_HOUSE_POSTURE_BLOCKED", "house posture blocks move-in")
    m["tenancy_status"] = "ACTIVE"
    h.touch(m)
    room["occupancy_state"] = "OCCUPIED"
    h.touch(room)
    d.eval_posture(house)
    return h.ok(d.serialize_membership(m), 200)


# ---------------------------------------------------------------------------
# Notice
# ---------------------------------------------------------------------------
@bp.post("/co-living/memberships/<mid>/notice")
def give_notice(mid):
    h.authorize("Member", "CommunityManager")
    m = h.find_or_404(S.memberships, mid, "ERR_MEMBERSHIP_NOT_FOUND")
    # Priority 4: ownership for Member
    if g.role == "Member" and m["member_id"] != g.user_id:
        raise h.ApiError("ERR_NOT_RESOURCE_OWNER", "caller does not own the tenancy")
    b = h.body()
    reason = h.req_enum(b, "reason", {"MEMBER_INITIATED", "NONPAYMENT"})
    supplied = h.opt_date(b, "scheduled_move_out_date")
    # Priority 10: state
    if m["tenancy_status"] != "ACTIVE":
        raise h.ApiError("ERR_INVALID_MEMBERSHIP_STATE", "membership is not ACTIVE")

    if reason == "MEMBER_INITIATED":
        if supplied is None:
            raise h.ApiError("ERR_INVALID_REQUEST", "scheduled_move_out_date required")
        # Priority 20: minimum notice length
        if supplied < clock_date() + timedelta(days=d.MIN_NOTICE_DAYS):
            raise h.ApiError("ERR_NOTICE_TOO_SHORT", "notice shorter than minimum")
        sched_date = supplied
        sched_str = b["scheduled_move_out_date"]
    else:  # NONPAYMENT
        # Priority 21: past-due precondition
        if m["billing_status"] != "PAST_DUE":
            raise h.ApiError("ERR_NOT_PAST_DUE", "membership is not PAST_DUE")
        sched_date = clock_date() + timedelta(days=d.NONPAYMENT_NOTICE_DAYS)
        sched_str = h.fmt_date(sched_date)

    _apply_notice(m, reason, sched_date, sched_str)
    return h.ok(d.serialize_membership(m), 200)


def _apply_notice(m, reason, sched_date, sched_str):
    m["tenancy_status"] = "NOTICE_GIVEN"
    m["notice_reason"] = reason
    m["scheduled_move_out_date"] = sched_str
    m["provisional_final_charge_cents"] = d.provisional_charge(m, sched_date)
    m["effective_end_date"] = sched_str  # coalesce(actual, scheduled) -> scheduled here
    h.touch(m)
    room = S.rooms[m["room_id"]]
    room["occupancy_state"] = "NOTICE_PENDING"
    room["available_from_date"] = h.fmt_date(sched_date + timedelta(days=d.TURNOVER_BUFFER_DAYS))
    h.touch(room)
    d.eval_posture(S.houses[m["house_id"]])


# ---------------------------------------------------------------------------
# Move-out
# ---------------------------------------------------------------------------
@bp.post("/co-living/memberships/<mid>/move-out")
def move_out(mid):
    h.authorize("CommunityManager")
    m = h.find_or_404(S.memberships, mid, "ERR_MEMBERSHIP_NOT_FOUND")
    b = h.body()
    actual = h.req_date(b, "actual_move_out_date")
    # Priority 10: state
    if m["tenancy_status"] != "NOTICE_GIVEN":
        raise h.ApiError("ERR_INVALID_MEMBERSHIP_STATE", "membership is not NOTICE_GIVEN")
    # Priority 18: date range
    if actual < h.parse_date(m["move_in_date"]) or actual > clock_date():
        raise h.ApiError("ERR_INVALID_DATE_RANGE", "actual_move_out_date out of range")

    m["actual_move_out_date"] = b["actual_move_out_date"]
    m["effective_end_date"] = b["actual_move_out_date"]
    m["tenancy_status"] = "MOVED_OUT"
    final_charge, proration, inv = d.final_settlement(m, actual)
    m["final_charge_cents"] = final_charge
    if inv is not None:
        inv["proration_adjustment_cents"] = proration
        inv["total_amount_cents"] = inv["subtotal_cents"] + proration + inv["late_fee_cents"]
        h.touch(inv)
    h.touch(m)
    balance = d.recompute_balance(m)
    if balance == 0 and m["billing_status"] != "SETTLED":
        m["billing_status"] = "SETTLED"
    room = S.rooms[m["room_id"]]
    room["occupancy_state"] = "VACANT"
    room["available_from_date"] = None
    h.touch(room)
    d.eval_posture(S.houses[m["house_id"]])
    return h.ok(d.serialize_membership(m), 200)


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------
@bp.post("/co-living/memberships/<mid>/cancel")
def cancel_membership(mid):
    h.authorize("CommunityManager", "Member")
    m = h.find_or_404(S.memberships, mid, "ERR_MEMBERSHIP_NOT_FOUND")
    # Priority 4: ownership for Member
    if g.role == "Member" and m["member_id"] != g.user_id:
        raise h.ApiError("ERR_NOT_RESOURCE_OWNER", "caller does not own the tenancy")
    h.body()  # cancel_reason optional, unused
    # Priority 10: state
    if m["tenancy_status"] != "PENDING_MOVE_IN":
        raise h.ApiError("ERR_INVALID_MEMBERSHIP_STATE", "membership is not PENDING_MOVE_IN")
    m["tenancy_status"] = "CANCELLED"
    h.touch(m)
    room = S.rooms[m["room_id"]]
    room["occupancy_state"] = "VACANT"
    room["available_from_date"] = None
    h.touch(room)
    d.eval_posture(S.houses[m["house_id"]])
    return h.ok(d.serialize_membership(m), 200)
