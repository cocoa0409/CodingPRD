"""Graph, share, uniqueness and precedence validations, and what they leave behind."""

from test_helpers import (
    DESIGN_ENGINEER,
    NON_EXISTENT_UUID,
    PROJECT_DIRECTOR,
    SITE_MANAGER,
    TEST_INSTANTS,
    ApiErrorId,
    assert_segment,
    create_flow_link_payload,
    create_segment_payload,
    create_simulation_payload,
    make_fat_passed_lot,
    make_linear_design,
    make_project,
    make_scheduled_window,
    make_segment,
    make_staging_bay,
    read_project,
    read_segment,
    read_window,
    run_simulation,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTheGraphMustStayAcyclic:
    """A reverse edge would close a cycle over the two-segment line."""

    def test_the_reverse_edge_is_rejected_with_flow_cycle(self, api):
        """TR-02 back to IB-01 closes the only possible cycle on this graph.

        PRD §3.2: "The graph must remain acyclic: any requested link that would close a
        cycle among the project's segments is rejected with `ERR_FLOW_CYCLE`, which is why
        the simulation may assume acyclicity without re-checking it."

        Design: Corner/validations/flow_link_closing_a_cycle_returns_flow_cycle
        """
        design = make_linear_design(api)

        response = api.create_flow_link(
            create_flow_link_payload(
                design["project"]["id"], design["tr02"]["id"], design["ib01"]["id"], 10000
            ),
            DESIGN_ENGINEER,
        )
        validate_error(response, ApiErrorId.ERR_FLOW_CYCLE.value)

    def test_the_rejected_edge_moves_no_counter_and_no_design_version(self, api):
        """The counters and the design version stay exactly as the first edge left them.

        PRD §3.2: "All three design mutations — adding a segment, revising a segment,
        adding a flow link — increment the project's `design_version` by 1 and the
        project's `version` by 1, and turn every simulation run of the project whose
        `status` is `COMPLETE` into `STALE`."

        Design: Corner/validations/flow_link_closing_a_cycle_returns_flow_cycle
        """
        design = make_linear_design(api)
        api.create_flow_link(
            create_flow_link_payload(
                design["project"]["id"], design["tr02"]["id"], design["ib01"]["id"], 10000
            ),
            DESIGN_ENGINEER,
        )

        upstream = read_segment(api, design["ib01"]["id"])
        downstream = read_segment(api, design["tr02"]["id"])
        assert upstream["outbound_link_count"] == 1
        assert upstream["inbound_link_count"] == 0
        assert downstream["inbound_link_count"] == 1
        assert downstream["outbound_link_count"] == 0
        assert read_project(api, design["project"]["id"])["design_version"] == 4

        links, meta = validate_paginated(
            api.list_flow_links(DESIGN_ENGINEER, params={"project_id": design["project"]["id"]})
        )
        assert meta["total_count"] == 1
        assert [link["id"] for link in links] == [design["link"]["id"]]


class TestSegmentCodeUniquenessIsScopedToTheProject:
    """The same business code is a duplicate inside a project and legal outside it."""

    def test_a_second_segment_with_the_same_code_is_rejected(self, api):
        """Every other attribute differs and the code alone still decides.

        PRD §3.2: "Segment creation is only legal while the project's `delivery_status` is
        `DESIGN`; attempting it in any other delivery state is rejected with
        `ERR_PROJECT_NOT_IN_DESIGN`, and re-using a `segment_code` already present on the
        same project is rejected with `ERR_DUPLICATE_SEGMENT_CODE`."

        Design: Corner/validations/duplicate_segment_code_within_a_project_returns_duplicate_segment_code
        """
        project = make_project(api)
        first = make_segment(
            api,
            project["id"],
            segment_code="IB-01",
            equipment_class="BELT",
            rated_capacity_cph=1500,
            availability_pct=96,
            source_share_bps=10000,
        )

        response = api.create_segment(
            create_segment_payload(
                project["id"],
                segment_code="IB-01",
                equipment_class="SORTATION",
                rated_capacity_cph=900,
                availability_pct=90,
                source_share_bps=None,
            ),
            DESIGN_ENGINEER,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_SEGMENT_CODE.value)

        stored = read_segment(api, first["id"])
        assert stored["equipment_class"] == "BELT"
        assert stored["rated_capacity_cph"] == 1500

        after = read_project(api, project["id"])
        assert after["design_version"] == 2
        assert after["delivery_status"] == "DESIGN"
        _, meta = validate_paginated(api.list_project_segments(project["id"], DESIGN_ENGINEER))
        assert meta["total_count"] == 1

    def test_the_same_code_on_another_project_is_accepted(self, api):
        """Uniqueness is "unique among that project's segments", so IB-01 may recur.

        PRD §3.2: "Each node is a **conveyor segment** created against a project by
        naming its `project_id`, its business identifier `segment_code` (something like
        "IB-01", unique among that project's segments), the equipment family it was
        selected from in `equipment_class` — one of `BELT`, `ROLLER`, `SORTATION` or
        `MERGE` — its vendor nameplate rating in `rated_capacity_cph` (at least 1 carton
        per hour), and its expected mechanical availability as a whole percent in
        `availability_pct` (from 1 through 100 inclusive)."

        Design: Corner/validations/the_same_segment_code_on_a_different_project_is_accepted
        """
        first_project = make_project(api)
        first_segment = make_segment(
            api,
            first_project["id"],
            segment_code="IB-01",
            equipment_class="BELT",
            rated_capacity_cph=1500,
            availability_pct=96,
            source_share_bps=10000,
        )
        second_project = make_project(
            api,
            customer_name="Vantage Parcel",
            facility_code="DC-DEN-01",
            customer_rep_user_id="cust-rep-88",
            required_throughput_cph=600,
            contract_base_cents=100_000_000,
            authorized_ceiling_cents=120_000_000,
            spares_budget_cents=1_000_000,
            service_tier="BASIC",
        )

        twin = validate_success(
            api.create_segment(
                create_segment_payload(
                    second_project["id"],
                    segment_code="IB-01",
                    equipment_class="BELT",
                    rated_capacity_cph=800,
                    availability_pct=92,
                    source_share_bps=10000,
                ),
                DESIGN_ENGINEER,
            ),
            expected_status=201,
        )
        assert_segment(twin)
        assert twin["segment_code"] == "IB-01"
        assert twin["rated_capacity_cph"] == 800
        assert twin["id"] != first_segment["id"]
        assert twin["project_id"] == second_project["id"]
        assert read_project(api, second_project["id"])["design_version"] == 2
        assert read_project(api, first_project["id"])["design_version"] == 2


class TestBodyShapeOutranksBodyReferences:
    """Band 5 runs before band 6, so the enum decides and the unknown id does not."""

    def test_an_undeclared_enum_beats_an_unresolvable_project_id(self, api):
        """The request is malformed and unresolvable at once; 400 wins over 404.

        PRD §2.12: "**Body reference existence** — every identifier carried in the body
        resolves, and every `segment_codes` element resolves within the project, otherwise
        the matching 404 code from §2.11."

        Design: Corner/validations/malformed_enum_beats_an_unknown_project_id_and_returns_invalid_request
        """
        response = api.create_segment(
            create_segment_payload(
                NON_EXISTENT_UUID,
                segment_code="IB-01",
                equipment_class="TROLLEY",
                rated_capacity_cph=1500,
                availability_pct=96,
                source_share_bps=10000,
            ),
            DESIGN_ENGINEER,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestAnEdgeMayNotSpanTwoProjects:
    """Both endpoints exist, so the failure is coherence rather than existence."""

    def test_a_downstream_segment_of_another_project_is_refused(self, api):
        """The link names one project while its head belongs to another.

        PRD §2.12: "**Cross-aggregate coherence** — referenced rows belong to the project
        the request names, otherwise `ERR_CROSS_PROJECT_REFERENCE` (422). Applies to
        cutover-window creation, flow-link creation and dispute filing."

        Design: Corner/validations/flow_link_joining_segments_of_two_projects_returns_cross_project_reference
        """
        host = make_project(api)
        head = make_segment(
            api,
            host["id"],
            segment_code="IB-01",
            equipment_class="BELT",
            rated_capacity_cph=1500,
            availability_pct=96,
            source_share_bps=10000,
        )
        other = make_project(
            api,
            customer_name="Vantage Parcel",
            facility_code="DC-DEN-01",
            customer_rep_user_id="cust-rep-88",
            required_throughput_cph=600,
            contract_base_cents=100_000_000,
            authorized_ceiling_cents=120_000_000,
            spares_budget_cents=1_000_000,
            service_tier="BASIC",
        )
        foreign_tail = make_segment(
            api,
            other["id"],
            segment_code="OB-09",
            equipment_class="ROLLER",
            rated_capacity_cph=700,
            availability_pct=94,
            source_share_bps=10000,
        )

        response = api.create_flow_link(
            create_flow_link_payload(host["id"], head["id"], foreign_tail["id"], 10000),
            DESIGN_ENGINEER,
        )
        validate_error(response, ApiErrorId.ERR_CROSS_PROJECT_REFERENCE.value)

        assert read_segment(api, head["id"])["outbound_link_count"] == 0
        assert read_segment(api, foreign_tail["id"])["inbound_link_count"] == 0
        assert read_project(api, host["id"])["design_version"] == 2
        assert read_project(api, other["id"])["design_version"] == 2
        _, meta = validate_paginated(
            api.list_flow_links(DESIGN_ENGINEER, params={"project_id": host["id"]})
        )
        assert meta["total_count"] == 0


class TestShareIntegrityIsCheckedBeforeAnyArithmetic:
    """Step 0 of the run rejects incomplete source and split share sets."""

    def test_source_shares_totalling_eight_thousand_are_refused(self, api):
        """Two sources at 4000 basis points each leave a fifth of the mix unaccounted.

        PRD §3.3: "The source set is every segment whose `inbound_link_count` is 0. The
        `source_share_bps` values across that set must total exactly 10000, otherwise the
        run is rejected with `ERR_SOURCE_SHARE_INVALID`."

        Design: Corner/validations/simulation_with_source_shares_short_of_ten_thousand_returns_source_share_invalid
        """
        project = make_project(api, facility_code="DC-ATL-06")
        first = make_segment(
            api,
            project["id"],
            segment_code="IB-01",
            equipment_class="BELT",
            rated_capacity_cph=1500,
            availability_pct=96,
            source_share_bps=4000,
        )
        second = make_segment(
            api,
            project["id"],
            segment_code="IB-02",
            equipment_class="BELT",
            rated_capacity_cph=1500,
            availability_pct=96,
            source_share_bps=4000,
        )

        response = api.run_simulation(
            project["id"],
            create_simulation_payload("DETERMINISTIC_STEADY_STATE"),
            DESIGN_ENGINEER,
        )
        validate_error(response, ApiErrorId.ERR_SOURCE_SHARE_INVALID.value)

        _, meta = validate_paginated(api.list_simulation_runs(project["id"], DESIGN_ENGINEER))
        assert meta["total_count"] == 0
        assert read_segment(api, first["id"])["flow_share_bps"] == 0
        assert read_segment(api, second["id"])["flow_share_bps"] == 0
        assert read_project(api, project["id"])["delivery_status"] == "DESIGN"

    def test_an_incomplete_outbound_split_is_refused(self, api):
        """6000 plus 3000 out of IB-01 totals 9000, one thousand short of the whole.

        PRD §3.3: "For every segment whose `outbound_link_count` is 1 or more, the
        `split_share_bps` values of its outbound links must total exactly 10000, otherwise
        the run is rejected with `ERR_SPLIT_SHARE_INVALID`."

        Design: Corner/validations/outbound_split_shares_short_of_ten_thousand_return_split_share_invalid
        """
        project = make_project(api, facility_code="DC-ATL-07")
        source = make_segment(
            api,
            project["id"],
            segment_code="IB-01",
            equipment_class="BELT",
            rated_capacity_cph=1500,
            availability_pct=96,
            source_share_bps=10000,
        )
        first_tail = make_segment(
            api,
            project["id"],
            segment_code="TR-02",
            equipment_class="ROLLER",
            rated_capacity_cph=1400,
            availability_pct=95,
            source_share_bps=None,
        )
        second_tail = make_segment(
            api,
            project["id"],
            segment_code="TR-03",
            equipment_class="ROLLER",
            rated_capacity_cph=900,
            availability_pct=95,
            source_share_bps=None,
        )
        major = validate_success(
            api.create_flow_link(
                create_flow_link_payload(project["id"], source["id"], first_tail["id"], 6000),
                DESIGN_ENGINEER,
            ),
            expected_status=201,
        )
        minor = validate_success(
            api.create_flow_link(
                create_flow_link_payload(project["id"], source["id"], second_tail["id"], 3000),
                DESIGN_ENGINEER,
            ),
            expected_status=201,
        )

        response = api.run_simulation(
            project["id"], create_simulation_payload("DEGRADED_AVAILABILITY"), DESIGN_ENGINEER
        )
        validate_error(response, ApiErrorId.ERR_SPLIT_SHARE_INVALID.value)

        assert major["split_share_bps"] == 6000
        assert minor["split_share_bps"] == 3000
        assert read_segment(api, source["id"])["outbound_link_count"] == 2
        _, meta = validate_paginated(api.list_simulation_runs(project["id"], DESIGN_ENGINEER))
        assert meta["total_count"] == 0


class TestTheFreezeGateReadsTheConservativeNumber:
    """A current, complete degraded run that is simply too slow blocks the freeze."""

    def _short_line(self, api):
        design = make_linear_design(api, required_throughput_cph=1400)
        design["simulation"] = run_simulation(
            api, design["project"]["id"], "DEGRADED_AVAILABILITY"
        )
        return design

    def test_a_seventy_carton_shortfall_is_reported_as_throughput_shortfall(self, api):
        """1330 against a promised 1400 is a shortfall, not a missing run.

        PRD §3.4: "Finally that qualifying run's `effective_throughput_cph` must be
        greater than or equal to the project's `required_throughput_cph`; a shortfall is
        rejected with `ERR_THROUGHPUT_SHORTFALL`."

        Design: Corner/validations/degraded_shortfall_blocks_the_design_freeze_with_throughput_shortfall
        """
        design = self._short_line(api)
        run = design["simulation"]
        assert run["status"] == "COMPLETE"
        assert run["effective_throughput_cph"] == 1330
        assert run["shortfall_cph"] == 70
        assert run["bottleneck_segment_code"] == "TR-02"

        response = api.design_freeze(design["project"]["id"], PROJECT_DIRECTOR)
        validate_error(response, ApiErrorId.ERR_THROUGHPUT_SHORTFALL.value)

    def test_the_blocked_freeze_leaves_the_project_in_design(self, api):
        """Nothing is stamped and the derates keep the availability arithmetic visible.

        PRD §3.4: "It advances `delivery_status` from `DESIGN` to `DESIGN_FROZEN`, and it
        is deliberately hard to pass."

        Design: Corner/validations/degraded_shortfall_blocks_the_design_freeze_with_throughput_shortfall
        """
        design = self._short_line(api)
        api.design_freeze(design["project"]["id"], PROJECT_DIRECTOR)

        after = read_project(api, design["project"]["id"])
        assert after["delivery_status"] == "DESIGN"
        assert after["design_frozen_at"] is None
        assert read_segment(api, design["ib01"]["id"])["derated_capacity_cph"] == 1440
        assert read_segment(api, design["tr02"]["id"])["derated_capacity_cph"] == 1330
        assert (
            design["simulation"]["design_version_at_run"] == after["design_version"]
        )


class TestTheFacilityMustBeFullyPartitioned:
    """A single zone holding 6000 basis points cannot start the first window."""

    def _partial_partition(self, api):
        state = make_fat_passed_lot(
            api,
            bay=make_staging_bay(api, bay_code="BAY-13", concurrent_capacity=2),
            lot_code="LOT-1300",
            measured_cph=1313,
            defect_count=0,
        )
        state = make_scheduled_window(
            api, state=state, zone_overrides={"throughput_share_bps": 6000}
        )
        set_clock(api, TEST_INSTANTS["WINDOW_DUE_UTC"])
        return state

    def test_the_start_is_refused_with_zone_share_incomplete(self, api):
        """Every state gate is clean and the share band still stops the start.

        PRD §3.6: "Last of all, because it belongs to the share-integrity band, the
        `throughput_share_bps` of every site zone on the project must total exactly 10000
        before the very first window may start, otherwise `ERR_ZONE_SHARE_INCOMPLETE` —
        the facility must be fully partitioned before any of it is torn up."

        Design: Corner/validations/zone_shares_short_of_ten_thousand_block_the_first_window_start
        """
        state = self._partial_partition(api)

        response = api.start_cutover_window(state["window"]["id"], SITE_MANAGER)
        validate_error(response, ApiErrorId.ERR_ZONE_SHARE_INCOMPLETE.value)

        window = read_window(api, state["window"]["id"])
        assert window["status"] == "SCHEDULED"
        assert window["started_at"] is None

        zones = validate_success(api.list_site_zones(state["project"]["id"], SITE_MANAGER))
        assert [zone["ops_status"] for zone in zones] == ["LIVE_LEGACY"]

        project = read_project(api, state["project"]["id"])
        assert project["legacy_share_bps"] == 10000
        assert project["in_transition_share_bps"] == 0
        assert project["cutover_share_bps"] == 0
        assert project["delivery_status"] == "IN_FABRICATION"
