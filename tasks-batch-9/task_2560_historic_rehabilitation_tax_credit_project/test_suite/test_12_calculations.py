"""The four derived quantities, each exercised on its own terms.

The segregation with its developer-fee cap and its two variants, the threshold with
its statutory floor, the ratable schedule that collapses to zero, and the investor
risk score with its scaled lease-term component.
"""

from test_helpers import (
    assertions,
    factories,
    fixtures,
    types,
    validate_success,
)


def test_the_developer_fee_cap_truncates_at_fifteen_percent_of_hard_costs(api):
    """A 7000000 fee against 40000000 of hard costs is allowed only to 6000000.

    Both items are in period and qualified, so the counted set is both of them. The
    hard qualified total excludes the fee and is 40000000, the cap is fifteen percent
    of that, 6000000, and the fee claimed exceeds it, so 1000000 is disallowed. The
    qualified total is 40000000 plus the allowed 6000000, and the disallowed slice
    moves to the non-qualified side rather than being dropped, so the classified total
    is the full 47000000 that was invoiced.

    PRD: "The developer fee is then capped at fifteen percent of the hard qualified total, and that cap is truncated downward to a whole cent rather than rounded."
    PRD: "The **fee allowed** is the lesser of the fee claimed and the cap, and the **fee disallowed** is the fee claimed minus the fee allowed. The qualified total for the variant is the hard qualified total plus the fee allowed. The non-qualified total is the sum of `amount_cents` over the in-period items whose `classification` is `NON_QRE` or `LOCKED_NON_QRE`, plus the fee disallowed — the excess fee is *moved* to the non-qualified side, never dropped."
    PRD: "`qre_total_final_cents` holds the qualified total under the `FINAL` variant, `qre_total_provisional_cents` holds it under the `PROVISIONAL` variant, `nonqualified_total_cents` holds the non-qualified total under the `FINAL` variant, `developer_fee_disallowed_cents` holds the fee disallowed under the `FINAL` variant, and `classified_cost_total_cents` holds the classified cost total."

    Design: Corner/calculations/qre_totals_developer_fee_cap_uses_floor_of_hard_costs
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
    fixtures.add_qre_cost(
        api, cast, project["id"], 40_000_000, incurred_date="2027-03-01"
    )
    fixtures.add_qre_cost(
        api,
        cast,
        project["id"],
        7_000_000,
        category="DEVELOPER_FEE",
        incurred_date="2027-04-01",
    )

    summary = validate_success(
        api.get_qre_summary(project["id"], cast.developer_headers, variant="FINAL")
    )

    types.assert_is_qre_summary(summary)
    assertions.assert_fields(
        summary,
        "final segregation",
        variant_applied="FINAL",
        hard_qre_cents=40_000_000,
        developer_fee_claimed_cents=7_000_000,
        developer_fee_allowed_cents=6_000_000,
        developer_fee_disallowed_cents=1_000_000,
        qre_total_cents=46_000_000,
        nonqualified_total_cents=1_000_000,
        classified_cost_total_cents=47_000_000,
        substantial_test_threshold_cents=60_000_000,
        substantial_test_status_under_variant="NOT_MET",
        in_period_item_count=2,
        pending_classification_item_count=0,
    )
    stored = fixtures.read_project(api, cast, project["id"])
    assertions.assert_ledger(
        stored,
        developer_fee_disallowed_cents=1_000_000,
        qre_total_final_cents=46_000_000,
    )
    assertions.assert_classified_cost_conservation(stored)


def test_only_in_period_items_enter_the_segregation_at_all(api):
    """A cost dated on the exclusive end date is in no total whatsoever.

    Of the three recorded items, two fall inside the half-open window and one is dated
    exactly on the exclusive end date, so its in-period flag is false. The segregation
    counts the two: 20000000 qualified and 30000000 non-qualified, for a classified
    total of 50000000. The out-of-period 5000000 appears in neither the totals nor the
    in-period count.

    PRD: "Only items whose `in_measuring_period` is true participate at all."
    PRD: "The classified cost total is the sum of `amount_cents` over the in-period items whose `classification` is any of `QRE`, `NON_QRE`, `LOCKED_QRE`, or `LOCKED_NON_QRE`."
    PRD: "The server also derives `in_measuring_period`, which is true exactly when the `incurred_date` falls on or after the project's `measuring_period_start_date` and strictly before its `measuring_period_end_date`, and initialises `exclusion_reason` to `NONE` and `reclassification_count` to zero."

    Design: Corner/calculations/qre_totals_input_set_filtering_excludes_out_of_period_costs
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
    in_period_qualified = fixtures.add_qre_cost(
        api, cast, project["id"], 20_000_000, incurred_date="2027-03-01"
    )
    in_period_nonqualified = fixtures.add_cost(
        api,
        cast,
        project["id"],
        category="ACQUISITION",
        amount_cents=30_000_000,
        incurred_date="2027-04-01",
        classification="NON_QRE",
    )
    fixtures.set_clock(api, "2028-10-01T00:00:00Z")
    out_of_period = fixtures.add_cost(
        api,
        cast,
        project["id"],
        category="HARD_CONSTRUCTION",
        amount_cents=5_000_000,
        incurred_date="2028-09-01",
        classification="NON_QRE",
    )

    summary = validate_success(
        api.get_qre_summary(project["id"], cast.developer_headers, variant="FINAL")
    )

    assertions.assert_fields(
        in_period_qualified, "qualified item", in_measuring_period=True
    )
    assertions.assert_fields(
        in_period_nonqualified, "non-qualified item", in_measuring_period=True
    )
    assertions.assert_fields(
        out_of_period, "late item", in_measuring_period=False
    )
    assertions.assert_fields(
        summary,
        "final segregation",
        in_period_item_count=2,
        qre_total_cents=20_000_000,
        nonqualified_total_cents=30_000_000,
        classified_cost_total_cents=50_000_000,
    )
    assertions.assert_ledger(
        fixtures.read_project(api, cast, project["id"]),
        classified_cost_total_cents=50_000_000,
    )


