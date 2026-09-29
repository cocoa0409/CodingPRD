"""One reachable refusal per error the contract declares, and what each refusal leaves behind."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    CURATOR_HEADERS,
    build_election_world,
    create_ballot_payload,
    create_candidacy_payload,
    create_induction_cycle_payload,
    create_travel_grant_payload,
    create_vote_submission_payload,
    create_voter_bloc_payload,
    elector_headers,
    induction_of,
    make_elector_headers,
    read_ballot,
    read_bloc,
    read_candidacy,
    read_candidate,
    read_cycle,
    read_grant,
    read_induction,
    read_slot,
    request_travel_grant,
    setup_cycle,
    setup_voter_bloc,
    slot_of,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ELECTOR_UUID = "11111111-1111-1111-1111-111111111111"


class TestNominationWithoutAnActingIdentity:
    """The first rung of the ladder: a declared role with nobody behind it."""

    @pytest.fixture
    def world(self, api):
        """An open cycle, one credentialed elector, one eligible candidate."""
        return build_election_world(
            api, stage="nominations_open", elector_count=1, candidate_count=1
        )

    def test_the_missing_header_is_unauthenticated_not_forbidden(self, api, world):
        """If either header is absent, or if `X-User-Role` is not one of the five role names declared
        below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

        Design: Corner/errors/nomination_missing_the_x_user_id_header_is_unauthenticated
        """
        validate_error(
            api.create_candidacy(
                create_candidacy_payload(
                    world["cycle"]["id"],
                    world["candidates"][0]["id"],
                    world["electors"][0]["id"],
                ),
                {"X-User-Role": "Elector"},
            ),
            "ERR_UNAUTHENTICATED",
            401,
        )

    def test_the_unauthenticated_call_writes_nothing(self, api, world):
        """Its creation increments the cycle's `nomination_count` by 1 and recomputes the cycle's
        `special_election_used`, which counts the cycle's candidacies whose `pathway` is `SPECIAL` and
        whose `status` is anything other than `REJECTED`.

        Design: Corner/errors/nomination_missing_the_x_user_id_header_is_unauthenticated
        """
        api.create_candidacy(
            create_candidacy_payload(
                world["cycle"]["id"], world["candidates"][0]["id"], world["electors"][0]["id"]
            ),
            {"X-User-Role": "Elector"},
        )
        assert read_cycle(api, world["cycle"]["id"])["nomination_count"] == 0
        _, meta = validate_paginated(
            api.list_candidacies(ADMIN_HEADERS, {"cycle_id": world["cycle"]["id"], "limit": 100})
        )
        assert meta["total_count"] == 0


class TestCycleCreationByTheWrongRole:
    """A valid, authenticated role that this endpoint does not list."""

    def test_curatorial_staff_may_not_open_a_cycle(self, api):
        """Once the caller is identified, the service confirms that the acting role appears in the
        endpoint's authorized-role list in §4; a caller whose role is not listed is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403).

        Design: Corner/errors/cycle_creation_by_curatorial_staff_is_unauthorized
        """
        validate_error(
            api.create_induction_cycle(
                create_induction_cycle_payload(escort_pool_size=2), CURATOR_HEADERS
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        _, meta = validate_paginated(api.list_induction_cycles(ADMIN_HEADERS, {"limit": 100}))
        assert meta["total_count"] == 0


class TestNominationByAnUnresolvableIdentity:
    """A well-formed header pair naming an elector who does not exist."""

    @pytest.fixture
    def world(self, api):
        """An open cycle with two credentialed electors."""
        return build_election_world(
            api, stage="nominations_open", elector_count=2, candidate_count=1
        )

    def test_the_unknown_identity_is_forbidden_not_missing(self, api, world):
        """For both of these roles, a request whose `X-User-ID` does not resolve to an existing elector
        row is rejected with `ERR_ELECTOR_IDENTITY_UNKNOWN` (HTTP 403); this applies to nomination
        intake, screening decisions, supplements, vote casting and vote withdrawal.

        Design: Corner/errors/nomination_by_an_unresolvable_elector_identity_rejected
        """
        validate_error(
            api.create_candidacy(
                create_candidacy_payload(
                    world["cycle"]["id"],
                    world["candidates"][0]["id"],
                    UNKNOWN_ELECTOR_UUID,
                ),
                make_elector_headers(UNKNOWN_ELECTOR_UUID),
            ),
            "ERR_ELECTOR_IDENTITY_UNKNOWN",
            403,
        )
        assert read_cycle(api, world["cycle"]["id"])["nomination_count"] == 0


class TestSupplementWithoutAnInformationRequest:
    """The return leg of a revision loop that nobody started."""

    @pytest.fixture
    def world(self, api):
        """A screening cycle whose only candidacy has had no decision recorded."""
        return build_election_world(
            api, stage="screened", elector_count=2, candidate_count=1, advance=[]
        )

    def test_a_supplement_is_legal_only_from_the_queried_state(self, api, world):
        """Supplying a supplement takes a single `supplement_note`, requires the candidacy to be in
        `INFO_REQUESTED` (otherwise `ERR_INVALID_CANDIDACY_STATE`), and requires the acting
        `X-User-ID` to equal the candidacy's `nominated_by_elector_id` — a different elector answering
        someone else's information request is refused with `ERR_NOMINATOR_IDENTITY_MISMATCH`.

        Design: Corner/errors/supplement_on_a_candidacy_that_was_never_queried_rejected
        """
        validate_error(
            api.create_supplement(
                world["candidacies"][0]["id"],
                {"supplement_note": "Adding the 1994 postseason record"},
                elector_headers(world, 0),
            ),
            "ERR_INVALID_CANDIDACY_STATE",
            409,
        )

    def test_the_refused_supplement_leaves_the_screening_record_untouched(self, api, world):
        """The supplement note is appended to the candidacy's `screening_notes` and the candidacy
        returns to `SCREENING`, where the committee may advance, reject, defer or — if it has a request
        left in the budget — query it again.

        Design: Corner/errors/supplement_on_a_candidacy_that_was_never_queried_rejected
        """
        api.create_supplement(
            world["candidacies"][0]["id"],
            {"supplement_note": "Adding the 1994 postseason record"},
            elector_headers(world, 0),
        )
        candidacy = read_candidacy(api, world["candidacies"][0]["id"])
        assert candidacy["status"] == "SCREENING"
        assert candidacy["info_request_count"] == 0
        assert candidacy["screening_notes"] is None


class TestSecondTallyWhileTheAuditIsPending:
    """The tabulation dimension refuses a re-count it has not been released for."""

    @pytest.fixture
    def world(self, api):
        """A closed round with two counted submissions and a drafted tally awaiting audit."""
        return build_election_world(
            api, stage="tallied", elector_count=2, candidate_count=1, votes=[(0, [0]), (1, [0])]
        )

    def test_a_pending_audit_blocks_the_re_run(self, api, world):
        """The draft tally requires the ballot's `voting_status` to be `CLOSED` — a ballot still `DRAFT`
        or `OPEN` is refused with `ERR_INVALID_BALLOT_STATE` — and its `tally_status` to be either
        `NOT_TALLIED` (a first tally) or `AUDIT_REJECTED` (a re-tally), with anything else refused as
        `ERR_INVALID_TALLY_STATE` (HTTP 409).

        Design: Corner/errors/second_tally_while_the_first_awaits_audit_rejected
        """
        validate_error(
            api.tally_ballot(world["ballot"]["id"], ADMIN_HEADERS),
            "ERR_INVALID_TALLY_STATE",
            409,
        )

    def test_the_first_count_and_its_owner_survive_the_refusal(self, api, world):
        """Finally the draft tally records `tallied_by_user_id` as the acting administrator's
        `X-User-ID`, moves `tally_status` from `NOT_TALLIED` (or `AUDIT_REJECTED`) to `PENDING_AUDIT`,
        and increments the ballot's `version` by 1.

        Design: Corner/errors/second_tally_while_the_first_awaits_audit_rejected
        """
        api.tally_ballot(world["ballot"]["id"], ADMIN_HEADERS)
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["tally_status"] == "PENDING_AUDIT"
        assert ballot["voting_status"] == "CLOSED"
        assert ballot["ballots_cast"] == 2
        assert ballot["tallied_by_user_id"] == ADMIN_USER_ID


class TestCertifyElectionBeforeTheAuditor:
    """Certification consumes the auditor's verdict, not the administrator's draft."""

    @pytest.fixture
    def world(self, api):
        """A balloting cycle whose newest ballot is drafted but unaudited."""
        return build_election_world(
            api, stage="tallied", elector_count=2, candidate_count=1, votes=[(0, [0]), (1, [0])]
        )

    def test_an_uncertified_count_is_not_a_final_election(self, api, world):
        """A cycle whose newest ballot has not been certified, or whose certified outcome was
        `RUNOFF_REQUIRED`, is refused with `ERR_ELECTION_NOT_FINAL` (HTTP 409) — the runoff must be run
        first.

        Design: Corner/errors/certify_election_before_the_audit_decision_rejected
        """
        validate_error(
            api.certify_election(world["cycle"]["id"], ADMIN_HEADERS),
            "ERR_ELECTION_NOT_FINAL",
            409,
        )
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["status"] == "BALLOTING"
        assert cycle["induction_count"] == 0

    def test_no_induction_and_no_appearance_is_recorded(self, api, world):
        """On a first round each `ADVANCED` candidacy is simultaneously driven `ADVANCED` →
        `ON_BALLOT`, and that transition sets the candidacy's `appearance_number` to the candidate's
        `ballot_appearances_used` plus one — the appearance this printing represents.

        Design: Corner/errors/certify_election_before_the_audit_decision_rejected
        """
        api.certify_election(world["cycle"]["id"], ADMIN_HEADERS)
        assert read_candidacy(api, world["candidacies"][0]["id"])["status"] == "ON_BALLOT"
        assert read_candidate(api, world["candidates"][0]["id"])["ballot_appearances_used"] == 0
        _, meta = validate_paginated(
            api.list_inductions(ADMIN_HEADERS, {"cycle_id": world["cycle"]["id"], "limit": 100})
        )
        assert meta["total_count"] == 0


class TestTravelGrantBeforeTheCeremonyIsPlanned:
    """Travel funding hangs off the ceremony, not off the election."""

    @pytest.fixture
    def world(self, api):
        """A certified cycle with one announced induction and no ceremony date."""
        world = build_election_world(
            api,
            stage="certified",
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
        )
        world["induction"] = induction_of(world, 0)
        return world

    def test_no_grant_may_be_created_before_the_ceremony_exists(self, api, world):
        """Until the cycle reaches `CEREMONY_PLANNED`, no travel grant may be created, approved, denied
        or cancelled — all four operations are refused with `ERR_CEREMONY_NOT_PLANNED` (HTTP 409).

        Design: Corner/errors/travel_grant_before_the_ceremony_is_planned_rejected
        """
        validate_error(
            api.create_travel_grant(
                create_travel_grant_payload(
                    world["induction"]["id"],
                    world["cycle_version"],
                    nights=2,
                    requested_airfare_cents=40000,
                ),
                ADMIN_HEADERS,
            ),
            "ERR_CEREMONY_NOT_PLANNED",
            409,
        )

    def test_the_refusal_precedes_every_award_computation(self, api, world):
        """The transition stores all four values, moves the cycle `CERTIFIED` → `CEREMONY_PLANNED`,
        recomputes `austerity_tier` from the ratio of `travel_committed_cents` to
        `travel_budget_cents`, and increments the cycle's `version` by 1.

        Design: Corner/errors/travel_grant_before_the_ceremony_is_planned_rejected
        """
        api.create_travel_grant(
            create_travel_grant_payload(
                world["induction"]["id"],
                world["cycle_version"],
                nights=2,
                requested_airfare_cents=40000,
            ),
            ADMIN_HEADERS,
        )
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["status"] == "CERTIFIED"
        assert cycle["travel_committed_cents"] == 0
        assert read_induction(api, world["induction"]["id"])["travel_status"] == "PENDING"
        _, meta = validate_paginated(
            api.list_travel_grants(ADMIN_HEADERS, {"cycle_id": world["cycle"]["id"], "limit": 100})
        )
        assert meta["total_count"] == 0


class TestSecondApprovalOfTheSameGrant:
    """Approval is not idempotent, because a second one would commit the money twice."""

    @pytest.fixture
    def world(self, api):
        """A planned ceremony with one approved one-night grant of 18,333 cents."""
        world = build_election_world(
            api,
            stage="ceremony",
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
        )
        world["induction"] = induction_of(world, 0)
        world["grant"] = request_travel_grant(
            world, world["induction"]["id"], nights=1, requested_airfare_cents=0
        )
        validate_success(api.approve_travel_grant(world["grant"]["id"], ADMIN_HEADERS), 200)
        return world

    def test_the_second_approval_is_refused_on_state(self, api, world):
        """A grant not in the required from-state — `REQUESTED` for approval and denial, `APPROVED` for
        cancellation — is refused with `ERR_INVALID_GRANT_STATE` (HTTP 409).

        Design: Corner/errors/second_approval_of_an_already_approved_grant_rejected
        """
        validate_error(
            api.approve_travel_grant(world["grant"]["id"], ADMIN_HEADERS),
            "ERR_INVALID_GRANT_STATE",
            409,
        )
        grant = read_grant(api, world["grant"]["id"])
        assert grant["status"] == "APPROVED"
        assert grant["award_cents"] == 18333

    def test_the_award_is_committed_exactly_once(self, api, world):
        """Approval then increases the cycle's `travel_committed_cents` by `award_cents`, which
        recomputes the cycle's `austerity_tier` from the new ratio and increments the cycle's `version`
        by 1.

        Design: Corner/errors/second_approval_of_an_already_approved_grant_rejected
        """
        api.approve_travel_grant(world["grant"]["id"], ADMIN_HEADERS)
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["travel_committed_cents"] == 18333
        assert cycle["austerity_tier"] == "FULL"
        assert read_induction(api, world["induction"]["id"])["travel_status"] == "APPROVED"


class TestNominationUnderAnotherElectorsName:
    """An elector may file on their own behalf only."""

    @pytest.fixture
    def world(self, api):
        """An open cycle with two credentialed electors and one eligible candidate."""
        return build_election_world(
            api, stage="nominations_open", elector_count=2, candidate_count=1
        )

    def test_the_acting_elector_must_be_the_named_nominator(self, api, world):
        """When the acting role is `Elector`, the supplied `nominated_by_elector_id` must equal the
        acting `X-User-ID`; an elector filing under someone else's name is refused with
        `ERR_NOMINATOR_IDENTITY_MISMATCH` (HTTP 403).

        Design: Corner/errors/nomination_filed_under_another_electors_name_rejected
        """
        validate_error(
            api.create_candidacy(
                create_candidacy_payload(
                    world["cycle"]["id"],
                    world["candidates"][0]["id"],
                    world["electors"][1]["id"],
                ),
                elector_headers(world, 0),
            ),
            "ERR_NOMINATOR_IDENTITY_MISMATCH",
            403,
        )
        assert read_cycle(api, world["cycle"]["id"])["nomination_count"] == 0

    def test_the_administrator_may_send_the_identical_body(self, api, world):
        """The payload names the `cycle_id` the nomination competes in, the `candidate_id` of the person
        being nominated, the `nominated_by_elector_id` of the credentialed elector filing it, and the
        `pathway` being claimed, which is one of `MODERN`, `VETERANS`, `POSTHUMOUS` or `SPECIAL`.

        Design: Corner/errors/nomination_filed_under_another_electors_name_rejected
        """
        payload = create_candidacy_payload(
            world["cycle"]["id"], world["candidates"][0]["id"], world["electors"][1]["id"]
        )
        validate_error(
            api.create_candidacy(payload, elector_headers(world, 0)),
            "ERR_NOMINATOR_IDENTITY_MISMATCH",
            403,
        )
        candidacy = validate_success(api.create_candidacy(payload, ADMIN_HEADERS), 201)
        assert candidacy["nominated_by_elector_id"] == world["electors"][1]["id"]


class TestSecondLiveCandidacyForOnePerson:
    """Uniqueness of the person within the cycle, whoever files the second one."""

    @pytest.fixture
    def world(self, api):
        """An open cycle already holding one submitted candidacy for the candidate."""
        return build_election_world(
            api, stage="nominated", elector_count=2, candidate_count=1
        )

    def test_the_second_nomination_of_the_same_person_is_refused(self, api, world):
        """The last intake gate is uniqueness of the person within the cycle: no other candidacy may
        exist for the same combination of `cycle_id` and `candidate_id` with a `status` other than
        `REJECTED`, and a second live nomination of the same person in the same cycle is refused with
        `ERR_DUPLICATE_CANDIDACY` (HTTP 409).

        Design: Corner/errors/second_live_candidacy_for_the_same_candidate_and_cycle_rejected
        """
        validate_error(
            api.create_candidacy(
                create_candidacy_payload(
                    world["cycle"]["id"],
                    world["candidates"][0]["id"],
                    world["electors"][1]["id"],
                ),
                ADMIN_HEADERS,
            ),
            "ERR_DUPLICATE_CANDIDACY",
            409,
        )
        assert read_cycle(api, world["cycle"]["id"])["nomination_count"] == 1

    def test_only_the_first_candidacy_survives(self, api, world):
        """A fresh candidacy is written in `SUBMITTED` status with `appearance_number` at 0 (it is
        off-ballot), `info_request_count` at 0, `latest_round_votes` and `latest_round_pct` at 0, and
        `screened_by_elector_id` and `screening_notes` unset.

        Design: Corner/errors/second_live_candidacy_for_the_same_candidate_and_cycle_rejected
        """
        api.create_candidacy(
            create_candidacy_payload(
                world["cycle"]["id"], world["candidates"][0]["id"], world["electors"][1]["id"]
            ),
            ADMIN_HEADERS,
        )
        rows, meta = validate_paginated(
            api.list_candidacies(
                ADMIN_HEADERS, {"candidate_id": world["candidates"][0]["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "SUBMITTED"


class TestSecondSubmissionByOneElector:
    """One elector, one live submission per ballot; only a withdrawal reopens the seat."""

    @pytest.fixture
    def world(self, api):
        """An open ballot already carrying that elector's counted submission."""
        return build_election_world(
            api, stage="voted", elector_count=2, candidate_count=1, votes=[(0, [0])]
        )

    def test_a_retry_with_the_current_version_is_still_a_duplicate(self, api, world):
        """Third, the elector may hold only one live submission per ballot: if another submission
        already exists for the same `ballot_id` and `elector_id` with a `status` of either `COUNTED` or
        `INVALIDATED`, the new one is refused with `ERR_DUPLICATE_SUBMISSION` (HTTP 409) — an
        invalidated submission still spends the seat, so an elector whose ballot the auditor threw out
        does not get a second one.

        Design: Corner/errors/second_submission_by_the_same_elector_on_one_ballot_rejected
        """
        validate_error(
            api.create_vote_submission(
                create_vote_submission_payload(
                    world["ballot"]["id"], [slot_of(world, 0)["id"]], world["ballot_version"]
                ),
                elector_headers(world, 0),
            ),
            "ERR_DUPLICATE_SUBMISSION",
            409,
        )

    def test_the_turnout_figures_stay_at_one(self, api, world):
        """The ballot's `ballots_cast` increases by 1 and its `total_selections_counted` increases by
        that submission's `selection_count`, so an abstention raises turnout without adding a single
        slot vote.

        Design: Corner/errors/second_submission_by_the_same_elector_on_one_ballot_rejected
        """
        api.create_vote_submission(
            create_vote_submission_payload(
                world["ballot"]["id"], [slot_of(world, 0)["id"]], world["ballot_version"]
            ),
            elector_headers(world, 0),
        )
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["ballots_cast"] == 1
        assert ballot["total_selections_counted"] == 1
        _, meta = validate_paginated(
            api.list_vote_submissions(
                ADMIN_HEADERS,
                {
                    "ballot_id": world["ballot"]["id"],
                    "elector_id": world["electors"][0]["id"],
                    "limit": 100,
                },
            )
        )
        assert meta["total_count"] == 1


