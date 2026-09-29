"""Values sitting exactly on a ceiling, and the same values one unit past it.

The chassis aux-amp ceiling and the contracted payload floor are both inclusive
boundaries, so the interesting pair of cases differs by a single amp and a
single pound.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_AUX_ELECTRICAL_LOAD_EXCEEDED,
    ERR_PAYLOAD_SHORTFALL,
)
from test_helpers.assertions import assert_order_commitments, assert_order_dimensions
from test_helpers.constants import vin_f450
from test_helpers.fixtures import (
    allocate,
    catalog_dump,
    new_configuration,
    new_customer,
    new_order,
    plan_equipment,
    projection,
    propose_interface,
    read_interface,
    read_order,
    received_and_inspected_chassis,
    release,
    submit_engineering,
)


def _dump_order_at_the_amp_ceiling(api):
    """A dump build whose body and hoist leave exactly 27 of the 40 amps free."""
    ns = catalog_dump(api)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-DUMP-B")
    ns.chassis = received_and_inspected_chassis(
        api, ns.cm["id"], availability_date="2026-08-10", measured=(4180, 2320)
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-2201",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=96,
        required_payload_lb=2000,
        requested_in_service_date="2026-09-15",
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    ns.hoist_install = plan_equipment(
        api, ns.order["id"], ns.hoist["id"], 130, "PRIMARY", headers=users.TECHNICIAN
    )
    ns.interface_at_ceiling = propose_interface(
        api, ns.order["id"], "BODY_BUILDER_MODULE", 27, "BODY_CONTROLLER"
    )
    ns.interface_over_ceiling = propose_interface(
        api, ns.order["id"], "BODY_BUILDER_MODULE", 1, "DISCRETE_CIRCUIT"
    )
    return ns


def _dump_order_with_required_payload(
    api, required_payload_lb, *, order_number, serial, config_code="CFG-DUMP-B", catalog=None
):
    ns = catalog or catalog_dump(api)
    ns.customer = getattr(ns, "customer", None) or new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code=config_code)
    ns.chassis = received_and_inspected_chassis(
        api,
        ns.cm["id"],
        vin=vin_f450(serial),
        availability_date="2026-08-10",
        measured=(4180, 2320),
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number=order_number,
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=96,
        required_payload_lb=required_payload_lb,
        requested_in_service_date="2026-09-15",
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    ns.hoist_install = plan_equipment(
        api, ns.order["id"], ns.hoist["id"], 130, "PRIMARY", headers=users.TECHNICIAN
    )
    ns.order = submit_engineering(api, ns.order["id"])
    return ns


class TestAuxLoadCeilingBoundary:
    """Forty amps is allowed on a forty-amp chassis; forty-one is not."""

    def test_an_interface_landing_exactly_on_the_ceiling_is_approved(self, api):
        """Thirteen amps of body and hoist plus twenty-seven make the ceiling exactly.

        Approval succeeds and the order's committed aux draw sits on the chassis
        maximum of forty amps rather than one short of it.

        Design: Difficulty/boundary_precision_check/aux_electrical_load_exactly_at_chassis_ceiling_then_one_amp_over
        """
        ns = _dump_order_at_the_amp_ceiling(api)

        approved = validate_success(
            api.approve_interface(ns.interface_at_ceiling["id"], users.OFFICER)
        )

        assert approved["status"] == "APPROVED"
        assert_order_commitments(read_order(api, ns.order["id"]), aux_amps=40)
        assert ns.cm["max_aux_amp_draw"] == 40

    def test_one_amp_beyond_the_ceiling_is_refused(self, api):
        """A single further amp cannot be approved onto the same chassis.

        The one-amp interface on the other signal source is refused, stays
        PROPOSED, and leaves the committed load exactly where it was — a failed
        approval contributes nothing.

        Design: Difficulty/boundary_precision_check/aux_electrical_load_exactly_at_chassis_ceiling_then_one_amp_over
        """
        ns = _dump_order_at_the_amp_ceiling(api)
        validate_success(api.approve_interface(ns.interface_at_ceiling["id"], users.OFFICER))

        response = api.approve_interface(ns.interface_over_ceiling["id"], users.OFFICER)

        validate_error(response, ERR_AUX_ELECTRICAL_LOAD_EXCEEDED, 422)
        assert read_interface(api, ns.interface_over_ceiling["id"])["status"] == "PROPOSED"
        assert_order_commitments(read_order(api, ns.order["id"]), aux_amps=40)

    def test_a_body_builder_module_leaves_the_chassis_warranty_intact(self, api):
        """Loading the chassis to its limit is not by itself a warranty concern.

        A body builder module on either bus has no warranty impact, so the order
        keeps an INTACT chassis warranty posture even at the ceiling.

        Design: Difficulty/boundary_precision_check/aux_electrical_load_exactly_at_chassis_ceiling_then_one_amp_over
        """
        ns = _dump_order_at_the_amp_ceiling(api)

        approved = validate_success(
            api.approve_interface(ns.interface_at_ceiling["id"], users.OFFICER)
        )

        assert approved["warranty_impact"] == "NONE"
        assert_order_commitments(read_order(api, ns.order["id"]), warranty_status="INTACT")


class TestRequiredPayloadBoundary:
    """A capacity of 2999 pounds satisfies a contract for 2999 but not for 3000."""

    def test_capacity_equal_to_the_contracted_payload_passes_the_gate(self, api):
        """The boundary is inclusive: equal capacity is enough to release.

        The order releases and is priced at 1966000 cents — body, hoist and
        fourteen dump labour hours with no tier discount, plus the lowest
        certification fee.

        Design: Difficulty/boundary_precision_check/payload_capacity_exactly_equals_required_payload_at_release
        """
        ns = _dump_order_with_required_payload(api, 2999, order_number="UO-2301", serial=4)

        released = release(api, ns.order["id"])

        assert_order_dimensions(released, build_status="RELEASED")
        assert_order_commitments(released, invoice_cents=1966000)

    def test_one_pound_more_of_contracted_payload_fails_the_gate(self, api):
        """Asking for a single pound more than the truck can carry is refused.

        The identical build with a 3000-pound contract is refused for payload
        shortfall, stays under engineering review and is never priced.

        Design: Difficulty/boundary_precision_check/payload_capacity_exactly_equals_required_payload_at_release
        """
        ns = _dump_order_with_required_payload(api, 3000, order_number="UO-2302", serial=5)

        response = api.release_order(ns.order["id"], users.SCHEDULER)

        validate_error(response, ERR_PAYLOAD_SHORTFALL, 422)
        order = read_order(api, ns.order["id"])
        assert_order_dimensions(order, build_status="ENGINEERING_REVIEW")
        assert order["invoice_total_cents"] == 0

    def test_the_two_builds_compute_the_same_capacity(self, api):
        """Only the contract differs; the truck is the same in both cases.

        Both orders project a design payload capacity of 2999 pounds, so the
        divergent outcomes come from the comparison against required_payload_lb
        and from nothing else.

        Design: Difficulty/boundary_precision_check/payload_capacity_exactly_equals_required_payload_at_release
        """
        equal_case = _dump_order_with_required_payload(
            api, 2999, order_number="UO-2301", serial=4, config_code="CFG-DUMP-EQ"
        )
        assert projection(api, equal_case.order["id"], "AS_DESIGNED")["payload_capacity_lb"] == 2999
        assert equal_case.order["required_payload_lb"] == 2999

        over_case = _dump_order_with_required_payload(
            api,
            3000,
            order_number="UO-2302",
            serial=5,
            config_code="CFG-DUMP-OVER",
            catalog=equal_case,
        )
        assert projection(api, over_case.order["id"], "AS_DESIGNED")["payload_capacity_lb"] == 2999
        assert over_case.order["required_payload_lb"] == 3000
