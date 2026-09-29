"""Loan sizing against three ceilings, the two allocation passes and the decision gates."""

import pytest

from test_helpers import (
    ApiErrorId,
    ApplicationStatus,
    DayCountConvention,
    ExperienceTier,
    PropertyStatus,
    RehabLineItemStatus,
    ScopeCode,
    api_client,
    assert_allocation_fields,
    assert_same_record,
    assert_sizing_fields,
    assert_system_fields,
    factories,
    fixtures,
    validate_error,
    validate_success,
    CREDIT_COMMITTEE,
    LOAN_OFFICER,
)

# 4/5 experience 32.00 + (696-600)/200 credit 12.00 + liquidity 12.00 +
# 6/10 career 9.00 = 65.00, which bands TIER_B.
TIER_B_SPONSOR = {
    "legal_entity_name": "Larkspur Holdings LLC",
    "flips_last_24mo": 4,
    "flips_lifetime": 6,
    "credit_score": 696,
    "liquidity_cents": 1_800_000,
    "declared_target_loan_cents": 30_000_000,
}


class TestTierConstantsFlipTheBindingCap:
    def test_tier_a_binds_on_the_after_repair_ceiling(self):
        """On a TIER_A sponsor the after-repair ceiling is the smallest of the three.

        Purchase advance plus rehab is 28,000,000 and loan-to-cost is 27,000,000,
        so the 75 percent after-repair figure of 24,000,000 is what binds. The PRD
        states: "`max_total_loan_cents` is the smallest of three quantities:
        `cap_purchase_advance_cents` plus `approved_rehab_total_cents`,
        `cap_ltc_cents`, and `cap_ltarv_cents`."

        Design: Difficulty/combinatorial_formula/mode_a_tier_constant_set_flips_binding_cap_in_nested_min
        """
        ctx = fixtures.build_sized_application()
        assert ctx.application["pricing_tier"] == ExperienceTier.TIER_A.value
        assert ctx.application["approved_rehab_total_cents"] == 10_000_000
        assert_sizing_fields(
            ctx.application,
            cap_purchase_advance_cents=18_000_000,
            cap_ltc_cents=27_000_000,
            cap_ltarv_cents=24_000_000,
            max_total_loan_cents=24_000_000,
            sized_initial_funding_cents=13_195_000,
            sized_interest_reserve_cents=758_713,
            sized_committed_amount_cents=23_953_713,
        )

    def test_the_tier_b_constant_set_moves_every_cap_and_shrinks_the_commitment(self):
        """Swapping TIER_A constants for TIER_B constants reprices all three ceilings.

        The same property and the same 10,000,000 rehab budget under TIER_B give
        17,000,000 / 25,500,000 / 22,400,000, so the binding ceiling is still the
        after-repair figure but 1,600,000 lower, and the sized commitment lands
        1,594,710 below the TIER_A answer. The PRD states: "The loan-to-purchase
        percentage is 90 percent for `TIER_A`, 85 percent for `TIER_B`, 80 percent
        for `TIER_C` and 70 percent for `TIER_D`".

        Design: Difficulty/combinatorial_formula/mode_a_tier_constant_set_flips_binding_cap_in_nested_min
        """
        tier_a = fixtures.build_sized_application()
        tier_b = fixtures.build_sized_application(
            clock=None, borrower_overrides=TIER_B_SPONSOR
        )
        assert tier_b.application["pricing_tier"] == ExperienceTier.TIER_B.value

        assert_sizing_fields(
            tier_b.application,
            cap_purchase_advance_cents=17_000_000,
            cap_ltc_cents=25_500_000,
            cap_ltarv_cents=22_400_000,
            max_total_loan_cents=22_400_000,
            sized_initial_funding_cents=11_687_000,
            sized_interest_reserve_cents=672_003,
            sized_committed_amount_cents=22_359_003,
        )
        spread = (
            tier_a.application["sized_committed_amount_cents"]
            - tier_b.application["sized_committed_amount_cents"]
        )
        assert spread == 1_594_710, (
            f"the two tier constant sets must differ by 1,594,710, got {spread}"
        )


