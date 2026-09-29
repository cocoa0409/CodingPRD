"""Trade negotiation and execution (PRD 3.7)."""
from flask import Blueprint

import calc
import domain
import shape
import views
from auth import (
    LEAGUE_OFFICER, TEAM_CAP_ANALYST, TEAM_MEDICAL_OFFICER, endpoint,
    require_team_scope,
)
from envelope import filter_records, paginate, single
from errors import fail
from store import base_record, db, hours, touch, values

bp = Blueprint("trades", __name__)

CLAUSE_TYPES = ("NONE", "PICK_CONDITIONAL", "PHYSICAL_CONTINGENT")
ASSET_KINDS = ("CONTRACT", "DRAFT_PICK", "CASH_CONSIDERATION")
DIRECTIONS = ("TO_COUNTERPARTY", "TO_INITIATOR")
NEGOTIABLE = ("PROPOSED", "COUNTERED")


def _expected_actor(trade):
    if trade["status"] == "PROPOSED":
        return trade["counterparty_team_id"]
    if trade["status"] == "COUNTERED":
        return trade["initiating_team_id"]
    return None


def _require_party(actor, trade):
    if actor.user_id not in (trade["initiating_team_id"], trade["counterparty_team_id"]):
        fail("ERR_ACTOR_SCOPE_VIOLATION", "club is not a party to this trade")


def _require_turn(actor, trade):
    _require_party(actor, trade)
    expected = _expected_actor(trade)
    if expected is not None and actor.user_id != expected:
        fail("ERR_ACTOR_SCOPE_VIOLATION", "the other club owes the response")


def _sending_club(trade, direction):
    if direction == "TO_COUNTERPARTY":
        return trade["initiating_team_id"]
    return trade["counterparty_team_id"]


def _receiving_club(trade, direction):
    if direction == "TO_COUNTERPARTY":
        return trade["counterparty_team_id"]
    return trade["initiating_team_id"]


def _medical_slot_free(team_id, start, end, ignore_trade_id=None):
    """Closed-interval occupancy: touching endpoints do collide."""
    occupied = 0
    for trade in db.trades.values():
        if trade["status"] != "MEDICAL_REVIEW" or trade["id"] == ignore_trade_id:
            continue
        if team_id not in (trade["initiating_team_id"], trade["counterparty_team_id"]):
            continue
        existing_start = trade["accepted_at"]
        existing_end = trade["medical_review_deadline_at"]
        if existing_start is None or existing_end is None:
            continue
        if start <= existing_end and existing_start <= end:
            occupied += 1
    return occupied < calc.MAX_CONCURRENT_MEDICAL_REVIEWS


@bp.route("/trades", methods=["POST"])
@endpoint(TEAM_CAP_ANALYST)
def create_trade(actor):
    body = shape.body()
    raw_team = shape.raw(body, "initiating_team_id")
    if isinstance(raw_team, str) and raw_team.strip() != actor.user_id:
        fail("ERR_ACTOR_SCOPE_VIOLATION", "trade belongs to another club")
    initiating_team_id = shape.req_ref(body, "initiating_team_id")
    require_team_scope(actor, initiating_team_id)
    counterparty_team_id = shape.req_ref(body, "counterparty_team_id")
    clause = shape.opt_enum(body, "conditional_clause_type", CLAUSE_TYPES, "NONE")
    note = shape.opt_str(body, "condition_note", None)
    if clause in ("PICK_CONDITIONAL", "PHYSICAL_CONTINGENT") and not note:
        fail("ERR_INVALID_REQUEST", "condition_note is required for a conditional clause")
    initiating = domain.get_team(initiating_team_id)
    counterparty = domain.get_team(counterparty_team_id)
    # Rule 15
    domain.require_not_frozen(initiating)
    domain.require_not_frozen(counterparty)
    # Rule 33
    if initiating_team_id == counterparty_team_id:
        fail("ERR_TRADE_SAME_TEAM", "a club cannot trade with itself")
    record = base_record()
    record.update({
        "initiating_team_id": initiating_team_id,
        "counterparty_team_id": counterparty_team_id,
        "status": "PROPOSED",
        "conditional_clause_type": clause,
        "condition_note": note,
        "round_count": 1,
        "accepted_at": None,
        "medical_review_deadline_at": None,
        "executed_at": None,
        "void_reason": None,
        "cap_delta_initiating_cents": 0,
        "cap_delta_counterparty_cents": 0,
    })
    db.trades[record["id"]] = record
    return single(views.trade(record), 201)


