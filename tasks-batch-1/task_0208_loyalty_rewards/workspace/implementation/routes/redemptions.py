"""Redemptions (burn): quote, confirm, fulfill, cancel; lines reads.
Dual-variant cost (quoted vs final). (PRD §3.7)"""
from flask import Blueprint, request

from db import db
from errors import (err, ERR_PROGRAM_NOT_ACTIVE, ERR_MEMBER_NOT_ACTIVE,
                    ERR_INVALID_STATE, ERR_EMPTY_REDEMPTION, ERR_INVALID_QUANTITY,
                    ERR_REWARD_UNAVAILABLE, ERR_INSUFFICIENT_POINTS,
                    ERR_INSUFFICIENT_STOCK, ERR_STALE_MEMBER_VERSION,
                    ERR_INVALID_REQUEST)
from middleware import require_roles
from response import success
from services import serialize, ledger
from services.helpers import (get_json_body, require_str, opt_int, paginate)
from services.lookup import (get_member, get_reward, get_redemption,
                             assert_member_owner, get_redemption_line)

bp = Blueprint("redemptions", __name__)


@bp.post("/redemptions")
def create_redemption():
    _, role = require_roles("ProgramAdmin", "Member")
    body = get_json_body()
    member_id = require_str(body, "member_id")
    lines_in = body.get("lines")

    member = get_member(member_id)
    user_id = request.headers.get("X-User-ID")
    assert_member_owner(role, user_id, member_id)
    program = db.programs[member["program_id"]]

    # shape: non-empty redemption (priority 5)
    if not isinstance(lines_in, list) or len(lines_in) == 0:
        raise err(ERR_EMPTY_REDEMPTION, "Redemption must have at least one line")
    # per-line shape + quantity (priority 5)
    for ln in lines_in:
        if not isinstance(ln, dict) or "reward_id" not in ln or ln.get("reward_id") is None:
            raise err(ERR_INVALID_REQUEST, "Each line needs a reward_id")
        qty = ln.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int):
            raise err(ERR_INVALID_REQUEST, "Each line needs an integer quantity")
        if qty < 1:
            raise err(ERR_INVALID_QUANTITY, "quantity must be >= 1")

    # existence of body-referenced rewards (priority 4)
    rewards = []
    for ln in lines_in:
        rewards.append(get_reward(ln["reward_id"]))

    # program-active gate (priority 11)
    if program["status"] != "ACTIVE":
        raise err(ERR_PROGRAM_NOT_ACTIVE, "Program is not ACTIVE")

    # reward availability (priority 18): ACTIVE and belongs to member's program
    for reward in rewards:
        if reward["status"] != "ACTIVE" or reward["program_id"] != member["program_id"]:
            raise err(ERR_REWARD_UNAVAILABLE, "Reward unavailable for this member")

    # Compute quoted cost using member's current tier (PRD §3.7 quoted variant).
    ledger.recompute_member(member)
    tier_code = member["current_tier_code"]

    red = {
        "member_id": member_id,
        "quoted_cost_points": 0,
        "final_cost_points": None,
        "status": "QUOTED",
        "expected_member_version": None,
    }
    db.stamp_create(red)

    total = 0
    line_recs = []
    for ln, reward in zip(lines_in, rewards):
        qty = ln["quantity"]
        disc = ledger.applicable_discount(member["program_id"], tier_code, reward)
        lc = ledger.line_cost(qty, reward["point_cost"], disc)
        total += lc
        line = {
            "redemption_id": red["id"],
            "reward_id": reward["id"],
            "quantity": qty,
            "line_cost_points": lc,
        }
        db.stamp_create(line, common_fields=False)
        line_recs.append(line)

    red["quoted_cost_points"] = total
    db.redemptions[red["id"]] = red
    for line in line_recs:
        db.redemption_lines[line["id"]] = line

    return success(serialize.redemption_out(red), 201)


@bp.get("/redemptions/<rid>")
def get_redemption_route(rid):
    _, role = require_roles("ProgramAdmin", "Member")
    red = get_redemption(rid)
    user_id = request.headers.get("X-User-ID")
    assert_member_owner(role, user_id, red["member_id"])
    return success(serialize.redemption_out(red), 200)


@bp.get("/members/<mid>/redemptions")
def list_member_redemptions(mid):
    _, role = require_roles("ProgramAdmin", "Member")
    get_member(mid)
    user_id = request.headers.get("X-User-ID")
    assert_member_owner(role, user_id, mid)
    status = request.args.get("status")
    items = [r for r in db.redemptions.values() if r["member_id"] == mid]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, pg = paginate(items)
    return success([serialize.redemption_out(x) for x in page], 200, pg)


@bp.get("/redemptions/<rid>/lines")
def list_redemption_lines(rid):
    _, role = require_roles("ProgramAdmin", "Member")
    red = get_redemption(rid)
    user_id = request.headers.get("X-User-ID")
    assert_member_owner(role, user_id, red["member_id"])
    items = [l for l in db.redemption_lines.values() if l["redemption_id"] == rid]
    page, pg = paginate(items)
    return success([serialize.redemption_line_out(x) for x in page], 200, pg)


@bp.get("/redemption-lines/<lid>")
def get_redemption_line_route(lid):
    _, role = require_roles("ProgramAdmin", "Member")
    line = get_redemption_line(lid)
    red = db.redemptions[line["redemption_id"]]
    user_id = request.headers.get("X-User-ID")
    assert_member_owner(role, user_id, red["member_id"])
    return success(serialize.redemption_line_out(line), 200)