class TestSecondBlocReusingTheSameCode:
    """Configuration rows are keyed by their natural business key."""

    @pytest.fixture
    def bloc(self, api):
        """The writers' bloc with ten seats and a half participation floor."""
        return setup_voter_bloc(api)

    def test_a_reused_bloc_code_is_refused(self, api, bloc):
        """Duplicate `bloc_code` values are refused with `ERR_DUPLICATE_CONFIGURATION`.

        Design: Corner/errors/second_voter_bloc_with_the_same_bloc_code_rejected
        """
        validate_error(
            api.create_voter_bloc(
                create_voter_bloc_payload(
                    bloc_code="WRITERS",
                    name="Rival Writers",
                    seat_cap=4,
                    min_participation_pct=0.9,
                ),
                ADMIN_HEADERS,
            ),
            "ERR_DUPLICATE_CONFIGURATION",
            409,
        )

    def test_the_refusal_is_not_a_silent_upsert(self, api, bloc):
        """Each carries a `bloc_code` that is unique across the table, a human-readable `name`, a
        `seat_cap` of at least 1 limiting how many seated electors the bloc may hold, and a
        `min_participation_pct` between 0 and 1 inclusive: the minimum fraction of the bloc's seated
        electors that must have a counted submission before a tally may be audit-certified.

        Design: Corner/errors/second_voter_bloc_with_the_same_bloc_code_rejected
        """
        api.create_voter_bloc(
            create_voter_bloc_payload(
                bloc_code="WRITERS", name="Rival Writers", seat_cap=4, min_participation_pct=0.9
            ),
            ADMIN_HEADERS,
        )
        stored = read_bloc(api, bloc["id"])
        assert stored["seat_cap"] == 10
        assert stored["min_participation_pct"] == pytest.approx(0.50, abs=0.005)
        _, meta = validate_paginated(
            api.list_voter_blocs(ADMIN_HEADERS, {"bloc_code": "WRITERS", "limit": 100})
        )
        assert meta["total_count"] == 1


