"""Spreading a levy across member insurers under their per-member ceilings."""

from test_helpers import (
    CLOCK_STARTUP_UTC,
    assert_assessment,
    assert_instant_equals,
    assert_member_assessment,
    certify_assessment,
    draft_assessment,
    file_surcharge,
    pay_member_levy,
    read_assessment,
    read_insolvency,
    read_member_assessment,
    register_member_insurers,
    setup_certified_assessment,
    setup_triggered_insolvency,
)

M1 = {
    "naic_code": "20001",
    "insurer_name": "Huron Standard Insurance",
    "direct_written_premium_cents": 10_000_000,
    "annual_cap_rate_bps": 200,
}
M2 = {
    "naic_code": "20002",
    "insurer_name": "Saginaw Reciprocal",
    "direct_written_premium_cents": 30_000_000,
    "annual_cap_rate_bps": 50,
}
M3 = {
    "naic_code": "20003",
    "insurer_name": "Detroit Indemnity Company",
    "direct_written_premium_cents": 60_000_000,
    "annual_cap_rate_bps": 200,
}
THREE_MEMBERS = [M1, M2, M3]

SINGLE_MEMBER = [
    {
        "naic_code": "20001",
        "insurer_name": "Huron Standard Insurance",
        "direct_written_premium_cents": 10_000_000,
    }
]


class TestCappedRedistribution:
    """A regulator-reduced ceiling pushes need onto the members that are still in the pool."""

    def test_capped_member_exits_the_pool_and_the_rest_carry_a_larger_share(self):
        """If any did, each such member is instead fixed at exactly its `cap_amount_cents`, taken in
        `created_at` ascending then `sequence` ascending order, its cap amount is subtracted from the
        outstanding need, and it is removed from the pool — after which the next round re-spreads the
        reduced need over the remaining premium base, so the uncapped members necessarily carry a
        strictly larger share than their first-round raw figure.

        Design: Difficulty/combinatorial_formula/assessment_cap_forces_second_round_redistribution
        """
        env = setup_certified_assessment(
            member_specs=THREE_MEMBERS, needed_amount_cents=1_400_000
        )
        first, second, third = env["member_assessments"]
        for invoice in (first, second, third):
            assert_member_assessment(invoice)

        assert second["cap_amount_cents"] == 150_000, (
            "50 basis points of a 30000000 premium base is a 150000 ceiling, got "
            f"{second['cap_amount_cents']}"
        )
        assert second["levied_amount_cents"] == 150_000
        assert second["capped"] is True

        assert first["cap_amount_cents"] == 200_000
        assert first["levied_amount_cents"] == 178_572, (
            "the second round re-spreads 1250000 over the remaining 70000000 base, lifting this "
            f"member above its 140000 first-round share, got {first['levied_amount_cents']}"
        )
        assert first["capped"] is False
        assert third["cap_amount_cents"] == 1_200_000
        assert third["levied_amount_cents"] == 1_071_428, (
            f"the largest remaining member absorbs the rest, got {third['levied_amount_cents']}"
        )
        assert third["capped"] is False

    def test_levy_that_fits_inside_the_ceilings_closes_with_no_shortfall(self):
        """On the assessment itself, `levied_amount_cents` becomes the sum of the invoiced amounts,
        `member_count` becomes the number of invoices created, `shortfall_cents` becomes the
        assessment's `needed_amount_cents` less its `levied_amount_cents` — positive exactly when the
        per-member ceilings exhausted the pool before the need was met — and `certified_at_utc` is
        stamped from the logical clock as the assessment moves `DRAFT → CERTIFIED`.

        Design: Difficulty/combinatorial_formula/assessment_cap_forces_second_round_redistribution
        """
        env = setup_certified_assessment(
            member_specs=THREE_MEMBERS, needed_amount_cents=1_400_000
        )
        assessment = read_assessment(env["assessment"]["id"])
        assert_assessment(assessment)
        assert assessment["status"] == "CERTIFIED", assessment["status"]
        assert assessment["levied_amount_cents"] == 1_400_000, (
            f"the whole need was raised, got {assessment['levied_amount_cents']}"
        )
        assert assessment["shortfall_cents"] == 0
        assert assessment["member_count"] == 3
        assert (
            sum(i["levied_amount_cents"] for i in env["member_assessments"]) == 1_400_000
        ), "the invoiced amounts must sum to the levied total exactly"

        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["assessment_shortfall_cents"] == 0


