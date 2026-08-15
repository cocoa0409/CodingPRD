"""Cargo insurance quoting (pinned evaluation order) and claim settlement
waterfall."""
from test_helpers import (
    ApiErrorId,
    create_confirmed_booking,
    create_insurance_policy_payload,
    file_claim_under_review,
    setup_approved_claim,
    setup_bound_policy,
    setup_lcl_lane,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADJ_1, ADJ_2, BC, FC
from test_helpers.test_users import make_adjuster_headers


class TestInsuredValuePinnedOrder:
    """Standard LCL booking: 4000 kg / 6.0 cbm CONTRACT 9500/RT min 20000,
    freight base 57000 (BAF/THC/DOC excluded); cargo value 5000000."""

    def test_freight_base_and_insured_value(self, api):
        """PRD §3.13: "Second, the `freight_base_cents` is a snapshot of the
        booking's ocean-freight base component only — excluding the bunker
        adjustment, the terminal handling charge, the documentation fee, and
        any rollover fee."
        PRD §3.13: "Third, the `insured_value_cents` is the round-half-up
        result of multiplying the sum of `cargo_value_cents` and
        `freight_base_cents` by 1.10 (the CIF-plus-ten-percent markup)."

        Design: Difficulty/combinatorial_formula/insured_value_premium_pinned_evaluation_order_mode_c
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)

        policy = validate_success(
            api.create_insurance_policy(
                create_insurance_policy_payload(booking["id"],
                                                coverage_type="ALL_RISK",
                                                cargo_value_cents=5000000),
                BC),
            201)
        assert policy["freight_base_cents"] == 57000, (
            "ocean freight base only; BAF/THC/DOC excluded by the pinned order"
        )
        # round_half_up((5000000 + 57000) x 1.10) = 5562700.
        assert policy["insured_value_cents"] == 5562700

    def test_premium_applies_coverage_rate_with_minimum_floor(self, api):
        """PRD §3.13: "Fourth, the `premium_cents` is the greater of a
        2500-cent minimum premium and the round-half-up product of
        `insured_value_cents` and the coverage rate: 0.006 for `ALL_RISK`,
        0.004 for `WA`, and 0.0025 for `FPA`. The premium and insured value
        are frozen at `QUOTED` creation; although the premium later feeds the
        booking's FREIGHT invoice and the shipper's exposure, the exposure
        gate never feeds back into the premium computation."

        Design: Difficulty/combinatorial_formula/insured_value_premium_pinned_evaluation_order_mode_c
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)

        policy = validate_success(
            api.create_insurance_policy(
                create_insurance_policy_payload(booking["id"],
                                                coverage_type="ALL_RISK",
                                                cargo_value_cents=5000000),
                BC),
            201)
        # max(2500, round_half_up(5562700 x 0.006)) = round_half_up(33376.2).
        assert policy["premium_cents"] == 33376
        assert policy["status"] == "QUOTED"


