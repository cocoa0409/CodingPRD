"""Transaction filings: create, file, decide, revise (PRD 3.3)."""
from flask import Blueprint

import calc
import domain
import shape
import views
from auth import (
    LEAGUE_OFFICER, TEAM_CAP_ANALYST, TEAM_MEDICAL_OFFICER, endpoint,
    require_segregation, require_team_scope,
)
from envelope import filter_records, paginate, single
from errors import fail
from store import base_record, db, hours, days, touch, values

bp = Blueprint("transactions", __name__)

TRANSACTION_TYPES = (
    "SIGNING", "RELEASE", "DESIGNATION_CHANGE", "IR_PLACEMENT",
    "IR_ACTIVATION", "PRACTICE_SQUAD_ELEVATION",
)
DESIGNATION_TARGETS = ("ACTIVE", "RESERVE", "INJURED_RESERVE", "PRACTICE_SQUAD")
OPTION_TYPES = ("NONE", "TEAM_OPTION", "PLAYER_OPTION")
REQUIRES_PHYSICAL_TYPES = ("SIGNING", "IR_ACTIVATION")


def _signing_terms(body, required=True):
    """Contract terms carried by a SIGNING filing."""
    terms = {}
    if required:
        terms["years"] = shape.req_int(body, "years", minimum=1, maximum=7)
        terms["base_salary_cents"] = shape.req_int(body, "base_salary_cents", minimum=0)
    else:
        terms["years"] = shape.opt_int(body, "years", None, minimum=1, maximum=7)
        terms["base_salary_cents"] = shape.opt_int(
            body, "base_salary_cents", None, minimum=0
        )
    terms["base_guaranteed"] = shape.opt_bool(body, "base_guaranteed", None)
    terms["signing_bonus_cents"] = shape.opt_int(
        body, "signing_bonus_cents", None, minimum=0
    )
    terms["start_season_year"] = shape.opt_int(
        body, "start_season_year", None, minimum=2026, maximum=2030
    )
    terms["is_practice_squad_contract"] = shape.opt_bool(
        body, "is_practice_squad_contract", None
    )
    terms["option_type"] = shape.opt_enum(body, "option_type", OPTION_TYPES, None)
    terms["option_deadline_at"] = shape.opt_dt(body, "option_deadline_at", None)
    terms["option_salary_cents"] = shape.opt_int(
        body, "option_salary_cents", None, minimum=0
    )
    terms["performance_ltbe_cents"] = shape.opt_int(
        body, "performance_ltbe_cents", None, minimum=0
    )
    terms["performance_nltbe_cents"] = shape.opt_int(
        body, "performance_nltbe_cents", None, minimum=0
    )
    if terms["option_type"] in ("TEAM_OPTION", "PLAYER_OPTION"):
        if terms["option_deadline_at"] is None or terms["option_salary_cents"] is None:
            fail(
                "ERR_INVALID_REQUEST",
                "option_deadline_at and option_salary_cents are required with an option",
            )
    return terms


def _new_contract(transaction, terms):
    record = base_record()
    record.update({
        "player_id": transaction["player_id"],
        "team_id": transaction["team_id"],
        "signed_via_transaction_id": transaction["id"],
        "status": "PENDING_APPROVAL",
        "years": terms["years"],
        "base_salary_cents": terms["base_salary_cents"],
        "base_guaranteed": bool(terms["base_guaranteed"]),
        "signing_bonus_cents": terms["signing_bonus_cents"] or 0,
        "start_season_year": terms["start_season_year"] or calc.CURRENT_SEASON_YEAR,
        "is_practice_squad_contract": bool(terms["is_practice_squad_contract"]),
        "proration_years": 0,
        "annual_proration_cents": 0,
        "final_season_proration_cents": 0,
        "current_season_cap_charge_cents": 0,
        "total_value_cents": 0,
        "option_type": terms["option_type"] or "NONE",
        "option_deadline_at": terms["option_deadline_at"],
        "option_salary_cents": terms["option_salary_cents"],
        "option_status": "NOT_APPLICABLE",
        "dead_money_current_season_cents": 0,
        "dead_money_next_season_cents": 0,
        "termination_reason": None,
        "_performance_ltbe_cents": terms["performance_ltbe_cents"] or 0,
        "_performance_nltbe_cents": terms["performance_nltbe_cents"] or 0,
    })
    domain.apply_proration(record)
    return record


