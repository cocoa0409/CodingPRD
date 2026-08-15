"""Insulation grant obligation math: the pinned per-component rounding of the
grant split, the PROVISIONAL vs FINAL obligation variants reconciled at
disbursement, fund ledger conservation across issue/decline/re-issue/disburse,
and the exact priority-score weight sum."""
from test_helpers import (
    assert_fund_ledger_invariants,
    assert_same_instant,
    create_application,
    create_fund,
    decide_application,
    issue_offer,
    read_fund,
    screen_application,
    setup_adopted_study_with_parcel,
    setup_decided_application,
    setup_grant_committed,
    submit_application,
    TEST_USERS,
    validate_success,
)

ADMIN = TEST_USERS["noise_office_admin_headers"]
LIAISON = TEST_USERS["community_liaison_headers"]
COORDINATOR = TEST_USERS["study_coordinator_headers"]


def _setup_tier1_school_application(api):
    """ACTIVE fund (5,000,000) + ADOPTED study with a SCHOOL parcel (final
    exposure 66.0, band 65) + application decided ELIGIBLE_TIER1 (permitted by
    the institution land use) on est_cost_cents 1,111,115."""
    fund = create_fund(fiscal_year="FY2027", total_allocation_cents=5_000_000)
    ctx = setup_adopted_study_with_parcel(
        measured=66.0, modeled=67.5, land_use="SCHOOL", zone_code="Z3"
    )
    application = create_application(
        ctx["parcel"]["id"], rooms_count=3, est_cost_cents=1_111_115
    )
    submit_application(application["id"])
    screen_application(application["id"])
    application = decide_application(application["id"], "ELIGIBLE_TIER1")
    return {
        "fund": read_fund(fund["id"]),
        "study": ctx["study"],
        "parcel": ctx["parcel"],
        "application": application,
    }


def test_grant_split_rounds_each_component_before_summing(api):
    """PRD 3.8: "The rounding order is pinned — each component is rounded to
    whole cents *first*, and only then are the three summed — so an estimated
    cost of 1,111,115 cents at tier one obligates exactly 1,277,783 cents
    (structure 1,111,115, contingency 111,112, administration 55,556), one cent
    more than a naive sum-then-round would produce."
    PRD 3.8: "The fund moves that amount from available to reserved —
    incrementing the fund's `version`".

    Design: Difficulty/combinatorial_formula/grant_split_round_per_component_then_sum_pinned
    """
    ctx = _setup_tier1_school_application(api)

    offered = issue_offer(ctx["application"]["id"], ctx["fund"]["id"])
    # Per-component round-half-up: structure 1,111,115; contingency
    # round(111,111.5) = 111,112; admin round(55,555.75) = 55,556.
    assert offered["offered_amount_cents"] == 1_277_783

    fund = read_fund(ctx["fund"]["id"])
    assert fund["reserved_cents"] == 1_277_783
    assert fund["available_cents"] == 5_000_000 - 1_277_783
    assert_fund_ledger_invariants(fund)


def test_grant_split_pinned_rounding_governs_final_disbursement(api):
    """PRD 3.8: "Grant money is obligated through a pinned split, computed in a
    provisional variant at offer time against `est_cost_cents` and in a final
    variant at disbursement against `actual_cost_cents`."
    PRD 3.8: "The final obligation is computed with the same pinned split on
    the actual basis; `disbursed_cents` records the final total".

    Design: Difficulty/combinatorial_formula/grant_split_round_per_component_then_sum_pinned
    """
    ctx = _setup_tier1_school_application(api)
    offered = issue_offer(ctx["application"]["id"], ctx["fund"]["id"])
    assert offered["offered_amount_cents"] == 1_277_783
    validate_success(api.accept_offer(ctx["application"]["id"], {}, LIAISON), 200)

    # Final split on the same 1,111,115 basis reproduces the same pinned total.
    disbursed = validate_success(
        api.disburse_application(
            ctx["application"]["id"], {"actual_cost_cents": 1_111_115}, ADMIN
        ),
        200,
    )
    assert disbursed["disbursed_cents"] == 1_277_783
    assert disbursed["funding_status"] == "REIMBURSED"

    fund = read_fund(ctx["fund"]["id"])
    assert fund["disbursed_cents"] == 1_277_783
    assert fund["reserved_cents"] == 0
    assert fund["available_cents"] == 3_722_217
    assert_fund_ledger_invariants(fund)


