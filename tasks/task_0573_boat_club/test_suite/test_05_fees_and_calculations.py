"""Fee arithmetic: fuel, damage, late-return, cleaning fees, plus the dual-variant
dues-invoice and provisional/final fuel calculations and per-line tax rounding.

Translates queue B (Corner) `calculations` instances and queue A (Difficulty)
instances for dual_variant_calc, combinatorial_formula, and boundary_precision.
"""
import test_helpers as th
from test_helpers import validate_success


# --------------------------------------------------------------------------- #
# Setup helpers
# --------------------------------------------------------------------------- #
def _trip_checked_out(tier="SAIL", boats=("PONTOON",), fuel_at_checkout=90,
                      start="2026-05-05T10:00:00Z", end="2026-05-05T12:00:00Z"):
    ctx = th.setup_active_basic_member(tier, boats=boats)
    m = ctx["member_id"]
    r = th.create_confirmed_reservation(m, ctx["dock_id"], boats[0], start, end)
    th.set_clock(start)
    data = th.checkout_reservation(m, r["id"], fuel_at_checkout)
    return ctx, r["id"], data


def _dv_dues_issued():
    """CRUISE member with one 10000 DAMAGE fee ASSESSED before issue; invoice issued."""
    ctx = th.setup_active_basic_member("CRUISE", boats=("PONTOON", "PONTOON"))
    m, b1 = ctx["member_id"], ctx["boat_ids"][0]
    r = th.request_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    th.assessed_damage_fee(r["id"], b1, "MINOR", 10000)  # dr1: 10000 DAMAGE fee, assessed before issue
    th.set_clock("2026-05-01T01:00:00Z")  # advance clock so the fee's assessed_at is strictly before issue
    mv = th.get_member_version(m)
    inv = th.issue_dues_invoice(m, "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", mv)
    return ctx, r, inv


def _cf_dues_issued():
    """CRUISE member with two 3334 DAMAGE fees ASSESSED before issue; invoice issued."""
    ctx = th.setup_active_basic_member("CRUISE", boats=("PONTOON", "PONTOON"))
    m, b1, b2 = ctx["member_id"], ctx["boat_ids"][0], ctx["boat_ids"][1]
    r = th.request_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    th.assessed_damage_fee(r["id"], b1, "MINOR", 3334)
    th.assessed_damage_fee(r["id"], b2, "MINOR", 3334)
    th.set_clock("2026-05-01T01:00:00Z")  # advance clock so both fees' assessed_at are strictly before issue
    mv = th.get_member_version(m)
    inv = th.issue_dues_invoice(m, "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", mv)
    return inv


# --------------------------------------------------------------------------- #
# calculations (queue B)
# --------------------------------------------------------------------------- #
def test_fuel_fee_not_charged_at_floor(api):
    """PRD §3.6: "A fuel fee is charged when `fuel_at_return` comes back below the
    25-percent fuel floor: the fee is 100 cents for every percentage point of the drop
    from `fuel_at_checkout` down to `fuel_at_return`; if the boat returns at or above
    the floor, there is no fuel fee."

    Design: Corner/calculations/fuel_fee_not_charged_when_return_at_or_above_floor
    """
    ctx, rid, _ = _trip_checked_out(fuel_at_checkout=90)
    m = ctx["member_id"]
    th.set_clock("2026-05-05T12:00:00Z")
    th.return_reservation(m, rid, 25)  # returned exactly at the 25% floor
    assert th.find_fees(reservation_id=rid, fee_type="FUEL") == [], "no fuel fee at the floor"


def test_damage_fee_severe_surcharge_lifts_cap(api):
    """PRD §3.6: "The damage fee is the smaller of the reported `repair_cost_cents` and
    a tier-dependent ceiling: that ceiling is the member's tier deductible — 50,000
    cents for `CRUISE`, 30,000 cents for `SAIL`, 10,000 cents for `UNLIMITED` — plus,
    only when the severity is `SEVERE`, an additional 20,000-cent surcharge."

    Design: Corner/calculations/damage_fee_severe_surcharge_lifts_cap
    """
    ctx = th.setup_active_basic_member("SAIL")
    m, b1 = ctx["member_id"], ctx["boat_ids"][0]
    r = th.request_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    dr = th.assessed_damage_fee(r["id"], b1, "SEVERE", 45000)  # min(45000, 30000+20000) = 45000
    assert dr["assessed_fee_cents"] == 45000


