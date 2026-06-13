"""Redemption draft/read/list/amend/settle/void and RedemptionLeg reads
(PRD §3.5). Split-tender waterfall allocation over the client-pinned
card_id_order."""

from flask import Blueprint, request

from db import db
from core import (
    get_body, stamp_new, touch, paginate,
    check_str, check_int,
    available_balance, post_ledger,
)
from errors import err
from middleware import get_identity, require_role
from response import success
from lookups import get_redemption, get_redemption_leg
import serialize
from domain import apply_balance_lifecycle

bp = Blueprint("redemptions", __name__)


def _owner_ok(redemption, uid, role):
    if role == "Customer" and redemption["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "Not the owner of this redemption.")


# ---------------------------------------------------------------- draft
@bp.post("/v1/redemptions")
def draft_redemption():
    uid, role = get_identity()
    require_role(role, {"StoreAssociate", "Customer"})
    body = get_body()
    program_id = check_str(body, "program_id")
    requested = check_int(body, "requested_amount_cents")
    card_id_order = body.get("card_id_order")
    customer_id = check_str(body, "customer_id", required=False)

    if not isinstance(card_id_order, list) or any(not isinstance(x, str) for x in card_id_order):
        raise err("ERR_VALIDATION", "card_id_order must be an array of strings.")

    # Body FK existence (priority 5): same-program entities.
    if program_id not in db.programs:
        raise err("ERR_REFERENCE_NOT_FOUND", "program_id does not exist.")
    if customer_id is not None and customer_id not in db.customers:
        raise err("ERR_REFERENCE_NOT_FOUND", "customer_id does not exist.")
    for cid in card_id_order:
        card = db.cards.get(cid)
        if card is None or card["program_id"] != program_id:
            raise err("ERR_REFERENCE_NOT_FOUND", "A card in card_id_order does not exist in this program.")

    # Customer ownership: a Customer drafts only their own redemption.
    if role == "Customer" and customer_id is not None and customer_id != uid:
        raise err("ERR_FORBIDDEN", "Customer may only draft own redemption.")

    # Domain shape (priority 6).
    if requested <= 0 or len(card_id_order) == 0:
        raise err("ERR_INVALID_REDEMPTION", "requested_amount_cents must be > 0 and card_id_order non-empty.")

    r = {
        "program_id": program_id,
        "customer_id": customer_id,
        "requested_amount_cents": requested,
        "card_id_order": list(card_id_order),
        "status": "DRAFT",
    }
    stamp_new(r)
    db.redemptions[r["id"]] = r
    return success(serialize.redemption(r), status=201)


@bp.get("/v1/redemptions/<redemption_id>")
def read_redemption(redemption_id):
    uid, role = get_identity()
    require_role(role, {"StoreAssociate", "ProgramAdmin", "FraudAnalyst", "Customer"})
    r = get_redemption(redemption_id)
    _owner_ok(r, uid, role)
    return success(serialize.redemption(r))


@bp.get("/v1/redemptions")
def list_redemptions():
    _uid, role = get_identity()
    require_role(role, {"StoreAssociate", "ProgramAdmin", "FraudAnalyst"})
    items = list(db.redemptions.values())
    for key in ("program_id", "customer_id"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    page, pg = paginate(items)
    return success([serialize.redemption(r) for r in page], pagination=pg)


# ---------------------------------------------------------------- amend (PATCH)
@bp.patch("/v1/redemptions/<redemption_id>")
def amend_redemption(redemption_id):
    uid, role = get_identity()
    require_role(role, {"StoreAssociate", "Customer"})
    r = get_redemption(redemption_id)
    _owner_ok(r, uid, role)
    body = get_body()

    new_amount = r["requested_amount_cents"]
    new_order = list(r["card_id_order"])

    if "requested_amount_cents" in body and body["requested_amount_cents"] is not None:
        v = body["requested_amount_cents"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise err("ERR_VALIDATION", "requested_amount_cents must be an integer.")
        new_amount = v
    if "card_id_order" in body and body["card_id_order"] is not None:
        order = body["card_id_order"]
        if not isinstance(order, list) or any(not isinstance(x, str) for x in order):
            raise err("ERR_VALIDATION", "card_id_order must be an array of strings.")
        for cid in order:
            card = db.cards.get(cid)
            if card is None or card["program_id"] != r["program_id"]:
                raise err("ERR_REFERENCE_NOT_FOUND", "A card in card_id_order does not exist in this program.")
        new_order = list(order)

    # State (priority 8): only DRAFT can be amended.
    if r["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT redemption may be amended.")
    # Domain shape (priority 6).
    if new_amount <= 0 or len(new_order) == 0:
        raise err("ERR_INVALID_REDEMPTION", "requested_amount_cents must be > 0 and card_id_order non-empty.")

    r["requested_amount_cents"] = new_amount
    r["card_id_order"] = new_order
    touch(r)
    return success(serialize.redemption(r))


# ---------------------------------------------------------------- settle
@bp.post("/v1/redemptions/<redemption_id>/settle")
def settle_redemption(redemption_id):
    uid, role = get_identity()
    require_role(role, {"StoreAssociate", "Customer", "FraudAnalyst"})
    r = get_redemption(redemption_id)
    _owner_ok(r, uid, role)
    body = get_body()
    expected_version = check_int(body, "expected_redemption_version")

    # OCC (priority 7).
    if expected_version != r["version"]:
        raise err("ERR_STALE_VERSION", "Redemption version is stale.")
    # Domain shape (priority 6).
    if r["requested_amount_cents"] <= 0 or len(r["card_id_order"]) == 0:
        raise err("ERR_INVALID_REDEMPTION", "Invalid redemption shape.")

    cards = [db.cards[cid] for cid in r["card_id_order"]]

    # State (priority 8): every card must be ACTIVE.
    if any(c["lifecycle_status"] != "ACTIVE" for c in cards):
        raise err("ERR_INVALID_STATE", "Every card in the order must be ACTIVE.")
    # Risk gate frozen (priority 9).
    if any(c["risk_status"] == "FROZEN_RISK" for c in cards):
        raise err("ERR_CARD_RISK_FROZEN", "A card in the order is frozen.")
    # Risk review gate (priority 10): a FLAGGED card requires a FraudAnalyst actor.
    if any(c["risk_status"] == "FLAGGED" for c in cards) and role != "FraudAnalyst":
        raise err("ERR_CARD_RISK_REVIEW", "A flagged card may only be settled by a FraudAnalyst.")
    # Sufficient authorized balance (priority 14).
    total_available = sum(max(available_balance(c["id"]), 0) for c in cards)
    if total_available < r["requested_amount_cents"]:
        raise err("ERR_INSUFFICIENT_BALANCE", "Insufficient available balance across the cards.")

    # Waterfall allocation over card_id_order (PRD §3.5).
    remaining = r["requested_amount_cents"]
    planned = []  # (card, take)
    for c in cards:
        if remaining == 0:
            break
        avail = max(available_balance(c["id"]), 0)
        take = min(remaining, avail)
        if take > 0:
            planned.append((c, take))
            remaining -= take
    if remaining > 0:
        # Defensive: should be caught above; persist nothing.
        raise err("ERR_INSUFFICIENT_BALANCE", "Insufficient available balance across the cards.")

    # Commit: one RedemptionLeg + one REDEEM debit per drawn card.
    for c, take in planned:
        entry = post_ledger(c, "REDEEM", -take, source_ref_id=r["id"])
        leg = {
            "redemption_id": r["id"],
            "card_id": c["id"],
            "leg_amount_cents": take,
            "ledger_entry_id": entry["id"],
        }
        stamp_new(leg, with_version=False)
        db.redemption_legs[leg["id"]] = leg
        apply_balance_lifecycle(c)

    r["status"] = "SETTLED"
    touch(r)
    return success(serialize.redemption(r))


# ---------------------------------------------------------------- void
@bp.post("/v1/redemptions/<redemption_id>/void")
def void_redemption(redemption_id):
    _uid, role = get_identity()
    require_role(role, {"StoreAssociate"})
    r = get_redemption(redemption_id)
    # State (priority 8): only DRAFT can be voided.
    if r["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT redemption may be voided.")
    r["status"] = "VOIDED"
    touch(r)
    return success(serialize.redemption(r))


# ---------------------------------------------------------------- RedemptionLeg
@bp.get("/v1/redemption-legs/<leg_id>")
def read_leg(leg_id):
    _uid, role = get_identity()
    require_role(role, {"StoreAssociate", "ProgramAdmin", "FraudAnalyst", "Customer"})
    leg = get_redemption_leg(leg_id)
    return success(serialize.redemption_leg(leg))


@bp.get("/v1/redemption-legs")
def list_legs():
    _uid, role = get_identity()
    require_role(role, {"StoreAssociate", "ProgramAdmin", "FraudAnalyst", "Customer"})
    items = list(db.redemption_legs.values())
    for key in ("redemption_id", "card_id", "ledger_entry_id"):
        val = request.args.get(key)
        if val is not None:
            items = [leg for leg in items if leg.get(key) == val]
    page, pg = paginate(items)
    return success([serialize.redemption_leg(leg) for leg in page], pagination=pg)