def test_the_segregation_read_defaults_to_the_provisional_variant(api):
    """Omitting the variant counts eligible unclassified items as qualified.

    One qualified 20000000 of hard construction sits alongside two unclassified
    in-period items: 4000000 of architectural and engineering work, whose category is
    QRE-eligible, and 30000000 of acquisition, whose category is not. With no variant
    requested the read applies PROVISIONAL, so the eligible pending item is counted and
    the qualified total is 24000000 while the ineligible one is left out. The classified
    total counts only the one item that has actually been classified.

    PRD: "The requested `variant` may be `PROVISIONAL` or `FINAL`, and omitting it defaults to `PROVISIONAL`."
    PRD: "Under the `PROVISIONAL` variant, the counted qualified set is those same items plus the items whose `classification` is `PENDING_CLASSIFICATION` and whose `category` is one of the four QRE-eligible categories `HARD_CONSTRUCTION`, `ARCHITECTURAL_ENGINEERING`, `DEVELOPER_FEE`, or `CONSTRUCTION_INTEREST`; the provisional figure is therefore an upper bound on the final one, and the final figure can only be less than or equal to it."
    PRD: "The **hard qualified total** is the sum of `amount_cents` over the counted items whose `category` is not `DEVELOPER_FEE`."

    Design: Corner/calculations/qre_summary_variant_defaults_to_provisional_when_variant_omitted
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
    fixtures.add_qre_cost(
        api, cast, project["id"], 20_000_000, incurred_date="2027-03-01"
    )
    eligible_pending = fixtures.add_cost(
        api,
        cast,
        project["id"],
        category="ARCHITECTURAL_ENGINEERING",
        amount_cents=4_000_000,
        incurred_date="2027-04-01",
    )
    ineligible_pending = fixtures.add_cost(
        api,
        cast,
        project["id"],
        category="ACQUISITION",
        amount_cents=30_000_000,
        incurred_date="2027-05-01",
    )

    summary = validate_success(
        api.get_qre_summary(project["id"], cast.developer_headers)
    )

    assertions.assert_fields(
        eligible_pending,
        "unclassified eligible item",
        classification="PENDING_CLASSIFICATION",
    )
    assertions.assert_fields(
        ineligible_pending,
        "unclassified ineligible item",
        classification="PENDING_CLASSIFICATION",
    )
    assertions.assert_fields(
        summary,
        "defaulted segregation",
        variant_applied="PROVISIONAL",
        hard_qre_cents=24_000_000,
        qre_total_cents=24_000_000,
        classified_cost_total_cents=20_000_000,
        in_period_item_count=3,
        pending_classification_item_count=2,
        substantial_test_status_under_variant="NOT_MET",
    )


def test_a_basis_below_the_statutory_floor_leaves_the_floor_as_the_threshold(api):
    """An adjusted basis of 300000 cents is beaten by the 500000-cent floor.

    The threshold is the greater of the basis and the statutory five-thousand-dollar
    floor, so it reads 500000 rather than the project's 300000 basis. A single
    qualified cost of exactly 500000 lands on that threshold, which the inclusive
    comparison reads as MET, and the schedule follows: four percent is 20000 a year and
    100000 over the five ratable years, all of it still unclaimed.

    PRD: "The threshold, held in `substantial_test_threshold_cents`, is the greater of the project's `adjusted_basis_cents` and a statutory floor of five thousand dollars expressed in cents."
    PRD: "Otherwise `annual_credit_cents` is four percent of `qre_total_final_cents`, rounded half up to a whole cent, and `total_claimable_credit_cents` is that **already-rounded** per-year amount multiplied by five, the number of ratable years."
    PRD: "`credit_unclaimed_cents` is then `total_claimable_credit_cents` less `credit_claimed_to_date_cents` less `credit_recaptured_cents`."

    Design: Corner/calculations/substantial_test_threshold_falls_back_to_statutory_floor
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api,
        cast,
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=300_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )

    response = api.create_cost_line_item(
        cast.developer_headers,
        project_id=project["id"],
        vendor_name="Keystone Masonry",
        category="HARD_CONSTRUCTION",
        amount_cents=500_000,
        incurred_date="2027-04-01",
        classification="QRE",
    )

    validate_success(response, 201)
    stored = fixtures.read_project(api, cast, project["id"])
    assertions.assert_substantial_test(stored, "MET", threshold_cents=500_000)
    assertions.assert_ratable_schedule(stored, 20_000)
    assertions.assert_ledger(
        stored,
        qre_total_final_cents=500_000,
        total_claimable_credit_cents=100_000,
        credit_unclaimed_cents=100_000,
        credit_claimed_to_date_cents=0,
    )


