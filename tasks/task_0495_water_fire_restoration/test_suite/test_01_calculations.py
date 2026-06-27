"""Calculation correctness: equipment sizing, estimate cost, ACV rounding,
psychrometric gpp, dual-variant billing vs estimate, drying progress.

Every test drives from an empty DB through PRD-declared endpoints only.
"""
import pytest

from test_helpers import (
    api_client as api,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_chamber_payload,
    create_estimate_payload,
    create_reading_payload,
    setup_dispatched_job,
    setup_monitoring_job,
    setup_job_with_chamber,
    create_claim,
    create_job,
    create_fire_job,
    create_technician,
    create_unit,
    tech_headers,
)
from test_helpers.fixtures import (
    DISPATCHER,
    ESTIMATOR,
    ADJUSTER,
)


# ===========================================================================
# Equipment sizing — tiered, non-linear (Difficulty/combinatorial_formula)
# ===========================================================================
class TestEquipmentSizing:
    def test_class2_700sqft_nonlinear_counts(self):
        """PRD §3.3: "divide `floor_area_sqft` by the per-class square-footage
        divisor — 100 square feet per air mover for class 1, 70 for class 2,
        60 for class 3, and 50 for class 4 — take the ceiling of that quotient,
        then take the larger of that value and 1, so the floor-area term is never
        below 1. The second term is the wet-wall term: divide `wet_wall_linear_ft`
        by 16 linear feet per air mover and take the ceiling. The two terms are
        added together."
        PRD §3.3: "First compute the water load in pints per day by multiplying
        `floor_area_sqft` by the per-class load factor — 0.5 for class 1, 1.0 for
        class 2, 1.5 for class 3, and 2.0 for class 4 — and round that product
        half up to two decimal places. Then divide the rounded water load by the
        chamber's `dehu_ppd_rating` and take the ceiling of that quotient; that
        ceiling is `dehumidifiers_required`."

        Design: Difficulty/combinatorial_formula/equipment_sizing_tiered_nonlinear
        """
        ctx = setup_dispatched_job(
            loss_type="WATER",
            certification="ASD",
            claim_overrides={"coverage_limit_cents": 9_000_000},
            job_overrides={"water_category": 2, "water_class": 2},
        )
        resp = api.create_chamber(
            create_chamber_payload(
                ctx["job"]["id"], room_label="R1", floor_area_sqft=700,
                wet_wall_linear_ft=40, dehu_ppd_rating=70, dry_standard_pct=12,
            ),
            ctx["tech_hdr"],
        )
        data = validate_success(resp, 201)
        # ceil(700/70)=10, max(10,1)=10, + ceil(40/16)=ceil(2.5)=3 => 13
        assert data["air_movers_required"] == 13, data["air_movers_required"]
        # water_load = round(700*1.0,2)=700.0; ceil(700/70)=10
        assert data["dehumidifiers_required"] == 10, data["dehumidifiers_required"]

    def test_class1_floor_term_floored_at_one(self):
        """PRD §3.3: "take the ceiling of that quotient, then take the larger of
        that value and 1, so the floor-area term is never below 1."

        Design: Difficulty/combinatorial_formula/equipment_sizing_tiered_nonlinear
        """
        ctx = setup_dispatched_job(
            loss_type="WATER", certification="ASD",
            claim_overrides={"coverage_limit_cents": 9_000_000},
            job_overrides={"water_category": 1, "water_class": 1},
        )
        resp = api.create_chamber(
            create_chamber_payload(
                ctx["job"]["id"], room_label="R1", floor_area_sqft=100,
                wet_wall_linear_ft=0, dehu_ppd_rating=70, dry_standard_pct=12,
            ),
            ctx["tech_hdr"],
        )
        data = validate_success(resp, 201)
        # ceil(100/100)=1, max(1,1)=1, +0 => 1
        assert data["air_movers_required"] == 1
        # water_load = round(100*0.5,2)=50.0; ceil(50/70)=1
        assert data["dehumidifiers_required"] == 1

    def test_fire_job_sizes_at_class2(self):
        """PRD §3.3: "The sizing depends on a **sizing class**: for a `WATER` job
        the class is the job's `water_class`; for a `FIRE` or `SMOKE` job the
        class defaults to 2."

        Design: Corner/calculations/equipment_sizing_fire_job_uses_class2
        """
        claim = create_claim(peril="FIRE", coverage_limit_cents=9_000_000)
        job = create_fire_job(claim["id"], loss_type="FIRE")
        resp = api.create_chamber(
            create_chamber_payload(
                job["id"], room_label="R1", floor_area_sqft=300,
                wet_wall_linear_ft=0, dehu_ppd_rating=70, dry_standard_pct=12,
            ),
            tech_headers("tech-x"),
        )
        data = validate_success(resp, 201)
        # class 2: ceil(300/70)=ceil(4.285)=5, max(5,1)=5, +0 => 5
        assert data["air_movers_required"] == 5
        # water_load = round(300*1.0,2)=300.0; ceil(300/70)=ceil(4.285)=5
        assert data["dehumidifiers_required"] == 5


