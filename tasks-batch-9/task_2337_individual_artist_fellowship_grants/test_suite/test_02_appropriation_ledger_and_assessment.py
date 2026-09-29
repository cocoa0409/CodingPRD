"""
The appropriation ledger: the assessment band, the funding waterfall and the
compensation a declined offer owes the cycle.
"""

from test_helpers import (
    BOARD_MEMBER,
    api_client,
    assert_available_identity,
    assert_cents,
    assert_committed_identity,
    assert_cycle_ledger,
    assert_rate,
    award_id_for_application,
    cycle_version,
    cyclemain_slot_approved,
    cyclemain_two_applications_slated,
    read_application,
    read_artist,
    read_award,
    read_cycle,
    read_discipline,
    validate_success,
)


def _approve(slot_id: str, cycle_id: str) -> dict:
    """Approve one slot with a freshly read cycle version."""
    return validate_success(
        api_client.board_action(
            slot_id,
            {
                "action": "APPROVE",
                "expected_cycle_version": cycle_version(cycle_id, BOARD_MEMBER),
            },
            BOARD_MEMBER,
        )
    )


class TestAdministrativeAssessmentBand:
    """The band is selected from the pre-assessment funded total, once and for all."""

    def test_the_first_approval_selects_the_first_band_on_its_funded_total(self):
        """
        A single 1,500,000-cent award puts the cycle's funded total in the first band, so
        the council retains 127,500 cents and publishes a committed figure of 1,627,500
        against a 300,000-cent contingency reserve.

        PRD: "The selected value is stored as `admin_assessment_rate`, and
        `admin_assessment_cents` is the basis multiplied by that rate, rounded half up to
        a whole cent."

        Design: Difficulty/combinatorial_formula/admin_assessment_tier_keyed_on_pre_assessment_funded_total
        """
        ctx = cyclemain_two_applications_slated()
        _approve(ctx.slot1, ctx.cyc)

        cycle = read_cycle(ctx.cyc)
        assert_cycle_ledger(
            cycle,
            funded_total_cents=1_500_000,
            admin_assessment_rate=0.085,
            admin_assessment_cents=127_500,
            reserve_cents=300_000,
            committed_cents=1_627_500,
            available_cents=4_072_500,
            posture="OPEN",
        )
        assert_committed_identity(cycle)
        assert_available_identity(cycle)

    def test_the_second_approval_prorates_the_remainder_without_reselecting_the_band(self):
        """
        The rank-2 slot takes the discipline's 500,000-cent remainder as a prorated
        award, lifting the funded total to exactly 2,000,000 — which stays in the first
        band, retains 170,000 cents and commits 2,170,000 rather than dropping to the
        second band against the committed figure.

        PRD: "A cycle with a funded total of exactly 2,000,000 cents therefore sits in
        the first band, retains 170,000 cents and reports `committed_cents` of 2,170,000;
        re-selecting the band against that committed figure would wrongly drop the rate
        to 0.070, and that reading is forbidden."

        Design: Difficulty/combinatorial_formula/admin_assessment_tier_keyed_on_pre_assessment_funded_total
        """
        ctx = cyclemain_two_applications_slated()
        _approve(ctx.slot1, ctx.cyc)
        second = _approve(ctx.slot2, ctx.cyc)

        assert_cents(second["awarded_amount_cents"], 500_000, "slot.awarded_amount_cents")
        award = read_award(award_id_for_application(ctx.app2))
        assert_cents(award["gross_amount_cents"], 500_000, "award.gross_amount_cents")
        assert award["is_prorated"] is True, (
            "an award funded from a short remainder under PRORATE is prorated"
        )

        cycle = read_cycle(ctx.cyc)
        assert_cycle_ledger(
            cycle,
            funded_total_cents=2_000_000,
            admin_assessment_rate=0.085,
            admin_assessment_cents=170_000,
            reserve_cents=300_000,
            committed_cents=2_170_000,
            available_cents=3_530_000,
            posture="OPEN",
        )
        assert_rate(cycle["admin_assessment_rate"], 0.085, "cycle.admin_assessment_rate")

    def test_the_discipline_accumulates_gross_amounts_only(self):
        """
        Both awards land on the discipline's own bookkeeping as gross amounts summing to
        its whole 2,000,000-cent allocation, with the cycle-level assessment held back
        against the appropriation instead.

        PRD: "Note that a discipline's `committed_cents` accumulates gross amounts only —
        the cycle-level administrative assessment is held against the cycle
        appropriation, never against a discipline allocation."

        Design: Difficulty/combinatorial_formula/admin_assessment_tier_keyed_on_pre_assessment_funded_total
        """
        ctx = cyclemain_two_applications_slated()
        _approve(ctx.slot1, ctx.cyc)
        _approve(ctx.slot2, ctx.cyc)

        discipline = read_discipline(ctx.disc)
        assert_cents(discipline["committed_cents"], 2_000_000, "discipline.committed_cents")
        assert discipline["funded_application_count"] == 2, (
            "both funded applications should be counted, got "
            f"{discipline['funded_application_count']}"
        )


