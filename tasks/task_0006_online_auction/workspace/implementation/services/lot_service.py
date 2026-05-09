from datetime import timedelta

import db
from services import calc
from services.calc import (
    PAYMENT_DEADLINE_SECONDS,
    RUNNER_UP_ACCEPT_WINDOW_SECONDS,
)


def bump(entity: dict) -> None:
    entity["updated_at"] = db.now()
    if "version" in entity:
        entity["version"] = entity.get("version", 1) + 1


def held_deposit_total(bidder_id: str) -> int:
    return sum(
        d["amount_cents"] for d in db.deposits.values()
        if d["bidder_id"] == bidder_id and d["status"] == "HELD"
    )


def refresh_bidder_held(bidder_id: str) -> None:
    b = db.bidders.get(bidder_id)
    if not b:
        return
    b["held_deposit_cents"] = held_deposit_total(bidder_id)


def recompute_lot_state(lot: dict) -> None:
    """Aggregation per PRD §3.2 lot-current-state."""
    eligible = [b for b in db.bids.values() if b["lot_id"] == lot["id"] and b["status"] in ("ACTIVE", "WINNING")]
    if not eligible:
        lot["current_price_cents"] = lot["starting_bid_cents"] - 1
        lot["current_winner_bid_id"] = None
        lot["current_winner_bidder_id"] = None
        lot["runner_up_bid_id"] = None
    else:
        eligible.sort(key=lambda b: (-b["amount_cents"], b["placed_at"]))
        top = eligible[0]
        lot["current_price_cents"] = top["amount_cents"]
        lot["current_winner_bid_id"] = top["id"]
        lot["current_winner_bidder_id"] = top["bidder_id"]
        rest = [b for b in eligible if b["bidder_id"] != top["bidder_id"]]
        lot["runner_up_bid_id"] = rest[0]["id"] if rest else None
    counted = [b for b in db.bids.values() if b["lot_id"] == lot["id"] and b["status"] in ("ACTIVE", "WINNING", "OUTBID")]
    lot["bid_count"] = len(counted)
    lot["has_met_reserve"] = lot["current_price_cents"] >= lot["reserve_price_cents"]


def get_or_create_deposit(bidder_id: str, lot_id: str, amount_cents: int):
    """Return (deposit, created_bool). Reuses existing HELD deposit on this (bidder, lot)."""
    for d in db.deposits.values():
        if d["bidder_id"] == bidder_id and d["lot_id"] == lot_id and d["status"] == "HELD":
            return d, False
    d_id = db.gen_id()
    deposit = {
        "id": d_id,
        "bidder_id": bidder_id,
        "lot_id": lot_id,
        "amount_cents": amount_cents,
        "status": "HELD",
        "refund_amount_cents": 0,
        "forfeit_amount_cents": 0,
        "terminal_reason": None,
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
    }
    db.deposits[d_id] = deposit
    return deposit, True


def maybe_soft_close(lot: dict, bid: dict) -> None:
    """Per PRD §3.2: if seconds_remaining ≤ 60 and > 0, extend by 120s."""
    end = lot["effective_end_at"]
    now = db.now()
    seconds_remaining = (end - now).total_seconds()
    if 0 < seconds_remaining <= calc.SOFT_CLOSE_TRIGGER_SECONDS:
        lot["effective_end_at"] = end + timedelta(seconds=calc.SOFT_CLOSE_EXTENSION_SECONDS)
        lot["extension_count"] = lot.get("extension_count", 0) + 1
        bid["triggered_extension"] = True
        bump(lot)


