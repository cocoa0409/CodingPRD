"""Loyalty tier boundary precision: the inclusive SILVER threshold at 5000
and GOLD at 20000 lifetime points (PRD §3.3, §3.5, §3.6).

Points reach a member when the attended event reaches COMPLETED (PRD §3.5),
so each scenario books, confirms, checks in, and then advances the logical
clock past the event's ends_at.
"""
from test_helpers import (
    TEST_USERS,
    award_points_via_seat,
    get_member,
    make_member,
    set_clock,
)

STAFF = TEST_USERS["shop_staff_headers"]


class TestSilverBoundary:
    def _member_at_4999(self):
        """Member with exactly 4999 lifetime points: one attended seat at
        flight price 499900 (floor(499900/100) = 4999 base at BRONZE 1.0x)."""
        set_clock()
        member = make_member(email="m11@x.com")
        award_points_via_seat(
            member["id"],
            flight_price_cents=499900,
            starts_at="2026-05-02T10:00:00Z",
            ends_at="2026-05-02T12:00:00Z",
            in_session_clock="2026-05-02T11:00:00Z",
            completed_clock="2026-05-02T13:00:00Z",
        )
        return member

    def test_4999_lifetime_points_stays_bronze(self, api):
        """PRD §3.3: "When it is at least 5000 but below 20000 the tier is
        `SILVER`. Below 5000 the tier is `BRONZE`."
        PRD §3.6: "At check-in the seat's `loyalty_points_awarded` is
        computed: the base is the integer floor of `price_paid_cents` divided
        by 100, multiplied by the member's tier multiplier at check-in time
        (`BRONZE` 1.0×, `SILVER` 1.25×, `GOLD` 1.5×, `PLATINUM` 2.0×), rounded
        half-up to a whole number."
        PRD §3.5: "at which point each `ATTENDED` seat's
        `loyalty_points_awarded` is granted to its member and the member's
        `loyalty_points_balance` and `loyalty_points_lifetime` are
        recomputed."

        Design: Difficulty/boundary_precision_check/loyalty_tier_silver_boundary_exactly_5000
        """
        member = self._member_at_4999()
        data = get_member(member["id"])
        assert data["loyalty_points_lifetime"] == 4999
        assert data["loyalty_tier"] == "BRONZE", (
            "strictly below the 5000 threshold the tier must remain BRONZE"
        )

    def test_exactly_5000_lifetime_points_flips_silver(self, api):
        """PRD §3.3: "The boundary at 5000 points is precise: at exactly 5000
        lifetime points the tier flips to `SILVER` — the threshold is
        inclusive, not exclusive."
        PRD §3.6: "At check-in the seat's `loyalty_points_awarded` is
        computed: the base is the integer floor of `price_paid_cents` divided
        by 100, multiplied by the member's tier multiplier at check-in time
        (`BRONZE` 1.0×, `SILVER` 1.25×, `GOLD` 1.5×, `PLATINUM` 2.0×), rounded
        half-up to a whole number."

        Design: Difficulty/boundary_precision_check/loyalty_tier_silver_boundary_exactly_5000
        """
        member = self._member_at_4999()
        # One more point: flight price 100 -> floor(100/100) = 1 at BRONZE 1.0x.
        award_points_via_seat(
            member["id"],
            flight_price_cents=100,
            starts_at="2026-05-03T10:00:00Z",
            ends_at="2026-05-03T12:00:00Z",
            in_session_clock="2026-05-03T11:00:00Z",
            completed_clock="2026-05-03T13:00:00Z",
        )
        data = get_member(member["id"])
        assert data["loyalty_points_lifetime"] == 5000
        assert data["loyalty_tier"] == "SILVER"


class TestGoldBoundary:
    def _member_at_19999(self):
        """Member with exactly 19999 lifetime points: one attended seat at
        flight price 1999900 (floor(1999900/100) = 19999 at BRONZE 1.0x)."""
        set_clock()
        member = make_member(email="mg@x.com")
        award_points_via_seat(
            member["id"],
            flight_price_cents=1999900,
            starts_at="2026-05-02T10:00:00Z",
            ends_at="2026-05-02T12:00:00Z",
            in_session_clock="2026-05-02T11:00:00Z",
            completed_clock="2026-05-02T13:00:00Z",
        )
        return member

    def test_19999_stays_silver_then_20000_flips_gold(self, api):
        """PRD §3.3: "The member's `loyalty_tier` is derived from
        `loyalty_points_lifetime` against four inclusive-lower-bound
        thresholds. When `loyalty_points_lifetime` is at least 50000 the tier
        is `PLATINUM`. When it is at least 20000 but below 50000 the tier is
        `GOLD`. When it is at least 5000 but below 20000 the tier is
        `SILVER`. Below 5000 the tier is `BRONZE`."
        PRD §3.5: "at which point each `ATTENDED` seat's
        `loyalty_points_awarded` is granted to its member and the member's
        `loyalty_points_balance` and `loyalty_points_lifetime` are
        recomputed."

        Design: Corner/calculations/loyalty_tier_gold_at_exactly_20000
        """
        member = self._member_at_19999()
        data = get_member(member["id"])
        assert data["loyalty_points_lifetime"] == 19999
        assert data["loyalty_tier"] == "SILVER"
        award_points_via_seat(
            member["id"],
            flight_price_cents=100,
            starts_at="2026-05-03T10:00:00Z",
            ends_at="2026-05-03T12:00:00Z",
            in_session_clock="2026-05-03T11:00:00Z",
            completed_clock="2026-05-03T13:00:00Z",
        )
        data = get_member(member["id"])
        assert data["loyalty_points_lifetime"] == 20000
        assert data["loyalty_tier"] == "GOLD"
