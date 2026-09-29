"""Contract reads, option decisions and bonus allocations (PRD 3.4)."""
from flask import Blueprint

import calc
import domain
import shape
import views
from auth import (
    LEAGUE_OFFICER, PLAYER_AGENT, TEAM_CAP_ANALYST, endpoint,
)
from envelope import filter_records, paginate, single
from errors import fail
from store import db, touch, values

bp = Blueprint("contracts", __name__)


@bp.route("/contracts/<contract_id>", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST, PLAYER_AGENT)
def read_contract(actor, contract_id):
    record = domain.get_contract(contract_id)
    return single(views.contract(record))


@bp.route("/contracts", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST, PLAYER_AGENT)
def list_contracts(actor):
    records = filter_records(values(db.contracts), {
        "team_id": "team_id",
        "player_id": "player_id",
        "signed_via_transaction_id": "signed_via_transaction_id",
        "status": "status",
    })
    return paginate(records, views.contract)


@bp.route("/contracts/<contract_id>/bonus-allocations", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST, PLAYER_AGENT)
def list_bonus_allocations(actor, contract_id):
    contract = domain.get_contract(contract_id)
    records = domain.contract_allocations(contract["id"])
    return paginate(records, views.bonus_allocation)


@bp.route("/contracts/<contract_id>/trade-assets", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST)
def list_contract_trade_assets(actor, contract_id):
    contract = domain.get_contract(contract_id)
    records = values(db.trade_assets, lambda a: a["contract_id"] == contract["id"])
    return paginate(records, views.trade_asset)


@bp.route("/contracts/<contract_id>/option-decision", methods=["POST"])
@endpoint(TEAM_CAP_ANALYST, PLAYER_AGENT)
def option_decision(actor, contract_id):
    contract = domain.get_contract(contract_id)
    # Rule 5: a team option belongs to the club, a player option to the agent.
    if actor.role == TEAM_CAP_ANALYST:
        if actor.user_id != contract["team_id"]:
            fail("ERR_ACTOR_SCOPE_VIOLATION", "contract belongs to another club")
        if contract["option_type"] == "PLAYER_OPTION":
            fail("ERR_ACTOR_SCOPE_VIOLATION", "a player option is decided by the agent")
    else:
        if actor.user_id != contract["player_id"]:
            fail("ERR_ACTOR_SCOPE_VIOLATION", "contract belongs to another player")
        if contract["option_type"] == "TEAM_OPTION":
            fail("ERR_ACTOR_SCOPE_VIOLATION", "a team option is decided by the club")
    body = shape.body()
    decision = shape.req_enum(body, "decision", ("EXERCISE", "DECLINE"))
    expected_version = shape.req_int(body, "expected_contract_version")
    # Rule 12
    domain.require_occ(expected_version, contract, "ERR_STALE_CONTRACT_VERSION")
    # Rule 13
    if contract["option_status"] != "PENDING":
        fail("ERR_INVALID_OPTION_STATE", "no pending option on this contract")
    if contract["status"] != "ACTIVE":
        fail("ERR_INVALID_CONTRACT_STATE", "contract is not active")
    # Rule 26: on the deadline is accepted.
    if contract["option_deadline_at"] is None or db.clock > contract["option_deadline_at"]:
        fail("ERR_OPTION_DEADLINE_PASSED", "option deadline has passed")
    team = domain.get_team(contract["team_id"])
    player = domain.get_player(contract["player_id"])
    if decision == "EXERCISE":
        contract["option_status"] = "EXERCISED"
        contract["base_salary_cents"] = contract["option_salary_cents"]
        contract["years"] = contract["years"] + 1
        domain.recompute_contract_charge(contract)
        touch(contract)
        domain.recompute_team(team, event=True)
    else:
        contract["option_status"] = "DECLINED"
        domain.terminate_contract(contract, "OPTION_DECLINED")
        domain.set_designation(player, "UNROSTERED", team_id=None)
        domain.recompute_team(team, event=True)
    return single(views.contract(contract))


@bp.route("/bonus-allocations/<allocation_id>/earn", methods=["POST"])
@endpoint(LEAGUE_OFFICER)
def earn_allocation(actor, allocation_id):
    allocation = domain.get_allocation(allocation_id)
    contract = domain.get_contract(allocation["contract_id"])
    # Rule 13: only a SCHEDULED row on an ACTIVE contract may be earned.
    if allocation["allocation_status"] != "SCHEDULED":
        fail("ERR_INVALID_CONTRACT_STATE", "allocation is not scheduled")
    if contract["status"] != "ACTIVE":
        fail("ERR_INVALID_CONTRACT_STATE", "parent contract is not active")
    allocation["allocation_status"] = "EARNED"
    allocation["earned_at"] = db.clock
    touch(allocation)
    team = db.teams.get(contract["team_id"])
    if team is not None:
        domain.recompute_team(team, event=True)
    return single(views.bonus_allocation(allocation))
