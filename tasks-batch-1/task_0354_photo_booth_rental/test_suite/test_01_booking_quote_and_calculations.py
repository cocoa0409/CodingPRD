"""Quote and settlement calculations: travel fee, idle ceil, dual-variant quote vs final,
overtime cap, per-line add-on rounding.

All monetary expectations are derived from the PRD §3.2 forward-looking quote and §3.5
chronological settlement formulas. deposit_due is never asserted as a literal because the
PRD states deposit_due = quote_subtotal * DEPOSIT_PCT without pinning DEPOSIT_PCT's value.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data, assert_booking, assert_booking_add_on,
    assert_cost_precision,
    create_booking_payload, create_booking_add_on_payload,
    make_customer_headers, TEST_USERS,
    seed_base_scenario, seed_model_and_package, create_customer, create_booking,
    add_add_on_line, create_finalized_booking, create_add_on,
)

OPS = TEST_USERS["operations_manager_headers"]


# ─── Booking creation computes travel_fee + forward-looking quote ──────

def test_create_booking_returns_draft_unpaid_with_computed_quote(api):
    """PRD §3.2: "A freshly drafted booking begins with `schedule_status` of `DRAFT`
    and `payment_status` of `UNPAID`."
    PRD §3.2: "The raw fee is the per-mile rate `TRAVEL_RATE_PER_MILE` ($1.50)
    multiplied by those billable miles — charged one way, never round-trip."
    PRD §3.2: "Coverage hours are the requested span from `event_start` to `event_end`,
    expressed in hours and rounded **up** to the next whole hour (coverage is billed in
    whole hours)."

    Design: Corner/entities/create_booking_returns_201_with_computed_quote
    """
    model, package = seed_model_and_package()
    customer = create_customer()
    # 6h event (18:00-00:00), lead 0, venue 40 miles, no add-ons.
    payload = create_booking_payload(
        customer["id"], package["id"],
        event_start="2026-09-12T18:00:00Z", event_end="2026-09-13T00:00:00Z",
        venue_distance_miles=40, requested_setup_lead_min=0)
    res = api.create_booking(payload, make_customer_headers(customer["id"]))
    booking = validate_success(res, 201)
    assert_booking(booking)
    assert booking["schedule_status"] == "DRAFT"
    assert booking["payment_status"] == "UNPAID"
    # travel: (40 - 25) * 1.50 = 22.50
    assert booking["travel_fee"] == pytest.approx(22.50, abs=0.01)
    # quote: base 1200 + overtime (6-4=2h*150=300) + idle 0 + addons 0 + travel 22.50 = 1522.50
    assert booking["quote_subtotal"] == pytest.approx(1522.50, abs=0.01)


def test_create_booking_booth_id_null_while_draft(api):
    """PRD §3.2: "The booking exposes `booth_id` (the physical unit assigned at
    confirmation, null while `DRAFT`)."
    PRD §2.4: "`version` (integer): a counter that starts at the resource's creation
    and increments by one on every mutation of that resource."

    Design: Corner/entities/booking_booth_id_computed_null_while_draft
    """
    model, package = seed_model_and_package()
    customer = create_customer()
    payload = create_booking_payload(
        customer["id"], package["id"],
        event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T22:00:00Z",
        venue_distance_miles=0)
    booking = validate_success(api.create_booking(payload, make_customer_headers(customer["id"])), 201)
    assert booking["booth_id"] is None
    assert booking["version"] == 1


def test_travel_fee_at_free_radius_boundary_is_zero(api):
    """PRD §3.2: "The billable mileage is the venue distance minus a free radius of
    `TRAVEL_FREE_RADIUS_MILES` (25) miles, floored at zero so that any distance within
    the free radius bills nothing."

    Design: Corner/calculations/travel_fee_under_free_radius_is_zero
    """
    model, package = seed_model_and_package()
    customer = create_customer()
    # 4h event, lead 0, venue exactly 25 miles == free radius.
    payload = create_booking_payload(
        customer["id"], package["id"],
        event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T22:00:00Z",
        venue_distance_miles=25)
    booking = validate_success(api.create_booking(payload, make_customer_headers(customer["id"])), 201)
    assert booking["travel_fee"] == pytest.approx(0.00, abs=0.01)
    # base 1200, 4h == included so no overtime, no idle/addons/travel.
    assert booking["quote_subtotal"] == pytest.approx(1200.00, abs=0.01)


def test_idle_hours_ceil_rounding_in_quote(api):
    """PRD §3.2: "Planned idle hours are the `requested_setup_lead_min` divided by 60
    and rounded **up** to a whole number of idle hours; the idle charge is the package's
    `idle_rate_per_hour` multiplied by those planned idle hours."

    Design: Corner/calculations/idle_hour_ceil_rounding_in_quote
    """
    model, package = seed_model_and_package()
    customer = create_customer()
    # 4h event, lead 61 minutes -> ceil(61/60) = 2 idle hours * 75 = 150.
    payload = create_booking_payload(
        customer["id"], package["id"],
        event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T22:00:00Z",
        venue_distance_miles=0, requested_setup_lead_min=61)
    booking = validate_success(api.create_booking(payload, make_customer_headers(customer["id"])), 201)
    # base 1200 + idle 150 = 1350 (no overtime, no travel, no add-ons).
    assert booking["quote_subtotal"] == pytest.approx(1350.00, abs=0.01)


# ─── Dual-variant: quote (booked) vs final settlement (actuals) ────────

class TestQuoteVsFinalSettlement:
    """Difficulty Rule 1: the forward-looking estimate and the chronological actual
    settlement deliberately differ for the same booking."""

    ADDONS = [
        {"code": "PROPS", "name": "Prop Box", "unit_price": 50.00},
        {"code": "BACKDROP", "name": "Sequin Backdrop", "unit_price": 100.00},
        {"code": "ALBUM", "name": "Leather Album", "unit_price": 150.00},
    ]
    BOOKING = {
        "event_start": "2026-09-12T18:00:00Z", "event_end": "2026-09-13T00:00:00Z",
        "venue_distance_miles": 40, "requested_setup_lead_min": 90,
    }
    ACTUALS = {
        "actual_setup_start": "2026-09-12T16:15:00Z",
        "actual_coverage_start": "2026-09-12T17:00:00Z",
        "actual_coverage_end": "2026-09-13T00:15:00Z",
        "actual_teardown_end": "2026-09-13T01:00:00Z",
        "actual_print_count": 360,
    }

    def test_quote_subtotal_uses_booked_window(self, api):
        """PRD §3.2: "Coverage hours are the requested span from `event_start` to
        `event_end`, expressed in hours and rounded **up** to the next whole hour
        (coverage is billed in whole hours)."
        PRD §3.2: "Print overage is **not** part of the quote, because actual print
        counts are unknown until the event happens."

        Design: Difficulty/dual_variant_calc/quote_vs_final_settlement_on_booking
        """
        built = create_finalized_booking(
            booking_overrides=self.BOOKING, add_ons=self.ADDONS, actuals=self.ACTUALS)
        # quote: base 1200 + overtime(6-4=2h*150=300) + idle(ceil(90/60)=2h*75=150)
        #        + addons(50+100+150=300) + travel((40-25)*1.5=22.50) = 1972.50
        assert built["booking"]["quote_subtotal"] == pytest.approx(1972.50, abs=0.01)

    def test_final_subtotal_uses_actuals_and_adds_print_overage(self, api):
        """PRD §3.5: "Unlike the quote, this settlement *does* include print overage
        from the actual count, which is the principal reason the two figures can diverge."
        PRD §3.5: "Overtime hours are that actual coverage minus the package's
        `included_hours`, rounded **up** to a whole number and floored at zero."

        Design: Difficulty/dual_variant_calc/quote_vs_final_settlement_on_booking
        """
        built = create_finalized_booking(
            booking_overrides=self.BOOKING, add_ons=self.ADDONS, actuals=self.ACTUALS)
        # final: base 1200 + overtime(ceil(7.25-4)=4h*150=600) + idle(ceil(45/60)=1h*75=75)
        #        + addons 300 + travel 22.50 + print_overage((360-300)*0.40=24.00) = 2221.50
        assert built["booking"]["final_subtotal"] == pytest.approx(2221.50, abs=0.01)

    def test_final_subtotal_differs_from_quote(self, api):
        """PRD §3.5: "This settlement uses the *logged* timestamps, processed in time
        order, and produces a number that may differ from the forward-looking quote for
        the same booking."

        Design: Difficulty/dual_variant_calc/quote_vs_final_settlement_on_booking
        """
        built = create_finalized_booking(
            booking_overrides=self.BOOKING, add_ons=self.ADDONS, actuals=self.ACTUALS)
        assert built["booking"]["final_subtotal"] != built["booking"]["quote_subtotal"]
        assert built["booking"]["final_subtotal"] == pytest.approx(2221.50, abs=0.01)
        assert built["booking"]["quote_subtotal"] == pytest.approx(1972.50, abs=0.01)


# ─── Combinatorial: overtime cap clamp via final settlement ────────────

class TestOvertimeCapClamp:
    """Difficulty Rule 2 (mode a): the final settlement nests
    min(overtime_rate*ceil(actual-included), OVERTIME_DAILY_CAP)."""

    BOOKING = {
        "event_start": "2026-09-12T18:00:00Z", "event_end": "2026-09-12T23:00:00Z",
        "venue_distance_miles": 10, "requested_setup_lead_min": 0,
    }
    # actual coverage 18:00 -> 03:06 next day = 9.1h.
    ACTUALS = {
        "actual_setup_start": "2026-09-12T17:55:00Z",
        "actual_coverage_start": "2026-09-12T18:00:00Z",
        "actual_coverage_end": "2026-09-13T03:06:00Z",
        "actual_teardown_end": "2026-09-13T04:00:00Z",
        "actual_print_count": 300,
    }

    def test_quote_overtime_one_hour_uncapped(self, api):
        """PRD §3.2: "Overtime hours are the coverage hours minus the package's
        `included_hours`, floored at zero. The overtime charge is the package's
        `overtime_rate_per_hour` multiplied by those overtime hours, but capped at the
        overtime daily cap `OVERTIME_DAILY_CAP` ($750.00) — the charge is the smaller of
        the two."

        Design: Difficulty/combinatorial_formula/overtime_cap_min_nonlinear_mode_a
        """
        built = create_finalized_booking(booking_overrides=self.BOOKING, actuals=self.ACTUALS)
        # quote: base 1200 + overtime(5-4=1h*150=150) + travel(10<25 => 0) = 1350.
        assert built["booking"]["quote_subtotal"] == pytest.approx(1350.00, abs=0.01)

    def test_final_overtime_clamped_to_daily_cap(self, api):
        """PRD §3.5: "The overtime charge is the package's `overtime_rate_per_hour`
        multiplied by those overtime hours, capped at the overtime daily cap
        `OVERTIME_DAILY_CAP` ($750.00) — the smaller of the two."

        Design: Difficulty/combinatorial_formula/overtime_cap_min_nonlinear_mode_a
        """
        built = create_finalized_booking(booking_overrides=self.BOOKING, actuals=self.ACTUALS)
        # final: base 1200 + overtime(ceil(9.1-4)=6h*150=900 clamped to 750)
        #        + idle(ceil(5/60)=1h*75=75) + travel 0 + overage 0 = 2025.00
        assert built["booking"]["final_subtotal"] == pytest.approx(2025.00, abs=0.01)


# ─── Combinatorial: per-line add-on rounding then sum ──────────────────

class TestAddOnPerLineRounding:
    """Difficulty Rule 2 (mode b): each line_total is round(unit_price*qty,2) first,
    then the already-rounded line totals are summed."""

    def _seed(self, api):
        model, package = seed_model_and_package()
        customer = create_customer()
        booking = create_booking(
            customer["id"], package["id"],
            event_start="2026-09-12T18:00:00Z", event_end="2026-09-12T22:00:00Z",
            venue_distance_miles=0, requested_setup_lead_min=0)
        return customer, booking

    def test_line_total_frozen_per_line(self, api):
        """PRD §3.3: "When a line is added, its `line_total` is frozen as the add-on's
        `unit_price` multiplied by the ordered `qty`, rounded half-up to two decimal
        places, and held at that value thereafter regardless of any later catalog price
        change."

        Design: Difficulty/combinatorial_formula/addon_round_per_line_then_sum_mode_b
        """
        customer, booking = self._seed(api)
        album = create_add_on(code="ALBUM", name="Leather Album", unit_price=150.00, max_qty=3)
        props = create_add_on(code="PROPS", name="Prop Box", unit_price=50.00, max_qty=5)
        line1 = add_add_on_line(booking["id"], customer["id"], album["id"], qty=2)
        line2 = add_add_on_line(booking["id"], customer["id"], props["id"], qty=3)
        assert_booking_add_on(line1)
        assert line1["line_total"] == pytest.approx(300.00, abs=0.01)   # 150*2
        assert line2["line_total"] == pytest.approx(150.00, abs=0.01)   # 50*3

    def test_quote_sums_rounded_line_totals(self, api):
        """PRD §3.2: "each add-on line is rounded to two decimal places when the line is
        created (its `line_total` is frozen at that moment), and then the already-rounded
        line totals are summed — round-per-line, then sum."

        Design: Difficulty/combinatorial_formula/addon_round_per_line_then_sum_mode_b
        """
        customer, booking = self._seed(api)
        album = create_add_on(code="ALBUM", name="Leather Album", unit_price=150.00, max_qty=3)
        props = create_add_on(code="PROPS", name="Prop Box", unit_price=50.00, max_qty=5)
        add_add_on_line(booking["id"], customer["id"], album["id"], qty=2)
        add_add_on_line(booking["id"], customer["id"], props["id"], qty=3)
        refreshed = get_success_data(api.get_booking(booking["id"], OPS))
        # base 1200 + addons(300+150=450) = 1650 (4h no overtime, lead 0, venue 0).
        assert refreshed["quote_subtotal"] == pytest.approx(1650.00, abs=0.01)
