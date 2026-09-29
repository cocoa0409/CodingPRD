"""Two undos that subtract exactly what they added, and nothing more."""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_field_values,
    assert_fields_null,
    assert_integer_cents,
    assert_reserve_conserved,
    assert_unchanged,
    assert_unit_ledger_conserved,
    assert_version_advanced,
)

# Thirty of a hundred units at 4999 plus 899 shipping: the per-unit handling fee
# of 7.5 percent rounds to 442 cents before the multiplication by quantity.
THIRTY_UNIT_REFUND = {
    "consumer_ref": "CR-5001",
    "remedy_type": "REFUND",
    "quantity": 30,
    "unit_price_cents": 4999,
    "shipping_cents_per_unit": 899,
}

FROZEN_REIMBURSEMENT_CENTS = 190200

# Four alleged violations on a report filed two days late behind a hospitalisation.
ASSESSED_PENALTY_CENTS = 5500000
PREVIEW_WITHOUT_BONUS_CENTS = 4675000
PREVIEW_WITH_BONUS_CENTS = 4400000

AGENCY_OFFER_CENTS = 4500000

VOID_REASON = "Consumer never returned the unit; refund reversed."
WITHDRAWAL_NOTE = "Offer withdrawn after new incident evidence arrived."


def _fulfilled_claim_env(api):
    """A monitoring recall whose ledger stands at 30 of 100, bonus granted."""
    env = fx.penalty_case_env(api, violation_count=4)
    claim = fx.fulfilled_claim(api, env["recall_id"], **THIRTY_UNIT_REFUND)
    env["claim"] = claim
    env["claim_id"] = claim["id"]
    return env


def _standing_agency_offer_env(api):
    """A penalty case with one agency offer of 4500000 on the table."""
    env = fx.penalty_case_on_report_env(api, violation_count=4)
    env["case"] = fx.make_offer(
        api,
        env["case_id"],
        AGENCY_OFFER_CENTS,
        "AGENCY",
        env["case"]["version"],
    )
    return env


class TestVoidingAFulfilledClaimRestoresTheUnitPartition:
    """A count of physical units, partitioned across a fixed total of 100."""

    def test_the_thirty_units_return_to_outstanding_and_the_sum_still_holds(self, api):
        """The partition reads 30 / 70 before the void and 0 / 100 after it.

        The contract states: "On a recall, the sum of `units_corrected` and
        `units_outstanding` always equals `units_in_commerce`, which is immutable
        after the recall is created; the pair is a strict partition of a fixed
        total, and `units_corrected` is never permitted to exceed
        `units_in_commerce`." The undo is exact, because "Its second link
        subtracts the claim's stored `quantity` from the recall's
        `units_corrected` and adds the same `quantity` back to
        `units_outstanding`, restoring the conserved total exactly."

        Design: Difficulty/compensating_invariant/claim_void_restores_the_unit_partition_and_undoes_the_cooperation_credit
        """
        env = _fulfilled_claim_env(api)

        before = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            before,
            units_in_commerce=100,
            units_corrected=30,
            units_outstanding=70,
            effectiveness_flag="MET",
            plan_status="MONITORING",
        )
        assert_unit_ledger_conserved(before)

        voided = fx.void_claim(api, env["claim_id"], reason=VOID_REASON)
        assert_field_values(voided, status="VOID", quantity=30)
        assert voided["voided_at"].startswith("2026-03-14T00:00:00"), voided

        after = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            after,
            units_in_commerce=100,
            units_corrected=0,
            units_outstanding=100,
            effectiveness_flag="PENDING",
            plan_status="MONITORING",
        )
        assert_unit_ledger_conserved(after)
        assert_unchanged(
            before, after, "units_in_commerce", "plan_status", "notification_status"
        )
        assert_version_advanced(before, after)

    def test_the_cooperation_credit_is_given_back_while_the_frozen_total_stays(
        self, api
    ):
        """The bonus and the preview revert; the claim's own total does not.

        The contract states: "Its fourth link, triggered only when the flag
        actually reverted out of `MET`, reaches the same linked civil penalty case
        in `ASSESSMENT_OPEN`, `OFFER_MADE` or `COUNTERED` and sets
        `cooperation_bonus_applied` back to false, recomputes its settlement
        preview, and increments its `version` by 1." What survives untouched is
        the historical figure, since "The claim's `reimbursement_total_cents` is
        computed once at registration and frozen; voiding the claim later does not
        recompute it, because the stored total is exactly what gets reversed."

        Design: Difficulty/compensating_invariant/claim_void_restores_the_unit_partition_and_undoes_the_cooperation_credit
        """
        env = _fulfilled_claim_env(api)

        credited = fx.get_penalty_case(api, env["case_id"])
        assert_field_values(
            credited,
            status="ASSESSMENT_OPEN",
            assessed_penalty_cents=ASSESSED_PENALTY_CENTS,
            cooperation_bonus_applied=True,
            consent_agreement_preview_cents=PREVIEW_WITH_BONUS_CENTS,
        )
        assert_reserve_conserved(credited)

        fx.void_claim(api, env["claim_id"], reason=VOID_REASON)

        after = fx.get_penalty_case(api, env["case_id"])
        assert_field_values(
            after,
            cooperation_bonus_applied=False,
            consent_agreement_preview_cents=PREVIEW_WITHOUT_BONUS_CENTS,
            assessed_penalty_cents=ASSESSED_PENALTY_CENTS,
        )
        assert_fields_null(
            after,
            "cooperation_credit_tier",
            "cooperation_credit_cents",
            "consent_agreement_total_cents",
        )
        assert_reserve_conserved(after)
        assert_unchanged(credited, after, "assessed_penalty_cents", "status")
        assert_version_advanced(credited, after)
        assert_integer_cents(
            after,
            "assessed_penalty_cents",
            "reserved_cents",
            "available_cents",
            "consent_agreement_preview_cents",
        )

        claim = fx.get_claim(api, env["claim_id"])
        assert_field_values(
            claim,
            status="VOID",
            reimbursement_total_cents=FROZEN_REIMBURSEMENT_CENTS,
        )


