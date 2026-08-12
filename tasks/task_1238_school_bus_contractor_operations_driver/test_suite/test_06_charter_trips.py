"""Charter trips: quote pricing, OCC-pinned approval, buffered windows,
tiered cancellation, credit hold, and schedule safety stack."""
from test_helpers import (
    ApiErrorId,
    assert_deposit_split_invariant,
    create_active_contract,
    create_approved_charter,
    create_bus,
    create_charter,
    create_completed_charter,
    create_district,
    create_inspection,
    create_quoted_charter,
    get_success_data,
    make_district_admin_headers,
    quote_charter,
    schedule_charter,
    set_clock,
    setup_billing_scenario,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import FLEET, OPS


def _active_contract_no_fleet(name, **contract_overrides):
    district = create_district(name=name)
    contract = create_active_contract(district["id"], **contract_overrides)
    return district, contract


class TestCharterQuotePricing:
    def test_charter_quote_provisional_value(self, api):
        """PRD section 3.6: "The provisional `quote_price_cents` is the
        estimated hours in tenths multiplied by the contract's
        `charter_hourly_rate_cents`, divided by ten and floored to whole cents,
        plus the `estimated_miles` multiplied by `charter_per_mile_cents`."
        PRD section 3.6: "The quote carries a deadline: `quote_valid_until` is
        set exactly 72 hours after the quoting instant, and quoting increments
        the trip's `version`."
        PRD section 2.5: "At server startup the clock is exactly
        `2026-05-01T00:00:00Z`; it never falls back to wall-clock time."

        Design: Corner/calculations/charter_quote_provisional_value
        """
        district, contract = _active_contract_no_fleet("D-CALC1",
                                                       bid_reference="BID-CA1")
        charter = create_charter(contract["id"], district["id"],
                                 purpose="Quote check", trip_date="2026-06-10",
                                 pickup_minute=600, return_minute=900,
                                 estimated_hours_x10=50, estimated_miles=100,
                                 passenger_count=20)
        quoted = quote_charter(charter["id"])
        # floor(50 x 12000 / 10) + 100 x 250 = 60000 + 25000.
        assert quoted["quote_price_cents"] == 85000
        assert quoted["quote_valid_until"] == "2026-05-04T00:00:00Z", (
            "default clock 2026-05-01T00:00:00Z + 72 hours")


class TestCharterFinalPrice:
    def test_charter_final_price_with_overage(self, api):
        """PRD section 3.6: "The final `final_price_cents` is the actual hours
        in tenths multiplied by the hourly rate, divided by ten and floored to
        whole cents, plus the actual miles multiplied by the per-mile rate, plus
        an overage charge on any hours beyond the estimate: the excess in tenths
        of an hour multiplied by the hourly rate and by 125, divided by one
        thousand, floored to whole cents — that is, excess hours bill at
        one-and-a-quarter times the hourly rate. The bus's `odometer_miles`
        advances by the actual miles."

        Design: Corner/calculations/charter_final_price_with_overage
        """
        district, contract = _active_contract_no_fleet("D-CALC2",
                                                       bid_reference="BID-CA2")
        bus = create_bus(district["id"], fleet_number="BC2")
        charter = create_completed_charter(
            contract["id"], district["id"], bus["id"],
            actual_hours_x10=60, actual_miles=110, deposit_cents=50000,
            purpose="Overage trip", trip_date="2026-06-10", pickup_minute=600,
            return_minute=900, estimated_hours_x10=50, estimated_miles=100,
            passenger_count=20)
        assert charter["status"] == "COMPLETED"
        # floor(60 x 12000 / 10) + 110 x 250 + floor(10 x 12000 x 125 / 1000)
        # = 72000 + 27500 + 15000.
        assert charter["final_price_cents"] == 114500
        assert charter["quote_price_cents"] == 85000, (
            "provisional preserved; final diverges by 29500")

        bus_after = validate_success(api.get_bus(bus["id"], FLEET))
        assert bus_after["odometer_miles"] == 110, "odometer advanced by actual_miles"


class TestCharterBufferedWindow:
    def _setup_three_charters(self, api):
        district, contract = _active_contract_no_fleet("D-OV2",
                                                       bid_reference="BID-O2")
        bus = create_bus(district["id"], fleet_number="BOV2")
        specs = [("Museum A", 600, 720, 20, 40), ("Museum B", 740, 800, 10, 20),
                 ("Museum C", 800, 900, 17, 30)]
        charters = [
            create_approved_charter(
                contract["id"], district["id"], deposit_cents=0, purpose=purpose,
                trip_date="2026-06-05", pickup_minute=pickup, return_minute=ret,
                estimated_hours_x10=hours, estimated_miles=miles,
                passenger_count=20)
            for purpose, pickup, ret, hours, miles in specs
        ]
        return district, contract, bus, charters

    def test_charter_buffered_window_conflict_rejected(self, api):
        """PRD section 3.6: "The bus's calendar is checked with a buffer: the
        charter occupies the closed window from thirty minutes before its pickup
        through thirty minutes after its return, and that buffered window must
        not intersect the buffered window of any other `SCHEDULED` or
        `IN_PROGRESS` charter on the same bus and date
        (`ERR_CHARTER_BUS_UNAVAILABLE`), nor intersect the planned interval —
        half-open, as with route work — of any `CONFIRMED` route assignment on
        the same bus and date (`ERR_BUS_OVERLAP_CONFLICT`)."

        Design: Difficulty/resource_temporal_overlap/charter_bus_buffered_window_overlap
        """
        _d, _c, bus, charters = self._setup_three_charters(api)
        first = schedule_charter(charters[0]["id"], bus["id"])
        assert first["status"] == "SCHEDULED", "first claim on the bus wins"

        resp = api.schedule_charter(charters[1]["id"], {"assigned_bus_id": bus["id"]},
                                    OPS)
        validate_error(resp, ApiErrorId.ERR_CHARTER_BUS_UNAVAILABLE, 409)
        fetched = validate_success(api.get_charter_trip(charters[1]["id"], OPS))
        assert fetched["status"] == "APPROVED", (
            "B buffered [710,830] intersects A buffered [570,750] — unchanged")

    def test_charter_outside_buffered_window_accepted(self, api):
        """PRD section 3.6: "The bus's calendar is checked with a buffer: the
        charter occupies the closed window from thirty minutes before its pickup
        through thirty minutes after its return, and that buffered window must
        not intersect the buffered window of any other `SCHEDULED` or
        `IN_PROGRESS` charter on the same bus and date
        (`ERR_CHARTER_BUS_UNAVAILABLE`), nor intersect the planned interval —
        half-open, as with route work — of any `CONFIRMED` route assignment on
        the same bus and date (`ERR_BUS_OVERLAP_CONFLICT`)."

        Design: Difficulty/resource_temporal_overlap/charter_bus_buffered_window_overlap
        """
        _d, _c, bus, charters = self._setup_three_charters(api)
        first = schedule_charter(charters[0]["id"], bus["id"])
        assert first["status"] == "SCHEDULED"
        resp_b = api.schedule_charter(charters[1]["id"],
                                      {"assigned_bus_id": bus["id"]}, OPS)
        validate_error(resp_b, ApiErrorId.ERR_CHARTER_BUS_UNAVAILABLE)

        third = schedule_charter(charters[2]["id"], bus["id"])
        assert third["status"] == "SCHEDULED", (
            "C buffered [770,930] is clear of A's 750 buffer end")


class TestCharterTerminalStates:
    def test_charter_decline_is_terminal_returns_409(self, api):
        """PRD section 3.6: "Declining, with an optional `reason`, moves `QUOTED`
        to terminal `DECLINED`."
        PRD section 2.8: "8. **Terminal-state rejection.** An entity already in a
        terminal state — `TERMINATED`, `PAID`, `WRITTEN_OFF`, `CLOSED`,
        `COMPLETED`, `NO_SHOW`, `CANCELLED`, `EXPIRED`, `DECOMMISSIONED`,
        `INVOICED`, `DECLINED`, as applicable per resource — accepts no further
        transitions; attempts yield `ERR_ALREADY_TERMINAL` (HTTP 409)."

        Design: Corner/state_machines/charter_decline_is_terminal_returns_409
        """
        district, contract = _active_contract_no_fleet("D-SM10",
                                                       bid_reference="BID-S10")
        charter = create_quoted_charter(contract["id"], district["id"],
                                        purpose="Declined trip")
        declined = get_success_data(api.decline_charter(
            charter["id"], {"reason": "Too expensive"},
            make_district_admin_headers(district["id"])))
        assert declined["status"] == "DECLINED"

        current = validate_success(api.get_charter_trip(charter["id"], OPS))
        resp = api.approve_charter(
            charter["id"], {"expected_charter_trip_version": current["version"],
                            "deposit_cents": 0},
            make_district_admin_headers(district["id"]))
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)
        fetched = validate_success(api.get_charter_trip(charter["id"], OPS))
        assert fetched["status"] == "DECLINED"

    def test_error_quote_expired_via_clock_terminal(self, api):
        """PRD section 3.6: "Approval is also racing the quote's shelf life:
        advancing the clock strictly past `quote_valid_until` flips a `QUOTED`
        trip to terminal `EXPIRED`, after which approval lands on a terminal
        state and fails with `ERR_ALREADY_TERMINAL`; an approval arriving exactly
        at the deadline still succeeds, because expiry is strictly-past."

        Design: Corner/errors/error_quote_expired_via_clock_terminal
        """
        district, contract = _active_contract_no_fleet("D-ERR20",
                                                       bid_reference="BID-E20")
        charter_a = create_quoted_charter(contract["id"], district["id"],
                                          purpose="Boundary A")
        charter_b = create_quoted_charter(contract["id"], district["id"],
                                          purpose="Boundary B")
        assert charter_a["quote_valid_until"] == "2026-05-04T00:00:00Z"
        district_headers = make_district_admin_headers(district["id"])

        # Exactly at the deadline the quote is still live.
        set_clock("2026-05-04T00:00:00Z")
        approved = get_success_data(api.approve_charter(
            charter_a["id"], {"expected_charter_trip_version": charter_a["version"],
                              "deposit_cents": 0}, district_headers))
        assert approved["status"] == "APPROVED"

        # Strictly past the deadline the system transition has fired.
        set_clock("2026-05-04T01:00:00Z")
        expired = validate_success(api.get_charter_trip(charter_b["id"], OPS))
        assert expired["status"] == "EXPIRED"
        resp = api.approve_charter(
            charter_b["id"], {"expected_charter_trip_version": expired["version"],
                              "deposit_cents": 0}, district_headers)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)


