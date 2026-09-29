"""Waiver wires, claims and processing (PRD 3.6)."""
from flask import Blueprint

import calc
import domain
import shape
import views
from auth import LEAGUE_OFFICER, TEAM_CAP_ANALYST, endpoint, require_team_scope
from envelope import filter_records, paginate, single
from errors import fail
from store import base_record, db, hours, touch, values

bp = Blueprint("waivers", __name__)


@bp.route("/waiver-requests", methods=["POST"])
@endpoint(TEAM_CAP_ANALYST)
def create_waiver_request(actor):
    body = shape.body()
    raw_team = shape.raw(body, "from_team_id")
    if isinstance(raw_team, str) and raw_team.strip() != actor.user_id:
        fail("ERR_ACTOR_SCOPE_VIOLATION", "wire belongs to another club")
    player_id = shape.req_ref(body, "player_id")
    from_team_id = shape.req_ref(body, "from_team_id")
    require_team_scope(actor, from_team_id)
    transaction_id = shape.req_ref(body, "transaction_id")
    player = domain.get_player(player_id)
    team = domain.get_team(from_team_id)
    filing = domain.get_transaction(transaction_id)
    # Rule 15
    domain.require_not_frozen(team)
    # Rule 20: the cited filing must be an approved release for this pair.
    if (
        filing["transaction_type"] != "RELEASE"
        or filing["status"] != "APPROVED"
        or filing["player_id"] != player_id
        or filing["team_id"] != from_team_id
    ):
        fail("ERR_RELEASE_FILING_MISMATCH", "filing is not an approved release for this player")
    if player["roster_designation"] != "WAIVED_PENDING":
        fail("ERR_INVALID_WAIVER_STATE", "player is not pending waivers")
    # Rule 32
    for existing in values(db.waiver_requests, lambda w: w["player_id"] == player_id):
        if existing["status"] == "PENDING":
            fail("ERR_WAIVER_ALREADY_PENDING", "player already sits on a pending wire")
    contract = domain.player_active_contract(player)
    revocability = domain.waiver_revocability_class(db.clock)
    record = base_record()
    record.update({
        "player_id": player_id,
        "from_team_id": from_team_id,
        "transaction_id": transaction_id,
        "contract_id": contract["id"] if contract else None,
        "origin_designation": filing["prior_designation"],
        "revocability": revocability,
        "status": "PENDING",
        "placed_at": db.clock,
        "clearance_deadline_at": calc.snap(
            db.clock + hours(calc.WAIVER_CLEARANCE_HOURS[revocability])
        ),
        "processed_at": None,
        "awarded_to_team_id": None,
        "claim_count": 0,
        "releasing_team_dead_money_cents": 0,
    })
    db.waiver_requests[record["id"]] = record
    touch(team)
    return single(views.waiver_request(record), 201)


@bp.route("/waiver-requests/<waiver_request_id>", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST)
def read_waiver_request(actor, waiver_request_id):
    record = domain.get_waiver_request(waiver_request_id)
    return single(views.waiver_request(record))


@bp.route("/waiver-requests", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST)
def list_waiver_requests(actor):
    records = filter_records(values(db.waiver_requests), {
        "player_id": "player_id",
        "from_team_id": "from_team_id",
        "awarded_to_team_id": "awarded_to_team_id",
        "transaction_id": "transaction_id",
        "contract_id": "contract_id",
        "status": "status",
    })
    return paginate(records, views.waiver_request)


@bp.route("/waiver-requests/<waiver_request_id>/withdraw", methods=["POST"])
@endpoint(TEAM_CAP_ANALYST)
def withdraw_waiver_request(actor, waiver_request_id):
    record = domain.get_waiver_request(waiver_request_id)
    require_team_scope(actor, record["from_team_id"])
    if record["status"] != "PENDING":
        fail("ERR_INVALID_WAIVER_STATE", "wire has already resolved")
    if record["revocability"] != "REVOCABLE":
        fail("ERR_INVALID_WAIVER_STATE", "wire is irrevocable")
    if db.clock >= record["clearance_deadline_at"]:
        fail("ERR_INVALID_WAIVER_STATE", "clearance deadline has been reached")
    team = domain.get_team(record["from_team_id"])
    player = domain.get_player(record["player_id"])
    origin = record["origin_designation"]
    # Rule 36: the club must still have room for the returning player.
    if origin in domain.DESIGNATION_COUNT:
        domain.require_room_for(team, origin)
    record["status"] = "WITHDRAWN"
    record["processed_at"] = db.clock
    touch(record)
    domain.set_designation(player, origin, team_id=record["from_team_id"])
    filing = db.transactions.get(record["transaction_id"])
    if filing is not None and filing["status"] == "APPROVED":
        filing["status"] = "VOIDED"
        filing["effective_at"] = None
        touch(filing)
    for claim in values(db.waiver_claims, lambda c: c["waiver_request_id"] == record["id"]):
        if claim["status"] == "SUBMITTED":
            claim["status"] = "INVALIDATED"
            touch(claim)
    domain.recompute_team(team, event=True)
    return single(views.waiver_request(record))