def test_provisional_obligation_reserves_against_estimated_cost(api):
    """PRD 3.8: "For a tier-one application, the structure component is the cost
    basis capped at 8,000,000 cents ... The contingency component is 10 percent
    of the structure, rounded half-up to whole cents. The administration
    component is 5 percent of the structure, rounded half-up to whole cents and
    capped at 250,000 cents."
    PRD 3.8: "the application records the reserving fund on `fund_id`, stamps
    `offer_issued_at`, computes `offer_expires_at` as exactly 45 days after
    issuance, and moves to `OFFER_ISSUED`".

    Design: Difficulty/dual_variant_calc/grant_provisional_vs_final_obligation_reconciled
    """
    ctx = setup_decided_application(
        decision="ELIGIBLE_TIER1",
        est_cost_cents=7_777_777,
        rooms_count=5,
        fund_total_cents=20_000_000,
        parcel_measured=72.0,
        parcel_modeled=73.0,
    )

    offered = issue_offer(ctx["application"]["id"], ctx["fund"]["id"])
    # PROVISIONAL on 7,777,777: structure 7,777,777 + contingency 777,778
    # + admin 250,000 (5% = 388,889 capped) = 8,805,555.
    assert offered["funding_status"] == "OFFER_ISSUED"
    assert offered["offered_amount_cents"] == 8_805_555
    assert offered["fund_id"] == ctx["fund"]["id"]
    # Issued at the startup clock 2026-08-01 -> expiry 2026-09-15.
    assert_same_instant(
        offered["offer_expires_at"], "2026-09-15T00:00:00Z", "offer_expires_at"
    )

    fund = read_fund(ctx["fund"]["id"])
    assert fund["available_cents"] == 11_194_445
    assert fund["reserved_cents"] == 8_805_555
    assert fund["disbursed_cents"] == 0
    assert_fund_ledger_invariants(fund)


def test_final_obligation_reconciled_at_disbursement(api):
    """PRD 3.8: "The final obligation is computed with the same pinned split on
    the actual basis; `disbursed_cents` records the final total; the fund moves
    that amount from reserved to disbursed, and when the final total is smaller
    than the provisional reservation the surplus flows from reserved back to
    available. The application becomes `REIMBURSED`, terminal on the funding
    dimension."

    Design: Difficulty/dual_variant_calc/grant_provisional_vs_final_obligation_reconciled
    """
    ctx = setup_grant_committed(
        decision="ELIGIBLE_TIER1",
        est_cost_cents=7_777_777,
        rooms_count=5,
        fund_total_cents=20_000_000,
        parcel_measured=72.0,
        parcel_modeled=73.0,
    )
    # The provisional reservation held 8,805,555.
    assert ctx["application"]["offered_amount_cents"] == 8_805_555

    disbursed = validate_success(
        api.disburse_application(
            ctx["application"]["id"], {"actual_cost_cents": 7_000_000}, ADMIN
        ),
        200,
    )
    # FINAL on 7,000,000: structure 7,000,000 + contingency 700,000
    # + admin 250,000 (350,000 capped) = 7,950,000.
    assert disbursed["disbursed_cents"] == 7_950_000
    assert disbursed["funding_status"] == "REIMBURSED"

    fund = read_fund(ctx["fund"]["id"])
    # The 855,555-cent delta flowed back from reserved to available.
    assert fund["available_cents"] == 12_050_000
    assert fund["reserved_cents"] == 0
    assert fund["disbursed_cents"] == 7_950_000
    assert_fund_ledger_invariants(fund)


