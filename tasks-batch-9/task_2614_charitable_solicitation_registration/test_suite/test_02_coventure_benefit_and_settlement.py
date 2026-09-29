"""Co-venture promotions: the benefit projected, the benefit owed, the window.

A cause-marketing campaign is priced twice — once looking forward at filing and
once looking back at settlement — and the same two endpoints of its window are
also what keep one commercial partner from running back-to-back campaigns.
"""

from test_helpers import (
    ApiErrorId,
    COMPLIANCE,
    activate_promotion,
    api_client,
    coventure_promotion_payload,
    create_fundraiser,
    create_officer,
    create_organization,
    draft_promotion,
    file_promotion,
    move_clock_to,
    read_promotion,
    register_fundraiser_in_state,
    seed_california_profile,
    settle_promotion,
    validate_error,
    validate_success,
)


def _coventure_scenario(register_partner: bool = True):
    """A charity, a certifying officer and a registered commercial partner."""
    seed_california_profile(coventure_filing_required=True, coventure_buffer_days=7)
    organization = create_organization(domicile_state_code="CA")
    certifier = create_officer(
        organization["id"], "Dana Reyes", "PRESIDENT", is_certifying_officer=True
    )
    coventurer = create_fundraiser(
        legal_name="BrightMart Retail Co",
        fundraiser_type="COMMERCIAL_COVENTURER",
        bond_amount_cents=2_500_000,
        bond_expires_at="2028-12-31T00:00:00Z",
    )
    if register_partner:
        register_fundraiser_in_state(
            coventurer["id"],
            "CA",
            bond_on_file_cents=2_500_000,
            expires_at="2027-12-31T00:00:00Z",
        )
    return organization, certifier, coventurer


class TestCoventureBenefitBases:
    """The projection and the settlement swap one operand, to great effect."""

    def test_filing_projects_the_benefit_on_the_dominant_per_unit_term(self):
        """PRD §3.7: "`projected_benefit_cents` is the forward-looking benefit
        estimate: the larger of `guaranteed_minimum_cents` and the product of
        `per_unit_cents` and `projected_units`. Both terms are integer cents, so
        no rounding arises." PRD §3.7 also states that
        "`disclosure_clause_required` is true when any state in `state_codes` has
        `coventure_filing_required` true".

        Design: Difficulty/dual_variant_calc/coventure_projected_vs_actual_benefit_divergence
        """
        organization, _certifier, coventurer = _coventure_scenario()

        promotion = draft_promotion(organization["id"], coventurer["id"], ["CA"])
        filed = validate_success(file_promotion(promotion["id"]))

        assert filed["projected_benefit_cents"] == 750_000, (
            "250 per unit across 3,000 projected units dominates the 500,000 "
            f"guarantee, got {filed['projected_benefit_cents']}"
        )
        assert filed["status"] == "FILED", (
            f"Filing drives DRAFT to FILED, got {filed['status']}"
        )
        assert filed["disclosure_clause_required"] is True, (
            "California requires a co-venture filing, so the percentage-to-charity "
            "clause is required"
        )
        assert filed["final_benefit_cents"] == 0, (
            "The actual-basis benefit is still unwritten before settlement, got "
            f"{filed['final_benefit_cents']}"
        )

    def test_settlement_recomputes_the_benefit_on_actual_units_so_the_guarantee_binds(
        self,
    ):
        """PRD §3.7: "`final_benefit_cents` is the larger of
        `guaranteed_minimum_cents` and the product of `per_unit_cents` and
        `actual_units`. This is the same formula as the projection with one
        operand swapped, and the swap is consequential — the guaranteed minimum
        can bind at settlement where it never bound at filing."

        Design: Difficulty/dual_variant_calc/coventure_projected_vs_actual_benefit_divergence
        """
        organization, certifier, coventurer = _coventure_scenario()
        promotion = draft_promotion(organization["id"], coventurer["id"], ["CA"])
        validate_success(file_promotion(promotion["id"]))
        move_clock_to("2026-09-05T00:00:00Z")
        validate_success(activate_promotion(promotion["id"]))
        move_clock_to("2026-10-01T00:00:00Z")

        settled = validate_success(
            settle_promotion(promotion["id"], certifier["id"], 1_600, 500_000)
        )

        assert settled["status"] == "SETTLED", (
            f"An exact remittance settles the promotion, got {settled['status']}"
        )
        assert settled["projected_benefit_cents"] == 750_000, (
            "The forward-looking projection is untouched by settlement, got "
            f"{settled['projected_benefit_cents']}"
        )
        assert settled["final_benefit_cents"] == 500_000, (
            "250 per unit across 1,600 actual units is only 400,000, so the "
            f"500,000 guarantee binds, got {settled['final_benefit_cents']}"
        )
        assert (
            settled["projected_benefit_cents"] - settled["final_benefit_cents"]
            == 250_000
        ), "The two bases diverge by 250,000 cents on identical stored inputs"
        assert settled["shortfall_cents"] == 0, (
            f"Nothing is owed after an exact remittance, got {settled['shortfall_cents']}"
        )


