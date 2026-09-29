"""The two figures the API computes twice: the stipend commitment and the
applicant risk score.  Each is written under a provisional variant and a final
variant that disagree on the very same row.
"""

from test_helpers import (
    TEST_USERS,
    assert_money,
    assert_score,
    get_applicant,
    get_production,
    record_screening_items,
    set_clock,
    setup_cleared_applicant,
    setup_drafted_agreement,
    setup_production,
    setup_published_casting_call,
    validate_success,
)

BA1 = TEST_USERS["business_affairs_headers"]
BA2 = TEST_USERS["business_affairs_2_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]
CO2 = TEST_USERS["compliance_officer_2_headers"]

# A COMPETITION_HIGH_STRESS season of 10 episodes with a generous pool.
ISLAND_TRIALS = {
    "title": "Island Trials S1",
    "format_type": "COMPETITION_HIGH_STRESS",
    "jurisdiction_code": "CA",
    "season_number": 1,
    "episode_order": 10,
    "stipend_pool_cents": 50_000_000,
    "welfare_budget_cents": 10_000_000,
    "minor_participant_cap": 2,
}

# The negotiated terms whose two variants diverge: 250,000 per episode over 6
# episodes, a 90-day exclusivity term, two press junkets, a reunion, and a
# LIMITED depiction licence.
RICH_TERMS = {
    "exclusivity_window_days": 90,
    "confidentiality_tier": "ENHANCED",
    "depiction_rights_scope": "LIMITED",
    "stipend_structure": "PER_EPISODE",
    "base_stipend_cents": 250_000,
    "episodes_committed": 6,
    "press_appearance_obligation_count": 2,
    "reunion_obligation": True,
}


def _cleared_high_stress_participant(**applicant_overrides):
    """One COMPETITION_HIGH_STRESS production with one fully cleared adult."""
    production = setup_production(**ISLAND_TRIALS)
    call = setup_published_casting_call(
        production["id"], min_age=18, max_age=45, exclusivity_window_days=90
    )
    applicant = setup_cleared_applicant(call["id"], **applicant_overrides)
    return production, call, applicant


class TestStipendVariants:
    """One unchanged agreement row, two stipend answers."""

    def test_provisional_and_final_stipend_diverge_on_one_row(self, api):
        """PRD §3.6: "The **provisional** variant, written to
        `provisional_stipend_cents` on every send transition and read by the
        send-time pool guard, is a deliberately forward-looking worst case over
        that same row."
        PRD §3.6: "It uses as its episode count the larger of
        `episodes_committed` and the production's `episode_order`, on the
        assumption that the participant is retained for the full season — and
        because that larger count can cross a tier boundary, the tier multiplier
        itself may differ from the final variant's."
        PRD §3.6: "The **final** variant, written to
        `total_stipend_commitment_cents` on execution and zeroed on voiding, uses
        `episodes_committed` exactly as agreed, the contracted press count
        without any reserve, the actual `reunion_obligation` flag, and it does
        apply the depiction adjustment."

        Design: Difficulty/dual_variant_calc/agreement_stipend_provisional_vs_final_diverge
        """
        production, _call, applicant = _cleared_high_stress_participant()
        agreement = setup_drafted_agreement(
            applicant["id"], production["id"], **RICH_TERMS
        )

        sent = validate_success(api.send_agreement(agreement["id"], BA1))
        # Episode count max(6, 10) = 10 -> tier 1.30: base 3,250,000, hazard
        # 325,000, three 30-day exclusivity blocks 120,000, (2 + 2 reserve)
        # press appearances 100,000, reunion charged unconditionally 150,000.
        assert_money(sent["provisional_stipend_cents"], 3_945_000, "provisional stipend")
        assert_money(
            sent["total_stipend_commitment_cents"], 0, "final stipend while only SENT"
        )

        executed = validate_success(api.execute_agreement(agreement["id"], BA2))
        # Episode count 6 -> tier 1.15: base 1,725,000, hazard 172,500,
        # exclusivity 120,000, contracted press 50,000, reunion 150,000; the
        # 2,217,500 subtotal then takes the LIMITED discount of 110,875.
        assert_money(
            executed["total_stipend_commitment_cents"], 2_106_625, "final stipend"
        )
        assert_money(
            executed["provisional_stipend_cents"],
            3_945_000,
            "provisional stipend after execution",
        )
        assert (
            executed["provisional_stipend_cents"]
            - executed["total_stipend_commitment_cents"]
            == 1_838_375
        ), "the two variants must disagree by 1,838,375 cents on this row"

    def test_only_the_final_variant_enters_the_committed_rollup(self, api):
        """PRD §3.6: "The final variant is the only one that enters the
        production's committed-stipend rollup; the provisional figure never
        does."
        PRD §2.11: "Committed stipend is the sum of
        `total_stipend_commitment_cents` over the production's participant
        agreements whose `status` is `EXECUTED`."

        Design: Difficulty/dual_variant_calc/agreement_stipend_provisional_vs_final_diverge
        """
        production, _call, applicant = _cleared_high_stress_participant()
        agreement = setup_drafted_agreement(
            applicant["id"], production["id"], **RICH_TERMS
        )

        validate_success(api.send_agreement(agreement["id"], BA1))
        after_send = get_production(production["id"])
        assert_money(
            after_send["stipend_committed_cents"],
            0,
            "committed stipend while the agreement is only SENT",
        )

        validate_success(api.execute_agreement(agreement["id"], BA2))
        after_execute = get_production(production["id"])
        assert_money(
            after_execute["stipend_committed_cents"],
            2_106_625,
            "committed stipend after execution",
        )
        assert after_execute["casting_posture"] == "OPEN", (
            "2,106,625 cents against a 50,000,000 cent pool is far below ninety "
            f"percent; got posture {after_execute['casting_posture']}"
        )


class TestRiskScoreVariants:
    """One applicant, two risk answers: the pessimistic ceiling and the decayed
    figure that every threshold actually reads."""

    def test_provisional_ceiling_and_final_decayed_diverge(self, api):
        """PRD §3.4: "Items that have been recorded contribute their own points
        at full weight, with no recency decay applied."
        PRD §3.4: "Its recorded items are ordered by `recorded_at` descending,
        with ties broken by `created_at` descending, and each item is then
        multiplied by a decay factor determined by its one-based position in that
        ordering: the first item keeps its full points, the second is multiplied
        by eight tenths, the third by six tenths, the fourth by one half, and
        every item from the fifth onward is also multiplied by one half."
        PRD §3.4: "Clearing recomputes both risk figures, sets
        `enhanced_support_required` to true exactly when `final_risk_score` is
        8.00 or above, and increments the originating casting call's
        `screened_pass_count` by one."

        Design: Difficulty/dual_variant_calc/applicant_risk_ceiling_vs_decayed_diverge
        """
        production = setup_production(**{**ISLAND_TRIALS, "title": "Island Trials Risk"})
        call = setup_published_casting_call(
            production["id"], min_age=18, max_age=45, exclusivity_window_days=90
        )
        applicant = validate_success(
            api.create_applicant(
                {
                    "casting_call_id": call["id"],
                    "legal_name": "Ben Ortiz",
                    "date_of_birth": "1994-04-02",
                    "residency_state_code": "CA",
                },
                TEST_USERS["casting_director_headers"],
            ),
            201,
        )

        # Four instruments recorded on four consecutive logical-clock days, so
        # the recency ordering is unambiguous.
        record_screening_items(
            applicant["id"],
            [
                (
                    "INTERVIEW",
                    "CONDITIONAL",
                    2,
                    CO1,
                )
            ],
        )
        set_clock("2026-08-02T00:00:00Z")
        record_screening_items(
            applicant["id"], [("BACKGROUND_CHECK", "CONDITIONAL", 3, CO1)]
        )
        set_clock("2026-08-03T00:00:00Z")
        record_screening_items(applicant["id"], [("MEDICAL_EXAM", "PASS", 0, CO1)])
        set_clock("2026-08-04T00:00:00Z")
        record_screening_items(
            applicant["id"], [("PSYCH_EVAL", "CONDITIONAL", 2, CO2)]
        )

        final = get_applicant(applicant["id"])
        # Undecayed points: interview 1.50, background check 4.50, medical 0,
        # psych evaluation 4.00.
        assert_score(final["provisional_risk_score"], 10.00, "provisional risk score")
        # Recency order psych / medical / background / interview weighted
        # 1.00 / 0.80 / 0.60 / 0.50 gives 4.00 + 0 + 2.70 + 0.75.
        assert_score(final["final_risk_score"], 7.45, "final risk score")
        assert final["provisional_risk_score"] != final["final_risk_score"], (
            "the two variants must disagree on identical evidence"
        )
        assert final["enhanced_support_required"] is False, (
            "7.45 is below the 8.00 threshold, so enhanced support is not required"
        )
        assert final["screening_status"] == "CLEARED"
        assert final["medical_status"] == "CLEARED"

    def test_pending_items_are_charged_at_the_ceiling_and_final_stays_unwritten(
        self, api
    ):
        """PRD §3.4: "The **provisional ceiling** variant is written to
        `provisional_risk_score` on every screening-item write, and it charges
        every item that has not yet been recorded — every item whose
        `recorded_at` is still absent — at the pessimistic ceiling: 5 severity
        flags multiplied by that item's kind weight multiplied by a factor of
        one."
        PRD §3.4: "The **final decayed** variant is written to
        `final_risk_score` only once every required kind has an item whose
        `recorded_at` is present; pending items contribute nothing at all to
        it."
        PRD §3.3: "Both risk figures, `provisional_risk_score` and
        `final_risk_score`, open at 0, and `enhanced_support_required` opens
        false."

        Design: Difficulty/dual_variant_calc/applicant_risk_ceiling_vs_decayed_diverge
        """
        production = setup_production(
            **{**ISLAND_TRIALS, "title": "Island Trials Pending"}
        )
        call = setup_published_casting_call(
            production["id"], min_age=18, max_age=45, exclusivity_window_days=90
        )
        applicant = validate_success(
            api.create_applicant(
                {
                    "casting_call_id": call["id"],
                    "legal_name": "Cal Ferreira",
                    "date_of_birth": "1994-04-02",
                    "residency_state_code": "CA",
                },
                TEST_USERS["casting_director_headers"],
            ),
            201,
        )
        assert_score(applicant["provisional_risk_score"], 0.0, "opening provisional")
        assert_score(applicant["final_risk_score"], 0.0, "opening final")

        # One recorded CONDITIONAL interview worth 1.50 points, plus one
        # background check left pending and therefore charged at 5 x 3.0 x 1.
        record_screening_items(applicant["id"], [("INTERVIEW", "CONDITIONAL", 2, CO1)])
        record_screening_items(applicant["id"], [("BACKGROUND_CHECK", None, 0, CO1)])

        mid = get_applicant(applicant["id"])
        assert_score(mid["provisional_risk_score"], 16.50, "provisional risk score")
        assert_score(
            mid["final_risk_score"],
            0.0,
            "final risk score while a required kind is still unrecorded",
        )
        assert mid["screening_status"] == "SCREENING"
