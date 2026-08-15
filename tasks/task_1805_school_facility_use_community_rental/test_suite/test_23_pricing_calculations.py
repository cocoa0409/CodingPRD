"""Pricing arithmetic corners: 30-minute block rounding, the long-booking
rebate boundary, deposit floor vs basis points, the INTERNAL zero-rate class,
and the custodial minimum-shift floor (PRD §3.5, §3.6)."""
import pytest

from test_helpers import (
    validate_success,
    invoice_of_kind,
    make_booking_env, make_approved_permit_in_env,
    make_facility, make_policy, add_renter_with_insurance,
    capture_deposit, set_clock, get_single_work_order,
    api_client,
    TEST_USERS,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]

NO_CUSTODIAN = {"requires_custodian": False}

FP_PRE_POLICY = {
    "policy_code": "FP-PRE", "rate_class": "FOR_PROFIT", "facility_tier": "PREMIUM",
    "hourly_rate_cents": 15000, "deposit_basis_points": 3000,
    "custodial_hourly_cents": 6000, "effective_from": "2026-01-01T00:00:00Z",
    "deposit_floor_cents": 20000,
}


def _provisional(api, permit_id):
    invoices = validate_success(api.list_permit_invoices(permit_id, DIRECTOR))
    return invoice_of_kind(invoices, "PROVISIONAL")


class TestRentalBlockRounding:
    def test_rental_block_rounding_61_vs_60_minutes(self, api):
        """PRD §3.6: "The occupancy window's duration in minutes is divided into
        whole 30-minute blocks, any partial block rounding up to a full block;
        the block count halved gives the billable hours. The base rental fee is
        those billable hours multiplied by the covering policy's
        `hourly_rate_cents`, an exact multiplication with no rounding."
        PRD §3.6: "when a facility needs no custodian there is no work order and
        the staffing component is zero."

        Design: Corner/calculations/rental_block_rounding_61_vs_60_minutes
        """
        env = make_booking_env(facility_overrides=NO_CUSTODIAN)
        req60, p60 = make_approved_permit_in_env(
            env, event_title="Exact Hour", headcount_estimate=20,
            starts_at="2026-12-01T18:00:00Z", ends_at="2026-12-01T19:00:00Z")
        req61, p61 = make_approved_permit_in_env(
            env, event_title="Sixty One", headcount_estimate=20,
            starts_at="2026-12-02T18:00:00Z", ends_at="2026-12-02T19:01:00Z")

        # 60 minutes = 2 blocks = 1.0 billable hour x 5000.
        assert _provisional(api, p60["id"])["rental_fee_cents"] == 5000
        # 61 minutes -> ceil -> 3 blocks = 1.5 billable hours x 5000: one minute
        # over the block boundary bills a whole extra half-hour.
        prov61 = _provisional(api, p61["id"])
        assert prov61["rental_fee_cents"] == 7500
        assert prov61["staffing_charge_cents"] == 0
        orders = validate_success(api.list_permit_work_orders(p61["id"], SUPERVISOR))
        assert orders == [], "no custodian required -> no work order"


class TestLongBookingRebate:
    def test_long_booking_rebate_at_exactly_6_hours(self, api):
        """PRD §3.6: "A booking of at least 6 billable hours earns a long-booking
        rebate of 10 percent off that base, and the rebated figure is rounded
        half-up to integer cents — the single rounding step in the rental
        computation."
        PRD §2.4: "Comparisons expressed in days (cancellation refund tiers, the
        fourteen-day appeal window, the thirty-day suspension clock) are made on
        whole calendar days in site-local time, and every day-count threshold in
        this document is inclusive of its lower bound."

        Design: Corner/calculations/long_booking_rebate_at_exactly_6_hours
        """
        env = make_booking_env(facility_overrides=NO_CUSTODIAN)
        req55, p55 = make_approved_permit_in_env(
            env, event_title="Five Half", headcount_estimate=20,
            starts_at="2026-12-01T17:00:00Z", ends_at="2026-12-01T22:30:00Z")
        req60, p60 = make_approved_permit_in_env(
            env, event_title="Six Hours", headcount_estimate=20,
            starts_at="2026-12-02T17:00:00Z", ends_at="2026-12-02T23:00:00Z")

        # 5.5 billable hours: no rebate (5.5 < 6).
        assert _provisional(api, p55["id"])["rental_fee_cents"] == 27500
        # Exactly 6.0 billable hours: rebate applies — the >= 6 boundary is
        # inclusive: round_half_up(30000 x 0.90).
        assert _provisional(api, p60["id"])["rental_fee_cents"] == 27000


