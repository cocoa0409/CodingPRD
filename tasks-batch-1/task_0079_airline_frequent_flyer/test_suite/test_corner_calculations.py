"""Queue B (Corner) — calculation formula outputs."""
from test_helpers import validate_success
from test_helpers.test_users import TEST_USERS
from test_helpers.fixtures import (
    set_clock, create_member, member_headers_for, grant_status_match,
    create_flown_segment, accrue_segment, create_pool, current_pool_version, inject_points,
)
from test_helpers.factories import create_award_booking_payload, create_upgrade_request_payload

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]


class TestCalculations:
    def test_award_pricing_fixed_first_class(self, api):
        """PRD §3.5: "A base chart price is read for the cabin: ECONOMY is 25000,
        BUSINESS is 60000, and FIRST is 100000 points. Under FIXED pricing the cabin
        price is exactly that chart value, independent of demand."

        Design: Corner/calculations/award_pricing_fixed_first_class
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m = create_member(api)
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="FIRST", pricing_mode="FIXED"),
                member_headers_for(m),
            ), 201,
        )
        assert award["points_price"] == 100000, award

    def test_dynamic_load_factor_zero_floor(self, api):
        """PRD §3.5: "the chart value is multiplied by the quantity zero-point-eight
        plus zero-point-eight times the load_factor, then rounded half-up - so the
        multiplier ranges from 0.8 at a load factor of 0 to 1.6 at a load factor of 1."

        Design: Corner/calculations/dynamic_load_factor_zero_floor
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m = create_member(api)
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="ECONOMY", pricing_mode="DYNAMIC", load_factor=0),
                member_headers_for(m),
            ), 201,
        )
        assert award["points_price"] == 20000, award  # 25000*0.8

    def test_accrual_first_class_platinum_bonus(self, api):
        """PRD §3.2: "A tier bonus percentage is then selected from the member's
        effective tier at the accrual instant: 0 for BASE, 25 for SILVER, 50 for GOLD,
        and 100 for PLATINUM."
        PRD §3.3: "a rival_tier of SILVER yields a matched tier of BASE, GOLD yields
        SILVER, and PLATINUM yields GOLD."

        Design: Corner/calculations/accrual_first_class_platinum_bonus
        """
        set_clock(api, "2026-02-01T00:00:00.000Z")
        m = create_member(api)
        grant_status_match(api, m["id"], rival_tier="PLATINUM")  # matched GOLD -> bonus 50%
        seg = create_flown_segment(
            api, m["id"], "2026-02-01T00:00:01.000Z",
            origin="SFO", destination="LAX", fare_class="FIRST",
            distance_miles=340, base_fare_usd=1000, scheduled_departure="2026-01-25T08:00:00.000Z",
        )
        accrued = accrue_segment(api, seg["id"])
        # base=1000*2.0=2000; floor=170; max=2000; GOLD 50% -> 3000
        assert accrued["points_awarded"] == 3000, accrued

    def test_discount_fare_not_qualifying(self, api):
        """PRD §3.2: "the segment's is_qualifying flag is set to true exactly when the
        fare class is not DISCOUNT."
        PRD §3.2: "If the segment is qualifying, the member's qualifying_segments_ytd
        increases by 1, which triggers a tier recomputation."

        Design: Corner/calculations/discount_fare_not_qualifying
        """
        set_clock(api, "2026-02-02T00:00:00.000Z")
        m = create_member(api)
        seg = create_flown_segment(
            api, m["id"], "2026-02-02T00:00:01.000Z",
            origin="SFO", destination="LAX", fare_class="DISCOUNT",
            distance_miles=340, base_fare_usd=100, scheduled_departure="2026-02-01T08:00:00.000Z",
        )
        accrue_segment(api, seg["id"])
        after = validate_success(api.get_flight_segment(seg["id"], AGENT))
        member = validate_success(api.get_member(m["id"], ADMIN))
        assert after["is_qualifying"] is False, after
        assert member["qualifying_segments_ytd"] == 0, member

    def test_upgrade_priority_score_value(self, api):
        """PRD §3.8: "The priority score is the rank of the member's effective tier
        multiplied by 1000 - using the ranks BASE 0, SILVER 1, GOLD 2, PLATINUM 3 -
        plus a fare-class weight of 0 for DISCOUNT, 10 for ECONOMY, 20 for BUSINESS,
        and 30 for FIRST."

        Design: Corner/calculations/upgrade_priority_score_value
        """
        set_clock(api, "2026-04-01T00:00:00.000Z")
        m = create_member(api)
        grant_status_match(api, m["id"], rival_tier="PLATINUM")  # effective GOLD -> rank 2
        pool = create_pool(api, flight_number="UA7", departure_at="2026-04-10T08:00:00.000Z", premium_capacity=2)
        v0 = current_pool_version(api, pool["id"])
        req = validate_success(
            api.create_upgrade_request(
                create_upgrade_request_payload(m["id"], pool["id"], v0, booked_fare_class="BUSINESS"),
                member_headers_for(m),
            ), 201,
        )
        assert req["priority_score"] == 2020, req  # 2*1000 + 20

    def test_expiry_sweep_burns_inactive_lot(self, api):
        """PRD §3.7: "For each member whose account has been inactive beyond the
        expiration window of 18 months - that is, the elapsed time from the member's
        last_activity_at to the current instant exceeds 18 months - the sweep expires
        that member's positive ledger lots whose expires_at is at or before the current
        instant."

        Design: Corner/calculations/expiry_sweep_burns_inactive_lot
        """
        set_clock(api, "2026-01-01T00:00:00.000Z")
        m = create_member(api)
        inject_points(api, m["id"], 5000)  # lot expires 2027-07-01
        set_clock(api, "2027-08-01T00:00:00.000Z")
        member = validate_success(api.get_member(m["id"], ADMIN))
        assert member["points_balance"] == 0, member
