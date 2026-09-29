"""What each endpoint returns, which fields it moves, and how its rows are found again."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    CURATOR_HEADERS,
    approve_travel_grant,
    build_election_world,
    create_audit_decision_payload,
    create_candidate_payload,
    create_exhibit_installation_payload,
    create_vote_submission_payload,
    elector_headers,
    induction_of,
    read_ballot,
    read_candidacy,
    read_candidate,
    read_case,
    read_cycle,
    read_grant,
    read_induction,
    read_slot,
    read_submission,
    request_travel_grant,
    set_clock,
    setup_artifact_intake,
    setup_exhibit_case,
    slot_of,
    validate_paginated,
    validate_success,
)


class TestCandidateMaintenanceRoundTrip:
    """Register, read back, then revise the one entity with a full maintenance surface."""

    @pytest.fixture
    def candidate(self, api):
        """A registered fifteen-season player."""
        return validate_success(
            api.create_candidate(
                create_candidate_payload(
                    full_name="Player Crud", career_seasons=15, career_metric_value=3000
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

    def test_the_read_echoes_every_registered_fact(self, api, candidate):
        """Registration takes the candidate's `full_name`, their `category`, the `retirement_year` in
        which their qualifying career ended (again between 1900 and 2200), the `career_seasons` they
        completed and their `career_metric_value`.

        Design: Corner/endpoints/candidate_create_read_and_patch_round_trip
        """
        stored = read_candidate(api, candidate["id"])
        assert stored["full_name"] == "Player Crud"
        assert stored["category"] == "PLAYER"
        assert stored["retirement_year"] == 2018
        assert stored["hof_status"] == "NOT_INDUCTED"
        assert stored["ballot_appearances_used"] == 0
        assert candidate["version"] == 1

    def test_a_partial_revision_touches_only_what_it_names(self, api, candidate):
        """An administrator may therefore revise a registered candidate's `career_seasons`,
        `career_metric_value`, `is_deceased` and `death_year` after the fact; such a revision
        increments the candidate's `version` by 1 and deliberately leaves `hof_status`,
        `ballot_appearances_used` and `veterans_eligible_from_year` exactly as they were, because those
        three are outcomes of the election machinery rather than biographical facts.

        Design: Corner/endpoints/candidate_create_read_and_patch_round_trip
        """
        revised = validate_success(
            api.patch_candidate(
                candidate["id"],
                {"career_seasons": 16, "career_metric_value": 3100},
                ADMIN_HEADERS,
            ),
            200,
        )
        assert revised["version"] == 2
        assert revised["career_seasons"] == 16
        assert revised["career_metric_value"] == 3100
        assert revised["full_name"] == "Player Crud"
        assert revised["retirement_year"] == 2018
        assert revised["hof_status"] == "NOT_INDUCTED"
        assert revised["ballot_appearances_used"] == 0


class TestOpeningTheRoundByCertification:
    """The bodiless action that turns a printed slate into a live round."""

    @pytest.fixture
    def world(self, api):
        """A one-slot slate printed but not yet opened."""
        return build_election_world(
            api, stage="ballot_draft", elector_count=2, candidate_count=1
        )

    def test_certifying_the_slate_opens_it_and_publishes_the_cap(self, api, world):
        """Certifying the printed slate opens it for voting, moving `voting_status` from `DRAFT` to
        `OPEN` and incrementing the ballot's `version` by 1.

        Design: Corner/endpoints/ballot_certify_action_opens_the_round_and_publishes_the_vote_cap
        """
        opened = validate_success(api.certify_ballot(world["ballot"]["id"], ADMIN_HEADERS), 200)
        assert opened["voting_status"] == "OPEN"
        assert opened["tally_status"] == "NOT_TALLIED"
        assert opened["slot_count"] == 1
        assert opened["max_votes_per_elector"] == 1
        assert opened["round_number"] == 1
        assert opened["version"] == world["ballot"]["version"] + 1

    def test_the_printed_slot_and_its_candidacy_carry_the_first_appearance(self, api, world):
        """On a first round each `ADVANCED` candidacy is simultaneously driven `ADVANCED` →
        `ON_BALLOT`, and that transition sets the candidacy's `appearance_number` to the candidate's
        `ballot_appearances_used` plus one — the appearance this printing represents.

        Design: Corner/endpoints/ballot_certify_action_opens_the_round_and_publishes_the_vote_cap
        """
        validate_success(api.certify_ballot(world["ballot"]["id"], ADMIN_HEADERS), 200)
        assert read_slot(api, slot_of(world, 0)["id"])["status"] == "LISTED"
        candidacy = read_candidacy(api, world["candidacies"][0]["id"])
        assert candidacy["status"] == "ON_BALLOT"
        assert candidacy["appearance_number"] == 1


class TestClosingAfterTheWindowHasPassed:
    """One endpoint, two destinations, chosen by the clock."""

    @pytest.fixture
    def world(self, api):
        """An open round with one submission, closed a day after its `closes_at`."""
        world = build_election_world(
            api, stage="voted", elector_count=2, candidate_count=1, votes=[(0, [0])]
        )
        set_clock(api, "2026-08-21T00:00:00Z")
        world["closed"] = validate_success(
            api.close_ballot(world["ballot"]["id"], ADMIN_HEADERS), 200
        )
        return world

    def test_a_late_close_voids_the_round_instead_of_closing_it(self, api, world):
        """If the logical clock has reached or passed `closes_at`, `voting_status` moves `OPEN` →
        `EXPIRED` instead: the round is void, the ballot is permanently untabulatable, no vote cast on
        it is ever counted, and the cycle must construct a replacement ballot for the same
        `round_number`.

        Design: Corner/endpoints/ballot_close_after_closes_at_expires_the_round_instead_of_closing_it
        """
        assert world["closed"]["voting_status"] == "EXPIRED"
        assert world["closed"]["tally_status"] == "NOT_TALLIED"
        assert world["closed"]["ballots_cast"] == 1

    def test_the_void_round_still_snapshots_the_roster_and_holds_the_round_number(self, api, world):
        """Both outcomes snapshot `credentialed_roster_at_close` — the count of elector rows whose
        `status` is `CREDENTIALED` and whose `credential_expires_on` is at or after the closing
        instant — and both increment the ballot's `version` by 1.

        Design: Corner/endpoints/ballot_close_after_closes_at_expires_the_round_instead_of_closing_it
        """
        assert world["closed"]["credentialed_roster_at_close"] == 2
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["status"] == "BALLOTING"
        assert cycle["current_round"] == 1


class TestCandidacyReadAfterTheAudit:
    """The candidacy read is a view of figures written by somebody else."""

    @pytest.fixture
    def world(self, api):
        """A certified count on a one-slot ballot, before the election is certified."""
        return build_election_world(
            api, stage="audited", elector_count=2, candidate_count=1, votes=[(0, [0]), (1, [0])]
        )

    def test_the_certified_count_is_copied_onto_the_candidacy(self, api, world):
        """Certification then copies each scored candidacy's figures back onto the candidacy itself:
        `latest_round_votes` takes its slot's `votes_received` and `latest_round_pct` takes its slot's
        `vote_pct`, rounded to two decimal places.

        Design: Corner/endpoints/candidacy_read_exposes_the_scores_copied_by_the_certification
        """
        candidacy = read_candidacy(api, world["candidacies"][0]["id"])
        assert candidacy["latest_round_votes"] == 2
        assert candidacy["latest_round_pct"] == pytest.approx(1.00, abs=0.005)

    def test_the_candidacy_is_still_on_the_ballot_with_its_nomination_figures(self, api, world):
        """The full candidacy lifecycle spans `SUBMITTED`, `SCREENING`, `INFO_REQUESTED`, `ADVANCED`,
        `REJECTED`, `DEFERRED`, `ON_BALLOT`, `ELECTED`, `CARRYOVER_ELIGIBLE`, `EXPIRED`, `ELIMINATED`
        and `STRUCK`.

        Design: Corner/endpoints/candidacy_read_exposes_the_scores_copied_by_the_certification
        """
        candidacy = read_candidacy(api, world["candidacies"][0]["id"])
        assert candidacy["status"] == "ON_BALLOT"
        assert candidacy["appearance_number"] == 1
        assert candidacy["eligible_from_year"] == 2023

    def test_the_slot_says_elected_while_the_candidate_is_not_yet_inducted(self, api, world):
        """Take the same house `election_threshold_pct`, multiply it by the ballot's frozen
        `credentialed_roster_at_close`, round the product up to the next whole vote, and store it as
        `threshold_votes_final`.

        Design: Corner/endpoints/candidacy_read_exposes_the_scores_copied_by_the_certification
        """
        assert read_slot(api, slot_of(world, 0)["id"])["status"] == "ELECTED"
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["threshold_votes_final"] == 2
        assert ballot["outcome"] == "ELECTION_COMPLETE"
        assert read_candidate(api, world["candidates"][0]["id"])["hof_status"] == "NOT_INDUCTED"


class TestInstallationJoinsTwoSubsystems:
    """The junction row between an induction and a case built by different roles."""

    @pytest.fixture
    def world(self, api):
        """A certified inductee with artifacts in hand and an empty ten-artifact case."""
        world = build_election_world(
            api,
            stage="certified",
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
        )
        world["induction"] = induction_of(world, 0)
        setup_artifact_intake(api, world["induction"]["id"], artifact_count=4)
        world["case"] = setup_exhibit_case(api, case_code="CASE-J")
        world["installation"] = validate_success(
            api.create_exhibit_installation(
                create_exhibit_installation_payload(
                    world["induction"]["id"], world["case"]["id"], artifact_count=2
                ),
                CURATOR_HEADERS,
            ),
            201,
        )
        return world

    def test_the_row_resolves_both_sides_and_moves_them(self, api, world):
        """On success the installation is written with `status` `INSTALLED`, the case's
        `artifacts_installed` increases by the new `artifact_count`, and the induction's
        `exhibit_status` moves `NOT_PLANNED` → `INSTALLED` if this is the first installation for that
        induction.

        Design: Corner/endpoints/installation_links_the_induction_and_the_case_and_moves_both_sides
        """
        installation = world["installation"]
        assert installation["induction_id"] == world["induction"]["id"]
        assert installation["exhibit_case_id"] == world["case"]["id"]
        assert installation["status"] == "INSTALLED"
        assert installation["artifact_count"] == 2
        assert read_case(api, world["case"]["id"])["artifacts_installed"] == 2
        induction = read_induction(api, world["induction"]["id"])
        assert induction["exhibit_status"] == "INSTALLED"
        assert induction["ceremony_ready"] is False

    def test_the_row_is_reachable_from_either_side(self, api, world):
        """The payload names the `induction_id`, the `exhibit_case_id`, the window's inclusive start
        `display_starts_on`, its exclusive end `display_ends_on`, and the `artifact_count` occupying
        case capacity for this window (at least 1).

        Design: Corner/endpoints/installation_links_the_induction_and_the_case_and_moves_both_sides
        """
        by_induction, induction_meta = validate_paginated(
            api.list_exhibit_installations(
                CURATOR_HEADERS, {"induction_id": world["induction"]["id"], "limit": 100}
            )
        )
        by_case, case_meta = validate_paginated(
            api.list_exhibit_installations(
                CURATOR_HEADERS, {"exhibit_case_id": world["case"]["id"], "limit": 100}
            )
        )
        assert induction_meta["total_count"] == 1
        assert case_meta["total_count"] == 1
        assert by_induction[0]["id"] == world["installation"]["id"]
        assert by_case[0]["id"] == world["installation"]["id"]


class TestAuditRejectionInvalidatesTheWholeList:
    """The one bulk input in the API, applied to two counted submissions at once."""

    @pytest.fixture
    def world(self, api):
        """A drafted tally of two submissions, both naming the single listed slot."""
        world = build_election_world(
            api, stage="tallied", elector_count=2, candidate_count=1, votes=[(0, [0]), (1, [0])]
        )
        world["rejected"] = validate_success(
            api.create_audit_decision(
                world["ballot"]["id"],
                create_audit_decision_payload(
                    "REJECT",
                    invalidate_submission_ids=[s["id"] for s in world["submissions"]],
                    audit_note="Both credentials failed the audit",
                ),
                AUDITOR_HEADERS,
            ),
            200,
        )
        return world

    def test_every_named_submission_is_invalidated_with_the_note(self, api, world):
        """Every submission whose identifier appears in `invalidate_submission_ids` moves `COUNTED` →
        `INVALIDATED` and stores the auditor's `audit_note` as its `invalidated_reason`.

        Design: Corner/endpoints/audit_rejection_invalidates_every_submission_in_the_list
        """
        assert world["rejected"]["tally_status"] == "AUDIT_REJECTED"
        for submission in world["submissions"]:
            stored = read_submission(api, submission["id"])
            assert stored["status"] == "INVALIDATED"
            assert stored["invalidated_reason"] == "Both credentials failed the audit"

    def test_the_two_hop_arithmetic_drains_every_figure(self, api, world):
        """Each invalidation decrements the ballot's `ballots_cast` by 1 and reduces its
        `total_selections_counted` by that submission's `selection_count`. Each of those reductions in
        turn reduces `votes_received` on every slot the invalidated submission had selected and
        re-derives that slot's `vote_pct` against the new `ballots_cast`.

        Design: Corner/endpoints/audit_rejection_invalidates_every_submission_in_the_list
        """
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["ballots_cast"] == 0
        assert ballot["total_selections_counted"] == 0
        slot = read_slot(api, slot_of(world, 0)["id"])
        assert slot["votes_received"] == 0
        assert slot["vote_pct"] == pytest.approx(0.0, abs=0.005)

    def test_the_rejection_releases_the_count_for_a_retally(self, api, world):
        """The rejection then resets `threshold_votes_provisional` to 0 and clears
        `tallied_by_user_id`, which is what allows a re-tally — possibly by a different administrator —
        to claim the count afresh.

        Design: Corner/endpoints/audit_rejection_invalidates_every_submission_in_the_list
        """
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["threshold_votes_provisional"] == 0
        assert ballot["tallied_by_user_id"] is None
        assert ballot["voting_status"] == "CLOSED"


class TestWithdrawalFreesTheElectorToRecast:
    """The only compensating action an elector may take on their own submission."""

    @pytest.fixture
    def world(self, api):
        """One elector has cast, withdrawn, and cast again on the same open ballot."""
        world = build_election_world(
            api, stage="voted", elector_count=2, candidate_count=1, votes=[(0, [0])]
        )
        world["first"] = world["submissions"][0]
        world["withdrawal"] = validate_success(
            api.withdraw_vote_submission(world["first"]["id"], elector_headers(world, 0)), 200
        )
        world["ballot_version"] = world["withdrawal"]["ballot_version_after"]
        world["second"] = validate_success(
            api.create_vote_submission(
                create_vote_submission_payload(
                    world["ballot"]["id"], [slot_of(world, 0)["id"]], world["ballot_version"]
                ),
                elector_headers(world, 0),
            ),
            201,
        )
        return world

    def test_the_same_elector_may_cast_a_replacement(self, api, world):
        """Because the duplicate-submission check ignores `WITHDRAWN` rows, withdrawal frees the
        elector to cast a replacement on the same ballot — which is the whole point of the state.

        Design: Corner/endpoints/withdrawn_submission_frees_the_elector_to_recast_on_the_same_ballot
        """
        assert read_submission(api, world["first"]["id"])["status"] == "WITHDRAWN"
        replacement = read_submission(api, world["second"]["id"])
        assert replacement["status"] == "COUNTED"
        assert replacement["elector_id"] == world["electors"][0]["id"]
        assert world["second"]["ballot_version_after"] > world["withdrawal"]["ballot_version_after"]

    def test_the_counters_show_exactly_one_live_submission(self, api, world):
        """The submission moves `COUNTED` → `WITHDRAWN`, the ballot's `ballots_cast` decreases by 1 and
        its `total_selections_counted` decreases by exactly that submission's `selection_count`, and
        the ballot's `version` increments by 1 with the new value reported in `ballot_version_after`.

        Design: Corner/endpoints/withdrawn_submission_frees_the_elector_to_recast_on_the_same_ballot
        """
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["ballots_cast"] == 1
        assert ballot["total_selections_counted"] == 1

    def test_both_rows_survive_but_only_one_is_counted(self, api, world):
        """Counting itself considers only submissions whose `status` is `COUNTED`; `WITHDRAWN` and
        `INVALIDATED` submissions are excluded from every figure.

        Design: Corner/endpoints/withdrawn_submission_frees_the_elector_to_recast_on_the_same_ballot
        """
        _, all_meta = validate_paginated(
            api.list_vote_submissions(
                AUDITOR_HEADERS,
                {
                    "ballot_id": world["ballot"]["id"],
                    "elector_id": world["electors"][0]["id"],
                    "limit": 100,
                },
            )
        )
        _, counted_meta = validate_paginated(
            api.list_vote_submissions(
                AUDITOR_HEADERS,
                {"ballot_id": world["ballot"]["id"], "status": "COUNTED", "limit": 100},
            )
        )
        assert all_meta["total_count"] == 2
        assert counted_meta["total_count"] == 1


class TestCycleReadShowsTheRecomputedTier:
    """Two derived figures meet on the cycle read: the commitment and the tier."""

    @pytest.fixture
    def world(self, api):
        """A 100,000-cent ceremony budget carrying one approved three-night living grant."""
        world = build_election_world(
            api,
            stage="ceremony",
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
            ceremony_overrides={"travel_budget_cents": 100000},
        )
        world["induction"] = induction_of(world, 0)
        world["grant"] = request_travel_grant(
            world, world["induction"]["id"], nights=3, requested_airfare_cents=0
        )
        approve_travel_grant(world, world["grant"]["id"])
        return world

    def test_the_grant_freezes_the_pre_commitment_tier(self, api, world):
        """The grant's `cycle_id` is copied from the induction, its `variant` and `traveler_count` are
        derived from the induction's frozen `delegation_type`, its `austerity_tier_applied` is frozen
        from the cycle's pre-commitment tier, its `status` is `REQUESTED`, and its
        `cancellation_reason` is unset.

        Design: Corner/endpoints/cycle_read_exposes_the_austerity_tier_recomputed_from_the_commitment
        """
        grant = read_grant(api, world["grant"]["id"])
        assert grant["award_cents"] == 54999
        assert grant["austerity_tier_applied"] == "FULL"
        assert grant["variant"] == "LIVING_INDUCTEE"
        assert grant["traveler_count"] == 1
        assert grant["status"] == "APPROVED"

    def test_the_cycle_read_reports_the_tier_the_commitment_produced(self, api, world):
        """A ratio below one half yields the `FULL` tier; a ratio from one half up to but not including
        four fifths yields `REDUCED`; a ratio of four fifths or more yields `MINIMAL`.

        Design: Corner/endpoints/cycle_read_exposes_the_austerity_tier_recomputed_from_the_commitment
        """
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["travel_budget_cents"] == 100000
        assert cycle["travel_committed_cents"] == 54999
        assert cycle["austerity_tier"] == "REDUCED"

    def test_funding_the_travel_alone_leaves_the_inductee_unready(self, api, world):
        """That transition requires the induction's `artifact_status` to be `RECEIVED`, recomputes
        `ceremony_ready`, and increments the cycle's `ceremony_ready_count` by 1 when readiness flips
        to true.

        Design: Corner/endpoints/cycle_read_exposes_the_austerity_tier_recomputed_from_the_commitment
        """
        induction = read_induction(api, world["induction"]["id"])
        assert induction["travel_status"] == "APPROVED"
        assert induction["ceremony_ready"] is False
        assert read_cycle(api, world["cycle"]["id"])["ceremony_ready_count"] == 0


class TestArtifactIntakeTakesTwoBranches:
    """One endpoint, one dimension, two destinations chosen by a flag in the body."""

    @pytest.fixture
    def world(self, api):
        """A half-threshold cycle that elected both nominees, so two inductions await artifacts."""
        world = build_election_world(
            api,
            stage="certified",
            rules=[{"election_threshold_pct": 0.5}],
            elector_count=2,
            candidate_count=2,
            votes=[(0, [0]), (1, [1])],
        )
        world["first"] = induction_of(world, 0)
        world["second"] = induction_of(world, 1)
        return world

    def test_the_exempt_branch_records_nothing_donated(self, api, world):
        """When the induction is exempt, `artifact_status` moves `AWAITED` → `EXEMPT` and
        `artifact_count` stays at 0.

        Design: Corner/endpoints/artifact_intake_exempt_and_received_branches_on_the_same_endpoint
        """
        exempt = validate_success(
            api.create_artifact_intake(world["first"]["id"], {"is_exempt": True}, CURATOR_HEADERS),
            200,
        )
        assert exempt["artifact_status"] == "EXEMPT"
        assert exempt["artifact_count"] == 0
        assert exempt["exhibit_status"] == "NOT_PLANNED"

    def test_the_default_branch_stores_the_donated_count(self, api, world):
        """When artifacts are donated, `artifact_status` moves `AWAITED` → `RECEIVED` and the
        induction's `artifact_count` is set to the number supplied.

        Design: Corner/endpoints/artifact_intake_exempt_and_received_branches_on_the_same_endpoint
        """
        received = validate_success(
            api.create_artifact_intake(
                world["second"]["id"], {"artifact_count": 3}, CURATOR_HEADERS
            ),
            200,
        )
        assert received["artifact_status"] == "RECEIVED"
        assert received["artifact_count"] == 3

    def test_neither_branch_reaches_readiness_while_travel_is_pending(self, api, world):
        """Concretely: `travel_status` must be either `APPROVED` or `WAIVED`; and either
        `artifact_status` is `RECEIVED` with `exhibit_status` at `INSTALLED`, or `artifact_status` is
        `EXEMPT` — an exempt induction has nothing to display and is ready without any installation.

        Design: Corner/endpoints/artifact_intake_exempt_and_received_branches_on_the_same_endpoint
        """
        validate_success(
            api.create_artifact_intake(world["first"]["id"], {"is_exempt": True}, CURATOR_HEADERS),
            200,
        )
        validate_success(
            api.create_artifact_intake(
                world["second"]["id"], {"artifact_count": 3}, CURATOR_HEADERS
            ),
            200,
        )
        assert read_induction(api, world["first"]["id"])["ceremony_ready"] is False
        assert read_induction(api, world["second"]["id"])["ceremony_ready"] is False
        cycle = read_cycle(api, world["cycle"]["id"])
        assert cycle["induction_count"] == 2
        assert cycle["ceremony_ready_count"] == 0

    def test_the_two_slot_round_elected_both_nominees_on_one_vote_each(self, api, world):
        """The ballot's `elected_slot_count` is the size of the elected set.

        Design: Corner/endpoints/artifact_intake_exempt_and_received_branches_on_the_same_endpoint
        """
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["max_votes_per_elector"] == 1
        assert ballot["elected_slot_count"] == 2
