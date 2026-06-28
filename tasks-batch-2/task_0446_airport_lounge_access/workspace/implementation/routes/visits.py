"""Visit endpoints: hold creation, check-in, complete, cancel (PRD §3.3-§3.5)."""
from flask import Blueprint

import errors
import clock
import domain
from db import db, new_id, make_common_fields, touch
from middleware import get_principal, require_role
from validation import get_json_body, require_str, require_int, optional_str
from serializers import serialize
from response import success
from routes.common import list_filtered

bp = Blueprint("visits", __name__)

CARD_STATUS_RANK = domain.CARD_RANK


# =============================================================================
# POST /visits — open a hold (PRD §3.3, §3.5; OCC-guarded on lounge)
# =============================================================================
@bp.route("/visits", methods=["POST"])
def open_hold():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "LoungeAgent"})
    body = get_json_body()

    # ---- existence of FKs (priority 3, left-to-right: path then body) ------
    lounge_id = require_str(body, "lounge_id")
    lounge = domain.get_lounge(lounge_id)
    if not lounge:
        raise errors.not_found("Lounge not found")

    member_id = optional_str(body, "member_id")
    member = None
    if member_id is not None:
        member = domain.get_member(member_id)
        if not member:
            raise errors.not_found("Member not found")

    day_pass_id = optional_str(body, "day_pass_id")
    day_pass = None
    if day_pass_id is not None:
        day_pass = domain.get_day_pass(day_pass_id)
        if not day_pass:
            raise errors.not_found("Day pass not found")

    # ---- body shape sanity for guest_count / guest_names -------------------
    guest_count = require_int(body, "guest_count", required=False, minimum=0,
                              default=0)
    guest_names = body.get("guest_names")
    if guest_names is None:
        guest_names = []
    if not isinstance(guest_names, list) or \
            any(not isinstance(n, str) for n in guest_names):
        raise errors.invalid_request("guest_names must be a list of strings")
    if guest_names and len(guest_names) != guest_count:
        raise errors.invalid_request(
            "guest_names length must equal guest_count"
        )
    if not guest_names and guest_count > 0:
        # allow guest_count without names → synthesize empty names? Spec ties
        # names to funding order; require names when guests are present.
        raise errors.invalid_request(
            "guest_names required when guest_count > 0"
        )

    # ---- determine entry funding mode --------------------------------------
    is_day_pass_entry = day_pass_id is not None
    plan = None
    if member is not None:
        domain.recompute_member_usage(member)
        plan = domain.get_plan(member["plan_id"])

    # ---- member-route business gates (priorities 6,7,8) --------------------
    snapshot_card_id = None
    if not is_day_pass_entry:
        # A non-day-pass entry requires a member.
        if member is None:
            raise errors.invalid_request(
                "member_id is required for a non-day-pass entry"
            )
        # priority 6: active, non-expired card
        active_card = domain.active_card_for_member(member_id)
        if active_card is None or domain.is_expired(active_card["valid_until"]):
            raise errors.err("ERR_NO_ACTIVE_CARD", "No active eligibility card")
        snapshot_card_id = active_card["id"]
        # priority 7: eligibility gate
        meets_card = (
            CARD_STATUS_RANK[active_card["card_status"]]
            >= CARD_STATUS_RANK[plan["min_card_status"]]
        )
        fare_ok = active_card["fare_class"] in ("BUSINESS", "FIRST")
        if not (meets_card or fare_ok):
            raise errors.err("ERR_NOT_ELIGIBLE", "Member not eligible to enter")
        # priority 8: standing
        if member["standing"] == "SUSPENDED":
            raise errors.err("ERR_MEMBER_SUSPENDED", "Member is suspended")

    # ---- priority 9: day-pass redemption validity at hold time -------------
    if is_day_pass_entry:
        if not _day_pass_valid_for(day_pass, lounge_id, member_id):
            raise errors.err("ERR_DAY_PASS_INVALID", "Day pass not valid")

    # ---- priority 10: lounge must be OPEN to accept new holds --------------
    if lounge["status"] != "OPEN":
        raise errors.err("ERR_LOUNGE_OVERFLOW",
                         "Lounge does not accept new holds")

    # ---- priority 15: OCC on the lounge version ----------------------------
    expected = require_int(body, "expected_lounge_version", minimum=0)
    if expected != lounge["version"]:
        raise errors.stale_version("expected_lounge_version mismatch")

    # ---- resolve entry mode + guest funding --------------------------------
    if is_day_pass_entry:
        entry_mode, allotment_consumed = "DAY_PASS", False
        guest_allotment_consumed, funded_by = 0, []
        # day-pass entries fund guests as charge (no member allotment when no
        # member, and a day-pass-only entry has no member plan to draw from)
        if member is not None:
            guest_allotment_consumed, funded_by = domain.resolve_guest_funding(
                member, plan, guest_count
            )
        else:
            funded_by = ["GUEST_CHARGE"] * guest_count
    else:
        entry_mode, allotment_consumed = domain.resolve_entry_mode(
            member, plan, day_pass_valid=False
        )
        guest_allotment_consumed, funded_by = domain.resolve_guest_funding(
            member, plan, guest_count
        )

    now = clock.now()
    occupant_count = 1 + guest_count
    visit = {
        "id": new_id(),
        "member_id": member_id,
        "lounge_id": lounge_id,
        "eligibility_card_id": snapshot_card_id,
        "day_pass_id": day_pass_id,
        "entry_mode": entry_mode,
        "guest_count": guest_count,
        "occupant_count": occupant_count,
        "allotment_consumed": allotment_consumed,
        "guest_allotment_consumed": guest_allotment_consumed,
        "status": "HELD",
        "held_at": clock.to_iso_millis(now),
        "hold_expires_at": clock.to_iso_millis(
            clock.add_minutes(now, domain.HOLD_TTL_MINUTES)
        ),
        "member_charge_cents": 0,
        "settlement_amount_cents": 0,
    }
    visit.update(make_common_fields())
    visit["_seq"] = db.visits.next_seq()
    db.visits.items[visit["id"]] = visit

    # Create Guest rows in guest_names creation order.
    for i, gname in enumerate(guest_names):
        g = {
            "id": new_id(),
            "visit_id": visit["id"],
            "full_name": gname,
            "funded_by": funded_by[i],
            "charge_cents": 0,
        }
        g.update(make_common_fields())
        g["_seq"] = db.guests.next_seq()
        db.guests.items[g["id"]] = g

    # If a day pass is redeemed, mark held-redemption (REDEEMED) at hold time.
    if is_day_pass_entry and day_pass is not None:
        day_pass["status"] = "REDEEMED"
        day_pass["redeemed_visit_id"] = visit["id"]
        touch(day_pass)

    # Recompute lounge occupancy/status (held_occupancy += occupant_count); this
    # bumps the lounge version exactly once (held_occupancy always changes on a
    # hold), which is the OCC parent supersede for hold creation.
    domain.recompute_lounge_occupancy(lounge)

    return success(serialize(visit), status=201)


