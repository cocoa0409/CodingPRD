"""Tournament phase axis, results-visibility axis, and clock-window gates."""
from test_helpers import (
    BEFORE_LOCK_DAY,
    LOCK_DAY,
    TEST_USERS,
    assert_tournament,
    get_entry,
    get_tournament,
    create_tournament,
    lock_tournament,
    make_coach_headers,
    open_registration,
    set_clock,
    setup_registration_scenario,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]


class TestParallelAxes:
    """The two tournament state axes evolve independently (PRD §2.10)."""

    def test_phase_axis_moves_while_visibility_stays_hidden(self, api):
        """PRD §2.10: "The phase axis `status` walks `DRAFT` → `REGISTRATION_OPEN`
        → `REGISTRATION_LOCKED` → `PRELIMS_ACTIVE` → `ELIMS_ACTIVE` → `COMPLETED`.
        The results axis `results_visibility` walks `HIDDEN` → `PUBLISHED` →
        `CERTIFIED`. They evolve independently: transitions on the results axis are
        gated on particular `status` values, but a results-axis transition never
        mutates `status`, and a phase transition never mutates
        `results_visibility`."

        Design: Difficulty/non_linear_state_machine/tournament_parallel_axes_independent_evolution
        """
        tournament = create_tournament(name="Districts PA")
        assert_tournament(tournament)

        opened = validate_success(api.open_registration(tournament["id"], DIRECTOR))
        assert opened["status"] == "REGISTRATION_OPEN"
        assert opened["results_visibility"] == "HIDDEN"

        set_clock(LOCK_DAY)
        locked = lock_tournament(tournament["id"])
        assert locked["status"] == "REGISTRATION_LOCKED", "phase axis advanced"
        assert locked["results_visibility"] == "HIDDEN", (
            "the phase transition never mutates results_visibility")

    def test_publish_gated_on_completed_while_prelims_begin(self, api):
        """PRD §3.7: "Publishing results requires the tournament's `status` to be
        `COMPLETED` and its `results_visibility` to be `HIDDEN` (either failure
        yields `ERR_TOURNAMENT_PHASE_FORBIDDEN`), and moves the axis `HIDDEN` →
        `PUBLISHED`."
        PRD §2.10: "a results-axis transition never mutates `status`, and a phase
        transition never mutates `results_visibility`."

        Design: Difficulty/non_linear_state_machine/tournament_parallel_axes_independent_evolution
        """
        tournament = create_tournament(name="Districts PA")
        open_registration(tournament["id"])
        set_clock(LOCK_DAY)
        lock_tournament(tournament["id"])

        rejected = api.publish_results(tournament["id"], DIRECTOR)
        validate_error(rejected, "ERR_TOURNAMENT_PHASE_FORBIDDEN")

        active = validate_success(api.start_prelims(tournament["id"], DIRECTOR))
        assert active["status"] == "PRELIMS_ACTIVE", (
            "with no divisions holding 2+ confirmed entries, the rounds gate is vacuous")
        final = get_tournament(tournament["id"])
        assert final["status"] == "PRELIMS_ACTIVE"
        assert final["results_visibility"] == "HIDDEN", (
            "visibility axis untouched by the failed publish and the phase advance")


class TestClockWindowGates:
    def test_open_before_registration_window_rejected(self, api):
        """PRD §2.5: "Opening registration requires the current logical UTC to be
        at or after the tournament's `registration_opens_at`, otherwise the
        request fails with `ERR_REGISTRATION_WINDOW_NOT_OPEN` (HTTP 409)."
        PRD §2.5: "At server startup the logical clock reads exactly
        2026-08-01T00:00:00Z".

        Design: Corner/validations/registration_window_not_open_rejected
        """
        tournament = create_tournament(
            name="WN", registration_opens_at="2026-08-02T00:00:00Z")
        resp = api.open_registration(tournament["id"], DIRECTOR)
        validate_error(resp, "ERR_REGISTRATION_WINDOW_NOT_OPEN")
        assert get_tournament(tournament["id"])["status"] == "DRAFT"

    def test_lock_before_locks_at_rejected(self, api):
        """PRD §2.5: "Locking registration requires the current logical UTC to be
        at or after `registration_locks_at`, otherwise it fails with
        `ERR_REGISTRATION_WINDOW_CLOSED` (HTTP 409)."

        Design: Corner/validations/lock_before_locks_at_rejected
        """
        tournament = create_tournament(name="LW")
        open_registration(tournament["id"])
        set_clock(BEFORE_LOCK_DAY)  # 2026-08-05, before locks_at 2026-08-10
        current = get_tournament(tournament["id"])
        resp = api.lock_registration(tournament["id"], current["version"], DIRECTOR)
        validate_error(resp, "ERR_REGISTRATION_WINDOW_CLOSED")
        assert get_tournament(tournament["id"])["status"] == "REGISTRATION_OPEN"


class TestPhaseAggregateGates:
    def test_start_prelims_without_rounds_rejected(self, api):
        """PRD §3.4: "Starting prelims moves the tournament `REGISTRATION_LOCKED`
        → `PRELIMS_ACTIVE`. It requires the tournament to be `REGISTRATION_LOCKED`
        (otherwise `ERR_TOURNAMENT_PHASE_FORBIDDEN`) and every division holding at
        least 2 `CONFIRMED` entries to have at least one `SCHEDULED` `PRELIM`
        round (otherwise `ERR_ROUNDS_NOT_SCHEDULED`)."

        Design: Corner/validations/start_prelims_without_rounds_rejected
        """
        ws = setup_registration_scenario(
            name="SP", prelim_round_count=2,
            schools=(
                {"key": "a", "name": "Alpha", "entries": {"d": 1}, "judges": [2]},
                {"key": "b", "name": "Beta", "entries": {"d": 1}, "judges": [2]},
            ))
        # No round was ever scheduled for the division.
        resp = api.start_prelims(ws["t"]["id"], DIRECTOR)
        validate_error(resp, "ERR_ROUNDS_NOT_SCHEDULED")

        assert get_tournament(ws["t"]["id"])["status"] == "REGISTRATION_LOCKED"
        for entry in ws["entries"]["a"] + ws["entries"]["b"]:
            assert get_entry(entry["id"])["status"] == "CONFIRMED", (
                "no COMPETING cascade fired when start-prelims is rejected")

    def test_entry_withdraw_after_lock_rejected(self, api):
        """PRD §3.2: "Withdrawing an entry (`CONFIRMED` → `WITHDRAWN`) is possible
        only before the lock, because it is a registration-graph write gated on
        `REGISTRATION_OPEN`; from any other entry state it yields
        `ERR_ENTRY_INVALID_STATE`."
        PRD §2.7: "writes into the registration graph are allowed only while the
        tournament is `REGISTRATION_OPEN`".

        Design: Corner/state_machines/entry_withdraw_after_lock_rejected
        """
        ws = setup_registration_scenario(
            name="WL", prelim_round_count=4,
            schools=(
                {"key": "a", "name": "Alpha", "entries": {"d": 1}, "judges": [4]},
            ))
        assert ws["t"]["status"] == "REGISTRATION_LOCKED"
        entry = ws["entries"]["a"][0]
        resp = api.withdraw_entry(
            entry["id"], make_coach_headers(ws["schools"]["a"]["id"]))
        validate_error(resp, "ERR_TOURNAMENT_PHASE_FORBIDDEN")
        assert get_entry(entry["id"])["status"] == "CONFIRMED", (
            "a rejected withdrawal leaves the entry CONFIRMED")
