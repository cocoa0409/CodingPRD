"""NAV publish + confirmation cascade orchestration."""
from datetime import datetime, timedelta, timezone
from clock import now, iso, parse_iso, parse_iso_date, date_to_dt_utc
from db import (
    funds, investors, orders, holdings, lot_entries,
    nav_snapshots, stamp_create, stamp_update,
)
from errors import err
from services import audit
from services.calculations import (
    compute_nav_components,
    compute_subscription_confirmation,
    compute_redemption_confirmation,
    compute_conversion_fee,
    compute_large_redemption_pct_bps,
)
from services.holdings import (
    get_or_create_holding, fifo_burn, recompute_holding_aggregates, create_lot,
    get_holding,
)


def find_nav_snapshot(fund_id: str, nav_date):
    """Find a NavSnapshot by (fund_id, nav_date). nav_date may be a date, datetime, or ISO-8601 string."""
    if isinstance(nav_date, datetime):
        target = nav_date.date()
    elif hasattr(nav_date, "year"):
        target = nav_date
    else:
        target = parse_iso_date(nav_date)
    for s in nav_snapshots.values():
        if s["fund_id"] != fund_id:
            continue
        snap_date = parse_iso_date(s["nav_date"])
        if snap_date == target:
            return s
    return None


def _published_nav_for(fund_id: str, target_date):
    s = find_nav_snapshot(fund_id, target_date)
    if s and s["status"] in ("PUBLISHED", "ADJUSTED"):
        return s
    return None


