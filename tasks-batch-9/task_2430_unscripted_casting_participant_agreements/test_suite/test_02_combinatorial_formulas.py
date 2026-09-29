"""Formulas whose inputs interact rather than add: the stipend tier jump and
depiction branch, the trust installment rounding order, and the welfare band
rate that is read off the pre-surcharge subtotal.
"""

from test_helpers import (
    TEST_USERS,
    assert_money,
    get_production,
    setup_cleared_applicant,
    setup_docusoap_production,
    setup_drafted_agreement,
    setup_minor_protection,
    setup_planned_welfare_protocol,
    setup_production,
    setup_published_casting_call,
    validate_success,
)

BA1 = TEST_USERS["business_affairs_headers"]
BA2 = TEST_USERS["business_affairs_2_headers"]
WO1 = TEST_USERS["welfare_officer_headers"]

HIGH_STRESS = {
    "format_type": "COMPETITION_HIGH_STRESS",
    "jurisdiction_code": "CA",
    "episode_order": 10,
    "stipend_pool_cents": 50_000_000,
    "welfare_budget_cents": 10_000_000,
    "minor_participant_cap": 2,
}

COVERAGE = {
    "coverage_start_utc": "2026-09-15T00:00:00Z",
    "coverage_end_utc": "2026-12-15T00:00:00Z",
}


