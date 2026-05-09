"""Cold-chain dispatch, temperature excursions, and disposal (PRD §3.7).
"""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    ApiErrorId,
    setup_cold_chain_dispatched,
    setup_cold_chain_with_score,
    setup_otc_purchase_scenario,
    setup_otc_order_in_review,
    setup_basic_platform,
    create_pharmacist,
    create_customer,
    create_otc_drug_on_shelf,
    create_cold_chain_drug_on_shelf,
    create_drug,
    create_drug_payload,
    place_order,
    pay_order,
    open_pharmacist_review,
    approve_review,
    dispense_order,
    ship_order,
    deliver_order,
    setup_platform_at_clock,
    advance_clock,
    add_seconds,
    add_milliseconds,
    iso_z,
    parse_iso,
    get_order,
    get_shipment,
    get_audit_logs,
    find_audit_logs,
    append_readings,
    reading_payload,
    create_shipment_payload,
    order_item,
    TEST_USERS,
    make_admin_headers,
    make_pharmacist_headers,
)


# ---------------------------------------------------------------------------
# Dispatch validation (PRD §3.7)
# ---------------------------------------------------------------------------

class TestColdChainDispatch:
    """PRD §3.7: 'The shipment may only be created against an order whose
    cold_chain_required is true and whose dispensing_status is APPROVED or
    DISPENSED (otherwise ERR_COLD_CHAIN_NOT_APPLICABLE). The pharmacist
    named in courier_pharmacist_id must have both courier_qualified equal
    to true and qualification_status equal to ACTIVE; otherwise the
    dispatch is rejected with ERR_COURIER_NOT_QUALIFIED.'
    """

    def test_dispatch_for_non_cold_chain_order_rejected(self, api):
        """PRD §3.7: 'cold_chain_required is true ... otherwise
        ERR_COLD_CHAIN_NOT_APPLICABLE.'"""
        s = setup_otc_order_in_review(api, paid=True)
        approve_review(api, s["platform"]["id"], s["order"]["id"],
                          s["review"]["id"], s["rr_pharmacist"])
        courier = create_pharmacist(api, s["platform"]["id"], courier_qualified=True)
        resp = api.create_cold_chain_shipment(
            s["platform"]["id"],
            create_shipment_payload(s["order"]["id"], courier["id"]),
            TEST_USERS["admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_COLD_CHAIN_NOT_APPLICABLE.value)

    def test_dispatch_with_unqualified_courier_rejected(self, api):
        """PRD §3.7: 'courier_qualified equal to true ... otherwise the
        dispatch is rejected with ERR_COURIER_NOT_QUALIFIED.'"""
        s = setup_cold_chain_dispatched(api)
        # Build a NOT-courier-qualified pharmacist and try a fresh order.
        pf, vendor = s["platform"], s["vendor"]
        not_courier = create_pharmacist(api, pf["id"], courier_qualified=False)
        # Build a parallel cold-chain order that does NOT yet have a shipment.
        from test_helpers import (
            create_customer, place_order, pay_order, create_two_pharmacists,
            open_pharmacist_review, approve_review,
        )
        customer = create_customer(api, pf["id"], real_name_verified=True)
        pr, rr = create_two_pharmacists(api, pf["id"])
        order = place_order(api, pf["id"], customer,
                              items=[order_item(s["drug"]["id"], qty=1, unit_price_cents=5000)])
        order = pay_order(api, pf["id"], order)
        review = open_pharmacist_review(api, pf["id"], order, rr)
        approve_review(api, pf["id"], order["id"], review["id"], rr)
        # Now order is APPROVED, cold_chain_required True, no shipment exists.
        resp = api.create_cold_chain_shipment(
            pf["id"],
            create_shipment_payload(order["id"], not_courier["id"]),
            TEST_USERS["admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_COURIER_NOT_QUALIFIED.value)

    def test_dispatch_succeeds_with_qualified_courier(self, api):
        """PRD §3.7: 'On successful dispatch, the shipment enters status
        DISPATCHED, dispatched_at is set to current_clock_iso, and the
        order's cold_chain_shipment_id is set to the new shipment.'"""
        s = setup_cold_chain_dispatched(api)
        assert s["shipment"]["status"] == "DISPATCHED"
        assert s["order"].get("cold_chain_shipment_id") == s["shipment"]["id"]


# ---------------------------------------------------------------------------
# Excursion score computation (PRD §3.7)
# ---------------------------------------------------------------------------

class TestExcursionScoreFormula:
    """PRD §3.7: 'The score is computed by sorting the readings ascending by
    recorded_at, then for each reading deriving a per-reading severity and
    a per-reading window length, multiplying them, and summing. The
    severity for a single reading is 0 when celsius_tenths is between 20
    and 80 inclusive ...; for any reading whose celsius_tenths is below 20
    or above 80, the severity is 5 if celsius_tenths is below 0 or above
    150 ..., and 1 otherwise. The window length for the i-th reading
    (zero-indexed) is, for every reading except the last, the difference
    in seconds between the next reading's recorded_at and this reading's
    recorded_at, divided by 60, rounded up to the next whole number, and
    clamped to be at least 1; for the last reading the window length is
    exactly 1. The per-reading score is the integer product of severity
    and window length. The shipment's excursion_score is the sum of these
    per-reading scores across all readings. The order is fixed: the
    per-reading product is always computed first per reading, and only
    then are the per-reading scores summed.'
    """

    def test_critical_then_safe_per_reading_then_sum(self, api):
        """Three readings: critical(60s gap), critical(360s gap), safe(last).
        Per-reading: 5*1=5, 5*6=30, 0*1=0; sum=35.

        # difficulty: combinatorial_formula/cold_chain_score_per_reading_then_sum
        """
        s = setup_cold_chain_dispatched(api,
                                            clock_iso="2025-01-01T00:00:00.000Z")
        pf, shipment = s["platform"], s["shipment"]
        base = "2025-01-01T00:00:00.000Z"
        readings = [
            reading_payload(base, 200),                              # 20.0°C critical
            reading_payload(add_seconds(base, 60), 200),             # 20.0°C critical, 60s window
            reading_payload(add_seconds(base, 60 + 360), 27),        # 2.7°C safe (last, window=1)
        ]
        final = append_readings(api, pf["id"], shipment["id"], readings)
        # r0 window: 60s → ceil(60/60)=1; per_reading r0 = 5*1 = 5
        # r1 window: 360s → ceil(360/60)=6; per_reading r1 = 5*6 = 30
        # r2 last: window=1; per_reading r2 = 0
        # excursion_score == 35
        assert final["excursion_score"] == 35

    def test_min_one_minute_floor_for_sub_minute_gap(self, api):
        """PRD §3.7: 'rounded up to the next whole number, and clamped to
        be at least 1.' A 1-millisecond gap yields window=1, not 0.

        # difficulty: resource_temporal_overlap/cold_chain_reading_adjacency_floored_window
        """
        s = setup_cold_chain_dispatched(api,
                                            clock_iso="2025-01-01T00:00:00.000Z")
        pf, shipment = s["platform"], s["shipment"]
        base = "2025-01-01T00:00:00.000Z"
        readings = [
            reading_payload(base, 200),                                  # critical
            reading_payload(add_milliseconds(base, 1), 200),             # critical, 1ms gap → window=1
            reading_payload(add_seconds(base, 60), 27),                  # safe (last)
        ]
        final = append_readings(api, pf["id"], shipment["id"], readings)
        # r0: 1ms → ceil(0.001/60)=1, max(1,1)=1; per=5
        # r1: ~60s → ceil(60/60)=1; per=5
        # r2: last; per=0
        # excursion_score == 10
        assert final["excursion_score"] == 10


# ---------------------------------------------------------------------------
# Disposal threshold boundary (PRD §3.7)
# ---------------------------------------------------------------------------

class TestDisposalThresholdBoundary:
    """PRD §3.7: 'a PlatformAdmin must dispose the shipment instead: the
    dispose action requires the shipment to currently be in IN_TRANSIT or
    DISPATCHED (otherwise ERR_SHIPMENT_NOT_DISPOSABLE) and excursion_score
    to be strictly greater than 30 (otherwise ERR_DISPOSAL_NOT_JUSTIFIED).'
    """

    def test_dispose_at_score_30_rejected(self, api):
        """PRD §3.7: excursion_score == 30 is NOT > 30 → ERR_DISPOSAL_NOT_JUSTIFIED.

        # difficulty: boundary_precision_check/cold_chain_dispose_exact_threshold_inclusive_vs_exclusive
        Construction: r0=critical (severity 5) with 6-min window → 30;
        r1=safe with 1-min window → 0; r2=safe last → 0. Total = 30.
        """
        s = setup_cold_chain_dispatched(api,
                                            clock_iso="2025-01-01T00:00:00.000Z")
        pf, shipment = s["platform"], s["shipment"]
        base = "2025-01-01T00:00:00.000Z"
        readings = [
            reading_payload(base, 200),                              # critical (5)
            reading_payload(add_seconds(base, 360), 27),             # safe (0), 6-min window for r0
            reading_payload(add_seconds(base, 360 + 60), 27),        # safe last
        ]
        final = append_readings(api, pf["id"], shipment["id"], readings)
        assert final["excursion_score"] == 30

        resp = api.dispose_cold_chain_shipment(pf["id"], shipment["id"],
                                                   TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_DISPOSAL_NOT_JUSTIFIED.value)

    def test_dispose_at_score_31_succeeds(self, api):
        """PRD §3.7: excursion_score == 31 is > 30 → dispose succeeds.

        # difficulty: boundary_precision_check/cold_chain_dispose_exact_threshold_inclusive_vs_exclusive
        Append a single mild reading on top of the 30-point trace to push
        score to 31.
        """
        s = setup_cold_chain_dispatched(api,
                                            clock_iso="2025-01-01T00:00:00.000Z")
        pf, shipment = s["platform"], s["shipment"]
        base = "2025-01-01T00:00:00.000Z"
        readings = [
            reading_payload(base, 200),                                   # critical (5)
            reading_payload(add_seconds(base, 360), 27),                  # safe last so far (0)
            reading_payload(add_seconds(base, 360 + 60), 27),             # safe last
            reading_payload(add_seconds(base, 360 + 120), 120),           # 12.0°C mild (severity 1, last)
        ]
        final = append_readings(api, pf["id"], shipment["id"], readings)
        # r0: window = 6 → 5*6 = 30
        # r1: window = 1 → 0
        # r2: window = 1 → 0  (gap to r3 is 60s)
        # r3: last → 1*1 = 1
        # total = 31
        assert final["excursion_score"] == 31

        resp = api.dispose_cold_chain_shipment(pf["id"], shipment["id"],
                                                   TEST_USERS["admin_headers"])
        data = validate_success(resp)
        assert data["status"] == "DISPOSED"


# ---------------------------------------------------------------------------
# Disposal cascades (PRD §3.7)
# ---------------------------------------------------------------------------

class TestDisposalCascade:
    """PRD §3.7: 'Disposal moves the shipment to DISPOSED, appends an
    AuditLog row with action COLD_CHAIN_DISPOSED, drives the order's
    dispensing_status to REJECTED, and runs the refund cascade if
    payment_status was PAID.'
    """

    def test_dispose_cascades_order_rejected_and_refunded(self, api):
        s = setup_cold_chain_dispatched(api)
        pf, shipment, order = s["platform"], s["shipment"], s["order"]
        # Push the score above 30: 7 critical readings 60s apart (5*7=35).
        base = "2025-01-01T00:00:00.000Z"
        readings = [reading_payload(add_seconds(base, 60 * i), 200)
                       for i in range(7)]
        readings.append(reading_payload(add_seconds(base, 60 * 7), 27))  # safe last
        append_readings(api, pf["id"], shipment["id"], readings)
        # Confirm score > 30 prerequisite for dispose.
        ship_now = get_shipment(api, pf["id"], shipment["id"])
        assert ship_now["excursion_score"] > 30

        api.dispose_cold_chain_shipment(pf["id"], shipment["id"],
                                            TEST_USERS["admin_headers"])
        order_after = get_order(api, pf["id"], order["id"])
        assert order_after["dispensing_status"] == "REJECTED"
        assert order_after["payment_status"] == "REFUNDED"

        # AuditLog COLD_CHAIN_DISPOSED row exists.
        logs = get_audit_logs(api, pf["id"])
        match = find_audit_logs(logs, subject_id=shipment["id"],
                                  action="COLD_CHAIN_DISPOSED")
        assert len(match) == 1


# ---------------------------------------------------------------------------
# Deliver requires excursion within range (PRD §3.7)
# ---------------------------------------------------------------------------

class TestDeliverColdChainOutOfRange:
    """PRD §3.7: 'Delivery moves dispensing_status from SHIPPED to DELIVERED.
    The order must be currently SHIPPED ...; if cold_chain_required is true,
    the linked shipment's status must be in IN_TRANSIT or DELIVERED and its
    excursion_score must be at most 30 (otherwise
    ERR_COLD_CHAIN_OUT_OF_RANGE).'
    """

    def test_deliver_with_score_above_threshold_rejected(self, api):
        s = setup_cold_chain_dispatched(api)
        pf, shipment, order = s["platform"], s["shipment"], s["order"]
        # Take order through dispense → ship: order.dispensing_status APPROVED.
        from test_helpers import dispense_order, ship_order
        dispense_order(api, pf["id"], order["id"], s["courier_pharmacist"])
        # Now ship — cascades shipment DISPATCHED → IN_TRANSIT.
        ship_order(api, pf["id"], order["id"])
        # Append readings to push excursion_score > 30.
        base = "2025-01-01T00:00:00.000Z"
        readings = [reading_payload(add_seconds(base, 60 * i), 200)
                       for i in range(7)]
        readings.append(reading_payload(add_seconds(base, 60 * 7), 27))
        append_readings(api, pf["id"], shipment["id"], readings)

        resp = api.deliver_order(pf["id"], order["id"], TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_COLD_CHAIN_OUT_OF_RANGE.value)


# ---------------------------------------------------------------------------
# Ship requires DISPATCHED shipment for cold-chain order (PRD §3.7)
# ---------------------------------------------------------------------------

class TestShipRequiresDispatchedShipment:
    """PRD §3.7: 'when cold_chain_required is true, a ColdChainShipment for
    the order exists with status DISPATCHED (otherwise
    ERR_COLD_CHAIN_SHIPMENT_REQUIRED).'
    """

    def test_ship_cold_chain_order_without_shipment_rejected(self, api):
        """Build a cold-chain order through APPROVED then DISPENSED (skipping
        shipment dispatch) and attempt ship. Should be rejected.
        """
        # Dispatch fixture creates shipment; we need the inverse path.
        pf = setup_platform_at_clock(api, "2025-01-01T00:00:00.000Z")
        from test_helpers import (
            create_vendor, create_cold_chain_drug_on_shelf,
            create_customer, create_pharmacist,
            create_two_pharmacists, place_order, pay_order,
            open_pharmacist_review, approve_review, dispense_order,
        )
        vendor = create_vendor(api, pf["id"])
        drug = create_cold_chain_drug_on_shelf(api, pf["id"], vendor["id"])
        customer = create_customer(api, pf["id"], real_name_verified=True)
        rr = create_pharmacist(api, pf["id"], full_name="Cold-RR no shipment")
        order = place_order(api, pf["id"], customer,
                              items=[order_item(drug["id"], qty=1, unit_price_cents=5000)])
        order = pay_order(api, pf["id"], order)
        review = open_pharmacist_review(api, pf["id"], order, rr)
        approve_review(api, pf["id"], order["id"], review["id"], rr)
        # Pharmacist (rr) dispenses.
        dispense_order(api, pf["id"], order["id"], rr)
        # Order is DISPENSED, cold_chain_required True, but NO shipment dispatched.
        resp = api.ship_order(pf["id"], order["id"], TEST_USERS["admin_headers"])
        validate_error(resp, ApiErrorId.ERR_COLD_CHAIN_SHIPMENT_REQUIRED.value)
