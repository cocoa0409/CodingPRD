# Quarter close pipeline (PRD 3.4) — pinned nine-step order — plus the
# supersede rollback. Also home to the shared fund refresh and ledger helpers.
from constants import (
    INCEPTION_UNIT_PRICE_MILLICENTS,
    LAPSE_QUARTERS,
    QUARTERS_PER_FISCAL_YEAR,
)
from db import store, bump, stamp_new
from services import calc
from services.spending import compute_distribution
from util import new_id, now_iso


def emit_ledger(fund_id, quarter_index, entry_type, units_delta, amount, reference_id):
    rec = {
        "id": new_id(),
        "fund_id": fund_id,
        "quarter_index": quarter_index,
        "entry_type": entry_type,
        "units_delta_micro": units_delta,
        "amount_cents": amount,
        "reference_id": reference_id,
    }
    # UnitLedgerEntry is append-only: id + created_at only, no updated_at/version.
    rec["created_at"] = now_iso()
    rec["_seq"] = store.next_seq()
    store.ledger[rec["id"]] = rec
    return rec


def refresh_fund_mv(fund, price_millicents):
    """Recompute market value and the underwater flag from a price/units move.
    Bumps the fund version only when a persisted value actually changes."""
    new_mv = calc.fund_market_value(fund["units_held_micro"], price_millicents)
    new_under = new_mv < fund["historic_gift_value_cents"]
    if new_mv != fund["market_value_cents"] or new_under != fund["is_underwater"]:
        fund["market_value_cents"] = new_mv
        fund["is_underwater"] = new_under
        bump(fund)


def _funds_of_pool(pool):
    return [f for f in store.funds.values() if f["pool_id"] == pool["id"]]


def _term_exempt_at_quarter(fund, quarter_index):
    return (
        fund["endowment_class"] == "TERM_ENDOWMENT"
        and fund["term_end_quarter_index"] is not None
        and quarter_index >= fund["term_end_quarter_index"]
    )


def _exempt_at_quarter(fund, quarter_index):
    return fund["endowment_class"] == "QUASI_ENDOWMENT" or _term_exempt_at_quarter(
        fund, quarter_index
    )


def revert_distributions_using_exception(exc):
    """Expiry/rescission cascade: linked APPROVED distributions revert to
    PROPOSED with a recomputed final amount."""
    for d in store.distributions.values():
        if (
            d.get("applied_exception_id") == exc["id"]
            and d["distribution_status"] == "APPROVED"
        ):
            d["distribution_status"] = "PROPOSED"
            d["applied_exception_id"] = None
            d["approved_by_user_id"] = None
            fund = store.funds.get(d["fund_id"])
            pool = store.pools.get(fund["pool_id"]) if fund else None
            if fund is not None and pool is not None:
                compute_distribution(d, fund, pool)
            bump(d)


def _exception_exit_posture(exc):
    """EXCEPTION_ACTIVE -> SPENDING_SUSPENDED when the exception leaves
    APPROVED (exercise/expiry/rescission); a later finalize may move the
    fund onward to NORMAL."""
    fund = store.funds.get(exc["fund_id"])
    if fund is not None and fund["spending_posture"] == "EXCEPTION_ACTIVE":
        fund["spending_posture"] = "SPENDING_SUSPENDED"
        bump(fund)