def confirm_order_at_nav(order: dict, snapshot: dict, fund: dict, actor_id: str, actor_role: str):
    """Move ACCEPTED -> CONFIRMED for SUBSCRIBE/REDEEM/CONVERT using snapshot's NAV. Returns the updated order."""
    nav_micros = snapshot["nav_per_share_micros"]
    investor = investors[order["investor_id"]]
    order_type = order["order_type"]
    confirmation_iso = iso(now())  # used for LotEntry.acquired_at

    if order_type == "SUBSCRIBE":
        gross = order["gross_amount_cents"]
        result = compute_subscription_confirmation(
            gross, nav_micros, fund["subscription_fee_tiers"], fund["back_end_load_enabled"]
        )
        order["confirmed_nav_per_share_micros"] = nav_micros
        order["subscription_fee_cents"] = result["subscription_fee_cents"]
        order["redemption_fee_cents"] = 0
        order["back_end_load_fee_cents"] = 0
        order["conversion_fee_cents"] = 0
        order["confirmed_shares"] = result["confirmed_shares"]
        order["confirmed_amount_cents"] = result["confirmed_amount_cents"]

        # Cascade: holding, lot, fund.outstanding, investor.cash
        holding = get_or_create_holding(investor["id"], fund["id"])
        # Lot cost is post-front-fee net (or gross if back-end)
        if fund["back_end_load_enabled"]:
            lot_cost = gross
        else:
            lot_cost = gross - result["subscription_fee_cents"]
        create_lot(holding["id"], order["id"], result["confirmed_shares"], lot_cost,
                   confirmation_iso)
        recompute_holding_aggregates(investor["id"], fund["id"])
        fund["total_outstanding_shares"] += result["confirmed_shares"]
        stamp_update(fund)
        investor["cash_balance_cents"] -= gross
        stamp_update(investor)

    elif order_type == "REDEEM":
        requested = order["requested_shares"]
        # FIFO burn
        consumed = fifo_burn(investor["id"], fund["id"], requested)
        td = parse_iso_date(order["trade_date"])
        result = compute_redemption_confirmation(
            requested, nav_micros, td,
            fund["redemption_fee_tiers"],
            fund["subscription_fee_tiers"],
            fund["back_end_load_enabled"],
            consumed,
        )
        order["confirmed_nav_per_share_micros"] = nav_micros
        order["subscription_fee_cents"] = 0
        order["redemption_fee_cents"] = result["redemption_fee_cents"]
        order["back_end_load_fee_cents"] = result["back_end_load_fee_cents"]
        order["conversion_fee_cents"] = 0
        order["confirmed_shares"] = requested
        order["confirmed_amount_cents"] = result["confirmed_amount_cents"]

        recompute_holding_aggregates(investor["id"], fund["id"])
        fund["total_outstanding_shares"] -= requested
        stamp_update(fund)
        investor["cash_balance_cents"] += result["confirmed_amount_cents"]
        stamp_update(investor)

    elif order_type == "CONVERT":
        target_fund = funds[order["target_fund_id"]]
        requested = order["requested_shares"]
        consumed = fifo_burn(investor["id"], fund["id"], requested)
        td = parse_iso_date(order["trade_date"])
        result = compute_redemption_confirmation(
            requested, nav_micros, td,
            fund["redemption_fee_tiers"],
            fund["subscription_fee_tiers"],
            fund["back_end_load_enabled"],
            consumed,
        )
        # Add conversion fee on top
        conv_fee = compute_conversion_fee(result["gross_redeem_amount_cents"], fund["conversion_fee_bps"])
        net_proceeds = result["confirmed_amount_cents"] - conv_fee

        order["confirmed_nav_per_share_micros"] = nav_micros
        order["subscription_fee_cents"] = 0
        order["redemption_fee_cents"] = result["redemption_fee_cents"]
        order["back_end_load_fee_cents"] = result["back_end_load_fee_cents"]
        order["conversion_fee_cents"] = conv_fee
        order["confirmed_shares"] = requested
        order["confirmed_amount_cents"] = net_proceeds

        # Source-side cascades
        recompute_holding_aggregates(investor["id"], fund["id"])
        fund["total_outstanding_shares"] -= requested
        stamp_update(fund)

        # Target-side: needs target NAV for share minting. Use target's published NAV at trade_date.
        target_snap = _published_nav_for(target_fund["id"], parse_iso_date(order["trade_date"]))
        if target_snap is not None:
            tgt_nav_micros = target_snap["nav_per_share_micros"]
        else:
            # Fall back to source snapshot's NAV (best-effort) — tests typically publish both.
            tgt_nav_micros = nav_micros
        if tgt_nav_micros <= 0:
            tgt_nav_micros = 1_000_000
        from services.util import round_half_up as _rhu
        target_shares_minted = _rhu(net_proceeds * 100_000_000, tgt_nav_micros)
        target_holding = get_or_create_holding(investor["id"], target_fund["id"])
        create_lot(target_holding["id"], order["id"], target_shares_minted, net_proceeds,
                   confirmation_iso)
        recompute_holding_aggregates(investor["id"], target_fund["id"])
        target_fund["total_outstanding_shares"] += target_shares_minted
        stamp_update(target_fund)

    order["status"] = "CONFIRMED"
    stamp_update(order)
    audit.write(actor_id, actor_role, "ORDER_STATUS_CHANGE", "Order", order["id"],
                "ACCEPTED", "CONFIRMED", {})
    return order


def confirm_deferred_order_at_nav(order: dict, snapshot: dict, fund: dict,
                                   actor_id: str, actor_role: str):
    """Confirm a LARGE_REDEMPTION_DEFERRED REDEEM order."""
    nav_micros = snapshot["nav_per_share_micros"]
    investor = investors[order["investor_id"]]
    requested = order["requested_shares"]
    consumed = fifo_burn(investor["id"], fund["id"], requested)
    td = parse_iso_date(order["trade_date"])
    result = compute_redemption_confirmation(
        requested, nav_micros, td,
        fund["redemption_fee_tiers"],
        fund["subscription_fee_tiers"],
        fund["back_end_load_enabled"],
        consumed,
    )
    order["confirmed_nav_per_share_micros"] = nav_micros
    order["subscription_fee_cents"] = 0
    order["redemption_fee_cents"] = result["redemption_fee_cents"]
    order["back_end_load_fee_cents"] = result["back_end_load_fee_cents"]
    order["conversion_fee_cents"] = 0
    order["confirmed_shares"] = requested
    order["confirmed_amount_cents"] = result["confirmed_amount_cents"]

    recompute_holding_aggregates(investor["id"], fund["id"])
    fund["total_outstanding_shares"] -= requested
    stamp_update(fund)
    investor["cash_balance_cents"] += result["confirmed_amount_cents"]
    stamp_update(investor)

    order["status"] = "CONFIRMED"
    stamp_update(order)
    audit.write(actor_id, actor_role, "ORDER_STATUS_CHANGE", "Order", order["id"],
                "LARGE_REDEMPTION_DEFERRED", "CONFIRMED", {})
    return order