def emit_proxy_bids(lot: dict) -> None:
    """After any bid placement (manual or proxy), let other ACTIVE proxies counter-bid.
    Iterates upward through ladder; proxy whose next required emission > max → EXHAUSTED.
    Proxy owner who is currently winning does not emit."""
    safety = 200
    while safety > 0:
        safety -= 1
        # Find an ACTIVE proxy whose owner is not currently winning, and whose owner's bidder is ACTIVE.
        proxies = [
            p for p in db.proxies.values()
            if p["lot_id"] == lot["id"] and p["status"] == "ACTIVE"
        ]
        if not proxies:
            return
        # Order by created_at ascending so older proxies act first.
        proxies.sort(key=lambda p: p["created_at"])
        emitted = False
        for p in proxies:
            owner = db.bidders.get(p["bidder_id"])
            if owner is None or owner["status"] != "ACTIVE":
                continue
            if lot["current_winner_bidder_id"] == p["bidder_id"]:
                # owner is currently winning, no need to emit
                continue
            min_required = calc.min_required_bid_cents(lot)
            if min_required > p["max_amount_cents"]:
                # Exhaust this proxy
                p["status"] = "EXHAUSTED"
                bump(p)
                continue
            # Emit a bid at min_required
            _emit_bid_from_proxy(lot, p, min_required)
            emitted = True
            break
        if not emitted:
            return


def _emit_bid_from_proxy(lot: dict, proxy: dict, amount_cents: int) -> None:
    bidder_id = proxy["bidder_id"]
    bid_id = db.gen_id()
    placed_at = db.now()
    bid = {
        "id": bid_id,
        "lot_id": lot["id"],
        "bidder_id": bidder_id,
        "amount_cents": amount_cents,
        "source": "PROXY",
        "proxy_id": proxy["id"],
        "status": "ACTIVE",
        "deposit_id": None,
        "placed_at": placed_at,
        "triggered_extension": False,
        "created_at": placed_at,
    }
    # Make sure deposit exists for this bidder on this lot (first qualifying placement).
    deposit, _created = get_or_create_deposit(bidder_id, lot["id"], calc.deposit_required_cents(lot["reserve_price_cents"]))
    bid["deposit_id"] = deposit["id"]
    refresh_bidder_held(bidder_id)
    db.bids[bid_id] = bid
    proxy["last_executed_amount_cents"] = amount_cents
    proxy["bids_emitted_count"] = proxy.get("bids_emitted_count", 0) + 1
    bump(proxy)
    recompute_lot_state(lot)
    maybe_soft_close(lot, bid)


def settle_lot_close(lot: dict) -> None:
    """Apply close cascade: SOLD or UNSOLD."""
    if lot["has_met_reserve"]:
        # Transition to SOLD
        lot["status"] = "SOLD"
        lot["hammer_price_cents"] = lot["current_price_cents"]
        lot["winning_bidder_id"] = lot["current_winner_bidder_id"]
        lot["hammer_at"] = db.now()
        lot["payment_deadline_at"] = db.now() + timedelta(seconds=PAYMENT_DEADLINE_SECONDS)
        winner_bid_id = lot["current_winner_bid_id"]
        # Bid statuses
        for b in db.bids.values():
            if b["lot_id"] == lot["id"]:
                if b["id"] == winner_bid_id:
                    b["status"] = "WINNING"
                elif b["status"] == "ACTIVE":
                    b["status"] = "OUTBID"
        # Cancel all ACTIVE proxies
        for p in db.proxies.values():
            if p["lot_id"] == lot["id"] and p["status"] == "ACTIVE":
                p["status"] = "CANCELLED"
                bump(p)
        # Create invoice
        bidder = db.bidders.get(lot["winning_bidder_id"])
        verified = bool(bidder and bidder.get("identity_verified"))
        bp = calc.buyer_premium_cents(lot["hammer_price_cents"], lot["category"], verified)
        sc = calc.seller_commission_cents(lot["hammer_price_cents"])
        inv_id = db.gen_id()
        invoice = {
            "id": inv_id,
            "lot_id": lot["id"],
            "buyer_id": lot["winning_bidder_id"],
            "seller_id": lot["seller_id"],
            "hammer_price_cents": lot["hammer_price_cents"],
            "buyer_premium_cents": bp,
            "seller_commission_cents": sc,
            "buyer_total_cents": lot["hammer_price_cents"] + bp,
            "seller_payout_cents": lot["hammer_price_cents"] - sc,
            "platform_take_cents": bp + sc,
            "status": "ISSUED",
            "paid_at": None,
            "refund_amount_cents": 0,
            "commission_reversal_amount_cents": 0,
            "created_at": db.now(),
            "updated_at": db.now(),
            "version": 1,
        }
        db.invoices[inv_id] = invoice
        # Release loser deposits
        for d in db.deposits.values():
            if d["lot_id"] == lot["id"] and d["status"] == "HELD" and d["bidder_id"] != lot["winning_bidder_id"]:
                _release_deposit(d, "LOSING_BIDDER")
        # Refresh held for all losers
        bidder_ids = {d["bidder_id"] for d in db.deposits.values() if d["lot_id"] == lot["id"]}
        for bid_id_ in bidder_ids:
            refresh_bidder_held(bid_id_)
    else:
        lot["status"] = "UNSOLD"
        # All ACTIVE bids → OUTBID
        for b in db.bids.values():
            if b["lot_id"] == lot["id"] and b["status"] == "ACTIVE":
                b["status"] = "OUTBID"
        # Cancel ACTIVE proxies
        for p in db.proxies.values():
            if p["lot_id"] == lot["id"] and p["status"] == "ACTIVE":
                p["status"] = "CANCELLED"
                bump(p)
        # Release every HELD deposit
        for d in db.deposits.values():
            if d["lot_id"] == lot["id"] and d["status"] == "HELD":
                _release_deposit(d, "LOSING_BIDDER")
        bidder_ids = {d["bidder_id"] for d in db.deposits.values() if d["lot_id"] == lot["id"]}
        for bid_id_ in bidder_ids:
            refresh_bidder_held(bid_id_)
    # Update seller total_lots_listed
    seller = db.sellers.get(lot["seller_id"])
    if seller:
        recompute_seller_counters(seller)
    bump(lot)


