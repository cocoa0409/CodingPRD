"""Round trips over the plant's reference catalog and the rows created from it.

Every field the body-builder book carries must survive a create, defaults must be
applied exactly as declared, server-derived fields must ignore whatever a client
sends, and a bad reference must be named for what it is.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_CAB_TO_AXLE_INSUFFICIENT,
    ERR_CHASSIS_MODEL_NOT_FOUND,
    ERR_CHASSIS_NOT_FOUND,
    ERR_EQUIPMENT_SPEC_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_UPFIT_ORDER_NOT_FOUND,
    ERR_WHEELBASE_INSUFFICIENT,
)
from test_helpers.assertions import (
    assert_clock_origin_timestamp,
    assert_common_fields,
    assert_immutable_label_shape,
    assert_pagination_meta,
)
from test_helpers.constants import (
    BODY_SERVICE_11FT,
    CM_F550,
    DEFAULT_WARRANTY_LIABILITY_CAP_CENTS,
    EQ_CRANE_6000,
    EQ_DUMP_HOIST_10T,
    EQ_LIFTGATE_2500,
    UNKNOWN_UUID,
    UNKNOWN_UUIDS,
    vin_f550,
)
from test_helpers.factories import (
    REMOVE,
    build_configuration_payload,
    chassis_model_payload,
    chassis_payload,
    compliance_label_payload,
    equipment_installation_payload,
    upfit_order_payload,
    work_bay_payload,
)
from test_helpers.fixtures import (
    advance_to_in_build,
    advance_to_released,
    approve_certification,
    catalog_service,
    draft_certification,
    install_body,
    new_body_spec,
    new_chassis_model,
    new_configuration,
    new_customer,
    new_equipment_spec,
    new_order,
    read_chassis,
    read_order,
    service_order_world,
)


class TestChassisModelCatalog:
    """The body-builder book entry is stored and returned whole."""

    def test_a_new_book_entry_returns_every_declared_field(self, clocked_api):
        """Creating a model echoes back all fourteen catalog fields plus system fields.

        Nothing is dropped or coerced: the ratings, the geometry, the curb
        weights, the electrical bus, the power take-off provision and both
        document revisions all come back as sent, on a row at version one with a
        real identifier and timestamps.

        Design: Corner/entities/chassis_model_create_returns_every_book_field
        """
        response = clocked_api.create_chassis_model(chassis_model_payload(), users.ADMIN)

        record = validate_success(response, 201)
        for field, value in CM_F550.items():
            assert record[field] == value, field
        assert record["code"] == "F550-DRW-84CA"
        assert record["gvwr_lb"] == 19500
        assert record["rear_gawr_lb"] == 14706
        assert record["electrical_bus"] == "J1939_CAN"
        assert record["pto_provision"] == "FULL"
        assert is_valid_uuid(record["id"])
        assert is_iso8601_timestamp(record["created_at"])
        assert is_iso8601_timestamp(record["updated_at"])
        assert_common_fields(record, expected_version=1)


class TestBodySpecCatalog:
    """A stored body specification reads back exactly as it was filed."""

    def test_reading_a_body_specification_returns_the_stored_row(self, clocked_api):
        """An engineer reading the catalog sees the filed geometry and price.

        Weight, both centre-of-gravity offsets, the minimum cab-to-axle and
        wheelbase the body needs, its hydraulic requirement and its list price all
        come back unchanged.

        Design: Corner/entities/body_spec_retrieval_returns_the_stored_catalog_row
        """
        created = new_body_spec(clocked_api, BODY_SERVICE_11FT)

        record = validate_success(clocked_api.get_body_spec(created["id"], users.ENGINEER))

        assert record["code"] == "SERVICE-11FT"
        assert record["body_type"] == "SERVICE"
        assert record["weight_lb"] == 2100
        assert record["cg_from_body_front_in"] == 62
        assert record["cargo_cg_from_body_front_in"] == 66
        assert record["required_min_ca_in"] == 84
        assert record["required_min_wheelbase_in"] == 189
        assert record["requires_hydraulics"] is False
        assert record["list_price_cents"] == 1450000


class TestEquipmentSpecCatalog:
    """Paging and filtering the equipment catalog reports honest counts."""

    def test_a_paged_equipment_listing_reports_the_full_count_and_more_to_come(
        self, clocked_api
    ):
        """Two of three rows come back with the total and a truthful has_more.

        The first page holds two rows, the metadata reports three in total with
        more available, the second page holds the remaining row with no more to
        come, and filtering on the hydraulic requirement narrows the total itself
        to the two power-take-off items.

        Design: Corner/entities/equipment_spec_listing_reports_total_count_and_has_more
        """
        new_equipment_spec(clocked_api, EQ_CRANE_6000)
        new_equipment_spec(clocked_api, EQ_LIFTGATE_2500)
        new_equipment_spec(clocked_api, EQ_DUMP_HOIST_10T)

        first_page, first_meta = validate_paginated(
            clocked_api.list_equipment_specs(users.TECHNICIAN, {"limit": 2, "offset": 0})
        )
        assert len(first_page) == 2
        assert_pagination_meta(first_meta, limit=2, offset=0, total_count=3, has_more=True)

        second_page, second_meta = validate_paginated(
            clocked_api.list_equipment_specs(users.TECHNICIAN, {"limit": 2, "offset": 2})
        )
        assert len(second_page) == 1
        assert_pagination_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)

        hydraulic, hydraulic_meta = validate_paginated(
            clocked_api.list_equipment_specs(
                users.TECHNICIAN, {"requires_pto": True, "limit": 10}
            )
        )
        assert sorted(row["code"] for row in hydraulic) == ["CRANE-6000", "DUMP-HOIST-10T"]
        assert hydraulic_meta["total_count"] == 2


class TestChassisReceipt:
    """Receiving a truck writes only what the yard is allowed to write."""

    def test_reading_an_unknown_unit_reports_a_missing_chassis(self, clocked_api):
        """A real truck exists, so the miss is about the identifier and not the table.

        The bogus identifier yields the chassis-specific not-found, and the real
        unit is still readable afterwards.

        Design: Corner/entities/chassis_get_with_unknown_id_returns_chassis_not_found
        """
        model = new_chassis_model(clocked_api, CM_F550)
        real = validate_success(
            clocked_api.receive_chassis(
                chassis_payload(model["id"], vin=vin_f550(1), ownership="POOL_STOCK"),
                users.ADMIN,
            ),
            201,
        )

        response = clocked_api.get_chassis(UNKNOWN_UUID, users.SCHEDULER)

        validate_error(response, ERR_CHASSIS_NOT_FOUND, 404)
        assert read_chassis(clocked_api, real["id"])["id"] == real["id"]

    def test_an_omitted_ownership_defaults_to_pool_stock(self, clocked_api):
        """A unit received without an ownership statement is plant stock.

        The truck lands at RECEIVED as POOL_STOCK with no scale ticket, no order
        attached and no quarantine note, at version one.

        Design: Corner/entities/chassis_omitted_ownership_defaults_to_pool_stock
        """
        model = new_chassis_model(clocked_api, CM_F550)

        record = validate_success(
            clocked_api.receive_chassis(
                chassis_payload(model["id"], vin=vin_f550(2), ownership=REMOVE), users.ADMIN
            ),
            201,
        )

        assert record["ownership"] == "POOL_STOCK"
        assert record["status"] == "RECEIVED"
        assert record["measured_front_axle_weight_lb"] is None
        assert record["measured_rear_axle_weight_lb"] is None
        assert record["allocated_upfit_order_id"] is None
        assert record["quarantine_reason"] is None
        assert_common_fields(record, expected_version=1)

    def test_system_owned_fields_on_a_received_unit_ignore_the_request(self, clocked_api):
        """A client cannot pre-set the identity, custody or history of a truck.

        The identifier is server-generated, the status is RECEIVED regardless of
        the ALLOCATED that was sent, the order binding and quarantine note stay
        null, the version starts at one rather than ninety-nine, and the creation
        instant is the plant clock rather than the date in the request.

        Design: Corner/entities/chassis_system_fields_generated_and_input_ignored
        """
        model = new_chassis_model(clocked_api, CM_F550)

        record = validate_success(
            clocked_api.receive_chassis(
                chassis_payload(
                    model["id"],
                    vin=vin_f550(3),
                    ownership="POOL_STOCK",
                    id="11111111-1111-4111-8111-111111111111",
                    status="ALLOCATED",
                    allocated_upfit_order_id="22222222-2222-4222-8222-222222222222",
                    quarantine_reason="client says so",
                    version=99,
                    created_at="2020-01-01T00:00:00Z",
                ),
                users.ADMIN,
            ),
            201,
        )

        assert record["id"] != "11111111-1111-4111-8111-111111111111"
        assert record["status"] == "RECEIVED"
        assert record["allocated_upfit_order_id"] is None
        assert record["quarantine_reason"] is None
        assert record["version"] == 1
        assert_clock_origin_timestamp(record["created_at"])


class TestUpfitOrderCreation:
    """Opening an order applies the declared defaults and derives the rest itself."""

    def test_an_order_without_a_body_mount_offset_is_rejected(self, clocked_api):
        """The mount offset is the one geometry input the order must carry.

        Omitting it is a malformed request rather than a business-rule failure, and
        no order row is left behind under that order number.

        Design: Corner/entities/upfit_order_create_missing_body_mount_offset_rejected
        """
        ns = catalog_service(clocked_api, with_equipment=False)
        customer = new_customer(clocked_api)
        config = new_configuration(
            clocked_api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A"
        )

        response = clocked_api.create_upfit_order(
            upfit_order_payload(
                config["id"],
                order_number="UO-5001",
                order_type="CUSTOMER_SPECIFIC",
                customer_id=customer["id"],
                body_mount_offset_from_front_axle_in=REMOVE,
            ),
            users.SCHEDULER,
        )

        validate_error(response, ERR_INVALID_REQUEST, 422)
        orders, _meta = validate_paginated(clocked_api.list_upfit_orders(users.SCHEDULER))
        assert [order for order in orders if order["order_number"] == "UO-5001"] == []

    def test_omitted_order_optionals_take_their_declared_defaults(self, clocked_api):
        """A pool-stock order opened with the bare minimum is fully specified anyway.

        The contracted payload defaults to zero, the warranty liability cap to five
        million cents and the in-service date to nothing at all, no customer is
        attached, and the configuration it was opened against carries an empty
        standard-equipment list and a publication stamp at the plant clock.

        Design: Corner/entities/upfit_order_omitted_optionals_apply_declared_defaults
        """
        ns = catalog_service(clocked_api, with_equipment=False)
        config = new_configuration(
            clocked_api,
            ns.cm["id"],
            ns.body["id"],
            config_code="CFG-SVC-A",
            standardization_tier="TIER_A",
        )

        record = validate_success(
            clocked_api.create_upfit_order(
                upfit_order_payload(
                    config["id"],
                    order_number="UO-5002",
                    order_type="POOL_STOCK",
                    customer_id=None,
                    body_mount_offset_from_front_axle_in=120,
                ),
                users.SCHEDULER,
            ),
            201,
        )

        assert record["required_payload_lb"] == 0
        assert record["warranty_liability_cap_cents"] == DEFAULT_WARRANTY_LIABILITY_CAP_CENTS
        assert record["requested_in_service_date"] is None
        assert record["customer_id"] is None
        assert config["standard_equipment_spec_ids"] == []
        assert_clock_origin_timestamp(config["published_at"])

    def test_derived_order_fields_ignore_whatever_the_client_sends(self, clocked_api):
        """Money, load, warranty posture and the body reference are all server-owned.

        The invoice stays at zero until release, the committed auxiliary load is
        the body's own twelve amps rather than the number in the request, the
        chassis warranty posture is INTACT because no interface has been approved,
        the committed flow is zero, the body reference is copied from the
        configuration, and the liability ledger starts empty.

        Design: Corner/entities/upfit_order_computed_fields_are_server_derived_and_input_ignored
        """
        ns = catalog_service(clocked_api, with_equipment=False)
        customer = new_customer(clocked_api)
        config = new_configuration(
            clocked_api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A"
        )

        record = validate_success(
            clocked_api.create_upfit_order(
                upfit_order_payload(
                    config["id"],
                    order_number="UO-5003",
                    order_type="CUSTOMER_SPECIFIC",
                    customer_id=customer["id"],
                    body_mount_offset_from_front_axle_in=120,
                    invoice_total_cents=999,
                    committed_aux_amp_draw=999,
                    chassis_warranty_status="VOIDED",
                    body_spec_id="deadbeef",
                ),
                users.SCHEDULER,
            ),
            201,
        )

        assert record["invoice_total_cents"] == 0
        assert record["committed_aux_amp_draw"] == 12
        assert record["chassis_warranty_status"] == "INTACT"
        assert record["committed_pto_flow_gpm"] == 0
        assert record["body_spec_id"] == ns.body["id"]
        assert record["chassis_liability_cents"] == 0
        assert record["upfitter_liability_cents"] == 0
        assert record["customer_goodwill_cents"] == 0


class TestWorkBayCatalog:
    """A bay may only claim body families the plant actually recognises."""

    def test_an_unknown_body_family_on_a_bay_is_rejected(self, clocked_api):
        """A tanker is not one of the four families a bay can support.

        The bay is refused as a malformed request, no row under that bay code
        exists, and the same call naming only a recognised family is accepted and
        opens the bay ACTIVE.

        Design: Corner/entities/work_bay_supported_body_types_rejects_unknown_enum_member
        """
        response = clocked_api.create_work_bay(
            work_bay_payload(
                code="BAY-9", concurrent_capacity=1, supported_body_types=["SERVICE", "TANKER"]
            ),
            users.ADMIN,
        )

        validate_error(response, ERR_INVALID_REQUEST, 422)
        bays, _meta = validate_paginated(clocked_api.list_work_bays(users.SCHEDULER))
        assert [bay for bay in bays if bay["code"] == "BAY-9"] == []

        accepted = validate_success(
            clocked_api.create_work_bay(
                work_bay_payload(
                    code="BAY-9", concurrent_capacity=1, supported_body_types=["SERVICE"]
                ),
                users.ADMIN,
            ),
            201,
        )
        assert accepted["status"] == "ACTIVE"
        assert accepted["supported_body_types"] == ["SERVICE"]


def _measured_certified_service_order(api):
    """A service build with the body on and both certifications approved, unlabelled."""
    ns = service_order_world(
        api,
        order_type="CUSTOMER_SPECIFIC",
        order_number="UO-5004",
        config_code="CFG-SVC-A",
        required_payload_lb=5000,
        with_equipment=False,
        vin=vin_f550(4),
    )
    advance_to_released(api, ns)
    advance_to_in_build(api, ns, slot_type="FINAL_QC")
    ns.order = install_body(api, ns.order["id"], 2160)
    ns.cert_designed = approve_certification(
        api, draft_certification(api, ns.order["id"], "AS_DESIGNED")["id"]
    )
    ns.cert_measured = approve_certification(
        api, draft_certification(api, ns.order["id"], "AS_MEASURED")["id"]
    )
    return ns


class TestComplianceLabelShape:
    """The label that goes on the door frame is a permanent, versionless record."""

    def test_an_issued_label_is_immutable_and_carries_the_certified_ratings(self, api):
        """A label has an identity and a birth instant, and nothing that implies revision.

        It records who issued it, is not void, copies the chassis ratings and the
        certified payload from the measured certification behind it, is an alterer
        label carried by the upfitter because a body and nothing else was added,
        and moves the order's compliance dimension to LABELED.

        Design: Corner/entities/compliance_label_is_immutable_with_no_version_and_no_update_endpoint
        """
        ns = _measured_certified_service_order(api)

        label = validate_success(
            api.create_compliance_label(
                compliance_label_payload(ns.order["id"], ns.cert_measured["id"]),
                users.OFFICER_ALT,
            ),
            201,
        )

        assert_immutable_label_shape(label)
        assert_clock_origin_timestamp(label["created_at"])
        assert label["issued_by_user_id"] == "co-2"
        assert label["voided_at"] is None
        assert label["certified_gvwr_lb"] == 19500
        assert label["certified_front_gawr_lb"] == 7000
        assert label["certified_rear_gawr_lb"] == 14706
        assert label["certified_payload_lb"] == 9680
        assert label["certified_payload_lb"] == ns.cert_measured["payload_capacity_lb"]
        assert label["label_type"] == "ALTERER"
        assert label["responsible_party"] == "UPFITTER"
        assert read_order(api, ns.order["id"])["compliance_status"] == "LABELED"


class TestChildCreateForeignKeys:
    """A child row naming something that does not exist is refused by reference class."""

    def test_planning_equipment_requires_both_a_real_order_and_a_real_specification(
        self, clocked_api
    ):
        """Each bad reference is reported against its own class, and nothing is written.

        A bogus order with a real item names the order, a real order with a bogus
        item names the item, a request where both are bogus names one of the two
        missing references, and the real order ends with no installation at all.

        Design: Corner/entities/equipment_installation_requires_an_existing_order_and_spec
        """
        ns = catalog_service(clocked_api, with_equipment=False)
        liftgate = new_equipment_spec(clocked_api, EQ_LIFTGATE_2500)
        customer = new_customer(clocked_api)
        config = new_configuration(
            clocked_api, ns.cm["id"], ns.body["id"], config_code="CFG-SVC-A"
        )
        order = new_order(
            clocked_api,
            config["id"],
            order_number="UO-5005",
            order_type="CUSTOMER_SPECIFIC",
            customer_id=customer["id"],
            body_mount_offset_from_front_axle_in=120,
        )

        validate_error(
            clocked_api.create_equipment_installation(
                equipment_installation_payload(
                    UNKNOWN_UUID,
                    liftgate["id"],
                    mount_cg_from_front_axle_in=320,
                    hydraulic_circuit="NONE",
                ),
                users.TECHNICIAN,
            ),
            ERR_UPFIT_ORDER_NOT_FOUND,
            404,
        )
        validate_error(
            clocked_api.create_equipment_installation(
                equipment_installation_payload(
                    order["id"],
                    UNKNOWN_UUID,
                    mount_cg_from_front_axle_in=320,
                    hydraulic_circuit="NONE",
                ),
                users.TECHNICIAN,
            ),
            ERR_EQUIPMENT_SPEC_NOT_FOUND,
            404,
        )
        validate_error_is_one_of(
            clocked_api.create_equipment_installation(
                equipment_installation_payload(
                    UNKNOWN_UUIDS[0],
                    UNKNOWN_UUIDS[1],
                    mount_cg_from_front_axle_in=320,
                    hydraulic_circuit="NONE",
                ),
                users.TECHNICIAN,
            ),
            [ERR_EQUIPMENT_SPEC_NOT_FOUND, ERR_UPFIT_ORDER_NOT_FOUND],
        )

        installations, _meta = validate_paginated(
            clocked_api.list_equipment_installations(
                users.TECHNICIAN, {"upfit_order_id": order["id"]}
            )
        )
        assert installations == []

    def test_a_configuration_naming_an_unknown_chassis_model_is_refused(self, clocked_api):
        """The missing book entry is reported, not the geometry it would have been checked against.

        Because the model cannot be loaded there is nothing to compare the body's
        cab-to-axle and wheelbase minimums against, so the refusal is the missing
        reference and no configuration row survives under that code.

        Design: Corner/entities/build_configuration_rejects_unknown_chassis_model_foreign_key
        """
        body = new_body_spec(clocked_api, BODY_SERVICE_11FT)

        response = clocked_api.create_build_configuration(
            build_configuration_payload(
                UNKNOWN_UUID,
                body["id"],
                config_code="CFG-GHOST",
                standardization_tier="TIER_A",
            ),
            users.ENGINEER,
        )

        error = validate_error(response, ERR_CHASSIS_MODEL_NOT_FOUND, 404)
        assert error["error_id"] != ERR_CAB_TO_AXLE_INSUFFICIENT
        assert error["error_id"] != ERR_WHEELBASE_INSUFFICIENT
        configs, _meta = validate_paginated(
            clocked_api.list_build_configurations(users.ENGINEER)
        )
        assert [row for row in configs if row["config_code"] == "CFG-GHOST"] == []