def test_the_schedule_stays_at_zero_while_the_test_is_not_met(api):
    """1000000 of qualified cost against a 60000000 threshold buys nothing.

    The qualified total is far below the threshold, so the test reads NOT_MET and both
    schedule fields are zero rather than four percent of the qualified total. With
    nothing claimable there is nothing unclaimed either, and the schedule is still live
    because Part 3 has not certified anything.

    PRD: "When `substantial_test_status` is `NOT_MET`, both `annual_credit_cents` and `total_claimable_credit_cents` are zero."
    PRD: "This schedule is recomputed after every substantial-test recomputation for as long as `frozen_at_certification` is false; once Part 3 certification sets that flag to true, the schedule is never recomputed again, and a later change in qualified expenditure leaves `annual_credit_cents` and `total_claimable_credit_cents` untouched and is expressed through recapture instead."

    Design: Corner/calculations/ratable_credit_schedule_is_zero_while_substantial_test_not_met
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

    response = api.create_cost_line_item(
        cast.developer_headers,
        project_id=project["id"],
        vendor_name="Keystone Masonry",
        category="HARD_CONSTRUCTION",
        amount_cents=1_000_000,
        incurred_date="2027-04-01",
        classification="QRE",
    )

    validate_success(response, 201)
    stored = fixtures.read_project(api, cast, project["id"])
    assertions.assert_substantial_test(stored, "NOT_MET", threshold_cents=60_000_000)
    assertions.assert_ledger(
        stored,
        qre_total_final_cents=1_000_000,
        annual_credit_cents=0,
        total_claimable_credit_cents=0,
        credit_unclaimed_cents=0,
        frozen_at_certification=False,
    )


def test_the_lease_term_component_scales_against_the_safe_harbour_and_rescores(api):
    """A 20-year lease scores 19 of the 30 lease points, and election drops 12.

    The safe harbour is eighty percent of the thirty-nine-year useful life truncated to
    whole years, which is 31. A 20-year term is shorter, so it scores 30 scaled by 20
    over 31 and rounded half up, which is 19. At admission the party is a taxable C
    corporation adding nothing and the election is still pending adding 12, so the base
    is 10 plus 19 plus 12, or 41. Making the election drops the pending penalty and
    re-scores the interest to 29, which becomes the project's standing maximum.

    PRD: "The lease-term component applies only to a `MASTER_LEASE_LESSEE` that has a `lease_term_years` value, and is otherwise zero: a safe-harbour term is first computed as eighty percent of the building's thirty-nine-year useful life, truncated downward to a whole number of years; a lease term at or beyond that safe harbour scores the full lease-term ceiling of 30 points, while a shorter term scores 30 points scaled by the ratio of `lease_term_years` to the safe-harbour term, rounded half up to a whole point."
    PRD: "Election moves `pass_through_election` from `PENDING` to `ELECTED`, stamps `election_at` from the logical clock, re-scores the interest under the `ADMISSION` variant — which drops the 12-point pending-election penalty and can therefore only lower the score — refreshes the project's `max_investor_risk_score`, and increments both the interest's and the project's `version`."
    PRD: "The project's `max_investor_risk_score` is the maximum `disqualification_risk_score` across its `ADMITTED` interests, and zero when the project has no `ADMITTED` interest at all."

    Design: Corner/calculations/investor_risk_lease_term_component_rounds_half_up_and_rescores_on_election
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )

    admitted = validate_success(
        api.create_investor_interest(
            cast.developer_headers,
            **factories.master_lease_interest_payload(
                project["id"],
                party_legal_name="Riverbend Credit Corp",
                party_tax_status="TAXABLE_C_CORP",
                capital_committed_cents=40_000_000,
                credit_allocation_pct=100,
                lease_term_years=20,
            ),
        ),
        201,
    )
    elected = validate_success(
        api.elect_pass_through(admitted["id"], fixtures.investor_headers(admitted))
    )

    types.assert_is_investor_interest(admitted)
    assertions.assert_risk_score(admitted, 41, "ADMISSION")
    assertions.assert_fields(
        admitted, "admitted lessee", pass_through_election="PENDING"
    )
    assertions.assert_risk_score(elected, 29, "ADMISSION")
    assertions.assert_fields(
        elected,
        "electing lessee",
        pass_through_election="ELECTED",
        status="ADMITTED",
    )
    assert elected["election_at"].startswith("2026-09-01T00:00:00"), (
        "the election instant comes from the logical clock"
    )
    assertions.assert_ledger(
        fixtures.read_project(api, cast, project["id"]), max_investor_risk_score=29
    )
