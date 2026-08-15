"""Weight-restriction offload selection, its cascade, and the rebook loop."""
from test_helpers import (
    ApiErrorId,
    assert_money,
    create_rebook_payload,
    get_booking,
    get_flight,
    get_plan,
    get_uld,
    impose_weight_restriction,
    make_accepted_booking,
    make_open_flight,
    make_uld_type_and_unit,
    create_build_up_plan,
    assign_booking,
    validate_error,
    validate_success,
)


def _setup_three_booking_flight(flight_number="CA205"):
    """Open flight cap 1200/100 with three ACCEPTED bookings totalling the
    full capacity; returns (flight, b1, b2, b3)."""
    flight = make_open_flight(
        flight_number=flight_number, max_payload_kg=1200, max_volume_m3=100
    )
    b1 = make_accepted_booking(
        flight["id"], shipper_ref="SHP-O1", gross_weight_kg=300, volume_m3=3
    )
    b2 = make_accepted_booking(
        flight["id"], shipper_ref="SHP-O2", gross_weight_kg=400, volume_m3=4
    )
    b3 = make_accepted_booking(
        flight["id"], shipper_ref="SHP-O3", gross_weight_kg=500, volume_m3=5
    )
    return flight, b1, b2, b3


class TestOffloadRebookCycle:
    def test_weight_restriction_offloads_newest_booking(
        self, api, capacity_controller_headers
    ):
        """PRD §3.7: "the candidate pool is every booking on the flight in
        `ACCEPTED` or `BUILT_UP` status, ranked by `created_at` descending so
        the most recently accepted cargo is sacrificed first, with ties broken
        by `gross_weight_kg` descending and then by `volume_m3` descending."
        PRD §3.7: "Each offload moves its booking to `OFFLOADED` and releases
        the flight's allocation by the booking's weight and volume."

        Design: Difficulty/non_linear_state_machine/booking_offload_rebook_cycle
        """
        flight, b1, b2, b3 = _setup_three_booking_flight()
        impose_weight_restriction(flight["id"], 900)
        assert get_booking(b3["id"])["status"] == "OFFLOADED", (
            "The newest and heaviest candidate (500kg) is sacrificed first"
        )
        assert get_booking(b1["id"])["status"] == "ACCEPTED"
        assert get_booking(b2["id"])["status"] == "ACCEPTED"
        assert_money(get_flight(flight["id"])["allocated_weight_kg"], 700)

    def test_offloaded_booking_rebooks_onto_new_flight(
        self, api, capacity_controller_headers
    ):
        """PRD §3.2: "A successful rebook moves the booking back to `ACCEPTED`,
        repoints its `flight_id` at the target flight, and debits the target
        flight's allocation counters; the original flight needs no adjustment
        because the offload already released its share."

        Design: Difficulty/non_linear_state_machine/booking_offload_rebook_cycle
        """
        flight, _b1, _b2, b3 = _setup_three_booking_flight()
        impose_weight_restriction(flight["id"], 900)
        target = make_open_flight(
            flight_number="CA206", max_payload_kg=1000, max_volume_m3=100,
            scheduled_departure="2026-08-11T08:00:00Z",
            scheduled_arrival="2026-08-13T08:00:00Z",
        )
        rebooked = validate_success(
            api.rebook_booking(
                b3["id"], create_rebook_payload(target["id"]),
                capacity_controller_headers,
            )
        )
        assert rebooked["status"] == "ACCEPTED", (
            "The cycle REQUESTED -> ACCEPTED -> OFFLOADED -> ACCEPTED completes"
        )
        assert rebooked["flight_id"] == target["id"]
        assert_money(get_flight(target["id"])["allocated_weight_kg"], 500)
        assert_money(get_flight(flight["id"])["allocated_weight_kg"], 700)


class TestOffloadCascade:
    def _setup_built_up_offload(self):
        flight, b1, b2, b3 = _setup_three_booking_flight("CA209")
        _uld_type, uld = make_uld_type_and_unit(
            {"tare_weight_kg": 100, "max_gross_weight_kg": 5000},
            uld_code="AKE00006CA",
        )
        plan = create_build_up_plan(flight["id"], uld["id"])
        assign_booking(plan["id"], b3["id"])
        return flight, b1, b2, b3, uld, plan

    def test_weight_restriction_offload_cascade_booking_and_flight(
        self, api, capacity_controller_headers
    ):
        """PRD §3.7: "Each offload moves its booking to `OFFLOADED` and
        releases the flight's allocation by the booking's weight and volume."
        PRD §3.7: "the candidate pool is every booking on the flight in
        `ACCEPTED` or `BUILT_UP` status, ranked by `created_at` descending so
        the most recently accepted cargo is sacrificed first, with ties broken
        by `gross_weight_kg` descending and then by `volume_m3` descending."

        Design: Difficulty/transitive_cascade/weight_restriction_offload_cascade
        """
        flight, b1, b2, b3, _uld, _plan = self._setup_built_up_offload()
        impose_weight_restriction(flight["id"], 900)
        observed = get_booking(b3["id"])
        assert observed["status"] == "OFFLOADED", (
            "Link 1: the newest candidate is offloaded"
        )
        assert observed.get("build_up_plan_id") is None, (
            "The offloaded booking is removed from its plan"
        )
        assert get_booking(b1["id"])["status"] == "ACCEPTED"
        assert get_booking(b2["id"])["status"] == "ACCEPTED"
        assert_money(get_flight(flight["id"])["allocated_weight_kg"], 700)

    def test_weight_restriction_offload_cascade_plan_and_uld(
        self, api, capacity_controller_headers
    ):
        """PRD §3.7: "if that removal empties a plan that is still `DRAFT` of
        its last `BUILT_UP` booking, the plan auto-transitions `DRAFT →
        CANCELLED`, which in turn releases its unit `ASSIGNED → SERVICEABLE`
        and decrements the flight's `reserved_positions` by one, exactly
        mirroring an operator-driven cancellation."

        Design: Difficulty/transitive_cascade/weight_restriction_offload_cascade
        """
        flight, _b1, _b2, _b3, uld, plan = self._setup_built_up_offload()
        assert get_flight(flight["id"])["reserved_positions"] == 1
        impose_weight_restriction(flight["id"], 900)
        observed_plan = get_plan(plan["id"])
        assert observed_plan["status"] == "CANCELLED", (
            "Link 2: the emptied DRAFT plan auto-cancels"
        )
        assert observed_plan["total_weight_kg"] == 0
        assert get_uld(uld["id"])["status"] == "SERVICEABLE", (
            "Link 3: the auto-cancel releases the unit"
        )
        assert get_flight(flight["id"])["reserved_positions"] == 0


class TestRebookEntryState:
    def test_rebook_accepted_booking_rejected(self, api, capacity_controller_headers):
        """PRD §3.2: "Attempting to rebook from any state other than
        `OFFLOADED` draws `ERR_BOOKING_INVALID_STATE`."

        Design: Corner/errors/rebook_accepted_booking_rejected
        """
        flight1 = make_open_flight(flight_number="CA335")
        flight2 = make_open_flight(flight_number="CA336")
        booking = make_accepted_booking(flight1["id"], shipper_ref="SHP-R2")
        res = api.rebook_booking(
            booking["id"], create_rebook_payload(flight2["id"]),
            capacity_controller_headers,
        )
        validate_error(res, ApiErrorId.ERR_BOOKING_INVALID_STATE)