class TestCircularReserveResolvesInOnePass:
    def test_the_sizing_pass_reprices_the_reserve_exactly_once(self):
        """The reduced principal is re-priced once and the leftover slack is kept.

        The first reserve of 805,000 on a 14,000,000 provisional advance overshoots
        the ceiling, so the excess is subtracted and the reserve is re-priced once
        on 13,195,000 to give 758,713 — leaving 46,287 of the 24,000,000 ceiling
        deliberately unused. The PRD states: "Otherwise the excess — the first
        committed total less `max_total_loan_cents` — is subtracted from the
        provisional figure to give `sized_initial_funding_cents`, and
        `sized_interest_reserve_cents` is re-priced on that reduced figure
        **exactly once**."

        Design: Difficulty/combinatorial_formula/mode_c_single_pass_circular_interest_reserve_not_fixed_point
        """
        ctx = fixtures.build_sized_application()
        assert_sizing_fields(
            ctx.application,
            max_total_loan_cents=24_000_000,
            sized_initial_funding_cents=13_195_000,
            sized_interest_reserve_cents=758_713,
            sized_committed_amount_cents=23_953_713,
        )
        slack = (
            ctx.application["max_total_loan_cents"]
            - ctx.application["sized_committed_amount_cents"]
        )
        assert slack == 46_287, (
            "a single bounded pass leaves 46,287 of residual slack unused, "
            f"got {slack}"
        )
        assert (
            ctx.application["sized_initial_funding_cents"]
            + ctx.application["sized_interest_reserve_cents"]
            + ctx.application["approved_rehab_total_cents"]
        ) == ctx.application["sized_committed_amount_cents"]

    def test_the_decision_pass_lands_on_the_approved_total_with_no_slack(self):
        """Carving the reserve out of the remainder diverges from the sizing answer.

        On the same 23,953,713 commitment the decision pass reports 13,151,375 of
        initial funding against the sizing pass's 13,195,000 — a deliberate
        43,625 divergence — and the three allocation buckets sum to the approved
        total exactly. The PRD states: "Because the reserve here is carved **out
        of** the non-rehab remainder rather than added **on top of** a capped
        purchase advance, the committed total lands on the approved amount
        exactly, with no slack — and the same application will therefore report a
        `sized_initial_funding_cents` that differs from its
        `alloc_initial_funding_cents`."

        Design: Difficulty/combinatorial_formula/mode_c_single_pass_circular_interest_reserve_not_fixed_point
        """
        ctx = fixtures.build_approved_application()
        assert ctx.application["status"] == ApplicationStatus.APPROVED.value
        assert_allocation_fields(
            ctx.application,
            approved_loan_amount_cents=23_953_713,
            alloc_initial_funding_cents=13_151_375,
            alloc_interest_reserve_cents=802_338,
            alloc_rehab_holdback_cents=10_000_000,
        )
        divergence = (
            ctx.application["sized_initial_funding_cents"]
            - ctx.application["alloc_initial_funding_cents"]
        )
        assert divergence == 43_625, (
            f"the two passes must diverge by 43,625, got {divergence}"
        )
        assert ctx.application["approved_rate_bps"] == 1150, (
            "approved_rate_bps defaults to quoted_rate_bps"
        )


class TestReserveRounding:
    def test_the_reserve_rounds_a_half_cent_up_at_sizing(self):
        """13,195,000 at 1150 bps over six months prices at 758,712.5 and rounds up.

        Half-up is the discriminating choice here: truncation and banker's
        rounding would both report 758,712. The PRD states: "for a given principal
        figure, the reserve is that principal multiplied by `quoted_rate_bps`
        divided by 10000, multiplied by `interest_reserve_months` divided by 12
        months, rounded half up to whole cents."

        Design: Corner/calculations/the_reserve_half_cent_rounds_up_at_sizing
        """
        ctx = fixtures.build_sized_application()
        unrounded = 13_195_000 * 1150 / 10_000 * 6 / 12
        assert unrounded == pytest.approx(758_712.5, abs=1e-6)
        assert ctx.application["sized_interest_reserve_cents"] == 758_713, (
            "a half cent must round up, not down and not to even"
        )


