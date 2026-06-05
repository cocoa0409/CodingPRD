"""Queue B (Corner) — entity defaults/constraints and state-machine transitions."""
from test_helpers import validate_success, validate_error
from test_helpers.test_users import TEST_USERS
from test_helpers.fixtures import (
    set_clock, create_member, member_headers_for, grant_status_match,
    create_companion_certificate, create_booked_segment, create_flown_segment,
    accrue_segment, inject_points, inject_qualifying_segments, create_pool,
    current_pool_version, create_pending_gift, member_version,
)
from test_helpers.factories import (
    create_member_payload, create_flight_segment_payload, create_award_booking_payload,
    create_upgrade_request_payload, create_points_gift_payload,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]


# ---------- section: entities ----------

class TestEntityDefaults:
    def test_member_create_defaults(self, api):
        """PRD §3.1: "A freshly registered member starts at BASE tier with a
        points_balance of 0, a qualifying_segments_ytd of 0, both status_match_active
        and status_match_used false, and no recorded last_activity_at."
        PRD §2.4: "The version begins at 1 when a record is created."

        Design: Corner/entities/member_create_defaults
        """
        set_clock(api, "2026-01-01T00:00:00.000Z")
        m = validate_success(api.create_member(create_member_payload(), ADMIN), 201)
        assert m["tier"] == "BASE", m
        assert m["points_balance"] == 0, m
        assert m["qualifying_segments_ytd"] == 0, m
        assert m["status_match_used"] is False, m
        assert m["version"] == 1, m

    def test_member_duplicate_email_rejected(self, api):
        """PRD §3.1: "The email is required, non-empty, and unique across all members;
        a second registration of an already-registered email is rejected with
        ERR_DUPLICATE_EMAIL."

        Design: Corner/entities/member_duplicate_email_rejected
        """
        set_clock(api, "2026-01-01T00:00:00.000Z")
        validate_success(api.create_member(create_member_payload(email="dup@air.test"), ADMIN), 201)
        validate_error(
            api.create_member(create_member_payload(email="dup@air.test"), ADMIN), "ERR_DUPLICATE_EMAIL"
        )

    def test_segment_points_awarded_zero_until_accrued(self, api):
        """PRD §3.2: "The computed points are stored on the segment as points_awarded
        and frozen there permanently for later compensation accounting, and the
        segment's is_qualifying flag is set to true exactly when the fare class is not
        DISCOUNT."
        PRD §3.2: "A newly booked segment is in state BOOKED."

        Design: Corner/entities/segment_points_awarded_zero_until_accrued
        """
        set_clock(api, "2026-01-01T00:00:00.000Z")
        m = create_member(api)
        seg = validate_success(
            api.create_flight_segment(
                create_flight_segment_payload(m["id"], scheduled_departure="2026-02-01T08:00:00.000Z"), AGENT
            ), 201,
        )
        assert seg["points_awarded"] == 0, seg
        assert seg["status"] == "BOOKED", seg
        assert seg["is_qualifying"] is False, seg


# ---------- section: state_machines ----------

