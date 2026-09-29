"""Parent-state, vetting, temporal, negotiation and offer gates.

The rungs below referential resolution are all business rules, and most of them
are only interesting one unit away from their boundary: a score one point short,
a clock one day early, a balance one cent over.
"""
from test_helpers import (
    CONSULTANT,
    PRINCIPAL,
    api_client,
    append_ledger_adjustment,
    book_trial,
    confirm_start_payload,
    create_accommodation_term_payload,
    create_fee_schedule_payload,
    create_placement_payload,
    create_requisition_payload,
    create_trial_engagement_payload,
    extend_offer,
    publish_fee_schedule,
    read_candidate,
    read_client,
    read_placement,
    read_requisition,
    read_term,
    read_trial,
    record_reference,
    record_trial_outcome,
    record_trial_outcome_payload,
    register_candidate,
    release_availability_payload,
    respond_to_term,
    set_clock,
    setup_booked_trial,
    setup_passed_trial,
    setup_pending_offer,
    setup_scenario,
    setup_sourcing_requisition,
    setup_substantiated_case,
    setup_terminated_placement,
    setup_vetted_candidate,
    start_trial,
    start_trial_payload,
    validate_error,
    validate_paginated,
    validate_success,
    verify_reference,
)

CHEF_REFERENCES = (
    {},
    {
        "principal_employer_name": "Marlow Estate",
        "contact_email": "marlow@mail.example",
        "employment_start_month": "2024-01",
        "employment_end_month": "2024-12",
        "chain_to_previous": True,
    },
)


class TestHouseholdEligibilityGates:
    def test_01_a_suspended_household_may_not_open_a_new_search(self):
        """The agreement is intact, so suspension is the only objection left.

        PRD §3.1: "Two household gates apply before the row is written: a
        household whose `confidentiality_agreement_status` is anything other than
        `COUNTERSIGNED` is refused with `ERR_NDA_NOT_COUNTERSIGNED` (HTTP 409) —
        the child's admissibility is decided by a field on its parent — and a
        household whose `status` is `SUSPENDED` is refused with
        `ERR_CLIENT_SUSPENDED` (HTTP 409)."

        Design: Corner/validations/a_suspended_household_cannot_open_a_new_search
        """
        scenario = setup_substantiated_case()
        client_id = scenario["client"]["id"]
        assert read_client(scenario["client"])["status"] == "SUSPENDED"

        validate_error(
            api_client.create_requisition(
                create_requisition_payload(client_id), CONSULTANT
            ),
            "ERR_CLIENT_SUSPENDED",
            409,
        )

        _, meta = validate_paginated(
            api_client.list_requisitions(CONSULTANT, {"client_id": client_id})
        )
        assert meta["total_count"] == 1

    def test_02_an_actual_package_off_the_band_table_blocks_confirmation(self):
        """The requisition priced happily; the actual package resolves nothing.

        PRD §3.2: "When the candidate set is empty the resolution has no result at
        all and the calling operation is refused with `ERR_NO_FEE_SCHEDULE_MATCH`
        (HTTP 422); the most common way to hit this is a compensation figure equal
        to the top band's ceiling when no unbounded band has been published above
        it."

        Design: Corner/validations/a_package_that_leaves_every_band_blocks_the_confirmation
        """
        scenario = setup_pending_offer(
            placement={
                "base_salary_cents": 15_000_000,
                "guaranteed_bonus_cents": 0,
                "accommodation_imputed_cents": 0,
                "overtime_allowance_cents": 0,
            }
        )
        set_clock("2026-09-01T00:00:00Z")

        validate_error(
            api_client.confirm_placement_start(
                scenario["placement"]["id"], confirm_start_payload(), PRINCIPAL
            ),
            "ERR_NO_FEE_SCHEDULE_MATCH",
            422,
        )

        stored = read_placement(scenario["placement"])
        assert stored["placement_status"] == "PENDING_ACCEPTANCE"
        assert stored["fee_variant"] == "PROVISIONAL"
        assert stored["fee_cents"] == 2_000_000
        assert stored["guarantee_expires_on"] == "2026-11-30"
        assert read_requisition(scenario["requisition"])["status"] == "OFFER_PENDING"

    def test_03_an_intersecting_band_on_the_same_effective_date_is_refused(self):
        """Same role type, same effective date, intersecting range.

        PRD §3.2: "Bands for the same `role_type` sharing the same `effective_from`
        may not overlap: if an existing `ACTIVE` band for that role type and that
        same effective date covers any part of the proposed range, the publication
        is refused with `ERR_FEE_BAND_OVERLAP` (HTTP 409)."

        Design: Corner/validations/a_second_band_overlapping_the_same_effective_date_is_refused
        """
        setup_scenario(stage="clock")
        publish_fee_schedule(comp_band_ceiling_cents=10_000_000)

        validate_error(
            api_client.create_fee_schedule(
                create_fee_schedule_payload(
                    comp_band_floor_cents=5_000_000,
                    comp_band_ceiling_cents=15_000_000,
                    fee_percent_bps=2500,
                    guarantee_window_days=120,
                ),
                PRINCIPAL,
            ),
            "ERR_FEE_BAND_OVERLAP",
            409,
        )

        _, meta = validate_paginated(
            api_client.list_fee_schedules(PRINCIPAL, {"role_type": "HOUSEKEEPER"})
        )
        assert meta["total_count"] == 1

    def test_04_bands_that_merely_touch_are_accepted(self):
        """A floor equal to the stored ceiling is adjacency, not overlap.

        PRD §3.2: "Overlap is judged on half-open ranges, so bands that merely
        touch — one band's ceiling exactly equal to the next band's floor — do not
        overlap and are accepted."

        Design: Corner/validations/touching_fee_bands_are_accepted
        """
        setup_scenario(stage="clock")
        publish_fee_schedule(comp_band_ceiling_cents=10_000_000)

        created = validate_success(
            api_client.create_fee_schedule(
                create_fee_schedule_payload(
                    comp_band_floor_cents=10_000_000,
                    comp_band_ceiling_cents=20_000_000,
                    fee_percent_bps=2500,
                    guarantee_window_days=120,
                ),
                PRINCIPAL,
            ),
            201,
        )
        assert created["status"] == "ACTIVE"
        assert created["comp_band_floor_cents"] == 10_000_000
        assert created["fee_percent_bps"] == 2500

        _, meta = validate_paginated(
            api_client.list_fee_schedules(PRINCIPAL, {"role_type": "HOUSEKEEPER"})
        )
        assert meta["total_count"] == 2


