"""Order settlement (INVEST / WITHDRAW) and the sweep + threshold auto-invest.

PRD §3.5 (sweep), §3.7 (invest/withdraw settlement). These hold the load-bearing
cascading side effects and pinned evaluation orders.
"""

from db import store
from errors import err
from models import (
    IRA_ANNUAL_CAP_CENTS,
    create_cash_transaction,
    new_entity,
    recompute_bucket,
    touch,
)
from response import format_ts
from services.calc import invest_fee_and_net, lot_market_value


# ---------------------------------------------------------------------------
# INVEST settlement (PRD §3.7) — pinned evaluation order.
# ---------------------------------------------------------------------------
def settle_invest(order, bucket, account):
    """Returns None on success; raises ApiError on precondition breach.

    Pinned order: gross -> floor fee -> net = gross - fee -> settled = net ->
    open TaxLot(cost=net, remaining=net) -> debit cash by full gross -> add net
    to lifetime_invested -> (IRA) add net to ytd_ira_contributed (cap-checked).
    """
    plan = store.subscription_plans[account["plan_id"]]
    gross = order["requested_amount_cents"]

    # Fiscal sufficiency (PRD §3.7): cash must cover the full gross.
    if account["cash_balance_cents"] < gross:
        raise err("ERR_INSUFFICIENT_CASH", "Cash balance is below the requested invest amount.")

    management_fee_cents, net_principal = invest_fee_and_net(gross, plan["management_fee_bps"])

    # IRA annual cap check before accumulation (PRD §3.7).
    if bucket["bucket_type"] == "IRA":
        if bucket["ytd_ira_contributed_cents"] + net_principal > IRA_ANNUAL_CAP_CENTS:
            raise err("ERR_IRA_CAP_EXCEEDED", "IRA annual contribution cap would be exceeded.")

    # Apply.
    order["settled_amount_cents"] = net_principal
    order["management_fee_cents"] = management_fee_cents
    order["realized_gain_cents"] = 0

    lot = new_entity(
        {
            "bucket_id": bucket["id"],
            "open_order_id": order["id"],
            "cost_basis_cents": net_principal,
            "remaining_basis_cents": net_principal,
            "unit_gain_ratio_bps": 0,
            "market_value_cents": net_principal,  # gain ratio 0 at open
            "acquired_at": format_ts(store.now()),
            "status": "OPEN",
        }
    )
    store.tax_lots[lot["id"]] = lot

    # Debit full gross from cash; the fee is withheld to the platform (PRD §3.7).
    # PRD §3.7's invest narrative directs only the cash debit (no CashTransaction
    # row is enumerated for an invest settlement), so we record none here.
    account["cash_balance_cents"] = account["cash_balance_cents"] - gross

    account["lifetime_invested_cents"] = account["lifetime_invested_cents"] + net_principal

    if bucket["bucket_type"] == "IRA":
        bucket["ytd_ira_contributed_cents"] = bucket["ytd_ira_contributed_cents"] + net_principal

    recompute_bucket(bucket)


# ---------------------------------------------------------------------------
# WITHDRAW settlement (PRD §3.7) — lot selection + realized gain.
# ---------------------------------------------------------------------------
def _ordered_lots(bucket, method, spec_lot_ids):
    open_lots = [
        lot
        for lot in store.tax_lots.values()
        if lot["bucket_id"] == bucket["id"] and lot["status"] == "OPEN"
    ]
    if method == "FIFO":
        return sorted(open_lots, key=lambda l: (l["acquired_at"], l["_seq"]))
    if method == "HIFO":
        return sorted(
            open_lots,
            key=lambda l: (-l["unit_gain_ratio_bps"], l["acquired_at"], l["_seq"]),
        )
    # SPEC_ID
    if spec_lot_ids:
        by_id = {lot["id"]: lot for lot in open_lots}
        ordered = [by_id[lid] for lid in spec_lot_ids if lid in by_id]
        return ordered
    # No explicit list -> fall back to oldest acquired_at first (PRD §3.7).
    return sorted(open_lots, key=lambda l: (l["acquired_at"], l["_seq"]))


