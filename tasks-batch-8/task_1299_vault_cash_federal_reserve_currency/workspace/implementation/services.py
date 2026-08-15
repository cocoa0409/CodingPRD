"""Business-logic services: ledger appends, site derivation, posture, recon cascade.

Everything here is shared by the route modules. The golden rule from PRD 2.10:
on-hand balances mutate ONLY through ledger-driven recompute; every ledger append
re-derives site totals + posture and refreshes matching OPEN/COUNTED recons.
"""
from datetime import timedelta
from decimal import Decimal

from db import DB, clock_dt, clock_date_str, clock_iso_ms, new_id
from util import round_half_up_cents, created_ts_key

# ---- calculation constants (scaffold Table 3) ----
STRAP_NOTES = 100
FEE_NUM, FEE_DEN = 1, 160
ATM_LOAD_STRAP_CENTS = 200000
MIN_RESIDUAL_CENTS = 100000
RESIDUAL_PCT_BPS = 1500
ELEVATED_NUM, ELEVATED_DEN = 9, 10
REPORT_OVERDUE_DAYS = 5
SEIZED_FREEZE_DAYS = 10
SHRINK_TOLERANCE_CENTS = 500
RECON_TOLERANCE_CENTS = 1000

DENOMINATIONS = {100, 200, 500, 1000, 2000, 5000, 10000}


# ============================================================================
# Common fields / serialization helpers
# ============================================================================

def stamp_new(record):
    ts = clock_iso_ms()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = created_ts_key()
    return record


def touch(record):
    record["updated_at"] = clock_iso_ms()
    record["version"] = record.get("version", 1) + 1
    return record


def public(record):
    """Strip internal keys (underscore-prefixed) for serialization."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ============================================================================
# Ledger + site derivation cascade
# ============================================================================

def ledger_entries_for(site_id, business_date=None):
    rows = [
        e
        for e in DB["cash_ledger_entries"].values()
        if e["site_id"] == site_id and (business_date is None or e["business_date"] == business_date)
    ]
    return rows


def append_ledger(site_id, business_date, entry_type, signed_amount_cents,
                  bucket="FIT", note="", touch_site=True):
    """Append a CashLedgerEntry, then run the site cascade (PRD 2.10).

    Returns the entry. Cascade: site totals re-derive -> posture re-derive ->
    matching OPEN/COUNTED recon refresh (final_expected, variance, status flips).
    touch_site=False is used only for the OPENING_BALANCE posts made inside the
    site-creation request, so the created site still reports version 1.
    """
    entry = {
        "id": new_id(),
        "site_id": site_id,
        "business_date": business_date,
        "entry_type": entry_type,
        "signed_amount_cents": signed_amount_cents,
        "bucket": bucket,
        "note": note,
        "created_at": clock_iso_ms(),
        "_seq": created_ts_key(),
    }
    DB["cash_ledger_entries"][entry["id"]] = entry

    site = DB["vault_sites"].get(site_id)
    if site is not None:
        recompute_site_from_ledger(site)
        refresh_site_recons(site)
        derive_site_posture(site)
        if touch_site:
            touch(site)
    return entry


def recompute_site_from_ledger(site):
    """on_hand fit/unfit are recomputed by replaying the site's ledger."""
    fit = 0
    unfit = 0
    for e in DB["cash_ledger_entries"].values():
        if e["site_id"] != site["id"]:
            continue
        if e["bucket"] == "FIT":
            fit += e["signed_amount_cents"]
        else:
            unfit += e["signed_amount_cents"]
    site["on_hand_fit_cents"] = fit
    site["on_hand_unfit_cents"] = unfit
    derive_site_exposure(site)


def derive_site_exposure(site):
    """Recompute derived exposure/total fields from current state (no ledger replay).

    reserved_out / in_transit_inbound / pending_inbound are maintained
    incrementally by callers; this recomputes the purely derived aggregates.
    """
    site["on_hand_total_cents"] = (
        site.get("on_hand_fit_cents", 0) + site.get("on_hand_unfit_cents", 0)
    )
    committed = (
        site["on_hand_total_cents"]
        + site.get("in_transit_inbound_cents", 0)
        + site.get("pending_inbound_order_cents", 0)
    )
    site["insurance_headroom_cents"] = site["insurance_coverage_cents"] - committed


def site_mutation(site, touch_site=True):
    """After reserved_out / in_transit / pending_inbound change outside the ledger."""
    derive_site_exposure(site)
    refresh_site_recons(site)
    derive_site_posture(site)
    if touch_site:
        touch(site)


