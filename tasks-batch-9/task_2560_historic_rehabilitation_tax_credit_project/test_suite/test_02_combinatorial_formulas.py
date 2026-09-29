"""Formulas whose evaluation order changes the answer.

Both scenarios here are chosen so that a plausible reordering of the steps
produces a different number: rounding the annual instalment after multiplying by
five instead of before, and mutating the project ledger before computing the
recapture offset instead of after.
"""

from test_helpers import assertions, fixtures, types, validate_success


def test_annual_instalment_rounds_half_up_before_the_five_year_multiplication(api):
    """The per-year figure is rounded first, and only then multiplied.

    A single qualified cost of 62500013 cents on a project with an adjusted basis
    of 60000000 clears the threshold, so the credit schedule runs. Four percent of
    62500013 is 2500000.52, which rounds half up to 2500001 for the annual
    instalment.

    PRD: "The threshold, held in `substantial_test_threshold_cents`, is the greater of the project's `adjusted_basis_cents` and a statutory floor of five thousand dollars expressed in cents."
    PRD: "Otherwise `annual_credit_cents` is four percent of `qre_total_final_cents`, rounded half up to a whole cent, and `total_claimable_credit_cents` is that **already-rounded** per-year amount multiplied by five, the number of ratable years."

    Design: Difficulty/combinatorial_formula/ratable_credit_rounding_order_pinned_per_year_then_multiply
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api,
        cast,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=60_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )

    cost = fixtures.add_qre_cost(
        api,
        cast,
        project["id"],
        62_500_013,
        category="HARD_CONSTRUCTION",
        incurred_date="2027-05-10",
    )

    types.assert_is_cost_line_item(cost)
    assertions.assert_fields(
        cost, "cost line item", classification="QRE", in_measuring_period=True
    )
    stored = fixtures.read_project(api, cast, project["id"])
    assertions.assert_ledger(
        stored,
        qre_total_final_cents=62_500_013,
        substantial_test_threshold_cents=60_000_000,
        substantial_test_status="MET",
        annual_credit_cents=2_500_001,
    )
    assert assertions.annual_credit_cents(62_500_013) == 2_500_001


def test_five_year_total_is_the_rounded_instalment_times_five_not_a_rounded_product(api):
    """Multiplying the rounded instalment gives 12500005, not 12500003.

    The same 62500013 of qualified expenditure yields an annual instalment of
    2500001, and five of those is 12500005. Rounding after the multiplication
    instead would give 12500003, three cents short, because 0.04 times 62500013
    times 5 is 12500002.6. Nothing has been claimed or recaptured yet, so the
    unclaimed figure is the whole 12500005.

    PRD: "Rounding after the multiplication instead of before it yields a different total for most inputs and is wrong."
    PRD: "`credit_unclaimed_cents` is then `total_claimable_credit_cents` less `credit_claimed_to_date_cents` less `credit_recaptured_cents`."

    Design: Difficulty/combinatorial_formula/ratable_credit_rounding_order_pinned_per_year_then_multiply
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api,
        cast,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=60_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )

    fixtures.add_qre_cost(
        api,
        cast,
        project["id"],
        62_500_013,
        category="HARD_CONSTRUCTION",
        incurred_date="2027-05-10",
    )

    stored = fixtures.read_project(api, cast, project["id"])
    assertions.assert_ratable_schedule(stored, 2_500_001)
    assertions.assert_ledger(
        stored,
        total_claimable_credit_cents=12_500_005,
        credit_claimed_to_date_cents=0,
        credit_recaptured_cents=0,
        credit_unclaimed_cents=12_500_005,
    )
    assert stored["total_claimable_credit_cents"] != 12_500_003, (
        "12500003 is what rounding after the multiplication would produce"
    )
    assertions.assert_credit_conservation(stored)