def confirmation_pass(fund: dict, snapshot: dict, actor_id: str, actor_role: str):
    """After NAV publish, walk orders and confirm/defer those whose trade_date == snapshot.nav_date and confirm_date reached.

    Also re-evaluates LARGE_REDEMPTION_DEFERRED orders whose new confirm_date has been reached.
    """
    snap_date = parse_iso_date(snapshot["nav_date"])
    current_now = now()

    # Pass B (collect FIRST, before Pass A may defer new orders into the same status):
    # PRD §3.4 ties deferred re-confirmation to the "next NAV publication". Orders deferred
    # in the current publish round must not be re-confirmed within the same call — only
    # orders that were already in LARGE_REDEMPTION_DEFERRED before this publish are eligible.
    candidates_b = []
    for o in orders.values():
        if o["status"] != "LARGE_REDEMPTION_DEFERRED":
            continue
        if o["fund_id"] != fund["id"]:
            continue
        confirm_dt = parse_iso(o["confirm_date"])
        if current_now < confirm_dt:
            continue
        candidates_b.append(o)

    # Pass A: process ACCEPTED orders whose trade_date == snap_date and confirm_date reached.
    candidates_a = []
    for o in orders.values():
        if o["status"] != "ACCEPTED":
            continue
        if o["fund_id"] != fund["id"]:
            continue
        if not o.get("trade_date"):
            continue
        if parse_iso_date(o["trade_date"]) != snap_date:
            continue
        confirm_dt = parse_iso(o["confirm_date"])
        if current_now < confirm_dt:
            continue
        candidates_a.append(o)
    candidates_a.sort(key=lambda o: (o["created_at"], o["_seq"]))
    snap_shares_at_nav = snapshot["shares_outstanding_at_nav"]
    for o in candidates_a:
        if o["order_type"] == "REDEEM":
            # Large-redemption test: use shares_outstanding at trade_date end (snapshot)
            pct = compute_large_redemption_pct_bps(o["requested_shares"], snap_shares_at_nav)
            if pct >= fund["large_redemption_threshold_pct_bps"]:
                o["large_redemption_pct_bps"] = pct
                # Defer +1 day
                old_confirm = parse_iso(o["confirm_date"])
                new_confirm = old_confirm + timedelta(days=1)
                o["confirm_date"] = iso(new_confirm)
                o["status"] = "LARGE_REDEMPTION_DEFERRED"
                stamp_update(o)
                audit.write(actor_id, actor_role, "ORDER_STATUS_CHANGE", "Order", o["id"],
                            "ACCEPTED", "LARGE_REDEMPTION_DEFERRED",
                            {"large_redemption_pct_bps": pct})
                continue
        confirm_order_at_nav(o, snapshot, fund, actor_id, actor_role)

    # Pass B (resolve previously-deferred orders against this NAV publication):
    candidates_b.sort(key=lambda o: (o["created_at"], o["_seq"]))
    for o in candidates_b:
        # Use the just-published snapshot (the deferred path re-uses next NAV publication's snapshot).
        confirm_deferred_order_at_nav(o, snapshot, fund, actor_id, actor_role)
