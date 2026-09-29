"""Book rules refusing requests that are structurally fine but physically wrong.

A dump body with nothing to lift it, a mounting point already taken, a body too
long for the frame behind the cab, a bay window opening before the truck arrives
and a contracted payload the build cannot carry are all refused here, each with
the one error the precedence ladder says comes first.
"""

from types import SimpleNamespace

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_BAY_CAPACITY_CONFLICT,
    ERR_CAB_TO_AXLE_INSUFFICIENT,
    ERR_CAN_GATEWAY_REQUIRED,
    ERR_CHASSIS_NOT_AVAILABLE_BY_SLOT_START,
    ERR_FRONT_GAWR_EXCEEDED,
    ERR_GVWR_EXCEEDED,
    ERR_HYDRAULIC_CIRCUIT_REQUIRED,
    ERR_HYDRAULIC_SOURCE_MISSING,
    ERR_MOUNT_ZONE_CONFLICT,
    ERR_NON_STANDARD_POOL_EQUIPMENT,
    ERR_PAYLOAD_SHORTFALL,
    ERR_REAR_GAWR_EXCEEDED,
    ERR_WHEELBASE_INSUFFICIENT,
)
from test_helpers.assertions import (
    assert_axle_numbers,
    assert_order_commitments,
    assert_order_dimensions,
    assert_projection_ratings,
)
from test_helpers.constants import (
    BODY_DUMP_12FT,
    BODY_SERVICE_11FT,
    CM_F450,
    EQ_CRANE_6000,
    vin_f450,
    vin_f550,
)
from test_helpers.factories import (
    build_configuration_payload,
    build_slot_payload,
    equipment_installation_payload,
)
from test_helpers.fixtures import (
    allocate,
    approve_interface,
    catalog_dump,
    catalog_service,
    new_body_spec,
    new_chassis_model,
    new_configuration,
    new_customer,
    new_equipment_spec,
    new_order,
    new_slot,
    new_work_bay,
    pin_clock,
    plan_equipment,
    projection,
    propose_interface,
    read_installation,
    read_order,
    read_slot,
    received_and_inspected_chassis,
    release,
    remove_equipment,
    submit_engineering,
)

CRANE_CAN = dict(
    EQ_CRANE_6000, code="CRANE-CAN-6000", requires_can_gateway=True, list_price_cents=800000
)
BAY_SERVICE_FLATBED = {
    "code": "BAY-1",
    "concurrent_capacity": 1,
    "supported_body_types": ["SERVICE", "FLATBED"],
}


def _dump_order_without_a_hoist(api):
    """A dump build ready for release with no hydraulic item planned at all."""
    ns = catalog_dump(api)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-DUMP-B")
    ns.chassis = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f450(17), measured=(4180, 2320)
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5024",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=96,
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    ns.order = submit_engineering(api, ns.order["id"])
    return ns


def _order_with_a_freed_mount_zone(api):
    """A service order whose behind-cab mounting point was vacated by a removal."""
    ns = catalog_service(api)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5023",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    ns.first_crane = plan_equipment(
        api, ns.order["id"], ns.crane["id"], 208, "PRIMARY", headers=users.TECHNICIAN
    )
    remove_equipment(api, ns.first_crane["id"], "wrong crane model shipped")
    return ns


def _short_frame_catalog(api):
    """A sixty-inch cab-to-axle F450 alongside one body it fits and one it does not."""
    pin_clock(api)
    ns = SimpleNamespace()
    ns.cm = new_chassis_model(api, CM_F450)
    ns.service_body = new_body_spec(api, BODY_SERVICE_11FT)
    ns.dump_body = new_body_spec(api, BODY_DUMP_12FT)
    return ns


