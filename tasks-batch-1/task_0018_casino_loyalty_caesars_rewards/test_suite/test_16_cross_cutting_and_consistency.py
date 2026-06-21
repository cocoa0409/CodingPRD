"""Cross-cutting complexity layers and consistency model: OCC stale-version
rejection, scheduled-deferred cancel, rate-threshold below-flag stay, and
immediate consistency of tier-credit accrual."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_property,
    create_member,
    record_gaming_session,
    get_member_version,
    schedule_annual_reset,
    create_host,
    create_host_assignment,
    ApiErrorId,
    make_loyalty_manager_headers,
    make_member_services_headers,
    make_compliance_officer_headers,
    bootstrap_two_managers_for_occ_test,
)


class TestOccStaleMemberVersionBlocksHostAssignmentCreate:
    """PRD §2.5: POST /host-assignments is OCC-gated on Member.version.
    A second strictly sequential call with the prior version fails."""

    def test_two_sequential_creates_with_same_version_second_fails(self, api):
        """PRD §2.5: "A POST to create a HostAssignment and a POST to
        create a CompRoomBooking each take expected_member_version as a
        non-optional input field, which the caller must populate with the
        version value the caller last observed on the target Member. The
        server compares this value against the current Member.version at
        the instant the request is processed; if it does not match —
        because, for example, an intervening self-exclusion has just
        transitioned the member to EXCLUDED and cascaded revokes onto
        prior assignments and bookings, advancing the member's version, or
        because a velocity-monitoring tick has just driven the member to
        SUSPENDED and bumped the same counter — the request is rejected
        with ERR_STALE_MEMBER_VERSION and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_member_version_blocks_host_assignment_create
        """
        ctx = bootstrap_two_managers_for_occ_test(
            clock="2026-02-01T00:00:00Z",
        )
        # First create succeeds, bumping member.version.
        validate_success(
            api.create_host_assignment(
                {
                    "member_id": ctx["member"]["id"],
                    "host_id": ctx["host_1"]["id"],
                    "expected_member_version": ctx["member"]["version"],
                },
                make_loyalty_manager_headers("lm_alice"),
            ),
            expected_status=201,
        )
        # Second create with the STALE version (same value as first) fails.
        resp = api.create_host_assignment(
            {
                "member_id": ctx["member"]["id"],
                "host_id": ctx["host_2"]["id"],
                "expected_member_version": ctx["member"]["version"],
            },
            make_loyalty_manager_headers("lm_alice"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_MEMBER_VERSION.value)


class TestOccStaleMemberVersionBlocksCompBookingCreate:
    """PRD §2.5: POST /comp-room-bookings is similarly OCC-gated."""

    def test_booking_create_with_stale_version_returns_412(self, api):
        """PRD §3.6: "The booking is refused if the member is excluded
        (ERR_MEMBER_EXCLUDED), if the member is velocity-suspended
        (ERR_MEMBER_VELOCITY_SUSPENDED), if check_out is not strictly
        greater than check_in (ERR_BOOKING_INVALID_DATES), if the supplied
        member version is stale (ERR_STALE_MEMBER_VERSION)".
        PRD §2.5: "if it does not match ... the request is rejected with
        ERR_STALE_MEMBER_VERSION and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_member_version_blocks_comp_booking_create
        """
        set_clock("2026-02-01T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="OCC2", email="occ2@x.com",
        )
        # Initial version is the one returned at create.
        initial_v = mem["version"]
        # Record a session — this bumps Member.version.
        record_gaming_session(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-02-01T01:00:00Z",
            ended_at="2026-02-01T02:00:00Z",
            game_type="SLOTS", theoretical_loss_cents=1_500_000,
        )
        # Now create a booking with the stale (initial) version.
        resp = api.create_comp_room_booking(
            {
                "member_id": mem["id"], "property_id": prop["id"],
                "check_in": "2026-03-01T15:00:00Z",
                "check_out": "2026-03-02T11:00:00Z",
                "expected_member_version": initial_v,
            },
            make_loyalty_manager_headers("lm_1"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_MEMBER_VERSION.value)


class TestScheduledDeferredCancelAnnualReset:
    """PRD §3.8: /cancel is permitted only while the clock is strictly
    before scheduled_for; on success the run transitions SCHEDULED →
    CANCELLED."""

    def test_cancel_scheduled_run_before_due_transitions_to_cancelled(self, api):
        """PRD §3.8: "Cancelling a scheduled run is permitted only while
        the server's current UTC clock remains strictly before
        scheduled_for; an attempt to cancel after that point fails with
        ERR_RESET_ALREADY_DUE. On success the run transitions SCHEDULED →
        CANCELLED and its version is incremented."

        Design: Corner/cross_cutting_complexity_layers/scheduled_action_cancel_annual_reset_before_due
        """
        set_clock("2027-06-01T00:00:00Z")
        ar = schedule_annual_reset(
            reset_year=2027, scheduled_for="2028-01-01T00:00:00Z",
        )
        resp = api.cancel_annual_reset_run(
            ar["id"], make_compliance_officer_headers("co_1"),
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CANCELLED"


class TestRateThresholdVelocityBelowFlagStaysNormal:
    """PRD §3.4: 499_999 cents in a fresh 60-min window stays below the
    FLAG threshold — velocity_status stays NORMAL."""

    def test_aggregate_below_flag_keeps_velocity_normal(self, api):
        """PRD §3.4: "a total that is greater than or equal to ... five
        hundred thousand cents (five thousand US dollars) but below the
        suspend threshold creates a VelocityAlert with severity FLAGGED.
        A total of exactly five hundred thousand cents trips FLAGGED, not
        NORMAL."

        Below five hundred thousand cents the gate ('>=') is not crossed.

        Design: Corner/cross_cutting_complexity_layers/rate_threshold_velocity_below_flag_stays_normal
        """
        set_clock("2026-05-15T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="RT", email="rt@x.com",
        )
        record_gaming_session(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-05-15T10:00:00Z",
            ended_at="2026-05-15T10:30:00Z",
            game_type="SLOTS", theoretical_loss_cents=499_999,
        )
        m = validate_success(
            api.get_member(mem["id"], make_loyalty_manager_headers("lm_1")),
            expected_status=200,
        )
        assert m["velocity_status"] == "NORMAL"


# ───────────────────────── Consistency ──────────────────────────────────

class TestImmediateConsistencyOnGamingSessionResponse:
    """PRD §2.7 + §3.3: the freshly-computed tier_credits_earned is
    returned in the SAME envelope as the POST /gaming-sessions response."""

    def test_post_session_response_contains_tier_credits_earned(self, api):
        """PRD §3.3: "The final value is rounded half-up to two decimal
        places — this rounding is done per session, before the value is
        added to any running total — and stored on the session as
        tier_credits_earned. The same value is then added to the member's
        tier_credits_ytd (year-to-date) and to the member's
        tier_credits_lifetime (which never resets)."

        Design: Corner/consistency_model/immediate_consistency_tier_credits_visible_in_same_response
        """
        set_clock("2026-02-01T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="IM", email="im@x.com",
        )
        # TABLE_GAMES at GOLD, $1000 loss: base = 1000; * 2.0 (TABLE_GAMES);
        # * 1.0 (GOLD) = 2000.00 TC.
        resp = api.create_gaming_session(
            {
                "member_id": mem["id"], "property_id": prop["id"],
                "started_at": "2026-02-01T10:00:00Z",
                "ended_at": "2026-02-01T11:00:00Z",
                "game_type": "TABLE_GAMES",
                "theoretical_loss_cents": 100000,
            },
            make_member_services_headers("ms_1"),
        )
        sess = validate_success(resp, expected_status=201)
        # tier_credits_earned must be in the same response envelope.
        assert sess["tier_credits_earned"] == pytest.approx(2000.00, abs=0.01)
        # And the Member's totals must be updated by the same time the
        # next GET resolves — immediate consistency.
        m = validate_success(
            api.get_member(mem["id"], make_loyalty_manager_headers("lm_1")),
            expected_status=200,
        )
        assert m["tier_credits_ytd"] == pytest.approx(2000.00, abs=0.01)
