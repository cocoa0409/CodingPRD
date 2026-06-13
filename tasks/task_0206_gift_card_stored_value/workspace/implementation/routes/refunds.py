"""RefundRequest open/read/list/approve/request-revision/resubmit/deny
(PRD §3.6)."""

from flask import Blueprint, request

from db import db
from core import (
    get_body, stamp_new, touch, paginate,
    check_str, check_int,
    settled_balance, post_ledger,
)
from errors import err
from middleware import get_identity, require_role
from response import success
from lookups import get_refund
import serialize
from domain import apply_balance_lifecycle, reverse_redemption

bp = Blueprint("refunds", __name__)


def _allocated(redemption_id):
    return sum(
        leg["leg_amount_cents"]
        for leg in db.redemption_legs.values()
        if leg["redemption_id"] == redemption_id
    )


@bp.post("/v1/refunds")
def open_refund():
    uid, role = get_identity()
    require_role(role, {"Customer", "StoreAssociate", "ProgramAdmin"})
    body = get_body()
    card_id = check_str(body, "card_id")
    requested = check_int(body, "requested_refund_cents")
    redemption_id = check_str(body, "redemption_id", required=False)

    # Body FK existence (priority 5).
    card = db.cards.get(card_id)
    if card is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "card_id does not exist.")
    if redemption_id is not None:
        red = db.redemptions.get(redemption_id)
        if red is None or red["program_id"] != card["program_id"]:
            raise err("ERR_REFERENCE_NOT_FOUND", "redemption_id does not exist in this program.")
    # Customer ownership: refund anchored to own card.
    if role == "Customer" and card["owner_customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "Customer may only refund own card.")
    # Domain shape (priority 6).
    if requested <= 0:
        raise err("ERR_INVALID_REDEMPTION", "requested_refund_cents must be > 0.")

    r = {
        "card_id": card_id,
        "redemption_id": redemption_id,
        "requested_refund_cents": requested,
        "status": "PENDING",
    }
    stamp_new(r)
    db.refunds[r["id"]] = r
    return success(serialize.refund(r), status=201)


@bp.get("/v1/refunds/<refund_id>")
def read_refund(refund_id):
    uid, role = get_identity()
    require_role(role, {"Customer", "StoreAssociate", "ProgramAdmin"})
    r = get_refund(refund_id)
    if role == "Customer":
        card = db.cards.get(r["card_id"])
        if card is None or card["owner_customer_id"] != uid:
            raise err("ERR_FORBIDDEN", "Not the owner of this refund.")
    return success(serialize.refund(r))


@bp.get("/v1/refunds")
def list_refunds():
    _uid, role = get_identity()
    require_role(role, {"Customer", "StoreAssociate", "ProgramAdmin"})
    items = list(db.refunds.values())
    for key in ("card_id", "redemption_id"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    page, pg = paginate(items)
    return success([serialize.refund(r) for r in page], pagination=pg)


@bp.post("/v1/refunds/<refund_id>/approve")
def approve_refund(refund_id):
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin"})
    r = get_refund(refund_id)
    card = db.cards[r["card_id"]]
    program = db.programs[card["program_id"]]

    # Refund must be PENDING (state, priority 8).
    if r["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Refund is not PENDING.")
    # Card lifecycle must be ACTIVE/EXHAUSTED.
    if card["lifecycle_status"] not in ("ACTIVE", "EXHAUSTED"):
        raise err("ERR_INVALID_STATE", "Card is not ACTIVE or EXHAUSTED.")
    # Balance cap (priority 13).
    if settled_balance(card["id"]) + r["requested_refund_cents"] > program["reload_max_balance_cents"]:
        raise err("ERR_BALANCE_CAP_EXCEEDED", "Refund would exceed balance cap.")
    # Refund vs referenced redemption.
    if r["redemption_id"] is not None:
        allocated = _allocated(r["redemption_id"])
        if r["requested_refund_cents"] > allocated:
            raise err("ERR_REFUND_EXCEEDS_REDEMPTION", "Refund exceeds redemption allocated amount.")

    # REFUND credit on the card; revive EXHAUSTED -> ACTIVE.
    post_ledger(card, "REFUND", r["requested_refund_cents"], source_ref_id=r["id"])
    apply_balance_lifecycle(card)

    # Full-amount redemption refund cascade -> drive Redemption SETTLED->VOIDED.
    if r["redemption_id"] is not None:
        red = db.redemptions[r["redemption_id"]]
        allocated = _allocated(r["redemption_id"])
        if red["status"] == "SETTLED" and r["requested_refund_cents"] == allocated:
            reverse_redemption(red, source_ref_id=r["id"])

    r["status"] = "APPLIED"
    touch(r)
    return success(serialize.refund(r))


@bp.post("/v1/refunds/<refund_id>/request-revision")
def request_revision(refund_id):
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin"})
    r = get_refund(refund_id)
    if r["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Refund is not PENDING.")
    r["status"] = "NEEDS_REVISION"
    touch(r)
    return success(serialize.refund(r))


@bp.post("/v1/refunds/<refund_id>/resubmit")
def resubmit_refund(refund_id):
    uid, role = get_identity()
    require_role(role, {"Customer"})
    r = get_refund(refund_id)
    # Customer ownership.
    card = db.cards.get(r["card_id"])
    if card is None or card["owner_customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "Not the owner of this refund.")
    body = get_body()
    requested = check_int(body, "requested_refund_cents")

    # State (priority 8): only NEEDS_REVISION may resubmit.
    if r["status"] != "NEEDS_REVISION":
        raise err("ERR_INVALID_STATE", "Refund is not NEEDS_REVISION.")
    # Domain shape (priority 6).
    if requested <= 0:
        raise err("ERR_INVALID_REDEMPTION", "requested_refund_cents must be > 0.")

    r["requested_refund_cents"] = requested
    r["status"] = "PENDING"
    touch(r)
    return success(serialize.refund(r))


@bp.post("/v1/refunds/<refund_id>/deny")
def deny_refund(refund_id):
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin"})
    r = get_refund(refund_id)
    if r["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Refund is not PENDING.")
    r["status"] = "DENIED"
    touch(r)
    return success(serialize.refund(r))
