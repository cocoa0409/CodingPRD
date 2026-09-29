"""Who may act, who may not, and which field only one role is allowed to see."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    CURATOR_HEADERS,
    build_election_world,
    create_audit_decision_payload,
    create_ballot_payload,
    create_screening_decision_payload,
    create_travel_grant_payload,
    elector_headers,
    induction_of,
    make_admin_headers,
    make_auditor_headers,
    make_elector_headers,
    make_screening_member_headers,
    read_ballot,
    read_bloc,
    read_candidacy,
    read_candidate,
    read_cycle,
    read_elector,
    read_induction,
    read_slot,
    setup_elector,
    setup_voter_bloc,
    slot_of,
    validate_error,
    validate_paginated,
    validate_success,
)

SHARED_OPERATOR_ID = "shared-user-9"


class TestCredentiallingBelongsToTheAdministrator:
    """The seat arithmetic is the administrator's alone."""

    @pytest.fixture
    def world(self, api):
        """A ten-seat bloc holding one provisional elector."""
        bloc = setup_voter_bloc(api)
        elector = setup_elector(api, bloc["id"], credential=False)
        return {"bloc": bloc, "elector": elector}

    def test_the_administrator_takes_the_seat_for_the_elector(self, api, world):
        """Credentialing an elector advances them from `PROVISIONAL` to `CREDENTIALED` and is where the
        bloc's seat arithmetic bites.

        Design: Corner/rbac/credentialing_is_exclusive_to_the_election_administrator
        """
        credentialed = validate_success(
            api.credential_elector(world["elector"]["id"], ADMIN_HEADERS), 200
        )
        assert credentialed["status"] == "CREDENTIALED"
        assert credentialed["consecutive_missed_cycles"] == 0

    def test_the_bloc_counter_records_the_occupied_seat(self, api, world):
        """A bloc starts with `seats_filled` at 0, and that counter tracks every elector of the bloc
        whose `status` is `CREDENTIALED` or `SUSPENDED`.

        Design: Corner/rbac/credentialing_is_exclusive_to_the_election_administrator
        """
        validate_success(api.credential_elector(world["elector"]["id"], ADMIN_HEADERS), 200)
        assert read_bloc(api, world["bloc"]["id"])["seats_filled"] == 1

    def test_an_elector_may_not_credential_themselves(self, api, world):
        """Once the caller is identified, the service confirms that the acting role appears in the
        endpoint's authorized-role list in §4; a caller whose role is not listed is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403).

        Design: Corner/rbac/credentialing_by_an_elector_role_is_unauthorized
        """
        validate_error(
            api.credential_elector(
                world["elector"]["id"], make_elector_headers(world["elector"]["id"])
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

    def test_the_refused_self_credential_leaves_the_seat_free(self, api, world):
        """On success the bloc's `seats_filled` increases by 1, and `credentialed_roster_count` is
        recomputed for every cycle whose `status` is `NOMINATIONS_OPEN`, `SCREENING` or `BALLOTING`.

        Design: Corner/rbac/credentialing_by_an_elector_role_is_unauthorized
        """
        api.credential_elector(
            world["elector"]["id"], make_elector_headers(world["elector"]["id"])
        )
        assert read_elector(api, world["elector"]["id"])["status"] == "PROVISIONAL"
        assert read_bloc(api, world["bloc"]["id"])["seats_filled"] == 0


class TestTheAuditDecisionBelongsToTheAuditor:
    """Only the auditor may resolve a round, and nobody else may try."""

    @pytest.fixture
    def world(self, api):
        """A drafted tally of two counted submissions on one listed slot."""
        return build_election_world(
            api, stage="tallied", elector_count=2, candidate_count=1, votes=[(0, [0]), (1, [0])]
        )

    def test_the_auditor_applies_the_roster_based_threshold(self, api, world):
        """Take the same house `election_threshold_pct`, multiply it by the ballot's frozen
        `credentialed_roster_at_close`, round the product up to the next whole vote, and store it as
        `threshold_votes_final`.

        Design: Corner/rbac/audit_certification_is_exclusive_to_the_independent_auditor
        """
        certified = validate_success(
            api.create_audit_decision(
                world["ballot"]["id"],
                create_audit_decision_payload(
                    "CERTIFY", audit_note="Counts reconciled against the credential roster"
                ),
                AUDITOR_HEADERS,
            ),
            200,
        )
        assert certified["tally_status"] == "AUDIT_CERTIFIED"
        assert certified["threshold_votes_provisional"] == 2
        assert certified["threshold_votes_final"] == 2
        assert certified["audit_note"] == "Counts reconciled against the credential roster"

    def test_the_certification_resolves_the_round_but_not_the_candidacy(self, api, world):
        """With `threshold_votes_final` in hand, the round is resolved by a seat waterfall over the
        ballot's `LISTED` slots — struck slots never qualify for anything.

        Design: Corner/rbac/audit_certification_is_exclusive_to_the_independent_auditor
        """
        certified = validate_success(
            api.create_audit_decision(
                world["ballot"]["id"],
                create_audit_decision_payload("CERTIFY", audit_note="Reconciled"),
                AUDITOR_HEADERS,
            ),
            200,
        )
        assert certified["elected_slot_count"] == 1
        assert certified["outcome"] == "ELECTION_COMPLETE"
        assert read_slot(api, slot_of(world, 0)["id"])["status"] == "ELECTED"
        assert read_candidacy(api, world["candidacies"][0]["id"])["status"] == "ON_BALLOT"

    def test_a_second_administrator_may_not_audit_either(self, api, world):
        """The audit decision is exclusive to the `IndependentAuditor` and carries a `decision` of either
        `REJECT` or `CERTIFY`, an optional `invalidate_submission_ids` array, and an optional
        `audit_note`.

        Design: Corner/rbac/audit_decision_by_the_election_administrator_is_unauthorized
        """
        validate_error(
            api.create_audit_decision(
                world["ballot"]["id"],
                create_audit_decision_payload("CERTIFY", audit_note="Self-certified"),
                make_admin_headers("admin-2"),
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

    def test_the_role_refusal_computes_no_final_figure(self, api, world):
        """The qualifying slots are those whose `votes_received` is greater than or equal to
        `threshold_votes_final`.

        Design: Corner/rbac/audit_decision_by_the_election_administrator_is_unauthorized
        """
        api.create_audit_decision(
            world["ballot"]["id"],
            create_audit_decision_payload("CERTIFY", audit_note="Self-certified"),
            make_admin_headers("admin-2"),
        )
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["tally_status"] == "PENDING_AUDIT"
        assert ballot["threshold_votes_final"] == 0
        assert ballot["outcome"] is None


class TestSegregationIsTrackedByOperatorIdentity:
    """One human wearing two roles is still one human."""

    @pytest.fixture
    def world(self, api):
        """A closed round tallied under a shared operator identifier."""
        world = build_election_world(
            api,
            stage="voting_closed",
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
        )
        world["ballot"] = validate_success(
            api.tally_ballot(world["ballot"]["id"], make_admin_headers(SHARED_OPERATOR_ID)), 200
        )
        return world

    def test_the_same_identifier_may_not_audit_its_own_count(self, api, world):
        """An audit decision may not be taken by the operator who produced the draft tally: when the
        acting `X-User-ID` equals the ballot's `tallied_by_user_id`, the audit decision is refused with
        the same `ERR_SEGREGATION_OF_DUTIES`.

        Design: Corner/rbac/audit_decision_by_the_user_who_produced_the_tally_is_refused
        """
        validate_error(
            api.create_audit_decision(
                world["ballot"]["id"],
                create_audit_decision_payload("CERTIFY", audit_note="Approving my own arithmetic"),
                make_auditor_headers(SHARED_OPERATOR_ID),
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )

    def test_the_stored_tallier_is_compared_as_a_string(self, api, world):
        """When `X-User-Role` is `IndependentAuditor`, `X-User-ID` is likewise an opaque operator
        identifier not tied to any persisted entity; the server compares it to the stored
        `tallied_by_user_id` string to enforce segregation of duties, but never resolves it to an entity
        row.

        Design: Corner/rbac/audit_decision_by_the_user_who_produced_the_tally_is_refused
        """
        api.create_audit_decision(
            world["ballot"]["id"],
            create_audit_decision_payload("CERTIFY", audit_note="Approving my own arithmetic"),
            make_auditor_headers(SHARED_OPERATOR_ID),
        )
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["tally_status"] == "PENDING_AUDIT"
        assert ballot["tallied_by_user_id"] == SHARED_OPERATOR_ID
        assert ballot["threshold_votes_final"] == 0


class TestArtifactIntakeBelongsToTheCurators:
    """The museum side of the domain has its own exclusive surface."""

    @pytest.fixture
    def world(self, api):
        """A certified cycle with one announced induction awaiting artifacts."""
        world = build_election_world(
            api,
            stage="certified",
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
        )
        world["induction"] = induction_of(world, 0)
        return world

    def test_the_curator_advances_only_the_artifact_dimension(self, api, world):
        """`CuratorialStaff` record what an inductee donates.

        Design: Corner/rbac/artifact_intake_is_exclusive_to_curatorial_staff
        """
        received = validate_success(
            api.create_artifact_intake(
                world["induction"]["id"], {"artifact_count": 3}, CURATOR_HEADERS
            ),
            200,
        )
        assert received["artifact_status"] == "RECEIVED"
        assert received["artifact_count"] == 3
        assert received["travel_status"] == "PENDING"
        assert received["exhibit_status"] == "NOT_PLANNED"

    def test_the_intake_alone_does_not_make_the_class_ready(self, api, world):
        """The cycle's `ceremony_ready_count` is likewise re-derived as the number of inductions of that
        cycle whose `ceremony_ready` is true, never incrementally patched from a stale value.

        Design: Corner/rbac/artifact_intake_is_exclusive_to_curatorial_staff
        """
        validate_success(
            api.create_artifact_intake(
                world["induction"]["id"], {"artifact_count": 3}, CURATOR_HEADERS
            ),
            200,
        )
        assert read_induction(api, world["induction"]["id"])["ceremony_ready"] is False
        assert read_cycle(api, world["cycle"]["id"])["ceremony_ready_count"] == 0

    def test_the_administrator_cannot_borrow_the_curators_operation(self, api, world):
        """The five roles are `ElectionAdministrator`, `ScreeningCommitteeMember`, `Elector`,
        `IndependentAuditor` and `CuratorialStaff`.

        Design: Corner/rbac/artifact_intake_by_the_election_administrator_is_unauthorized
        """
        validate_error(
            api.create_artifact_intake(
                world["induction"]["id"], {"artifact_count": 3}, ADMIN_HEADERS
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        induction = read_induction(api, world["induction"]["id"])
        assert induction["artifact_status"] == "AWAITED"
        assert induction["artifact_count"] == 0


class TestTravelFundingIsSharedByTwoRoles:
    """The one funding endpoint two roles own, priced identically for both."""

    @pytest.fixture
    def world(self, api):
        """A planned ceremony with two living inductees and nothing committed yet."""
        world = build_election_world(
            api,
            stage="ceremony",
            rules=[{"election_threshold_pct": 0.5}],
            elector_count=2,
            candidate_count=2,
            votes=[(0, [0]), (1, [1])],
        )
        world["first"] = induction_of(world, 0)
        world["second"] = induction_of(world, 1)
        return world

    def _grant(self, api, world, induction, headers):
        """Request a one-night grant, threading the cycle version the last write reported."""
        grant = validate_success(
            api.create_travel_grant(
                create_travel_grant_payload(
                    induction["id"], world["cycle_version"], nights=1, requested_airfare_cents=0
                ),
                headers,
            ),
            201,
        )
        world["cycle_version"] = grant["cycle_version_after"]
        return grant

    def test_both_roles_may_request_funding_at_the_same_price(self, api, world):
        """Either an `ElectionAdministrator` or `CuratorialStaff` may request funding for one induction.

        Design: Corner/rbac/travel_grant_creation_is_shared_between_the_administrator_and_the_curator
        """
        by_admin = self._grant(api, world, world["first"], ADMIN_HEADERS)
        by_curator = self._grant(api, world, world["second"], CURATOR_HEADERS)
        assert by_admin["award_cents"] == 18333
        assert by_curator["award_cents"] == 18333
        assert by_admin["austerity_tier_applied"] == "FULL"
        assert by_curator["austerity_tier_applied"] == "FULL"
        assert by_admin["status"] == "REQUESTED"
        assert by_curator["status"] == "REQUESTED"

    def test_neither_request_commits_a_cent(self, api, world):
        """The grant requires the induction's `travel_status` to be `PENDING`, and it drives that
        dimension `PENDING` → `REQUESTED`, which recomputes `ceremony_ready` (still false, since a merely
        requested grant funds nothing).

        Design: Corner/rbac/travel_grant_creation_is_shared_between_the_administrator_and_the_curator
        """
        self._grant(api, world, world["first"], ADMIN_HEADERS)
        self._grant(api, world, world["second"], CURATOR_HEADERS)
        assert read_induction(api, world["first"]["id"])["travel_status"] == "REQUESTED"
        assert read_induction(api, world["second"]["id"])["travel_status"] == "REQUESTED"
        assert read_cycle(api, world["cycle"]["id"])["travel_committed_cents"] == 0


class TestOnlyTheAuditorSeesTheSelections:
    """Confidentiality is a rule about a field, not about an endpoint."""

    @pytest.fixture
    def world(self, api):
        """An open ballot carrying one counted submission from the first elector."""
        return build_election_world(
            api, stage="voted", elector_count=2, candidate_count=1, votes=[(0, [0])]
        )

    def test_the_casting_elector_reads_their_own_row_without_the_choices(self, api, world):
        """For every other role — `ElectionAdministrator` and `Elector` included, and on both the
        single-submission read and the submission list — the `selected_slot_ids` field is returned as
        `null`.

        Design: Corner/rbac/individual_ballot_selections_are_readable_only_by_the_independent_auditor
        """
        own = validate_success(
            api.get_vote_submission(world["submissions"][0]["id"], elector_headers(world, 0)), 200
        )
        assert own["selected_slot_ids"] is None
        assert own["selection_count"] == 1
        assert own["status"] == "COUNTED"

    def test_the_auditor_reads_the_identical_row_with_the_choices(self, api, world):
        """A vote submission's `selected_slot_ids` array is stored in full, but it is echoed back as a
        non-null array only when the acting role is `IndependentAuditor`.

        Design: Corner/rbac/individual_ballot_selections_are_readable_only_by_the_independent_auditor
        """
        audited = validate_success(
            api.get_vote_submission(world["submissions"][0]["id"], AUDITOR_HEADERS), 200
        )
        assert audited["selected_slot_ids"] == [slot_of(world, 0)["id"]]
        assert audited["elector_id"] == world["electors"][0]["id"]


class TestNobodyScreensTheirOwnNomination:
    """A real committee member, the right endpoint, the wrong candidacy."""

    @pytest.fixture
    def world(self, api):
        """A screening cycle whose only candidacy was filed by the committee member."""
        return build_election_world(
            api,
            stage="screened",
            elector_count=2,
            candidate_count=1,
            advance=[],
            nominator_index=1,
        )

    def test_the_nominator_may_not_advance_their_own_candidacy(self, api, world):
        """The acting `X-User-ID` must not equal the candidacy's `nominated_by_elector_id` — nobody
        screens their own nomination — and a self-screening attempt is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

        Design: Corner/rbac/screening_decision_by_the_nominating_committee_member_is_refused
        """
        validate_error(
            api.create_screening_decision(
                world["candidacies"][0]["id"],
                create_screening_decision_payload(
                    "ADVANCE", screening_notes="Obvious first-ballot case"
                ),
                make_screening_member_headers(world["electors"][1]["id"]),
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )

    def test_the_refused_decision_stamps_nobody(self, api, world):
        """A screening decision may not be recorded by the elector who filed the nomination: when the
        acting `X-User-ID` equals the candidacy's `nominated_by_elector_id`, the decision is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

        Design: Corner/rbac/screening_decision_by_the_nominating_committee_member_is_refused
        """
        api.create_screening_decision(
            world["candidacies"][0]["id"],
            create_screening_decision_payload("ADVANCE"),
            make_screening_member_headers(world["electors"][1]["id"]),
        )
        candidacy = read_candidacy(api, world["candidacies"][0]["id"])
        assert candidacy["status"] == "SCREENING"
        assert candidacy["screened_by_elector_id"] is None
        assert read_cycle(api, world["cycle"]["id"])["advanced_candidacy_count"] == 0


class TestMembershipLivesOnTheElectorRow:
    """Wearing the committee role is not the same as sitting on the committee."""

    @pytest.fixture
    def world(self, api):
        """Three credentialed electors, only the second of them a committee member."""
        return build_election_world(
            api, stage="screened", elector_count=3, candidate_count=1, advance=[]
        )

    def test_a_credentialed_non_member_is_refused(self, api, world):
        """The acting elector must genuinely sit on the committee: their elector row must have
        `is_screening_member` true *and* `status` `CREDENTIALED`, and a caller failing either condition
        is refused with `ERR_NOT_SCREENING_MEMBER` (HTTP 403).

        Design: Corner/rbac/screening_decision_by_a_credentialed_non_member_is_refused
        """
        validate_error(
            api.create_screening_decision(
                world["candidacies"][0]["id"],
                create_screening_decision_payload("REJECT", screening_notes="Not convinced"),
                make_screening_member_headers(world["electors"][2]["id"]),
            ),
            "ERR_NOT_SCREENING_MEMBER",
            403,
        )
        assert read_elector(api, world["electors"][2]["id"])["is_screening_member"] is False

    def test_the_candidacy_keeps_waiting_for_a_real_member(self, api, world):
        """Whichever decision is recorded, the candidacy's `screened_by_elector_id` is set to the acting
        `X-User-ID`, so the record always shows who last touched it.

        Design: Corner/rbac/screening_decision_by_a_credentialed_non_member_is_refused
        """
        api.create_screening_decision(
            world["candidacies"][0]["id"],
            create_screening_decision_payload("REJECT", screening_notes="Not convinced"),
            make_screening_member_headers(world["electors"][2]["id"]),
        )
        candidacy = read_candidacy(api, world["candidacies"][0]["id"])
        assert candidacy["status"] == "SCREENING"
        assert candidacy["screened_by_elector_id"] is None


class TestTheSupplementBelongsToTheNominator:
    """Filing a nomination for an elector does not buy authority over the whole candidacy."""

    @pytest.fixture
    def world(self, api):
        """A candidacy parked in the queried state after one committee information request."""
        world = build_election_world(
            api, stage="screened", elector_count=2, candidate_count=1, advance=[]
        )
        validate_success(
            api.create_screening_decision(
                world["candidacies"][0]["id"],
                create_screening_decision_payload(
                    "REQUEST_INFO", screening_notes="Confirm the qualifying seasons"
                ),
                make_screening_member_headers(world["electors"][1]["id"]),
            ),
            200,
        )
        return world

    def test_the_administrator_may_not_answer_the_committee(self, api, world):
        """Supplying a supplement takes a single `supplement_note`, requires the candidacy to be in
        `INFO_REQUESTED` (otherwise `ERR_INVALID_CANDIDACY_STATE`), and requires the acting `X-User-ID`
        to equal the candidacy's `nominated_by_elector_id` — a different elector answering someone else's
        information request is refused with `ERR_NOMINATOR_IDENTITY_MISMATCH`.

        Design: Corner/rbac/supplement_by_the_election_administrator_is_unauthorized
        """
        validate_error(
            api.create_supplement(
                world["candidacies"][0]["id"],
                {"supplement_note": "Seasons verified at 15"},
                ADMIN_HEADERS,
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

    def test_the_candidacy_stays_parked_with_its_request_spent(self, api, world):
        """`REQUEST_INFO` is the one decision that does not end the review. It moves the candidacy from
        `SCREENING` to `INFO_REQUESTED` and increments its `info_request_count` by 1.

        Design: Corner/rbac/supplement_by_the_election_administrator_is_unauthorized
        """
        api.create_supplement(
            world["candidacies"][0]["id"],
            {"supplement_note": "Seasons verified at 15"},
            ADMIN_HEADERS,
        )
        candidacy = read_candidacy(api, world["candidacies"][0]["id"])
        assert candidacy["status"] == "INFO_REQUESTED"
        assert candidacy["info_request_count"] == 1
        assert candidacy["nominated_by_elector_id"] == world["electors"][0]["id"]


class TestScreeningRejectionIsTheCommitteesOwnWork:
    """The committee's exclusive operation, exercised on its terminal decision."""

    @pytest.fixture
    def world(self, api):
        """A screening cycle whose candidacy was filed by an elector other than the member."""
        return build_election_world(
            api, stage="screened", elector_count=2, candidate_count=1, advance=[]
        )

    def test_the_member_may_reject_and_is_recorded_as_the_decider(self, api, world):
        """`REJECT` moves the candidacy from `SCREENING` to the terminal `REJECTED` state and recomputes
        the cycle's `special_election_used` when the rejected candidacy's `pathway` was `SPECIAL`,
        releasing the cycle's single special slot.

        Design: Corner/rbac/screening_rejection_is_exclusive_to_the_committee_member
        """
        rejected = validate_success(
            api.create_screening_decision(
                world["candidacies"][0]["id"],
                create_screening_decision_payload(
                    "REJECT", screening_notes="Career metric short of the era standard"
                ),
                make_screening_member_headers(world["electors"][1]["id"]),
            ),
            200,
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["screened_by_elector_id"] == world["electors"][1]["id"]

    def test_a_rejection_advances_nothing_and_inducts_nobody(self, api, world):
        """Advancing increments the cycle's `advanced_candidacy_count` by 1, and that counter change
        increments the cycle's `version` by 1.

        Design: Corner/rbac/screening_rejection_is_exclusive_to_the_committee_member
        """
        validate_success(
            api.create_screening_decision(
                world["candidacies"][0]["id"],
                create_screening_decision_payload("REJECT"),
                make_screening_member_headers(world["electors"][1]["id"]),
            ),
            200,
        )
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["advanced_candidacy_count"] == 0
        assert cycle["special_election_used"] == 0
        assert cycle["status"] == "SCREENING"
        candidate = read_candidate(api, world["candidates"][0]["id"])
        assert candidate["hof_status"] == "NOT_INDUCTED"
        assert candidate["ballot_appearances_used"] == 0


class TestTheCommitteeDoesNotPrintTheBallot:
    """Every substantive precondition passes; only the role explains the refusal."""

    @pytest.fixture
    def world(self, api):
        """A screening cycle with one advanced candidacy, ready for construction."""
        return build_election_world(
            api, stage="screened", elector_count=2, candidate_count=1
        )

    def test_a_committee_member_may_not_construct_the_ballot(self, api, world):
        """Ballot construction is the act that turns a screened field into a printed slate, and it is
        reserved to the `ElectionAdministrator`.

        Design: Corner/rbac/ballot_construction_by_a_screening_committee_member_is_unauthorized
        """
        validate_error(
            api.create_ballot(
                create_ballot_payload(world["cycle"]["id"], world["cycle_version"]),
                make_screening_member_headers(world["electors"][1]["id"]),
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

    def test_the_role_check_precedes_the_concurrency_check(self, api, world):
        """A `POST /ballots` request must carry `expected_cycle_version` matching the target
        `InductionCycle`'s current `version`.

        Design: Corner/rbac/ballot_construction_by_a_screening_committee_member_is_unauthorized
        """
        api.create_ballot(
            create_ballot_payload(world["cycle"]["id"], world["cycle_version"]),
            make_screening_member_headers(world["electors"][1]["id"]),
        )
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["status"] == "SCREENING"
        assert cycle["current_round"] == 0
        assert cycle["advanced_candidacy_count"] == 1
        assert read_candidacy(api, world["candidacies"][0]["id"])["status"] == "ADVANCED"
        _, meta = validate_paginated(
            api.list_ballots(ADMIN_HEADERS, {"cycle_id": world["cycle"]["id"], "limit": 100})
        )
        assert meta["total_count"] == 0
