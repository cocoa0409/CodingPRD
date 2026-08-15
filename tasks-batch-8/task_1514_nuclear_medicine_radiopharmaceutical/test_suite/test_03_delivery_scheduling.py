"""Isotope supply: hot-lab capacity, receipt tolerance, failure, and the
delivery-side guards on vial preparation."""
from test_helpers import (
    TEST_USERS,
    assert_isotope_delivery,
    create_dose_vial_payload,
    create_isotope,
    create_isotope_delivery_payload,
    create_license,
    create_order,
    create_patient,
    create_authorized_user,
    get_order,
    receive_delivery,
    schedule_delivery,
    set_clock,
    setup_f18_department,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
RP = TEST_USERS["radiopharmacist_headers"]


class TestDeliveryReceipt:
    def test_receive_tolerance_exceeded_rejected(self, api):
        """PRD §3.2: "the measured value must agree with the reference activity
        decayed from `reference_time_at` to the receipt instant — the absolute
        difference must be at most ten percent of that decayed reference value,
        a deviation of exactly ten percent passes, and anything larger is
        rejected with `ERR_ACTIVITY_TOLERANCE_EXCEEDED` (HTTP 422)."

        The fixture leaves the clock at 08:30, thirty minutes after the
        08:00 reference instant, so the decayed reference is
        5000 x 0.5^(30/110) = 4138.766 MBq and the ten-percent band is
        +/-413.877. Measured 3000 deviates by 1138.766 (~27.5%), well
        outside the band.

        Design: Corner/validations/receive_tolerance_exceeded_rejected
        """
        ctx = setup_f18_department(receive=False, with_room=False)
        res = api.receive_isotope_delivery(
            ctx["delivery"]["id"], {"measured_activity_mbq": 3000}, RP
        )
        validate_error(res, "ERR_ACTIVITY_TOLERANCE_EXCEEDED", expected_status=422)

        delivery = validate_success(api.get_isotope_delivery(ctx["delivery"]["id"], ADMIN), 200)
        assert delivery["status"] == "SCHEDULED", "rejected receipt leaves no trace"

    def test_receive_failed_delivery_returns_invalid_state(self, api):
        """PRD §3.2: "the delivery must still be `SCHEDULED` (otherwise
        `ERR_INVALID_STATE`)" and "only a `SCHEDULED` delivery can be marked
        failed (otherwise `ERR_INVALID_STATE`)". FAILED is terminal.

        Design: Corner/state_machines/receive_failed_delivery_returns_invalid_state
        """
        ctx = setup_f18_department(receive=False, with_room=False)
        failed = validate_success(
            api.mark_isotope_delivery_failed(
                ctx["delivery"]["id"], {"reason": "generator outage at supplier"}, RP
            ),
            200,
        )
        assert_isotope_delivery(failed)
        assert failed["status"] == "FAILED"

        res = api.receive_isotope_delivery(
            ctx["delivery"]["id"], {"measured_activity_mbq": 5000}, RP
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)


class TestHotLabAggregateCapacity:
    """Delivery scheduling is aggregate-capacity, not exclusion: overlapping
    arrival windows are allowed and only the decayed sum at the latest arrival
    instant is constrained."""

    def test_overlapping_deliveries_exceeding_capacity_rejected(self, api):
        """PRD §3.2: "Only when this aggregate load is strictly greater than
        37,000 MBq is the scheduling rejected with `ERR_HOT_LAB_CAPACITY_EXCEEDED`
        (HTTP 409); a load of exactly 37,000 MBq is accepted. Note the
        aggregate-capacity semantics: overlapping arrivals are allowed, and only
        the decayed sum at the reference instant is constrained..."

        A: 20000 MBq @ 12:00; B: 20000 MBq @ 12:10. Windows [11:30,12:30) and
        [11:40,12:40) intersect; at the 12:10 reference instant the decayed sum
        is roughly 38,779 MBq, which exceeds 37,000.

        Design: Difficulty/resource_temporal_overlap/delivery_aggregate_capacity_overlap
        """
        set_clock("2026-08-01T08:00:00Z")
        iso = create_isotope()
        create_license(iso["id"])
        delivery_a = schedule_delivery(
            iso["id"],
            scheduled_arrival_at="2026-08-01T12:00:00Z",
            reference_activity_mbq=20000,
            reference_time_at="2026-08-01T12:00:00Z",
        )
        assert delivery_a["status"] == "SCHEDULED"

        res = api.create_isotope_delivery(
            create_isotope_delivery_payload(
                iso["id"],
                scheduled_arrival_at="2026-08-01T12:10:00Z",
                reference_activity_mbq=20000,
                reference_time_at="2026-08-01T12:10:00Z",
            ),
            RP,
        )
        validate_error(res, "ERR_HOT_LAB_CAPACITY_EXCEEDED", expected_status=409)

        after = validate_success(api.get_isotope_delivery(delivery_a["id"], ADMIN), 200)
        assert after["status"] == "SCHEDULED", "rejection of B leaves no trace on A"

    def test_touching_windows_do_not_intersect(self, api):
        """PRD §3.2: "Every delivery occupies a half-open arrival window that
        opens thirty minutes before its `scheduled_arrival_at` and closes thirty
        minutes after it — the window includes its opening instant and excludes
        its closing instant. The candidate set is every other delivery in
        `SCHEDULED` or `RECEIVED` status whose window intersects the new
        delivery's window with a non-empty intersection; windows that merely
        touch at an endpoint do not intersect..."

        A at 12:00 occupies [11:30, 12:30); C at 13:00 occupies [12:30, 13:30).
        The windows touch at 12:30 without intersecting, so C's load is only its
        own decayed contribution (20,000 at its reference instant) and C is
        accepted.

        Design: Difficulty/resource_temporal_overlap/delivery_aggregate_capacity_overlap
        """
        set_clock("2026-08-01T08:00:00Z")
        iso = create_isotope()
        create_license(iso["id"])
        schedule_delivery(
            iso["id"],
            scheduled_arrival_at="2026-08-01T12:00:00Z",
            reference_activity_mbq=20000,
            reference_time_at="2026-08-01T12:00:00Z",
        )
        res = api.create_isotope_delivery(
            create_isotope_delivery_payload(
                iso["id"],
                scheduled_arrival_at="2026-08-01T13:00:00Z",
                reference_activity_mbq=20000,
                reference_time_at="2026-08-01T13:00:00Z",
            ),
            RP,
        )
        delivery_c = validate_success(res, 201)
        assert_isotope_delivery(delivery_c)
        assert delivery_c["status"] == "SCHEDULED"


class TestDeliveryGuardsOnVialPreparation:
    def test_administration_before_delivery_arrival_rejected(self, api):
        """PRD §3.4: "the order's `administration_scheduled_at` must not be
        earlier than the delivery's `scheduled_arrival_at`, otherwise
        `ERR_ADMIN_BEFORE_DELIVERY` (HTTP 409)."

        Order scheduled 07:00 against a delivery arriving 08:00; preparation is
        attempted after receipt.

        Design: Corner/validations/vial_prep_before_delivery_arrival_rejected
        """
        set_clock("2026-08-01T06:00:00Z")
        iso = create_isotope()
        lic = create_license(iso["id"])
        au = create_authorized_user(lic["id"])
        pat = create_patient()
        delivery = schedule_delivery(iso["id"])  # arrival 08:00, ref 5000 @ 08:00
        order = create_order(
            pat["id"], iso["id"], au, administration_scheduled_at="2026-08-01T07:00:00Z"
        )
        set_clock("2026-08-01T08:00:00Z")
        assert get_order(order["id"])["status"] == "ORDERED", "order expiry is 10:40"
        receive_delivery(delivery["id"], 5000)

        res = api.create_dose_vial(create_dose_vial_payload(order["id"], delivery["id"]), RP)
        validate_error(res, "ERR_ADMIN_BEFORE_DELIVERY", expected_status=409)

    def test_insufficient_delivery_activity_rejected(self, api):
        """PRD §3.4: "the delivery's reference activity decayed to the current
        instant must be at least the computed `required_activity_mbq`, otherwise
        `ERR_INSUFFICIENT_DELIVERY_ACTIVITY` (HTTP 409)."

        Required draw is 100 x 2^(110/110) x 1.10 = 220.000 MBq while the
        100 MBq delivery has decayed to roughly 82.8 MBq by 08:30.

        Design: Corner/validations/vial_prep_insufficient_delivery_activity
        """
        ctx = setup_f18_department(
            with_room=False, delivery_overrides={"reference_activity_mbq": 100}
        )
        order = create_order(ctx["patient"]["id"], ctx["isotope"]["id"], ctx["authorized_user"])
        res = api.create_dose_vial(
            create_dose_vial_payload(order["id"], ctx["delivery"]["id"]), RP
        )
        validate_error(res, "ERR_INSUFFICIENT_DELIVERY_ACTIVITY", expected_status=409)
        assert get_order(order["id"])["status"] == "ORDERED", "no partial vial, no status drift"