class TestCharterCancelDepositSplit:
    def _approved_charter_36h_out(self, api):
        district, contract = _active_contract_no_fleet("D-INV2",
                                                       bid_reference="BID-I2")
        charter = create_approved_charter(
            contract["id"], district["id"], deposit_cents=50000,
            purpose="Science fair", trip_date="2026-06-10", pickup_minute=600,
            return_minute=900, estimated_hours_x10=50, estimated_miles=100,
            passenger_count=20)
        set_clock("2026-06-08T22:00:00Z")  # exactly 36h before the 10:00 pickup
        return district, charter

    def test_cancel_fee_tier_25_percent_applies(self, api):
        """PRD section 3.6: "Cancellation computes a tiered `cancel_fee_cents`
        from the whole hours between the cancellation instant and the scheduled
        pickup: 72 hours or more means no fee; at least 24 but fewer than 72
        hours means twenty-five percent of `quote_price_cents`, rounded half-up;
        fewer than 24 hours means fifty percent, rounded half-up."

        Design: Difficulty/compensating_invariant/charter_cancel_conserves_deposit_split
        """
        district, charter = self._approved_charter_36h_out(api)
        assert charter["quote_price_cents"] == 85000, (
            "provisional: 5.0h x 12000 + 100 mi x 250")

        cancelled = get_success_data(api.cancel_charter(
            charter["id"], {"reason": "District request"},
            make_district_admin_headers(district["id"])))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_fee_cents"] == 21250, (
            "24 <= 36 < 72 hours: 25% of 85000 rounded half-up")
        assert cancelled["refund_cents"] == 28750

    def test_deposit_split_is_conserved(self, api):
        """PRD section 3.6: "The `refund_cents` returned to the district is the
        `deposit_cents` minus the fee, so fee plus refund always equals the
        deposit; trips cancelled from `REQUESTED` or `QUOTED` hold no deposit,
        so both fee and refund are zero there."

        Design: Difficulty/compensating_invariant/charter_cancel_conserves_deposit_split
        """
        district, charter = self._approved_charter_36h_out(api)
        cancelled = get_success_data(api.cancel_charter(
            charter["id"], {"reason": "District request"},
            make_district_admin_headers(district["id"])))
        assert cancelled["deposit_cents"] == 50000
        assert_deposit_split_invariant(cancelled)
        assert cancelled["cancel_fee_cents"] + cancelled["refund_cents"] == 50000