@bp.route("/waiver-requests/<waiver_request_id>/claims", methods=["POST"])
@endpoint(TEAM_CAP_ANALYST)
def create_claim(actor, waiver_request_id):
    wire = domain.get_waiver_request(waiver_request_id)
    body = shape.body()
    raw_team = shape.raw(body, "claiming_team_id")
    if isinstance(raw_team, str) and raw_team.strip() != actor.user_id:
        fail("ERR_ACTOR_SCOPE_VIOLATION", "claim belongs to another club")
    claiming_team_id = shape.req_ref(body, "claiming_team_id")
    require_team_scope(actor, claiming_team_id)
    if claiming_team_id == wire["from_team_id"]:
        fail("ERR_ACTOR_SCOPE_VIOLATION", "the releasing club may not claim its own player")
    expected_team_version = shape.req_int(body, "expected_team_version")
    team = domain.get_team(claiming_team_id)
    # Rule 10
    domain.require_occ(expected_team_version, team, "ERR_STALE_TEAM_VERSION")
    # Rule 13
    if wire["status"] != "PENDING":
        fail("ERR_INVALID_WAIVER_STATE", "wire is no longer open to claims")
    if db.clock >= wire["clearance_deadline_at"]:
        fail("ERR_INVALID_WAIVER_STATE", "the claim window has closed")
    # Rule 15
    domain.require_not_frozen(team)
    # Rule 32
    for existing in values(db.waiver_claims, lambda c: c["waiver_request_id"] == wire["id"]):
        if existing["claiming_team_id"] == claiming_team_id and existing["status"] == "SUBMITTED":
            fail("ERR_CLAIM_ALREADY_SUBMITTED", "club has already claimed this player")
    contract = db.contracts.get(wire["contract_id"])
    domain.recompute_team(team)
    record = base_record()
    record.update({
        "waiver_request_id": wire["id"],
        "claiming_team_id": claiming_team_id,
        "status": "SUBMITTED",
        "priority_rank_snapshot": team["waiver_priority_rank"],
        "cap_space_snapshot_cents": team["cap_space_cents"],
        "required_cap_charge_cents": contract["base_salary_cents"] if contract else 0,
        "submitted_at": db.clock,
    })
    db.waiver_claims[record["id"]] = record
    wire["claim_count"] = len(
        values(db.waiver_claims, lambda c: c["waiver_request_id"] == wire["id"])
    )
    touch(wire)
    touch(team)
    return single(views.waiver_claim(record), 201)


@bp.route("/waiver-claims/<claim_id>", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST)
def read_claim(actor, claim_id):
    record = domain.get_waiver_claim(claim_id)
    return single(views.waiver_claim(record))


@bp.route("/waiver-claims", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST)
def list_claims(actor):
    records = filter_records(values(db.waiver_claims), {
        "waiver_request_id": "waiver_request_id",
        "claiming_team_id": "claiming_team_id",
        "status": "status",
    })
    return paginate(records, views.waiver_claim)


def _invalidate(claim):
    claim["status"] = "INVALIDATED"
    touch(claim)


@bp.route("/waiver-requests/<waiver_request_id>/process", methods=["POST"])
@endpoint(LEAGUE_OFFICER)
def process_waiver_request(actor, waiver_request_id):
    wire = domain.get_waiver_request(waiver_request_id)
    # Rule 13
    if wire["status"] != "PENDING":
        fail("ERR_INVALID_WAIVER_STATE", "wire has already resolved")
    # Rule 22
    domain.require_window()
    # Rule 24: reaching the deadline is enough.
    if db.clock < wire["clearance_deadline_at"]:
        fail("ERR_CLEARANCE_NOT_REACHED", "clearance deadline has not been reached")
    releasing = domain.get_team(wire["from_team_id"])
    player = domain.get_player(wire["player_id"])
    contract = db.contracts.get(wire["contract_id"])
    candidates = [
        claim for claim in values(
            db.waiver_claims, lambda c: c["waiver_request_id"] == wire["id"]
        )
        if claim["status"] == "SUBMITTED"
    ]
    survivors = []
    for claim in candidates:
        club = db.teams.get(claim["claiming_team_id"])
        if club is None:
            _invalidate(claim)
            continue
        domain.recompute_team(club)
        # Stage 1: live cap space.
        if claim["required_cap_charge_cents"] > club["cap_space_cents"]:
            _invalidate(claim)
            continue
        # Stage 2: posture.
        if club["compliance_status"] in domain.FROZEN_STATUSES:
            _invalidate(claim)
            continue
        # Stage 3: active roster room.
        if club["active_roster_count"] >= club["active_roster_limit"]:
            _invalidate(claim)
            continue
        survivors.append(claim)
    survivors.sort(key=lambda c: (c["priority_rank_snapshot"], c["created_at"], c["_seq"]))

    wire["processed_at"] = db.clock
    if survivors:
        winner = survivors[0]
        winning_club = domain.get_team(winner["claiming_team_id"])
        # Rule 36
        domain.require_projected_quotas(
            winning_club, [(None, "ACTIVE")]
        )
        winner["status"] = "AWARDED"
        touch(winner)
        for claim in survivors[1:]:
            claim["status"] = "LOST"
            touch(claim)
        wire["status"] = "CLAIMED"
        wire["awarded_to_team_id"] = winning_club["id"]
        domain.set_designation(player, "ACTIVE", team_id=winning_club["id"])
        if contract is not None:
            contract["team_id"] = winning_club["id"]
            touch(contract)
            # Only the unamortised signing bonus stays behind; base salary travels.
            current, _following = calc.dead_money_split(
                contract["signing_bonus_cents"],
                contract["annual_proration_cents"],
                contract["start_season_year"],
                db.clock,
            )
            wire["releasing_team_dead_money_cents"] = current
        touch(wire)
        domain.recompute_team(winning_club, event=True)
        domain.recompute_team(releasing, event=True)
    else:
        wire["status"] = "CLEARED"
        for claim in candidates:
            if claim["status"] == "SUBMITTED":
                _invalidate(claim)
        domain.set_designation(player, "UNROSTERED", team_id=None)
        if contract is not None and contract["status"] == "ACTIVE":
            domain.terminate_contract(contract, "RELEASE_CLEARED")
            wire["releasing_team_dead_money_cents"] = contract["dead_money_current_season_cents"]
        touch(wire)
        domain.recompute_team(releasing, event=True)
    return single(views.waiver_request(wire))
