"""Ticket endpoints + validation branching state machine (PRD 3.4, 3.8)."""
from flask import Blueprint, request

from clock import clock
from db import db
from errors import err
from middleware import get_auth, require_roles
from models import (_stamp_create, serialize, touch, get_or_404,
                    parse_pagination, paginate, sort_by_created)
from response import success
from util import add_days, mul_round
from validate import require_body, req_str, req_int

tickets_bp = Blueprint("tickets", __name__)


def _compute_claim_deadline(ticket, game):
    return add_days(ticket["draw_date"], game["claim_window_days"])


def _serialize_ticket(t):
    return serialize(t)


@tickets_bp.route("/tickets", methods=["POST"])
def create_ticket():
    _, role = get_auth()
    require_roles(role, {"TerminalOperator"})
    body = require_body(request.get_json(silent=True))

    game_id = req_str(body, "game_id")
    terminal_id = req_str(body, "terminal_id")
    serial = req_str(body, "serial")
    price_cents = req_int(body, "price_cents", minimum=1)
    draw_date_raw = body.get("draw_date")
    declared_tier = req_int(body, "declared_tier", minimum=0, maximum=9)
    gross_prize_cents = req_int(body, "gross_prize_cents", minimum=0)

    # draw_date required datetime
    from util import parse_iso8601
    if draw_date_raw is None:
        raise err("ERR_INVALID_REQUEST", "draw_date is required")
    draw_date = parse_iso8601(draw_date_raw, "draw_date")

    # Existence of FKs left-to-right: game then terminal.
    game = get_or_404(db.games, game_id, "game")
    terminal = get_or_404(db.terminals, terminal_id, "terminal")

    # Uniqueness on serial.
    for t in db.tickets.values():
        if t["serial"] == serial:
            raise err("ERR_DUPLICATE_RESOURCE", "ticket serial already exists")

    # Sale requires terminal ACTIVE (and thereby retailer licensed).
    if terminal["status"] != "ACTIVE":
        raise err("ERR_TERMINAL_NOT_ACTIVE", "selling terminal not ACTIVE")

    ticket = {
        "game_id": game_id,
        "terminal_id": terminal_id,
        "serial": serial,
        "price_cents": price_cents,
        "draw_date": draw_date,
        "declared_tier": declared_tier,
        "gross_prize_cents": gross_prize_cents,
        "validation_status": "UNVALIDATED",
        "second_chance_status": "INELIGIBLE",
        "claim_deadline": None,
    }
    ticket["claim_deadline"] = _compute_claim_deadline(ticket, game)
    _stamp_create(ticket)
    db.tickets[ticket["id"]] = ticket

    # Increment selling terminal's tickets_sold_count.
    terminal["tickets_sold_count"] += 1
    touch(terminal)

    return success(_serialize_ticket(ticket), 201)


@tickets_bp.route("/tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer", "ClaimsClerk", "TerminalOperator"})
    ticket = get_or_404(db.tickets, tid, "ticket")
    return success(_serialize_ticket(ticket), 200)


@tickets_bp.route("/tickets", methods=["GET"])
def list_tickets():
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer", "ClaimsClerk", "TerminalOperator"})
    limit, offset = parse_pagination(request.args)
    rows = list(db.tickets.values())
    for key in ("game_id", "terminal_id", "validation_status", "second_chance_status"):
        f = request.args.get(key)
        if f is not None:
            rows = [t for t in rows if t[key] == f]
    rows = sort_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([_serialize_ticket(t) for t in page], 200, pagination=meta)


@tickets_bp.route("/tickets/<tid>/validate", methods=["POST"])
def validate_ticket(tid):
    _, role = get_auth()
    require_roles(role, {"TerminalOperator"})
    ticket = get_or_404(db.tickets, tid, "ticket")

    # State gate: only UNVALIDATED tickets may be validated.
    if ticket["validation_status"] != "UNVALIDATED":
        raise err("ERR_INVALID_STATE", "ticket not UNVALIDATED")

    # Terminal must be ACTIVE in every branch.
    terminal = db.terminals.get(ticket["terminal_id"])
    if terminal is None or terminal["status"] != "ACTIVE":
        raise err("ERR_TERMINAL_NOT_ACTIVE", "selling terminal not ACTIVE")

    game = db.games[ticket["game_id"]]
    deadline = ticket["claim_deadline"]
    expired = clock.now > deadline
    tier = ticket["declared_tier"]
    gross = ticket["gross_prize_cents"]
    threshold = game["federal_withholding_threshold_cents"]

    if tier == 0:
        # Non-winner -> VALIDATED_NONWINNER + second-chance ELIGIBLE.
        ticket["validation_status"] = "VALIDATED_NONWINNER"
        ticket["second_chance_status"] = "ELIGIBLE"
        touch(ticket)
        return success(_serialize_ticket(ticket), 200)

    # tier 1..9 (winner branches) — deadline matters.
    if expired:
        # Expired UNVALIDATED ticket -> REJECTED (terminal).
        ticket["validation_status"] = "REJECTED"
        touch(ticket)
        return success(_serialize_ticket(ticket), 200)

    if gross >= threshold:
        # Over-threshold winner -> VALIDATED_WINNER.
        ticket["validation_status"] = "VALIDATED_WINNER"
        touch(ticket)
        return success(_serialize_ticket(ticket), 200)

    # Under-threshold winner -> PAID_AT_COUNTER, accrue cashing bonus.
    ticket["validation_status"] = "PAID_AT_COUNTER"
    retailer = db.retailers.get(terminal["retailer_id"])
    if retailer is not None:
        bonus = mul_round(gross, retailer["cashing_bonus_rate"])
        retailer["commission_balance_cents"] += bonus
        touch(retailer)
    touch(ticket)
    return success(_serialize_ticket(ticket), 200)


@tickets_bp.route("/tickets/<tid>/reverse-counter-pay", methods=["POST"])
def reverse_counter_pay(tid):
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    ticket = get_or_404(db.tickets, tid, "ticket")
    if ticket["validation_status"] != "PAID_AT_COUNTER":
        raise err("ERR_INVALID_STATE", "ticket not PAID_AT_COUNTER")

    ticket["validation_status"] = "COUNTER_REVERSED"
    terminal = db.terminals.get(ticket["terminal_id"])
    if terminal is not None:
        retailer = db.retailers.get(terminal["retailer_id"])
        if retailer is not None:
            bonus = mul_round(ticket["gross_prize_cents"], retailer["cashing_bonus_rate"])
            new_balance = retailer["commission_balance_cents"] - bonus
            retailer["commission_balance_cents"] = max(0, new_balance)
            touch(retailer)
    touch(ticket)
    return success(_serialize_ticket(ticket), 200)
