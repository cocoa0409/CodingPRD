"""Legal transitions, refused transitions, and the side effects each one fires."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    CURATOR_HEADERS,
    TEST_DEFAULTS,
    assert_same_instant,
    build_election_world,
    create_exhibit_installation_payload,
    induction_of,
    read_bloc,
    read_candidacy,
    read_case,
    read_cycle,
    read_elector,
    read_induction,
    read_slot,
    set_clock,
    setup_artifact_intake,
    setup_ceremony_ready_world,
    setup_cycle,
    setup_eligibility_rule,
    setup_elector,
    setup_exhibit_case,
    setup_voter_bloc,
    validate_error,
    validate_success,
)


class TestOpeningNominations:
    """SETUP → NOMINATIONS_OPEN, and the criteria table it depends on."""

    def test_opening_intake_snapshots_the_roster_and_bumps_the_version(self, api):
        """The transition recomputes `credentialed_roster_count` from the live elector roster and
        increments the cycle's `version` by 1.

        Design: Corner/state_machines/open_nominations_moves_setup_to_nominations_open
        """
        world = build_election_world(api, stage="setup", elector_count=1, candidate_count=1)
        assert world["cycle"]["status"] == "SETUP"
        assert world["cycle"]["version"] == 1
        cycle = validate_success(api.open_nominations(world["cycle"]["id"], ADMIN_HEADERS), 200)
        assert cycle["status"] == "NOMINATIONS_OPEN"
        assert cycle["credentialed_roster_count"] == 1
        assert cycle["version"] == 2
        assert cycle["current_round"] == 0

    def test_intake_will_not_open_before_the_criteria_are_published(self, api):
        """Opening nominations moves the cycle from `SETUP` to `NOMINATIONS_OPEN`, and it will not
        proceed while the eligibility-rule table is empty: a cycle whose criteria have not been
        published yet is refused with `ERR_ELIGIBILITY_RULE_NOT_FOUND` (HTTP 404).

        Design: Corner/state_machines/open_nominations_without_any_eligibility_rule_rejected
        """
        cycle = setup_cycle(api)
        validate_error(
            api.open_nominations(cycle["id"], ADMIN_HEADERS),
            "ERR_ELIGIBILITY_RULE_NOT_FOUND",
            404,
        )
        refused = read_cycle(api, cycle["id"])
        assert refused["status"] == "SETUP"
        assert refused["version"] == 1


class TestClosingNominations:
    """NOMINATIONS_OPEN → SCREENING sweeps the intake queue; SETUP cannot reach it."""

    def test_every_submitted_candidacy_is_swept_into_screening(self, api):
        """Closing nominations moves the cycle from `NOMINATIONS_OPEN` to `SCREENING` and sweeps the
        intake queue into the committee's hands: every candidacy of that cycle still in `SUBMITTED`
        is transitioned to `SCREENING`, processed in ascending `created_at` order, and each swept
        candidacy has its own `version` incremented by 1.

        Design: Corner/state_machines/close_nominations_sweeps_submitted_candidacies_to_screening
        """
        world = build_election_world(
            api, stage="nominated", elector_count=2, candidate_count=2
        )
        for candidacy in world["candidacies"]:
            assert candidacy["status"] == "SUBMITTED"
            assert candidacy["version"] == 1
        validate_success(api.close_nominations(world["cycle"]["id"], ADMIN_HEADERS), 200)
        for candidacy in world["candidacies"]:
            swept = read_candidacy(api, candidacy["id"])
            assert swept["status"] == "SCREENING"
            assert swept["version"] == 2

    def test_the_sweep_moves_the_cycle_and_leaves_the_advance_counter_alone(self, api):
        """The cycle's `version` is incremented by 1 as well. A candidacy filed but never swept
        cannot exist — after this transition the cycle holds no `SUBMITTED` rows.

        Design: Corner/state_machines/close_nominations_sweeps_submitted_candidacies_to_screening
        """
        world = build_election_world(
            api, stage="nominated", elector_count=2, candidate_count=2
        )
        before = read_cycle(api, world["cycle"]["id"])
        cycle = validate_success(api.close_nominations(world["cycle"]["id"], ADMIN_HEADERS), 200)
        assert cycle["status"] == "SCREENING"
        assert cycle["version"] == before["version"] + 1
        assert cycle["nomination_count"] == 2
        assert cycle["advanced_candidacy_count"] == 0

    def test_a_setup_cycle_cannot_close_an_intake_it_never_opened(self, api):
        """Any write that addresses a cycle whose `status` is not the from-state that write requires
        is refused with `ERR_INVALID_CYCLE_STATE` (HTTP 409) — `SETUP` is required to open
        nominations, `NOMINATIONS_OPEN` to close them and to file a nomination, `SCREENING` to
        record a screening decision and to construct the first ballot, `BALLOTING` to certify the
        election, `CERTIFIED` to plan the ceremony, and `CEREMONY_PLANNED` to hold it.

        Design: Corner/state_machines/close_nominations_on_setup_cycle_rejected
        """
        setup_eligibility_rule(api)
        cycle = setup_cycle(api)
        validate_error(
            api.close_nominations(cycle["id"], ADMIN_HEADERS), "ERR_INVALID_CYCLE_STATE", 409
        )
        refused = read_cycle(api, cycle["id"])
        assert refused["status"] == "SETUP"
        assert refused["version"] == 1


class TestCredentiallingAnElector:
    """PROVISIONAL → CREDENTIALED, and the seat arithmetic behind it."""

    def test_a_new_elector_is_provisional_and_holds_no_seat_yet(self, api):
        """A new elector begins in `PROVISIONAL` standing with `consecutive_missed_cycles` at 0,
        `last_participated_cycle_year` unset and `suspension_reason` unset.

        Design: Corner/state_machines/elector_starts_provisional_and_credential_fills_the_seat
        """
        bloc = setup_voter_bloc(api, seat_cap=4)
        elector = setup_elector(api, bloc["id"], credential=False)
        assert elector["status"] == "PROVISIONAL"
        assert elector["consecutive_missed_cycles"] == 0
        assert elector["last_participated_cycle_year"] is None
        assert elector["suspension_reason"] is None
        assert read_bloc(api, bloc["id"])["seats_filled"] == 0

    def test_credentialling_fills_the_seat(self, api):
        """On success the bloc's `seats_filled` increases by 1, and `credentialed_roster_count` is
        recomputed for every cycle whose `status` is `NOMINATIONS_OPEN`, `SCREENING` or
        `BALLOTING` — that counter is the number of elector rows whose `status` is `CREDENTIALED`
        and whose `credential_expires_on` is at or after the logical clock's current instant.

        Design: Corner/state_machines/elector_starts_provisional_and_credential_fills_the_seat
        """
        bloc = setup_voter_bloc(api, seat_cap=4)
        elector = setup_elector(api, bloc["id"], credential=False)
        credentialed = validate_success(api.credential_elector(elector["id"], ADMIN_HEADERS), 200)
        assert credentialed["status"] == "CREDENTIALED"
        assert credentialed["consecutive_missed_cycles"] == 0
        assert credentialed["last_participated_cycle_year"] is None
        assert credentialed["suspension_reason"] is None
        assert read_bloc(api, bloc["id"])["seats_filled"] == 1

    def test_a_second_credential_on_the_same_elector_is_refused(self, api):
        """An operation addressing an elector who is not in the required from-state —
        `PROVISIONAL` for credentialing, `CREDENTIALED` for suspension, `SUSPENDED` for
        reinstatement — is refused with `ERR_INVALID_ELECTOR_STATE` (HTTP 409).

        Design: Corner/state_machines/second_credential_grant_on_same_elector_rejected
        """
        bloc = setup_voter_bloc(api, seat_cap=4)
        elector = setup_elector(api, bloc["id"])
        validate_error(
            api.credential_elector(
                elector["id"], ADMIN_HEADERS, {"credential_expires_on": "2028-12-31T00:00:00Z"}
            ),
            "ERR_INVALID_ELECTOR_STATE",
            409,
        )
        row = read_elector(api, elector["id"])
        assert row["status"] == "CREDENTIALED"
        assert_same_instant(
            row["credential_expires_on"],
            TEST_DEFAULTS["CREDENTIAL_EXPIRES_ON"],
            "credential_expires_on",
        )
        assert read_bloc(api, bloc["id"])["seats_filled"] == 1

    def test_reinstating_a_credentialed_elector_is_refused(self, api):
        """Suspension and reinstatement close a loop that a working voting body runs constantly:
        `CREDENTIALED` → `SUSPENDED` → `CREDENTIALED`.

        Design: Corner/state_machines/reinstate_on_credentialed_elector_rejected
        """
        bloc = setup_voter_bloc(api, seat_cap=4)
        elector = setup_elector(api, bloc["id"])
        validate_error(
            api.reinstate_elector(elector["id"], ADMIN_HEADERS), "ERR_INVALID_ELECTOR_STATE", 409
        )
        assert read_elector(api, elector["id"])["status"] == "CREDENTIALED"
        assert read_bloc(api, bloc["id"])["seats_filled"] == 1

    def test_a_full_bloc_refuses_the_next_credential(self, api):
        """The bloc must have room — its `seats_filled` must be strictly below its `seat_cap`, and a
        full bloc is refused with `ERR_BLOC_SEATS_EXHAUSTED` (HTTP 409).

        Design: Corner/state_machines/credential_blocked_when_bloc_seats_are_exhausted
        """
        bloc = setup_voter_bloc(api, seat_cap=1)
        first = setup_elector(api, bloc["id"], full_name="Elector One")
        second = setup_elector(
            api, bloc["id"], credential=False, full_name="Elector Two"
        )
        validate_error(
            api.credential_elector(second["id"], ADMIN_HEADERS),
            "ERR_BLOC_SEATS_EXHAUSTED",
            409,
        )
        assert read_elector(api, second["id"])["status"] == "PROVISIONAL"
        assert read_elector(api, first["id"])["status"] == "CREDENTIALED"
        assert read_bloc(api, bloc["id"])["seats_filled"] == 1


class TestSuspensionLoop:
    """CREDENTIALED → SUSPENDED → CREDENTIALED against a live roster count."""

    REASON = "Ballot leak under review"

    @pytest.fixture
    def world(self, api):
        """A NOMINATIONS_OPEN cycle whose two electors are both credentialed."""
        return build_election_world(
            api, stage="nominations_open", elector_count=2, candidate_count=1
        )

    def test_suspension_stores_the_reason_and_lowers_only_the_roster_count(self, api, world):
        """It deliberately does **not** free the bloc seat — a suspended elector still occupies one,
        so `seats_filled` is unchanged — but it does recompute `credentialed_roster_count` on every
        cycle in `NOMINATIONS_OPEN`, `SCREENING` or `BALLOTING`, because a suspended elector is no
        longer part of the credentialed roster.

        Design: Corner/state_machines/suspension_keeps_the_bloc_seat_but_drops_the_roster_count
        """
        assert world["cycle"]["credentialed_roster_count"] == 2
        suspended = validate_success(
            api.suspend_elector(
                world["electors"][1]["id"], {"suspension_reason": self.REASON}, ADMIN_HEADERS
            ),
            200,
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == self.REASON
        assert read_cycle(api, world["cycle"]["id"])["credentialed_roster_count"] == 1
        assert read_bloc(api, world["bloc"]["id"])["seats_filled"] == 2

    def test_reinstatement_closes_the_loop_and_restores_the_roster(self, api, world):
        """Reinstating a suspended elector returns them to `CREDENTIALED`, clears
        `suspension_reason`, accepts an optional replacement `credential_expires_on`, requires that
        the resulting `credential_expires_on` be strictly later than the logical clock's current
        instant, and again recomputes `credentialed_roster_count` on those same three cycle phases.

        Design: Corner/state_machines/suspension_keeps_the_bloc_seat_but_drops_the_roster_count
        """
        validate_success(
            api.suspend_elector(
                world["electors"][1]["id"], {"suspension_reason": self.REASON}, ADMIN_HEADERS
            ),
            200,
        )
        reinstated = validate_success(
            api.reinstate_elector(world["electors"][1]["id"], ADMIN_HEADERS), 200
        )
        assert reinstated["status"] == "CREDENTIALED"
        assert reinstated["suspension_reason"] is None
        assert read_cycle(api, world["cycle"]["id"])["credentialed_roster_count"] == 2
        assert read_bloc(api, world["bloc"]["id"])["seats_filled"] == 2


class TestDraftTallySideEffects:
    """One tally call fires every declared side effect at once."""

    @pytest.fixture
    def world(self, api):
        """A closed single-slot ballot carrying two counted submissions."""
        return build_election_world(
            api,
            stage="voting_closed",
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
        )

    def test_the_tally_scores_every_listed_slot(self, api, world):
        """Then, for each slot of the ballot whose `status` is `LISTED`, `votes_received` becomes the
        number of counted submissions whose `selected_slot_ids` contains that slot's identifier, and
        `vote_pct` becomes `votes_received` divided by `ballots_cast`, rounded half-up to two
        decimal places — or exactly 0 when `ballots_cast` is 0.

        Design: Corner/state_machines/tally_side_effects_set_slot_counts_and_provisional_threshold
        """
        validate_success(api.tally_ballot(world["ballot"]["id"], ADMIN_HEADERS), 200)
        slot = read_slot(api, world["slot_list"][0]["id"])
        assert slot["votes_received"] == 2
        assert slot["vote_pct"] == pytest.approx(1.0, abs=0.01)

    def test_the_tally_stamps_the_operator_and_the_provisional_threshold(self, api, world):
        """Finally the draft tally records `tallied_by_user_id` as the acting administrator's
        `X-User-ID`, moves `tally_status` from `NOT_TALLIED` (or `AUDIT_REJECTED`) to
        `PENDING_AUDIT`, and increments the ballot's `version` by 1.

        Design: Corner/state_machines/tally_side_effects_set_slot_counts_and_provisional_threshold
        """
        ballot = validate_success(api.tally_ballot(world["ballot"]["id"], ADMIN_HEADERS), 200)
        assert ballot["tally_status"] == "PENDING_AUDIT"
        assert ballot["voting_status"] == "CLOSED"
        assert ballot["ballots_cast"] == 2
        assert ballot["total_selections_counted"] == 2
        assert ballot["credentialed_roster_at_close"] == 2
        assert ballot["threshold_votes_provisional"] == 2
        assert ballot["tallied_by_user_id"] == "admin-1"
        assert ballot["version"] == world["ballot"]["version"] + 1


class TestExhibitInstallationGuardedByIntake:
    """The exhibit dimension will not move until the artifact dimension has."""

    WINDOW = ("2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")

    @pytest.fixture
    def world(self, api):
        """A certified cycle with one induction and an empty ten-artifact case."""
        world = build_election_world(
            api,
            stage="certified",
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
        )
        world["case"] = setup_exhibit_case(
            api, case_code="HALLA", capacity_artifacts=10, changeover_buffer_days=5
        )
        world["induction"] = induction_of(world, 0)
        return world

    def _install(self, api, world, count=3):
        return api.create_exhibit_installation(
            create_exhibit_installation_payload(
                world["induction"]["id"],
                world["case"]["id"],
                display_starts_on=self.WINDOW[0],
                display_ends_on=self.WINDOW[1],
                artifact_count=count,
            ),
            CURATOR_HEADERS,
        )

    def test_an_installation_before_the_intake_is_refused(self, api, world):
        """The induction's artifacts must actually be in hand: `artifact_status` must be
        `RECEIVED`, and an installation requested while it is `AWAITED` or `EXEMPT` is refused with
        `ERR_ARTIFACTS_NOT_RECEIVED` (HTTP 409).

        Design: Corner/state_machines/exhibit_install_guarded_by_artifact_intake
        """
        assert world["induction"]["artifact_status"] == "AWAITED"
        assert world["induction"]["exhibit_status"] == "NOT_PLANNED"
        validate_error(self._install(api, world), "ERR_ARTIFACTS_NOT_RECEIVED", 409)
        assert read_case(api, world["case"]["id"])["artifacts_installed"] == 0

    def test_recording_the_intake_unblocks_the_identical_call(self, api, world):
        """When artifacts are donated, `artifact_status` moves `AWAITED` → `RECEIVED` and the
        induction's `artifact_count` is set to the number supplied.

        Design: Corner/state_machines/exhibit_install_guarded_by_artifact_intake
        """
        validate_error(self._install(api, world), "ERR_ARTIFACTS_NOT_RECEIVED", 409)
        received = setup_artifact_intake(api, world["induction"]["id"], artifact_count=3)
        assert received["artifact_status"] == "RECEIVED"
        assert received["artifact_count"] == 3
        installation = validate_success(self._install(api, world), 201)
        assert installation["status"] == "INSTALLED"
        assert read_case(api, world["case"]["id"])["artifacts_installed"] == 3
        assert read_induction(api, world["induction"]["id"])["exhibit_status"] == "INSTALLED"

    def test_the_exhibit_dimension_alone_does_not_make_the_ceremony_ready(self, api, world):
        """Concretely: `travel_status` must be either `APPROVED` or `WAIVED`; and either
        `artifact_status` is `RECEIVED` with `exhibit_status` at `INSTALLED`, or `artifact_status` is
        `EXEMPT` — an exempt induction has nothing to display and is ready without any installation.

        Design: Corner/state_machines/exhibit_install_guarded_by_artifact_intake
        """
        setup_artifact_intake(api, world["induction"]["id"], artifact_count=3)
        validate_success(self._install(api, world), 201)
        induction = read_induction(api, world["induction"]["id"])
        assert induction["travel_status"] == "PENDING"
        assert induction["exhibit_status"] == "INSTALLED"
        assert induction["ceremony_ready"] is False
        assert read_cycle(api, world["cycle"]["id"])["ceremony_ready_count"] == 0


class TestWithdrawingOneOfTwoInstallations:
    """The exhibit cascade fires only when the last installed window goes away."""

    WINDOW = ("2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")

    @pytest.fixture
    def world(self, api):
        """A ceremony-planned induction with approved travel and two installed windows."""
        world = setup_ceremony_ready_world(
            api,
            exempt_artifacts=False,
            nights=3,
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
        )
        world["induction"] = induction_of(world, 0)
        world["case_a"] = setup_exhibit_case(
            api, case_code="HALLA", capacity_artifacts=10, changeover_buffer_days=5
        )
        world["case_b"] = setup_exhibit_case(
            api, case_code="HALLB", capacity_artifacts=10, changeover_buffer_days=5
        )
        for key in ("case_a", "case_b"):
            world[key + "_installation"] = validate_success(
                api.create_exhibit_installation(
                    create_exhibit_installation_payload(
                        world["induction"]["id"],
                        world[key]["id"],
                        display_starts_on=self.WINDOW[0],
                        display_ends_on=self.WINDOW[1],
                        artifact_count=2,
                    ),
                    CURATOR_HEADERS,
                ),
                201,
            )
        return world

    def test_the_first_withdrawal_leaves_the_dimension_installed(self, api, world):
        """If no other installation of that induction is still `INSTALLED`, the induction's
        `exhibit_status` moves `INSTALLED` → `NOT_PLANNED`, which recomputes `ceremony_ready` and
        decrements the cycle's `ceremony_ready_count` when readiness flips to false.

        Design: Corner/state_machines/withdrawing_one_of_two_installations_keeps_exhibit_status_installed
        """
        validate_success(
            api.withdraw_exhibit_installation(
                world["case_a_installation"]["id"], CURATOR_HEADERS
            ),
            200,
        )
        induction = read_induction(api, world["induction"]["id"])
        assert induction["exhibit_status"] == "INSTALLED"
        assert induction["ceremony_ready"] is True
        assert read_case(api, world["case_a"]["id"])["artifacts_installed"] == 0
        assert read_case(api, world["case_b"]["id"])["artifacts_installed"] == 2
        assert read_cycle(api, world["cycle"]["id"])["ceremony_ready_count"] == 1

    def test_the_second_withdrawal_flips_the_dimension_and_the_readiness(self, api, world):
        """Withdrawing an installation moves it `INSTALLED` → `WITHDRAWN`, requires the owning
        induction's `status` to still be `ANNOUNCED`, and is the exhibit counterpart of grant
        cancellation: the case's `artifacts_installed` decreases by exactly that installation's
        `artifact_count`, restoring the pre-installation occupancy precisely.

        Design: Corner/state_machines/withdrawing_one_of_two_installations_keeps_exhibit_status_installed
        """
        for key in ("case_a_installation", "case_b_installation"):
            withdrawn = validate_success(
                api.withdraw_exhibit_installation(world[key]["id"], CURATOR_HEADERS), 200
            )
            assert withdrawn["status"] == "WITHDRAWN"
        induction = read_induction(api, world["induction"]["id"])
        assert induction["exhibit_status"] == "NOT_PLANNED"
        assert induction["ceremony_ready"] is False
        assert induction["artifact_count"] == 2
        assert read_case(api, world["case_b"]["id"])["artifacts_installed"] == 0
        assert read_cycle(api, world["cycle"]["id"])["ceremony_ready_count"] == 0


class TestClosedCycleIsTerminal:
    """CEREMONY_PLANNED → CLOSED freezes the cycle and its inductions for good."""

    CEREMONY_INSTANT = "2026-11-15T18:00:00Z"

    @pytest.fixture
    def world(self, api):
        """A cycle held all the way to CLOSED with its single induction enshrined."""
        world = setup_ceremony_ready_world(
            api,
            exempt_artifacts=True,
            nights=3,
            elector_count=2,
            candidate_count=1,
            votes=[(0, [0]), (1, [0])],
        )
        world["induction"] = induction_of(world, 0)
        set_clock(api, self.CEREMONY_INSTANT)
        world["closed_cycle"] = validate_success(
            api.hold_ceremony(world["cycle"]["id"], ADMIN_HEADERS), 200
        )
        return world

    def test_holding_the_ceremony_closes_the_cycle_and_enshrines_the_induction(self, api, world):
        """On success the cycle moves `CEREMONY_PLANNED` → `CLOSED` and every induction of the cycle
        is driven `ANNOUNCED` → `ENSHRINED`, which freezes all three of its dimensions: no further
        travel, artifact or exhibit mutation is accepted on an enshrined induction.

        Design: Corner/state_machines/closed_cycle_and_enshrined_induction_reject_further_triggers
        """
        assert world["closed_cycle"]["status"] == "CLOSED"
        assert read_induction(api, world["induction"]["id"])["status"] == "ENSHRINED"

    def test_a_second_hold_ceremony_is_refused_and_freezes_the_version(self, api, world):
        """Any write that addresses a cycle whose `status` is not the from-state that write requires
        is refused with `ERR_INVALID_CYCLE_STATE` (HTTP 409).

        Design: Corner/state_machines/closed_cycle_and_enshrined_induction_reject_further_triggers
        """
        validate_error(
            api.hold_ceremony(world["cycle"]["id"], ADMIN_HEADERS), "ERR_INVALID_CYCLE_STATE", 409
        )
        after = read_cycle(api, world["cycle"]["id"])
        assert after["status"] == "CLOSED"
        assert after["version"] == world["closed_cycle"]["version"]

    def test_an_enshrined_induction_refuses_further_artifact_intake(self, api, world):
        """The three dimensions advance independently of one another, driven by three different
        workflows, and any mutation that addresses a dimension already past its from-state — or any
        mutation at all on an induction whose `status` is `ENSHRINED` — is refused with
        `ERR_INVALID_INDUCTION_STATE` (HTTP 409).

        Design: Corner/state_machines/closed_cycle_and_enshrined_induction_reject_further_triggers
        """
        validate_error(
            api.create_artifact_intake(
                world["induction"]["id"], {"artifact_count": 2}, CURATOR_HEADERS
            ),
            "ERR_INVALID_INDUCTION_STATE",
            409,
        )
        induction = read_induction(api, world["induction"]["id"])
        assert induction["artifact_status"] == "EXEMPT"
        assert induction["artifact_count"] == 0
