"""Track service/derail dimensions, spot-order scheduling gates, window and
crew-buffer overlap semantics, supersede cascade, and optimistic concurrency."""
from test_helpers import (
    ApiErrorId,
    allocation_adjustment_payload,
    create_spot_order_payload,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    BILLING,
    OPERATOR,
    SAFETY,
    YARD,
    arrive_car,
    create_customer,
    create_equipment,
    create_facility,
    create_incident,
    create_lot,
    create_product,
    create_railcar,
    create_spot_order_for_car,
    create_track,
    get_railcar,
    get_track,
    list_all_charges,
    schedule_spot_order,
    set_clock,
    setup_active_transfer,
    setup_spotted_car,
)


class TestTrackDimensions:
    def test_track_parallel_dimensions_positive(self, api):
        """PRD §2.7: "Each `Track` carries two independent, parallel
        dimensions. The first, `status`, starts at `ACTIVE` and may be taken
        to `OUT_OF_SERVICE` by a `YardMaster` — but only while the track's
        `occupied_spots` is zero; attempting it with cars still spotted is
        rejected with `ERR_TRACK_OCCUPIED`. Restoring service returns the
        track to `ACTIVE` without preconditions."
        PRD §2.7: "The second dimension, `derail_protection`, starts at
        `DISENGAGED`; a `SafetyOfficer` may engage and disengage it at will."

        Design: Corner/state_machines/track_parallel_dimensions_positive
        """
        create_facility(name="FT-S5")
        trk = create_track(name="T1", spot_capacity=2)

        s1 = validate_success(api.take_track_out_of_service(trk["id"], YARD))
        assert s1["status"] == "OUT_OF_SERVICE"
        assert s1["derail_protection"] == "DISENGAGED", "derail untouched by take-out"

        s2 = validate_success(api.engage_derail(trk["id"], SAFETY))
        assert s2["derail_protection"] == "ENGAGED"
        assert s2["status"] == "OUT_OF_SERVICE", "status untouched by engage"

        s3 = validate_success(api.restore_track_service(trk["id"], YARD))
        assert s3["status"] == "ACTIVE"
        assert s3["derail_protection"] == "ENGAGED"

        s4 = validate_success(api.disengage_derail(trk["id"], SAFETY))
        assert s4["derail_protection"] == "DISENGAGED"
        assert s4["status"] == "ACTIVE"


def _spot_gate_setup(api):
    """Facility with five cap-1 tracks, customers C1 (alloc 5) and C2
    (alloc 0), and six cars in assorted states — one isolated gate per order.

    T2 is taken OUT_OF_SERVICE up front. soB (carB REGISTERED), soC (carC on
    T2), soA (carA on T4), soE (carE of C2 on T5) are created REQUESTED.
    """
    set_clock("2026-08-03T00:00:00Z")
    create_facility(name="FT-S6")
    c1 = create_customer(name="C1", allocated_car_spots=5)
    c2 = create_customer(name="C2", allocated_car_spots=0)
    prod = create_product(name="Salt")
    lot1 = create_lot(c1["id"], prod["id"])
    lot2 = create_lot(c2["id"], prod["id"])
    t1 = create_track(name="T1", spot_capacity=1)
    t2 = create_track(name="T2", spot_capacity=1)
    t3 = create_track(name="T3", spot_capacity=1)
    t4 = create_track(name="T4", spot_capacity=1)
    t5 = create_track(name="T5", spot_capacity=1)
    get_success_data(api.take_track_out_of_service(t2["id"], YARD))

    car_a = arrive_car(create_railcar(c1["id"], prod["id"], lot1["id"],
                                      car_number="96101")["id"])
    car_b = create_railcar(c1["id"], prod["id"], lot1["id"], car_number="96102")
    car_c = arrive_car(create_railcar(c1["id"], prod["id"], lot1["id"],
                                      car_number="96103")["id"])
    car_d = arrive_car(create_railcar(c1["id"], prod["id"], lot1["id"],
                                      car_number="96104")["id"])
    car_e = arrive_car(create_railcar(c2["id"], prod["id"], lot2["id"],
                                      car_number="96105")["id"])
    car_f = arrive_car(create_railcar(c1["id"], prod["id"], lot1["id"],
                                      car_number="96106")["id"])

    so_b = create_spot_order_for_car(car_b["id"], t1["id"], 1,
                                     "2026-08-03T06:00:00Z", "2026-08-03T08:00:00Z")
    so_c = create_spot_order_for_car(car_c["id"], t2["id"], 1,
                                     "2026-08-03T01:00:00Z", "2026-08-03T03:00:00Z")
    so_a = create_spot_order_for_car(car_a["id"], t4["id"], 1,
                                     "2026-08-03T01:00:00Z", "2026-08-03T03:00:00Z")
    so_e = create_spot_order_for_car(car_e["id"], t5["id"], 1,
                                     "2026-08-03T13:00:00Z", "2026-08-03T15:00:00Z")
    return {
        "c1": c1, "c2": c2, "prod": prod, "lot1": lot1,
        "t1": t1, "t2": t2, "t3": t3, "t4": t4, "t5": t5,
        "car_a": car_a, "car_b": car_b, "car_c": car_c,
        "car_d": car_d, "car_e": car_e, "car_f": car_f,
        "so_a": so_a, "so_b": so_b, "so_c": so_c, "so_e": so_e,
    }


