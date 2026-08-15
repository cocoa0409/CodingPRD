"""Ledger computations: accountability_balance_doses and private_lending_balance.

Per SCAFFOLD §1.3 (accountability_balance_reconciliation, private_lending_balance)
and PRD §2.7 / §3.9.

The running/provisional site balance (ProviderSite.accountability_balance_doses)
uses the provisional variant: transfers in INITIATED count as transferred-out
while OPEN excursions contribute nothing to wasted.

The frozen audit snapshot uses the final_snapshot variant: only transfers in
IN_TRANSIT or RECEIVED count; OPEN excursions contribute 0 to wasted.
"""

from decimal import Decimal, ROUND_HALF_UP

import db


def _lots_of_site(site_id):
    return [lot for lot in db.lots.values() if lot["provider_site_id"] == site_id]


def _public_lots_of_site(site_id):
    return [lot for lot in _lots_of_site(site_id) if lot["stock_type"] == "PUBLIC_VFC"]


def _site_excursions(site_id):
    """All excursions belonging to any storage unit of the site."""
    unit_ids = {u["id"] for u in db.storage_units.values() if u["provider_site_id"] == site_id}
    return [e for e in db.temperature_excursions.values() if e["storage_unit_id"] in unit_ids]


def compute_excursion_count_open(site_id):
    return sum(
        1
        for e in _site_excursions(site_id)
        if e["status"] in ("OPEN", "UNDER_REVIEW")
    )


def _public_doses_received(site_id):
    total = 0
    for receipt in db.allocation_receipts.values():
        order = db.vaccine_orders.get(receipt["vaccine_order_id"])
        if order is not None and order["provider_site_id"] == site_id:
            total += receipt["quantity_doses"]
    return total


def _public_doses_administered(site_id):
    return sum(
        1
        for d in db.dose_administrations.values()
        if d["provider_site_id"] == site_id and d["funding_source"] == "PUBLIC_VFC"
    )


def _public_doses_wasted_excursions(site_id):
    """Sum of excursion doses_written_off attributable to PUBLIC_VFC lots.

    We track the public portion of each wasted resolution explicitly on the
    excursion record (public_doses_written_off) at resolve time.
    """
    return sum(
        e.get("public_doses_written_off", 0)
        for e in _site_excursions(site_id)
        if e["status"] == "RESOLVED_WASTED"
    )


def _public_doses_wasted_expiry(site_id):
    """Pre-zero on-hand quantities of PUBLIC_VFC lots that expired at this site.

    Tracked explicitly on each lot as expired_written_off_doses when the
    expiration sweep zeroes it.
    """
    return sum(
        lot.get("expired_written_off_doses", 0)
        for lot in _public_lots_of_site(site_id)
        if lot["status"] == "EXPIRED"
    )


def _public_doses_transferred_out(site_id, include_initiated):
    total = 0
    for t in db.short_date_transfers.values():
        if t["provider_site_id"] != site_id:
            continue
        from_lot = db.lots.get(t["from_lot_id"])
        if from_lot is None or from_lot["stock_type"] != "PUBLIC_VFC":
            continue
        if t["status"] in ("IN_TRANSIT", "RECEIVED"):
            total += t["quantity_doses"]
        elif include_initiated and t["status"] == "INITIATED":
            total += t["quantity_doses"]
    return total


def recompute_accountability_balance(site_id):
    """Provisional (running) balance per PRD §2.7:
    received - administered - wasted - transferred_out.
    Provisional variant counts INITIATED transfers and ignores OPEN excursions
    (only RESOLVED_WASTED write-offs count — by construction).
    """
    site = db.provider_sites.get(site_id)
    if site is None:
        return
    received = _public_doses_received(site_id)
    administered = _public_doses_administered(site_id)
    wasted = _public_doses_wasted_excursions(site_id) + _public_doses_wasted_expiry(site_id)
    transferred_out = _public_doses_transferred_out(site_id, include_initiated=True)
    site["accountability_balance_doses"] = received - administered - wasted - transferred_out


def recompute_private_lending_balance(site_id):
    site = db.provider_sites.get(site_id)
    if site is None:
        return
    total = 0
    for bt in db.borrow_tickets.values():
        if bt["provider_site_id"] != site_id:
            continue
        if bt["status"] in ("OPEN", "PARTIALLY_REPAID") and bt["direction"] == "PUBLIC_FROM_PRIVATE":
            total += bt["borrowed_quantity"] - bt["paid_back_quantity"]
    site["private_lending_balance"] = total


def compute_audit_snapshot(site_id):
    """Final-snapshot semantics per SCAFFOLD §1.3 final_snapshot / PRD §3.9."""
    received = _public_doses_received(site_id)
    administered = _public_doses_administered(site_id)
    wasted = _public_doses_wasted_excursions(site_id) + _public_doses_wasted_expiry(site_id)
    transferred_out = _public_doses_transferred_out(site_id, include_initiated=False)
    gap = received - administered - wasted - transferred_out
    on_hand_public_total = sum(
        lot["quantity_on_hand"]
        for lot in _public_lots_of_site(site_id)
        if lot["status"] in ("AVAILABLE", "QUARANTINED")
    )
    return {
        "public_doses_received": received,
        "public_doses_administered": administered,
        "public_doses_wasted": wasted,
        "public_doses_transferred_out": transferred_out,
        "accountability_gap": gap,
        "on_hand_public_total": on_hand_public_total,
    }


def compute_wastage_rate(public_doses_wasted, public_doses_received):
    """Tiered wastage rate per SCAFFOLD §1.3 tiered_wastage_rate_reporting.

    Returns (rounded_rate_4dp, tier). Tier compares the UNROUNDED rate.
    """
    denominator = max(public_doses_received, 1)
    rate = Decimal(public_doses_wasted) / Decimal(denominator)
    if rate < Decimal("0.05"):
        tier = "GREEN"
    elif rate < Decimal("0.10"):
        tier = "AMBER"
    else:
        tier = "RED"
    rounded = rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return rounded, tier


# ---------------------------------------------------------------------------
# Expiration sweep (logical clock advance) per PRD §2.10
# ---------------------------------------------------------------------------

def run_expiration_sweep():
    """Every AVAILABLE lot whose expires_on now lies strictly in the past
    (current_date > expires_on) with quantity_on_hand > 0 transitions to EXPIRED
    and is zeroed. PUBLIC_VFC expiries recompute the site accountability balance
    on the wasted side.
    """
    current_date = db.get_logical_date()
    affected_sites = set()
    for lot in db.lots.values():
        if lot["status"] != "AVAILABLE":
            continue
        if lot["quantity_on_hand"] <= 0:
            continue
        if current_date > lot["_expires_on_date"]:
            pre_zero = lot["quantity_on_hand"]
            lot["quantity_on_hand"] = 0
            lot["status"] = "EXPIRED"
            lot["expired_written_off_doses"] = pre_zero
            lot["updated_at"] = db.now_ts()
            lot["version"] += 1
            if lot["stock_type"] == "PUBLIC_VFC":
                affected_sites.add(lot["provider_site_id"])
    for site_id in affected_sites:
        recompute_accountability_balance(site_id)
