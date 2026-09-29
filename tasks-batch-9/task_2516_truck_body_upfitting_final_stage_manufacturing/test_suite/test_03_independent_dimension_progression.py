"""Progressions that are not a single straight line.

An order carries three dimensions that move on their own schedules, and an
equipment installation can be commissioned, taken back out of service and
commissioned again without ever giving up its share of the hydraulic pool.
"""

from test_helpers import test_users as users
from test_helpers.assertions import assert_order_commitments, assert_order_dimensions
from test_helpers.fixtures import (
    allocate,
    approve_certification,
    catalog_service,
    commission_equipment,
    decommission_equipment,
    draft_certification,
    install_equipment,
    new_configuration,
    new_customer,
    new_order,
    new_slot,
    new_work_bay,
    plan_equipment,
    read_certification,
    read_installation,
    read_order,
    received_and_inspected_chassis,
    release,
    request_rework,
    start_slot,
    submit_engineering,
)


def _certified_review_world(api):
    """A service order under engineering review with a drafted design certification."""
    ns = catalog_service(api, with_equipment=False)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis = received_and_inspected_chassis(api, ns.cm["id"], measured=(4820, 2680))
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-1301",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
        required_payload_lb=5000,
        requested_in_service_date="2026-09-15",
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    ns.order = submit_engineering(api, ns.order["id"])
    ns.cert = draft_certification(
        api, ns.order["id"], "AS_DESIGNED", expected_version=ns.order["version"]
    )
    return ns


def _crane_in_build_world(api):
    """A released service order in a started integration window with the crane bolted on."""
    ns = catalog_service(api)
    ns.bay = new_work_bay(api)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis = received_and_inspected_chassis(api, ns.cm["id"], measured=(4820, 2680))
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-1401",
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
    ns.order = release(api, ns.order["id"])
    ns.slot = new_slot(
        api,
        ns.order["id"],
        ns.bay["id"],
        "2026-09-01",
        "2026-09-10",
        slot_type="EQUIPMENT_INTEGRATION",
    )
    ns.slot = start_slot(api, ns.slot["id"])
    ns.crane_install = install_equipment(api, ns.crane_install["id"], 1250)
    return ns


class TestOrderDimensionsAdvanceIndependently:
    """Production, compliance and body installation are three separate tracks."""

    def test_approving_a_design_certification_moves_compliance_alone(self, api):
        """Certification approval does not touch where the truck is in production.

        The order stays under engineering review while its compliance dimension
        steps to DESIGN_CERTIFIED, and the body is still only planned.

        Design: Difficulty/non_linear_state_machine/order_build_and_compliance_dimensions_advance_independently
        """
        ns = _certified_review_world(api)

        approve_certification(api, ns.cert["id"], headers=users.OFFICER)

        order = read_order(api, ns.order["id"])
        assert_order_dimensions(
            order,
            build_status="ENGINEERING_REVIEW",
            compliance_status="DESIGN_CERTIFIED",
            body_install_status="PLANNED",
        )

    def test_rework_and_resubmission_move_production_without_undoing_compliance(self, api):
        """A trip back through rework leaves the approved certification standing.

        Requesting rework drops production to REWORK and counts a rework round,
        and resubmitting brings it back to engineering review; through both moves
        the compliance dimension stays at DESIGN_CERTIFIED.

        Design: Difficulty/non_linear_state_machine/order_build_and_compliance_dimensions_advance_independently
        """
        ns = _certified_review_world(api)
        approve_certification(api, ns.cert["id"], headers=users.OFFICER)

        reworked = request_rework(
            api, ns.order["id"], "reposition the compartment doors", headers=users.OFFICER
        )
        assert_order_dimensions(
            reworked, build_status="REWORK", compliance_status="DESIGN_CERTIFIED"
        )
        assert reworked["rework_round"] == 1

        resubmitted = submit_engineering(api, ns.order["id"])
        assert_order_dimensions(
            resubmitted,
            build_status="ENGINEERING_REVIEW",
            compliance_status="DESIGN_CERTIFIED",
        )
        assert resubmitted["rework_round"] == 1

    def test_release_after_rework_carries_both_dimensions_forward_unchanged(self, api):
        """The end state pairs a released build with an already certified design.

        Release advances production only; the certification is still APPROVED in
        the name of the officer who approved it, the rework round is still one,
        and the body has not been bolted down.

        Design: Difficulty/non_linear_state_machine/order_build_and_compliance_dimensions_advance_independently
        """
        ns = _certified_review_world(api)
        approve_certification(api, ns.cert["id"], headers=users.OFFICER)
        request_rework(
            api, ns.order["id"], "reposition the compartment doors", headers=users.OFFICER
        )
        submit_engineering(api, ns.order["id"])

        released = release(api, ns.order["id"])

        assert_order_dimensions(
            released,
            build_status="RELEASED",
            compliance_status="DESIGN_CERTIFIED",
            body_install_status="PLANNED",
        )
        assert released["rework_round"] == 1
        certification = read_certification(api, ns.cert["id"])
        assert certification["status"] == "APPROVED"
        assert certification["approved_by_user_id"] == "co-1"