def run_quarter_close(pool, valuation, final_mv, user_id):
    """The pinned nine-step pipeline. Gates are checked by the route layer
    before this runs; each step observes only earlier steps' outputs."""
    q = valuation["quarter_index"]

    # Snapshot allocation drift state BEFORE this finalize (supersede rollback).
    valuation["_alloc_snapshot"] = {
        a["id"]: {
            "actual_pct_bps": a["actual_pct_bps"],
            "drift_status": a["drift_status"],
            "drift_acknowledged": a["drift_acknowledged"],
        }
        for a in store.allocations.values()
        if a["pool_id"] == pool["id"]
    }

    # --- Step 1: price (pre-flow units only) ---
    units_pre = pool["total_units_outstanding_micro"]
    price = calc.final_price(final_mv, units_pre)
    valuation["final_pool_market_value_cents"] = final_mv
    valuation["final_unit_price_millicents"] = price

    # --- Step 2: lapse sweep (before unitization) ---
    for payout in sorted(
        store.payouts.values(), key=lambda p: (p["created_at"], p["_seq"])
    ):
        if payout["payout_status"] != "DISBURSED":
            continue
        dist = store.distributions.get(payout["distribution_id"])
        fund = store.funds.get(dist["fund_id"]) if dist else None
        if fund is None or fund["pool_id"] != pool["id"]:
            continue
        if (q - payout["disbursed_quarter_index"]) < LAPSE_QUARTERS:
            continue
        unspent = payout["allocated_amount_cents"] - payout["spent_amount_cents"]
        gift = {
            "id": new_id(),
            "fund_id": fund["id"],
            "donor_id": None,
            "external_ref": "SWEEP-" + payout["id"],
            "gift_type": "EXPENDABLE",
            "amount_cents": unspent,
            "gift_status": "RECEIVED",
            "received_quarter_index": q,
            "provisional_units_estimate_micro": calc.units_for_amount(
                unspent, pool["current_unit_price_millicents"]
            ),
            "unitized_quarter_index": None,
            "units_purchased_micro": None,
            "source_payout_id": payout["id"],
            "version": 1,
        }
        stamp_new(gift)
        store.gifts[gift["id"]] = gift
        payout["payout_status"] = "CLOSED_RETURNED"
        payout["unspent_amount_cents"] = 0
        payout["swept_gift_id"] = gift["id"]
        bump(payout)

    # --- Step 3: unitization (donor gifts and sweep reinvestments alike) ---
    eligible_gifts = [
        g
        for g in store.gifts.values()
        if g["gift_status"] == "RECEIVED" and g["received_quarter_index"] == q
        and (store.funds.get(g["fund_id"]) or {}).get("pool_id") == pool["id"]
    ]
    eligible_gifts.sort(key=lambda g: (g["created_at"], g["external_ref"]))
    unitized = []
    for g in eligible_gifts:
        units = calc.units_for_amount(g["amount_cents"], price)
        g["units_purchased_micro"] = units
        g["unitized_quarter_index"] = q
        g["gift_status"] = "UNITIZED"
        bump(g)
        fund = store.funds[g["fund_id"]]
        fund["units_held_micro"] += units
        pool["total_units_outstanding_micro"] += units
        entry_type = (
            "REINVEST_UNITIZE" if g.get("source_payout_id") else "GIFT_UNITIZE"
        )
        reference_id = g["source_payout_id"] if g.get("source_payout_id") else g["id"]
        emit_ledger(fund["id"], q, entry_type, units, g["amount_cents"], reference_id)
        unitized.append(g)

    # --- Step 4: HGV refresh for CORPUS gifts unitized in step 3 ---
    hgv_touched = set()
    for g in unitized:
        if g["gift_type"] == "CORPUS":
            fund = store.funds[g["fund_id"]]
            fund["historic_gift_value_cents"] += g["amount_cents"]
            hgv_touched.add(fund["id"])
    for fid in hgv_touched:
        bump(store.funds[fid])

    # --- Step 5: market value + underwater refresh on every pool fund ---
    for fund in _funds_of_pool(pool):
        new_mv = calc.fund_market_value(fund["units_held_micro"], price)
        new_under = new_mv < fund["historic_gift_value_cents"]
        if new_mv != fund["market_value_cents"] or new_under != fund["is_underwater"]:
            fund["market_value_cents"] = new_mv
            fund["is_underwater"] = new_under
            bump(fund)

    # --- Step 6: posture transitions (NORMAL <-> SPENDING_SUSPENDED) ---
    for fund in _funds_of_pool(pool):
        exempt = _exempt_at_quarter(fund, q)
        if (
            fund["is_underwater"]
            and not exempt
            and fund["spending_posture"] == "NORMAL"
        ):
            fund["spending_posture"] = "SPENDING_SUSPENDED"
            bump(fund)
        elif (
            (not fund["is_underwater"] or exempt)
            and fund["spending_posture"] == "SPENDING_SUSPENDED"
        ):
            fund["spending_posture"] = "NORMAL"
            bump(fund)

    # --- Step 7: exception expiry ---
    for exc in sorted(
        store.exceptions.values(), key=lambda e: (e["created_at"], e["_seq"])
    ):
        if exc["exception_status"] != "APPROVED":
            continue
        fund = store.funds.get(exc["fund_id"])
        if fund is None or fund["pool_id"] != pool["id"]:
            continue
        last_quarter = QUARTERS_PER_FISCAL_YEAR * (
            exc["fiscal_year"] - pool["inception_fiscal_year"] + 1
        )
        if q != last_quarter:
            continue
        exc["exception_status"] = "EXPIRED"
        bump(exc)
        revert_distributions_using_exception(exc)
        _exception_exit_posture(exc)

    # --- Step 8: allocation drift ---
    quarter_reports = [
        r
        for r in store.manager_reports.values()
        if r["quarter_index"] == q
        and (store.managers.get(r["manager_id"]) or {}).get("pool_id") == pool["id"]
    ]
    for alloc in sorted(
        (a for a in store.allocations.values() if a["pool_id"] == pool["id"]),
        key=lambda a: (a["created_at"], a["_seq"]),
    ):
        class_mv = sum(
            r["ending_mv_cents"]
            for r in quarter_reports
            if store.managers[r["manager_id"]]["asset_class"] == alloc["asset_class"]
        )
        if final_mv == 0:
            actual = 0
        else:
            actual = calc.rhu_pct(class_mv, final_mv)
        new_drift = (
            "BREACHED"
            if abs(actual - alloc["target_pct_bps"]) > alloc["rebalance_band_bps"]
            else "IN_BAND"
        )
        changed = False
        if actual != alloc["actual_pct_bps"]:
            alloc["actual_pct_bps"] = actual
            changed = True
        if new_drift != alloc["drift_status"]:
            alloc["drift_status"] = new_drift
            alloc["drift_acknowledged"] = False
            changed = True
        if changed:
            bump(alloc)

    # --- Step 9: epoch advance ---
    pool["current_quarter_index"] = q
    pool["current_unit_price_millicents"] = price
    pool["total_market_value_cents"] = final_mv
    bump(pool)

    valuation["valuation_status"] = "FINAL"
    valuation["finalized_by_user_id"] = user_id
    bump(valuation)