class TestDeclinedOfferCompensation:
    """A decline must restore the ledger to its exact pre-award figures."""

    def test_declining_returns_every_fiscal_field_to_its_pre_award_value(self):
        """
        Declining the only award of the cycle returns the funded total, the assessment
        rate, the assessment, the committed figure and the availability to precisely the
        values they held before the award existed — the rate back to 0, not left at
        0.085.

        PRD: "Declining, rescinding or forfeiting an award unwinds the cycle's fiscal
        fields to precisely the figures they held before the award existed; waiving a
        previously blocking conflict restores the affected application's review counts
        and provisional score to their exact pre-block values; and reversing a paid
        installment issues a replacement such that the award's `gross_amount_cents` still
        equals the sum of `gross_cents` over its installments in `SCHEDULED`, `HELD`,
        `RELEASED` and `PAID`."

        Design: Difficulty/compensating_invariant/declined_offer_restores_the_cycle_ledger_to_its_pre_award_values
        """
        ctx = cyclemain_slot_approved()
        committed = read_cycle(ctx.cyc)
        assert_cycle_ledger(
            committed,
            funded_total_cents=1_500_000,
            admin_assessment_rate=0.085,
            admin_assessment_cents=127_500,
            reserve_cents=300_000,
            committed_cents=1_627_500,
            available_cents=4_072_500,
            posture="OPEN",
        )

        validate_success(api_client.decline_award(ctx.aw1, ctx.art1_headers))

        cycle = read_cycle(ctx.cyc)
        assert_cycle_ledger(
            cycle,
            funded_total_cents=0,
            admin_assessment_rate=0.0,
            admin_assessment_cents=0,
            reserve_cents=300_000,
            committed_cents=0,
            available_cents=5_700_000,
            posture="OPEN",
        )
        assert_committed_identity(cycle)
        assert_available_identity(cycle)

    def test_declining_unwinds_the_slot_application_artist_and_discipline(self):
        """
        The same decline voids the slot with a zeroed amount, returns the application to
        NOT_AWARDED, decrements the artist's and the discipline's counters, and leaves
        the award row itself standing in DECLINED as the audit record.

        PRD: "**Declining** is the recipient's own act, available only from `OFFERED` and
        only to the award's own artist: the award moves `OFFERED → DECLINED`, the
        application moves `RECOMMENDED → NOT_AWARDED` with `notified_at` re-stamped, the
        slot moves `BOARD_APPROVED → VOIDED` with its `awarded_amount_cents` reset to 0,
        the artist's `active_award_count` is decremented, the discipline's
        `committed_cents` and `funded_application_count` are decremented, and the cycle's
        `funded_total_cents`, `admin_assessment_rate`, `admin_assessment_cents`,
        `committed_cents`, `available_cents` and `posture` are recomputed."

        Design: Difficulty/compensating_invariant/declined_offer_restores_the_cycle_ledger_to_its_pre_award_values
        """
        ctx = cyclemain_slot_approved()
        validate_success(api_client.decline_award(ctx.aw1, ctx.art1_headers))

        award = read_award(ctx.aw1)
        assert award["status"] == "DECLINED", (
            f"the award row should persist as DECLINED, got {award['status']}"
        )

        slot = validate_success(api_client.get_slot(ctx.slot1, BOARD_MEMBER))
        assert slot["status"] == "VOIDED", (
            f"the slot should move BOARD_APPROVED -> VOIDED, got {slot['status']}"
        )
        assert_cents(slot["awarded_amount_cents"], 0, "slot.awarded_amount_cents")

        assert read_application(ctx.app1)["status"] == "NOT_AWARDED", (
            "the application should move RECOMMENDED -> NOT_AWARDED"
        )

        artist = read_artist(ctx.art1)
        assert artist["active_award_count"] == 0, (
            f"active_award_count should return to 0, got {artist['active_award_count']}"
        )
        assert artist["prior_award_count"] == 0, (
            "a declined offer never becomes award history, got "
            f"{artist['prior_award_count']}"
        )

        discipline = read_discipline(ctx.disc)
        assert_cents(discipline["committed_cents"], 0, "discipline.committed_cents")
        assert discipline["funded_application_count"] == 0, (
            f"funded_application_count should return to 0, got {discipline['funded_application_count']}"
        )