class TestVettingAndScoreGates:
    def test_05_an_unvetted_candidate_cannot_be_booked_for_a_trial(self):
        """The vetting gate answers before the presentation score gate.

        PRD §3.4: "The candidate's `vetting_status` must be one of
        `REFERENCES_VERIFIED`, `BACKGROUND_PENDING` or `CLEARED` — a trial may
        deliberately be run while the background screen is still outstanding — and
        anything else, including `UNVETTED`, `SCREENING` and `REJECTED`, is
        refused with `ERR_CANDIDATE_NOT_VETTED`."

        Design: Corner/validations/booking_an_unvetted_candidate_for_a_trial_is_refused
        """
        scenario = setup_sourcing_requisition()
        candidate = register_candidate()
        assert candidate["vetting_status"] == "UNVETTED"
        assert candidate["screening_score"] == 0

        validate_error(
            api_client.create_trial_engagement(
                scenario["requisition"]["id"],
                create_trial_engagement_payload(candidate["id"]),
                CONSULTANT,
            ),
            "ERR_CANDIDATE_NOT_VETTED",
            409,
        )

        stored = read_requisition(scenario["requisition"])
        assert stored["status"] == "SOURCING"
        assert stored["active_trial_count"] == 0

    def test_06_the_offer_branch_of_the_vetting_gate_demands_cleared(self):
        """A candidate good enough for the trial is not good enough for the offer.

        PRD §3.6: "The candidate's `vetting_status` must be exactly `CLEARED` —
        the looser trial-stage set does not apply to offers — and anything else is
        refused with `ERR_CANDIDATE_NOT_VETTED`."

        Design: Corner/validations/offering_a_candidate_whose_background_is_still_pending_is_refused
        """
        scenario = setup_scenario(stage="background_ordered")
        trial = book_trial(scenario["requisition"], scenario["candidate"])
        set_clock("2026-08-10T17:00:00Z")
        start_trial(trial)
        record_trial_outcome(trial, "PASSED")

        assert read_candidate(scenario["candidate"])["vetting_status"] == (
            "BACKGROUND_PENDING"
        )

        requisition = read_requisition(scenario["requisition"])
        validate_error(
            api_client.create_placement(
                create_placement_payload(
                    requisition["id"],
                    scenario["candidate"]["id"],
                    requisition["version"],
                ),
                CONSULTANT,
            ),
            "ERR_CANDIDATE_NOT_VETTED",
            409,
        )

        _, meta = validate_paginated(api_client.list_placements(CONSULTANT))
        assert meta["total_count"] == 0
        assert read_requisition(scenario["requisition"])["status"] == "TRIALING"

    def test_07_a_placement_ready_score_one_point_short_is_refused(self):
        """One disputed reference costs fifteen points and the offer gate.

        PRD §3.3: "**The disputed penalty** is 15 points for every
        `ReferenceCheck` of this candidate whose `status` is `DISPUTED`, and it is
        subtracted."

        PRD §3.6: "The candidate's `placement_ready_score` must be at least 80
        points, or the offer is refused with
        `ERR_CANDIDATE_SCORE_BELOW_THRESHOLD` (HTTP 422)."

        Design: Corner/validations/a_placement_ready_score_of_seventynine_is_refused
        """
        scenario = setup_passed_trial()
        disputed = record_reference(
            scenario["candidate"],
            principal_employer_name="Pemberton House",
            contact_email="pemberton@mail.example",
            employment_start_month="2019-01",
            employment_end_month="2019-06",
        )
        verify_reference(disputed, "DISPUTED")

        candidate = read_candidate(scenario["candidate"])
        assert candidate["screening_score"] == 74
        assert candidate["placement_ready_score"] == 79

        requisition = read_requisition(scenario["requisition"])
        validate_error(
            api_client.create_placement(
                create_placement_payload(
                    requisition["id"], candidate["id"], requisition["version"]
                ),
                CONSULTANT,
            ),
            "ERR_CANDIDATE_SCORE_BELOW_THRESHOLD",
            422,
        )

        _, meta = validate_paginated(api_client.list_placements(CONSULTANT))
        assert meta["total_count"] == 0

    def test_08_a_chef_search_applies_the_senior_chain_threshold(self):
        """The same dossier that would fill a housekeeper post is too thin here.

        PRD §3.6: "The candidate's `longest_contiguous_months` must be at least 24
        — two unbroken verified years — when the requisition's `role_type` is
        `ESTATE_MANAGER` or `CHEF`, and at least 12 when it is `HOUSEKEEPER` or
        `CHAUFFEUR`; a shorter chain is refused with
        `ERR_REFERENCE_CHAIN_TOO_SHORT` (HTTP 422)."

        Design: Corner/validations/a_chef_offer_needs_a_longer_contiguous_chain_than_a_housekeeper_offer
        """
        scenario = setup_scenario(
            stage="term_accepted",
            fee_schedules=[{"role_type": "CHEF"}],
            requisition={"role_type": "CHEF"},
            candidate={"primary_role_type": "CHEF", "years_experience": 20},
            references=CHEF_REFERENCES,
        )

        candidate = read_candidate(scenario["candidate"])
        assert candidate["longest_contiguous_months"] == 12
        assert candidate["reference_coverage_months"] == 24
        assert candidate["screening_score"] == 80
        assert candidate["placement_ready_score"] == 100

        requisition = read_requisition(scenario["requisition"])
        validate_error(
            api_client.create_placement(
                create_placement_payload(
                    requisition["id"], candidate["id"], requisition["version"]
                ),
                CONSULTANT,
            ),
            "ERR_REFERENCE_CHAIN_TOO_SHORT",
            422,
        )