def _release_deposit(d: dict, reason: str) -> None:
    """Release a HELD deposit. wallet_balance_cents represents total funds; held_deposit_cents
    is the currently-locked portion (computed). Release just removes the lock (no wallet move)."""
    d["status"] = "RELEASED"
    d["terminal_reason"] = reason
    d["refund_amount_cents"] = d["amount_cents"]
    d["forfeit_amount_cents"] = 0
    bump(d)


def _forfeit_deposit(d: dict, reason: str) -> None:
    """Forfeit takes the deposit out of the wallet."""
    d["status"] = "FORFEITED"
    d["terminal_reason"] = reason
    d["refund_amount_cents"] = 0
    d["forfeit_amount_cents"] = d["amount_cents"]
    bump(d)
    bidder = db.bidders.get(d["bidder_id"])
    if bidder is not None:
        bidder["wallet_balance_cents"] -= d["amount_cents"]
        bump(bidder)


def _partial_refund_deposit(d: dict, reason: str) -> None:
    """Partial refund: forfeit portion leaves the wallet, refund portion stays."""
    refund = calc.default_partial_refund_cents(d["amount_cents"])
    forfeit = d["amount_cents"] - refund
    d["status"] = "PARTIAL_REFUND"
    d["terminal_reason"] = reason
    d["refund_amount_cents"] = refund
    d["forfeit_amount_cents"] = forfeit
    bump(d)
    bidder = db.bidders.get(d["bidder_id"])
    if bidder is not None and forfeit > 0:
        bidder["wallet_balance_cents"] -= forfeit
        bump(bidder)