def test_filing_offsets_the_outstanding_recapture_before_it_touches_the_ledger(api):
    """The offset is the lesser of the claim's gross and the standing balance.

    The 2029 claim was filed for its full 2500001, so 2500001 has been claimed to
    date. A COVENANT_BREACH dated 2030-01-20 sits one full 365-day year after the
    2029-01-15 in-service date, so four compliance years remain and the percentage
    is 0.80; 2500001 times 0.80 is 2000000.8, which rounds half up to 2000001 and
    becomes the outstanding balance. Filing the 2030 claim, whose stored gross is
    also 2500001, offsets the smaller of the two figures, 2000001, and leaves a
    net of 500000.

    PRD: "**Second**, `recapture_offset_cents` is set to the lesser of that gross figure and the project's currently outstanding `recapture_balance_cents` — the outstanding recapture obligation is satisfied out of this claim first, capped by what the claim is worth."
    PRD: "**Third**, `net_claim_cents` is the gross figure less that offset: it is what survives the offset."
    PRD: "`recapture_amount_cents` is then the project's `credit_claimed_to_date_cents` multiplied by `recapture_pct`, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/claim_settlement_evaluation_order_offset_before_ledger_write
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
    assertions.assert_ledger(
        scenario["project"], credit_claimed_to_date_cents=2_500_001
    )
    fixtures.set_clock(api, "2030-03-01T00:00:00Z")
    event = fixtures.report_recapture_event(
        api, project_id, "COVENANT_BREACH", "2030-01-20"
    )
    second_claim = fixtures.create_claim(
        api, scenario["interest"], project_id, tax_year=2030
    )

    filed = fixtures.file_claim(api, scenario["interest"], second_claim["id"])

    types.assert_is_recapture_event(event)
    assertions.assert_fields(
        event,
        "recapture event",
        full_years_elapsed=1,
        recapture_pct=0.80,
        recapture_amount_cents=2_000_001,
        status="ASSESSED",
        source="REPORTED",
    )
    types.assert_is_credit_claim(filed)
    assertions.assert_fields(
        filed,
        "second claim",
        tax_year=2030,
        claim_sequence=2,
        gross_credit_cents=2_500_001,
        recapture_offset_cents=2_000_001,
        net_claim_cents=500_000,
        status="FILED",
    )
    assert filed["filed_at"] is not None, "a filed claim is stamped from the clock"


def test_settled_event_and_restored_posture_follow_the_ledger_write(api):
    """Settlement, then posture, both strictly after the ledger is mutated.

    The 2030 filing adds its net 500000 to the 2500001 already claimed, giving
    3000001, moves the 2000001 offset into the recaptured column, and drives the
    outstanding balance to zero. Only then does the assessed event become SETTLED,
    and only after that does the compliance dimension return from CURE_PENDING to
    IN_SERVICE_MONITORING. The ledger identity still holds: 3000001 claimed plus
    2000001 recaptured plus 7500003 unclaimed is the 12500005 total.

    PRD: "**Fourth**, and only now, the project ledger is mutated: `credit_claimed_to_date_cents` increases by `net_claim_cents`, `credit_recaptured_cents` increases by `recapture_offset_cents`, `recapture_balance_cents` decreases by `recapture_offset_cents`, and `credit_unclaimed_cents` is recomputed as `total_claimable_credit_cents` less `credit_claimed_to_date_cents` less `credit_recaptured_cents`."
    PRD: "**Fifth**, only after the balance has been reduced, every recapture event of the project whose `status` is `ASSESSED` moves to `SETTLED` if `recapture_balance_cents` has reached zero."
    PRD: "**Sixth**, only after those two steps, the compliance posture is re-derived: when `recapture_balance_cents` is zero, no covenant of the project is `BREACHED`, and the dimension currently reads `CURE_PENDING`, it returns `CURE_PENDING → IN_SERVICE_MONITORING`."

    Design: Difficulty/combinatorial_formula/claim_settlement_evaluation_order_offset_before_ledger_write
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
    assertions.assert_ledger(
        fixtures.read_project(api, cast, project_id), recapture_balance_cents=2_000_001
    )
    second_claim = fixtures.create_claim(
        api, scenario["interest"], project_id, tax_year=2030
    )

    fixtures.file_claim(api, scenario["interest"], second_claim["id"])

    project = fixtures.read_project(api, cast, project_id)
    assertions.assert_ledger(
        project,
        credit_claimed_to_date_cents=3_000_001,
        credit_recaptured_cents=2_000_001,
        credit_unclaimed_cents=7_500_003,
        total_claimable_credit_cents=12_500_005,
        recapture_balance_cents=0,
    )
    assertions.assert_credit_conservation(project)
    settled = validate_success(
        api.get_recapture_event(event["id"], cast.developer_headers)
    )
    assertions.assert_fields(settled, "recapture event", status="SETTLED")
    assertions.assert_project_state(project, compliance_status="IN_SERVICE_MONITORING")
