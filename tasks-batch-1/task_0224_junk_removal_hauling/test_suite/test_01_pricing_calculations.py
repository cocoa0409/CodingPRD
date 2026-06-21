"""Pricing-engine tests: estimate vs final divergence, tiered marginal base, per-item
surcharge, dump-fee variants, same-day uplift, diversion credit, and fraction-billing
boundaries.

All expected cents are computed strictly from the PRD's stated formulas (§3.3, §3.7) over
the canonical std_policy rate set.
"""
from test_helpers import (
    validate_success, validate_paginated,
    setup_loaded_job, setup_estimated_job,
    make_crew_lead_headers,
)


# ─── dual_variant_calc ────────────────────────────────

def test_estimate_and_final_totals_diverge_for_same_job(api):
    """PRD §1: "The estimate is deliberately incomplete (dump, diversion, and tax are
    unknowable before the load is weighed), and the final figure is authoritative."
    PRD §3.7: "The subtotal is the base (with any uplift) plus the item surcharge plus
    the dump total plus the recycling fee, minus the diversion credit. Tax is the
    subtotal multiplied by the policy's `tax_pct`, rounded. The final total is the
    subtotal plus the tax."

    Estimate: raw 0.30 -> billed 0.375; base = 0.25*60000*1.0 + 0.125*60000*0.9 = 15000+6750
    = 21750; declared 1 mattress + 1 appliance -> surcharge 3500+2500=6000; estimated total
    = 27750. Final: measured 0.40 -> billed 0.5; base = 15000+6750+0=... walk bands:
    [0,0.25)=0.25*60000*1.0=15000; [0.25,0.5)=0.25*60000*0.9=13500 -> base 28500; actual items
    1 mattress + 2 appliance + 1 freon -> 3500 + 5000 + 5000 = 13500; dump (WEIGHT 0.8t)
    round(0.8*9000)=7200; recycle (RECYCLING 0.5t) round(0.5*4000)=2000; credit (0.5t)
    round(0.5*1500)=750; subtotal = 28500+13500+7200+2000-750 = 50450; tax round(50450*0.08)
    = 4036; final = 54486.

    Design: Difficulty/dual_variant_calc/estimate_vs_final_total_diverge_across_photoestimate_and_hauljob
    """
    ctx = setup_loaded_job(
        raw_fraction=0.30,
        declared_items=[{"category": "MATTRESS", "quantity": 1}, {"category": "APPLIANCE", "quantity": 1}],
        items=[("MATTRESS", 1), ("APPLIANCE", 2), ("FREON_APPLIANCE", 1)],
        measured_truck_fraction=0.40,
        diversions=[("RECYCLING", 0.5)],
        dump_tickets=[("WEIGHT_BASED", 0.8, 0.5)],
        crew_overrides={"hazmat_certified": True},
    )
    job = validate_success(api.get_haul_job(ctx["job"]["id"], make_crew_lead_headers(ctx["crew"]["id"])))
    assert job["estimated_total_cents"] == 27750, f"estimated_total_cents={job['estimated_total_cents']}"
    assert job["final_total_cents"] == 54486, f"final_total_cents={job['final_total_cents']}"
    assert job["estimated_total_cents"] != job["final_total_cents"]


def test_estimated_total_excludes_dump_diversion_and_tax(api):
    """PRD §3.3: "Crucially, the estimate deliberately excludes landfill dump fees,
    recycling fees, diversion credits, and tax — none of those are knowable until the
    load is weighed on site, so they appear only in the final bill."

    Estimate raw 0.30 -> billed 0.375 base 21750; declared 1 mattress + 1 appliance
    surcharge 6000; estimated_total = 27750 with no dump/diversion/tax terms.

    Design: Difficulty/dual_variant_calc/estimate_vs_final_total_diverge_across_photoestimate_and_hauljob
    """
    ctx = setup_estimated_job(
        raw_fraction=0.30,
        declared_items=[{"category": "MATTRESS", "quantity": 1}, {"category": "APPLIANCE", "quantity": 1}],
    )
    job = ctx["job"]
    assert job["estimated_total_cents"] == 27750, f"estimated_total_cents={job['estimated_total_cents']}"


