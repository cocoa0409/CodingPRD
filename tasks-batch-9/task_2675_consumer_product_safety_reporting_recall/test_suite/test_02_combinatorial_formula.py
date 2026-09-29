"""Money figures that fold several independent factors into one integer."""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_field_values,
    assert_fields_null,
    assert_integer_cents,
    assert_reserve_conserved,
    assert_unit_ledger_conserved,
)

# The determination lands at 2026-03-01, so report_due_at is that instant plus
# 240 hours; filing at 2026-03-13 is therefore exactly two days late.
DETERMINATION_CLOCK = "2026-03-01T00:00:00Z"
REPORT_DUE_AT = "2026-03-11T00:00:00"
LATE_SUBMIT_CLOCK = "2026-03-13T00:00:00Z"

# 4 * 1,000,000 * 1.25 (HOSPITALIZATION) * 1.10 (two days late) = 5,500,000.
EXPECTED_ASSESSMENT_CENTS = 5500000
ADDITIVE_LATENESS_ASSESSMENT_CENTS = 5000000
WRONG_INJURY_MULTIPLIER_ASSESSMENT_CENTS = 5400000

# TIER_2 at fifteen percent of the pre-credit base 5,500,000.
EXPECTED_CREDIT_CENTS = 825000
EXPECTED_SETTLEMENT_CENTS = 4675000
REKEYED_TIER_SETTLEMENT_CENTS = 4207500


def _instant(value):
    """The second-resolution prefix of an ISO 8601 instant."""
    return str(value)[:19]


class TestCivilPenaltyAssessmentMatrix:
    """One frozen assessment folding three factors from three entities."""

    def _late_filing_with_penalty_case(self, api):
        """A hospitalisation docket filed two days late with a case opened on it."""
        return fx.penalty_case_on_report_env(
            api,
            violation_count=4,
            clock=DETERMINATION_CLOCK,
            submit_clock=LATE_SUBMIT_CLOCK,
        )

    def test_assessment_multiplies_the_violation_base_by_injury_and_lateness(
        self, api
    ):
        """Four violations, a hospitalisation and two late days give 5,500,000 cents.

        The contract states: "The computation starts from a base of 1,000,000
        cents per alleged violation, that is 1,000,000 multiplied by
        `violation_count`." The office then reads two further factors off the
        docket: "When the worst injury is `FATALITY` the severity multiplier is
        1.50; when it is `HOSPITALIZATION` the multiplier is 1.25; for every
        other worst injury the multiplier is 1.00" and "The base is then scaled a
        second time by a lateness multiplier of 1.00 plus the smaller of 0.50 and
        the product of 0.05 and the report's stored `days_late`, so each full day
        of delay adds five percent up to a hard ceiling of fifty percent." Those
        factors compose multiplicatively: "The base, the severity multiplier and
        the lateness multiplier are multiplied together; the statutory ceiling of
        17,150,000 cents is then applied by taking the smaller of the product and
        that ceiling; and only then is the result rounded half up to whole cents,
        exactly once."

        Design: Difficulty/combinatorial_formula/civil_penalty_assessment_violation_injury_lateness_matrix
        """
        env = self._late_filing_with_penalty_case(api)

        evaluation = fx.get_evaluation(api, env["evaluation_id"])
        assert _instant(evaluation["report_due_at"]) == REPORT_DUE_AT

        report = fx.get_section_report(api, env["report_id"])
        assert_field_values(report, days_late=2, late_surcharge_cents=500000)

        case = fx.get_penalty_case(api, env["case_id"])
        assert_field_values(
            case,
            violation_count=4,
            assessed_penalty_cents=EXPECTED_ASSESSMENT_CENTS,
        )
        assert_integer_cents(case, "assessed_penalty_cents")
        assert case["assessed_penalty_cents"] != ADDITIVE_LATENESS_ASSESSMENT_CENTS, (
            "the lateness factor must scale the base, not be added beside it"
        )
        assert (
            case["assessed_penalty_cents"]
            != WRONG_INJURY_MULTIPLIER_ASSESSMENT_CENTS
        ), "a hospitalisation carries the 1.25 multiplier, not 1.20"

    def test_new_case_reserves_nothing_and_previews_the_credit_off_the_assessment(
        self, api
    ):
        """Opening the docket leaves the whole assessment available and unnegotiated.

        The contract states: "A new case is created in `status`
        `ASSESSMENT_OPEN`, with `reserved_cents` at 0 and `available_cents` equal
        to `assessed_penalty_cents`, so the conserved reserve identity holds from
        the first instant." It continues: "`current_offer_round` starts at 0,
        `current_offer_cents` and `current_offer_by` are null,
        `cooperation_bonus_applied` is false, `cooperation_credit_tier`,
        `cooperation_credit_cents` and `consent_agreement_total_cents` are null,
        `compliance_program_required` is false, and `reporting_obligation_months`
        is 0. Creation also computes the non-binding
        `consent_agreement_preview_cents`."

        Design: Difficulty/combinatorial_formula/civil_penalty_assessment_violation_injury_lateness_matrix
        """
        env = self._late_filing_with_penalty_case(api)

        case = fx.get_penalty_case(api, env["case_id"])

        assert_field_values(
            case,
            status="ASSESSMENT_OPEN",
            reserved_cents=0,
            available_cents=EXPECTED_ASSESSMENT_CENTS,
            current_offer_round=0,
            cooperation_bonus_applied=False,
            compliance_program_required=False,
            reporting_obligation_months=0,
            consent_agreement_preview_cents=EXPECTED_SETTLEMENT_CENTS,
        )
        assert_fields_null(
            case,
            "current_offer_cents",
            "current_offer_by",
            "cooperation_credit_tier",
            "cooperation_credit_cents",
            "consent_agreement_total_cents",
        )
        assert_reserve_conserved(case)


