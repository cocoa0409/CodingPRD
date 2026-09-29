"""Single edges of the order, chassis, slot, interface and installation machines.

Some edges fan out across several rows at once, some are refused because a
neighbouring row is in the wrong state, and the terminal states refuse everything
that is offered to them.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_CHASSIS_INVALID_STATE,
    ERR_INSTALLATION_INVALID_STATE,
    ERR_ORDER_INVALID_STATE,
)
from test_helpers.assertions import assert_order_commitments, assert_order_dimensions
from test_helpers.fixtures import (
    allocate,
    cancel_order,
    cancel_slot,
    catalog_service,
    close_slot,
    delivered_service_order,
    install_body,
    install_equipment,
    new_configuration,
    new_customer,
    new_order,
    new_slot,
    new_work_bay,
    order_version,
    plan_equipment,
    propose_interface,
    read_chassis,
    read_installation,
    read_interface,
    read_order,
    read_slot,
    received_and_inspected_chassis,
    release,
    request_rework,
    start_slot,
    submit_engineering,
)


def _catalog_customer_and_config(api, *, with_equipment=False):
    ns = catalog_service(api, with_equipment=with_equipment)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    return ns


def _draft_order(api, order_number, *, with_equipment=False):
    ns = _catalog_customer_and_config(api, with_equipment=with_equipment)
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number=order_number,
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    return ns


def _released_order_with_bay(api, order_number, *, with_equipment=False, bay_overrides=None):
    ns = _draft_order(api, order_number, with_equipment=with_equipment)
    ns.bay = new_work_bay(api, bay_overrides) if bay_overrides else new_work_bay(api)
    ns.chassis = received_and_inspected_chassis(api, ns.cm["id"], measured=(4905, 2755))
    allocate(api, ns.order["id"], ns.chassis["id"])
    submit_engineering(api, ns.order["id"])
    ns.order = release(api, ns.order["id"])
    return ns


class TestDeclaredInitialStates:
    """A brand new order and an untouched truck start exactly where the contract says."""

    def test_a_new_order_starts_on_all_three_declared_initial_states(self, clocked_api):
        """The three dimensions and the counters all start from their declared values.

        The order is a draft with nothing certified and no body on, carries no
        truck and no weighed body, has never been sent back for rework, and the
        truck standing in the yard is untouched by the order being opened.

        Design: Corner/state_machines/chassis_and_order_dimensions_start_in_declared_initial_states
        """
        ns = _catalog_customer_and_config(clocked_api)
        chassis = validate_success(
            clocked_api.receive_chassis(
                {
                    "vin": "1FDUF5HT0AA100001",
                    "chassis_model_id": ns.cm["id"],
                    "ownership": "POOL_STOCK",
                    "availability_date": "2026-08-05",
                },
                users.ADMIN,
            ),
            201,
        )

        order = validate_success(
            clocked_api.create_upfit_order(
                {
                    "order_number": "UO-5006",
                    "order_type": "CUSTOMER_SPECIFIC",
                    "customer_id": ns.customer["id"],
                    "build_configuration_id": ns.config["id"],
                    "body_mount_offset_from_front_axle_in": 120,
                },
                users.SCHEDULER,
            ),
            201,
        )

        assert_order_dimensions(
            order,
            build_status="DRAFT",
            compliance_status="NOT_STARTED",
            body_install_status="PLANNED",
        )
        assert order["chassis_id"] is None
        assert order["body_actual_weight_lb"] is None
        assert order["rework_round"] == 0
        assert read_chassis(clocked_api, chassis["id"])["status"] == "RECEIVED"


class TestSlotStartFansOut:
    """Starting work in a bay moves the window, the order and the truck together."""

    def test_starting_the_window_moves_three_rows_and_leaves_the_others_alone(self, api):
        """One call, three transitions, and two dimensions deliberately untouched.

        The window goes to IN_BUILD in the response itself, the order follows to
        IN_BUILD and the truck to IN_UPFIT, while the compliance and body-install
        dimensions stay where they were and the window still carries the truck
        stamped on it at booking time.

        Design: Corner/state_machines/slot_start_moves_slot_order_and_chassis_in_one_call
        """
        ns = _released_order_with_bay(api, "UO-5007")
        slot = new_slot(
            api, ns.order["id"], ns.bay["id"], "2026-09-01", "2026-09-10", slot_type="FINAL_QC"
        )

        started = validate_success(api.start_build_slot(slot["id"], users.TECHNICIAN))

        assert started["status"] == "IN_BUILD"
        assert started["chassis_id"] == ns.chassis["id"]
        assert_order_dimensions(
            read_order(api, ns.order["id"]),
            build_status="IN_BUILD",
            compliance_status="NOT_STARTED",
            body_install_status="PLANNED",
        )
        assert read_chassis(api, ns.chassis["id"])["status"] == "IN_UPFIT"


class TestSubmitEngineeringHappensOnce:
    """An order already under engineering review cannot be submitted again."""

    def test_a_second_submission_is_refused_but_a_rework_round_reopens_the_edge(self, api):
        """The edge is closed from ENGINEERING_REVIEW and reopened from REWORK.

        The repeat submission is refused on the order's state and changes neither
        the state, the rework counter nor the version; sending the order back for
        rework raises the counter to one and the identical submission then
        succeeds and lands on engineering review again.

        Design: Corner/state_machines/second_submit_engineering_on_the_same_order_is_rejected
        """
        ns = _draft_order(api, "UO-5008")
        submitted = submit_engineering(api, ns.order["id"])
        version_before = order_version(api, ns.order["id"])

        response = api.submit_engineering(ns.order["id"], users.ENGINEER)

        validate_error(response, ERR_ORDER_INVALID_STATE, 409)
        order = read_order(api, ns.order["id"])
        assert_order_dimensions(order, build_status="ENGINEERING_REVIEW")
        assert order["rework_round"] == 0
        assert order["version"] == version_before == submitted["version"]

        reworked = request_rework(api, ns.order["id"], "engineering must revisit the mount offset")
        assert_order_dimensions(reworked, build_status="REWORK")
        assert reworked["rework_round"] == 1
        resubmitted = validate_success(api.submit_engineering(ns.order["id"], users.ENGINEER))
        assert_order_dimensions(resubmitted, build_status="ENGINEERING_REVIEW")


class TestTerminalStatesRefuseEverything:
    """A delivered order and a completed truck are the end of the line."""

    def test_every_further_trigger_on_a_delivered_truck_is_refused(self, api):
        """Cancellation, return, quarantine, resubmission and redelivery all bounce.

        The delivered order refuses cancellation on its state and stays DELIVERED
        and LABELED, the handed-over truck reads COMPLETED and refuses both return
        and quarantine, and neither a second engineering submission nor a second
        delivery is accepted.

        Design: Corner/state_machines/delivered_order_and_completed_chassis_refuse_every_further_trigger
        """
        ns = delivered_service_order(api, order_type="CUSTOMER_SPECIFIC")

        validate_error(
            api.cancel_order(
                ns.order["id"], {"reason": "customer walked away after delivery"}, users.ADMIN
            ),
            ERR_ORDER_INVALID_STATE,
            409,
        )

        assert_order_dimensions(
            read_order(api, ns.order["id"]),
            build_status="DELIVERED",
            compliance_status="LABELED",
        )
        assert read_chassis(api, ns.chassis["id"])["status"] == "COMPLETED"
        validate_error(
            api.return_chassis(
                ns.chassis["id"], {"reason": "fleet wants the unit sent back"}, users.ADMIN
            ),
            ERR_CHASSIS_INVALID_STATE,
            409,
        )
        validate_error(
            api.quarantine_chassis(
                ns.chassis["id"], {"quarantine_reason": "paint defect reported"}, users.ADMIN
            ),
            ERR_CHASSIS_INVALID_STATE,
            409,
        )
        validate_error(
            api.submit_engineering(ns.order["id"], users.ENGINEER), ERR_ORDER_INVALID_STATE, 409
        )
        validate_error(
            api.deliver_order(ns.order["id"], users.SCHEDULER), ERR_ORDER_INVALID_STATE, 409
        )


class TestInterfaceSupersession:
    """Approving a second interface on one signal source retires the first."""

    def test_the_earlier_approved_interface_on_the_same_source_is_superseded(self, api):
        """Only one approved interface may own a signal source at a time.

        Approving the eight-amp proposal retires the twenty-amp incumbent, and the
        order's committed auxiliary load counts the body plus the survivor alone;
        a body builder module on this chassis bus carries no warranty consequence,
        so the chassis warranty posture stays intact.

        Design: Corner/state_machines/interface_approval_supersedes_the_prior_interface_on_the_same_signal_source
        """
        ns = _draft_order(api, "UO-5011")
        first = propose_interface(api, ns.order["id"], "BODY_BUILDER_MODULE", 20, "BODY_CONTROLLER")
        second = propose_interface(api, ns.order["id"], "BODY_BUILDER_MODULE", 8, "BODY_CONTROLLER")
        validate_success(api.approve_interface(first["id"], users.OFFICER))

        approved = validate_success(api.approve_interface(second["id"], users.OFFICER))

        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "co-1"
        assert read_interface(api, first["id"])["status"] == "SUPERSEDED"
        assert_order_commitments(
            read_order(api, ns.order["id"]), aux_amps=20, warranty_status="INTACT"
        )
        assert read_interface(api, first["id"])["warranty_impact"] == "NONE"
        assert approved["warranty_impact"] == "NONE"


class TestInstallRequiresAnOpenWindow:
    """An item may only be bolted on while the truck is actually under work."""

    def test_installing_before_any_window_starts_is_refused_on_the_order(self, api):
        """The installation is fine; the order has not reached the floor yet.

        The refusal is about the order still being merely released rather than
        about the installation, whose own status is a perfectly valid PLANNED with
        no weight recorded and no hydraulic involvement, and the committed
        auxiliary load is unchanged by the attempt. Once a window is booked and
        started the identical call succeeds and records the weighed liftgate.

        Design: Corner/state_machines/equipment_install_before_the_bay_slot_starts_is_rejected
        """
        ns = _draft_order(api, "UO-5012", with_equipment=True)
        ns.bay = new_work_bay(api)
        ns.chassis = received_and_inspected_chassis(api, ns.cm["id"], measured=(4905, 2755))
        lift = plan_equipment(
            api, ns.order["id"], ns.liftgate["id"], 320, "NONE", headers=users.TECHNICIAN
        )
        allocate(api, ns.order["id"], ns.chassis["id"])
        submit_engineering(api, ns.order["id"])
        ns.order = release(api, ns.order["id"])
        assert_order_dimensions(ns.order, build_status="RELEASED")

        error = validate_error(
            api.install_equipment(lift["id"], {"actual_weight_lb": 795}, users.TECHNICIAN),
            ERR_ORDER_INVALID_STATE,
            409,
        )

        assert error["error_id"] != ERR_INSTALLATION_INVALID_STATE
        planned = read_installation(api, lift["id"])
        assert planned["status"] == "PLANNED"
        assert planned["actual_weight_lb"] is None
        assert planned["hydraulic_status"] == "NOT_APPLICABLE"
        assert planned["allocated_flow_gpm"] == 0
        assert_order_commitments(read_order(api, ns.order["id"]), aux_amps=42)

        slot = new_slot(
            api, ns.order["id"], ns.bay["id"], "2026-09-01", "2026-09-10", slot_type="FINAL_QC"
        )
        start_slot(api, slot["id"])
        installed = install_equipment(api, lift["id"], 795)
        assert installed["status"] == "INSTALLED"
        assert installed["actual_weight_lb"] == 795
        assert_order_commitments(read_order(api, ns.order["id"]), aux_amps=42)


class TestSlotCloseWithoutAMountedBody:
    """Closing the only window does not finish a build whose body is not on."""

    def test_the_order_stays_in_build_when_the_body_is_still_missing(self, api):
        """The bubble-up to BUILD_COMPLETE is conditional and does not fire here.

        The window closes, but the order stays IN_BUILD with the body still merely
        planned, delivery is refused, and the truck is still recorded as being
        worked on.

        Design: Corner/state_machines/slot_close_without_a_mounted_body_leaves_the_order_in_build
        """
        ns = _released_order_with_bay(api, "UO-5013")
        slot = new_slot(
            api, ns.order["id"], ns.bay["id"], "2026-09-01", "2026-09-10", slot_type="FINAL_QC"
        )
        start_slot(api, slot["id"])

        closed = validate_success(api.close_build_slot(slot["id"], users.TECHNICIAN))

        assert closed["status"] == "CLOSED"
        assert_order_dimensions(
            read_order(api, ns.order["id"]),
            build_status="IN_BUILD",
            body_install_status="PLANNED",
        )
        validate_error(
            api.deliver_order(ns.order["id"], users.SCHEDULER), ERR_ORDER_INVALID_STATE, 409
        )
        assert read_chassis(api, ns.chassis["id"])["status"] == "IN_UPFIT"


class TestBuildCompleteBubbleUp:
    """With the body on and no window left open, the build reports itself complete."""

    def test_closing_the_last_open_window_completes_the_build(self, api):
        """A cancelled sibling window counts as gone, so the last close finishes the job.

        The started window closes and the order bubbles to BUILD_COMPLETE because
        nothing is queued, scheduled or under work any more and the body is on; the
        cancelled sibling stayed cancelled without moving the order itself, the
        truck is still in the shop because only delivery completes it, and delivery
        is refused while nothing has been certified.

        Design: Corner/state_machines/order_bubbles_to_build_complete_when_the_last_slot_closes
        """
        ns = _released_order_with_bay(
            api,
            "UO-5014",
            bay_overrides={
                "code": "BAY-2",
                "concurrent_capacity": 2,
                "supported_body_types": ["SERVICE", "DUMP", "FLATBED", "VAN"],
            },
        )
        slot_a = new_slot(
            api, ns.order["id"], ns.bay["id"], "2026-09-01", "2026-09-05", slot_type="BODY_MOUNT"
        )
        slot_b = new_slot(
            api,
            ns.order["id"],
            ns.bay["id"],
            "2026-09-06",
            "2026-09-10",
            slot_type="EQUIPMENT_INTEGRATION",
        )
        start_slot(api, slot_a["id"])
        install_body(api, ns.order["id"], 2160)
        cancel_slot(api, slot_b["id"], "equipment integration not needed on this unit")

        closed = close_slot(api, slot_a["id"])

        assert closed["status"] == "CLOSED"
        assert_order_dimensions(
            read_order(api, ns.order["id"]),
            build_status="BUILD_COMPLETE",
            compliance_status="NOT_STARTED",
            body_install_status="INSTALLED",
        )
        assert read_slot(api, slot_b["id"])["status"] == "CANCELLED"
        assert read_chassis(api, ns.chassis["id"])["status"] == "IN_UPFIT"
        validate_error(
            api.deliver_order(ns.order["id"], users.SCHEDULER), ERR_ORDER_INVALID_STATE, 409
        )


class TestOrderCancellationReleasesResources:
    """Cancelling a released order hands the truck back and strips planned items."""

    def test_cancellation_returns_the_truck_to_the_inspected_pool(self, api):
        """The scale ticket survives the cancellation; the binding does not.

        The order lands at CANCELLED, the truck returns to INSPECTED rather than
        RECEIVED with its weights intact and no order attached, the planned
        liftgate is stripped to REMOVED, and the customer assignment stamped at
        allocation is not undone. The cancellation cascade of §3.3 recomputes
        ``committed_pto_flow_gpm`` and nothing else, so the auxiliary figure is
        left exactly where planning the liftgate put it — the body's twelve amps
        plus the liftgate's thirty — even though that row is now removed.

        Design: Corner/state_machines/order_cancel_returns_the_bound_chassis_to_inspected
        """
        ns = _draft_order(api, "UO-5015", with_equipment=True)
        ns.chassis = received_and_inspected_chassis(api, ns.cm["id"], measured=(4905, 2755))
        lift = plan_equipment(
            api, ns.order["id"], ns.liftgate["id"], 320, "NONE", headers=users.TECHNICIAN
        )
        allocate(api, ns.order["id"], ns.chassis["id"])
        submit_engineering(api, ns.order["id"])
        release(api, ns.order["id"])

        cancelled = cancel_order(api, ns.order["id"], "customer cancelled the purchase order")

        assert_order_dimensions(cancelled, build_status="CANCELLED")
        chassis = read_chassis(api, ns.chassis["id"])
        assert chassis["status"] == "INSPECTED"
        assert chassis["allocated_upfit_order_id"] is None
        assert chassis["measured_front_axle_weight_lb"] == 4905
        assert chassis["measured_rear_axle_weight_lb"] == 2755
        assert chassis["ownership"] == "CUSTOMER_ASSIGNED"
        assert read_installation(api, lift["id"])["status"] == "REMOVED"
        # PRD 3.3: "the order's `committed_pto_flow_gpm` is recomputed
        # accordingly" is the only recomputation the cancellation cascade names,
        # unlike the removal cascade of 3.4 which names both figures explicitly.
        assert_order_commitments(read_order(api, ns.order["id"]), flow_gpm=0, aux_amps=42)