class TestStipendTierAndDepictionInteraction:
    """Five inputs interacting: episode count, tier multiplier, hazard uplift,
    depiction scope and the rounding order between them."""

    def test_tier_jump_and_depiction_branch_reshape_identical_provisionals(self, api):
        """PRD §3.6: "The tier multiplier is selected by the episode count used:
        a count of 4 or fewer takes a multiplier of 1.00, a count from 5 to 8
        inclusive takes 1.15, and a count of 9 or more takes 1.30."
        PRD §3.6: "The **hazard component** applies only to a production whose
        `format_type` is `COMPETITION_HIGH_STRESS`, where it is one tenth of the
        rounded base component, itself rounded half up to whole cents; for every
        other format it is zero."
        PRD §2.8: "In the stipend commitment computation, each component is
        rounded to whole cents **before** the components are summed, and the
        depiction adjustment is then applied to the already-rounded subtotal
        rather than to any individual component."

        Design: Difficulty/combinatorial_formula/stipend_formula_tier_jump_and_depiction_branch_mode_a
        """
        production = setup_production(title="Island Trials S2", **HIGH_STRESS)
        call = setup_published_casting_call(
            production["id"], min_age=18, max_age=45, exclusivity_window_days=0
        )
        cara = setup_cleared_applicant(
            call["id"], legal_name="Cara Lin", date_of_birth="1994-04-02"
        )
        dev = setup_cleared_applicant(
            call["id"], legal_name="Dev Roy", date_of_birth="1993-11-08"
        )

        terms = {
            "exclusivity_window_days": 0,
            "confidentiality_tier": "STANDARD",
            "stipend_structure": "PER_EPISODE",
            "base_stipend_cents": 300_000,
            "press_appearance_obligation_count": 0,
            "reunion_obligation": False,
        }
        cara_agreement = setup_drafted_agreement(
            cara["id"],
            production["id"],
            depiction_rights_scope="FULL",
            episodes_committed=4,
            **terms,
        )
        dev_agreement = setup_drafted_agreement(
            dev["id"],
            production["id"],
            depiction_rights_scope="PSEUDONYMIZED",
            episodes_committed=5,
            **terms,
        )

        cara_sent = validate_success(api.send_agreement(cara_agreement["id"], BA1))
        cara_done = validate_success(api.execute_agreement(cara_agreement["id"], BA2))
        dev_sent = validate_success(api.send_agreement(dev_agreement["id"], BA1))
        dev_done = validate_success(api.execute_agreement(dev_agreement["id"], BA2))

        # Both provisional variants use episode count max(n, 10) = 10, so they
        # land on tier 1.30 and are identical despite the differing terms.
        assert_money(cara_sent["provisional_stipend_cents"], 4_490_000, "Cara provisional")
        assert_money(dev_sent["provisional_stipend_cents"], 4_490_000, "Dev provisional")
        assert (
            cara_sent["provisional_stipend_cents"]
            == dev_sent["provisional_stipend_cents"]
        ), "the two provisional figures must be identical"

        # 4 episodes: 1,200,000 base + 120,000 hazard, FULL licence, no discount.
        assert_money(
            cara_done["total_stipend_commitment_cents"], 1_320_000, "Cara final"
        )
        # 5 episodes crosses to tier 1.15: 1,725,000 base + 172,500 hazard, then
        # a PSEUDONYMIZED reduction of 227,700 off the 1,897,500 subtotal.
        assert_money(dev_done["total_stipend_commitment_cents"], 1_669_800, "Dev final")

        rolled_up = get_production(production["id"])
        assert_money(
            rolled_up["stipend_committed_cents"], 2_989_800, "committed stipend"
        )

    def test_one_extra_episode_lifts_the_base_component_by_more_than_its_share(
        self, api
    ):
        """PRD §3.6: "The **base component** is `base_stipend_cents` multiplied
        by the episode count used, multiplied by that tier multiplier, rounded
        half up to whole cents."
        PRD §3.6: "The tier multiplier is selected by the episode count used: a
        count of 4 or fewer takes a multiplier of 1.00, a count from 5 to 8
        inclusive takes 1.15, and a count of 9 or more takes 1.30."

        Design: Difficulty/combinatorial_formula/stipend_formula_tier_jump_and_depiction_branch_mode_a
        """
        production = setup_production(title="Island Trials Tier", **HIGH_STRESS)
        call = setup_published_casting_call(
            production["id"], min_age=18, max_age=45, exclusivity_window_days=0
        )
        four = setup_cleared_applicant(
            call["id"], legal_name="Eli Marsh", date_of_birth="1992-01-05"
        )
        five = setup_cleared_applicant(
            call["id"], legal_name="Fay Odile", date_of_birth="1992-03-09"
        )

        terms = {
            "exclusivity_window_days": 0,
            "confidentiality_tier": "STANDARD",
            "depiction_rights_scope": "FULL",
            "stipend_structure": "PER_EPISODE",
            "base_stipend_cents": 300_000,
            "press_appearance_obligation_count": 0,
            "reunion_obligation": False,
        }
        agreement_four = setup_drafted_agreement(
            four["id"], production["id"], episodes_committed=4, **terms
        )
        agreement_five = setup_drafted_agreement(
            five["id"], production["id"], episodes_committed=5, **terms
        )

        validate_success(api.send_agreement(agreement_four["id"], BA1))
        done_four = validate_success(api.execute_agreement(agreement_four["id"], BA2))
        validate_success(api.send_agreement(agreement_five["id"], BA1))
        done_five = validate_success(api.execute_agreement(agreement_five["id"], BA2))

        assert_money(
            done_four["total_stipend_commitment_cents"], 1_320_000, "four-episode total"
        )
        # A 25 percent increase in episodes produces a 43.75 percent increase in
        # the committed figure, because the tier multiplier moves too.
        assert_money(
            done_five["total_stipend_commitment_cents"], 1_897_500, "five-episode total"
        )


