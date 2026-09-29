"""Two different overlap semantics applied to the very same booking.

Bay floor space is counted over a half-open window, so a changeover day may be
shared by two trucks; a single truck is held over a closed window, so the same
changeover day collides with itself.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_BAY_CAPACITY_CONFLICT,
    ERR_CHASSIS_OCCUPANCY_CONFLICT,
)
from test_helpers.assertions import assert_order_dimensions
from test_helpers.constants import vin_f550
from test_helpers.factories import build_slot_payload
from test_helpers.fixtures import (
    allocate,
    catalog_service,
    new_configuration,
    new_customer,
    new_order,
    new_slot,
    new_work_bay,
    read_order,
    read_slot,
    received_and_inspected_chassis,
    release,
    submit_engineering,
)


def _three_released_orders_one_bay(api):
    """Three trucks, three orders, and a single bay that fits one of them at a time."""
    ns = catalog_service(api, with_equipment=False)
    ns.bay = new_work_bay(api)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.orders = []
    ns.chassis_list = []
    for serial, order_number, in_service in (
        (14, "UO-2601", "2026-09-20"),
        (15, "UO-2602", "2026-09-25"),
        (16, "UO-2603", "2026-09-30"),
    ):
        chassis = received_and_inspected_chassis(
            api, ns.cm["id"], vin=vin_f550(serial), measured=(4820, 2680)
        )
        order = new_order(
            api,
            ns.config["id"],
            order_number=order_number,
            order_type="CUSTOMER_SPECIFIC",
            customer_id=ns.customer["id"],
            body_mount_offset_from_front_axle_in=120,
            required_payload_lb=5000,
            requested_in_service_date=in_service,
        )
        allocate(api, order["id"], chassis["id"])
        submit_engineering(api, order["id"])
        ns.chassis_list.append(chassis)
        ns.orders.append(release(api, order["id"]))
    return ns


def _scheduled_body_mount_window(api):
    """One order holding a body-mount window from the first to the tenth of September."""
    ns = catalog_service(api, with_equipment=False)
    ns.bay = new_work_bay(api)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(17), measured=(4820, 2680)
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-2701",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
        required_payload_lb=5000,
        requested_in_service_date="2026-09-25",
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    submit_engineering(api, ns.order["id"])
    ns.order = release(api, ns.order["id"])
    ns.slot_a = new_slot(
        api,
        ns.order["id"],
        ns.bay["id"],
        "2026-09-01",
        "2026-09-10",
        slot_type="BODY_MOUNT",
    )
    ns.order = read_order(api, ns.order["id"])
    return ns


class TestBayCapacityCountsHalfOpenWindows:
    """A bay of capacity one accepts back-to-back windows but never a true overlap."""

    def test_two_windows_sharing_a_changeover_day_both_schedule(self, api):
        """The tenth of September is the exclusive end of one window and the start of the next.

        Both bookings land at SCHEDULED on the same single-capacity bay, because
        adjacency is not counted as occupancy.

        Design: Difficulty/resource_temporal_overlap/work_bay_aggregate_capacity_half_open_adjacency_allowed
        """
        ns = _three_released_orders_one_bay(api)

        first = validate_success(
            api.create_build_slot(
                build_slot_payload(
                    ns.orders[0]["id"],
                    ns.bay["id"],
                    "2026-09-01",
                    "2026-09-10",
                    slot_type="FINAL_QC",
                ),
                users.SCHEDULER,
            ),
            201,
        )
        second = validate_success(
            api.create_build_slot(
                build_slot_payload(
                    ns.orders[1]["id"],
                    ns.bay["id"],
                    "2026-09-10",
                    "2026-09-15",
                    slot_type="FINAL_QC",
                ),
                users.SCHEDULER,
            ),
            201,
        )

        assert first["status"] == "SCHEDULED"
        assert second["status"] == "SCHEDULED"
        assert ns.bay["concurrent_capacity"] == 1

    def test_a_window_genuinely_overlapping_the_first_is_refused(self, api):
        """Starting a day before the incumbent's end really does share floor space.

        The third booking spans the ninth to the twelfth, which overlaps the first
        window on the ninth, so the bay is at capacity and the request is refused.

        Design: Difficulty/resource_temporal_overlap/work_bay_aggregate_capacity_half_open_adjacency_allowed
        """
        ns = _three_released_orders_one_bay(api)
        new_slot(
            api, ns.orders[0]["id"], ns.bay["id"], "2026-09-01", "2026-09-10", slot_type="FINAL_QC"
        )
        new_slot(
            api, ns.orders[1]["id"], ns.bay["id"], "2026-09-10", "2026-09-15", slot_type="FINAL_QC"
        )

        response = api.create_build_slot(
            build_slot_payload(
                ns.orders[2]["id"],
                ns.bay["id"],
                "2026-09-09",
                "2026-09-12",
                slot_type="FINAL_QC",
            ),
            users.SCHEDULER,
        )

        validate_error(response, ERR_BAY_CAPACITY_CONFLICT, 409)

    def test_only_the_two_accepted_windows_exist_and_only_their_orders_advanced(self, api):
        """The refused booking leaves no row and no schedule progress behind.

        The bay holds exactly the two windows that were accepted, the first two
        orders are SCHEDULED, and the third is still merely RELEASED.

        Design: Difficulty/resource_temporal_overlap/work_bay_aggregate_capacity_half_open_adjacency_allowed
        """
        ns = _three_released_orders_one_bay(api)
        new_slot(
            api, ns.orders[0]["id"], ns.bay["id"], "2026-09-01", "2026-09-10", slot_type="FINAL_QC"
        )
        new_slot(
            api, ns.orders[1]["id"], ns.bay["id"], "2026-09-10", "2026-09-15", slot_type="FINAL_QC"
        )
        validate_error(
            api.create_build_slot(
                build_slot_payload(
                    ns.orders[2]["id"],
                    ns.bay["id"],
                    "2026-09-09",
                    "2026-09-12",
                    slot_type="FINAL_QC",
                ),
                users.SCHEDULER,
            ),
            ERR_BAY_CAPACITY_CONFLICT,
            409,
        )

        slots, _meta = validate_paginated(
            api.list_build_slots(users.SCHEDULER, {"work_bay_id": ns.bay["id"]})
        )
        assert len(slots) == 2
        assert_order_dimensions(read_order(api, ns.orders[0]["id"]), build_status="SCHEDULED")
        assert_order_dimensions(read_order(api, ns.orders[1]["id"]), build_status="SCHEDULED")
        assert_order_dimensions(read_order(api, ns.orders[2]["id"]), build_status="RELEASED")


class TestChassisOccupancyCountsClosedWindows:
    """One truck cannot be in two windows on the changeover day, whatever the bay allows."""

    def test_a_second_window_touching_the_first_endpoint_is_refused_on_the_truck(self, api):
        """The very handoff the bay rule permits is blocked by the truck rule.

        A quality-control window starting on the tenth touches the body-mount
        window ending on the tenth, and because the truck is held over a closed
        interval the refusal names the occupancy conflict, not bay capacity.

        Design: Difficulty/resource_temporal_overlap/chassis_exclusive_closed_interval_rejects_touching_endpoint
        """
        ns = _scheduled_body_mount_window(api)
        assert ns.slot_a["status"] == "SCHEDULED"

        response = api.create_build_slot(
            build_slot_payload(
                ns.order["id"], ns.bay["id"], "2026-09-10", "2026-09-15", slot_type="FINAL_QC"
            ),
            users.SCHEDULER,
        )

        error = validate_error(response, ERR_CHASSIS_OCCUPANCY_CONFLICT, 409)
        assert error["error_id"] != ERR_BAY_CAPACITY_CONFLICT

    def test_one_clear_day_later_the_same_window_is_accepted(self, api):
        """Moving the start to the eleventh clears the closed interval.

        The window is created at SCHEDULED and carries the truck copied from the
        order's allocated unit.

        Design: Difficulty/resource_temporal_overlap/chassis_exclusive_closed_interval_rejects_touching_endpoint
        """
        ns = _scheduled_body_mount_window(api)
        validate_error(
            api.create_build_slot(
                build_slot_payload(
                    ns.order["id"], ns.bay["id"], "2026-09-10", "2026-09-15", slot_type="FINAL_QC"
                ),
                users.SCHEDULER,
            ),
            ERR_CHASSIS_OCCUPANCY_CONFLICT,
            409,
        )

        accepted = validate_success(
            api.create_build_slot(
                build_slot_payload(
                    ns.order["id"], ns.bay["id"], "2026-09-11", "2026-09-15", slot_type="FINAL_QC"
                ),
                users.SCHEDULER,
            ),
            201,
        )

        assert accepted["status"] == "SCHEDULED"
        assert accepted["chassis_id"] == ns.chassis["id"]

    def test_the_order_ends_with_exactly_the_two_surviving_windows(self, api):
        """The refused booking left nothing behind on the order.

        The order holds precisely the body-mount window and the accepted
        quality-control window, the first is untouched at SCHEDULED, and the order
        itself is SCHEDULED.

        Design: Difficulty/resource_temporal_overlap/chassis_exclusive_closed_interval_rejects_touching_endpoint
        """
        ns = _scheduled_body_mount_window(api)
        validate_error(
            api.create_build_slot(
                build_slot_payload(
                    ns.order["id"], ns.bay["id"], "2026-09-10", "2026-09-15", slot_type="FINAL_QC"
                ),
                users.SCHEDULER,
            ),
            ERR_CHASSIS_OCCUPANCY_CONFLICT,
            409,
        )
        new_slot(
            api, ns.order["id"], ns.bay["id"], "2026-09-11", "2026-09-15", slot_type="FINAL_QC"
        )

        slots, _meta = validate_paginated(
            api.list_build_slots(users.SCHEDULER, {"upfit_order_id": ns.order["id"]})
        )
        assert len(slots) == 2
        assert read_slot(api, ns.slot_a["id"])["status"] == "SCHEDULED"
        assert_order_dimensions(read_order(api, ns.order["id"]), build_status="SCHEDULED")