class TestClaimSettlementWaterfall:
    def test_claim_fpa_partial_damage_settles_zero(self, api):
        """PRD §3.14: "if `claim_type` is `DELAY`, the settlement is zero —
        consequential loss is excluded on every coverage; otherwise, if
        `coverage_type` is `FPA` and `claim_type` is `DAMAGE` or `SHORTAGE`,
        the settlement is zero — FPA covers total loss only, so partial losses
        pay nothing regardless of the claimed amount; otherwise, the
        settlement is the greater of zero and the smaller of
        `claimed_amount_cents` and `insured_value_cents` minus the
        deductible."
        PRD §3.14: "for `FPA` coverage the `deductible_cents` is the greater
        of 100000 cents and the round-half-up product of `insured_value_cents`
        and 0.02."

        Design: Corner/calculations/claim_fpa_partial_damage_settles_zero
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)
        policy = setup_bound_policy(ctx, booking, coverage_type="FPA",
                                    cargo_value_cents=5000000)
        assert policy["insured_value_cents"] == 5562700
        # max(2500, round_half_up(5562700 x 0.0025)) = round_half_up(13906.75).
        assert policy["premium_cents"] == 13907

        claim = file_claim_under_review(policy, ctx["shipper"]["id"],
                                        claim_type="DAMAGE",
                                        claimed_amount_cents=400000)
        approved = validate_success(api.approve_claim(claim["id"], ADJ_2), 200)
        assert approved["status"] == "APPROVED"
        assert approved["settlement_amount_cents"] == 0, (
            "FPA excludes partial DAMAGE losses"
        )
        # max(100000, round_half_up(5562700 x 0.02)) = 111254.
        assert approved["deductible_cents"] == 111254

    def test_claim_settlement_waterfall_capped_at_insured_value(self, api):
        """PRD §3.14: "otherwise, the settlement is the greater of zero and
        the smaller of `claimed_amount_cents` and `insured_value_cents` minus
        the deductible."
        PRD §3.14: "for `ALL_RISK` and `WA` coverage the `deductible_cents` is
        the greater of 50000 cents and the round-half-up product of
        `insured_value_cents` and 0.01".

        Design: Corner/calculations/claim_settlement_waterfall_capped_at_insured_value
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)
        policy = setup_bound_policy(ctx, booking, coverage_type="ALL_RISK",
                                    cargo_value_cents=5000000)

        claim = file_claim_under_review(policy, ctx["shipper"]["id"],
                                        claim_type="LOSS",
                                        claimed_amount_cents=99999999)
        approved = validate_success(api.approve_claim(claim["id"], ADJ_2), 200)
        # max(50000, round_half_up(5562700 x 0.01)) = 55627.
        assert approved["deductible_cents"] == 55627
        # min(99999999, 5562700) - 55627: the min() clamps before subtraction.
        assert approved["settlement_amount_cents"] == 5507073

        settled = validate_success(api.settle_claim(claim["id"], FC), 200)
        assert settled["status"] == "SETTLED"

    def test_claim_delay_type_excluded_all_coverages(self, api):
        """PRD §3.14: "if `claim_type` is `DELAY`, the settlement is zero —
        consequential loss is excluded on every coverage".

        Design: Corner/calculations/claim_delay_type_excluded_all_coverages
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)
        policy = setup_bound_policy(ctx, booking, coverage_type="ALL_RISK",
                                    cargo_value_cents=5000000)

        claim = file_claim_under_review(policy, ctx["shipper"]["id"],
                                        claim_type="DELAY",
                                        claimed_amount_cents=100000)
        approved = validate_success(api.approve_claim(claim["id"], ADJ_2), 200)
        assert approved["status"] == "APPROVED"
        assert approved["settlement_amount_cents"] == 0, (
            "DELAY is excluded before the min()/deductible arithmetic"
        )


class TestClaimSegregationOfDuties:
    def test_sod_claim_reviewer_cannot_approve(self, api):
        """PRD §3.14: "Approval or denial is also a `ClaimsAdjuster` action,
        but the segregation-of-duties rule applies: the approving or denying
        adjuster's `X-User-ID` must differ from `reviewed_by_user_id`
        (otherwise `ERR_SEGREGATION_OF_DUTIES`), and the claim must currently
        be `UNDER_REVIEW` (otherwise `ERR_CLAIM_INVALID_STATE`)."

        Design: Corner/validations/sod_claim_reviewer_cannot_approve
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)
        policy = setup_bound_policy(ctx, booking, coverage_type="ALL_RISK",
                                    cargo_value_cents=5000000)
        claim = file_claim_under_review(policy, ctx["shipper"]["id"],
                                        claim_type="DAMAGE",
                                        claimed_amount_cents=400000,
                                        reviewed_by="adj_1")

        res = api.approve_claim(claim["id"], ADJ_1)
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=403)
        still = validate_success(api.get_claim(claim["id"], ADJ_1), 200)
        assert still["status"] == "UNDER_REVIEW"

        approved = validate_success(api.approve_claim(claim["id"], ADJ_2), 200)
        assert approved["status"] == "APPROVED"
        # min(400000, 5562700) - 55627 = 344373.
        assert approved["settlement_amount_cents"] == 344373

    def test_claims_adjuster_cannot_settle_claim(self, api):
        """PRD §3.14: "Settlement — a `FinanceController` action — transitions
        an `APPROVED` claim to `SETTLED` (any other state rejects with
        `ERR_CLAIM_INVALID_STATE`) and stamps `settled_at` with the logical
        clock."
        PRD §2.1: "A request whose role is not listed in the endpoint's
        authorized roles is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."

        Design: Corner/rbac/claims_adjuster_cannot_settle_claim
        """
        ctx = setup_approved_claim(claim_type="DAMAGE",
                                   claimed_amount_cents=400000)
        claim = ctx["claim"]
        assert claim["status"] == "APPROVED"

        res = api.settle_claim(claim["id"], make_adjuster_headers("adj_2"))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                       expected_status=403)
        still = validate_success(api.get_claim(claim["id"], ADJ_1), 200)
        assert still["status"] == "APPROVED"

        settled = validate_success(api.settle_claim(claim["id"], FC), 200)
        assert settled["status"] == "SETTLED"
        assert settled["settled_at"] is not None
