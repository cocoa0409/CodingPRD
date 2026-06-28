"""Lounge endpoints: CRUD + close/reopen/sweep/settlement-summary/settlements pay
+ day-pass purchase (PRD §3.1, §3.3, §3.6, §3.8)."""
import re

from flask import Blueprint

import errors
import clock
import domain
from db import db, new_id, make_common_fields, make_event_fields, touch
from middleware import get_principal, require_role
from validation import get_json_body, require_str, require_int, optional_str
from serializers import serialize
from response import success
from routes.common import list_filtered

bp = Blueprint("lounges", __name__)

AIRPORT_RE = re.compile(r"^[A-Z]{3}$")


# =============================================================================
# Lounge CRUD
# =============================================================================
@bp.route("/lounges", methods=["POST"])
def create_lounge():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    body = get_json_body()

    name = require_str(body, "name")
    airport_code = require_str(body, "airport_code")
    if not AIRPORT_RE.match(airport_code):
        raise errors.invalid_request("airport_code must be 3 uppercase letters")
    capacity = require_int(body, "capacity", minimum=1)
    settlement_rate = require_int(body, "settlement_rate_cents", minimum=0)
    guest_fee = require_int(body, "guest_fee_cents", minimum=0)
    day_pass_price = require_int(body, "day_pass_price_cents", minimum=0)

    lounge = {
        "id": new_id(),
        "name": name,
        "airport_code": airport_code,
        "capacity": capacity,
        "settlement_rate_cents": settlement_rate,
        "guest_fee_cents": guest_fee,
        "day_pass_price_cents": day_pass_price,
        "status": "OPEN",
        "current_occupancy": 0,
        "held_occupancy": 0,
        "settlement_balance_cents": 0,
    }
    lounge.update(make_common_fields())
    lounge["_seq"] = db.lounges.next_seq()
    db.lounges.items[lounge["id"]] = lounge
    return success(serialize(lounge), status=201)


@bp.route("/lounges", methods=["GET"])
def list_lounges():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member", "LoungeAgent"})
    return list_filtered(
        db.lounges,
        [("airport_code", "airport_code", "str"), ("status", "status", "str")],
    )


@bp.route("/lounges/<lounge_id>", methods=["GET"])
def get_lounge(lounge_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member", "LoungeAgent"})
    lounge = db.lounges.items.get(lounge_id)
    if not lounge:
        raise errors.not_found("Lounge not found")
    return success(serialize(lounge))


# =============================================================================
# Settlement summary (computed read, PRD §3.8)
# =============================================================================
@bp.route("/lounges/<lounge_id>/settlement-summary", methods=["GET"])
def settlement_summary(lounge_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "LoungeAgent"})
    lounge = db.lounges.items.get(lounge_id)
    if not lounge:
        raise errors.not_found("Lounge not found")

    payable = 0
    paid = 0
    for s in db.settlements.items.values():
        if s["lounge_id"] != lounge_id:
            continue
        if s["status"] == "PAYABLE":
            payable += s["amount_cents"]
        elif s["status"] == "PAID":
            paid += s["amount_cents"]
    return success(
        {
            "payable_balance_cents": payable,
            "lifetime_earned_cents": payable + paid,
            "paid_cents": paid,
        }
    )