def test_weight_based_dump_fee_uses_tons_times_per_ton_rate(api):
    """PRD §3.7: "A `WEIGHT_BASED` ticket's fee is its `landfill_tons` multiplied by the
    policy's `dump_fee_per_ton_cents`, rounded."

    0.8 ton * 9000 = round(7200) = 7200.

    Design: Difficulty/dual_variant_calc/dump_fee_weight_vs_volume_diverge_on_dumpticket
    """
    ctx = setup_loaded_job(
        raw_fraction=0.30,
        measured_truck_fraction=0.20,
        dump_tickets=[("WEIGHT_BASED", 0.8, 0.5)],
    )
    ticket = ctx["dump_tickets"][0]
    tickets, _ = validate_paginated(api.list_dump_tickets(ctx["job"]["id"], make_crew_lead_headers(ctx["crew"]["id"])))
    rec = next(t for t in tickets if t["id"] == ticket["id"])
    assert rec["dump_fee_cents"] == 7200, f"dump_fee_cents={rec['dump_fee_cents']}"


def test_volume_based_dump_fee_uses_fraction_times_flat_cost(api):
    """PRD §3.7: "A `VOLUME_BASED` ticket's fee is its `landfill_fraction` multiplied by
    the policy's `full_truck_dump_cents`, rounded. The same physical load can therefore
    produce a different fee under the two bases, and each ticket is computed
    independently and rounded on its own."

    0.5 fraction * 12000 = round(6000) = 6000 — the SAME 0.8t/0.5-fraction load yields a
    different fee than the weight basis (7200).

    Design: Difficulty/dual_variant_calc/dump_fee_weight_vs_volume_diverge_on_dumpticket
    """
    ctx = setup_loaded_job(
        raw_fraction=0.30,
        measured_truck_fraction=0.20,
        dump_tickets=[("VOLUME_BASED", 0.8, 0.5)],
    )
    ticket = ctx["dump_tickets"][0]
    tickets, _ = validate_paginated(api.list_dump_tickets(ctx["job"]["id"], make_crew_lead_headers(ctx["crew"]["id"])))
    rec = next(t for t in tickets if t["id"] == ticket["id"])
    assert rec["dump_fee_cents"] == 6000, f"dump_fee_cents={rec['dump_fee_cents']}"


# ─── combinatorial_formula ────────────────────────────

def test_final_total_combines_tiered_base_surcharge_dump_recycle_credit_tax(api):
    """PRD §3.7: "The job's `final_total_cents` is assembled, in cents, as follows ...
    The subtotal is the base (with any uplift) plus the item surcharge plus the dump
    total plus the recycling fee, minus the diversion credit. Tax is the subtotal
    multiplied by the policy's `tax_pct`, rounded. The final total is the subtotal plus
    the tax."

    measured 0.40 -> billed 0.5; base 28500; items 1 mattress + 2 appliance + 1 freon ->
    3500+5000+5000=13500; dump WEIGHT 0.8t -> 7200; recycle 0.5t -> 2000; credit 0.5t ->
    750; subtotal 50450; tax 4036; final 54486.

    Design: Difficulty/combinatorial_formula/final_total_nonlinear_tiered_with_conditional_branches_mode_a
    """
    ctx = setup_loaded_job(
        raw_fraction=0.30,
        items=[("MATTRESS", 1), ("APPLIANCE", 2), ("FREON_APPLIANCE", 1)],
        measured_truck_fraction=0.40,
        diversions=[("RECYCLING", 0.5)],
        dump_tickets=[("WEIGHT_BASED", 0.8, 0.5)],
        crew_overrides={"hazmat_certified": True},
    )
    assert ctx["job"]["final_total_cents"] == 54486, f"final_total_cents={ctx['job']['final_total_cents']}"