class TestTrustInstallmentRoundingOrder:
    """The per-installment amount is rounded first; the total is a multiplication
    of that rounded figure and is never re-rounded."""

    def _minor_with_executed_agreement(self, api, title):
        production = setup_production(title=title, **HIGH_STRESS)
        call = setup_published_casting_call(
            production["id"], min_age=13, max_age=45, exclusivity_window_days=90
        )
        applicant = setup_cleared_applicant(
            call["id"],
            minor=True,
            legal_name="Hana Kim",
            date_of_birth="2011-05-20",
            guardian_name="Iris Kim",
        )
        protection = setup_minor_protection(
            applicant["id"],
            work_permit_number="CA-WP-88001",
            permit_expires_on="2027-03-31",
            education_hours_scheduled_weekly=15,
            trust_deposit_pct=0.15,
        )
        agreement = setup_drafted_agreement(
            applicant["id"],
            production["id"],
            exclusivity_window_days=90,
            confidentiality_tier="ENHANCED",
            depiction_rights_scope="LIMITED",
            stipend_structure="PER_EPISODE",
            base_stipend_cents=250_000,
            episodes_committed=6,
            press_appearance_obligation_count=2,
            reunion_obligation=True,
        )
        validate_success(api.send_agreement(agreement["id"], BA1))
        executed = validate_success(api.execute_agreement(agreement["id"], BA2))
        assert_money(
            executed["total_stipend_commitment_cents"], 2_106_625, "executed stipend"
        )
        return production, protection

    def test_six_installments_round_up_before_summation(self, api):
        """PRD §2.8: "In the minor trust deposit schedule, the per-installment
        amount is rounded half up **first** and the total is then obtained by
        multiplying that rounded installment by the installment count. The
        resulting total is never re-rounded, and the alternative order — round
        the target, then divide — is incorrect."
        PRD §3.5: "That target is divided by the installment count and the
        quotient is rounded half up to whole cents to give
        `per_installment_cents`; `trust_deposited_cents` is then that rounded
        installment multiplied by the installment count, and it is not rounded
        again."

        Design: Difficulty/combinatorial_formula/trust_installments_rounded_per_installment_then_summed_mode_b
        """
        production, protection = self._minor_with_executed_agreement(
            api, "Teen Trials S1"
        )

        # Target 2,106,625 x 0.15 = 315,993.75; over six installments each is
        # 52,665.625, rounding half up to 52,666.
        # A deposit brings no new resource into existence — PRD §2.4 enumerates
        # every record type and none of them is a trust deposit — so the funded
        # packet comes back as an amendment under PRD §4's uniform status rule.
        deposited = validate_success(
            api.create_trust_deposit(protection["id"], {"installment_count": 6}, BA1),
            200,
        )
        assert_money(deposited["per_installment_cents"], 52_666, "per installment")
        assert_money(deposited["trust_deposited_cents"], 315_996, "trust deposited")
        assert deposited["trust_deposited_cents"] != 315_994, (
            "rounding the target before dividing would have produced 315,994"
        )
        assert deposited["installment_count"] == 6

        rolled_up = get_production(production["id"])
        assert_money(
            rolled_up["trust_escrow_balance_cents"], 315_996, "trust escrow balance"
        )

    def test_four_installments_round_down_and_undershoot_the_target(self, api):
        """PRD §2.8: "In the minor trust deposit schedule, the per-installment
        amount is rounded half up **first** and the total is then obtained by
        multiplying that rounded installment by the installment count. The
        resulting total is never re-rounded, and the alternative order — round
        the target, then divide — is incorrect."
        PRD §2.11: "Trust escrow is the sum of `trust_deposited_cents` over the
        minor-protection packets reachable from the production through its
        applicants' agreements whose packet `status` is `INCOMPLETE`, `COMPLETE`
        or `LAPSED`".

        Design: Difficulty/combinatorial_formula/trust_installments_rounded_per_installment_then_summed_mode_b
        """
        production, protection = self._minor_with_executed_agreement(
            api, "Teen Trials Four"
        )

        # 315,993.75 over four installments is 78,998.4375, rounding down to
        # 78,998 and summing to 315,992 — two cents short of the target, and
        # four cents short of what rounding the target first would have given.
        # As above: funding amends the packet rather than creating a record, so
        # PRD §4's uniform rule gives 200 OK.
        deposited = validate_success(
            api.create_trust_deposit(protection["id"], {"installment_count": 4}, BA1),
            200,
        )
        assert_money(deposited["per_installment_cents"], 78_998, "per installment")
        assert_money(deposited["trust_deposited_cents"], 315_992, "trust deposited")
        assert deposited["trust_deposited_cents"] != 315_996, (
            "rounding the target to 315,994 before dividing would have produced "
            "78,999 per installment and 315,996 in total"
        )

        rolled_up = get_production(production["id"])
        assert_money(
            rolled_up["trust_escrow_balance_cents"], 315_992, "trust escrow balance"
        )