class TestBallotConstructionWithNothingAdvanced:
    """A first round prints the advanced candidacies, and there are none."""

    @pytest.fixture
    def world(self, api):
        """A screening cycle whose only candidacy has never been decided."""
        return build_election_world(
            api, stage="screened", elector_count=2, candidate_count=1, advance=[]
        )

    def test_an_empty_source_set_is_refused_for_lack_of_a_slate(self, api, world):
        """If the applicable source yields nothing at all — no `ADVANCED` candidacy for a first round,
        no slot carried to the runoff for a runoff round, no `ON_BALLOT` candidacy when replacing an
        expired ballot — the construction is refused with `ERR_NO_SLATE_AVAILABLE` (HTTP 409).

        Design: Corner/errors/ballot_construction_with_nothing_advanced_rejected
        """
        validate_error(
            api.create_ballot(
                create_ballot_payload(world["cycle"]["id"], world["cycle_version"]),
                ADMIN_HEADERS,
            ),
            "ERR_NO_SLATE_AVAILABLE",
            409,
        )

    def test_the_cycle_never_leaves_screening(self, api, world):
        """Each construction increments the cycle's `version` by 1.

        Design: Corner/errors/ballot_construction_with_nothing_advanced_rejected
        """
        api.create_ballot(
            create_ballot_payload(world["cycle"]["id"], world["cycle_version"]), ADMIN_HEADERS
        )
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["status"] == "SCREENING"
        assert cycle["current_round"] == 0
        assert read_candidacy(api, world["candidacies"][0]["id"])["status"] == "SCREENING"
        _, meta = validate_paginated(
            api.list_ballots(ADMIN_HEADERS, {"cycle_id": world["cycle"]["id"], "limit": 100})
        )
        assert meta["total_count"] == 0


