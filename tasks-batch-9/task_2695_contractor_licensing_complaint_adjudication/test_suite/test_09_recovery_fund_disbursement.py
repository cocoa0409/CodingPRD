"""One payment call, four causal hops, and a pool divided across a cohort.

Disbursement is the widest cascade in the system: the money moves, the licence
falls into an indefinite suspension, and the qualifier's slot is released — none
of which appears on the row the endpoint returns. When the pool cannot cover the
cohort, the same call also divides it pro rata and hands the odd cent to the
oldest claim.
"""

from test_helpers import (
    FUND_ADJUDICATOR_HEADERS,
    LICENSING_ANALYST_HEADERS,
    AssignmentStatus,
    ClaimStatus,
    CompliancePosture,
    LicenseStatus,
    SuspensionReason,
    assert_fields,
    assert_qualification_count,
    assert_recovery_fund_claim,
    assert_suspension,
    constants as K,
    fixtures as FX,
    validate_success,
)


def _approved_claim_awaiting_disbursement(api):
    """A ripe 900,000 judgment claim approved against a fully funded appropriation."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    fund_account = FX.open_fund_account(api)
    ctx = FX.mint_active_license(api)
    consumer = FX.register_consumer(
        api, full_name="Pat Ratepayer", contact_email="pat@home.test"
    )
    FX.set_clock(api, "2026-09-01T00:00:00Z")
    _complaint, claim = FX.approved_court_judgment_claim(
        api, ctx, fund_account, consumer
    )
    return ctx, fund_account, claim


def test_01_paying_the_claim_stamps_it_and_drains_the_pool_by_the_award(api):
    """The first two hops: the claim is paid and the cash leaves the appropriation.

    PRD: "**Second**, *because* cash has moved, the appropriation's `balance_cents`
    falls by the total disbursed while the licence's `recovery_paid_to_date_cents`
    and `outstanding_recovery_repayment_cents` both rise by that same total, and the
    licensee's `outstanding_recovery_payout_cents` rises with them."

    Design: Difficulty/transitive_cascade/recovery_payout_cascade_suspends_license_and_releases_qualifier_slot
    """
    ctx, fund_account, claim = _approved_claim_awaiting_disbursement(api)

    paid = FX.pay_claim(api, claim["id"], fund_account["id"])

    assert_recovery_fund_claim(
        paid,
        status=ClaimStatus.PAID,
        paid_amount_cents=900000,
        paid_on="2026-12-04",
    )
    assert_fields(
        FX.read_fund_account(api, fund_account["id"]), {"balance_cents": 4100000}
    )
    assert_fields(
        FX.read_license(api, ctx.license_id),
        {
            "recovery_paid_to_date_cents": 900000,
            "outstanding_recovery_repayment_cents": 900000,
        },
    )
    assert_fields(
        validate_success(
            api.get_licensee(ctx.licensee_id, LICENSING_ANALYST_HEADERS)
        ),
        {"outstanding_recovery_payout_cents": 900000},
    )


def test_02_the_payout_debt_suspends_the_licence_indefinitely(api):
    """The third hop turns a fiscal fact into a licensure state with no end date.

    PRD: "**Third**, *because* `outstanding_recovery_repayment_cents` is now greater
    than zero, the licence moves `ACTIVE → SUSPENDED` with `suspension_reason` of
    `RECOVERY_FUND_PAYOUT` and `suspension_until` left null — the suspension is
    indefinite and lasts until the money is repaid — and its `compliance_posture`
    becomes `NON_COMPLIANT`."

    Design: Difficulty/transitive_cascade/recovery_payout_cascade_suspends_license_and_releases_qualifier_slot
    """
    ctx, fund_account, claim = _approved_claim_awaiting_disbursement(api)

    FX.pay_claim(api, claim["id"], fund_account["id"])

    suspended = FX.read_license(api, ctx.license_id)
    assert_fields(
        suspended,
        {
            "status": LicenseStatus.SUSPENDED,
            "compliance_posture": CompliancePosture.NON_COMPLIANT,
        },
    )
    assert_suspension(suspended, SuspensionReason.RECOVERY_FUND_PAYOUT, None)


def test_03_the_suspension_releases_the_qualifier_slot_invisibly(api):
    """The fourth hop touches neither the claim row nor the licence row.

    PRD: "**Fourth**, *because* the licence has entered `SUSPENDED`, every
    designation on it in `ACTIVE` moves to `SUSPENDED_BY_LICENSE` and each affected
    qualifier's `active_qualification_count` falls by one."

    Design: Difficulty/transitive_cascade/recovery_payout_cascade_suspends_license_and_releases_qualifier_slot
    """
    ctx, fund_account, claim = _approved_claim_awaiting_disbursement(api)
    assignment = FX.find_assignment_for_license(api, ctx.license_id)
    assert_qualification_count(
        validate_success(
            api.get_qualifying_individual(
                ctx.individual_id, LICENSING_ANALYST_HEADERS
            )
        ),
        1,
    )

    FX.pay_claim(api, claim["id"], fund_account["id"])

    assert_fields(
        validate_success(
            api.get_qualifier_assignment(assignment["id"], LICENSING_ANALYST_HEADERS)
        ),
        {"status": AssignmentStatus.SUSPENDED_BY_LICENSE},
    )
    assert_qualification_count(
        validate_success(
            api.get_qualifying_individual(
                ctx.individual_id, LICENSING_ANALYST_HEADERS
            )
        ),
        0,
    )


def _two_approved_claims_over_a_short_pool(api):
    """A 900,000 pool facing a cohort awarded 1,100,000 on one licence."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    fund_account = FX.open_fund_account(api, initial_balance_cents=900000)
    ctx = FX.mint_active_license(api)
    consumer_one = FX.register_consumer(
        api, full_name="Pat Ratepayer", contact_email="pat@home.test"
    )
    consumer_two = FX.register_consumer(
        api, full_name="Rae Homeowner", contact_email="rae@home.test"
    )
    FX.set_clock(api, "2026-09-01T00:00:00Z")
    complaint_one = FX.file_complaint(
        api,
        consumer_one["id"],
        ctx.license_id,
        alleged_loss_cents=800000,
        contract_date="2026-08-05",
        work_completed_on="2026-08-20",
        description="Service upgrade abandoned mid-job",
    )
    FX.screen_accepted(api, complaint_one["id"])
    complaint_two = FX.file_complaint(
        api,
        consumer_two["id"],
        ctx.license_id,
        alleged_loss_cents=500000,
        contract_date="2026-08-06",
        work_completed_on="2026-08-21",
        description="Subpanel never energised, deposit retained",
    )
    FX.screen_accepted(api, complaint_two["id"])
    FX.set_clock(api, "2026-11-01T00:00:00Z")
    claim_a = FX.file_judgment_claim(
        api,
        fund_account["id"],
        complaint_one["id"],
        consumer_one["id"],
        700000,
        750000,
        "CV-2026-201",
        "2026-09-05",
    )
    FX.set_clock(api, "2026-11-02T00:00:00Z")
    claim_b = FX.file_judgment_claim(
        api,
        fund_account["id"],
        complaint_two["id"],
        consumer_two["id"],
        400000,
        450000,
        "CV-2026-202",
        "2026-09-05",
    )
    FX.set_clock(api, "2026-12-04T00:00:00Z")
    approved_a = FX.approve_claim(api, claim_a["id"])
    approved_b = FX.approve_claim(api, claim_b["id"])
    return ctx, fund_account, approved_a, approved_b


