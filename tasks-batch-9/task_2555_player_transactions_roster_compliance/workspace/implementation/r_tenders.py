"""Qualifying offers and restricted tenders (PRD 3.8)."""
from flask import Blueprint

import calc
import domain
import shape
import views
from auth import (
    LEAGUE_OFFICER, PLAYER_AGENT, TEAM_CAP_ANALYST, endpoint, require_team_scope,
)
from envelope import filter_records, paginate, single
from errors import fail
from store import base_record, db, hours, touch, values

bp = Blueprint("tenders", __name__)

OFFER_TYPES = ("QUALIFYING_OFFER", "RESTRICTED_TENDER", "ARBITRATION_TENDER")
TENDER_LEVELS = ("FIRST_ROUND", "SECOND_ROUND", "ORIGINAL_ROUND", "RIGHT_OF_FIRST_REFUSAL")


@bp.route("/qualifying-offers", methods=["POST"])
@endpoint(TEAM_CAP_ANALYST)
def create_tender(actor):
    body = shape.body()
    raw_team = shape.raw(body, "team_id")
    if isinstance(raw_team, str) and raw_team.strip() != actor.user_id:
        fail("ERR_ACTOR_SCOPE_VIOLATION", "tender belongs to another club")
    player_id = shape.req_ref(body, "player_id")
    team_id = shape.req_ref(body, "team_id")
    require_team_scope(actor, team_id)
    offer_type = shape.req_enum(body, "offer_type", OFFER_TYPES)
    tender_level = shape.req_enum(body, "tender_level", TENDER_LEVELS)
    prior_base = shape.req_int(body, "prior_base_salary_cents", minimum=0)
    player = domain.get_player(player_id)
    team = domain.get_team(team_id)
    # Rule 13
    if player["roster_designation"] != "UNROSTERED":
        fail("ERR_INVALID_TENDER_STATE", "player is still under roster control")
    # Rule 15
    domain.require_not_frozen(team)
    # Rule 16
    if player["medical_status"] == "FAILED_PHYSICAL":
        fail("ERR_PLAYER_FAILED_PHYSICAL", "player has failed a physical")
    # Rule 32
    for existing in values(db.qualifying_offers, lambda t: t["player_id"] == player_id):
        if existing["team_id"] == team_id and existing["status"] == "ISSUED":
            fail("ERR_TENDER_ALREADY_ISSUED", "club has already tendered this player")
    # Rule 35
    rights = domain.contract_rights_class(player)
    if rights not in ("RESTRICTED", "ARBITRATION_ELIGIBLE"):
        fail("ERR_RESTRICTED_RIGHTS_REQUIRED", "player does not hold tenderable rights")
    if offer_type == "ARBITRATION_TENDER" and rights != "ARBITRATION_ELIGIBLE":
        fail("ERR_RESTRICTED_RIGHTS_REQUIRED", "arbitration tender requires arbitration eligibility")
    # Rule 37
    domain.recompute_team(team)
    if team["provisional_cap_committed_cents"] > team["salary_cap_limit_cents"]:
        fail("ERR_CAP_LIMIT_EXCEEDED", "club is over the provisional cap")
    amount = calc.tender_amount(
        prior_base, tender_level, offer_type, domain.service_years(player)
    )
    record = base_record()
    record.update({
        "player_id": player_id,
        "team_id": team_id,
        "offer_type": offer_type,
        "tender_level": tender_level,
        "prior_base_salary_cents": prior_base,
        "amount_cents": amount,
        "status": "ISSUED",
        "issued_at": db.clock,
        "deadline_at": calc.snap(db.clock + hours(calc.TENDER_RESPONSE_HOURS)),
        "responded_at": None,
        "resulting_transaction_id": None,
    })
    db.qualifying_offers[record["id"]] = record
    return single(views.qualifying_offer(record), 201)


@bp.route("/qualifying-offers/<tender_id>", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST, PLAYER_AGENT)
def read_tender(actor, tender_id):
    record = domain.get_tender(tender_id)
    return single(views.qualifying_offer(record))


@bp.route("/qualifying-offers", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST, PLAYER_AGENT)
def list_tenders(actor):
    records = filter_records(values(db.qualifying_offers), {
        "player_id": "player_id",
        "team_id": "team_id",
        "resulting_transaction_id": "resulting_transaction_id",
        "status": "status",
    })
    return paginate(records, views.qualifying_offer)


def _accept_tender(record, team, player):
    filing = base_record()
    filing.update({
        "team_id": team["id"],
        "player_id": player["id"],
        "transaction_type": "SIGNING",
        "status": "DRAFT",
        "target_designation": None,
        "injury_designation_id": None,
        "contract_id": None,
        "requires_physical": True,
        "filing_deadline_at": calc.snap(db.clock + hours(calc.FILING_DEADLINE_HOURS)),
        "filed_at": None,
        "filed_by_user_id": None,
        "decided_at": None,
        "decided_by_user_id": None,
        "effective_at": None,
        "rejection_reason": None,
        "revision_count": 0,
        "prior_designation": None,
    })
    contract = base_record()
    contract.update({
        "player_id": player["id"],
        "team_id": team["id"],
        "signed_via_transaction_id": filing["id"],
        "status": "PENDING_APPROVAL",
        "years": 1,
        "base_salary_cents": record["amount_cents"],
        "base_guaranteed": False,
        "signing_bonus_cents": 0,
        "start_season_year": calc.CURRENT_SEASON_YEAR,
        "is_practice_squad_contract": False,
        "proration_years": 0,
        "annual_proration_cents": 0,
        "final_season_proration_cents": 0,
        "current_season_cap_charge_cents": 0,
        "total_value_cents": 0,
        "option_type": "NONE",
        "option_deadline_at": None,
        "option_salary_cents": None,
        "option_status": "NOT_APPLICABLE",
        "dead_money_current_season_cents": 0,
        "dead_money_next_season_cents": 0,
        "termination_reason": None,
        "_performance_ltbe_cents": 0,
        "_performance_nltbe_cents": 0,
    })
    domain.apply_proration(contract)
    filing["contract_id"] = contract["id"]
    db.contracts[contract["id"]] = contract
    db.transactions[filing["id"]] = filing
    record["resulting_transaction_id"] = filing["id"]
    domain.recompute_team(team, event=True)
    touch(team)


@bp.route("/qualifying-offers/<tender_id>/respond", methods=["POST"])
@endpoint(PLAYER_AGENT)
def respond_tender(actor, tender_id):
    record = domain.get_tender(tender_id)
    # Rule 5: only the player's own agent may answer.
    if actor.user_id != record["player_id"]:
        fail("ERR_ACTOR_SCOPE_VIOLATION", "tender belongs to another player")
    body = shape.body()
    response = shape.req_enum(body, "response", ("ACCEPT", "DECLINE"))
    # Rule 13
    if record["status"] != "ISSUED":
        fail("ERR_INVALID_TENDER_STATE", "tender is no longer open")
    team = domain.get_team(record["team_id"])
    player = domain.get_player(record["player_id"])
    # Rule 15: only an acceptance needs the club to be transacting.
    if response == "ACCEPT":
        domain.require_not_frozen(team)
    # Rule 25: on the deadline is on time.
    if db.clock > record["deadline_at"]:
        fail("ERR_TENDER_DEADLINE_PASSED", "tender deadline has passed")
    record["responded_at"] = db.clock
    if response == "ACCEPT":
        record["status"] = "ACCEPTED"
        _accept_tender(record, team, player)
    else:
        record["status"] = "DECLINED"
    touch(record)
    return single(views.qualifying_offer(record))
