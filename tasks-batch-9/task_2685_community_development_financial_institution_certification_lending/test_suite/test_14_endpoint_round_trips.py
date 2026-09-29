"""Round trips: what each surface writes, returns, filters and refuses.

These cases exercise the plain contract of individual endpoints — the shape
that comes back, the filters that select, and the instant the clock supplies.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMINISTRATOR, ANALYST, REVIEWER


def test_markets_round_trip_from_creation_through_a_state_filtered_list():
    """Two definitions on one lender, separated by the state filter.

    PRD: "An `INVESTMENT_AREA` is composed of eleven-character tract codes
    supplied in `census_tract_codes`, which must be non-empty for that market
    type and must be empty for the other two; the field defaults to an empty
    collection."
    PRD: "A new definition is created in `state` `DRAFT` with `approved_at`
    null."
    PRD: "Approval stamps `approved_at` with the logical clock, and because
    seats pointing at that definition now begin to count, it also recomputes the
    institution's accountability figures and advances the institution's
    `version` by 1."
    PRD: "Target markets may be filtered by `institution_id`, `market_type` and
    `state`."

    Design: Corner/endpoints/target_market_create_read_and_filtered_list_round_trip
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution()
    institution_id = institution["id"]
    approved = fixtures.create_approved_target_market(
        institution_id, name="South Bronx Investment Area"
    )
    draft = fixtures.create_target_market(
        institution_id,
        name="Mott Haven Investment Area",
        census_tract_codes=["36005011200", "36005011300"],
    )

    everything, all_meta = validate_paginated(
        api_client.list_institution_target_markets(institution_id, ANALYST)
    )
    assert all_meta["total_count"] == 2
    assert {row["id"] for row in everything} == {approved["id"], draft["id"]}

    drafts, draft_meta = validate_paginated(
        api_client.list_institution_target_markets(
            institution_id, ANALYST, {"state": "DRAFT"}
        )
    )
    assert draft_meta["total_count"] == 1
    assert drafts[0]["id"] == draft["id"]

    _approved_rows, approved_meta = validate_paginated(
        api_client.list_institution_target_markets(
            institution_id, ANALYST, {"state": "APPROVED"}
        )
    )
    assert approved_meta["total_count"] == 1

    read_approved = validate_success(
        api_client.get_target_market(approved["id"], ANALYST)
    )
    assert read_approved["state"] == "APPROVED"
    assert read_approved["approved_at"] == "2026-09-01T00:00:00.000Z"

    read_draft = validate_success(api_client.get_target_market(draft["id"], ANALYST))
    assert read_draft["state"] == "DRAFT"
    assert read_draft["approved_at"] is None
    assert read_draft["census_tract_codes"] == ["36005011200", "36005011300"]