def test_fund_conservation_across_issue_decline_and_reissue(api):
    """PRD 3.8: "The fund is a ledger: the invariant `available_cents` +
    `reserved_cents` + `disbursed_cents` = `total_allocation_cents` holds at all
    times, with reservations and disbursements moving money between the
    buckets."
    PRD 3.8: "Declining the offer moves it to `OFFER_DECLINED`, releases the
    reservation in the same manner, and immediately re-queues the application to
    `UNFUNDED` within the same request, leaving it eligible for a future offer."

    Design: Difficulty/compensating_invariant/fund_conservation_across_issue_decline_reissue_disburse
    """
    ctx = setup_decided_application(
        decision="ELIGIBLE_TIER2", est_cost_cents=5_000_000, rooms_count=6
    )

    # TIER2 provisional on 5,000,000: structure 4,000,000 (80% at the cap)
    # + contingency 400,000 + admin 200,000 = 4,600,000.
    offered = issue_offer(ctx["application"]["id"], ctx["fund"]["id"])
    assert offered["offered_amount_cents"] == 4_600_000
    fund = read_fund(ctx["fund"]["id"])
    assert (fund["available_cents"], fund["reserved_cents"], fund["disbursed_cents"]) == (
        400_000,
        4_600_000,
        0,
    )
    assert_fund_ledger_invariants(fund)

    validate_success(api.decline_offer(ctx["application"]["id"], {}, LIAISON), 200)
    fund = read_fund(ctx["fund"]["id"])
    # The reservation was released back to available in full.
    assert (fund["available_cents"], fund["reserved_cents"], fund["disbursed_cents"]) == (
        5_000_000,
        0,
        0,
    )
    assert_fund_ledger_invariants(fund)
    # The decline re-queued the application to UNFUNDED within the same request.
    reread = validate_success(api.get_application(ctx["application"]["id"], COORDINATOR))
    assert reread["funding_status"] == "UNFUNDED"

    reissued = issue_offer(ctx["application"]["id"], ctx["fund"]["id"])
    assert reissued["funding_status"] == "OFFER_ISSUED"
    assert reissued["offered_amount_cents"] == 4_600_000
    fund = read_fund(ctx["fund"]["id"])
    assert (fund["available_cents"], fund["reserved_cents"], fund["disbursed_cents"]) == (
        400_000,
        4_600_000,
        0,
    )
    assert_fund_ledger_invariants(fund)


def test_fund_conservation_disbursement_releases_provisional_surplus(api):
    """PRD 3.8: "The fund is a ledger: the invariant `available_cents` +
    `reserved_cents` + `disbursed_cents` = `total_allocation_cents` holds at all
    times, with reservations and disbursements moving money between the
    buckets."
    PRD 3.8: "the fund moves that amount from reserved to disbursed, and when
    the final total is smaller than the provisional reservation the surplus
    flows from reserved back to available."

    Design: Difficulty/compensating_invariant/fund_conservation_across_issue_decline_reissue_disburse
    """
    ctx = setup_grant_committed(
        decision="ELIGIBLE_TIER2", est_cost_cents=5_000_000, rooms_count=6
    )
    # Provisional reservation: 4,600,000.
    assert ctx["application"]["offered_amount_cents"] == 4_600_000

    disbursed = validate_success(
        api.disburse_application(
            ctx["application"]["id"], {"actual_cost_cents": 4_000_000}, ADMIN
        ),
        200,
    )
    # TIER2 final on 4,000,000: structure 3,200,000 + contingency 320,000
    # + admin 160,000 = 3,680,000; the 920,000 surplus returns to available.
    assert disbursed["disbursed_cents"] == 3_680_000
    assert disbursed["funding_status"] == "REIMBURSED"

    fund = read_fund(ctx["fund"]["id"])
    assert (fund["available_cents"], fund["reserved_cents"], fund["disbursed_cents"]) == (
        1_320_000,
        0,
        3_680_000,
    )
    assert_fund_ledger_invariants(fund)


def test_priority_score_exact_weight_sum(api):
    """PRD 3.8: "The priority score is an integer sum: a `dnl_band` of at least
    75 contributes 80 points, at least 70 but below 75 contributes 60, at least
    65 but below 70 contributes 40, and lower bands contribute nothing; `SCHOOL`
    or `HOSPITAL` land use contributes 20, `RESIDENTIAL` 10, and other uses
    none; a linked complainant whose `substantiated_count` is at least five
    contributes 10; and a dwelling with at least eight rooms contributes 5."
    PRD 3.8: "computes the application's `priority_score` and its
    `tier_cap_cents` — 8,000,000 cents for tier one, 4,000,000 for tier two".

    Design: Corner/calculations/priority_score_exact_weight_sum
    """
    # HOSPITAL parcel, final exposure 76.0 -> band 75; rooms 9; no complainant.
    # Score = 80 (band 75) + 20 (HOSPITAL) + 0 (no linked complainant)
    # + 5 (rooms >= 8) = 105.
    ctx = setup_decided_application(
        decision="ELIGIBLE_TIER1",
        est_cost_cents=300_000,
        rooms_count=9,
        parcel_measured=76.0,
        parcel_modeled=77.0,
        land_use="HOSPITAL",
    )
    application = ctx["application"]
    assert application["eligibility_status"] == "ELIGIBLE_TIER1"
    assert application["priority_score"] == 105
    assert application["tier_cap_cents"] == 8_000_000
