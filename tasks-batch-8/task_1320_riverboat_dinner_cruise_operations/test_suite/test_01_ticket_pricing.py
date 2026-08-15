"""Ticket and beverage-package pricing: pinned rounding, tiers, seasons,
holiday premium, and derived season/holiday fields (PRD §3.2, §3.3)."""
from test_helpers import (
    TEST_USERS,
    assign_confirmed_bartender,
    create_booking,
    create_cruise,
    create_customer,
    get_cruise,
    pay_booking,
    setup_inventory,
)

OM = TEST_USERS["ops_manager_headers"]


class TestTicketPricingStack:
    def test_holiday_peak_party_of_four_priced_in_pinned_order(self, api):
        """PRD §3.3: "Ticket pricing is a pinned four-step evaluation, in this
        exact order."
        PRD §3.3: "parties of four or five receive five percent off"
        PRD §3.3: "only when the cruise's `is_holiday` flag is true, a flat
        holiday premium of 1,500 cents per passenger — the `party_size`
        multiplied by 1,500 cents — is added to the seasonal result; on
        non-holiday departures nothing is added."

        Design: Difficulty/combinatorial_formula/ticket_pricing_tiered_seasonal_holiday_stack
        """
        inv = setup_inventory()
        cruise_h = create_cruise(inv["vessel"]["id"], inv["tier"]["id"],
                                 depart_at="2026-07-04T19:00:00Z",
                                 return_at="2026-07-04T22:00:00Z")
        cruise_n = create_cruise(inv["vessel"]["id"], inv["tier"]["id"],
                                 depart_at="2026-06-27T19:00:00Z",
                                 return_at="2026-06-27T22:00:00Z")
        customer = create_customer("a@example.com", "A")

        bk_h = create_booking(cruise_h["id"], customer["id"], 4,
                              cruise_h["version"])
        bk_n = create_booking(cruise_n["id"], customer["id"], 4,
                              cruise_n["version"])

        cruise_h_after = get_cruise(cruise_h["id"])
        cruise_n_after = get_cruise(cruise_n["id"])
        assert cruise_h_after["season"] == "PEAK"
        assert cruise_h_after["is_holiday"] is True
        assert cruise_n_after["season"] == "PEAK"
        assert cruise_n_after["is_holiday"] is False
        # 4*8900=35600 -> 5% off = 33820 -> *1.25 = 42275 -> +4*1500 = 48275
        assert bk_h["booking_total_cents"] == 48275, (
            f"Holiday PEAK party of 4 must total 48275, got "
            f"{bk_h['booking_total_cents']}"
        )
        # Same party one week earlier: 42275 (no holiday premium)
        assert bk_n["booking_total_cents"] == 42275, (
            f"Non-holiday PEAK party of 4 must total 42275, got "
            f"{bk_n['booking_total_cents']}"
        )

    def test_holiday_premium_not_applied_on_non_holiday_same_season(self, api):
        """PRD §3.2: "The flag `is_holiday` is true exactly when the departure's
        UTC calendar date falls in the fixed holiday set: 2026-07-04, 2026-09-07,
        2026-12-25, or 2026-12-31."
        PRD §3.3: "on non-holiday departures nothing is added."

        Design: Difficulty/combinatorial_formula/ticket_pricing_tiered_seasonal_holiday_stack
        """
        inv = setup_inventory()
        cruise = create_cruise(inv["vessel"]["id"], inv["tier"]["id"],
                               depart_at="2026-07-11T19:00:00Z",
                               return_at="2026-07-11T22:00:00Z")
        customer = create_customer("b@example.com", "B")
        booking = create_booking(cruise["id"], customer["id"], 4,
                                 cruise["version"])
        cruise_after = get_cruise(cruise["id"])
        assert cruise_after["season"] == "PEAK"
        assert cruise_after["is_holiday"] is False
        assert booking["booking_total_cents"] == 42275


