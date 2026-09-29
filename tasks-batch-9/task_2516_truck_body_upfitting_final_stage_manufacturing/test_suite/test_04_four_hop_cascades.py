"""Single calls whose consequences travel four hops.

Pulling a crane off a finished truck unwinds the hydraulic pool, the measured
certification, the label on the door frame and the closed bay window; sending a
damaged chassis back to the manufacturer unwinds its order, its window and drags
a waiting order out of the queue in its place.
"""

from test_helpers import test_users as users
from test_helpers.assertions import (
    assert_clock_origin_timestamp,
    assert_order_commitments,
    assert_order_dimensions,
)
from test_helpers.constants import vin_f550
from test_helpers.fixtures import (
    allocate,
    approve_certification,
    catalog_service,
    close_slot,
    draft_certification,
    install_body,
    install_equipment,
    issue_label,
    new_configuration,
    new_customer,
    new_order,
    new_slot,
    new_work_bay,
    plan_equipment,
    read_certification,
    read_chassis,
    read_installation,
    read_label,
    read_order,
    read_slot,
    received_and_inspected_chassis,
    release,
    remove_equipment,
    return_chassis,
    start_slot,
    submit_engineering,
)

REMOVAL_REASON = "customer deleted the crane from the spec after final QC"
RETURN_REASON = "frame rail damage found in receiving re-inspection"


def _labelled_crane_truck(api):
    """One crane, one closed window, both certifications approved and a label issued."""
    ns = catalog_service(api)
    ns.bay = new_work_bay(api)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis = received_and_inspected_chassis(api, ns.cm["id"], measured=(4905, 2755))
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-1601",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
        required_payload_lb=5000,
        requested_in_service_date="2026-09-15",
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    ns.crane_install = plan_equipment(
        api, ns.order["id"], ns.crane["id"], 208, "PRIMARY", headers=users.TECHNICIAN
    )
    ns.order = submit_engineering(api, ns.order["id"])
    ns.cert_designed = draft_certification(
        api, ns.order["id"], "AS_DESIGNED", expected_version=ns.order["version"]
    )
    ns.cert_designed = approve_certification(api, ns.cert_designed["id"])
    ns.order = release(api, ns.order["id"])
    ns.slot = new_slot(
        api,
        ns.order["id"],
        ns.bay["id"],
        "2026-09-01",
        "2026-09-10",
        slot_type="FINAL_QC",
    )
    ns.slot = start_slot(api, ns.slot["id"])
    ns.crane_install = install_equipment(api, ns.crane_install["id"], 1290)
    ns.order = install_body(api, ns.order["id"], 2160)
    ns.cert_measured = draft_certification(
        api, ns.order["id"], "AS_MEASURED", expected_version=ns.order["version"]
    )
    ns.cert_measured = approve_certification(api, ns.cert_measured["id"])
    ns.label = issue_label(api, ns.order["id"], ns.cert_measured["id"])
    ns.slot = close_slot(api, ns.slot["id"])
    ns.order = read_order(api, ns.order["id"])
    return ns


def _two_orders_one_bay(api):
    """One bay of capacity one, a scheduled window and a queued window behind it."""
    ns = catalog_service(api, with_equipment=False)
    ns.bay = new_work_bay(api)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis_x = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(8), measured=(4820, 2680)
    )
    ns.chassis_y = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(9), measured=(4820, 2680)
    )
    ns.order_x = new_order(
        api,
        ns.config["id"],
        order_number="UO-1701",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
        required_payload_lb=5000,
        requested_in_service_date="2026-09-15",
    )
    allocate(api, ns.order_x["id"], ns.chassis_x["id"])
    submit_engineering(api, ns.order_x["id"])
    ns.order_x = release(api, ns.order_x["id"])
    ns.slot_x = new_slot(
        api,
        ns.order_x["id"],
        ns.bay["id"],
        "2026-09-01",
        "2026-09-10",
        slot_type="FINAL_QC",
    )
    ns.order_y = new_order(
        api,
        ns.config["id"],
        order_number="UO-1702",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
        required_payload_lb=5000,
        requested_in_service_date="2026-09-20",
    )
    allocate(api, ns.order_y["id"], ns.chassis_y["id"])
    submit_engineering(api, ns.order_y["id"])
    ns.order_y = release(api, ns.order_y["id"])
    ns.slot_y = new_slot(
        api,
        ns.order_y["id"],
        ns.bay["id"],
        "2026-09-05",
        "2026-09-08",
        slot_type="FINAL_QC",
        queue_if_full=True,
    )
    ns.order_x = read_order(api, ns.order_x["id"])
    ns.order_y = read_order(api, ns.order_y["id"])
    return ns