class TestSpotOrderGates:
    def test_spot_schedule_gate_errors(self, api):
        """PRD §3.4: "The checks, in evaluation order: the railcar's
        `placement_status` must be `ARRIVED` (`ERR_CAR_NOT_ARRIVED`); the track
        must be `ACTIVE` (`ERR_TRACK_OUT_OF_SERVICE`); the track's
        `derail_protection` must be `DISENGAGED` (`ERR_DERAIL_ENGAGED`); the
        facility must not be `SUSPENDED` (`ERR_FACILITY_SUSPENDED`); the
        requested `spot_number` must be at least 1 and at most the track's
        `spot_capacity` (`ERR_SPOT_NUMBER_INVALID`); no other spot order in
        `REQUESTED`, `SCHEDULED`, or `EXECUTED` on the same track with the same
        `spot_number` may have a window that overlaps this order's half-open
        window, and no railcar may currently be `SPOTTED` on that track at that
        spot number (both `ERR_SPOT_WINDOW_OVERLAP`); the track's
        `occupied_spots` plus `reserved_spots`, counting this order, must not
        exceed `spot_capacity` (`ERR_TRACK_FULL`); the customer's
        occupied-plus-reserved spots across all tracks, counting this order,
        must not exceed their `allocated_car_spots` (`ERR_ALLOCATION_EXCEEDED`);
        the customer's `credit_standing` must not be `CREDIT_HOLD`
        (`ERR_CREDIT_HOLD`); and no switch order in `SCHEDULED` on the same
        track may have a window within the facility's `switch_buffer_minutes`
        of this order's window (`ERR_SWITCH_WINDOW_CONFLICT`)."
        PRD §2.9: "Every endpoint evaluates its checks in a fixed priority
        order, and when several checks fail the earliest one wins:" (derail,
        item 7, precedes the track/window constraints, item 10).

        Design: Corner/state_machines/track_and_posture_gates_on_spot_orders_rejected
        """
        ctx = _spot_gate_setup(api)

        # Car never arrived -> ERR_CAR_NOT_ARRIVED
        validate_error(api.schedule_spot_order(ctx["so_b"]["id"], YARD),
                       ApiErrorId.ERR_CAR_NOT_ARRIVED)

        # Track OUT_OF_SERVICE -> ERR_TRACK_OUT_OF_SERVICE
        validate_error(api.schedule_spot_order(ctx["so_c"]["id"], YARD),
                       ApiErrorId.ERR_TRACK_OUT_OF_SERVICE)

        # Clean schedule succeeds; T4 reservation now equals capacity
        scheduled = validate_success(api.schedule_spot_order(ctx["so_a"]["id"], YARD))
        assert scheduled["status"] == "SCHEDULED"
        t4 = get_track(ctx["t4"]["id"])
        assert t4["reserved_spots"] == 1

        # Second order on the now-full T4 -> ERR_TRACK_FULL
        so_f = create_spot_order_for_car(ctx["car_f"]["id"], ctx["t4"]["id"], 1,
                                         "2026-08-03T10:00:00Z",
                                         "2026-08-03T12:00:00Z")
        validate_error(api.schedule_spot_order(so_f["id"], YARD),
                       ApiErrorId.ERR_TRACK_FULL)

        # Customer C2 has allocated_car_spots 0 -> ERR_ALLOCATION_EXCEEDED
        validate_error(api.schedule_spot_order(ctx["so_e"]["id"], YARD),
                       ApiErrorId.ERR_ALLOCATION_EXCEEDED)

        # Derail engaged + out-of-range spot: the safety gate wins
        get_success_data(api.engage_derail(ctx["t3"]["id"], SAFETY))
        so_d = create_spot_order_for_car(ctx["car_d"]["id"], ctx["t3"]["id"], 9,
                                         "2026-08-03T10:00:00Z",
                                         "2026-08-03T12:00:00Z")
        validate_error(api.schedule_spot_order(so_d["id"], YARD),
                       ApiErrorId.ERR_DERAIL_ENGAGED)

        # Derail cleared: the out-of-range spot number is reported
        get_success_data(api.disengage_derail(ctx["t3"]["id"], SAFETY))
        validate_error(api.schedule_spot_order(so_d["id"], YARD),
                       ApiErrorId.ERR_SPOT_NUMBER_INVALID)

        # A valid replacement order on T3 schedules cleanly
        get_success_data(api.cancel_spot_order(so_d["id"], YARD))
        so_d2 = create_spot_order_for_car(ctx["car_d"]["id"], ctx["t3"]["id"], 1,
                                          "2026-08-03T10:00:00Z",
                                          "2026-08-03T12:00:00Z")
        ok = validate_success(api.schedule_spot_order(so_d2["id"], YARD))
        assert ok["status"] == "SCHEDULED"

    def test_spot_execute_window_and_suspension_gates(self, api):
        """PRD §3.4: "The gates repeat in miniature — car still `ARRIVED`
        (`ERR_CAR_NOT_ARRIVED`), track `ACTIVE` (`ERR_TRACK_OUT_OF_SERVICE`),
        derail `DISENGAGED` (`ERR_DERAIL_ENGAGED`), facility not `SUSPENDED`
        (`ERR_FACILITY_SUSPENDED`) — plus the window check: the current logical
        clock must fall within the half-open window from `window_start` to
        `window_end` (`ERR_WINDOW_NOT_ACTIVE`)."
        PRD §2.6: "The posture gates operations facility-wide: while
        `SUSPENDED`, spot-order scheduling and execution, transfer activation,
        and railcar release are all blocked with `ERR_FACILITY_SUSPENDED`."
        PRD §2.7: "The first, `status`, starts at `ACTIVE` and may be taken to
        `OUT_OF_SERVICE` by a `YardMaster` — but only while the track's
        `occupied_spots` is zero; attempting it with cars still spotted is
        rejected with `ERR_TRACK_OCCUPIED`."

        Design: Corner/state_machines/track_and_posture_gates_on_spot_orders_rejected
        """
        ctx = _spot_gate_setup(api)
        so_d2 = create_spot_order_for_car(ctx["car_d"]["id"], ctx["t3"]["id"], 1,
                                          "2026-08-03T10:00:00Z",
                                          "2026-08-03T12:00:00Z")
        schedule_spot_order(so_d2["id"])

        # Execute exactly at window_end (exclusive) -> ERR_WINDOW_NOT_ACTIVE
        set_clock("2026-08-03T12:00:00Z")
        validate_error(api.execute_spot_order(so_d2["id"], YARD),
                       ApiErrorId.ERR_WINDOW_NOT_ACTIVE)
        # Execute after the window -> ERR_WINDOW_NOT_ACTIVE
        set_clock("2026-08-03T13:00:00Z")
        validate_error(api.execute_spot_order(so_d2["id"], YARD),
                       ApiErrorId.ERR_WINDOW_NOT_ACTIVE)

        # Facility SUSPENDED -> scheduling blocked
        create_incident(severity="CRITICAL", description="derail")
        get_success_data(api.cancel_spot_order(so_d2["id"], YARD))
        so_d3 = create_spot_order_for_car(ctx["car_d"]["id"], ctx["t3"]["id"], 1,
                                          "2026-08-03T14:00:00Z",
                                          "2026-08-03T16:00:00Z")
        validate_error(api.schedule_spot_order(so_d3["id"], YARD),
                       ApiErrorId.ERR_FACILITY_SUSPENDED)

        # No car ever executed onto T3: take-out-of-service succeeds with
        # occupied_spots == 0
        out = validate_success(api.take_track_out_of_service(ctx["t3"]["id"], YARD))
        assert out["occupied_spots"] == 0
        assert out["status"] == "OUT_OF_SERVICE"


