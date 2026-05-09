"""Cascade helpers and risk-score recomputation."""
from store import store, bump
import calc


# ---------------- Risk Scores ----------------

def recompute_leader_risk(leader_id):
    """Recompute chronic + acute risk for a leader; uses current period."""
    leader = store.group_leaders.get(leader_id)
    if leader is None:
        return
    cur = store.system_period_index

    # Window 30: created_period in [cur-29, cur]
    bot_30 = 0
    coll_30 = 0
    for a in store.risk_alerts.values():
        if a["status"] != "CONFIRMED":
            continue
        if not (cur - 29 <= a["created_period_index"] <= cur):
            continue
        if a["alert_type"] == "BOT_ORDER" and a["target_kind"] == "ORDER":
            order = store.orders.get(a["target_id"])
            if order and order.get("campaign_kind") == "GROUP_BUY":
                cmp = store.group_buy_campaigns.get(order["campaign_id"])
                if cmp and cmp["leader_id"] == leader_id:
                    bot_30 += 1
        if a["alert_type"] == "LEADER_SUPPLIER_COLLUSION" and a["target_kind"] == "GROUP_LEADER":
            if a["target_id"] == leader_id:
                coll_30 += 1
    fake_30 = 0
    for cmp in store.group_buy_campaigns.values():
        if cmp.get("leader_id") != leader_id:
            continue
        if cmp.get("status") not in ("FAILED",):
            continue
        if cmp.get("participant_count", 0) != 0:
            continue
        close_period = store.failed_close_period.get(cmp["id"])
        if close_period is None:
            continue
        if cur - 29 <= close_period <= cur:
            fake_30 += 1

    # Window 5
    bot_5 = 0
    coll_5 = 0
    for a in store.risk_alerts.values():
        if a["status"] != "CONFIRMED":
            continue
        if not (cur - 4 <= a["created_period_index"] <= cur):
            continue
        if a["alert_type"] == "BOT_ORDER" and a["target_kind"] == "ORDER":
            order = store.orders.get(a["target_id"])
            if order and order.get("campaign_kind") == "GROUP_BUY":
                cmp = store.group_buy_campaigns.get(order["campaign_id"])
                if cmp and cmp["leader_id"] == leader_id:
                    bot_5 += 1
        if a["alert_type"] == "LEADER_SUPPLIER_COLLUSION" and a["target_kind"] == "GROUP_LEADER":
            if a["target_id"] == leader_id:
                coll_5 += 1
    fake_5 = 0
    for cmp in store.group_buy_campaigns.values():
        if cmp.get("leader_id") != leader_id:
            continue
        if cmp.get("status") != "FAILED":
            continue
        if cmp.get("participant_count", 0) != 0:
            continue
        close_period = store.failed_close_period.get(cmp["id"])
        if close_period is None:
            continue
        if cur - 4 <= close_period <= cur:
            fake_5 += 1

    leader["chronic_risk_score"] = calc.chronic_risk_score(bot_30, fake_30, coll_30)
    leader["acute_risk_score"] = calc.acute_risk_score(bot_5, fake_5, coll_5)


def recompute_all_active_leaders():
    for leader in list(store.group_leaders.values()):
        if leader["status"] == "ACTIVE":
            recompute_leader_risk(leader["id"])


# ---------------- Order cancel cascade ----------------

def cancel_non_terminal_shipments(order):
    for shp_id, shp in list(store.shipments.items()):
        if shp["order_id"] != order["id"]:
            continue
        if shp["status"] in ("PLANNED", "DISPATCHED"):
            shp["status"] = "CANCELLED"
            bump(shp)


def cascade_order_cancel_from_fulfillment(order):
    """Cancel non-terminal shipments and set fulfillment_status = CANCELLED if eligible."""
    if order["fulfillment_status"] in ("NOT_PLANNED", "PLANNED", "DISPATCHED"):
        order["fulfillment_status"] = "CANCELLED"
        bump(order)
    cancel_non_terminal_shipments(order)


# ---------------- Group-buy campaign close cascades ----------------