class TestTemporalGates:
    def test_09_releasing_a_day_before_the_cooling_off_date_is_refused(self):
        """The comparison is inclusive, so the eve of the date still refuses.

        PRD §3.3: "From `COOLING_OFF` this is admissible only when the
        logical-clock date is on or after `cooling_off_until`; an earlier date is
        refused with `ERR_COOLING_OFF_ACTIVE` (HTTP 409), so a clock landing
        exactly on `cooling_off_until` releases the candidate while one day
        earlier does not."

        Design: Corner/validations/releasing_a_candidate_one_day_before_the_cooling_off_date_is_refused
        """
        scenario = setup_terminated_placement()
        set_clock("2026-11-14T00:00:00Z")

        validate_error(
            api_client.release_availability(
                scenario["candidate"]["id"], release_availability_payload(), CONSULTANT
            ),
            "ERR_COOLING_OFF_ACTIVE",
            409,
        )

        stored = read_candidate(scenario["candidate"])
        assert stored["availability_status"] == "COOLING_OFF"
        assert stored["cooling_off_until"] == "2026-11-15"

    def test_10_a_trial_cannot_start_before_its_start_instant(self):
        """The engagement is SCHEDULED, so only the clock is wrong.

        PRD §3.4: "The engagement must be `SCHEDULED`, and any other non-terminal
        state is refused with `ERR_TRIAL_NOT_SCHEDULED`; a `PASSED`, `FAILED` or
        `CANCELLED` engagement is refused with `ERR_ENTITY_TERMINAL`. The logical
        clock must be at or after `start_at`, and an earlier clock is refused with
        `ERR_TRIAL_NOT_STARTED`."

        Design: Corner/validations/starting_a_trial_before_its_start_at_is_refused
        """
        scenario = setup_booked_trial()

        validate_error(
            api_client.start_trial(
                scenario["trial"]["id"], start_trial_payload(), CONSULTANT
            ),
            "ERR_TRIAL_NOT_STARTED",
            409,
        )

        assert read_trial(scenario["trial"])["status"] == "SCHEDULED"

    def test_11_an_outcome_one_minute_inside_the_window_is_refused(self):
        """The engagement is genuinely IN_PROGRESS, so the window rule speaks.

        PRD §3.4: "The engagement must be `IN_PROGRESS`, or the request is refused
        with `ERR_TRIAL_NOT_IN_PROGRESS`; the logical clock must be at or after
        `end_at`, or it is refused with `ERR_TRIAL_WINDOW_NOT_ELAPSED`."

        Design: Corner/validations/recording_an_outcome_one_minute_before_the_trial_ends_is_refused
        """
        scenario = setup_scenario(
            stage="trial_started", trial_end_clock="2026-08-10T09:00:00Z"
        )
        set_clock("2026-08-10T16:59:00Z")

        validate_error(
            api_client.record_trial_outcome(
                scenario["trial"]["id"], record_trial_outcome_payload("PASSED"), CONSULTANT
            ),
            "ERR_TRIAL_WINDOW_NOT_ELAPSED",
            409,
        )

        stored = read_trial(scenario["trial"])
        assert stored["status"] == "IN_PROGRESS"
        assert stored["outcome_note"] is None