class TestSizingInputs:
    def test_sizing_counts_only_approved_scope_lines(self):
        """A rejected line drops out of the rehab budget the sizing is built on.

        With the electrical line rejected the approved rehab total is 7,500,000
        rather than 10,000,000, and every ceiling and bucket is rebuilt on that
        figure. The PRD states: "An approval recomputes the application's
        `approved_rehab_total_cents`, which is the sum of `approved_cost_cents`
        over lines whose `status` is `APPROVED` or `FULLY_RELEASED` and which
        starts at 0".

        Design: Corner/calculations/sizing_counts_only_approved_scope_lines
        """
        ctx = fixtures.build_origination(approve_scope=False)
        roof = ctx.line_by_code(ScopeCode.ROOF.value)
        kitchen = ctx.line_by_code(ScopeCode.KITCHEN.value)
        electrical = ctx.line_by_code(ScopeCode.ELECTRICAL.value)

        validate_error(
            api_client.size_application(
                ctx.application_id, factories.size_payload(), LOAN_OFFICER
            ),
            ApiErrorId.SCOPE_NOT_VALIDATED.value,
        )

        fixtures.approve_scope_line(roof["id"], 4_000_000)
        fixtures.approve_scope_line(kitchen["id"], 3_500_000)
        validate_success(
            api_client.review_rehab_line_item(
                electrical["id"], factories.scope_reject_payload(), LOAN_OFFICER
            ),
            200,
        )
        assert ctx.refresh_application()["approved_rehab_total_cents"] == 7_500_000

        fixtures.size_application(ctx)
        assert_sizing_fields(
            ctx.application,
            cap_purchase_advance_cents=18_000_000,
            cap_ltc_cents=24_750_000,
            cap_ltarv_cents=24_000_000,
            max_total_loan_cents=24_000_000,
            sized_initial_funding_cents=15_551_250,
            sized_interest_reserve_cents=894_197,
            sized_committed_amount_cents=23_945_447,
        )
        assert fixtures.read_line(electrical["id"])["status"] == (
            RehabLineItemStatus.REJECTED.value
        )

    def test_omitted_optional_fields_take_their_declared_defaults(self):
        """Three optional inputs each fall back to the value the PRD declares.

        Omitting `day_count_convention` gives `PER_DIEM_360`, omitting
        `approved_cost_cents` on an approval gives the borrower's proposed cost,
        and omitting `rate_bps` on a decision gives the quoted rate. The PRD
        states: "an optional `day_count_convention` of `PER_DIEM_360` or
        `PER_DIEM_365` that defaults to `PER_DIEM_360`".

        Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
        """
        fixtures.set_clock("2026-08-10T09:00:00Z")
        borrower = fixtures.build_approved_sponsor()
        subject = fixtures.register_property()
        contractor = fixtures.register_contractor()

        application = validate_success(
            api_client.create_application(
                factories.application_payload(
                    borrower["id"],
                    subject["id"],
                    **factories.omit("day_count_convention"),
                ),
                LOAN_OFFICER,
            ),
            201,
        )
        assert application["day_count_convention"] == (
            DayCountConvention.PER_DIEM_360.value
        )

        line = fixtures.add_scope_line(
            application["id"],
            fixtures.ScopeSpec("ROOF", 4_000_000, 0, "Tear-off and re-deck"),
            contractor["id"],
        )
        # A live sibling of equal cost so the concentration cap admits an approval at
        # the full proposed figure; it is rejected afterwards so the sizing can run.
        sibling = fixtures.add_scope_line(
            application["id"],
            fixtures.ScopeSpec("KITCHEN", 4_000_000, 0, "Cabinets and counters"),
            contractor["id"],
        )
        approved = validate_success(
            api_client.review_rehab_line_item(
                line["id"], {"decision": "APPROVE"}, LOAN_OFFICER
            ),
            200,
        )
        validate_success(
            api_client.review_rehab_line_item(
                sibling["id"], factories.scope_reject_payload(), LOAN_OFFICER
            ),
            200,
        )
        assert approved["approved_cost_cents"] == 4_000_000
        assert approved["reviewer_note"] is None

        validate_success(
            api_client.size_application(
                application["id"], factories.size_payload(), LOAN_OFFICER
            ),
            200,
        )
        decided = validate_success(
            api_client.decide_application(
                application["id"], {"decision": "APPROVE"}, CREDIT_COMMITTEE
            ),
            200,
        )
        assert decided["approved_rate_bps"] == 1150
        assert decided["decline_reason"] is None