def close_campaign_failed(campaign, close_period=None):
    """Close a campaign as FAILED; cascade child PAID orders into auto-refund."""
    campaign["status"] = "FAILED"
    bump(campaign)
    store.failed_close_period[campaign["id"]] = (
        close_period if close_period is not None else store.system_period_index
    )
    for order in list(store.orders.values()):
        if order.get("campaign_kind") != "GROUP_BUY":
            continue
        if order["campaign_id"] != campaign["id"]:
            continue
        if order["payment_status"] == "PAID":
            # synchronous: PAID -> REFUND_PENDING
            order["payment_status"] = "REFUND_PENDING"
            bump(order)
            # full refund of subtotal queued for sweep
            store.refund_pending[order["id"]] = order.get("subtotal_cents", 0)
            cascade_order_cancel_from_fulfillment(order)
            # PENDING commission entries -> PENDING_CLAWBACK (none for FAILED, but for safety)
            for ce in store.commission_entries.values():
                if ce["order_id"] == order["id"] and ce["status"] == "PENDING":
                    ce["status"] = "PENDING_CLAWBACK"
                    bump(ce)


def close_campaign_succeeded(campaign):
    """Close a campaign as SUCCEEDED; pin discount, settle PAID orders, generate commissions."""
    from calc import select_discount_tier, compute_order_total
    campaign["status"] = "SUCCEEDED"
    pcount = campaign.get("participant_count", 0)
    tier_idx, disc_bp = select_discount_tier(pcount, campaign["discount_tiers"])
    campaign["settled_tier_index"] = tier_idx
    campaign["settled_discount_basis_points"] = disc_bp
    bump(campaign)
    # Settle every PAID order
    for order in list(store.orders.values()):
        if order.get("campaign_kind") != "GROUP_BUY":
            continue
        if order["campaign_id"] != campaign["id"]:
            continue
        if order["payment_status"] == "PAID":
            order["payment_status"] = "SETTLED"
            order["settled_total_cents"] = compute_order_total(order["subtotal_cents"], disc_bp)
            bump(order)
            generate_commission_entries(campaign, order)


def generate_commission_entries(campaign, order):
    """Generate PRIMARY/SECONDARY/UPSTREAM commission entries for a settled order."""
    from store import stamp_create
    primary_leader = store.group_leaders.get(campaign["leader_id"])
    if primary_leader is None:
        return
    primary_tier = primary_leader["tier"]
    settled = order["settled_total_cents"]
    paid_period = order.get("paid_period_index", store.system_period_index)
    target_period = calc.compute_payout_target(paid_period, primary_tier)
    line_items = order["line_items"]

    # Determine whether there is a qualifying secondary partner
    partner_ids = campaign.get("cross_community_partner_leader_ids") or []
    qualified_partners = []
    for pid in partner_ids:
        partner = store.group_leaders.get(pid)
        if partner and partner.get("tier", 0) <= 2:
            qualified_partners.append(partner)
    # Pick first qualifying partner's tier as the secondary_tier for the PRIMARY bonus
    secondary_tier_for_primary = qualified_partners[0]["tier"] if qualified_partners else None

    # PRIMARY entry
    gross = calc.compute_tiered_rebate(
        settled, "PRIMARY", primary_tier,
        secondary_tier=secondary_tier_for_primary,
    )
    tax = calc.compute_tax_withholding(gross, line_items)
    entry = {
        **stamp_create(),
        "leader_id": primary_leader["id"],
        "order_id": order["id"],
        "leader_role": "PRIMARY",
        "gross_rebate_cents": gross,
        "tax_withholding_cents": tax,
        "net_rebate_cents": gross - tax,
        "payout_target_period_index": target_period,
        "status": "PENDING",
        "payout_id": None,
    }
    store.commission_entries[entry["id"]] = entry

    # SECONDARY entries
    for partner in qualified_partners:
        gross_s = calc.compute_tiered_rebate(
            settled, "SECONDARY", primary_tier,
            secondary_tier=partner["tier"],
        )
        tax_s = calc.compute_tax_withholding(gross_s, line_items)
        e = {
            **stamp_create(),
            "leader_id": partner["id"],
            "order_id": order["id"],
            "leader_role": "SECONDARY",
            "gross_rebate_cents": gross_s,
            "tax_withholding_cents": tax_s,
            "net_rebate_cents": gross_s - tax_s,
            "payout_target_period_index": target_period,
            "status": "PENDING",
            "payout_id": None,
        }
        store.commission_entries[e["id"]] = e

    # UPSTREAM entries — walk parent chain (capped at depth 2)
    cur_id = primary_leader.get("parent_leader_id")
    depth = 1
    while cur_id and depth <= 2:
        upstream = store.group_leaders.get(cur_id)
        if not upstream:
            break
        gross_u = calc.compute_tiered_rebate(
            settled, "UPSTREAM", primary_tier, upstream_depth=depth,
        )
        tax_u = calc.compute_tax_withholding(gross_u, line_items)
        e = {
            **stamp_create(),
            "leader_id": upstream["id"],
            "order_id": order["id"],
            "leader_role": "UPSTREAM",
            "gross_rebate_cents": gross_u,
            "tax_withholding_cents": tax_u,
            "net_rebate_cents": gross_u - tax_u,
            "payout_target_period_index": target_period,
            "status": "PENDING",
            "payout_id": None,
        }
        store.commission_entries[e["id"]] = e
        cur_id = upstream.get("parent_leader_id")
        depth += 1


