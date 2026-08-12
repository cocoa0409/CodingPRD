"""Calculation rules: sludge estimates, flush volume, disposal cost, invoice,
mass balance (PRD §2.7, §3.4, §3.5, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_product_payload,
    new_ctx, create_job, schedule_job, activate_window_and_take_oos,
    record_heel, create_approved_profile, add_shipment, record_sludge,
    request_gas_free, issue_certificate, add_permit, begin_entry,
    complete_entry, add_inspector, create_inspection, run_inspection,
    begin_and_verify_flush, request_rts, contractor_headers,
    setup_ctx_tank_oos, setup_ctx_inspection_accepted,
    setup_ctx_flush_verified, get_job,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]
EHS = TEST_USERS["ehs_headers"]


class TestSludgeEstimateDualVariant:
    def test_provisional_estimate_uses_sounding_volume_at_creation(self, api):
        """PRD §3.4: "the provisional sludge estimate `sludge_estimate_provisional_kg` is the sounding volume multiplied by the sludge ratio of the from-product's family — 0.02 for `GASOLINE`, 0.03 for `DISTILLATE`, 0.015 for `JET`, 0.08 for `CRUDE`, 0.05 for `CHEMICAL`, 0.04 for `VEGOIL` — plus the tank's `capacity_m3` multiplied by the surface factor of the from-product's viscosity class — 0.5 for `LOW`, 1.0 for `MEDIUM`, 2.0 for `HIGH` — the whole result rounded half-up to whole kilograms"
        PRD §3.5: "Until this point `expected_solids_kg` remains null."

        Design: Difficulty/dual_variant_calc/sludge_estimate_provisional_vs_final_basis
        """
        ctx = new_ctx()
        job = create_job(ctx, heel_volume_liters_sounding=2000,
                         base_service_fee_cents=500000, lines_included=True)
        # 2000 * 0.02 + 5000 * 0.5 = 2540 (sounding basis).
        assert job["sludge_estimate_provisional_kg"] == 2540
        assert job.get("expected_solids_kg") is None

    def test_final_basis_uses_metered_volume_after_heel_removal(self, api):
        """PRD §3.5: "The job moves `TANK_OOS` to `HEEL_REMOVED`, the value is stored as `heel_volume_liters_metered`, and `expected_solids_kg` is computed on the final basis: exactly the same sludge formula as the provisional estimate of §3.4 — metered volume times the family sludge ratio, plus capacity times the viscosity surface factor, rounded half-up to whole kilograms — differing only in that the metered volume replaces the sounding volume."

        Design: Difficulty/dual_variant_calc/sludge_estimate_provisional_vs_final_basis
        """
        ctx = setup_ctx_tank_oos(heel_volume_liters_sounding=2000,
                                 base_service_fee_cents=500000,
                                 lines_included=True)
        job = record_heel(ctx, 2100)
        assert job["status"] == "HEEL_REMOVED"
        # 2100 * 0.02 + 5000 * 0.5 = 2542 (metered basis) — same constants,
        # only the volume source differs from the provisional 2540.
        assert job["expected_solids_kg"] == 2542
        assert job["sludge_estimate_provisional_kg"] == 2540
        assert job["expected_solids_kg"] != job["sludge_estimate_provisional_kg"]


class TestFlushVolumeTiers:
    def _products(self, api):
        crude = validate_success(api.create_product(create_product_payload(
            code="CRD01", family="CRUDE", viscosity_class="HIGH",
            compatibility_group="CRUDE", flash_point_c=20), ADMIN), 201)
        gas2 = validate_success(api.create_product(create_product_payload(
            code="GAS92", family="GASOLINE", viscosity_class="LOW",
            compatibility_group="GAS", flash_point_c=-38), ADMIN), 201)
        return crude, gas2

    def test_requires_flush_unclamped_with_lines_allowance(self, api):
        """PRD §3.4: "the required `flush_volume_liters` is the tank capacity in liters — `capacity_m3` times one thousand — multiplied by the base factor of the from-product's viscosity class (0.02 for `LOW`, 0.035 for `MEDIUM`, 0.05 for `HIGH`) and by the class multiplier of the changeover class (0.5 for `COMPATIBLE_DIRECT`, 1.0 for `REQUIRES_FLUSH`, 1.8 for `REQUIRES_FULL_STRIP`); when `lines_included` is set, a further 5,000 liters is added"

        Design: Difficulty/combinatorial_formula/flush_volume_nested_min_max_tiers
        """
        ctx = new_ctx()
        job = create_job(ctx, lines_included=True)
        assert job["changeover_class"] == "REQUIRES_FLUSH"
        # 5000*1000 * 0.02 * 1.0 + 5000 = 105000 (within the floor/ceiling).
        assert job["flush_volume_liters"] == 105000

    def test_requires_flush_capped_at_max_flush_liters(self, api):
        """PRD §3.4: "the raw figure is then rounded up to the next whole liter and finally confined to a floor of 2,000 liters and a ceiling of 200,000 liters."

        Design: Difficulty/combinatorial_formula/flush_volume_nested_min_max_tiers
        """
        ctx = new_ctx()
        crude, _ = self._products(api)
        job = create_job(ctx, lines_included=True, from_product_id=crude["id"])
        # crude(HIGH) -> dist: 5000*1000 * 0.05 * 1.0 + 5000 = 255000 raw.
        assert job["changeover_class"] == "REQUIRES_FLUSH"
        assert job["flush_volume_liters"] == 200000

    def test_compatible_direct_half_multiplier_without_lines(self, api):
        """PRD §3.4: "if both products share the same `compatibility_group`, the class is `COMPATIBLE_DIRECT`"
        PRD §3.4: "the required `flush_volume_liters` is the tank capacity in liters — `capacity_m3` times one thousand — multiplied by the base factor of the from-product's viscosity class (0.02 for `LOW`, 0.035 for `MEDIUM`, 0.05 for `HIGH`) and by the class multiplier of the changeover class (0.5 for `COMPATIBLE_DIRECT`, 1.0 for `REQUIRES_FLUSH`, 1.8 for `REQUIRES_FULL_STRIP`)"

        Design: Difficulty/combinatorial_formula/flush_volume_nested_min_max_tiers
        """
        ctx = new_ctx()
        _, gas2 = self._products(api)
        job = create_job(ctx, lines_included=False, to_product_id=gas2["id"])
        assert job["changeover_class"] == "COMPATIBLE_DIRECT"
        # 5000*1000 * 0.02 * 0.5 = 50000; no lines allowance added.
        assert job["flush_volume_liters"] == 50000


class TestWasteDisposalCostRounding:
    def test_per_line_rounding_then_sum_pinned(self, api):
        """PRD §2.7: "Disposal costing follows a pinned rounding order: each shipment line is rounded half-up to whole cents first, and only then are the line amounts summed into the shipment total — summing raw line products and rounding once at the end produces a different number and is not the contract."

        Design: Difficulty/combinatorial_formula/waste_cost_per_line_rounding_pinned
        """
        ctx = new_ctx()
        create_job(ctx)
        create_approved_profile(ctx, hazard_class="NON_HAZARDOUS")
        shipment = add_shipment(
            ctx, [{"material": "SLUDGE", "kg": 17, "rate_cents_per_kg": 2.2},
                  {"material": "WASH_WATER", "kg": 23, "rate_cents_per_kg": 1.8}],
            dispatch=False, deliver=False)
        # round_half_up(17*2.2*1.0)=37 + round_half_up(23*1.8*1.0)=41 -> 78.
        # (sum-then-round would give 78.8 -> 79, which is not the contract.)
        assert shipment["disposal_cost_cents"] == 78
        assert shipment["manifested_kg"] == 40

    def test_per_line_rounding_with_hazardous_multiplier(self, api):
        """PRD §3.5: "its `disposal_cost_cents` follows the pinned rounding order of §2.7: each line's kilograms multiplied by its rate and by the hazard multiplier of the profile's class — 1.0 for `NON_HAZARDOUS`, 2.5 for `HAZARDOUS` — rounded half-up to whole cents per line, then summed."

        Design: Difficulty/combinatorial_formula/waste_cost_per_line_rounding_pinned
        """
        ctx = new_ctx()
        create_job(ctx)
        create_approved_profile(ctx, hazard_class="HAZARDOUS")
        shipment = add_shipment(
            ctx, [{"material": "SLUDGE", "kg": 17, "rate_cents_per_kg": 2.2},
                  {"material": "WASH_WATER", "kg": 23, "rate_cents_per_kg": 1.8}],
            dispatch=False, deliver=False)
        # round_half_up(93.5)=94 + round_half_up(103.5)=104 -> 198.
        assert shipment["disposal_cost_cents"] == 198
        assert shipment["manifested_kg"] == 40


class TestJobInvoiceWaterfall:
    def test_five_percent_tier_keyed_on_pre_discount_total(self, api):
        """PRD §3.8: "Third, the pre-discount total is the sum of `base_service_fee_cents`, the waste charges, and the flush charge. Fourth, the tier is read off that pre-discount total: ten percent when it reaches 1,000,000 cents, five percent when it reaches 500,000 cents, and nothing below that. Fifth, the discount is `base_service_fee_cents` multiplied by the tier percentage, rounded half-up to whole cents — the only rounding step in the waterfall. Finally, the invoice total is the pre-discount total minus the discount."

        Design: Difficulty/combinatorial_formula/job_invoice_circular_tier_pinned
        """
        ctx = setup_ctx_flush_verified(
            lines_included=True,
            shipment_lines=[{"material": "SLUDGE", "kg": 1200,
                             "rate_cents_per_kg": 2.2},
                            {"material": "WASH_WATER", "kg": 1342,
                             "rate_cents_per_kg": 1.8}],
            reconcile=True)
        job = request_rts(ctx)
        assert job["status"] == "RTS_PENDING"
        # waste = 2640 + 2416 = 5056; flush = 105000 * 2 = 210000;
        # pre_total = 500000 + 5056 + 210000 = 715056 (>= 500000 -> 5%);
        # invoice = 715056 - round_half_up(500000 * 0.05) = 690056.
        assert job["waste_cost_cents"] == 5056
        assert job["invoice_total_cents"] == 690056

    def test_ten_percent_tier_at_one_million_pre_total(self, api):
        """PRD §3.8: "Fourth, the tier is read off that pre-discount total: ten percent when it reaches 1,000,000 cents, five percent when it reaches 500,000 cents, and nothing below that."
        PRD §3.8: "First, waste charges are taken as the job's `waste_cost_cents`, the sum of disposal costs over its `RECONCILED` shipments. Second, the flush charge is the job's `flush_volume_liters` at two cents per liter."

        Design: Difficulty/combinatorial_formula/job_invoice_circular_tier_pinned
        """
        ctx = setup_ctx_flush_verified(
            base_service_fee_cents=1000000, lines_included=False,
            reconcile=False)  # delivered-only shipment -> waste charges 0
        job = request_rts(ctx)
        assert job["status"] == "RTS_PENDING"
        # pre_total = 1000000 + 0 + 100000*2 = 1200000 (>= 1000000 -> 10%);
        # invoice = 1200000 - round_half_up(1000000 * 0.10) = 1100000.
        assert job["invoice_total_cents"] == 1100000

    def test_no_discount_below_five_hundred_thousand_pre_total(self, api):
        """PRD §3.8: "the tier is read off that pre-discount total: ten percent when it reaches 1,000,000 cents, five percent when it reaches 500,000 cents, and nothing below that."

        Design: Difficulty/combinatorial_formula/job_invoice_circular_tier_pinned
        """
        ctx = new_ctx(tank_overrides={"capacity_m3": 1000})
        ctx = setup_ctx_flush_verified(
            ctx, base_service_fee_cents=100000, lines_included=False,
            metered_liters=2100,
            shipment_lines=[{"material": "SLUDGE", "kg": 542,
                             "rate_cents_per_kg": 2.0}],
            reconcile=True)
        # expected solids = 2100*0.02 + 1000*0.5 = 542; shipped 542 -> delta 0.
        job = request_rts(ctx)
        assert job["status"] == "RTS_PENDING"
        # pre_total = 100000 + 1084 + 20000*2 = 141084 (< 500000 -> no tier).
        assert job["invoice_total_cents"] == 141084


class TestFlushVerifyBoundary:
    def test_flush_verify_one_liter_short_then_exactly_enough(self, api):
        """PRD §3.8: "the flush passes when that figure is at least the job's computed `flush_volume_liters` — the boundary is inclusive, so a flush exactly equal to the requirement verifies — failing which `ERR_FLUSH_VOLUME_INSUFFICIENT` (HTTP 409)."

        Design: Corner/calculations/flush_verify_inclusive_boundary
        """
        ctx = setup_ctx_inspection_accepted()  # lines_included false -> 100000 L
        job = ctx["job"]
        validate_success(api.begin_flush(job["id"], contractor_headers(ctx)), 200)
        res = api.verify_flush(job["id"], {"actual_flush_liters": 99999}, EHS)
        validate_error(res, ApiErrorId.ERR_FLUSH_VOLUME_INSUFFICIENT)
        done = validate_success(
            api.verify_flush(job["id"], {"actual_flush_liters": 100000}, EHS), 200)
        assert done["status"] == "FLUSH_VERIFIED"


class TestMassBalanceTolerance:
    def test_delta_at_tolerance_bound_passes_and_one_beyond_fails(self, api):
        """PRD §3.8: "the absolute difference between the two must not exceed the expected figure multiplied by the terminal's `mass_balance_tolerance_pct` divided by one hundred, and a delta exactly equal to the tolerance passes. A breach rejects the request with `ERR_MASS_BALANCE_OUT_OF_TOLERANCE` (HTTP 409)."

        Design: Corner/calculations/mass_balance_inclusive_tolerance_boundary
        """
        base = new_ctx(terminal_overrides={"mass_balance_tolerance_pct": 2.0})

        def run_job(tank_number, residual):
            tank = validate_success(api.create_tank(
                {"terminal_id": base["terminal"]["id"],
                 "tank_number": tank_number, "capacity_m3": 5000,
                 "current_product_id": base["gas"]["id"]}, ADMIN), 201)
            sub = {"terminal": base["terminal"], "gas": base["gas"],
                   "dist": base["dist"], "tank": tank,
                   "contractor": base["contractor"]}
            create_job(sub)
            schedule_job(sub)
            activate_window_and_take_oos(sub)
            record_heel(sub, 2100)  # expected solids 2542
            create_approved_profile(sub)
            add_shipment(sub, [{"material": "SLUDGE", "kg": 2500,
                                "rate_cents_per_kg": 2.0}])
            record_sludge(sub, residual)
            request_gas_free(sub)
            issue_certificate(sub)
            add_permit(sub, issue=True, activate=True)
            begin_entry(sub)
            complete_entry(sub)
            return sub

        sub_a = run_job("T-A", 92)   # actual 2592, delta 50 <= 50.84 bound
        sub_b = run_job("T-B", 93)   # actual 2593, delta 51 > 50.84 bound

        add_inspector(base)
        sub_a["inspector"] = base["inspector"]
        sub_b["inspector"] = base["inspector"]
        create_inspection(sub_a, "2026-05-03T00:00:00Z", "2026-05-03T08:00:00Z")
        run_inspection(sub_a)
        create_inspection(sub_b, "2026-05-03T08:00:00Z", "2026-05-03T16:00:00Z")
        run_inspection(sub_b)
        begin_and_verify_flush(sub_a, 100000)
        begin_and_verify_flush(sub_b, 100000)

        job_a = request_rts(sub_a)
        assert job_a["status"] == "RTS_PENDING"
        res_b = api.request_rts(sub_b["job"]["id"], OPERATOR)
        validate_error(res_b, ApiErrorId.ERR_MASS_BALANCE_OUT_OF_TOLERANCE)