class TestTrackOccupied:
    def test_track_occupied_blocks_out_of_service_rejected(self, api):
        """PRD §2.7: "The first, `status`, starts at `ACTIVE` and may be taken
        to `OUT_OF_SERVICE` by a `YardMaster` — but only while the track's
        `occupied_spots` is zero; attempting it with cars still spotted is
        rejected with `ERR_TRACK_OCCUPIED`."

        Design: Corner/state_machines/track_occupied_blocks_out_of_service_rejected
        """
        ctx = setup_spotted_car(quantity_loaded_tons=40.0, car_number="96201")

        validate_error(api.take_track_out_of_service(ctx["track"]["id"], YARD),
                       ApiErrorId.ERR_TRACK_OCCUPIED)
        track = get_track(ctx["track"]["id"])
        assert track["status"] == "ACTIVE"
        assert track["occupied_spots"] == 1


class TestSpotSupersede:
    def test_spot_order_supersede_success_cascade(self, api):
        """PRD §3.4: "if the car already has a spot order in `REQUESTED` or
        `SCHEDULED`, that prior order is superseded — it moves to `SUPERSEDED`"
        and "A superseded order that was `SCHEDULED` releases its reservation
        (`Track.reserved_spots` decreases by one, bumping `Track.version`);
        regardless of which of the two states it was in, its linked switch
        order (if any) moves from `SCHEDULED` to `CANCELLED` and that move's
        `SWITCHING` charge entry moves from `ACCRUED` to `VOIDED`. The new
        order then takes its own reservation — `Track.reserved_spots`
        increases by one — starts in `REQUESTED`, and bumps `Railcar.version`."

        Design: Corner/state_machines/spot_order_supersede_success_cascade
        """
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-S8")
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=2)
        car = arrive_car(
            create_railcar(cust["id"], prod["id"], lot["id"], car_number="96301")["id"]
        )
        so1 = create_spot_order_for_car(car["id"], trk["id"], 1,
                                        "2026-08-03T10:00:00Z",
                                        "2026-08-03T12:00:00Z")
        so1 = schedule_spot_order(so1["id"])
        sw1_id = so1["switch_order_id"]

        so2 = validate_success(
            api.create_spot_order(
                car["id"],
                create_spot_order_payload(
                    expected_railcar_version=get_railcar(car["id"])["version"],
                    track_id=trk["id"],
                    spot_number=2,
                    window_start="2026-08-03T14:00:00Z",
                    window_end="2026-08-03T16:00:00Z",
                ),
                YARD,
            ),
            201,
        )
        assert so2["status"] == "REQUESTED"

        so1_after = validate_success(api.get_spot_order(so1["id"], YARD))
        assert so1_after["status"] == "SUPERSEDED"
        sw1 = validate_success(api.get_switch_order(sw1_id, YARD))
        assert sw1["status"] == "CANCELLED"

        charges = [c for c in list_all_charges()
                   if c["charge_type"] == "SWITCHING" and c["railcar_id"] == car["id"]]
        assert len(charges) == 1 and charges[0]["status"] == "VOIDED", (
            "the superseded order's switching charge is voided"
        )

        track = get_track(trk["id"])
        assert track["reserved_spots"] == 1, (
            "SO1's reservation released, SO2's added — invariant conserved"
        )


