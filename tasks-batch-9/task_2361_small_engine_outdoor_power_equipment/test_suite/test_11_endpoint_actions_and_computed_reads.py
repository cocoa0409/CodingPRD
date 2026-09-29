"""Endpoint contracts: creation, computed reads, action endpoints and list shapes.

Every test builds its own state from an empty database through the documented
endpoints only.
"""

from test_helpers import (
    HTTP_STATUS_CODES,
    ApiErrorId,
    api_client,
    assert_build_order_unit_conservation,
    assert_envelope_meta,
    assert_service_part,
    assert_version_advanced_by,
    build_allocatable_plant,
    build_closed_machining_run,
    build_engine_platform,
    build_released_order_plant,
    build_service_part,
    build_supplier,
    create_engine_unit_payload,
    create_parts_request_payload,
    create_service_part_payload,
    inspect_component_lot,
    raise_parts_request,
    read_lot,
    read_service_part,
    read_supplier_scorecard,
    receive_component_lot,
    run_allocations,
    set_clock,
    stage_engine_unit,
    validate_error,
    validate_paginated,
    validate_success,
)


def _expect_error(response, error_id: ApiErrorId) -> dict:
    """Assert the documented error identifier and its documented HTTP status."""
    return validate_error(
        response, error_id.value, HTTP_STATUS_CODES[error_id.value]
    )


def _response_type(response) -> str:
    return response.json()["response_type"]


class TestServicePartSurface:
    """Create, read and list on the service-part collection."""

    def test_service_part_surface_is_create_read_and_list_only(
        self, family_with_platform, plant_admin_headers, channel_partner_headers
    ):
        """
        PRD §4: "Operations that mint a new resource — declaring a certification family, creating a platform or model, recording a safety certification, receiving a component lot, opening a machining run, creating an assembly line, planning a build order, scheduling a durability run or a line audit, staging an engine unit, creating a service part, raising a parts request — answer `201 Created`."
        PRD §4: "All retrievals answer `200 OK`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
        PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope, where `total_count` is the number of rows matching the request's filters before pagination is applied and `has_more` indicates whether rows remain beyond the returned page."
        PRD §2.3: "Unless a particular endpoint states otherwise, list results are ordered by `created_at` ascending."
        PRD §3.9: "The server derives `commitment_expires_year` as `last_production_year` plus `committed_availability_years`, and the part opens in `status` `ACTIVE` with `superseded_by_part_id` empty, `filled_request_count`, `substituted_request_count` and `backordered_request_count` all 0, and `fill_rate_pct` empty."
        PRD §3.9: "Service parts are readable individually and as a list, filterable by `engine_platform_id`, by `superseded_by_part_id` to trace supersession pointers, by `status` and by `category`."

        Design: Corner/endpoints/service_part_crud_surface_is_create_read_list_only
        """
        platform_id = family_with_platform.platform_id

        kit_response = api_client.create_service_part(
            create_service_part_payload(platform_id), plant_admin_headers
        )
        kit = validate_success(kit_response, 201)
        assert_envelope_meta(kit_response.json())
        assert _response_type(kit_response) == "object"
        assert_service_part(kit)
        assert kit["status"] == "ACTIVE"
        assert kit["commitment_expires_year"] == 2037
        assert kit["superseded_by_part_id"] is None
        assert kit["fill_rate_pct"] is None

        module_response = api_client.create_service_part(
            create_service_part_payload(
                platform_id,
                part_number="PN-IGN-MOD-1",
                category="IGNITION_MODULE",
                on_hand_qty=3,
                committed_availability_years=8,
            ),
            plant_admin_headers,
        )
        module = validate_success(module_response, 201)
        assert _response_type(module_response) == "object"
        assert module["commitment_expires_year"] == 2035

        read_response = api_client.get_service_part(kit["id"], channel_partner_headers)
        read = validate_success(read_response, 200)
        assert _response_type(read_response) == "object"
        assert read["id"] == kit["id"]
        assert read["commitment_expires_year"] == 2037

        filtered_response = api_client.list_service_parts(
            channel_partner_headers,
            {
                "engine_platform_id": platform_id,
                "category": "IGNITION_MODULE",
                "limit": 10,
                "offset": 0,
            },
        )
        filtered_rows, filtered_meta = validate_paginated(filtered_response)
        assert _response_type(filtered_response) == "array"
        assert filtered_meta["total_count"] == 1
        assert filtered_meta["has_more"] is False
        assert [row["id"] for row in filtered_rows] == [module["id"]]

        paged_rows, paged_meta = validate_paginated(
            api_client.list_service_parts(
                plant_admin_headers, {"status": "ACTIVE", "limit": 1, "offset": 1}
            )
        )
        assert paged_meta["limit"] == 1
        assert paged_meta["offset"] == 1
        assert paged_meta["total_count"] == 2
        assert paged_meta["has_more"] is False
        assert len(paged_rows) == 1
        assert paged_rows[0]["id"] == module["id"]


