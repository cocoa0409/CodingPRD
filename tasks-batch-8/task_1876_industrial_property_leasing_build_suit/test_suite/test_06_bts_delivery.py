"""Build-to-suit cost/rent conversion, approval cap, and the delivery cascade
(PRD §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_priced_plan,
    assert_same_instant,
    clear_both_reviews,
    create_accepted_loi,
    create_bolt_requirement,
    create_bts_site,
    create_completed_tour,
    create_milestone_payload,
    get_plan_for_loi,
    price_plan,
    setup_approved_plan_with_sc_milestone,
    setup_executed_bolt_loi,
    setup_executed_loi,
    validate_error,
    validate_success,
)

REP_1 = TEST_USERS["tenant_rep_1_headers"]

LM = TEST_USERS["leasing_manager_headers"]
PM = TEST_USERS["project_manager_headers"]
AM = TEST_USERS["asset_manager_headers"]


class TestPricingMethodDivergence:
    """Identical cost inputs, two pricing methods -> different converted rent
    (PRD §3.5)."""

    def _setup_schematic_plan(self, api):
        bundle = setup_executed_loi(commission_basis="GROSS_AGGREGATE")
        return bundle

    def test_yield_on_cost_conversion(self, api):
        """PRD §3.5: "Under `YIELD_ON_COST`, `converted_base_rate_psf` is
        `total_project_cost` multiplied by the eight-percent target yield and
        divided by `leased_sf`, rounded half-up to cents."

        Design: Difficulty/dual_variant_calc/bts_pricing_method_divergence
        """
        bundle = self._setup_schematic_plan(api)
        priced = price_plan(bundle["plan"]["id"], pricing_method="YIELD_ON_COST")
        assert_priced_plan(priced)
        assert priced["status"] == "PRICED"
        assert priced["converted_base_rate_psf"] == pytest.approx(
            10.25, abs=0.005
        ), (
            f"YIELD_ON_COST converted rate must be 10.25, got "
            f"{priced['converted_base_rate_psf']}"
        )
        assert priced["total_project_cost"] == pytest.approx(
            12814064.36, abs=0.005
        )

    def test_market_comp_diverges_on_identical_costs(self, api):
        """PRD §3.5: "Under `MARKET_COMP`, `converted_base_rate_psf` is the
        greater of the linked site's `asking_rate_psf` and the yield-on-cost
        rate grown by a five-percent market markup and rounded half-up to
        cents — identical cost inputs produce a different, and never
        below-market, rent." and "the computed pricing fields from the last
        run are retained until the next pricing overwrites them."

        Design: Difficulty/dual_variant_calc/bts_pricing_method_divergence
        """
        bundle = self._setup_schematic_plan(api)
        plan_id = bundle["plan"]["id"]
        yoc = price_plan(plan_id, pricing_method="YIELD_ON_COST")

        validate_success(api.revise_bts_plan(plan_id, PM))  # PRICED -> SCHEMATIC
        market = price_plan(plan_id, pricing_method="MARKET_COMP")
        assert market["converted_base_rate_psf"] == pytest.approx(
            10.76, abs=0.005
        ), (
            f"MARKET_COMP must convert to max(6.00 asking, 10.25 x 1.05) = "
            f"10.76, got {market['converted_base_rate_psf']}"
        )
        assert (
            market["converted_base_rate_psf"]
            != yoc["converted_base_rate_psf"]
        ), "Identical cost inputs must produce a different rent per variant"
        assert market["total_project_cost"] == pytest.approx(
            yoc["total_project_cost"], abs=0.005
        ), (
            "total_project_cost is computed before variant selection and must "
            "not differ between variants"
        )
        assert market["total_project_cost"] == pytest.approx(
            12814064.36, abs=0.005
        )


class TestTwoPassCircularOrder:
    """The two-pass evaluation order pins the commission-on-provisional-rent
    estimate (PRD §3.5)."""

    def _price_canonical(self, api):
        bundle = setup_executed_loi(commission_basis="GROSS_AGGREGATE")
        return price_plan(bundle["plan"]["id"], pricing_method="YIELD_ON_COST")

    def test_pass_one_provisional_rate_and_commission_estimate(self, api):
        """PRD §3.5: "In pass one, the base cost is the sum of
        `hard_cost_total` and `soft_cost_total`, grown by `contingency_pct`;
        `provisional_base_rate_psf` is that base cost multiplied by the
        eight-percent target yield and divided by the linked LOI's
        `leased_sf`, rounded half-up to cents; a provisional aggregate rent is
        then computed with the aggregate formula of §3.3 at that provisional
        rate over the LOI's `leased_sf`, `term_years`, and `escalation_pct`;
        and `commission_cost_estimate` is four percent of the provisional
        aggregate, rounded half-up to cents."

        Design: Difficulty/combinatorial_formula/bts_two_pass_circular_order
        """
        priced = self._price_canonical(api)
        assert priced["provisional_base_rate_psf"] == pytest.approx(
            10.08, abs=0.005
        ), (
            f"12600000.00 x 0.08 / 100000 must be 10.08, got "
            f"{priced['provisional_base_rate_psf']}"
        )
        assert priced["commission_cost_estimate"] == pytest.approx(
            214064.36, abs=0.005
        ), (
            f"4% of the provisional aggregate 5351608.90 must be 214064.36, "
            f"got {priced['commission_cost_estimate']}"
        )

    def test_pass_two_total_cost_and_yield(self, api):
        """PRD §3.5: "In pass two, `total_project_cost` is the base cost plus
        `commission_cost_estimate`" and "Finally, `yield_on_cost` is
        `converted_base_rate_psf` multiplied by `leased_sf` and divided by
        `total_project_cost`, rounded half-up to four decimal places."

        Design: Difficulty/combinatorial_formula/bts_two_pass_circular_order
        """
        priced = self._price_canonical(api)
        assert priced["total_project_cost"] == pytest.approx(
            12814064.36, abs=0.005
        ), (
            f"12600000.00 + 214064.36 must be 12814064.36, got "
            f"{priced['total_project_cost']}"
        )
        assert priced["converted_base_rate_psf"] == pytest.approx(
            10.25, abs=0.005
        )
        assert priced["yield_on_cost"] == pytest.approx(0.0800, abs=0.00005), (
            f"10.25 x 100000 / 12814064.36 rounded to 4dp must be 0.0800, "
            f"got {priced['yield_on_cost']}"
        )


class TestApprovalCap:
    def test_approve_at_exact_overrun_cap(self, api):
        """PRD §3.5: "Approval is the `AssetManager`'s second signature,
        allowed from `PRICED` only when `converted_base_rate_psf` is no more
        than one hundred ten percent of the linked LOI's `base_rate_psf` — the
        cap computed by multiplying the LOI's base rate by 1.10 and rounding
        half-up to cents".

        MARKET_COMP on a 13.20-asking site converts to exactly 13.20 ==
        round(1.10 x 12.00, 2); the cap is inclusive.

        Design: Difficulty/boundary_precision_check/approve_at_exact_overrun_cap
        """
        bundle = setup_executed_bolt_loi()
        priced = price_plan(bundle["plan"]["id"], pricing_method="MARKET_COMP")
        assert priced["converted_base_rate_psf"] == pytest.approx(
            13.20, abs=0.005
        ), (
            f"max(13.20 asking, 10.25 x 1.05 = 10.76) must be 13.20, got "
            f"{priced['converted_base_rate_psf']}"
        )
        approved = validate_success(api.approve_bts_plan(priced["id"], AM))
        assert approved["status"] in ("APPROVED", "DELIVERED"), (
            f"Approval at exact cap equality must succeed (no "
            f"ERR_RENT_CONVERSION_OVER_RUN), got {approved['status']}"
        )

    def test_approve_at_exact_cap_reports_converted_rate(self, api):
        """PRD §3.5: "Under `MARKET_COMP`, `converted_base_rate_psf` is the
        greater of the linked site's `asking_rate_psf` and the yield-on-cost
        rate grown by a five-percent market markup and rounded half-up to
        cents".

        Design: Difficulty/boundary_precision_check/approve_at_exact_overrun_cap
        """
        bundle = setup_executed_bolt_loi()
        priced = price_plan(bundle["plan"]["id"], pricing_method="MARKET_COMP")
        # 13.20 > 10.76: the market floor, not the marked-up yield rate, wins.
        assert priced["converted_base_rate_psf"] == pytest.approx(
            13.20, abs=0.005
        )
        cap = round(1.10 * 12.00, 2)
        assert cap == pytest.approx(13.20, abs=0.005)
        approved = validate_success(api.approve_bts_plan(priced["id"], AM))
        assert approved["status"] in ("APPROVED", "DELIVERED")

    def test_rent_conversion_over_run_at_approve_returns_422(self, api):
        """PRD §3.5: "with an overrun rejected as
        `ERR_RENT_CONVERSION_OVER_RUN` (422)."

        Asking 13.21 converts to 13.21 > cap 13.20 (1.10 x 12.00) — one cent
        over the inclusive boundary flips approval to the overrun error.

        Design: Corner/validations/rent_conversion_over_run_at_approve_returns_422
        """
        req = create_bolt_requirement()
        site = create_bts_site(site_name="Premium BTS Site",
                               asking_rate_psf=13.21)
        create_completed_tour(
            site["id"], req["id"], REP_1,
            start_at="2026-08-11T10:00:00Z", end_at="2026-08-11T11:00:00Z",
        )
        loi = create_accepted_loi(
            req["id"], site["id"], REP_1, base_rate_psf=12.00,
        )
        clear_both_reviews(site["id"], req["id"])
        validate_success(api.execute_loi(loi["id"], AM))
        plan = get_plan_for_loi(loi["id"])
        priced = price_plan(plan["id"], pricing_method="MARKET_COMP")
        assert priced["converted_base_rate_psf"] == pytest.approx(
            13.21, abs=0.005
        )
        resp = api.approve_bts_plan(plan["id"], AM)
        validate_error(resp, ApiErrorId.ERR_RENT_CONVERSION_OVER_RUN)
        after = validate_success(api.get_bts_plan(plan["id"], PM))
        assert after["status"] == "PRICED", (
            "An overrun-rejected approval must leave the plan PRICED"
        )

    def test_projectmanager_cannot_approve_plan_returns_forbidden(self, api):
        """PRD §2.1: "`AssetManager` — the developer-side final approver:
        executes accepted LOIs, approves build-to-suit pricing, and operates
        the logical clock." and "A request whose role is not authorized for
        the endpoint it targets is rejected with `ERR_FORBIDDEN` (HTTP 403)".

        Design: Corner/rbac/projectmanager_cannot_approve_plan_returns_forbidden
        """
        bundle = setup_executed_bolt_loi()
        priced = price_plan(bundle["plan"]["id"], pricing_method="YIELD_ON_COST")
        resp = api.approve_bts_plan(priced["id"], PM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api.get_bts_plan(priced["id"], PM))
        assert after["status"] == "PRICED"


class TestDeliveryCascade:
    def test_delivery_completion_three_hop(self, api):
        """PRD §3.5: "When a completion clears the last `PENDING` milestone of
        an `APPROVED` plan, the plan bubbles up `APPROVED` → `DELIVERED`
        within the same request." and "At `DELIVERED`, the linked LOI's
        `rent_commencement_date` — null until this moment — is set to the
        `actual_date` of the plan's `SUBSTANTIAL_COMPLETION` milestone, and
        its `abatement_days` is set to the extra free-rent days owed for late
        delivery: the whole-day difference between that milestone's
        `actual_date` and its `planned_date`, reduced by a thirty-day grace
        and floored at zero." and "The site then moves `COMMITTED` →
        `LEASED`".

        Design: Difficulty/transitive_cascade/delivery_completion_three_hop
        """
        bundle = setup_approved_plan_with_sc_milestone()
        completed = validate_success(
            api.complete_delivery_milestone(
                bundle["milestone"]["id"],
                {"actual_date": "2027-04-15T00:00:00Z"},
                PM,
            )
        )
        assert completed["status"] == "COMPLETE"

        plan = validate_success(api.get_bts_plan(bundle["plan"]["id"], PM))
        assert plan["status"] == "DELIVERED", (
            f"Completing the last PENDING milestone of an APPROVED plan must "
            f"bubble it to DELIVERED, got {plan['status']}"
        )

        loi = validate_success(api.get_loi(bundle["loi"]["id"], LM))
        assert_same_instant(
            loi["rent_commencement_date"], "2027-04-15T00:00:00Z"
        )
        assert loi["abatement_days"] == 15, (
            f"45-day delay minus the 30-day grace must yield 15 abatement "
            f"days, got {loi['abatement_days']}"
        )

        site = validate_success(api.get_site(bundle["site"]["id"], LM))
        assert site["status"] == "LEASED"

    def test_delivery_flips_installment_2_due_on_both_invoices(self, api):
        """PRD §3.5: "The site then moves `COMMITTED` → `LEASED`, and that
        transition flips `installment_2_due` to true on every commission
        invoice of the linked LOI — the third and final cascade link."

        Design: Difficulty/transitive_cascade/delivery_completion_three_hop
        """
        bundle = setup_approved_plan_with_sc_milestone()
        validate_success(
            api.complete_delivery_milestone(
                bundle["milestone"]["id"],
                {"actual_date": "2027-04-15T00:00:00Z"},
                PM,
            )
        )
        invoices = validate_success(
            api.list_commission_invoices(LM, params={"loi_id": bundle["loi"]["id"]})
        )
        assert len(invoices) == 2
        for inv in invoices:
            assert inv["installment_2_due"] is True, (
                f"installment_2_due must flip to true on the {inv['broker_side']} "
                f"invoice once the site reaches LEASED"
            )


class TestAbatementBoundary:
    def test_abatement_grace_boundary_30_days(self, api):
        """PRD §3.5: "Exactly thirty days late yields zero abatement days;
        thirty-one days late yields one."

        Design: Corner/calculations/abatement_grace_boundary_30_days
        """
        bundle = setup_approved_plan_with_sc_milestone()
        validate_success(
            api.complete_delivery_milestone(
                bundle["milestone"]["id"],
                {"actual_date": "2027-03-31T00:00:00Z"},
                PM,
            )
        )
        plan = validate_success(api.get_bts_plan(bundle["plan"]["id"], PM))
        assert plan["status"] == "DELIVERED"
        loi = validate_success(api.get_loi(bundle["loi"]["id"], LM))
        assert loi["abatement_days"] == 0, (
            f"A 30-day delay is exactly the grace: abatement_days must be 0, "
            f"got {loi['abatement_days']}"
        )
        assert_same_instant(
            loi["rent_commencement_date"], "2027-03-31T00:00:00Z"
        )


class TestMilestones:
    def test_milestone_complete_twice_returns_invalid_state(self, api):
        """PRD §3.5: "Completing one records the payload's `actual_date` as
        the milestone's `actual_date` and moves it `PENDING` → `COMPLETE`".
        PRD §2.8: "The requested transition must be declared from the entity's
        current status; terminal states accept no further transitions —
        otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/milestone_complete_twice_returns_invalid_state
        """
        bundle = setup_executed_bolt_loi()
        milestone = validate_success(
            api.create_delivery_milestone(
                create_milestone_payload(
                    bundle["plan"]["id"], milestone_type="SHELL",
                    planned_date="2027-02-01T00:00:00Z",
                ),
                PM,
            ),
            201,
        )
        first = validate_success(
            api.complete_delivery_milestone(
                milestone["id"], {"actual_date": "2027-02-03T00:00:00Z"}, PM
            )
        )
        assert first["status"] == "COMPLETE"
        resp = api.complete_delivery_milestone(
            milestone["id"], {"actual_date": "2027-02-04T00:00:00Z"}, PM
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_delivery_milestone(milestone["id"], PM))
        assert after["actual_date"] == first["actual_date"], (
            "The second (rejected) completion must not overwrite actual_date"
        )

    def test_duplicate_milestone_type_returns_409(self, api):
        """PRD §3.5: "the plan must be in `SCHEMATIC`, `PRICED`, or
        `APPROVED`, and each `milestone_type` may appear only once per plan —
        a wrong plan status or a repeated type is rejected alike with
        `ERR_DUPLICATE_MILESTONE` (409)."

        Design: Corner/validations/duplicate_milestone_type_returns_409
        """
        bundle = setup_executed_bolt_loi()
        validate_success(
            api.create_delivery_milestone(
                create_milestone_payload(bundle["plan"]["id"]), PM
            ),
            201,
        )
        resp = api.create_delivery_milestone(
            create_milestone_payload(
                bundle["plan"]["id"], planned_date="2027-03-15T00:00:00Z"
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MILESTONE)
