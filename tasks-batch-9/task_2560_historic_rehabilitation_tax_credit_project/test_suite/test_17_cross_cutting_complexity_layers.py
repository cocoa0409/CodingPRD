"""Where concurrency control and the risk gate meet the rest of the machinery.

The two guarded writes refused on a version the client no longer holds, and a filing
that is allowed through because the in-service score stops one point short of the
disqualifying threshold.
"""

from test_helpers import (
    ApiErrorId,
    assertions,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_success,
)


def test_a_part_application_quoting_a_superseded_version_is_refused(api):
    """Creating the first application moved the project past the version quoted.

    The client read the project, applied for Part 1 — which incremented the project's
    version — and then applied again still quoting its original read. Only exact
    equality passes, so the second attempt is rejected as stale rather than superseding
    the first: the project still has exactly one application, that application is
    untouched in DRAFT and supersedes nothing, and the project's version is the one the
    first creation produced.

    PRD: "Creating a part application against a project whose `version` has advanced since the client last read it is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."
    PRD: "In both cases the check is `expected_project_version` against the project's current `version` at the moment of the write, and only exact equality passes."
    PRD: "Creation increments the project's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/stale_project_version_on_part_application_create_returns_precondition_failed
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )
    stale_version = project["version"]
    first = fixtures.create_part_application(
        api, cast, project["id"], 1, expected_version=stale_version
    )
    after_first = fixtures.read_project(api, cast, project["id"])
    assert after_first["version"] == stale_version + 1, (
        "creating the first application advances the project by exactly one version"
    )

    response = api.create_part_application(
        cast.developer_headers,
        **factories.part_application_payload(
            project["id"],
            1,
            stale_version,
            narrative="Competing evaluation of significance for the same building.",
        ),
    )

    validate_error(response, ApiErrorId.STALE_PROJECT_VERSION.value, 412)
    assertions.assert_page(
        api.list_part_applications(cast.developer_headers, project_id=project["id"]),
        total_count=1,
    )
    assertions.assert_fields(
        get_success_data(api.get_part_application(first["id"], cast.developer_headers)),
        "the surviving draft",
        status="DRAFT",
        supersedes_application_id=None,
    )
    assertions.assert_fields(
        fixtures.read_project(api, cast, project["id"]),
        "the project after the refused creation",
        version=after_first["version"],
    )


def test_a_basis_revision_quoting_a_stale_version_leaves_the_ledger_alone(api):
    """Recording the cost advanced the project, so the revision is a precondition failure.

    The client read the project at its opening version, then recorded 30000000 of
    qualified construction, which advanced the project. The revision it now sends still
    quotes the opening version, so it is refused before anything is recomputed: the
    basis is still 60000000, the threshold still follows that basis, the qualified total
    is the recorded 30000000, the test still reads NOT_MET with no credit scheduled, and
    the project's version is the one the cost produced.

    PRD: "Revising the adjusted basis or the measuring period on a project whose `version` has advanced since the client last read it is rejected with the same `ERR_STALE_PROJECT_VERSION` (HTTP 412)."
    PRD: "A basis revision supersedes the prior basis outright, so it cannot be re-derived from a stale read: the substantial-rehabilitation threshold the client believed it was moving away from may already have changed underneath it."
    PRD: "When `substantial_test_status` is `NOT_MET`, both `annual_credit_cents` and `total_claimable_credit_cents` are zero."

    Design: Corner/cross_cutting_complexity_layers/stale_project_version_on_basis_revision_returns_precondition_failed
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
    stale_version = project["version"]
    fixtures.add_qre_cost(
        api, cast, project["id"], 30_000_000, incurred_date="2027-05-01"
    )
    after_cost = fixtures.read_project(api, cast, project["id"])
    assert after_cost["version"] == stale_version + 1, (
        "recording the cost advances the project by exactly one version"
    )

    response = api.patch_project(
        project["id"],
        cast.developer_headers,
        expected_project_version=stale_version,
        adjusted_basis_cents=20_000_000,
    )

    validate_error(response, ApiErrorId.STALE_PROJECT_VERSION.value, 412)
    stored = fixtures.read_project(api, cast, project["id"])
    assertions.assert_fields(
        stored,
        "the unrevised project",
        adjusted_basis_cents=60_000_000,
        version=after_cost["version"],
    )
    assertions.assert_substantial_test(stored, "NOT_MET", threshold_cents=60_000_000)
    assertions.assert_ledger(
        stored,
        qre_total_final_cents=30_000_000,
        annual_credit_cents=0,
        total_claimable_credit_cents=0,
    )


