"""Departure gate ordering, resource calendar overlap semantics, and
compensating invariants (PRD §3.6-§3.9)."""
from test_helpers import (
    BILLING,
    DISPATCHER,
    DRIVER,
    ApiErrorId,
    assert_escort_booking,
    book_escort,
    create_crane_appointment_payload,
    create_customer,
    create_escort_booking_payload,
    create_load_for_customer,
    get_load_version,
    issue_invoice,
    plan_load,
    schedule_crane,
    set_clock,
    setup_ca_oversize_overweight_cleared,
    survey_load,
    validate_error,
    validate_success,
)


class TestSafetyBeatsFiscalAtDepart:
    def _setup_cleared_then_escort_cancelled(self, api):
        """CLEARED CA load whose provisional estimate (475740) exceeds the
        customer's remaining credit (400000); the only REAR escort is then
        cancelled (the gate does not demote a CLEARED load)."""
        ctx = setup_ca_oversize_overweight_cleared(
            company_name="Golden Gate Rigging", credit_limit_cents=400_000,
            route_miles=500,
        )
        validate_success(
            api.cancel_escort_booking(ctx["escort"]["id"], DISPATCHER), 200
        )
        set_clock("2026-08-12T10:00:00Z")
        return ctx

    def test_escort_gap_reports_requirement_unmet(self, api):
        """PRD §3.7: "The checks evaluate in a pinned order — load state,
        escort coverage, travel windows, curfew, then credit — so the earliest
        failing check is the error returned."
        PRD §3.7: "Every required escort position must still be covered by a
        `CONFIRMED` booking, or departure is rejected with
        `ERR_ESCORT_REQUIREMENT_UNMET` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_at_depart
        """
        ctx = self._setup_cleared_then_escort_cancelled(api)
        err = validate_error(
            api.depart_load(ctx["load"]["id"], DRIVER),
            ApiErrorId.ERR_ESCORT_REQUIREMENT_UNMET,
        )
        assert err["error_id"] == "ERR_ESCORT_REQUIREMENT_UNMET"

    def test_credit_failure_is_armed_but_loses_to_escort(self, api):
        """PRD §3.7: "The checks evaluate in a pinned order — load state,
        escort coverage, travel windows, curfew, then credit — so the earliest
        failing check is the error returned."
        PRD §3.7: "Finally, the provisional cost estimate's `total_cents` must
        not exceed the customer's remaining credit — `credit_limit_cents` minus
        `outstanding_balance_cents` — with equality passing and any excess
        rejected as `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_at_depart
        """
        ctx = self._setup_cleared_then_escort_cancelled(api)
        # The credit failure is armed alongside the escort failure: the
        # provisional estimate exceeds the remaining credit (400000). After
        # the escort cancellation, PRD §3.7 says "escorts are summed over
        # `CONFIRMED` bookings", so the cancelled REAR booking drops out and
        # the estimate is linehaul 350000 + permits 42500 + escorts 0 =
        # subtotal 392500; fuel 8% = 31400; total = 423900.
        est = validate_success(
            api.get_cost_estimate(ctx["load"]["id"], BILLING), 200
        )
        assert est["total_cents"] == 423900
        assert est["total_cents"] > 400000
        err = validate_error(
            api.depart_load(ctx["load"]["id"], DRIVER),
            ApiErrorId.ERR_ESCORT_REQUIREMENT_UNMET,
        )
        # A wrong ordering would surface ERR_CREDIT_LIMIT_EXCEEDED instead.
        assert err["error_id"] != "ERR_CREDIT_LIMIT_EXCEEDED"
        assert err["error_id"] == "ERR_ESCORT_REQUIREMENT_UNMET"