class TestAllocationResetAction:
    """The compensating action behind a channel allocation run."""

    def test_allocation_reset_returns_the_whole_pool_to_unallocated(
        self, canonical_clock, production_planner_headers
    ):
        """
        PRD §3.8: "The results are written as `allocated_dealer_units`, `allocated_mass_retail_units` and `unallocated_units`, `allocation_status` becomes `ALLOCATED`, `allocation_run_at` is stamped from the clock, and the order's `version` increments by 1."
        PRD §3.8: "A compensating reset is also available to the planner: it sets `allocated_dealer_units` and `allocated_mass_retail_units` to 0, sets `unallocated_units` to the full `built_quantity`, returns `allocation_status` to `UNALLOCATED` and clears `allocation_run_at`, all without touching a single engine and while preserving the same invariant."
        PRD §3.8: "When it is 1, that single unit goes to whichever bucket had the larger fractional part, and when the two fractional parts are equal the unit goes to the **dealer** bucket."
        PRD §2.5: "`version` is an integer that starts at 1 when the row is created and increments by 1 on every mutation of that row — including mutations the server performs on its own initiative, such as a derived counter being recomputed or a cascade imposing a hold."

        Design: Corner/endpoints/allocation_reset_action_clears_the_split_and_reopens_the_pool
        """
        scenario = build_allocatable_plant(
            released_units=1, order_overrides={"planned_quantity": 1}
        )
        order = scenario.refresh_build_order()
        assert order["status"] == "COMPLETED"
        assert order["built_quantity"] == 1

        first_run = run_allocations(order["id"], order["version"])
        assert first_run["allocated_dealer_units"] == 1
        assert first_run["allocated_mass_retail_units"] == 0
        assert first_run["unallocated_units"] == 0
        assert first_run["allocation_status"] == "ALLOCATED"
        assert first_run["allocation_run_at"] is not None
        assert first_run["allocation_run_at"].startswith("2026-08-03T08:00:00")
        assert_version_advanced_by(
            order["version"], first_run["version"], 1, "BuildOrder"
        )
        assert_build_order_unit_conservation(first_run)

        reset = validate_success(
            api_client.reset_build_order_allocations(
                order["id"], production_planner_headers
            ),
            200,
        )
        assert reset["allocated_dealer_units"] == 0
        assert reset["allocated_mass_retail_units"] == 0
        assert reset["unallocated_units"] == 1
        assert reset["allocation_status"] == "UNALLOCATED"
        assert reset["allocation_run_at"] is None
        assert reset["version"] > first_run["version"]
        assert reset["status"] == "COMPLETED"
        assert reset["built_quantity"] == 1
        assert_build_order_unit_conservation(reset)

        second_run = run_allocations(order["id"], reset["version"])
        assert second_run["allocated_dealer_units"] == 1
        assert second_run["allocated_mass_retail_units"] == 0
        assert second_run["unallocated_units"] == 0
        assert second_run["status"] == "COMPLETED"
        assert second_run["built_quantity"] == 1
        assert_build_order_unit_conservation(second_run)