# ===========================================================================
# Insurance ACV — per-line rounding order (Difficulty/combinatorial_formula)
# ===========================================================================
class TestInsuranceAcv:
    def test_per_line_depreciation_rounding_pinned(self):
        """PRD §3.5: "For each line, compute its replacement-cost value as `qty`
        times `unit_price_cents`, then compute the depreciation for that line as
        that replacement-cost value multiplied by the claim's `depreciation_pct`
        divided by 100, rounded half up to whole cents — the rounding happens per
        line, never after summation."

        Design: Difficulty/combinatorial_formula/insurance_acv_per_line_rounding_order
        """
        claim = create_claim(peril="FIRE", coverage_limit_cents=9_000_000,
                             depreciation_pct=15, tax_pct=0)
        job = create_fire_job(claim["id"], loss_type="FIRE")
        v = get_success_data(api.get_job(job["id"], DISPATCHER))["version"]
        resp = api.create_estimate(
            create_estimate_payload(
                job["id"], v, estimated_drying_days=3,
                line_items=[
                    {"qty": 1, "unit_price_cents": 1050},
                    {"qty": 1, "unit_price_cents": 1050},
                    {"qty": 1, "unit_price_cents": 1050},
                ],
            ),
            ESTIMATOR,
        )
        data = validate_success(resp, 201)
        assert data["scope_lines_total_cents"] == 3150
        # per line: dep=round(1050*0.15)=round(157.5)=158; acv line=892; x3=2676
        # sum-then-round would be 2677; pinned per-line yields 2676
        assert data["acv_total_cents"] == 2676, data["acv_total_cents"]

    def test_zero_depreciation_acv_equals_scope(self):
        """PRD §3.5: "Accumulate, across all lines, the replacement-cost value
        minus the per-line depreciation; call that running sum the ACV subtotal.
        Then compute tax as the ACV subtotal multiplied by the claim's `tax_pct`
        divided by 100, rounded half up to whole cents. The `acv_total_cents` is
        the ACV subtotal plus that tax."

        Design: Difficulty/combinatorial_formula/insurance_acv_per_line_rounding_order
        """
        ctx = setup_job_with_chamber(
            certification="ASD",
            claim_overrides={"coverage_limit_cents": 9_000_000,
                             "depreciation_pct": 0, "tax_pct": 0},
            chamber_overrides={"room_label": "R1", "floor_area_sqft": 100,
                               "wet_wall_linear_ft": 0, "dehu_ppd_rating": 70,
                               "dry_standard_pct": 12},
        )
        v = get_success_data(api.get_job(ctx["job"]["id"], DISPATCHER))["version"]
        resp = api.create_estimate(
            create_estimate_payload(
                ctx["job"]["id"], v, estimated_drying_days=2,
                line_items=[{"qty": 2, "unit_price_cents": 10000}],
            ),
            ESTIMATOR,
        )
        data = validate_success(resp, 201)
        # dep 0 => acv subtotal == scope 20000; tax 0 => acv_total 20000
        assert data["scope_lines_total_cents"] == 20000
        assert data["acv_total_cents"] == 20000