def test_cleaning_fee_charged_when_soiled(api):
    """PRD §3.6: "A cleaning fee is a flat 4,000 cents, charged only when the returned
    `cleaning_state` is `SOILED`."

    Design: Corner/calculations/cleaning_fee_charged_when_soiled
    """
    ctx, rid, _ = _trip_checked_out(fuel_at_checkout=90)
    m = ctx["member_id"]
    th.set_clock("2026-05-05T12:00:00Z")
    th.return_reservation(m, rid, 80, cleaning_state="SOILED")  # fuel above floor, on time
    fees = th.find_fees(reservation_id=rid, fee_type="CLEANING")
    assert len(fees) == 1
    assert fees[0]["amount_cents"] == 4000


# --------------------------------------------------------------------------- #
# dual_variant_calc (queue A) — dues estimated vs final
# --------------------------------------------------------------------------- #
def test_dues_estimated_total_pinned_at_issue(api):
    """PRD §3.8: "The estimated total is evaluated as of `issued_at`, so it rolls only
    the fees already assessed at issue and is stored in `estimated_total_cents`."
    PRD §3.8: "multiplying that fee's `amount_cents` by one plus the 8.5-percent tax
    rate, rounding that single line to whole cents with the round-half-up rule".

    Design: Difficulty/dual_variant_calc/dv_dues_estimated_vs_final
    """
    ctx, r, inv = _dv_dues_issued()
    fresh = th.get_dues_invoice(inv["id"])
    # base 15000 + round_half_up(10000 * 1.085)=10850 -> 25850
    assert fresh["estimated_total_cents"] == 25850


def test_dues_final_total_diverges_from_estimate(api):
    """PRD §3.8: "Paying recomputes `fees_rolled_cents` chronologically as of `paid_at`
    — capturing every fee assessed up to payment, including any assessed after the
    invoice was issued — pins that result into `final_total_cents`".
    PRD §3.8: "The final total diverges from the estimate precisely when a fee is
    assessed in the gap between issue and payment."

    Design: Difficulty/dual_variant_calc/dv_dues_estimated_vs_final
    """
    ctx, r, inv = _dv_dues_issued()
    m, b2 = ctx["member_id"], ctx["boat_ids"][1]
    th.assessed_damage_fee(r["id"], b2, "MINOR", 10000)  # second 10000 fee, after issue
    th.set_clock("2026-05-01T02:00:00Z")  # advance clock so the post-issue fee's assessed_at is strictly before payment
    th.pay_dues_invoice(m, inv["id"])
    fresh = th.get_dues_invoice(inv["id"])
    # 15000 + 10850 + 10850 = 36700
    assert fresh["final_total_cents"] == 36700
    assert fresh["estimated_total_cents"] == 25850
    assert fresh["estimated_total_cents"] != fresh["final_total_cents"]


# --------------------------------------------------------------------------- #
# dual_variant_calc (queue A) — fuel provisional vs final
# --------------------------------------------------------------------------- #
def test_provisional_fuel_fee_projects_to_floor(api):
    """PRD §3.3: "if `fuel_at_checkout` is above the 25-percent fuel floor, the
    provisional fee is 100 cents for every percentage point between `fuel_at_checkout`
    and 25; if `fuel_at_checkout` is at or below that floor, the provisional fee is zero."

    Design: Difficulty/dual_variant_calc/dv_fuel_provisional_vs_final
    """
    ctx, rid, checkout_data = _trip_checked_out(fuel_at_checkout=90)
    # 100 * (90 - 25) = 6500
    assert checkout_data["provisional_fuel_fee_cents"] == 6500


def test_final_fuel_fee_measures_actual_drop(api):
    """PRD §3.6: "A fuel fee is charged when `fuel_at_return` comes back below the
    25-percent fuel floor: the fee is 100 cents for every percentage point of the drop
    from `fuel_at_checkout` down to `fuel_at_return`".

    Design: Difficulty/dual_variant_calc/dv_fuel_provisional_vs_final
    """
    ctx, rid, checkout_data = _trip_checked_out(fuel_at_checkout=90)
    m = ctx["member_id"]
    th.set_clock("2026-05-05T12:00:00Z")
    th.return_reservation(m, rid, 10)  # 100 * (90 - 10) = 8000
    fees = th.find_fees(member_id=m, fee_type="FUEL")
    assert len(fees) == 1
    assert fees[0]["amount_cents"] == 8000
    assert checkout_data["provisional_fuel_fee_cents"] != fees[0]["amount_cents"]


