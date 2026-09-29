"""The servicing pass: the strictly-greater grace-period comparison and the
round-then-clamp order on the fee amount.
"""

from test_helpers import (
    factories,
    fixtures,
    late_fee_cents,
    round_half_up,
)


def _two_active_notes(api):
    """G1 (installment 1 of 154761) and G2 (installment 1 of 9083), both ACTIVE.

    Both notes fall due on 2026-11-01 under a regime whose grace period is ten
    days, so a single servicing pass sees them together.
    """
    ctx = fixtures.origination_context(api, clock="2026-09-05T00:00:00Z")
    g1 = fixtures.active_agreement(
        api,
        ctx=ctx,
        policies=[
            factories.financed_policy(
                ctx["insurer_id"],
                policy_number="MC-G-7001",
                gross_premium_cents=1550000,
            )
        ],
        down_payment_cents=300000,
        service_fee_cents=2000,
        installment_count=9,
        first_installment_due_date="2026-11-01",
    )
    g2 = fixtures.active_agreement(
        api,
        ctx=ctx,
        policies=[
            factories.financed_policy(
                ctx["insurer_id"],
                policy_number="MC-G-7002",
                gross_premium_cents=100000,
            )
        ],
        down_payment_cents=52000,
        service_fee_cents=2000,
        installment_count=6,
        first_installment_due_date="2026-11-01",
    )
    assert g1["activated"]["amount_financed_cents"] == 1252000
    assert g1["activated"]["finance_charge_cents"] == 140850
    assert g2["activated"]["amount_financed_cents"] == 50000
    assert g2["activated"]["effective_annual_rate_bps"] == 1800, (
        "an amount financed of exactly 50000 cents is inside the first volume tier"
    )
    assert g2["activated"]["finance_charge_cents"] == 4500
    return g1, g2


def _first_installment(api, agreement_id):
    rows = fixtures.read_installments(api, agreement_id)
    return next(row for row in rows if row["installment_number"] == 1)


