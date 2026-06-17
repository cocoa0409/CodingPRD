"""Shared entity helpers: creation stamping, mutation stamping, serialization,
and the cross-entity recompute functions (fee balance / standing / feedback score).
"""
import db
import constants as C


def stamp_new(entity, with_version=True):
    """Set common system fields on a freshly created entity (PRD §2.4)."""
    now = db.now_iso()
    entity["created_at"] = now
    if with_version:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version by one (PRD §2.4, §2.5)."""
    if "version" in entity:
        entity["version"] = entity["version"] + 1
    if "updated_at" in entity:
        entity["updated_at"] = db.now_iso()


# ---------------------------------------------------------------------------
# Cross-entity recomputes
# ---------------------------------------------------------------------------

def recompute_account_fee_balance(account_id):
    """PRD §2.8 / §3.7: fee_balance_cents = sum of INVOICED invoices' amount_cents
    for this seller; PAID and CREDITED contribute 0. Derive standing.

    This recompute does NOT itself bump the account version/timestamp; standing and
    fee_balance_cents are computed fields. (The PRD describes them as derived
    quantities, not direct edits.)
    """
    acct = db.accounts.get(account_id)
    if acct is None:
        return
    total = 0
    for inv in db.seller_fee_invoices.values():
        if inv["seller_account_id"] == account_id and inv["settlement_status"] == "INVOICED":
            total += inv["amount_cents"]
    acct["fee_balance_cents"] = total
    acct["standing"] = "SUSPENDED" if total > C.FEE_SUSPEND_THRESHOLD_CENTS else "GOOD"


def recompute_feedback_score(account_id):
    """PRD §3.1: net score = count(POSITIVE as ratee) - count(NEGATIVE as ratee).
    NEUTRAL contributes 0. Lifetime, recomputed in full.
    """
    acct = db.accounts.get(account_id)
    if acct is None:
        return
    pos = 0
    neg = 0
    for fb in db.feedback.values():
        if fb["ratee_account_id"] == account_id:
            if fb["rating"] == "POSITIVE":
                pos += 1
            elif fb["rating"] == "NEGATIVE":
                neg += 1
    acct["feedback_score"] = pos - neg


# ---------------------------------------------------------------------------
# Serialization — present public field sets per entity (order per scaffold §1.1)
# ---------------------------------------------------------------------------

def ser_account(a):
    return {
        "id": a["id"],
        "email": a["email"],
        "display_name": a["display_name"],
        "roles": list(a["roles"]),
        "fee_balance_cents": a["fee_balance_cents"],
        "feedback_score": a["feedback_score"],
        "standing": a["standing"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_listing(l):
    return {
        "id": l["id"],
        "seller_account_id": l["seller_account_id"],
        "title": l["title"],
        "format": l["format"],
        "start_price_cents": l["start_price_cents"],
        "buy_now_price_cents": l["buy_now_price_cents"],
        "reserve_price_cents": l["reserve_price_cents"],
        "accepts_offers": l["accepts_offers"],
        "scheduled_end_at": l["scheduled_end_at"],
        "effective_end_at": l["effective_end_at"],
        "highest_bid_id": l["highest_bid_id"],
        "current_price_cents": l["current_price_cents"],
        "bid_count": l["bid_count"],
        "status": l["status"],
        "winner_account_id": l["winner_account_id"],
        "sold_price_cents": l["sold_price_cents"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_bid(b):
    return {
        "id": b["id"],
        "listing_id": b["listing_id"],
        "bidder_account_id": b["bidder_account_id"],
        "max_proxy_cents": b["max_proxy_cents"],
        "current_price_cents": b["current_price_cents"],
        "is_winning": b["is_winning"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_watch(w):
    return {
        "id": w["id"],
        "listing_id": w["listing_id"],
        "watcher_account_id": w["watcher_account_id"],
        "active": w["active"],
        "created_at": w["created_at"],
    }


def ser_offer(o):
    return {
        "id": o["id"],
        "listing_id": o["listing_id"],
        "buyer_account_id": o["buyer_account_id"],
        "amount_cents": o["amount_cents"],
        "round_no": o["round_no"],
        "last_actor": o["last_actor"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_order(o):
    return {
        "id": o["id"],
        "listing_id": o["listing_id"],
        "buyer_account_id": o["buyer_account_id"],
        "seller_account_id": o["seller_account_id"],
        "source": o["source"],
        "item_price_cents": o["item_price_cents"],
        "shipping_cents": o["shipping_cents"],
        "total_cents": o["total_cents"],
        "payment_status": o["payment_status"],
        "fulfillment_status": o["fulfillment_status"],
        "paid_amount_cents": o["paid_amount_cents"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_invoice(i):
    return {
        "id": i["id"],
        "order_id": i["order_id"],
        "seller_account_id": i["seller_account_id"],
        "gross_item_cents": i["gross_item_cents"],
        "fvf_rate_basis_points": i["fvf_rate_basis_points"],
        "amount_cents": i["amount_cents"],
        "settlement_status": i["settlement_status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def ser_payment(p):
    return {
        "id": p["id"],
        "order_id": p["order_id"],
        "kind": p["kind"],
        "amount_cents": p["amount_cents"],
        "created_at": p["created_at"],
    }


def ser_feedback(f):
    return {
        "id": f["id"],
        "order_id": f["order_id"],
        "rater_account_id": f["rater_account_id"],
        "ratee_account_id": f["ratee_account_id"],
        "role": f["role"],
        "rating": f["rating"],
        "comment": f["comment"],
        "created_at": f["created_at"],
    }


def ser_dispute(d):
    return {
        "id": d["id"],
        "order_id": d["order_id"],
        "opener_account_id": d["opener_account_id"],
        "reason": d["reason"],
        "requested_amount_cents": d["requested_amount_cents"],
        "resolved_amount_cents": d["resolved_amount_cents"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }
