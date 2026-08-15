"""The rental cycle: provisional vs final charges, best-rate tiers, minimum
period floor, off-rent / re-rent segment finalization, terminal lockdown."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, create_customer, create_equipment_class,
    create_equipment_unit, create_contract, add_line, activate_contract,
    set_clock, schedule_trip, start_trip, complete_trip, deliver_line,
    setup_draft_contract_with_line, setup_active_rental, setup_returned_line,
    off_rent, re_rent, pickup_line, get_line, get_trip, get_invoice,
    make_customer_headers,
    assert_rental_line, assert_invoice,
)


class TestProvisionalVsFinalSegmentCharge:
    def test_provisional_invoice_quote_while_out_on_rent(
            self, api, rental_coordinator_headers):
        """PRD §3.4: "For an `OUT_ON_RENT` line, the projected segment runs
        from `on_rent_at` to the later of the current logical-clock reading
        and midnight UTC on the day after `requested_end_date`; the
        provisional charge is the best-rate calculation over that projected
        segment plus whatever has already accrued into `accrued_charge_cents`
        from finalized segments."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_segment_charge
        """
        ctx = setup_active_rental(requested_start_date="2026-08-10",
                                  requested_end_date="2026-08-15",
                                  deliver_at="2026-08-10T09:00:00Z")
        # Projected end 2026-08-16T00:00:00Z minus on_rent 2026-08-10T09:00:00Z
        # = 5d15h -> ceil 6 days -> min(14500*6=87000, 43500*1, 99000*1).
        invoice = get_invoice(ctx["contract"]["id"])
        assert_invoice(invoice)
        assert invoice["rental_subtotal_cents"] == 43500
        line = get_line(ctx["line"]["id"])
        assert line["provisional_charge_cents"] == 43500

    def test_final_segment_charge_after_off_rent(self, api):
        """PRD §3.4: "Off-rent stamps `off_rent_at` from the logical clock,
        finalizes the segment over the actual `on_rent_at`-to-`off_rent_at`
        interval using the best-rate calculation above, adds that charge into
        `accrued_charge_cents`, and increments `segment_count`."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_segment_charge
        """
        ctx = setup_active_rental(requested_start_date="2026-08-10",
                                  requested_end_date="2026-08-15",
                                  deliver_at="2026-08-10T09:00:00Z")
        set_clock("2026-08-18T09:00:00Z")
        line = off_rent(ctx["line"]["id"],
                        customer_id=ctx["customer"]["id"])
        # Exactly 8 elapsed days: min(14500*8=116000, 43500*2=87000, 99000*1).
        assert line["status"] == "OFF_RENT"
        assert line["accrued_charge_cents"] == 87000
        assert line["segment_count"] == 1
        assert 87000 != 43500, (
            "final settlement over the actual interval differs from the "
            "forward-looking provisional quote for the same rate card")


class TestBestRateTierSelection:
    def test_weekly_tier_wins_at_eight_days(self, api):
        """PRD §3.4: "The segment charge itself is the lowest of three rate
        applications over that billable day count: the class's
        `daily_rate_cents` multiplied by the billable days; the
        `weekly_rate_cents` multiplied by the number of seven-day week blocks
        needed to cover the billable days (the day count divided by seven,
        rounded up); and the `monthly_rate_cents` multiplied by the number of
        twenty-eight-day month blocks needed to cover them (divided by
        twenty-eight, rounded up)."

        Design: Difficulty/combinatorial_formula/best_rate_tier_selection
        """
        ctx = setup_active_rental(
            class_kwargs={"class_code": "S32", "max_working_height_ft": 38,
                          "daily_rate_cents": 12000, "weekly_rate_cents": 40000,
                          "monthly_rate_cents": 150000,
                          "replacement_value_cents": 3_000_000},
            requested_start_date="2026-08-10", requested_end_date="2026-08-20",
            required_working_height_ft=30, deliver_at="2026-08-10T09:00:00Z")
        set_clock("2026-08-18T09:00:00Z")
        line = off_rent(ctx["line"]["id"])
        # 8 days: daily 12000*8=96000 loses, weekly 40000*ceil(8/7)=80000 wins,
        # monthly 150000*1 loses.
        assert line["accrued_charge_cents"] == 80000

    def test_reserved_provisional_quote_uses_best_rate(self, api):
        """PRD §3.4: "For a `RESERVED` line, the projected segment runs from
        midnight UTC on `requested_start_date` to midnight UTC on the day
        after `requested_end_date`, and the provisional charge is the
        best-rate calculation over that window."

        Design: Difficulty/combinatorial_formula/best_rate_tier_selection
        """
        ctx = setup_draft_contract_with_line(
            class_kwargs={"class_code": "S32P", "max_working_height_ft": 38,
                          "daily_rate_cents": 12000, "weekly_rate_cents": 40000,
                          "monthly_rate_cents": 150000,
                          "replacement_value_cents": 3_000_000},
            requested_start_date="2026-08-10", requested_end_date="2026-08-20",
            required_working_height_ft=30)
        line = ctx["line"]
        assert line["status"] == "RESERVED"
        # 11 projected days: min(12000*11=132000, 40000*2=80000, 150000*1).
        assert line["provisional_charge_cents"] == 80000


class TestMinimumRentalFloor:
    RATES = {"class_code": "BOOM45M", "max_working_height_ft": 51,
             "min_rental_days": 4, "daily_rate_cents": 20000,
             "weekly_rate_cents": 80000, "monthly_rate_cents": 240000,
             "replacement_value_cents": 4_000_000}

    def test_below_floor_bills_minimum(self, api):
        """PRD §3.4: "the number of seconds between segment start and segment
        end is divided by the 86,400 seconds in a day and rounded up to a
        whole day, and the class's `min_rental_days` then applies as a floor —
        a segment never bills fewer days than the class minimum."

        Design: Difficulty/boundary_precision_check/min_rental_floor_boundary
        """
        ctx = setup_active_rental(
            class_kwargs=dict(self.RATES),
            requested_start_date="2026-08-10", requested_end_date="2026-08-31",
            required_working_height_ft=40, deliver_at="2026-08-10T09:00:00Z")
        set_clock("2026-08-13T09:00:00Z")  # 72 elapsed hours = 3 raw days
        line = off_rent(ctx["line"]["id"])
        # Floor applies: 4 days -> min(20000*4, 80000*1, 240000*1) = 80000.
        assert line["accrued_charge_cents"] == 80000
        assert line["segment_count"] == 1

    def test_exactly_at_floor_does_not_round_up(self, api):
        """PRD §3.4: "the class's `min_rental_days` then applies as a floor —
        a segment never bills fewer days than the class minimum" and "the
        number of seconds between segment start and segment end is divided by
        the 86,400 seconds in a day and rounded up to a whole day".

        Design: Difficulty/boundary_precision_check/min_rental_floor_boundary
        """
        ctx = setup_active_rental(
            class_kwargs=dict(self.RATES, class_code="BOOM45N"),
            requested_start_date="2026-08-10", requested_end_date="2026-08-31",
            required_working_height_ft=40, deliver_at="2026-08-10T09:00:00Z")
        set_clock("2026-08-14T09:00:00Z")  # exactly 96 elapsed hours = 4 days
        line = off_rent(ctx["line"]["id"])
        # Exactly at the floor: 4 billable days, NOT 5 -> 80000.
        assert line["accrued_charge_cents"] == 80000


class TestOffRentCeilPartialDay:
    def test_twenty_five_hours_bills_two_days(self, api):
        """PRD §3.4: "the number of seconds between segment start and segment
        end is divided by the 86,400 seconds in a day and rounded up to a
        whole day"."

        Design: Corner/calculations/off_rent_ceil_partial_day
        """
        ctx = setup_active_rental(deliver_at="2026-08-10T09:00:00Z")
        set_clock("2026-08-11T10:00:00Z")  # 25 elapsed hours
        line = off_rent(ctx["line"]["id"])
        # 2 billable days -> min(14500*2, 43500, 99000) = 29000.
        assert line["accrued_charge_cents"] == 29000
        assert line["segment_count"] == 1


class TestOffRentReRentCycle:
    def test_two_segments_then_return(self, api, rental_coordinator_headers):
        """PRD §3.4: "Re-renting moves the line back from `OFF_RENT` to
        `OUT_ON_RENT`, stamps a fresh `on_rent_at` from the logical clock,
        clears `off_rent_at` back to null, and increments the line's
        `version`." and "The `OUT_ON_RENT` → `OFF_RENT` → `OUT_ON_RENT` cycle
        may repeat as often as the job demands, and each off-rent finalizes
        exactly one more billable segment." PRD §3.5: "the line then moves
        from `OFF_RENT` to `RETURNED` with `final_charge_cents` set to
        `accrued_charge_cents`".

        Design: Difficulty/non_linear_state_machine/line_off_rent_re_rent_cycle
        """
        ctx = setup_active_rental(requested_start_date="2026-08-10",
                                  requested_end_date="2026-08-31",
                                  deliver_at="2026-08-10T09:00:00Z")
        line_id = ctx["line"]["id"]
        contract_id = ctx["contract"]["id"]

        set_clock("2026-08-12T09:00:00Z")
        first = off_rent(line_id)
        # 2 days: min(14500*2=29000, 43500*1) = 29000.
        assert first["status"] == "OFF_RENT"
        assert first["accrued_charge_cents"] == 29000
        assert first["segment_count"] == 1

        pickup1 = schedule_trip(contract_id, line_id, "PICKUP", "drv-1",
                                "2026-08-12T13:00:00Z", "2026-08-12T15:00:00Z")
        cycled = re_rent(line_id)
        assert cycled["status"] == "OUT_ON_RENT", "cycle completed"
        assert get_trip(pickup1["id"])["status"] == "CANCELLED"

        set_clock("2026-08-15T09:00:00Z")
        second = off_rent(line_id)
        # +3 days: min(14500*3=43500, 43500*1) = 43500; accrued 29000+43500.
        assert second["accrued_charge_cents"] == 72500
        assert second["segment_count"] == 2

        pickup_line(contract_id, line_id, "drv-1",
                    "2026-08-15T13:00:00Z", "2026-08-15T15:00:00Z")
        final = get_line(line_id)
        assert final["status"] == "RETURNED"
        assert final["final_charge_cents"] == 72500

    def test_re_rent_cancels_scheduled_pickup_and_restamps(self, api):
        """PRD §3.4: "Because the customer has kept the equipment, any pickup
        already scheduled becomes pointless: every `SCHEDULED` pickup trip for
        the line is cancelled by cascade (each such trip's `version`
        increments as it moves to `CANCELLED`)." and "stamps a fresh
        `on_rent_at` from the logical clock, clears `off_rent_at` back to
        null".

        Design: Difficulty/non_linear_state_machine/line_off_rent_re_rent_cycle
        """
        ctx = setup_active_rental(deliver_at="2026-08-10T09:00:00Z")
        line_id = ctx["line"]["id"]
        set_clock("2026-08-12T09:00:00Z")
        off_rent(line_id)
        pickup = schedule_trip(ctx["contract"]["id"], line_id, "PICKUP",
                               "drv-1", "2026-08-12T13:00:00Z",
                               "2026-08-12T15:00:00Z")

        set_clock("2026-08-12T10:00:00Z")
        cycled = re_rent(line_id, customer_id=ctx["customer"]["id"])
        assert_rental_line(cycled)
        assert cycled["status"] == "OUT_ON_RENT"
        assert cycled["off_rent_at"] is None
        assert cycled["on_rent_at"].startswith("2026-08-12T10:00:00"), (
            "a fresh on_rent_at marks the new segment")
        assert cycled["segment_count"] == 1, "the finalized segment persists"

        cancelled = get_trip(pickup["id"])
        assert cancelled["status"] == "CANCELLED"


class TestLineStateGates:
    def test_off_rent_reserved_line_returns_invalid_state(
            self, api, rental_coordinator_headers):
        """PRD §3.4: "Either a `RentalCoordinator` or the `Customer` that owns
        the contract may call a line off rent; the line must currently be
        `OUT_ON_RENT` and its contract must be `ACTIVE` — violations of either
        yield `ERR_INVALID_STATE` — and a `Customer` caller's identity must
        match the contract's `customer_id` (`ERR_FORBIDDEN`)."

        Design: Corner/state_machines/off_rent_reserved_line_returns_invalid_state
        """
        ctx = setup_draft_contract_with_line()
        assert ctx["line"]["status"] == "RESERVED"
        res = api.off_rent_line(ctx["line"]["id"], rental_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_line(ctx["line"]["id"])["status"] == "RESERVED"

    def test_returned_line_terminal_lockdown_rejected(
            self, api, rental_coordinator_headers):
        """PRD §3.4: "`RETURNED` is terminal, as is `CANCELLED`." PRD §2.8:
        "wrong from-state, writes against terminal states, and cross-entity
        state gates (for example, a line action requiring its contract to be
        `ACTIVE`) yield `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/returned_line_terminal_lockdown_rejected
        """
        ctx = setup_returned_line()
        assert ctx["line"]["status"] == "RETURNED"

        res_off = api.off_rent_line(ctx["line"]["id"], rental_coordinator_headers)
        validate_error(res_off, ApiErrorId.ERR_INVALID_STATE)
        res_re = api.re_rent_line(ctx["line"]["id"], rental_coordinator_headers)
        validate_error(res_re, ApiErrorId.ERR_INVALID_STATE)


class TestInvoiceReconciliation:
    def test_invoice_reflects_off_rent_segment(self, api):
        """PRD §3.4: "These per-line values feed the contract's
        `rental_subtotal_cents`: `RETURNED` lines contribute
        `final_charge_cents`, `OFF_RENT` lines contribute
        `accrued_charge_cents`, `RESERVED` and `OUT_ON_RENT` lines contribute
        `provisional_charge_cents`, and `CANCELLED` lines contribute zero."
        PRD §3.5: "a flat `trip_fee_cents` of 15,000 cents per completed
        trip".

        Design: Corner/cross_cutting_complexity_layers/invoice_reflects_off_rent_segment
        """
        ctx = setup_active_rental(requested_start_date="2026-08-10",
                                  requested_end_date="2026-08-12",
                                  deliver_at="2026-08-10T09:00:00Z")
        before = get_invoice(ctx["contract"]["id"])
        # Projected end 2026-08-13T00:00:00Z: 2d15h -> 3 days -> 43500.
        assert before["rental_subtotal_cents"] == 43500
        assert before["invoice_total_cents"] == 58500  # + 15000 trip fee

        set_clock("2026-08-11T09:00:00Z")
        off_rent(ctx["line"]["id"])
        after = get_invoice(ctx["contract"]["id"])
        # Exactly 1 elapsed day -> 14500; subtotal reconciles immediately.
        assert after["rental_subtotal_cents"] == 14500
        assert after["invoice_total_cents"] == 29500
