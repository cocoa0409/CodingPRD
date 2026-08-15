"""Accounting period close and reopen (PRD 3.9): AFUDC accrual, depreciation,
amortization, CIAC expiry sweep, seal — and the compensating reopen."""
from decimal import Decimal

from db import db, next_seq
from services.core import (
    touch, wo_actual_direct_cents, wo_afudc_total_cents, wo_ciac_received_to_date,
    unit_accumulated_depreciation_cents, asset_posted_amortization,
    asset_remaining_cents, new_record,
)
from util import CLOCK, now_ts, new_id, dec, rhu_dec, rhu_div, num_out, parse_dt


def _sorted(collection):
    return sorted(db[collection].values(), key=lambda r: (r["created_at"], r["_seq"]))


def _new_entry(fields):
    rec = {
        "id": new_id(),
        "created_at": now_ts(),
        "_seq": next_seq(),
    }
    rec.update(fields)
    return rec


# ---------------------------------------------------------------------------
# Step 1 — AFUDC accrual
# ---------------------------------------------------------------------------

def _composite_monthly_rate_pct(program) -> Decimal:
    w_d = dec(program["afudc_debt_weight_pct"])
    r_d = dec(program["afudc_debt_rate_pct"])
    r_e = dec(program["afudc_equity_rate_pct"])
    return (w_d * r_d + (Decimal(100) - w_d) * r_e) / Decimal(100) / Decimal(12)


def _step_afudc(period, touched_wos):
    for wo in _sorted("work_orders"):
        if wo["order_type"] != "CAPITAL":
            continue  # EXPENSE orders never accrue AFUDC
        if wo["status"] not in ("AUTHORIZED", "IN_PROGRESS", "SUSPENDED"):
            continue  # accrual stops at completion (in-service date)
        program = db["capital_programs"].get(wo["program_id"])
        if program is None or program["status"] != "OPEN":
            continue
        rate = _composite_monthly_rate_pct(program)

        # Pinned evaluation order (scaffold afudc_accrual):
        # 1. begin_cwip = CWIP at the beginning of this period = the prior
        #    period's ending position: all charges attributed to earlier
        #    periods plus all still-ACCRUED AFUDC from prior closes (AFUDC
        #    compounds across periods; this period's own accrual is never in
        #    its own base).
        prior_charges = sum(
            c["total_cents"]
            for c in db["cost_charges"].values()
            if c["work_order_id"] == wo["id"] and c["accounting_period_id"] != period["id"]
        )
        begin_cwip = prior_charges + wo_afudc_total_cents(wo["id"])
        # 2. CIAC-financed CWIP earns no AFUDC.
        net_begin = max(0, begin_cwip - wo_ciac_received_to_date(wo["id"]))
        # 3. This period's own charges (originals and reversal rows alike).
        period_charges = sum(
            c["total_cents"]
            for c in db["cost_charges"].values()
            if c["work_order_id"] == wo["id"] and c["accounting_period_id"] == period["id"]
        )
        # 4. Base convention.
        if program["afudc_method"] == "HALF_MONTH":
            base = Decimal(net_begin) + Decimal(period_charges) * Decimal("0.5")
        else:  # FULL_MONTH
            base = Decimal(net_begin) + Decimal(period_charges)
        # 5. Round half up per row; skip when the accrual rounds to zero.
        amount = rhu_dec(base * rate / Decimal(100))
        if amount == 0:
            continue
        entry = _new_entry({
            "work_order_id": wo["id"],
            "accounting_period_id": period["id"],
            "method": program["afudc_method"],
            "base_cents": rhu_dec(base),
            "rate_pct_applied": num_out(rate),
            "amount_cents": amount,
            "status": "ACCRUED",
        })
        db["afudc_entries"][entry["id"]] = entry
        touched_wos.add(wo["id"])


# ---------------------------------------------------------------------------
# Step 2 — Depreciation
# ---------------------------------------------------------------------------

def _step_depreciation(period, touched_units, touched_programs):
    for unit in _sorted("fixed_asset_units"):
        retired_here = (
            unit["status"] == "RETIRED" and unit["retirement_period_id"] == period["id"]
        )
        if unit["status"] == "IN_SERVICE":
            isp = db["accounting_periods"].get(unit["in_service_period_id"])
            if isp is None or isp["_start"] > period["_end"]:
                continue  # periods strictly before the in-service period get nothing
        elif not retired_here:
            continue  # RETIRED units receive only their retirement period's final entry

        catalog = db["unit_catalog"].get(unit["unit_catalog_id"])
        rate = dec(catalog["annual_depreciation_rate_pct"])
        monthly_full = rhu_dec(Decimal(unit["allocated_cost_cents"]) * rate / Decimal(1200))
        # Half-month factor in the in-service period and in the retirement
        # period; a unit placed in service and retired in the SAME period gets
        # a single half-month entry (handled: it is RETIRED here, one entry).
        if period["id"] == unit["in_service_period_id"] or retired_here:
            factor = Decimal("0.5")
        else:
            factor = Decimal(1)
        amount = rhu_dec(Decimal(monthly_full) * factor)

        # CIAC contra credit (GROSS_WITH_CONTRA programs only).
        contra = 0
        wo = db["work_orders"].get(unit["work_order_id"])
        program = db["capital_programs"].get(wo["program_id"]) if wo else None
        if (
            program is not None
            and program.get("ciac_method") == "GROSS_WITH_CONTRA"
            and wo.get("gross_cwip_cents")
        ):
            contra = rhu_div(amount * (wo.get("ciac_applied_cents") or 0), wo["gross_cwip_cents"])

        entry = _new_entry({
            "fixed_asset_unit_id": unit["id"],
            "accounting_period_id": period["id"],
            "amount_cents": amount,
            "ciac_contra_credit_cents": contra,
            "status": "POSTED",
        })
        db["depreciation_entries"][entry["id"]] = entry
        if retired_here:
            # Net book value written off: allocated minus accumulated
            # depreciation INCLUDING this final entry.
            unit["retirement_nbv_cents"] = (
                unit["allocated_cost_cents"] - unit_accumulated_depreciation_cents(unit["id"])
            )
        touched_units.add(unit["id"])
        if contra and program is not None:
            touched_programs.add(program["id"])