def test_04_the_cohort_is_awarded_in_full_before_any_cash_is_considered(api):
    """Both awards stand at their computed figures even though the pool is short.

    PRD: "Note what the award is **not** limited by: the appropriation's
    `balance_cents`."

    Design: Difficulty/combinatorial_formula/prorata_distribution_of_exhausted_fund_across_two_approved_claims
    """
    _ctx, _fund_account, approved_a, approved_b = _two_approved_claims_over_a_short_pool(
        api
    )

    assert_recovery_fund_claim(
        approved_a, status=ClaimStatus.APPROVED, awarded_amount_cents=700000
    )
    assert_recovery_fund_claim(
        approved_b, status=ClaimStatus.APPROVED, awarded_amount_cents=400000
    )


def test_05_the_short_pool_is_divided_pro_rata_with_the_odd_cent_going_oldest(api):
    """One payment call pays both siblings 572,728 and 327,272 and empties the pool.

    PRD: "with 900,000 cents in the pool and a cohort of two claims awarded 700,000
    and 400,000, the total awarded of 1,100,000 exceeds the balance, so the first
    claim's floored share is 572,727 and the second's is 327,272; the one leftover
    cent goes to the earlier-created claim, giving 572,728 and 327,272; the pool
    falls to zero and the licence carries 900,000 of repayment debt."

    Design: Difficulty/combinatorial_formula/prorata_distribution_of_exhausted_fund_across_two_approved_claims
    """
    _ctx, fund_account, approved_a, approved_b = _two_approved_claims_over_a_short_pool(
        api
    )

    paid_a = FX.pay_claim(api, approved_a["id"], fund_account["id"])

    assert_recovery_fund_claim(
        paid_a,
        status=ClaimStatus.PAID,
        paid_amount_cents=572728,
        paid_on="2026-12-04",
    )
    assert_recovery_fund_claim(
        validate_success(api.get_claim(approved_b["id"], FUND_ADJUDICATOR_HEADERS)),
        status=ClaimStatus.PAID,
        paid_amount_cents=327272,
        paid_on="2026-12-04",
    )
    assert_fields(
        FX.read_fund_account(api, fund_account["id"]), {"balance_cents": 0}
    )


def test_06_the_whole_distribution_lands_as_one_debt_on_the_licence(api):
    """The two shares add back to the pool and suspend the licence once.

    PRD: "Every cohort member then moves `APPROVED → PAID` with `paid_on` set to the
    clock date, **including sibling claims that were not the request's target**."

    Design: Difficulty/combinatorial_formula/prorata_distribution_of_exhausted_fund_across_two_approved_claims
    """
    ctx, fund_account, approved_a, _approved_b = _two_approved_claims_over_a_short_pool(
        api
    )

    FX.pay_claim(api, approved_a["id"], fund_account["id"])

    suspended = FX.read_license(api, ctx.license_id)
    assert_fields(
        suspended,
        {
            "recovery_paid_to_date_cents": 900000,
            "outstanding_recovery_repayment_cents": 900000,
            "status": LicenseStatus.SUSPENDED,
        },
    )
    assert_suspension(suspended, SuspensionReason.RECOVERY_FUND_PAYOUT, None)
    assert_fields(
        validate_success(
            api.get_licensee(ctx.licensee_id, LICENSING_ANALYST_HEADERS)
        ),
        {"outstanding_recovery_payout_cents": 900000},
    )
    assert_qualification_count(
        validate_success(
            api.get_qualifying_individual(
                ctx.individual_id, LICENSING_ANALYST_HEADERS
            )
        ),
        0,
    )
