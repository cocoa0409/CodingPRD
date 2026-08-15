"""Equipment logistics: stock selection, dispatch/return, billing dimension,
late/shortage charges, and segregation of duties (PRD §2.9, §3.6)."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_charge_entry,
    assert_equipment_reservation,
    assert_stock_conservation,
    create_application_record,
    create_reservation_record,
    create_stock_record,
    dispatch_then_return,
    make_depot_officer_headers,
    make_organizer_headers,
    pay_reservation_record,
    return_reservation_record,
    set_logical_clock,
    setup_issued_application,
    setup_under_review_application,
    submit_application_record,
    validate_error,
    validate_success,
    verify_return_record,
)

DEPOT_1 = TEST_USERS["depot_officer_1_headers"]
DEPOT_2 = TEST_USERS["depot_officer_2_headers"]
OFFICER = TEST_USERS["permit_officer_headers"]


def _issued_with_barricades(api, *, units=4, stock_total=10, attendance=100, length_m=48,
                            tcp_barricades=4):
    return setup_issued_application(
        application_overrides={"expected_attendance": attendance},
        segment_overrides={"length_m": length_m},
        tcp_overrides={"barricade_count": tcp_barricades},
        stocks=[{"equipment_kind": "BARRICADE", "total_units": stock_total}],
        reservations=[{"equipment_kind": "BARRICADE", "units": units}],
    )


class TestParallelBillingDimension:
    def _issued_dispatched_returned(self, api):
        ctx = _issued_with_barricades(api, units=4)
        dispatch_then_return(
            ctx, dispatch_at="2026-06-19T15:00:00Z", return_at="2026-06-21T10:00:00Z",
            returned_units=4,
        )
        return ctx

    def test_billing_axis_gates_verify_return(self, api):
        """PRD §3.6: "billing must already be settled — `PAID` or `WAIVED`, since an
        outstanding `INVOICED` balance fails with `ERR_BILLING_UNSETTLED`."
        PRD §3.5: "every reservation still `HELD` is confirmed — `reservation_status` becomes
        `CONFIRMED` while its `billing_status` moves from `UNBILLED` to `INVOICED` with
        `invoice_cents` computed per line."

        Design: Difficulty/non_linear_state_machine/reservation_parallel_billing_dimension_gates_close
        """
        ctx = _issued_with_barricades(api, units=4)
        reservation = ctx["reservations"][0]
        # After issuance the two dimensions sit at CONFIRMED x INVOICED independently.
        assert reservation["reservation_status"] == "CONFIRMED"
        assert reservation["billing_status"] == "INVOICED"
        assert reservation["invoice_cents"] == 1083, "4*250 + round_half_up(82.5)=83"

        dispatch_then_return(
            ctx, dispatch_at="2026-06-19T15:00:00Z", return_at="2026-06-21T10:00:00Z",
            returned_units=4,
        )
        # Verify-return while the billing axis is still INVOICED is rejected.
        res = api.verify_return_equipment_reservation(reservation["id"], DEPOT_2)
        validate_error(res, "ERR_BILLING_UNSETTLED")
        current = validate_success(
            api.get_equipment_reservation(
                reservation["id"], make_organizer_headers(ctx["organizer"]["id"])), 200
        )
        assert current["reservation_status"] == "RETURNED"

    def test_pay_then_verify_closes_reservation(self, api):
        """PRD §3.6: "the organizer pays an `INVOICED` reservation — payment is simulated —
        taking billing to `PAID`".
        PRD §3.6: "Verifying a return — moving the reservation from `RETURNED` to terminal
        `CLOSED` — must be performed by a `DepotOfficer` whose `X-User-ID` differs from the
        `dispatched_by` recorded at dispatch".

        Design: Difficulty/non_linear_state_machine/reservation_parallel_billing_dimension_gates_close
        """
        ctx = self._issued_dispatched_returned(api)
        reservation = ctx["reservations"][0]
        assert reservation["reservation_status"] == "RETURNED"

        paid = pay_reservation_record(reservation["id"], ctx["organizer"])
        assert paid["billing_status"] == "PAID"
        assert paid["reservation_status"] == "RETURNED", "payment leaves the lifecycle axis alone"

        closed = verify_return_record(reservation["id"], DEPOT_2)
        assert closed["reservation_status"] == "CLOSED"
        assert closed["return_verified_by"] == "depot-2"


class TestBufferedAggregateCapacity:
    def _setup_three_applications(self, api):
        ctx = setup_under_review_application(
            application_overrides={
                "event_start_at": "2026-06-20T14:00:00Z",
                "event_end_at": "2026-06-20T22:00:00Z",
            }
        )
        petition, organizer = ctx["petition"], ctx["organizer"]
        stock = create_stock_record(equipment_kind="BARRICADE", total_units=10)
        res_a = create_reservation_record(ctx["application"], organizer, "BARRICADE", 7)
        app_b = create_application_record(
            petition, organizer,
            event_start_at="2026-06-22T14:00:00Z", event_end_at="2026-06-22T20:00:00Z",
        )
        submit_application_record(app_b, organizer)
        app_c = create_application_record(
            petition, organizer,
            event_start_at="2026-06-23T14:00:00Z", event_end_at="2026-06-23T20:00:00Z",
        )
        submit_application_record(app_c, organizer)
        ctx.update(stock=stock, res_a=res_a, app_b=app_b, app_c=app_c)
        return ctx

    def test_buffered_overlap_rejects_second_event(self, api):
        """PRD §3.6: "Overlap is closed — two windows overlap whenever each starts no later
        than the other ends, so windows that merely touch at an endpoint still overlap."
        PRD §3.6: "Stocks whose window-available units meet or exceed the requested `units`
        are candidates; the selector ranks candidates by window-available units descending
        and breaks ties by the stock's `created_at` ascending, never by `id`. An empty
        candidate set rejects the reservation with `ERR_EQUIPMENT_UNAVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/equipment_buffered_aggregate_capacity
        """
        ctx = self._setup_three_applications(api)
        organizer = ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        # B's buffered window [06-21T14:00, 06-23T20:00] overlaps A's buffered window
        # [06-19T14:00, 06-21T22:00]: 7 + 4 = 11 > 10 -> no candidate.
        res = api.create_equipment_reservation(
            ctx["app_b"]["id"], {"equipment_kind": "BARRICADE", "units": 4}, headers
        )
        validate_error(res, "ERR_EQUIPMENT_UNAVAILABLE")

    def test_non_overlapping_window_accepted_and_counters(self, api):
        """PRD §2.9: "`reserved_units` is the sum of `units` over reservations drawn on that
        stock whose `reservation_status` is `HELD` or `CONFIRMED` and whose parent
        application's buffered window contains the current logical time".
        PRD §3.6: "An empty candidate set rejects the reservation with
        `ERR_EQUIPMENT_UNAVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/equipment_buffered_aggregate_capacity
        """
        ctx = self._setup_three_applications(api)
        organizer = ctx["organizer"]
        headers = make_organizer_headers(organizer["id"])
        # C's buffered window starts 06-22T14:00, after A's buffered end 06-21T22:00.
        res_c = create_reservation_record(ctx["app_c"], organizer, "BARRICADE", 4)
        assert res_c["reservation_status"] == "HELD"

        # Inside A's buffered window but outside C's: only A's 7 units tally.
        set_logical_clock("2026-06-20T15:00:00Z")
        stock = validate_success(api.get_equipment_stock(ctx["stock"]["id"], OFFICER), 200)
        assert stock["reserved_units"] == 7
        assert stock["out_units"] == 0
        assert stock["available_units"] == 3
        assert_stock_conservation(stock)


class TestUnitConservationInvariant:
    def test_reserved_units_inside_buffered_window(self, api):
        """PRD §2.9: "`available_units` is `total_units` minus `reserved_units` minus
        `out_units`. The conservation invariant `total_units` equals `available_units` plus
        `reserved_units` plus `out_units` holds at every instant".

        Design: Difficulty/compensating_invariant/equipment_unit_conservation_invariant
        """
        ctx = _issued_with_barricades(api, units=4)
        set_logical_clock("2026-06-19T15:00:00Z")  # inside the buffered window
        stock = validate_success(api.get_equipment_stock(ctx["stocks"][0]["id"], OFFICER), 200)
        assert stock["reserved_units"] == 4
        assert stock["out_units"] == 0
        assert stock["available_units"] == 6
        assert_stock_conservation(stock)

    def test_dispatch_and_return_pair_conserves_units(self, api):
        """PRD §2.9: "The conservation invariant `total_units` equals `available_units` plus
        `reserved_units` plus `out_units` holds at every instant: dispatching moves units
        from the reserved tally into the out tally, recording a return subtracts the returned
        quantity from the out tally, and cancellation, recall, and closure release their
        reservation entirely."

        Design: Difficulty/compensating_invariant/equipment_unit_conservation_invariant
        """
        ctx = _issued_with_barricades(api, units=4)
        stock_id = ctx["stocks"][0]["id"]
        set_logical_clock("2026-06-19T15:00:00Z")
        dispatch_reservation_record = api.dispatch_equipment_reservation(
            ctx["reservations"][0]["id"], DEPOT_1
        )
        validate_success(dispatch_reservation_record, 200)
        stock = validate_success(api.get_equipment_stock(stock_id, OFFICER), 200)
        assert (stock["reserved_units"], stock["out_units"], stock["available_units"]) == (0, 4, 6)
        assert_stock_conservation(stock)

        set_logical_clock("2026-06-21T10:00:00Z")
        validate_success(
            api.return_equipment_reservation(
                ctx["reservations"][0]["id"], {"returned_units": 4}, DEPOT_1
            ),
            200,
        )
        stock = validate_success(api.get_equipment_stock(stock_id, OFFICER), 200)
        assert (stock["reserved_units"], stock["out_units"], stock["available_units"]) == (0, 0, 10)
        assert_stock_conservation(stock)


class TestStockSelector:
    def test_selector_ranks_by_window_available_then_created_at(self, api):
        """PRD §3.6: "Stocks whose window-available units meet or exceed the requested
        `units` are candidates; the selector ranks candidates by window-available units
        descending and breaks ties by the stock's `created_at` ascending, never by `id`."
        PRD §3.6: "A created reservation opens with `reservation_status` `HELD` and
        `billing_status` `UNBILLED`, its `stock_id` recording the selector's choice".

        Design: Corner/calculations/selector_rank_and_tiebreak
        """
        ctx = setup_under_review_application()
        app, organizer = ctx["application"], ctx["organizer"]
        s1 = create_stock_record(depot_name="Depot S1", equipment_kind="BARRICADE", total_units=5)
        s2 = create_stock_record(depot_name="Depot S2", equipment_kind="BARRICADE", total_units=10)
        s3 = create_stock_record(depot_name="Depot S3", equipment_kind="BARRICADE", total_units=10)

        first = create_reservation_record(app, organizer, "BARRICADE", 4)
        assert first["stock_id"] == s2["id"], "10 available beats 5; S2/S3 tie -> older S2"
        second = create_reservation_record(app, organizer, "BARRICADE", 4)
        assert second["stock_id"] == s3["id"], "after the first hold S2 has 6 left, S3 has 10"
        assert first["reservation_status"] == "HELD"
        assert first["billing_status"] == "UNBILLED"

    def test_selector_empty_pool_rejected(self, api):
        """PRD §3.6: "An empty candidate set rejects the reservation with
        `ERR_EQUIPMENT_UNAVAILABLE`."

        Design: Corner/calculations/selector_empty_pool_returns_409
        """
        ctx = setup_under_review_application()
        create_stock_record(depot_name="Depot N", equipment_kind="CONE", total_units=50)
        res = api.create_equipment_reservation(
            ctx["application"]["id"], {"equipment_kind": "SIGN", "units": 2},
            make_organizer_headers(ctx["organizer"]["id"]),
        )
        validate_error(res, "ERR_EQUIPMENT_UNAVAILABLE")


class TestDispatchAndReturn:
    def test_dispatch_window_violation_and_inclusive_boundary(self, api):
        """PRD §3.6: "A `DepotOfficer` dispatches a `CONFIRMED` reservation only while the
        parent application is `ISSUED` (else `ERR_INVALID_STATE`) and only inside the
        dispatch window — from 48 hours before `event_start_at` through `event_start_at`
        itself, both endpoints included, with attempts outside rejected as
        `ERR_DISPATCH_WINDOW_VIOLATION`."
        PRD §3.6: "Dispatch records `dispatched_by` from the officer's `X-User-ID`, stamps
        `dispatched_at` from the logical clock, fixes `return_due_at` at 48 hours after
        `event_end_at`, and moves the reserved `units` into the stock's out tally."

        Design: Corner/errors/dispatch_window_violation_and_boundary
        """
        ctx = _issued_with_barricades(api, units=1, length_m=12, tcp_barricades=1)
        reservation = ctx["reservations"][0]
        # 2026-06-17T15:00 is before the window opens at event_start - 48h (06-18T14:00).
        set_logical_clock("2026-06-17T15:00:00Z")
        res = api.dispatch_equipment_reservation(reservation["id"], DEPOT_1)
        validate_error(res, "ERR_DISPATCH_WINDOW_VIOLATION")
        # Exactly at event_start (inclusive bound) succeeds.
        set_logical_clock("2026-06-20T14:00:00Z")
        dispatched = validate_success(api.dispatch_equipment_reservation(reservation["id"], DEPOT_1), 200)
        assert dispatched["reservation_status"] == "DISPATCHED"
        assert dispatched["dispatched_by"] == "depot-1"
        due = datetime.fromisoformat(dispatched["return_due_at"].replace("Z", "+00:00"))
        assert due == datetime(2026, 6, 22, 22, 0, tzinfo=timezone.utc)

    def test_return_at_exact_due_instant_is_on_time(self, api):
        """PRD §3.6: "The platform stamps `returned_at`, computes `late_days` — zero when the
        return lands at or before `return_due_at` (a return exactly at the deadline is on
        time), otherwise the hours late divided by 24 rounded up to whole days — and
        subtracts the returned quantity from the stock's out tally."

        Design: Corner/calculations/late_fee_zero_at_exact_due_boundary
        """
        ctx = _issued_with_barricades(api, units=1, stock_total=5, attendance=40,
                                      length_m=12, tcp_barricades=1)
        dispatch_then_return(
            ctx, dispatch_at="2026-06-19T15:00:00Z", return_at="2026-06-22T22:00:00Z",
            returned_units=1,
        )
        reservation = ctx["reservations"][0]
        assert reservation["reservation_status"] == "RETURNED"
        assert reservation["late_days"] == 0
        headers = make_organizer_headers(ctx["organizer"]["id"])
        charges = validate_success(api.list_deposit_charges(ctx["deposit"]["id"], headers), 200)
        assert charges == [], "on-time return posts no charge"
        deposit = validate_success(api.get_deposit(ctx["deposit"]["id"], headers), 200)
        assert deposit["charges_cents"] == 0

    def test_return_response_carries_computed_fields(self, api):
        """PRD §3.6: "The platform stamps `returned_at`, computes `late_days` — zero when the
        return lands at or before `return_due_at` (a return exactly at the deadline is on
        time), otherwise the hours late divided by 24 rounded up to whole days — and
        subtracts the returned quantity from the stock's out tally."
        PRD §3.6: "Dispatch records `dispatched_by` from the officer's `X-User-ID`, stamps
        `dispatched_at` from the logical clock, fixes `return_due_at` at 48 hours after
        `event_end_at`, and moves the reserved `units` into the stock's out tally."

        Design: Corner/consistency_model/immediate_consistency_on_return_response
        """
        ctx = _issued_with_barricades(api, units=1, stock_total=5, attendance=40,
                                      length_m=12, tcp_barricades=1)
        set_logical_clock("2026-06-19T15:00:00Z")
        validate_success(
            api.dispatch_equipment_reservation(ctx["reservations"][0]["id"], DEPOT_1), 200
        )
        set_logical_clock("2026-06-23T10:00:00Z")  # 12h past the 06-22T22:00 deadline
        returned = validate_success(
            api.return_equipment_reservation(
                ctx["reservations"][0]["id"], {"returned_units": 1}, DEPOT_1
            ),
            200,
        )
        # The return response itself carries the reconciled state; no follow-up read needed.
        assert returned["reservation_status"] == "RETURNED"
        assert returned["late_days"] == 1
        due = datetime.fromisoformat(returned["return_due_at"].replace("Z", "+00:00"))
        assert due == datetime(2026, 6, 22, 22, 0, tzinfo=timezone.utc)

    def test_charge_entry_shape_and_late_amount(self, api):
        """PRD §2.4: "The one exception is the ChargeEntry posted against a deposit: a charge
        entry carries only `id` and `created_at`. Both `updated_at` and `version` are absent
        from charge entries, because a posted charge is immutable once written."
        PRD §3.6: "A late return posts a `LATE_EQUIPMENT` ChargeEntry of `returned_units`
        times the kind's unit rate times two, times `late_days`, written only when positive."

        Design: Corner/entities/charge_entry_immutable_shape
        """
        ctx = _issued_with_barricades(api, units=1, stock_total=5, attendance=40,
                                      length_m=12, tcp_barricades=1)
        dispatch_then_return(
            ctx, dispatch_at="2026-06-19T15:00:00Z", return_at="2026-06-23T10:00:00Z",
            returned_units=1,
        )
        headers = make_organizer_headers(ctx["organizer"]["id"])
        charges = validate_success(api.list_deposit_charges(ctx["deposit"]["id"], headers), 200)
        assert len(charges) == 1
        charge = charges[0]
        assert_charge_entry(charge)
        assert charge["kind"] == "LATE_EQUIPMENT"
        assert charge["amount_cents"] == 500, "1 unit * 250 * 2 * 1 late day"
        assert charge["deposit_id"] == ctx["deposit"]["id"]
        assert charge["source_reservation_id"] == ctx["reservations"][0]["id"]


class TestWaiverCapAndSod:
    def test_waive_cap_boundary(self, api):
        """PRD §3.6: "a `PermitOfficer` may waive an invoice of at most 500 cents (an invoice
        of exactly 500 cents qualifies; anything larger fails with
        `ERR_WAIVER_AMOUNT_TOO_LARGE`), taking billing to `WAIVED`."

        Design: Corner/errors/waive_cap_boundary
        """
        ctx = setup_issued_application(
            segment_overrides={"length_m": 24},
            tcp_overrides={"barricade_count": 2, "cone_count": 1},
            stocks=[
                {"equipment_kind": "BARRICADE", "total_units": 5},
                {"equipment_kind": "CONE", "total_units": 5},
            ],
            reservations=[
                {"equipment_kind": "BARRICADE", "units": 2},
                {"equipment_kind": "CONE", "units": 1},
            ],
        )
        res_b, res_c = ctx["reservations"]
        assert res_b["invoice_cents"] == 541, "500 + round_half_up(41.25)=41"
        assert res_c["invoice_cents"] == 27, "25 + round_half_up(2.0625)=2"

        res = api.waive_equipment_reservation(res_b["id"], OFFICER)
        validate_error(res, "ERR_WAIVER_AMOUNT_TOO_LARGE")
        waived = validate_success(api.waive_equipment_reservation(res_c["id"], OFFICER), 200)
        assert waived["billing_status"] == "WAIVED"
        assert waived["reservation_status"] == "CONFIRMED", "waiving leaves the lifecycle axis alone"

    def test_same_officer_cannot_verify_own_dispatch(self, api):
        """PRD §3.6: "Verifying a return — moving the reservation from `RETURNED` to terminal
        `CLOSED` — must be performed by a `DepotOfficer` whose `X-User-ID` differs from the
        `dispatched_by` recorded at dispatch, segregation failures surfacing as
        `ERR_SOD_SAME_OFFICER` (HTTP 403), and billing must already be settled — `PAID` or
        `WAIVED`, since an outstanding `INVOICED` balance fails with `ERR_BILLING_UNSETTLED`."

        Design: Corner/validations/sod_same_officer_verify_return_returns_403
        """
        ctx = _issued_with_barricades(api, units=1, stock_total=5, attendance=40,
                                      length_m=12, tcp_barricades=1)
        reservation = ctx["reservations"][0]
        dispatch_then_return(
            ctx, dispatch_at="2026-06-19T15:00:00Z", return_at="2026-06-21T10:00:00Z",
            returned_units=1,
        )
        pay_reservation_record(reservation["id"], ctx["organizer"])
        # The dispatcher (depot-1) cannot verify their own return.
        res = api.verify_return_equipment_reservation(reservation["id"], DEPOT_1)
        validate_error(res, "ERR_SOD_SAME_OFFICER")
        # A different officer closes it.
        closed = verify_return_record(reservation["id"], DEPOT_2)
        assert closed["reservation_status"] == "CLOSED"
        assert closed["return_verified_by"] == "depot-2"
        assert_equipment_reservation(closed)
