"""Payout endpoints (PRD §3.9 scheduling, release, failure, reversal)."""
from decimal import Decimal

from flask import Blueprint, request

from common import (
    parse_pagination, paginate, sort_by_created, get_json_body,
    require_fields, round_half_up, err,
)
from errors import (
    ERR_INVALID_STATE, ERR_SELLER_NOT_ACTIVE, ERR_STALE_SELLER_VERSION,
    ERR_SEGREGATION_OF_DUTIES, ERR_NO_VERIFIED_PAYOUT_METHOD, ERR_NOTHING_TO_PAY,
)
from db import db
from middleware import (
    get_identity, require_roles, ROLE_SELLER, ROLE_REVIEWER, ROLE_FINANCE,
)
from response import success
from routes.helpers import fetch, ensure_seller_owns
from services.entity import stamp_create, touch
from services.ledger import (
    post_ledger_entry, sum_available_ledger, reconcile_balances,
    HOLD_AVAILABLE,
)
from services.seller import refresh_seller_derived
from services.reserve import (
    reserve_pct_for_tier, open_or_extend_reserve, release_reserve_row,
)

bp = Blueprint("payouts", __name__)


def _swept_orders(seller_id):
    """Orders eligible for the sweep: settlement_status AVAILABLE and
    clawback_status NONE, ordered created_at ASC (PRD §3.9)."""
    orders = [
        o for o in db.orders.values()
        if o["seller_id"] == seller_id
        and o["settlement_status"] == "AVAILABLE"
        and o["clawback_status"] == "NONE"
    ]
    return sort_by_created(orders)


@bp.post("/payouts")
def schedule_payout():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE])
    body = get_json_body()
    require_fields(body, ["seller_id"])
    seller = fetch(db.sellers, body["seller_id"])
    refresh_seller_derived(seller)

    order_ids = [o["id"] for o in _swept_orders(seller["id"])]
    payout = {
        "seller_id": seller["id"],
        "payout_method_id": None,
        "payout_status": "SCHEDULED",
        "gross_available_cents": seller["available_balance_cents"],
        "reserve_withheld_cents": 0,
        "payout_amount_cents": 0,
        "order_ids": order_ids,
        "finance_user_id": None,
    }
    stamp_create(payout)
    db.payouts[payout["id"]] = payout
    return success(payout, status=201)


@bp.get("/payouts/<payout_id>")
def get_payout(payout_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_REVIEWER, ROLE_SELLER])
    payout = fetch(db.payouts, payout_id)
    ensure_seller_owns(role, user_id, payout["seller_id"])
    return success(payout)


@bp.get("/payouts")
def list_payouts():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_REVIEWER, ROLE_SELLER])
    limit, offset = parse_pagination()
    items = list(db.payouts.values())
    if role == ROLE_SELLER:
        items = [p for p in items if p["seller_id"] == user_id]
    for key in ("seller_id", "payout_method_id", "payout_status"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p[key] == val]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, pagination=meta)


def _default_method(seller_id):
    for m in db.payout_methods.values():
        if (m["seller_id"] == seller_id and m["verification_status"] == "VERIFIED"
                and m.get("is_default")):
            return m
    return None