class TestAbstentionCombinedWithASelection:
    """The cap rule is a biconditional, not just a ceiling."""

    @pytest.fixture
    def world(self, api):
        """An open one-slot ballot with no submission yet."""
        return build_election_world(
            api, stage="ballot_open", elector_count=2, candidate_count=1
        )

    def test_an_abstention_that_names_a_slot_is_refused(self, api, world):
        """Fourth, the selection count must respect the cap and the abstention flag together: the number
        of entries in `selected_slot_ids` must not exceed the ballot's `max_votes_per_elector`, and the
        list must be empty exactly when `is_abstention` is true.

        Design: Corner/errors/abstention_flag_combined_with_a_selection_rejected
        """
        validate_error(
            api.create_vote_submission(
                create_vote_submission_payload(
                    world["ballot"]["id"],
                    [slot_of(world, 0)["id"]],
                    world["ballot_version"],
                    is_abstention=True,
                ),
                elector_headers(world, 0),
            ),
            "ERR_MAX_VOTES_EXCEEDED",
            422,
        )

    def test_the_inside_the_cap_body_still_records_nothing(self, api, world):
        """An over-long list, an empty list without the abstention flag, or an abstention that
        nonetheless names slots are all refused with `ERR_MAX_VOTES_EXCEEDED` (HTTP 422).

        Design: Corner/errors/abstention_flag_combined_with_a_selection_rejected
        """
        api.create_vote_submission(
            create_vote_submission_payload(
                world["ballot"]["id"],
                [slot_of(world, 0)["id"]],
                world["ballot_version"],
                is_abstention=True,
            ),
            elector_headers(world, 0),
        )
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["max_votes_per_elector"] == 1
        assert ballot["ballots_cast"] == 0
        _, meta = validate_paginated(
            api.list_vote_submissions(
                ADMIN_HEADERS, {"ballot_id": world["ballot"]["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 0


class TestTallyOfARoundNobodyVotedIn:
    """An empty round is not tabulated as all-zeros; it is not tabulated at all."""

    @pytest.fixture
    def world(self, api):
        """A closed round whose voting window ran with no submissions."""
        return build_election_world(
            api, stage="voting_closed", elector_count=2, candidate_count=1, votes=[]
        )

    def test_a_zero_turnout_round_is_refused(self, api, world):
        """And there must be something to count: a ballot whose `ballots_cast` is 0 is refused with
        `ERR_NO_BALLOTS_CAST` (HTTP 409).

        Design: Corner/errors/tally_of_a_round_nobody_voted_in_rejected
        """
        validate_error(
            api.tally_ballot(world["ballot"]["id"], ADMIN_HEADERS), "ERR_NO_BALLOTS_CAST", 409
        )

    def test_the_round_keeps_its_snapshot_and_computes_no_threshold(self, api, world):
        """A constructed ballot is in `DRAFT` on the voting dimension and `NOT_TALLIED` on the
        tabulation dimension, with `ballots_cast`, `total_selections_counted`,
        `credentialed_roster_at_close`, `threshold_votes_provisional`, `threshold_votes_final` and
        `elected_slot_count` all at 0.

        Design: Corner/errors/tally_of_a_round_nobody_voted_in_rejected
        """
        api.tally_ballot(world["ballot"]["id"], ADMIN_HEADERS)
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["voting_status"] == "CLOSED"
        assert ballot["tally_status"] == "NOT_TALLIED"
        assert ballot["credentialed_roster_at_close"] == 2
        assert ballot["threshold_votes_provisional"] == 0
        assert read_slot(api, slot_of(world, 0)["id"])["votes_received"] == 0


class TestTravelGrantWithAnInvertedEscortInterval:
    """Optional fields, once supplied, must still be coherent."""

    @pytest.fixture
    def world(self, api):
        """A planned ceremony with a two-escort pool and one living inductee awaiting travel."""
        world = build_election_world(
            api,
            stage="ceremony",
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
            ceremony_overrides={"escort_pool_size": 2},
        )
        world["induction"] = induction_of(world, 0)
        return world

    def test_an_inverted_interval_is_refused_before_the_budget_is_probed(self, api, world):
        """A grant whose `variant` is `POSTHUMOUS_DELEGATION` must supply both `escort_from` and
        `escort_to`, with `escort_from` no later than `escort_to`; a missing endpoint or an inverted
        interval is refused with `ERR_INVALID_ESCORT_INTERVAL` (HTTP 422).

        Design: Corner/errors/travel_grant_with_an_inverted_escort_interval_rejected
        """
        validate_error(
            api.create_travel_grant(
                create_travel_grant_payload(
                    world["induction"]["id"],
                    world["cycle_version"],
                    nights=1,
                    requested_airfare_cents=0,
                    escort_from="2026-11-18T09:00:00Z",
                    escort_to="2026-11-16T09:00:00Z",
                ),
                ADMIN_HEADERS,
            ),
            "ERR_INVALID_ESCORT_INTERVAL",
            422,
        )
        assert read_cycle(api, world["cycle"]["id"])["travel_committed_cents"] == 0

    def test_no_grant_row_is_written_for_the_inductee(self, api, world):
        """Two optional timestamps, `escort_from` and `escort_to`, declare the ceremony-escort
        occupation interval.

        Design: Corner/errors/travel_grant_with_an_inverted_escort_interval_rejected
        """
        api.create_travel_grant(
            create_travel_grant_payload(
                world["induction"]["id"],
                world["cycle_version"],
                nights=1,
                requested_airfare_cents=0,
                escort_from="2026-11-18T09:00:00Z",
                escort_to="2026-11-16T09:00:00Z",
            ),
            ADMIN_HEADERS,
        )
        assert read_induction(api, world["induction"]["id"])["travel_status"] == "PENDING"
        _, meta = validate_paginated(
            api.list_travel_grants(
                ADMIN_HEADERS, {"induction_id": world["induction"]["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 0


class TestTravelGrantNamingAForeignFundingCycle:
    """The optional cycle cross-check must agree with the induction."""

    @pytest.fixture
    def world(self, api):
        """A planned 2026 ceremony beside an unrelated 2027 cycle still in setup."""
        world = build_election_world(
            api,
            stage="ceremony",
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
        )
        world["induction"] = induction_of(world, 0)
        world["other_cycle"] = setup_cycle(api, cycle_year=2027, travel_budget_cents=500000)
        return world

    def test_a_foreign_funder_is_refused_as_a_cycle_mismatch(self, api, world):
        """Two optional timestamps, `escort_from` and `escort_to`, declare the ceremony-escort
        occupation interval, and an optional `cycle_id` may be supplied purely as a cross-check: when
        present it must equal the induction's own `cycle_id`, and a mismatch is refused with
        `ERR_INDUCTION_CYCLE_MISMATCH` (HTTP 422).

        Design: Corner/errors/travel_grant_naming_a_foreign_funding_cycle_rejected
        """
        validate_error(
            api.create_travel_grant(
                create_travel_grant_payload(
                    world["induction"]["id"],
                    world["cycle_version"],
                    cycle_id=world["other_cycle"]["id"],
                    nights=1,
                    requested_airfare_cents=0,
                ),
                ADMIN_HEADERS,
            ),
            "ERR_INDUCTION_CYCLE_MISMATCH",
            422,
        )

    def test_neither_cycle_budget_moves(self, api, world):
        """The grant's `cycle_id` is copied from the induction, its `variant` and `traveler_count` are
        derived from the induction's frozen `delegation_type`, its `austerity_tier_applied` is frozen
        from the cycle's pre-commitment tier, its `status` is `REQUESTED`, and its `cancellation_reason`
        is unset.

        Design: Corner/errors/travel_grant_naming_a_foreign_funding_cycle_rejected
        """
        api.create_travel_grant(
            create_travel_grant_payload(
                world["induction"]["id"],
                world["cycle_version"],
                cycle_id=world["other_cycle"]["id"],
                nights=1,
                requested_airfare_cents=0,
            ),
            ADMIN_HEADERS,
        )
        assert read_cycle(api, world["cycle"]["id"])["travel_committed_cents"] == 0
        other = read_cycle(api, world["other_cycle"]["id"])
        assert other["travel_committed_cents"] == 0
        assert other["status"] == "SETUP"
        assert read_induction(api, world["induction"]["id"])["travel_status"] == "PENDING"


class TestSecondSpecialElectionNomination:
    """The special election is rationed to exactly one per cycle."""

    @pytest.fixture
    def world(self, api):
        """An open cycle whose single special slot is already taken by a live nomination."""
        world = build_election_world(
            api,
            stage="nominations_open",
            rules=[{}, {"pathway": "SPECIAL"}],
            elector_count=1,
            candidate_count=2,
        )
        world["first"] = validate_success(
            api.create_candidacy(
                create_candidacy_payload(
                    world["cycle"]["id"],
                    world["candidates"][0]["id"],
                    world["electors"][0]["id"],
                    pathway="SPECIAL",
                    justification="First overlooked contributor",
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        return world

    def test_the_second_special_nomination_exhausts_the_quota(self, api, world):
        """And the special election is rationed to exactly one per cycle: the cycle's
        `special_election_used` must be strictly less than one at the moment of filing, so a second live
        special nomination in the same cycle is refused with `ERR_SPECIAL_ELECTION_QUOTA_EXHAUSTED`
        (HTTP 409).

        Design: Corner/errors/second_special_election_nomination_in_one_cycle_rejected
        """
        validate_error(
            api.create_candidacy(
                create_candidacy_payload(
                    world["cycle"]["id"],
                    world["candidates"][1]["id"],
                    world["electors"][0]["id"],
                    pathway="SPECIAL",
                    justification="Second overlooked contributor",
                ),
                ADMIN_HEADERS,
            ),
            "ERR_SPECIAL_ELECTION_QUOTA_EXHAUSTED",
            409,
        )
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["special_election_used"] == 1
        assert cycle["nomination_count"] == 1

    def test_the_rationed_candidate_gets_no_candidacy_row(self, api, world):
        """Because the counter excludes `REJECTED` candidacies, a special nomination that the screening
        committee rejects releases the cycle's single slot for another attempt.

        Design: Corner/errors/second_special_election_nomination_in_one_cycle_rejected
        """
        api.create_candidacy(
            create_candidacy_payload(
                world["cycle"]["id"],
                world["candidates"][1]["id"],
                world["electors"][0]["id"],
                pathway="SPECIAL",
                justification="Second overlooked contributor",
            ),
            ADMIN_HEADERS,
        )
        _, meta = validate_paginated(
            api.list_candidacies(
                ADMIN_HEADERS, {"candidate_id": world["candidates"][1]["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 0