# =============================================================================
# Close / Reopen (Lounge.status state machine, PRD §3.1)
# =============================================================================
@bp.route("/lounges/<lounge_id>/close", methods=["POST"])
def close_lounge(lounge_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    lounge = db.lounges.items.get(lounge_id)
    if not lounge:
        raise errors.not_found("Lounge not found")
    body = get_json_body()
    # state check first (priority 5) then OCC (priority 15)
    if lounge["status"] not in ("OPEN", "OVERFLOW"):
        raise errors.invalid_state("Lounge is not OPEN or OVERFLOW")
    expected = require_int(body, "expected_lounge_version", minimum=0)
    if expected != lounge["version"]:
        raise errors.stale_version("expected_lounge_version mismatch")
    lounge["status"] = "CLOSED"
    touch(lounge)
    return success(serialize(lounge))


@bp.route("/lounges/<lounge_id>/reopen", methods=["POST"])
def reopen_lounge(lounge_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    lounge = db.lounges.items.get(lounge_id)
    if not lounge:
        raise errors.not_found("Lounge not found")
    if lounge["status"] != "CLOSED":
        raise errors.invalid_state("Lounge is not CLOSED")
    # Recompute status from the occupancy line.
    line = lounge["current_occupancy"] + lounge["held_occupancy"]
    lounge["status"] = "OVERFLOW" if line >= lounge["capacity"] else "OPEN"
    touch(lounge)
    return success(serialize(lounge))


# =============================================================================
# Housekeeping sweep (PRD §3.8)
# =============================================================================
@bp.route("/lounges/<lounge_id>/sweep", methods=["POST"])
def sweep(lounge_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    lounge = db.lounges.items.get(lounge_id)
    if not lounge:
        raise errors.not_found("Lounge not found")

    swept_no_show = 0
    swept_abandoned = 0
    expired_day_pass = 0

    now = clock.now()

    # The sweep is run "against a lounge": it resolves the HELD/CHECKED_IN visits
    # and ISSUED day passes of THIS lounge. (The no-show suspension cascade may
    # still reach a member's holds at other lounges, since suspension is
    # member-wide — see apply_no_show_strike_cascade.)

    # 1) Expire HELD visits of this lounge past hold_expires_at -> NO_SHOW.
    affected_members = set()
    affected_lounges = set()
    for v in list(db.visits.items.values()):
        if v["lounge_id"] != lounge_id:
            continue
        if v["status"] != "HELD":
            continue
        if clock.parse_iso(v["hold_expires_at"]) <= now:
            v["status"] = "NO_SHOW"
            touch(v)
            swept_no_show += 1
            affected_lounges.add(v["lounge_id"])
            # revert any redeemed day pass -> EXPIRED (forfeited)
            dp_id = v.get("day_pass_id")
            if dp_id:
                dp = domain.get_day_pass(dp_id)
                if dp and dp["status"] == "REDEEMED" and \
                        dp.get("redeemed_visit_id") == v["id"]:
                    dp["status"] = "EXPIRED"
                    dp["redeemed_visit_id"] = None
                    touch(dp)
            if v.get("member_id"):
                affected_members.add(v["member_id"])

    # Recompute member usage (incl. strikes) then apply suspension cascade.
    for mid in affected_members:
        member = domain.get_member(mid)
        if member:
            domain.recompute_member_usage(member)
            domain.apply_no_show_strike_cascade(member)

    # 2) Abandon stranded CHECKED_IN visits of this lounge whose snapshot card
    #    expired mid-visit.
    for v in list(db.visits.items.values()):
        if v["lounge_id"] != lounge_id:
            continue
        if v["status"] != "CHECKED_IN":
            continue
        card_id = v.get("eligibility_card_id")
        if not card_id:
            continue
        card = domain.get_card(card_id)
        if card and domain.is_expired(card["valid_until"]):
            v["status"] = "ABANDONED"
            touch(v)
            swept_abandoned += 1
            affected_lounges.add(v["lounge_id"])

    # 3) Expire ISSUED day passes of this lounge past valid_until.
    for dp in list(db.day_passes.items.values()):
        if dp["lounge_id"] != lounge_id:
            continue
        if dp["status"] == "ISSUED" and domain.is_expired(dp["valid_until"]):
            dp["status"] = "EXPIRED"
            touch(dp)
            expired_day_pass += 1

    # Recompute all affected lounge occupancy/status.
    for lid in affected_lounges:
        lo = domain.get_lounge(lid)
        if lo:
            domain.recompute_lounge_occupancy(lo)

    return success(
        {
            "swept_no_show_count": swept_no_show,
            "swept_abandoned_count": swept_abandoned,
            "expired_day_pass_count": expired_day_pass,
        }
    )


# =============================================================================
# Day-pass purchase (OCC-guarded, PRD §3.6)
# =============================================================================
@bp.route("/lounges/<lounge_id>/day-passes", methods=["POST"])
def purchase_day_pass(lounge_id):
    user_id, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member"})
    lounge = db.lounges.items.get(lounge_id)
    if not lounge:
        raise errors.not_found("Lounge not found")
    body = get_json_body()

    member_id = optional_str(body, "member_id")
    buyer_name = optional_str(body, "buyer_name")

    # Existence of member FK (priority 3).
    member = None
    if member_id is not None:
        member = domain.get_member(member_id)
        if not member:
            raise errors.not_found("Member not found")

    # Ownership: a Member buyer must purchase for themselves.
    if role == "Member":
        if member_id is None or member_id != user_id:
            raise errors.not_owner("Member may only purchase for themselves")

    # Body shape: need either member_id or buyer_name.
    if member_id is None and buyer_name is None:
        raise errors.invalid_request("Either member_id or buyer_name is required")

    # OCC on the lounge (priority 15).
    expected = require_int(body, "expected_lounge_version", minimum=0)
    if expected != lounge["version"]:
        raise errors.stale_version("expected_lounge_version mismatch")

    now = clock.now()
    dp = {
        "id": new_id(),
        "lounge_id": lounge_id,
        "member_id": member_id,
        "buyer_name": buyer_name,
        "price_cents": lounge["day_pass_price_cents"],
        "status": "ISSUED",
        "valid_until": clock.to_iso_millis(
            clock.add_hours(now, domain.DAY_PASS_TTL_HOURS)
        ),
        "redeemed_visit_id": None,
    }
    dp.update(make_common_fields())
    dp["_seq"] = db.day_passes.next_seq()
    db.day_passes.items[dp["id"]] = dp

    # The purchase bumps the lounge version (OCC parent supersede).
    touch(lounge)

    # When member-owned: post a DAY_PASS ledger entry and recompute wallet.
    if member is not None:
        domain.post_ledger_entry(
            member_id, "DAY_PASS", dp["price_cents"], day_pass_id=dp["id"]
        )
        domain.recompute_wallet(member)

    return success(serialize(dp), status=201)


# =============================================================================
# Batch-pay settlements (PRD §3.8)
# =============================================================================
@bp.route("/lounges/<lounge_id>/settlements/pay", methods=["POST"])
def pay_settlements(lounge_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    lounge = db.lounges.items.get(lounge_id)
    if not lounge:
        raise errors.not_found("Lounge not found")

    payable = [
        s for s in db.settlements.items.values()
        if s["lounge_id"] == lounge_id and s["status"] == "PAYABLE"
    ]
    payable.sort(key=lambda s: s["_seq"])

    paid_count = 0
    paid_total = 0
    for s in payable:
        s["status"] = "PAID"
        paid_count += 1
        paid_total += s["amount_cents"]

    domain.recompute_lounge_settlement_balance(lounge)

    return success({"paid_count": paid_count, "paid_total_cents": paid_total})
