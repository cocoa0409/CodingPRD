"""Operations on one row that are gated by the state of a different row.

Binding a unit to an order depends on the unit's custody state, and approving a
measured certification depends on whether the body is actually on the frame.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import test_users as users
from test_helpers.api_errors import ERR_CHASSIS_INVALID_STATE, ERR_ORDER_INVALID_STATE
from test_helpers.assertions import assert_axle_numbers, assert_order_dimensions
from test_helpers.factories import allocate_chassis_payload
from test_helpers.fixtures import (
    allocate,
    approve_certification,
    catalog_service,
    chassis_version,
    draft_certification,
    inspect_chassis,
    install_body,
    new_configuration,
    new_customer,
    new_order,
    new_slot,
    new_work_bay,
    quarantine_chassis,
    read_certification,
    read_chassis,
    read_order,
    received_and_inspected_chassis,
    release,
    start_slot,
    submit_engineering,
)


def _quarantined_unit_and_draft_order(api):
    """A draft order with no truck, and a paint-blistered unit sitting in quarantine."""
    ns = catalog_service(api, with_equipment=False)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis = received_and_inspected_chassis(api, ns.cm["id"], measured=(4820, 2680))
    ns.chassis = quarantine_chassis(
        api, ns.chassis["id"], "cab paint blister found in receiving"
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-2401",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
        required_payload_lb=5000,
        requested_in_service_date="2026-09-15",
    )
    return ns


def _in_build_order_with_early_measured_draft(api):
    """A truck under work whose body is not on yet, carrying a premature measured draft."""
    ns = catalog_service(api, with_equipment=False)
    ns.bay = new_work_bay(api)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.chassis = received_and_inspected_chassis(api, ns.cm["id"], measured=(4905, 2755))
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-2501",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
        required_payload_lb=5000,
        requested_in_service_date="2026-09-15",
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
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
    ns.order = read_order(api, ns.order["id"])
    ns.cert_early = draft_certification(
        api, ns.order["id"], "AS_MEASURED", expected_version=ns.order["version"]
    )
    return ns


class TestAllocationDependsOnCustodyState:
    """A quarantined unit is out of the allocatable pool until it is re-inspected."""

    def test_allocating_a_quarantined_unit_is_refused(self, api):
        """The order is perfectly ready; the truck is not.

        The version supplied is the unit's current one, so nothing is stale — the
        refusal is about the unit's custody state.

        Design: Difficulty/cross_entity_state_dependency/allocate_chassis_blocked_while_unit_is_quarantined
        """
        ns = _quarantined_unit_and_draft_order(api)
        assert ns.chassis["status"] == "QUARANTINED"

        response = api.allocate_chassis(
            ns.order["id"],
            allocate_chassis_payload(ns.chassis["id"], chassis_version(api, ns.chassis["id"])),
            users.SCHEDULER,
        )

        validate_error(response, ERR_CHASSIS_INVALID_STATE, 409)

    def test_the_refused_allocation_leaves_both_rows_untouched(self, api):
        """Neither side of the binding is half-written.

        The order still has no chassis and is still a draft, and the unit is still
        quarantined with no order attached.

        Design: Difficulty/cross_entity_state_dependency/allocate_chassis_blocked_while_unit_is_quarantined
        """
        ns = _quarantined_unit_and_draft_order(api)
        validate_error(
            api.allocate_chassis(
                ns.order["id"],
                allocate_chassis_payload(
                    ns.chassis["id"], chassis_version(api, ns.chassis["id"])
                ),
                users.SCHEDULER,
            ),
            ERR_CHASSIS_INVALID_STATE,
            409,
        )

        order = read_order(api, ns.order["id"])
        assert order["chassis_id"] is None
        assert_order_dimensions(order, build_status="DRAFT")
        chassis = read_chassis(api, ns.chassis["id"])
        assert chassis["status"] == "QUARANTINED"
        assert chassis["allocated_upfit_order_id"] is None

    def test_re_inspection_reopens_the_pool_and_the_same_allocation_succeeds(self, api):
        """Re-inspection is the only way back, and it is enough.

        A fresh scale ticket returns the unit to INSPECTED, the identical
        allocation then succeeds and binds both rows, and the order's production
        dimension stays at DRAFT because binding a unit is not progress on the
        floor.

        Design: Difficulty/cross_entity_state_dependency/allocate_chassis_blocked_while_unit_is_quarantined
        """
        ns = _quarantined_unit_and_draft_order(api)

        reinspected = inspect_chassis(api, ns.chassis["id"], 4820, 2680)
        assert reinspected["status"] == "INSPECTED"

        allocate(api, ns.order["id"], ns.chassis["id"])

        chassis = read_chassis(api, ns.chassis["id"])
        assert chassis["status"] == "ALLOCATED"
        assert chassis["allocated_upfit_order_id"] == ns.order["id"]
        order = read_order(api, ns.order["id"])
        assert order["chassis_id"] == ns.chassis["id"]
        assert_order_dimensions(order, build_status="DRAFT")


class TestMeasuredApprovalDependsOnBodyInstallation:
    """A measured certification may only be approved once the body is bolted down."""

    def test_approving_a_measured_certification_before_the_body_is_on_is_refused(self, api):
        """The draft is legal but unapprovable while the frame is bare.

        The premature draft counts no components at all and reads the bare scale
        ticket, and the approval is refused on the state of the order, leaving the
        compliance dimension where it was.

        Design: Difficulty/cross_entity_state_dependency/measured_certification_approve_requires_body_installed
        """
        ns = _in_build_order_with_early_measured_draft(api)
        assert_order_dimensions(ns.order, build_status="IN_BUILD", body_install_status="PLANNED")
        assert_axle_numbers(ns.cert_early, 4905, 2755, 7660, 11840, component_count=0)

        response = api.approve_weight_certification(ns.cert_early["id"], users.OFFICER)

        validate_error(response, ERR_ORDER_INVALID_STATE, 409)
        assert_order_dimensions(
            read_order(api, ns.order["id"]), compliance_status="DESIGN_CERTIFIED"
        )

    def test_the_premature_draft_is_voided_by_the_later_draft_of_the_same_basis(self, api):
        """A second measured draft supersedes the first one outright.

        Once the body is on and a fresh measured certification is drafted, the
        earlier row is voided rather than left standing as a competing draft.

        Design: Difficulty/cross_entity_state_dependency/measured_certification_approve_requires_body_installed
        """
        ns = _in_build_order_with_early_measured_draft(api)
        validate_error(
            api.approve_weight_certification(ns.cert_early["id"], users.OFFICER),
            ERR_ORDER_INVALID_STATE,
            409,
        )

        order = install_body(api, ns.order["id"], 2160)
        draft_certification(api, ns.order["id"], "AS_MEASURED", expected_version=order["version"])

        assert read_certification(api, ns.cert_early["id"])["status"] == "VOIDED"

    def test_the_later_measured_certification_approves_and_advances_compliance(self, api):
        """With the body on the frame the same operation goes through.

        The new certification reads the mounted body and one component, the
        officer approves it, and the order reaches MEASURED_CERTIFIED with the
        body recorded as installed.

        Design: Difficulty/cross_entity_state_dependency/measured_certification_approve_requires_body_installed
        """
        ns = _in_build_order_with_early_measured_draft(api)
        validate_error(
            api.approve_weight_certification(ns.cert_early["id"], users.OFFICER),
            ERR_ORDER_INVALID_STATE,
            409,
        )

        order = install_body(api, ns.order["id"], 2160)
        later = draft_certification(
            api, ns.order["id"], "AS_MEASURED", expected_version=order["version"]
        )
        assert_axle_numbers(later, 5099, 4721, 9820, 9680, component_count=1)

        approved = validate_success(
            api.approve_weight_certification(later["id"], users.OFFICER)
        )
        assert approved["status"] == "APPROVED"
        assert_order_dimensions(
            read_order(api, ns.order["id"]),
            compliance_status="MEASURED_CERTIFIED",
            body_install_status="INSTALLED",
        )