# ---------------------------------------------------------------------------
# Step 3 — Amortization
# ---------------------------------------------------------------------------

def _step_amortization(period, touched_assets):
    for asset in _sorted("regulatory_assets"):
        if asset["status"] not in ("APPROVED", "AMORTIZING"):
            continue
        monthly = rhu_div(asset["original_cents"], asset["amortization_months"])
        n = len(asset_posted_amortization(asset["id"]))  # 0-based before this entry
        remaining = asset_remaining_cents(asset)
        if n == asset["amortization_months"] - 1:
            entry_amount = remaining  # final scheduled month plugs the remainder
        else:
            entry_amount = min(monthly, remaining)
        entry = _new_entry({
            "regulatory_asset_id": asset["id"],
            "accounting_period_id": period["id"],
            "amount_cents": entry_amount,
            "status": "POSTED",
        })
        db["amortization_entries"][entry["id"]] = entry
        if remaining - entry_amount == 0:
            asset["status"] = "FULLY_AMORTIZED"
        elif asset["status"] == "APPROVED":
            asset["status"] = "AMORTIZING"
        touched_assets.add(asset["id"])


# ---------------------------------------------------------------------------
# Step 4 — CIAC sweep
# ---------------------------------------------------------------------------

def _step_ciac_sweep(touched_ciac):
    now = CLOCK.now()
    for a in _sorted("ciac_agreements"):
        if a["status"] == "PLEDGED" and parse_dt(a["pledge_expiry_at"]) < now:
            a["status"] = "EXPIRED"
            touched_ciac.add(a["id"])


# ---------------------------------------------------------------------------
# Close / reopen drivers
# ---------------------------------------------------------------------------

def close_period(period):
    """The five-step ops-run checkpoint, atomic within the request."""
    touched_wos, touched_units, touched_assets = set(), set(), set()
    touched_programs, touched_ciac = set(), set()

    _step_afudc(period, touched_wos)
    _step_depreciation(period, touched_units, touched_programs)
    _step_amortization(period, touched_assets)
    _step_ciac_sweep(touched_ciac)

    # Step 5 — seal.
    period["status"] = "CLOSED"
    period["closed_at"] = CLOCK.now_iso()
    touch(period)

    for wid in touched_wos:
        touch(db["work_orders"][wid])
    for uid in touched_units:
        touch(db["fixed_asset_units"][uid])
    for aid in touched_assets:
        touch(db["regulatory_assets"][aid])
    for pid in touched_programs:
        touch(db["capital_programs"][pid])
    for cid in touched_ciac:
        touch(db["ciac_agreements"][cid])
    return period


def reopen_period(period):
    """Compensating mirror: reverse every entry this period's close posted and
    still ACCRUED/POSTED; derived balances recompute without them."""
    touched_wos, touched_units, touched_assets, touched_programs = set(), set(), set(), set()

    for e in _sorted("afudc_entries"):
        if e["accounting_period_id"] == period["id"] and e["status"] == "ACCRUED":
            e["status"] = "REVERSED"
            touched_wos.add(e["work_order_id"])

    for e in _sorted("depreciation_entries"):
        if e["accounting_period_id"] == period["id"] and e["status"] == "POSTED":
            e["status"] = "REVERSED"
            unit = db["fixed_asset_units"].get(e["fixed_asset_unit_id"])
            if unit is not None:
                if unit["retirement_period_id"] == period["id"] and unit["retirement_nbv_cents"] is not None:
                    unit["retirement_nbv_cents"] = None
                touched_units.add(unit["id"])
                wo = db["work_orders"].get(unit["work_order_id"])
                if wo is not None:
                    touched_programs.add(wo["program_id"])

    for e in _sorted("amortization_entries"):
        if e["accounting_period_id"] == period["id"] and e["status"] == "POSTED":
            e["status"] = "REVERSED"
            touched_assets.add(e["regulatory_asset_id"])

    # Regulatory-asset status follows the restored balance.
    for aid in touched_assets:
        asset = db["regulatory_assets"][aid]
        remaining = asset_remaining_cents(asset)
        if remaining == asset["original_cents"]:
            asset["status"] = "APPROVED"
        elif remaining == 0:
            asset["status"] = "FULLY_AMORTIZED"
        else:
            asset["status"] = "AMORTIZING"

    period["status"] = "REOPENED"
    touch(period)

    for wid in touched_wos:
        touch(db["work_orders"][wid])
    for uid in touched_units:
        touch(db["fixed_asset_units"][uid])
    for aid in touched_assets:
        touch(db["regulatory_assets"][aid])
    for pid in touched_programs:
        if pid in db["capital_programs"]:
            touch(db["capital_programs"][pid])
    return period