def rollback_supersede(pool, valuation):
    """Roll the pool back to the end of quarter_index - 1 after a supersede."""
    q = valuation["quarter_index"]
    pool["current_quarter_index"] = q - 1
    if q == 1:
        pool["current_unit_price_millicents"] = INCEPTION_UNIT_PRICE_MILLICENTS
        pool["total_market_value_cents"] = 0
    else:
        prior = None
        for v in store.valuations.values():
            if (
                v["pool_id"] == pool["id"]
                and v["quarter_index"] == q - 1
                and v["valuation_status"] == "FINAL"
            ):
                prior = v
                break
        if prior is not None:
            pool["current_unit_price_millicents"] = prior["final_unit_price_millicents"]
            pool["total_market_value_cents"] = prior["final_pool_market_value_cents"]
        else:
            pool["current_unit_price_millicents"] = INCEPTION_UNIT_PRICE_MILLICENTS
            pool["total_market_value_cents"] = 0

    # Restore allocation drift to pre-finalize values.
    snapshot = valuation.get("_alloc_snapshot") or {}
    for aid, snap in snapshot.items():
        alloc = store.allocations.get(aid)
        if alloc is None:
            continue
        changed = False
        for field in ("actual_pct_bps", "drift_status", "drift_acknowledged"):
            if alloc[field] != snap[field]:
                alloc[field] = snap[field]
                changed = True
        if changed:
            bump(alloc)

    # The price moved: refresh fund market values and underwater flags.
    for fund in _funds_of_pool(pool):
        refresh_fund_mv(fund, pool["current_unit_price_millicents"])