class TestWelfareBandFromPreSurchargeSubtotal:
    """The band rate is chosen from the subtotal before the surcharge is added,
    which breaks the apparent circularity in the four-step order."""

    def test_band_rate_reads_the_presurcharge_subtotal(self, api):
        """PRD §3.7: "Step two selects the band rate from that pre-surcharge
        subtotal: four hundredths when the subtotal is below 5,000,000 cents,
        seven hundredths when it is at least 5,000,000 cents and below
        20,000,000 cents, and nine hundredths when it is 20,000,000 cents or
        more."
        PRD §3.7: "Step three multiplies the subtotal by that band rate and
        again by the tier factor for the production's current
        `duty_of_care_tier` — one for `STANDARD`, one and a half for `ENHANCED`,
        two for `CRITICAL` — rounding the product half up to whole cents to give
        the duty-of-care surcharge."
        PRD §3.7: "Step four sets `welfare_committed_cents` to the protocol
        subtotal plus that surcharge."

        Design: Difficulty/combinatorial_formula/welfare_band_read_from_presurcharge_subtotal_mode_c
        """
        production = setup_production(title="Island Trials S3", **HIGH_STRESS)
        assert production["duty_of_care_tier"] == "ENHANCED", (
            "a COMPETITION_HIGH_STRESS production opens at the ENHANCED tier"
        )

        first = setup_planned_welfare_protocol(
            production["id"], kind="DUTY_OF_CARE_OFFICER", cost_cents=2_400_000, **COVERAGE
        )
        after_first = get_production(production["id"])
        # Subtotal 2,400,000 -> band 0.04 -> surcharge 144,000.
        assert_money(
            after_first["welfare_committed_cents"], 2_544_000, "committed welfare"
        )

        second = setup_planned_welfare_protocol(
            production["id"], kind="ONSET_PSYCH_SUPPORT", cost_cents=2_500_000, **COVERAGE
        )
        after_second = get_production(production["id"])
        # Subtotal 4,900,000 is still below the 5,000,000 floor, so the band
        # stays at 0.04 and the surcharge is 294,000.
        assert_money(
            after_second["welfare_committed_cents"], 5_194_000, "committed welfare"
        )
        assert after_second["welfare_committed_cents"] != 5_414_500, (
            "reading the band off the post-surcharge total would have selected "
            "0.07 and produced 5,414,500"
        )
        assert after_second["casting_posture"] == "OPEN"
        assert first["status"] == "PLANNED"
        assert second["status"] == "PLANNED"

    def test_tier_factor_scales_the_same_subtotal_and_activation_does_not(self, api):
        """PRD §3.7: "Step one sums `cost_cents` over the production's protocols
        whose `status` is `PLANNED` or `ACTIVE`, excluding both `EXPIRED` and
        `CANCELLED` rows, to give the protocol subtotal; coverage dates play no
        part in membership, only the sweep's expiry transition does."
        PRD §3.7: "Notably, because `PLANNED` and `ACTIVE` rows both count,
        activating a protocol leaves the subtotal unchanged, and because
        cancelled rows drop out, cancelling one removes its cost exactly."
        PRD §3.1: "A `COMPETITION_HIGH_STRESS` production opens at a
        `duty_of_care_tier` of `ENHANCED`; every other format opens at
        `STANDARD`."

        Design: Difficulty/combinatorial_formula/welfare_band_read_from_presurcharge_subtotal_mode_c
        """
        production = setup_docusoap_production(
            title="Harbour Nights Band", welfare_budget_cents=10_000_000
        )
        assert production["duty_of_care_tier"] == "STANDARD"

        setup_planned_welfare_protocol(
            production["id"], kind="DUTY_OF_CARE_OFFICER", cost_cents=2_400_000, **COVERAGE
        )
        protocol = setup_planned_welfare_protocol(
            production["id"], kind="ONSET_PSYCH_SUPPORT", cost_cents=2_500_000, **COVERAGE
        )
        planned = get_production(production["id"])
        # The same 4,900,000 subtotal and the same 0.04 band, but the STANDARD
        # tier factor of one gives a surcharge of 196,000 rather than 294,000.
        assert_money(
            planned["welfare_committed_cents"], 5_096_000, "committed welfare"
        )

        activated = validate_success(api.activate_welfare_protocol(protocol["id"], WO1))
        assert activated["status"] == "ACTIVE"
        after_activation = get_production(production["id"])
        assert_money(
            after_activation["welfare_committed_cents"],
            5_096_000,
            "committed welfare after activation",
        )
