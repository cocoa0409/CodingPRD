"""Pricing & efficiency calculations (PRD 2.7, 3.5, 3.6, 3.7; SCAFFOLD 1.3).

All money is whole integer cents. Rounding is round-half-up (PRD 2.7). Hours
carry 3 decimals; efficiency carries 1 decimal (round half up). Rounding order
is pinned: round each line first, then sum; tax rounded once on the subtotal
(PRD 2.7, 3.6).
"""
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import ApiError


def round_half_up(value):
    """Round a Decimal/number to the nearest whole integer, half up -> int cents."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    """Round to 1 decimal place, half up -> float."""
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def round_hours(value):
    """Hours carried to three decimal places (PRD 2.7)."""
    return float(Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- #
# labor_charge (PRD 3.5)
# --------------------------------------------------------------------------- #
def labor_charge_cents(line):
    """Compute a labor line's charge_cents.

    effective_rate = line.rate_cents if set else labor_operation.default_rate_cents.
    warranty -> 0. FLAT_RATE -> book_hours * rate. T&M -> actual_hours * rate.
    Rounded half up to whole cents.
    """
    if line.get("is_warranty"):
        return 0
    if line.get("rate_cents") is not None:
        effective_rate = line["rate_cents"]
    else:
        op = db.labor_operations[line["labor_operation_id"]]
        effective_rate = op["default_rate_cents"]
    if line["billing_method"] == "FLAT_RATE":
        return round_half_up(Decimal(str(line["book_hours"])) * Decimal(effective_rate))
    else:  # TIME_AND_MATERIALS
        return round_half_up(Decimal(str(line["actual_hours"])) * Decimal(effective_rate))


# --------------------------------------------------------------------------- #
# parts_markup (PRD 3.5)
# --------------------------------------------------------------------------- #
def _sorted_tiers():
    return sorted(db.markup_tiers.values(), key=lambda t: t["tier_index"])


def parts_extended_charge_cents(quantity, unit_cost_cents, markup_mode, is_warranty):
    """Compute extended_charge_cents for a part line / recommended-job estimate.

    Tier selection driven by per-unit unit_cost_cents. warranty -> 0.
    FLAT_BRACKET: whole unit cost marked up at the single containing band.
    MARGINAL: unit cost sliced across bands, each slice marked up per band,
              rounded half up per slice.
    Raises ERR_MARKUP_TIER_MISSING if the matrix does not cover the cost.
    Final = per-unit sell price * quantity.
    """
    if is_warranty:
        return 0
    c = unit_cost_cents
    tiers = _sorted_tiers()

    if markup_mode == "FLAT_BRACKET":
        chosen = None
        for t in tiers:
            lo = t["lower_bound_cents"]
            hi = t["upper_bound_cents"]
            if lo <= c and (hi is None or c < hi):
                chosen = t
                break
        if chosen is None:
            raise ApiError("ERR_MARKUP_TIER_MISSING",
                           "No markup tier band contains the part's unit cost.")
        unit_sell = round_half_up(
            Decimal(c) * (Decimal(1) + Decimal(str(chosen["markup_pct"])))
        )
    else:  # MARGINAL
        # Slice [0, c) across the bands; each positive slice rounded per slice.
        unit_sell = 0
        for t in tiers:
            band_lo = t["lower_bound_cents"]
            band_hi = t["upper_bound_cents"]
            upper = c if band_hi is None else min(c, band_hi)
            slice_amt = max(0, upper - band_lo)
            if slice_amt > 0:
                unit_sell += round_half_up(
                    Decimal(slice_amt) * (Decimal(1) + Decimal(str(t["markup_pct"])))
                )
        # The tiers must collectively cover [0, c). Verify coverage.
        if not _covers_interval(tiers, c):
            raise ApiError("ERR_MARKUP_TIER_MISSING",
                           "Markup tiers do not cover the part's unit cost interval.")

    return unit_sell * quantity


def _covers_interval(tiers, c):
    """True iff the union of tier bands covers [0, c).

    Bands are [lower_bound_cents, upper_bound_cents) ascending by tier_index;
    a null upper bound is +inf. Coverage requires contiguous coverage from 0
    up to c with no gap.
    """
    if c <= 0:
        # [0, 0) is empty -> trivially covered. Need a tier starting at 0 so the
        # cost point 0 maps to a band; treat c==0 as covered when a tier with
        # lower_bound_cents == 0 exists, else not.
        for t in tiers:
            if t["lower_bound_cents"] == 0:
                return True
        return False
    covered_upto = 0
    for t in tiers:
        lo = t["lower_bound_cents"]
        hi = t["upper_bound_cents"]
        if lo > covered_upto:
            # gap before this band
            break
        band_hi = float("inf") if hi is None else hi
        if band_hi > covered_upto:
            covered_upto = band_hi
        if covered_upto >= c:
            return True
    return covered_upto >= c


# --------------------------------------------------------------------------- #
# repair_order_total (PRD 3.6)
# --------------------------------------------------------------------------- #
def recompute_repair_order_total(ro):
    """Recompute an RO's computed totals and bump version (cascade, PRD 2.8).

    labor_total, parts_total, tax, approved_work_value are pure functions of the
    current line/job states, computed round-per-line-then-sum; tax rounded once
    on the taxable subtotal; grand total is plain addition (PRD 2.7, 3.6).

    core_deposit_total_cents is a CONSERVED quantity (SCAFFOLD entity note): it
    rises on core creation and falls on return, but a FORFEIT leaves it
    unchanged — "forfeited deposits remain billed" (PRD 3.12). It is therefore
    maintained incrementally (see services._create_core_charge / route return)
    and is NOT overwritten here; the from-scratch "sum of CHARGED" in PRD 3.6 is
    the equivalent only while no forfeit has occurred.

    Each recompute is a server cascade mutation, so the RO's updated_at/version
    are bumped (PRD 2.8/2.9 — "adding a line ... advances that version").
    """
    labor_lines = [l for l in db.labor_lines.values() if l["repair_order_id"] == ro["id"]]
    part_lines = [p for p in db.part_lines.values()
                  if p["repair_order_id"] == ro["id"] and p["status"] != "RETURNED"]
    rec_jobs = [r for r in db.recommended_jobs.values()
                if r["repair_order_id"] == ro["id"] and r["status"] == "APPROVED"]

    labor_total = sum(l["charge_cents"] for l in labor_lines)
    parts_total = sum(p["extended_charge_cents"] for p in part_lines)
    core_total = ro["core_deposit_total_cents"]   # conserved; maintained elsewhere
    taxable_subtotal = labor_total + parts_total   # core deposits NOT taxable
    tax = round_half_up(Decimal(taxable_subtotal) * Decimal(str(ro["tax_rate"])))
    grand_total = labor_total + parts_total + core_total + tax
    approved_value = sum(r["estimated_value_cents"] for r in rec_jobs)

    ro["labor_total_cents"] = labor_total
    ro["parts_total_cents"] = parts_total
    ro["tax_cents"] = tax
    ro["grand_total_cents"] = grand_total
    ro["approved_work_value_cents"] = approved_value
    db.touch(ro)


# --------------------------------------------------------------------------- #
# technician_efficiency (PRD 3.7)
# --------------------------------------------------------------------------- #
def recompute_efficiency(tech):
    """Recompute efficiency_pct from banked hours.

    efficiency_pct = 100 * banked_flat_hours / banked_actual_hours, 1 dp half up.
    Boundary: banked_actual_hours == 0 -> null (no division by zero).
    """
    actual = tech["banked_actual_hours"]
    if actual == 0:
        tech["efficiency_pct"] = None
    else:
        tech["efficiency_pct"] = round_half_up_1dp(
            Decimal(100) * Decimal(str(tech["banked_flat_hours"])) / Decimal(str(actual))
        )
