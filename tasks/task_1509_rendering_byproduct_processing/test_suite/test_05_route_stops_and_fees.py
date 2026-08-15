"""Route stops: creation rules, pickup fees, collection and void (PRD §2.11, §3.4)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    add_stop,
    assert_batch,
    assert_stop,
    create_active_agreement,
    create_plant,
    create_route,
    create_supplier,
    create_vehicle,
    get_batch_for_stop,
    get_settlement,
    read_route_version,
    setup_collected_stop,
    setup_dispatched_route_with_arrived_stop,
    setup_planned_route_with_stop,
    setup_plant_with_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
RD = TEST_USERS["route_dispatcher_headers"]
ANY = TEST_USERS["any_headers"]

BOGUS_1 = "00000000-0000-0000-0000-000000000001"
BOGUS_2 = "00000000-0000-0000-0000-000000000002"
BOGUS_3 = "00000000-0000-0000-0000-000000000003"


def _stop_payload(route_id, supplier_id, agreement_id, plant_id, version, **overrides):
    from test_helpers import create_stop_payload

    return create_stop_payload(
        route_id, supplier_id, agreement_id, plant_id, version, **overrides
    )


class TestStopCreationExistence:
    def test_stop_create_with_unknown_route_rejected(self, api):
        """PRD §2.9: "Every identifier in the path must exist, then every foreign-key
        identifier in the body must exist, validated left-to-right — path first, then body
        fields in their declared order. The first missing resource yields its specific 404:
        ... `ERR_ROUTE_NOT_FOUND`, ..."

        Design: Corner/entities/stop_create_with_unknown_route_rejected
        """
        plant, supplier, agreement = setup_plant_with_agreement()
        vehicle = create_vehicle(plant["id"])
        route = create_route(plant["id"], vehicle["id"])

        payload = _stop_payload(
            NON_EXISTENT_UUID, supplier["id"], agreement["id"], plant["id"],
            route["version"],
        )
        res = api.create_route_stop(payload, RD)
        validate_error(res, ApiErrorId.ERR_ROUTE_NOT_FOUND, expected_status=404)

    def test_stop_create_existence_left_to_right(self, api):
        """PRD §2.9: "Every identifier in the path must exist, then every foreign-key
        identifier in the body must exist, validated left-to-right — path first, then body
        fields in their declared order. The first missing resource yields its specific 404:
        ... `ERR_ROUTE_NOT_FOUND`, ... `ERR_SUPPLIER_NOT_FOUND`, ..."
        PRD §3.4: "The create payload carries the `route_id`, the `supplier_id`, the
        `agreement_id` of an agreement belonging to that supplier, a `plant_id` equal to the
        route's plant, ..."

        Design: Corner/validations/stop_create_existence_left_to_right
        """
        plant = create_plant()
        vehicle = create_vehicle(plant["id"])
        route = create_route(plant["id"], vehicle["id"])

        # route_id, supplier_id and agreement_id are all bogus; route_id is declared
        # first in the payload, so its 404 is the one reported.
        payload = _stop_payload(BOGUS_1, BOGUS_2, BOGUS_3, plant["id"], route["version"])
        res = api.create_route_stop(payload, RD)
        validate_error(res, ApiErrorId.ERR_ROUTE_NOT_FOUND, expected_status=404)


class TestStopCreationBusinessRules:
    def test_stop_window_outside_route_rejected(self, api):
        """PRD §3.4: "... the planned arrival window from `scheduled_window_start` to a
        strictly later `scheduled_window_end` (both must fall within the route's
        departure-to-return window, else `ERR_WINDOW_OUTSIDE_ROUTE`), ..."

        Design: Corner/validations/stop_window_outside_route_rejected
        """
        plant, supplier, agreement = setup_plant_with_agreement()
        vehicle = create_vehicle(plant["id"])
        route = create_route(plant["id"], vehicle["id"])

        payload = _stop_payload(
            route["id"], supplier["id"], agreement["id"], plant["id"], route["version"],
            scheduled_window_start="2026-08-10T17:00:00Z",
            scheduled_window_end="2026-08-10T19:00:00Z",
        )
        res = api.create_route_stop(payload, RD)
        validate_error(res, ApiErrorId.ERR_WINDOW_OUTSIDE_ROUTE, expected_status=422)

        # The rejected stop mutated nothing: no stops, and the route version is unchanged.
        stops, meta = validate_paginated(
            api.list_route_stops(ANY, params={"route_id": route["id"]})
        )
        assert stops == []
        assert meta["total_count"] == 0
        route_after = validate_success(api.get_collection_route(route["id"], ANY), 200)
        assert route_after["version"] == route["version"]

    def test_agreement_not_in_effect_for_service_date(self, api):
        """PRD §3.4: "... the route's `service_date` must lie within the agreement's
        `effective_from`-to-`effective_to` window (`ERR_AGREEMENT_NOT_IN_EFFECT`), ..."

        Design: Corner/validations/agreement_not_in_effect_for_service_date
        """
        plant = create_plant()
        supplier = create_supplier(plant["id"])
        agreement = create_active_agreement(
            plant["id"], supplier["id"],
            effective_from="2026-08-01", effective_to="2026-08-31",
        )
        vehicle = create_vehicle(plant["id"])
        route = create_route(
            plant["id"], vehicle["id"], service_date="2026-09-01",
            scheduled_departure="2026-09-01T06:00:00Z",
            scheduled_return="2026-09-01T18:00:00Z",
        )
        payload = _stop_payload(
            route["id"], supplier["id"], agreement["id"], plant["id"], route["version"],
            scheduled_window_start="2026-09-01T08:00:00Z",
            scheduled_window_end="2026-09-01T09:00:00Z",
        )
        res = api.create_route_stop(payload, RD)
        validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_IN_EFFECT, expected_status=422)

    def test_dead_stock_stop_rejected_when_agreement_declines(self, api):
        """PRD §3.4: "... and a stop marked `is_dead_stock` requires the agreement to accept
        dead stock (`ERR_DEAD_STOCK_NOT_ACCEPTED`)."

        Design: Corner/validations/dead_stock_stop_rejected_when_agreement_declines
        """
        # Default agreement factory sets accepts_dead_stock False.
        plant, supplier, agreement = setup_plant_with_agreement()
        assert agreement["accepts_dead_stock"] is False
        vehicle = create_vehicle(plant["id"])
        route = create_route(plant["id"], vehicle["id"])
        payload = _stop_payload(
            route["id"], supplier["id"], agreement["id"], plant["id"], route["version"],
            is_dead_stock=True,
        )
        res = api.create_route_stop(payload, RD)
        validate_error(res, ApiErrorId.ERR_DEAD_STOCK_NOT_ACCEPTED, expected_status=422)

    def test_species_out_of_scope_rejected(self, api):
        """PRD §3.4: "... the `species_tag` must appear in the agreement's `species_scope`
        (`ERR_SPECIES_OUT_OF_SCOPE`), ..."

        Design: Corner/validations/species_out_of_scope_rejected
        """
        plant, supplier, agreement = setup_plant_with_agreement()  # scope [BOVINE]
        vehicle = create_vehicle(plant["id"])
        route = create_route(plant["id"], vehicle["id"])
        payload = _stop_payload(
            route["id"], supplier["id"], agreement["id"], plant["id"], route["version"],
            species_tag="POULTRY",
        )
        res = api.create_route_stop(payload, RD)
        validate_error(res, ApiErrorId.ERR_SPECIES_OUT_OF_SCOPE, expected_status=422)

    def test_duplicate_stop_sequence_rejected(self, api):
        """PRD §3.4: "... a `sequence_no` of at least 1 that must be unique within the route
        among non-`CANCELLED` stops (`ERR_DUPLICATE_STOP_SEQUENCE`), ..."

        Design: Corner/validations/duplicate_stop_sequence_rejected
        """
        plant, supplier, agreement = setup_plant_with_agreement()
        vehicle = create_vehicle(plant["id"])
        route = create_route(plant["id"], vehicle["id"])
        add_stop(route["id"], supplier["id"], agreement["id"], plant["id"], sequence_no=1)

        payload = _stop_payload(
            route["id"], supplier["id"], agreement["id"], plant["id"],
            read_route_version(route["id"]),
            sequence_no=1,
            scheduled_window_start="2026-08-10T10:00:00Z",
            scheduled_window_end="2026-08-10T11:00:00Z",
            estimated_weight_lbs=4000,
            estimated_distance_miles=5,
        )
        res = api.create_route_stop(payload, RD)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_STOP_SEQUENCE, expected_status=422)


class TestRouteCapacityBoundary:
    def _setup_capacity_route(self, api):
        plant, supplier, agreement = setup_plant_with_agreement()
        vehicle = create_vehicle(plant["id"], capacity_lbs=40000)
        route = create_route(plant["id"], vehicle["id"])
        return plant, supplier, agreement, vehicle, route

    def test_route_capacity_exact_fit_accepted(self, api):
        """PRD §3.4: "Capacity is checked in aggregate: the planned load — the sum of
        `estimated_weight_lbs` over the route's stops currently `SCHEDULED` or `ARRIVED`,
        plus the new stop's own estimate — must not exceed the vehicle's `capacity_lbs`.
        Equality is allowed; one pound over returns `ERR_ROUTE_OVER_CAPACITY`."

        Design: Difficulty/boundary_precision_check/route_capacity_exact_fit
        """
        plant, supplier, agreement, vehicle, route = self._setup_capacity_route(api)
        stop1 = add_stop(route["id"], supplier["id"], agreement["id"], plant["id"],
                         sequence_no=1, estimated_weight_lbs=25000)
        stop2 = add_stop(route["id"], supplier["id"], agreement["id"], plant["id"],
                         sequence_no=2, estimated_weight_lbs=15000,
                         scheduled_window_start="2026-08-10T10:00:00Z",
                         scheduled_window_end="2026-08-10T11:00:00Z")
        assert stop1["status"] == "SCHEDULED"
        assert stop2["status"] == "SCHEDULED"
        stops, meta = validate_paginated(
            api.list_route_stops(ANY, params={"route_id": route["id"]})
        )
        assert meta["total_count"] == 2

    def test_route_capacity_one_pound_over_rejected(self, api):
        """PRD §3.4: "Capacity is checked in aggregate: the planned load — the sum of
        `estimated_weight_lbs` over the route's stops currently `SCHEDULED` or `ARRIVED`,
        plus the new stop's own estimate — must not exceed the vehicle's `capacity_lbs`.
        Equality is allowed; one pound over returns `ERR_ROUTE_OVER_CAPACITY`."

        Design: Difficulty/boundary_precision_check/route_capacity_exact_fit
        """
        plant, supplier, agreement, vehicle, route = self._setup_capacity_route(api)
        add_stop(route["id"], supplier["id"], agreement["id"], plant["id"],
                 sequence_no=1, estimated_weight_lbs=25000)
        add_stop(route["id"], supplier["id"], agreement["id"], plant["id"],
                 sequence_no=2, estimated_weight_lbs=15000,
                 scheduled_window_start="2026-08-10T10:00:00Z",
                 scheduled_window_end="2026-08-10T11:00:00Z")
        # 40000 lbs planned == capacity; one more pound overflows.
        payload = _stop_payload(
            route["id"], supplier["id"], agreement["id"], plant["id"],
            read_route_version(route["id"]),
            sequence_no=3,
            scheduled_window_start="2026-08-10T12:00:00Z",
            scheduled_window_end="2026-08-10T13:00:00Z",
            estimated_weight_lbs=1,
            estimated_distance_miles=1,
        )
        res = api.create_route_stop(payload, RD)
        validate_error(res, ApiErrorId.ERR_ROUTE_OVER_CAPACITY, expected_status=422)

        stops, meta = validate_paginated(
            api.list_route_stops(ANY, params={"route_id": route["id"]})
        )
        assert meta["total_count"] == 2


class TestStopTerminalTransitions:
    def test_route_cancel_with_collected_stop_rejected(self, api):
        """PRD §3.4: "Manual cancellation is available from `PLANNED`, `DISPATCHED`, or
        `IN_PROGRESS` but is refused while any stop is `COLLECTED`
        (`ERR_ROUTE_HAS_COLLECTED_STOPS`) — such stops must first be delivered or voided —
        and cancels every `SCHEDULED` or `ARRIVED` stop."

        Design: Corner/state_machines/route_cancel_with_collected_stop_rejected
        """
        ctx = setup_collected_stop(actual_weight_lbs=5000, actual_distance_miles=20)
        assert ctx["stop"]["status"] == "COLLECTED"

        res = api.cancel_route(ctx["route"]["id"], RD)
        validate_error(res, ApiErrorId.ERR_ROUTE_HAS_COLLECTED_STOPS, expected_status=409)
        mid = validate_success(api.get_collection_route(ctx["route"]["id"], ANY), 200)
        assert mid["status"] == "IN_PROGRESS"

        # Voiding the collected stop unblocks cancellation.
        voided = validate_success(api.void_stop(ctx["stop"]["id"], RD), 200)
        assert voided["status"] == "VOIDED"
        cancelled = validate_success(api.cancel_route(ctx["route"]["id"], RD), 200)
        assert cancelled["status"] == "CANCELLED"

    def test_stop_void_from_scheduled_rejected(self, api):
        """PRD §3.4: "Attempting to void from any stop state other than `COLLECTED` or
        `DELIVERED` returns `ERR_STOP_INVALID_STATE`."

        Design: Corner/state_machines/stop_void_from_scheduled_rejected
        """
        ctx = setup_planned_route_with_stop()
        assert ctx["stop"]["status"] == "SCHEDULED"

        res = api.void_stop(ctx["stop"]["id"], RD)
        validate_error(res, ApiErrorId.ERR_STOP_INVALID_STATE, expected_status=409)

        fetched = validate_success(api.get_route_stop(ctx["stop"]["id"], ANY), 200)
        assert fetched["status"] == "SCHEDULED"


class TestPickupFeeDualVariant:
    def _setup_two_stop_route(self, api):
        """Agreement: base 15000, 3/lb, 250/mi, dead-stock surcharge 7500,
        minimum_volume_lbs 20000, discount 0.05. Stop1 (dead stock) and stop2
        (regular), both ARRIVED on a dispatched route."""
        plant = create_plant()
        supplier = create_supplier(plant["id"])
        agreement = create_active_agreement(
            plant["id"], supplier["id"],
            prohibited_material_policy="ZERO_TOLERANCE",
            accepts_dead_stock=True,
            pickup_base_fee_cents=15000,
            per_lb_fee_cents=3,
            mileage_rate_cents=250,
            dead_stock_surcharge_cents=7500,
            minimum_volume_lbs=20000,
            volume_discount_pct=0.05,
        )
        vehicle = create_vehicle(plant["id"])
        route = create_route(plant["id"], vehicle["id"])
        stop1 = add_stop(
            route["id"], supplier["id"], agreement["id"], plant["id"],
            sequence_no=1, estimated_weight_lbs=8000, estimated_distance_miles=40,
            is_dead_stock=True,
        )
        stop2 = add_stop(
            route["id"], supplier["id"], agreement["id"], plant["id"],
            sequence_no=2, estimated_weight_lbs=12000, estimated_distance_miles=10,
            scheduled_window_start="2026-08-10T10:00:00Z",
            scheduled_window_end="2026-08-10T11:00:00Z",
        )
        validate_success(api.dispatch_route(route["id"], RD), 200)
        validate_success(api.arrive_stop(stop1["id"], RD), 200)
        validate_success(api.arrive_stop(stop2["id"], RD), 200)
        return plant, supplier, agreement, route, stop1, stop2

    def test_pickup_fee_provisional_uses_estimates_no_discount(self, api):
        """PRD §3.4: "its creation increments the route's `version` by one, and the server
        records a `provisional_fee_cents` estimate: the agreement's `pickup_base_fee_cents`,
        plus `estimated_weight_lbs` times `per_lb_fee_cents`, plus `estimated_distance_miles`
        times `mileage_rate_cents`, plus `dead_stock_surcharge_cents` when the stop is a
        dead-stock pickup. The provisional estimate never includes the volume discount."

        Design: Difficulty/dual_variant_calc/pickup_fee_provisional_vs_final
        """
        plant, supplier, agreement, route, stop1, stop2 = self._setup_two_stop_route(api)
        # Provisional (estimated): stop1 = 15000 + 8000*3 + 40*250 + 7500 = 56500.
        assert stop1["provisional_fee_cents"] == 56500
        # Provisional: stop2 = 15000 + 12000*3 + 10*250 = 53500 (no discount, ever).
        assert stop2["provisional_fee_cents"] == 53500

    def test_pickup_fee_final_settles_with_volume_discount(self, api):
        """PRD §3.4: "The stop becomes `COLLECTED` and the server settles its
        `final_fee_cents`: the agreement's `pickup_base_fee_cents`, plus `actual_weight_lbs`
        times `per_lb_fee_cents`, plus `actual_distance_miles` times `mileage_rate_cents`,
        plus `dead_stock_surcharge_cents` when the stop is a dead-stock pickup — and then,
        when the agreement's `minimum_volume_lbs` is greater than zero and the supplier's
        current-period collected volume reaches or exceeds that minimum, a discount equal to
        the subtotal times `volume_discount_pct`, rounded half-up to whole cents, is
        subtracted."
        PRD §3.4: "Financially, the current period settlement's `pickup_fees_accrued_cents`
        increases by the final fee, its `transport_costs_cents` increases by the actual miles
        times the fleet transport rate of 150 cents per mile, and the supplier's
        `outstanding_service_fees_cents` increases by the final fee."

        Design: Difficulty/dual_variant_calc/pickup_fee_provisional_vs_final
        """
        plant, supplier, agreement, route, stop1, stop2 = self._setup_two_stop_route(api)

        # Stop 1: subtotal 15000 + 8400*3 + 44*250 + 7500 = 58700; cumulative volume
        # 8400 < 20000, so no discount.
        collected1 = validate_success(
            api.collect_stop(stop1["id"], {"actual_weight_lbs": 8400,
                                           "actual_distance_miles": 44,
                                           "temperature_f": 65.0}, RD),
            201,
        )
        assert collected1["final_fee_cents"] == 58700
        assert collected1["status"] == "COLLECTED"

        # Stop 2: subtotal 53500; cumulative 8400 + 12000 = 20400 >= 20000, so the
        # discount round_half_up(53500 * 0.05) = 2675 applies: 53500 - 2675 = 50825.
        collected2 = validate_success(
            api.collect_stop(stop2["id"], {"actual_weight_lbs": 12000,
                                           "actual_distance_miles": 10,
                                           "temperature_f": 60.0}, RD),
            201,
        )
        assert collected2["final_fee_cents"] == 50825

        settlement = get_settlement(plant["id"], period_index=1)
        assert settlement["pickup_fees_accrued_cents"] == 109525  # 58700 + 50825
        assert settlement["transport_costs_cents"] == 8100  # (44 + 10) * 150

        supplier_after = validate_success(api.get_supplier(supplier["id"], ANY), 200)
        assert supplier_after["outstanding_service_fees_cents"] == 109525


class TestCollectVoidConservation:
    def test_collect_accrues_fee_and_transport(self, api):
        """PRD §2.11: "The current period settlement's `pickup_fees_accrued_cents` tracks
        the running sum of `final_fee_cents` over the period's collected and delivered
        stops, minus reversals."
        PRD §3.4: "Financially, the current period settlement's `pickup_fees_accrued_cents`
        increases by the final fee, its `transport_costs_cents` increases by the actual miles
        times the fleet transport rate of 150 cents per mile, and the supplier's
        `outstanding_service_fees_cents` increases by the final fee."

        Design: Difficulty/compensating_invariant/collect_void_fee_conservation
        """
        # Agreement: base 10000, 2/lb, 100/mi, no surcharge, no volume discount.
        ctx = setup_collected_stop(actual_weight_lbs=5000, actual_distance_miles=20)
        # Final fee = 10000 + 5000*2 + 20*100 = 22000.
        assert ctx["stop"]["final_fee_cents"] == 22000
        assert ctx["stop"]["status"] == "COLLECTED"

        settlement = get_settlement(ctx["plant"]["id"], period_index=1)
        assert settlement["pickup_fees_accrued_cents"] == 22000
        assert settlement["transport_costs_cents"] == 3000  # 20 * 150

        supplier = validate_success(api.get_supplier(ctx["supplier"]["id"], ANY), 200)
        assert supplier["outstanding_service_fees_cents"] == 22000

    def test_void_restores_accruals_exactly(self, api):
        """PRD §2.11: "Collecting a stop and later voiding that same stop must leave
        `pickup_fees_accrued_cents`, `transport_costs_cents`, and the supplier's
        `outstanding_service_fees_cents` exactly at their pre-collection values."
        PRD §3.4: "Voiding moves the stop to `VOIDED`, subtracts the final fee from
        `pickup_fees_accrued_cents`, subtracts the actual miles times 150 cents from
        `transport_costs_cents`, subtracts the final fee from the supplier's
        `outstanding_service_fees_cents`, and moves the linked batch to `REJECTED` —
        exactly restoring the pre-collection ledger per §2.11."

        Design: Difficulty/compensating_invariant/collect_void_fee_conservation
        """
        ctx = setup_collected_stop(actual_weight_lbs=5000, actual_distance_miles=20)

        voided = validate_success(api.void_stop(ctx["stop"]["id"], RD), 200)
        assert voided["status"] == "VOIDED"

        settlement = get_settlement(ctx["plant"]["id"], period_index=1)
        assert settlement["pickup_fees_accrued_cents"] == 0
        assert settlement["transport_costs_cents"] == 0

        supplier = validate_success(api.get_supplier(ctx["supplier"]["id"], ANY), 200)
        assert supplier["outstanding_service_fees_cents"] == 0

        batch = validate_success(api.get_inbound_batch(ctx["batch"]["id"], ANY), 200)
        assert batch["status"] == "REJECTED"


class TestProvisionalFeeFiltering:
    def test_provisional_fee_never_discounted(self, api):
        """PRD §3.4: "The provisional estimate never includes the volume discount."
        PRD §3.4: "The supplier's current-period collected volume is the sum of
        `actual_weight_lbs` over this supplier's stops collected into the current period —
        the period whose `period_index` equals the plant's `current_period_index` —
        including this stop."

        Design: Corner/calculations/provisional_fee_never_discounted
        """
        plant = create_plant()
        supplier = create_supplier(plant["id"])
        agreement = create_active_agreement(
            plant["id"], supplier["id"],
            minimum_volume_lbs=20000, volume_discount_pct=0.1,
        )
        vehicle = create_vehicle(plant["id"])
        route1 = create_route(plant["id"], vehicle["id"], route_code="R1")
        stop_a = add_stop(route1["id"], supplier["id"], agreement["id"], plant["id"],
                          estimated_weight_lbs=25000, estimated_distance_miles=10)
        validate_success(api.dispatch_route(route1["id"], RD), 200)
        validate_success(api.arrive_stop(stop_a["id"], RD), 200)
        # Collect 25000 lbs: cumulative volume 25000 >= 20000, so the FINAL fee takes
        # discount round_half_up(61000 * 0.10) = 6100 off subtotal 61000.
        collected = validate_success(
            api.collect_stop(stop_a["id"], {"actual_weight_lbs": 25000,
                                            "actual_distance_miles": 10,
                                            "temperature_f": 60.0}, RD),
            201,
        )
        assert collected["final_fee_cents"] == 54900

        # The supplier is already past the volume threshold, yet a NEW stop's provisional
        # estimate still excludes the discount: 10000 + 10000*2 + 10*100 = 31000.
        route2 = create_route(
            plant["id"], vehicle["id"], route_code="R2", service_date="2026-08-11",
            scheduled_departure="2026-08-11T06:00:00Z",
            scheduled_return="2026-08-11T18:00:00Z",
        )
        stop_b = add_stop(
            route2["id"], supplier["id"], agreement["id"], plant["id"],
            estimated_weight_lbs=10000, estimated_distance_miles=10,
            scheduled_window_start="2026-08-11T08:00:00Z",
            scheduled_window_end="2026-08-11T09:00:00Z",
        )
        assert stop_b["provisional_fee_cents"] == 31000


class TestImmediateConsistency:
    def test_collect_immediately_visible_across_reads(self, api):
        """PRD §1: "Every mutation, including cascaded side effects, commits atomically
        within its request and is visible immediately in the response and in all subsequent
        reads."
        PRD §3.4: "Collection also creates the corresponding `InboundBatch` in `RECEIVED`
        with `screening_result` `PENDING`, its `weight_lbs` equal to the stop's
        `actual_weight_lbs`, its species carried from the stop's `species_tag`, its
        `temperature_f` as recorded at the truck, and its `route_stop_id` pointing back to
        this stop."
        PRD §3.4: "Because collection creates the batch resource, the collection call
        returns 201 rather than 200."

        Design: Corner/consistency_model/collect_immediately_visible_across_reads
        """
        ctx = setup_dispatched_route_with_arrived_stop(
            estimated_weight_lbs=5000, estimated_distance_miles=20
        )
        collected = validate_success(
            api.collect_stop(ctx["stop"]["id"], {"actual_weight_lbs": 5000,
                                                 "actual_distance_miles": 20,
                                                 "temperature_f": 62.0}, RD),
            201,
        )
        assert collected["status"] == "COLLECTED"
        assert collected["final_fee_cents"] == 22000  # 10000 + 5000*2 + 20*100

        # The batch is visible immediately via reverse lookup.
        batch = get_batch_for_stop(ctx["stop"]["id"])
        assert_batch(batch)
        assert batch["status"] == "RECEIVED"
        assert batch["screening_result"] == "PENDING"
        assert batch["weight_lbs"] == 5000
        assert batch["route_stop_id"] == ctx["stop"]["id"]

        # And the settlement reflects the accrual in the same read window.
        settlement = get_settlement(ctx["plant"]["id"], period_index=1)
        assert settlement["pickup_fees_accrued_cents"] == 22000
        assert settlement["transport_costs_cents"] == 3000
