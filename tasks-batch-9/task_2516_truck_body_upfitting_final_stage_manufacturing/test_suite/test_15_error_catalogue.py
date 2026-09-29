"""The published error catalogue is reachable: every code can actually be fired.

Fourteen lookups on ids that were never minted, then a battery of duplicate,
publication, provisioning, scheduling and wrong-state refusals, each landing on
its own catalogued code and its own catalogued status.
"""

from types import SimpleNamespace

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_BAY_BODY_TYPE_UNSUPPORTED,
    ERR_BODY_ALREADY_INSTALLED,
    ERR_BODY_SPEC_NOT_FOUND,
    ERR_BUILD_CONFIGURATION_NOT_FOUND,
    ERR_BUILD_SLOT_NOT_FOUND,
    ERR_CHASSIS_MODEL_NOT_FOUND,
    ERR_CHASSIS_NOT_FOUND,
    ERR_CHASSIS_WARRANTY_VOIDING_INTERFACE,
    ERR_COMPLIANCE_LABEL_NOT_FOUND,
    ERR_CONFIG_INVALID_STATE,
    ERR_CONFIG_NOT_PUBLISHED,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_DUPLICATE_CONFIG_CODE,
    ERR_DUPLICATE_ORDER_NUMBER,
    ERR_DUPLICATE_VIN,
    ERR_ELECTRICAL_INTERFACE_NOT_FOUND,
    ERR_EQUIPMENT_INSTALLATION_NOT_FOUND,
    ERR_EQUIPMENT_SPEC_NOT_FOUND,
    ERR_INTERFACE_INVALID_STATE,
    ERR_ORDER_INVALID_STATE,
    ERR_PTO_NOT_PROVISIONED,
    ERR_SLOT_DATE_RANGE_INVALID,
    ERR_SLOT_INVALID_STATE,
    ERR_UPFIT_ORDER_NOT_FOUND,
    ERR_WARRANTY_CLAIM_NOT_FOUND,
    ERR_WEIGHT_CERTIFICATION_NOT_FOUND,
    ERR_WORK_BAY_NOT_FOUND,
)
from test_helpers.constants import (
    BODY_DUMP_12FT,
    BODY_SERVICE_11FT,
    CM_F350_NO_PTO,
    CM_F550,
    EQ_DUMP_HOIST_10T,
    UNKNOWN_UUIDS,
    WORK_BAY_1,
    vin_f550,
)
from test_helpers.factories import (
    build_configuration_payload,
    build_slot_payload,
    chassis_payload,
    electrical_interface_payload,
    equipment_installation_payload,
    upfit_order_payload,
)
from test_helpers.fixtures import (
    allocate,
    approve_certification,
    approve_interface,
    draft_certification,
    install_body,
    new_body_spec,
    new_chassis_model,
    new_configuration,
    new_customer,
    new_equipment_spec,
    new_order,
    new_slot,
    new_work_bay,
    pin_clock,
    propose_interface,
    read_order,
    read_slot,
    received_and_inspected_chassis,
    release,
    start_slot,
    submit_engineering,
)

BAY_VAN_ONLY = {"code": "BAY-3", "concurrent_capacity": 1, "supported_body_types": ["VAN"]}
LEAK_MARKERS = (
    "traceback",
    "sqlalchemy",
    "psycopg",
    "sqlite",
    "select ",
    "insert into",
    '.py", line',
)


