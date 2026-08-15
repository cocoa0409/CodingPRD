"""Business logic: exposure accounting, warehouse position, allocation
waterfall, landed cost, yield variance, cupping scoring, hedge P&L,
freshness aging. All money/ratio math goes through Decimal (PRD §2.5).
"""

from datetime import timedelta
from decimal import Decimal

from clock import fmt_iso, now, now_iso, parse_iso
from db import DB
from errors import ERR_INSUFFICIENT_GREEN_INVENTORY, err
from middleware import D, floor_int, q2, q5, touch

OPEN_EXPOSURE_STATUSES = ("OPEN", "PARTIALLY_RECEIVED")


# ---------------------------------------------------------------------------
# Counterparty exposure (PRD §2.7 dual accounting basis)
# ---------------------------------------------------------------------------

def _open_contracts(counterparty_id):
    return [
        c for c in DB.contracts.values()
        if c["counterparty_id"] == counterparty_id
        and c["fulfillment_status"] in OPEN_EXPOSURE_STATUSES
    ]


def _approved_hedges(contract_id):
    return [
        h for h in DB.futures_hedges.values()
        if h["contract_id"] == contract_id and h["hedge_status"] == "APPROVED"
    ]


def current_spot_futures():
    """The most recent PriceFixEvent's futures price across ANY contract
    (system-wide mark), or None when no price-fix exists yet."""
    if not DB.price_fixes:
        return None
    latest = max(DB.price_fixes.values(), key=lambda e: e["_seq"])
    return latest["futures_price_usd_per_lb"]


def provisional_exposure(counterparty_id):
    """PROVISIONAL variant — the stored open_exposure_usd used for
    credit-limit gating and counterparty reporting.

    Per contract with fulfillment_status OPEN or PARTIALLY_RECEIVED:
    the unfixed remainder marked at (current spot + differential) — with
    the differential alone as the flat-price fallback when no price-fix
    exists anywhere yet — PLUS the already-priced notional; FIXED_OUTRIGHT
    contracts contribute their not-yet-received remainder at the outright
    price; APPROVED hedges subtract hedge_lbs * entry_price. Never
    negative; 2 dp half-up."""
    spot = current_spot_futures()
    contracts = _open_contracts(counterparty_id)
    total = Decimal(0)
    for c in contracts:
        if c["pricing_mode"] == "DIFFERENTIAL_PTBF":
            diff = D(c["differential_usd_per_lb"])
            if spot is None:
                total += D(c["unpriced_lbs"]) * diff
            else:
                total += D(c["unpriced_lbs"]) * (D(spot) + diff)
            total += D(c["priced_notional_usd"] or 0)
        else:  # FIXED_OUTRIGHT
            total += D(c["total_lbs"] - c["received_lbs_accum"]) * D(c["fixed_price_usd_per_lb"])
    for c in contracts:
        for h in _approved_hedges(c["id"]):
            total -= D(h["hedge_lbs"]) * D(h["entry_price_usd_per_lb"])
    if total < 0:
        total = Decimal(0)
    return q2(total)


def provisional_exposure_after_fix(counterparty, fixed_contract, fix_lbs, new_spot):
    """PROVISIONAL variant — credit-limit gating at price-fix time,
    evaluated as if the candidate fix were already recorded (the new fix
    becomes the most recent PriceFixEvent, so its futures level is the
    current spot that re-marks every unfixed pound).

    Per contract (OPEN / PARTIALLY_RECEIVED): the unfixed remainder marked
    at (spot + differential) PLUS the already-priced notional
    (fixed_lbs * (weighted_avg + differential)); FIXED_OUTRIGHT contracts
    contribute their not-yet-received remainder at the outright price;
    APPROVED hedges subtract hedge_lbs * entry_price. Never negative."""
    spot = D(new_spot)
    contracts = _open_contracts(counterparty["id"])
    total = Decimal(0)
    for c in contracts:
        if c["pricing_mode"] == "DIFFERENTIAL_PTBF":
            diff = D(c["differential_usd_per_lb"])
            if c["id"] == fixed_contract["id"]:
                # Post-fix view of this contract: fold the candidate fix into
                # the fixed accumulator and the weighted-average futures level.
                events = [e for e in DB.price_fixes.values()
                          if e["contract_id"] == c["id"]]
                accum_after = c["fixed_lbs_accum"] + fix_lbs
                wsum = sum(D(e["fix_lbs"]) * D(e["futures_price_usd_per_lb"]) for e in events)
                wsum += D(fix_lbs) * spot
                wavg_after = q5(wsum / D(accum_after)) if accum_after else None
                unpriced = c["total_lbs"] - accum_after
                total += D(unpriced) * (spot + diff)
                if accum_after:
                    total += D(accum_after) * (D(wavg_after) + diff)
            else:
                total += D(c["unpriced_lbs"]) * (spot + diff)
                if c["fixed_lbs_accum"]:
                    total += D(c["fixed_lbs_accum"]) * (
                        D(c["weighted_avg_fixed_futures_usd"]) + diff)
        else:  # FIXED_OUTRIGHT: not-yet-received remainder at outright price
            total += D(c["total_lbs"] - c["received_lbs_accum"]) * D(c["fixed_price_usd_per_lb"])
    for c in contracts:
        for h in _approved_hedges(c["id"]):
            total -= D(h["hedge_lbs"]) * D(h["entry_price_usd_per_lb"])
    if total < 0:
        total = Decimal(0)
    return q2(total)


