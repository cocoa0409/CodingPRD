"""Derived-field recompute chains (PRD section 2.8) and reserve-ledger helpers."""

import calc
from store import ordered, stamp_ledger, store, touch, touch_time_only


# ---------------------------------------------------------------------------
# Child collections
# ---------------------------------------------------------------------------
def engagement_tiers(engagement_id):
    return ordered([t for t in store.tiers.values() if t["engagement_id"] == engagement_id])


def engagement_riders(engagement_id):
    return ordered([r for r in store.riders.values() if r["engagement_id"] == engagement_id])


def engagement_calls(engagement_id):
    return ordered([c for c in store.calls.values() if c["engagement_id"] == engagement_id])


def engagement_programs(engagement_id):
    return ordered([p for p in store.programs.values() if p["engagement_id"] == engagement_id])


def engagement_negotiations(engagement_id):
    return ordered([n for n in store.negotiations.values() if n["engagement_id"] == engagement_id])


def engagement_settlements(engagement_id):
    return ordered([s for s in store.settlements.values() if s["engagement_id"] == engagement_id])


def rider_lines(tech_rider_id):
    return ordered([l for l in store.lines.values() if l["tech_rider_id"] == tech_rider_id])


def tier_sales(price_tier_id):
    return ordered([s for s in store.sales.values() if s["price_tier_id"] == price_tier_id])


def engagement_sales(engagement_id):
    tier_ids = set(t["id"] for t in engagement_tiers(engagement_id))
    return ordered([s for s in store.sales.values() if s["price_tier_id"] in tier_ids])


def engagement_lines(engagement_id):
    rider_ids = set(r["id"] for r in engagement_riders(engagement_id))
    return ordered([l for l in store.lines.values() if l["tech_rider_id"] in rider_ids])


# ---------------------------------------------------------------------------
# Mutation helper: bump version only when a value actually changes
# ---------------------------------------------------------------------------
def apply_changes(rec, changes):
    changed = False
    for key, value in changes.items():
        if rec.get(key) != value:
            rec[key] = value
            changed = True
    if changed:
        touch(rec)
    return changed


# ---------------------------------------------------------------------------
# Recompute chains
# ---------------------------------------------------------------------------
LABOR_ESTIMATE_STATES = ("ESTIMATED", "WORKED", "RECONCILED")


def recompute_labor_estimate(engagement):
    total = sum(
        c["estimated_cost_cents"]
        for c in engagement_calls(engagement["id"])
        if c["status"] in LABOR_ESTIMATE_STATES
    )
    if engagement["labor_estimate_total_cents"] != total:
        engagement["labor_estimate_total_cents"] = total
        touch_time_only(engagement)
    return total


def recompute_rider_equipment(rider):
    total = sum(
        l["line_cost_cents"] for l in rider_lines(rider["id"]) if l["status"] == "RESERVED"
    )
    apply_changes(rider, {"additional_equipment_cost_cents": total})
    return total


def recompute_engagement_equipment(engagement):
    total = sum(
        l["line_cost_cents"]
        for l in engagement_lines(engagement["id"])
        if l["status"] == "RESERVED"
    )
    if engagement["additional_equipment_cost_cents"] != total:
        engagement["additional_equipment_cost_cents"] = total
        touch_time_only(engagement)
    return total


def recompute_item_reserved(item):
    total = sum(
        l["qty"]
        for l in store.lines.values()
        if l["status"] == "RESERVED" and l["equipment_item_id"] == item["id"]
    )
    apply_changes(item, {"reserved_qty": total})
    return total


def recompute_tier_counters(tier):
    sold = [s for s in tier_sales(tier["id"]) if s["status"] == "SOLD"]
    sold_qty = sum(s["qty"] for s in sold)
    gross = sum(s["gross_cents"] for s in sold)
    apply_changes(
        tier,
        {
            "sold_qty": sold_qty,
            "gross_cents": gross,
            "available_qty": tier["seats_allocated"] - sold_qty - tier["subscription_held_qty"],
        },
    )


def recompute_realized_gross(engagement):
    tiers = engagement_tiers(engagement["id"])
    tier_ids = set(t["id"] for t in tiers)
    total = 0
    for sale in ordered([s for s in store.sales.values() if s["price_tier_id"] in tier_ids]):
        if sale["status"] == "SOLD":
            total += sale["gross_cents"]
    total += sum(t["subscription_revenue_cents"] for t in tiers)
    if engagement["realized_gross_cents"] != total:
        engagement["realized_gross_cents"] = total
        touch_time_only(engagement)
    return total


def recompute_deposit(engagement):
    """Re-derive deposit_required_cents; a no-op for a presented engagement."""
    if engagement["engagement_type"] != "RENTAL":
        return engagement["deposit_required_cents"]
    client = store.clients.get(engagement["rental_client_id"])
    if client is None:
        return engagement["deposit_required_cents"]
    value = calc.deposit_requirement(engagement, client)
    if engagement["deposit_required_cents"] != value:
        engagement["deposit_required_cents"] = value
        touch_time_only(engagement)
    return value


# ---------------------------------------------------------------------------
# Projection (PRD section 3.5)
# ---------------------------------------------------------------------------
def fee_basis_cents(engagement):
    rounds = engagement_negotiations(engagement["id"])
    if any(r["status"] == "ACCEPTED" for r in rounds):
        return engagement["negotiated_fee_cents"]
    open_rounds = [r for r in rounds if r["status"] in ("OFFERED", "COUNTERED")]
    if open_rounds:
        best = max(open_rounds, key=lambda r: r["round_index"])
        return best["offered_fee_cents"]
    return 0


def projected_gross_cents(engagement):
    tiers = [t for t in engagement_tiers(engagement["id"]) if t["status"] == "ACTIVE"]
    if engagement["engagement_type"] == "PRESENTED":
        artist = store.artists.get(engagement["artist_id"])
        sell_through = artist["historical_sell_through_pct"] if artist else 0
    else:
        sell_through = 0
    return calc.projected_gross(tiers, sell_through)


def recompute_projection(engagement):
    """Write both projected_gross_cents and projected_margin_cents."""
    gross = projected_gross_cents(engagement)
    basis = fee_basis_cents(engagement)
    margin = gross - calc.projected_costs(basis, engagement)
    engagement["projected_gross_cents"] = gross
    engagement["projected_margin_cents"] = margin
    return gross, margin


def recompute_projected_margin_only(engagement):
    """Fee acceptance recomputes the margin against the stored projected gross."""
    basis = fee_basis_cents(engagement)
    margin = engagement["projected_gross_cents"] - calc.projected_costs(basis, engagement)
    engagement["projected_margin_cents"] = margin
    return margin


# ---------------------------------------------------------------------------
# Reserve ledger (PRD section 2.11)
# ---------------------------------------------------------------------------
def ledger_entries():
    return ordered(list(store.ledger.values()))


def reserve_balance():
    entries = ledger_entries()
    if not entries:
        return 0
    return entries[-1]["balance_after_cents"]


def append_ledger(entry_type, amount_cents, memo, engagement_id=None):
    entry = {
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "engagement_id": engagement_id,
        "memo": memo,
        "balance_after_cents": reserve_balance() + amount_cents,
    }
    stamp_ledger(entry)
    store.ledger[entry["id"]] = entry
    return entry
