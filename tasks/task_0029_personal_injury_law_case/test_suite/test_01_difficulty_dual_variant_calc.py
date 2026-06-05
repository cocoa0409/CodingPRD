"""Difficulty Rule 1 — dual_variant_calc.

Two valid algorithms that consume the same input set produce demonstrably
different numbers under PRD-pinned variants:

  • gross damages model: ECONOMIC_ONLY vs FULL_MODEL (PRD §3.3)
  • contingency fee: PRE_SUIT (33.33%) vs POST_SUIT (40.00%) (PRD §3.7)
"""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    register_client,
    sign_retainer,
    create_case,
    activate_case,
    register_provider,
    create_records_request,
    walk_records_request_to_reviewed,
    create_included_damages,
    create_demand_letter,
    send_demand_letter,
    create_offer,
    accept_offer,
    file_suit,
    get_case_version,
    get_disbursement_for_case,
    setup_active_case_with_reviewed_records,
)


# =============================================================================
# Instance: gross_damages_model_economic_only_vs_full_diverges
# =============================================================================


class TestGrossDamagesModelEconomicOnlyVsFullDiverges:
    """The same INCLUDED damages set on a single Case must produce two distinct
    gross totals — gross_economic_only_cents (excludes PAIN_SUFFERING) and
    gross_full_model_cents (includes PAIN_SUFFERING)."""

    def _setup_case_with_full_damages(self):
        """Active CA case + REVIEWED records + 5 INCLUDED items totaling 4_400_000."""
        client, case, provider, mrr = setup_active_case_with_reviewed_records()
        create_included_damages(case["id"], "MEDICAL_BILLS", 1_000_000)
        create_included_damages(case["id"], "LOST_WAGES", 500_000)
        create_included_damages(case["id"], "FUTURE_MEDICAL", 600_000)
        create_included_damages(case["id"], "PROPERTY", 300_000)
        create_included_damages(case["id"], "PAIN_SUFFERING", 2_000_000)
        return case

    def test_economic_only_excludes_pain_suffering_full_model_includes_it(self, api):
        """PRD §3.3: "The economic-only model sums `amount_cents` across `INCLUDED`
        items whose `category` is one of `MEDICAL_BILLS`, `LOST_WAGES`,
        `FUTURE_MEDICAL`, or `PROPERTY`; the full model adds the sum of
        `amount_cents` across `INCLUDED` items in `PAIN_SUFFERING`."

        Design: Difficulty/dual_variant_calc/gross_damages_model_economic_only_vs_full_diverges
        """
        case = self._setup_case_with_full_damages()
        from test_helpers import TEST_USERS
        res = api.get_damages_summary(case["id"], TEST_USERS["attorney_headers"])
        body = validate_success(res, 200)
        # economic_only = 1_000_000 + 500_000 + 600_000 + 300_000 = 2_400_000
        # full_model   = 2_400_000 + 2_000_000 (PAIN_SUFFERING) = 4_400_000
        assert body["gross_economic_only_cents"] == 2_400_000
        assert body["gross_full_model_cents"] == 4_400_000
        assert body["included_damages_total_cents"] == 4_400_000

    def test_two_variants_diverge_by_exactly_the_pain_suffering_sum(self, api):
        """PRD §3.3: "The economic-only model sums `amount_cents` across `INCLUDED`
        items whose `category` is one of `MEDICAL_BILLS`, `LOST_WAGES`,
        `FUTURE_MEDICAL`, or `PROPERTY`; the full model adds the sum of
        `amount_cents` across `INCLUDED` items in `PAIN_SUFFERING`."

        Design: Difficulty/dual_variant_calc/gross_damages_model_economic_only_vs_full_diverges
        """
        case = self._setup_case_with_full_damages()
        from test_helpers import TEST_USERS
        body = validate_success(
            api.get_damages_summary(case["id"], TEST_USERS["attorney_headers"]),
            200,
        )
        # Divergence between the two variants must equal the PAIN_SUFFERING contribution.
        assert body["gross_full_model_cents"] - body["gross_economic_only_cents"] == 2_000_000


# =============================================================================
# Instance: contingency_fee_pre_suit_vs_post_suit_diverges
# =============================================================================