class TestDecisionGates:
    def test_the_decision_chains_the_sizing_gate_then_the_sized_limit(self):
        """An unsized application, then an over-ceiling amount, then the approval.

        The committee cannot decide before the officer has sized, and once sized
        it cannot approve one cent above `max_total_loan_cents`. The PRD states:
        "the amount being approved — `approved_loan_amount_cents` when supplied,
        otherwise `sized_committed_amount_cents` — to be less than or equal to
        `max_total_loan_cents`; an amount above the ceiling is rejected with
        `ERR_LOAN_AMOUNT_EXCEEDS_LIMIT`."

        Design: Corner/validations/the_decision_gate_chains_sizing_then_the_sized_limit
        """
        ctx = fixtures.build_origination()
        assert ctx.application["status"] == ApplicationStatus.DRAFT.value

        validate_error(
            api_client.decide_application(
                ctx.application_id, factories.decision_payload(), CREDIT_COMMITTEE
            ),
            ApiErrorId.SIZING_REQUIRED.value,
        )

        fixtures.size_application(ctx)
        assert ctx.application["max_total_loan_cents"] == 24_000_000
        assert ctx.application["sized_committed_amount_cents"] == 23_953_713

        validate_error(
            api_client.decide_application(
                ctx.application_id,
                factories.decision_payload(approved_loan_amount_cents=24_000_001),
                CREDIT_COMMITTEE,
            ),
            ApiErrorId.LOAN_AMOUNT_EXCEEDS_LIMIT.value,
        )
        assert ctx.refresh_application()["status"] == ApplicationStatus.SIZED.value
        assert ctx.application["approved_loan_amount_cents"] is None

        approved = validate_success(
            api_client.decide_application(
                ctx.application_id,
                factories.decision_payload(approved_loan_amount_cents=24_000_000),
                CREDIT_COMMITTEE,
            ),
            200,
        )
        assert_allocation_fields(
            approved,
            approved_loan_amount_cents=24_000_000,
            alloc_initial_funding_cents=13_195_000,
            alloc_interest_reserve_cents=805_000,
            alloc_rehab_holdback_cents=10_000_000,
        )