class TestSpotWindowOverlap:
    def test_schedule_rejected_on_physically_occupied_spot(self, api):
        """PRD §3.4: "no other spot order in `REQUESTED`, `SCHEDULED`, or
        `EXECUTED` on the same track with the same `spot_number` may have a
        window that overlaps this order's half-open window, and no railcar may
        currently be `SPOTTED` on that track at that spot number (both
        `ERR_SPOT_WINDOW_OVERLAP`)"

        Design: Difficulty/resource_temporal_overlap/spot_window_half_open_overlap
        """
        set_clock("2026-08-03T09:00:00Z")
        create_facility(name="FT-O1")
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=2)
        car_a = arrive_car(
            create_railcar(cust["id"], prod["id"], lot["id"], car_number="92001")["id"]
        )
        car_b = arrive_car(
            create_railcar(cust["id"], prod["id"], lot["id"], car_number="92002")["id"]
        )
        so_a = create_spot_order_for_car(car_a["id"], trk["id"], 1,
                                         "2026-08-03T10:00:00Z",
                                         "2026-08-03T12:00:00Z")
        schedule_spot_order(so_a["id"])
        set_clock("2026-08-03T10:30:00Z")
        get_success_data(api.execute_spot_order(so_a["id"], YARD))

        # Car A physically occupies spot 1: any window on spot 1 conflicts.
        so_b = create_spot_order_for_car(car_b["id"], trk["id"], 1,
                                         "2026-08-03T14:00:00Z",
                                         "2026-08-03T16:00:00Z")
        validate_error(api.schedule_spot_order(so_b["id"], YARD),
                       ApiErrorId.ERR_SPOT_WINDOW_OVERLAP)
        after = validate_success(api.get_spot_order(so_b["id"], YARD))
        assert after["status"] == "REQUESTED", "rejected schedule leaves the order open"

    def test_schedule_accepted_on_free_spot_after_buffer(self, api):
        """PRD §3.4: "no other spot order in `REQUESTED`, `SCHEDULED`, or
        `EXECUTED` on the same track with the same `spot_number` may have a
        window that overlaps this order's half-open window, and no railcar may
        currently be `SPOTTED` on that track at that spot number (both
        `ERR_SPOT_WINDOW_OVERLAP`)"
        PRD §3.1: "`occupied_spots` is the count of railcars currently
        `SPOTTED` on the track; `reserved_spots` is the count of spot orders in
        `REQUESTED` or `SCHEDULED` on the track."

        Design: Difficulty/resource_temporal_overlap/spot_window_half_open_overlap
        """
        set_clock("2026-08-03T09:00:00Z")
        create_facility(name="FT-O1")
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=2)
        car_a = arrive_car(
            create_railcar(cust["id"], prod["id"], lot["id"], car_number="92001")["id"]
        )
        car_b = arrive_car(
            create_railcar(cust["id"], prod["id"], lot["id"], car_number="92002")["id"]
        )
        so_a = create_spot_order_for_car(car_a["id"], trk["id"], 1,
                                         "2026-08-03T10:00:00Z",
                                         "2026-08-03T12:00:00Z")
        schedule_spot_order(so_a["id"])
        set_clock("2026-08-03T10:30:00Z")
        get_success_data(api.execute_spot_order(so_a["id"], YARD))

        # Spot 2 is free; the new window starts at 12:30, exactly the resident
        # window end (12:00) plus the 30-minute crew buffer.
        so_b2 = create_spot_order_for_car(car_b["id"], trk["id"], 2,
                                          "2026-08-03T12:30:00Z",
                                          "2026-08-03T14:00:00Z")
        ok = validate_success(api.schedule_spot_order(so_b2["id"], YARD))
        assert ok["status"] == "SCHEDULED"

        track = get_track(trk["id"])
        assert track["occupied_spots"] == 1, "car A still spotted"
        assert track["reserved_spots"] == 1, "one open scheduled order"