class TestWithdrawingAnOfferRestoresTheReservePartition:
    """Money in cents, partitioned across the frozen assessment of 5500000."""

    def test_the_reserve_split_returns_to_zero_and_the_full_assessment(self, api):
        """The offer moves 4500000 across the partition and the undo moves it back.

        The contract states: "On a civil penalty case, the sum of `reserved_cents`
        and `available_cents` always equals `assessed_penalty_cents`, which is
        frozen at assessment time." The withdrawal is exact, because "`WITHDRAWN`
        returns the case `OFFER_MADE → ASSESSMENT_OPEN`, clears
        `current_offer_cents` and `current_offer_by` back to null, and compensates
        the reserve exactly by setting `reserved_cents` to 0 and `available_cents`
        to `assessed_penalty_cents`."

        Design: Difficulty/compensating_invariant/offer_withdrawal_restores_the_penalty_reserve_partition
        """
        env = _standing_agency_offer_env(api)
        offered = env["case"]

        assert_field_values(
            offered,
            status="OFFER_MADE",
            assessed_penalty_cents=ASSESSED_PENALTY_CENTS,
            reserved_cents=AGENCY_OFFER_CENTS,
            available_cents=ASSESSED_PENALTY_CENTS - AGENCY_OFFER_CENTS,
            current_offer_cents=AGENCY_OFFER_CENTS,
            current_offer_by="AGENCY",
            current_offer_round=1,
        )
        assert_reserve_conserved(offered)

        withdrawn = fx.resolve_offer(
            api, env["case_id"], "WITHDRAWN", note=WITHDRAWAL_NOTE
        )
        assert_field_values(
            withdrawn,
            status="ASSESSMENT_OPEN",
            reserved_cents=0,
            available_cents=ASSESSED_PENALTY_CENTS,
            assessed_penalty_cents=ASSESSED_PENALTY_CENTS,
        )
        assert_fields_null(withdrawn, "current_offer_cents", "current_offer_by")
        assert_reserve_conserved(withdrawn)
        assert_integer_cents(withdrawn, "reserved_cents", "available_cents")
        assert (
            withdrawn["reserved_cents"] + withdrawn["available_cents"]
            == offered["reserved_cents"] + offered["available_cents"]
        ), "the partition total must not drift across the compensation"

    def test_the_consumed_negotiation_round_is_not_given_back(self, api):
        """The money is restored while the monotonic round counter stands still.

        The contract states: "It pointedly does **not** give the round back: a
        withdrawn offer still consumed a round, so `current_offer_round` is left
        where it stands and six withdrawn offers exhaust the negotiation just as
        surely as six live ones." That is the general rule, since "What
        compensation never restores is a monotonic counter: a withdrawn offer
        still consumed a negotiation round, and a delinquency once recorded
        against a retailer stays recorded."

        Design: Difficulty/compensating_invariant/offer_withdrawal_restores_the_penalty_reserve_partition
        """
        env = _standing_agency_offer_env(api)
        offered = env["case"]

        withdrawn = fx.resolve_offer(
            api, env["case_id"], "WITHDRAWN", note=WITHDRAWAL_NOTE
        )

        assert_field_values(
            withdrawn,
            current_offer_round=1,
            cooperation_bonus_applied=False,
            compliance_program_required=False,
            reporting_obligation_months=0,
        )
        assert_fields_null(
            withdrawn,
            "cooperation_credit_tier",
            "cooperation_credit_cents",
            "consent_agreement_total_cents",
        )
        assert_unchanged(
            offered, withdrawn, "current_offer_round", "assessed_penalty_cents"
        )
        assert_version_advanced(offered, withdrawn)

        report = fx.get_section_report(api, env["report_id"])
        assert_field_values(report, days_late=2, late_surcharge_cents=500000)