class TestDepositComputation:
    def test_deposit_floor_vs_basis_points(self, api):
        """PRD §3.5: "`deposit_required_cents` is the quoted rental fee
        multiplied by the policy's `deposit_basis_points` and divided by 10000,
        rounded half-up to integer cents, and then raised to at least the
        policy's `deposit_floor_cents`."

        Design: Corner/calculations/deposit_floor_vs_basis_points
        """
        env = make_booking_env(facility_overrides=NO_CUSTODIAN)
        aud = make_facility(env["site"]["id"], facility_code="AUD",
                            facility_tier="PREMIUM", capacity=500,
                            requires_custodian=False)
        make_policy(**FP_PRE_POLICY)
        org_fp, _ = add_renter_with_insurance("Gala Productions LLC",
                                              rate_class="FOR_PROFIT")

        # Small NONPROFIT booking: fee 5000 -> bp leg round(5000 x 0.20) = 1000,
        # below the 10000 floor -> the floor binds.
        req_s, p_small = make_approved_permit_in_env(
            env, event_title="Small Meetup", headcount_estimate=20,
            starts_at="2026-12-01T18:00:00Z", ends_at="2026-12-01T19:00:00Z")
        assert p_small["deposit_required_cents"] == 10000

        # Large FOR_PROFIT x PREMIUM booking: 6 billable hours ->
        # round_half_up(90000 x 0.90) = 81000 fee; bp leg round(81000 x 0.30) =
        # 24300 exceeds the 20000 floor -> the basis-points value binds.
        env_fp = {**env, "facility": aud, "org": org_fp}
        req_b, p_big = make_approved_permit_in_env(
            env_fp, event_title="Big Launch", headcount_estimate=400,
            starts_at="2026-12-02T14:00:00Z", ends_at="2026-12-02T20:00:00Z")
        assert p_big["deposit_required_cents"] == 24300


class TestInternalRateClass:
    def test_internal_rate_class_zero_invoice_and_auto_secure(self, api):
        """PRD §3.5: "When the required deposit computes to zero — the norm for
        `INTERNAL` bookings — the permit secures automatically at issuance with
        `deposit_held_cents` of 0."
        PRD §3.3: "`INTERNAL` renters are exempt from the insurance gate entirely
        — the district self-insures."
        PRD §3.4: "Submission also derives the request's `request_priority_class`
        from the renter's rate class: `INTERNAL` requests are `P0`, `NONPROFIT`
        requests are `P2`, and `FOR_PROFIT` requests are `P3`; a `NONPROFIT`
        request flagged `district_sponsored` is eligible for promotion to `P1` at
        the `FacilitiesDirector`'s discretion."

        Design: Corner/calculations/internal_rate_class_zero_invoice_and_auto_secure
        """
        env = make_booking_env(
            facility_overrides=NO_CUSTODIAN,
            policy_overrides={
                "policy_code": "IN-STD", "rate_class": "INTERNAL",
                "hourly_rate_cents": 0, "deposit_basis_points": 0,
                "custodial_hourly_cents": 0, "deposit_floor_cents": 0,
            },
            org_name="District Athletics Dept", rate_class="INTERNAL",
            insurance=False)
        req, permit = make_approved_permit_in_env(
            env, event_title="Dept Meeting", headcount_estimate=50,
            starts_at="2026-12-01T18:00:00Z", ends_at="2026-12-01T20:00:00Z")

        # Approval succeeded with NO InsuranceCertificate on file.
        assert permit["deposit_required_cents"] == 0
        assert permit["deposit_held_cents"] == 0
        assert permit["financial_status"] == "SECURED", (
            "zero required deposit secures automatically at issuance")
        prov = _provisional(api, permit["id"])
        assert prov["total_cents"] == 0
        assert prov["invoice_status"] == "ISSUED"
        request = validate_success(api.get_request(req["id"], DIRECTOR))
        assert request["request_priority_class"] == "P0"


class TestMinShiftFloor:
    def test_min_shift_floor_boundary_actual_hours(self, api):
        """PRD §3.6: "A minimum-shift floor applies: whenever the hours are
        greater than zero but less than 2.0, exactly 2.0 hours are billed
        instead, that product likewise rounded half-up."

        Design: Corner/calculations/min_shift_floor_boundary_actual_hours
        """
        env = make_booking_env()
        days = [("2026-09-12T00:00:00Z", "2026-09-12T02:00:00Z", "dep-ms-a", 2.0, 8000),
                ("2026-09-13T00:00:00Z", "2026-09-13T02:00:00Z", "dep-ms-b", 1.75, 8000),
                ("2026-09-14T00:00:00Z", "2026-09-14T02:00:00Z", "dep-ms-c", 2.5, 10000)]
        permits = []
        for i, (start, end, key, _actual, _expected) in enumerate(days):
            req, permit = make_approved_permit_in_env(
                env, event_title=f"Day {i}", headcount_estimate=50,
                starts_at=start, ends_at=end)
            capture_deposit(env, permit["id"], 10000, key)
            permits.append(permit)

        set_clock("2026-09-15T00:00:00Z")  # past all three occupancy ends
        for permit, (_s, _e, _k, actual, _exp) in zip(permits, days):
            validate_success(api.complete_permit(permit["id"], COORDINATOR))
            order = get_single_work_order(permit["id"])
            validate_success(api.verify_work_order(
                order["id"], {"actual_hours": actual}, SUPERVISOR))

        for permit, (_s, _e, _k, actual, expected) in zip(permits, days):
            invoices = validate_success(api.list_permit_invoices(permit["id"], DIRECTOR))
            final = invoice_of_kind(invoices, "FINAL")
            assert final["staffing_charge_cents"] == expected, (
                f"actual {actual}h @4000 with the 2.0h floor -> {expected}")