class TestContingencyFeePreSuitVsPostSuitDiverges:
    """The same gross_settlement_cents (6_000_000) yields a different
    contingency_fee_cents depending on Case.filed_in_court at the moment of accept:
    1_999_800 pre-suit (0.3333) vs 2_400_000 post-suit (0.40)."""

    def _settle_at_gross(self, gross_cents: int, file_before_accept: bool,
                          email_prefix: str):
        """Build a case, send demand, post a CARRIER offer at gross_cents,
        optionally file suit, then accept. Returns the Disbursement.
        """
        # Fresh client/case.
        c = register_client(email=f"{email_prefix}@example.com")
        sign_retainer(c["id"])
        case = create_case(c["id"], accident_date="2024-06-15", jurisdiction="CA")
        activate_case(case["id"])
        provider = register_provider()
        mrr = create_records_request(case["id"], provider["id"])
        walk_records_request_to_reviewed(mrr["id"])
        create_included_damages(case["id"], "MEDICAL_BILLS", 1_000_000)
        dl = create_demand_letter(case["id"], pain_multiplier=1.5,
                                   drafter_user_id=f"drafter-{email_prefix}")
        send_demand_letter(dl["id"], partner_user_id=f"partner-{email_prefix}")
        offer = create_offer(case["id"], gross_cents, "CARRIER")
        if file_before_accept:
            file_suit(case["id"])
        case_v = get_case_version(case["id"])
        accept_offer(offer["id"], case_v,
                     partner_user_id=f"partner-{email_prefix}")
        return get_disbursement_for_case(case["id"])

    def test_pre_suit_fee_is_3333_basis_points_of_gross(self, api):
        """PRD §3.7: "The fee rate is a dual-variant: if the case has not been
        filed in court at the moment of accept — that is, if the case's
        `filed_in_court` flag is `false` — the rate is `0.3333` (the pre-suit
        rate); if suit has been filed (`filed_in_court` is `true`), the rate is
        `0.40` (the post-suit rate)."
        PRD §3.7: "The `contingency_fee_cents` is computed as the product of
        `gross_settlement_cents` and the applicable rate, with the
        multiplication performed as a single Decimal operation against integer
        cents, rounded half-up once at the end — there is no per-line rounding
        inside the fee."
        PRD §2.10: "Tests drive it forward with a `PlatformAdmin`-only setter
        endpoint that takes a `to_iso8601` value."

        Design: Difficulty/dual_variant_calc/contingency_fee_pre_suit_vs_post_suit_diverges
        """
        set_clock("2026-01-01T00:00:00Z")
        disb_a = self._settle_at_gross(6_000_000, file_before_accept=False,
                                         email_prefix="presuit")
        # 6_000_000 * 0.3333 = 1_999_800
        assert disb_a["contingency_fee_cents"] == 1_999_800
        assert disb_a["gross_settlement_cents"] == 6_000_000

    def test_post_suit_fee_is_4000_basis_points_of_gross(self, api):
        """PRD §3.7: "The fee rate is a dual-variant: if the case has not been
        filed in court at the moment of accept — that is, if the case's
        `filed_in_court` flag is `false` — the rate is `0.3333` (the pre-suit
        rate); if suit has been filed (`filed_in_court` is `true`), the rate is
        `0.40` (the post-suit rate)."
        PRD §3.8: "On success, the case moves `IN_NEGOTIATION → LITIGATION`,
        `Case.filed_in_court` is set to `true`, a `CourtEvent` of `event_type`
        `FILING` is created in `status` `OCCURRED` with `scheduled_at` equal to
        the current clock value, and `Case.version` is incremented by one."

        Design: Difficulty/dual_variant_calc/contingency_fee_pre_suit_vs_post_suit_diverges
        """
        set_clock("2026-01-01T00:00:00Z")
        disb_b = self._settle_at_gross(6_000_000, file_before_accept=True,
                                         email_prefix="postsuit")
        # 6_000_000 * 0.40 = 2_400_000
        assert disb_b["contingency_fee_cents"] == 2_400_000
        assert disb_b["gross_settlement_cents"] == 6_000_000

    def test_two_fee_variants_diverge_on_identical_gross(self, api):
        """PRD §3.7: "The same gross settlement amount produces a smaller fee
        under the pre-suit rate than under the post-suit rate, which means a
        pre-suit acceptance leaves more dollars in the lien pool and ultimately
        for the client than the same headline number after suit has been filed."

        Design: Difficulty/dual_variant_calc/contingency_fee_pre_suit_vs_post_suit_diverges
        """
        set_clock("2026-01-01T00:00:00Z")
        disb_a = self._settle_at_gross(6_000_000, file_before_accept=False,
                                         email_prefix="pre2")
        set_clock("2026-01-01T00:00:00Z")
        disb_b = self._settle_at_gross(6_000_000, file_before_accept=True,
                                         email_prefix="post2")
        # Post-suit fee strictly exceeds pre-suit fee on the same gross.
        assert disb_b["contingency_fee_cents"] > disb_a["contingency_fee_cents"]
        assert disb_b["contingency_fee_cents"] - disb_a["contingency_fee_cents"] == 400_200