class TestGracePeriodBoundary:
    """The past-due mark and the fee assessment are two separate comparisons with
    two different strictnesses."""

    def test_a_pass_before_the_due_date_marks_nothing(self, api):
        """An installment due today is not yet late.

        The PRD states: "If it is `SCHEDULED`, its `due_date` is strictly earlier
        than the clock date and its `paid_cents` is less than its `amount_cents`,
        it moves `SCHEDULED` → `PAST_DUE` and its `version` advances."

        Design: Difficulty/boundary_precision_check/grace_period_boundary_and_late_fee_clamp_on_servicing_run
        """
        g1, _g2 = _two_active_notes(api)
        assert _first_installment(api, g1["agreement_id"])["amount_cents"] == 154761

        report = fixtures.advance_and_service(api, "2026-10-31T00:00:00Z")

        assert report["past_due_marked"] == 0, (
            "on 2026-10-31 neither installment's due date is strictly earlier "
            "than the clock date"
        )
        assert report["late_fees_assessed"] == 0
        assert report["agreements_advanced_to_late"] == 0

    def test_a_pass_on_the_grace_boundary_marks_past_due_but_charges_nothing(
        self, api
    ):
        """Exactly on the due date plus the grace period, nothing is charged.

        The PRD states: "Then, if an installment is `PAST_DUE` and the clock date
        is *strictly after* its `due_date` advanced by the regime's
        `grace_period_days`, a late fee may be assessed against it."

        Design: Difficulty/boundary_precision_check/grace_period_boundary_and_late_fee_clamp_on_servicing_run
        """
        g1, _g2 = _two_active_notes(api)
        fixtures.advance_and_service(api, "2026-10-31T00:00:00Z")

        report = fixtures.advance_and_service(api, "2026-11-11T00:00:00Z")

        assert report["past_due_marked"] == 2, (
            "both installments were due 2026-11-01 and are now past due"
        )
        assert report["agreements_advanced_to_late"] == 2, (
            "an agreement that acquires a newly past-due installment while "
            "CURRENT advances CURRENT -> LATE in the same pass"
        )
        assert report["late_fees_assessed"] == 0, (
            "2026-11-11 is exactly the due date advanced by ten grace days, and "
            "the comparison is strictly after"
        )
        agreement = fixtures.read_agreement(api, g1["agreement_id"])
        assert agreement["delinquency_stage"] == "LATE"
        assert agreement["late_fee_balance_cents"] == 0
        assert agreement["late_fee_count"] == 0

    def test_a_pass_one_day_past_the_boundary_assesses_the_rounded_fee(self, api):
        """One day past the boundary the fee is charged, rounded half up.

        The PRD states: "the fee amount is computed by taking the installment's
        `amount_cents` multiplied by the regime's `late_fee_bps`, divided by 10000
        and rounded half up, and then clamping that raw figure into the statutory
        band".

        Design: Difficulty/boundary_precision_check/grace_period_boundary_and_late_fee_clamp_on_servicing_run
        """
        g1, _g2 = _two_active_notes(api)
        fixtures.advance_and_service(api, "2026-10-31T00:00:00Z")
        fixtures.advance_and_service(api, "2026-11-11T00:00:00Z")

        report = fixtures.advance_and_service(api, "2026-11-12T00:00:00Z")

        assert report["past_due_marked"] == 0, (
            "both installments are already PAST_DUE, so nothing is newly marked"
        )
        assert report["late_fees_assessed"] == 2
        assert report["agreements_advanced_to_late"] == 0

        fees = fixtures.read_late_fees(api, g1["agreement_id"])
        assert len(fees) == 1, "one fee for the single past-due installment"
        fee = fees[0]
        expected = late_fee_cents(154761, 500, 500, 10000)
        assert round_half_up(154761 * 500, 10000) == 7738, (
            "the raw fee is round_half_up(7738.05), so rounding half up is the "
            "only order that lands on 7738"
        )
        assert fee["amount_cents"] == expected == 7738
        assert fee["status"] == "OUTSTANDING"
        assert fee["assessed_date"] == "2026-11-12", (
            "the assessment carries an assessed_date equal to the clock date"
        )
        assert fee["installment_number"] == 1, (
            "the assessment carries the installment_number of the installment "
            "that triggered it"
        )

    def test_the_statutory_floor_lifts_a_raw_fee_below_the_minimum(self, api):
        """A raw fee under the floor is raised to the floor after rounding.

        The PRD states: "Rounding happens before the clamp; clamping first and
        rounding second can differ by a cent."

        Design: Difficulty/boundary_precision_check/grace_period_boundary_and_late_fee_clamp_on_servicing_run
        """
        _g1, g2 = _two_active_notes(api)
        assert _first_installment(api, g2["agreement_id"])["amount_cents"] == 9083
        fixtures.advance_and_service(api, "2026-10-31T00:00:00Z")
        fixtures.advance_and_service(api, "2026-11-11T00:00:00Z")
        fixtures.advance_and_service(api, "2026-11-12T00:00:00Z")

        fees = fixtures.read_late_fees(api, g2["agreement_id"])
        assert len(fees) == 1
        raw = round_half_up(9083 * 500, 10000)
        assert raw == 454, "round_half_up(454.15) is 454, below the 500 floor"
        assert fees[0]["amount_cents"] == late_fee_cents(9083, 500, 500, 10000) == 500, (
            "the floor lifts the rounded 454 to 500; clamping before rounding, "
            "or forgetting the floor, reports 454"
        )
        assert fees[0]["assessed_date"] == "2026-11-12"

    def test_a_further_pass_assesses_nothing_more(self, api):
        """A single installment is charged once no matter how many passes run.

        The PRD states: "And no late fee may already exist for that agreement and
        that `installment_number` unless the existing one is `REVERSED`, so a
        single installment is charged once no matter how many passes run over it".

        Design: Difficulty/boundary_precision_check/grace_period_boundary_and_late_fee_clamp_on_servicing_run
        """
        g1, g2 = _two_active_notes(api)
        fixtures.advance_and_service(api, "2026-10-31T00:00:00Z")
        fixtures.advance_and_service(api, "2026-11-11T00:00:00Z")
        fixtures.advance_and_service(api, "2026-11-12T00:00:00Z")

        report = fixtures.advance_and_service(api, "2026-11-13T00:00:00Z")

        assert report["late_fees_assessed"] == 0, (
            "an OUTSTANDING fee already exists for each (agreement, "
            "installment_number) pair"
        )
        assert len(fixtures.read_late_fees(api, g1["agreement_id"])) == 1
        assert len(fixtures.read_late_fees(api, g2["agreement_id"])) == 1
        g1_after = fixtures.read_agreement(api, g1["agreement_id"])
        assert g1_after["late_fee_count"] == 1
        assert g1_after["late_fee_balance_cents"] == 7738
