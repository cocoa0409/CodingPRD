"""Crop insurance: filing-time pinning, segregation of duties, duplicate-open
gate, payment gate, and the preliminary-vs-final indemnity variants."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_insurance_claim_payload, create_kiln, create_dried_lot,
    file_claim, file_claim_on_growing_plan, drive_claim_to_approved,
    make_farm_manager_headers, make_insurance_adjuster_headers,
    assert_insurance_claim, TEST_USERS,
)

FM = TEST_USERS["farm_manager_headers"]
IA = TEST_USERS["insurance_adjuster_headers"]


class TestFilingPinsGuaranteeAndEstimate:
    def test_default_coverage_applied(self, api, farm_manager_headers):
        """PRD §3.8: "optionally the `coverage_pct`, the share of the guarantee
        yield being insured, which must be greater than 0 and at most 1 and
        defaults to 0.75 when omitted." and "The `guarantee_lbs` is the plan's
        `planned_acreage` times the same per-acre base yield table used for
        projections — 1800 for `CASCADE` ... — times the `coverage_pct`, rounded
        half-up to a whole pound." 40 x 1800 x 0.75 = 54000.

        Design: Corner/entities/claim_default_coverage_applied
        """
        ctx = file_claim_on_growing_plan(filer_user_id="grower-1",
                                         price_election_cents_per_lb=300)
        claim = ctx["claim"]
        assert_insurance_claim(claim)
        assert claim["coverage_pct"] == 0.75
        assert claim["guarantee_lbs"] == 54000
        assert claim["filed_by_user_id"] == "grower-1"

    def test_preliminary_estimate_uses_projected_yield(self, api):
        """PRD §3.8: "The `indemnity_estimate_cents` is the preliminary indemnity
        variant: the greater of zero and the `guarantee_lbs` minus the plan's
        `projected_yield_lbs`, that difference times the
        `price_election_cents_per_lb`." max(0, 54000 - 72000) x 300 = 0.

        Design: Difficulty/dual_variant_calc/insurance_indemnity_preliminary_vs_final
        """
        ctx = file_claim_on_growing_plan(filer_user_id="grower-1",
                                         price_election_cents_per_lb=300)
        claim = ctx["claim"]
        assert ctx["plan"]["projected_yield_lbs"] == 72000
        assert claim["guarantee_lbs"] == 54000
        assert claim["indemnity_estimate_cents"] == 0
        assert claim["indemnity_final_cents"] is None, (
            "the final variant arrives only at payment")


class TestSegregationOfDuties:
    def test_filer_cannot_review_own_claim(self, api):
        """PRD §3.8: "All three adjuster actions enforce segregation of duties:
        the caller's `X-User-ID` must differ from the claim's
        `filed_by_user_id`, and a self-review, self-decision, or self-payment is
        rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/claim_segregation_of_duties
        """
        ctx = file_claim_on_growing_plan(filer_user_id="grower-1")
        claim_id = ctx["claim"]["id"]
        self_review = api.begin_review_claim(
            claim_id, make_insurance_adjuster_headers("grower-1"))
        validate_error(self_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        reviewed = validate_success(api.begin_review_claim(
            claim_id, make_insurance_adjuster_headers("adjuster-9")), 200)
        assert reviewed["status"] == "UNDER_REVIEW"


class TestOpenClaimGate:
    def test_second_open_claim_rejected(self, api):
        """PRD §3.8: "A plan carries at most one open claim at a time — one in
        `FILED`, `UNDER_REVIEW`, or `APPROVED` — and a second filing is rejected
        with `ERR_DUPLICATE_CLAIM`."

        Design: Corner/validations/duplicate_open_claim_rejected
        """
        ctx = file_claim_on_growing_plan(filer_user_id="grower-1",
                                         price_election_cents_per_lb=300)
        res = api.create_insurance_claim(
            create_insurance_claim_payload(ctx["plan"]["id"],
                                           price_election_cents_per_lb=310),
            make_farm_manager_headers("grower-1"))
        validate_error(res, ApiErrorId.ERR_DUPLICATE_CLAIM)


class TestPaymentGate:
    def test_pay_blocked_until_plan_complete(self, api, farm_manager_headers):
        """PRD §3.8: "Payment carries one further gate: the linked plan must be
        `COMPLETE`, otherwise `ERR_PLAN_NOT_COMPLETE`, because the final
        indemnity needs the kiln-dried actuals."

        Design: Corner/validations/pay_blocked_plan_not_complete
        """
        ctx = file_claim_on_growing_plan(filer_user_id="grower-1")
        claim_id = ctx["claim"]["id"]
        # Plan advances to HARVESTING — still not COMPLETE.
        validate_success(api.open_harvest(ctx["plan"]["id"], farm_manager_headers), 200)
        drive_claim_to_approved(claim_id, adjuster_user_id="adjuster-9")
        res = api.pay_claim(claim_id, make_insurance_adjuster_headers("adjuster-9"))
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_COMPLETE)
        after = validate_success(api.get_insurance_claim(claim_id, IA), 200)
        assert after["status"] == "APPROVED"


class TestIndemnityVariants:
    def test_payment_computes_final_variant_and_estimate_stays_frozen(
            self, api, farm_manager_headers):
        """PRD §3.8: "A successful payment computes `indemnity_final_cents` as
        the final variant: the greater of zero and the `guarantee_lbs` minus the
        plan's `actual_yield_lbs`, times the `price_election_cents_per_lb` —
        diverging from the filing estimate whenever actual production differed
        from the projection." and the estimate "is computed once at filing,
        stored, and not recomputed later — completing the plan does not touch
        it". Actuals 50000 against guarantee 54000 at 300 cents: (54000 - 50000)
        x 300 = 1200000 while the estimate stays 0.

        Design: Difficulty/dual_variant_calc/insurance_indemnity_preliminary_vs_final
        """
        ctx = file_claim_on_growing_plan(filer_user_id="grower-1",
                                         price_election_cents_per_lb=300)
        plan = ctx["plan"]
        claim_id = ctx["claim"]["id"]
        assert ctx["claim"]["indemnity_estimate_cents"] == 0

        # Bring the crop in: one lot dried to 50000 lbs, then complete the plan.
        validate_success(api.open_harvest(plan["id"], farm_manager_headers), 200)
        kiln = create_kiln()
        create_dried_lot(plan["id"], kiln["id"], wet_lbs=187500, dried_lbs=50000)
        completed = validate_success(api.complete_plan(plan["id"], farm_manager_headers), 200)
        assert completed["actual_yield_lbs"] == 50000

        drive_claim_to_approved(claim_id, adjuster_user_id="adjuster-9")
        paid = validate_success(api.pay_claim(
            claim_id, make_insurance_adjuster_headers("adjuster-9")), 200)
        assert paid["status"] == "PAID"
        assert paid["indemnity_final_cents"] == 1200000, (
            "final variant over kiln-dried actuals")
        after = validate_success(api.get_insurance_claim(claim_id, IA), 200)
        assert after["indemnity_estimate_cents"] == 0, (
            "the filing-time estimate is never recomputed")