@bp.post("/payouts/<payout_id>/release")
def release(payout_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE])
    payout = fetch(db.payouts, payout_id)
    seller = db.sellers[payout["seller_id"]]

    # Validation order for release (PRD §2.11): auth/role (done) -> SoD
    # (priority 3) -> existence (done by fetch) -> state (priority 6, SCHEDULED)
    # -> seller active (7) -> OCC stale-version (8) -> verified method ->
    # nothing-to-pay floor (14). Existence necessarily resolves first (we cannot
    # identify the seller without it); among entity-dependent checks SoD leads.

    # Segregation of duties (PRD §2.10, §2.11, priority 3): acting finance
    # X-User-ID must differ from the seller's kyc_reviewer_id.
    if seller.get("kyc_reviewer_id") is not None and user_id == seller["kyc_reviewer_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES,
                  "Releasing operator approved this seller's KYC.")

    # State guard (priority 6): payout must be SCHEDULED.
    if payout["payout_status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Only a SCHEDULED payout can be released.")

    # Seller-active standing (priority 7, before OCC) (PRD §2.11).
    if seller["account_status"] != "ACTIVE":
        raise err(ERR_SELLER_NOT_ACTIVE, "Seller must be ACTIVE to release a payout.")

    # OCC: expected_seller_version must match seller.version (priority 8).
    body = get_json_body()
    require_fields(body, ["expected_seller_version"])
    expected = body["expected_seller_version"]
    if expected != seller["version"]:
        raise err(ERR_STALE_SELLER_VERSION,
                  "expected_seller_version does not match the seller's version.")

    # VERIFIED default payout method required (PRD §3.9).
    method = _default_method(seller["id"])
    if method is None:
        raise err(ERR_NO_VERIFIED_PAYOUT_METHOD,
                  "Seller has no VERIFIED default payout method.")

    # Reserve waterfall over the available pool (priority 14 nothing-to-pay).
    gross_available = sum_available_ledger(seller["id"])
    if gross_available <= 0:
        raise err(ERR_NOTHING_TO_PAY, "Nothing available to pay out.")

    reserve_pct = reserve_pct_for_tier(seller)
    reserve_withheld = round_half_up(
        Decimal(gross_available) * Decimal(reserve_pct) / Decimal(100)
    )
    payout_amount = gross_available - reserve_withheld

    # --- Commit the cascade atomically ---
    payout["payout_method_id"] = method["id"]
    payout["gross_available_cents"] = gross_available
    payout["reserve_withheld_cents"] = reserve_withheld
    payout["payout_amount_cents"] = payout_amount

    # Post negative PAYOUT entry for the disbursed amount.
    post_ledger_entry(
        seller_id=seller["id"],
        source_type="PAYOUT",
        source_id=payout["id"],
        amount_cents=-payout_amount,
        hold_state=HOLD_AVAILABLE,
        memo="Payout disbursement",
    )
    # Withhold the reserve (opens a reserve row + RESERVE_HOLD audit entry).
    if reserve_withheld > 0:
        open_or_extend_reserve(seller, reserve_withheld, reserve_pct, payout["id"])

    # Flip every swept order AVAILABLE->PAID (cascade).
    for oid in payout["order_ids"]:
        o = db.orders.get(oid)
        if o is not None and o["settlement_status"] == "AVAILABLE":
            o["settlement_status"] = "PAID"
            touch(o)

    # Increment seller version; record operator; reconcile.
    seller["version"] = seller.get("version", 1) + 1
    seller["updated_at"] = db.now_iso()
    payout["finance_user_id"] = user_id
    payout["payout_status"] = "RELEASED"
    touch(payout)
    refresh_seller_derived(seller)
    return success(payout)


@bp.post("/payouts/<payout_id>/mark-failed")
def mark_failed(payout_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE])
    payout = fetch(db.payouts, payout_id)
    if payout["payout_status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Only a SCHEDULED payout can be marked failed.")
    payout["payout_status"] = "FAILED"
    touch(payout)
    return success(payout)


@bp.post("/payouts/<payout_id>/reverse")
def reverse(payout_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE])
    payout = fetch(db.payouts, payout_id)
    seller = db.sellers[payout["seller_id"]]
    if payout["payout_status"] != "RELEASED":
        raise err(ERR_INVALID_STATE, "Only a RELEASED payout can be reversed.")

    # Compensating cascade (PRD §3.9): net effect on available is zero.
    # Positive PAYOUT reversal restoring the disbursed amount.
    post_ledger_entry(
        seller_id=seller["id"],
        source_type="PAYOUT",
        source_id=payout["id"],
        amount_cents=payout["payout_amount_cents"],
        hold_state=HOLD_AVAILABLE,
        memo="Payout reversal",
    )
    # Flip swept orders PAID->AVAILABLE.
    for oid in payout["order_ids"]:
        o = db.orders.get(oid)
        if o is not None and o["settlement_status"] == "PAID":
            o["settlement_status"] = "AVAILABLE"
            touch(o)
    # Release the RESERVE_HOLD posted for this payout (Reserve OPEN->RELEASED).
    for r in list(db.reserves.values()):
        if (r["seller_id"] == seller["id"] and r["reserve_status"] == "OPEN"
                and r["held_amount_cents"] == payout["reserve_withheld_cents"]
                and payout["reserve_withheld_cents"] > 0):
            release_reserve_row(seller, r, source_id=payout["id"])
            break

    payout["payout_status"] = "REVERSED"
    touch(payout)
    refresh_seller_derived(seller)
    return success(payout)
