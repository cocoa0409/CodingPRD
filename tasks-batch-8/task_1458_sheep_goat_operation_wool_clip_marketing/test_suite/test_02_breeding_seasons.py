"""Breeding season chain, clock gates, uniqueness, birth-record window/arithmetic."""
from test_helpers import (
    ApiErrorId,
    assert_birth_record,
    assert_breeding_season,
    create_flock,
    create_season,
    create_season_in_state,
    log_birth,
    set_clock,
    transition_season,
    validate_error,
    validate_success,
)

SEASON_KW = dict(
    season_label="2026-fall",
    ewes_bred=200,
    breeding_start_date="2026-08-05T00:00:00Z",
    breeding_end_date="2026-09-19T00:00:00Z",
)


class TestBreedingSeasonChain:

    def test_breeding_season_full_chain_with_clock_gates(self, api, ranch_manager_headers):
        """PRD §3.1: "`GESTATION -> LAMBING` requires the clock to have reached
        `expected_lambing_start`. `LAMBING -> WEANING` requires the clock to
        have reached 45 days after `expected_lambing_start`."
        PRD §3.1: "the `birth_date` must fall inside the lambing window running
        from `expected_lambing_start` through 45 days after it, inclusive
        (otherwise `ERR_BIRTH_OUTSIDE_WINDOW`, HTTP 422); and the arithmetic
        must balance — `births_reported` must equal the sum of `born_alive` and
        `born_dead`, with `births_reported` at least 1 and both components
        non-negative (otherwise `ERR_BIRTH_COUNT_MISMATCH`, HTTP 422)."
        PRD §3.1: "Each birth record immediately recomputes the season's
        `total_born` (the sum of `births_reported` across the season's
        records), `total_born_alive` (the sum of `born_alive`), and
        `lambing_rate_pct` (the season's live-born total divided by
        `ewes_bred`, multiplied by 100, rounded half-up to one decimal place)".

        Design: Corner/state_machines/breeding_season_full_chain_with_clock_gates
        """
        flock = create_flock(flock_name="Chain Ranch", species="SHEEP", baseline_headcount=500)
        season = create_season(flock["id"], **SEASON_KW)
        sid = season["id"]
        assert season["season_status"] == "PLANNED"
        # 2026-08-05 + 147 days = 2026-12-30
        assert season["expected_lambing_start"] == "2026-12-30T00:00:00Z"

        transition_season(sid, "BREEDING")
        set_clock("2026-09-19T00:00:00Z")
        season = transition_season(sid, "GESTATION")
        assert season["season_status"] == "GESTATION"
        set_clock("2026-12-30T00:00:00Z")
        season = transition_season(sid, "LAMBING")
        assert season["season_status"] == "LAMBING"

        # One day before expected_lambing_start -> outside the window.
        resp = api.create_birth_record({
            "season_id": sid, "birth_date": "2026-12-29T00:00:00Z",
            "births_reported": 5, "born_alive": 5, "born_dead": 0,
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_BIRTH_OUTSIDE_WINDOW.value, expected_status=422)

        # In-window but arithmetic unbalanced.
        resp = api.create_birth_record({
            "season_id": sid, "birth_date": "2027-01-02T00:00:00Z",
            "births_reported": 10, "born_alive": 9, "born_dead": 0,
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_BIRTH_COUNT_MISMATCH.value, expected_status=422)

        log_birth(sid, birth_date="2026-12-30T06:00:00Z",
                  births_reported=100, born_alive=90, born_dead=10)
        log_birth(sid, birth_date="2027-01-05T06:00:00Z",
                  births_reported=50, born_alive=48, born_dead=2)

        set_clock("2027-02-13T00:00:00Z")
        season = transition_season(sid, "WEANING")
        assert season["season_status"] == "WEANING"
        season = transition_season(sid, "CLOSED")
        assert season["season_status"] == "CLOSED"

        season = validate_success(api.get_breeding_season(sid, ranch_manager_headers))
        assert season["total_born"] == 150
        assert season["total_born_alive"] == 138
        assert season["lambing_rate_pct"] == 69.0, "138/200*100 round-half-up 1dp == 69.0"
        flock = validate_success(api.get_flock(flock["id"], ranch_manager_headers))
        assert flock["current_headcount"] == 638, "500 baseline + 138 live births"

    def test_season_gestation_too_early_returns_422(self, api, ranch_manager_headers):
        """PRD §3.1: "`BREEDING -> GESTATION` requires the logical clock to have
        reached `breeding_end_date`."
        PRD §3.1: "Each of the three clock gates is rejected with
        `ERR_SEASON_TOO_EARLY` (HTTP 422) when the clock has not yet arrived."

        Design: Corner/state_machines/season_gestation_too_early_returns_422
        """
        flock = create_flock(flock_name="Early Ranch", species="SHEEP", baseline_headcount=500)
        season = create_season(flock["id"], **SEASON_KW)
        transition_season(season["id"], "BREEDING")
        # Clock is still the startup default 2026-08-01 (before breeding_end 09-19).
        resp = api.transition_breeding_season(season["id"], {"to": "GESTATION"}, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_SEASON_TOO_EARLY.value, expected_status=422)
        season = validate_success(api.get_breeding_season(season["id"], ranch_manager_headers))
        assert season["season_status"] == "BREEDING"

    def test_season_cancel_from_gestation_rejected(self, api, ranch_manager_headers):
        """PRD §3.1: "Cancellation is possible from `PLANNED` or from `BREEDING`
        (`PLANNED -> CANCELLED`, `BREEDING -> CANCELLED`); once the season
        reaches `GESTATION` the lambs or kids are already on the way and the
        season can no longer be cancelled, and any transition not defined from
        the current `season_status` is rejected with `ERR_SEASON_INVALID_STATE`
        (HTTP 409)."
        PRD §3.1: "the season must currently be in `LAMBING` (otherwise
        `ERR_SEASON_INVALID_STATE`)".

        Design: Corner/state_machines/season_cancel_from_gestation_rejected
        """
        flock = create_flock(flock_name="NoCancel Ranch", species="SHEEP", baseline_headcount=500)
        season = create_season_in_state(flock["id"], "GESTATION", **SEASON_KW)
        resp = api.transition_breeding_season(season["id"], {"to": "CANCELLED"}, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_SEASON_INVALID_STATE.value, expected_status=409)
        # Births are recordable only while LAMBING; season is in GESTATION.
        resp = api.create_birth_record({
            "season_id": season["id"], "birth_date": "2026-12-30T06:00:00Z",
            "births_reported": 4, "born_alive": 4, "born_dead": 0,
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_SEASON_INVALID_STATE.value, expected_status=409)

    def test_season_terminal_closed_lockdown_rejected(self, api, ranch_manager_headers):
        """PRD §2.9: "Terminal states accept no further transitions, and attempts
        to move out of them take the invalid-state error."

        Design: Corner/state_machines/season_terminal_closed_lockdown_rejected
        """
        flock = create_flock(flock_name="Terminal Ranch", species="SHEEP", baseline_headcount=500)
        season = create_season_in_state(flock["id"], "CLOSED", **SEASON_KW)
        assert season["season_status"] == "CLOSED"
        resp = api.transition_breeding_season(season["id"], {"to": "BREEDING"}, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_SEASON_INVALID_STATE.value, expected_status=409)
        season = validate_success(api.get_breeding_season(season["id"], ranch_manager_headers))
        assert season["season_status"] == "CLOSED"

    def test_open_season_uniqueness_rejected(self, api, ranch_manager_headers):
        """PRD §3.1: "Only one open season per flock is permitted: creating a
        season while the same flock already has one in `PLANNED`, `BREEDING`,
        `GESTATION`, `LAMBING`, or `WEANING` is rejected with
        `ERR_OPEN_SEASON_EXISTS` (HTTP 409)."

        Design: Corner/state_machines/open_season_uniqueness_rejected
        """
        flock = create_flock(flock_name="OneSeason Ranch", species="SHEEP", baseline_headcount=500)
        season = create_season(flock["id"], **SEASON_KW)
        transition_season(season["id"], "BREEDING")
        resp = api.create_breeding_season({
            "flock_id": flock["id"], "season_label": "2026-winter", "ewes_bred": 100,
            "breeding_start_date": "2026-10-01T00:00:00Z",
            "breeding_end_date": "2026-11-15T00:00:00Z",
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_OPEN_SEASON_EXISTS.value, expected_status=409)
        data = validate_success(
            api.list_breeding_seasons(ranch_manager_headers, params={"flock_id": flock["id"]}))
        assert len(data) == 1, "only the original season exists for the flock"

    def test_birth_record_immutable_event_entity(self, api, range_hand_headers, ranch_manager_headers):
        """PRD §2.4: "A birth record is the single exception: it carries only
        `id` and `created_at`, and both `updated_at` and `version` are absent
        from it, because a birth record is never modified after it is logged."

        Design: Corner/entities/birth_record_immutable_event_entity
        """
        flock = create_flock(flock_name="Event Ranch", species="SHEEP", baseline_headcount=500)
        season = create_season_in_state(flock["id"], "LAMBING", **SEASON_KW)
        resp = api.create_birth_record({
            "season_id": season["id"], "birth_date": "2026-12-30T06:00:00Z",
            "births_reported": 12, "born_alive": 11, "born_dead": 1,
        }, range_hand_headers)
        data = validate_success(resp, expected_status=201)
        assert_birth_record(data)
        assert data["recorded_by_user_id"] == "rh-1", (
            "PRD §3.1: the server stamps recorded_by_user_id with the caller's X-User-ID"
        )
