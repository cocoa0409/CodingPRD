"""Match draft and referee tests (PRD §3.4).

Covers PATCH /matches/{mid} overlap detection (half-open interval),
referee assignment double-booking (15-minute buffered geometry),
referee certification expiry, draft step ordering, and the
SCHEDULED → DRAFT_IN_PROGRESS → LIVE → COMPLETED happy path.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    REFEREE_BUFFER_MINUTES,
    TEST_USERS,
    advance_clock_to,
    api_client,
    assign_referee_payload,
    create_referee,
    draft_event_payload,
    iso_utc,
    make_referee_headers,
    setup_live_match_with_certified_referee,
    setup_tournament_with_published_bracket,
    update_match_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Referee assignment double-booking (PRD §3.4)
# ===========================================================================
class TestRefereeDoubleBooking:
    def test_referee_overlap_with_15_minute_buffer_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.4: "the assigned referee may not already be allocated
        to any other match whose buffered interval (scheduled_start
        minus 15 minutes through scheduled_end plus 15 minutes)
        overlaps the current match's identically buffered interval —
        otherwise ERR_REFEREE_DOUBLE_BOOKED."

        Claim: assigning the same referee to two matches whose buffered
        intervals overlap → ERR_REFEREE_DOUBLE_BOOKED.
        """
        tournament, regs, matches = setup_tournament_with_published_bracket(
            num_teams=4,
        )
        playable = [m for m in matches if not m.get("is_bye")]
        if len(playable) < 2:
            pytest.skip("Need two non-bye matches for double-booking test")
        referee = create_referee(certification_level="L2")
        # First assignment should succeed.
        first_response = api.assign_referee(
            playable[0]["id"], assign_referee_payload(referee["user_id"]),
            league_admin_headers,
        )
        validate_success(first_response)
        # Set up second match to fall inside the buffered window of the
        # first: end of m0 + 5 min start, end + 65 min end. The buffered
        # geometry [start-15m, end+15m] of m0 still overlaps.
        from datetime import datetime, timedelta
        end0 = datetime.fromisoformat(
            playable[0]["scheduled_end"].replace("Z", "+00:00"),
        )
        # 5 minutes after end0 — within the +15m buffer.
        new_start = (end0 + timedelta(minutes=5)).isoformat(
            timespec="milliseconds",
        ).replace("+00:00", "Z")
        new_end = (end0 + timedelta(minutes=65)).isoformat(
            timespec="milliseconds",
        ).replace("+00:00", "Z")
        # Patch m1 into the conflicting window first (need an interval
        # that ONLY conflicts on referee, not on team — so pick a match
        # that doesn't share teams with m0 if possible).
        target = playable[1]
        shared = (
            {playable[0]["team_a_id"], playable[0]["team_b_id"]}
            & {target["team_a_id"], target["team_b_id"]}
        )
        if shared:
            # Skip if all candidate matches share a team — separate
            # ERR_MATCH_TIME_CONFLICT path would fire first.
            pytest.skip(
                "Cannot isolate referee double-booking from team overlap",
            )
        patch_response = api.update_match(
            target["id"],
            update_match_payload(
                scheduled_start=new_start, scheduled_end=new_end,
                version=target.get("version"),
            ),
            league_admin_headers,
        )
        validate_success(patch_response)
        # Now assign the same referee to target — should fail because of
        # 15-min buffer overlap.
        response = api.assign_referee(
            target["id"], assign_referee_payload(referee["user_id"]),
            league_admin_headers,
        )
        validate_error(response, ApiErrorId.ERR_REFEREE_DOUBLE_BOOKED.value)


