"""Role permissions, read closure, request scoping and segregation of duties.

Every test builds its own state from an empty database through the documented
endpoints only.
"""

import pytest

from test_helpers import (
    ALL_ROLE_NAMES,
    HTTP_STATUS_CODES,
    NON_EXISTENT_UUID,
    PLANT_READ_ROLE_NAMES,
    ApiErrorId,
    api_client,
    build_allocatable_plant,
    build_certification_family,
    build_engine_platform,
    build_released_order_plant,
    build_service_part,
    build_supplier,
    complete_durability_run,
    create_build_order_payload,
    create_certification_family_payload,
    create_component_lot_payload,
    create_engine_platform_payload,
    create_engine_unit_payload,
    create_machining_run_payload,
    create_parts_request_payload,
    create_safety_certification_payload,
    create_service_part_payload,
    headers_for_role,
    inspect_component_lot,
    make_compliance_officer_headers,
    raise_parts_request,
    read_family,
    read_service_part,
    receive_component_lot,
    run_allocations_payload,
    schedule_durability_run,
    set_clock_payload,
    submit_family,
    validate_error,
    validate_paginated,
    validate_success,
)


def _expect_error(response, error_id: ApiErrorId) -> dict:
    """Assert the documented error identifier and its documented HTTP status."""
    return validate_error(
        response, error_id.value, HTTP_STATUS_CODES[error_id.value]
    )


class TestRolesPerformTheirOwnOperations:
    """Each role drives the workflow step the endpoint table gives it."""

    def test_each_role_performs_its_own_exclusive_and_shared_operations(
        self, canonical_clock, channel_partner_headers
    ):
        """
        PRD §2.1: "`PlantAdmin` owns plant master data — engine platforms, product models, suppliers, assembly lines and service parts — and is the only role permitted to reposition the plant's logical clock."
        PRD §2.1: "`CertificationEngineer` owns emission certification families and durability testing. This role declares a family, schedules and completes its durability runs, and submits it for review; it may never certify a family."
        PRD §2.1: "`ComplianceOfficer` is the regulatory authority. It certifies families, records safety bench tests, grants component deviations, schedules production line audits and records their results."
        PRD §2.1: "`QualityEngineer` owns incoming inspection, machining capability and the assembly line itself: receiving and inspecting lots, opening and closing machining runs, staging engine units, recording torque, running the hot test, releasing, reworking and cancelling units."
        PRD §2.1: "`ProductionPlanner` owns seasonal planning: build orders, release to the floor, and channel inventory positioning."
        PRD §2.1: "`ChannelPartner` is the dealer or mass-retail service counter. It may raise a parts fulfillment request and read the service-part surface; every certification, supplier, machining and production read is closed to it."
        PRD §2.1: "`PlantAdmin`, `CertificationEngineer`, `ComplianceOfficer`, `QualityEngineer` and `ProductionPlanner` may call every retrieval endpoint in the system."
        PRD §2.4: "A `PlantAdmin` may reposition the clock for test-driving purposes by supplying a `to_iso8601` instant; the operation answers with the resulting `current_utc` and mutates no entity."

        Design: Corner/rbac/each_role_performs_its_own_exclusive_and_shared_operations
        """
        assert canonical_clock["current_utc"].startswith("2026-08-03T08:00:00")

        scenario = build_released_order_plant()
        assert scenario.family["status"] == "CERTIFIED"
        assert scenario.durability_run["status"] == "COMPLETED"
        assert scenario.platform["certification_posture"] == "OPEN"
        assert scenario.model["status"] == "RELEASED"
        assert scenario.safety_certification["result"] == "PASSED"
        assert scenario.lots["carburetor"]["status"] == "ACCEPTED"
        assert scenario.lots["ignition"]["status"] == "ACCEPTED"
        assert scenario.lots["casting"]["status"] == "ACCEPTED"
        assert scenario.machining_run["status"] == "CLOSED"
        assert scenario.build_order["status"] == "RELEASED"

        part = build_service_part(scenario.platform_id)
        request = validate_success(
            api_client.create_parts_request(
                create_parts_request_payload(part["id"]), channel_partner_headers
            ),
            201,
        )
        assert request["status"] == "FILLED"
        assert request["requester_user_id"] == channel_partner_headers["X-User-ID"]

        assert len(PLANT_READ_ROLE_NAMES) == 5
        reads = [
            validate_success(
                api_client.get_build_order(
                    scenario.build_order_id, headers_for_role(role, f"reader-{index}")
                ),
                200,
            )
            for index, role in enumerate(PLANT_READ_ROLE_NAMES, start=1)
        ]
        for row in reads:
            assert row == reads[0]