def transition_to_defaulted(lot: dict) -> None:
    """SOLD → DEFAULTED. Increase defaulter acute and recompute risk."""
    from services import risk as risk_svc
    lot["status"] = "DEFAULTED"
    bump(lot)
    defaulter_id = lot.get("winning_bidder_id")
    defaulter = db.bidders.get(defaulter_id) if defaulter_id else None
    if defaulter is not None:
        defaulter["default_count_since_reinstate"] = defaulter.get("default_count_since_reinstate", 0) + 1
        risk_svc.recompute_risk(defaulter)
        risk_svc.maybe_threshold_transition(defaulter)
        bump(defaulter)
    # Determine fork: REOFFERED or UNSOLD
    if lot.get("runner_up_bid_id"):
        lot["status"] = "REOFFERED"
        lot["runner_up_acceptance_deadline_at"] = db.now() + timedelta(seconds=RUNNER_UP_ACCEPT_WINDOW_SECONDS)
        bump(lot)
    else:
        # No runner-up → UNSOLD
        lot["status"] = "UNSOLD"
        # Forfeit defaulter's deposit
        for d in db.deposits.values():
            if d["lot_id"] == lot["id"] and d["bidder_id"] == defaulter_id and d["status"] == "HELD":
                _forfeit_deposit(d, "WINNER_DEFAULT_NO_REOFFER")
        # Reverse invoice
        for inv in db.invoices.values():
            if inv["lot_id"] == lot["id"] and inv["status"] in ("PENDING", "ISSUED", "PAID"):
                _reverse_invoice(inv, refund_amount_cents=0)
        if defaulter_id:
            refresh_bidder_held(defaulter_id)
        bump(lot)


def _reverse_invoice(invoice: dict, refund_amount_cents: int) -> None:
    was_paid = invoice["status"] == "PAID"
    invoice["status"] = "REVERSED"
    invoice["refund_amount_cents"] = refund_amount_cents
    bump(invoice)
    if was_paid:
        # decrement seller proceeds
        seller = db.sellers.get(invoice["seller_id"])
        if seller:
            recompute_seller_counters(seller)


def transition_reoffered_to_sold(lot: dict, runner_up_bidder_id: str) -> None:
    """REOFFERED → SOLD. Defaulter deposit → PARTIAL_REFUND, new invoice issued."""
    runner_up_bid_id = lot["runner_up_bid_id"]
    runner_up_bid = db.bids.get(runner_up_bid_id)
    if runner_up_bid is None:
        return
    defaulter_id = lot.get("winning_bidder_id")
    # defaulter deposit → PARTIAL_REFUND
    for d in db.deposits.values():
        if d["lot_id"] == lot["id"] and d["bidder_id"] == defaulter_id and d["status"] == "HELD":
            _partial_refund_deposit(d, "WINNER_DEFAULT_REOFFER_FILLED")
    # Reverse old invoice
    for inv in db.invoices.values():
        if inv["lot_id"] == lot["id"] and inv["status"] in ("PENDING", "ISSUED", "PAID"):
            _reverse_invoice(inv, refund_amount_cents=0)
    # Update lot
    lot["status"] = "SOLD"
    lot["winning_bidder_id"] = runner_up_bidder_id
    lot["hammer_price_cents"] = runner_up_bid["amount_cents"]
    lot["current_winner_bid_id"] = runner_up_bid_id
    lot["current_winner_bidder_id"] = runner_up_bidder_id
    lot["current_price_cents"] = runner_up_bid["amount_cents"]
    lot["payment_deadline_at"] = db.now() + timedelta(seconds=PAYMENT_DEADLINE_SECONDS)
    runner_up_bid["status"] = "WINNING"
    # Create new invoice
    bidder = db.bidders.get(runner_up_bidder_id)
    verified = bool(bidder and bidder.get("identity_verified"))
    bp = calc.buyer_premium_cents(lot["hammer_price_cents"], lot["category"], verified)
    sc = calc.seller_commission_cents(lot["hammer_price_cents"])
    inv_id = db.gen_id()
    invoice = {
        "id": inv_id,
        "lot_id": lot["id"],
        "buyer_id": runner_up_bidder_id,
        "seller_id": lot["seller_id"],
        "hammer_price_cents": lot["hammer_price_cents"],
        "buyer_premium_cents": bp,
        "seller_commission_cents": sc,
        "buyer_total_cents": lot["hammer_price_cents"] + bp,
        "seller_payout_cents": lot["hammer_price_cents"] - sc,
        "platform_take_cents": bp + sc,
        "status": "ISSUED",
        "paid_at": None,
        "refund_amount_cents": 0,
        "commission_reversal_amount_cents": 0,
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
    }
    db.invoices[inv_id] = invoice
    if defaulter_id:
        refresh_bidder_held(defaulter_id)
    refresh_bidder_held(runner_up_bidder_id)
    bump(lot)