class TestEscortProviderHalfOpenAdjacency:
    def _setup_surveyed_ca_load(self, api):
        customer = create_customer("Overlap Test Co", 100_000_000)
        load = create_load_for_customer(
            customer["id"],
            cargo_description="Tank", gross_weight_lbs=96000,
            width_in=150, height_in=100, length_in=400,
            origin="Fresno CA", destination="Visalia CA",
        )
        plan_load(
            load["id"], trailer_type="EXTENDABLE_DOUBLE_DROP",
            trailer_axle_count=6, driver_name="P. Yu",
            driver_oversize_endorsed=True,
        )
        survey_load(
            load["id"], route_miles=500, states_crossed=["CA"],
            min_bridge_clearance_in=200, max_bridge_weight_lbs=120000,
        )
        return load

    def test_adjacent_booking_accepted_under_half_open_semantics(self, api):
        """PRD §3.6: "A new booking is rejected with
        `ERR_ESCORT_WINDOW_OVERLAP` (HTTP 409) when its half-open window —
        inclusive of `scheduled_start`, exclusive of `scheduled_end` —
        intersects any other `CONFIRMED` booking for the same `provider_name`.
        Adjacency is allowed: a booking that begins exactly when another ends
        does not overlap it."

        Design: Difficulty/resource_temporal_overlap/escort_provider_half_open_adjacency
        """
        load = self._setup_surveyed_ca_load(api)
        first = book_escort(
            load["id"], provider_name="Shared Roads Pilot", position="REAR",
            start="2026-08-12T08:00:00Z", end="2026-08-12T10:00:00Z",
        )
        assert_escort_booking(first)
        assert first["status"] == "CONFIRMED"
        # new.start == existing.end is adjacency, not overlap.
        second = book_escort(
            load["id"], provider_name="Shared Roads Pilot", position="REAR",
            start="2026-08-12T10:00:00Z", end="2026-08-12T12:00:00Z",
        )
        assert second["status"] == "CONFIRMED"

    def test_intersecting_booking_rejected(self, api):
        """PRD §3.6: "A provider cannot be in two places at once. A new booking
        is rejected with `ERR_ESCORT_WINDOW_OVERLAP` (HTTP 409) when its
        half-open window — inclusive of `scheduled_start`, exclusive of
        `scheduled_end` — intersects any other `CONFIRMED` booking for the same
        `provider_name`."

        Design: Difficulty/resource_temporal_overlap/escort_provider_half_open_adjacency
        """
        load = self._setup_surveyed_ca_load(api)
        book_escort(
            load["id"], provider_name="Shared Roads Pilot", position="REAR",
            start="2026-08-12T08:00:00Z", end="2026-08-12T10:00:00Z",
        )
        book_escort(
            load["id"], provider_name="Shared Roads Pilot", position="REAR",
            start="2026-08-12T10:00:00Z", end="2026-08-12T12:00:00Z",
        )
        # 09:30-10:30 genuinely intersects both CONFIRMED windows.
        err = validate_error(
            api.create_escort_booking(
                load["id"],
                create_escort_booking_payload(
                    provider_name="Shared Roads Pilot", position="REAR",
                    scheduled_start="2026-08-12T09:30:00Z",
                    scheduled_end="2026-08-12T10:30:00Z",
                    expected_load_version=get_load_version(load["id"]),
                ),
                DISPATCHER,
            ),
            ApiErrorId.ERR_ESCORT_WINDOW_OVERLAP,
        )
        assert err["error_id"] == "ERR_ESCORT_WINDOW_OVERLAP"


class TestOutstandingBalanceIssueVoidConservation:
    def test_issue_raises_outstanding_to_issued_total(self, api):
        """PRD §3.1: "The outstanding balance is a computed figure: it is the
        sum of `total_cents` over that customer's invoices currently in
        `ISSUED` status, so issuing an invoice debits the balance while paying
        or voiding it credits the balance back."

        Design: Difficulty/compensating_invariant/outstanding_balance_issue_void_conservation
        """
        ctx = setup_ca_oversize_overweight_cleared(
            company_name="Ledger Test Co", route_miles=500,
        )
        load_id = ctx["load"]["id"]
        cust_id = ctx["customer"]["id"]
        set_clock("2026-08-12T10:00:00Z")
        validate_success(api.depart_load(load_id, DRIVER), 200)
        validate_success(api.arrive_load(load_id, DRIVER), 200)
        before = validate_success(api.get_customer(cust_id, BILLING), 200)
        # Invariant baseline: sum over zero ISSUED invoices.
        assert before["outstanding_balance_cents"] == 0
        inv = issue_invoice(load_id)
        # subtotal 440500 = 350000 + 42500 + 48000; fuel 8% = 35240.
        assert inv["total_cents"] == 475740
        mid = validate_success(api.get_customer(cust_id, BILLING), 200)
        # Forward action: outstanding == the single ISSUED total.
        assert mid["outstanding_balance_cents"] == 475740

    def test_void_returns_outstanding_to_baseline(self, api):
        """PRD §3.9: "Voiding, also restricted to `ISSUED` invoices, moves it
        to the terminal `VOID` state, credits the same amount off the
        outstanding balance, and un-sweeps the invoice's fines from `APPLIED`
        back to `PENDING` so that a replacement invoice can legitimately
        include them."

        Design: Difficulty/compensating_invariant/outstanding_balance_issue_void_conservation
        """
        ctx = setup_ca_oversize_overweight_cleared(
            company_name="Ledger Test Co", route_miles=500,
        )
        load_id = ctx["load"]["id"]
        cust_id = ctx["customer"]["id"]
        set_clock("2026-08-12T10:00:00Z")
        validate_success(api.depart_load(load_id, DRIVER), 200)
        validate_success(api.arrive_load(load_id, DRIVER), 200)
        inv = issue_invoice(load_id)
        validate_success(api.void_invoice(inv["id"], BILLING), 200)
        after = validate_success(api.get_customer(cust_id, BILLING), 200)
        # Compensating action: void returns the conserved quantity exactly to
        # baseline — zero drift.
        assert after["outstanding_balance_cents"] == 0


