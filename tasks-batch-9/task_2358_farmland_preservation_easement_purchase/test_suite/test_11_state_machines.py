"""Declared initial states, guarded edges, terminal states and replayed edges.

Every row in the system starts in a state the PRD names explicitly, and most of
the interesting edges are guarded by a condition that lives on some other row.
Replaying an edge that has already been taken has to be refused rather than
repeated.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    APPRAISER_USER_ID_ALT,
    CLOCK_2026_08_10,
    CLOCK_2026_10_01,
    CLOCK_2026_10_12,
    OFFICER_USER_ID,
    REVIEWER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    accept_as_landowner,
    api_client,
    assert_source_ledger_conserved,
    commitments_of,
    counter_payload,
    create_application_payload,
    create_draft_round,
    create_landowner,
    create_parcel,
    create_program,
    create_standard_sources,
    engage_appraisal,
    engage_appraisal_payload,
    list_negotiation_log,
    make_landowner_headers,
    rank_payload,
    rank_round,
    read_application,
    read_appraisal,
    read_parcel,
    read_source,
    requirement_of_type,
    review_appraisal_payload,
    set_clock,
    setup_certified_appraisal,
    setup_filed_application,
    setup_funded_application,
    setup_offered_application,
    setup_program_with_round,
    setup_ranked_application,
    submit_and_accept_requirement,
    submit_appraisal_payload,
    submit_subordination_payload,
    submit_survey_payload,
    submit_title_payload,
    withdrawal_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
OFFICER = TEST_USERS["acquisition_officer_headers"]
REVIEWER = TEST_USERS["appraisal_reviewer_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]

BERKS_PARCEL = {
    "county": "Berks",
    "acres": 80.00,
    "prime_soil_acres": 72.00,
    "statewide_important_soil_acres": 8.00,
    "contiguous_preserved_acres": 60.00,
    "road_frontage_feet": 400,
    "sewer_available": True,
    "zoning_min_lot_acres": 1.5,
    "baseline_dwelling_rights": 3,
    "unrestricted_value_cents": 120_000_000,
    "restricted_value_cents": 45_500_000,
}


def read_round(round_id: str) -> dict:
    return validate_success(api_client.get_funding_round(round_id, ADMIN))


class TestRoundLifecycle:
    """The round walks DRAFT to OPEN to SELECTED and no edge repeats."""

    def test_opening_a_draft_round_with_an_active_source_moves_it_to_open(self):
        """The three opening conditions all hold, so the edge is taken.

        PRD §3.1: "Opening a round moves it `DRAFT → OPEN`, and three conditions
        must hold: the round is in `DRAFT`, the parent program's `status` is
        `ACTIVE`, and at least one funding source exists on that same program
        with `status` of `ACTIVE`."

        Design: Corner/state_machines/round_opening_moves_draft_to_open_and_increments_version
        """
        program = create_program()
        assert program["status"] == "ACTIVE"
        set_clock(CLOCK_2026_08_10)
        create_standard_sources(program["id"])

        draft = create_draft_round(program["id"])
        assert draft["status"] == "DRAFT"
        assert draft["version"] == 1
        assert draft["score_basis"] is None
        assert draft["ranked_at"] is None

        opened = validate_success(
            api_client.open_funding_round(draft["id"], ADMIN)
        )
        assert opened["status"] == "OPEN"
        # One mutation on the row, so the counter lands on 2.
        assert opened["version"] == 2
        assert opened["round_label"] == "2026 Cycle A"
        assert opened["pool_cents"] == 500_000_000
        assert opened["application_count"] == 0
        assert opened["selected_count"] == 0
        assert opened["ranked_at"] is None
        assert opened["score_basis"] is None
        assert opened["id"] == draft["id"]

    def test_a_second_opening_and_a_second_rank_are_both_refused(self):
        """Neither edge may be replayed once the round has left OPEN.

        PRD §3.3: "It requires the round to be `OPEN` — a second attempt
        therefore fails with `ERR_INVALID_ROUND_STATE` — requires the logical
        clock to be strictly past `closes_on`, failing which the answer is
        `ERR_ROUND_WINDOW_CLOSED`, and requires at least one application on the
        round still in `RECEIVED`, failing which the answer is
        `ERR_NO_SCORED_APPLICATIONS`."

        Design: Corner/state_machines/a_second_opening_and_a_second_rank_on_the_same_round_are_rejected
        """
        scenario = setup_ranked_application()
        round_id = scenario["round"]["id"]
        application = scenario["application"]
        assert application["status"] == "RANKED"
        assert application["composite_score"] == pytest.approx(73.40, abs=0.01)

        validate_error(
            api_client.open_funding_round(round_id, ADMIN),
            ApiErrorId.ERR_INVALID_ROUND_STATE.value,
        )
        validate_error(
            api_client.rank_funding_round(
                round_id, rank_payload("ROUND_CLOSE_BASIS"), ADMIN
            ),
            ApiErrorId.ERR_INVALID_ROUND_STATE.value,
        )

        after = read_round(round_id)
        assert after["status"] == "SELECTED"
        # The rejected replay never overwrites the basis that was recorded.
        assert after["score_basis"] == "RECEIPT_BASIS"
        assert after["ranked_at"].startswith("2026-10-01")
        assert after["application_count"] == 1
        assert after["selected_count"] == 1

        unchanged = read_application(application["id"])
        assert unchanged["status"] == "RANKED"
        assert unchanged["composite_score"] == pytest.approx(73.40, abs=0.01)
        assert unchanged["version"] == application["version"]

    def test_a_filing_one_day_past_the_close_date_is_refused(self):
        """The intake window is inclusive, so the day after `closes_on` is out.

        PRD §3.3: "The round's `status` must be `OPEN` and the logical clock must
        lie within the intake window inclusive of both endpoints — at or after
        `opens_on` and at or before `closes_on` — otherwise the filing is
        rejected with `ERR_ROUND_WINDOW_CLOSED`."

        Design: Corner/state_machines/application_filed_after_the_round_close_date_is_rejected
        """
        scenario = setup_program_with_round()
        landowner_id = scenario["landowner"]["id"]
        parcel = create_parcel(landowner_id)
        assert scenario["round"]["closes_on"].startswith("2026-09-30")

        set_clock(CLOCK_2026_10_01)
        validate_error(
            api_client.create_application(
                create_application_payload(
                    scenario["round"]["id"], parcel["id"], landowner_id
                ),
                make_landowner_headers(landowner_id),
            ),
            ApiErrorId.ERR_ROUND_WINDOW_CLOSED.value,
        )

        # The round is still OPEN — only the clock moved — and nothing was written.
        still_open = read_round(scenario["round"]["id"])
        assert still_open["status"] == "OPEN"
        assert still_open["application_count"] == 0
        assert read_parcel(parcel["id"])["status"] == "ELIGIBLE"

        _rows, meta = validate_paginated(
            api_client.list_applications(
                ADMIN, {"funding_round_id": scenario["round"]["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestDeclaredInitialStates:
    """Every freshly created row opens in the state the PRD names for it."""

    def test_newly_created_rows_start_in_their_declared_initial_states(self):
        """Source, round, parcel, application and appraisal at birth.

        PRD §3.1: "A new source opens `ACTIVE` with all three sums at 0 and
        `available_cents` equal to `authorized_cents`, and with
        `suspension_reason` null."

        PRD §3.3: "The application opens with `status` `RECEIVED`,
        `closing_status` `NOT_APPLICABLE`, `funding_plan_status` `UNFUNDED` and
        `negotiation_round_count` at 0."

        Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
        """
        program = create_program()
        landowner = create_landowner()
        set_clock(CLOCK_2026_08_10)
        sources = create_standard_sources(program["id"])

        local = sources["local"]
        assert local["status"] == "ACTIVE"
        assert local["committed_cents"] == 0
        assert local["reserved_cents"] == 0
        assert local["disbursed_cents"] == 0
        assert local["available_cents"] == 60_000_000
        assert local["authorized_cents"] == 60_000_000
        assert local["suspension_reason"] is None
        assert_source_ledger_conserved(local)

        draft = create_draft_round(program["id"])
        assert draft["status"] == "DRAFT"
        assert draft["application_count"] == 0
        assert draft["selected_count"] == 0
        opened = validate_success(api_client.open_funding_round(draft["id"], ADMIN))
        assert opened["status"] == "OPEN"

        parcel = create_parcel(landowner["id"])
        assert parcel["status"] == "ELIGIBLE"

        application = validate_success(
            api_client.create_application(
                create_application_payload(
                    opened["id"], parcel["id"], landowner["id"]
                ),
                make_landowner_headers(landowner["id"]),
            ),
            201,
        )
        assert application["status"] == "RECEIVED"
        assert application["closing_status"] == "NOT_APPLICABLE"
        assert application["funding_plan_status"] == "UNFUNDED"
        assert application["negotiation_round_count"] == 0
        assert application["composite_score"] is None
        assert application["rank_position"] is None
        assert application["agreed_price_cents"] is None

        appraisal = engage_appraisal(application["id"])
        assert appraisal["status"] == "ASSIGNED"
        assert appraisal["basis"] == "CERTIFIED_APPRAISAL_BASIS"
        assert appraisal["submission_count"] == 0
        assert appraisal["engaged_by_user_id"] == OFFICER_USER_ID
        assert appraisal["easement_value_cents"] is None
        assert appraisal["certified_by_user_id"] is None
        assert appraisal["review_note"] is None


class TestAppraisalLifecycle:
    """`CERTIFIED` is terminal, and engagement reads the application's state."""

    def test_a_certified_appraisal_refuses_both_resubmission_and_re_review(self):
        """Nothing leaves `CERTIFIED`, in either direction.

        PRD §3.4: "The lifecycle enumeration is `ASSIGNED`, `SUBMITTED`,
        `CERTIFIED` and `REJECTED`, and `CERTIFIED` is terminal."

        Design: Corner/state_machines/certified_appraisal_is_terminal_and_admits_no_resubmission_or_re_review
        """
        scenario = setup_filed_application()
        certified = setup_certified_appraisal(scenario["application"]["id"])
        assert certified["status"] == "CERTIFIED"

        validate_error(
            api_client.submit_appraisal(
                certified["id"],
                submit_appraisal_payload(300_000_000, 100_000_000),
                APPRAISER,
            ),
            ApiErrorId.ERR_INVALID_APPRAISAL_STATE.value,
        )
        validate_error(
            api_client.review_appraisal(
                certified["id"],
                review_appraisal_payload("REJECT", review_note="on second thought"),
                REVIEWER,
            ),
            ApiErrorId.ERR_INVALID_APPRAISAL_STATE.value,
        )

        after = read_appraisal(certified["id"])
        assert after["status"] == "CERTIFIED"
        # The refused resubmission never re-derived the value or the counter.
        assert after["easement_value_cents"] == 175_550_000
        assert after["submission_count"] == 1
        assert after["certified_by_user_id"] == REVIEWER_USER_ID
        assert after["review_note"] is None

        application = read_application(scenario["application"]["id"])
        assert application["certified_easement_value_cents"] == 175_550_000

    def test_engagement_is_refused_on_a_withdrawn_application(self):
        """The identical payload turns on the parent application's state.

        PRD §3.4: "The application must be in `RECEIVED`, `RANKED`,
        `OFFER_ISSUED` or `COUNTERED`, and any other state is rejected with
        `ERR_INVALID_APPLICATION_STATE`."

        Design: Corner/state_machines/appraisal_assignment_is_guarded_by_the_application_status_dimension
        """
        scenario = setup_filed_application()
        landowner_id = scenario["landowner"]["id"]
        landowner_headers = make_landowner_headers(landowner_id)

        second_parcel = create_parcel(landowner_id, **BERKS_PARCEL)
        second_application = validate_success(
            api_client.create_application(
                create_application_payload(
                    scenario["round"]["id"],
                    second_parcel["id"],
                    landowner_id,
                    requested_price_cents=70_000_000,
                ),
                landowner_headers,
            ),
            201,
        )
        withdrawn = validate_success(
            api_client.withdraw_application(
                second_application["id"],
                withdrawal_payload("landowner reconsidered"),
                landowner_headers,
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["withdrawal_reason"] == "landowner reconsidered"

        payload = engage_appraisal_payload()
        admitted = validate_success(
            api_client.engage_appraisal(
                scenario["application"]["id"], payload, OFFICER
            ),
            201,
        )
        assert admitted["status"] == "ASSIGNED"

        validate_error(
            api_client.engage_appraisal(second_application["id"], payload, OFFICER),
            ApiErrorId.ERR_INVALID_APPLICATION_STATE.value,
        )

        assert read_application(scenario["application"]["id"])["status"] == "RECEIVED"
        _rows, meta = validate_paginated(
            api_client.list_appraisals(second_application["id"], ADMIN)
        )
        assert meta["total_count"] == 0
        # A withdrawal released the land, so the parcel is eligible again.
        assert read_parcel(second_parcel["id"])["status"] == "ELIGIBLE"

    def test_a_counter_and_a_review_are_both_refused_from_the_wrong_state(self):
        """Two different machines, two different conflict codes, one request each.

        PRD §3.5: "The landowner answers an offer with a counter, which requires
        the application to be in `OFFER_ISSUED` and `X-User-ID` to equal the
        application's `landowner_id`."

        PRD §3.4: "The appraisal must be in `SUBMITTED`, and the
        segregation-of-duties gate of §2.9 applies."

        Design: Corner/state_machines/counter_on_a_ranked_application_and_review_of_an_assigned_appraisal_are_rejected
        """
        scenario = setup_filed_application()
        application_id = scenario["application"]["id"]
        landowner_id = scenario["landowner"]["id"]
        setup_certified_appraisal(application_id)

        # A second engagement, well clear of the first window plus its buffer.
        spare = engage_appraisal(
            application_id,
            appraiser_user_id=APPRAISER_USER_ID_ALT,
            appraiser_firm="Conestoga Valuation",
            engagement_start="2026-09-10T00:00:00Z",
            engagement_end="2026-09-20T00:00:00Z",
            method="INCOME_CAPITALIZATION",
        )
        assert spare["status"] == "ASSIGNED"

        rank_round(scenario["round"]["id"])
        assert read_application(application_id)["status"] == "RANKED"

        validate_error(
            api_client.file_counter(
                application_id,
                counter_payload(100_000_000),
                make_landowner_headers(landowner_id),
            ),
            ApiErrorId.ERR_INVALID_APPLICATION_STATE.value,
        )
        validate_error(
            api_client.review_appraisal(
                spare["id"], review_appraisal_payload("CERTIFY"), REVIEWER
            ),
            ApiErrorId.ERR_INVALID_APPRAISAL_STATE.value,
        )

        application = read_application(application_id)
        assert application["status"] == "RANKED"
        assert application["last_counter_cents"] is None
        assert application["negotiation_round_count"] == 0
        assert list_negotiation_log(application_id, {"limit": 100}) == []
        # The certification that did happen is untouched by the refusals.
        assert application["certified_easement_value_cents"] == 175_550_000

        untouched = read_appraisal(spare["id"])
        assert untouched["status"] == "ASSIGNED"
        assert untouched["certified_by_user_id"] is None


class TestOfferIssuance:
    """One offer appends one log entry and rewrites the whole cost stack."""

    def test_offer_issuance_appends_a_round_and_rewrites_every_derived_cost_field(self):
        """The log entry, the offer stamps and all four cost fields at once.

        PRD §3.5: "A successful offer appends an `OFFER` entry whose `round_index`
        is one more than the current `negotiation_round_count` and whose
        `amount_cents` is the offer amount, recomputes `negotiation_round_count`
        from the log, and writes `structure`, `donation_pct`,
        `installment_years`, `current_offer_cents`, `current_offer_expires_on`,
        `proposed_price_cents` (also the offer amount) and
        `offer_issued_by_user_id` (the issuing officer's `X-User-ID`)."

        Design: Corner/state_machines/offer_issuance_appends_a_round_and_rewrites_every_derived_cost_field
        """
        scenario = setup_offered_application()
        offered = scenario["application"]
        assert offered["status"] == "OFFER_ISSUED"
        assert offered["negotiation_round_count"] == 1

        entries = list_negotiation_log(offered["id"], {"limit": 100})
        assert len(entries) == 1
        entry = entries[0]
        assert entry["kind"] == "OFFER"
        assert entry["round_index"] == 1
        assert entry["amount_cents"] == 175_550_000
        assert entry["offer_expires_on"].startswith("2026-11-19")
        assert entry["actor_role"] == "AcquisitionOfficer"
        assert entry["actor_user_id"] == OFFICER_USER_ID
        assert entry["rationale"] is None

        assert offered["structure"] == "BARGAIN_SALE"
        assert offered["donation_pct"] == pytest.approx(0.10, abs=0.0001)
        assert offered["installment_years"] is None
        assert offered["current_offer_cents"] == 175_550_000
        assert offered["current_offer_expires_on"].startswith("2026-11-19")
        assert offered["proposed_price_cents"] == 175_550_000
        assert offered["offer_issued_by_user_id"] == OFFICER_USER_ID

        # 10 percent donation, then a 1.5 percent fee on the cash portion.
        assert offered["donation_cents"] == 17_555_000
        assert offered["bargain_sale_price_cents"] == 157_995_000
        assert offered["admin_fee_cents"] == 2_369_925
        assert offered["total_program_cost_cents"] == 160_364_925
        assert offered["first_installment_cents"] is None
        assert offered["final_installment_cents"] is None
        assert offered["installment_interest_total_cents"] is None

        # The other two dimensions are untouched by an offer.
        assert offered["funding_plan_status"] == "UNFUNDED"
        assert offered["closing_status"] == "NOT_APPLICABLE"


class TestClosingStatusBubbling:
    """`closing_status` is a pure function of the requirement children."""

    def test_the_third_acceptance_clears_the_file_and_a_resubmission_unclears_it(self):
        """The bubble runs in both directions inside the same request.

        PRD §3.7: "Clearance is a pure function of the children plus the funding
        dimension: the application's `closing_status` bubbles
        `PENDING_REQUIREMENTS → CLEARED` exactly when `requirement_total` is
        greater than 0, `requirement_satisfied_count` equals `requirement_total`,
        and `funding_plan_status` is `OBLIGATED`."

        PRD §3.7: "and because it may have left `SATISFIED`, the satisfied count
        can fall below the total and bubble `CLEARED → PENDING_REQUIREMENTS`."

        Design: Corner/state_machines/requirement_satisfaction_bubbles_closing_status_up_and_resubmission_bubbles_it_back_down
        """
        scenario = setup_funded_application()
        application_id = scenario["application"]["id"]
        set_clock(CLOCK_2026_10_12)
        accepted = accept_as_landowner(application_id, scenario["landowner"]["id"])
        assert accepted["requirement_total"] == 3
        assert accepted["requirement_satisfied_count"] == 0
        assert accepted["closing_status"] == "PENDING_REQUIREMENTS"

        title = requirement_of_type(application_id, "TITLE_COMMITMENT")
        subordination = requirement_of_type(application_id, "MORTGAGE_SUBORDINATION")
        survey = requirement_of_type(application_id, "BOUNDARY_SURVEY")

        submit_and_accept_requirement(title["id"], submit_title_payload(0))
        after_first = read_application(application_id)
        assert after_first["requirement_satisfied_count"] == 1
        assert after_first["closing_status"] == "PENDING_REQUIREMENTS"

        submit_and_accept_requirement(
            subordination["id"], submit_subordination_payload("Midstate Farm Credit")
        )
        after_second = read_application(application_id)
        assert after_second["requirement_satisfied_count"] == 2
        assert after_second["closing_status"] == "PENDING_REQUIREMENTS"

        submit_and_accept_requirement(survey["id"], submit_survey_payload(160.00))
        cleared = read_application(application_id)
        assert cleared["requirement_satisfied_count"] == 3
        assert cleared["closing_status"] == "CLEARED"

        # Fresh title work supersedes the accepted work in one request.
        resubmitted = validate_success(
            api_client.submit_closing_requirement(
                title["id"], submit_title_payload(0), OFFICER
            )
        )
        assert resubmitted["status"] == "SUBMITTED"

        reopened = read_application(application_id)
        assert reopened["requirement_satisfied_count"] == 2
        assert reopened["closing_status"] == "PENDING_REQUIREMENTS"
        assert reopened["requirement_total"] == 3
        # The acquisition and funding dimensions never moved.
        assert reopened["status"] == "ACCEPTED"
        assert reopened["funding_plan_status"] == "OBLIGATED"

        assert (
            validate_success(
                api_client.get_closing_requirement(subordination["id"], ADMIN)
            )["status"]
            == "SATISFIED"
        )
        assert (
            validate_success(api_client.get_closing_requirement(survey["id"], ADMIN))[
                "status"
            ]
            == "SATISFIED"
        )


class TestCommitmentObligation:
    """Obligation moves cents from the reserved column to the committed one."""

    def test_acceptance_moves_every_reservation_into_the_committed_column(self):
        """Reserved falls to zero, committed rises by exactly the same cents.

        PRD §3.1: "`committed_cents` is the sum of `amount_cents` over its
        commitments whose status is `OBLIGATED` or `DISBURSED`. `reserved_cents`
        is the same sum over commitments in `RESERVED`. `disbursed_cents` is the
        same sum over commitments in `DISBURSED`. `available_cents` is
        `authorized_cents` less `committed_cents` — reserved commitments are
        deliberately not netted out, which is why two competing plans may reserve
        against the same headroom and the loser lapses when the winner is
        accepted."

        Design: Corner/state_machines/commitment_obligation_syncs_the_source_reserved_committed_and_available_ledgers
        """
        scenario = setup_funded_application()
        sources = scenario["sources"]
        expected = {
            "local": (56_127_723, 60_000_000),
            "state": (64_145_970, 120_000_000),
            "federal": (40_091_232, 200_000_000),
        }

        for key, (amount, authorized) in expected.items():
            before = read_source(sources[key]["id"])
            assert before["reserved_cents"] == amount
            assert before["committed_cents"] == 0
            assert before["disbursed_cents"] == 0
            # Reservations are not netted, so headroom is still the full authority.
            assert before["available_cents"] == authorized
            assert_source_ledger_conserved(before)

        set_clock(CLOCK_2026_10_12)
        accepted = accept_as_landowner(
            scenario["application"]["id"], scenario["landowner"]["id"]
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["funding_plan_status"] == "OBLIGATED"
        assert accepted["agreed_price_cents"] == 175_550_000

        for key, (amount, authorized) in expected.items():
            after = read_source(sources[key]["id"])
            assert after["reserved_cents"] == 0
            assert after["committed_cents"] == amount
            assert after["disbursed_cents"] == 0
            assert after["available_cents"] == authorized - amount
            # No source reaches its 0.95 obligation floor on one plan.
            assert after["status"] == "ACTIVE"
            assert_source_ledger_conserved(after)

        obligated = commitments_of(accepted["id"])
        assert len(obligated) == 3
        assert {row["status"] for row in obligated} == {"OBLIGATED"}
