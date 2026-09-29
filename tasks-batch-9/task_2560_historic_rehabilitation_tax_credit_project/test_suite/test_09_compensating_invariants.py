"""Round trips that must leave a conserved total exactly where they found it.

Cycling a cost off the qualified side and back must restore the classified total,
and offsetting a recapture out of a later claim must leave the five-year credit
total untouched even as the three columns beneath it move.
"""

from test_helpers import assertions, fixtures, validate_success


def test_cycling_a_cost_off_and_back_conserves_the_classified_total(api):
    """The classified total is identical at all three checkpoints.

    Two in-period costs, 200000000 of hard construction and 10000000 of
    architectural and engineering work, are both qualified at creation, so the
    classified total is 210000000. Moving the larger one to the non-qualified side
    shifts 200000000 across but leaves the classified total at 210000000. Moving it
    back restores the qualified total to 210000000 and the non-qualified total to
    zero, with the classified total never having moved.

    PRD: "These fields obey a conservation invariant that must hold after every classification history whatsoever: `qre_total_final_cents` plus `nonqualified_total_cents` equals `classified_cost_total_cents`."
    PRD: "It holds precisely because the disallowed fee slice is relocated between the two sides rather than discarded, which is also why cycling an item `QRE → NON_QRE → QRE` restores `classified_cost_total_cents` to exactly its former value."

    Design: Difficulty/compensating_invariant/qre_reclassification_round_trip_conserves_classified_cost_total
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api,
        cast,
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=60_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )
    first = fixtures.add_qre_cost(
        api, cast, project["id"], 200_000_000, incurred_date="2027-01-15"
    )
    fixtures.add_qre_cost(
        api,
        cast,
        project["id"],
        10_000_000,
        category="ARCHITECTURAL_ENGINEERING",
        incurred_date="2027-02-10",
    )
    checkpoint_one = fixtures.read_project(api, cast, project["id"])
    assertions.assert_ledger(
        checkpoint_one,
        qre_total_final_cents=210_000_000,
        nonqualified_total_cents=0,
        classified_cost_total_cents=210_000_000,
    )
    assertions.assert_classified_cost_conservation(checkpoint_one)

    fixtures.classify_cost(
        api, cast, first["id"], "NON_QRE", exclusion_reason="REVIEWER_DISALLOWED"
    )
    checkpoint_two = fixtures.read_project(api, cast, project["id"])
    fixtures.classify_cost(api, cast, first["id"], "QRE")
    checkpoint_three = fixtures.read_project(api, cast, project["id"])

    assertions.assert_ledger(
        checkpoint_two,
        qre_total_final_cents=10_000_000,
        nonqualified_total_cents=200_000_000,
        classified_cost_total_cents=210_000_000,
    )
    assertions.assert_classified_cost_conservation(checkpoint_two)
    assertions.assert_ledger(
        checkpoint_three,
        qre_total_final_cents=210_000_000,
        nonqualified_total_cents=0,
        classified_cost_total_cents=210_000_000,
    )
    assertions.assert_classified_cost_conservation(checkpoint_three)


def test_the_round_trip_restores_the_credit_and_counts_two_reclassifications(api):
    """The test and the schedule return, and only the cycled item's counter moves.

    At the first checkpoint the qualified total of 210000000 clears the 60000000
    threshold, so the test reads MET at 8400000 a year. The disallowance drops the
    qualified total to 10000000, below the threshold, so the test reads NOT_MET and
    the schedule collapses to zero. Restoring the item brings back MET, 8400000 a
    year and 42000000 over five years; the restored item's exclusion reason is
    cleared and its reclassification count is two, while the untouched item's count
    is still zero.

    PRD: "Moving an item to `QRE` sets `exclusion_reason` back to `NONE`; moving it to `NON_QRE` sets `exclusion_reason` to the supplied value when one is given, and otherwise derives it — `NONQUALIFIED_CATEGORY` for a statutorily excluded category, `OUTSIDE_MEASURING_PERIOD` when `in_measuring_period` is false, `DEVELOPER_FEE_CAP` for the disallowed slice of a developer fee, and `REVIEWER_DISALLOWED` for an auditor's disallowance."
    PRD: "Reclassification is a first-class operation, and each successful one raises `reclassification_count` by one."
    PRD: "When `substantial_test_status` is `NOT_MET`, both `annual_credit_cents` and `total_claimable_credit_cents` are zero."

    Design: Difficulty/compensating_invariant/qre_reclassification_round_trip_conserves_classified_cost_total
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api,
        cast,
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=60_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )
    first = fixtures.add_qre_cost(
        api, cast, project["id"], 200_000_000, incurred_date="2027-01-15"
    )
    second = fixtures.add_qre_cost(
        api,
        cast,
        project["id"],
        10_000_000,
        category="ARCHITECTURAL_ENGINEERING",
        incurred_date="2027-02-10",
    )
    assertions.assert_ledger(
        fixtures.read_project(api, cast, project["id"]),
        substantial_test_status="MET",
        annual_credit_cents=8_400_000,
    )

    fixtures.classify_cost(
        api, cast, first["id"], "NON_QRE", exclusion_reason="REVIEWER_DISALLOWED"
    )
    assertions.assert_ledger(
        fixtures.read_project(api, cast, project["id"]),
        substantial_test_status="NOT_MET",
        annual_credit_cents=0,
        total_claimable_credit_cents=0,
    )
    restored = fixtures.classify_cost(api, cast, first["id"], "QRE")

    assertions.assert_fields(
        restored,
        "cost after the round trip",
        classification="QRE",
        exclusion_reason="NONE",
        reclassification_count=2,
    )
    untouched = validate_success(
        api.get_cost_line_item(second["id"], cast.developer_headers)
    )
    assertions.assert_fields(
        untouched, "untouched cost", classification="QRE", reclassification_count=0
    )
    assertions.assert_ledger(
        fixtures.read_project(api, cast, project["id"]),
        substantial_test_status="MET",
        annual_credit_cents=8_400_000,
        total_claimable_credit_cents=42_000_000,
    )