class TestStateMachines:
    def test_segment_fly_from_booked(self, api):
        """PRD §3.2: "Once travel has happened, the agent marks the segment flown,
        moving BOOKED -> FLOWN."

        Design: Corner/state_machines/segment_fly_from_booked
        """
        m = create_member(api)
        seg = create_flown_segment(
            api, m["id"], "2026-02-02T00:00:00.000Z", scheduled_departure="2026-02-01T08:00:00.000Z"
        )
        after = validate_success(api.get_flight_segment(seg["id"], AGENT))
        assert after["status"] == "FLOWN", after

    def test_segment_accrue_from_booked_invalid_state(self, api):
        """PRD §3.2: "Attempting a transition from a state that does not permit it
        yields ERR_INVALID_STATE."

        Design: Corner/state_machines/segment_accrue_from_booked_invalid_state
        """
        set_clock(api, "2026-02-02T00:00:00.000Z")
        m = create_member(api)
        seg = create_booked_segment(api, m["id"], scheduled_departure="2026-02-01T08:00:00.000Z")
        validate_error(api.accrue_flight_segment(seg["id"], AGENT), "ERR_INVALID_STATE")

    def test_segment_cancel_after_accrued_invalid_state(self, api):
        """PRD §3.2: "ACCRUED is terminal."
        PRD §3.2: "Attempting a transition from a state that does not permit it yields
        ERR_INVALID_STATE."

        Design: Corner/state_machines/segment_cancel_after_accrued_invalid_state
        """
        m = create_member(api)
        seg = create_flown_segment(
            api, m["id"], "2026-02-02T00:00:00.000Z", scheduled_departure="2026-02-01T08:00:00.000Z"
        )
        accrue_segment(api, seg["id"])
        validate_error(api.cancel_flight_segment(seg["id"], AGENT), "ERR_INVALID_STATE")

    def test_award_fly_from_quoted_invalid_state(self, api):
        """PRD §3.5: "Finally, an OperationsAgent marks an issued award flown
        (ISSUED -> FLOWN) once the clock has reached the award's travel date."
        PRD §3.2: "Attempting a transition from a state that does not permit it yields
        ERR_INVALID_STATE."

        Design: Corner/state_machines/award_fly_from_quoted_invalid_state
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m = create_member(api)
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="ECONOMY", pricing_mode="FIXED"),
                member_headers_for(m),
            ), 201,
        )
        validate_error(api.fly_award_booking(award["id"], AGENT), "ERR_INVALID_STATE")

    def test_gift_reverse_from_settled_invalid_state(self, api):
        """PRD §3.6: "Reversing a pending gift (PENDING -> REVERSED) is also sender-only;
        because a pending gift moved no points, reversal writes no ledger rows."
        PRD §3.2: "Attempting a transition from a state that does not permit it yields
        ERR_INVALID_STATE."

        Design: Corner/state_machines/gift_reverse_from_settled_invalid_state
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        sender = create_member(api)
        recipient = create_member(api)
        inject_points(api, sender["id"], 5000)
        gift = create_pending_gift(api, sender, recipient["id"], amount=1000)
        mv = member_version(api, sender["id"])
        validate_success(
            api.settle_points_gift(gift["id"], {"expected_member_version": mv}, member_headers_for(sender))
        )
        validate_error(api.reverse_points_gift(gift["id"], member_headers_for(sender)), "ERR_INVALID_STATE")

    def test_upgrade_withdraw_after_cleared_invalid_state(self, api):
        """PRD §3.8: "A member may withdraw their own still-waitlisted request
        (WAITLISTED -> WITHDRAWN), but only while the pool has not yet been cleared."
        PRD §3.2: "Attempting a transition from a state that does not permit it yields
        ERR_INVALID_STATE."

        Design: Corner/state_machines/upgrade_withdraw_after_cleared_invalid_state
        """
        set_clock(api, "2026-04-01T00:00:00.000Z")
        m = create_member(api)
        pool = create_pool(api, flight_number="UA9", departure_at="2026-04-10T08:00:00.000Z", premium_capacity=1)
        v0 = current_pool_version(api, pool["id"])
        req = validate_success(
            api.create_upgrade_request(
                create_upgrade_request_payload(m["id"], pool["id"], v0, booked_fare_class="ECONOMY"),
                member_headers_for(m),
            ), 201,
        )
        set_clock(api, "2026-04-10T09:00:00.000Z")
        validate_success(api.clear_waitlist(pool["id"], AGENT))
        validate_error(api.withdraw_upgrade_request(req["id"], member_headers_for(m)), "ERR_INVALID_STATE")

    def test_status_match_grant_floors_effective_tier(self, api):
        """PRD §3.3: "A successful grant creates a StatusMatch in state GRANTED,
        computes the matched_tier the member is floored at, sets the member's
        status_match_active to true and status_match_used to true, and runs a tier
        recomputation so the floor takes effect immediately."
        PRD §3.3: "a rival_tier of SILVER yields a matched tier of BASE, GOLD yields
        SILVER, and PLATINUM yields GOLD."

        Design: Corner/state_machines/status_match_grant_floors_effective_tier
        """
        set_clock(api, "2026-02-01T00:00:00.000Z")
        m = create_member(api)
        sm = grant_status_match(api, m["id"], rival_tier="PLATINUM")
        assert sm["matched_tier"] == "GOLD", sm
        assert sm["status"] == "GRANTED", sm
        member = validate_success(api.get_member(m["id"], ADMIN))
        assert member["status_match_active"] is True, member
        assert member["status_match_used"] is True, member
        assert member["effective_tier"] == "GOLD", member

    def test_status_match_expires_on_clock_advance(self, api):
        """PRD §3.7: "any StatusMatch in state GRANTED whose valid_until is now in the
        past (the current instant is strictly after valid_until) moves
        GRANTED -> EXPIRED, sets the member's status_match_active to false, and triggers
        a tier recomputation that may drop the effective tier now that the floor is
        gone."

        Design: Corner/state_machines/status_match_expires_on_clock_advance
        """
        set_clock(api, "2026-02-01T00:00:00.000Z")
        m = create_member(api)
        sm = grant_status_match(api, m["id"], rival_tier="GOLD", valid_until="2026-03-01T00:00:00.000Z")
        set_clock(api, "2026-03-02T00:00:00.000Z")
        after = validate_success(api.get_status_match(sm["id"], ADMIN))
        member = validate_success(api.get_member(m["id"], ADMIN))
        assert after["status"] == "EXPIRED", after
        assert member["status_match_active"] is False, member

    def test_companion_cert_expires_on_clock_advance(self, api):
        """PRD §3.7: "Likewise, any CompanionCertificate still in state ISSUED whose
        valid_until has passed (the current instant is strictly after valid_until)
        moves ISSUED -> EXPIRED."

        Design: Corner/state_machines/companion_cert_expires_on_clock_advance
        """
        set_clock(api, "2026-02-01T00:00:00.000Z")
        m = create_member(api)
        cert = create_companion_certificate(
            api, m["id"], valid_from="2026-01-01T00:00:00.000Z", valid_until="2026-03-01T00:00:00.000Z"
        )
        set_clock(api, "2026-03-02T00:00:00.000Z")
        after = validate_success(api.get_companion_certificate(cert["id"], ADMIN))
        assert after["status"] == "EXPIRED", after

    def test_year_end_resets_qualifying_segments(self, api):
        """PRD §3.7: "when the newly derived program_year is greater than the program
        year under which a member's qualifying count was accumulated, that member's
        qualifying_segments_ytd is reset to 0 and the tier is recomputed from the
        now-empty count - floored by any still-active status match."

        Design: Corner/state_machines/year_end_resets_qualifying_segments
        """
        set_clock(api, "2026-06-01T00:00:00.000Z")
        m = create_member(api)
        inject_qualifying_segments(api, m["id"], 20)  # SILVER
        set_clock(api, "2027-01-01T00:00:00.000Z")
        member = validate_success(api.get_member(m["id"], ADMIN))
        assert member["qualifying_segments_ytd"] == 0, member
        assert member["tier"] == "BASE", member