def test_a_score_of_sixty_nine_still_lets_the_claim_be_filed(api):
    """One point below the disqualifying threshold, so the filing goes through.

    On a thirty-year lease the term falls just short of the thirty-one-year safe
    harbour and scores 29 of the 30 lease points, so the tenant is admitted at 61 and
    drops to 49 on electing the pass-through. The breached covenant's 20-point
    in-service adder takes it to 69 — below the threshold of 70 — so the filing is
    allowed. With nothing recaptured the whole 2400000 gross survives the offset,
    the ledger moves that amount from unclaimed to claimed, the acting interest is
    recorded as the filer, and the project stays parked in CURE_PENDING because the
    covenant is still breached.

    PRD: "The project's `max_investor_risk_score` must be below 70 (`ERR_DISQUALIFICATION_RISK_TOO_HIGH`)."
    PRD: "**Second**, `recapture_offset_cents` is set to the lesser of that gross figure and the project's currently outstanding `recapture_balance_cents` — the outstanding recapture obligation is satisfied out of this claim first, capped by what the claim is worth."
    PRD: "**Fourth**, and only now, the project ledger is mutated: `credit_claimed_to_date_cents` increases by `net_claim_cents`, `credit_recaptured_cents` increases by `recapture_offset_cents`, `recapture_balance_cents` decreases by `recapture_offset_cents`, and `credit_unclaimed_cents` is recomputed as `total_claimable_credit_cents` less `credit_claimed_to_date_cents` less `credit_recaptured_cents`."
    PRD: "Filing also stamps the audit trail: `status` moves `DRAFT → FILED`, `filed_at` is taken from the logical clock, and `filed_by_user_id` records the acting `X-User-ID`."

    Design: Corner/cross_cutting_complexity_layers/in_service_risk_score_of_sixty_nine_permits_filing_at_the_threshold_boundary
    """
    scenario = fixtures.part3_certified_project(
        api,
        qre_cents=60_000_000,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=60_000_000,
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    admitted = validate_success(
        api.create_investor_interest(
            cast.developer_headers,
            **factories.master_lease_interest_payload(
                project_id,
                party_legal_name="Buckeye Credit Fund LP",
                party_tax_status="PARTNERSHIP",
                capital_committed_cents=40_000_000,
                credit_allocation_pct=100.0,
                lease_term_years=30,
            ),
        ),
        201,
    )
    assertions.assert_risk_score(admitted, 61, "ADMISSION")
    headers = fixtures.investor_headers(admitted)
    validate_success(api.elect_pass_through(admitted["id"], headers))
    covenant = fixtures.create_covenant(
        api,
        cast,
        project_id,
        covenant_type="USE_RESTRICTION",
        monitoring_frequency="ANNUAL",
        window_start_date="2029-01-15",
        window_end_date="2029-01-31",
    )
    fixtures.attest_covenant(api, cast, covenant["id"], "2029-01-31", "EXCEPTION")
    claim = fixtures.create_claim(api, admitted, project_id, tax_year=2029)

    filed = validate_success(api.file_credit_claim(claim["id"], headers))

    assertions.assert_fields(
        filed,
        "the filed claim",
        status="FILED",
        gross_credit_cents=2_400_000,
        recapture_offset_cents=0,
        net_claim_cents=2_400_000,
        filed_by_user_id=admitted["id"],
    )
    stored_interest = validate_success(
        api.get_investor_interest(admitted["id"], cast.developer_headers)
    )
    assertions.assert_risk_score(stored_interest, 69, "IN_SERVICE")
    stored_project = fixtures.read_project(api, cast, project_id)
    assertions.assert_ledger(
        stored_project,
        max_investor_risk_score=69,
        credit_claimed_to_date_cents=2_400_000,
        credit_recaptured_cents=0,
        credit_unclaimed_cents=9_600_000,
    )
    assertions.assert_project_state(stored_project, compliance_status="CURE_PENDING")
    assertions.assert_credit_conservation(stored_project)