class TestCertificationCascade:
    """One certify call writes invoices, the assessment rollup and the parent file."""

    def test_every_member_capping_out_leaves_the_gap_as_shortfall(self):
        """When no member's raw share exceeds its cap in the first round, the levy closes in a single
        round at exactly `needed_amount_cents` with `shortfall_cents` at 0; when every member caps
        out, the levy stops short and the whole gap lands in `shortfall_cents`.

        Design: Difficulty/transitive_cascade/certification_cascades_member_levies_into_assessment_and_insolvency_shortfall
        """
        env = setup_certified_assessment(
            member_specs=THREE_MEMBERS, needed_amount_cents=2_500_000
        )
        assessment = env["assessment"]
        assert_assessment(assessment)
        assert assessment["levied_amount_cents"] == 1_550_000, (
            "total member capacity is 200000 + 150000 + 1200000, got "
            f"{assessment['levied_amount_cents']}"
        )
        assert assessment["shortfall_cents"] == 950_000, (
            f"the unfundable remainder of the need is the shortfall, got {assessment['shortfall_cents']}"
        )
        assert assessment["member_count"] == 3
        assert_instant_equals(
            assessment["certified_at_utc"],
            CLOCK_STARTUP_UTC,
            f"certification is stamped from the logical clock, got {assessment['certified_at_utc']}",
        )

        first, second, third = env["member_assessments"]
        assert [i["levied_amount_cents"] for i in (first, second, third)] == [
            200_000,
            150_000,
            1_200_000,
        ]
        for invoice in (first, second, third):
            assert invoice["capped"] is True, (
                f"every member was fixed at its ceiling, got capped={invoice['capped']}"
            )
            assert invoice["billing_status"] == "INVOICED", invoice["billing_status"]

    def test_shortfall_travels_two_hops_onto_the_insolvency_file(self):
        """The resulting `shortfall_cents` is added into the insolvency file's
        `assessment_shortfall_cents`.

        Design: Difficulty/transitive_cascade/certification_cascades_member_levies_into_assessment_and_insolvency_shortfall
        """
        env = setup_triggered_insolvency()
        register_member_insurers(THREE_MEMBERS)
        assessment = draft_assessment(env["insolvency"]["id"], needed_amount_cents=2_500_000)

        before = read_insolvency(env["insolvency"]["id"])
        assert before["assessment_shortfall_cents"] == 0, (
            "a levy still in draft contributes nothing to the file's shortfall counter"
        )

        certified = certify_assessment(assessment["id"])
        assert certified["shortfall_cents"] == 950_000

        after = read_insolvency(env["insolvency"]["id"])
        assert after["assessment_shortfall_cents"] == 950_000, (
            "the certified shortfall must land on the parent file, got "
            f"{after['assessment_shortfall_cents']}"
        )


class TestIndependentBillingAndRecoupmentDimensions:
    """One invoice row, two axes that never constrain each other."""

    def test_partial_payment_advances_billing_and_leaves_recoupment_untouched(self):
        """Every payment recomputes the parent assessment's `collected_amount_cents` as the sum of
        `paid_amount_cents` across its invoices, and leaves `recoupment_status` untouched.

        Design: Difficulty/non_linear_state_machine/member_assessment_billing_and_recoupment_dimensions_move_independently
        """
        env = setup_certified_assessment(
            member_specs=SINGLE_MEMBER, needed_amount_cents=150_000
        )
        invoice = env["member_assessment"]
        assert invoice["levied_amount_cents"] == 150_000
        assert invoice["billing_status"] == "INVOICED"
        assert invoice["recoupment_status"] == "NOT_STARTED"

        paid = pay_member_levy(env, 50_000, "WIRE-77")
        assert_member_assessment(paid)
        assert paid["billing_status"] == "PARTIALLY_PAID", paid["billing_status"]
        assert paid["paid_amount_cents"] == 50_000
        assert paid["recoupment_status"] == "NOT_STARTED", (
            f"cash collection must not move the recoupment axis, got {paid['recoupment_status']}"
        )

        assessment = read_assessment(env["assessment"]["id"])
        assert assessment["status"] == "CERTIFIED", (
            "a part-paid invoice must not settle the assessment"
        )
        assert assessment["collected_amount_cents"] == 50_000

    def test_surcharge_filing_advances_recoupment_and_leaves_billing_untouched(self):
        """A successful filing moves the invoice `NOT_STARTED → SURCHARGE_FILED`, stores
        `surcharge_rate_bps` and `surcharge_base_cents` from the filing, leaves `billing_status`
        untouched, and computes `projected_recoupment_cents` as `surcharge_base_cents` multiplied by
        `surcharge_rate_bps`, divided by ten thousand, rounded half up to whole cents, and then
        limited to whichever is smaller of that figure and `levied_amount_cents` — a member may not
        project recovering more than it was levied.

        Design: Difficulty/non_linear_state_machine/member_assessment_billing_and_recoupment_dimensions_move_independently
        """
        env = setup_certified_assessment(
            member_specs=SINGLE_MEMBER, needed_amount_cents=150_000
        )
        pay_member_levy(env, 50_000, "WIRE-77")
        filed = file_surcharge(env, 25, 60_000_000, "RS-2026-01")

        assert_member_assessment(filed)
        assert filed["recoupment_status"] == "SURCHARGE_FILED", filed["recoupment_status"]
        assert filed["surcharge_rate_bps"] == 25
        assert filed["surcharge_base_cents"] == 60_000_000
        assert filed["projected_recoupment_cents"] == 150_000, (
            "25 basis points of 60000000 is 150000, which is exactly the levy ceiling, got "
            f"{filed['projected_recoupment_cents']}"
        )
        assert filed["recouped_amount_cents"] == 0, (
            "projecting a recovery collects nothing"
        )

        reread = read_member_assessment(filed["id"])
        assert reread["billing_status"] == "PARTIALLY_PAID", (
            f"the surcharge filing must not move the billing axis, got {reread['billing_status']}"
        )
        assert reread["paid_amount_cents"] == 50_000