def derive_site_posture(site):
    """PRD 2.9 / calculations.vault_posture_derivation — integer cross-mult only."""
    total = site.get("on_hand_total_cents", 0)
    limit = site["vault_limit_cents"]
    now = clock_dt()

    frozen = (
        total >= limit
        or site.get("insurance_headroom_cents", 0) <= 0
        or _has_seized_older_than(site["id"], now, SEIZED_FREEZE_DAYS)
    )
    if frozen:
        site["posture"] = "FROZEN"
        return

    elevated = (
        total * ELEVATED_DEN >= limit * ELEVATED_NUM
        or _has_seized_older_than(site["id"], now, REPORT_OVERDUE_DAYS)
        or any(
            r["site_id"] == site["id"] and r["status"] == "ESCALATED"
            for r in DB["reconciliations"].values()
        )
    )
    site["posture"] = "ELEVATED" if elevated else "NORMAL"


def _has_seized_older_than(site_id, now, days):
    for case in DB["counterfeit_cases"].values():
        if case["site_id"] != site_id or case["status"] != "SEIZED":
            continue
        seized_at = case.get("seized_at")
        if seized_at is None:
            continue
        from util import parse_dt

        if parse_dt(seized_at) + timedelta(days=days) < now:
            return True
    return False


def refresh_site_recons(site):
    """Refresh OPEN/COUNTED (+BALANCED/VARIANCE_PENDING) recons of the site.

    Per PRD 3.8 the sweep refreshes final_expected/variance and flips status
    between BALANCED and VARIANCE_PENDING for recons that have been counted
    but not escalated/approved/locked.
    """
    for recon in DB["reconciliations"].values():
        if recon["site_id"] != site["id"]:
            continue
        if recon["status"] not in ("OPEN", "COUNTED", "BALANCED", "VARIANCE_PENDING"):
            continue
        refresh_recon_final(recon)


def refresh_recon_final(recon):
    total = recon["opening_balance_cents"]
    for e in ledger_entries_for(recon["site_id"], recon["business_date"]):
        total += e["signed_amount_cents"]
    recon["final_expected_cents"] = total
    if recon.get("counted_on_hand_cents") is not None:
        recon["variance_cents"] = recon["counted_on_hand_cents"] - total
        if recon["status"] in ("COUNTED", "BALANCED", "VARIANCE_PENDING"):
            if abs(recon["variance_cents"]) <= RECON_TOLERANCE_CENTS:
                recon["status"] = "BALANCED"
            else:
                recon["status"] = "VARIANCE_PENDING"
            touch(recon)


def ledger_sum_for_recon_at(recon_site_id, business_date, opened_seq):
    """Provisional snapshot: entries created at or before the recon open (seq order)."""
    total = 0
    for e in ledger_entries_for(recon_site_id, business_date):
        if e["_seq"] <= opened_seq:
            total += e["signed_amount_cents"]
    return total


# ============================================================================
# Fed order totals (calculations.fed_order_face_total / fed_service_fee)
# ============================================================================

def recompute_order_totals(order):
    lines = DB["denomination_lines"].get(order["id"], [])
    face = sum(l["line_cents"] for l in lines)
    # PINNED: per-line round-half-up, then sum (never sum-then-round).
    fee = sum(
        round_half_up_cents(Decimal(l["line_cents"]) * FEE_NUM / FEE_DEN) for l in lines
    )
    order["face_total_cents"] = face
    order["fee_total_cents"] = fee
    order["grand_total_cents"] = face + fee


def effective_basis(order):
    basis = order.get("settled_basis_cents")
    return basis if basis is not None else order["face_total_cents"]


# ============================================================================
# ATM helpers
# ============================================================================

def derive_atm_posture(atm):
    balance = atm.get("current_balance_cents", 0)
    capacity = atm["cash_capacity_cents"]
    if balance * 20 < capacity:
        atm["cash_posture"] = "CRITICAL"
    elif balance * 5 < capacity:
        atm["cash_posture"] = "LOW"
    else:
        atm["cash_posture"] = "NORMAL"


def seasonal_window_for(site_id, forecast_date):
    """Return the site's SeasonalWindow covering forecast_date (inclusive), else None."""
    from util import parse_ymd

    target = parse_ymd(forecast_date)
    for w in DB["seasonal_windows"].values():
        if w["site_id"] != site_id:
            continue
        if parse_ymd(w["start_date"]) <= target <= parse_ymd(w["end_date"]):
            return w
    return None