class TestRemedyReimbursementRoundingPosition:
    """A handling fee rounded per unit before the quantity multiplication."""

    def test_refund_fee_is_rounded_per_unit_before_the_quantity_multiply(self, api):
        """Seven refunded units at 4999 plus 899 reimburse 44,380 cents.

        The contract states: "A handling fee of 7.5 percent of that per-unit
        subtotal is then computed and **rounded half up to whole cents at the
        per-unit level, before any multiplication by quantity**; the rounded fee
        is added to the per-unit subtotal to give a per-unit total, and the
        per-unit total is multiplied by `quantity` to give
        `reimbursement_total_cents`." It adds: "A consequence worth remembering as
        a self-check is that the stored total is always exactly divisible by
        `quantity`."

        Design: Difficulty/combinatorial_formula/remedy_reimbursement_per_unit_rounding_before_quantity_multiply
        """
        env = fx.monitoring_recall_env(api)

        claim = fx.create_claim(
            api,
            env["recall_id"],
            consumer_ref="CR-2001",
            remedy_type="REFUND",
            quantity=7,
            unit_price_cents=4999,
            shipping_cents_per_unit=899,
        )

        assert_field_values(
            claim,
            status="SUBMITTED",
            remedy_type="REFUND",
            quantity=7,
            reimbursement_total_cents=44380,
        )
        assert_integer_cents(claim, "reimbursement_total_cents")
        assert claim["reimbursement_total_cents"] != 44382, (
            "the fee must be rounded per unit, never once over the aggregate"
        )
        assert claim["reimbursement_total_cents"] % claim["quantity"] == 0, (
            "a per-unit total multiplied by quantity divides back exactly"
        )

    def test_repair_claim_prices_the_kit_cost_and_ignores_the_submitted_price(
        self, api
    ):
        """Three repaired units reimburse 10,962 cents off the fixed kit cost.

        The contract states: "A `REPAIR` claim uses a fixed repair-kit cost of
        2,500 cents and **ignores** `unit_price_cents` entirely." The same
        per-unit arithmetic then applies: "To that base value the
        `shipping_cents_per_unit` is added, giving a per-unit subtotal."

        Design: Difficulty/combinatorial_formula/remedy_reimbursement_per_unit_rounding_before_quantity_multiply
        """
        env = fx.monitoring_recall_env(api)

        claim = fx.create_claim(
            api,
            env["recall_id"],
            consumer_ref="CR-2002",
            remedy_type="REPAIR",
            quantity=3,
            unit_price_cents=0,
            shipping_cents_per_unit=899,
        )

        assert_field_values(
            claim,
            status="SUBMITTED",
            remedy_type="REPAIR",
            quantity=3,
            reimbursement_total_cents=10962,
        )
        assert claim["reimbursement_total_cents"] != 2898, (
            "the submitted unit_price_cents must not displace the kit cost"
        )
        assert claim["reimbursement_total_cents"] % claim["quantity"] == 0, (
            "a per-unit total multiplied by quantity divides back exactly"
        )

    def test_registering_the_two_claims_moves_no_units_on_the_ledger(self, api):
        """Both claims are priced while the recall's unit ledger stands still.

        The contract states: "Registration deliberately moves no units: neither
        `units_corrected` nor `units_outstanding` changes until fulfilment."

        Design: Difficulty/combinatorial_formula/remedy_reimbursement_per_unit_rounding_before_quantity_multiply
        """
        env = fx.monitoring_recall_env(api)

        fx.create_claim(
            api,
            env["recall_id"],
            consumer_ref="CR-2001",
            remedy_type="REFUND",
            quantity=7,
            unit_price_cents=4999,
            shipping_cents_per_unit=899,
        )
        fx.create_claim(
            api,
            env["recall_id"],
            consumer_ref="CR-2002",
            remedy_type="REPAIR",
            quantity=3,
            unit_price_cents=0,
            shipping_cents_per_unit=899,
        )

        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            recall,
            units_in_commerce=100,
            units_corrected=0,
            units_outstanding=100,
            effectiveness_flag="PENDING",
        )
        assert_unit_ledger_conserved(recall)


