"""Calculations: forward-looking quoted_fee, chronological final_fee,
route_total_distance, planned_arrival_assignment, and the
customer rolling-30-day count.

All formulas come from PRD §3.7 with constants pinned in §3.7 itself.
Precision (PRD §2.8): all monetary values 2 decimal places, distances
2 decimal places, half-up rounding applied once at the end.
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
    REATTEMPT_FEE,
    RESIDENTIAL_SURCHARGE,
    RETURN_TO_SENDER_FEE,
    SIGNATURE_SURCHARGE,
    TEST_USERS,
    WEIGHT_FREE_KG,
    WEIGHT_PER_KG_FEE,
    add_stop,
    api_client,
    assert_cost_precision,
    create_appointment_payload,
    create_parcel,
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
    record_attempt,
    reset_driver_to_on_duty,
    return_to_sender,
    setup_baseline,
    sort_parcel,
    validate_error,
    validate_success,
    walk_parcel_to_out_for_delivery,
    walk_parcel_to_sorted,
)


def _expected_quote(
    weight_kg: float, distance_km: float,
    hazmat: bool, signature: bool, residential: bool,
) -> float:
    """Reproduce the PRD §3.7 forward-looking quote formula in full
    precision, rounded once at the end half-up to 2 decimals."""
    base_fee = BASE_FEE
    weight_extra = max(0.0, weight_kg - WEIGHT_FREE_KG)
    weight_fee = math.ceil(weight_extra) * WEIGHT_PER_KG_FEE
    distance_fee = (math.ceil(distance_km / DISTANCE_BUCKET_KM)
                    * DISTANCE_BUCKET_FEE)
    hazmat_fee = HAZMAT_SURCHARGE if hazmat else 0.0
    signature_fee = SIGNATURE_SURCHARGE if signature else 0.0
    residential_fee = RESIDENTIAL_SURCHARGE if residential else 0.0
    raw = (base_fee + weight_fee + distance_fee
           + hazmat_fee + signature_fee + residential_fee)
    # PRD §2.8 'round half up' applied once at the end.
    return float(round(raw + 1e-12, 2))


# ---------------------------------------------------------------------------
# Forward-looking quoted_fee — PRD §3.7
# ---------------------------------------------------------------------------
class TestQuotedFeeFormula:

    def test_basic_quoted_fee_residential_only(self, api):
        """PRD §3.7: 'The base fee is a flat 5.00. ... The residential
        surcharge of 1.00 is added if and only if the destination
        address's residential flag is true.'"""
        base = setup_baseline(
            center_lat=33.94, center_lon=-118.40,
            address_lat=34.05, address_lon=-118.25,
            residential=True,
        )
        d = haversine_km(33.94, -118.40, 34.05, -118.25)
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            weight_kg=3.0,
            signature_required=False,
            hazmat_class="NONE",
        )
        expected = _expected_quote(
            weight_kg=3.0, distance_km=d,
            hazmat=False, signature=False, residential=True,
        )
        assert parcel["quoted_fee"] == pytest.approx(expected, abs=0.01)
        assert_cost_precision(parcel["quoted_fee"])

    def test_quoted_fee_with_hazmat_signature_residential(self, api):
        """PRD §3.7: 'The hazmat surcharge of 12.00 is added if and
        only if the parcel's hazmat_class is anything other than NONE.
        The signature surcharge of 2.50 is added if and only if
        signature_required is true.'"""
        base = setup_baseline(
            hazmat_certified=True,
            center_lat=33.94, center_lon=-118.40,
            address_lat=34.05, address_lon=-118.25,
            residential=True,
        )
        d = haversine_km(33.94, -118.40, 34.05, -118.25)
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            weight_kg=3.0,
            signature_required=True,
            hazmat_class="CLASS_3",
        )
        expected = _expected_quote(
            weight_kg=3.0, distance_km=d,
            hazmat=True, signature=True, residential=True,
        )
        assert parcel["quoted_fee"] == pytest.approx(expected, abs=0.01)

    def test_quoted_fee_recomputed_on_induct_to_hub(self, api):
        """PRD §3.3: 'On success, the origin center's parcels_on_belt
        counter is incremented and the parcel's quoted_fee is
        recomputed.'"""
        base = setup_baseline()
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        before_quote = parcel["quoted_fee"]
        in_hub = validate_success(api.induct_parcel_to_hub(
            parcel["id"], TEST_USERS["sorting_hub_operator_headers"],
        ), 200)
        # No inputs changed -> quoted_fee stable.
        assert in_hub["quoted_fee"] == pytest.approx(before_quote, abs=0.01)
        assert_cost_precision(in_hub["quoted_fee"])

    def test_patch_weight_recomputes_quoted_fee(self, api):
        """PRD §3.7: 'A quote is computed every time ... the controlled
        update path mutates weight_kg ... while the parcel is still
        in INDUCTED or IN_TRANSIT_HUB.'"""
        base = setup_baseline()
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            weight_kg=1.0,
        )
        before = parcel["quoted_fee"]
        # Push weight to a higher bucket.
        updated = validate_success(api.patch_parcel(
            parcel["id"], {"weight_kg": 5.0},
            TEST_USERS["dispatcher_headers"],
        ), 200)
        # Going from 1.0 to 5.0 adds ceil(4)*0.75 = 3.00 worth of
        # weight_fee. Allow exact-up-to-2dp comparison.
        assert updated["quoted_fee"] == pytest.approx(
            before + 3.00, abs=0.01,
        )

    def test_patch_after_sort_rejected_invalid_state(self, api):
        """PRD §3.3: 'Once the parcel has advanced past IN_TRANSIT_HUB,
        this edit path is no longer admissible and the request is
        rejected with ERR_INVALID_STATE.'"""
        base = setup_baseline()
        parcel = walk_parcel_to_sorted(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        res = api.patch_parcel(
            parcel["id"], {"weight_kg": 5.0},
            TEST_USERS["dispatcher_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")


# ---------------------------------------------------------------------------
# Chronological final_fee — PRD §3.7
# ---------------------------------------------------------------------------
class TestFinalFeeFormula:

    def test_final_fee_success_path_no_reattempts(self, api):
        """PRD §3.7: 'The accumulator begins at quoted_fee. The system
        then iterates the parcel's DeliveryAttempt rows in ascending
        attempted_at order'. With one DELIVERED_SIGNED attempt,
        final_fee == quoted_fee."""
        ctx = walk_parcel_to_out_for_delivery()
        quoted = ctx["parcel"]["quoted_fee"]
        deliver_signed(ctx["parcel"], ctx["stop"], ctx["driver"]["id"])
        parcel_after = validate_success(api.get_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        assert parcel_after["status"] == "DELIVERED"
        assert parcel_after["final_fee"] == pytest.approx(quoted, abs=0.01)
        assert_cost_precision(parcel_after["final_fee"])

    def test_final_fee_adds_reattempt_fee_once_per_no_one_home(self, api):
        """PRD §3.7: 'if the attempt's outcome is NO_ONE_HOME or REFUSED,
        a reattempt fee of 3.00 is added to the accumulator'."""
        ctx = walk_parcel_to_out_for_delivery()
        quoted = ctx["parcel"]["quoted_fee"]
        # 1st attempt: NO_ONE_HOME.
        move_clock_into_window(ctx["parcel"])
        api.create_attempt(
            ctx["parcel"]["id"],
            {"route_stop_id": ctx["stop"]["id"],
             "outcome": "NO_ONE_HOME"},
            make_driver_headers(ctx["driver"]["id"]),
        )
        # PRD §3.2 driver cycle requires close-route + check-out before
        # the next check-in/dispatch. Then reattempt -> SORTED -> new
        # route -> dispatch -> deliver. PRD §3.7: pin the new route's
        # planned_date to the parcel's window date.
        reset_driver_to_on_duty(ctx["driver"]["id"], ctx["route"]["id"])
        api.reattempt_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        )
        parcel_window_date = ctx["parcel"]["time_window_start"][:10]
        route2 = create_route(
            ctx["center"]["id"], ctx["driver"]["id"],
            planned_date=parcel_window_date,
        )
        stop2 = add_stop(route2["id"], ctx["parcel"]["id"])
        dispatch_route(route2["id"])
        re_p = validate_success(api.get_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        deliver_signed(re_p, stop2, ctx["driver"]["id"])
        terminal = validate_success(api.get_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        expected_final = quoted + REATTEMPT_FEE
        assert terminal["final_fee"] == pytest.approx(
            expected_final, abs=0.01,
        )

    def test_final_fee_returned_to_sender_includes_return_surcharge(self, api):
        """PRD §3.7: 'Finally, if the parcel's terminal status is
        RETURNED_TO_SENDER, a return-to-sender surcharge of 7.00 is
        added to the accumulator.'"""
        ctx = walk_parcel_to_out_for_delivery()
        quoted = ctx["parcel"]["quoted_fee"]
        move_clock_into_window(ctx["parcel"])
        # ADDRESS_INVALID -> EXCEPTION -> return-to-sender.
        api.create_attempt(
            ctx["parcel"]["id"],
            {"route_stop_id": ctx["stop"]["id"],
             "outcome": "ADDRESS_INVALID"},
            make_driver_headers(ctx["driver"]["id"]),
        )
        terminal = validate_success(api.return_to_sender(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        # PRD §3.7 'return path' includes ADDRESS_CORRECTION_FEE 8.00
        # AND the chronological walk stops after ADDRESS_INVALID
        # (no further reattempt surcharges accrue), THEN
        # RETURN_TO_SENDER_FEE 7.00 is added.
        from test_helpers import ADDRESS_CORRECTION_FEE
        expected_final = quoted + ADDRESS_CORRECTION_FEE + RETURN_TO_SENDER_FEE
        assert terminal["final_fee"] == pytest.approx(
            expected_final, abs=0.01,
        )

    def test_final_fee_with_accepted_appointment_charges_change_fee(self, api):
        """PRD §3.7: 'the system counts the number of Appointment rows
        for this parcel whose status is ACCEPTED and adds the
        appointment-change fee of 4.50 to the accumulator once per
        accepted appointment.'"""
        ctx = walk_parcel_to_out_for_delivery()
        quoted = ctx["parcel"]["quoted_fee"]
        # Move clock backward in time relative to parcel window: clock
        # is already at the parcel's induction time. We need a
        # parcel-state that admits a new appointment: SORTED, ON_VEHICLE,
        # OUT_FOR_DELIVERY, or EXCEPTION. Parcel currently
        # OUT_FOR_DELIVERY — admits.
        new_start = parse_iso(ctx["parcel"]["time_window_start"]) + timedelta(hours=1)
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
        # Now deliver within the new window.
        re_p = validate_success(api.get_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        deliver_signed(re_p, ctx["stop"], ctx["driver"]["id"])
        terminal = validate_success(api.get_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        expected_final = quoted + APPOINTMENT_CHANGE_FEE
        assert terminal["final_fee"] == pytest.approx(
            expected_final, abs=0.01,
        )


# ---------------------------------------------------------------------------
# Route distance — PRD §3.7
# ---------------------------------------------------------------------------
class TestRouteDistance:

    def test_total_distance_km_zero_on_empty_route(self, api):
        """PRD §3.4: 'A new route starts in PLANNED with
        total_distance_km of 0.00, stop_count of 0, and hazmat_present
        of false.'"""
        base = setup_baseline()
        route = create_route(base["center"]["id"], base["driver"]["id"])
        assert route["total_distance_km"] == pytest.approx(0.00, abs=0.001)
        assert route["stop_count"] == 0
        assert route["hazmat_present"] is False

    def test_single_stop_distance_matches_haversine(self, api):
        """PRD §3.7: 'Starting from the origin transit center's stored
        coordinates, the system iterates the stops in ascending
        sequence order and ... adds that leg to a running total.'"""
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
        # PRD §2.8 distance precision 2 decimal places.
        assert route_after["total_distance_km"] == pytest.approx(
            round(expected_km + 1e-12, 2), abs=0.02,
        )
        assert route_after["stop_count"] == 1