class TestCrewBuffer:
    def test_crew_window_within_buffer_rejected(self, api):
        """PRD §3.4: "no switch order in `SCHEDULED` on the same track may
        have a window within the facility's `switch_buffer_minutes` of this
        order's window (`ERR_SWITCH_WINDOW_CONFLICT`)"

        Design: Difficulty/resource_temporal_overlap/switch_crew_buffer_semantics
        """
        set_clock("2026-08-03T09:00:00Z")
        create_facility(name="FT-O2")
        cust = create_customer(name="C1", allocated_car_spots=6)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        t1 = create_track(name="T1", spot_capacity=2)
        car_c = arrive_car(
            create_railcar(cust["id"], prod["id"], lot["id"], car_number="93001")["id"]
        )
        car_d = arrive_car(
            create_railcar(cust["id"], prod["id"], lot["id"], car_number="93002")["id"]
        )
        so_c = create_spot_order_for_car(car_c["id"], t1["id"], 1,
                                         "2026-08-03T10:00:00Z",
                                         "2026-08-03T11:00:00Z")
        schedule_spot_order(so_c["id"])
        so_d = create_spot_order_for_car(car_d["id"], t1["id"], 2,
                                         "2026-08-03T11:15:00Z",
                                         "2026-08-03T12:15:00Z")

        # 15-minute gap after the scheduled 10:00-11:00 crew window < 30 buffer
        validate_error(api.schedule_spot_order(so_d["id"], YARD),
                       ApiErrorId.ERR_SWITCH_WINDOW_CONFLICT)

    def test_crew_window_at_exact_buffer_and_other_track_accepted(self, api):
        """PRD §3.4: "no switch order in `SCHEDULED` on the same track may
        have a window within the facility's `switch_buffer_minutes` of this
        order's window (`ERR_SWITCH_WINDOW_CONFLICT`)"

        Design: Difficulty/resource_temporal_overlap/switch_crew_buffer_semantics
        """
        set_clock("2026-08-03T09:00:00Z")
        create_facility(name="FT-O2")
        cust = create_customer(name="C1", allocated_car_spots=6)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        t1 = create_track(name="T1", spot_capacity=2)
        t2 = create_track(name="T2", spot_capacity=1)
        car_c = arrive_car(
            create_railcar(cust["id"], prod["id"], lot["id"], car_number="93001")["id"]
        )
        car_d = arrive_car(
            create_railcar(cust["id"], prod["id"], lot["id"], car_number="93002")["id"]
        )
        car_e = arrive_car(
            create_railcar(cust["id"], prod["id"], lot["id"], car_number="93003")["id"]
        )
        so_c = create_spot_order_for_car(car_c["id"], t1["id"], 1,
                                         "2026-08-03T10:00:00Z",
                                         "2026-08-03T11:00:00Z")
        schedule_spot_order(so_c["id"])

        # Full overlap on a DIFFERENT track: the buffer is per-track
        so_e = create_spot_order_for_car(car_e["id"], t2["id"], 1,
                                         "2026-08-03T10:30:00Z",
                                         "2026-08-03T11:30:00Z")
        ok_e = validate_success(api.schedule_spot_order(so_e["id"], YARD))
        assert ok_e["status"] == "SCHEDULED"

        # Gap exactly equal to the 30-minute buffer is allowed
        so_d = create_spot_order_for_car(car_d["id"], t1["id"], 2,
                                         "2026-08-03T11:30:00Z",
                                         "2026-08-03T12:30:00Z")
        ok_d = validate_success(api.schedule_spot_order(so_d["id"], YARD))
        assert ok_d["status"] == "SCHEDULED"