# --------------------------------------------------------------------------- #
# combinatorial_formula (queue A) — damage nested min/max
# --------------------------------------------------------------------------- #
def _cf_damage_assessed():
    ctx = th.setup_active_basic_member("SAIL")
    m, b1 = ctx["member_id"], ctx["boat_ids"][0]
    r = th.request_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    dr = th.assessed_damage_fee(r["id"], b1, "MODERATE", 45000)  # min(45000, 30000+0) = 30000
    return m, dr


def test_damage_fee_deductible_binds_when_moderate(api):
    """PRD §3.6: "The damage fee is the smaller of the reported `repair_cost_cents` and
    a tier-dependent ceiling: that ceiling is the member's tier deductible — 50,000
    cents for `CRUISE`, 30,000 cents for `SAIL`, 10,000 cents for `UNLIMITED` — plus,
    only when the severity is `SEVERE`, an additional 20,000-cent surcharge."

    Design: Difficulty/combinatorial_formula/cf_damage_fee_nested_minmax
    """
    m, dr = _cf_damage_assessed()
    assert dr["assessed_fee_cents"] == 30000


def test_damage_fee_creates_matching_damage_fee(api):
    """PRD §3.6: "Assessing the report moves it from `FILED` to `ASSESSED`, computes
    `assessed_fee_cents`, creates a `DAMAGE` fee for the reservation's member".

    Design: Difficulty/combinatorial_formula/cf_damage_fee_nested_minmax
    """
    m, dr = _cf_damage_assessed()
    fees = th.find_fees(member_id=m, fee_type="DAMAGE")
    assert len(fees) == 1
    assert fees[0]["amount_cents"] == 30000


# --------------------------------------------------------------------------- #
# combinatorial_formula (queue A) — per-line tax rounding order
# --------------------------------------------------------------------------- #
def test_dues_fees_rolled_uses_per_line_rounding(api):
    """PRD §2.6: "the rounding method is "round half up" and it is applied to the
    individual line before any summation — never to a running or final sum."
    PRD §3.8: "rounding that single line to whole cents with the round-half-up rule,
    and only then summing the rounded lines — per line first, sum second, never sum first."

    Design: Difficulty/combinatorial_formula/cf_dues_perline_tax_rounding_order
    """
    inv = _cf_dues_issued()
    fresh = th.get_dues_invoice(inv["id"])
    # round_half_up(3334*1.085)=3617 per line; 3617+3617 = 7234 (sum-then-round would give 7235)
    assert fresh["fees_rolled_cents"] == 7234


def test_dues_estimated_total_includes_rolled_fees(api):
    """PRD §3.8: "The invoice total is `base_dues_cents` plus that summed
    `fees_rolled_cents`."

    Design: Difficulty/combinatorial_formula/cf_dues_perline_tax_rounding_order
    """
    inv = _cf_dues_issued()
    fresh = th.get_dues_invoice(inv["id"])
    # base 15000 + 7234 = 22234
    assert fresh["estimated_total_cents"] == 22234


# --------------------------------------------------------------------------- #
# boundary_precision_check (queue A) — late-return grace 15 vs 16
# --------------------------------------------------------------------------- #
def test_late_return_at_grace_boundary_is_free(api):
    """PRD §3.6: "Exactly 15 minutes late is free; only lateness strictly greater than
    that 15-minute grace is billable."

    Design: Difficulty/boundary_precision_check/bp_late_return_grace_15_vs_16
    """
    ctx, rid, _ = _trip_checked_out(fuel_at_checkout=90)
    m = ctx["member_id"]
    th.set_clock("2026-05-05T12:15:00Z")  # exactly 15 minutes after the 12:00 end
    th.return_reservation(m, rid, 80)
    assert th.find_fees(reservation_id=rid, fee_type="LATE_RETURN") == [], "15 minutes late is free"


def test_late_return_past_grace_is_charged_one_block(api):
    """PRD §3.6: "When it is billable, the fee is 2,500 cents for each started
    30-minute block of lateness — that is, 2,500 cents multiplied by the minutes late
    divided by 30 and rounded up to the next whole block."

    Design: Difficulty/boundary_precision_check/bp_late_return_grace_15_vs_16
    """
    ctx, rid, _ = _trip_checked_out(fuel_at_checkout=90)
    m = ctx["member_id"]
    th.set_clock("2026-05-05T12:16:00Z")  # 16 minutes late -> strictly past the grace
    th.return_reservation(m, rid, 80)
    fees = th.find_fees(reservation_id=rid, fee_type="LATE_RETURN")
    assert len(fees) == 1
    assert fees[0]["amount_cents"] == 2500