class TestExclusiveWritesRejectOtherRoles:
    """A write reserved to one role answers 403 for every other role."""

    @pytest.mark.parametrize(
        "role", [name for name in ALL_ROLE_NAMES if name != "CertificationEngineer"]
    )
    def test_family_declaration_rejects_every_other_recognised_role(
        self, canonical_clock, role
    ):
        """
        PRD §2.1: "If both headers are present and the role is recognised but that role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "`CertificationEngineer` owns emission certification families and durability testing. This role declares a family, schedules and completes its durability runs, and submits it for review; it may never certify a family."
        PRD §2.1: "The six roles are `PlantAdmin`, `CertificationEngineer`, `ComplianceOfficer`, `QualityEngineer`, `ProductionPlanner` and `ChannelPartner`."

        Design: Corner/rbac/exclusive_writes_reject_every_other_role_forbidden
        """
        response = api_client.create_certification_family(
            create_certification_family_payload(),
            headers_for_role(role, "intruder-1"),
        )
        _expect_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_every_exclusive_write_rejects_a_role_outside_its_column(
        self,
        canonical_clock,
        plant_admin_headers,
        certification_engineer_headers,
        compliance_officer_headers,
        quality_engineer_headers,
        production_planner_headers,
        channel_partner_headers,
    ):
        """
        PRD §2.1: "If both headers are present and the role is recognised but that role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "`PlantAdmin` owns plant master data — engine platforms, product models, suppliers, assembly lines and service parts — and is the only role permitted to reposition the plant's logical clock."
        PRD §2.1: "`ComplianceOfficer` is the regulatory authority. It certifies families, records safety bench tests, grants component deviations, schedules production line audits and records their results."
        PRD §2.1: "`QualityEngineer` owns incoming inspection, machining capability and the assembly line itself: receiving and inspecting lots, opening and closing machining runs, staging engine units, recording torque, running the hot test, releasing, reworking and cancelling units."
        PRD §2.1: "`ProductionPlanner` owns seasonal planning: build orders, release to the floor, and channel inventory positioning."
        PRD §2.1: "`ChannelPartner` is the dealer or mass-retail service counter. It may raise a parts fulfillment request and read the service-part surface; every certification, supplier, machining and production read is closed to it."

        Design: Corner/rbac/exclusive_writes_reject_every_other_role_forbidden
        """
        scenario = build_released_order_plant()
        family_version_before = read_family(scenario.family_id)["version"]

        refusals = [
            api_client.set_clock(
                set_clock_payload("2026-09-01T08:00:00Z"), production_planner_headers
            ),
            api_client.create_engine_platform(
                create_engine_platform_payload(
                    scenario.family_id, platform_code="210SS", displacement_cc=210
                ),
                certification_engineer_headers,
            ),
            api_client.certify_certification_family(
                scenario.family_id, certification_engineer_headers
            ),
            api_client.create_safety_certification(
                create_safety_certification_payload(scenario.model_id),
                plant_admin_headers,
            ),
            api_client.create_component_lot(
                create_component_lot_payload(
                    scenario.suppliers["carburetor"]["id"], lot_code="CB-777"
                ),
                compliance_officer_headers,
            ),
            api_client.create_machining_run(
                create_machining_run_payload(
                    scenario.platform_id, scenario.casting_lot_id
                ),
                production_planner_headers,
            ),
            api_client.create_build_order(
                create_build_order_payload(scenario.model_id, scenario.line_id),
                quality_engineer_headers,
            ),
            api_client.create_engine_unit(
                create_engine_unit_payload(
                    scenario.build_order_id,
                    scenario.machining_run_id,
                    scenario.carburetor_lot_id,
                    scenario.ignition_lot_id,
                    "SN-9001",
                ),
                production_planner_headers,
            ),
            api_client.run_build_order_allocations(
                scenario.build_order_id,
                run_allocations_payload(scenario.build_order["version"]),
                channel_partner_headers,
            ),
            api_client.create_service_part(
                create_service_part_payload(scenario.platform_id),
                channel_partner_headers,
            ),
            api_client.create_parts_request(
                create_parts_request_payload(NON_EXISTENT_UUID), plant_admin_headers
            ),
        ]
        for response in refusals:
            _expect_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)

        assert read_family(scenario.family_id)["version"] == family_version_before

        _, orders = validate_paginated(
            api_client.list_build_orders(
                plant_admin_headers, {"limit": 10, "offset": 0}
            )
        )
        assert orders["total_count"] == 1

        _, units = validate_paginated(
            api_client.list_engine_units(plant_admin_headers, {"limit": 10, "offset": 0})
        )
        assert units["total_count"] == 0

        _, lots = validate_paginated(
            api_client.list_component_lots(
                plant_admin_headers, {"limit": 10, "offset": 0}
            )
        )
        assert lots["total_count"] == 3

        _, parts = validate_paginated(
            api_client.list_service_parts(
                plant_admin_headers, {"limit": 10, "offset": 0}
            )
        )
        assert parts["total_count"] == 0

    def test_role_refusal_outranks_a_target_that_does_not_exist(self, canonical_clock):
        """
        PRD §2.8: "More generally, an operation may fail several of this specification's rules at once."
        PRD §2.8: "The rules are evaluated in a fixed order and **the first violated rule decides the response** — later rules are never reported."
        PRD §2.1: "If both headers are present and the role is recognised but that role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/exclusive_writes_reject_every_other_role_forbidden
        """
        response = api_client.certify_certification_family(
            NON_EXISTENT_UUID, headers_for_role("QualityEngineer", "intruder-2")
        )
        _expect_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestChannelPartnerReadClosure:
    """The dealer counter sees the service-part surface and nothing else."""

    def test_production_and_supplier_reads_are_closed_to_the_channel_partner(
        self, canonical_clock, channel_partner_headers
    ):
        """
        PRD §2.1: "`ChannelPartner` is the dealer or mass-retail service counter. It may raise a parts fulfillment request and read the service-part surface; every certification, supplier, machining and production read is closed to it."
        PRD §2.1: "`ChannelPartner` may read only individual service parts, the service-part list, and the fulfillment requests raised against a part."
        PRD §2.1: "If both headers are present and the role is recognised but that role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/production_and_supplier_reads_are_closed_to_the_channel_partner_forbidden
        """
        scenario = build_allocatable_plant(
            released_units=1, order_overrides={"planned_quantity": 1}
        )
        unit = scenario.units[0]
        part = build_service_part(scenario.platform_id)
        page = {"limit": 10, "offset": 0}

        validate_success(
            api_client.get_service_part(part["id"], channel_partner_headers), 200
        )
        validate_paginated(api_client.list_service_parts(channel_partner_headers, page))
        validate_paginated(
            api_client.list_service_part_requests(
                part["id"], channel_partner_headers, page
            )
        )

        closed_reads = [
            api_client.get_certification_family(
                scenario.family_id, channel_partner_headers
            ),
            api_client.list_family_engine_platforms(
                scenario.family_id, channel_partner_headers, page
            ),
            api_client.get_engine_platform(
                scenario.platform_id, channel_partner_headers
            ),
            api_client.list_platform_product_models(
                scenario.platform_id, channel_partner_headers, page
            ),
            api_client.get_durability_test(
                scenario.durability_run["id"], channel_partner_headers
            ),
            api_client.list_durability_tests(channel_partner_headers, page),
            api_client.get_product_model(scenario.model_id, channel_partner_headers),
            api_client.list_model_safety_certifications(
                scenario.model_id, channel_partner_headers, page
            ),
            api_client.get_supplier_scorecard(
                scenario.suppliers["carburetor"]["id"], channel_partner_headers
            ),
            api_client.get_component_lot(
                scenario.carburetor_lot_id, channel_partner_headers
            ),
            api_client.list_component_lots(channel_partner_headers, page),
            api_client.get_machining_run(
                scenario.machining_run_id, channel_partner_headers
            ),
            api_client.list_machining_runs(channel_partner_headers, page),
            api_client.get_build_order(
                scenario.build_order_id, channel_partner_headers
            ),
            api_client.list_build_orders(channel_partner_headers, page),
            api_client.list_line_audits(
                scenario.build_order_id, channel_partner_headers, page
            ),
            api_client.get_engine_unit(unit["id"], channel_partner_headers),
            api_client.list_engine_units(channel_partner_headers, page),
        ]
        assert len(closed_reads) == 18
        for response in closed_reads:
            _expect_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestPartsRequestScoping:
    """A dealer sees only the requests it raised; plant roles see them all."""

    def test_parts_request_listing_is_scoped_to_the_requesting_dealer(
        self,
        family_with_platform,
        channel_partner_headers,
        second_channel_partner_headers,
        production_planner_headers,
    ):
        """
        PRD §2.1: "The two comparisons the server does perform on these recorded identifiers are inequality checks between two operators, described in §2.9, plus one visibility filter: when a `ChannelPartner` lists the fulfillment requests of a part, it sees only rows whose `requester_user_id` equals its own `X-User-ID`, while every other role sees all rows."
        PRD §3.9: "The request is minted in `BACKORDERED` and settles within the very same call when stock allows: if the part's `on_hand_qty` is at least `requested_quantity`, the request becomes `FILLED`, its `shipped_from_part_id` is set to the part it was requested from, and the part's `on_hand_qty` is reduced by `requested_quantity`."
        PRD §3.9: "A request that is `FILLED` or `SUBSTITUTED` gets `promised_ship_date` equal to the clock date plus the lead time its channel earns — `dealer_lead_time_days` for a `DEALER` request and `mass_retail_lead_time_days` for a `MASS_RETAIL` request, read from the part the pieces actually ship from."
        PRD §3.9: "A request left `BACKORDERED` gets `promised_ship_date` equal to the clock date plus 21 days."
        PRD §3.9: "Otherwise it is the served count divided by the total, multiplied by 100, rounded half up to 2 decimal places."
        PRD §3.9: "The requests raised against a part are listable from the part and filterable by `status`, subject to the `ChannelPartner` scoping described in §2.1."

        Design: Corner/rbac/parts_request_listing_is_scoped_to_the_requesting_dealer
        """
        part = build_service_part(family_with_platform.platform_id, on_hand_qty=1)

        filled = raise_parts_request(
            part["id"], channel_partner_headers, requested_quantity=1, channel="DEALER"
        )
        assert filled["status"] == "FILLED"
        assert filled["promised_ship_date"] == "2026-08-05"
        assert filled["shipped_from_part_id"] == part["id"]
        assert filled["requester_user_id"] == channel_partner_headers["X-User-ID"]

        backordered = raise_parts_request(
            part["id"],
            second_channel_partner_headers,
            requested_quantity=1,
            channel="DEALER",
        )
        assert backordered["status"] == "BACKORDERED"
        assert backordered["promised_ship_date"] == "2026-08-24"
        assert (
            backordered["requester_user_id"]
            == second_channel_partner_headers["X-User-ID"]
        )

        page = {"limit": 10, "offset": 0}
        own_rows, own_meta = validate_paginated(
            api_client.list_service_part_requests(
                part["id"], channel_partner_headers, page
            )
        )
        assert own_meta["total_count"] == 1
        assert [row["id"] for row in own_rows] == [filled["id"]]

        other_rows, other_meta = validate_paginated(
            api_client.list_service_part_requests(
                part["id"], second_channel_partner_headers, page
            )
        )
        assert other_meta["total_count"] == 1
        assert [row["id"] for row in other_rows] == [backordered["id"]]

        all_rows, all_meta = validate_paginated(
            api_client.list_service_part_requests(
                part["id"], production_planner_headers, page
            )
        )
        assert all_meta["total_count"] == 2
        assert [row["id"] for row in all_rows] == [filled["id"], backordered["id"]]

        _, planner_filtered = validate_paginated(
            api_client.list_service_part_requests(
                part["id"],
                production_planner_headers,
                {"status": "BACKORDERED", "limit": 10, "offset": 0},
            )
        )
        assert planner_filtered["total_count"] == 1

        _, dealer_filtered = validate_paginated(
            api_client.list_service_part_requests(
                part["id"],
                channel_partner_headers,
                {"status": "BACKORDERED", "limit": 10, "offset": 0},
            )
        )
        assert dealer_filtered["total_count"] == 0

        refreshed = read_service_part(part["id"])
        assert refreshed["on_hand_qty"] == 0
        assert refreshed["filled_request_count"] == 1
        assert refreshed["substituted_request_count"] == 0
        assert refreshed["backordered_request_count"] == 1
        assert refreshed["fill_rate_pct"] == pytest.approx(50.00, abs=0.01)