def _released_order_with_a_late_arriving_unit(api):
    """A released order whose truck does not reach the plant until the twentieth."""
    ns = catalog_service(api, with_equipment=False)
    ns.bay = new_work_bay(api, BAY_SERVICE_FLATBED)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis = received_and_inspected_chassis(
        api,
        ns.cm["id"],
        vin=vin_f550(18),
        availability_date="2026-09-20",
        measured=(4905, 2755),
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5025",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    submit_engineering(api, ns.order["id"])
    ns.order = release(api, ns.order["id"])
    return ns


def _full_bay_and_a_second_released_order(api):
    """One bay of capacity one, already booked, and a second order that wants it."""
    ns = catalog_service(api, with_equipment=False)
    ns.bay = new_work_bay(api, BAY_SERVICE_FLATBED)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis_a = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(19), measured=(4905, 2755)
    )
    ns.chassis_b = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(20), measured=(4905, 2755)
    )
    ns.order_a = new_order(
        api,
        ns.config["id"],
        order_number="UO-5026",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    allocate(api, ns.order_a["id"], ns.chassis_a["id"])
    submit_engineering(api, ns.order_a["id"])
    release(api, ns.order_a["id"])
    ns.slot_a = new_slot(
        api, ns.order_a["id"], ns.bay["id"], "2026-09-01", "2026-09-05", slot_type="BODY_MOUNT"
    )
    ns.order_b = new_order(
        api,
        ns.config["id"],
        order_number="UO-5027",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    allocate(api, ns.order_b["id"], ns.chassis_b["id"])
    submit_engineering(api, ns.order_b["id"])
    ns.order_b = release(api, ns.order_b["id"])
    return ns


def _pool_order_on_an_empty_standard_list(api):
    """A tier-B pool configuration that standardizes nothing at all."""
    ns = catalog_service(api, with_equipment=False)
    ns.crane = new_equipment_spec(api, EQ_CRANE_6000)
    ns.config = new_configuration(
        api,
        ns.cm["id"],
        ns.body["id"],
        config_code="CFG-POOL-B",
        standardization_tier="TIER_B",
        standard_equipment_spec_ids=[],
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5028",
        order_type="POOL_STOCK",
        body_mount_offset_from_front_axle_in=120,
    )
    return ns


def _order_contracted_for_a_payload(api, required_payload_lb):
    """A submitted service order carrying a contracted payload figure."""
    ns = catalog_service(api, with_equipment=False)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(21), measured=(4905, 2755)
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5029",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
        required_payload_lb=required_payload_lb,
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    ns.order = submit_engineering(api, ns.order["id"])
    return ns


def _order_wanting_a_network_crane(api):
    """A customer order for a crane that has to be read through an approved gateway."""
    ns = catalog_service(api, with_equipment=False)
    ns.can_crane = new_equipment_spec(api, CRANE_CAN)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5030",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    return ns


def _plan_can_crane(api, ns, order_id):
    """The installation request for the network crane, issued as the technician."""
    return api.create_equipment_installation(
        equipment_installation_payload(
            order_id,
            ns.can_crane["id"],
            mount_cg_from_front_axle_in=208,
            hydraulic_circuit="PRIMARY",
        ),
        users.TECHNICIAN,
    )


class TestDumpBodyNeedsSomethingToLiftIt:
    """A body that requires hydraulics may not be released without a hydraulic item."""

    def test_the_release_of_a_hoistless_dump_build_is_refused(self, api):
        """The dump body declares that it needs hydraulics and nothing supplies them.

        The release is refused on the missing hydraulic source, the order stays at
        engineering review and no invoice was stamped, because a refused release
        writes nothing at all.

        Design: Corner/validations/dump_body_without_a_hoist_cannot_be_released
        """
        ns = _dump_order_without_a_hoist(api)

        response = api.release_order(ns.order["id"], users.SCHEDULER)

        validate_error(response, ERR_HYDRAULIC_SOURCE_MISSING, 422)
        order = read_order(api, ns.order["id"])
        assert_order_dimensions(order, build_status="ENGINEERING_REVIEW")
        assert order["invoice_total_cents"] == 0

    def test_every_weight_gate_ahead_of_it_was_already_satisfied(self, api):
        """The refusal is not a weight problem in disguise.

        The book projection for this dump build sits comfortably inside all three
        ratings, and its payload capacity is set by the rear-axle bucket rather than
        the gross bucket because the cargo centroid sits behind the rear axle.

        Design: Corner/validations/dump_body_without_a_hoist_cannot_be_released
        """
        ns = _dump_order_without_a_hoist(api)

        designed = projection(api, ns.order["id"], "AS_DESIGNED")

        assert_axle_numbers(designed, 4219, 5681, 9900, 3685, component_count=1)
        assert_projection_ratings(designed, 14000, 5000, 9450)

    def test_planning_a_hoist_lets_the_identical_release_through(self, api):
        """One planned hoist is all the rule asks for.

        With the hoist planned onto the primary circuit the same release call is
        accepted and the order reaches released.

        Design: Corner/validations/dump_body_without_a_hoist_cannot_be_released
        """
        ns = _dump_order_without_a_hoist(api)
        validate_error(
            api.release_order(ns.order["id"], users.SCHEDULER), ERR_HYDRAULIC_SOURCE_MISSING, 422
        )

        plan_equipment(
            api, ns.order["id"], ns.hoist["id"], 130, "PRIMARY", headers=users.TECHNICIAN
        )
        released = validate_success(api.release_order(ns.order["id"], users.SCHEDULER))

        assert_order_dimensions(released, build_status="RELEASED")


class TestMountZoneExclusivityCountsLiveRowsOnly:
    """A mounting point occupied by a removed installation is not occupied at all."""

    def test_the_zone_freed_by_a_removal_takes_a_replacement(self, api):
        """The wrong crane went back on the truck, so the right one may go on.

        The replacement installation is created at planned while the stripped row
        stays removed, and the order's commitments count only the live crane on top
        of the body's own draw.

        Design: Corner/validations/mount_zone_conflict_ignores_the_removed_occupant
        """
        ns = _order_with_a_freed_mount_zone(api)

        replacement = validate_success(
            api.create_equipment_installation(
                equipment_installation_payload(
                    ns.order["id"],
                    ns.crane["id"],
                    mount_cg_from_front_axle_in=208,
                    hydraulic_circuit="PRIMARY",
                ),
                users.TECHNICIAN,
            ),
            201,
        )

        assert replacement["status"] == "PLANNED"
        assert read_installation(api, ns.first_crane["id"])["status"] == "REMOVED"
        assert_order_commitments(
            read_order(api, ns.order["id"]), flow_gpm=8, aux_amps=22
        )

    def test_the_rule_is_still_armed_against_the_live_occupant(self, api):
        """Freeing the zone once does not disarm the exclusivity rule.

        A third crane aimed at the same mounting point while the replacement is
        planned is refused on the mount-zone conflict.

        Design: Corner/validations/mount_zone_conflict_ignores_the_removed_occupant
        """
        ns = _order_with_a_freed_mount_zone(api)
        plan_equipment(
            api, ns.order["id"], ns.crane["id"], 208, "PRIMARY", headers=users.TECHNICIAN
        )

        response = api.create_equipment_installation(
            equipment_installation_payload(
                ns.order["id"],
                ns.crane["id"],
                mount_cg_from_front_axle_in=208,
                hydraulic_circuit="PRIMARY",
            ),
            users.TECHNICIAN,
        )

        validate_error(response, ERR_MOUNT_ZONE_CONFLICT, 409)


class TestCabToAxleIsReportedBeforeWheelbase:
    """Two book minimums violated at once are reported in the ladder's order."""

    def test_the_cab_to_axle_shortfall_is_the_one_reported(self, api):
        """Sixty inches behind the cab cannot take a body that needs eighty-four.

        The pairing also falls short on wheelbase, but the cab-to-axle rule sits
        higher on the ladder, so that is the error returned and no configuration row
        survives the attempt.

        Design: Corner/validations/cab_to_axle_outranks_wheelbase_at_configuration_create
        """
        ns = _short_frame_catalog(api)

        response = api.create_build_configuration(
            build_configuration_payload(
                ns.cm["id"], ns.service_body["id"], config_code="CFG-BAD-SVC"
            ),
            users.ENGINEER,
        )

        error = validate_error(response, ERR_CAB_TO_AXLE_INSUFFICIENT, 422)
        assert error["error_id"] != ERR_WHEELBASE_INSUFFICIENT
        configs, _meta = validate_paginated(api.list_build_configurations(users.ENGINEER))
        assert [c for c in configs if c["config_code"] == "CFG-BAD-SVC"] == []

    def test_a_pairing_that_meets_both_minimums_exactly_is_accepted(self, api):
        """Exact equality on both book minimums is a fit, not a shortfall.

        The dump body asks for exactly the frame this model offers on both counts, so
        the configuration is created and starts as a draft.

        Design: Corner/validations/cab_to_axle_outranks_wheelbase_at_configuration_create
        """
        ns = _short_frame_catalog(api)

        created = validate_success(
            api.create_build_configuration(
                build_configuration_payload(
                    ns.cm["id"], ns.dump_body["id"], config_code="CFG-DUMP-B"
                ),
                users.ENGINEER,
            ),
            201,
        )

        assert created["status"] == "DRAFT"
        assert created["config_code"] == "CFG-DUMP-B"


class TestBayWindowCannotOpenBeforeTheTruckArrives:
    """A window may not start on a day the unit is not yet at the plant."""

    def test_a_window_opening_ten_days_early_is_refused(self, api):
        """The truck lands on the twentieth; the window wanted to start on the tenth.

        The booking is refused because the unit is not available by the window's
        start, nothing was created, and the order is still merely released.

        Design: Corner/validations/slot_that_starts_before_the_unit_arrives_is_rejected
        """
        ns = _released_order_with_a_late_arriving_unit(api)

        response = api.create_build_slot(
            build_slot_payload(
                ns.order["id"], ns.bay["id"], "2026-09-10", "2026-09-15", slot_type="BODY_MOUNT"
            ),
            users.SCHEDULER,
        )

        validate_error(response, ERR_CHASSIS_NOT_AVAILABLE_BY_SLOT_START, 422)
        slots, _meta = validate_paginated(
            api.list_build_slots(users.SCHEDULER, {"upfit_order_id": ns.order["id"]})
        )
        assert slots == []
        assert_order_dimensions(read_order(api, ns.order["id"]), build_status="RELEASED")

    def test_a_window_starting_on_the_arrival_day_itself_is_accepted(self, api):
        """Equality between the arrival date and the start date is availability enough.

        Moving the start to the twentieth, the day the unit arrives, is accepted and
        the window is scheduled.

        Design: Corner/validations/slot_that_starts_before_the_unit_arrives_is_rejected
        """
        ns = _released_order_with_a_late_arriving_unit(api)
        validate_error(
            api.create_build_slot(
                build_slot_payload(
                    ns.order["id"], ns.bay["id"], "2026-09-10", "2026-09-15", slot_type="BODY_MOUNT"
                ),
                users.SCHEDULER,
            ),
            ERR_CHASSIS_NOT_AVAILABLE_BY_SLOT_START,
            422,
        )

        accepted = validate_success(
            api.create_build_slot(
                build_slot_payload(
                    ns.order["id"], ns.bay["id"], "2026-09-20", "2026-09-25", slot_type="BODY_MOUNT"
                ),
                users.SCHEDULER,
            ),
            201,
        )

        assert accepted["status"] == "SCHEDULED"

    def test_the_accepted_window_moves_the_order_onto_the_schedule(self, api):
        """The first scheduled window is what advances the production dimension.

        Once the twentieth-of-September window is booked the order reads scheduled.

        Design: Corner/validations/slot_that_starts_before_the_unit_arrives_is_rejected
        """
        ns = _released_order_with_a_late_arriving_unit(api)

        new_slot(
            api, ns.order["id"], ns.bay["id"], "2026-09-20", "2026-09-25", slot_type="BODY_MOUNT"
        )

        assert_order_dimensions(read_order(api, ns.order["id"]), build_status="SCHEDULED")


class TestQueueingInsteadOfBeingRefused:
    """Asking to be queued turns a full bay from a refusal into a place in line."""

    def test_without_the_flag_the_full_bay_refuses_the_booking(self, api):
        """The second order's window overlaps the incumbent on three days.

        The bay holds one truck at a time and is already booked across those days, so
        the request is refused on bay capacity and nothing is created.

        Design: Corner/validations/queue_if_full_flag_converts_the_capacity_rejection_into_a_queued_slot
        """
        ns = _full_bay_and_a_second_released_order(api)

        response = api.create_build_slot(
            build_slot_payload(
                ns.order_b["id"], ns.bay["id"], "2026-09-03", "2026-09-07", slot_type="BODY_MOUNT"
            ),
            users.SCHEDULER,
        )

        validate_error(response, ERR_BAY_CAPACITY_CONFLICT, 409)
        slots, _meta = validate_paginated(
            api.list_build_slots(users.SCHEDULER, {"upfit_order_id": ns.order_b["id"]})
        )
        assert slots == []

    def test_with_the_flag_the_identical_window_is_queued(self, api):
        """The same dates asked for politely are taken as a place in the queue.

        The window is created at queued rather than refused, and because a queued
        window is not a booked window the order stays merely released.

        Design: Corner/validations/queue_if_full_flag_converts_the_capacity_rejection_into_a_queued_slot
        """
        ns = _full_bay_and_a_second_released_order(api)
        validate_error(
            api.create_build_slot(
                build_slot_payload(
                    ns.order_b["id"],
                    ns.bay["id"],
                    "2026-09-03",
                    "2026-09-07",
                    slot_type="BODY_MOUNT",
                ),
                users.SCHEDULER,
            ),
            ERR_BAY_CAPACITY_CONFLICT,
            409,
        )

        queued = validate_success(
            api.create_build_slot(
                dict(
                    build_slot_payload(
                        ns.order_b["id"],
                        ns.bay["id"],
                        "2026-09-03",
                        "2026-09-07",
                        slot_type="BODY_MOUNT",
                    ),
                    queue_if_full=True,
                ),
                users.SCHEDULER,
            ),
            201,
        )

        assert queued["status"] == "QUEUED"
        assert_order_dimensions(read_order(api, ns.order_b["id"]), build_status="RELEASED")

    def test_the_incumbent_is_untouched_and_the_queued_window_carries_its_own_truck(self, api):
        """Queueing behind somebody does not disturb the somebody.

        The incumbent window and its order are both still scheduled, and the queued
        window carries the second order's own unit, stamped onto it when it was
        created.

        Design: Corner/validations/queue_if_full_flag_converts_the_capacity_rejection_into_a_queued_slot
        """
        ns = _full_bay_and_a_second_released_order(api)

        queued = new_slot(
            api,
            ns.order_b["id"],
            ns.bay["id"],
            "2026-09-03",
            "2026-09-07",
            slot_type="BODY_MOUNT",
            queue_if_full=True,
        )

        assert read_slot(api, ns.slot_a["id"])["status"] == "SCHEDULED"
        assert_order_dimensions(read_order(api, ns.order_a["id"]), build_status="SCHEDULED")
        assert queued["chassis_id"] == ns.chassis_b["id"]


class TestCircuitCoherenceOutranksPoolStandardization:
    """Two rules are broken at once and only the higher-ranked one is reported."""

    def test_the_circuit_mismatch_masks_the_standardization_breach(self, api):
        """A hydraulic crane submitted with no circuit is refused on the circuit.

        The crane is also not a standard item for this pool configuration, but circuit
        coherence sits above pool standardization on the ladder, so that is the error
        returned; nothing was created and the order commits no flow.

        Design: Corner/validations/hydraulic_circuit_check_outranks_the_pool_standardization_check
        """
        ns = _pool_order_on_an_empty_standard_list(api)

        response = api.create_equipment_installation(
            equipment_installation_payload(
                ns.order["id"],
                ns.crane["id"],
                mount_cg_from_front_axle_in=208,
                hydraulic_circuit="NONE",
            ),
            users.TECHNICIAN,
        )

        error = validate_error(response, ERR_HYDRAULIC_CIRCUIT_REQUIRED, 422)
        assert error["error_id"] != ERR_NON_STANDARD_POOL_EQUIPMENT
        installations, _meta = validate_paginated(
            api.list_equipment_installations(
                users.TECHNICIAN, {"upfit_order_id": ns.order["id"]}
            )
        )
        assert installations == []
        assert_order_commitments(read_order(api, ns.order["id"]), flow_gpm=0)

    def test_the_masked_rule_surfaces_once_the_circuit_is_named(self, api):
        """The lower-ranked rule was hidden, not absent.

        With the crane plumbed onto the primary circuit the request is refused again,
        this time because a pool build may only carry the items its configuration
        standardizes — and this configuration standardizes none.

        Design: Corner/validations/hydraulic_circuit_check_outranks_the_pool_standardization_check
        """
        ns = _pool_order_on_an_empty_standard_list(api)
        validate_error(
            api.create_equipment_installation(
                equipment_installation_payload(
                    ns.order["id"],
                    ns.crane["id"],
                    mount_cg_from_front_axle_in=208,
                    hydraulic_circuit="NONE",
                ),
                users.TECHNICIAN,
            ),
            ERR_HYDRAULIC_CIRCUIT_REQUIRED,
            422,
        )

        response = api.create_equipment_installation(
            equipment_installation_payload(
                ns.order["id"],
                ns.crane["id"],
                mount_cg_from_front_axle_in=208,
                hydraulic_circuit="PRIMARY",
            ),
            users.TECHNICIAN,
        )

        validate_error(response, ERR_NON_STANDARD_POOL_EQUIPMENT, 422)

    def test_the_standardization_rule_binds_pool_builds_only(self, api):
        """The very same crane on a customer build over the same configuration is fine.

        A customer-specific order may install any specification, so the identical
        request on such an order over this configuration is accepted.

        Design: Corner/validations/hydraulic_circuit_check_outranks_the_pool_standardization_check
        """
        ns = _pool_order_on_an_empty_standard_list(api)
        customer = new_customer(api)
        customer_order = new_order(
            api,
            ns.config["id"],
            order_number="UO-5028-CS",
            order_type="CUSTOMER_SPECIFIC",
            customer_id=customer["id"],
            body_mount_offset_from_front_axle_in=120,
        )

        accepted = validate_success(
            api.create_equipment_installation(
                equipment_installation_payload(
                    customer_order["id"],
                    ns.crane["id"],
                    mount_cg_from_front_axle_in=208,
                    hydraulic_circuit="PRIMARY",
                ),
                users.TECHNICIAN,
            ),
            201,
        )

        assert accepted["status"] == "PLANNED"


class TestPayloadShortfallReadsTheComputedCapacity:
    """The contracted payload is compared against what the build actually leaves over."""

    def test_a_contract_fifty_pounds_beyond_the_capacity_is_refused(self, api):
        """Nine thousand nine hundred and fifty is fifty pounds more than the build allows.

        The release is refused on the payload shortfall rather than on any of the
        three regulatory ceilings, and the order stays at engineering review.

        Design: Corner/validations/payload_shortfall_is_evaluated_from_the_result_of_the_weight_gates
        """
        ns = _order_contracted_for_a_payload(api, 9950)

        response = api.release_order(ns.order["id"], users.SCHEDULER)

        error = validate_error(response, ERR_PAYLOAD_SHORTFALL, 422)
        assert error["error_id"] not in (
            ERR_GVWR_EXCEEDED,
            ERR_REAR_GAWR_EXCEEDED,
            ERR_FRONT_GAWR_EXCEEDED,
        )
        assert_order_dimensions(
            read_order(api, ns.order["id"]), build_status="ENGINEERING_REVIEW"
        )

    def test_the_three_regulatory_ceilings_were_all_satisfied(self, api):
        """The truck is legal; it simply cannot carry what was promised.

        The book computation puts the gross weight, the rear axle and the front axle
        all inside their ratings, and the capacity it leaves over is nine thousand
        nine hundred pounds.

        Design: Corner/validations/payload_shortfall_is_evaluated_from_the_result_of_the_weight_gates
        """
        ns = _order_contracted_for_a_payload(api, 9950)

        designed = projection(api, ns.order["id"], "AS_DESIGNED")

        assert_axle_numbers(designed, 5009, 4591, 9600, 9900, component_count=1)
        assert_projection_ratings(designed, 19500, 7000, 14706)

    def test_a_contract_exactly_at_the_capacity_is_accepted(self, api):
        """The comparison accepts equality, so nine thousand nine hundred passes.

        An otherwise identical order contracted for exactly the capacity the build
        leaves over is released.

        Design: Corner/validations/payload_shortfall_is_evaluated_from_the_result_of_the_weight_gates
        """
        ns = _order_contracted_for_a_payload(api, 9900)

        released = validate_success(api.release_order(ns.order["id"], users.SCHEDULER))

        assert_order_dimensions(released, build_status="RELEASED")


class TestNetworkCraneNeedsAnApprovedGateway:
    """An item read off the vehicle network may not be planned without a gateway."""

    def test_planning_a_network_crane_with_no_interface_at_all_is_refused(self, api):
        """There is nothing for the crane to read the vehicle through.

        The order holds no electrical interface, so the installation of a
        network-dependent crane is refused on the gateway prerequisite.

        Design: Corner/validations/can_gateway_dependent_equipment_needs_an_approved_interface
        """
        ns = _order_wanting_a_network_crane(api)

        response = _plan_can_crane(api, ns, ns.order["id"])

        validate_error(response, ERR_CAN_GATEWAY_REQUIRED, 422)

    def test_a_proposed_gateway_is_not_yet_a_gateway(self, api):
        """The rule asks for an approved interface, not a proposed one.

        While the body-builder module is merely proposed the installation is still
        refused; once the compliance officer approves it the identical request is
        accepted, and the crane is planned in deficit with no flow granted because no
        truck is bound yet.

        Design: Corner/validations/can_gateway_dependent_equipment_needs_an_approved_interface
        """
        ns = _order_wanting_a_network_crane(api)
        gateway = propose_interface(
            api, ns.order["id"], "BODY_BUILDER_MODULE", 20, "BODY_CONTROLLER"
        )

        validate_error(_plan_can_crane(api, ns, ns.order["id"]), ERR_CAN_GATEWAY_REQUIRED, 422)

        approve_interface(api, gateway["id"])
        planned = validate_success(_plan_can_crane(api, ns, ns.order["id"]), 201)
        assert planned["status"] == "PLANNED"
        assert planned["hydraulic_status"] == "DEFICIT"
        assert planned["allocated_flow_gpm"] == 0

    def test_the_committed_load_counts_the_gateway_and_the_crane_together(self, api):
        """Body, approved interface and planned crane make forty-two amps.

        The order's committed auxiliary load counts all three, and a body-builder
        module carries no warranty consequence so the chassis posture stays intact.

        Design: Corner/validations/can_gateway_dependent_equipment_needs_an_approved_interface
        """
        ns = _order_wanting_a_network_crane(api)
        gateway = propose_interface(
            api, ns.order["id"], "BODY_BUILDER_MODULE", 20, "BODY_CONTROLLER"
        )
        approve_interface(api, gateway["id"])
        validate_success(_plan_can_crane(api, ns, ns.order["id"]), 201)

        assert_order_commitments(
            read_order(api, ns.order["id"]), aux_amps=42, warranty_status="INTACT"
        )

    def test_an_approved_splice_does_not_satisfy_the_gateway_rule(self, api):
        """Only a gateway or a body-builder module counts; a splice does not.

        On a parallel order carrying an approved direct splice the network crane is
        still refused, because the rule names the two acceptable interface methods
        explicitly.

        Design: Corner/validations/can_gateway_dependent_equipment_needs_an_approved_interface
        """
        ns = _order_wanting_a_network_crane(api)
        parallel = new_order(
            api,
            ns.config["id"],
            order_number="UO-5030-B",
            order_type="CUSTOMER_SPECIFIC",
            customer_id=ns.customer["id"],
            body_mount_offset_from_front_axle_in=120,
        )
        splice = propose_interface(
            api, parallel["id"], "DIRECT_SPLICE", 25, "DISCRETE_CIRCUIT", waiver=True
        )
        approve_interface(api, splice["id"])

        response = _plan_can_crane(api, ns, parallel["id"])

        validate_error(response, ERR_CAN_GATEWAY_REQUIRED, 422)
