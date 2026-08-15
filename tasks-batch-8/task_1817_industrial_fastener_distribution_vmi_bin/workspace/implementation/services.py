"""Shared business logic: posture, balance, pricing, sizing, cascades."""

import math
from fractions import Fraction

import errors
from db import store, touch, now_iso, new_id

# --- calculation constants (scaffold section 1.3) ---
QTY_TIER1_MIN = 100
QTY_TIER2_MIN = 500
TIER1_DISCOUNT_PCT = 2
TIER2_DISCOUNT_PCT = 5
CERT_FEE_CENTS = 1500

LOOKBACK_WEEKS = 4
SAFETY_FACTOR = Fraction(3, 2)  # 1.5
MAX_MULTIPLE = 3

PER_BAG_CENTS = 250
PER_UNIT_CENTS = 3
PART_SURCHARGE_PCT = 4

STATION_BUFFER_MINUTES = 15


# ---------------------------------------------------------------------------
# Derived-field reconciliation (PRD section 2.9)
# ---------------------------------------------------------------------------

def recompute_posture(agr):
    """ACTIVE <-> AT_CAPACITY auto-transition on on_hand+open vs max_qty.

    A flip is itself an auto-transition with its own version increment.
    """
    if agr["status"] not in ("ACTIVE", "AT_CAPACITY"):
        return
    total = agr["on_hand_qty"] + agr["open_order_qty"]
    new_status = "AT_CAPACITY" if total >= agr["max_qty"] else "ACTIVE"
    if new_status != agr["status"]:
        agr["status"] = new_status
        touch(agr)


def recompute_site_balance(site_id):
    """Exact integer-cent sum over the site's CONFIRMED / IN_TRANSIT orders."""
    site = store.sites.get(site_id)
    if site is None:
        return
    total = sum(
        o["total_price_cents"]
        for o in store.orders.values()
        if o["site_id"] == site_id and o["status"] in ("CONFIRMED", "IN_TRANSIT")
    )
    site["outstanding_balance_cents"] = total


# ---------------------------------------------------------------------------
# order_pricing calculation (PRD section 3.4) — fixed at creation, never
# recomputed. Evaluation order: tier selection -> qty multiplication -> cert fee.
# ---------------------------------------------------------------------------

def price_order(agr, part, ordered_qty):
    if agr["pricing_mode"] == "UNIT_PRICE":
        base = part["unit_price_cents"]
        if ordered_qty >= QTY_TIER2_MIN:
            unit = base * (100 - TIER2_DISCOUNT_PCT) // 100  # 5% off, truncating
        elif ordered_qty >= QTY_TIER1_MIN:
            unit = base * (100 - TIER1_DISCOUNT_PCT) // 100  # 2% off, truncating
        else:
            unit = base
        total = unit * ordered_qty
        if part["is_critical"]:
            total += CERT_FEE_CENTS
        return unit, total
    # COST_PER_BIN: flat per-trip fee regardless of quantity
    total = agr["flat_bin_price_cents"]
    if part["is_critical"]:
        total += CERT_FEE_CENTS
    return 0, total


# ---------------------------------------------------------------------------
# kit_packaging_cost calculation (PRD section 3.6) — per-line ceil, then sum,
# then multiply by kit_count. Order pinned.
# ---------------------------------------------------------------------------

def kit_packaging_cost(job):
    lines = []
    for pid in job["component_part_ids"]:
        part = store.parts[pid]
        raw = (
            PER_BAG_CENTS
            + job["qty_per_part"] * PER_UNIT_CENTS
            + Fraction(part["unit_price_cents"] * PART_SURCHARGE_PCT, 100)
        )
        lines.append(math.ceil(raw))
    return job["kit_count"] * sum(lines)


# ---------------------------------------------------------------------------
# bin_sizing_recommendation calculation (PRD section 3.2)
# ---------------------------------------------------------------------------

