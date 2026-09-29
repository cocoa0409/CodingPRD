"""Where each rounding and each snapshot sits inside a composed money formula."""

from test_helpers import (
    ClaimDecision,
    FundingStatus,
    assert_cap_pool_conserved,
    build_northwind_base,
    build_northwind_three_credit_enrolled,
    build_summit_second_claim_filed,
    build_summit_third_claim_filed,
    validate_success,
)


def test_the_per_credit_rate_is_rounded_once_when_the_listing_is_curated(api):
    """41,002 discounted 25% lands on a half cent and rounds up to 30,752 there.

    PRD §3.3: "The `negotiated_tuition_per_credit_cents` is the program's
    `list_tuition_per_credit_cents` multiplied by one minus the agreement's
    `negotiated_discount_pct`, with the result rounded half up to a whole cent at that
    point and only that point."

    PRD §2.5: "First, the negotiated per-credit tuition rate is rounded to whole cents
    once, at the moment a catalog listing is created, and it is that already-rounded
    rate that gets multiplied by a term's credit count later; the alternative order —
    multiplying the exact discounted product by credits and rounding the total — is not
    what this system does and diverges whenever the exact per-credit product carries a
    half-cent remainder."

    Design: Difficulty/combinatorial_formula/per_credit_discount_rounding_precedes_credit_multiplication
    """
    s = build_northwind_base(api)

    listing = validate_success(api.get_catalog_listing(s.listing_id, s.benefit_admin))
    assert listing["negotiated_tuition_per_credit_cents"] == 30_752

    enrollment = s.enroll(
        term_code="2026-FA",
        term_start_date="2026-09-01",
        term_end_date="2026-12-15",
        credits=3,
    )
    assert enrollment["gross_tuition_cents"] == 30_752 * 3 == 92_256
    assert enrollment["gross_tuition_cents"] != 92_255


def test_the_reserve_multiplies_the_already_rounded_rate_then_rounds_again(api):
    """Rate first, then credits, then the 0.60 share: 30,752 → 92,256 → 55,354.

    PRD §3.4: "`gross_tuition_cents` is the listing's already-rounded
    `negotiated_tuition_per_credit_cents` multiplied by the enrollment's `credits`."

    PRD §3.4: "`drop_deadline_date` is the `term_start_date` advanced by the policy's
    `drop_window_days`; a withdrawal on or before that date releases funding with no
    repayment obligation."

    Design: Difficulty/combinatorial_formula/per_credit_discount_rounding_precedes_credit_multiplication
    """
    s = build_northwind_three_credit_enrolled(api)

    enrollment = s.read_enrollment()
    assert enrollment["gross_tuition_cents"] == 92_256
    assert enrollment["employer_reserved_cents"] == 55_354
    assert enrollment["employer_reserved_cents"] != 55_353
    assert enrollment["employee_share_cents"] == 36_902
    assert enrollment["drop_deadline_date"] == "2026-09-15"

    employee = s.read_employee()
    assert employee["cap_reserved_cents"] == 55_354
    assert_cap_pool_conserved(employee, 600_000)


def test_the_fee_tier_reads_the_basis_as_it_stood_before_this_settlement(api):
    """A 4,990,000 pre-state basis keeps the second settlement in tier 1 at 5%.

    PRD §3.6: "Third, the fee basis is snapshotted as the employer's
    `total_disbursed_cents` as it stood *before* this request mutated anything, which
    means it excludes the amount being approved right now."

    PRD §3.6: "Fourth, the fee percentage is chosen from that basis: 5 percent while
    the basis is below 5,000,000 cents (fifty thousand dollars of lifetime employer
    spend), 4 percent while the basis is at least 5,000,000 cents and below 20,000,000
    cents, and 3 percent once the basis reaches 20,000,000 cents."

    Design: Difficulty/combinatorial_formula/admin_fee_tier_keyed_on_pre_settlement_employer_disbursement
    """
    s = build_summit_second_claim_filed(api)
    assert s.read_listing(s.listing_id)["negotiated_tuition_per_credit_cents"] == 499_000
    assert (
        s.read_listing(s.second_listing_id)["negotiated_tuition_per_credit_cents"]
        == 32_802
    )
    assert (
        s.read_listing(s.third_listing_id)["negotiated_tuition_per_credit_cents"]
        == 40_000
    )

    pre_state = s.read_employer()
    assert pre_state["total_disbursed_cents"] == 4_990_000
    assert pre_state["total_admin_fee_cents"] == 0

    decided = s.decide_claim(ClaimDecision.APPROVE)
    assert decided["approved_amount_cents"] == 68_884
    assert decided["platform_admin_fee_cents"] == 3_444
    assert decided["platform_admin_fee_cents"] != 2_755

    settled = s.read_enrollment(s.second_enrollment_id)
    assert settled["gross_tuition_cents"] == 98_406
    assert settled["employer_settled_cents"] == 68_884
    assert settled["funding_status"] == FundingStatus.SETTLED


def test_each_settlement_pushes_the_next_one_toward_a_cheaper_tier(api):
    """The third claim reads a 5,058,884 basis and drops from 5% to 4%.

    PRD §3.6: "Sixth, the employer's `total_disbursed_cents` grows by
    `approved_amount_cents` and its `total_admin_fee_cents` grows by
    `platform_admin_fee_cents`, so the *next* settlement may well land in a cheaper
    tier."

    PRD §2.8: "`total_admin_fee_cents` is the sum of `platform_admin_fee_cents` over
    that employer's claims whose `status` is `APPROVED`."

    Design: Difficulty/combinatorial_formula/admin_fee_tier_keyed_on_pre_settlement_employer_disbursement
    """
    s = build_summit_third_claim_filed(api)
    pre_state = s.read_employer()
    assert pre_state["total_disbursed_cents"] == 5_058_884
    assert pre_state["total_admin_fee_cents"] == 3_444

    decided = s.decide_claim(ClaimDecision.APPROVE)
    assert decided["approved_amount_cents"] == 48_000
    assert decided["platform_admin_fee_cents"] == 1_920
    assert decided["platform_admin_fee_cents"] != 2_400

    employer = s.read_employer()
    assert employer["total_disbursed_cents"] == 5_106_884
    assert employer["total_admin_fee_cents"] == 5_364

    third = s.read_enrollment(s.third_enrollment_id)
    assert third["gross_tuition_cents"] == 80_000
    assert third["employer_settled_cents"] == 48_000
    assert third["employer_disbursed_cents"] == 48_000