class TestBarPackagePerLineRounding:
    def test_per_line_rounding_pinned_over_aggregate(self, api):
        """PRD §3.3: "Rounding each package line first and then multiplying is
        pinned — computing eighteen percent on the aggregate and rounding once
        is a different, non-conformant calculation."
        PRD §3.3: "when `bar_package_count` is greater than zero, the cruise's
        `bar_service_enabled` must be true at that moment (otherwise
        `ERR_BAR_SERVICE_UNAVAILABLE`"

        Design: Difficulty/combinatorial_formula/bar_package_per_line_rounding_order
        """
        inv = setup_inventory(tier_overrides={"code": "PREMIUM",
                                              "base_price_cents": 12000,
                                              "galley_load_per_cover": 3.0,
                                              "bar_package_price_cents": 4199})
        cruise = inv["cruise"]
        assign_confirmed_bartender(cruise["id"])
        customer = create_customer("a@example.com", "A")
        # Confirming the bartender recomputes bar_service_enabled, which bumps
        # the cruise version (PRD §2.10) — re-read before the OCC token.
        booking = create_booking(cruise["id"], customer["id"], 3,
                                 get_cruise(cruise["id"])["version"],
                                 bar_package_count=3)
        paid = pay_booking(booking["id"], customer["id"])

        # round_half_up(4199*0.18)=756 per line; (4199+756)*3 = 14865
        assert paid["bar_package_total_cents"] == 14865, (
            f"Per-line rounding pins 14865 (aggregate-first gives 14864), got "
            f"{paid['bar_package_total_cents']}"
        )
        assert paid["payment_status"] == "PAID"
        assert get_cruise(cruise["id"])["bar_service_enabled"] is True

    def test_bar_total_is_per_package_price_times_count(self, api):
        """PRD §3.3: "the per-package price is then the `bar_package_price_cents`
        plus that rounded gratuity; and the booking's `bar_package_total_cents`
        is the per-package price multiplied by `bar_package_count`."

        Design: Difficulty/combinatorial_formula/bar_package_per_line_rounding_order
        """
        inv = setup_inventory()  # bar_package_price_cents 4200
        cruise = inv["cruise"]
        assign_confirmed_bartender(cruise["id"])
        customer = create_customer("c@example.com", "C")
        # Confirming the bartender recomputes bar_service_enabled, which bumps
        # the cruise version (PRD §2.10) — re-read before the OCC token.
        booking = create_booking(cruise["id"], customer["id"], 2,
                                 get_cruise(cruise["id"])["version"],
                                 bar_package_count=2)
        paid = pay_booking(booking["id"], customer["id"])
        # round_half_up(4200*0.18)=756; (4200+756)*2 = 9912
        assert paid["bar_package_total_cents"] == 9912, (
            f"Expected 9912, got {paid['bar_package_total_cents']}"
        )


class TestSeasonalMultiplierConstants:
    def test_off_and_shoulder_multipliers_applied(self, api):
        """PRD §3.3: "the discounted line is multiplied by the cruise's seasonal
        multiplier: 1.25 for a `PEAK` sailing, 1.10 for `SHOULDER`, and 1.00 for
        `OFF`"
        PRD §3.2: "The cruise's `season` is `PEAK` when the departure month is
        June, July, or August; `SHOULDER` when it is May or September; and `OFF`
        in every other month."

        Design: Corner/calculations/seasonal_multiplier_constants_applied
        """
        inv = setup_inventory()
        cr_off = create_cruise(inv["vessel"]["id"], inv["tier"]["id"],
                               depart_at="2026-01-15T19:00:00Z",
                               return_at="2026-01-15T22:00:00Z")
        cr_sh = create_cruise(inv["vessel"]["id"], inv["tier"]["id"],
                              depart_at="2026-09-15T19:00:00Z",
                              return_at="2026-09-15T22:00:00Z")
        customer = create_customer("a@example.com", "A")
        bk_off = create_booking(cr_off["id"], customer["id"], 2,
                                cr_off["version"])
        bk_sh = create_booking(cr_sh["id"], customer["id"], 2,
                               cr_sh["version"])
        # party 2: no discount; OFF 2*8900*1.00 = 17800
        assert bk_off["booking_total_cents"] == 17800, (
            f"OFF-season party of 2 must total 17800, got "
            f"{bk_off['booking_total_cents']}"
        )
        # SHOULDER round_half_up(17800*1.10) = 19580
        assert bk_sh["booking_total_cents"] == 19580, (
            f"SHOULDER-season party of 2 must total 19580, got "
            f"{bk_sh['booking_total_cents']}"
        )


class TestPartyDiscountTierBoundaries:
    def test_discount_tiers_at_three_six_ten(self, api):
        """PRD §3.3: "parties of ten or more receive fifteen percent off;
        parties of six to nine receive ten percent off; parties of four or five
        receive five percent off; parties of three or fewer receive no discount."
        PRD §3.3: "The discounted line is rounded half-up to whole cents — the
        first pinned rounding step."

        Design: Corner/calculations/party_discount_tier_boundaries
        """
        # OFF season (January) isolates the tier: multiplier 1.00, no holiday.
        inv = setup_inventory(depart_at="2026-01-15T19:00:00Z",
                              return_at="2026-01-15T22:00:00Z")
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")

        expected = {3: 26700, 4: 33820, 6: 48060, 10: 75650}
        version = cruise["version"]
        for party_size, expected_total in expected.items():
            booking = create_booking(cruise["id"], customer["id"], party_size,
                                     version)
            assert booking["booking_total_cents"] == expected_total, (
                f"party_size {party_size} must total {expected_total}, got "
                f"{booking['booking_total_cents']}"
            )
            version = get_cruise(cruise["id"])["version"]


class TestCruiseSeasonDerivation:
    def test_january_cruise_derives_off_season(self, api):
        """PRD §3.2: "`SHOULDER` when it is May or September; and `OFF` in every
        other month."
        PRD §3.2: "The flag `is_holiday` is true exactly when the departure's
        UTC calendar date falls in the fixed holiday set: 2026-07-04, 2026-09-07,
        2026-12-25, or 2026-12-31."

        Design: Corner/entities/cruise_off_season_derivation
        """
        inv = setup_inventory()
        cruise = create_cruise(inv["vessel"]["id"], inv["tier"]["id"],
                               depart_at="2026-01-15T19:00:00Z",
                               return_at="2026-01-15T22:00:00Z")
        assert cruise["season"] == "OFF", (
            f"January departure must derive season OFF, got {cruise['season']}"
        )
        assert cruise["is_holiday"] is False
