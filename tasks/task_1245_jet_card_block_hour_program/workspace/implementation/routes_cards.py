"""JetCard endpoints: purchase, lifecycle actions, reads, ledger, escrow,
refund creation, fractional upgrades, and card-scoped FK reverse reads."""

from decimal import Decimal

from flask import Blueprint, g, request

from httpkit import (
    ApiError, authenticate, ensure_empty_body, err_invalid_request,
    err_invalid_state, err_not_found, err_reference_not_found, get_body,
    paginate, require_member_ownership, require_roles, respond_object,
    sorted_items,
)
from serializers import (
    card_json, escrow_json, ledger_json, peak_window_json, refund_json,
    upgrade_json,
)
from services import (
    activate_card, card_escrow, card_ledger_entries, forward_hours_remaining,
    insert_ledger_entry, new_common, touch,
)
from store import db
from util import D, add_months, round_hours, round_money

bp = Blueprint("cards", __name__)


def get_card_or_404(card_id):
    c = db.cards.get(card_id)
    if c is None:
        raise err_not_found(f"JetCard {card_id} does not exist")
    return c


def _check_card_occ(card, data):
    """Priority-15 OCC check: expected_card_version vs current version."""
    if data.get("expected_card_version") != card["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_card_version does not match current card version")


# ---------------------------------------------------------------------------
# Purchase / lifecycle
# ---------------------------------------------------------------------------

@bp.post("/members/<memberId>/cards")
def purchase_card(memberId):
    data = get_body([
        {"name": "program_id", "type": "string", "required": True},
    ])
    authenticate()
    require_roles("Ops")
    member = db.members.get(memberId)
    if member is None:
        raise err_not_found(f"Member {memberId} does not exist")
    # Priority 4 (body FK existence) precedes priority 6 (member active).
    program = db.programs.get(data["program_id"])
    if program is None:
        raise err_reference_not_found(
            f"CardProgram {data['program_id']} does not exist")
    if member["member_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409,
                       "Member must be ACTIVE to purchase a card")
    card = new_common()
    card.update({
        "member_id": memberId,
        "program_id": data["program_id"],
        "card_status": "PENDING_PAYMENT",
        "purchased_at": None,
        "expires_at": None,
        "hours_total": program["hours_purchased"],
        "hours_remaining": Decimal("0"),
        "hours_consumed": Decimal("0"),
        "hours_expired": Decimal("0"),
        "escrow_balance_cents": 0,
        "peak_hours_used": Decimal("0"),
    })
    db.cards[card["id"]] = card
    return respond_object(card_json(card), 201)


@bp.post("/cards/<cardId>/activate")
def activate(cardId):
    ensure_empty_body()
    authenticate()
    require_roles("Ops")
    card = get_card_or_404(cardId)
    if card["card_status"] != "PENDING_PAYMENT":
        raise err_invalid_state("Card is not in PENDING_PAYMENT")
    program = db.programs.get(card["program_id"])
    if program is None:
        raise err_reference_not_found("Referenced program no longer exists")
    activate_card(card, program)
    return respond_object(card_json(card))


@bp.post("/cards/<cardId>/suspend")
def suspend_card(cardId):
    ensure_empty_body()
    authenticate()
    require_roles("Ops")
    card = get_card_or_404(cardId)
    if card["card_status"] != "ACTIVE":
        raise err_invalid_state("Card is not ACTIVE")
    card["card_status"] = "SUSPENDED"
    touch(card)
    return respond_object(card_json(card))


@bp.post("/cards/<cardId>/resume")
def resume_card(cardId):
    ensure_empty_body()
    authenticate()
    require_roles("Ops")
    card = get_card_or_404(cardId)
    if card["card_status"] != "SUSPENDED":
        raise err_invalid_state("Card is not SUSPENDED")
    card["card_status"] = "ACTIVE"
    touch(card)
    return respond_object(card_json(card))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@bp.get("/cards/<cardId>")
def get_card(cardId):
    authenticate()
    require_roles("Ops", "Member")
    card = get_card_or_404(cardId)
    require_member_ownership(card["member_id"])
    return respond_object(card_json(card))


@bp.get("/members/<memberId>/cards")
def list_member_cards(memberId):
    authenticate()
    require_roles("Ops", "Member")
    member = db.members.get(memberId)
    if member is None:
        raise err_not_found(f"Member {memberId} does not exist")
    require_member_ownership(memberId)
    items = sorted_items(
        c for c in db.cards.values() if c["member_id"] == memberId)
    flt = request.args.get("card_status")
    if flt is not None:
        items = [c for c in items if c["card_status"] == flt]
    return paginate([card_json(c) for c in items])


@bp.get("/cards/<cardId>/projection")
def card_projection(cardId):
    authenticate()
    require_roles("Ops", "Member")
    card = get_card_or_404(cardId)
    require_member_ownership(card["member_id"])
    fwd = forward_hours_remaining(card)
    return respond_object(card_json(card, hours_remaining_override=fwd))


@bp.get("/cards/<cardId>/ledger")
def list_card_ledger(cardId):
    authenticate()
    require_roles("Ops", "Member")
    card = get_card_or_404(cardId)
    require_member_ownership(card["member_id"])
    items = sorted_items(card_ledger_entries(cardId))
    flt = request.args.get("entry_kind")
    if flt is not None:
        items = [e for e in items if e["entry_kind"] == flt]
    return paginate([ledger_json(e) for e in items])


@bp.get("/cards/<cardId>/escrow")
def get_card_escrow(cardId):
    authenticate()
    require_roles("Ops", "Member")
    card = get_card_or_404(cardId)
    require_member_ownership(card["member_id"])
    escrow = card_escrow(cardId)
    items = [] if escrow is None else [escrow]
    return paginate([escrow_json(e) for e in items])


