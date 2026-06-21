"""Difficulty Rule 2 — combinatorial_formula.

Two combinatorial-mode instances:
  (A) Per-step rounding pins seasonal pricing at 550 (base 333, SUMMER liveaboard);
      a single end-of-formula round would yield 549.
  (B) Tow-assist outcome with valid insurance and out-of-radius distance pins
      OUT_OF_RADIUS — proving step 1 passed before step 2 was evaluated.
"""
from test_helpers import (
    validate_success,
    set_clock,
    create_marina,
    create_slip,
    setup_tenant_with_vessel,
    make_tenant_approved_for_liveaboard,
    reserve_lease,
    create_tow_assist_event_payload,
    make_tenant_headers,
    TEST_USERS,
)


class TestSeasonalPricingPerStepRoundingPinsValue:
    """base_daily_rate_cents = 333 in SUMMER liveaboard:
      step 2: 333 * 150/100 = 499.5 -> round_half_up -> 500
      step 3: 500 * 110/100 = 550 -> round_half_up -> 550
    Sum-then-round (333 * 1.65 = 549.45 -> 549) would diverge by 1 cent.
    """

    def _setup_lease(self):
        marina = create_marina(liveaboard_cap=3)
        slip = create_slip(
            marina["id"],
            slip_number="C-1",
            length_ft=50,
            beam_ft=15,
            power_amp="A50",
            pumpout_available=True,
            liveaboard_allowed=True,
            base_daily_rate_cents=333,
        )
        tv = setup_tenant_with_vessel(loa_ft=40, beam_ft=12)
        tenant, vessel = tv["tenant"], tv["vessel"]
        make_tenant_approved_for_liveaboard(tenant["id"], marina["id"])
        set_clock("2026-07-01T00:00:00Z")
        lease = reserve_lease(
            marina_id=marina["id"],
            slip_id=slip["id"],
            tenant_id=tenant["id"],
            vessel_id=vessel["id"],
            start_date="2026-07-10",
            end_date="2026-07-12",  # 2 nights
            expected_slip_version=slip["version"],
            is_liveaboard=True,
        )
        set_clock("2026-07-10T00:00:00Z")
        return lease

    def test_per_step_rounded_nightly_rate_is_550_not_549(self, api):
        """PRD §3.5: "Rounding is applied independently at step two and at step three; the system does not collapse the two multiplications into a single multiplication and round only once, and the intermediate rounding at step two can produce a per-step rounded result that differs from sum-then-round arithmetic on certain inputs."

        Design: Difficulty/combinatorial_formula/seasonal_pricing_per_step_rounding_pins_value
        """
        lease = self._setup_lease()
        res = api.check_in_lease(lease["id"], TEST_USERS["marina_staff_headers"])
        data = validate_success(res, expected_status=200)
        # Per-step rounding: 333 * 1.5 = 499.5 -> 500; 500 * 1.1 = 550.
        # Sum-then-round (333 * 1.65 = 549.45 -> 549) would FAIL this assertion.
        assert data["nightly_rate_cents"] == 550, (
            f"per-step rounding: 333*1.5=499.5 -> 500, then 500*1.1=550; "
            f"sum-then-round would yield 549. Got {data['nightly_rate_cents']}"
        )

    def test_total_cost_includes_per_night_utility_surcharge(self, api):
        """PRD §3.5: "The base cost is the number of nights multiplied by the pinned `nightly_rate_cents`."
        PRD §3.5: "When the lease's `is_liveaboard` is true, a utility surcharge equal to `LIVEABOARD_UTILITY_FEE_PER_NIGHT_CENTS` of fifteen dollars in cents multiplied by the number of nights is added on top; otherwise the surcharge is zero."

        Design: Difficulty/combinatorial_formula/seasonal_pricing_per_step_rounding_pins_value
        """
        lease = self._setup_lease()
        res = api.check_in_lease(lease["id"], TEST_USERS["marina_staff_headers"])
        data = validate_success(res, expected_status=200)
        # 2 nights * 550 = 1100; + 2 * 1500 utility = 4100.
        assert data["total_cost_cents"] == 4100, (
            f"2*550 + 2*1500 = 4100, got {data['total_cost_cents']}"
        )


class TestTowAssistEvaluationOrderPinned:
    """Vessel insurance is VALID; incident distance exceeds marina radius:
    step 1 passes, step 2 fails -> OUT_OF_RADIUS. Proves evaluation order:
    radius is reached only when insurance passes.
    """

    def test_valid_insurance_out_of_radius_yields_out_of_radius(self, api):
        """PRD §3.7: "The outcome is `INSURANCE_INVALID` if step one fails; `OUT_OF_RADIUS` if step one passes but step two fails; and `COVERED` if both pass."

        Design: Difficulty/combinatorial_formula/tow_assist_evaluation_order_pinned
        """
        marina = create_marina(liveaboard_cap=2, tow_assist_radius_nm=10.0)
        tv = setup_tenant_with_vessel(
            insurance_expires_on="2026-10-01",  # valid through 2026-09-30
            insurance_coverage_cents=6_000_000,
            loa_ft=30,
            beam_ft=10,
        )
        tenant, vessel = tv["tenant"], tv["vessel"]
        set_clock("2026-08-01T00:00:00Z")
        res = api.create_tow_assist_event(
            create_tow_assist_event_payload(
                tenant_id=tenant["id"],
                vessel_id=vessel["id"],
                marina_id=marina["id"],
                incident_distance_nm=50.0,  # exceeds 10
            ),
            make_tenant_headers(tenant["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert data["outcome"] == "OUT_OF_RADIUS", \
            f"step 1 passes, step 2 fails -> OUT_OF_RADIUS, got {data['outcome']}"

    def test_radius_step_two_uses_marina_tow_assist_radius(self, api):
        """PRD §3.7: "Step two validates the radius: `incident_distance_nm` must be less than or equal to the marina's `tow_assist_radius_nm`."

        Design: Difficulty/combinatorial_formula/tow_assist_evaluation_order_pinned
        """
        marina = create_marina(liveaboard_cap=2, tow_assist_radius_nm=10.0)
        tv = setup_tenant_with_vessel(
            insurance_expires_on="2026-10-01",
            insurance_coverage_cents=6_000_000,
        )
        tenant, vessel = tv["tenant"], tv["vessel"]
        set_clock("2026-08-01T00:00:00Z")
        res = api.create_tow_assist_event(
            create_tow_assist_event_payload(
                tenant_id=tenant["id"],
                vessel_id=vessel["id"],
                marina_id=marina["id"],
                incident_distance_nm=50.0,
            ),
            make_tenant_headers(tenant["id"]),
        )
        data = validate_success(res, expected_status=201)
        # The marina's radius is 10; the incident is 50 > 10 → OUT_OF_RADIUS.
        assert data["outcome"] == "OUT_OF_RADIUS"
