"""Harvest lots, window/refrigeration/vehicle constraints (PRD §3.1, §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    cancel_event,
    coordinator_headers,
    create_event_payload,
    create_lot_payload,
    create_offer_payload,
    finish_event,
    get_container,
    get_event,
    get_lot,
    get_vehicle,
    make_crew_leader_headers,
    new_crew_leader,
    new_event,
    new_farm,
    new_offer,
    new_vehicle,
    publish_event,
    reject_lot,
    setup_in_progress_event,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    verify_lot,
)


class TestEventCreationGates:
    def test_refrigeration_mismatch_at_event_creation(self, api):
        """PRD §3.3: "Refrigeration matching: the offer's `requires_refrigeration` flag
        must equal the vehicle's `refrigerated` flag, otherwise
        `ERR_VEHICLE_REFRIGERATION_MISMATCH`."

        Design: Corner/validations/refrigeration_mismatch_event_creation
        """
        farm = new_farm(farm_name="RM", county_code="RM1")
        vehicle = new_vehicle(refrigerated=False)
        lead = new_crew_leader()
        offer = new_offer(farm["id"], crop_code="LEAFY_GREENS",
                          perishability_class="HIGH", requires_refrigeration=True)
        resp = api.create_event(
            create_event_payload(offer["id"], lead["id"], vehicle["id"]),
            coordinator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_VEHICLE_REFRIGERATION_MISMATCH, 422)

    def test_event_window_containment_closed_upper_bound(self, api):
        """PRD §3.3: "Window containment: `scheduled_start` must fall on or after the
        offer's `window_start`, `scheduled_end` must fall on or before the offer's
        `window_end`, and the start must be strictly before the end — otherwise
        `ERR_EVENT_WINDOW_OUTSIDE_OFFER`."

        Design: Corner/validations/event_window_outside_offer
        """
        farm = new_farm(farm_name="EW", county_code="EW1")
        vehicle = new_vehicle()
        lead = new_crew_leader()
        offer = new_offer(farm["id"], window_start="2026-08-05T00:00:00Z",
                          window_end="2026-08-10T00:00:00Z")
        ok = api.create_event(
            create_event_payload(offer["id"], lead["id"], vehicle["id"],
                                 scheduled_start="2026-08-09T08:00:00Z",
                                 scheduled_end="2026-08-10T00:00:00Z"),
            coordinator_headers(),
        )
        validate_success(ok, 201)  # scheduled_end == window_end is allowed
        bad = api.create_event(
            create_event_payload(offer["id"], lead["id"], vehicle["id"],
                                 scheduled_start="2026-08-09T08:00:00Z",
                                 scheduled_end="2026-08-10T00:00:01Z"),
            coordinator_headers(),
        )
        validate_error(bad, ApiErrorId.ERR_EVENT_WINDOW_OUTSIDE_OFFER, 422)


class TestLotConstraints:
    def test_segregation_of_duties_on_verify(self, api):
        """PRD §3.3: "verifying a `PENDING` lot supplies `verified_by_coordinator_id`,
        which must differ from the lot's `recorded_by_volunteer_id`
        (`ERR_SEGREGATION_OF_DUTIES`)"

        Design: Corner/validations/segregation_of_duties_lot_verify
        """
        ctx = setup_in_progress_event(lot_specs=[{"gross": 60.0, "cull": 0.0}])
        lot = ctx["lots"][0]
        resp = api.verify_lot(
            lot["id"], {"verified_by_coordinator_id": ctx["lead"]["id"]},
            coordinator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 422)
        assert get_lot(lot["id"])["status"] == "PENDING"

    def test_cull_equal_to_net_is_allowed_and_over_is_rejected(self, api):
        """PRD §3.3: "`cull_lbs` for field-culled non-food pounds (at least zero, and
        never more than the gross weight minus the tare weight — an excess is rejected
        with `ERR_CULL_EXCEEDS_NET`)"

        Design: Corner/validations/cull_exceeds_net_rejection
        """
        ctx = setup_in_progress_event()
        event_id = ctx["event"]["id"]
        cont_id = ctx["containers"][0]["id"]
        lead = ctx["lead"]
        ok = api.create_lot(
            create_lot_payload(event_id, cont_id, lead["id"], gross_lbs=100.0,
                               cull_lbs=90.0),
            make_crew_leader_headers(lead["id"]),
        )
        lot = validate_success(ok, 201)
        assert lot["net_lbs"] == pytest.approx(0.0), "cull == gross - tare nets to zero"
        bad = api.create_lot(
            create_lot_payload(event_id, cont_id, lead["id"], gross_lbs=100.0,
                               cull_lbs=90.1),
            make_crew_leader_headers(lead["id"]),
        )
        validate_error(bad, ApiErrorId.ERR_CULL_EXCEEDS_NET, 422)

    def test_verify_already_verified_lot_rejected(self, api):
        """PRD §3.3: "Verification is a coordinator's act and a second pair of eyes:
        verifying a `PENDING` lot supplies `verified_by_coordinator_id`"
        PRD §2.6: "4. **State compatibility** — the target resource must be in a state
        that permits the requested transition, failing with `ERR_INVALID_STATE` (HTTP
        409)."

        Design: Corner/state_machines/lot_invalid_from_verified_verify_again
        """
        ctx = setup_in_progress_event(lot_specs=[{"gross": 60.0, "cull": 0.0,
                                                  "verify": True}])
        lot = ctx["lots"][0]
        assert lot["status"] == "VERIFIED"
        resp = api.verify_lot(
            lot["id"], {"verified_by_coordinator_id": ctx["coord"]["id"]},
            coordinator_headers(),
        )
        assert resp.status_code == 409
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ALREADY_TERMINAL]
        )
        assert get_lot(lot["id"])["status"] == "VERIFIED"


class TestLotWeightMath:
    def test_net_weight_and_tare_default_from_container(self, api):
        """PRD §3.3: "an optional `tare_lbs` that defaults to the referenced
        container's own `tare_lbs` when omitted"
        PRD §3.3: "The system computes `net_lbs` as the gross weight minus the tare
        weight minus the cull weight, with inputs rounded per §2.8."

        Design: Corner/calculations/net_lot_weight_correct_result
        """
        ctx = setup_in_progress_event(
            container_over={"tare_lbs": 12.5},
            lot_specs=[{"gross": 100.0, "cull": 7.5}],
        )
        lot = ctx["lots"][0]
        assert lot["tare_lbs"] == pytest.approx(12.5), "tare defaults from the container"
        assert lot["net_lbs"] == pytest.approx(80.0), "100.0 - 12.5 - 7.5"

    def test_only_verified_lots_count_toward_harvest_total(self, api):
        """PRD §3.3: "recomputes the event's `total_harvested_lbs` as the sum of
        `net_lbs` over its `VERIFIED` lots only — `PENDING` and `REJECTED` lots never
        count."

        Design: Corner/calculations/actual_poundage_input_set_filtering
        """
        ctx = setup_in_progress_event(
            offer_over={"estimated_lbs": 200.0},
            container_count=3,
            lot_specs=[
                {"gross": 60.0, "verify": True},    # net 50.0
                {"gross": 80.0, "reject": True},    # net 70.0, excluded
                {"gross": 40.0},                    # net 30.0 PENDING, excluded
            ],
        )
        event = finish_event(ctx["event"]["id"], ctx["lead"]["id"])
        assert event["total_harvested_lbs"] == pytest.approx(50.0)

    def test_reject_reconciles_harvest_total_to_verified_only(self, api):
        """PRD §3.3: "A coordinator may instead reject a pending lot, moving it to
        `REJECTED`."
        PRD §3.3: "the event's `total_harvested_lbs` as the sum of `net_lbs` over its
        `VERIFIED` lots only — `PENDING` and `REJECTED` lots never count."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_on_reject
        """
        ctx = setup_in_progress_event(
            offer_over={"estimated_lbs": 150.0},
            container_count=2,
            lot_specs=[
                {"gross": 70.0, "verify": True},   # net 60.0
                {"gross": 50.0},                   # net 40.0 PENDING
            ],
        )
        reject_lot(ctx["lots"][1]["id"])
        event = get_event(ctx["event"]["id"])
        assert event["total_harvested_lbs"] == pytest.approx(60.0), (
            "the rejected lot contributes nothing to the derived total"
        )


class TestVehiclePayloadCascade:
    def _payload_setup(self, api):
        return setup_in_progress_event(
            offer_over={"estimated_lbs": 1500.0},
            vehicle_over={"payload_capacity_lbs": 1000.0},
            container_count=2,
            container_over={"capacity_lbs": 700.0},
            lot_specs=[{"gross": 610.0}, {"gross": 510.0}],  # net 600.0 / 500.0
        )

    def test_verify_moves_container_in_use_and_recomputes_total(self, api):
        """PRD §3.3: "A successful verification moves the lot to `VERIFIED`,
        transitions the referenced container from `AVAILABLE` to `IN_USE`, and
        recomputes the event's `total_harvested_lbs` as the sum of `net_lbs` over its
        `VERIFIED` lots only"

        Design: Difficulty/transitive_cascade/lot_verify_container_inuse_depth2
        """
        ctx = self._payload_setup(api)
        lot1 = ctx["lots"][0]
        verified = verify_lot(lot1["id"], ctx["coord"]["id"])
        assert verified["status"] == "VERIFIED"
        assert get_container(ctx["containers"][0]["id"])["status"] == "IN_USE"
        assert get_event(ctx["event"]["id"])["total_harvested_lbs"] == pytest.approx(600.0)

    def test_next_verify_rejected_when_payload_exceeded(self, api):
        """PRD §3.3: "Verification also runs the payload check — the sum of `net_lbs`
        across the event's `VERIFIED` lots, including the one being verified, may not
        exceed the assigned vehicle's `payload_capacity_lbs`, although a total exactly
        equal to the capacity is allowed; an excess is rejected with
        `ERR_VEHICLE_PAYLOAD_EXCEEDED`."

        Design: Difficulty/transitive_cascade/lot_verify_container_inuse_depth2
        """
        ctx = self._payload_setup(api)
        lot1, lot2 = ctx["lots"]
        verify_lot(lot1["id"], ctx["coord"]["id"])
        resp = api.verify_lot(
            lot2["id"], {"verified_by_coordinator_id": ctx["coord"]["id"]},
            coordinator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_VEHICLE_PAYLOAD_EXCEEDED, 422)
        assert get_lot(lot2["id"])["status"] == "PENDING"
        assert get_event(ctx["event"]["id"])["total_harvested_lbs"] == pytest.approx(600.0)


class TestOfferWindowAdjacency:
    def test_adjacent_offer_window_permitted(self, api):
        """PRD §3.1: "a farm may not hold two non-terminal offers for the same
        `crop_code` whose half-open harvest windows overlap, although adjacency — one
        window ending exactly when the other begins — is permitted."

        Design: Difficulty/resource_temporal_overlap/offer_window_half_open_adjacency
        """
        farm = new_farm(farm_name="FM", county_code="MMM")
        new_offer(farm["id"], window_start="2026-08-05T00:00:00Z",
                  window_end="2026-08-10T00:00:00Z")
        resp = api.create_offer(
            create_offer_payload(farm["id"], estimated_lbs=80.0,
                                 window_start="2026-08-10T00:00:00Z",
                                 window_end="2026-08-15T00:00:00Z"),
            coordinator_headers(),
        )
        offer_b = validate_success(resp, 201)
        assert offer_b["status"] == "OFFERED"

    def test_overlapping_offer_window_rejected(self, api):
        """PRD §3.1: "A violating publish is rejected with
        `ERR_OFFER_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/offer_window_half_open_adjacency
        """
        farm = new_farm(farm_name="FM2", county_code="MM2")
        new_offer(farm["id"], window_start="2026-08-05T00:00:00Z",
                  window_end="2026-08-10T00:00:00Z")
        resp = api.create_offer(
            create_offer_payload(farm["id"], estimated_lbs=60.0,
                                 window_start="2026-08-09T23:59:59Z",
                                 window_end="2026-08-16T00:00:00Z"),
            coordinator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_WINDOW_OVERLAP, 422)


class TestVehicleScheduleOverlap:
    def _vehicle_overlap_setup(self):
        farm = new_farm(farm_name="FO", county_code="OOO")
        vehicle = new_vehicle()
        lead = new_crew_leader()
        offer_1 = new_offer(farm["id"], crop_code="ROOT_VEG")
        offer_2 = new_offer(farm["id"], crop_code="APPLES")
        ev1 = new_event(offer_1["id"], lead["id"], vehicle["id"],
                        scheduled_start="2026-08-10T08:00:00Z",
                        scheduled_end="2026-08-10T12:00:00Z")
        publish_event(ev1["id"])
        return {"farm": farm, "vehicle": vehicle, "lead": lead,
                "offer_1": offer_1, "offer_2": offer_2, "ev1": ev1}

    def test_cancelled_event_frees_vehicle_despite_geometric_overlap(self, api):
        """PRD §3.3: "the assigned vehicle may not already sit on another event in
        `OPEN`, `FULL`, `IN_PROGRESS`, or `HARVESTED` whose half-open schedule
        interval overlaps this one — adjacency permitted — on pain of
        `ERR_VEHICLE_SCHEDULE_CONFLICT`."
        PRD §3.3: "Cancelling an `OPEN` event declines its `PENDING` and `CONFIRMED`
        assignments and returns the vehicle from `ASSIGNED` to `AVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/vehicle_assignment_state_gated_overlap
        """
        ctx = self._vehicle_overlap_setup()
        cancel_event(ctx["ev1"]["id"])
        assert get_vehicle(ctx["vehicle"]["id"])["status"] == "AVAILABLE"
        ev2 = new_event(ctx["offer_2"]["id"], ctx["lead"]["id"], ctx["vehicle"]["id"],
                        scheduled_start="2026-08-10T09:00:00Z",
                        scheduled_end="2026-08-10T13:00:00Z")
        published = publish_event(ev2["id"])
        assert published["status"] == "OPEN", (
            "a CANCELLED event does not occupy the vehicle"
        )

    def test_open_event_blocks_overlapping_vehicle_reuse(self, api):
        """PRD §3.3: "Vehicle scheduling: the assigned vehicle may not already sit on
        another event in `OPEN`, `FULL`, `IN_PROGRESS`, or `HARVESTED` whose half-open
        schedule interval overlaps this one — adjacency permitted — on pain of
        `ERR_VEHICLE_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/vehicle_assignment_state_gated_overlap
        """
        ctx = self._vehicle_overlap_setup()
        cancel_event(ctx["ev1"]["id"])
        ev2 = new_event(ctx["offer_2"]["id"], ctx["lead"]["id"], ctx["vehicle"]["id"],
                        scheduled_start="2026-08-10T09:00:00Z",
                        scheduled_end="2026-08-10T13:00:00Z")
        publish_event(ev2["id"])
        resp = api.create_event(
            create_event_payload(ctx["offer_2"]["id"], ctx["lead"]["id"],
                                 ctx["vehicle"]["id"],
                                 scheduled_start="2026-08-10T10:00:00Z",
                                 scheduled_end="2026-08-10T14:00:00Z"),
            coordinator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_VEHICLE_SCHEDULE_CONFLICT, 422)
