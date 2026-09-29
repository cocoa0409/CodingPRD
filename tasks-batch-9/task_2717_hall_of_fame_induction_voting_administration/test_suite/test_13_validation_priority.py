"""Which rule speaks first when a single call breaks several of them at once."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    CURATOR_HEADERS,
    build_election_world,
    cast_vote,
    create_audit_decision_payload,
    create_candidacy_payload,
    create_ceremony_payload,
    create_screening_decision_payload,
    create_travel_grant_payload,
    create_exhibit_installation_payload,
    create_vote_submission_payload,
    elector_headers,
    induction_of,
    make_elector_headers,
    read_ballot,
    read_candidacy,
    read_candidate,
    read_case,
    read_cycle,
    read_elector,
    read_induction,
    read_slot,
    screening_headers,
    set_clock,
    setup_artifact_intake,
    setup_cycle,
    setup_elector,
    setup_exhibit_case,
    slot_of,
    validate_error,
    validate_paginated,
    validate_success,
)

STRAY_SLOT_ID = "11111111-1111-1111-1111-111111111111"
COACH_UNDERQUALIFIED = {
    "full_name": "Assistant Coach",
    "category": "COACH",
    "retirement_year": 2025,
    "career_seasons": 3,
    "career_metric_value": 100,
}


class TestAuditDecisionOnAnExpiredBallot:
    """An expired round is never tabulated and never audited."""

    @pytest.fixture
    def world(self, api):
        """A ballot closed after its `closes_at`, so it landed in EXPIRED."""
        world = build_election_world(
            api, stage="ballot_open", elector_count=2, candidate_count=1
        )
        cast_vote(world, (0, [0]))
        set_clock(api, "2026-08-21T00:00:00Z")
        validate_success(api.close_ballot(world["ballot"]["id"], ADMIN_HEADERS), 200)
        return world

    def test_the_auditor_is_told_the_round_is_void(self, api, world):
        """A ballot whose `voting_status` is `EXPIRED` is never tabulated and never audited under any
        circumstances; both operations on such a ballot are refused with `ERR_BALLOT_EXPIRED`
        (HTTP 409).

        Design: Corner/validations/audit_decision_on_an_expired_ballot_reports_ballot_expired
        """
        validate_error(
            api.create_audit_decision(
                world["ballot"]["id"],
                create_audit_decision_payload("CERTIFY", audit_note="Reviewed the void round"),
                AUDITOR_HEADERS,
            ),
            "ERR_BALLOT_EXPIRED",
            409,
        )

    def test_the_void_round_leaves_the_cycle_and_the_tally_where_they_were(self, api, world):
        """If the logical clock has reached or passed `closes_at`, `voting_status` moves `OPEN` →
        `EXPIRED` instead: the round is void, the ballot is permanently untabulatable, no vote cast on
        it is ever counted, and the cycle must construct a replacement ballot for the same
        `round_number`.

        Design: Corner/validations/audit_decision_on_an_expired_ballot_reports_ballot_expired
        """
        api.create_audit_decision(
            world["ballot"]["id"], create_audit_decision_payload("CERTIFY"), AUDITOR_HEADERS
        )
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["voting_status"] == "EXPIRED"
        assert ballot["tally_status"] == "NOT_TALLIED"
        assert read_cycle(api, world["cycle"]["id"])["status"] == "BALLOTING"


class TestWindowConflictOutranksCapacity:
    """One installation breaks the window rule and the capacity rule together."""

    @pytest.fixture
    def world(self, api):
        """A three-artifact case already fully occupied by one overlapping window."""
        world = build_election_world(
            api,
            stage="certified",
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
        )
        world["induction"] = induction_of(world, 0)
        setup_artifact_intake(api, world["induction"]["id"], artifact_count=3)
        world["case"] = setup_exhibit_case(
            api, case_code="HALLC", capacity_artifacts=3, changeover_buffer_days=0
        )
        world["installation"] = validate_success(
            api.create_exhibit_installation(
                create_exhibit_installation_payload(
                    world["induction"]["id"],
                    world["case"]["id"],
                    display_starts_on="2026-09-01T00:00:00Z",
                    display_ends_on="2026-09-10T00:00:00Z",
                    artifact_count=3,
                ),
                CURATOR_HEADERS,
            ),
            201,
        )
        return world

    def test_the_overlapping_window_is_reported_and_not_the_capacity(self, api, world):
        """Capacity is checked only after the window survives.

        Design: Corner/validations/case_window_conflict_outranks_case_capacity_on_the_same_installation
        """
        validate_error(
            api.create_exhibit_installation(
                create_exhibit_installation_payload(
                    world["induction"]["id"],
                    world["case"]["id"],
                    display_starts_on="2026-09-05T00:00:00Z",
                    display_ends_on="2026-09-15T00:00:00Z",
                    artifact_count=3,
                ),
                CURATOR_HEADERS,
            ),
            "ERR_CASE_WINDOW_CONFLICT",
            409,
        )

    def test_the_refusal_leaves_the_case_and_the_first_window_untouched(self, api, world):
        """The case's current `artifacts_installed` plus the new `artifact_count` must not exceed the
        case's `capacity_artifacts`, and an over-subscription is refused with
        `ERR_CASE_CAPACITY_EXCEEDED` (HTTP 409).

        Design: Corner/validations/case_window_conflict_outranks_case_capacity_on_the_same_installation
        """
        api.create_exhibit_installation(
            create_exhibit_installation_payload(
                world["induction"]["id"],
                world["case"]["id"],
                display_starts_on="2026-09-05T00:00:00Z",
                display_ends_on="2026-09-15T00:00:00Z",
                artifact_count=3,
            ),
            CURATOR_HEADERS,
        )
        assert read_case(api, world["case"]["id"])["artifacts_installed"] == 3
        assert read_induction(api, world["induction"]["id"])["exhibit_status"] == "INSTALLED"
        rows, meta = validate_paginated(
            api.list_exhibit_installations(
                CURATOR_HEADERS, {"exhibit_case_id": world["case"]["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "INSTALLED"


class TestHoldCeremonyGuardOrder:
    """The date is checked before the readiness of the class."""

    @pytest.fixture
    def world(self, api):
        """A ceremony-planned cycle whose only induction is ready in no dimension."""
        world = build_election_world(
            api,
            stage="ceremony",
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
        )
        world["induction"] = induction_of(world, 0)
        return world

    def test_an_early_ceremony_reports_the_date_first(self, api, world):
        """The final act requires the cycle to be in `CEREMONY_PLANNED`, requires the logical clock to
        have reached or passed the stored `ceremony_date` — an early ceremony is refused with
        `ERR_CEREMONY_DATE_NOT_REACHED` (HTTP 409).

        Design: Corner/validations/hold_ceremony_before_the_ceremony_date_reports_date_not_reached
        """
        validate_error(
            api.hold_ceremony(world["cycle"]["id"], ADMIN_HEADERS),
            "ERR_CEREMONY_DATE_NOT_REACHED",
            409,
        )
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["status"] == "CEREMONY_PLANNED"
        assert cycle["induction_count"] == 1
        assert cycle["ceremony_ready_count"] == 0

    def test_the_early_refusal_does_not_enshrine_anyone(self, api, world):
        """On success the cycle moves `CEREMONY_PLANNED` → `CLOSED` and every induction of the cycle
        is driven `ANNOUNCED` → `ENSHRINED`, which freezes all three of its dimensions: no further
        travel, artifact or exhibit mutation is accepted on an enshrined induction.

        Design: Corner/validations/hold_ceremony_before_the_ceremony_date_reports_date_not_reached
        """
        api.hold_ceremony(world["cycle"]["id"], ADMIN_HEADERS)
        induction = read_induction(api, world["induction"]["id"])
        assert induction["status"] == "ANNOUNCED"
        assert induction["travel_status"] == "PENDING"
        assert induction["artifact_status"] == "AWAITED"
        assert induction["exhibit_status"] == "NOT_PLANNED"

    def test_once_the_date_passes_the_readiness_shortfall_is_reported(self, api, world):
        """And requires the cycle's `ceremony_ready_count` to equal its `induction_count` exactly, so
        that no inductee is left behind; a shortfall is refused with `ERR_INDUCTIONS_NOT_READY`
        (HTTP 409).

        Design: Corner/validations/hold_ceremony_after_the_date_with_an_unready_induction_reports_not_ready
        """
        set_clock(api, "2026-11-20T00:00:00Z")
        validate_error(
            api.hold_ceremony(world["cycle"]["id"], ADMIN_HEADERS),
            "ERR_INDUCTIONS_NOT_READY",
            409,
        )
        assert read_cycle(api, world["cycle"]["id"])["status"] == "CEREMONY_PLANNED"
        induction = read_induction(api, world["induction"]["id"])
        assert induction["ceremony_ready"] is False
        assert induction["status"] == "ANNOUNCED"

    def test_the_two_guards_report_two_different_codes(self, api, world):
        """An induction's `ceremony_ready` flag is re-derived from scratch on every mutation of any of
        its three dimensions, and it is true exactly when the travel dimension is settled *and* the
        display obligation is discharged.

        Design: Corner/validations/hold_ceremony_after_the_date_with_an_unready_induction_reports_not_ready
        """
        validate_error(
            api.hold_ceremony(world["cycle"]["id"], ADMIN_HEADERS),
            "ERR_CEREMONY_DATE_NOT_REACHED",
            409,
        )
        set_clock(api, "2026-11-20T00:00:00Z")
        validate_error(
            api.hold_ceremony(world["cycle"]["id"], ADMIN_HEADERS),
            "ERR_INDUCTIONS_NOT_READY",
            409,
        )


class TestNominationByAnUncredentialedElector:
    """The nominator's own standing decides a candidacy write."""

    @pytest.fixture
    def world(self, api):
        """An open cycle whose third elector was created but never credentialed."""
        world = build_election_world(
            api, stage="nominations_open", elector_count=2, candidate_count=1
        )
        world["provisional"] = setup_elector(
            api, world["bloc"]["id"], credential=False, full_name="Elector Three"
        )
        return world

    def test_a_provisional_nominator_may_not_file(self, api, world):
        """First, the elector the operation depends on must be `CREDENTIALED`; a `PROVISIONAL`,
        `SUSPENDED` or `LAPSED` elector may neither nominate nor vote, and the attempt is refused with
        `ERR_ELECTOR_NOT_CREDENTIALED` (HTTP 403).

        Design: Corner/validations/nomination_by_an_uncredentialed_elector_rejected
        """
        validate_error(
            api.create_candidacy(
                create_candidacy_payload(
                    world["cycle"]["id"],
                    world["candidates"][0]["id"],
                    world["provisional"]["id"],
                ),
                make_elector_headers(world["provisional"]["id"]),
            ),
            "ERR_ELECTOR_NOT_CREDENTIALED",
            403,
        )
        assert read_elector(api, world["provisional"]["id"])["status"] == "PROVISIONAL"

    def test_the_same_body_from_a_credentialed_nominator_is_accepted(self, api, world):
        """`PROVISIONAL` electors may neither nominate nor vote.

        Design: Corner/validations/nomination_by_an_uncredentialed_elector_rejected
        """
        api.create_candidacy(
            create_candidacy_payload(
                world["cycle"]["id"], world["candidates"][0]["id"], world["provisional"]["id"]
            ),
            make_elector_headers(world["provisional"]["id"]),
        )
        assert read_cycle(api, world["cycle"]["id"])["nomination_count"] == 0
        validate_success(
            api.create_candidacy(
                create_candidacy_payload(
                    world["cycle"]["id"],
                    world["candidates"][0]["id"],
                    world["electors"][0]["id"],
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert read_cycle(api, world["cycle"]["id"])["nomination_count"] == 1


class TestVoteAfterTheWindowCloses:
    """An OPEN ballot is not an open window once the clock moves on."""

    @pytest.fixture
    def world(self, api):
        """An OPEN ballot whose `closes_at` the clock has already passed."""
        world = build_election_world(
            api, stage="ballot_open", elector_count=2, candidate_count=1
        )
        set_clock(api, "2026-08-25T00:00:00Z")
        return world

    def test_the_window_is_measured_against_the_clock(self, api, world):
        """The ballot must be `OPEN`, otherwise the submission is refused with
        `ERR_INVALID_BALLOT_STATE`, and the logical clock must be strictly before the ballot's
        `closes_at`; a submission at or after that instant is refused with
        `ERR_VOTING_WINDOW_CLOSED` (HTTP 409).

        Design: Corner/validations/vote_cast_after_the_voting_window_closes_rejected
        """
        validate_error(
            api.create_vote_submission(
                create_vote_submission_payload(
                    world["ballot"]["id"],
                    [slot_of(world, 0)["id"]],
                    world["ballot"]["version"],
                ),
                elector_headers(world, 0),
            ),
            "ERR_VOTING_WINDOW_CLOSED",
            409,
        )

    def test_the_refusal_records_no_submission_and_no_transition(self, api, world):
        """The two dimensions are genuinely independent: `voting_status` runs `DRAFT` → `OPEN` →
        `CLOSED` (or `OPEN` → `EXPIRED`, which is terminal).

        Design: Corner/validations/vote_cast_after_the_voting_window_closes_rejected
        """
        api.create_vote_submission(
            create_vote_submission_payload(
                world["ballot"]["id"], [slot_of(world, 0)["id"]], world["ballot"]["version"]
            ),
            elector_headers(world, 0),
        )
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["voting_status"] == "OPEN"
        assert ballot["ballots_cast"] == 0
        _, meta = validate_paginated(
            api.list_vote_submissions(
                AUDITOR_HEADERS, {"ballot_id": world["ballot"]["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 0


class TestCeremonyDateInThePast:
    """The ceremony leg of the temporal rule refuses a date already gone."""

    @pytest.fixture
    def world(self, api):
        """A certified cycle with one induction and no ceremony planned yet."""
        return build_election_world(
            api,
            stage="certified",
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
        )

    def test_a_date_before_the_clock_is_refused(self, api, world):
        """The `ceremony_date` must be strictly later than the logical clock's current instant; a
        ceremony scheduled in the past or exactly now is refused with `ERR_INVALID_TIME_WINDOW`
        (HTTP 422).

        Design: Corner/validations/ceremony_date_in_the_past_rejected
        """
        validate_error(
            api.patch_ceremony(
                world["cycle"]["id"],
                create_ceremony_payload(ceremony_date="2026-07-01T00:00:00Z"),
                ADMIN_HEADERS,
            ),
            "ERR_INVALID_TIME_WINDOW",
            422,
        )

    def test_nothing_of_the_refused_plan_is_stored(self, api, world):
        """The transition stores all four values, moves the cycle `CERTIFIED` → `CEREMONY_PLANNED`,
        recomputes `austerity_tier` from the ratio of `travel_committed_cents` to
        `travel_budget_cents`, and increments the cycle's `version` by 1.

        Design: Corner/validations/ceremony_date_in_the_past_rejected
        """
        api.patch_ceremony(
            world["cycle"]["id"],
            create_ceremony_payload(ceremony_date="2026-07-01T00:00:00Z"),
            ADMIN_HEADERS,
        )
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["status"] == "CERTIFIED"
        assert cycle["ceremony_date"] is None
        assert cycle["ceremony_venue"] is None


class TestBlocParticipationShortfall:
    """Individually valid ballots can still fail collectively."""

    @pytest.fixture
    def world(self, api):
        """A tallied ballot carrying one submission against three filled seats."""
        return build_election_world(
            api, stage="tallied", elector_count=3, candidate_count=1, votes=[(2, [0])]
        )

    def test_one_vote_in_three_seats_blocks_the_certification(self, api, world):
        """A single under-participating seated bloc blocks the whole certification with
        `ERR_BLOC_QUORUM_NOT_MET` (HTTP 409); blocs with no seated electors are ignored.

        Design: Corner/validations/bloc_participation_shortfall_blocks_the_auditor_certification
        """
        validate_error(
            api.create_audit_decision(
                world["ballot"]["id"],
                create_audit_decision_payload("CERTIFY", audit_note="Turnout review"),
                AUDITOR_HEADERS,
            ),
            "ERR_BLOC_QUORUM_NOT_MET",
            409,
        )

    def test_the_draft_tally_survives_for_a_later_run(self, api, world):
        """For every voter bloc whose `seats_filled` is at least 1, the number of counted submissions
        on this ballot cast by electors of that bloc, divided by that bloc's `seats_filled`, must be
        greater than or equal to the bloc's `min_participation_pct`.

        Design: Corner/validations/bloc_participation_shortfall_blocks_the_auditor_certification
        """
        api.create_audit_decision(
            world["ballot"]["id"], create_audit_decision_payload("CERTIFY"), AUDITOR_HEADERS
        )
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["tally_status"] == "PENDING_AUDIT"
        assert ballot["ballots_cast"] == 1
        assert ballot["threshold_votes_provisional"] == 1
        assert read_slot(api, slot_of(world, 0)["id"])["status"] == "LISTED"


class TestCaseCapacityIsAnAggregate:
    """Two lawful windows can still overfill one case between them."""

    @pytest.fixture
    def world(self, api):
        """A three-artifact case holding one two-artifact window ending 2026-09-10."""
        world = build_election_world(
            api,
            stage="certified",
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
        )
        world["induction"] = induction_of(world, 0)
        setup_artifact_intake(api, world["induction"]["id"], artifact_count=4)
        world["case"] = setup_exhibit_case(
            api, case_code="HALLD", capacity_artifacts=3, changeover_buffer_days=0
        )
        world["installation"] = validate_success(
            api.create_exhibit_installation(
                create_exhibit_installation_payload(
                    world["induction"]["id"],
                    world["case"]["id"],
                    display_starts_on="2026-09-01T00:00:00Z",
                    display_ends_on="2026-09-10T00:00:00Z",
                    artifact_count=2,
                ),
                CURATOR_HEADERS,
            ),
            201,
        )
        return world

    def _adjacent(self, api, world, count):
        return api.create_exhibit_installation(
            create_exhibit_installation_payload(
                world["induction"]["id"],
                world["case"]["id"],
                display_starts_on="2026-09-10T00:00:00Z",
                display_ends_on="2026-09-20T00:00:00Z",
                artifact_count=count,
            ),
            CURATOR_HEADERS,
        )

    def test_the_sum_of_two_lawful_windows_is_refused(self, api, world):
        """The case's current `artifacts_installed` plus the new `artifact_count` must not exceed the
        case's `capacity_artifacts`, and an over-subscription is refused with
        `ERR_CASE_CAPACITY_EXCEEDED` (HTTP 409).

        Design: Corner/validations/two_individually_legal_installations_exceed_the_case_capacity
        """
        validate_error(self._adjacent(api, world, 2), "ERR_CASE_CAPACITY_EXCEEDED", 409)
        assert read_case(api, world["case"]["id"])["artifacts_installed"] == 2
        _, meta = validate_paginated(
            api.list_exhibit_installations(
                CURATOR_HEADERS, {"exhibit_case_id": world["case"]["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 1

    def test_a_window_landing_exactly_on_the_ceiling_is_accepted(self, api, world):
        """If the other installation belongs to the **same induction**, plain half-open intersection
        applies: the conflict is real when the new start is strictly before the other's end and the
        other's start is strictly before the new end, so back-to-back windows for one inductee are
        legal.

        Design: Corner/validations/installation_landing_exactly_on_the_case_capacity_ceiling_succeeds
        """
        installation = validate_success(self._adjacent(api, world, 1), 201)
        assert installation["status"] == "INSTALLED"
        assert installation["artifact_count"] == 1
        assert read_case(api, world["case"]["id"])["artifacts_installed"] == 3

    def test_filling_the_case_does_not_make_the_ceremony_ready(self, api, world):
        """That transition requires the induction's `artifact_status` to be `RECEIVED`, recomputes
        `ceremony_ready`, and increments the cycle's `ceremony_ready_count` by 1 when readiness flips
        to true.

        Design: Corner/validations/installation_landing_exactly_on_the_case_capacity_ceiling_succeeds
        """
        validate_success(self._adjacent(api, world, 1), 201)
        assert read_induction(api, world["induction"]["id"])["exhibit_status"] == "INSTALLED"
        assert read_cycle(api, world["cycle"]["id"])["ceremony_ready_count"] == 0


class TestConditionalNominationGates:
    """Two gates that fire only for the pathway that declares them."""

    @pytest.fixture
    def world(self, api):
        """An open cycle carrying modern, special and posthumous rules for one living player."""
        return build_election_world(
            api,
            stage="nominations_open",
            rules=[{}, {"pathway": "SPECIAL"}, {"pathway": "POSTHUMOUS"}],
            elector_count=1,
            candidate_count=1,
        )

    def _file(self, api, world, **overrides):
        return api.create_candidacy(
            create_candidacy_payload(
                world["cycle"]["id"],
                world["candidates"][0]["id"],
                world["electors"][0]["id"],
                **overrides,
            ),
            ADMIN_HEADERS,
        )

    def test_a_special_nomination_without_a_justification_is_refused(self, api, world):
        """A `SPECIAL` nomination must supply a non-empty `justification`, and one that omits it or
        sends an empty string is refused with `ERR_JUSTIFICATION_REQUIRED` (HTTP 422).

        Design: Corner/validations/special_pathway_nomination_without_justification_rejected
        """
        validate_error(
            self._file(api, world, pathway="SPECIAL"), "ERR_JUSTIFICATION_REQUIRED", 422
        )
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["special_election_used"] == 0
        assert cycle["nomination_count"] == 0

    def test_the_identical_body_on_the_modern_pathway_is_accepted(self, api, world):
        """The special election carries two further gates that apply to no other pathway.

        Design: Corner/validations/special_pathway_nomination_without_justification_rejected
        """
        validate_error(
            self._file(api, world, pathway="SPECIAL"), "ERR_JUSTIFICATION_REQUIRED", 422
        )
        candidacy = validate_success(self._file(api, world, pathway="MODERN"), 201)
        assert candidacy["pathway"] == "MODERN"
        assert read_cycle(api, world["cycle"]["id"])["nomination_count"] == 1

    def test_a_posthumous_nomination_of_a_living_candidate_is_refused(self, api, world):
        """For a `POSTHUMOUS` nomination the candidate must actually be deceased: `is_deceased` must
        be true and `death_year` must not be null, otherwise the nomination is refused with
        `ERR_POSTHUMOUS_PATHWAY_REQUIRES_DECEASED` (HTTP 422).

        Design: Corner/validations/posthumous_pathway_for_a_living_candidate_rejected
        """
        validate_error(
            self._file(api, world, pathway="POSTHUMOUS"),
            "ERR_POSTHUMOUS_PATHWAY_REQUIRES_DECEASED",
            422,
        )
        assert read_candidate(api, world["candidates"][0]["id"])["is_deceased"] is False
        _, meta = validate_paginated(
            api.list_candidacies(
                ADMIN_HEADERS, {"candidate_id": world["candidates"][0]["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 0


class TestRuleLookupPrecedesEveryOtherCheck:
    """Nothing downstream can be computed from a rule that was never found."""

    @pytest.fixture
    def world(self, api):
        """An open cycle whose only rule is for players, plus an unqualified coach."""
        return build_election_world(
            api,
            stage="nominations_open",
            elector_count=1,
            candidate_specs=[COACH_UNDERQUALIFIED],
        )

    def test_the_missing_rule_is_reported_and_not_the_shortfalls(self, api, world):
        """The assessment first locates the single eligibility rule whose `category` equals the
        candidate's `category` and whose `pathway` equals the candidacy's claimed `pathway`. If no
        such rule has been published, the nomination is refused with
        `ERR_ELIGIBILITY_RULE_NOT_FOUND` (HTTP 404).

        Design: Corner/validations/eligibility_rule_lookup_precedes_every_career_and_waiting_check
        """
        validate_error(
            api.create_candidacy(
                create_candidacy_payload(
                    world["cycle"]["id"],
                    world["candidates"][0]["id"],
                    world["electors"][0]["id"],
                ),
                ADMIN_HEADERS,
            ),
            "ERR_ELIGIBILITY_RULE_NOT_FOUND",
            404,
        )
        assert read_cycle(api, world["cycle"]["id"])["nomination_count"] == 0

    def test_no_candidacy_row_survives_the_lookup_failure(self, api, world):
        """An institution that never wrote down what a posthumous contributor must achieve cannot
        process one.

        Design: Corner/validations/eligibility_rule_lookup_precedes_every_career_and_waiting_check
        """
        api.create_candidacy(
            create_candidacy_payload(
                world["cycle"]["id"], world["candidates"][0]["id"], world["electors"][0]["id"]
            ),
            ADMIN_HEADERS,
        )
        _, meta = validate_paginated(
            api.list_candidacies(ADMIN_HEADERS, {"cycle_id": world["cycle"]["id"], "limit": 100})
        )
        assert meta["total_count"] == 0


class TestSlotMembershipBeforeTheVoteCap:
    """The cap cannot be applied to a list that has not been validated."""

    @pytest.fixture
    def world(self, api):
        """An open single-slot ballot, so the per-elector cap is one."""
        return build_election_world(
            api, stage="ballot_open", elector_count=2, candidate_count=1
        )

    def test_a_stray_identifier_is_reported_before_the_over_long_list(self, api, world):
        """First, every identifier in `selected_slot_ids` must belong to the ballot named by
        `ballot_id`; a stray slot from another ballot is refused with `ERR_SLOT_NOT_ON_BALLOT`
        (HTTP 422).

        Design: Corner/validations/slot_membership_is_checked_before_the_per_elector_vote_cap
        """
        validate_error(
            api.create_vote_submission(
                create_vote_submission_payload(
                    world["ballot"]["id"],
                    [slot_of(world, 0)["id"], STRAY_SLOT_ID],
                    world["ballot"]["version"],
                ),
                elector_headers(world, 0),
            ),
            "ERR_SLOT_NOT_ON_BALLOT",
            422,
        )

    def test_the_refused_submission_moves_no_turnout_figure(self, api, world):
        """An over-long list, an empty list without the abstention flag, or an abstention that
        nonetheless names slots are all refused with `ERR_MAX_VOTES_EXCEEDED` (HTTP 422).

        Design: Corner/validations/slot_membership_is_checked_before_the_per_elector_vote_cap
        """
        api.create_vote_submission(
            create_vote_submission_payload(
                world["ballot"]["id"],
                [slot_of(world, 0)["id"], STRAY_SLOT_ID],
                world["ballot"]["version"],
            ),
            elector_headers(world, 0),
        )
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["max_votes_per_elector"] == 1
        assert ballot["ballots_cast"] == 0
        assert ballot["total_selections_counted"] == 0


class TestScreeningDecisionByAnIndependentMember:
    """The positive side of the screening gauntlet."""

    @pytest.fixture
    def world(self, api):
        """A screening cycle whose single candidacy has had no decision yet."""
        return build_election_world(
            api, stage="screened", elector_count=2, candidate_count=1, advance=[]
        )

    def test_an_independent_committee_member_may_advance_the_candidacy(self, api, world):
        """The acting elector must genuinely sit on the committee: their elector row must have
        `is_screening_member` true *and* `status` `CREDENTIALED`, and a caller failing either
        condition is refused with `ERR_NOT_SCREENING_MEMBER` (HTTP 403).

        Design: Corner/validations/screening_decision_by_an_independent_committee_member_succeeds
        """
        candidacy = validate_success(
            api.create_screening_decision(
                world["candidacies"][0]["id"],
                create_screening_decision_payload(
                    "ADVANCE", screening_notes="Clears the modern-era bar"
                ),
                screening_headers(world),
            ),
            200,
        )
        assert candidacy["status"] == "ADVANCED"
        assert candidacy["screened_by_elector_id"] == world["electors"][1]["id"]

    def test_the_advance_moves_the_cycle_counter_and_version_together(self, api, world):
        """Advancing increments the cycle's `advanced_candidacy_count` by 1, and that counter change
        increments the cycle's `version` by 1, which is precisely how a late advance invalidates an
        administrator's in-flight ballot construction.

        Design: Corner/validations/screening_decision_by_an_independent_committee_member_succeeds
        """
        before = read_cycle(api, world["cycle"]["id"])
        validate_success(
            api.create_screening_decision(
                world["candidacies"][0]["id"],
                create_screening_decision_payload("ADVANCE"),
                screening_headers(world),
            ),
            200,
        )
        after = read_cycle(api, world["cycle"]["id"])
        assert after["advanced_candidacy_count"] == 1
        assert after["status"] == "SCREENING"
        assert after["version"] == before["version"] + 1


class TestTravelGrantAboveTheRemainingBudget:
    """The budget fit test runs at creation, not only at approval."""

    @pytest.fixture
    def world(self, api):
        """A ceremony-planned cycle whose whole travel budget is 10,000 cents."""
        world = build_election_world(
            api,
            stage="ceremony",
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
            ceremony_overrides={"travel_budget_cents": 10000},
        )
        world["induction"] = induction_of(world, 0)
        return world

    def test_an_unfundable_award_is_rejected_before_it_is_recorded(self, api, world):
        """That same fit test is also applied at creation time, so an award that could never be funded
        is rejected before it is ever recorded.

        Design: Corner/validations/travel_grant_above_the_remaining_budget_rejected_at_creation
        """
        validate_error(
            api.create_travel_grant(
                create_travel_grant_payload(
                    world["induction"]["id"],
                    world["cycle_version"],
                    nights=1,
                    requested_airfare_cents=0,
                ),
                ADMIN_HEADERS,
            ),
            "ERR_TRAVEL_BUDGET_EXCEEDED",
            409,
        )
        _, meta = validate_paginated(
            api.list_travel_grants(
                ADMIN_HEADERS, {"induction_id": world["induction"]["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 0

    def test_the_refusal_leaves_the_travel_dimension_pending(self, api, world):
        """The frozen `award_cents` must fit the remaining budget: it must be less than or equal to
        the cycle's `travel_budget_cents` minus its `travel_committed_cents`, and a grant that does
        not fit is refused with `ERR_TRAVEL_BUDGET_EXCEEDED` (HTTP 409).

        Design: Corner/validations/travel_grant_above_the_remaining_budget_rejected_at_creation
        """
        api.create_travel_grant(
            create_travel_grant_payload(
                world["induction"]["id"],
                world["cycle_version"],
                nights=1,
                requested_airfare_cents=0,
            ),
            ADMIN_HEADERS,
        )
        assert read_induction(api, world["induction"]["id"])["travel_status"] == "PENDING"
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["travel_committed_cents"] == 0
        assert cycle["austerity_tier"] == "FULL"


class TestAppearanceBudgetSpentByThePreviousCycle:
    """The appearance the 2026 round used is the one 2027 no longer has."""

    @pytest.fixture
    def world(self, api):
        """A certified 2026 cycle whose single appearance budget is now spent."""
        return build_election_world(
            api,
            stage="certified",
            rules=[{"max_ballot_appearances": 1}],
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0])],
        )

    def test_the_expired_candidacy_spent_the_only_appearance(self, api, world):
        """The rule increments the candidate's `ballot_appearances_used` by 1 first, because the
        appearance was in fact used, and only then compares. If the incremented
        `ballot_appearances_used` is greater than or equal to the `max_ballot_appearances` of the
        eligibility rule for the candidate's `category` paired with the candidacy's `pathway`, the
        candidacy becomes `EXPIRED`.

        Design: Corner/validations/appearance_budget_exhausted_by_the_previous_cycle_blocks_the_next_nomination
        """
        candidate = read_candidate(api, world["candidates"][0]["id"])
        assert candidate["ballot_appearances_used"] == 1
        assert candidate["hof_status"] == "NOT_INDUCTED"
        assert read_candidacy(api, world["candidacies"][0]["id"])["status"] == "EXPIRED"

    def test_the_expiration_writes_the_veterans_floor(self, api, world):
        """The candidate's `veterans_eligible_from_year` becomes the later of two years: the
        candidate's `retirement_year` plus twenty-five years, and this cycle's `cycle_year` plus three
        years.

        Design: Corner/validations/appearance_budget_exhausted_by_the_previous_cycle_blocks_the_next_nomination
        """
        assert (
            read_candidate(api, world["candidates"][0]["id"])["veterans_eligible_from_year"] == 2043
        )

    def test_the_next_cycle_refuses_the_same_candidate(self, api, world):
        """Next comes the appearance budget: the candidate's `ballot_appearances_used` must be
        strictly less than the rule's `max_ballot_appearances`, and a candidate who has already used
        every appearance the pathway allows is refused with `ERR_APPEARANCE_LIMIT_REACHED`
        (HTTP 422).

        Design: Corner/validations/appearance_budget_exhausted_by_the_previous_cycle_blocks_the_next_nomination
        """
        later = setup_cycle(api, cycle_year=2027)
        validate_success(api.open_nominations(later["id"], ADMIN_HEADERS), 200)
        validate_error(
            api.create_candidacy(
                create_candidacy_payload(
                    later["id"], world["candidates"][0]["id"], world["electors"][0]["id"]
                ),
                ADMIN_HEADERS,
            ),
            "ERR_APPEARANCE_LIMIT_REACHED",
            422,
        )
        assert read_cycle(api, later["id"])["nomination_count"] == 0