def sizing_recommendation(agr, method):
    """Returns (recommended_min, recommended_max).

    Window: the four most recent SUBMITTED stops for the agreement
    (created_at DESC selection), processed oldest-first. Each stop's usage is
    the previously recorded on-hand (i.e. the prior submitted stop's counted
    quantity, 0 when none) minus this stop's counted_qty, clamped at zero.
    """
    stops = [
        s for s in store.stops.values()
        if s["bin_agreement_id"] == agr["id"] and s["status"] == "SUBMITTED"
    ]
    stops.sort(key=lambda s: s["_seq"], reverse=True)
    window = list(reversed(stops[:LOOKBACK_WEEKS]))  # oldest-first
    usages = [max(0, s["_prev_scan_qty"] - s["counted_qty"]) for s in window]

    if method == "PROJECTED":
        weights = [2 if s["generated_order_id"] else 1 for s in window]
        denom = sum(weights)
        avg = (
            Fraction(sum(w * u for w, u in zip(weights, usages)), denom)
            if denom
            else Fraction(0)
        )
        recommended_min = math.ceil(avg * SAFETY_FACTOR)
    else:  # TRAILING (default)
        avg = Fraction(sum(usages), LOOKBACK_WEEKS)
        recommended_min = math.ceil(avg * SAFETY_FACTOR)

    return recommended_min, recommended_min * MAX_MULTIPLE


# ---------------------------------------------------------------------------
# Replenishment-order creation inside a scan submission (PRD section 3.3)
# ---------------------------------------------------------------------------

def create_replenishment_order(agr, counted_qty):
    part = store.parts[agr["part_id"]]
    ordered_qty = agr["max_qty"] - counted_qty
    unit_price, total_price = price_order(agr, part, ordered_qty)
    ts = now_iso()
    order = {
        "id": new_id(),
        "bin_agreement_id": agr["id"],
        "site_id": agr["site_id"],
        "part_id": agr["part_id"],
        "ordered_qty": ordered_qty,
        "unit_price_cents": unit_price,
        "total_price_cents": total_price,
        "delivery_mode": None,  # pinned at confirmation
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.orders[order["id"]] = order
    return order


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def obsolete_part_cascade(part):
    """PRD section 3.7: bin retirement, cross-reference deactivation."""
    has_live_substitute = any(
        x["from_part_id"] == part["id"]
        and x["is_active"]
        and store.parts.get(x["to_part_id"]) is not None
        and store.parts[x["to_part_id"]]["status"] == "ACTIVE"
        for x in store.xrefs.values()
    )
    for agr in store.agreements.values():
        if (
            agr["part_id"] == part["id"]
            and agr["status"] in ("ACTIVE", "AT_CAPACITY")
            and not has_live_substitute
        ):
            agr["status"] = "RETIRED"
            touch(agr)
    for x in store.xrefs.values():
        if x["to_part_id"] == part["id"] and x["is_active"]:
            # cross-references carry no version / updated_at
            x["is_active"] = False


def cert_expiry_cascade(cert):
    """PRD section 3.5: expire one certificate, fire the depth-2 cascade."""
    cert["status"] = "EXPIRED"
    touch(cert)
    part = store.parts.get(cert["part_id"])
    if part is None or not part["is_critical"]:
        return
    for agr in store.agreements.values():
        if (
            agr["part_id"] == cert["part_id"]
            and agr["status"] in ("ACTIVE", "AT_CAPACITY")
            and agr["compliance_flag"] != "BLOCKED"
        ):
            agr["compliance_flag"] = "BLOCKED"
            touch(agr)
    for order in store.orders.values():
        if order["part_id"] == cert["part_id"] and order["status"] == "CONFIRMED":
            order["status"] = "ON_HOLD"
            touch(order)


def has_valid_certificate(part_id):
    return any(
        c["part_id"] == part_id and c["status"] == "VALID"
        for c in store.certs.values()
    )


def certification_gate(agr, part):
    """Stage 11 gate used at confirmation (and hold release per PRD 3.5)."""
    if agr["compliance_flag"] != "CLEAR":
        raise errors.certification_blocked(
            "Agreement compliance_flag is BLOCKED"
        )
    if part["is_critical"] and not has_valid_certificate(part["id"]):
        raise errors.certification_blocked(
            "Critical part has no VALID lot certificate"
        )
