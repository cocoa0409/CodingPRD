"""Engagements and contract options: the exercise cascade, window bounds,
buffered overlap arithmetic, temporal-vs-overlap priority, and lifecycle gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    confirm_engagement,
    create_and_verify_event,
    create_hold_engagement,
    create_negotiating_opportunity,
    create_option,
    get_success_data,
    report_event,
    setup_artist_team,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["firm_admin_headers"]


class TestOptionExerciseCascade:
    def _setup_exercise_over_hold(self, api):
        """A NEGOTIATING opportunity with a linked HOLD engagement whose buffered
        window overlaps the engagement the option exercise will create."""
        sc = setup_artist_team(stage_name="Hold Act", primary_genre="rock")
        opp = create_negotiating_opportunity(
            sc, proposed_value_cents=5000000, fit_score=60,
            window=("2026-10-10T18:00:00Z", "2026-10-10T23:00:00Z"))
        hold = create_hold_engagement(
            sc, start="2026-10-10T18:00:00Z", end="2026-10-10T23:00:00Z",
            buffer_hours=24, guarantee_cents=5000000, counterparty_name="FestH",
            opportunity_id=opp["id"])
        option = create_option(
            sc, window=("2026-07-01T00:00:00Z", "2026-09-01T00:00:00Z"),
            engagement_window=("2026-10-11T12:00:00Z", "2026-10-11T22:00:00Z"),
            exercise_value_cents=8000000)
        return sc, opp, hold, option

    def test_exercise_creates_confirmed_engagement(self, api):
        """PRD: "Exercise creates that engagement with the option's engagement
        window, a 24-hour travel buffer, `guarantee_cents` equal to
        `exercise_value_cents`, the option's `income_type`, and `confirmed_at`
        from the clock; `exercised_engagement_id` records the result."

        Design: Difficulty/transitive_cascade/option_exercise_hold_release_cascade
        """
        sc, _opp, _hold, option = self._setup_exercise_over_hold(api)
        engagement = validate_success(api.exercise_option(option["id"],
                                                          sc["agent_headers"]), 201)
        assert engagement["status"] == "CONFIRMED", "The new engagement is born CONFIRMED"
        assert engagement["travel_buffer_hours"] == 24
        assert engagement["guarantee_cents"] == 8000000
        assert engagement["income_type"] == "TOURING"
        assert engagement["start_datetime"] == "2026-10-11T12:00:00Z"
        assert engagement["end_datetime"] == "2026-10-11T22:00:00Z"

        after = validate_success(api.get_option(option["id"], ADMIN))
        assert after["status"] == "EXERCISED"
        assert after["exercised_engagement_id"] == engagement["id"]

    def test_exercise_releases_hold_and_withdraws_opportunity(self, api):
        """PRD: "The same buffered overlap rule applies: a conflict fails the
        exercise wholesale with `ERR_ENGAGEMENT_OVERLAP`, and otherwise
        overlapping holds are released and their open opportunities withdrawn."
        PRD: "every overlapping `HOLD` engagement of the same artist is
        `RELEASED`, and a released hold whose `opportunity_id` points at an
        opportunity still in `RECEIVED`, `UNDER_EVALUATION`, or `NEGOTIATING`
        drives that opportunity to `WITHDRAWN`"

        Design: Difficulty/transitive_cascade/option_exercise_hold_release_cascade
        """
        sc, opp, hold, option = self._setup_exercise_over_hold(api)
        validate_success(api.exercise_option(option["id"], sc["agent_headers"]), 201)

        hold_after = validate_success(api.get_engagement(hold["id"], ADMIN))
        assert hold_after["status"] == "RELEASED", (
            "Buffered windows overlap: [10-09T18:00, 10-11T23:00] vs "
            "[10-10T12:00, 10-12T22:00]"
        )
        opp_after = validate_success(api.get_opportunity(opp["id"], ADMIN))
        assert opp_after["status"] == "WITHDRAWN", (
            "Driven by the hold's release, not by the exercise call directly"
        )


class TestOptionExerciseGates:
    def _setup_option(self, api, stage_name="Term Act"):
        sc = setup_artist_team(stage_name=stage_name, primary_genre="rock")
        option = create_option(
            sc, window=("2026-07-01T00:00:00Z", "2026-09-01T00:00:00Z"),
            engagement_window=("2027-03-01T20:00:00Z", "2027-03-01T23:00:00Z"),
            exercise_value_cents=500000)
        return sc, option

    def test_exercise_after_termination_rejected(self, api):
        """PRD: "The referenced agreement must still be `ACTIVE`
        (`ERR_AGREEMENT_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/option_exercise_gated_on_agreement_active
        """
        sc, option = self._setup_option(api)
        get_success_data(api.terminate_agreement(sc["agreement"]["id"],
                                                 "2026-06-15", ADMIN))

        resp = api.exercise_option(option["id"], sc["agent_headers"])
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

        after = validate_success(api.get_option(option["id"], ADMIN))
        assert after["status"] == "OPEN", "The failed exercise leaves the option OPEN"
        assert after["exercised_engagement_id"] is None
        _data, meta = validate_paginated(
            api.list_engagements(ADMIN, params={"artist_id": sc["artist"]["id"]}))
        assert meta["total_count"] == 0, "No engagement may be created"

    def test_exercise_while_agreement_active_succeeds(self, api):
        """PRD: "Exercising an option, an `Agent`-only action, is allowed only
        while the clock instant is at or after `exercise_window_start` and at or
        before `exercise_window_end` — both bounds inclusive"
        PRD: "The referenced agreement must still be `ACTIVE`
        (`ERR_AGREEMENT_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/option_exercise_gated_on_agreement_active
        """
        sc, option = self._setup_option(api, "Term Act Control")
        engagement = validate_success(api.exercise_option(option["id"],
                                                          sc["agent_headers"]), 201)
        assert engagement["status"] == "CONFIRMED"
        after = validate_success(api.get_option(option["id"], ADMIN))
        assert after["status"] == "EXERCISED"

    def test_exercise_at_window_end_succeeds(self, api):
        """PRD: "Exercising an option, an `Agent`-only action, is allowed only
        while the clock instant is at or after `exercise_window_start` and at or
        before `exercise_window_end` — both bounds inclusive; violations are
        rejected with `ERR_OPTION_WINDOW_VIOLATION`."
        PRD: "the clock sweep lapses `OPEN` options once the clock passes
        `exercise_window_end`, moving them to `LAPSED`."

        Design: Difficulty/boundary_precision_check/option_exercise_window_inclusive_bounds
        """
        sc = setup_artist_team(stage_name="Bound Act")
        option = create_option(
            sc, window=("2026-07-01T00:00:00Z", "2026-09-01T00:00:00Z"),
            engagement_window=("2027-03-01T20:00:00Z", "2027-03-01T23:00:00Z"))
        advance_clock("2026-09-01T00:00:00Z")
        still_open = validate_success(api.get_option(option["id"], ADMIN))
        assert still_open["status"] == "OPEN", (
            "The sweep only lapses options PAST their window end, never at it"
        )

        engagement = validate_success(api.exercise_option(option["id"],
                                                          sc["agent_headers"]), 201)
        assert engagement["status"] == "CONFIRMED"
        after = validate_success(api.get_option(option["id"], ADMIN))
        assert after["status"] == "EXERCISED", (
            "Exercise at clock == exercise_window_end succeeds (inclusive bound)"
        )

    def test_exercise_before_window_start_rejected(self, api):
        """PRD: "Exercising an option, an `Agent`-only action, is allowed only
        while the clock instant is at or after `exercise_window_start` and at or
        before `exercise_window_end` — both bounds inclusive; violations are
        rejected with `ERR_OPTION_WINDOW_VIOLATION`."

        Design: Difficulty/boundary_precision_check/option_exercise_window_inclusive_bounds
        """
        sc = setup_artist_team(stage_name="Bound Act 2")
        option = create_option(
            sc, window=("2026-09-15T00:00:00Z", "2026-10-15T00:00:00Z"),
            engagement_window=("2027-04-01T10:00:00Z", "2027-04-01T18:00:00Z"),
            option_type="RECORDING_CYCLE", income_type="RECORDING",
            exercise_value_cents=600000)

        resp = api.exercise_option(option["id"], sc["agent_headers"])
        validate_error(resp, ApiErrorId.ERR_OPTION_WINDOW_VIOLATION)

        after = validate_success(api.get_option(option["id"], ADMIN))
        assert after["status"] == "OPEN", "The option remains OPEN"
        _data, meta = validate_paginated(
            api.list_engagements(ADMIN, params={"artist_id": sc["artist"]["id"]}))
        assert meta["total_count"] == 0

    def test_terminal_option_waived_rejects_exercise(self, api):
        """PRD: "An option can instead be given up — waived to `WAIVED` by the
        `Artist` or a `FirmAdmin`"
        PRD endpoint table: exercise is the `OPEN → EXERCISED` transition, and
        "State-machine preconditions — the target is in a state from which the
        requested transition exists (`ERR_INVALID_STATE`"

        Design: Corner/state_machines/terminal_option_waived_rejects_exercise
        """
        sc = setup_artist_team(stage_name="Waive Act", primary_genre="rock")
        option = create_option(sc)
        validate_success(api.waive_option(option["id"], sc["artist_headers"]))

        resp = api.exercise_option(option["id"], sc["agent_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_option(option["id"], ADMIN))
        assert after["status"] == "WAIVED"
        _data, meta = validate_paginated(
            api.list_engagements(ADMIN, params={"artist_id": sc["artist"]["id"]}))
        assert meta["total_count"] == 0, "No engagement may be created"


class TestEngagementOverlapArithmetic:
    def _setup_overlap_artist(self, api, stage_name="Edge Act"):
        """E1 CONFIRMED 2026-09-10T18:00..23:00 with buffer 24h, so its effective
        window is [2026-09-09T18:00, 2026-09-11T23:00]."""
        sc = setup_artist_team(stage_name=stage_name, primary_genre="rock")
        eng1 = create_hold_engagement(
            sc, start="2026-09-10T18:00:00Z", end="2026-09-10T23:00:00Z",
            buffer_hours=24, counterparty_name="Venue A")
        confirm_engagement(sc, eng1["id"])
        return sc, eng1

    def test_touching_buffered_edge_confirms(self, api):
        """PRD: "rejects the confirmation with `ERR_ENGAGEMENT_OVERLAP` when
        another `CONFIRMED` engagement of the same artist has a buffered window
        that strictly intersects it"
        PRD: "windows that merely touch at the buffered edge do not conflict."

        Design: Difficulty/resource_temporal_overlap/engagement_buffered_window_strict_touch
        """
        sc, eng1 = self._setup_overlap_artist(api)
        eng2 = create_hold_engagement(
            sc, start="2026-09-11T23:00:00Z", end="2026-09-12T02:00:00Z",
            buffer_hours=0, counterparty_name="Venue B")

        confirmed = validate_success(api.confirm_engagement(eng2["id"],
                                                            sc["agent_headers"]))
        assert confirmed["status"] == "CONFIRMED", (
            "Effective start 2026-09-11T23:00 merely touches E1's effective end"
        )
        first = validate_success(api.get_engagement(eng1["id"], ADMIN))
        assert first["status"] == "CONFIRMED"

    def test_one_hour_inside_buffer_rejected(self, api):
        """PRD: "rejects the confirmation with `ERR_ENGAGEMENT_OVERLAP` when
        another `CONFIRMED` engagement of the same artist has a buffered window
        that strictly intersects it — the candidate's buffered start falls before
        the existing one's buffered end, and the existing one's buffered start
        falls before the candidate's buffered end"

        Design: Difficulty/resource_temporal_overlap/engagement_buffered_window_strict_touch
        """
        sc, _eng1 = self._setup_overlap_artist(api, "Edge Act 2")
        eng3 = create_hold_engagement(
            sc, start="2026-09-11T22:00:00Z", end="2026-09-12T01:00:00Z",
            buffer_hours=0, counterparty_name="Venue C")

        resp = api.confirm_engagement(eng3["id"], sc["agent_headers"])
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_OVERLAP)

        after = validate_success(api.get_engagement(eng3["id"], ADMIN))
        assert after["status"] == "HOLD"


class TestConfirmValidationPriority:
    def test_past_window_and_overlap_returns_window_past(self, api):
        """PRD: "When a request violates several rules at once, the server reports
        the earliest failure in a fixed evaluation order:"
        PRD: "Temporal guards — option exercise windows, offer expiry, engagement
        window guards, dispute and audit windows, statement periods in the future
        (`ERR_OPTION_WINDOW_VIOLATION`, `ERR_OFFER_EXPIRED`,
        `ERR_ENGAGEMENT_WINDOW_PAST`, `ERR_ENGAGEMENT_NOT_ENDED`,
        `ERR_DISPUTE_WINDOW_CLOSED`, `ERR_AUDIT_WINDOW_CLOSED`,
        `ERR_STATEMENT_PERIOD_FUTURE`)."
        PRD: "Uniqueness and overlap — rate-schedule windows, buffered engagement
        windows, statement periods, one active dispute per statement, one
        non-closed audit per statement (`ERR_RATE_SCHEDULE_OVERLAP`,
        `ERR_ENGAGEMENT_OVERLAP`, `ERR_STATEMENT_PERIOD_OVERLAP`,
        `ERR_DISPUTE_ALREADY_ACTIVE`, `ERR_AUDIT_ALREADY_ACTIVE`)."

        Design: Difficulty/priority_pair_validation_conflict/engagement_confirm_temporal_beats_overlap
        """
        sc = setup_artist_team(stage_name="Clash Act", primary_genre="rock")
        eng1 = create_hold_engagement(
            sc, start="2026-09-10T18:00:00Z", end="2026-09-10T23:00:00Z",
            buffer_hours=0, counterparty_name="Venue 1")
        confirm_engagement(sc, eng1["id"])  # confirmed while the window is future
        eng2 = create_hold_engagement(
            sc, start="2026-09-10T20:00:00Z", end="2026-09-11T02:00:00Z",
            buffer_hours=0, counterparty_name="Venue 2")
        advance_clock("2026-10-01T00:00:00Z")

        # Dual failure: window already past (temporal, priority 11) AND overlap
        # with CONFIRMED E1 (constraint, priority 13).
        resp = api.confirm_engagement(eng2["id"], sc["agent_headers"])
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_WINDOW_PAST)

        after = validate_success(api.get_engagement(eng2["id"], ADMIN))
        assert after["status"] == "HOLD", "The rejected confirm leaves the hold unchanged"

    def test_overlap_alone_returns_engagement_overlap(self, api):
        """PRD: "rejects the confirmation with `ERR_ENGAGEMENT_OVERLAP` when
        another `CONFIRMED` engagement of the same artist has a buffered window
        that strictly intersects it"

        Design: Difficulty/priority_pair_validation_conflict/engagement_confirm_temporal_beats_overlap
        """
        sc = setup_artist_team(stage_name="Clash Act Control", primary_genre="rock")
        eng1 = create_hold_engagement(
            sc, start="2026-09-10T18:00:00Z", end="2026-09-10T23:00:00Z",
            buffer_hours=0, counterparty_name="Venue 1")
        confirm_engagement(sc, eng1["id"])
        eng2 = create_hold_engagement(
            sc, start="2026-09-10T20:00:00Z", end="2026-09-11T02:00:00Z",
            buffer_hours=0, counterparty_name="Venue 2")

        # Control at the default clock: the window is still future, so only the
        # overlap violation exists.
        resp = api.confirm_engagement(eng2["id"], sc["agent_headers"])
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_OVERLAP)

        after = validate_success(api.get_engagement(eng2["id"], ADMIN))
        assert after["status"] == "HOLD"


class TestEngagementLifecycleGates:
    def test_complete_engagement_before_end_rejected(self, api):
        """PRD: "After the engagement ends — the clock at or past `end_datetime`,
        with earlier attempts rejected as `ERR_ENGAGEMENT_NOT_ENDED` — an `Agent`
        or `BusinessManager` marks it `COMPLETED`."

        Design: Corner/validations/complete_engagement_before_end_rejected
        """
        sc = setup_artist_team(stage_name="Busy Act", primary_genre="rock")
        eng = create_hold_engagement(sc)
        confirm_engagement(sc, eng["id"])

        resp = api.complete_engagement(eng["id"], sc["agent_headers"])
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_ENDED)

        advance_clock("2026-09-11T00:00:00Z")
        completed = validate_success(api.complete_engagement(eng["id"],
                                                             sc["agent_headers"]))
        assert completed["status"] == "COMPLETED"

    def test_cancel_engagement_with_verified_income_rejected(self, api):
        """PRD: "Cancellation is available from `HOLD` or `CONFIRMED` but is
        blocked with `ERR_ENGAGEMENT_HAS_INCOME` when a linked income event has
        already reached `VERIFIED`, `SETTLED`, or `POSTED`."

        Design: Corner/validations/cancel_engagement_with_verified_income_rejected
        """
        sc = setup_artist_team(stage_name="Lock Act", primary_genre="rock")
        eng = create_hold_engagement(sc, guarantee_cents=200000)
        confirm_engagement(sc, eng["id"])
        event = create_and_verify_event(sc, gross_amount_cents=200000,
                                        recognition_date="2026-03-10",
                                        source_name="Venue",
                                        linked_engagement_id=eng["id"])
        assert event["status"] == "VERIFIED"

        resp = api.cancel_engagement(eng["id"], sc["agent_headers"])
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_HAS_INCOME)

        after = validate_success(api.get_engagement(eng["id"], ADMIN))
        assert after["status"] == "CONFIRMED"