# ===========================================================================
# Psychrometric gpp (Corner/calculations)
# ===========================================================================
class TestPsychrometricGpp:
    def test_gpp_computed_round_half_up(self):
        """PRD §3.4: "Finally multiply the humidity ratio by 7000 grains per pound
        and round the result half up to a whole number of grains; that is `gpp`."

        Design: Corner/calculations/gpp_computed_correctly_on_reading
        """
        ctx = setup_job_with_chamber(certification="WRT")
        resp = api.create_reading(
            ctx["chamber"]["id"],
            create_reading_payload(temp_f=85, relative_humidity_pct=60,
                                   moisture_content_pct=30),
            ctx["tech_hdr"],
        )
        data = validate_success(resp, 201)
        assert data["gpp"] == 108, data["gpp"]


# ===========================================================================
# Over-coverage at approval (Corner/calculations)
# ===========================================================================
class TestOverCoverageLimit:
    def test_approve_over_coverage_limit_rejected(self):
        """PRD §3.5: "The estimate's `estimate_total_cents` must not exceed the
        claim's `coverage_limit_cents`; an over-limit estimate is rejected with
        `ERR_OVER_COVERAGE_LIMIT`."

        Design: Corner/calculations/over_coverage_limit_on_approve
        """
        claim = create_claim(coverage_limit_cents=30000)
        job = create_job(claim["id"], loss_type="WATER",
                         water_category=1, water_class=1, property_address="X")
        v = get_success_data(api.get_job(job["id"], DISPATCHER))["version"]
        est = get_success_data(
            api.create_estimate(
                create_estimate_payload(
                    job["id"], v, estimated_drying_days=1,
                    line_items=[{"qty": 5, "unit_price_cents": 10000}],
                ),
                ESTIMATOR,
            )
        )
        assert est["estimate_total_cents"] == 50000
        resp = api.approve_estimate(est["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_OVER_COVERAGE_LIMIT.value)


# ===========================================================================
# Immediate computed fields on estimate create (Corner/consistency_model)
# ===========================================================================
class TestImmediateComputedFields:
    def test_estimate_create_carries_all_computed_fields(self):
        """PRD §3.5: "The **estimate total**, `estimate_total_cents`, is
        `scope_lines_total_cents` plus `equipment_estimate_cents`."
        PRD §3.5: "it is `estimated_drying_days` multiplied by the sum, taken over
        every non-`DECOMMISSIONED` chamber on the job, of that chamber's
        `air_movers_required` multiplied by the air-mover day rate of 2500 cents
        plus that chamber's `dehumidifiers_required` multiplied by the dehumidifier
        day rate of 8000 cents."

        Design: Corner/consistency_model/estimate_create_immediate_computed_fields
        """
        ctx = setup_job_with_chamber(
            certification="ASD",
            claim_overrides={"coverage_limit_cents": 9_000_000,
                             "depreciation_pct": 0, "tax_pct": 0},
            chamber_overrides={"room_label": "R1", "floor_area_sqft": 100,
                               "wet_wall_linear_ft": 0, "dehu_ppd_rating": 70,
                               "dry_standard_pct": 12},
        )
        v = get_success_data(api.get_job(ctx["job"]["id"], DISPATCHER))["version"]
        resp = api.create_estimate(
            create_estimate_payload(
                ctx["job"]["id"], v, estimated_drying_days=2,
                line_items=[{"qty": 2, "unit_price_cents": 10000}],
            ),
            ESTIMATOR,
        )
        data = validate_success(resp, 201)
        assert data["scope_lines_total_cents"] == 20000
        # 1 AM (2500) + 1 DEHU (8000) = 10500 per day * 2 days = 21000
        assert data["equipment_estimate_cents"] == 21000
        assert data["estimate_total_cents"] == 41000
        assert data["acv_total_cents"] == 20000


# ===========================================================================
# Dual-variant: estimate (projected) vs realized billing
# (Difficulty/dual_variant_calc)
# ===========================================================================
class TestDualVariantBilling:
    def _build_billing_scenario(self):
        """WATER class-1 job, one chamber R1 (1 AM/1 DEHU required), APPROVED
        estimate (drying_days=2, scope line qty=2 @ 10000 => total 41000), one
        AM + one DEHU placed on day 0, advanced 3 days, both removed on day 3
        (billable_days=3 each)."""
        ctx = setup_monitoring_job(
            certification="ASD",
            claim_overrides={"coverage_limit_cents": 200000},
        )
        job_id = ctx["job"]["id"]
        tech_hdr = ctx["tech_hdr"]
        # NOTE: setup_monitoring_job already placed 1 AM + 1 DEHU and reached
        # MONITORING. But we need the estimate APPROVED before completion math;
        # estimate uses required counts (1 AM, 1 DEHU). Build/approve estimate.
        v = get_success_data(api.get_job(job_id, DISPATCHER))["version"]
        est = get_success_data(
            api.create_estimate(
                create_estimate_payload(
                    job_id, v, estimated_drying_days=2,
                    line_items=[{"qty": 2, "unit_price_cents": 10000}],
                ),
                ESTIMATOR,
            )
        )
        get_success_data(api.approve_estimate(est["id"], ADJUSTER))
        # advance 3 monitoring days then remove both placements (billable 3 each)
        for _ in range(3):
            get_success_data(api.advance_day(job_id, tech_hdr))
        get_success_data(api.remove_placement(ctx["air_placement"]["id"], tech_hdr))
        get_success_data(api.remove_placement(ctx["dehu_placement"]["id"], tech_hdr))
        return ctx, est

    def test_estimate_total_is_projection(self):
        """PRD §3.5: "The **estimate total**, `estimate_total_cents`, is
        `scope_lines_total_cents` plus `equipment_estimate_cents`."
        PRD §3.5: "Note this uses each chamber's *required* counts, not the actual
        placements on the ground."

        Design: Difficulty/dual_variant_calc/estimate_cost_estimated_vs_final_billed
        """
        ctx, est = self._build_billing_scenario()
        fetched = get_success_data(api.get_estimate(est["id"], ESTIMATOR))
        # scope 20000 + equip (1*2500 + 1*8000)*2 = 21000 => 41000
        assert fetched["estimate_total_cents"] == 41000, fetched["estimate_total_cents"]

    def test_realized_billing_diverges_from_estimate(self):
        """PRD §3.7: "The realized equipment cost sums, over every equipment
        placement on the job — whether `ACTIVE` or `REMOVED`, walked in
        `created_at` ascending order — the placement's day rate (2500 cents for an
        `AIR_MOVER`, 8000 cents for a `DEHUMIDIFIER`) multiplied by its
        `billable_days`. The final total is the `scope_lines_total_cents` of the
        `APPROVED` estimate plus that realized equipment cost. The billing variance
        is the final total minus the approved estimate's `estimate_total_cents`."

        Design: Difficulty/dual_variant_calc/estimate_cost_estimated_vs_final_billed
        """
        ctx, est = self._build_billing_scenario()
        resp = api.get_billing(ctx["job"]["id"], ADJUSTER)
        data = validate_success(resp, 200)
        # final equipment = (2500*3) + (8000*3) = 7500 + 24000 = 31500
        assert data["final_equipment_cents"] == 31500, data["final_equipment_cents"]
        # final total = scope 20000 + 31500 = 51500
        assert data["final_total_cents"] == 51500, data["final_total_cents"]
        # variance = 51500 - 41000 = 10500
        assert data["billing_variance_cents"] == 10500, data["billing_variance_cents"]


# ===========================================================================
# Dual-variant: drying progress INSTANT vs TRAILING
# (Difficulty/dual_variant_calc)
# ===========================================================================
class TestDryingProgressModes:
    def _build_progress_scenario(self):
        """DISPATCHED WATER job, UNAFFECTED-REF chamber (newest gpp=43), and a
        target chamber R1 with three readings gpp 149 -> 108 -> 79, kept OPEN."""
        ctx = setup_dispatched_job(certification="ASD",
                                   claim_overrides={"coverage_limit_cents": 500000})
        job_id = ctx["job"]["id"]
        tech_hdr = ctx["tech_hdr"]
        ref = get_success_data(
            api.create_chamber(
                create_chamber_payload(job_id, room_label="UNAFFECTED-REF",
                                       floor_area_sqft=100, wet_wall_linear_ft=0,
                                       dehu_ppd_rating=70, dry_standard_pct=12),
                tech_hdr,
            )
        )
        r1 = get_success_data(
            api.create_chamber(
                create_chamber_payload(job_id, room_label="R1",
                                       floor_area_sqft=100, wet_wall_linear_ft=0,
                                       dehu_ppd_rating=70, dry_standard_pct=12),
                tech_hdr,
            )
        )
        ref_reading = get_success_data(
            api.create_reading(ref["id"],
                               create_reading_payload(temp_f=70, relative_humidity_pct=40,
                                                      moisture_content_pct=10), tech_hdr)
        )
        first = get_success_data(
            api.create_reading(r1["id"],
                               create_reading_payload(temp_f=90, relative_humidity_pct=70,
                                                      moisture_content_pct=40), tech_hdr)
        )
        get_success_data(
            api.create_reading(r1["id"],
                               create_reading_payload(temp_f=85, relative_humidity_pct=60,
                                                      moisture_content_pct=30), tech_hdr)
        )
        latest = get_success_data(
            api.create_reading(r1["id"],
                               create_reading_payload(temp_f=78, relative_humidity_pct=55,
                                                      moisture_content_pct=20), tech_hdr)
        )
        return ctx, ref, r1, ref_reading, first, latest

    @staticmethod
    def _progress_for(per_chamber, chamber_id):
        for entry in per_chamber:
            if entry.get("chamber_id") == chamber_id:
                return entry
        raise AssertionError(f"chamber {chamber_id} not in per_chamber {per_chamber}")

    def test_reference_gpp_is_newest_ref_reading(self):
        """PRD §3.7: "the `reference_gpp` is the `gpp` of the newest reading (by
        `created_at` descending) on the chamber whose `room_label` is
        `UNAFFECTED-REF`."

        Design: Difficulty/dual_variant_calc/drying_progress_instant_vs_trailing
        """
        ctx, ref, r1, ref_reading, first, latest = self._build_progress_scenario()
        assert ref_reading["gpp"] == 43, ref_reading["gpp"]
        resp = api.get_drying_progress(ctx["job"]["id"], ctx["tech_hdr"],
                                       params={"mode": "INSTANT"})
        data = validate_success(resp, 200)
        assert data["job_reference_gpp"] == 43, data["job_reference_gpp"]

    def test_instant_vs_trailing_progress_diverge(self):
        """PRD §3.7: "in the default instantaneous mode — when `mode` is `INSTANT`
        or omitted — it is the `gpp` of the single newest reading by `created_at`
        descending; in trailing mode — when `mode` is `TRAILING` — it is the mean
        of the two newest readings' `gpp`, rounded half up to a whole number. The
        two modes diverge whenever the two newest readings differ."
        PRD §3.7: "The progress percentage is the initial difference minus the
        current difference, divided by the initial difference, multiplied by 100,
        and rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/drying_progress_instant_vs_trailing
        """
        ctx, ref, r1, ref_reading, first, latest = self._build_progress_scenario()
        # INSTANT: initial_diff = 149-43=106; current_diff = 79-43=36;
        #   progress = (106-36)/106*100 = 66.0377... -> 66.04
        resp_i = api.get_drying_progress(ctx["job"]["id"], ctx["tech_hdr"],
                                         params={"mode": "INSTANT"})
        data_i = validate_success(resp_i, 200)
        prog_i = self._progress_for(data_i["per_chamber"], r1["id"])
        assert prog_i["progress_pct"] == pytest.approx(66.04, abs=0.001), prog_i

        # TRAILING: chamber_gpp = round((79+108)/2)=round(93.5)=94;
        #   current_diff = 94-43=51; progress=(106-51)/106*100=51.886... -> 51.89
        resp_t = api.get_drying_progress(ctx["job"]["id"], ctx["tech_hdr"],
                                         params={"mode": "TRAILING"})
        data_t = validate_success(resp_t, 200)
        prog_t = self._progress_for(data_t["per_chamber"], r1["id"])
        assert prog_t["progress_pct"] == pytest.approx(51.89, abs=0.001), prog_t
        assert prog_i["progress_pct"] != prog_t["progress_pct"]
