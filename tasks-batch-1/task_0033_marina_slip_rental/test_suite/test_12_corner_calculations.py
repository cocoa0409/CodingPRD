"""Corner — calculations section.

Pump-out charge and winter-seasonal-pricing calculations.
"""
from test_helpers import (
    validate_success,
    set_clock,
    create_marina,
    create_slip,
    setup_tenant_with_vessel,
    reserve_lease,
    check_in_lease,
    create_pump_out_request,
    TEST_USERS,
)


class TestPumpoutChargeZeroWhenSlipHasIntegratedPumpout:

    def test_pumpout_complete_on_integrated_slip_pins_zero_charge(self, api):
        """PRD §3.6: "On completion, the request's `charge_cents` is pinned by the pump-out charge rule: if the slip's `pumpout_available` is true, the charge is zero (a marina with integrated plumbing absorbs the fee); otherwise the charge is `PUMPOUT_PORTABLE_FEE_CENTS` of twenty-five dollars in cents, reflecting the portable-cart operation."

        Design: Corner/calculations/pumpout_charge_zero_when_slip_has_integrated_pumpout
        """
        marina = create_marina(liveaboard_cap=1)
        slip = create_slip(
            marina["id"], slip_number="P-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            pumpout_available=True,
            base_daily_rate_cents=5000,
        )
        tv = setup_tenant_with_vessel()
        tenant, vessel = tv["tenant"], tv["vessel"]
        set_clock("2026-07-01T00:00:00Z")
        lease = reserve_lease(
            marina["id"], slip["id"], tenant["id"], vessel["id"],
            "2026-07-10", "2026-07-15", slip["version"],
        )
        set_clock("2026-07-10T00:00:00Z")
        check_in_lease(lease["id"])
        po = create_pump_out_request(lease["id"], tenant["id"])
        res = api.complete_pump_out_request(po["id"], TEST_USERS["marina_staff_headers"])
        data = validate_success(res, expected_status=200)
        assert data["charge_cents"] == 0, \
            f"integrated slip pumpout charge must be 0, got {data['charge_cents']}"
        assert data["status"] == "COMPLETED"


class TestPumpoutChargePortableWhenNoIntegratedPumpout:

    def test_pumpout_complete_on_portable_slip_pins_2500_cents(self, api):
        """PRD §3.6: "On completion, the request's `charge_cents` is pinned by the pump-out charge rule: if the slip's `pumpout_available` is true, the charge is zero (a marina with integrated plumbing absorbs the fee); otherwise the charge is `PUMPOUT_PORTABLE_FEE_CENTS` of twenty-five dollars in cents, reflecting the portable-cart operation."

        Design: Corner/calculations/pumpout_charge_portable_when_no_integrated_pumpout
        """
        marina = create_marina(liveaboard_cap=1)
        slip = create_slip(
            marina["id"], slip_number="PF-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            pumpout_available=False,
            base_daily_rate_cents=5000,
        )
        tv = setup_tenant_with_vessel()
        tenant, vessel = tv["tenant"], tv["vessel"]
        set_clock("2026-07-01T00:00:00Z")
        lease = reserve_lease(
            marina["id"], slip["id"], tenant["id"], vessel["id"],
            "2026-07-10", "2026-07-15", slip["version"],
        )
        set_clock("2026-07-10T00:00:00Z")
        check_in_lease(lease["id"])
        po = create_pump_out_request(lease["id"], tenant["id"])
        res = api.complete_pump_out_request(po["id"], TEST_USERS["marina_staff_headers"])
        data = validate_success(res, expected_status=200)
        # twenty-five dollars in cents == 2500
        assert data["charge_cents"] == 2500, \
            f"portable pumpout fee must be 2500 cents, got {data['charge_cents']}"


class TestWinterPricingBelowBase:

    def test_winter_lease_uses_zero_point_eight_multiplier(self, api):
        """PRD §3.5: "The lease falls into the SUMMER tier when its `start_date` (month-day component) lies on or between `season_summer_start` and `season_summer_end` inclusive, and into the WINTER tier otherwise."
        PRD §3.5: "The WINTER multiplier is eighty hundredths (numerator 80, denominator 100, i.e. zero point eight)."

        Design: Corner/calculations/winter_pricing_below_base
        """
        # Marina defaults season_summer_start/end to 05-01..09-30 per PRD §3.1.
        marina = create_marina(liveaboard_cap=1)
        slip = create_slip(
            marina["id"], slip_number="W-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            base_daily_rate_cents=5000,
        )
        tv = setup_tenant_with_vessel(insurance_expires_on="2027-06-01")
        tenant, vessel = tv["tenant"], tv["vessel"]
        set_clock("2026-01-01T00:00:00Z")
        lease = reserve_lease(
            marina["id"], slip["id"], tenant["id"], vessel["id"],
            "2026-01-15", "2026-01-18", slip["version"],  # 3 nights WINTER
        )
        set_clock("2026-01-15T00:00:00Z")
        res = api.check_in_lease(lease["id"], TEST_USERS["marina_staff_headers"])
        data = validate_success(res, expected_status=200)
        # 5000 * 80/100 = 4000 nightly; 3 * 4000 = 12000 total (no liveaboard).
        assert data["nightly_rate_cents"] == 4000, \
            f"WINTER 5000*0.8 = 4000, got {data['nightly_rate_cents']}"
        assert data["total_cost_cents"] == 12000, \
            f"3 nights * 4000 = 12000, got {data['total_cost_cents']}"