@bp.route("/trades/<trade_id>", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST, TEAM_MEDICAL_OFFICER)
def read_trade(actor, trade_id):
    record = domain.get_trade(trade_id)
    return single(views.trade(record))


@bp.route("/trades", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST, TEAM_MEDICAL_OFFICER)
def list_trades(actor):
    records = filter_records(values(db.trades), {
        "initiating_team_id": "initiating_team_id",
        "counterparty_team_id": "counterparty_team_id",
        "status": "status",
    })
    return paginate(records, views.trade)


@bp.route("/trades/<trade_id>/assets", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST, TEAM_MEDICAL_OFFICER)
def list_trade_assets(actor, trade_id):
    trade = domain.get_trade(trade_id)
    return paginate(domain.trade_assets(trade["id"]), views.trade_asset)


@bp.route("/trades/<trade_id>/assets", methods=["POST"])
@endpoint(TEAM_CAP_ANALYST)
def add_trade_asset(actor, trade_id):
    trade = domain.get_trade(trade_id)
    _require_party(actor, trade)
    body = shape.body()
    asset_kind = shape.req_enum(body, "asset_kind", ASSET_KINDS)
    direction = shape.req_enum(body, "direction", DIRECTIONS)
    expected_trade_version = shape.req_int(body, "expected_trade_version")
    contract_id = None
    draft_pick_year = None
    draft_pick_round = None
    cash_amount_cents = None
    if asset_kind == "CONTRACT":
        contract_id = shape.req_ref(body, "contract_id")
        if shape.present(body, "draft_pick_year") or shape.present(body, "draft_pick_round") \
                or shape.present(body, "cash_amount_cents"):
            fail("ERR_INVALID_REQUEST", "contract assets carry no other companion field")
    elif asset_kind == "DRAFT_PICK":
        draft_pick_year = shape.req_int(body, "draft_pick_year", minimum=2027, maximum=2031)
        draft_pick_round = shape.req_int(body, "draft_pick_round", minimum=1, maximum=7)
        if shape.present(body, "contract_id") or shape.present(body, "cash_amount_cents"):
            fail("ERR_INVALID_REQUEST", "draft picks carry no other companion field")
    else:
        cash_amount_cents = shape.req_int(body, "cash_amount_cents", minimum=1)
        if shape.present(body, "contract_id") or shape.present(body, "draft_pick_year") \
                or shape.present(body, "draft_pick_round"):
            fail("ERR_INVALID_REQUEST", "cash considerations carry no other companion field")
    # Rule 5: only the sending club may add an asset.
    if actor.user_id != _sending_club(trade, direction):
        fail("ERR_ACTOR_SCOPE_VIOLATION", "only the sending club may add this asset")
    contract = domain.get_contract(contract_id) if contract_id else None
    # Rule 11
    domain.require_occ(expected_trade_version, trade, "ERR_STALE_TRADE_VERSION")
    # Rule 13
    if trade["status"] not in NEGOTIABLE:
        fail("ERR_INVALID_TRADE_STATE", "the trade no longer accepts assets")
    # Rule 21
    if contract is not None:
        if contract["status"] != "ACTIVE" or contract["team_id"] != _sending_club(trade, direction):
            fail("ERR_ASSET_NOT_OWNED", "contract is not an active asset of the sending club")
    snapshot = 0
    if asset_kind == "CONTRACT":
        snapshot = contract["current_season_cap_charge_cents"]
    elif asset_kind == "CASH_CONSIDERATION":
        snapshot = cash_amount_cents
    record = base_record()
    record.update({
        "trade_id": trade["id"],
        "asset_kind": asset_kind,
        "direction": direction,
        "contract_id": contract_id,
        "draft_pick_year": draft_pick_year,
        "draft_pick_round": draft_pick_round,
        "cash_amount_cents": cash_amount_cents if cash_amount_cents is not None else 0,
        "status": "PROPOSED",
        "cap_charge_snapshot_cents": snapshot,
    })
    db.trade_assets[record["id"]] = record
    domain.recompute_trade_deltas(trade)
    touch(trade)
    return single(views.trade_asset(record), 201)


