"""Difficulty Rule 1 — dual_variant_calc.

Two variant calculations diverge when their inputs disagree:
  (A) Lease nightly_rate_cents SUMMER non-liveaboard vs SUMMER liveaboard
  (B) Tow-assist outcome INSURANCE_INVALID vs OUT_OF_RADIUS on the
      same incident, distinguished by which gate fails first.
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


class TestSeasonalPricingVariantsDivergeOnLease:
    """SUMMER + is_liveaboard=false produces 7500; SUMMER + is_liveaboard=true
    produces 8250 from the same base rate (5000 cents) — same slip configuration
    and same date window, only Lease.is_liveaboard differs.
    """

    def _setup(self):
        marina = create_marina(liveaboard_cap=5)
        slip_a = create_slip(
            marina["id"],
            slip_number="A-1",
            length_ft=50,
            beam_ft=15,
            power_amp="A50",
            pumpout_available=True,
            liveaboard_allowed=True,
            base_daily_rate_cents=5000,
        )
        slip_b = create_slip(
            marina["id"],
            slip_number="A-2",
            length_ft=50,
            beam_ft=15,
            power_amp="A50",
            pumpout_available=True,
            liveaboard_allowed=True,
            base_daily_rate_cents=5000,
        )
        tv = setup_tenant_with_vessel(
            insurance_expires_on="2027-01-01",
            insurance_coverage_cents=6_000_000,
            loa_ft=40,
            beam_ft=12,
        )
        tenant = tv["tenant"]
        vessel = tv["vessel"]
        make_tenant_approved_for_liveaboard(tenant["id"], marina["id"])
        set_clock("2026-07-01T00:00:00Z")
        lease_nl = reserve_lease(
            marina_id=marina["id"],
            slip_id=slip_a["id"],
            tenant_id=tenant["id"],
            vessel_id=vessel["id"],
            start_date="2026-07-10",
            end_date="2026-07-15",
            expected_slip_version=slip_a["version"],
            is_liveaboard=False,
        )
        lease_la = reserve_lease(
            marina_id=marina["id"],
            slip_id=slip_b["id"],
            tenant_id=tenant["id"],
            vessel_id=vessel["id"],
            start_date="2026-07-10",
            end_date="2026-07-15",
            expected_slip_version=slip_b["version"],
            is_liveaboard=True,
        )
        set_clock("2026-07-10T00:00:00Z")
        return lease_nl, lease_la

    def test_summer_non_liveaboard_nightly_rate_is_7500(self, api):
        """PRD §3.5: "The SUMMER multiplier is one hundred fifty hundredths (numerator 150, denominator 100, i.e. one point five)."
        PRD §3.5: "When `is_liveaboard` is false, the surcharge multiplier is one hundred hundredths (numerator 100, denominator 100, i.e. one point zero) — a no-op — so the lease's `nightly_rate_cents` equals the result of step two."

        Design: Difficulty/dual_variant_calc/seasonal_pricing_variants_diverge_on_lease
        """
        lease_nl, _ = self._setup()
        res = api.check_in_lease(lease_nl["id"], TEST_USERS["marina_staff_headers"])
        data = validate_success(res, expected_status=200)
        assert data["nightly_rate_cents"] == 7500, \
            f"SUMMER non-liveaboard: 5000 * 150/100 = 7500, got {data['nightly_rate_cents']}"

    def test_summer_liveaboard_nightly_rate_is_8250(self, api):
        """PRD §3.5: "The SUMMER multiplier is one hundred fifty hundredths (numerator 150, denominator 100, i.e. one point five)."
        PRD §3.5: "When the lease's `is_liveaboard` is true, the interim nightly rate from step two is multiplied by one hundred ten hundredths (numerator 110, denominator 100, i.e. one point one), and the product is again rounded half up to the nearest integer cent; the result becomes the lease's `nightly_rate_cents`."

        Design: Difficulty/dual_variant_calc/seasonal_pricing_variants_diverge_on_lease
        """
        _, lease_la = self._setup()
        res = api.check_in_lease(lease_la["id"], TEST_USERS["marina_staff_headers"])
        data = validate_success(res, expected_status=200)
        # 5000 * 150/100 = 7500 (step 2); 7500 * 110/100 = 8250 (step 3).
        assert data["nightly_rate_cents"] == 8250, \
            f"SUMMER liveaboard: 5000*1.5=7500, 7500*1.1=8250, got {data['nightly_rate_cents']}"

    def test_total_cost_non_liveaboard_summer_five_nights(self, api):
        """PRD §3.5: "The number of nights is computed as `end_date` minus `start_date` in days using the half-open interval (so a lease from the 1st to the 4th is three nights)."
        PRD §3.5: "The base cost is the number of nights multiplied by the pinned `nightly_rate_cents`."

        Design: Difficulty/dual_variant_calc/seasonal_pricing_variants_diverge_on_lease
        """
        lease_nl, _ = self._setup()
        res = api.check_in_lease(lease_nl["id"], TEST_USERS["marina_staff_headers"])
        data = validate_success(res, expected_status=200)
        # 5 nights * 7500 = 37500; no liveaboard surcharge.
        assert data["total_cost_cents"] == 37500, \
            f"non-liveaboard total: 5 nights * 7500 = 37500, got {data['total_cost_cents']}"

    def test_total_cost_liveaboard_summer_five_nights_with_utility(self, api):
        """PRD §3.5: "When the lease's `is_liveaboard` is true, a utility surcharge equal to `LIVEABOARD_UTILITY_FEE_PER_NIGHT_CENTS` of fifteen dollars in cents multiplied by the number of nights is added on top; otherwise the surcharge is zero."

        Design: Difficulty/dual_variant_calc/seasonal_pricing_variants_diverge_on_lease
        """
        _, lease_la = self._setup()
        res = api.check_in_lease(lease_la["id"], TEST_USERS["marina_staff_headers"])
        data = validate_success(res, expected_status=200)
        # 5 nights * 8250 = 41250 base + 5 * 1500 utility = 48750.
        assert data["total_cost_cents"] == 48750, \
            f"liveaboard total: 5*8250 + 5*1500 = 48750, got {data['total_cost_cents']}"


class TestTowAssistOutcomeBranchesOnVessel:
    """Same incident inputs, but the insurance-first evaluation order pins
    INSURANCE_INVALID when both gates fail.
    """

    def test_tow_assist_with_expired_insurance_and_out_of_radius_pins_insurance_invalid(self, api):
        """PRD §3.7: "Order is binding: when a single event fails both gates (expired insurance AND distance outside radius), the recorded outcome is `INSURANCE_INVALID` because the insurance step short-circuits before the radius step is reached."

        Design: Difficulty/dual_variant_calc/tow_assist_outcome_branches_on_vessel
        """
        marina = create_marina(liveaboard_cap=3, tow_assist_radius_nm=25.0)
        tv = setup_tenant_with_vessel(
            insurance_expires_on="2020-01-01",  # expired
            insurance_coverage_cents=6_000_000,
            loa_ft=35,
            beam_ft=12,
        )
        tenant = tv["tenant"]
        vessel = tv["vessel"]
        set_clock("2026-08-01T00:00:00Z")
        res = api.create_tow_assist_event(
            create_tow_assist_event_payload(
                tenant_id=tenant["id"],
                vessel_id=vessel["id"],
                marina_id=marina["id"],
                incident_distance_nm=50.0,  # out of radius
            ),
            make_tenant_headers(tenant["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert data["outcome"] == "INSURANCE_INVALID", \
            f"insurance-first short-circuit: outcome must be INSURANCE_INVALID, got {data['outcome']}"

    def test_tow_assist_outcome_is_a_persisted_field_on_the_event(self, api):
        """PRD §3.7: "the system computes the dispatch outcome and persists a `TowAssistEvent` recording the result with `outcome` set to one of `COVERED`, `OUT_OF_RADIUS`, or `INSURANCE_INVALID` and `dispatched_at` stamped to the current UTC."

        Design: Difficulty/dual_variant_calc/tow_assist_outcome_branches_on_vessel
        """
        marina = create_marina(liveaboard_cap=3, tow_assist_radius_nm=25.0)
        tv = setup_tenant_with_vessel(
            insurance_expires_on="2020-01-01",
            insurance_coverage_cents=6_000_000,
        )
        tenant = tv["tenant"]
        vessel = tv["vessel"]
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
        assert data["outcome"] in {"COVERED", "OUT_OF_RADIUS", "INSURANCE_INVALID"}
        assert data["outcome"] == "INSURANCE_INVALID"