class TestEngineUnitLinks:
    """Staging binds four upstream records and validates each on its own axis."""

    def test_unit_staging_validates_each_of_its_four_links(
        self, canonical_clock, quality_engineer_headers
    ):
        """
        PRD §3.7: "The machining run's `engine_platform_id` must equal the `engine_platform_id` of the model the build order is for — machining cut for one platform cannot be dropped into an engine of another — and a divergence is refused with `ERR_PLATFORM_MISMATCH`."
        PRD §3.7: "The `carburetor_lot_id` must resolve to a lot whose `component_category` is `CARBURETOR` and the `ignition_lot_id` to a lot whose category is `IGNITION`, with any cross-wiring refused as `ERR_COMPONENT_CATEGORY_MISMATCH`."
        PRD §3.7: "Each of the two consumed lots has 1 added to `consumed_qty` and 1 subtracted from `remaining_qty`, per §2.11 — note that the bound machining run and its casting lot are not charged in this way; only the carburetor and ignition lots are consumed piecewise."
        PRD §3.7: "Units are readable individually and as a list, filterable by `build_order_id`, `machining_run_id`, `carburetor_lot_id`, `ignition_lot_id`, `build_state` and `conformance_state`."

        Design: Corner/endpoints/unit_creation_links_four_entities_and_validates_each_link
        """
        scenario = build_released_order_plant()
        other_platform = build_engine_platform(
            scenario.family_id,
            platform_code="210SS",
            displacement_cc=210,
            torque_spec_nm=23.0,
        )
        other_run = build_closed_machining_run(
            other_platform["id"], scenario.casting_lot_id
        )
        assert other_run["status"] == "CLOSED"

        wrong_platform = api_client.create_engine_unit(
            create_engine_unit_payload(
                scenario.build_order_id,
                other_run["id"],
                scenario.carburetor_lot_id,
                scenario.ignition_lot_id,
                "SN-0041",
            ),
            quality_engineer_headers,
        )
        _expect_error(wrong_platform, ApiErrorId.ERR_PLATFORM_MISMATCH)

        cross_wired = api_client.create_engine_unit(
            create_engine_unit_payload(
                scenario.build_order_id,
                scenario.machining_run_id,
                scenario.ignition_lot_id,
                scenario.carburetor_lot_id,
                "SN-0042",
            ),
            quality_engineer_headers,
        )
        _expect_error(cross_wired, ApiErrorId.ERR_COMPONENT_CATEGORY_MISMATCH)

        unit = stage_engine_unit(scenario, "SN-0001")
        assert unit["build_order_id"] == scenario.build_order_id
        assert unit["machining_run_id"] == scenario.machining_run_id
        assert unit["carburetor_lot_id"] == scenario.carburetor_lot_id
        assert unit["ignition_lot_id"] == scenario.ignition_lot_id

        _, by_run = validate_paginated(
            api_client.list_engine_units(
                quality_engineer_headers,
                {
                    "machining_run_id": scenario.machining_run_id,
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert by_run["total_count"] == 1

        _, by_lot = validate_paginated(
            api_client.list_engine_units(
                quality_engineer_headers,
                {
                    "carburetor_lot_id": scenario.carburetor_lot_id,
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert by_lot["total_count"] == 1

        other_rows, other_meta = validate_paginated(
            api_client.list_machining_runs(
                quality_engineer_headers,
                {
                    "engine_platform_id": other_platform["id"],
                    "status": "CLOSED",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert other_meta["total_count"] == 1
        assert other_rows[0]["id"] == other_run["id"]

        assert read_lot(scenario.ignition_lot_id)["consumed_qty"] == 1
        assert read_lot(scenario.carburetor_lot_id)["consumed_qty"] == 1


class TestServicePartObsoletion:
    """Retirement waits for the availability commitment and for open backorders."""

    def test_part_obsoletion_waits_for_the_commitment_year_and_open_backorders(
        self, family_with_platform, plant_admin_headers, channel_partner_headers
    ):
        """
        PRD §3.9: "The plant's parts-availability commitment must have actually run out: the logical clock's year must be **strictly greater** than the part's `commitment_expires_year`, so a part whose commitment expires in the current clock year cannot yet be retired, and the attempt is refused with `ERR_AVAILABILITY_COMMITMENT_ACTIVE`."
        PRD §3.9: "And no backorder may still be open: a `backordered_request_count` above zero refuses the retirement with `ERR_OPEN_BACKORDERS_EXIST`."
        PRD §3.9: "On success the part reaches the terminal `OBSOLETE`, after which no new fulfillment request against it is accepted."
        PRD §3.9: "The part must be `ACTIVE`; requesting a part that is `SUPERSEDED` or `OBSOLETE` is refused with `ERR_PART_STATE_INVALID`."
        PRD §3.9: "A request left `BACKORDERED` gets `promised_ship_date` equal to the clock date plus 21 days."

        Design: Corner/endpoints/part_obsoletion_is_allowed_only_after_the_commitment_and_backorders_clear
        """
        platform_id = family_with_platform.platform_id
        part_a = build_service_part(
            platform_id,
            part_number="PN-OBS-A",
            category="CARBURETOR_KIT",
            on_hand_qty=1,
            committed_availability_years=10,
            last_production_year=2027,
        )
        part_b = build_service_part(
            platform_id,
            part_number="PN-OBS-B",
            category="FILTER_KIT",
            on_hand_qty=0,
            committed_availability_years=10,
            last_production_year=2027,
        )
        assert part_a["commitment_expires_year"] == 2037

        _expect_error(
            api_client.obsolete_service_part(part_a["id"], plant_admin_headers),
            ApiErrorId.ERR_AVAILABILITY_COMMITMENT_ACTIVE,
        )

        set_clock("2037-12-31T23:00:00Z")
        _expect_error(
            api_client.obsolete_service_part(part_a["id"], plant_admin_headers),
            ApiErrorId.ERR_AVAILABILITY_COMMITMENT_ACTIVE,
        )

        set_clock("2038-01-05T08:00:00Z")
        backorder = raise_parts_request(part_a["id"], requested_quantity=4)
        assert backorder["status"] == "BACKORDERED"
        assert backorder["promised_ship_date"] == "2038-01-26"

        _expect_error(
            api_client.obsolete_service_part(part_a["id"], plant_admin_headers),
            ApiErrorId.ERR_OPEN_BACKORDERS_EXIST,
        )

        retired = validate_success(
            api_client.obsolete_service_part(part_b["id"], plant_admin_headers), 200
        )
        assert retired["status"] == "OBSOLETE"

        _expect_error(
            api_client.create_parts_request(
                create_parts_request_payload(part_b["id"]), channel_partner_headers
            ),
            ApiErrorId.ERR_PART_STATE_INVALID,
        )
        assert read_service_part(part_a["id"])["status"] == "ACTIVE"


class TestSupplierScorecard:
    """The scorecard is a computed read over the supplier's inspected lots."""

    def test_supplier_scorecard_exposes_criticality_and_both_defect_variants(
        self, canonical_clock
    ):
        """
        PRD §3.4: "The supplier's `criticality` follows from that category and is never supplied: a `CASTING` supplier is `CRITICAL`, and a `CARBURETOR` or `IGNITION` supplier is `MAJOR`."
        PRD §3.4: "At `NORMAL` it is the larger of 8 pieces and five percent of `lot_quantity` rounded up."
        PRD §3.4: "The acceptance number — the maximum number of defective pieces in the sample that still permits acceptance — is 0 for a `CRITICAL` supplier, and for a `MAJOR` supplier it is ten percent of the resulting sample size rounded **down** to a whole number."
        PRD §3.4: "The disposition forks on the frozen acceptance number: when `defects_found` is at most `acceptance_number` the lot moves `RECEIVED → ACCEPTED`, and when it is greater the lot moves `RECEIVED → REJECTED`."
        PRD §3.4: "The pooled rate is the sum of `defects_found` across that population, divided by the sum of `sample_size` across the same population, multiplied by one million, rounded half up to a whole number, and stored as `rolling_defect_ppm`."
        PRD §3.4: "Both parts-per-million thresholds are strict, so a supplier sitting at exactly 25,000 ppm remains `APPROVED` and one at exactly 100,000 ppm lands on `PROBATION` rather than suspension."
        PRD §3.4: "Only the pooled figure gates anything: the scorecard read returns `supplier_id`, `rolling_defect_ppm`, `scorecard_average_ppm`, `inspected_lot_count`, `consecutive_accepted_lots`, `approval_status`, `incoming_inspection_level` and `criticality`, and changes nothing."

        Design: Corner/endpoints/supplier_scorecard_computed_read_exposes_criticality_and_streak
        """
        casting_supplier = build_supplier(
            supplier_code="SUP-CAST",
            name="Foundry Alliance",
            component_category="CASTING",
        )
        carburetor_supplier = build_supplier(
            supplier_code="SUP-CARB",
            name="Carburetion Partners",
            component_category="CARBURETOR",
        )

        casting_lot = receive_component_lot(
            casting_supplier["id"], lot_code="CS-010", lot_quantity=800
        )
        assert casting_lot["sample_size"] == 40
        assert casting_lot["acceptance_number"] == 0
        casting_lot = inspect_component_lot(casting_lot["id"], defects_found=1)
        assert casting_lot["status"] == "REJECTED"

        carburetor_lot = receive_component_lot(
            carburetor_supplier["id"], lot_code="CB-010", lot_quantity=800
        )
        assert carburetor_lot["sample_size"] == 40
        assert carburetor_lot["acceptance_number"] == 4
        carburetor_lot = inspect_component_lot(carburetor_lot["id"], defects_found=1)
        assert carburetor_lot["status"] == "ACCEPTED"

        casting_card = read_supplier_scorecard(casting_supplier["id"])
        assert casting_card["supplier_id"] == casting_supplier["id"]
        assert casting_card["criticality"] == "CRITICAL"
        assert casting_card["inspected_lot_count"] == 1
        assert casting_card["rolling_defect_ppm"] == 25000
        assert casting_card["scorecard_average_ppm"] == 25000
        assert casting_card["consecutive_accepted_lots"] == 0
        assert casting_card["approval_status"] == "APPROVED"
        assert casting_card["incoming_inspection_level"] == "NORMAL"

        carburetor_card = read_supplier_scorecard(carburetor_supplier["id"])
        assert carburetor_card["supplier_id"] == carburetor_supplier["id"]
        assert carburetor_card["criticality"] == "MAJOR"
        assert carburetor_card["consecutive_accepted_lots"] == 1
        assert carburetor_card["rolling_defect_ppm"] == 25000
        assert carburetor_card["scorecard_average_ppm"] == 25000
        assert carburetor_card["approval_status"] == "APPROVED"
        assert carburetor_card["incoming_inspection_level"] == "NORMAL"

        assert read_supplier_scorecard(casting_supplier["id"]) == casting_card