# ---------------- Leader suspension cascade ----------------

def suspend_leader_cascade(leader):
    """Move leader to SUSPENDED and auto-close FORMING/EXTENDED campaigns as FAILED."""
    leader["status"] = "SUSPENDED"
    bump(leader)
    for cmp in list(store.group_buy_campaigns.values()):
        if cmp.get("leader_id") != leader["id"]:
            continue
        if cmp.get("status") in ("FORMING", "EXTENDED"):
            close_campaign_failed(cmp)


# ---------------- Refund / clawback handling on after-sales ----------------

def order_to_refund_pending(order, amount_cents):
    """Synchronous PAID/SETTLED -> REFUND_PENDING with PENDING entries -> PENDING_CLAWBACK."""
    order["payment_status"] = "REFUND_PENDING"
    bump(order)
    store.refund_pending[order["id"]] = amount_cents
    for ce in store.commission_entries.values():
        if ce["order_id"] != order["id"]:
            continue
        if ce["status"] == "PENDING":
            ce["status"] = "PENDING_CLAWBACK"
            bump(ce)
            recompute_payout_total(ce.get("payout_id"))


def recompute_payout_total(payout_id):
    if not payout_id:
        return
    payout = store.payouts.get(payout_id)
    if not payout:
        return
    total = 0
    for entry_id in payout["bundled_entry_ids"]:
        ce = store.commission_entries.get(entry_id)
        if ce is None:
            continue
        if ce["status"] in ("PENDING_CLAWBACK", "CLAWED_BACK"):
            continue
        total += ce["net_rebate_cents"]
    payout["total_amount_cents"] = total
    bump(payout)


def revert_clawbacks_for_order(order):
    """When after-sales rejects, return PENDING_CLAWBACK -> PENDING for the order's entries."""
    for ce in store.commission_entries.values():
        if ce["order_id"] != order["id"]:
            continue
        if ce["status"] == "PENDING_CLAWBACK":
            ce["status"] = "PENDING"
            bump(ce)
            recompute_payout_total(ce.get("payout_id"))


def proportional_partial_compensation(order, resolved_amount_cents):
    """Order: SETTLED -> PARTIALLY_REFUNDED; refunded_amount += resolved; commission entries reduced proportionally."""
    order["payment_status"] = "PARTIALLY_REFUNDED"
    order["refunded_amount_cents"] = order.get("refunded_amount_cents", 0) + resolved_amount_cents
    bump(order)
    settled = order.get("settled_total_cents", 0)
    if settled <= 0:
        return
    remaining = max(settled - order["refunded_amount_cents"], 0)
    for ce in store.commission_entries.values():
        if ce["order_id"] != order["id"]:
            continue
        if ce["status"] not in ("PENDING", "SETTLED"):
            continue
        new_gross = (ce["gross_rebate_cents"] * remaining) // settled
        ce["gross_rebate_cents"] = new_gross
        ce["tax_withholding_cents"] = calc.compute_tax_withholding(new_gross, order["line_items"])
        ce["net_rebate_cents"] = new_gross - ce["tax_withholding_cents"]
        bump(ce)
        recompute_payout_total(ce.get("payout_id"))