@bp.route("/trades/<trade_id>/counter", methods=["POST"])
@endpoint(TEAM_CAP_ANALYST)
def counter_trade(actor, trade_id):
    trade = domain.get_trade(trade_id)
    _require_turn(actor, trade)
    body = shape.body()
    expected_trade_version = shape.req_int(body, "expected_trade_version")
    # Rule 11
    domain.require_occ(expected_trade_version, trade, "ERR_STALE_TRADE_VERSION")
    # Rule 13
    if trade["status"] not in NEGOTIABLE:
        fail("ERR_INVALID_TRADE_STATE", "the trade cannot be countered")
    if trade["round_count"] >= calc.MAX_TRADE_ROUNDS:
        # The round budget is spent: this counter kills the deal.
        trade["round_count"] = trade["round_count"] + 1
        domain.void_trade(trade, "ROUND_LIMIT_EXCEEDED")
        return single(views.trade(trade))
    trade["round_count"] = trade["round_count"] + 1
    trade["status"] = "COUNTERED" if trade["status"] == "PROPOSED" else "PROPOSED"
    touch(trade)
    return single(views.trade(trade))


@bp.route("/trades/<trade_id>/accept", methods=["POST"])
@endpoint(TEAM_CAP_ANALYST)
def accept_trade(actor, trade_id):
    trade = domain.get_trade(trade_id)
    _require_turn(actor, trade)
    # Rule 13
    if trade["status"] not in NEGOTIABLE:
        fail("ERR_INVALID_TRADE_STATE", "the trade cannot be accepted")
    if not domain.proposed_assets(trade["id"]):
        fail("ERR_INVALID_TRADE_STATE", "the trade carries no proposed asset")
    initiating, counterparty = domain.trade_clubs(trade)
    # Rule 15
    domain.require_not_frozen(initiating)
    domain.require_not_frozen(counterparty)
    if trade["conditional_clause_type"] == "PHYSICAL_CONTINGENT":
        candidate_start = db.clock
        candidate_end = db.clock + hours(calc.MEDICAL_REVIEW_HOURS)
        # Rule 31: capacity is exactly one open review per club.
        for club in (initiating, counterparty):
            if not _medical_slot_free(club["id"], candidate_start, candidate_end, trade["id"]):
                fail("ERR_MEDICAL_REVIEW_SLOT_TAKEN", "club already has an open medical review")
        trade["status"] = "MEDICAL_REVIEW"
        trade["accepted_at"] = db.clock
        trade["medical_review_deadline_at"] = candidate_end
        touch(trade)
        for club in (initiating, counterparty):
            domain.recompute_team(club)
    else:
        trade["status"] = "ACCEPTED"
        trade["accepted_at"] = db.clock
        touch(trade)
    return single(views.trade(trade))