class TestRemittanceShortfallBoundary:
    """One cent decides whether a campaign closes clean or leaves a debt."""

    def _active_promotion(self, promo_start: str, promo_end: str, activate_at: str):
        organization, certifier, coventurer = _coventure_scenario()
        promotion = draft_promotion(
            organization["id"],
            coventurer["id"],
            ["CA"],
            promo_start=promo_start,
            promo_end=promo_end,
        )
        validate_success(file_promotion(promotion["id"]))
        move_clock_to(activate_at)
        validate_success(activate_promotion(promotion["id"]))
        return certifier, promotion

    def test_remitting_exactly_the_benefit_owed_settles_with_a_zero_shortfall(self):
        """PRD §3.7: "When the amount remitted is greater than or equal to the
        benefit owed, the promotion moves `ACTIVE` → `SETTLED`: `actual_units` and
        `remitted_cents` are written from the request, `final_benefit_cents` is
        written from the actual-basis computation, and `shortfall_cents` is set to
        0."

        Design: Difficulty/boundary_precision_check/coventure_remittance_shortfall_boundary_of_one_cent
        """
        certifier, promotion = self._active_promotion(
            "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z", "2026-09-05T00:00:00Z"
        )
        move_clock_to("2026-10-10T00:00:00Z")

        settled = validate_success(
            settle_promotion(promotion["id"], certifier["id"], 1_600, 500_000)
        )

        assert settled["status"] == "SETTLED", (
            f"500,000 remitted against 500,000 owed settles, got {settled['status']}"
        )
        assert settled["final_benefit_cents"] == 500_000, (
            "The guarantee binds over the 400,000 per-unit product, got "
            f"{settled['final_benefit_cents']}"
        )
        assert settled["shortfall_cents"] == 0, (
            f"An exact remittance leaves no shortfall, got {settled['shortfall_cents']}"
        )
        assert settled["remitted_cents"] == 500_000, (
            f"The remitted amount is recorded verbatim, got {settled['remitted_cents']}"
        )

    def test_remitting_one_cent_less_records_a_one_cent_debt_instead_of_an_error(self):
        """PRD §3.7: "When the amount remitted falls short of the benefit owed, the
        promotion moves `ACTIVE` → `DEFICIENT_REMITTANCE` instead: the same three
        fields are written, and `shortfall_cents` is set to the benefit owed minus
        the amount remitted. A shortfall is emphatically **not** an error — there
        is no rejection code for under-remittance, and implementations must not
        invent one; the deficiency is a state, and the state is the record of the
        debt."

        Design: Difficulty/boundary_precision_check/coventure_remittance_shortfall_boundary_of_one_cent
        """
        certifier, promotion = self._active_promotion(
            "2026-10-08T00:00:00Z", "2026-10-20T00:00:00Z", "2026-10-10T00:00:00Z"
        )
        move_clock_to("2026-10-21T00:00:00Z")

        deficient = validate_success(
            settle_promotion(promotion["id"], certifier["id"], 1_600, 499_999)
        )

        assert deficient["status"] == "DEFICIENT_REMITTANCE", (
            "499,999 against 500,000 owed is a deficiency, not a rejection, got "
            f"{deficient['status']}"
        )
        assert deficient["final_benefit_cents"] == 500_000, (
            "The comparison is against the guarantee-bound benefit, not the "
            f"400,000 per-unit product, got {deficient['final_benefit_cents']}"
        )
        assert deficient["shortfall_cents"] == 1, (
            f"500,000 owed minus 499,999 remitted, got {deficient['shortfall_cents']}"
        )
        assert deficient["actual_units"] == 1_600, (
            f"The reported units are recorded, got {deficient['actual_units']}"
        )