def _lookup_probes(api):
    """The fourteen entity reads, in the contract's own existence-resolution order."""
    ids = UNKNOWN_UUIDS
    return [
        (api.get_chassis_model(ids[0], users.ADMIN), ERR_CHASSIS_MODEL_NOT_FOUND),
        (api.get_body_spec(ids[1], users.ADMIN), ERR_BODY_SPEC_NOT_FOUND),
        (api.get_equipment_spec(ids[2], users.ADMIN), ERR_EQUIPMENT_SPEC_NOT_FOUND),
        (api.get_work_bay(ids[3], users.ADMIN), ERR_WORK_BAY_NOT_FOUND),
        (api.get_customer(ids[4], users.ADMIN), ERR_CUSTOMER_NOT_FOUND),
        (api.get_build_configuration(ids[5], users.ENGINEER), ERR_BUILD_CONFIGURATION_NOT_FOUND),
        (api.get_chassis(ids[6], users.SCHEDULER), ERR_CHASSIS_NOT_FOUND),
        (api.get_upfit_order(ids[7], users.SCHEDULER), ERR_UPFIT_ORDER_NOT_FOUND),
        (
            api.get_equipment_installation(ids[8], users.TECHNICIAN),
            ERR_EQUIPMENT_INSTALLATION_NOT_FOUND,
        ),
        (api.get_electrical_interface(ids[9], users.ENGINEER), ERR_ELECTRICAL_INTERFACE_NOT_FOUND),
        (api.get_build_slot(ids[10], users.SCHEDULER), ERR_BUILD_SLOT_NOT_FOUND),
        (api.get_weight_certification(ids[11], users.OFFICER), ERR_WEIGHT_CERTIFICATION_NOT_FOUND),
        (api.get_compliance_label(ids[12], users.OFFICER), ERR_COMPLIANCE_LABEL_NOT_FOUND),
        (api.get_warranty_claim(ids[13], users.WARRANTY_ADMIN), ERR_WARRANTY_CLAIM_NOT_FOUND),
    ]