class TestValuationRevisionCascade:
    def test_a_revaluation_stales_the_sizing_and_blocks_the_committee(self):
        """Moving the after-repair value invalidates a sizing computed against it.

        The sized application goes stale while its `sizing_arv_cents` sentinel
        still remembers 32,000,000, a sibling application still in `DRAFT` is
        untouched, and the committee is refused. The PRD states: "The field
        `sizing_stale` reads true while the application is `SIZED` and either the
        property's `arv_cents` no longer equals `sizing_arv_cents` or
        `approved_rehab_total_cents` has changed since the sizing ran."

        Design: Difficulty/transitive_cascade/valuation_revision_cascades_to_stale_sizing_and_blocks_decision
        """
        ctx = fixtures.build_sized_application()
        assert ctx.application["sizing_arv_cents"] == 32_000_000
        assert ctx.application["sizing_stale"] is False

        draft = fixtures.open_application(ctx.borrower_id, ctx.property_id)
        assert draft["status"] == ApplicationStatus.DRAFT.value

        revalued = validate_success(
            api_client.revalue_property(
                ctx.property_id,
                factories.valuation_payload(arv_cents=28_000_000),
                LOAN_OFFICER,
            ),
            200,
        )
        assert revalued["arv_cents"] == 28_000_000
        assert revalued["valuation_revision_count"] == 1

        stale = ctx.refresh_application()
        assert stale["sizing_stale"] is True
        assert stale["sizing_arv_cents"] == 32_000_000, (
            "the staleness sentinel must keep the value the sizing was run against"
        )
        assert stale["max_total_loan_cents"] == 24_000_000

        untouched = fixtures.read_application(draft["id"])
        assert untouched["sizing_stale"] is False, (
            "a DRAFT application is not marked stale by a revaluation"
        )

        validate_error(
            api_client.decide_application(
                ctx.application_id, factories.decision_payload(), CREDIT_COMMITTEE
            ),
            ApiErrorId.SIZING_STALE.value,
        )

    def test_resizing_against_the_new_appraisal_reprices_and_unblocks_the_decision(self):
        """The re-sizing drops the after-repair ceiling to 21,000,000 and clears staleness.

        Seventy-five percent of the revised 28,000,000 after-repair value is now
        the binding ceiling, taking the sized commitment down to 20,963,631, after
        which the committee can approve and the decision pass lands exactly.
        The PRD states: "`cap_ltarv_cents` is the floor of the
        loan-to-after-repair-value percentage applied to the property's
        `arv_cents`."

        Design: Difficulty/transitive_cascade/valuation_revision_cascades_to_stale_sizing_and_blocks_decision
        """
        ctx = fixtures.build_sized_application()
        validate_success(
            api_client.revalue_property(
                ctx.property_id,
                factories.valuation_payload(arv_cents=28_000_000),
                LOAN_OFFICER,
            ),
            200,
        )

        fixtures.size_application(ctx)
        assert_sizing_fields(
            ctx.application,
            cap_purchase_advance_cents=18_000_000,
            cap_ltc_cents=27_000_000,
            cap_ltarv_cents=21_000_000,
            max_total_loan_cents=21_000_000,
            sized_initial_funding_cents=10_367_500,
            sized_interest_reserve_cents=596_131,
            sized_committed_amount_cents=20_963_631,
            sizing_stale=False,
        )
        assert ctx.application["sizing_arv_cents"] == 28_000_000

        approved = validate_success(
            api_client.decide_application(
                ctx.application_id, factories.decision_payload(), CREDIT_COMMITTEE
            ),
            200,
        )
        assert approved["status"] == ApplicationStatus.APPROVED.value
        assert_allocation_fields(
            approved,
            approved_loan_amount_cents=20_963_631,
            alloc_initial_funding_cents=10_333_222,
            alloc_interest_reserve_cents=630_409,
            alloc_rehab_holdback_cents=10_000_000,
        )


class TestPropertyRoundTrip:
    def test_property_create_read_and_revalue_round_trip(self):
        """A property reads back exactly as filed, and a revaluation bumps once.

        The revaluation moves the after-repair value and the appraisal date while
        leaving the purchase price and as-is value alone, and it consumes exactly
        one version. The PRD states: "Each accepted revision increments
        `valuation_revision_count` by one and cascades outward: every application
        on that property whose `status` is `SIZED` has `sizing_stale` set to
        true, because the after-repair value that the sizing was computed against
        has moved."

        Design: Corner/endpoints/property_create_read_and_revalue_round_trip
        """
        fixtures.set_clock("2026-08-10T09:00:00Z")
        created = fixtures.register_property()
        assert_system_fields(created, expected_version=1)

        read = fixtures.read_property(created["id"])
        assert_same_record(created, read)
        assert read["purchase_price_cents"] == 20_000_000
        assert read["as_is_value_cents"] == 21_000_000
        assert read["arv_cents"] == 32_000_000
        assert read["appraisal_date"] == "2026-07-20"
        assert read["county_code"] == "MARICOPA"
        assert read["status"] == PropertyStatus.UNDER_CONTRACT.value
        assert read["valuation_revision_count"] == 0

        revalued = validate_success(
            api_client.revalue_property(
                created["id"],
                factories.valuation_payload(
                    appraisal_date="2026-09-15", arv_cents=28_000_000
                ),
                LOAN_OFFICER,
            ),
            200,
        )
        assert revalued["arv_cents"] == 28_000_000
        assert revalued["appraisal_date"] == "2026-09-15"
        assert revalued["purchase_price_cents"] == 20_000_000
        assert revalued["as_is_value_cents"] == 21_000_000
        assert revalued["valuation_revision_count"] == 1
        assert revalued["version"] == 2

        reread = fixtures.read_property(created["id"])
        assert_same_record(revalued, reread)
        assert reread["version"] == 2, "a read must not bump the version again"