def transition_reoffered_to_unsold(lot: dict) -> None:
    """REOFFERED → UNSOLD. Defaulter forfeit, runner-up release."""
    defaulter_id = lot.get("winning_bidder_id")
    runner_up_bid_id = lot.get("runner_up_bid_id")
    runner_up_bidder_id = None
    rb = db.bids.get(runner_up_bid_id) if runner_up_bid_id else None
    if rb:
        runner_up_bidder_id = rb["bidder_id"]
    # Defaulter forfeit
    for d in db.deposits.values():
        if d["lot_id"] == lot["id"] and d["bidder_id"] == defaulter_id and d["status"] == "HELD":
            _forfeit_deposit(d, "WINNER_DEFAULT_NO_REOFFER")
    # Runner-up release (if still HELD)
    if runner_up_bidder_id:
        for d in db.deposits.values():
            if d["lot_id"] == lot["id"] and d["bidder_id"] == runner_up_bidder_id and d["status"] == "HELD":
                _release_deposit(d, "LOSING_BIDDER")
    # All other HELD deposits on this lot → release as losing
    for d in db.deposits.values():
        if d["lot_id"] == lot["id"] and d["status"] == "HELD":
            _release_deposit(d, "LOSING_BIDDER")
    # Reverse invoice
    for inv in db.invoices.values():
        if inv["lot_id"] == lot["id"] and inv["status"] in ("PENDING", "ISSUED", "PAID"):
            _reverse_invoice(inv, refund_amount_cents=0)
    lot["status"] = "UNSOLD"
    if defaulter_id:
        refresh_bidder_held(defaulter_id)
    if runner_up_bidder_id:
        refresh_bidder_held(runner_up_bidder_id)
    bump(lot)


def transition_disputed_refund(lot: dict, dispute: dict) -> None:
    """DISPUTED → REFUNDED. Refund cascade per §2.8."""
    invoice = _find_active_invoice(lot["id"])
    if invoice is None:
        return
    refund = dispute.get("resolution_refund_amount_cents", 0)
    rev = calc.commission_reversal_amount_cents(refund, invoice["buyer_total_cents"], invoice["seller_commission_cents"])
    invoice["commission_reversal_amount_cents"] = rev
    _reverse_invoice(invoice, refund_amount_cents=refund)
    # Buyer deposit release
    buyer_id = invoice["buyer_id"]
    for d in db.deposits.values():
        if d["lot_id"] == lot["id"] and d["bidder_id"] == buyer_id and d["status"] == "HELD":
            _release_deposit(d, "DISPUTE_REFUND")
    refresh_bidder_held(buyer_id)
    lot["status"] = "REFUNDED"
    bump(lot)


def transition_disputed_relist(lot: dict, dispute: dict) -> None:
    """DISPUTED → RELISTED. Full refund + new DRAFT lot."""
    invoice = _find_active_invoice(lot["id"])
    if invoice is None:
        return
    invoice["commission_reversal_amount_cents"] = invoice["seller_commission_cents"]
    _reverse_invoice(invoice, refund_amount_cents=invoice["buyer_total_cents"])
    # Buyer deposit release
    buyer_id = invoice["buyer_id"]
    for d in db.deposits.values():
        if d["lot_id"] == lot["id"] and d["bidder_id"] == buyer_id and d["status"] == "HELD":
            _release_deposit(d, "DISPUTE_REFUND")
    refresh_bidder_held(buyer_id)
    # Create relisted lot
    new_id = db.gen_id()
    new_lot = {
        "id": new_id,
        "seller_id": lot["seller_id"],
        "title": lot["title"],
        "category": lot["category"],
        "condition": lot["condition"],
        "physical_item_serial": lot["physical_item_serial"],
        "reserve_price_cents": lot["reserve_price_cents"],
        "starting_bid_cents": lot["starting_bid_cents"],
        "scheduled_start_at": None,
        "scheduled_end_at": None,
        "effective_end_at": None,
        "extension_count": 0,
        "status": "DRAFT",
        "current_price_cents": lot["starting_bid_cents"] - 1,
        "current_winner_bid_id": None,
        "current_winner_bidder_id": None,
        "bid_count": 0,
        "has_met_reserve": False,
        "hammer_price_cents": None,
        "winning_bidder_id": None,
        "runner_up_bid_id": None,
        "payment_deadline_at": None,
        "hammer_at": None,
        "delivered_at": None,
        "relisted_from_lot_id": lot["id"],
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "runner_up_acceptance_deadline_at": None,
    }
    db.lots[new_id] = new_lot
    lot["status"] = "RELISTED"
    bump(lot)