def test_a_servicing_run_returns_the_recomputed_lender_and_bumps_its_version():
    """An empty book still recomputes, still pins the ratio and still versions.

    PRD: "The run finishes by recomputing both reserve variants, then
    `reserve_coverage_ratio` and `compliance_posture`, in that order, and
    advances the institution's `version` by 1."
    PRD: "`loss_reserve_required_cents` then takes whichever variant the
    institution's `reserve_method` names, `reserve_coverage_ratio` is
    `loss_reserve_balance_cents` divided by `loss_reserve_required_cents` rounded
    half up to four decimal places — pinned to 1.0000 when the required figure is
    0 — and `compliance_posture` falls out of the bands in §2.11."

    Design: Corner/endpoints/servicing_run_returns_the_recomputed_institution_and_bumps_its_version
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution(loss_reserve_balance_cents=0)
    assert institution["version"] == 1

    first_run = validate_success(
        api_client.run_servicing(institution["id"], ANALYST)
    )
    assert first_run["version"] == 2
    assert float(first_run["reserve_coverage_ratio"]) == 1.0000
    assert first_run["compliance_posture"] == "COMPLIANT"

    second_run = validate_success(
        api_client.run_servicing(institution["id"], ANALYST)
    )
    assert second_run["version"] == 3, "every run advances the version"
    assert second_run["loss_reserve_required_cents"] == 0
    assert second_run["reserve_deficit_cents"] == 0

    reread = fixtures.read_institution(institution["id"])
    assert reread["loss_reserve_required_migration_cents"] == 0
    assert reread["loss_reserve_required_static_cents"] == 0
    assert reread["compliance_posture"] == "COMPLIANT"
    assert reread["version"] == 3


def test_resuming_draws_on_a_draft_award_is_a_state_error_not_a_posture_error():
    """The generic transition check runs ahead of the posture check.

    PRD: "First, the generic check that the requested transition is declared for
    the resource's current state, reported as `ERR_INVALID_STATE_TRANSITION`
    (HTTP 409) — this applies to every state-changing endpoint for which no more
    specific state error exists."
    PRD: "An `AwardAdministrator` must lift the suspension explicitly, and the
    gate to do so is strictly tighter than the activation gate: the application
    must be in `DRAW_SUSPENDED` and the institution's `compliance_posture` must
    be exactly `COMPLIANT` — `WATCH` is not sufficient here, and an attempt under
    `WATCH` or `PROBATION` is refused with `ERR_POSTURE_NOT_COMPLIANT`."

    Design: Corner/endpoints/resume_draws_on_a_draft_award_is_a_state_error_not_a_posture_error
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution()
    assert institution["compliance_posture"] == "COMPLIANT", (
        "a loan-free lender has nothing to reserve against"
    )
    award = fixtures.open_award_application(
        institution["id"],
        program="CMF",
        requested_amount_cents=5_000_000,
        match_ratio_pct=100.00,
        performance_goal_jobs=0,
        performance_goal_housing_units=25,
        period_start="2027-01-01T00:00:00Z",
        period_end="2027-12-31T00:00:00Z",
    )
    assert award["state"] == "DRAFT"

    response = api_client.resume_award_draws(award["id"], ADMINISTRATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    unchanged = validate_success(
        api_client.get_award_application(award["id"], ADMINISTRATOR)
    )
    assert unchanged["state"] == "DRAFT"
    assert unchanged["suspension_reason"] is None
    assert unchanged["version"] == 1


def test_a_refinance_link_is_stored_and_filterable_from_the_prior_loan():
    """The self-reference points one way only, and the filter follows it.

    PRD: "A refinance names the prior obligation in `refinance_of_loan_id`, which
    must resolve to another loan of the same borrower; new-money requests leave
    it null, and this self-reference is how credit-building step-ups are traced."
    PRD: "Loans may be filtered by `institution_id`, `borrower_id`, `product_id`,
    `refinance_of_loan_id`, `underwriting_state` and `servicing_state`."

    Design: Corner/endpoints/refinance_link_is_stored_and_filterable_in_both_directions
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.setup_lending_ready_institution()
    institution_id = scenario["institution"]["id"]
    borrower_id = scenario["borrower"]["id"]
    product_id = scenario["product"]["id"]
    prior = fixtures.file_loan(institution_id, borrower_id, product_id, 1_000_000)

    step_up = validate_success(
        api_client.create_loan(
            factories.loan_payload(
                institution_id, borrower_id, product_id, 1_200_000,
                refinance_of_loan_id=prior["id"],
            ),
            scenario["officer"],
        ),
        201,
    )
    assert step_up["refinance_of_loan_id"] == prior["id"]
    assert step_up["requested_principal_cents"] == 1_200_000
    assert step_up["underwriting_state"] == "SCREENING"

    forward, forward_meta = validate_paginated(
        api_client.list_loans(ANALYST, {"refinance_of_loan_id": prior["id"]})
    )
    assert forward_meta["total_count"] == 1
    assert forward[0]["id"] == step_up["id"]

    _reverse, reverse_meta = validate_paginated(
        api_client.list_loans(ANALYST, {"refinance_of_loan_id": step_up["id"]})
    )
    assert reverse_meta["total_count"] == 0, "nothing refinances the step-up itself"

    _both, both_meta = validate_paginated(
        api_client.list_loans(ANALYST, {"borrower_id": borrower_id})
    )
    assert both_meta["total_count"] == 2

    reread_prior = validate_success(api_client.get_loan(prior["id"], ANALYST))
    assert reread_prior["refinance_of_loan_id"] is None
    assert reread_prior["underwriting_state"] == "SCREENING"


def test_moving_the_clock_moves_the_instant_that_side_effects_stamp():
    """Two writes on two different instants stamp two different instants.

    PRD: "Nothing in this system reads the host's wall clock. A single
    server-side logical UTC instant supplies every date-derived value: the
    instant a certification decision is signed, the instant a target market is
    approved, the instant a board seat is retired, the instant a report is
    verified, the date a loan is first disbursed and the vintage year derived
    from it, the installment due date, the days-past-due arithmetic in the
    servicing checkpoint, the close instant of a technical-assistance engagement,
    the finalization instant of a measurement, and the upper bound a measurement
    window is checked against."
    PRD: "An administrative test-driving capability sets the clock to a supplied
    instant carried in the request field `to_iso8601`; the call mutates no
    entity, returns HTTP 200, and is available to every role except `Borrower`."
    PRD: "Resignation sets the seat's `status` to `RESIGNED`, stamps
    `resigned_at` from the logical clock, decrements the matching active-seat
    counter on the institution, recomputes `accountability_score` and
    `accountability_satisfied`, and advances the institution's `version` by 1."

    Design: Corner/endpoints/clock_endpoint_moves_the_instant_that_side_effects_stamp
    """
    institution = fixtures.create_institution()
    institution_id = institution["id"]
    officer = fixtures.make_institution_officer_headers(institution_id)
    market = fixtures.create_target_market(
        institution_id, name="South Bronx Investment Area"
    )
    seat = fixtures.create_board_seat(
        institution_id,
        structure="GOVERNING_BOARD",
        holder_name="R. Alvarez",
        represents_target_market=True,
        target_market_id=market["id"],
    )
    assert seat["status"] == "ACTIVE"
    assert seat["resigned_at"] is None

    validate_success(api_client.set_clock("2026-09-05T00:00:00Z", ANALYST))
    approved = validate_success(
        api_client.approve_target_market(market["id"], REVIEWER)
    )
    assert approved["approved_at"] == "2026-09-05T00:00:00.000Z"

    validate_success(api_client.set_clock("2026-09-06T00:00:00Z", ANALYST))
    resigned = validate_success(api_client.resign_board_seat(seat["id"], officer))
    assert resigned["status"] == "RESIGNED"
    assert resigned["resigned_at"] == "2026-09-06T00:00:00.000Z"

    reread_market = validate_success(
        api_client.get_target_market(market["id"], ANALYST)
    )
    assert reread_market["approved_at"] == "2026-09-05T00:00:00.000Z", (
        "moving the clock forward does not re-stamp what was already written"
    )

    lender = fixtures.read_institution(institution_id)
    assert lender["governing_seats_active"] == 0
    assert float(lender["accountability_score"]) == 0.0000


def test_every_child_resolves_by_parent_filter_and_by_single_read():
    """Flat lists select by parent; single reads return the same rows.

    PRD: "Because ownership is a graph rather than a strict tree — a loan points
    at an institution, a borrower and a product, and optionally at another loan
    it refinances; a board seat joins an institution to a target market; an
    engagement joins an institution, a borrower and optionally a loan — most
    collections are also exposed as flat lists carrying explicit filters."
    PRD: "Matching-fund commitments may be filtered by `award_application_id`,
    `status` and `source_type`."
    PRD: "A pledge is created with `status` `PLEDGED`, `eligible_cents` 0,
    `verified_by_user_id` null and `withdraw_reason` null."

    Design: Corner/endpoints/flat_reverse_lookup_lists_and_single_reads_resolve_every_child_by_parent
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    parent = fixtures.create_institution(
        legal_name="Harborline Community Fund", ein="210000059"
    )
    childless = fixtures.create_institution(
        legal_name="Rival Community Lenders", ein="210000060",
        entity_type="CREDIT_UNION", asset_size_cents=100_000_000,
        reserve_method="STATIC_POOL",
    )
    market = fixtures.create_target_market(
        parent["id"],
        market_type="LOW_INCOME_TARGETED_POPULATION",
        name="Low Income Households",
        census_tract_codes=[],
        ami_threshold_pct=80.00,
    )
    borrower = fixtures.create_borrower(parent["id"])
    product = fixtures.create_loan_product(parent["id"], product_cap_cents=5_000_000)
    award = fixtures.open_award_application(
        parent["id"],
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-06-30T00:00:00Z",
    )
    commitment = fixtures.pledge_commitment(
        award["id"], source_name="Community Trust Grant",
        source_type="CASH_PRIVATE", amount_cents=1_000_000,
        committed_on="2026-05-01T00:00:00Z",
    )

    markets, market_meta = validate_paginated(
        api_client.list_target_markets(ANALYST, {"institution_id": parent["id"]})
    )
    assert market_meta["total_count"] == 1
    assert markets[0]["state"] == "DRAFT"

    borrowers, borrower_meta = validate_paginated(
        api_client.list_borrowers(ANALYST, {"institution_id": parent["id"]})
    )
    assert borrower_meta["total_count"] == 1
    assert float(borrowers[0]["income_pct_ami"]) == 60.00

    empty, empty_meta = validate_paginated(
        api_client.list_loan_products(ANALYST, {"institution_id": childless["id"]})
    )
    assert empty == []
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False

    commitments, commitment_meta = validate_paginated(
        api_client.list_matching_fund_commitments(
            ANALYST, {"award_application_id": award["id"]}
        )
    )
    assert commitment_meta["total_count"] == 1
    assert commitments[0]["status"] == "PLEDGED"

    read_market = validate_success(api_client.get_target_market(market["id"], ANALYST))
    assert read_market["state"] == "DRAFT"
    assert read_market["approved_at"] is None
    assert float(read_market["ami_threshold_pct"]) == 80.00

    read_product = validate_success(api_client.get_loan_product(product["id"], ANALYST))
    assert read_product["committed_principal_cents"] == 0
    assert read_product["product_cap_cents"] == 5_000_000

    read_commitment = validate_success(
        api_client.get_matching_fund_commitment(commitment["id"], ANALYST)
    )
    assert read_commitment["status"] == "PLEDGED"
    assert read_commitment["eligible_cents"] == 0

    _parent_products, parent_product_meta = validate_paginated(
        api_client.list_loan_products(ANALYST, {"institution_id": parent["id"]})
    )
    assert parent_product_meta["total_count"] == 1
    assert borrower["institution_id"] == parent["id"]