def _error_battery_world(api):
    """Two models, two bodies, two bays, three configurations and one released order."""
    ns = SimpleNamespace()
    pin_clock(api)
    ns.cm = new_chassis_model(api, CM_F550)
    ns.cm_no_pto = new_chassis_model(api, CM_F350_NO_PTO)
    ns.body = new_body_spec(api, BODY_SERVICE_11FT)
    ns.dump_body = new_body_spec(api, BODY_DUMP_12FT)
    ns.hoist = new_equipment_spec(api, EQ_DUMP_HOIST_10T)
    ns.bay_service = new_work_bay(api, WORK_BAY_1, supported_body_types=["SERVICE", "FLATBED"])
    ns.bay_van = new_work_bay(api, BAY_VAN_ONLY)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A")
    ns.draft_config = new_configuration(
        api, ns.cm["id"], ns.body["id"], config_code="CFG-DRAFT-X", publish=False
    )
    ns.no_pto_config = new_configuration(
        api, ns.cm_no_pto["id"], ns.dump_body["id"], config_code="CFG-NOPTO"
    )
    ns.chassis = received_and_inspected_chassis(
        api, ns.cm["id"], vin=vin_f550(26), measured=(4905, 2755)
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-5034",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=120,
    )
    ns.no_pto_order = new_order(
        api,
        ns.no_pto_config["id"],
        order_number="UO-5035",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=96,
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    submit_engineering(api, ns.order["id"])
    ns.certification = approve_certification(
        api, draft_certification(api, ns.order["id"], "AS_DESIGNED")["id"]
    )
    ns.interface = approve_interface(
        api,
        propose_interface(api, ns.order["id"], "BODY_BUILDER_MODULE", 20, "BODY_CONTROLLER")["id"],
    )
    ns.order = release(api, ns.order["id"])
    ns.slot = new_slot(
        api, ns.order["id"], ns.bay_service["id"], "2026-09-01", "2026-09-05"
    )
    return ns


class TestEveryEntityLookupCanFail:
    """Each of the fourteen entities answers a never-minted id with its own code."""

    def test_all_fourteen_lookups_report_their_own_not_found_code(self, clocked_api):
        """Fourteen reads on an empty store, fourteen distinct catalogued codes.

        Every read returns not-found, each carrying the code named for the entity
        that was asked for and nothing else.

        Design: Corner/errors/every_entity_lookup_error_is_triggerable_not_found
        """
        probes = _lookup_probes(clocked_api)

        assert len(probes) == 14
        for response, expected_error_id in probes:
            validate_error(response, expected_error_id, 404)

    def test_no_lookup_failure_leaks_internal_machinery(self, clocked_api):
        """A refusal names the code and explains itself in words, and stops there.

        Every one of the fourteen bodies carries a code and a non-empty readable
        message, and none of them contains a stack frame, a driver name or a
        fragment of query text.

        Design: Corner/errors/every_entity_lookup_error_is_triggerable_not_found
        """
        for response, expected_error_id in _lookup_probes(clocked_api):
            error = validate_error(response, expected_error_id, 404)
            message = error["message"]
            assert isinstance(message, str) and message.strip() != ""
            lowered = message.lower()
            for marker in LEAK_MARKERS:
                assert marker not in lowered, f"{expected_error_id} leaked {marker!r}: {message}"

    def test_the_same_codes_come_back_when_the_unknown_id_is_a_body_reference(self, clocked_api):
        """An unknown id in a request body is resolved exactly like one in a path.

        A configuration create naming an unknown chassis model reports the chassis
        model as missing, one naming an unknown body spec reports the body spec, and
        one naming both reports the chassis model, because the existence ladder ranks
        the chassis model ahead of the body spec.

        Design: Corner/errors/every_entity_lookup_error_is_triggerable_not_found
        """
        model = new_chassis_model(clocked_api, CM_F550)
        body = new_body_spec(clocked_api, BODY_SERVICE_11FT)

        validate_error(
            clocked_api.create_build_configuration(
                build_configuration_payload(UNKNOWN_UUIDS[0], body["id"], config_code="CFG-X1"),
                users.ENGINEER,
            ),
            ERR_CHASSIS_MODEL_NOT_FOUND,
            404,
        )
        validate_error(
            clocked_api.create_build_configuration(
                build_configuration_payload(model["id"], UNKNOWN_UUIDS[1], config_code="CFG-X2"),
                users.ENGINEER,
            ),
            ERR_BODY_SPEC_NOT_FOUND,
            404,
        )
        validate_error(
            clocked_api.create_build_configuration(
                build_configuration_payload(
                    UNKNOWN_UUIDS[0], UNKNOWN_UUIDS[1], config_code="CFG-X3"
                ),
                users.ENGINEER,
            ),
            ERR_CHASSIS_MODEL_NOT_FOUND,
            404,
        )


class TestDuplicateKeysAreRefused:
    """The three business keys the contract declares unique are each defended."""

    def test_a_second_unit_cannot_reuse_a_vehicle_identification_number(self, api):
        """A different arrival date does not make it a different truck.

        The re-used identification number is refused as a duplicate.

        Design: Corner/errors/duplicate_and_wrong_state_error_battery_is_rejected
        """
        ns = _error_battery_world(api)

        response = api.receive_chassis(
            chassis_payload(
                ns.cm["id"],
                vin=vin_f550(26),
                ownership="POOL_STOCK",
                availability_date="2026-08-06",
            ),
            users.ADMIN,
        )

        validate_error(response, ERR_DUPLICATE_VIN, 409)

    def test_configuration_codes_and_order_numbers_are_unique_across_the_plant(self, api):
        """Neither key is scoped to a model, a tier or a customer.

        A second configuration reusing the published code is refused even on a
        different standardization tier, and a second order reusing the order number
        is refused as well.

        Design: Corner/errors/duplicate_and_wrong_state_error_battery_is_rejected
        """
        ns = _error_battery_world(api)

        validate_error(
            api.create_build_configuration(
                build_configuration_payload(
                    ns.cm["id"],
                    ns.body["id"],
                    config_code="CFG-SVC-A",
                    standardization_tier="TIER_A",
                ),
                users.ENGINEER,
            ),
            ERR_DUPLICATE_CONFIG_CODE,
            409,
        )
        validate_error(
            api.create_upfit_order(
                upfit_order_payload(
                    ns.config["id"],
                    order_number="UO-5034",
                    order_type="CUSTOMER_SPECIFIC",
                    customer_id=ns.customer["id"],
                    body_mount_offset_from_front_axle_in=120,
                ),
                users.SCHEDULER,
            ),
            ERR_DUPLICATE_ORDER_NUMBER,
            409,
        )


class TestConfigurationPublicationErrors:
    """A draft cannot be ordered against and a publication cannot be repeated."""

    def test_an_unpublished_configuration_cannot_carry_an_order(self, api):
        """The engineering package must be signed off before anybody sells it.

        Opening an order against the still-draft configuration is refused on
        publication, and publishing the already-published configuration a second time
        is refused on the configuration's own state.

        Design: Corner/errors/duplicate_and_wrong_state_error_battery_is_rejected
        """
        ns = _error_battery_world(api)

        validate_error(
            api.create_upfit_order(
                upfit_order_payload(
                    ns.draft_config["id"],
                    order_number="UO-5036",
                    order_type="CUSTOMER_SPECIFIC",
                    customer_id=ns.customer["id"],
                    body_mount_offset_from_front_axle_in=120,
                ),
                users.SCHEDULER,
            ),
            ERR_CONFIG_NOT_PUBLISHED,
            409,
        )
        validate_error(
            api.publish_build_configuration(ns.config["id"], users.ENGINEER),
            ERR_CONFIG_INVALID_STATE,
            409,
        )


class TestProvisioningIsABookProperty:
    """A truck built without a power take-off can never drive a hoist."""

    def test_a_hoist_cannot_be_planned_on_an_unprovisioned_model(self, api):
        """The circuit is named correctly and it still cannot be done.

        Planning the hoist with a proper primary circuit on the order drawn against
        the unprovisioned model is refused on provisioning, and the order's committed
        flow is still nothing at all.

        Design: Corner/errors/duplicate_and_wrong_state_error_battery_is_rejected
        """
        ns = _error_battery_world(api)

        response = api.create_equipment_installation(
            equipment_installation_payload(
                ns.no_pto_order["id"],
                ns.hoist["id"],
                mount_cg_from_front_axle_in=130,
                hydraulic_circuit="PRIMARY",
            ),
            users.TECHNICIAN,
        )

        validate_error(response, ERR_PTO_NOT_PROVISIONED, 422)
        assert read_order(api, ns.no_pto_order["id"])["committed_pto_flow_gpm"] == 0


class TestSchedulingRequestShapeAndBayEligibility:
    """A backwards window and an ineligible bay are refused for their own reasons."""

    def test_a_window_that_ends_before_it_starts_is_refused(self, api):
        """The span check is what fires, not a capacity or availability complaint.

        The booking whose end date precedes its start date is refused on the date
        range, and no slot is added to the order's single existing booking.

        Design: Corner/errors/duplicate_and_wrong_state_error_battery_is_rejected
        """
        ns = _error_battery_world(api)

        response = api.create_build_slot(
            build_slot_payload(
                ns.order["id"],
                ns.bay_service["id"],
                "2026-09-20",
                "2026-09-15",
                slot_type="FINAL_QC",
            ),
            users.SCHEDULER,
        )

        validate_error(response, ERR_SLOT_DATE_RANGE_INVALID, 422)
        _, meta = validate_paginated(
            api.list_build_slots(users.SCHEDULER, {"upfit_order_id": ns.order["id"]})
        )
        assert meta["total_count"] == 1

    def test_a_bay_that_cannot_mount_this_body_family_is_refused(self, api):
        """The van bay is free on those dates and still cannot take a service body.

        The booking in the van-only bay is refused on bay eligibility even though the
        window is valid, the truck is free and the bay is empty.

        Design: Corner/errors/duplicate_and_wrong_state_error_battery_is_rejected
        """
        ns = _error_battery_world(api)

        response = api.create_build_slot(
            build_slot_payload(
                ns.order["id"],
                ns.bay_van["id"],
                "2026-09-10",
                "2026-09-12",
                slot_type="FINAL_QC",
            ),
            users.SCHEDULER,
        )

        validate_error(response, ERR_BAY_BODY_TYPE_UNSUPPORTED, 422)


class TestApprovalsAreDefinedFromOneStateOnly:
    """An approval already granted cannot be granted again by anybody."""

    def test_re_approving_an_interface_and_a_certification_are_both_refused(self, api):
        """Two artifacts, two state codes, and a second approver to prove the point.

        Re-approving the standing interface is refused on the interface's state, and
        re-approving the standing certification through a different compliance officer
        is refused on a state precondition rather than on segregation of duties,
        because that second officer never authored the certification. Per the
        precedence ladder of §2.6 the order's own dimension outranks the
        certification's, and the approved AS_DESIGNED certification has already
        carried the order off ``NOT_STARTED``, so the refusal names the order.

        Design: Corner/errors/duplicate_and_wrong_state_error_battery_is_rejected
        """
        ns = _error_battery_world(api)

        validate_error(
            api.approve_interface(ns.interface["id"], users.OFFICER),
            ERR_INTERFACE_INVALID_STATE,
            409,
        )
        validate_error(
            api.approve_weight_certification(ns.certification["id"], users.OFFICER_ALT),
            ERR_ORDER_INVALID_STATE,
            409,
        )


class TestWarrantyVoidingTapNeedsAWaiver:
    """Cutting into a multiplexed network without a signature is refused."""

    def test_a_direct_splice_on_a_network_chassis_is_refused_unwaived(self, api):
        """The computed impact voids the warranty and no customer has signed for it.

        The proposal is refused on the warranty-voiding method, and the order's
        warranty posture is still intact because nothing was recorded.

        Design: Corner/errors/duplicate_and_wrong_state_error_battery_is_rejected
        """
        ns = _error_battery_world(api)

        response = api.create_electrical_interface(
            electrical_interface_payload(
                ns.order["id"],
                interface_method="DIRECT_SPLICE",
                circuit_amp_draw=5,
                signal_source="DISCRETE_CIRCUIT",
            ),
            users.ENGINEER,
        )

        validate_error(response, ERR_CHASSIS_WARRANTY_VOIDING_INTERFACE, 422)
        assert read_order(api, ns.order["id"])["chassis_warranty_status"] == "INTACT"


class TestSlotAndBodyInstallStateErrors:
    """A window must be open before it closes, and a body goes on exactly once."""

    def test_closing_a_scheduled_window_is_refused_before_it_starts(self, api):
        """Closing is defined from work in progress only.

        The scheduled window cannot be closed, and it is still scheduled afterwards.

        Design: Corner/errors/duplicate_and_wrong_state_error_battery_is_rejected
        """
        ns = _error_battery_world(api)

        validate_error(
            api.close_build_slot(ns.slot["id"], users.TECHNICIAN), ERR_SLOT_INVALID_STATE, 409
        )
        assert read_slot(api, ns.slot["id"])["status"] == "SCHEDULED"

    def test_the_body_goes_on_once_and_the_repeat_is_refused_on_that_dimension(self, api):
        """The second bolt-down is refused for being already done.

        Starting the window puts the build on the floor and the body install records
        the weighed body, and the identical second install is refused as already
        installed rather than as a wrong order state.

        Design: Corner/errors/duplicate_and_wrong_state_error_battery_is_rejected
        """
        ns = _error_battery_world(api)
        started = start_slot(api, ns.slot["id"])
        assert started["status"] == "IN_BUILD"
        installed = install_body(api, ns.order["id"], 2160)
        assert installed["build_status"] == "IN_BUILD"
        assert installed["body_install_status"] == "INSTALLED"

        response = api.body_install(
            ns.order["id"], {"body_actual_weight_lb": 2160}, users.TECHNICIAN
        )

        validate_error(response, ERR_BODY_ALREADY_INSTALLED, 409)
        assert read_order(api, ns.order["id"])["body_actual_weight_lb"] == 2160

    def test_none_of_the_refused_calls_left_a_row_behind(self, api):
        """Twelve refusals in a row and the store is exactly as it was.

        After the whole battery the yard still holds one truck and the catalog still
        holds three configurations, and the order drawn on the unprovisioned model
        still commits no hydraulic flow.

        Design: Corner/errors/duplicate_and_wrong_state_error_battery_is_rejected
        """
        ns = _error_battery_world(api)
        api.receive_chassis(
            chassis_payload(ns.cm["id"], vin=vin_f550(26), availability_date="2026-08-06"),
            users.ADMIN,
        )
        api.create_build_configuration(
            build_configuration_payload(ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A"),
            users.ENGINEER,
        )
        api.create_upfit_order(
            upfit_order_payload(
                ns.draft_config["id"],
                order_number="UO-5036",
                order_type="CUSTOMER_SPECIFIC",
                customer_id=ns.customer["id"],
            ),
            users.SCHEDULER,
        )
        api.create_equipment_installation(
            equipment_installation_payload(
                ns.no_pto_order["id"], ns.hoist["id"], mount_cg_from_front_axle_in=130
            ),
            users.TECHNICIAN,
        )
        api.create_build_slot(
            build_slot_payload(
                ns.order["id"], ns.bay_service["id"], "2026-09-20", "2026-09-15"
            ),
            users.SCHEDULER,
        )

        _, chassis_meta = validate_paginated(api.list_chassis(users.SCHEDULER, {"limit": 50}))
        _, config_meta = validate_paginated(api.list_build_configurations(users.ENGINEER))

        assert chassis_meta["total_count"] == 1
        assert config_meta["total_count"] == 3
        assert read_order(api, ns.no_pto_order["id"])["committed_pto_flow_gpm"] == 0
