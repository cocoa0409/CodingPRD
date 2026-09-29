"""Tier tables, waterfall allocation, input-set filtering and seat re-aggregation."""

from test_helpers import (
    TEST_USERS,
    add_element,
    advance_to_in_execution,
    approve_line,
    create_active_contract,
    create_program,
    create_supplier,
    create_transport_segment,
    create_venue,
    deliver,
    issue_invoice,
    manifest_guest,
    mark_ready,
    open_reconciliation,
    open_settlement_payment,
    read_program,
    set_clock,
    setup_multi_element_program,
    validate_paginated,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
OC = TEST_USERS["operations_coordinator_headers"]
CTRL = TEST_USERS["controller_headers"]


class TestCancellationTierBands:
    FAR_OUT = {
        "element_type": "ACTIVITY",
        "title": "Element P (far out)",
        "starts_at": "2026-10-04T09:00:00Z",
        "ends_at": "2026-10-04T13:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 5_000,
    }
    NEAR = {
        "element_type": "ACTIVITY",
        "title": "Element Q (near)",
        "starts_at": "2026-09-12T09:00:00Z",
        "ends_at": "2026-09-12T13:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 5_000,
    }

    def _two_elements_one_clock(self):
        ctx = setup_multi_element_program(
            [self.FAR_OUT, self.NEAR],
            program_overrides={
                "client_name": "Tier Band Client",
                "group_name": "Tier Band Group",
                "departure_date": "2026-10-05",
                "guaranteed_count": 40,
            },
            venue_overrides={"name": "Tier Band Venue"},
            supplier_overrides={"legal_name": "Tier Band Supplier"},
            contract_overrides={
                "contract_value_cents": 200_000,
                "cancellation_tier": "STANDARD",
            },
        )
        # 33 whole days to the far element, 11 whole days to the near one.
        set_clock("2026-09-01T00:00:00Z")
        return ctx

    def test_the_same_clock_lands_two_elements_in_two_different_bands(self, api):
        """PRD §3.7: "All the day comparisons are inclusive, so exactly 30 whole days out on
        `STANDARD` attracts no penalty at all while 29 attracts a quarter."

        Design: Corner/calculations/cancellation_penalty_standard_tier_band_selected_by_days_to_start
        """
        ctx = self._two_elements_one_clock()
        far, near = ctx["elements"]

        far_cancelled = validate_success(
            api.cancel_element(
                far["id"], PD, {"cancel_reason": "Client dropped the closing activity."}
            )
        )
        near_cancelled = validate_success(
            api.cancel_element(
                near["id"], PD, {"cancel_reason": "Client dropped the mid-week activity."}
            )
        )

        assert far_cancelled["status"] == "CANCELLED"
        assert far_cancelled["cancellation_penalty_cents"] == 0
        assert near_cancelled["status"] == "CANCELLED"
        # Half of 20 guests at 5,000 cents each.
        assert near_cancelled["cancellation_penalty_cents"] == 50_000

    def test_cancelling_both_elements_empties_the_open_set(self, api):
        """PRD §3.7: "First compute the days to service: take the interval from the logical
        clock's current instant to the element's `starts_at` and express it in whole 24-hour
        days, discarding any fractional remainder."

        Design: Corner/calculations/cancellation_penalty_standard_tier_band_selected_by_days_to_start
        """
        ctx = self._two_elements_one_clock()
        for element in ctx["elements"]:
            validate_success(
                api.cancel_element(element["id"], PD, {"cancel_reason": "Scope cut."})
            )

        program = read_program(ctx["program"]["id"])

        assert program["open_element_count"] == 0
        assert program["element_count"] == 2


class TestCancellationTierConstants:
    STANDARD_ELEMENT = {
        "element_type": "ACTIVITY",
        "title": "Element M",
        "starts_at": "2026-09-12T09:00:00Z",
        "ends_at": "2026-09-12T13:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 5_000,
    }
    STRICT_ELEMENT = {
        "element_type": "DINE_AROUND",
        "title": "Element N",
        "starts_at": "2026-09-12T09:00:00Z",
        "ends_at": "2026-09-12T13:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 5_000,
    }

    def _identical_elements_under_different_terms(self):
        venue_a = create_venue(
            name="Strict Venue A", capacity_seated=100, capacity_reception=200
        )
        venue_b = create_venue(
            name="Strict Venue B", capacity_seated=100, capacity_reception=200
        )
        standard_supplier = create_supplier(legal_name="Standard Terms Supplier")
        strict_supplier = create_supplier(
            legal_name="Strict Terms Supplier", supplier_type="VENUE_SERVICES"
        )
        program = create_program(
            client_name="Tier Compare Client",
            group_name="Tier Compare Group",
            guaranteed_count=40,
        )
        standard_element = add_element(
            program["id"],
            standard_supplier["id"],
            venue_id=venue_a["id"],
            **self.STANDARD_ELEMENT,
        )
        strict_element = add_element(
            program["id"],
            strict_supplier["id"],
            venue_id=venue_b["id"],
            **self.STRICT_ELEMENT,
        )
        create_active_contract(
            program["id"],
            standard_supplier["id"],
            contract_value_cents=100_000,
            cancellation_tier="STANDARD",
        )
        create_active_contract(
            program["id"],
            strict_supplier["id"],
            contract_value_cents=100_000,
            cancellation_tier="STRICT",
        )
        # Eleven whole days before both elements start.
        set_clock("2026-09-01T00:00:00Z")
        return {"standard": standard_element, "strict": strict_element}

    def test_only_the_contract_tier_separates_the_two_penalties(self, api):
        """PRD §3.7: "On the `STRICT` schedule, even a cancellation 45 or more days out
        costs a tenth; at 30 to 44 days it costs 35 hundredths; at 8 to 29 days it costs
        three quarters; and inside 8 days it costs the whole planned value."

        Design: Corner/calculations/cancellation_penalty_strict_tier_constants_diverge_from_standard
        """
        ctx = self._identical_elements_under_different_terms()

        standard = validate_success(
            api.cancel_element(
                ctx["standard"]["id"], PD, {"cancel_reason": "Scope reduction."}
            )
        )
        strict = validate_success(
            api.cancel_element(
                ctx["strict"]["id"], PD, {"cancel_reason": "Scope reduction."}
            )
        )

        assert standard["cancellation_penalty_cents"] == 50_000
        assert strict["cancellation_penalty_cents"] == 75_000
        # Identical head counts, identical rates, identical clock: only the tier differs.
        assert (
            strict["cancellation_penalty_cents"] - standard["cancellation_penalty_cents"]
            == 25_000
        )


class TestDepositWaterfallOverflow:
    DELIVERED_ELEMENT = {
        "element_type": "ACTIVITY",
        "title": "Waterfall A",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T13:00:00Z",
        "planned_headcount": 25,
        "guaranteed_headcount": 25,
        "per_person_cost_cents": 4_000,
    }
    CANCELLED_ELEMENT = {
        "element_type": "ACTIVITY",
        "title": "Waterfall B",
        "starts_at": "2026-09-25T09:00:00Z",
        "ends_at": "2026-09-25T13:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 5_000,
    }

    def _deposit_larger_than_the_approved_cost(self, api):
        """200,000 cents of deposit against 150,000 cents of approved supplier cost."""
        ctx = setup_multi_element_program(
            [self.DELIVERED_ELEMENT, self.CANCELLED_ELEMENT],
            program_overrides={
                "client_name": "Waterfall Client",
                "group_name": "Waterfall Group",
                "departure_date": "2026-09-30",
                "guaranteed_count": 25,
                "markup_pct": 0.20,
            },
            venue_overrides={"name": "Waterfall Venue"},
            supplier_overrides={"legal_name": "Waterfall Supplier"},
            contract_overrides={"contract_value_cents": 400_000, "deposit_pct": 0.5},
        )
        delivered, cancelled = ctx["elements"]
        advance_to_in_execution(ctx["program"]["id"])
        mark_ready(delivered["id"])
        deliver(delivered["id"], 25, clock="2026-09-11T13:30:00Z")
        # Eleven whole days before the closing element, so the STANDARD half-rate applies.
        set_clock("2026-09-14T09:00:00Z")
        validate_success(
            api.cancel_element(
                cancelled["id"], PD, {"cancel_reason": "Closing dinner cut by the client."}
            )
        )
        lines = open_reconciliation(ctx["program"]["id"])
        for line in lines:
            approve_line(line["id"])
        ctx["program"] = issue_invoice(ctx["program"]["id"])
        ctx["lines"] = {
            line["line_kind"]: validate_success(
                api.get_reconciliation_line(line["id"], PD)
            )
            for line in lines
        }
        return ctx

    def test_the_deposit_covers_everything_and_still_leaves_a_credit(self, api):
        """PRD §3.9: "No rounding occurs anywhere in the waterfall, since it only
        redistributes existing whole cents, and as a result `deposit_applied_cents` plus
        `overpayment_credit_cents` always equals the contract's `deposit_paid_cents`
        exactly."

        Design: Corner/calculations/settlement_deposit_waterfall_overflow_yields_overpayment_credit
        """
        ctx = self._deposit_larger_than_the_approved_cost(api)

        payment = open_settlement_payment(
            ctx["program"]["id"], ctx["supplier"]["id"], ctx["contract"]["id"]
        )

        assert payment["gross_cents"] == 150_000
        assert payment["deposit_applied_cents"] == 150_000
        assert payment["net_payable_cents"] == 0
        assert payment["overpayment_credit_cents"] == 50_000
        assert (
            payment["deposit_applied_cents"] + payment["overpayment_credit_cents"]
            == 200_000
        )

    def test_the_two_line_kinds_feed_the_gross_the_waterfall_consumes(self, api):
        """PRD §3.9: "`gross_cents` is the sum of `supplier_cost_cents` over the
        reconciliation lines of this programme and this supplier whose status is
        `APPROVED`."

        Design: Corner/calculations/settlement_deposit_waterfall_overflow_yields_overpayment_credit
        """
        ctx = self._deposit_larger_than_the_approved_cost(api)

        delivery = ctx["lines"]["DELIVERY"]
        penalty = ctx["lines"]["CANCELLATION_PENALTY"]

        assert delivery["supplier_cost_cents"] == 100_000
        assert delivery["markup_cents"] == 20_000
        assert penalty["supplier_cost_cents"] == 50_000
        assert penalty["markup_cents"] == 10_000
        program = validate_success(api.get_program(ctx["program"]["id"], PD))
        assert program["final_subtotal_cents"] == 150_000
        assert program["disclosed_markup_cents"] == 30_000
        # A 180,000-cent base sits in the bottom fee band at 12 hundredths.
        assert program["management_fee_cents"] == 21_600
        assert program["final_client_total_cents"] == 201_600


class TestReconciliationInputSet:
    PRIMARY = {
        "element_type": "ACTIVITY",
        "title": "Filter Primary",
        "starts_at": "2026-09-11T14:00:00Z",
        "ends_at": "2026-09-11T17:00:00Z",
        "planned_headcount": 30,
        "guaranteed_headcount": 30,
        "per_person_cost_cents": 4_000,
        "is_weather_dependent": True,
    }
    STAND_IN = {
        "element_type": "ACTIVITY",
        "title": "Filter Stand-In",
        "starts_at": "2026-09-11T14:00:00Z",
        "ends_at": "2026-09-11T17:00:00Z",
        "planned_headcount": 30,
        "guaranteed_headcount": 30,
        "per_person_cost_cents": 4_000,
    }

    def _switched_primary_and_delivered_stand_in(self, api):
        lawn = create_venue(
            name="Filter Lawn", capacity_seated=100, capacity_reception=200
        )
        atrium = create_venue(
            name="Filter Atrium", capacity_seated=100, capacity_reception=200
        )
        supplier = create_supplier(legal_name="Filter Supplier")
        program = create_program(
            client_name="Filter Client", group_name="Filter Group", guaranteed_count=30
        )
        primary = add_element(
            program["id"], supplier["id"], venue_id=lawn["id"], **self.PRIMARY
        )
        stand_in = add_element(
            program["id"],
            supplier["id"],
            venue_id=atrium["id"],
            alternative_for_element_id=primary["id"],
            **self.STAND_IN,
        )
        create_active_contract(program["id"], supplier["id"], contract_value_cents=200_000)
        advance_to_in_execution(program["id"])
        mark_ready(primary["id"])
        set_clock("2026-09-11T13:00:00Z")
        validate_success(api.weather_switch_element(primary["id"], OC))
        deliver(stand_in["id"], 28, clock="2026-09-11T17:30:00Z")
        return {"program": program, "primary": primary, "stand_in": stand_in}

    def test_only_the_delivered_stand_in_gets_a_reconciliation_line(self, api):
        """PRD §3.8: "Opening reconciliation materialises exactly one **reconciliation
        line** for each element of the programme in `DELIVERED` or `CANCELLED`, created in
        ascending `starts_at` order of the underlying element with ascending `created_at` as
        the tie-break."

        Design: Corner/calculations/reconciliation_excludes_weather_switched_element_from_line_set
        """
        ctx = self._switched_primary_and_delivered_stand_in(api)
        validate_success(api.reconcile_program(ctx["program"]["id"], PD))

        lines, meta = validate_paginated(
            api.list_reconciliation_lines(
                PD, params={"program_id": ctx["program"]["id"], "limit": 10, "offset": 0}
            )
        )

        assert meta["total_count"] == 1
        assert lines[0]["element_id"] == ctx["stand_in"]["id"]
        assert lines[0]["billed_headcount"] == 28
        assert lines[0]["supplier_cost_cents"] == 112_000
        assert lines[0]["markup_cents"] == 20_160

    def test_the_switched_away_element_never_reaches_the_client_total(self, api):
        """PRD §3.9: "The **final** variant, run at invoice issue, walks the programme's
        reconciliation lines in `APPROVED` status and uses each line's stored
        `supplier_cost_cents` and `markup_cents` figures."

        Design: Corner/calculations/reconciliation_excludes_weather_switched_element_from_line_set
        """
        ctx = self._switched_primary_and_delivered_stand_in(api)
        lines = open_reconciliation(ctx["program"]["id"])
        approve_line(lines[0]["id"])

        program = issue_invoice(ctx["program"]["id"])

        assert program["final_subtotal_cents"] == 112_000
        assert program["disclosed_markup_cents"] == 20_160
        assert program["management_fee_cents"] == 15_859
        assert program["final_client_total_cents"] == 148_019
        assert program["settlement_status"] == "CLIENT_INVOICED"


class TestSeatOccupancyReaggregation:
    FIRST_SHUTTLE = {
        "segment_type": "SHUTTLE_LOOP",
        "vehicle_code": "SHTL-01",
        "origin": "Host Hotel",
        "destination": "Riverside Loft",
        "depart_at": "2026-09-11T18:00:00Z",
        "arrive_at": "2026-09-11T18:40:00Z",
        "seat_capacity": 12,
    }
    SECOND_SHUTTLE = {
        "segment_type": "SHUTTLE_LOOP",
        "vehicle_code": "SHTL-02",
        "origin": "Host Hotel",
        "destination": "Riverside Loft",
        "depart_at": "2026-09-11T18:15:00Z",
        "arrive_at": "2026-09-11T18:55:00Z",
        "seat_capacity": 12,
    }

    def _nine_seats_split_five_and_four(self):
        program = create_program(
            client_name="Occupancy Client",
            group_name="Occupancy Group",
            guaranteed_count=20,
        )
        first = create_transport_segment(program["id"], **self.FIRST_SHUTTLE)
        second = create_transport_segment(program["id"], **self.SECOND_SHUTTLE)
        party_of_five = manifest_guest(
            first["id"], guest_ref="G-100", guest_name="Ada Wren", seat_count=5
        )
        party_of_four = manifest_guest(
            first["id"], guest_ref="G-200", guest_name="Bo Larsen", seat_count=4
        )
        return {
            "program": program,
            "first": first,
            "second": second,
            "five": party_of_five,
            "four": party_of_four,
        }

    def test_moving_the_smaller_party_re_sums_both_vehicles(self, api):
        """PRD §3.5: "A segment's `booked_seat_count` is the sum of `seat_count` over that
        segment's entries whose status is `ASSIGNED` or `CHECKED_IN`; entries in `RELEASED`
        or `NO_SHOW` are excluded."

        Design: Corner/calculations/segment_seat_occupancy_reaggregated_after_move
        """
        ctx = self._nine_seats_split_five_and_four()
        before_first = validate_success(api.get_transport_segment(ctx["first"]["id"], OC))
        before_second = validate_success(
            api.get_transport_segment(ctx["second"]["id"], OC)
        )
        assert before_first["booked_seat_count"] == 9
        assert before_second["booked_seat_count"] == 0

        moved = validate_success(
            api.move_manifest_entry(
                ctx["four"]["id"], {"target_segment_id": ctx["second"]["id"]}, OC
            )
        )

        first = validate_success(api.get_transport_segment(ctx["first"]["id"], OC))
        second = validate_success(api.get_transport_segment(ctx["second"]["id"], OC))
        assert first["booked_seat_count"] == 5
        assert second["booked_seat_count"] == 4
        assert moved["segment_id"] == ctx["second"]["id"]
        assert moved["status"] == "ASSIGNED"
        stayed = validate_success(api.get_manifest_entry(ctx["five"]["id"], OC))
        assert stayed["segment_id"] == ctx["first"]["id"]
        program = read_program(ctx["program"]["id"])
        assert program["seated_guest_count"] == 9