def recompute_counterparty_exposure(counterparty):
    """Refresh the stored (provisional-variant) open_exposure_usd and drive
    the ACTIVE <-> SUSPENDED flip against credit_limit_usd. The
    counterparty's version bumps when the value changes or the status
    flips (PRD §2.4)."""
    new_val = provisional_exposure(counterparty["id"])
    changed = new_val != counterparty["open_exposure_usd"]
    counterparty["open_exposure_usd"] = new_val
    limit = D(counterparty["credit_limit_usd"])
    if counterparty["counterparty_status"] == "ACTIVE" and D(new_val) > limit:
        counterparty["counterparty_status"] = "SUSPENDED"
        changed = True
    elif counterparty["counterparty_status"] == "SUSPENDED" and D(new_val) <= limit:
        counterparty["counterparty_status"] = "ACTIVE"
        changed = True
    if changed:
        touch(counterparty)


# ---------------------------------------------------------------------------
# Contract computed pricing fields
# ---------------------------------------------------------------------------

def weighted_avg_fixed_futures(contract_id):
    """Pound-weighted average futures level over all PriceFixEvent rows,
    5 dp half-up; None when no fixes exist."""
    events = [e for e in DB.price_fixes.values() if e["contract_id"] == contract_id]
    total_lbs = sum(e["fix_lbs"] for e in events)
    if total_lbs == 0:
        return None
    weighted = sum(D(e["fix_lbs"]) * D(e["futures_price_usd_per_lb"]) for e in events)
    return q5(weighted / D(total_lbs))


def recompute_contract_pricing(contract):
    """Refresh weighted_avg / priced_notional / unpriced_lbs from fix state."""
    if contract["pricing_mode"] == "FIXED_OUTRIGHT":
        contract["fixed_lbs_accum"] = contract["total_lbs"]
        contract["unpriced_lbs"] = 0
        contract["weighted_avg_fixed_futures_usd"] = None
        contract["priced_notional_usd"] = q2(
            D(contract["total_lbs"]) * D(contract["fixed_price_usd_per_lb"])
        )
        return
    contract["weighted_avg_fixed_futures_usd"] = weighted_avg_fixed_futures(contract["id"])
    if contract["fixed_lbs_accum"] == 0:
        contract["priced_notional_usd"] = 0.0
    else:
        contract["priced_notional_usd"] = q2(
            D(contract["fixed_lbs_accum"])
            * (D(contract["weighted_avg_fixed_futures_usd"]) + D(contract["differential_usd_per_lb"]))
        )
    contract["unpriced_lbs"] = contract["total_lbs"] - contract["fixed_lbs_accum"]


def contract_received_accum(contract_id):
    """Sum of GreenLot.received_lbs over this contract's RECEIVED shipments."""
    received_shipment_ids = {
        s["id"] for s in DB.shipments.values()
        if s["contract_id"] == contract_id and s["transit_status"] == "RECEIVED"
    }
    return sum(
        lot["received_lbs"]
        for lot in DB.green_lots.values()
        if lot["shipment_id"] in received_shipment_ids
    )


# ---------------------------------------------------------------------------
# Green lots / warehouse position (PRD §2.6)
# ---------------------------------------------------------------------------

def lot_grade(lot):
    """A lot's coffee grade is inherited from its contract via the shipment."""
    shipment = DB.shipments.get(lot["shipment_id"])
    if shipment is None:
        return None
    contract = DB.contracts.get(shipment["contract_id"])
    if contract is None:
        return None
    return contract["coffee_grade"]


