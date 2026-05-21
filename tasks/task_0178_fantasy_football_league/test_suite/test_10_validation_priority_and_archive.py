"""Validation priority ordering and the archive lifecycle cascade.

Covers PRD §2.9 (validation priority: auth → existence → state → business),
§3.8 (archive cancels pending waivers and rejects open trades).
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    COMMISSIONER,
    advance_clock_to,
    create_league_payload,
    create_league_with_teams,
    create_player,
    create_waiver_payload,
    DEFAULT_BASE_CLOCK,
    fetch_waiver,
    iso_utc,
    list_trades,
    list_waivers,
    make_manager_headers,
    manager_uid,
    propose_trade,
    set_player_status,
    setup_drafted_league,
    setup_locked_week,
    submit_waiver,
    validate_error,
    validate_success,
)


def _now(league):
    return datetime.fromisoformat(league["now_ts"].replace("Z", "+00:00"))


# ===========================================================================
# Validation priority — PRD §2.9 (difficulty Rule 5)
# ===========================================================================
class TestValidationPriority:
    # DELETED — test_state_check_wins_over_business_fiscal_on_waiver_submit.
    # PRD §3.6 does not enumerate a league-status state precondition
    # (no ERR_INVALID_STATE rule) for POST /waivers. The PRD-silence
    # on "waivers in DRAFT_PENDING" leaves the test undecidable
    # against a PRD-faithful implementation. Deleted.

    def test_lineup_lock_wins_over_position_constraint(self, api):
        """PRD §2.9: "state-machine preconditions, surfaced as ERR_INVALID_STATE; and (8) business safety, referential, constraint, temporal, and fiscal checks".
        PRD §3.4: "(a) If MatchupWeek.status for the team's current-week matchup is already LOCKED — that is, if the weekly lock has fired — the mutation is rejected with ERR_LINEUP_LOCKED."

        Claim: PATCHing a roster slot AFTER lock AND with an invalid
        position assignment (QB into RB1) yields ERR_LINEUP_LOCKED —
        the business_safety check (PRD §3.4 (a)) fires before the
        business_constraint check (PRD §3.4 position eligibility).

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_on_lineup_patch
        """
        bundle = setup_locked_week(team_count=4)
        league = bundle["league"]
        t0 = bundle["teams"][0]
        # Find any QB slot (BENCH or STARTER). Whether or not the
        # initial lineup placed the team's QB as a starter is an
        # implementation detail; what we need is any QB-position slot
        # whose mutation to position_label='RB1' would simultaneously
        # be lock-blocked AND position-ineligible.
        from test_helpers import list_roster_slots_for_team
        slots = list_roster_slots_for_team(league["id"], t0["id"])
        players_by_id = {p["id"]: p for p in bundle["players_flat"]}
        qb_slot = None
        for s in slots:
            pdata = players_by_id.get(s.get("player_id"))
            if pdata and pdata.get("position") == "QB":
                qb_slot = s
                break
        assert qb_slot is not None, "Expected at least one QB slot on team"
        from test_helpers import patch_roster_slot_payload
        h0 = make_manager_headers(t0["manager_user_id"])
        res = api.patch_roster_slot(
            t0["id"], qb_slot["id"],
            patch_roster_slot_payload(slot_type="STARTER", position_label="RB1"),
            h0,
        )
        body = res.json()
        assert body.get("response_type") == "error"
        assert body["data"]["error_id"] != ApiErrorId.ERR_POSITION_CONSTRAINT.value, \
            "PRD §2.9: lineup-lock (business_safety) fires before " \
            "position-constraint (business_constraint)"
        validate_error(res, ApiErrorId.ERR_LINEUP_LOCKED.value)