class TestInstallationCommissioningCycle:
    """An installation may leave and re-enter service inside one build."""

    def test_decommissioning_returns_a_commissioned_installation_to_installed(self, api):
        """A fault found on the function test steps the crane back one state.

        The crane goes INSTALLED, COMMISSIONED and back to INSTALLED, which is a
        backwards step inside the installation lifecycle rather than a removal.

        Design: Difficulty/non_linear_state_machine/equipment_installation_commission_decommission_recommission_cycle
        """
        ns = _crane_in_build_world(api)
        assert ns.crane_install["status"] == "INSTALLED"

        commissioned = commission_equipment(api, ns.crane_install["id"])
        assert commissioned["status"] == "COMMISSIONED"

        decommissioned = decommission_equipment(
            api, ns.crane_install["id"], "boom rotation fault found during function test"
        )
        assert decommissioned["status"] == "INSTALLED"

    def test_the_same_installation_can_be_commissioned_a_second_time(self, api):
        """Once the fault is cleared the crane is commissioned again.

        The observed sequence over the whole cycle is INSTALLED, COMMISSIONED,
        INSTALLED, COMMISSIONED on one and the same installation row.

        Design: Difficulty/non_linear_state_machine/equipment_installation_commission_decommission_recommission_cycle
        """
        ns = _crane_in_build_world(api)
        sequence = [ns.crane_install["status"]]

        sequence.append(commission_equipment(api, ns.crane_install["id"])["status"])
        sequence.append(
            decommission_equipment(
                api, ns.crane_install["id"], "boom rotation fault found during function test"
            )["status"]
        )
        sequence.append(commission_equipment(api, ns.crane_install["id"])["status"])

        assert sequence == ["INSTALLED", "COMMISSIONED", "INSTALLED", "COMMISSIONED"]
        assert read_installation(api, ns.crane_install["id"])["status"] == "COMMISSIONED"

    def test_the_flow_grant_survives_every_step_of_the_cycle(self, api):
        """Going out of service does not hand the hydraulic pool back.

        The crane keeps its eight gallon per minute grant and an OK hydraulic
        status at every point in the cycle, including while it is decommissioned,
        so the order's committed flow never moves off eight.

        Design: Difficulty/non_linear_state_machine/equipment_installation_commission_decommission_recommission_cycle
        """
        ns = _crane_in_build_world(api)
        observed = []

        for step in (
            lambda: commission_equipment(api, ns.crane_install["id"]),
            lambda: decommission_equipment(
                api, ns.crane_install["id"], "boom rotation fault found during function test"
            ),
            lambda: commission_equipment(api, ns.crane_install["id"]),
        ):
            record = step()
            observed.append((record["allocated_flow_gpm"], record["hydraulic_status"]))
            assert_order_commitments(read_order(api, ns.order["id"]), flow_gpm=8)

        assert observed == [(8, "OK"), (8, "OK"), (8, "OK")]
        order = read_order(api, ns.order["id"])
        assert_order_commitments(order, flow_gpm=8, aux_amps=22)
        assert_order_dimensions(order, build_status="IN_BUILD")