@bp.get("/redemption-lines")
def list_redemption_lines_filter():
    _, role = require_roles("ProgramAdmin", "Member")
    user_id = request.headers.get("X-User-ID")
    reward_id = request.args.get("reward_id")
    redemption_id = request.args.get("redemption_id")
    items = list(db.redemption_lines.values())
    if role == "Member":
        owned = {r["id"] for r in db.redemptions.values()
                 if r["member_id"] == user_id}
        items = [l for l in items if l["redemption_id"] in owned]
    if reward_id is not None:
        items = [l for l in items if l["reward_id"] == reward_id]
    if redemption_id is not None:
        items = [l for l in items if l["redemption_id"] == redemption_id]
    page, pg = paginate(items)
    return success([serialize.redemption_line_out(x) for x in page], 200, pg)


@bp.post("/redemptions/<rid>/confirm")
def confirm_redemption(rid):
    _, role = require_roles("Member", "ProgramAdmin")
    red = get_redemption(rid)
    member = db.members[red["member_id"]]
    user_id = request.headers.get("X-User-ID")
    assert_member_owner(role, user_id, red["member_id"])
    program = db.programs[member["program_id"]]

    body = get_json_body()
    expected_member_version = opt_int(body, "expected_member_version", None)

    # target-state gate (priority 12)
    if red["status"] != "QUOTED":
        raise err(ERR_INVALID_STATE, "Redemption is not QUOTED")
    # member-active gate (priority 13)
    if member["status"] != "ACTIVE":
        raise err(ERR_MEMBER_NOT_ACTIVE, "Member is not ACTIVE")

    # fiscal sufficiency (priority 20) — available_points (counts expired unswept)
    ledger.recompute_member(member)
    if member["available_points"] < red["quoted_cost_points"]:
        raise err(ERR_INSUFFICIENT_POINTS, "Insufficient available points")

    # OCC last (priority 25), just before the write.
    if expected_member_version is not None and expected_member_version != member["version"]:
        raise err(ERR_STALE_MEMBER_VERSION, "Member version is stale")

    # Burn FIFO (skips past-expiry lots; ERR_LOT_EXPIRED if burnable supply short).
    ledger.fifo_burn(member, red["quoted_cost_points"], tx_type="REDEEM",
                     ref_redemption_id=red["id"])

    red["expected_member_version"] = expected_member_version
    red["status"] = "CONFIRMED"
    db.touch(red)
    ledger.recompute_member(member)
    db.touch(member)  # version advances by 1 (PRD §3.7)
    return success(serialize.redemption_out(red), 200)


@bp.post("/redemptions/<rid>/fulfill")
def fulfill_redemption(rid):
    require_roles("ProgramAdmin")
    red = get_redemption(rid)
    member = db.members[red["member_id"]]

    # target-state gate (priority 12)
    if red["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Redemption is not CONFIRMED")

    lines = [l for l in db.redemption_lines.values()
             if l["redemption_id"] == rid]
    lines.sort(key=lambda l: l["_seq"])

    # reward availability + stock at fulfillment (priorities 18-19)
    for line in lines:
        reward = db.rewards[line["reward_id"]]
        if reward["status"] != "ACTIVE":
            raise err(ERR_REWARD_UNAVAILABLE, "Reward is not ACTIVE")
    for line in lines:
        reward = db.rewards[line["reward_id"]]
        if reward["stock"] < line["quantity"]:
            raise err(ERR_INSUFFICIENT_STOCK, "Insufficient stock at fulfillment")

    # Recompute final cost using tier at fulfillment (PRD §3.7 final variant).
    ledger.recompute_member(member)
    tier_code = member["current_tier_code"]
    final_total = 0
    for line in lines:
        reward = db.rewards[line["reward_id"]]
        disc = ledger.applicable_discount(member["program_id"], tier_code, reward)
        final_total += ledger.line_cost(line["quantity"], reward["point_cost"], disc)

    red["final_cost_points"] = final_total
    quoted = red["quoted_cost_points"]

    if final_total < quoted:
        # refund the difference as an EARN_BONUS lot (PRD §3.7).
        ledger.mint_lot(member, source_type="EARN_BONUS",
                        points=quoted - final_total, source_id=red["id"],
                        tx_type="EARN_BONUS", ref_redemption_id=red["id"])
    elif final_total > quoted:
        # burn the extra shortfall in FIFO order.
        ledger.fifo_burn(member, final_total - quoted, tx_type="REDEEM",
                         ref_redemption_id=red["id"])

    # Decrement stock per line.
    for line in lines:
        reward = db.rewards[line["reward_id"]]
        reward["stock"] -= line["quantity"]
        db.touch(reward)

    red["status"] = "FULFILLED"
    db.touch(red)
    ledger.recompute_member(member)
    db.touch(member)
    return success(serialize.redemption_out(red), 200)


@bp.post("/redemptions/<rid>/cancel")
def cancel_redemption(rid):
    _, role = require_roles("Member", "ProgramAdmin")
    red = get_redemption(rid)
    member = db.members[red["member_id"]]
    user_id = request.headers.get("X-User-ID")
    assert_member_owner(role, user_id, red["member_id"])

    if red["status"] == "QUOTED":
        # nothing burned; clean cancel.
        red["status"] = "CANCELLED"
        db.touch(red)
        return success(serialize.redemption_out(red), 200)

    if red["status"] == "CONFIRMED":
        # compensation: mint a single EARN_BONUS lot of quoted_cost_points.
        ledger.mint_lot(member, source_type="EARN_BONUS",
                        points=red["quoted_cost_points"], source_id=red["id"],
                        tx_type="EARN_BONUS", ref_redemption_id=red["id"])
        red["status"] = "CANCELLED"
        db.touch(red)
        ledger.recompute_member(member)
        db.touch(member)
        return success(serialize.redemption_out(red), 200)

    raise err(ERR_INVALID_STATE, "Redemption cannot be cancelled from its state")