class TestNegotiationGates:
    def test_12_a_live_in_term_for_an_unwilling_candidate_is_refused(self):
        """The version is current and the candidate resolves, so only the
        accommodation clashes.

        PRD §3.5: "A term proposing `live_in` true for a candidate whose
        `live_in_willing` is false is refused with `ERR_LIVE_IN_INCOMPATIBLE`
        (HTTP 409)."

        Design: Corner/validations/proposing_live_in_to_an_unwilling_candidate_is_refused
        """
        scenario = setup_sourcing_requisition()
        candidate = register_candidate(live_in_willing=False)
        requisition = read_requisition(scenario["requisition"])

        validate_error(
            api_client.create_accommodation_term(
                requisition["id"],
                create_accommodation_term_payload(
                    candidate["id"],
                    requisition["version"],
                    live_in=True,
                    private_quarters=True,
                    imputed_accommodation_cents=300_000,
                ),
                CONSULTANT,
            ),
            "ERR_LIVE_IN_INCOMPATIBLE",
            409,
        )

        _, meta = validate_paginated(
            api_client.list_accommodation_terms(
                CONSULTANT, {"requisition_id": requisition["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert read_requisition(requisition)["live_in_required"] is False

    def test_13_a_counter_arriving_at_round_four_hits_the_cap(self):
        """Three alternating counters carry the term to the cap.

        PRD §3.5: "**The round cap:** a `COUNTER` is admissible only while
        `round_no` is strictly below four, so the fourth round is the last one
        that may be countered and a `COUNTER` arriving when `round_no` has already
        reached four is refused with `ERR_NEGOTIATION_ROUND_LIMIT` (HTTP 409)."

        Design: Corner/validations/the_fifth_negotiation_round_is_refused
        """
        scenario = setup_scenario(stage="term_proposed")
        term = scenario["term"]

        respond_to_term(term, scenario["client_headers"], "COUNTER", weekly_hours=42)
        respond_to_term(term, scenario["candidate_headers"], "COUNTER", weekly_hours=38)
        fourth = respond_to_term(
            term, scenario["client_headers"], "COUNTER", weekly_hours=41
        )
        assert fourth["round_no"] == 4
        assert fourth["last_responder_role"] == "CLIENT"

        validate_error(
            api_client.respond_accommodation_term(
                term["id"],
                {
                    "response": "COUNTER",
                    "weekly_hours": 39,
                    "note": "Response recorded.",
                },
                scenario["candidate_headers"],
            ),
            "ERR_NEGOTIATION_ROUND_LIMIT",
            409,
        )

        stored = read_term(term)
        assert stored["round_no"] == 4
        assert stored["weekly_hours"] == 41
        assert stored["status"] == "COUNTERED"

    def test_14_the_same_side_may_not_answer_twice_in_a_row(self):
        """round_no is only 2, so the cap is far away and alternation is the rule
        that bites.

        PRD §3.5: "**Alternation:** the party implied by `X-User-Role` must differ
        from `last_responder_role`, and a party attempting to answer its own move
        is refused with `ERR_RESPONDER_MUST_ALTERNATE` (HTTP 409) — a household
        cannot counter its own counter, and after the agency's opening proposal
        either counterparty may speak first, but then the other must reply."

        Design: Corner/validations/a_household_cannot_counter_its_own_counter
        """
        scenario = setup_scenario(stage="term_proposed")
        term = scenario["term"]
        respond_to_term(term, scenario["client_headers"], "COUNTER", weekly_hours=42)

        validate_error(
            api_client.respond_accommodation_term(
                term["id"],
                {
                    "response": "COUNTER",
                    "weekly_hours": 41,
                    "note": "Response recorded.",
                },
                scenario["client_headers"],
            ),
            "ERR_RESPONDER_MUST_ALTERNATE",
            409,
        )

        stored = read_term(term)
        assert stored["round_no"] == 2
        assert stored["weekly_hours"] == 42
        assert stored["last_responder_role"] == "CLIENT"


class TestOfferAndCreditGates:
    def test_15_an_engagement_that_exists_is_not_an_engagement_that_passed(self):
        """The relationship check is satisfied; the trial is merely still
        SCHEDULED.

        PRD §3.6: "After that, at least one `TrialEngagement` with the named
        `requisition_id` and `candidate_id` must have `status` `PASSED`, or the
        offer is refused with `ERR_NO_PASSED_TRIAL` (HTTP 409) — note the
        distinction from the relationship check above, which only asks whether any
        engagement exists at all."

        Design: Corner/validations/an_offer_without_a_passed_trial_is_refused
        """
        scenario = setup_booked_trial()
        assert read_trial(scenario["trial"])["status"] == "SCHEDULED"

        requisition = read_requisition(scenario["requisition"])
        validate_error(
            api_client.create_placement(
                create_placement_payload(
                    requisition["id"],
                    scenario["candidate"]["id"],
                    requisition["version"],
                ),
                CONSULTANT,
            ),
            "ERR_NO_PASSED_TRIAL",
            409,
        )

        _, meta = validate_paginated(api_client.list_placements(CONSULTANT))
        assert meta["total_count"] == 0

    def test_16_a_start_cannot_be_confirmed_without_an_accepted_term(self):
        """No negotiation was ever opened, so the confirmation has nothing to
        stand on.

        PRD §3.6: "An `AccommodationTerm` with the placement's `requisition_id`
        and `candidate_id` and `status` `ACCEPTED` must exist, or the confirmation
        is refused with `ERR_ACCOMMODATION_NOT_ACCEPTED` (HTTP 409)."

        Design: Corner/validations/confirming_a_start_without_an_accepted_term_is_refused
        """
        scenario = setup_passed_trial()
        placement = extend_offer(scenario["requisition"], scenario["candidate"])
        set_clock("2026-09-01T00:00:00Z")

        validate_error(
            api_client.confirm_placement_start(
                placement["id"], confirm_start_payload(), PRINCIPAL
            ),
            "ERR_ACCOMMODATION_NOT_ACCEPTED",
            409,
        )

        stored = read_placement(placement)
        assert stored["placement_status"] == "PENDING_ACCEPTANCE"
        assert stored["fee_variant"] == "PROVISIONAL"
        assert stored["guarantee_expires_on"] == "2026-11-30"

        household = read_client(scenario["client"])
        assert household["placement_count"] == 0
        assert household["non_solicitation_expires_on"] is None

    def test_17_a_balance_one_cent_over_the_limit_blocks_a_booking(self):
        """The limit is a strict comparison, so 5,000,001 is the first refusal.

        PRD §2.12: "When a household's `outstanding_balance_cents` is **strictly
        greater** than 5,000,000 cents — fifty thousand dollars — it is on
        **credit hold**, and neither a new trial booking nor a new offer may be
        made for it; both are refused with `ERR_CLIENT_CREDIT_HOLD` (HTTP 409). A
        balance of exactly 5,000,000 cents still transacts."

        Design: Corner/validations/a_household_one_cent_over_its_credit_limit_cannot_book_a_trial
        """
        scenario = setup_vetted_candidate()
        append_ledger_adjustment(scenario["client"], 5_000_001)
        assert read_client(scenario["client"])["outstanding_balance_cents"] == 5_000_001

        validate_error(
            api_client.create_trial_engagement(
                scenario["requisition"]["id"],
                create_trial_engagement_payload(scenario["candidate"]["id"]),
                CONSULTANT,
            ),
            "ERR_CLIENT_CREDIT_HOLD",
            409,
        )

        stored = read_requisition(scenario["requisition"])
        assert stored["status"] == "SOURCING"
        assert stored["active_trial_count"] == 0