def landed_cost_at_receipt(contract):
    """Dual-basis landed cost (PRD §2.7), 5 dp half-up."""
    if contract["pricing_mode"] == "FIXED_OUTRIGHT":
        return q5(D(contract["fixed_price_usd_per_lb"]))
    if contract["pricing_status"] == "UNFIXED":
        # Provisional basis: differential alone; later fixes do not revalue.
        return q5(D(contract["differential_usd_per_lb"]))
    return q5(D(contract["weighted_avg_fixed_futures_usd"]) + D(contract["differential_usd_per_lb"]))


def recompute_position():
    """Refresh the singleton warehouse position from source-of-truth rows."""
    p = DB.position
    physical = sum(
        lot["received_lbs"]
        for lot in DB.green_lots.values()
        if lot["lot_status"] in ("RELEASED", "QUARANTINE")
    )
    committed = sum(
        a["allocated_lbs"]
        for a in DB.roast_allocations.values()
        if a["allocation_status"] == "ACTIVE"
    )
    reserved = sum(
        r["reserved_lbs"]
        for r in DB.financing_reserves.values()
        if r["reserve_status"] == "ACTIVE"
    )
    released = [lot for lot in DB.green_lots.values() if lot["lot_status"] == "RELEASED"]
    if released:
        total_mass = sum(lot["received_lbs"] for lot in released)
        weighted = sum(D(lot["received_lbs"]) * D(lot["landed_cost_usd_per_lb"]) for lot in released)
        p["weighted_avg_landed_cost_usd"] = q5(weighted / D(total_mass))
    else:
        p["weighted_avg_landed_cost_usd"] = None
    p["physical_lbs"] = physical
    p["committed_lbs"] = committed
    p["reserved_for_financing_lbs"] = reserved
    p["open_to_sell_lbs"] = physical - committed - reserved
    p["position_as_of"] = now_iso()
    p["updated_at"] = now_iso()
    p["version"] += 1


def maybe_deplete_green_lot(lot):
    """RELEASED -> DEPLETED when available_lbs hits 0 with no ACTIVE allocations."""
    if lot["lot_status"] != "RELEASED":
        return
    if lot["available_lbs"] != 0:
        return
    has_active = any(
        a["green_lot_id"] == lot["id"] and a["allocation_status"] == "ACTIVE"
        for a in DB.roast_allocations.values()
    )
    if not has_active:
        lot["lot_status"] = "DEPLETED"
        touch(lot)


# ---------------------------------------------------------------------------
# Blend allocation waterfall (calc_blend_allocation)
# ---------------------------------------------------------------------------

def recipe_components(recipe_id):
    comps = [c for c in DB.recipe_components.values() if c["recipe_id"] == recipe_id]
    # component_pct DESC, ties by earlier creation (created_at, then seq).
    comps.sort(key=lambda c: c["_seq"])
    comps.sort(key=lambda c: D(c["component_pct"]), reverse=True)
    return comps


def plan_blend_allocation(recipe, scheduled_green_lbs):
    """Compute the allocation plan without mutating anything.

    Returns a list of dicts {component, lot, take, is_substitution} in
    creation order, or raises ERR_INSUFFICIENT_GREEN_INVENTORY.
    """
    comps = recipe_components(recipe["id"])
    # Per-component targets: round half-up to integer lbs, then reconcile the
    # remainder into the largest component (first in the DESC ordering).
    targets = {}
    for comp in comps:
        targets[comp["id"]] = int(
            (D(scheduled_green_lbs) * D(comp["component_pct"])).quantize(
                Decimal("1"), rounding="ROUND_HALF_UP"
            )
        )
    if comps:
        diff = int(scheduled_green_lbs) - sum(targets.values())
        targets[comps[0]["id"]] += diff

    released_lots = [
        lot for lot in DB.green_lots.values() if lot["lot_status"] == "RELEASED"
    ]
    released_lots.sort(key=lambda l: (l["created_at"], l["_seq"]))
    avail = {lot["id"]: lot["available_lbs"] for lot in released_lots}

    plan = []
    for comp in comps:
        target = targets[comp["id"]]
        if target <= 0:
            continue
        allocated = 0
        for lot in released_lots:
            if lot_grade(lot) != comp["required_grade"]:
                continue
            take = min(avail[lot["id"]], target - allocated)
            if take > 0:
                plan.append({"component": comp, "lot": lot, "take": take,
                             "is_substitution": False})
                avail[lot["id"]] -= take
                allocated += take
            if allocated == target:
                break
        if allocated < target and comp.get("substitution_grade") is not None:
            cap = floor_int(D(target) * D(comp["substitution_max_pct"]))
            sub_allocated = 0
            for lot in released_lots:
                if lot_grade(lot) != comp["substitution_grade"]:
                    continue
                take = min(avail[lot["id"]], target - allocated, cap - sub_allocated)
                if take > 0:
                    plan.append({"component": comp, "lot": lot, "take": take,
                                 "is_substitution": True})
                    avail[lot["id"]] -= take
                    allocated += take
                    sub_allocated += take
                if allocated == target:
                    break
        if allocated < target:
            raise err(
                ERR_INSUFFICIENT_GREEN_INVENTORY,
                "Insufficient RELEASED green lot mass to satisfy all recipe components",
            )
    return plan