def _day_pass_valid_for(day_pass, lounge_id, member_id):
    if day_pass["status"] != "ISSUED":
        return False
    if domain.is_expired(day_pass["valid_until"]):
        return False
    if day_pass["lounge_id"] != lounge_id:
        return False
    if day_pass.get("member_id") is not None and \
            day_pass["member_id"] != member_id:
        return False
    return True


# =============================================================================
# Lists / get
# =============================================================================
@bp.route("/visits", methods=["GET"])
def list_visits():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member", "LoungeAgent"})
    return list_filtered(
        db.visits,
        [
            ("member_id", "member_id", "str"),
            ("lounge_id", "lounge_id", "str"),
            ("eligibility_card_id", "eligibility_card_id", "str"),
            ("day_pass_id", "day_pass_id", "str"),
            ("status", "status", "str"),
        ],
    )


@bp.route("/visits/<visit_id>", methods=["GET"])
def get_visit(visit_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member", "LoungeAgent"})
    visit = domain.get_visit(visit_id)
    if not visit:
        raise errors.not_found("Visit not found")
    return success(serialize(visit))


# =============================================================================
# POST /visits/{id}/check-in (PRD §3.4)
# =============================================================================
@bp.route("/visits/<visit_id>/check-in", methods=["POST"])
def check_in(visit_id):
    user_id, role = get_principal()
    require_role(role, {"LoungeAgent"})
    visit = domain.get_visit(visit_id)
    if not visit:
        raise errors.not_found("Visit not found")
    # ownership: agent must staff this visit's lounge (priority 4)
    if user_id != visit["lounge_id"]:
        raise errors.not_owner("Agent does not staff this lounge")
    # state (priority 5)
    if visit["status"] != "HELD":
        raise errors.invalid_state("Visit is not HELD")

    lounge = domain.get_lounge(visit["lounge_id"])

    # hold not expired
    if clock.parse_iso(visit["hold_expires_at"]) <= clock.now():
        # An expired hold cannot be checked in; it is a no-show condition.
        raise errors.invalid_state("Hold has expired")

    # lounge must be OPEN or OVERFLOW (CLOSED admits no one)
    if lounge["status"] == "CLOSED":
        raise errors.invalid_state("Lounge is CLOSED")

    member = domain.get_member(visit["member_id"]) if visit.get("member_id") \
        else None

    # day-pass validity re-checked at check-in (priority 9)
    day_pass = None
    if visit.get("day_pass_id"):
        day_pass = domain.get_day_pass(visit["day_pass_id"])
        # redeeming hold marks it REDEEMED at hold time; accept REDEEMED for
        # this visit or ISSUED, but it must not be expired/wrong lounge/owner.
        if not _day_pass_valid_at_checkin(day_pass, visit):
            raise errors.err("ERR_DAY_PASS_INVALID", "Day pass not valid")

    # standing must be GOOD for non-day-pass entries
    if visit["entry_mode"] != "DAY_PASS":
        if member is not None and member["standing"] != "GOOD":
            raise errors.err("ERR_MEMBER_SUSPENDED", "Member is suspended")

    # capacity check (priority 11)
    if lounge["current_occupancy"] + visit["occupant_count"] > lounge["capacity"]:
        raise errors.err("ERR_OVER_CAPACITY", "Check-in exceeds capacity")

    # ---- compute member charge (calc 3) ------------------------------------
    plan = domain.get_plan(member["plan_id"]) if member else None
    total, overage_line, per_guest, day_pass_line = domain.compute_member_charge(
        visit, plan, lounge, member, day_pass
    )

    visit["member_charge_cents"] = total

    # Always pin each guest's charge_cents (the per-line-rounded figure).
    for g, line in per_guest:
        g["charge_cents"] = line
        touch(g)

    # Post ledger entries (only for member-tied entries). Each guest's ledger
    # rows sum exactly to that guest's charge_cents so wallet stays consistent
    # with the per-line-rounded member_charge_cents.
    if member is not None:
        if overage_line > 0 and visit["entry_mode"] == "OVERAGE":
            domain.post_ledger_entry(
                member["id"], "OVERAGE", overage_line, visit_id=visit["id"]
            )
        for g, line in per_guest:
            _post_guest_ledger(member, visit, lounge, g, line)

    # finalise day pass redemption
    if day_pass is not None:
        day_pass["status"] = "REDEEMED"
        day_pass["redeemed_visit_id"] = visit["id"]
        touch(day_pass)

    visit["status"] = "CHECKED_IN"
    touch(visit)

    # recompute lounge occupancy (current += occupant, held -= occupant)
    domain.recompute_lounge_occupancy(lounge)

    # recompute member usage + wallet
    if member is not None:
        domain.recompute_member_usage(member)

    return success(serialize(visit))


def _post_guest_ledger(member, visit, lounge, guest, guest_line):
    """Post the per-guest ledger rows so they sum exactly to guest_line
    (the guest's already-rounded charge_cents).

    GUEST_CHARGE guest → a LOUNGE_GUEST_FEE row (the rounded lounge door fee
    portion) and a GUEST_CHARGE row (the remaining plan portion).
    GUEST_ALLOTMENT guest → only a LOUNGE_GUEST_FEE row (the whole line is the
    lounge door fee; the plan guest charge is waived).

    Rows with a zero amount are not posted (every ledger amount is non-zero).
    """
    from decimal import Decimal
    active_card = domain.active_card_for_member(member["id"])
    is_gold = bool(active_card and active_card["card_status"] == "GOLD")
    disc = domain.MEMBER_FEE_DISCOUNT if is_gold else Decimal("1")

    fee_portion = domain.round_half_up_cents(lounge["guest_fee_cents"], disc)
    # Clamp so the door-fee portion never exceeds the rounded guest line.
    fee_portion = min(fee_portion, guest_line)
    plan_portion = guest_line - fee_portion  # GUEST_CHARGE remainder

    if fee_portion != 0:
        domain.post_ledger_entry(
            member["id"], "LOUNGE_GUEST_FEE", fee_portion, visit_id=visit["id"]
        )
    if guest["funded_by"] == "GUEST_CHARGE" and plan_portion != 0:
        domain.post_ledger_entry(
            member["id"], "GUEST_CHARGE", plan_portion, visit_id=visit["id"]
        )


def _day_pass_valid_at_checkin(day_pass, visit):
    if day_pass is None:
        return False
    if day_pass["status"] not in ("ISSUED", "REDEEMED"):
        return False
    if day_pass["status"] == "REDEEMED" and \
            day_pass.get("redeemed_visit_id") not in (None, visit["id"]):
        return False
    if domain.is_expired(day_pass["valid_until"]):
        return False
    if day_pass["lounge_id"] != visit["lounge_id"]:
        return False
    if day_pass.get("member_id") is not None and \
            visit.get("member_id") is not None and \
            day_pass["member_id"] != visit["member_id"]:
        return False
    return True


# =============================================================================
# POST /visits/{id}/complete (PRD §3.4)
# =============================================================================
@bp.route("/visits/<visit_id>/complete", methods=["POST"])
def complete(visit_id):
    user_id, role = get_principal()
    require_role(role, {"LoungeAgent"})
    visit = domain.get_visit(visit_id)
    if not visit:
        raise errors.not_found("Visit not found")
    if user_id != visit["lounge_id"]:
        raise errors.not_owner("Agent does not staff this lounge")
    if visit["status"] != "CHECKED_IN":
        raise errors.invalid_state("Visit is not CHECKED_IN")

    lounge = domain.get_lounge(visit["lounge_id"])
    amount = domain.compute_settlement_amount(visit, lounge)
    visit["settlement_amount_cents"] = amount
    visit["status"] = "COMPLETED"
    touch(visit)

    domain.create_settlement(lounge["id"], visit["id"], amount)
    domain.recompute_lounge_settlement_balance(lounge)
    domain.recompute_lounge_occupancy(lounge)

    return success(serialize(visit))


# =============================================================================
# POST /visits/{id}/cancel (PRD §3.3)
# =============================================================================
@bp.route("/visits/<visit_id>/cancel", methods=["POST"])
def cancel(visit_id):
    user_id, role = get_principal()
    require_role(role, {"Member", "NetworkAdmin"})
    visit = domain.get_visit(visit_id)
    if not visit:
        raise errors.not_found("Visit not found")
    if role == "Member" and user_id != visit.get("member_id"):
        raise errors.not_owner("Member may only cancel their own holds")
    if visit["status"] != "HELD":
        raise errors.invalid_state("Visit is not HELD")

    visit["status"] = "CANCELLED"
    touch(visit)

    # revert redeeming day pass back to ISSUED
    domain._revert_day_pass_on_cancel(visit)

    lounge = domain.get_lounge(visit["lounge_id"])
    domain.recompute_lounge_occupancy(lounge)

    # recompute member usage (cancelled leaves consuming set)
    if visit.get("member_id"):
        member = domain.get_member(visit["member_id"])
        if member:
            domain.recompute_member_usage(member)

    return success(serialize(visit))