class TestPromotionWindowBufferBoundary:
    """Consecutive campaigns by one partner must be strictly more than the
    buffer apart."""

    def _incumbent_draft(self):
        organization, _certifier, coventurer = _coventure_scenario(
            register_partner=False
        )
        incumbent = draft_promotion(
            organization["id"],
            coventurer["id"],
            ["CA"],
            promo_start="2026-09-01T00:00:00Z",
            promo_end="2026-09-30T00:00:00Z",
        )
        return organization, coventurer, incumbent

    def test_starting_exactly_on_the_buffered_end_of_a_draft_campaign_is_a_conflict(
        self,
    ):
        """PRD §3.7: "the new promotion is rejected with
        `ERR_PROMOTION_WINDOW_CONFLICT` when the new `promo_start` falls at or
        before the existing `promo_end` advanced by the buffer **and** the
        existing `promo_start` falls at or before the new `promo_end` advanced by
        the buffer". The incumbent counts even in draft: "For every state shared
        with an existing promotion of the same `coventurer_id` whose `status` is
        `DRAFT`, `FILED` or `ACTIVE`, the two closed windows must be separated by
        strictly more than that state's `coventure_buffer_days` (default 0)."

        Design: Difficulty/resource_temporal_overlap/promotion_window_closed_interval_plus_buffer_day_boundary
        """
        organization, coventurer, incumbent = self._incumbent_draft()

        response = api_client.create_coventure_promotion(
            coventure_promotion_payload(
                organization["id"],
                coventurer["id"],
                ["CA"],
                promo_start="2026-10-07T00:00:00Z",
                promo_end="2026-10-15T00:00:00Z",
            ),
            COMPLIANCE,
        )

        validate_error(response, ApiErrorId.ERR_PROMOTION_WINDOW_CONFLICT.value)
        assert read_promotion(incumbent["id"])["status"] == "DRAFT", (
            "The rejected attempt leaves the incumbent promotion untouched"
        )

    def test_starting_one_day_past_the_buffer_clears_the_separation_rule(self):
        """PRD §3.7: "when either half of that condition fails the windows are far
        enough apart and the create proceeds." The window itself is inclusive:
        "Unlike a coverage interval, the promotion window is **closed at both
        ends**: both endpoints are inside it, and `promo_end` may equal
        `promo_start` for a single-day promotion."

        Design: Difficulty/resource_temporal_overlap/promotion_window_closed_interval_plus_buffer_day_boundary
        """
        organization, coventurer, incumbent = self._incumbent_draft()

        response = api_client.create_coventure_promotion(
            coventure_promotion_payload(
                organization["id"],
                coventurer["id"],
                ["CA"],
                promo_start="2026-10-08T00:00:00Z",
                promo_end="2026-10-16T00:00:00Z",
            ),
            COMPLIANCE,
        )

        accepted = validate_success(response, 201)

        assert accepted["status"] == "DRAFT", (
            f"A newly created promotion is born in DRAFT, got {accepted['status']}"
        )
        assert accepted["promo_start"] == "2026-10-08T00:00:00.000Z", (
            f"The requested start is stored verbatim, got {accepted['promo_start']}"
        )
        assert accepted["projected_benefit_cents"] == 750_000, (
            "250 per unit across 3,000 projected units, got "
            f"{accepted['projected_benefit_cents']}"
        )
        assert accepted["disclosure_clause_required"] is True, (
            "California requires a co-venture filing for this campaign"
        )
        assert read_promotion(incumbent["id"])["status"] == "DRAFT", (
            "The incumbent is unaffected by the accepted second campaign"
        )