class TestCharterCreditHold:
    def test_error_district_credit_hold_on_schedule_returns_402(self, api):
        """PRD section 3.6: "Last comes the fiscal gate of §3.7: the district's
        outstanding balance plus this trip's `quote_price_cents` must not exceed
        the district's `credit_limit_cents`, with equality allowed, else the
        schedule is rejected with `ERR_DISTRICT_CREDIT_HOLD` (HTTP 402)."
        PRD section 3.7: "The district's `outstanding_balance_cents` is the sum
        of `total_cents` over all its `ISSUED` invoices across every contract —
        unpaid and not written off — and it is recomputed at issue, reissue,
        payment, and write-off."

        Design: Corner/errors/error_district_credit_hold_on_schedule_returns_402
        """
        ctx = setup_billing_scenario(
            district_name="D-ERR25",
            district_overrides={"credit_limit_cents": 1},
            issue=True)
        # outstanding balance is now 50000 (one completed bus-day at 50000).
        charter = create_approved_charter(
            ctx["contract"]["id"], ctx["district"]["id"], deposit_cents=0,
            purpose="Credit check")
        assert charter["quote_price_cents"] == 34000  # 2.0h x 12000 + 40 x 250

        resp = api.schedule_charter(
            charter["id"], {"assigned_bus_id": ctx["bus"]["id"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_DISTRICT_CREDIT_HOLD, 402)


class TestCharterDatePast:
    def test_error_charter_date_past_returns_422(self, api):
        """PRD section 3.6: "A `DistrictAdmin` requests one under an `ACTIVE`
        contract — a request under any other contract state fails with
        `ERR_CONTRACT_NOT_ACTIVE` — supplying the `contract_id`, a free-text
        `purpose`, a `trip_date` on or after the logical clock date (an earlier
        date is rejected with `ERR_CHARTER_DATE_PAST`, HTTP 422)"
        PRD section 2.5: "At server startup the clock is exactly
        `2026-05-01T00:00:00Z`; it never falls back to wall-clock time."

        Design: Corner/errors/error_charter_date_past_returns_422
        """
        district, contract = _active_contract_no_fleet("D-ERR10",
                                                       bid_reference="BID-E10")
        resp = api.create_charter_trip(
            {"contract_id": contract["id"], "purpose": "Too late",
             "trip_date": "2026-04-01", "pickup_minute": 600, "return_minute": 720,
             "estimated_hours_x10": 20, "estimated_miles": 40,
             "passenger_count": 20},
            make_district_admin_headers(district["id"]))
        validate_error(resp, ApiErrorId.ERR_CHARTER_DATE_PAST, 422)


class TestSchedulePrioritySafetyBeatsFiscal:
    def _setup_grounded_bus_and_credit_hold(self, api):
        ctx = setup_billing_scenario(
            district_name="D-PC3",
            district_overrides={"credit_limit_cents": 1},
            issue=True, issue_clock="2026-05-20T00:00:00Z")
        charter = create_approved_charter(
            ctx["contract"]["id"], ctx["district"]["id"], deposit_cents=1000,
            purpose="Zoo trip", trip_date="2026-06-10", pickup_minute=600,
            return_minute=720, estimated_hours_x10=50, estimated_miles=100,
            passenger_count=20)
        inspection = create_inspection(ctx["bus"]["id"],
                                       scheduled_date="2026-05-21",
                                       inspector_ref="ST-9")
        get_success_data(api.record_inspection_result(
            inspection["id"], {"result": "FAIL"}, FLEET))
        return ctx, charter

    def test_grounded_bus_rejects_schedule_before_credit_check(self, api):
        """PRD section 2.8: "Every request passes through a fixed validation
        pipeline, and the order is part of the contract — when several checks
        would fail, the earliest one in this order determines the error
        returned:"
        PRD section 2.8: "10. **Bus dispatchability.** The bus is `IN_SERVICE`
        (`ERR_BUS_NOT_IN_SERVICE`), its `next_inspection_due` is on or after the
        service or trip date (`ERR_INSPECTION_OVERDUE`), and its `capacity`
        covers the ridership (`ERR_CAPACITY_INSUFFICIENT`, HTTP 422)." — the bus
        rung precedes "14. **Fiscal rules.** The district credit check
        (`ERR_DISTRICT_CREDIT_HOLD`, HTTP 402), the invoice period containing
        something final to bill (`ERR_INVOICE_PERIOD_INCOMPLETE`), and the
        contract being `ACTIVE` where required (`ERR_CONTRACT_NOT_ACTIVE`)."

        Design: Difficulty/priority_pair_validation_conflict/schedule_charter_grounded_bus_and_credit_hold_returns_409
        """
        ctx, charter = self._setup_grounded_bus_and_credit_hold(api)
        bus = validate_success(api.get_bus(ctx["bus"]["id"], FLEET))
        assert bus["status"] == "GROUNDED"

        resp = api.schedule_charter(
            charter["id"], {"assigned_bus_id": ctx["bus"]["id"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_BUS_NOT_IN_SERVICE, 409)
        fetched = validate_success(api.get_charter_trip(charter["id"], OPS))
        assert fetched["status"] == "APPROVED", "failed schedule mutates nothing"

    def test_credit_hold_armed_but_safety_fires_first(self, api):
        """PRD section 3.7: "The district's `outstanding_balance_cents` is the
        sum of `total_cents` over all its `ISSUED` invoices across every contract
        — unpaid and not written off — and it is recomputed at issue, reissue,
        payment, and write-off."
        PRD section 2.8: "Every request passes through a fixed validation
        pipeline, and the order is part of the contract — when several checks
        would fail, the earliest one in this order determines the error
        returned:"

        Design: Difficulty/priority_pair_validation_conflict/schedule_charter_grounded_bus_and_credit_hold_returns_409
        """
        ctx, charter = self._setup_grounded_bus_and_credit_hold(api)
        resp = api.schedule_charter(
            charter["id"], {"assigned_bus_id": ctx["bus"]["id"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_BUS_NOT_IN_SERVICE)

        district = validate_success(api.get_district(ctx["district"]["id"], OPS))
        assert district["outstanding_balance_cents"] == 50000, (
            "the fiscal failure was armed (50000 + 85000 > 1) yet the bus "
            "rung won")