# ---------------------------------------------------------------------------
# Roast yield (calc_yield_variance)
# ---------------------------------------------------------------------------

def compute_yield_fields(batch, product):
    """Returns (actual_yield_loss_pct, yield_variance_flag)."""
    scheduled = D(batch["scheduled_green_lbs"])
    actual = D(batch["actual_roasted_lbs"])
    loss = q5(Decimal(1) - actual / scheduled)
    profile = DB.roast_profiles.get(product["target_roast_profile_id"])
    expected = D(profile["expected_yield_loss_pct"])
    band = D(profile["shrinkage_alert_band_pct"])
    loss_d = D(loss)
    if loss_d > expected + band:
        flag = "ABOVE_BAND"
    elif loss_d < expected - band:
        flag = "BELOW_BAND"
    else:
        flag = "WITHIN_BAND"
    return loss, flag


# ---------------------------------------------------------------------------
# Cupping (calc_cupping_final_score)
# ---------------------------------------------------------------------------

SCORE_FIELDS = (
    "score_aroma", "score_flavor", "score_aftertaste", "score_acidity",
    "score_body", "score_balance", "score_uniformity", "score_clean_cup",
    "score_sweetness", "score_overall",
)

SPECIALTY_GREEN_THRESHOLD = Decimal("80.00")
ROASTED_BATCH_THRESHOLD = Decimal("78.00")


def compute_final_score(session):
    base = sum(D(session[f]) for f in SCORE_FIELDS)
    return q2(base - D(session["defects_subtracted"]))


def verdict_for(session, final_score):
    threshold = (
        SPECIALTY_GREEN_THRESHOLD
        if session["subject_kind"] == "GREEN_LOT"
        else ROASTED_BATCH_THRESHOLD
    )
    return "PASS" if D(final_score) >= threshold else "FAIL"


# ---------------------------------------------------------------------------
# Futures hedges (calc_hedge_realized_pnl)
# ---------------------------------------------------------------------------

def hedge_realized_pnl(hedge):
    if hedge["hedge_side"] == "BUY_FUTURES":
        diff = D(hedge["exit_price_usd_per_lb"]) - D(hedge["entry_price_usd_per_lb"])
    else:  # SELL_FUTURES
        diff = D(hedge["entry_price_usd_per_lb"]) - D(hedge["exit_price_usd_per_lb"])
    return q2(diff * D(hedge["hedge_lbs"]))


# ---------------------------------------------------------------------------
# Finished goods freshness (PRD §2.11 lazy aging; calc_freshness_sellable_until)
# ---------------------------------------------------------------------------

def sellable_until_for(batch, product):
    completed = parse_iso(batch["roast_completed_at"])
    return fmt_iso(completed + timedelta(days=int(product["freshness_days"])))


def lazy_stale_finished_lot(lot):
    """FRESH -> STALE when current logical time is strictly past sellable_until."""
    if lot["lot_status"] == "FRESH" and now() > parse_iso(lot["sellable_until"]):
        lot["lot_status"] = "STALE"
        touch(lot)


# ---------------------------------------------------------------------------
# Financing
# ---------------------------------------------------------------------------

def reserve_advance(reserved_lbs, lot, line):
    """reserve_advance_usd = reserved_lbs * landed_cost * advance_rate, 2 dp."""
    return q2(D(reserved_lbs) * D(lot["landed_cost_usd_per_lb"]) * D(line["advance_rate_pct"]))


def reserve_collateral(reserved_lbs, lot):
    return q2(D(reserved_lbs) * D(lot["landed_cost_usd_per_lb"]))