class TestSegregationOfDuties:
    """The operator who set a decision up may not be the one who takes it."""

    def test_family_certification_refuses_the_submitting_operator(
        self,
        canonical_clock,
        certification_engineer_headers,
        quality_engineer_headers,
        compliance_officer_headers,
    ):
        """
        PRD §2.9: "The first is emission certification."
        PRD §2.9: "The `X-User-ID` that submits a family is retained as `submitted_by_user_id`."
        PRD §2.9: "When a `ComplianceOfficer` later certifies that family, the server compares the certifying `X-User-ID` against `submitted_by_user_id`; if they are the same operator, the certification is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §2.1: "If both headers are present and the role is recognised but that role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §3.2: "On success the family moves `SUBMITTED → CERTIFIED`, `certified_by_user_id` records the certifying operator, `certified_at` is stamped from the clock, and every platform of the family has its posture recomputed to `OPEN`."

        Design: Corner/rbac/segregation_of_duties_bars_the_submitter_and_the_inspector
        """
        family = build_certification_family()
        platform = build_engine_platform(family["id"])
        run = schedule_durability_run(family["id"], platform["id"])
        complete_durability_run(run["id"])
        submitted = submit_family(family["id"])
        assert submitted["status"] == "SUBMITTED"
        assert (
            submitted["submitted_by_user_id"]
            == certification_engineer_headers["X-User-ID"]
        )

        same_operator = api_client.certify_certification_family(
            family["id"],
            make_compliance_officer_headers(
                certification_engineer_headers["X-User-ID"]
            ),
        )
        _expect_error(same_operator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        _expect_error(
            api_client.certify_certification_family(
                family["id"], quality_engineer_headers
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )
        assert read_family(family["id"])["status"] == "SUBMITTED"

        certified = validate_success(
            api_client.certify_certification_family(
                family["id"], compliance_officer_headers
            ),
            200,
        )
        assert certified["status"] == "CERTIFIED"
        assert (
            certified["certified_by_user_id"] == compliance_officer_headers["X-User-ID"]
        )
        assert certified["certified_at"] is not None
        assert certified["certified_emission_g_per_kwh"] == pytest.approx(
            5.12, abs=0.01
        )

    def test_lot_deviation_refuses_the_inspecting_operator(
        self, canonical_clock, quality_engineer_headers, compliance_officer_headers
    ):
        """
        PRD §2.9: "The second is component deviation."
        PRD §2.9: "The `X-User-ID` that inspects a lot is retained as `inspected_by_user_id`."
        PRD §2.9: "When a `ComplianceOfficer` grants that lot a deviation acceptance, the server compares the approving `X-User-ID` against `inspected_by_user_id`; if they are the same operator, the deviation is refused with the same `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.1: "If both headers are present and the role is recognised but that role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §3.4: "On success the lot moves to `DEVIATION_ACCEPTED`, `deviation_flag` becomes true, `deviation_approved_by_user_id` records the approver, and the released quantity is recomputed: `accepted_qty` becomes `lot_quantity` minus `defects_found`, with `remaining_qty` set equal to it."

        Design: Corner/rbac/segregation_of_duties_bars_the_submitter_and_the_inspector
        """
        supplier = build_supplier(
            supplier_code="SUP-CARB",
            name="Kirin Carburetor Works",
            component_category="CARBURETOR",
        )
        lot = receive_component_lot(
            supplier["id"], lot_code="CB-001", lot_quantity=800
        )
        assert lot["sample_size"] == 40
        assert lot["acceptance_number"] == 4

        inspected = inspect_component_lot(lot["id"], defects_found=5)
        assert inspected["status"] == "REJECTED"
        assert (
            inspected["inspected_by_user_id"] == quality_engineer_headers["X-User-ID"]
        )

        same_operator = api_client.deviation_accept_component_lot(
            lot["id"],
            make_compliance_officer_headers(quality_engineer_headers["X-User-ID"]),
        )
        _expect_error(same_operator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        _expect_error(
            api_client.deviation_accept_component_lot(
                lot["id"], quality_engineer_headers
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )

        deviated = validate_success(
            api_client.deviation_accept_component_lot(
                lot["id"], compliance_officer_headers
            ),
            200,
        )
        assert deviated["status"] == "DEVIATION_ACCEPTED"
        assert deviated["deviation_flag"] is True
        assert (
            deviated["deviation_approved_by_user_id"]
            == compliance_officer_headers["X-User-ID"]
        )
        assert deviated["accepted_qty"] == 795
        assert deviated["remaining_qty"] == 795
