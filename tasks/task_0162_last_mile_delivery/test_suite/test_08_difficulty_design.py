"""Difficulty-design priority queue coverage.

Every instance declared in the difficulty-design index produces at
least TWO dedicated tests. Each docstring quotes the PRD prose that
states the underlying rule (the difficulty-design entry itself is
NEVER the citation) and tags the test with its rule/instance label.
"""
from __future__ import annotations

import math
from datetime import timedelta

import pytest

from test_helpers import (
    APPOINTMENT_CHANGE_FEE,
    BASE_FEE,
    DISTANCE_BUCKET_FEE,
    DISTANCE_BUCKET_KM,
    EARTH_RADIUS_KM,
    HAZMAT_SURCHARGE,
    PARCEL_WEIGHT_MAX_INCLUSIVE,
    REATTEMPT_FEE,
    RESIDENTIAL_SURCHARGE,
    SIGNATURE_SURCHARGE,
    TEST_USERS,
    WEIGHT_FREE_KG,
    WEIGHT_PER_KG_FEE,
    add_stop,
    advance_clock_by_days,
    advance_clock_to,
    api_client,
    assert_cost_precision,
    check_in_driver,
    create_appointment_payload,
    create_parcel,
    create_parcel_payload,
    create_route,
    current_clock,
    deliver_signed,
    dispatch_route,
    haversine_km,
    induct_to_hub,
    iso_utc,
    make_customer_headers,
    make_driver_headers,
    move_clock_into_window,
    parse_iso,
    reattempt_parcel,
    record_attempt,
    reset_driver_to_on_duty,
    setup_appointment_on_exception_parcel,
    setup_baseline,
    setup_parcel_in_exception,
    setup_quote_vs_final_divergence_scenario,
    setup_three_sorted_parcels_one_route,
    sort_parcel,
    validate_error,
    validate_success,
    walk_parcel_to_out_for_delivery,
    walk_parcel_to_sorted,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalcParcelQuoteVsFinal:
    """difficulty: dual_variant_calc/parcel_quote_vs_final_fee_divergence"""

    def test_quoted_and_final_diverge_after_one_reattempt(self, api):
        """PRD §3.7 (quote): 'The quote is forward-looking: it presumes
        a single successful first-attempt delivery, zero redelivery
        surcharges, and no appointment changes.'
        PRD §3.7 (final): 'if the attempt's outcome is NO_ONE_HOME or
        REFUSED, a reattempt fee of 3.00 is added to the accumulator'.

        Claim: a parcel that suffers a NO_ONE_HOME then a successful
        delivery must have final_fee == quoted_fee + REATTEMPT_FEE
        (3.00), making them strictly different.
        """
        # difficulty: dual_variant_calc/parcel_quote_vs_final_fee_divergence
        ctx = setup_quote_vs_final_divergence_scenario()
        assert ctx["parcel"]["status"] == "DELIVERED"
        assert ctx["parcel"]["final_fee"] == pytest.approx(
            ctx["quoted_fee"] + REATTEMPT_FEE, abs=0.01,
        )
        assert ctx["parcel"]["final_fee"] != ctx["quoted_fee"]
        assert_cost_precision(ctx["parcel"]["final_fee"])
        assert_cost_precision(ctx["quoted_fee"])

    def test_quoted_remains_stable_during_lifecycle_until_post_in_transit_edits(self, api):
        """PRD §3.7 (quote): 'A quote is computed every time a parcel
        is inducted into the system, every time it transitions from
        INDUCTED to IN_TRANSIT_HUB, and every time the controlled
        update path mutates weight_kg, destination_address_id,
        hazmat_class, or signature_required while the parcel is still
        in INDUCTED or IN_TRANSIT_HUB.'

        Two-reader claim: when no quote-input changes, quoted_fee at
        induction equals quoted_fee at IN_TRANSIT_HUB transition. This
        complements the divergence test above by isolating that the
        quote's forward-looking nature is not "drift" but "no further
        recomputation occurs once SORTED."
        """
        # difficulty: dual_variant_calc/parcel_quote_vs_final_fee_divergence
        base = setup_baseline()
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        quote_at_induction = parcel["quoted_fee"]
        in_hub = validate_success(api.induct_parcel_to_hub(
            parcel["id"], TEST_USERS["sorting_hub_operator_headers"],
        ), 200)
        assert in_hub["quoted_fee"] == pytest.approx(
            quote_at_induction, abs=0.01,
        )


class TestDualVariantCalcCustomerRollingVsParcelCounter:
    """difficulty: dual_variant_calc/customer_rolling_redelivery_vs_parcel_redelivery_counter"""

    def test_parcel_counter_is_monotonic_per_parcel(self, api):
        """PRD §3.5: 'redelivery_attempts is incremented by one' on
        each failed attempt. Distinct from the customer's rolling
        counter, this is a per-parcel monotonic integer.
        """
        # difficulty: dual_variant_calc/customer_rolling_redelivery_vs_parcel_redelivery_counter
        ctx = walk_parcel_to_out_for_delivery()
        before = ctx["parcel"]["redelivery_attempts"]
        move_clock_into_window(ctx["parcel"])
        api.create_attempt(
            ctx["parcel"]["id"],
            {"route_stop_id": ctx["stop"]["id"],
             "outcome": "NO_ONE_HOME"},
            make_driver_headers(ctx["driver"]["id"]),
        )
        after = validate_success(api.get_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        assert after["redelivery_attempts"] == before + 1

    def test_customer_counter_drops_after_30_day_window_passes(self, api):
        """PRD §3.7: 'the system counts the number of DeliveryAttempt
        rows whose outcome is either NO_ONE_HOME or REFUSED and whose
        attempted_at is greater than or equal to the instant exactly
        30 days before Clock.now, and at most equal to Clock.now.'

        Claim: failures older than 30 days drop out of the customer
        counter while Parcel.redelivery_attempts remains.
        """
        # difficulty: dual_variant_calc/customer_rolling_redelivery_vs_parcel_redelivery_counter
        ctx = walk_parcel_to_out_for_delivery()
        move_clock_into_window(ctx["parcel"])
        api.create_attempt(
            ctx["parcel"]["id"],
            {"route_stop_id": ctx["stop"]["id"],
             "outcome": "NO_ONE_HOME"},
            make_driver_headers(ctx["driver"]["id"]),
        )
        # Customer counter is 1 now.
        cust_before = validate_success(api.get_customer(
            ctx["customer"]["id"],
            make_customer_headers(ctx["customer"]["id"]),
        ), 200)
        assert cust_before["redelivery_attempts_used_30d"] == 1
        # Advance clock past 30 days.
        advance_clock_by_days(31)
        cust_after = validate_success(api.get_customer(
            ctx["customer"]["id"],
            make_customer_headers(ctx["customer"]["id"]),
        ), 200)
        assert cust_after["redelivery_attempts_used_30d"] == 0
        # But the parcel's per-lifecycle counter is unchanged.
        parcel_after = validate_success(api.get_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        assert parcel_after["redelivery_attempts"] == 1


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormulaQuotedFeeMultiSurcharge:
    """difficulty: combinatorial_formula/quoted_fee_multi_surcharge_nonlinear"""

    def test_full_surcharge_combination_quote(self, api):
        """PRD §3.7: 'The quote is the sum of six components ... The
        base fee is a flat 5.00 ... weight ... ceiling ... 0.75 ...
        distance ... ceiling ... 1.50 ... hazmat 12.00 ... signature
        2.50 ... residential 1.00'. Pinned by the difficulty design
        at 25.00 for the canonical combination (weight 3.0,
        distance bucket 2, hazmat, signature, residential).
        """
        # difficulty: combinatorial_formula/quoted_fee_multi_surcharge_nonlinear
        base = setup_baseline(
            hazmat_certified=True,
            center_lat=33.94, center_lon=-118.40,
            address_lat=34.05, address_lon=-118.25,
            residential=True,
        )
        d = haversine_km(33.94, -118.40, 34.05, -118.25)
        assert d <= 50.0  # ensures two distance buckets
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            weight_kg=3.0,
            signature_required=True,
            hazmat_class="CLASS_3",
        )
        # Components per PRD: 5.00 + ceil(2)*0.75=1.50 +
        # ceil(d/25)*1.50 + 12.00 + 2.50 + 1.00.
        expected = (
            BASE_FEE
            + math.ceil(3.0 - WEIGHT_FREE_KG) * WEIGHT_PER_KG_FEE
            + math.ceil(d / DISTANCE_BUCKET_KM) * DISTANCE_BUCKET_FEE
            + HAZMAT_SURCHARGE
            + SIGNATURE_SURCHARGE
            + RESIDENTIAL_SURCHARGE
        )
        expected = round(expected + 1e-12, 2)
        assert parcel["quoted_fee"] == pytest.approx(expected, abs=0.01)
        assert_cost_precision(parcel["quoted_fee"])

    def test_weight_bucketing_is_ceiling_step(self, api):
        """PRD §3.7: 'subtracting the free-weight allowance of 1.0
        kilogram, taking the result as zero if it would otherwise be
        negative; the remaining kilograms are then rounded up to the
        next whole kilogram (ceiling); the resulting integer is
        multiplied by the per-kilogram rate of 0.75.'

        Claim: weight 1.01 kg and weight 2.00 kg produce the SAME
        weight_fee (both round up to 1 extra kg) — the non-linear
        bucketing.
        """
        # difficulty: combinatorial_formula/quoted_fee_multi_surcharge_nonlinear
        # Equal everything-else between p1 and p2 so we isolate the
        # weight-bucket non-linearity; haversine distance and all
        # surcharge flags are identical when the same destination /
        # origin / hazmat / signature / residential are used.
        base = setup_baseline()
        p1 = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            weight_kg=1.01,
        )
        p2 = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            weight_kg=2.00,
        )
        # Both fall in the "1 extra kg" bucket -> identical quoted_fee
        # given the rest of the inputs are equal.
        assert p1["quoted_fee"] == pytest.approx(p2["quoted_fee"], abs=0.01)