def _destination(transaction):
    kind = transaction["transaction_type"]
    if kind == "SIGNING":
        contract = db.contracts.get(transaction["contract_id"])
        if contract is not None and contract["is_practice_squad_contract"]:
            return "PRACTICE_SQUAD"
        return "ACTIVE"
    if kind == "RELEASE":
        return "WAIVED_PENDING"
    if kind in ("DESIGNATION_CHANGE", "PRACTICE_SQUAD_ELEVATION"):
        return transaction["target_designation"]
    if kind == "IR_PLACEMENT":
        return "INJURED_RESERVE"
    return "ACTIVE"


@bp.route("/transactions", methods=["POST"])
@endpoint(TEAM_CAP_ANALYST)
def create_transaction(actor):
    body = shape.body()
    # Rule 5: the acting club must be the club named in the body.
    raw_team = shape.raw(body, "team_id")
    if isinstance(raw_team, str) and raw_team.strip() != actor.user_id:
        fail("ERR_ACTOR_SCOPE_VIOLATION", "filing belongs to another club")
    # Rule 7: request shape.
    team_id = shape.req_ref(body, "team_id")
    require_team_scope(actor, team_id)
    player_id = shape.req_ref(body, "player_id")
    kind = shape.req_enum(body, "transaction_type", TRANSACTION_TYPES)
    expected_team_version = shape.req_int(body, "expected_team_version")
    target_designation = shape.opt_enum(
        body, "target_designation", DESIGNATION_TARGETS, None
    )
    designation_id = shape.opt_ref(body, "injury_designation_id")
    terms = None
    if kind == "SIGNING":
        terms = _signing_terms(body, required=True)
    if kind in ("DESIGNATION_CHANGE", "PRACTICE_SQUAD_ELEVATION") and target_designation is None:
        fail("ERR_INVALID_REQUEST", "target_designation is required")
    if kind in ("IR_PLACEMENT", "IR_ACTIVATION") and designation_id is None:
        fail("ERR_INVALID_REQUEST", "injury_designation_id is required")
    # Rule 9: body references resolve in declaration order.
    team = domain.get_team(team_id)
    player = domain.get_player(player_id)
    designation = domain.get_designation(designation_id) if designation_id else None
    # Rule 10: optimistic concurrency on the owning club.
    domain.require_occ(expected_team_version, team, "ERR_STALE_TEAM_VERSION")
    # Rule 13: the player's designation must admit this filing.
    if kind == "SIGNING":
        if player["roster_designation"] != "UNROSTERED":
            fail("ERR_INVALID_TRANSACTION_STATE", "player is already rostered")
    elif kind == "RELEASE":
        if player["current_team_id"] != team_id or player["roster_designation"] not in domain.ROSTERED_DESIGNATIONS:
            fail("ERR_INVALID_TRANSACTION_STATE", "player is not on this club's roster")
    elif kind in ("DESIGNATION_CHANGE", "PRACTICE_SQUAD_ELEVATION"):
        if player["current_team_id"] != team_id:
            fail("ERR_INVALID_TRANSACTION_STATE", "player is not on this club's roster")
        if player["roster_designation"] == target_designation:
            fail("ERR_INVALID_TRANSACTION_STATE", "player already holds that designation")
    # Rule 15: frozen clubs may not open filings.
    domain.require_not_frozen(team)
    # Rule 19: a cited designation must match the filing's player and club.
    if designation is not None:
        if designation["player_id"] != player_id or designation["team_id"] != team_id:
            fail("ERR_DESIGNATION_PLAYER_MISMATCH", "designation does not match filing")
    # Rule 34: practice-squad eligibility at create time.
    if kind == "PRACTICE_SQUAD_ELEVATION" and not domain.practice_squad_eligible(player):
        fail("ERR_PRACTICE_SQUAD_INELIGIBLE", "player is not practice-squad eligible")
    record = base_record()
    record.update({
        "team_id": team_id,
        "player_id": player_id,
        "transaction_type": kind,
        "status": "DRAFT",
        "target_designation": target_designation,
        "injury_designation_id": designation_id,
        "contract_id": None,
        "requires_physical": kind in REQUIRES_PHYSICAL_TYPES,
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
    contract = None
    if kind == "SIGNING":
        contract = _new_contract(record, terms)
        record["contract_id"] = contract["id"]
        # Rule 37: the provisional cap ceiling.
        domain.recompute_team(team)
        prospective = (
            team["provisional_cap_committed_cents"]
            + contract["current_season_cap_charge_cents"]
        )
        if prospective > team["salary_cap_limit_cents"]:
            fail("ERR_CAP_LIMIT_EXCEEDED", "signing would exceed the salary cap")
        db.contracts[contract["id"]] = contract
    db.transactions[record["id"]] = record
    domain.recompute_team(team, event=True)
    touch(team)
    return single(views.transaction(record), 201)


@bp.route("/transactions/<transaction_id>", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST, TEAM_MEDICAL_OFFICER)
def read_transaction(actor, transaction_id):
    record = domain.get_transaction(transaction_id)
    return single(views.transaction(record))


@bp.route("/transactions", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST, TEAM_MEDICAL_OFFICER)
def list_transactions(actor):
    records = filter_records(values(db.transactions), {
        "team_id": "team_id",
        "player_id": "player_id",
        "contract_id": "contract_id",
        "injury_designation_id": "injury_designation_id",
        "transaction_type": "transaction_type",
        "status": "status",
    })
    return paginate(records, views.transaction)


@bp.route("/transactions/<transaction_id>/file", methods=["POST"])
@endpoint(TEAM_CAP_ANALYST)
def file_transaction(actor, transaction_id):
    record = domain.get_transaction(transaction_id)
    require_team_scope(actor, record["team_id"])
    team = domain.get_team(record["team_id"])
    player = domain.get_player(record["player_id"])
    # Rule 13
    if record["status"] != "DRAFT":
        fail("ERR_INVALID_TRANSACTION_STATE", "only a DRAFT filing may be submitted")
    # Rule 15
    domain.require_not_frozen(team)
    # Rule 22
    domain.require_window()
    # Rule 23: on the deadline is on time.
    if db.clock > record["filing_deadline_at"]:
        fail("ERR_FILING_DEADLINE_PASSED", "filing deadline has passed")
    # Rule 36: post-approval headcounts must satisfy every quota.
    domain.require_projected_quotas(
        team, [(player["roster_designation"], _destination(record))]
    )
    record["status"] = "FILED"
    record["filed_at"] = db.clock
    record["filed_by_user_id"] = actor.user_id
    touch(record)
    return single(views.transaction(record))


def _approve(actor, record, team, player):
    kind = record["transaction_type"]
    designation = db.injury_designations.get(record["injury_designation_id"])
    destination = _destination(record)
    # Rule 16
    if player["medical_status"] == "FAILED_PHYSICAL":
        fail("ERR_PLAYER_FAILED_PHYSICAL", "player has failed a physical")
    # Rule 17
    if record["requires_physical"]:
        if domain.citable_physical(player["id"], record["id"]) is None:
            fail("ERR_PHYSICAL_NOT_PASSED", "no passed, unexpired physical on file")
    # Rule 18
    if kind == "IR_PLACEMENT":
        if designation is None or designation["status"] != "PAPERWORK_FILED":
            fail("ERR_INJURY_PAPERWORK_MISSING", "injury paperwork is not filed")
    if kind == "IR_ACTIVATION":
        if designation is None or designation["status"] != "RETURN_WINDOW_OPEN":
            fail("ERR_INJURY_PAPERWORK_MISSING", "return window is not open")
    # Rule 22
    domain.require_window()
    # Rule 27
    if kind == "IR_ACTIVATION":
        opens = designation["return_window_opens_at"]
        closes = designation["return_window_closes_at"]
        if opens is None or closes is None or db.clock < opens or db.clock > closes:
            fail("ERR_RETURN_WINDOW_CLOSED", "outside the return window")
    # Rule 34
    if destination == "PRACTICE_SQUAD" and not domain.practice_squad_eligible(player):
        fail("ERR_PRACTICE_SQUAD_INELIGIBLE", "player is not practice-squad eligible")
    # Rule 36
    domain.require_projected_quotas(team, [(player["roster_designation"], destination)])
    # Rule 37
    domain.recompute_team(team)
    if team["provisional_cap_committed_cents"] > team["salary_cap_limit_cents"]:
        fail("ERR_CAP_LIMIT_EXCEEDED", "club is over the provisional cap")

    record["prior_designation"] = player["roster_designation"]
    record["status"] = "APPROVED"
    record["decided_at"] = db.clock
    record["effective_at"] = db.clock
    record["decided_by_user_id"] = actor.user_id
    if kind == "SIGNING":
        contract = db.contracts.get(record["contract_id"])
        if contract is not None:
            contract["status"] = "ACTIVE"
            domain.materialise_allocations(
                contract,
                contract.get("_performance_ltbe_cents", 0),
                contract.get("_performance_nltbe_cents", 0),
            )
            if contract["option_type"] in ("TEAM_OPTION", "PLAYER_OPTION"):
                contract["option_status"] = "PENDING"
            else:
                contract["option_status"] = "NOT_APPLICABLE"
            touch(contract)
        domain.set_designation(player, destination, team_id=record["team_id"])
    elif kind == "RELEASE":
        # The club keeps the player's rights while the wire runs.
        domain.set_designation(player, "WAIVED_PENDING")
    elif kind in ("DESIGNATION_CHANGE", "PRACTICE_SQUAD_ELEVATION"):
        domain.set_designation(player, destination, team_id=record["team_id"])
    elif kind == "IR_PLACEMENT":
        domain.require_room_for(team, "INJURED_RESERVE")
        domain.set_designation(player, "INJURED_RESERVE", team_id=record["team_id"])
        designation["status"] = "ACTIVE"
        designation["activated_at"] = db.clock
        designation["return_window_opens_at"] = db.clock + days(
            designation["minimum_stay_days"]
        )
        designation["return_window_closes_at"] = (
            designation["return_window_opens_at"] + days(calc.RETURN_WINDOW_LENGTH_DAYS)
        )
        touch(designation)
    elif kind == "IR_ACTIVATION":
        domain.set_designation(player, "ACTIVE", team_id=record["team_id"])
        player["medical_status"] = "CLEARED"
        designation["status"] = "CLOSED"
        designation["closed_at"] = db.clock
        designation["ir_service_credit_days"] = calc.elapsed_days(
            designation["activated_at"], designation["closed_at"]
        )
        touch(designation)
    domain.recompute_team(team, event=True)
    touch(team)
    touch(record)


def _reject(actor, record, team, reason):
    domain.require_window()
    record["status"] = "REJECTED"
    record["decided_at"] = db.clock
    record["decided_by_user_id"] = actor.user_id
    record["rejection_reason"] = reason
    if record["transaction_type"] == "SIGNING":
        contract = db.contracts.get(record["contract_id"])
        if contract is not None:
            domain.void_contract(contract)
    domain.recompute_team(team, event=True)
    touch(team)
    touch(record)


@bp.route("/transactions/<transaction_id>/decide", methods=["POST"])
@endpoint(LEAGUE_OFFICER)
def decide_transaction(actor, transaction_id):
    record = domain.get_transaction(transaction_id)
    # Rule 6: the decider may not be the filer.
    require_segregation(actor, record["filed_by_user_id"])
    body = shape.body()
    decision = shape.req_enum(body, "decision", ("APPROVE", "REJECT"))
    reason = None
    if decision == "REJECT":
        reason = shape.req_str(body, "rejection_reason")
    # Rule 13
    if record["status"] != "FILED":
        fail("ERR_INVALID_TRANSACTION_STATE", "only a FILED filing may be decided")
    team = domain.get_team(record["team_id"])
    player = domain.get_player(record["player_id"])
    # Rule 15
    domain.require_not_frozen(team)
    if decision == "APPROVE":
        _approve(actor, record, team, player)
    else:
        _reject(actor, record, team, reason)
    return single(views.transaction(record))


@bp.route("/transactions/<transaction_id>/revise", methods=["POST"])
@endpoint(TEAM_CAP_ANALYST)
def revise_transaction(actor, transaction_id):
    record = domain.get_transaction(transaction_id)
    require_team_scope(actor, record["team_id"])
    body = shape.body()
    target_designation = shape.opt_enum(
        body, "target_designation", DESIGNATION_TARGETS, None
    )
    designation_id = shape.opt_ref(body, "injury_designation_id")
    terms = _signing_terms(body, required=False) if record["transaction_type"] == "SIGNING" else None
    if designation_id is not None:
        domain.get_designation(designation_id)
    # Rules 13 and 14: the revision budget is two.
    if record["status"] == "VOIDED" and record["revision_count"] >= calc.MAX_TRANSACTION_REVISIONS:
        fail("ERR_REVISION_LIMIT_EXCEEDED", "revision budget exhausted")
    if record["status"] != "REJECTED":
        fail("ERR_INVALID_TRANSACTION_STATE", "only a REJECTED filing may be revised")
    team = domain.get_team(record["team_id"])
    # Rule 15
    domain.require_not_frozen(team)
    # Rule 19
    effective_designation_id = designation_id or record["injury_designation_id"]
    if effective_designation_id:
        designation = domain.get_designation(effective_designation_id)
        if (
            designation["player_id"] != record["player_id"]
            or designation["team_id"] != record["team_id"]
        ):
            fail("ERR_DESIGNATION_PLAYER_MISMATCH", "designation does not match filing")
    # Rule 23: the deadline never moves, and a revision cannot outrun it.
    if db.clock > record["filing_deadline_at"]:
        fail("ERR_FILING_DEADLINE_PASSED", "filing deadline has passed")

    if record["revision_count"] < calc.MAX_TRANSACTION_REVISIONS:
        record["status"] = "DRAFT"
        record["revision_count"] = record["revision_count"] + 1
        record["rejection_reason"] = None
        record["decided_at"] = None
        record["decided_by_user_id"] = None
        record["filed_at"] = None
        record["filed_by_user_id"] = None
        if target_designation is not None:
            record["target_designation"] = target_designation
        if designation_id is not None:
            record["injury_designation_id"] = designation_id
        contract = db.contracts.get(record["contract_id"])
        if contract is not None:
            if terms:
                for field in (
                    "years", "base_salary_cents", "base_guaranteed",
                    "signing_bonus_cents", "option_type", "option_deadline_at",
                    "option_salary_cents",
                ):
                    if terms.get(field) is not None:
                        contract[field] = terms[field]
                if terms.get("performance_ltbe_cents") is not None:
                    contract["_performance_ltbe_cents"] = terms["performance_ltbe_cents"]
                if terms.get("performance_nltbe_cents") is not None:
                    contract["_performance_nltbe_cents"] = terms["performance_nltbe_cents"]
            contract["status"] = "PENDING_APPROVAL"
            domain.apply_proration(contract)
            touch(contract)
    else:
        record["status"] = "VOIDED"
    domain.recompute_team(team, event=True)
    touch(team)
    touch(record)
    return single(views.transaction(record))