@bp.route("/trades/<trade_id>/execute", methods=["POST"])
@endpoint(LEAGUE_OFFICER)
def execute_trade(actor, trade_id):
    trade = domain.get_trade(trade_id)
    # Rule 13
    if trade["status"] not in ("ACCEPTED", "MEDICAL_REVIEW"):
        fail("ERR_INVALID_TRADE_STATE", "only an accepted trade may be executed")
    initiating, counterparty = domain.trade_clubs(trade)
    # Rule 15
    domain.require_not_frozen(initiating)
    domain.require_not_frozen(counterparty)
    assets = domain.proposed_assets(trade["id"])
    contract_assets = [a for a in assets if a["asset_kind"] == "CONTRACT"]
    # Rule 16
    for asset in contract_assets:
        contract = db.contracts.get(asset["contract_id"])
        player = db.players.get(contract["player_id"]) if contract else None
        if player is not None and player["medical_status"] == "FAILED_PHYSICAL":
            fail("ERR_PLAYER_FAILED_PHYSICAL", "a player in the deal has failed a physical")
    # Rule 21: ownership is re-tested at execution.
    for asset in contract_assets:
        contract = db.contracts.get(asset["contract_id"])
        sender = _sending_club(trade, asset["direction"])
        if contract is None or contract["status"] != "ACTIVE" or contract["team_id"] != sender:
            fail("ERR_ASSET_NOT_OWNED", "contract is no longer owned by the sending club")
    # Rule 22
    domain.require_window()
    if trade["status"] == "MEDICAL_REVIEW":
        # Rule 28
        if trade["medical_review_deadline_at"] is None or db.clock > trade["medical_review_deadline_at"]:
            fail("ERR_MEDICAL_WINDOW_EXPIRED", "the medical review window has expired")
        for exam in values(db.physical_exams, lambda e: e["trade_id"] == trade["id"]):
            if exam["status"] != "PASSED" or exam["expires_at"] is None or exam["expires_at"] <= db.clock:
                fail("ERR_PHYSICAL_NOT_PASSED", "a trade physical is not passed and current")
    # Rule 36: each receiving club must have room for the players it takes in.
    moves = {}
    for asset in contract_assets:
        contract = db.contracts.get(asset["contract_id"])
        player = db.players.get(contract["player_id"])
        sender = _sending_club(trade, asset["direction"])
        receiver = _receiving_club(trade, asset["direction"])
        outgoing = player["roster_designation"] if player["current_team_id"] == sender else None
        moves.setdefault(sender, []).append((outgoing, None))
        moves.setdefault(receiver, []).append((None, "ACTIVE"))
    for team_id, pairs in moves.items():
        club = db.teams.get(team_id)
        if club is None:
            continue
        projected = domain.projected_counts(club, pairs)
        if projected["ACTIVE"] > club["active_roster_limit"]:
            fail("ERR_ROSTER_LIMIT_EXCEEDED", "receiving club has no active roster room")
    # Rule 38: both clubs must fit under their caps after their own delta.
    domain.recompute_trade_deltas(trade)
    for club, delta in (
        (initiating, trade["cap_delta_initiating_cents"]),
        (counterparty, trade["cap_delta_counterparty_cents"]),
    ):
        domain.recompute_team(club)
        if club["provisional_cap_committed_cents"] + delta > club["salary_cap_limit_cents"]:
            fail("ERR_TRADE_CAP_INCOMPATIBLE", "trade does not fit under both salary caps")

    was_medical_review = trade["status"] == "MEDICAL_REVIEW"
    trade["status"] = "EXECUTED"
    trade["executed_at"] = db.clock
    for asset in assets:
        if asset["asset_kind"] == "CONTRACT":
            contract = db.contracts.get(asset["contract_id"])
            player = db.players.get(contract["player_id"])
            receiver = _receiving_club(trade, asset["direction"])
            contract["team_id"] = receiver
            touch(contract)
            domain.set_designation(player, "ACTIVE", team_id=receiver)
        asset["status"] = "TRANSFERRED"
        touch(asset)
    touch(trade)
    for club in (initiating, counterparty):
        if club is not None:
            domain.recompute_team(club, event=True)
    return single(views.trade(trade))