def transition_disputed_denied(lot: dict, dispute: dict) -> None:
    """DISPUTED → SOLD."""
    lot["status"] = "SOLD"
    bump(lot)
    # filer dispute_loss_count
    from services import risk as risk_svc
    filer_id = dispute.get("filer_user_id")
    if dispute.get("filed_by") == "BIDDER" and filer_id:
        risk_svc.update_dispute_loss_count(filer_id)
        b = db.bidders.get(filer_id)
        if b:
            risk_svc.recompute_risk(b)
            risk_svc.maybe_threshold_transition(b)
            bump(b)


def _find_active_invoice(lot_id: str):
    invs = [i for i in db.invoices.values() if i["lot_id"] == lot_id and i["status"] != "REVERSED"]
    if not invs:
        return None
    invs.sort(key=lambda i: i["created_at"], reverse=True)
    return invs[0]


def bidder_suspend_cascade(bidder: dict) -> None:
    """All bids→WITHDRAWN_BY_RISK, recompute affected lots, cancel proxies, release HELD deposits on LIVE/SCHEDULED lots."""
    from services import risk as risk_svc
    bid_ids = [b["id"] for b in db.bids.values() if b["bidder_id"] == bidder["id"] and b["status"] in ("ACTIVE", "WINNING")]
    affected_lot_ids = set()
    for bid_id in bid_ids:
        b = db.bids[bid_id]
        b["status"] = "WITHDRAWN_BY_RISK"
        affected_lot_ids.add(b["lot_id"])
    # cancel ACTIVE proxies
    for p in db.proxies.values():
        if p["bidder_id"] == bidder["id"] and p["status"] == "ACTIVE":
            p["status"] = "CANCELLED"
            bump(p)
    # release HELD deposits where lot is LIVE/SCHEDULED
    for d in db.deposits.values():
        if d["bidder_id"] == bidder["id"] and d["status"] == "HELD":
            lot = db.lots.get(d["lot_id"])
            if lot and lot["status"] in ("LIVE", "SCHEDULED"):
                _release_deposit(d, "BIDDER_RISK_WITHDRAWN")
    # recompute affected lots
    for lid in affected_lot_ids:
        lot = db.lots.get(lid)
        if lot:
            recompute_lot_state(lot)
            bump(lot)
    # update withdrawal count and chronic component
    risk_svc.update_withdrawal_count(bidder["id"])
    refresh_bidder_held(bidder["id"])


def recompute_seller_counters(seller: dict) -> None:
    seller_id = seller["id"]
    total_lots = sum(1 for l in db.lots.values() if l["seller_id"] == seller_id and l["status"] != "DRAFT")
    seller["total_lots_listed"] = total_lots
    gross = 0
    net = 0
    for inv in db.invoices.values():
        if inv["seller_id"] != seller_id:
            continue
        if inv["status"] == "PAID":
            gross += inv["seller_payout_cents"]
            net += inv["seller_payout_cents"]
        elif inv["status"] == "REVERSED" and inv.get("paid_at") is not None:
            # PRD §3.5 refund cascade: "net_proceeds_cents is reduced by the freshly
            # computed reversal amount". Gross is the cumulative seller_payout from
            # historical payments (it does not retract on reversal); net is gross
            # minus accumulated commission_reversal.
            gross += inv["seller_payout_cents"]
            net += inv["seller_payout_cents"] - inv.get("commission_reversal_amount_cents", 0)
    seller["gross_proceeds_cents"] = gross
    seller["net_proceeds_cents"] = net


