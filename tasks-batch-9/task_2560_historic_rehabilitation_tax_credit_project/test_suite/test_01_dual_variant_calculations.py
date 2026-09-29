"""Calculations that run in two variants over the same stored facts.

Cost segregation runs as PROVISIONAL and FINAL over one set of line items, and
investor disqualification risk runs as ADMISSION and IN_SERVICE over one set of
party attributes. Both pairs are exercised here on inputs chosen so the two
variants disagree, because a single-variant implementation passes any test whose
inputs make them agree.
"""

from test_helpers import assertions, fixtures, types, validate_success


def test_provisional_variant_counts_the_pending_cost_that_final_variant_excludes(api):
    """The two segregation variants disagree on an unclassified in-period cost.

    A master-lease project carries an adjusted basis of 250000000 cents and three
    in-period costs: 200000000 of hard construction and 10000000 of architectural
    and engineering work, both classified QRE, and 40000000 of hard construction
    left unclassified. The PROVISIONAL read counts the unclassified item because
    its category is QRE-eligible, reaching 250000000 and landing exactly on the
    threshold, so the test reads MET under that variant. The FINAL read counts
    only the two classified items, reaching 210000000, which is below the
    threshold and reads NOT_MET. One in-period item is still awaiting
    classification and all three are in period.

    PRD: "Only items whose `in_measuring_period` is true participate at all."
    PRD: "Under the `FINAL` variant, the counted qualified set is the items whose `classification` is `QRE` or `LOCKED_QRE`."
    PRD: "The requested `variant` may be `PROVISIONAL` or `FINAL`, and omitting it defaults to `PROVISIONAL`."
    PRD: "`substantial_test_status` reads `MET` when `qre_total_final_cents` is greater than or equal to that threshold and `NOT_MET` otherwise; the comparison is inclusive, so an amount landing exactly on the threshold is `MET`."

    Design: Difficulty/dual_variant_calc/qre_provisional_vs_final_divergence_flips_substantial_test
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api,
        cast,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=250_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )
    fixtures.add_qre_cost(
        api,
        cast,
        project["id"],
        200_000_000,
        category="HARD_CONSTRUCTION",
        incurred_date="2027-01-15",
    )
    fixtures.add_qre_cost(
        api,
        cast,
        project["id"],
        10_000_000,
        category="ARCHITECTURAL_ENGINEERING",
        incurred_date="2027-02-10",
    )
    fixtures.add_cost(
        api,
        cast,
        project["id"],
        amount_cents=40_000_000,
        category="HARD_CONSTRUCTION",
        incurred_date="2027-03-05",
    )

    provisional = validate_success(
        api.get_qre_summary(project["id"], cast.developer_headers, variant="PROVISIONAL")
    )
    final = validate_success(
        api.get_qre_summary(project["id"], cast.developer_headers, variant="FINAL")
    )

    types.assert_is_qre_summary(provisional)
    types.assert_is_qre_summary(final)
    assertions.assert_fields(
        provisional,
        "PROVISIONAL summary",
        variant_applied="PROVISIONAL",
        qre_total_cents=250_000_000,
        substantial_test_status_under_variant="MET",
        substantial_test_threshold_cents=250_000_000,
        in_period_item_count=3,
        pending_classification_item_count=1,
    )
    assertions.assert_fields(
        final,
        "FINAL summary",
        variant_applied="FINAL",
        qre_total_cents=210_000_000,
        substantial_test_status_under_variant="NOT_MET",
        substantial_test_threshold_cents=250_000_000,
        in_period_item_count=3,
        pending_classification_item_count=1,
    )
    assert final["qre_total_cents"] <= provisional["qre_total_cents"], (
        "the final qualified total can only be less than or equal to the "
        "provisional one"
    )


def test_project_ledger_stores_both_qre_variants_and_credits_only_the_final_one(api):
    """Both variant totals persist, but the credit follows the final one only.

    On the same project, the stored provisional total is 250000000 and the stored
    final total is 210000000. The substantial test runs against the final figure
    alone, so it reads NOT_MET even though the provisional figure lands on the
    threshold, and the ratable schedule is therefore zero in both the annual and
    the five-year fields. Only the two classified items reach the classified cost
    total of 210000000; the unclassified 40000000 is in neither side.

    PRD: "`qre_total_final_cents` holds the qualified total under the `FINAL` variant, `qre_total_provisional_cents` holds it under the `PROVISIONAL` variant, `nonqualified_total_cents` holds the non-qualified total under the `FINAL` variant, `developer_fee_disallowed_cents` holds the fee disallowed under the `FINAL` variant, and `classified_cost_total_cents` holds the classified cost total."
    PRD: "When `substantial_test_status` is `NOT_MET`, both `annual_credit_cents` and `total_claimable_credit_cents` are zero."
    PRD: "The `PROVISIONAL` variant is what a developer watches while preparing Part 3; the `FINAL` variant is what the certification and the credit actually run on."

    Design: Difficulty/dual_variant_calc/qre_provisional_vs_final_divergence_flips_substantial_test
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api,
        cast,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=250_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )
    fixtures.add_qre_cost(
        api,
        cast,
        project["id"],
        200_000_000,
        category="HARD_CONSTRUCTION",
        incurred_date="2027-01-15",
    )
    fixtures.add_qre_cost(
        api,
        cast,
        project["id"],
        10_000_000,
        category="ARCHITECTURAL_ENGINEERING",
        incurred_date="2027-02-10",
    )
    fixtures.add_cost(
        api,
        cast,
        project["id"],
        amount_cents=40_000_000,
        category="HARD_CONSTRUCTION",
        incurred_date="2027-03-05",
    )

    stored = fixtures.read_project(api, cast, project["id"])

    types.assert_is_project(stored)
    assertions.assert_ledger(
        stored,
        qre_total_provisional_cents=250_000_000,
        qre_total_final_cents=210_000_000,
        nonqualified_total_cents=0,
        classified_cost_total_cents=210_000_000,
        substantial_test_threshold_cents=250_000_000,
        substantial_test_status="NOT_MET",
        annual_credit_cents=0,
        total_claimable_credit_cents=0,
        credit_unclaimed_cents=0,
    )
    assertions.assert_classified_cost_conservation(stored)