def test_an_assessed_recapture_sits_outside_the_ledger_identity(api):
    """The assessment moves the balance without disturbing the three columns.

    After the 2029 filing the ledger reads 2500001 claimed, nothing recaptured and
    10000004 unclaimed, which sums to the 12500005 total. A COVENANT_BREACH assessed
    one year into the compliance period raises the outstanding balance to 2000001,
    yet the three ledger columns are exactly where the filing left them, because the
    obligation is carried on the balance rather than written into the ledger.

    PRD: "The event is persisted with `status` of `ASSESSED` and `source` of `REPORTED` for a monitor's report, or `SYSTEM_DERIVED` for one the system raises itself, and the amount is added to the project's `recapture_balance_cents`."
    PRD: "Across the whole ledger, one invariant must hold after every filing: `credit_claimed_to_date_cents` plus `credit_recaptured_cents` plus `credit_unclaimed_cents` equals `total_claimable_credit_cents`."

    Design: Difficulty/compensating_invariant/recapture_offset_round_trip_conserves_total_claimable_credit
    """
    scenario = fixtures.claim_filed_project(
        api,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=60_000_000,
        qre_cents=62_500_013,
        tax_year=2029,
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    checkpoint_one = scenario["project"]
    assertions.assert_ledger(
        checkpoint_one,
        total_claimable_credit_cents=12_500_005,
        credit_claimed_to_date_cents=2_500_001,
        credit_recaptured_cents=0,
        credit_unclaimed_cents=10_000_004,
        recapture_balance_cents=0,
    )
    assertions.assert_credit_conservation(checkpoint_one)
    fixtures.set_clock(api, "2030-03-01T00:00:00Z")

    event = fixtures.report_recapture_event(
        api, project_id, "COVENANT_BREACH", "2030-01-20"
    )

    checkpoint_two = fixtures.read_project(api, cast, project_id)
    assertions.assert_ledger(
        checkpoint_two,
        total_claimable_credit_cents=12_500_005,
        credit_claimed_to_date_cents=2_500_001,
        credit_recaptured_cents=0,
        credit_unclaimed_cents=10_000_004,
        recapture_balance_cents=2_000_001,
    )
    assertions.assert_credit_conservation(checkpoint_two)
    assertions.assert_fields(event, "assessed event", status="ASSESSED")


def test_the_compensating_filing_settles_the_balance_and_conserves_the_total(api):
    """Three columns move, their sum does not, and the event settles.

    Filing the 2030 claim offsets 2000001 of its 2500001 gross, so 500000 is added
    to the claimed column and 2000001 to the recaptured column while the unclaimed
    column falls to 7500003. The three still sum to 12500005, which was never
    rewritten. The balance reaches zero, so the assessed event moves to SETTLED.

    PRD: "**Fifth**, only after the balance has been reduced, every recapture event of the project whose `status` is `ASSESSED` moves to `SETTLED` if `recapture_balance_cents` has reached zero."
    PRD: "An assessed event leaves `ASSESSED` only one way: it moves `ASSESSED → SETTLED`, incrementing its `version`, once the project's `recapture_balance_cents` has been driven back to zero by claim offsets."

    Design: Difficulty/compensating_invariant/recapture_offset_round_trip_conserves_total_claimable_credit
    """
    scenario = fixtures.claim_filed_project(
        api,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=60_000_000,
        qre_cents=62_500_013,
        tax_year=2029,
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    fixtures.set_clock(api, "2030-03-01T00:00:00Z")
    event = fixtures.report_recapture_event(
        api, project_id, "COVENANT_BREACH", "2030-01-20"
    )
    second_claim = fixtures.create_claim(
        api, scenario["interest"], project_id, tax_year=2030
    )

    filed = fixtures.file_claim(api, scenario["interest"], second_claim["id"])

    checkpoint_three = fixtures.read_project(api, cast, project_id)
    assertions.assert_ledger(
        checkpoint_three,
        total_claimable_credit_cents=12_500_005,
        credit_claimed_to_date_cents=3_000_001,
        credit_recaptured_cents=2_000_001,
        credit_unclaimed_cents=7_500_003,
        recapture_balance_cents=0,
    )
    assertions.assert_credit_conservation(checkpoint_three)
    assertions.assert_fields(
        filed,
        "compensating claim",
        recapture_offset_cents=2_000_001,
        net_claim_cents=500_000,
    )
    settled = validate_success(
        api.get_recapture_event(event["id"], cast.developer_headers)
    )
    assertions.assert_fields(
        settled,
        "settled event",
        status="SETTLED",
        version=event["version"] + 1,
    )