def settle_withdraw(order, bucket, account, spec_lot_ids):
    """Consume lots per lot_selection_method; compute realized gain and proceeds.

    Precondition (PRD §3.7): the market value of the selected open lots must
    cover the requested proceeds, else ERR_INSUFFICIENT_LOTS.
    """
    method = order.get("lot_selection_method") or "FIFO"
    lots = _ordered_lots(bucket, method, spec_lot_ids)

    target = order["requested_amount_cents"]

    # Coverage check across the selected lots (PRD §3.7).
    available_mv = sum(
        lot_market_value(lot["remaining_basis_cents"], lot["unit_gain_ratio_bps"])
        for lot in lots
    )
    if available_mv < target:
        raise err("ERR_INSUFFICIENT_LOTS", "Selected lots do not cover the requested proceeds.")

    remaining = target
    proceeds = 0
    realized_gain = 0

    for lot in lots:
        if remaining <= 0:
            break
        lot_mv = lot_market_value(lot["remaining_basis_cents"], lot["unit_gain_ratio_bps"])
        if lot_mv <= 0:
            continue
        take_mv = min(lot_mv, remaining)
        basis_consumed = (lot["remaining_basis_cents"] * take_mv) // lot_mv
        realized_gain += take_mv - basis_consumed
        lot["remaining_basis_cents"] = lot["remaining_basis_cents"] - basis_consumed
        if lot["remaining_basis_cents"] == 0:
            lot["status"] = "DEPLETED"
        lot["market_value_cents"] = lot_market_value(
            lot["remaining_basis_cents"], lot["unit_gain_ratio_bps"]
        )
        touch(lot)
        proceeds += take_mv
        remaining -= take_mv

    order["settled_amount_cents"] = proceeds
    order["realized_gain_cents"] = realized_gain
    order["management_fee_cents"] = 0

    account["cash_balance_cents"] = account["cash_balance_cents"] + proceeds
    create_cash_transaction(account["id"], "WITHDRAW_PROCEEDS", proceeds, "CONFIRMED")

    recompute_bucket(bucket)


# ---------------------------------------------------------------------------
# Sweep + threshold auto-invest (PRD §3.5).
# ---------------------------------------------------------------------------
def run_sweep(account):
    """Gather PENDING accruals -> SWEPT, credit cash by the summed frozen
    effective amounts, then auto-invest the whole balance if at/above threshold.
    The owning account version is bumped exactly once by the caller (route).
    """
    pending = [
        acc
        for acc in store.roundup_accruals.values()
        if acc["account_id"] == account["id"] and acc["status"] == "PENDING"
    ]
    # Round-per-accrual at accrual time, THEN sum here (PRD §3.5).
    swept_total = sum(acc["effective_amount_cents"] for acc in pending)
    for acc in pending:
        acc["status"] = "SWEPT"
        touch(acc)
    account["cash_balance_cents"] = account["cash_balance_cents"] + swept_total
    # pending_roundup_cents now zero for these (recompute in route after).

    # Threshold step (PRD §3.5): inclusive comparison.
    if account["cash_balance_cents"] >= account["sweep_threshold_cents"]:
        invest_amount = account["cash_balance_cents"]
        _auto_invest_sweep(account, invest_amount)


def _auto_invest_sweep(account, invest_amount):
    """Auto-create and immediately settle a SETTLED INVEST order (source=SWEEP)
    into the account's primary TAXABLE bucket (PRD §3.5)."""
    bucket = _primary_taxable_bucket(account)
    if bucket is None:
        # No taxable bucket to invest into; cash simply remains in the buffer.
        return

    order = new_entity(
        {
            "account_id": account["id"],
            "bucket_id": bucket["id"],
            "order_kind": "INVEST",
            "source": "SWEEP",
            "requested_amount_cents": invest_amount,
            "lot_selection_method": None,
            "settled_amount_cents": 0,
            "realized_gain_cents": 0,
            "management_fee_cents": 0,
            "status": "SUBMITTED",
        }
    )
    store.orders[order["id"]] = order
    settle_invest(order, bucket, account)
    order["status"] = "SETTLED"
    touch(order)


def _primary_taxable_bucket(account):
    """The account's primary TAXABLE bucket: earliest-created OPEN TAXABLE bucket."""
    taxable = [
        b
        for b in store.buckets.values()
        if b["account_id"] == account["id"]
        and b["bucket_type"] == "TAXABLE"
        and b["status"] == "OPEN"
    ]
    if not taxable:
        return None
    return sorted(taxable, key=lambda b: b["_seq"])[0]