def test_final_total_tiered_base_floors_at_min_fraction_for_low_volume(api):
    """PRD §3.3: "divide the raw fraction by the policy's `fraction_step` and round that
    quotient up to the next whole number of steps, multiply back by `fraction_step` to
    get the billed fraction, then take the larger of that billed fraction and the
    policy's `min_billable_fraction`."

    Reuses the marginal-band base over the lowest band: measured 0.05 -> billed 0.125;
    base = 0.125*60000*1.0 = 7500 (all inside first band).

    Design: Difficulty/combinatorial_formula/final_total_nonlinear_tiered_with_conditional_branches_mode_a
    """
    ctx = setup_loaded_job(raw_fraction=0.05, measured_truck_fraction=0.05)
    # base 7500; no items/dump/diversion; subtotal 7500; tax round(7500*0.08)=600; total 8100.
    assert ctx["job"]["final_total_cents"] == 8100, f"final_total_cents={ctx['job']['final_total_cents']}"


def test_item_surcharge_rounds_per_item_then_sums(api):
    """PRD §3.7: "The item surcharge is summed over the job's actual `JobItem` manifest
    (not the declared estimate items): for each item, its category's surcharge rate
    multiplied by its `quantity`, rounded per item, then summed."

    1 mattress + 2 appliance -> round(3500*1)+round(2500*2)=3500+5000=8500; base(0.125)=7500;
    subtotal=16000; tax round(16000*0.08)=1280; total 17280.

    Design: Difficulty/combinatorial_formula/surcharge_round_per_item_then_sum_mode_b
    """
    ctx = setup_loaded_job(
        raw_fraction=0.05,
        items=[("MATTRESS", 1), ("APPLIANCE", 2)],
        measured_truck_fraction=0.05,
    )
    assert ctx["job"]["final_total_cents"] == 17280, f"final_total_cents={ctx['job']['final_total_cents']}"


def test_freon_item_surcharge_applied_per_item(api):
    """PRD §3.7: "for each item, its category's surcharge rate multiplied by its
    `quantity`, rounded per item, then summed."
    PRD §3.3: "`freon_surcharge_cents` for `FREON_APPLIANCE` (a refrigerant appliance
    requiring EPA recovery)."

    1 freon -> round(5000*1)=5000; base(0.125)=7500; subtotal=12500; tax round(12500*0.08)
    =1000; total 13500.

    Design: Difficulty/combinatorial_formula/surcharge_round_per_item_then_sum_mode_b
    """
    ctx = setup_loaded_job(
        raw_fraction=0.05,
        items=[("FREON_APPLIANCE", 1)],
        measured_truck_fraction=0.05,
        crew_overrides={"hazmat_certified": True},
    )
    assert ctx["job"]["final_total_cents"] == 13500, f"final_total_cents={ctx['job']['final_total_cents']}"


# ─── boundary_precision_check ─────────────────────────

def test_estimate_tier_boundary_exact_quarter_fraction(api):
    """PRD §3.3: "To compute the base, walk the bands in order, treating each band as the
    interval from the previous band's upper bound to its own `upper_fraction`. For each
    band, the amount of the billed fraction that falls inside that band — the lesser of
    the billed fraction and the band's upper bound, minus the previous band's upper
    bound, never less than zero — is multiplied by `full_truck_cents` and by that band's
    `marginal_multiplier`, and the products are accumulated across all bands."

    raw 0.25 -> billed 0.25 (exact step), all in first band -> base 0.25*60000*1.0=15000;
    estimated_total = 15000 (no items, SCHEDULED).

    Design: Difficulty/boundary_precision_check/estimate_tier_boundary_quarter_fraction_exact_vs_over
    """
    ctx = setup_estimated_job(raw_fraction=0.25)
    assert ctx["job"]["estimated_truck_fraction"] == 0.25, f"frac={ctx['job']['estimated_truck_fraction']}"
    assert ctx["job"]["estimated_total_cents"] == 15000, f"est={ctx['job']['estimated_total_cents']}"