class TestEquipmentRemovalCascade:
    """Removing the crane walks from the pool out to the bay window."""

    def test_removal_hands_back_the_flow_grant_and_the_aux_load(self, api):
        """The first hop is the hydraulic and electrical bookkeeping.

        The removed crane keeps no allocated flow and no applicable hydraulic
        status, and the order's committed flow falls to zero while its aux draw
        drops back to the twelve amps the body alone asks for.

        Design: Difficulty/transitive_cascade/equipment_remove_cascades_four_hops_to_slot_reopen
        """
        ns = _labelled_crane_truck(api)

        remove_equipment(api, ns.crane_install["id"], REMOVAL_REASON)

        installation = read_installation(api, ns.crane_install["id"])
        assert installation["status"] == "REMOVED"
        assert installation["allocated_flow_gpm"] == 0
        assert installation["hydraulic_status"] == "NOT_APPLICABLE"
        assert_order_commitments(read_order(api, ns.order["id"]), flow_gpm=0, aux_amps=12)

    def test_removal_voids_the_measured_certification_and_the_label_citing_it(self, api):
        """The second and third hops undo the compliance paperwork.

        The measured certification is voided because the component set changed
        while the design certification is untouched, the label is stamped void at
        the logical clock, and the order's compliance dimension falls back to
        DESIGN_CERTIFIED.

        Design: Difficulty/transitive_cascade/equipment_remove_cascades_four_hops_to_slot_reopen
        """
        ns = _labelled_crane_truck(api)

        remove_equipment(api, ns.crane_install["id"], REMOVAL_REASON)

        measured = read_certification(api, ns.cert_measured["id"])
        assert measured["status"] == "VOIDED"
        assert measured["voided_reason"] == "COMPONENT_SET_CHANGED"
        assert read_certification(api, ns.cert_designed["id"])["status"] == "APPROVED"
        assert_clock_origin_timestamp(read_label(api, ns.label["id"])["voided_at"])
        assert_order_dimensions(
            read_order(api, ns.order["id"]), compliance_status="DESIGN_CERTIFIED"
        )

    def test_removal_reopens_the_closed_window_and_pulls_the_build_back(self, api):
        """The fourth hop reaches the bay: the truck is back under work.

        The closed window returns to IN_BUILD and the order steps back from
        BUILD_COMPLETE to IN_BUILD, while the unit itself never leaves the bay.

        Design: Difficulty/transitive_cascade/equipment_remove_cascades_four_hops_to_slot_reopen
        """
        ns = _labelled_crane_truck(api)
        assert_order_dimensions(ns.order, build_status="BUILD_COMPLETE")
        assert ns.slot["status"] == "CLOSED"

        remove_equipment(api, ns.crane_install["id"], REMOVAL_REASON)

        assert_order_dimensions(read_order(api, ns.order["id"]), build_status="IN_BUILD")
        assert read_slot(api, ns.slot["id"])["status"] == "IN_BUILD"
        assert read_chassis(api, ns.chassis["id"])["status"] == "IN_UPFIT"


class TestChassisReturnCascade:
    """Returning a unit frees a bay window and the waitlist drains behind it."""

    def test_returning_the_bound_unit_puts_its_order_on_chassis_hold(self, api):
        """The first hop severs the binding in both directions.

        The unit goes to RETURNED with no order attached, and the order it was
        carrying lands on CHASSIS_HOLD with a null chassis.

        Design: Difficulty/transitive_cascade/chassis_return_cascades_four_hops_into_queue_promotion
        """
        ns = _two_orders_one_bay(api)
        assert_order_dimensions(ns.order_x, build_status="SCHEDULED")
        assert ns.slot_x["status"] == "SCHEDULED"

        return_chassis(api, ns.chassis_x["id"], RETURN_REASON)

        chassis = read_chassis(api, ns.chassis_x["id"])
        assert chassis["status"] == "RETURNED"
        assert chassis["allocated_upfit_order_id"] is None
        order_x = read_order(api, ns.order_x["id"])
        assert_order_dimensions(order_x, build_status="CHASSIS_HOLD")
        assert order_x["chassis_id"] is None

    def test_the_returned_units_scheduled_window_is_cancelled(self, api):
        """The second hop cancels the window that unit was going to occupy.

        The scheduled window on the returned chassis is cancelled outright rather
        than left standing against a truck that is no longer in the plant.

        Design: Difficulty/transitive_cascade/chassis_return_cascades_four_hops_into_queue_promotion
        """
        ns = _two_orders_one_bay(api)

        return_chassis(api, ns.chassis_x["id"], RETURN_REASON)

        assert read_slot(api, ns.slot_x["id"])["status"] == "CANCELLED"

    def test_the_freed_window_promotes_the_queued_slot_and_its_order(self, api):
        """The third and fourth hops reach an order that was never touched.

        The waiting window is promoted out of the queue with a promotion stamp
        taken from the logical clock, its own order steps from RELEASED to
        SCHEDULED, and that order's unit keeps the binding it already had.

        Design: Difficulty/transitive_cascade/chassis_return_cascades_four_hops_into_queue_promotion
        """
        ns = _two_orders_one_bay(api)
        assert ns.slot_y["status"] == "QUEUED"
        assert_order_dimensions(ns.order_y, build_status="RELEASED")

        return_chassis(api, ns.chassis_x["id"], RETURN_REASON)

        slot_y = read_slot(api, ns.slot_y["id"])
        assert slot_y["status"] == "SCHEDULED"
        assert_clock_origin_timestamp(slot_y["promoted_from_queue_at"])
        assert_order_dimensions(read_order(api, ns.order_y["id"]), build_status="SCHEDULED")
        chassis_y = read_chassis(api, ns.chassis_y["id"])
        assert chassis_y["status"] == "ALLOCATED"
        assert chassis_y["allocated_upfit_order_id"] == ns.order_y["id"]
