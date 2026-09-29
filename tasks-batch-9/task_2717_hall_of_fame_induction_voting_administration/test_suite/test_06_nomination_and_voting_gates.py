"""Validation priority and cross-entity standing on nomination and vote casting."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    CLOCK_EPOCH,
    build_election_world,
    create_candidacy_payload,
    create_vote_submission_payload,
    elector_headers,
    read_ballot,
    read_bloc,
    read_cycle,
    read_elector,
    read_slot,
    set_clock,
    setup_cycle,
    slot_of,
    assert_same_instant,
    validate_error,
    validate_success,
)

SUB_THRESHOLD_CANDIDATE = {
    "full_name": "Short Career",
    "retirement_year": 2018,
    "career_seasons": 5,
    "career_metric_value": 2500,
}

LATE_RETIREE = {
    "full_name": "Late Retiree",
    "retirement_year": 2021,
    "career_seasons": 15,
    "career_metric_value": 3000,
}

TWO_2017_RETIREES = [
    {
        "full_name": "Barred Player",
        "retirement_year": 2017,
        "career_seasons": 15,
        "career_metric_value": 3000,
    },
    {
        "full_name": "Clean Player",
        "retirement_year": 2017,
        "career_seasons": 14,
        "career_metric_value": 2800,
    },
]


class TestCycleStateOutranksCareerThreshold:
    """A sub-threshold candidate filed against a cycle still in SETUP."""

    @pytest.fixture
    def world(self, api):
        """A SETUP cycle, one credentialed elector and one under-qualified candidate."""
        return build_election_world(
            api, stage="setup", elector_count=1, candidate_specs=[SUB_THRESHOLD_CANDIDATE]
        )

    def _payload(self, world):
        return create_candidacy_payload(
            world["cycle"]["id"],
            world["candidates"][0]["id"],
            world["electors"][0]["id"],
        )

    def test_the_wrong_cycle_phase_is_reported_before_the_career_shortfall(self, api, world):
        """The service evaluates in ascending priority band and stops at the first failure.

        Design: Difficulty/priority_pair_validation_conflict/cycle_state_outranks_career_threshold_on_nomination
        """
        assert world["cycle"]["status"] == "SETUP"
        validate_error(
            api.create_candidacy(self._payload(world), ADMIN_HEADERS),
            "ERR_INVALID_CYCLE_STATE",
            409,
        )

    def test_the_same_body_reports_the_shortfall_once_nominations_open(self, api, world):
        """The candidate's `career_seasons` must be greater than or equal to the rule's
        `min_career_seasons`, and their `career_metric_value` must be greater than or equal to
        the rule's `min_career_metric`; both comparisons are inclusive at the boundary, and
        either shortfall is refused with `ERR_CAREER_THRESHOLD_NOT_MET` (HTTP 422).

        Design: Difficulty/priority_pair_validation_conflict/cycle_state_outranks_career_threshold_on_nomination
        """
        validate_error(
            api.create_candidacy(self._payload(world), ADMIN_HEADERS),
            "ERR_INVALID_CYCLE_STATE",
            409,
        )
        validate_success(api.open_nominations(world["cycle"]["id"], ADMIN_HEADERS), 200)
        validate_error(
            api.create_candidacy(self._payload(world), ADMIN_HEADERS),
            "ERR_CAREER_THRESHOLD_NOT_MET",
            422,
        )

    def test_neither_refusal_records_a_nomination(self, api, world):
        """Its creation increments the cycle's `nomination_count` by 1 and recomputes the cycle's
        `special_election_used`, which counts the cycle's candidacies whose `pathway` is
        `SPECIAL` and whose `status` is anything other than `REJECTED`.

        Design: Difficulty/priority_pair_validation_conflict/cycle_state_outranks_career_threshold_on_nomination
        """
        api.create_candidacy(self._payload(world), ADMIN_HEADERS)
        validate_success(api.open_nominations(world["cycle"]["id"], ADMIN_HEADERS), 200)
        api.create_candidacy(self._payload(world), ADMIN_HEADERS)
        assert read_cycle(api, world["cycle"]["id"])["nomination_count"] == 0


class TestExpiredCredentialOutranksStruckSlot:
    """A time-expired elector voting for a slot that has been struck."""

    @pytest.fixture
    def world(self, api):
        """An open ballot with one struck slot, and one elector whose credential has run out."""
        world = build_election_world(
            api,
            stage="ballot_open",
            elector_specs=[
                {"full_name": "Elector One", "is_screening_member": False},
                {"full_name": "Screener Two", "is_screening_member": True},
                {
                    "full_name": "Short Credential",
                    "is_screening_member": False,
                    "credential_expires_on": "2026-08-10T00:00:00Z",
                },
            ],
            candidate_count=2,
        )
        validate_success(
            api.declare_permanent_ineligibility(
                world["candidates"][0]["id"],
                {"permanently_ineligible_reason": "Barred by the review panel"},
                ADMIN_HEADERS,
            ),
            200,
        )
        set_clock(api, "2026-08-15T00:00:00Z")
        world["ballot"] = read_ballot(api, world["ballot"]["id"])
        return world

    def _struck_vote(self, world):
        return create_vote_submission_payload(
            world["ballot"]["id"], [slot_of(world, 0)["id"]], world["ballot"]["version"]
        )

    def test_the_expired_credential_is_reported_before_the_struck_slot(self, api, world):
        """Second, that elector's `credential_expires_on` must be at or after the logical clock's
        current instant; a lapsed-by-time credential is refused with `ERR_CREDENTIAL_EXPIRED`
        (HTTP 403).

        Design: Difficulty/priority_pair_validation_conflict/expired_credential_outranks_struck_slot_on_vote
        """
        validate_error(
            api.create_vote_submission(self._struck_vote(world), elector_headers(world, 2)),
            "ERR_CREDENTIAL_EXPIRED",
            403,
        )

    def test_a_live_credential_reaches_the_struck_slot_check(self, api, world):
        """Second, no selected slot may have a `status` of `STRUCK`; voting for a barred candidate
        is refused with `ERR_SLOT_STRUCK` (HTTP 409).

        Design: Difficulty/priority_pair_validation_conflict/expired_credential_outranks_struck_slot_on_vote
        """
        validate_error(
            api.create_vote_submission(self._struck_vote(world), elector_headers(world, 0)),
            "ERR_SLOT_STRUCK",
            409,
        )

    def test_neither_refusal_moves_the_ballot_or_the_elector(self, api, world):
        """The ballot's `version` increments by 1, and the new value is echoed back on the
        submission as `ballot_version_after` so that the next elector can supply a fresh
        `expected_ballot_version` without re-reading the ballot.

        Design: Difficulty/priority_pair_validation_conflict/expired_credential_outranks_struck_slot_on_vote
        """
        api.create_vote_submission(self._struck_vote(world), elector_headers(world, 2))
        api.create_vote_submission(self._struck_vote(world), elector_headers(world, 0))
        ballot = read_ballot(api, world["ballot"]["id"])
        assert ballot["version"] == 3
        assert ballot["slot_count"] == 1
        assert ballot["ballots_cast"] == 0
        assert read_elector(api, world["electors"][2]["id"])["status"] == "CREDENTIALED"
        assert read_slot(api, slot_of(world, 0)["id"])["status"] == "STRUCK"


class TestWaitingPeriodInclusiveBoundary:
    """A five-year wait that lands exactly on the cycle under test."""

    @pytest.fixture
    def world(self, api):
        """A 2026 cycle open for nominations, plus a candidate eligible from 2026."""
        return build_election_world(
            api, stage="nominations_open", elector_count=1, candidate_specs=[LATE_RETIREE]
        )

    def _payload(self, world, cycle_id):
        return create_candidacy_payload(
            cycle_id, world["candidates"][0]["id"], world["electors"][0]["id"]
        )

    def test_a_cycle_year_exactly_at_the_eligible_year_is_accepted(self, api, world):
        """Waiting is checked inclusively: the cycle's `cycle_year` must be greater than or equal
        to the computed `eligible_from_year`, and a cycle running earlier than that is refused
        with `ERR_WAITING_PERIOD_NOT_MET` (HTTP 422).

        Design: Difficulty/boundary_precision_check/waiting_period_inclusive_at_exact_eligible_year
        """
        candidacy = validate_success(
            api.create_candidacy(self._payload(world, world["cycle"]["id"]), ADMIN_HEADERS),
            201,
        )
        assert candidacy["eligible_from_year"] == 2026
        assert candidacy["status"] == "SUBMITTED"

    def test_a_cycle_year_one_below_the_eligible_year_is_refused(self, api, world):
        """**Years** are integers throughout, and every year comparison in the eligibility
        machinery — waiting periods, the veterans floor, career thresholds — is inclusive at the
        boundary.

        Design: Difficulty/boundary_precision_check/waiting_period_inclusive_at_exact_eligible_year
        """
        earlier = setup_cycle(api, cycle_year=2025)
        validate_success(api.open_nominations(earlier["id"], ADMIN_HEADERS), 200)
        validate_error(
            api.create_candidacy(self._payload(world, earlier["id"]), ADMIN_HEADERS),
            "ERR_WAITING_PERIOD_NOT_MET",
            422,
        )
        assert read_cycle(api, earlier["id"])["nomination_count"] == 0

    def test_the_stored_eligible_year_is_the_baseline_plus_the_effective_wait(self, api, world):
        """The candidacy's `eligible_from_year` is then the baseline year plus the effective
        waiting period, and it is stored on the row.

        Design: Difficulty/boundary_precision_check/waiting_period_inclusive_at_exact_eligible_year
        """
        candidacy = validate_success(
            api.create_candidacy(self._payload(world, world["cycle"]["id"]), ADMIN_HEADERS),
            201,
        )
        assert candidacy["eligible_from_year"] == 2021 + 5
        assert read_cycle(api, world["cycle"]["id"])["nomination_count"] == 1


class TestNominationBlockedByCandidateStanding:
    """A permanently barred candidate against an otherwise identical clean one."""

    @pytest.fixture
    def world(self, api):
        """Two 2017 retirees in an open cycle; the first has been barred permanently."""
        world = build_election_world(
            api,
            stage="nominations_open",
            elector_count=1,
            candidate_specs=TWO_2017_RETIREES,
        )
        validate_success(
            api.declare_permanent_ineligibility(
                world["candidates"][0]["id"],
                {"permanently_ineligible_reason": "Barred by the review panel"},
                ADMIN_HEADERS,
            ),
            200,
        )
        return world

    def _payload(self, world, candidate_index):
        return create_candidacy_payload(
            world["cycle"]["id"],
            world["candidates"][candidate_index]["id"],
            world["electors"][0]["id"],
        )

    def test_a_barred_candidate_cannot_be_nominated(self, api, world):
        """And the candidate must still be in play: a candidate whose `hof_status` is `INDUCTED`
        or `PERMANENTLY_INELIGIBLE` is refused with `ERR_CANDIDATE_INELIGIBLE` (HTTP 422).

        Design: Difficulty/cross_entity_state_dependency/nomination_blocked_by_candidate_hof_status
        """
        validate_error(
            api.create_candidacy(self._payload(world, 0), ADMIN_HEADERS),
            "ERR_CANDIDATE_INELIGIBLE",
            422,
        )

    def test_a_candidate_still_in_play_is_written_in_submitted(self, api, world):
        """A fresh candidacy is written in `SUBMITTED` status with `appearance_number` at 0 (it is
        off-ballot), `info_request_count` at 0, `latest_round_votes` and `latest_round_pct` at 0,
        and `screened_by_elector_id` and `screening_notes` unset.

        Design: Difficulty/cross_entity_state_dependency/nomination_blocked_by_candidate_hof_status
        """
        candidacy = validate_success(
            api.create_candidacy(self._payload(world, 1), ADMIN_HEADERS), 201
        )
        assert candidacy["status"] == "SUBMITTED"
        assert candidacy["eligible_from_year"] == 2022
        assert candidacy["appearance_number"] == 0
        assert candidacy["info_request_count"] == 0
        assert candidacy["latest_round_votes"] == 0
        assert candidacy["latest_round_pct"] == pytest.approx(0.0, abs=0.01)
        assert candidacy["screened_by_elector_id"] is None
        assert candidacy["screening_notes"] is None

    def test_only_the_accepted_nomination_moves_the_cycle_counter(self, api, world):
        """Its creation increments the cycle's `nomination_count` by 1 and recomputes the cycle's
        `special_election_used`, which counts the cycle's candidacies whose `pathway` is
        `SPECIAL` and whose `status` is anything other than `REJECTED`.

        Design: Difficulty/cross_entity_state_dependency/nomination_blocked_by_candidate_hof_status
        """
        api.create_candidacy(self._payload(world, 0), ADMIN_HEADERS)
        validate_success(api.create_candidacy(self._payload(world, 1), ADMIN_HEADERS), 201)
        assert read_cycle(api, world["cycle"]["id"])["nomination_count"] == 1


class TestVoteBlockedByElectorSuspension:
    """Suspension bars the vote; reinstatement restores it on the same request body."""

    @pytest.fixture
    def world(self, api):
        """A two-elector body with an open two-slot ballot; the nominator is suspended."""
        world = build_election_world(
            api, stage="ballot_open", elector_count=2, candidate_count=2
        )
        validate_success(
            api.suspend_elector(
                world["electors"][0]["id"],
                {"suspension_reason": "Conflict of interest review"},
                ADMIN_HEADERS,
            ),
            200,
        )
        return world

    def _payload(self, world):
        return create_vote_submission_payload(
            world["ballot"]["id"], [slot_of(world, 0)["id"]], world["ballot"]["version"]
        )

    def test_a_suspended_elector_may_not_vote(self, api, world):
        """First, the elector the operation depends on must be `CREDENTIALED`; a `PROVISIONAL`,
        `SUSPENDED` or `LAPSED` elector may neither nominate nor vote, and the attempt is
        refused with `ERR_ELECTOR_NOT_CREDENTIALED` (HTTP 403).

        Design: Difficulty/cross_entity_state_dependency/vote_submission_blocked_by_elector_suspension
        """
        validate_error(
            api.create_vote_submission(self._payload(world), elector_headers(world, 0)),
            "ERR_ELECTOR_NOT_CREDENTIALED",
            403,
        )

    def test_suspension_holds_the_bloc_seat_while_shrinking_the_roster(self, api, world):
        """It deliberately does **not** free the bloc seat — a suspended elector still occupies
        one, so `seats_filled` is unchanged — but it does recompute `credentialed_roster_count`
        on every cycle in `NOMINATIONS_OPEN`, `SCREENING` or `BALLOTING`, because a suspended
        elector is no longer part of the credentialed roster.

        Design: Difficulty/cross_entity_state_dependency/vote_submission_blocked_by_elector_suspension
        """
        assert read_bloc(api, world["bloc"]["id"])["seats_filled"] == 2
        assert read_cycle(api, world["cycle"]["id"])["credentialed_roster_count"] == 1

    def test_reinstatement_clears_the_reason_and_restores_the_roster(self, api, world):
        """Reinstating a suspended elector returns them to `CREDENTIALED`, clears
        `suspension_reason`, accepts an optional replacement `credential_expires_on`, requires
        that the resulting `credential_expires_on` be strictly later than the logical clock's
        current instant, and again recomputes `credentialed_roster_count` on those same three
        cycle phases.

        Design: Difficulty/cross_entity_state_dependency/vote_submission_blocked_by_elector_suspension
        """
        elector = validate_success(
            api.reinstate_elector(world["electors"][0]["id"], ADMIN_HEADERS), 200
        )
        assert elector["status"] == "CREDENTIALED"
        assert elector["suspension_reason"] is None
        assert read_bloc(api, world["bloc"]["id"])["seats_filled"] == 2
        assert read_cycle(api, world["cycle"]["id"])["credentialed_roster_count"] == 2

    def test_the_same_body_is_accepted_after_reinstatement(self, api, world):
        """The submission is written with `status` `COUNTED`, `selection_count` set to the length
        of `selected_slot_ids` (zero for an abstention), `cast_at` set to the logical clock's
        current instant, and `invalidated_reason` unset.

        Design: Difficulty/cross_entity_state_dependency/vote_submission_blocked_by_elector_suspension
        """
        payload = self._payload(world)
        validate_error(
            api.create_vote_submission(payload, elector_headers(world, 0)),
            "ERR_ELECTOR_NOT_CREDENTIALED",
            403,
        )
        validate_success(api.reinstate_elector(world["electors"][0]["id"], ADMIN_HEADERS), 200)
        submission = validate_success(
            api.create_vote_submission(payload, elector_headers(world, 0)), 201
        )
        assert submission["status"] == "COUNTED"
        assert submission["selection_count"] == 1
        assert submission["invalidated_reason"] is None
        assert_same_instant(submission["cast_at"], CLOCK_EPOCH, "cast_at")
        assert submission["ballot_version_after"] == 3