class TestConsentAgreementTierKeying:
    """A settlement whose tier is pinned to the base the credit is taken from."""

    def _accepted_full_value_agreement(self, api):
        """An agency offer at the full assessment, accepted into a consent agreement."""
        env = fx.penalty_case_on_report_env(
            api,
            violation_count=4,
            clock=DETERMINATION_CLOCK,
            submit_clock=LATE_SUBMIT_CLOCK,
        )
        case = fx.get_penalty_case(api, env["case_id"])
        fx.make_offer(
            api,
            env["case_id"],
            EXPECTED_ASSESSMENT_CENTS,
            "AGENCY",
            case["version"],
        )
        env["case"] = fx.resolve_offer(
            api,
            env["case_id"],
            "ACCEPTED",
            note="Respondent accepts the assessed amount in full settlement.",
        )
        return env

    def test_credit_tier_is_keyed_on_the_pre_credit_settlement_base(self, api):
        """A base of 5,500,000 selects TIER_2 and never re-keys on the discount.

        The contract states: "The cooperation credit tier is keyed on that
        **pre-credit** settlement base and never on the discounted total: when the
        base is below 5,000,000 cents the tier is `TIER_1` at ten percent; when the
        base is at least 5,000,000 and at most 12,000,000 cents the tier is
        `TIER_2` at fifteen percent; above 12,000,000 cents the tier is `TIER_3` at
        twenty percent." It adds: "Keying the tier on the post-credit total would
        make the formula self-referential, because the credit would change the tier
        which would change the credit, and it must not be done."

        Design: Difficulty/combinatorial_formula/consent_agreement_tier_keyed_on_pre_credit_settlement_base
        """
        env = self._accepted_full_value_agreement(api)

        case = fx.get_penalty_case(api, env["case_id"])

        assert_field_values(
            case,
            status="AGREED",
            assessed_penalty_cents=EXPECTED_ASSESSMENT_CENTS,
            current_offer_cents=EXPECTED_ASSESSMENT_CENTS,
            cooperation_bonus_applied=False,
            cooperation_credit_tier="TIER_2",
            cooperation_credit_cents=EXPECTED_CREDIT_CENTS,
            consent_agreement_total_cents=EXPECTED_SETTLEMENT_CENTS,
        )
        assert case["consent_agreement_total_cents"] != REKEYED_TIER_SETTLEMENT_CENTS, (
            "re-keying the tier on the post-credit total is forbidden"
        )
        assert (
            case["cooperation_credit_cents"] + case["consent_agreement_total_cents"]
            == case["current_offer_cents"]
        ), "credit plus total must reconstruct the settlement base exactly"

    def test_downstream_obligations_are_keyed_on_the_settled_total(self, api):
        """A settled 4,675,000 stays under the floor, so no programme and 12 months.

        The contract states: "`compliance_program_required` is set true when
        `consent_agreement_total_cents` has reached 5,000,000 cents and false
        otherwise, and `reporting_obligation_months` is set to 24 when the
        compliance programme is required and to 12 when it is not." It continues:
        "Acceptance also moves the reserve one last time, setting `reserved_cents`
        to `consent_agreement_total_cents` and `available_cents` to
        `assessed_penalty_cents` minus `consent_agreement_total_cents`, preserving
        the reserve identity in its final resting state."

        Design: Difficulty/combinatorial_formula/consent_agreement_tier_keyed_on_pre_credit_settlement_base
        """
        env = self._accepted_full_value_agreement(api)

        case = fx.get_penalty_case(api, env["case_id"])

        assert_field_values(
            case,
            compliance_program_required=False,
            reporting_obligation_months=12,
            reserved_cents=EXPECTED_SETTLEMENT_CENTS,
            available_cents=EXPECTED_CREDIT_CENTS,
        )
        assert_integer_cents(
            case,
            "cooperation_credit_cents",
            "consent_agreement_total_cents",
            "reserved_cents",
            "available_cents",
        )
        assert_reserve_conserved(case)
