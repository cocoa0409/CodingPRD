"""Pricing and billing calculations: dual-variant rental/trip totals and the
combinatorial fill-price / trip-discount-rounding formulas.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula.
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    make_shop_admin_headers, make_instructor_headers,
    create_diver, sign_waiver, create_rental, set_clock,
    setup_trip_with_certified_diver, setup_nitrox_certified_diver,
)
from test_helpers import factories as f

ADMIN = make_shop_admin_headers()


class TestRentalChargeDualVariant:
    def test_rental_estimated_and_actual_charges_diverge(self, api):
        """PRD 3.8: "The `estimated_cost_cents`, projected forward at checkout
        against the planned return, is the billed days from `checkout_at` to
        `scheduled_return_at` multiplied by the `daily_rate_cents`; it deliberately
        excludes any late surcharge and damage fee, neither of which is known yet."
        PRD 3.8: "The `actual_cost_cents` is the on-time days at the standard daily
        rate, plus the late days at the late-day rate, plus the `damage_fee_cents`."

        Design: Difficulty/dual_variant_calc/rental_charge_estimated_vs_actual_diverge
        """
        set_clock("2026-06-10T09:00:00Z")
        diver = create_diver(full_name="Rita Renter")
        rental = create_rental(
            diver["id"], item_description="BCD + reg set",
            daily_rate_cents=4500, deposit_cents=20000,
            scheduled_return_at="2026-06-12T09:00:00Z",
        )
        assert rental["estimated_cost_cents"] == 9000, rental
        set_clock("2026-06-13T15:00:00Z")
        data = validate_success(
            api.checkin_rental_agreement(rental["id"], {}, ADMIN)
        )
        assert data["actual_cost_cents"] == 22500, data
        assert data["actual_cost_cents"] != data["estimated_cost_cents"]

    def test_trip_total_solo_vs_group_diverge(self, api):
        """PRD 3.7: "A group discount of 15 percent applies to that subtotal when
        the `party_size` is at least 4; for a smaller party no discount applies (a
        discount of zero)."
        PRD 3.7: "The discount is applied to the summed subtotal as a single step,
        and the discounted amount is then rounded half-up once to whole cents to
        yield `total_cents` — the line items are never rounded individually before
        summing."

        Design: Difficulty/dual_variant_calc/trip_total_solo_vs_group_diverge
        """
        # Two OPEN_WATER-certified divers; trip base 12000 + fill_addon 1500.
        boat, trip, diver_solo = setup_trip_with_certified_diver(
            trip_overrides={"base_fare_cents": 12000, "fill_addon_cents": 1500},
            diver_full_name="Solo Sam",
        )
        # A second certified diver for the group booking.
        diver_grp = setup_nitrox_certified_diver()  # cert_level OPEN_WATER + waiver
        trip_now = get_success_data(api.get_dive_trip(trip["id"], ADMIN))

        tb_solo = validate_success(
            api.create_trip_booking(
                f.create_trip_booking_payload(
                    trip["id"], diver_solo["id"], trip_now["version"],
                    tanks=2, party_size=1,
                ), ADMIN,
            ), expected_status=201,
        )
        trip_now = get_success_data(api.get_dive_trip(trip["id"], ADMIN))
        tb_grp = validate_success(
            api.create_trip_booking(
                f.create_trip_booking_payload(
                    trip["id"], diver_grp["id"], trip_now["version"],
                    tanks=2, party_size=4,
                ), ADMIN,
            ), expected_status=201,
        )
        # subtotal = 12000 + 2*1500 = 15000; solo => 15000, group => round(15000*0.85)=12750
        assert tb_solo["total_cents"] == 15000, tb_solo
        assert tb_grp["total_cents"] == 12750, tb_grp
        assert tb_solo["total_cents"] != tb_grp["total_cents"]


class TestCombinatorialFormulas:
    def test_fill_price_nitrox_mid_band_large_tank(self, api):
        """PRD 3.9: "A `NITROX` fill adds a surcharge banded by oxygen percentage:
        800 cents when `o2_pct` is at most 32, 1400 cents when `o2_pct` is at most
        36 (that is, 33 through 36), and 2200 cents when `o2_pct` is higher (37
        through 40)."
        PRD 3.9: "A large-tank factor then applies: if `tank_capacity_liters` is
        greater than 12 the subtotal is multiplied by 1.25, otherwise by 1.0. The
        final `price_cents` is that product rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/fill_price_tiered_three_inputs_mode_a
        """
        diver = setup_nitrox_certified_diver()
        # 36% (mid band: base 1200 + 1400 = 2600) * 1.25 (15L > 12) = 3250
        fill = validate_success(
            api.create_fill_service(
                f.create_fill_service_payload(
                    diver["id"], gas="NITROX", o2_pct=36, tank_capacity_liters=15
                ), ADMIN,
            ), expected_status=201,
        )
        assert fill["price_cents"] == 3250, fill

    def test_trip_total_discount_applied_then_rounded_once(self, api):
        """PRD 3.7: "The discount is applied to the summed subtotal as a single
        step, and the discounted amount is then rounded half-up once to whole cents
        to yield `total_cents` — the line items are never rounded individually
        before summing."
        PRD 3.7: "The `deposit_cents` is `total_cents` multiplied by 30 percent,
        rounded half-up to whole cents. The `balance_due_cents` is `total_cents`
        minus `deposit_cents`."

        Design: Difficulty/combinatorial_formula/trip_total_round_after_discount_mode_b
        """
        boat, trip, diver = setup_trip_with_certified_diver(
            trip_overrides={"base_fare_cents": 12000, "fill_addon_cents": 1500},
            diver_full_name="Pat Party",
        )
        trip_now = get_success_data(api.get_dive_trip(trip["id"], ADMIN))
        tb = validate_success(
            api.create_trip_booking(
                f.create_trip_booking_payload(
                    trip["id"], diver["id"], trip_now["version"],
                    tanks=2, party_size=4,
                ), ADMIN,
            ), expected_status=201,
        )
        # subtotal 15000 -> round(15000*0.85)=12750; deposit round(12750*0.30)=3825
        assert tb["total_cents"] == 12750, tb
        assert tb["deposit_cents"] == 3825, tb
        assert tb["balance_due_cents"] == 8925, tb