def evaluate_clock_transitions() -> None:
    """Run all time-gated transitions in the order specified by §2.9."""
    now = db.now()
    # 1. SCHEDULED → LIVE
    for lot in list(db.lots.values()):
        if lot["status"] == "SCHEDULED" and lot.get("scheduled_start_at") and now >= lot["scheduled_start_at"]:
            lot["status"] = "LIVE"
            bump(lot)
    # 2. LIVE → SOLD/UNSOLD
    for lot in list(db.lots.values()):
        if lot["status"] == "LIVE" and lot.get("effective_end_at") and now >= lot["effective_end_at"]:
            settle_lot_close(lot)
    # 3. SOLD → DEFAULTED on payment_deadline expiry
    for lot in list(db.lots.values()):
        if lot["status"] == "SOLD" and lot.get("payment_deadline_at") and now > lot["payment_deadline_at"]:
            inv = _find_active_invoice(lot["id"])
            if inv is None or inv["status"] != "PAID":
                transition_to_defaulted(lot)
    # 4. REOFFERED → UNSOLD on runner-up window expiry
    for lot in list(db.lots.values()):
        if lot["status"] == "REOFFERED" and lot.get("runner_up_acceptance_deadline_at") and now > lot["runner_up_acceptance_deadline_at"]:
            transition_reoffered_to_unsold(lot)


