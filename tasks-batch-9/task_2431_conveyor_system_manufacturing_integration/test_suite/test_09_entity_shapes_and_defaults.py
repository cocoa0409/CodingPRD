"""Entity representations: stored inputs, computed fields, defaults and identity."""

from test_helpers import (
    DESIGN_ENGINEER,
    NON_EXISTENT_UUID,
    PROJECT_DIRECTOR,
    SHOP_SUPERVISOR,
    ApiErrorId,
    assert_append_only_fields,
    assert_fabrication_lot,
    assert_flow_link,
    assert_project,
    assert_segment,
    assert_spare_part_line,
    create_fabrication_lot_payload,
    create_project_payload,
    create_segment_payload,
    is_iso8601_timestamp,
    make_frozen_project,
    make_linear_design,
    make_project,
    make_segment,
    make_simulated_design,
    make_spare_part_line,
    make_staging_bay,
    read_project,
    read_segment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProjectCreation:
    """Opening a project echoes its inputs and seeds three ledgers."""

    def test_creation_returns_201_with_stored_inputs_and_seeded_ledgers(self, api):
        """Every declared input is echoed and all three ledgers are seeded at once.

        PRD §3.1: "The remainder of the new project's state is seeded
        deterministically. `design_version` starts at 1, `delivery_status` at `DESIGN`,
        `commercial_status` at `CLEAN`, and `design_frozen_at` at null."

        Design: Corner/entities/project_creation_returns_201_with_stored_inputs_and_seeded_ledgers
        """
        created = validate_success(
            api.create_project(create_project_payload(), PROJECT_DIRECTOR), expected_status=201
        )
        assert_project(created)

        assert created["customer_name"] == "Northstar Grocers"
        assert created["facility_code"] == "DC-ATL-04"
        assert created["required_throughput_cph"] == 1250
        assert created["contract_base_cents"] == 240_000_000
        assert created["escalation_fee_cents"] == 3_600_000
        assert created["contract_value_cents"] == 243_600_000
        assert created["response_sla_minutes"] == 240
        assert created["legacy_share_bps"] == 10000
        assert created["in_transition_share_bps"] == 0
        assert created["cutover_share_bps"] == 0
        assert created["spares_allocated_cents"] == 0
        assert created["spares_unallocated_cents"] == 5_000_000
        assert created["design_version"] == 1
        assert created["version"] == 1
        assert created["delivery_status"] == "DESIGN"
        assert created["commercial_status"] == "CLEAN"
        assert created["design_frozen_at"] is None
        assert created["acceptance_ready"] is False

    def test_creation_without_service_tier_is_a_malformed_request(self, api):
        """service_tier is a required enumerated input, so its absence is a 400.

        PRD §2.12: "**Request-body shape** — required fields are present, enumerated
        fields carry declared values, integers satisfy their declared bounds, and every
        interval is properly ordered (`occupancy_end_utc` strictly after
        `occupancy_start_utc`, `end_utc` strictly after `start_utc`,
        `protected_shift_end_minute` strictly greater than
        `protected_shift_start_minute`), otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/project_creation_missing_service_tier_returns_invalid_request
        """
        payload = create_project_payload(customer_name="Midway Grocers", facility_code="DC-ORD-05")
        payload.pop("service_tier")

        response = api.create_project(payload, PROJECT_DIRECTOR)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestSegmentRepresentation:
    """A segment reads back exactly as written, with simulation outputs still zero."""

    def test_retrieval_returns_the_stored_rating_and_class(self, api):
        """A MERGE source segment keeps its rating and reports zeroed derived fields.

        PRD §3.2: "A freshly created segment starts with `inbound_link_count` 0,
        `outbound_link_count` 0, `flow_share_bps` 0 and `derated_capacity_cph` 0 — the
        last two remain zero until a simulation writes them."

        Design: Corner/entities/segment_retrieval_returns_stored_rating_and_class
        """
        project = make_project(
            api,
            customer_name="Harbor Freight Lines",
            facility_code="DC-SEA-02",
            required_throughput_cph=1200,
            contract_base_cents=200_000_000,
            authorized_ceiling_cents=260_000_000,
            spares_budget_cents=3_000_000,
            service_tier="BASIC",
        )
        created = make_segment(
            api,
            project["id"],
            segment_code="MG-X",
            equipment_class="MERGE",
            rated_capacity_cph=1751,
            availability_pct=89,
            source_share_bps=10000,
        )

        stored = validate_success(api.get_segment(created["id"], SHOP_SUPERVISOR))
        assert_segment(stored)
        assert stored["segment_code"] == "MG-X"
        assert stored["equipment_class"] == "MERGE"
        assert stored["rated_capacity_cph"] == 1751
        assert stored["availability_pct"] == 89
        assert stored["source_share_bps"] == 10000
        assert stored["inbound_link_count"] == 0
        assert stored["outbound_link_count"] == 0
        assert stored["flow_share_bps"] == 0
        assert stored["derated_capacity_cph"] == 0

    def test_an_unknown_segment_id_is_a_typed_404(self, api):
        """A well-formed UUID matching no row yields the segment's own not-found code.

        PRD §2.11: "Each resource type has its own not-found code: a project identifier
        that does not resolve yields `ERR_PROJECT_NOT_FOUND`, a segment identifier
        `ERR_SEGMENT_NOT_FOUND`, a flow-link identifier `ERR_FLOW_LINK_NOT_FOUND`, a
        fabrication-lot identifier `ERR_LOT_NOT_FOUND`, a cutover-window identifier
        `ERR_WINDOW_NOT_FOUND`, a change-order identifier `ERR_CHANGE_ORDER_NOT_FOUND`,
        an acceptance-certificate identifier `ERR_CERTIFICATE_NOT_FOUND` and a
        performance-dispute identifier `ERR_DISPUTE_NOT_FOUND`."

        Design: Corner/entities/segment_read_with_unknown_id_returns_segment_not_found
        """
        response = api.get_segment(NON_EXISTENT_UUID, DESIGN_ENGINEER)
        validate_error(response, ApiErrorId.ERR_SEGMENT_NOT_FOUND.value)

    def test_an_undeclared_equipment_class_is_rejected_and_moves_no_version(self, api):
        """SPIRAL is outside the four declared families, so nothing is persisted.

        PRD §3.2: "Each node is a **conveyor segment** created against a project by
        naming its `project_id`, its business identifier `segment_code` (something like
        "IB-01", unique among that project's segments), the equipment family it was
        selected from in `equipment_class` — one of `BELT`, `ROLLER`, `SORTATION` or
        `MERGE` — its vendor nameplate rating in `rated_capacity_cph` (at least 1 carton
        per hour), and its expected mechanical availability as a whole percent in
        `availability_pct` (from 1 through 100 inclusive)."

        Design: Corner/entities/segment_creation_with_unknown_equipment_class_returns_invalid_enum
        """
        project = make_project(api)

        response = api.create_segment(
            create_segment_payload(
                project["id"],
                segment_code="SP-09",
                equipment_class="SPIRAL",
                rated_capacity_cph=1500,
                availability_pct=96,
                source_share_bps=10000,
            ),
            DESIGN_ENGINEER,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

        after = read_project(api, project["id"])
        assert after["design_version"] == 1
        assert after["version"] == 1
        _, meta = validate_paginated(api.list_project_segments(project["id"], DESIGN_ENGINEER))
        assert meta["total_count"] == 0


class TestFlowLinkIsAnAppendOnlyEdge:
    """Edges are junction rows: they carry counts on their endpoints and no version."""

    def test_creating_an_edge_refreshes_both_link_counters(self, api):
        """One edge raises exactly one outbound and one inbound counter.

        PRD §3.2: "Creating a link increments the upstream segment's
        `outbound_link_count` by 1 and the downstream segment's `inbound_link_count` by
        1."

        Design: Corner/entities/flow_link_creation_refreshes_inbound_and_outbound_link_counts
        """
        design = make_linear_design(api)
        third = make_segment(
            api,
            design["project"]["id"],
            segment_code="TR-03",
            equipment_class="ROLLER",
            rated_capacity_cph=1300,
            availability_pct=95,
            source_share_bps=10000,
        )

        assert design["link"]["split_share_bps"] == 10000
        upstream = read_segment(api, design["ib01"]["id"])
        downstream = read_segment(api, design["tr02"]["id"])
        untouched = read_segment(api, third["id"])

        assert upstream["outbound_link_count"] == 1
        assert upstream["inbound_link_count"] == 0
        assert downstream["inbound_link_count"] == 1
        assert downstream["outbound_link_count"] == 0
        assert untouched["inbound_link_count"] == 0
        assert untouched["outbound_link_count"] == 0

        _, meta = validate_paginated(
            api.list_flow_links(DESIGN_ENGINEER, params={"to_segment_id": design["tr02"]["id"]})
        )
        assert meta["total_count"] == 1

    def test_a_flow_link_carries_neither_version_nor_updated_at(self, api):
        """The edge is an append-only ledger entry, so those two keys must be absent.

        PRD §2.4: "Three record types are append-only ledger entries and therefore carry
        only `id` and `created_at` — they have neither an `updated_at` field nor a
        `version` field, and neither field should appear in their representations at all:
        flow links, factory acceptance tests, and commissioning ramp steps."

        Design: Corner/entities/flow_link_is_immutable_with_no_version_field_and_no_patch_endpoint
        """
        design = make_linear_design(api)

        stored = validate_success(api.get_flow_link(design["link"]["id"], DESIGN_ENGINEER))
        assert_flow_link(stored)
        assert_append_only_fields(stored)
        assert stored["project_id"] == design["project"]["id"]
        assert stored["from_segment_id"] == design["ib01"]["id"]
        assert stored["to_segment_id"] == design["tr02"]["id"]
        assert stored["split_share_bps"] == 10000
        assert "version" not in stored
        assert "updated_at" not in stored


class TestSparePartLineRepresentation:
    """Money on a spare line is computed at creation, before any waterfall."""

    def test_requested_and_weighted_target_are_computed_at_creation(self, api):
        """A MAJOR line of 645,003 by 2 requests 1,290,006 and targets 774,004.

        PRD §3.9: "At creation the line's `requested_cents` is computed as
        `unit_cost_cents` multiplied by `min_stock_qty`, and its `weighted_target_cents`
        as `requested_cents` multiplied by the coverage factor for its class, divided by
        10000 and rounded half up to a whole cent."

        Design: Corner/entities/spare_part_line_requested_and_weighted_target_computed_at_creation
        """
        project = make_project(
            api,
            customer_name="Lakeside Foods",
            facility_code="DC-MSP-01",
            spares_budget_cents=3_500_000,
        )
        line = make_spare_part_line(
            api,
            project["id"],
            part_no="GB-4400",
            criticality="MAJOR",
            unit_cost_cents=645_003,
            min_stock_qty=2,
            lead_time_days=30,
        )

        assert_spare_part_line(line)
        assert line["requested_cents"] == 1_290_006
        assert line["weighted_target_cents"] == 774_004
        assert line["allocated_cents"] == 0
        assert line["status"] == "DRAFT"

        after = read_project(api, project["id"])
        assert after["spares_allocated_cents"] == 0
        assert after["spares_unallocated_cents"] == 3_500_000

    def test_the_listing_pages_with_total_count_and_has_more(self, api):
        """Three lines paged two at a time report a stable total and a flipping has_more.

        PRD §2.3: "For every list response, the `meta` object carries all four
        pagination fields: `limit` and `offset` echo the effective values actually
        applied, `total_count` reports the number of records matching the filter before
        paging, and `has_more` is true exactly when records remain beyond the current
        window."

        Design: Corner/entities/spare_part_lines_listing_paginates_with_total_count_and_has_more
        """
        project = make_project(
            api, customer_name="Lakeside Foods", facility_code="DC-MSP-01"
        )
        make_spare_part_line(
            api,
            project["id"],
            part_no="BR-1000",
            criticality="CRITICAL",
            unit_cost_cents=850_000,
            min_stock_qty=2,
            lead_time_days=90,
        )
        make_spare_part_line(
            api,
            project["id"],
            part_no="MT-2000",
            criticality="MAJOR",
            unit_cost_cents=1_255_000,
            min_stock_qty=2,
            lead_time_days=60,
        )
        make_spare_part_line(
            api,
            project["id"],
            part_no="BL-3000",
            criticality="MINOR",
            unit_cost_cents=100_000,
            min_stock_qty=1,
            lead_time_days=10,
        )

        first_page, first_meta = validate_paginated(
            api.list_spare_part_lines(
                project["id"], PROJECT_DIRECTOR, params={"limit": 2, "offset": 0}
            )
        )
        assert first_meta["total_count"] == 3
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True
        assert len(first_page) == 2

        second_page, second_meta = validate_paginated(
            api.list_spare_part_lines(
                project["id"], PROJECT_DIRECTOR, params={"limit": 2, "offset": 2}
            )
        )
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert len(second_page) == 1

        filtered, filtered_meta = validate_paginated(
            api.list_spare_part_lines(
                project["id"], PROJECT_DIRECTOR, params={"criticality": "MINOR"}
            )
        )
        assert filtered_meta["total_count"] == 1
        assert [line["part_no"] for line in filtered] == ["BL-3000"]


class TestFabricationLotRepresentation:
    """Planning snapshots the shop target and starts the attempt counter at zero."""

    def test_a_new_lot_defaults_to_planned_with_zero_attempts(self, api):
        """The traveller opens at PLANNED with a 1313 carton target and version 1.

        PRD §3.4: "The lot's `fat_target_cph` is snapshotted as the project's
        `required_throughput_cph` multiplied by 105 and divided by 100, rounded **up** to
        the next whole carton per hour — the shop must demonstrate five percent of
        headroom above the contractual rate, because a test loop is kinder than a live
        facility."

        Design: Corner/entities/fabrication_lot_created_defaults_to_planned_with_zero_attempts
        """
        frozen = make_frozen_project(api)
        bay = make_staging_bay(api, bay_code="BAY-1", concurrent_capacity=2)

        lot = validate_success(
            api.create_fabrication_lot(
                create_fabrication_lot_payload(
                    frozen["project"]["id"],
                    bay["id"],
                    ["IB-01", "TR-02"],
                    lot_code="LOT-100",
                    occupancy_start_utc="2026-08-02T00:00:00Z",
                    occupancy_end_utc="2026-08-05T00:00:00Z",
                ),
                SHOP_SUPERVISOR,
            ),
            expected_status=201,
        )
        assert_fabrication_lot(lot)
        assert lot["status"] == "PLANNED"
        assert lot["fat_attempt_count"] == 0
        assert lot["fat_target_cph"] == 1313
        assert lot["version"] == 1

    def test_a_segment_code_from_another_project_is_a_404(self, api):
        """segment_codes resolve inside the lot's own project and nowhere else.

        PRD §2.11: "Every element of a lot's `segment_codes` array must also resolve to
        a conveyor segment of the same project; an element that does not resolve yields
        `ERR_SEGMENT_NOT_FOUND`."

        Design: Corner/entities/fabrication_lot_with_segment_code_of_another_project_returns_segment_not_found
        """
        frozen = make_frozen_project(api)
        other = make_project(
            api,
            customer_name="Cascade Distribution",
            facility_code="DC-PDX-07",
            customer_rep_user_id="cust-rep-88",
            required_throughput_cph=1200,
            contract_base_cents=200_000_000,
            authorized_ceiling_cents=260_000_000,
            spares_budget_cents=3_000_000,
            service_tier="BASIC",
        )
        make_segment(
            api,
            other["id"],
            segment_code="XX-99",
            equipment_class="BELT",
            rated_capacity_cph=1500,
            availability_pct=90,
            source_share_bps=10000,
        )
        bay = make_staging_bay(api, bay_code="BAY-2", concurrent_capacity=2)

        response = api.create_fabrication_lot(
            create_fabrication_lot_payload(
                frozen["project"]["id"],
                bay["id"],
                ["IB-01", "XX-99"],
                lot_code="LOT-200",
            ),
            SHOP_SUPERVISOR,
        )
        validate_error(response, ApiErrorId.ERR_SEGMENT_NOT_FOUND.value)

        _, meta = validate_paginated(
            api.list_fabrication_lots(
                SHOP_SUPERVISOR, params={"project_id": frozen["project"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert read_project(api, frozen["project"]["id"])["delivery_status"] == "DESIGN_FROZEN"


class TestSystemStampedFields:
    """Instants come from the logical clock, never from the host wall clock."""

    def test_design_frozen_at_is_stamped_from_the_logical_clock(self, api):
        """The freeze records the instant the clock was set to just beforehand.

        PRD §3.4: "A successful freeze writes `design_frozen_at` from the logical clock
        and increments the project's `version` by 1."

        Design: Corner/entities/project_design_frozen_at_stamped_from_the_logical_clock
        """
        design = make_simulated_design(api)
        assert design["project"]["design_frozen_at"] is None
        set_clock(api, "2026-08-03T09:15:00Z")

        frozen = validate_success(
            api.design_freeze(design["project"]["id"], PROJECT_DIRECTOR)
        )
        assert frozen["delivery_status"] == "DESIGN_FROZEN"
        assert is_iso8601_timestamp(frozen["design_frozen_at"])
        assert frozen["design_frozen_at"].startswith("2026-08-03T09:15:00")
        assert frozen["commercial_status"] == "CLEAN"
