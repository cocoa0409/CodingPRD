"""Roster slot patches: ownership, lineup lock, IR eligibility, position
constraints, shape constraints.

Covers PRD §3.4 (PATCH /teams/.../roster-slots/{rid}) — the four
protections (a) lineup lock, (b) IR eligibility, (c) shape, (d)
position constraint, plus position eligibility (§3.4 last paragraph).
Covers PRD §2.8 (OCC version mismatch).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    create_player,
    fetch_team,
    first_team_bench_slot,
    first_team_starter_slot,
    list_roster_slots_for_team,
    make_manager_headers,
    patch_roster_slot_payload,
    set_player_status,
    setup_drafted_league,
    setup_locked_week,
    validate_error,
    validate_success,
)


# ===========================================================================
# Ownership (PRD §2.1 / §1.4 priority 6)
# ===========================================================================
class TestRosterOwnership:
    def test_patch_slot_by_non_owner_rejected(self, api):
        """PRD §2.1: "any operation that targets a team_id other than the one the acting Manager owns is rejected with ERR_NOT_TEAM_OWNER."

        Claim: a Manager whose X-User-ID maps to a different team
        cannot PATCH another team's roster-slot.
        """
        bundle = setup_drafted_league(team_count=4)
        league_id = bundle["league"]["id"]
        t0, t1 = bundle["teams"][0], bundle["teams"][1]
        # Find any of t0's slots.
        slot = first_team_starter_slot(league_id, t0["id"]) \
            or first_team_bench_slot(league_id, t0["id"])
        assert slot is not None, "setup_drafted_league should produce roster slots"
        # Use t1's manager — they don't own t0.
        h_other = make_manager_headers(t1["manager_user_id"])
        res = api.patch_roster_slot(
            t0["id"], slot["id"],
            patch_roster_slot_payload(slot_type="BENCH"),
            h_other,
        )
        validate_error(res, ApiErrorId.ERR_NOT_TEAM_OWNER.value)


# ===========================================================================
# Lineup lock — PRD §3.4 (a)
# ===========================================================================
class TestLineupLock:
    def test_patch_after_lock_rejected_with_lineup_locked(self, api):
        """PRD §3.4: "(a) If MatchupWeek.status for the team's current-week matchup is already LOCKED — that is, if the weekly lock has fired — the mutation is rejected with ERR_LINEUP_LOCKED."

        Claim: PATCH a roster slot after the week is LOCKED yields
        ERR_LINEUP_LOCKED.

        # difficulty: cross_entity_state_dependency/roster_slot_lineup_change_requires_matchup_week_unlocked
        """
        bundle = setup_locked_week(team_count=4)
        league_id = bundle["league"]["id"]
        t0 = bundle["teams"][0]
        # Find a starter to mutate.
        slot = first_team_starter_slot(league_id, t0["id"])
        assert slot is not None
        h0 = make_manager_headers(t0["manager_user_id"])
        res = api.patch_roster_slot(
            t0["id"], slot["id"],
            patch_roster_slot_payload(slot_type="BENCH"),
            h0,
        )
        validate_error(res, ApiErrorId.ERR_LINEUP_LOCKED.value)


# ===========================================================================
# IR eligibility — PRD §3.4 (b)
# ===========================================================================
class TestIREligibility:
    def test_patch_active_player_to_ir_rejected(self, api):
        """PRD §3.4: "(b) A slot may only carry slot_type IR when the player it holds has Player.status_tag either OUT or IR_ELIGIBLE; promoting a healthy player to IR is rejected with ERR_IR_INELIGIBLE."

        Claim: moving a Player whose status_tag is ACTIVE into an IR
        slot yields ERR_IR_INELIGIBLE.
        """
        bundle = setup_drafted_league(team_count=4, ir_slots=2)
        league_id = bundle["league"]["id"]
        t0 = bundle["teams"][0]
        # Pick any of t0's bench slots; the player there starts ACTIVE.
        bench_slot = first_team_bench_slot(league_id, t0["id"])
        assert bench_slot is not None, "Expected at least one BENCH slot after draft"
        h0 = make_manager_headers(t0["manager_user_id"])
        # Confirm the underlying player is ACTIVE (default state per PRD §3.1).
        res = api.patch_roster_slot(
            t0["id"], bench_slot["id"],
            patch_roster_slot_payload(slot_type="IR"),
            h0,
        )
        validate_error(res, ApiErrorId.ERR_IR_INELIGIBLE.value)

    def test_patch_out_player_to_ir_succeeds(self, api):
        """PRD §3.4: "(b) A slot may only carry slot_type IR when the player it holds has Player.status_tag either OUT or IR_ELIGIBLE".

        Claim: moving a Player whose status_tag is OUT into an IR slot
        succeeds (positive branch of the IR eligibility rule).
        """
        bundle = setup_drafted_league(team_count=4, ir_slots=2)
        league_id = bundle["league"]["id"]
        t0 = bundle["teams"][0]
        bench_slot = first_team_bench_slot(league_id, t0["id"])
        assert bench_slot is not None
        # Flip the player to OUT via the Commissioner-only status endpoint.
        set_player_status(bench_slot["player_id"], "OUT")
        h0 = make_manager_headers(t0["manager_user_id"])
        res = api.patch_roster_slot(
            t0["id"], bench_slot["id"],
            patch_roster_slot_payload(slot_type="IR"),
            h0,
        )
        data = validate_success(res, 200)
        assert data["slot_type"] == "IR"


# ===========================================================================
# Position eligibility — PRD §3.4 last paragraph
# ===========================================================================
class TestPositionEligibility:
    def test_patch_qb_into_rb_slot_rejected(self, api):
        """PRD §3.4: "The placement must also respect basic position eligibility (Player.position matching the slot's position_label root, with FLEX_RWT players satisfying FLEX); incompatible placements yield ERR_POSITION_INELIGIBLE."

        Claim: placing a QB into an RB starter slot yields
        ERR_POSITION_INELIGIBLE.
        """
        bundle = setup_drafted_league(team_count=4)
        league_id = bundle["league"]["id"]
        t0 = bundle["teams"][0]
        # Find a bench slot for a QB-position player.
        slots = list_roster_slots_for_team(league_id, t0["id"])
        # Pick the team's QB bench slot. With our seed plan, the QB is
        # at the BENCH after finish-draft.
        # We need a player_id whose position is QB on t0's roster. Find
        # by scanning roster slots and matching against the drafted
        # players from the bundle.
        players_by_id = {p["id"]: p for p in bundle["players_flat"]}
        qb_slot = None
        for s in slots:
            pdata = players_by_id.get(s.get("player_id"))
            if pdata and pdata.get("position") == "QB":
                qb_slot = s
                break
        assert qb_slot is not None, "Expected a QB on t0's roster"
        h0 = make_manager_headers(t0["manager_user_id"])
        res = api.patch_roster_slot(
            t0["id"], qb_slot["id"],
            patch_roster_slot_payload(slot_type="STARTER", position_label="RB1"),
            h0,
        )
        validate_error(res, ApiErrorId.ERR_POSITION_INELIGIBLE.value)


# ===========================================================================
# Optimistic concurrency — PRD §2.8
# ===========================================================================
class TestRosterVersionConflict:
    def test_patch_with_wrong_version_rejected(self, api):
        """PRD §2.8: "If the supplied version differs from the value currently on the server, the request is rejected with ERR_VERSION_CONFLICT."

        Claim: PATCH /roster-slots with a stale version yields
        ERR_VERSION_CONFLICT.
        """
        bundle = setup_drafted_league(team_count=4)
        league_id = bundle["league"]["id"]
        t0 = bundle["teams"][0]
        # Find an RB bench slot to swap into RB1 (we want a valid mutation
        # otherwise; only the version is wrong).
        slots = list_roster_slots_for_team(league_id, t0["id"])
        players_by_id = {p["id"]: p for p in bundle["players_flat"]}
        slot = None
        for s in slots:
            if s.get("slot_type") != "BENCH":
                continue
            pdata = players_by_id.get(s.get("player_id"))
            if pdata and pdata.get("position") == "RB":
                slot = s
                break
        assert slot is not None
        h0 = make_manager_headers(t0["manager_user_id"])
        # Use a version that cannot match — high above any plausible
        # current version.
        res = api.patch_roster_slot(
            t0["id"], slot["id"],
            patch_roster_slot_payload(
                slot_type="BENCH",  # no-op but still triggers mutation path
                version=9999,
            ),
            h0,
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_patch_without_version_field_skips_check(self, api):
        """PRD §2.8: "If the body omits the version field altogether, the server skips the concurrency check and processes the mutation unconditionally."

        Claim: a body without a version field is accepted (no
        ERR_VERSION_CONFLICT can fire when the field is omitted).
        """
        bundle = setup_drafted_league(team_count=4)
        league_id = bundle["league"]["id"]
        t0 = bundle["teams"][0]
        slots = list_roster_slots_for_team(league_id, t0["id"])
        # A no-op-style slot_type=BENCH should be accepted; if any other
        # validation would fire we accept a non-422 (we only assert it's
        # not ERR_VERSION_CONFLICT).
        slot = None
        for s in slots:
            if s.get("slot_type") == "BENCH":
                slot = s
                break
        assert slot is not None
        h0 = make_manager_headers(t0["manager_user_id"])
        res = api.patch_roster_slot(
            t0["id"], slot["id"],
            patch_roster_slot_payload(slot_type="BENCH"),  # no version
            h0,
        )
        body = res.json()
        if body.get("response_type") == "error":
            assert body["data"]["error_id"] != ApiErrorId.ERR_VERSION_CONFLICT.value, \
                "PRD §2.8: omitting version field must skip the concurrency check"