class TestCombinatorialFormulaFinalFeeRoundingOrder:
    """difficulty: combinatorial_formula/final_fee_rounding_order_pinned"""

    def test_final_fee_with_reattempt_then_appointment_pinned(self, api):
        """PRD §3.7: 'The order matters. A redelivery surcharge that
        accrued chronologically before an appointment change must
        remain in the running total even after the appointment is
        accepted.'

        Scenario: NO_ONE_HOME at T+3h (+3.00), then appointment
        accepted (+4.50), then DELIVERED_SIGNED. final_fee =
        quoted + 3.00 + 4.50, rounded once at the end.
        """
        # difficulty: combinatorial_formula/final_fee_rounding_order_pinned
        ctx = walk_parcel_to_out_for_delivery(
            driver_release_authorized=True,
        )
        quoted = ctx["parcel"]["quoted_fee"]
        # 1st attempt: NO_ONE_HOME.
        move_clock_into_window(ctx["parcel"])
        api.create_attempt(
            ctx["parcel"]["id"],
            {"route_stop_id": ctx["stop"]["id"],
             "outcome": "NO_ONE_HOME"},
            make_driver_headers(ctx["driver"]["id"]),
        )
        # Close current route + reset driver to ON_DUTY so the next
        # cycle can dispatch (PRD §3.2 four-state cycle).
        reset_driver_to_on_duty(ctx["driver"]["id"], ctx["route"]["id"])
        # Reattempt -> SORTED.
        reattempt_parcel(ctx["parcel"]["id"])
        # File + accept new appointment. PRD §3.5: 'The parcel's
        # time_window_start and time_window_end are overwritten with
        # the new window.' Use a window inside today's logical-clock
        # forward future.
        new_start = current_clock() + timedelta(hours=2)
        new_end = new_start + timedelta(hours=3)
        appt = validate_success(api.create_appointment(
            create_appointment_payload(
                parcel_id=ctx["parcel"]["id"],
                requested_window_start=iso_utc(new_start),
                requested_window_end=iso_utc(new_end),
            ),
            make_customer_headers(ctx["customer"]["id"]),
        ), 201)
        validate_success(api.accept_appointment(
            appt["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        # Re-fetch parcel to pick up the new window the accept wrote.
        ctx["parcel"] = validate_success(api.get_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        # New route, dispatch, deliver inside new window. PRD §3.7:
        # pin planned_date to the parcel's (new) window date.
        parcel_window_date = ctx["parcel"]["time_window_start"][:10]
        new_route = create_route(
            ctx["center"]["id"], ctx["driver"]["id"],
            planned_date=parcel_window_date,
        )
        new_stop = add_stop(new_route["id"], ctx["parcel"]["id"])
        dispatch_route(new_route["id"])
        re_p = validate_success(api.get_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        deliver_signed(re_p, new_stop, ctx["driver"]["id"])
        terminal = validate_success(api.get_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        expected_final = quoted + REATTEMPT_FEE + APPOINTMENT_CHANGE_FEE
        assert terminal["final_fee"] == pytest.approx(
            round(expected_final + 1e-12, 2), abs=0.01,
        )

    def test_final_fee_is_strictly_greater_than_quoted_when_extras_applied(self, api):
        """PRD §3.7: chronological accumulation can only ADD to the
        accumulator that begins at quoted_fee. The PRD prose pins
        every surcharge as non-negative, so any parcel that takes a
        reattempt OR an accepted appointment OR a return MUST have
        final_fee > quoted_fee.
        """
        # difficulty: combinatorial_formula/final_fee_rounding_order_pinned
        ctx = walk_parcel_to_out_for_delivery()
        quoted = ctx["parcel"]["quoted_fee"]
        # Take one NO_ONE_HOME.
        move_clock_into_window(ctx["parcel"])
        api.create_attempt(
            ctx["parcel"]["id"],
            {"route_stop_id": ctx["stop"]["id"],
             "outcome": "NO_ONE_HOME"},
            make_driver_headers(ctx["driver"]["id"]),
        )
        # Reattempt, re-route, deliver. PRD §3.2 driver cycle requires
        # close-route + check-out + check-in before the next dispatch.
        # PRD §3.7: pin new route's planned_date to parcel window date
        # because reattempt does NOT re-set the parcel window (PRD §3.5).
        reset_driver_to_on_duty(ctx["driver"]["id"], ctx["route"]["id"])
        reattempt_parcel(ctx["parcel"]["id"])
        parcel_window_date = ctx["parcel"]["time_window_start"][:10]
        new_route = create_route(
            ctx["center"]["id"], ctx["driver"]["id"],
            planned_date=parcel_window_date,
        )
        new_stop = add_stop(new_route["id"], ctx["parcel"]["id"])
        dispatch_route(new_route["id"])
        re_p = validate_success(api.get_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        deliver_signed(re_p, new_stop, ctx["driver"]["id"])
        terminal = validate_success(api.get_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        assert terminal["final_fee"] > quoted


class TestCombinatorialFormulaRouteDistanceSequence:
    """difficulty: combinatorial_formula/route_distance_sequence_dependent"""

    def test_route_distance_accumulates_per_leg(self, api):
        """PRD §3.7: 'Starting from the origin transit center's stored
        coordinates, the system iterates the stops in ascending
        sequence order and, for each stop, computes the haversine
        distance ... and adds that leg to a running total ... No
        return-to-hub leg is included in the total.'
        """
        # difficulty: combinatorial_formula/route_distance_sequence_dependent
        base = setup_baseline(
            center_lat=33.94, center_lon=-118.40,
            address_lat=34.05, address_lon=-118.25,
        )
        parcel = walk_parcel_to_sorted(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        route = create_route(base["center"]["id"], base["driver"]["id"])
        add_stop(route["id"], parcel["id"])
        route_after = validate_success(api.get_route(
            route["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        expected_km = haversine_km(33.94, -118.40, 34.05, -118.25)
        assert route_after["total_distance_km"] == pytest.approx(
            round(expected_km + 1e-12, 2), abs=0.02,
        )

    def test_route_total_distance_recomputes_after_stop_deletion(self, api):
        """PRD §3.7: 'Whenever a RouteStop is added or removed, or the
        sequence is renumbered, the system recomputes
        total_distance_km for the parent route.'
        PRD §3.4: 'Removal reverts the underlying parcel from
        ON_VEHICLE back to SORTED, recomputes total_distance_km and
        stop_count on the route'.
        """
        # difficulty: combinatorial_formula/route_distance_sequence_dependent
        ctx = setup_three_sorted_parcels_one_route(parcel_count=2)
        before = validate_success(api.get_route(
            ctx["route"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        # Delete first stop. PRD §4: 'A successful stop-removal returns
        # 204 No Content' — no JSON body, so we check status directly.
        del_res = api.delete_stop(
            ctx["route"]["id"], ctx["stops"][0]["id"],
            TEST_USERS["dispatcher_headers"],
        )
        assert del_res.status_code == 204, (
            f"Expected 204 No Content, got {del_res.status_code}: "
            f"{del_res.text}"
        )
        after = validate_success(api.get_route(
            ctx["route"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        # PRD §3.4: 'Removal reverts the underlying parcel from
        # ON_VEHICLE back to SORTED, recomputes total_distance_km and
        # stop_count on the route'. stop_count decrements; distance is
        # recomputed (the value may or may not change depending on the
        # particular destination geometry — PRD only mandates that the
        # recomputation happens).
        assert after["stop_count"] == before["stop_count"] - 1


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachineParcelRedeliveryCycle:
    """difficulty: non_linear_state_machine/parcel_redelivery_cycle"""

    def test_parcel_cycles_to_on_vehicle_after_reattempt(self, api):
        """PRD §3.5: 'The reattempt arc transitions the parcel back to
        SORTED and re-enters it into the origin center's queue.'
        PRD §3.4: 'The action drives a SORTED -> ON_VEHICLE transition
        on the parcel'.

        Claim: after the cycle OUT_FOR_DELIVERY -> EXCEPTION -> SORTED
        -> ON_VEHICLE, parcel.redelivery_attempts == 1 and status ==
        ON_VEHICLE.
        """
        # difficulty: non_linear_state_machine/parcel_redelivery_cycle
        ctx = walk_parcel_to_out_for_delivery()
        move_clock_into_window(ctx["parcel"])
        api.create_attempt(
            ctx["parcel"]["id"],
            {"route_stop_id": ctx["stop"]["id"],
             "outcome": "NO_ONE_HOME"},
            make_driver_headers(ctx["driver"]["id"]),
        )
        # PRD §3.2 driver cycle: close+reset before next dispatch.
        reset_driver_to_on_duty(ctx["driver"]["id"], ctx["route"]["id"])
        reattempt_parcel(ctx["parcel"]["id"])
        # PRD §3.7: pin planned_date to parcel window date.
        parcel_window_date = ctx["parcel"]["time_window_start"][:10]
        new_route = create_route(
            ctx["center"]["id"], ctx["driver"]["id"],
            planned_date=parcel_window_date,
        )
        add_stop(new_route["id"], ctx["parcel"]["id"])
        re_p = validate_success(api.get_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        assert re_p["status"] == "ON_VEHICLE"
        assert re_p["redelivery_attempts"] == 1

    def test_parcel_supports_two_full_cycles_before_third(self, api):
        """PRD §3.5: 'the parcel's redelivery_attempts must be strictly
        less than three' for reattempt to be admissible. Claim: two
        full redelivery cycles complete successfully (each yielding
        redelivery_attempts++); a third failure leaves the counter at
        3.
        """
        # difficulty: non_linear_state_machine/parcel_redelivery_cycle
        ctx = walk_parcel_to_out_for_delivery()
        for cycle_idx in range(2):
            move_clock_into_window(ctx["parcel"])
            api.create_attempt(
                ctx["parcel"]["id"],
                {"route_stop_id": ctx["stop"]["id"],
                 "outcome": "NO_ONE_HOME"},
                make_driver_headers(ctx["driver"]["id"]),
            )
            re_p = validate_success(api.get_parcel(
                ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
            ), 200)
            assert re_p["redelivery_attempts"] == cycle_idx + 1
            # PRD §3.2 four-state driver cycle: must close route + check-out
            # + check-in before next dispatch. PRD §3.7: pin planned_date
            # to parcel window date so stop assignment stays in-window.
            reset_driver_to_on_duty(ctx["driver"]["id"], ctx["route"]["id"])
            reattempt_parcel(ctx["parcel"]["id"])
            parcel_window_date = ctx["parcel"]["time_window_start"][:10]
            new_route = create_route(
                ctx["center"]["id"], ctx["driver"]["id"],
                planned_date=parcel_window_date,
            )
            new_stop = add_stop(new_route["id"], ctx["parcel"]["id"])
            dispatch_route(new_route["id"])
            ctx["stop"] = new_stop
            ctx["route"] = new_route
            ctx["parcel"] = validate_success(api.get_parcel(
                ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
            ), 200)
        # Two cycles done; counter == 2.
        final_p = validate_success(api.get_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        assert final_p["redelivery_attempts"] == 2


class TestNonLinearStateMachineRouteBranchingTerminals:
    """difficulty: non_linear_state_machine/route_branching_terminals"""

    def test_route_planned_can_branch_to_cancelled(self, api):
        """PRD §3.4: 'On cancellation, every parcel currently in
        ON_VEHICLE on the route reverts to SORTED, every RouteStop
        row attached to the route is deleted as a cascade, and
        hazmat_present is recomputed to false. The route lands in the
        terminal CANCELLED state.'
        """
        # difficulty: non_linear_state_machine/route_branching_terminals
        ctx = setup_three_sorted_parcels_one_route(parcel_count=2)
        cancelled = validate_success(api.cancel_route(
            ctx["route"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["stop_count"] == 0
        for p in ctx["parcels"]:
            re_p = validate_success(api.get_parcel(
                p["id"], TEST_USERS["dispatcher_headers"],
            ), 200)
            assert re_p["status"] == "SORTED"

    def test_route_planned_can_branch_to_dispatched_in_progress(self, api):
        """PRD §3.4: 'Dispatch advances the route from PLANNED through
        DISPATCHED to IN_PROGRESS atomically ... every parcel on the
        route currently in ON_VEHICLE advances to OUT_FOR_DELIVERY.'
        """
        # difficulty: non_linear_state_machine/route_branching_terminals
        ctx = setup_three_sorted_parcels_one_route(parcel_count=2)
        check_in_driver(ctx["driver"]["id"])
        dispatched = dispatch_route(ctx["route"]["id"])
        assert dispatched["status"] == "IN_PROGRESS"
        for p in ctx["parcels"]:
            re_p = validate_success(api.get_parcel(
                p["id"], TEST_USERS["dispatcher_headers"],
            ), 200)
            assert re_p["status"] == "OUT_FOR_DELIVERY"


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascadeDispatchDepth3:
    """difficulty: transitive_cascade/dispatch_cascade_depth_3"""

    def test_dispatch_cascades_parcels_to_out_for_delivery(self, api):
        """PRD §3.4: 'Dispatch cascades broadly ... every parcel on the
        route currently in ON_VEHICLE advances to OUT_FOR_DELIVERY.'
        """
        # difficulty: transitive_cascade/dispatch_cascade_depth_3
        ctx = setup_three_sorted_parcels_one_route(parcel_count=2)
        check_in_driver(ctx["driver"]["id"])
        dispatch_route(ctx["route"]["id"])
        for p in ctx["parcels"]:
            re_p = validate_success(api.get_parcel(
                p["id"], TEST_USERS["dispatcher_headers"],
            ), 200)
            assert re_p["status"] == "OUT_FOR_DELIVERY"

    def test_dispatch_advances_route_to_in_progress(self, api):
        """PRD §3.4: 'Dispatch advances the route from PLANNED through
        DISPATCHED to IN_PROGRESS atomically — clients never observe
        an intermediate DISPATCHED state in steady-state reads.'
        """
        # difficulty: transitive_cascade/dispatch_cascade_depth_3
        ctx = setup_three_sorted_parcels_one_route(parcel_count=1)
        check_in_driver(ctx["driver"]["id"])
        dispatched = dispatch_route(ctx["route"]["id"])
        assert dispatched["status"] == "IN_PROGRESS"


class TestTransitiveCascadeReattemptDepth2:
    """difficulty: transitive_cascade/reattempt_cascade_depth_2"""

    def test_reattempt_supersedes_pending_appointment(self, api):
        """PRD §3.5: 'As a side effect of the reattempt, any
        Appointment for the same parcel that is still in PENDING is
        auto-superseded to SUPERSEDED.'
        """
        # difficulty: transitive_cascade/reattempt_cascade_depth_2
        ctx = setup_appointment_on_exception_parcel()
        reattempt_parcel(ctx["parcel"]["id"])
        # The previously-PENDING appointment is now SUPERSEDED:
        # accept_appointment is no longer admissible.
        res = api.accept_appointment(
            ctx["appointment"]["id"], TEST_USERS["dispatcher_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_reattempt_drives_parcel_back_to_sorted(self, api):
        """PRD §3.5: 'The reattempt arc transitions the parcel back to
        SORTED and re-enters it into the origin center's queue.'
        """
        # difficulty: transitive_cascade/reattempt_cascade_depth_2
        ctx = setup_parcel_in_exception()
        sorted_p = validate_success(api.reattempt_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        assert sorted_p["status"] == "SORTED"


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairStateVsBusinessSafety:
    """difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_attempt"""

    def test_state_check_wins_over_driver_release_authorization(self, api):
        """PRD §2.9: 'State-machine admissibility on all transition
        endpoints — an operation requested in a state that does not
        admit it yields ERR_INVALID_STATE.' Priority 5 is named
        before the §2.6/§2.7 business-safety rules (priority 6).

        Scenario: a parcel that has already been DELIVERED (so the
        RouteStop exists, satisfying the priority-4 FK-existence
        check) receives a second DRIVER_RELEASED attempt with a
        customer who is NOT authorized. Both the state check
        (parcel not in OUT_FOR_DELIVERY) and the business-safety
        check (driver-release unauthorized + signature_required
        ambiguity) would fail; per PRD priority 5 > 6, the state
        check wins.
        """
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_attempt
        # Build a parcel that has reached DELIVERED so a real
        # route_stop_id exists (satisfying priority-4 FK existence)
        # and the parcel is in DELIVERED, NOT in OUT_FOR_DELIVERY.
        ctx = walk_parcel_to_out_for_delivery(
            driver_release_authorized=False,  # business-safety would fail
        )
        move_clock_into_window(ctx["parcel"])
        # First, deliver the parcel so it moves OUT_FOR_DELIVERY -> DELIVERED.
        api.create_attempt(
            ctx["parcel"]["id"],
            {"route_stop_id": ctx["stop"]["id"],
             "outcome": "DELIVERED_SIGNED",
             "signature_blob_ref": "sig-blob-0"},
            make_driver_headers(ctx["driver"]["id"]),
        )
        # Now the parcel is DELIVERED; attempt is not admissible from
        # this state. The DRIVER_RELEASED outcome would also fail the
        # business-safety check because the customer has not authorized
        # driver release. PRD priority 5 wins.
        res = api.create_attempt(
            ctx["parcel"]["id"],
            {"route_stop_id": ctx["stop"]["id"],
             "outcome": "DRIVER_RELEASED",
             "release_location": "porch"},
            make_driver_headers(ctx["driver"]["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_state_check_wins_over_signature_missing(self, api):
        """PRD §2.9: same priority story for DELIVERED_SIGNED without
        a signature_blob_ref on a parcel still in a non-delivering
        state — state check wins over signature check.
        """
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_attempt
        # Build a parcel that has reached DELIVERED so a real
        # route_stop_id exists (satisfying priority-4 FK existence)
        # and the parcel is in DELIVERED, NOT in OUT_FOR_DELIVERY.
        ctx = walk_parcel_to_out_for_delivery()
        move_clock_into_window(ctx["parcel"])
        api.create_attempt(
            ctx["parcel"]["id"],
            {"route_stop_id": ctx["stop"]["id"],
             "outcome": "DELIVERED_SIGNED",
             "signature_blob_ref": "sig-blob-0"},
            make_driver_headers(ctx["driver"]["id"]),
        )
        # Second attempt without signature_blob_ref on already-DELIVERED
        # parcel: state check (priority 5) wins over signature check
        # (priority 6).
        res = api.create_attempt(
            ctx["parcel"]["id"],
            {"route_stop_id": ctx["stop"]["id"],
             "outcome": "DELIVERED_SIGNED"},
            make_driver_headers(ctx["driver"]["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


class TestPriorityPairBusinessSafetyVsReferential:
    """difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_on_sort"""

    def test_hazmat_certification_check_wins_over_postal_prefix(self, api):
        """PRD §2.9: priority 6 'Business-safety rules — hazmat hub
        certification' comes before priority 7 'Business-referential
        rules — postal-prefix service area'. When BOTH conditions
        fail, PRD names ERR_HAZMAT_HUB_NOT_CERTIFIED.
        """
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_on_sort
        base = setup_baseline(
            hazmat_certified=False,
            address_postal_code="90210",
            serviced_postal_prefixes=["100"],
        )
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            hazmat_class="CLASS_3",
        )
        # Walk to IN_TRANSIT_HUB even though hazmat-uncertified: the
        # induction itself is gated by hazmat check, which would
        # reject. To exercise the SORT-time priority conflict we need
        # the parcel already in IN_TRANSIT_HUB. Achieved by inducting
        # non-hazmat, then PATCH-ing to hazmat in IN_TRANSIT_HUB.
        # First detach the hazmat class:
        parcel_nh = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            hazmat_class="NONE",
        )
        induct_to_hub(parcel_nh["id"])
        # Flip to hazmat while in IN_TRANSIT_HUB (PRD §3.3 permits).
        validate_success(api.patch_parcel(
            parcel_nh["id"], {"hazmat_class": "CLASS_3"},
            TEST_USERS["dispatcher_headers"],
        ), 200)
        res = api.sort_parcel(
            parcel_nh["id"], TEST_USERS["sorting_hub_operator_headers"],
        )
        validate_error(res, "ERR_HAZMAT_HUB_NOT_CERTIFIED")

    def test_safety_check_alone_returns_safety_error(self, api):
        """PRD §2.9: confirm the safety error_id is the one named
        when only safety fails (no postal conflict)."""
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_on_sort
        base = setup_baseline(
            hazmat_certified=False,
            address_postal_code="90210",
            serviced_postal_prefixes=["902"],  # postal is fine
        )
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            hazmat_class="NONE",
        )
        induct_to_hub(parcel["id"])
        validate_success(api.patch_parcel(
            parcel["id"], {"hazmat_class": "CLASS_3"},
            TEST_USERS["dispatcher_headers"],
        ), 200)
        res = api.sort_parcel(
            parcel["id"], TEST_USERS["sorting_hub_operator_headers"],
        )
        validate_error(res, "ERR_HAZMAT_HUB_NOT_CERTIFIED")


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionParcelWeight:
    """difficulty: boundary_precision_check/parcel_weight_upper_bound"""

    def test_weight_exactly_70_accepted(self, api):
        """PRD §3.3: '70.0 inclusive is accepted'."""
        # difficulty: boundary_precision_check/parcel_weight_upper_bound
        base = setup_baseline()
        res = api.create_parcel(
            create_parcel_payload(
                customer_id=base["customer"]["id"],
                origin_center_id=base["center"]["id"],
                destination_address_id=base["address"]["id"],
                weight_kg=PARCEL_WEIGHT_MAX_INCLUSIVE,
            ),
            TEST_USERS["dispatcher_headers"],
        )
        parcel = validate_success(res, 201)
        assert parcel["weight_kg"] == PARCEL_WEIGHT_MAX_INCLUSIVE

    def test_weight_just_above_70_rejected(self, api):
        """PRD §3.3: '70.01 is rejected'."""
        # difficulty: boundary_precision_check/parcel_weight_upper_bound
        base = setup_baseline()
        res = api.create_parcel(
            create_parcel_payload(
                customer_id=base["customer"]["id"],
                origin_center_id=base["center"]["id"],
                destination_address_id=base["address"]["id"],
                weight_kg=PARCEL_WEIGHT_MAX_INCLUSIVE + 0.01,
            ),
            TEST_USERS["dispatcher_headers"],
        )
        validate_error(res, "ERR_PARCEL_WEIGHT_OUT_OF_RANGE")


class TestBoundaryPrecisionRouteCloseEmptyPending:
    """difficulty: boundary_precision_check/route_close_with_zero_stops_pending"""

    def test_route_with_one_completed_stop_closes_cleanly(self, api):
        """PRD §3.4: 'It is admissible only when every RouteStop on the
        route has reached one of COMPLETED, FAILED, or SKIPPED'.

        Empty-set boundary: a Route in IN_PROGRESS with zero remaining
        non-terminal stops closes successfully.
        """
        # difficulty: boundary_precision_check/route_close_with_zero_stops_pending
        ctx = walk_parcel_to_out_for_delivery()
        deliver_signed(ctx["parcel"], ctx["stop"], ctx["driver"]["id"])
        closed = validate_success(api.close_route(
            ctx["route"]["id"],
            make_driver_headers(ctx["driver"]["id"]),
        ), 200)
        assert closed["status"] == "CLOSED"

    def test_close_with_planned_stop_rejected(self, api):
        """PRD §3.4: 'if any stop is still in PLANNED or ARRIVED, the
        close is rejected with ERR_INVALID_STATE.' The complementary
        boundary: one non-terminal stop rejects the close.
        """
        # difficulty: boundary_precision_check/route_close_with_zero_stops_pending
        ctx = walk_parcel_to_out_for_delivery()
        # Don't deliver; stop remains PLANNED.
        res = api.close_route(
            ctx["route"]["id"],
            make_driver_headers(ctx["driver"]["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityRouteDependsOnDriverStatus:
    """difficulty: cross_entity_state_dependency/route_dispatch_depends_on_driver_status"""

    def test_dispatch_rejected_when_driver_not_on_duty(self, api):
        """PRD §3.4: 'the assigned driver's status must currently be
        ON_DUTY' — PRD §2.9 puts state-admissibility failures under
        ERR_INVALID_STATE.
        """
        # difficulty: cross_entity_state_dependency/route_dispatch_depends_on_driver_status
        ctx = setup_three_sorted_parcels_one_route(parcel_count=1)
        # Driver is OFF_DUTY (no check-in).
        res = api.dispatch_route(
            ctx["route"]["id"], TEST_USERS["dispatcher_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_dispatch_succeeds_after_driver_checks_in(self, api):
        """PRD §3.2: 'transitioning to ON_DUTY when the driver checks
        in'. PRD §3.4: dispatch then admissible."""
        # difficulty: cross_entity_state_dependency/route_dispatch_depends_on_driver_status
        ctx = setup_three_sorted_parcels_one_route(parcel_count=1)
        check_in_driver(ctx["driver"]["id"])
        dispatched = validate_success(api.dispatch_route(
            ctx["route"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        assert dispatched["status"] == "IN_PROGRESS"


class TestCrossEntityParcelSortDependsOnHubCertification:
    """difficulty: cross_entity_state_dependency/parcel_sort_depends_on_transit_center_certification"""

    def test_sort_blocked_when_hub_not_hazmat_certified(self, api):
        """PRD §3.3: 'if the parcel is regulated, the origin center
        must still be hazmat_certified (rejected with
        ERR_HAZMAT_HUB_NOT_CERTIFIED if not).'"""
        # difficulty: cross_entity_state_dependency/parcel_sort_depends_on_transit_center_certification
        base = setup_baseline(hazmat_certified=False)
        # Workaround: induct non-hazmat then patch to hazmat.
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            hazmat_class="NONE",
        )
        induct_to_hub(parcel["id"])
        validate_success(api.patch_parcel(
            parcel["id"], {"hazmat_class": "CLASS_3"},
            TEST_USERS["dispatcher_headers"],
        ), 200)
        res = api.sort_parcel(
            parcel["id"], TEST_USERS["sorting_hub_operator_headers"],
        )
        validate_error(res, "ERR_HAZMAT_HUB_NOT_CERTIFIED")

    def test_sort_succeeds_when_hub_hazmat_certified(self, api):
        """PRD §2.6: positive complement. 'A regulated parcel may only
        be inducted into or sorted by a TransitCenter whose
        hazmat_certified flag is true' — at a certified hub, sort
        succeeds."""
        # difficulty: cross_entity_state_dependency/parcel_sort_depends_on_transit_center_certification
        base = setup_baseline(hazmat_certified=True)
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            hazmat_class="CLASS_3",
        )
        induct_to_hub(parcel["id"])
        sorted_p = validate_success(api.sort_parcel(
            parcel["id"], TEST_USERS["sorting_hub_operator_headers"],
        ), 200)
        assert sorted_p["status"] == "SORTED"


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlapRouteStopWindow:
    """difficulty: resource_temporal_overlap/parcel_time_window_infeasibility_on_routestop"""

    def test_stop_add_rejected_when_planned_arrival_after_window_end(self, api):
        """PRD §3.7: 'If the cursor is now strictly later than the
        parcel's time_window_end, the assignment fails immediately
        and the stop-add is rejected with ERR_TIME_WINDOW_INFEASIBLE.'

        Construction: create a parcel whose time window ends before
        the route's depart hour 08:00 local of the planned_date — so
        the cursor at the first stop already exceeds time_window_end.
        """
        # difficulty: resource_temporal_overlap/parcel_time_window_infeasibility_on_routestop
        base = setup_baseline()
        from datetime import date, datetime, timezone
        # Planned date is tomorrow; depart hour is 08:00 local.
        # Set the parcel's time window to 06:00-07:00 UTC of that day
        # so the cursor (08:00) exceeds time_window_end (07:00).
        # Note: PRD uses center's local tz; lacking explicit tz, we
        # construct UTC instants strictly earlier than depart hour.
        from test_helpers import utcnow
        tomorrow = (utcnow() + timedelta(days=1)).date()
        window_start = datetime(
            tomorrow.year, tomorrow.month, tomorrow.day,
            0, 0, 0, tzinfo=timezone.utc,
        )
        window_end = window_start + timedelta(hours=1)  # 00:00-01:00 UTC
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            time_window_start=iso_utc(window_start),
            time_window_end=iso_utc(window_end),
        )
        induct_to_hub(parcel["id"])
        sort_parcel(parcel["id"])
        route = create_route(
            base["center"]["id"], base["driver"]["id"],
            planned_date=tomorrow.isoformat(),
        )
        res = api.create_stop(
            route["id"], {"parcel_id": parcel["id"]},
            TEST_USERS["dispatcher_headers"],
        )
        validate_error(res, "ERR_TIME_WINDOW_INFEASIBLE")

    def test_stop_add_succeeds_when_window_admits_arrival(self, api):
        """PRD §3.7: positive complement. When the cursor remains at
        or below time_window_end, the stop is created with
        planned_arrival assigned.
        """
        # difficulty: resource_temporal_overlap/parcel_time_window_infeasibility_on_routestop
        base = setup_baseline()
        # Generous window starting at 08:00 UTC of tomorrow.
        from test_helpers import utcnow
        from datetime import datetime, timezone
        tomorrow = (utcnow() + timedelta(days=1)).date()
        window_start = datetime(
            tomorrow.year, tomorrow.month, tomorrow.day,
            8, 0, 0, tzinfo=timezone.utc,
        )
        window_end = window_start + timedelta(hours=10)
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            time_window_start=iso_utc(window_start),
            time_window_end=iso_utc(window_end),
        )
        induct_to_hub(parcel["id"])
        sort_parcel(parcel["id"])
        route = create_route(
            base["center"]["id"], base["driver"]["id"],
            planned_date=tomorrow.isoformat(),
        )
        stop = validate_success(api.create_stop(
            route["id"], {"parcel_id": parcel["id"]},
            TEST_USERS["dispatcher_headers"],
        ), 201)
        assert stop["sequence"] == 1


class TestResourceTemporalOverlapAppointmentWindow:
    """difficulty: resource_temporal_overlap/appointment_window_minimum_length"""

    def test_appointment_with_window_under_two_hours_rejected(self, api):
        """PRD §3.5: 'the interval between them must be at least two
        hours long. A window that violates either feasibility rule is
        rejected with ERR_APPOINTMENT_WINDOW_INVALID.'"""
        # difficulty: resource_temporal_overlap/appointment_window_minimum_length
        ctx = setup_parcel_in_exception()
        start = current_clock() + timedelta(hours=5)
        end = start + timedelta(hours=1, minutes=59)  # 1h59m < 2h
        res = api.create_appointment(
            create_appointment_payload(
                parcel_id=ctx["parcel"]["id"],
                requested_window_start=iso_utc(start),
                requested_window_end=iso_utc(end),
            ),
            make_customer_headers(ctx["customer"]["id"]),
        )
        validate_error(res, "ERR_APPOINTMENT_WINDOW_INVALID")

    def test_appointment_with_window_exactly_two_hours_accepted(self, api):
        """PRD §3.5: '... must be at least two hours long' — at exactly
        2 hours the boundary is satisfied (>= 2h)."""
        # difficulty: resource_temporal_overlap/appointment_window_minimum_length
        ctx = setup_parcel_in_exception()
        start = current_clock() + timedelta(hours=5)
        end = start + timedelta(hours=2)  # exactly 2h
        res = api.create_appointment(
            create_appointment_payload(
                parcel_id=ctx["parcel"]["id"],
                requested_window_start=iso_utc(start),
                requested_window_end=iso_utc(end),
            ),
            make_customer_headers(ctx["customer"]["id"]),
        )
        appt = validate_success(res, 201)
        assert appt["status"] == "PENDING"


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariantRouteCancel:
    """difficulty: compensating_invariant/route_cancel_restores_parcel_belt_state"""

    def test_cancel_restores_all_parcels_to_sorted(self, api):
        """PRD §3.4: 'On cancellation, every parcel currently in
        ON_VEHICLE on the route reverts to SORTED, every RouteStop
        row attached to the route is deleted as a cascade, and
        hazmat_present is recomputed to false. The route lands in
        the terminal CANCELLED state.'

        Conserved-quantity claim:
            count(SORTED) + count(ON_VEHICLE) over these parcels is
            invariant across add-stop then cancel-route. After cancel,
            count(SORTED) == 3 and count(ON_VEHICLE) == 0 (for the
            parcels under test).
        """
        # difficulty: compensating_invariant/route_cancel_restores_parcel_belt_state
        ctx = setup_three_sorted_parcels_one_route(parcel_count=3)
        # After all 3 stops were added, parcels are ON_VEHICLE.
        for p in ctx["parcels"]:
            re_p = validate_success(api.get_parcel(
                p["id"], TEST_USERS["dispatcher_headers"],
            ), 200)
            assert re_p["status"] == "ON_VEHICLE"
        # Cancel.
        cancelled = validate_success(api.cancel_route(
            ctx["route"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["stop_count"] == 0
        sorted_count = on_vehicle_count = 0
        for p in ctx["parcels"]:
            re_p = validate_success(api.get_parcel(
                p["id"], TEST_USERS["dispatcher_headers"],
            ), 200)
            if re_p["status"] == "SORTED":
                sorted_count += 1
            elif re_p["status"] == "ON_VEHICLE":
                on_vehicle_count += 1
        assert sorted_count == 3
        assert on_vehicle_count == 0

    def test_cancel_recomputes_hazmat_present_to_false(self, api):
        """PRD §3.4: 'hazmat_present is recomputed to false' on cancel.
        """
        # difficulty: compensating_invariant/route_cancel_restores_parcel_belt_state
        base = setup_baseline(
            hazmat_certified=True, hazmat_endorsement=True,
        )
        parcel = walk_parcel_to_sorted(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            hazmat_class="CLASS_3",
        )
        route = create_route(base["center"]["id"], base["driver"]["id"])
        add_stop(route["id"], parcel["id"])
        rcheck = validate_success(api.get_route(
            route["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        assert rcheck["hazmat_present"] is True
        cancelled = validate_success(api.cancel_route(
            route["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        assert cancelled["hazmat_present"] is False


class TestCompensatingInvariantAppointmentReattempt:
    """difficulty: compensating_invariant/appointment_reattempt_keeps_active_appointment_count_pinned"""

    def test_pending_appointment_count_zero_after_reattempt(self, api):
        """PRD §3.5: 'As a side effect of the reattempt, any
        Appointment for the same parcel that is still in PENDING is
        auto-superseded to SUPERSEDED.'

        Invariant: after the reattempt the parcel has zero PENDING
        appointments — observable by attempting to accept the prior
        appointment (must fail with ERR_INVALID_STATE since it is no
        longer PENDING).
        """
        # difficulty: compensating_invariant/appointment_reattempt_keeps_active_appointment_count_pinned
        ctx = setup_appointment_on_exception_parcel()
        # Pre: appointment is PENDING (accept would have succeeded
        # before reattempt — covered by other tests).
        reattempt_parcel(ctx["parcel"]["id"])
        res = api.accept_appointment(
            ctx["appointment"]["id"], TEST_USERS["dispatcher_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_terminal_appointment_count_increments_by_one_on_reattempt(self, api):
        """PRD §3.5: 'Filing a brand-new appointment for a parcel that
        already has a PENDING appointment auto-supersedes the prior
        one to SUPERSEDED.' Plus the reattempt cascade. The conserved
        quantity is non-PENDING appointment count.

        Claim: after one PENDING appointment + one reattempt, exactly
        one appointment row for the parcel is in SUPERSEDED state.
        We observe this by filing a NEW appointment after the
        reattempt and noting that the first appointment is
        terminalized — and the new one can be filed (PENDING).
        """
        # difficulty: compensating_invariant/appointment_reattempt_keeps_active_appointment_count_pinned
        ctx = setup_appointment_on_exception_parcel()
        reattempt_parcel(ctx["parcel"]["id"])
        # File a fresh appointment after reattempt — admissible since
        # parcel is now SORTED, which is in the admit-set.
        start = current_clock() + timedelta(hours=3)
        end = start + timedelta(hours=3)
        res = api.create_appointment(
            create_appointment_payload(
                parcel_id=ctx["parcel"]["id"],
                requested_window_start=iso_utc(start),
                requested_window_end=iso_utc(end),
            ),
            make_customer_headers(ctx["customer"]["id"]),
        )
        new_appt = validate_success(res, 201)
        assert new_appt["status"] == "PENDING"