class TestEscortWindowBookCancelConservation:
    def test_cancel_frees_the_provider_window(self, api):
        """PRD §3.6: "The `Dispatcher` may also cancel a `CONFIRMED` booking;
        cancellation frees the provider's window and re-evaluates the readiness
        gate, but per §2.7 it never demotes an already-`CLEARED` load."

        Design: Difficulty/compensating_invariant/escort_window_book_cancel_conservation
        """
        customer = create_customer("Calendar Test Co", 100_000_000)
        load = create_load_for_customer(
            customer["id"],
            cargo_description="Mixer drum", gross_weight_lbs=96000,
            width_in=150, height_in=100, length_in=400,
            origin="Modesto CA", destination="Stockton CA",
        )
        plan_load(
            load["id"], trailer_type="EXTENDABLE_DOUBLE_DROP",
            trailer_axle_count=6, driver_name="S. Voss",
            driver_oversize_endorsed=True,
        )
        survey_load(
            load["id"], route_miles=500, states_crossed=["CA"],
            min_bridge_clearance_in=200, max_bridge_weight_lbs=120000,
        )
        first = book_escort(
            load["id"], provider_name="Cal Heavy Pilots", position="REAR",
            start="2026-08-12T08:00:00Z", end="2026-08-12T12:00:00Z",
        )
        assert first["status"] == "CONFIRMED"
        cancelled = validate_success(
            api.cancel_escort_booking(first["id"], DISPATCHER), 200
        )
        assert cancelled["status"] == "CANCELLED"

    def test_rebooking_identical_window_after_cancel_succeeds(self, api):
        """PRD §3.6: "cancellation frees the provider's window and re-evaluates
        the readiness gate, but per §2.7 it never demotes an already-`CLEARED`
        load."
        PRD §3.6: "A new booking is rejected with `ERR_ESCORT_WINDOW_OVERLAP`
        (HTTP 409) when its half-open window — inclusive of `scheduled_start`,
        exclusive of `scheduled_end` — intersects any other `CONFIRMED` booking
        for the same `provider_name`."

        Design: Difficulty/compensating_invariant/escort_window_book_cancel_conservation
        """
        customer = create_customer("Calendar Test Co", 100_000_000)
        load = create_load_for_customer(
            customer["id"],
            cargo_description="Mixer drum", gross_weight_lbs=96000,
            width_in=150, height_in=100, length_in=400,
            origin="Modesto CA", destination="Stockton CA",
        )
        plan_load(
            load["id"], trailer_type="EXTENDABLE_DOUBLE_DROP",
            trailer_axle_count=6, driver_name="S. Voss",
            driver_oversize_endorsed=True,
        )
        survey_load(
            load["id"], route_miles=500, states_crossed=["CA"],
            min_bridge_clearance_in=200, max_bridge_weight_lbs=120000,
        )
        first = book_escort(
            load["id"], provider_name="Cal Heavy Pilots", position="REAR",
            start="2026-08-12T08:00:00Z", end="2026-08-12T12:00:00Z",
        )
        validate_success(api.cancel_escort_booking(first["id"], DISPATCHER), 200)
        # Rebooking the identical window succeeds: the occupied set after
        # create+cancel equals the empty baseline (no phantom occupation).
        second = book_escort(
            load["id"], provider_name="Cal Heavy Pilots", position="REAR",
            start="2026-08-12T08:00:00Z", end="2026-08-12T12:00:00Z",
        )
        assert second["status"] == "CONFIRMED"
