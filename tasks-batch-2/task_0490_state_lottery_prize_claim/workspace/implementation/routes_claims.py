"""PrizeClaim endpoints + branching adjudication state machine (PRD 3.5, 3.7)."""
from flask import Blueprint, request

from clock import clock
from db import db
from errors import err
from middleware import get_auth, require_roles
from models import (_stamp_create, serialize, touch, get_or_404,
                    parse_pagination, paginate, sort_by_created)
from response import success
from validate import require_body, req_str, req_enum
from calculations import prize_payout_calc
from routes_players import is_excluded_now

claims_bp = Blueprint("claims", __name__)

PAYOUT_OPTIONS = {"CASH", "ANNUITY"}


def _serialize_claim(c):
    return serialize(c)


@claims_bp.route("/prize-claims", methods=["POST"])
def create_claim():
    _, role = get_auth()
    require_roles(role, {"ClaimsClerk"})
    body = require_body(request.get_json(silent=True))

    ticket_id = req_str(body, "ticket_id")
    player_id = req_str(body, "player_id")
    payout_option = req_enum(body, "payout_option", PAYOUT_OPTIONS)

    # Existence left-to-right: ticket then player.
    ticket = get_or_404(db.tickets, ticket_id, "ticket")
    player = get_or_404(db.players, player_id, "player")
    game = db.games[ticket["game_id"]]

    # Business rules in priority order:
    # 9: ANNUITY only on JACKPOT games.
    if payout_option == "ANNUITY" and game["game_type"] != "JACKPOT":
        raise err("ERR_ANNUITY_NOT_ALLOWED", "annuity only on jackpot games")
    # 10: over-threshold claim requires non-empty government_id_number.
    if not player.get("government_id_number") or not str(player["government_id_number"]).strip():
        raise err("ERR_ID_VERIFICATION_REQUIRED", "claimant lacks government_id_number")
    # 11: claim window not strictly passed.
    if clock.now > ticket["claim_deadline"]:
        raise err("ERR_CLAIM_WINDOW_EXPIRED", "claim window expired")
    # 19: ticket must be VALIDATED_WINNER.
    if ticket["validation_status"] != "VALIDATED_WINNER":
        raise err("ERR_TICKET_NOT_CLAIMABLE", "ticket not VALIDATED_WINNER")

    claim = {
        "ticket_id": ticket_id,
        "player_id": player_id,
        "adjudicated_by_user_id": None,
        "disbursed_by_user_id": None,
        "payout_option": payout_option,
        "gross_payout_cents": 0,
        "federal_withholding_cents": 0,
        "state_withholding_cents": 0,
        "net_payout_cents": 0,
        "annual_installment_cents": 0,
        "status": "SUBMITTED",
    }
    _stamp_create(claim)
    db.prize_claims[claim["id"]] = claim

    # Cascade: ticket VALIDATED_WINNER -> CLAIM_PENDING.
    ticket["validation_status"] = "CLAIM_PENDING"
    touch(ticket)

    return success(_serialize_claim(claim), 201)


@claims_bp.route("/prize-claims/<cid>", methods=["GET"])
def get_claim(cid):
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer", "ClaimsClerk"})
    claim = get_or_404(db.prize_claims, cid, "prize claim")
    return success(_serialize_claim(claim), 200)


@claims_bp.route("/prize-claims", methods=["GET"])
def list_claims():
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer", "ClaimsClerk"})
    limit, offset = parse_pagination(request.args)
    rows = list(db.prize_claims.values())
    for key in ("ticket_id", "player_id", "status"):
        f = request.args.get(key)
        if f is not None:
            rows = [c for c in rows if c[key] == f]
    rows = sort_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([_serialize_claim(c) for c in page], 200, pagination=meta)


@claims_bp.route("/prize-claims/<cid>/begin-adjudication", methods=["POST"])
def begin_adjudication(cid):
    user_id, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    claim = get_or_404(db.prize_claims, cid, "prize claim")
    if claim["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "claim not SUBMITTED")
    # Self-exclusion guard (priority 6).
    player = db.players.get(claim["player_id"])
    if player is not None and is_excluded_now(player):
        raise err("ERR_PLAYER_SELF_EXCLUDED", "claimant under active self-exclusion")
    claim["status"] = "ADJUDICATING"
    claim["adjudicated_by_user_id"] = user_id
    touch(claim)
    return success(_serialize_claim(claim), 200)


@claims_bp.route("/prize-claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    user_id, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    claim = get_or_404(db.prize_claims, cid, "prize claim")
    if claim["status"] != "ADJUDICATING":
        raise err("ERR_INVALID_STATE", "claim not ADJUDICATING")
    # Only the adjudicating officer may approve.
    if user_id != claim["adjudicated_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "approver must be the adjudicating officer")

    ticket = db.tickets[claim["ticket_id"]]
    game = db.games[ticket["game_id"]]
    payout_option = claim["payout_option"]

    # Annuity only on JACKPOT games (priority 9).
    if payout_option == "ANNUITY" and game["game_type"] != "JACKPOT":
        raise err("ERR_ANNUITY_NOT_ALLOWED", "annuity only on jackpot games")

    result = prize_payout_calc(ticket, game, payout_option)
    claim.update(result)
    claim["status"] = "APPROVED_CASH" if payout_option == "CASH" else "APPROVED_ANNUITY"
    touch(claim)
    return success(_serialize_claim(claim), 200)


@claims_bp.route("/prize-claims/<cid>/reject", methods=["POST"])
def reject_claim(cid):
    user_id, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    claim = get_or_404(db.prize_claims, cid, "prize claim")
    if claim["status"] != "ADJUDICATING":
        raise err("ERR_INVALID_STATE", "claim not ADJUDICATING")
    if user_id != claim["adjudicated_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "rejector must be the adjudicating officer")
    claim["status"] = "REJECTED"
    touch(claim)
    # Cascade: ticket CLAIM_PENDING -> VALIDATED_WINNER.
    ticket = db.tickets.get(claim["ticket_id"])
    if ticket is not None and ticket["validation_status"] == "CLAIM_PENDING":
        ticket["validation_status"] = "VALIDATED_WINNER"
        touch(ticket)
    return success(_serialize_claim(claim), 200)


@claims_bp.route("/prize-claims/<cid>/disburse", methods=["POST"])
def disburse_claim(cid):
    user_id, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    claim = get_or_404(db.prize_claims, cid, "prize claim")
    if claim["status"] not in ("APPROVED_CASH", "APPROVED_ANNUITY"):
        raise err("ERR_INVALID_STATE", "claim not approved")
    # Segregation of duties: disburser must differ from adjudicator.
    if user_id == claim["adjudicated_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "disburser must differ from adjudicator")
    claim["status"] = "PAID"
    claim["disbursed_by_user_id"] = user_id
    touch(claim)
    # Ticket remains CLAIM_PENDING permanently (no further cascade).
    return success(_serialize_claim(claim), 200)


@claims_bp.route("/prize-claims/<cid>/void", methods=["POST"])
def void_claim(cid):
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    claim = get_or_404(db.prize_claims, cid, "prize claim")
    if claim["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "claim not SUBMITTED")
    claim["status"] = "VOIDED"
    touch(claim)
    # Cascade: ticket CLAIM_PENDING -> VALIDATED_WINNER.
    ticket = db.tickets.get(claim["ticket_id"])
    if ticket is not None and ticket["validation_status"] == "CLAIM_PENDING":
        ticket["validation_status"] = "VALIDATED_WINNER"
        touch(ticket)
    return success(_serialize_claim(claim), 200)