class TestOptimisticConcurrency:
    def test_occ_spot_order_stale_version_rejected(self, api):
        """PRD §2.8: "Creating a spot order against a railcar requires
        `expected_railcar_version` as a non-optional input, carrying the
        client's last observed `version` of that car. If the railcar's current
        `version` does not match — because another writer has advanced it since
        the client last read the car — the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.4: "The new order then takes its own reservation —
        `Track.reserved_spots` increases by one — starts in `REQUESTED`, and
        bumps `Railcar.version`."

        Design: Corner/cross_cutting_layers/occ_spot_order_stale_version_rejected
        """
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-L1")
        cust = create_customer(name="C1", allocated_car_spots=5)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=2)
        car = arrive_car(
            create_railcar(cust["id"], prod["id"], lot["id"], car_number="97401")["id"]
        )
        stale_version = car["version"]

        so_a = validate_success(
            api.create_spot_order(
                car["id"],
                create_spot_order_payload(
                    expected_railcar_version=stale_version,
                    track_id=trk["id"], spot_number=1,
                    window_start="2026-08-03T10:00:00Z",
                    window_end="2026-08-03T12:00:00Z",
                ),
                YARD,
            ),
            201,
        )
        assert so_a["status"] == "REQUESTED"

        # The first create bumped the car; replaying the stale version is 412
        validate_error(
            api.create_spot_order(
                car["id"],
                create_spot_order_payload(
                    expected_railcar_version=stale_version,
                    track_id=trk["id"], spot_number=2,
                    window_start="2026-08-03T13:00:00Z",
                    window_end="2026-08-03T15:00:00Z",
                ),
                YARD,
            ),
            ApiErrorId.ERR_STALE_VERSION,
        )

        car_after = get_railcar(car["id"])
        assert car_after["version"] == stale_version + 1, (
            "only the successful create bumped the car version"
        )
        so_a_after = validate_success(api.get_spot_order(so_a["id"], YARD))
        assert so_a_after["status"] == "REQUESTED", "no supersede fired"

    def test_occ_allocation_adjustment_stale_and_floor(self, api):
        """PRD §2.8: "Posting a track-space allocation adjustment against a
        customer requires `expected_customer_version` as a non-optional input,
        carrying the client's last observed `version` of that `Customer`. If
        the customer's current `version` does not match, the adjustment is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.1: "the new allocation must be at least the customer's current
        occupied-plus-reserved spots — a `new_allocated_car_spots` below that
        floor is rejected with `ERR_ALLOCATION_BELOW_FLOOR`. On success,
        `allocated_car_spots` is replaced and `Customer.version` increments."

        Design: Corner/cross_cutting_layers/occ_allocation_adjustment_stale_and_floor
        """
        set_clock("2026-08-03T00:00:00Z")
        create_facility(name="FT-L2")
        cust = create_customer(name="C1", allocated_car_spots=2)
        prod = create_product(name="Salt")
        lot = create_lot(cust["id"], prod["id"])
        trk = create_track(name="T1", spot_capacity=2)
        car = arrive_car(
            create_railcar(cust["id"], prod["id"], lot["id"], car_number="97402")["id"]
        )
        # One open reservation -> the customer's occupied+reserved floor is 1
        create_spot_order_for_car(car["id"], trk["id"], 1,
                                  "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z")

        ok = get_success_data(
            api.create_allocation_adjustment(
                cust["id"],
                allocation_adjustment_payload(
                    expected_customer_version=cust["version"],
                    new_allocated_car_spots=3,
                ),
                ADMIN,
            )
        )
        assert ok["allocated_car_spots"] == 3
        assert ok["version"] == cust["version"] + 1

        # Stale replay of the pre-adjustment version -> 412
        validate_error(
            api.create_allocation_adjustment(
                cust["id"],
                allocation_adjustment_payload(
                    expected_customer_version=cust["version"],
                    new_allocated_car_spots=5,
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_STALE_VERSION,
        )

        # Below the occupied+reserved floor of 1 -> 409
        validate_error(
            api.create_allocation_adjustment(
                cust["id"],
                allocation_adjustment_payload(
                    expected_customer_version=ok["version"],
                    new_allocated_car_spots=0,
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_ALLOCATION_BELOW_FLOOR,
        )

        # Floor-equal is allowed (the floor is inclusive: "at least")
        ok2 = get_success_data(
            api.create_allocation_adjustment(
                cust["id"],
                allocation_adjustment_payload(
                    expected_customer_version=ok["version"],
                    new_allocated_car_spots=1,
                ),
                ADMIN,
            )
        )
        assert ok2["allocated_car_spots"] == 1
        assert ok2["version"] == ok["version"] + 1


class TestEquipmentFilters:
    def test_equipment_contamination_audit_filters(self, api):
        """PRD §3.1: "The equipment list endpoint supports a
        contamination-audit filter by `last_product_id` and by `status`,
        alongside `limit` and `offset`."

        Design: Corner/endpoints/fk_reverse_reachability_lists
        """
        ctx = setup_active_transfer(quantity_planned_tons=10.0)
        eq = ctx["equipment"]
        prod = ctx["product"]

        data, meta = validate_paginated(
            api.list_equipment(OPERATOR, params={"last_product_id": prod["id"]})
        )
        assert [e["id"] for e in data] == [eq["id"]]
        assert meta["total_count"] == 1

        data, _ = validate_paginated(
            api.list_equipment(OPERATOR, params={"status": "IN_USE"})
        )
        assert [e["id"] for e in data] == [eq["id"]]

        data, meta = validate_paginated(
            api.list_equipment(OPERATOR, params={"status": "AVAILABLE"})
        )
        assert data == [] and meta["total_count"] == 0