def test_admitted_interest_rescores_under_in_service_variant_after_a_breach(api):
    """The same party attributes score higher once the building is in service.

    A master-lease lessee of PARTNERSHIP tax status with a 23-year lease scores
    10 base plus 10 for tax status plus 22 for the lease term under the ADMISSION
    variant once the pass-through election has dropped the 12-point pending
    penalty, giving 42. An EXCEPTION attestation then breaches the project's only
    covenant, and the interest is re-scored under the IN_SERVICE variant, which
    adds 20 points for that one breached covenant: 62. The project's standing
    maximum follows the re-scored interest.

    PRD: "Every interest starts from a base risk of 10 points."
    PRD: "Its `party_tax_status` adds points on a fixed scale: nothing for `TAXABLE_C_CORP`, 10 points for `PARTNERSHIP`, 35 points for `GOVERNMENTAL_UNIT`, and 45 points for `TAX_EXEMPT_ORG`."
    PRD: "The `IN_SERVICE` variant, applied to every `ADMITTED` interest of a project whose compliance dimension has left `NOT_MONITORED`, adds a project-level adder on top of the base score: 20 points for each `BREACHED` covenant of the project, plus 10 points for each unresolved preservation violation, counting the total of `unresolved_violation_count` over the project's applications whose status is not `SUPERSEDED`."
    PRD: "The project's `max_investor_risk_score` is the maximum `disqualification_risk_score` across its `ADMITTED` interests, and zero when the project has no `ADMITTED` interest at all."

    Design: Difficulty/dual_variant_calc/investor_risk_admission_vs_in_service_variant_divergence
    """
    scenario = fixtures.in_service_project(
        api, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    interest = fixtures.admit_master_lease_lessee(
        api,
        cast,
        project_id,
        party_tax_status="PARTNERSHIP",
        lease_term_years=23,
        capital_committed_cents=40_000_000,
        credit_allocation_pct=99.0,
    )
    covenant = fixtures.create_covenant(
        api,
        cast,
        project_id,
        headers=fixtures.MONITOR,
        covenant_type="USE_RESTRICTION",
        monitoring_frequency="ANNUAL",
        window_start_date="2029-01-15",
        window_end_date="2030-01-14",
    )

    types.assert_is_investor_interest(interest)
    assertions.assert_risk_score(interest, 42, "ADMISSION")
    assert assertions.lease_term_risk_points(23) == 22

    fixtures.attest_covenant(api, cast, covenant["id"], "2029-01-31", "EXCEPTION")

    rescored = validate_success(
        api.get_investor_interest(interest["id"], cast.developer_headers)
    )
    assertions.assert_risk_score(rescored, 62, "IN_SERVICE")
    project = fixtures.read_project(api, cast, project_id)
    assertions.assert_ledger(project, max_investor_risk_score=62)


def test_exception_attestation_breaches_the_covenant_and_opens_the_cure_window(api):
    """The breach that changes the risk variant also moves covenant and project.

    The EXCEPTION attestation of the 2029-01-31 period is the covenant's first,
    so its attestation count reaches one alongside an exception count of one, the
    last attested period is recorded, and the cure deadline is the covenant
    window end of 2030-01-14 advanced by ninety days, namely 2030-04-14. The
    project's compliance dimension leaves monitoring for CURE_PENDING while its
    certification dimension stays where Part 2 approval left it.

    PRD: "Every accepted attestation raises `attestation_count` by one and writes `period_end_date` into `last_attested_period_end`; the `period_end_date` must be on or before the current logical clock date, and, when a previous attestation exists, strictly after `last_attested_period_end`, with an incoherent period rejected as `ERR_INVALID_REQUEST`."
    PRD: "From `PENDING_ATTESTATION`, `COMPLIANT`, or `CURED`, the covenant moves to `BREACHED`; `exception_count` rises by one alongside `attestation_count`, and `cure_deadline_date` is set to `window_end_date` advanced by ninety days."
    PRD: "The breach then cascades in three hops: the project's compliance dimension moves `IN_SERVICE_MONITORING → CURE_PENDING`; every `ADMITTED` investor interest of the project has its `disqualification_risk_score` recomputed under the `IN_SERVICE` variant, with each recomputed interest's `version` incrementing; and the project's `max_investor_risk_score` is refreshed from those scores."

    Design: Difficulty/dual_variant_calc/investor_risk_admission_vs_in_service_variant_divergence
    """
    scenario = fixtures.in_service_project(
        api, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    fixtures.admit_master_lease_lessee(
        api,
        cast,
        project_id,
        party_tax_status="PARTNERSHIP",
        lease_term_years=23,
        capital_committed_cents=40_000_000,
        credit_allocation_pct=99.0,
    )
    covenant = fixtures.create_covenant(
        api,
        cast,
        project_id,
        headers=fixtures.MONITOR,
        covenant_type="USE_RESTRICTION",
        monitoring_frequency="ANNUAL",
        window_start_date="2029-01-15",
        window_end_date="2030-01-14",
    )
    assertions.assert_fields(
        covenant,
        "new covenant",
        status="PENDING_ATTESTATION",
        attestation_count=0,
        exception_count=0,
        last_attested_period_end=None,
        cure_deadline_date=None,
    )

    breached = fixtures.attest_covenant(
        api, cast, covenant["id"], "2029-01-31", "EXCEPTION"
    )

    types.assert_is_compliance_covenant(breached)
    assertions.assert_fields(
        breached,
        "breached covenant",
        status="BREACHED",
        attestation_count=1,
        exception_count=1,
        last_attested_period_end="2029-01-31",
        cure_deadline_date="2030-04-14",
    )
    project = fixtures.read_project(api, cast, project_id)
    assertions.assert_project_state(
        project, certification_status="PART2_APPROVED", compliance_status="CURE_PENDING"
    )