def serialize_seller(s):
    return {
        "id": s["id"],
        "display_name": s["display_name"],
        "status": s["status"],
        "total_lots_listed": s["total_lots_listed"],
        "gross_proceeds_cents": s["gross_proceeds_cents"],
        "net_proceeds_cents": s["net_proceeds_cents"],
        "created_at": db.fmt_dt(s["created_at"]),
        "updated_at": db.fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def serialize_bidder(b):
    return {
        "id": b["id"],
        "display_name": b["display_name"],
        "affiliated_seller_id": b.get("affiliated_seller_id"),
        "identity_verified": b["identity_verified"],
        "wallet_balance_cents": b["wallet_balance_cents"],
        "held_deposit_cents": b["held_deposit_cents"],
        "status": b["status"],
        "risk_score": b["risk_score"],
        "chronic_score": b["chronic_score"],
        "acute_score": b["acute_score"],
        "shill_pattern_detected": b["shill_pattern_detected"],
        "account_takeover_alert": b["account_takeover_alert"],
        "withdrawal_count": b["withdrawal_count"],
        "dispute_loss_count": b["dispute_loss_count"],
        "created_at": db.fmt_dt(b["created_at"]),
        "updated_at": db.fmt_dt(b["updated_at"]),
        "version": b["version"],
    }


def serialize_lot(l):
    return {
        "id": l["id"],
        "seller_id": l["seller_id"],
        "title": l["title"],
        "category": l["category"],
        "condition": l["condition"],
        "physical_item_serial": l["physical_item_serial"],
        "reserve_price_cents": l["reserve_price_cents"],
        "starting_bid_cents": l["starting_bid_cents"],
        "scheduled_start_at": db.fmt_dt(l["scheduled_start_at"]),
        "scheduled_end_at": db.fmt_dt(l["scheduled_end_at"]),
        "effective_end_at": db.fmt_dt(l["effective_end_at"]),
        "extension_count": l["extension_count"],
        "status": l["status"],
        "current_price_cents": l["current_price_cents"],
        "current_winner_bid_id": l["current_winner_bid_id"],
        "current_winner_bidder_id": l["current_winner_bidder_id"],
        "bid_count": l["bid_count"],
        "has_met_reserve": l["has_met_reserve"],
        "hammer_price_cents": l["hammer_price_cents"],
        "winning_bidder_id": l["winning_bidder_id"],
        "runner_up_bid_id": l["runner_up_bid_id"],
        "payment_deadline_at": db.fmt_dt(l["payment_deadline_at"]),
        "hammer_at": db.fmt_dt(l["hammer_at"]),
        "delivered_at": db.fmt_dt(l["delivered_at"]),
        "relisted_from_lot_id": l["relisted_from_lot_id"],
        "runner_up_acceptance_deadline_at": db.fmt_dt(l.get("runner_up_acceptance_deadline_at")),
        "created_at": db.fmt_dt(l["created_at"]),
        "updated_at": db.fmt_dt(l["updated_at"]),
        "version": l["version"],
    }


def serialize_bid(b):
    return {
        "id": b["id"],
        "lot_id": b["lot_id"],
        "bidder_id": b["bidder_id"],
        "amount_cents": b["amount_cents"],
        "source": b["source"],
        "proxy_id": b.get("proxy_id"),
        "status": b["status"],
        "deposit_id": b["deposit_id"],
        "placed_at": db.fmt_dt(b["placed_at"]),
        "triggered_extension": b["triggered_extension"],
        "created_at": db.fmt_dt(b["created_at"]),
    }


def serialize_proxy(p, mask_max=False):
    out = {
        "id": p["id"],
        "lot_id": p["lot_id"],
        "bidder_id": p["bidder_id"],
        "max_amount_cents": None if mask_max else p["max_amount_cents"],
        "status": p["status"],
        "last_executed_amount_cents": p.get("last_executed_amount_cents"),
        "bids_emitted_count": p.get("bids_emitted_count", 0),
        "created_at": db.fmt_dt(p["created_at"]),
        "updated_at": db.fmt_dt(p["updated_at"]),
        "version": p["version"],
    }
    return out


def serialize_deposit(d):
    return {
        "id": d["id"],
        "bidder_id": d["bidder_id"],
        "lot_id": d["lot_id"],
        "amount_cents": d["amount_cents"],
        "status": d["status"],
        "refund_amount_cents": d["refund_amount_cents"],
        "forfeit_amount_cents": d["forfeit_amount_cents"],
        "terminal_reason": d["terminal_reason"],
        "created_at": db.fmt_dt(d["created_at"]),
        "updated_at": db.fmt_dt(d["updated_at"]),
        "version": d["version"],
    }


def serialize_invoice(i):
    return {
        "id": i["id"],
        "lot_id": i["lot_id"],
        "buyer_id": i["buyer_id"],
        "seller_id": i["seller_id"],
        "hammer_price_cents": i["hammer_price_cents"],
        "buyer_premium_cents": i["buyer_premium_cents"],
        "seller_commission_cents": i["seller_commission_cents"],
        "buyer_total_cents": i["buyer_total_cents"],
        "seller_payout_cents": i["seller_payout_cents"],
        "platform_take_cents": i["platform_take_cents"],
        "status": i["status"],
        "paid_at": db.fmt_dt(i["paid_at"]),
        "refund_amount_cents": i["refund_amount_cents"],
        "commission_reversal_amount_cents": i["commission_reversal_amount_cents"],
        "created_at": db.fmt_dt(i["created_at"]),
        "updated_at": db.fmt_dt(i["updated_at"]),
        "version": i["version"],
    }


def serialize_dispute(d):
    return {
        "id": d["id"],
        "lot_id": d["lot_id"],
        "invoice_id": d["invoice_id"],
        "filed_by": d["filed_by"],
        "filer_user_id": d["filer_user_id"],
        "reason": d["reason"],
        "evidence": d["evidence"],
        "claimed_refund_amount_cents": d["claimed_refund_amount_cents"],
        "status": d["status"],
        "resolution_outcome": d.get("resolution_outcome"),
        "resolution_refund_amount_cents": d.get("resolution_refund_amount_cents", 0),
        "arbitrator_user_id": d.get("arbitrator_user_id"),
        "filed_at": db.fmt_dt(d["filed_at"]),
        "review_started_at": db.fmt_dt(d.get("review_started_at")),
        "resolved_at": db.fmt_dt(d.get("resolved_at")),
        "created_at": db.fmt_dt(d["created_at"]),
        "updated_at": db.fmt_dt(d["updated_at"]),
        "version": d["version"],
    }
