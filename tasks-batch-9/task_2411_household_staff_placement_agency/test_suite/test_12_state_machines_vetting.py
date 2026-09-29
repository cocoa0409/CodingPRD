"""Edges of the two candidate dimensions and of the negotiation machine.

The vetting axis and the availability axis are separate machines on one row, so
every test here reads both back and checks that only the intended one moved.
"""
from test_helpers import (
    CONSULTANT,
    PRINCIPAL,
    RECORDER,
    VERIFIER,
    adjudicate_background,
    adjudicate_background_payload,
    api_client,
    create_background_verification_payload,
    read_background_verification,
    read_candidate,
    read_requisition,
    read_term,
    record_background_result,
    record_reference,
    register_candidate,
    release_availability_payload,
    respond_to_term,
    set_clock,
    setup_scenario,
    terminate_placement,
    validate_error,
    validate_paginated,
    validate_success,
    verify_reference,
)

SEPARATION_DATE = "2026-10-16"
COOLING_OFF_UNTIL = "2026-11-15"


class TestCandidateVettingAxis:
    def test_01_a_candidate_enters_on_both_axes_at_once(self):
        """Two parallel dimensions, each at its own entry value.

        PRD §3.3: "A fresh candidate begins at `vetting_status` `UNVETTED` and
        `availability_status` `AVAILABLE`, with `cooling_off_until` null,
        `verified_reference_count`, `reference_coverage_months`,
        `longest_contiguous_months`, `screening_score` and `placement_ready_score`
        all 0, and `version` 1."

        Design: Corner/state_machines/candidate_initial_state_holds_both_dimensions_at_their_entry_values
        """
        setup_scenario(stage="clock")

        candidate = register_candidate()
        assert candidate["vetting_status"] == "UNVETTED"
        assert candidate["availability_status"] == "AVAILABLE"
        assert candidate["cooling_off_until"] is None
        assert candidate["version"] == 1

        stored = read_candidate(candidate)
        assert stored["vetting_status"] == "UNVETTED"
        assert stored["availability_status"] == "AVAILABLE"

    def test_02_a_pending_reference_moves_the_axis_without_scoring(self):
        """The transition fires on recording, but a PENDING row scores nothing.

        PRD §3.3: "The new row is created with `status` `PENDING`, a null
        `verification_note`, a null `verified_by_user_id`, and `created_by_user_id`
        stamped from the acting `X-User-ID`."

        PRD §3.3: "Recording a reference also drives the vetting axis: a candidate
        at `UNVETTED` moves `UNVETTED → SCREENING` on its first reference, and —
        this is a genuine cycle, not a mistake — a candidate previously rejected
        moves `REJECTED → SCREENING`, so a rejected candidate can be re-vetted from
        scratch simply by adding a new reference."

        PRD §3.3: "**Reference chain coverage** is computed over the candidate's
        `VERIFIED` reference rows only; `PENDING`, `UNREACHABLE` and `DISPUTED`
        rows contribute neither to the count nor to any month total."

        PRD §3.3: "**Experience points** are the candidate's `years_experience`
        multiplied by three, capped at 36 points — so twelve years of service
        reaches the cap and further years add nothing."

        PRD §3.3: "`screening_score` is the sum of those three components and
        nothing else: background work is not yet expected when a candidate is being
        put in front of a household, so background points contribute zero, and
        disputed references are ignored entirely at this stage."

        Design: Corner/state_machines/the_first_recorded_reference_moves_the_candidate_into_screening
        """
        setup_scenario(stage="clock")
        candidate = register_candidate()

        reference = record_reference(candidate)
        assert reference["status"] == "PENDING"
        assert reference["verified_by_user_id"] is None

        stored = read_candidate(candidate)
        assert stored["vetting_status"] == "SCREENING"
        assert stored["availability_status"] == "AVAILABLE"
        assert stored["verified_reference_count"] == 0
        assert stored["reference_coverage_months"] == 0
        assert stored["screening_score"] == 30

    def test_03_the_second_verification_closes_the_reference_gate(self):
        """Two adjacent verified years merge into one 24-month chain.

        PRD §3.3: "The intervals are sorted by start month and then merged
        pairwise whenever two of them either overlap or are *adjacent*, where
        adjacency means the next interval's start month is the calendar month
        immediately following the previous interval's end month, leaving a gap of
        zero months."

        PRD §3.3: "A candidate advances `SCREENING → REFERENCES_VERIFIED` when the
        recomputed `verified_reference_count` is at least two **and** the
        recomputed `longest_contiguous_months` is at least twelve — one unbroken
        verified year."

        PRD §3.3: "**Reference points** are the sum, over the candidate's
        `VERIFIED` reference rows, of the weight of each row's `relationship_type`
        — twelve points for a `PRINCIPAL_EMPLOYER`, eight for an
        `AGENCY_SUPERVISOR`, four for a `PEER` — capped at 24 points."

        PRD §3.3: "**Coverage points** are the candidate's
        `reference_coverage_months`, capped at 20 points, so a candidate with
        twenty or more merged verified months is at the cap."

        Design: Corner/state_machines/the_second_verification_meets_the_reference_gate
        """
        scenario = setup_scenario(stage="references_recorded")
        first, second = scenario["references"]
        verify_reference(first)
        assert read_candidate(scenario["candidate"])["vetting_status"] == "SCREENING"

        data = verify_reference(second)
        assert data["status"] == "VERIFIED"
        assert data["verified_by_user_id"] == VERIFIER["X-User-ID"]

        stored = read_candidate(scenario["candidate"])
        assert stored["vetting_status"] == "REFERENCES_VERIFIED"
        assert stored["verified_reference_count"] == 2
        assert stored["reference_coverage_months"] == 24
        assert stored["longest_contiguous_months"] == 24
        assert stored["screening_score"] == 74
        assert stored["placement_ready_score"] == 74

    def test_04_one_verified_reference_fails_the_count_half_of_the_gate(self):
        """The gate is a conjunction: a 12-month chain alone is not enough.

        PRD §3.3: "A candidate advances `SCREENING → REFERENCES_VERIFIED` when the
        recomputed `verified_reference_count` is at least two **and** the
        recomputed `longest_contiguous_months` is at least twelve — one unbroken
        verified year."

        PRD §3.3: "`verified_reference_count` is simply how many `VERIFIED` rows
        the candidate has."

        PRD §3.3: "**Coverage points** are the candidate's
        `reference_coverage_months`, capped at 20 points, so a candidate with
        twenty or more merged verified months is at the cap."

        Design: Corner/state_machines/a_single_verified_reference_leaves_the_candidate_in_screening
        """
        setup_scenario(stage="clock")
        candidate = register_candidate()
        reference = record_reference(candidate)

        data = verify_reference(reference)
        assert data["status"] == "VERIFIED"

        stored = read_candidate(candidate)
        assert stored["vetting_status"] == "SCREENING"
        assert stored["verified_reference_count"] == 1
        assert stored["reference_coverage_months"] == 12
        assert stored["longest_contiguous_months"] == 12
        assert stored["screening_score"] == 54

    def test_05_a_screening_candidate_cannot_have_a_screen_ordered(self):
        """The refusal creates no BackgroundVerification row at all.

        PRD §3.3: "Ordering a screen for a candidate not sitting at
        `REFERENCES_VERIFIED` is refused with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/ordering_a_background_check_before_the_reference_gate_is_refused
        """
        setup_scenario(stage="clock")
        candidate = register_candidate()
        verify_reference(record_reference(candidate))
        assert read_candidate(candidate)["vetting_status"] == "SCREENING"

        validate_error(
            api_client.create_background_verification(
                candidate["id"], create_background_verification_payload(), VERIFIER
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )

        _, meta = validate_paginated(
            api_client.list_candidate_background_verifications(
                candidate["id"], VERIFIER
            )
        )
        assert meta["total_count"] == 0
        assert read_candidate(candidate)["vetting_status"] == "SCREENING"


class TestBackgroundFork:
    def test_06_a_flagged_result_moves_the_screen_and_not_the_candidate(self):
        """FLAGGED is the branch with no candidate-side promotion and no points.

        PRD §3.3: "A `result` of `FLAGGED` moves the screen to `FLAGGED` and
        stamps the same two fields, but leaves the candidate at
        `BACKGROUND_PENDING` pending adjudication — no candidate-side movement at
        all."

        PRD §3.3: "**Background points** are 20 when a `BackgroundVerification` of
        this candidate has reached `CLEARED`, 10 when the best status the
        candidate's screens have reached is `ADJUDICATED_PASS` — a waived flag is
        worth half of a clean result — and 0 otherwise."

        Design: Corner/state_machines/a_flagged_background_result_leaves_the_candidate_at_background_pending
        """
        scenario = setup_scenario(stage="background_ordered")
        assert read_candidate(scenario["candidate"])["vetting_status"] == (
            "BACKGROUND_PENDING"
        )

        data = record_background_result(scenario["background"], "FLAGGED")
        assert data["status"] == "FLAGGED"

        stored = read_candidate(scenario["candidate"])
        assert stored["vetting_status"] == "BACKGROUND_PENDING"
        assert stored["placement_ready_score"] == 74

    def test_07_a_cleared_screen_reports_the_state_error_not_the_version_one(self):
        """The supplied version is current, isolating the FLAGGED precondition.

        PRD §3.3: "The screen must be `FLAGGED`, or the request is refused with
        `ERR_BACKGROUND_NOT_FLAGGED` (HTTP 409); an already-adjudicated screen is
        refused with `ERR_ENTITY_TERMINAL`; and a stale
        `expected_candidate_version` is refused with
        `ERR_STALE_CANDIDATE_VERSION` (HTTP 412) before either of those checks
        would be reached."

        Design: Corner/state_machines/adjudicating_a_cleared_background_is_refused
        """
        scenario = setup_scenario(stage="background_recorded")
        current = read_candidate(scenario["candidate"])
        assert current["vetting_status"] == "CLEARED"

        validate_error(
            api_client.adjudicate_background_verification(
                scenario["background"]["id"],
                adjudicate_background_payload("PASS", current["version"]),
                PRINCIPAL,
            ),
            "ERR_BACKGROUND_NOT_FLAGGED",
            409,
        )

        assert read_background_verification(scenario["background"])["status"] == (
            "CLEARED"
        )
        assert read_candidate(scenario["candidate"])["vetting_status"] == "CLEARED"

    def test_08_an_adjudicated_fail_refuses_a_second_decision(self):
        """The second call carries a fresh version, so only the lock can fire.

        PRD §3.3: "`FAIL` moves the screen `FLAGGED → ADJUDICATED_FAIL` and fans a
        four-hop cascade: first the candidate's `vetting_status` moves
        `BACKGROUND_PENDING → REJECTED`; second, because the candidate is now
        rejected, every `TrialEngagement` of that candidate whose `status` is
        `SCHEDULED` or `IN_PROGRESS` moves to `CANCELLED` with `cancel_reason`
        `VETTING_FAILED`; third, because those trials have left the active set,
        every affected `RoleRequisition` sitting in `TRIALING` whose recomputed
        `active_trial_count` reaches 0 falls back to `SOURCING`; and fourth, the
        candidate's `availability_status` moves `ON_TRIAL → INACTIVE` with
        `cooling_off_until` cleared to null."

        PRD §2.9: "An action aimed at a row already sitting in a terminal state of
        the machine it would drive is refused with `ERR_ENTITY_TERMINAL` (HTTP
        409)."

        Design: Corner/state_machines/an_adjudicated_fail_is_terminal_and_refuses_a_second_decision
        """
        scenario = setup_scenario(stage="background_ordered")
        flagged = record_background_result(scenario["background"], "FLAGGED")
        candidate = read_candidate(scenario["candidate"])

        failed = adjudicate_background(flagged, "FAIL", candidate["version"])
        assert failed["status"] == "ADJUDICATED_FAIL"
        rejected = read_candidate(scenario["candidate"])
        assert rejected["vetting_status"] == "REJECTED"

        validate_error(
            api_client.adjudicate_background_verification(
                flagged["id"],
                adjudicate_background_payload("PASS", rejected["version"]),
                PRINCIPAL,
            ),
            "ERR_ENTITY_TERMINAL",
            409,
        )

        assert read_background_verification(flagged)["status"] == "ADJUDICATED_FAIL"
        assert read_candidate(scenario["candidate"])["vetting_status"] == "REJECTED"


class TestAvailabilityAxis:
    def test_09_release_is_admitted_on_the_cooling_off_date_itself(self):
        """The loop-back edge of the availability cycle, taken on its boundary.

        PRD §3.6: "Recording it moves the placement `ACTIVE →
        TERMINATED_NO_REMEDY`, stamps `separation_date`, and moves the candidate
        `PLACED → COOLING_OFF` with `cooling_off_until` set to the logical-clock
        date plus 30 days."

        PRD §3.3: "From `COOLING_OFF` this is admissible only when the
        logical-clock date is on or after `cooling_off_until`; an earlier date is
        refused with `ERR_COOLING_OFF_ACTIVE` (HTTP 409), so a clock landing
        exactly on `cooling_off_until` releases the candidate while one day earlier
        does not."

        PRD §3.3: "A successful release from `COOLING_OFF` moves
        `availability_status` `COOLING_OFF → AVAILABLE` and clears
        `cooling_off_until` to null."

        Design: Corner/state_machines/the_candidate_release_edge_reopens_availability_at_the_cooling_off_boundary
        """
        scenario = setup_scenario(stage="placement_active")
        set_clock(f"{SEPARATION_DATE}T00:00:00Z")
        terminate_placement(scenario["placement"], SEPARATION_DATE)

        cooling = read_candidate(scenario["candidate"])
        assert cooling["availability_status"] == "COOLING_OFF"
        assert cooling["cooling_off_until"] == COOLING_OFF_UNTIL

        set_clock(f"{COOLING_OFF_UNTIL}T00:00:00Z")
        data = validate_success(
            api_client.release_availability(
                scenario["candidate"]["id"], release_availability_payload(), RECORDER
            )
        )
        assert data["availability_status"] == "AVAILABLE"
        assert data["cooling_off_until"] is None
        assert data["vetting_status"] == "CLEARED"

        stored = read_candidate(scenario["candidate"])
        assert stored["availability_status"] == "AVAILABLE"
        assert stored["cooling_off_until"] is None


class TestNegotiationMachine:
    def test_10_a_counter_is_a_self_loop_that_flips_the_speaker(self):
        """The cyclic edge: round_no rises, one field is replaced, the term stays
        open.

        PRD §3.5: "A response carries a `response` of `COUNTER`, `ACCEPT` or
        `REJECT`, and may carry replacement values for `live_in`, `weekly_hours`,
        `days_off_per_week`, `private_quarters` and `imputed_accommodation_cents`,
        plus a `note`."

        PRD §3.5: "A `COUNTER` moves the term `PROPOSED → COUNTERED` on the first
        counter and then takes the `COUNTERED → COUNTERED` self-loop for each
        further round — the negotiation genuinely cycles between household and
        candidate until the cap is reached."

        PRD §3.5: "Each counter increments `round_no` by 1, overwrites `live_in`,
        `weekly_hours`, `days_off_per_week`, `private_quarters` and
        `imputed_accommodation_cents` with the supplied counter values, sets
        `last_responder_role` to `CLIENT` or `CANDIDATE` according to the
        responding role, and increments `AccommodationTerm.version`."

        Design: Corner/state_machines/a_counter_response_is_a_self_loop_that_flips_the_responder
        """
        scenario = setup_scenario(stage="term_proposed")
        assert scenario["term"]["status"] == "PROPOSED"
        assert scenario["term"]["round_no"] == 1
        assert scenario["term"]["last_responder_role"] == "AGENCY"

        data = respond_to_term(
            scenario["term"], scenario["client_headers"], "COUNTER", weekly_hours=42
        )
        assert data["status"] == "COUNTERED"
        assert data["round_no"] == 2
        assert data["last_responder_role"] == "CLIENT"
        assert data["weekly_hours"] == 42
        assert data["live_in"] is False
        assert data["days_off_per_week"] == 2
        assert data["private_quarters"] is False

        rows, meta = validate_paginated(
            api_client.list_accommodation_terms(
                CONSULTANT,
                {
                    "requisition_id": scenario["requisition"]["id"],
                    "status": "COUNTERED",
                },
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == scenario["term"]["id"]

    def test_11_accepting_a_live_in_term_writes_back_to_the_requisition(self):
        """Acceptance from COUNTERED aligns the parent search's live-in flag.

        PRD §3.5: "**Alternation:** the party implied by `X-User-Role` must differ
        from `last_responder_role`, and a party attempting to answer its own move
        is refused with `ERR_RESPONDER_MUST_ALTERNATE` (HTTP 409) — a household
        cannot counter its own counter, and after the agency's opening proposal
        either counterparty may speak first, but then the other must reply."

        PRD §3.5: "Acceptance from `COUNTERED` also aligns the parent search to
        the agreed package: `RoleRequisition.live_in_required` is set to the
        accepted term's `live_in`, while `RoleRequisition.schedule_pattern` is
        deliberately left untouched, because the pattern describes the shape of the
        role rather than the negotiated accommodation."

        Design: Corner/state_machines/accepting_a_live_in_term_aligns_the_requisition_flag
        """
        scenario = setup_scenario(
            stage="term_proposed",
            term={
                "live_in": True,
                "private_quarters": True,
                "imputed_accommodation_cents": 300_000,
            },
        )
        assert scenario["requisition"]["live_in_required"] is False

        countered = respond_to_term(
            scenario["term"], scenario["client_headers"], "COUNTER", weekly_hours=42
        )
        assert countered["status"] == "COUNTERED"

        data = respond_to_term(countered, scenario["candidate_headers"], "ACCEPT")
        assert data["status"] == "ACCEPTED"
        assert data["live_in"] is True

        requisition = read_requisition(scenario["requisition"])
        assert requisition["live_in_required"] is True
        assert requisition["status"] == "TRIALING"
        assert requisition["schedule_pattern"] == "FIVE_TWO"

    def test_12_an_accepted_term_is_closed_to_both_counterparties(self):
        """A further counter cannot reopen the negotiation at round 2.

        PRD §3.5: "A response aimed at a term already in `ACCEPTED`, `REJECTED` or
        `SUPERSEDED` is refused with `ERR_ENTITY_TERMINAL`."

        Design: Corner/state_machines/an_accepted_term_is_locked_against_a_further_response
        """
        scenario = setup_scenario(stage="term_accepted")
        assert scenario["term"]["status"] == "ACCEPTED"

        validate_error(
            api_client.respond_accommodation_term(
                scenario["term"]["id"],
                {"response": "COUNTER", "weekly_hours": 38, "note": "Reopening."},
                scenario["candidate_headers"],
            ),
            "ERR_ENTITY_TERMINAL",
            409,
        )

        after = read_term(scenario["term"])
        assert after["status"] == "ACCEPTED"
        assert after["round_no"] == 1
        assert after["weekly_hours"] == 40