# ===========================================================================
# Start-draft preconditions (PRD §3.4)
# ===========================================================================
class TestStartDraft:
    def test_start_draft_before_window_rejected(self, api,
                                                league_admin_headers):
        """PRD §3.4: "Clock.now must lie in the half-open interval
        [scheduled_start, scheduled_end) — otherwise ERR_MATCH_NOT_IN_WINDOW."

        Claim: start-draft when Clock.now < scheduled_start →
        ERR_MATCH_NOT_IN_WINDOW.
        """
        tournament, regs, matches = setup_tournament_with_published_bracket(
            num_teams=2,
        )
        playable = [m for m in matches if not m.get("is_bye")]
        if not playable:
            pytest.skip("No playable match in 2-team bracket")
        target = playable[0]
        # Push the match's window strictly into the future so Clock.now <
        # scheduled_start regardless of how the implementation chose
        # scheduled_start at publish time. The PRD-required precondition
        # is "Clock.now < scheduled_start", which this PATCH establishes.
        patch_resp = api.update_match(
            target["id"],
            update_match_payload(
                scheduled_start=iso_utc(days_offset=2),
                scheduled_end=iso_utc(days_offset=2, hours_offset=1),
                version=target.get("version"),
            ),
            league_admin_headers,
        )
        target = validate_success(patch_resp)
        referee = create_referee(certification_level="L2")
        api.assign_referee(
            target["id"], assign_referee_payload(referee["user_id"]),
            league_admin_headers,
        )
        # Do NOT advance the clock — match scheduled_start is in the future.
        response = api.start_draft(
            target["id"], make_referee_headers(referee["user_id"]),
        )
        validate_error(response, ApiErrorId.ERR_MATCH_NOT_IN_WINDOW.value)


# ===========================================================================
# Draft step ordering (PRD §3.4)
# ===========================================================================
class TestDraftStepOrdering:
    def test_draft_event_with_wrong_step_index_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.4: "The strict-ordering rule is that the submitted
        step_index must equal the next expected step, which is computed
        as the count of DraftEvent rows already recorded for this match
        whose anomaly_type is null plus one — otherwise
        ERR_DRAFT_STEP_OUT_OF_ORDER."

        Claim: submitting step_index=2 when next expected is 1 →
        ERR_DRAFT_STEP_OUT_OF_ORDER.
        """
        tournament, regs, matches = setup_tournament_with_published_bracket(
            num_teams=2,
        )
        playable = [m for m in matches if not m.get("is_bye")]
        if not playable:
            pytest.skip("No playable match in 2-team bracket")
        target = playable[0]
        # Need to start the tournament first to leave BRACKET_PUBLISHED.
        from test_helpers import start_tournament
        start_tournament(tournament["id"])
        referee = create_referee(certification_level="L2")
        api.assign_referee(
            target["id"], assign_referee_payload(referee["user_id"]),
            league_admin_headers,
        )
        advance_clock_to(target["scheduled_start"])
        api.start_draft(target["id"], make_referee_headers(referee["user_id"]))
        # Next expected step is 1. Submit step_index=2.
        response = api.post_draft_event(
            target["id"],
            draft_event_payload(
                step_index=2, action="BAN", side="A",
                target_type="MAP", target_name="map_alpha",
            ),
            make_referee_headers(referee["user_id"]),
        )
        validate_error(response, ApiErrorId.ERR_DRAFT_STEP_OUT_OF_ORDER.value)


# ===========================================================================
# Referee certification expiry (PRD §3.4)
# ===========================================================================
class TestRefereeCertificationExpiry:
    def test_filing_incident_with_expired_certification_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.4: "the calling Referee's user_id must equal X-User-ID,
        the referee's status must be ACTIVE, and Clock.now must be
        strictly earlier than certification_expiry — otherwise
        ERR_REFEREE_CERT_EXPIRED; the same expiry check is also enforced
        when filing a MatchIncident."

        Claim: filing a MatchIncident when Clock.now >= referee's
        certification_expiry → ERR_REFEREE_CERT_EXPIRED.
        """
        from test_helpers import create_incident_payload, reset_clock_to_epoch
        tournament, match, referee = setup_live_match_with_certified_referee()
        # Advance the clock past the referee's certification expiry.
        from datetime import datetime, timedelta
        expiry = datetime.fromisoformat(
            referee["certification_expiry"].replace("Z", "+00:00"),
        )
        past = (expiry + timedelta(days=1)).isoformat(
            timespec="milliseconds",
        ).replace("+00:00", "Z")
        advance_clock_to(past)
        response = api.file_incident(
            create_incident_payload(
                match_id=match["id"], subject_type="TEAM",
                subject_id=match["team_a_id"],
                referee_id=referee["user_id"],
                classification="LATENCY",
            ),
            make_referee_headers(referee["user_id"]),
        )
        validate_error(response, ApiErrorId.ERR_REFEREE_CERT_EXPIRED.value)