# ---------------------------------------------------------------------------
# Refunds (creation is an OCC-guarded write on the card)
# ---------------------------------------------------------------------------

@bp.post("/cards/<cardId>/refunds")
def create_refund(cardId):
    data = get_body([
        {"name": "expected_card_version", "type": "integer", "required": True},
    ])
    authenticate()
    require_roles("Member", "Ops")
    card = get_card_or_404(cardId)
    require_member_ownership(card["member_id"])
    _check_card_occ(card, data)
    refund = new_common()
    refund.update({
        "card_id": cardId,
        "refund_status": "DRAFT",
        "hours_at_request": None,
        "gross_refund_cents": None,
        "penalty_cents": None,
        "net_refund_cents": None,
        "requested_at": None,
        "denial_reason": None,
    })
    db.refunds[refund["id"]] = refund
    # Refund creation mutates the card: version increments (PRD 3.10).
    touch(card)
    return respond_object(refund_json(refund), 201)


@bp.get("/cards/<cardId>/refunds")
def list_card_refunds(cardId):
    authenticate()
    require_roles("Ops", "Member")
    card = get_card_or_404(cardId)
    require_member_ownership(card["member_id"])
    items = sorted_items(
        r for r in db.refunds.values() if r["card_id"] == cardId)
    flt = request.args.get("refund_status")
    if flt is not None:
        items = [r for r in items if r["refund_status"] == flt]
    return paginate([refund_json(r) for r in items])


# ---------------------------------------------------------------------------
# Fractional upgrades (second OCC-guarded write)
# ---------------------------------------------------------------------------

@bp.post("/cards/<cardId>/fractional_upgrades")
def create_fractional_upgrade(cardId):
    data = get_body([
        {"name": "expected_card_version", "type": "integer", "required": True},
    ])
    authenticate()
    require_roles("Member", "Ops")
    card = get_card_or_404(cardId)
    require_member_ownership(card["member_id"])
    # Priority 5: card must be ACTIVE.
    if card["card_status"] != "ACTIVE":
        raise ApiError("ERR_CARD_NOT_ACTIVE", 409,
                       "Operation requires JetCard.card_status == ACTIVE")
    program = db.programs.get(card["program_id"])
    # Priority 14: minimum 1/16-share threshold.
    implied_rate = D(program["purchase_price_cents"]) / D(program["hours_purchased"])
    conversion_value = round_money(card["hours_remaining"] * implied_rate)
    share_cost = D(program["fractional_upgrade_ratio"]) * D(
        program["purchase_price_cents"])
    if D(conversion_value) < (share_cost / D(16)):
        raise ApiError("ERR_INSUFFICIENT_HOURS_FOR_UPGRADE", 402,
                       "Card hours_remaining below 1/16-share threshold")
    # Priority 15: OCC.
    _check_card_occ(card, data)

    hours_to_debit = card["hours_remaining"]
    upgrade = new_common()
    upgrade.update({
        "card_id": cardId,
        "hours_converted": hours_to_debit,
        "share_fraction": "1/16",
        "upgrade_status": "PENDING",
        "applied_at": None,
    })
    db.upgrades[upgrade["id"]] = upgrade
    insert_ledger_entry(cardId, "UPGRADE_DEBIT", -hours_to_debit)
    card["hours_remaining"] = round_hours(card["hours_remaining"] - hours_to_debit)
    touch(card)
    return respond_object(upgrade_json(upgrade), 201)


@bp.get("/cards/<cardId>/fractional_upgrades")
def list_fractional_upgrades(cardId):
    authenticate()
    require_roles("Ops", "Member")
    card = get_card_or_404(cardId)
    require_member_ownership(card["member_id"])
    items = sorted_items(
        u for u in db.upgrades.values() if u["card_id"] == cardId)
    return paginate([upgrade_json(u) for u in items])


# ---------------------------------------------------------------------------
# Card-scoped FK reverse-reachability reads
# ---------------------------------------------------------------------------

@bp.get("/cards/<id>/hour_bank_ledger")
def list_card_hour_bank_ledger(id):
    authenticate()
    require_roles("Ops", "Member")
    card = get_card_or_404(id)
    require_member_ownership(card["member_id"])
    items = sorted_items(card_ledger_entries(id))
    return paginate([ledger_json(e) for e in items])


@bp.get("/cards/<id>/trip_requests")
def list_card_trip_requests(id):
    from serializers import trip_json
    authenticate()
    require_roles("Ops", "Member")
    card = get_card_or_404(id)
    require_member_ownership(card["member_id"])
    items = sorted_items(
        t for t in db.trips.values() if t["card_id"] == id)
    return paginate([trip_json(t) for t in items])


@bp.get("/cards/<id>/escrow_accounts")
def list_card_escrow_accounts(id):
    authenticate()
    require_roles("Ops", "Member")
    card = get_card_or_404(id)
    require_member_ownership(card["member_id"])
    escrow = card_escrow(id)
    items = [] if escrow is None else [escrow]
    return paginate([escrow_json(e) for e in items])


@bp.get("/cards/<id>/refunds_fk")
def list_card_refunds_fk(id):
    authenticate()
    require_roles("Ops", "Member")
    card = get_card_or_404(id)
    require_member_ownership(card["member_id"])
    items = sorted_items(
        r for r in db.refunds.values() if r["card_id"] == id)
    return paginate([refund_json(r) for r in items])


@bp.get("/cards/<id>/fractional_upgrades_fk")
def list_card_upgrades_fk(id):
    authenticate()
    require_roles("Ops", "Member")
    card = get_card_or_404(id)
    require_member_ownership(card["member_id"])
    items = sorted_items(
        u for u in db.upgrades.values() if u["card_id"] == id)
    return paginate([upgrade_json(u) for u in items])