def test_estimate_tier_boundary_just_over_quarter_rounds_up_into_next_band(api):
    """PRD §2.8: "a measured or estimated raw fraction is always rounded **up** to the
    next whole multiple of `fraction_step`."
    PRD §3.3: "the products are accumulated across all bands. The accumulated base is then
    rounded."

    raw 0.26 -> billed 0.375 (rounds up past 0.25 into the 0.9x band); base =
    0.25*60000*1.0 + 0.125*60000*0.9 = 15000+6750 = 21750.

    Design: Difficulty/boundary_precision_check/estimate_tier_boundary_quarter_fraction_exact_vs_over
    """
    ctx = setup_estimated_job(raw_fraction=0.26)
    assert ctx["job"]["estimated_truck_fraction"] == 0.375, f"frac={ctx['job']['estimated_truck_fraction']}"
    assert ctx["job"]["estimated_total_cents"] == 21750, f"est={ctx['job']['estimated_total_cents']}"


def test_load_floors_low_measured_fraction_at_min_billable(api):
    """PRD §2.8: "After that round-up, a floor is applied: the billed fraction may not
    fall below the policy's `min_billable_fraction`, which also defaults to 0.125."

    measured 0.05 -> rounds up to 0.125 (the step) which equals the floor -> billed 0.125;
    base 7500; no other terms; tax 600; final 8100. The stored measured_truck_fraction is
    the raw 0.05.

    Design: Difficulty/boundary_precision_check/load_empty_items_min_fraction_floor_boundary
    """
    ctx = setup_loaded_job(raw_fraction=0.05, measured_truck_fraction=0.05)
    assert ctx["job"]["measured_truck_fraction"] == 0.05, f"measured={ctx['job']['measured_truck_fraction']}"
    assert ctx["job"]["final_total_cents"] == 8100, f"final={ctx['job']['final_total_cents']}"


def test_load_with_zero_items_has_no_surcharge_or_dump_terms(api):
    """PRD §3.7: "The dump total is the sum of every dump ticket's computed
    `dump_fee_cents`." (with no tickets, the dump total contributes nothing.)
    PRD §3.7: "The item surcharge is summed over the job's actual `JobItem` manifest" (an
    empty manifest contributes nothing).

    Empty job, measured 0.125 -> billed 0.125 base 7500; subtotal 7500; tax 600; final 8100.

    Design: Difficulty/boundary_precision_check/load_empty_items_min_fraction_floor_boundary
    """
    ctx = setup_loaded_job(raw_fraction=0.125, measured_truck_fraction=0.125)
    assert ctx["job"]["final_total_cents"] == 8100, f"final={ctx['job']['final_total_cents']}"


# ─── corner: calculations ─────────────────────────────

def test_same_day_uplift_applied_to_base(api):
    """PRD §3.7: "If the job's `service_type` is `SAME_DAY`, the same-day uplift — the
    base multiplied by `same_day_surcharge_pct`, rounded — is added to the base."

    SAME_DAY, measured 0.20 -> billed 0.25 base 15000; uplift round(15000*0.20)=3000;
    subtotal 18000; tax round(18000*0.08)=1440; final 19440.

    Design: Corner/calculations/same_day_surcharge_uplift_applied_to_base
    """
    ctx = setup_loaded_job(raw_fraction=0.20, service_type="SAME_DAY", measured_truck_fraction=0.20)
    assert ctx["job"]["final_total_cents"] == 19440, f"final={ctx['job']['final_total_cents']}"


def test_donation_diversion_earns_credit_with_no_recycle_fee(api):
    """PRD §3.6: "Both destinations earn the customer a diversion credit; recycling
    additionally incurs a recycling gate fee."
    PRD §3.7: "The diversion credit is summed over **all** diversion records regardless
    of destination — both `DONATION` and `RECYCLING` earn it: each record's `tons`
    multiplied by `diversion_credit_per_ton_cents`, rounded, then summed."

    base 7500; DONATION 1.0t credit round(1.0*1500)=1500; no recycle fee; subtotal
    7500-1500=6000; tax round(6000*0.08)=480; final 6480.

    Design: Corner/calculations/donation_diversion_credit_subtracted_no_recycle_fee
    """
    ctx = setup_loaded_job(
        raw_fraction=0.05,
        measured_truck_fraction=0.05,
        diversions=[("DONATION", 1.0)],
    )
    assert ctx["job"]["final_total_cents"] == 6480, f"final={ctx['job']['final_total_cents']}"
