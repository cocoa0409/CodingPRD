"""Pick trades: proposal, counter, accept, termination and the conditional
dimension (PRD 3.6)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import constants as K
import derive
import logic
import respond
import validate
from db import db
from errors import ApiError

bp = Blueprint("trades", __name__)

READ_ROLES = ["LeagueDraftAdmin", "ClubGM"]

TERMINATION_ROLES = {
    "WITHDRAW": ("ClubGM",),
    "REJECT": ("ClubGM",),
    "RESCIND": ("LeagueDraftAdmin",),
}


def _suspended(club):
    return derive.club_tier(club) == "SUSPENDED"


def _tier_guard(*clubs):
    for club in clubs:
        if club is not None and _suspended(club):
            raise ApiError(
                "ERR_TRADE_AUTHORIZATION_SUSPENDED",
                "Club %s is suspended from the trade market." % club["club_code"],
            )


def _parties(trade):
    return (trade["proposing_club_id"], trade["receiving_club_id"])


def _self_trade(detail):
    raise ApiError("ERR_SELF_TRADE_FORBIDDEN", detail)


@bp.post("/pick-trades")
def create_trade():
    user_id, role = auth.begin(["ClubGM"])
    data = validate.body()
    cycle_id = validate.string(data, "draft_cycle_id")
    proposing_club_id = validate.string(data, "proposing_club_id")
    receiving_club_id = validate.string(data, "receiving_club_id")
    offered_ids = validate.id_list(data, "offered_pick_ids")
    requested_ids = validate.id_list(data, "requested_pick_ids")
    conditional_round_number = validate.integer(
        data, "conditional_round_number", required=False, minimum=1, maximum=7
    )
    conditional_condition_code = validate.enum(
        data, "conditional_condition_code", K.CONDITION_CODES, required=False
    )
    if (conditional_round_number is None) != (conditional_condition_code is None):
        validate.bad(
            "conditional_round_number and conditional_condition_code must be "
            "supplied together."
        )

    cycle = logic.fk_lookup(db.draft_cycles, cycle_id, "draft cycle")
    proposing = logic.fk_lookup(db.clubs, proposing_club_id, "club")
    receiving = logic.fk_lookup(db.clubs, receiving_club_id, "club")
    for pick_id in offered_ids + requested_ids:
        logic.fk_lookup(db.draft_picks, pick_id, "draft pick")

    logic.own_club(role, user_id, proposing["id"])
    logic.require_phase(cycle, ("ORDER_FINAL", "DRAFT_LIVE"))
    logic.require_unfrozen(cycle)

    if proposing["id"] == receiving["id"]:
        _self_trade("A club may not trade with itself.")

    logic.require_same_cycle(proposing["draft_cycle_id"], cycle["id"])
    logic.require_same_cycle(receiving["draft_cycle_id"], cycle["id"])
    for pick_id in offered_ids + requested_ids:
        logic.require_same_cycle(db.draft_picks[pick_id]["draft_cycle_id"], cycle["id"])

    logic.check_pick_package(
        cycle["id"], offered_ids, requested_ids, proposing["id"], receiving["id"]
    )
    _tier_guard(proposing, receiving)

    balance, ratio, surplus = logic.trade_valuation(offered_ids, requested_ids)
    attached = conditional_condition_code is not None
    rec = db.insert(
        db.pick_trades,
        "PickTrade",
        {
            "draft_cycle_id": cycle["id"],
            "proposing_club_id": proposing["id"],
            "receiving_club_id": receiving["id"],
            "offered_pick_ids": list(offered_ids),
            "requested_pick_ids": list(requested_ids),
            "round_index": 1,
            "status": "PROPOSED",
            "last_actor_club_id": proposing["id"],
            "chart_balance_points": balance,
            "imbalance_ratio": ratio,
            "surplus_balance_points": surplus,
            "conditional_round_number": conditional_round_number,
            "conditional_condition_code": conditional_condition_code,
            "conditional_probability_tier": (
                K.CONDITION_TIERS[conditional_condition_code] if attached else None
            ),
            "conditional_status": "OPEN" if attached else "NONE",
            "conditional_conveyed_overall_number": 0,
        },
    )
    return respond.created(rec)


@bp.get("/pick-trades/<trade_id>")
def get_trade(trade_id):
    auth.begin(READ_ROLES)
    return respond.one(logic.path_lookup(db.pick_trades, trade_id))


@bp.get("/pick-trades")
def list_trades():
    auth.begin(READ_ROLES)
    limit, offset = validate.pagination()
    cycle_id = validate.query_str("draft_cycle_id")
    proposing_club_id = validate.query_str("proposing_club_id")
    receiving_club_id = validate.query_str("receiving_club_id")
    last_actor_club_id = validate.query_str("last_actor_club_id")
    status = validate.query_enum("status", K.TRADE_STATUSES)
    conditional_status = validate.query_enum(
        "conditional_status", K.CONDITIONAL_STATUSES
    )
    rows = list(db.pick_trades.values())
    if cycle_id is not None:
        rows = [r for r in rows if r["draft_cycle_id"] == cycle_id]
    if proposing_club_id is not None:
        rows = [r for r in rows if r["proposing_club_id"] == proposing_club_id]
    if receiving_club_id is not None:
        rows = [r for r in rows if r["receiving_club_id"] == receiving_club_id]
    if last_actor_club_id is not None:
        rows = [r for r in rows if r["last_actor_club_id"] == last_actor_club_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if conditional_status is not None:
        rows = [r for r in rows if r["conditional_status"] == conditional_status]
    return respond.listing(logic.by_created(rows), limit, offset)


@bp.post("/pick-trades/<trade_id>/counter")
def counter(trade_id):
    user_id, _role = auth.begin(["ClubGM"])
    data = validate.body()
    offered_ids = validate.id_list(data, "offered_pick_ids")
    requested_ids = validate.id_list(data, "requested_pick_ids")

    trade = logic.path_lookup(db.pick_trades, trade_id)
    for pick_id in offered_ids + requested_ids:
        logic.fk_lookup(db.draft_picks, pick_id, "draft pick")

    cycle = db.draft_cycles.get(trade["draft_cycle_id"])
    logic.require_phase(cycle, ("ORDER_FINAL", "DRAFT_LIVE"))
    logic.require_unfrozen(cycle)

    if trade["status"] not in ("PROPOSED", "COUNTERED"):
        raise logic.invalid_transition("Only an open negotiation may be countered.")
    if user_id == trade["last_actor_club_id"]:
        raise logic.invalid_transition("The clubs must alternate; you acted last.")
    if user_id not in _parties(trade):
        _self_trade("Only a party to the trade may counter it.")

    logic.check_pick_package(
        trade["draft_cycle_id"],
        offered_ids,
        requested_ids,
        trade["proposing_club_id"],
        trade["receiving_club_id"],
    )

    if trade["round_index"] >= K.TRADE_MAX_NEGOTIATION_ROUNDS:
        raise ApiError(
            "ERR_TRADE_ROUNDS_EXHAUSTED",
            "This negotiation has exhausted its rounds.",
        )

    if trade["status"] == "PROPOSED":
        _tier_guard(db.clubs.get(user_id))

    trade["offered_pick_ids"] = list(offered_ids)
    trade["requested_pick_ids"] = list(requested_ids)
    trade["round_index"] += 1
    trade["status"] = "COUNTERED"
    trade["last_actor_club_id"] = user_id
    logic.apply_valuation(trade)
    return respond.ok(trade)


@bp.post("/pick-trades/<trade_id>/accept")
def accept(trade_id):
    user_id, _role = auth.begin(["ClubGM"])
    validate.body()
    trade = logic.path_lookup(db.pick_trades, trade_id)
    if user_id not in _parties(trade):
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "Only a party to the trade may accept it."
        )

    cycle = db.draft_cycles.get(trade["draft_cycle_id"])
    logic.require_phase(cycle, ("ORDER_FINAL", "DRAFT_LIVE"))
    logic.require_unfrozen(cycle)

    if trade["status"] not in ("PROPOSED", "COUNTERED"):
        raise logic.invalid_transition("Only an open negotiation may be accepted.")
    if user_id == trade["last_actor_club_id"]:
        raise logic.invalid_transition("The clubs must alternate; you acted last.")

    logic.check_pick_package(
        trade["draft_cycle_id"],
        trade["offered_pick_ids"],
        trade["requested_pick_ids"],
        trade["proposing_club_id"],
        trade["receiving_club_id"],
    )
    proposing = db.clubs.get(trade["proposing_club_id"])
    receiving = db.clubs.get(trade["receiving_club_id"])
    _tier_guard(proposing, receiving)

    if calc.dec(trade["imbalance_ratio"]) > K.TRADE_TOLERANCE_RATIO:
        raise ApiError(
            "ERR_TRADE_VALUE_IMBALANCED",
            "The package exceeds the 0.15 imbalance tolerance.",
        )

    for pick_id in trade["offered_pick_ids"]:
        db.draft_picks[pick_id]["owning_club_id"] = trade["receiving_club_id"]
    for pick_id in trade["requested_pick_ids"]:
        db.draft_picks[pick_id]["owning_club_id"] = trade["proposing_club_id"]
    trade["status"] = "ACCEPTED"
    trade["last_actor_club_id"] = user_id
    return respond.ok(trade)


@bp.post("/pick-trades/<trade_id>/termination")
def termination(trade_id):
    user_id, role = auth.actor()
    auth.require(role, ["ClubGM", "LeagueDraftAdmin"])
    auth.require_action_role(role, validate.peek("action"), TERMINATION_ROLES)

    data = validate.body()
    action = validate.enum(data, "action", ("WITHDRAW", "REJECT", "RESCIND"))
    if action == "RESCIND":
        validate.string(data, "reason")

    trade = logic.path_lookup(db.pick_trades, trade_id)
    if role == "ClubGM" and user_id not in _parties(trade):
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "Only a party to the trade may terminate it."
        )

    cycle = db.draft_cycles.get(trade["draft_cycle_id"])
    logic.require_unfrozen(cycle)

    if action == "REJECT":
        if trade["status"] not in ("PROPOSED", "COUNTERED"):
            raise logic.invalid_transition("Only an open negotiation may be rejected.")
        if user_id == trade["last_actor_club_id"]:
            raise logic.invalid_transition("You may not reject your own offer.")
        trade["status"] = "REJECTED"
        return respond.ok(trade)

    if action == "WITHDRAW":
        if trade["status"] != "PROPOSED":
            raise logic.invalid_transition("Only a PROPOSED trade may be withdrawn.")
        if user_id != trade["last_actor_club_id"]:
            raise logic.invalid_transition(
                "Only the club holding the outstanding offer may withdraw it."
            )
        trade["status"] = "WITHDRAWN"
        return respond.ok(trade)

    # RESCIND
    if trade["status"] != "ACCEPTED":
        raise logic.invalid_transition("Only an ACCEPTED trade may be rescinded.")
    traded = trade["offered_pick_ids"] + trade["requested_pick_ids"]
    for pick_id in traded:
        pick = db.draft_picks.get(pick_id)
        if pick is None or pick["status"] != "PENDING":
            raise logic.invalid_transition(
                "Every traded pick must still be PENDING to rescind."
            )
    for pick_id in trade["offered_pick_ids"]:
        db.draft_picks[pick_id]["owning_club_id"] = trade["proposing_club_id"]
    for pick_id in trade["requested_pick_ids"]:
        db.draft_picks[pick_id]["owning_club_id"] = trade["receiving_club_id"]
    trade["status"] = "RESCINDED"
    if trade["conditional_status"] == "OPEN":
        trade["conditional_status"] = "VOID"
    return respond.ok(trade)


@bp.post("/pick-trades/<trade_id>/conditional-resolution")
def conditional_resolution(trade_id):
    auth.begin(["LeagueDraftAdmin"])
    data = validate.body()
    satisfied = validate.boolean(data, "condition_satisfied")

    trade = logic.path_lookup(db.pick_trades, trade_id)
    cycle = db.draft_cycles.get(trade["draft_cycle_id"])
    logic.require_unfrozen(cycle)

    if trade["status"] != "ACCEPTED":
        raise logic.invalid_transition(
            "A condition may only be resolved on an ACCEPTED trade."
        )
    if trade["conditional_status"] != "OPEN":
        raise logic.invalid_transition("This trade has no open condition.")

    if not satisfied:
        trade["conditional_status"] = "UNMET_EXTINGUISHED"
        return respond.ok(trade)

    tier = trade["conditional_probability_tier"]
    if tier == "REMOTE":
        trade["conditional_status"] = "DEFERRED"
        return respond.ok(trade)

    highest = 0
    for pick_id in trade["offered_pick_ids"] + trade["requested_pick_ids"]:
        pick = db.draft_picks.get(pick_id)
        if pick is not None and pick["overall_number"] > highest:
            highest = pick["overall_number"]
    trade["conditional_status"] = "MET_CONVEYED"
    trade["conditional_conveyed_overall_number"] = highest
    return respond.ok(trade)
