"""Queue B (Corner) — business-rule and input-domain validation rejections."""
from test_helpers import validate_success, validate_error
from test_helpers.test_users import TEST_USERS
from test_helpers.fixtures import (
    set_clock, create_member, member_headers_for, grant_status_match,
    create_companion_certificate, create_booked_segment, inject_points, create_pool,
    create_pending_gift, member_version,
)
from test_helpers.factories import (
    create_award_booking_payload, create_flight_segment_payload, create_points_gift_payload,
    create_status_match_payload, create_flight_pool_payload,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]


class TestValidations:
    def test_dynamic_pricing_requires_load_factor(self, api):
        """PRD §3.5: "Dynamic pricing requires a load_factor and fixed pricing must omit
        it. A DYNAMIC quote with no load_factor, a FIXED quote that supplies one, or
        any load_factor outside the inclusive range from 0 to 1 is rejected with
        ERR_LOAD_FACTOR_REQUIRED."

        Design: Corner/validations/dynamic_pricing_requires_load_factor
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m = create_member(api)
        validate_error(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="ECONOMY", pricing_mode="DYNAMIC"),
                member_headers_for(m),
            ),
            "ERR_LOAD_FACTOR_REQUIRED",
        )

    def test_status_match_lifetime_exhausted(self, api):
        """PRD §3.3: "The match is a once-in-a-lifetime benefit: if the member's
        status_match_used flag is already true, the grant is refused with
        ERR_STATUS_MATCH_EXHAUSTED."

        Design: Corner/validations/status_match_lifetime_exhausted
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m = create_member(api)
        grant_status_match(api, m["id"], rival_tier="GOLD")
        validate_error(
            api.create_status_match(create_status_match_payload(m["id"], rival_tier="SILVER"), ADMIN),
            "ERR_STATUS_MATCH_EXHAUSTED",
        )

    def test_gift_to_self_rejected(self, api):
        """PRD §3.6: "The recipient must differ from the sender; a self-gift is rejected
        with ERR_GIFT_TO_SELF."

        Design: Corner/validations/gift_to_self_rejected
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m = create_member(api)
        validate_error(
            api.create_points_gift(create_points_gift_payload(m["id"], m["id"], amount=100), member_headers_for(m)),
            "ERR_GIFT_TO_SELF",
        )

    def test_fly_before_departure_rejected(self, api):
        """PRD §3.2: "This is only permitted once the clock has reached departure: the
        current instant must be at or after the segment's scheduled_departure. An
        attempt to fly a segment before that instant is rejected with
        ERR_DEPARTURE_NOT_REACHED."

        Design: Corner/validations/fly_before_departure_rejected
        """
        set_clock(api, "2026-01-01T00:00:00.000Z")
        m = create_member(api)
        seg = create_booked_segment(api, m["id"], scheduled_departure="2026-06-01T08:00:00.000Z")
        validate_error(api.fly_flight_segment(seg["id"], AGENT), "ERR_DEPARTURE_NOT_REACHED")

    def test_pool_clear_twice_rejected(self, api):
        """PRD §3.8: "The run is gated twice: it may only execute when the pool has not
        already been cleared and only at or after the pool's departure_at; invoking it
        on an already-cleared pool, or before departure, is rejected with
        ERR_POOL_ALREADY_CLEARED."

        Design: Corner/validations/pool_clear_twice_rejected
        """
        set_clock(api, "2026-04-01T00:00:00.000Z")
        pool = create_pool(api, flight_number="UA8", departure_at="2026-04-05T08:00:00.000Z", premium_capacity=2)
        set_clock(api, "2026-04-05T09:00:00.000Z")
        validate_success(api.clear_waitlist(pool["id"], AGENT))
        validate_error(api.clear_waitlist(pool["id"], AGENT), "ERR_POOL_ALREADY_CLEARED")

    def test_insufficient_points_on_gift_settle(self, api):
        """PRD §3.6: "It is permitted only when the sender's points_balance is at least
        the gift amount; otherwise it is rejected with ERR_INSUFFICIENT_POINTS."

        Design: Corner/validations/insufficient_points_on_gift_settle
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        sender = create_member(api)
        recipient = create_member(api)
        inject_points(api, sender["id"], 500)
        gift = create_pending_gift(api, sender, recipient["id"], amount=2000)
        mv = member_version(api, sender["id"])
        validate_error(
            api.settle_points_gift(gift["id"], {"expected_member_version": mv}, member_headers_for(sender)),
            "ERR_INSUFFICIENT_POINTS",
        )

    def test_gift_zero_amount_rejected(self, api):
        """PRD §3.6: "An amount below the minimum of 1 is rejected with
        ERR_GIFT_AMOUNT_INVALID."

        Design: Corner/validations/gift_zero_amount_rejected
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m1 = create_member(api)
        m2 = create_member(api)
        validate_error(
            api.create_points_gift(create_points_gift_payload(m1["id"], m2["id"], amount=0), member_headers_for(m1)),
            "ERR_GIFT_AMOUNT_INVALID",
        )

    def test_pool_negative_capacity_rejected(self, api):
        """PRD §3.8: "the premium_capacity - the total number of premium seats available
        for upgrade clearance, which must be a non-negative integer; a negative
        capacity is rejected with ERR_POOL_CAPACITY_INVALID."

        Design: Corner/validations/pool_negative_capacity_rejected
        """
        set_clock(api, "2026-04-01T00:00:00.000Z")
        validate_error(
            api.create_flight_pool(
                create_flight_pool_payload(flight_number="UA0", premium_capacity=-1), AGENT
            ),
            "ERR_POOL_CAPACITY_INVALID",
        )

    def test_bad_iata_code_rejected(self, api):
        """PRD §3.2: "supplying the member_id, the origin and destination IATA codes
        (each exactly three uppercase letters, and the destination must differ from the
        origin)."
        PRD §3.1: "The home airport is an IATA code of exactly three uppercase letters;
        a malformed code fails generic input validation."

        Design: Corner/validations/bad_iata_code_rejected
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m = create_member(api)
        validate_error(
            api.create_flight_segment(
                create_flight_segment_payload(
                    m["id"], origin="sf", destination="LAX", scheduled_departure="2026-04-01T08:00:00.000Z"
                ),
                AGENT,
            ),
            "ERR_VALIDATION",
        )

    def test_certificate_window_excludes_attach_rejected(self, api):
        """PRD §3.5: "a certificate that is not ISSUED or whose window does not cover the
        travel is rejected with ERR_CERTIFICATE_NOT_VALID."

        Design: Corner/validations/certificate_window_excludes_attach_rejected
        """
        set_clock(api, "2026-01-01T00:00:00.000Z")
        m = create_member(api)
        cert = create_companion_certificate(
            api, m["id"], valid_from="2026-01-01T00:00:00.000Z", valid_until="2026-01-05T00:00:00.000Z"
        )
        set_clock(api, "2026-02-01T00:00:00.000Z")  # past the window; cert now EXPIRED / window excludes attach
        validate_error(
            api.create_award_booking(
                create_award_booking_payload(
                    m["id"], cabin="ECONOMY", pricing_mode="FIXED", companion_certificate_id=cert["id"]
                ),
                member_headers_for(m),
            ),
            "ERR_CERTIFICATE_NOT_VALID",
        )
