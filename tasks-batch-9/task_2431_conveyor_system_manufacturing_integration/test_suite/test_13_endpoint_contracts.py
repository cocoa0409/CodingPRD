"""Endpoint contracts: partial updates, the clock driver, reverse lookups and gates."""

from test_helpers import (
    DESIGN_ENGINEER,
    PROJECT_DIRECTOR,
    SHOP_SUPERVISOR,
    SITE_MANAGER,
    ApiErrorId,
    assert_project,
    assert_segment,
    create_cutover_window_payload,
    create_fabrication_lot_payload,
    create_project_payload,
    is_iso8601_timestamp,
    make_flow_link,
    make_linear_design,
    make_planned_lot,
    make_project,
    make_segment,
    make_site_zone,
    make_staging_bay,
    patch_segment_payload,
    read_project,
    read_segment,
    run_simulation,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSegmentRevisionIsAPartialUpdate:
    """PATCH rewrites one field, bumps two counters and invalidates the evidence."""

    def test_patching_the_rating_leaves_the_other_fields_alone(self, api):
        """Only rated_capacity_cph is supplied, so class, code and availability stand.

        PRD §3.2: "An engineer may revise a segment later, supplying any subset of
        `rated_capacity_cph`, `availability_pct` and `source_share_bps`; a revision is
        subject to the same `DESIGN`-only gate and the same `ERR_PROJECT_NOT_IN_DESIGN`
        rejection, and it increments the segment's own `version` by 1."

        Design: Corner/endpoints/segment_patch_revises_the_rating_and_stales_the_current_simulation
        """
        design = make_linear_design(api)
        run_simulation(api, design["project"]["id"], "DETERMINISTIC_STEADY_STATE")
        before = read_segment(api, design["tr02"]["id"])

        revised = validate_success(
            api.update_segment(
                design["tr02"]["id"],
                patch_segment_payload(rated_capacity_cph=1200),
                DESIGN_ENGINEER,
            )
        )
        assert_segment(revised)
        assert revised["rated_capacity_cph"] == 1200
        assert revised["availability_pct"] == 95
        assert revised["segment_code"] == "TR-02"
        assert revised["equipment_class"] == "ROLLER"
        assert revised["version"] == before["version"] + 1

    def test_the_revision_stales_the_complete_run_without_recomputing_it(self, api):
        """The run keeps its 1400 and the segment keeps its pre-edit derate.

        PRD §3.2: "All three design mutations — adding a segment, revising a segment,
        adding a flow link — increment the project's `design_version` by 1 and the
        project's `version` by 1, and turn every simulation run of the project whose
        `status` is `COMPLETE` into `STALE`."

        Design: Corner/endpoints/segment_patch_revises_the_rating_and_stales_the_current_simulation
        """
        design = make_linear_design(api)
        project_id = design["project"]["id"]
        run = run_simulation(api, project_id, "DETERMINISTIC_STEADY_STATE")
        assert run["effective_throughput_cph"] == 1400

        validate_success(
            api.update_segment(
                design["tr02"]["id"],
                patch_segment_payload(rated_capacity_cph=1200),
                DESIGN_ENGINEER,
            )
        )

        runs, meta = validate_paginated(api.list_simulation_runs(project_id, DESIGN_ENGINEER))
        assert meta["total_count"] == 1
        assert runs[0]["id"] == run["id"]
        assert runs[0]["status"] == "STALE"
        assert runs[0]["effective_throughput_cph"] == 1400

        assert read_segment(api, design["tr02"]["id"])["derated_capacity_cph"] == 1400
        after = read_project(api, project_id)
        assert after["design_version"] == 5
        assert after["delivery_status"] == "DESIGN"


class TestTheClockDrivesTimestampsAndMutatesNothing:
    """Moving the clock rewrites no row; it only changes what the next write records."""

    def test_a_clock_move_leaves_the_existing_project_untouched(self, api):
        """The project created at the default keeps its default stamps and version.

        PRD §2.4: "An administrative test-driving capability, restricted to a
        `ProjectDirector`, sets the clock to an instant supplied as `to_iso8601`; the
        clock may be advanced or rewound freely and setting it mutates no entity."

        Design: Corner/endpoints/clock_set_endpoint_moves_the_logical_clock_without_mutating_entities
        """
        first = make_project(api)
        assert first["created_at"].startswith("2026-08-01T00:00:00")

        set_clock(api, "2026-09-15T06:30:00Z")

        after = read_project(api, first["id"])
        assert after["created_at"].startswith("2026-08-01T00:00:00")
        assert after["updated_at"].startswith("2026-08-01T00:00:00")
        assert after["version"] == 1
        assert after["design_version"] == 1
        assert after["delivery_status"] == "DESIGN"

    def test_the_next_created_project_is_stamped_from_the_new_instant(self, api):
        """The clock, not the host wall clock, supplies created_at on the next write.

        PRD §2.4: "All time-dependent behaviour in this system reads a **logical clock**
        rather than the host's wall clock. The clock's startup value is exactly
        `2026-08-01T00:00:00Z`, and it never falls back to real time."

        Design: Corner/endpoints/clock_set_endpoint_moves_the_logical_clock_without_mutating_entities
        """
        make_project(api)
        set_clock(api, "2026-09-15T06:30:00Z")

        later = validate_success(
            api.create_project(
                create_project_payload(
                    customer_name="Vantage Parcel",
                    facility_code="DC-DEN-01",
                    customer_rep_user_id="cust-rep-90",
                    required_throughput_cph=600,
                    contract_base_cents=100_000_000,
                    authorized_ceiling_cents=120_000_000,
                    spares_budget_cents=1_000_000,
                    service_tier="BASIC",
                ),
                PROJECT_DIRECTOR,
            ),
            expected_status=201,
        )
        assert_project(later)
        assert is_iso8601_timestamp(later["created_at"])
        assert later["created_at"].startswith("2026-09-15T06:30:00")


class TestAWindowIsReachableFromBothOfItsParents:
    """The same row answers the zone filter and the lot filter."""

    def _scheduled_against_a_whole_facility(self, api):
        state = make_planned_lot(
            api,
            bay=make_staging_bay(api, bay_code="BAY-14", concurrent_capacity=1),
            segment_codes=["IB-01", "TR-02"],
            lot_code="LOT-1400",
        )
        state["zone"] = make_site_zone(
            api, state["project"]["id"], zone_code="Z-INBOUND", throughput_share_bps=10000
        )
        state["window"] = validate_success(
            api.create_cutover_window(
                create_cutover_window_payload(
                    state["project"]["id"], state["zone"]["id"], state["lot"]["id"]
                ),
                SITE_MANAGER,
            ),
            expected_status=201,
        )
        return state

    def test_scheduling_binds_the_zone_and_the_lot_without_advancing_either(self, api):
        """A new window opens SCHEDULED with both instants null and the lot still PLANNED.

        PRD §3.6: "A new window is created with `status` `SCHEDULED`, with `abort_reason`,
        `started_at` and `closed_at` all null, and it increments the project's `version` by
        1."

        Design: Corner/endpoints/cutover_window_is_reachable_through_both_the_zone_and_the_lot_filter
        """
        state = self._scheduled_against_a_whole_facility(api)
        window = state["window"]

        assert window["site_zone_id"] == state["zone"]["id"]
        assert window["fabrication_lot_id"] == state["lot"]["id"]
        assert window["status"] == "SCHEDULED"
        assert window["started_at"] is None
        assert window["closed_at"] is None
        assert window["abort_reason"] is None
        assert validate_success(api.get_fabrication_lot(state["lot"]["id"], SHOP_SUPERVISOR))[
            "status"
        ] == "PLANNED"

    def test_both_reverse_lookups_reach_the_same_single_row(self, api):
        """Filtering by zone, by lot, or by project and status all return that one window.

        PRD §3.6: "Windows may be read individually or listed with `project_id`,
        `site_zone_id`, `fabrication_lot_id` and `status` filters."

        Design: Corner/endpoints/cutover_window_is_reachable_through_both_the_zone_and_the_lot_filter
        """
        state = self._scheduled_against_a_whole_facility(api)
        window_id = state["window"]["id"]

        by_zone, zone_meta = validate_paginated(
            api.list_cutover_windows(SITE_MANAGER, params={"site_zone_id": state["zone"]["id"]})
        )
        assert zone_meta["total_count"] == 1
        assert [window["id"] for window in by_zone] == [window_id]

        by_lot, lot_meta = validate_paginated(
            api.list_cutover_windows(
                SITE_MANAGER, params={"fabrication_lot_id": state["lot"]["id"]}
            )
        )
        assert lot_meta["total_count"] == 1
        assert [window["id"] for window in by_lot] == [window_id]

        _, status_meta = validate_paginated(
            api.list_cutover_windows(
                SITE_MANAGER,
                params={"project_id": state["project"]["id"], "status": "SCHEDULED"},
            )
        )
        assert status_meta["total_count"] == 1


class TestTheSegmentListReportsTheLatestRunsFlowShares:
    """A split design leaves 10000 / 6000 / 4000 on the rows the run touched."""

    def _split_design(self, api):
        project = make_project(api, facility_code="DC-ATL-11")
        source = make_segment(
            api,
            project["id"],
            segment_code="IB-01",
            equipment_class="BELT",
            rated_capacity_cph=1500,
            availability_pct=96,
            source_share_bps=10000,
        )
        major = make_segment(
            api,
            project["id"],
            segment_code="TR-02",
            equipment_class="ROLLER",
            rated_capacity_cph=1400,
            availability_pct=95,
            source_share_bps=None,
        )
        minor = make_segment(
            api,
            project["id"],
            segment_code="TR-03",
            equipment_class="ROLLER",
            rated_capacity_cph=900,
            availability_pct=95,
            source_share_bps=None,
        )
        make_flow_link(api, project["id"], source["id"], major["id"], 6000)
        make_flow_link(api, project["id"], source["id"], minor["id"], 4000)
        return {"project": project, "source": source, "major": major, "minor": minor}

    def test_the_source_carrying_the_whole_flow_is_the_bottleneck(self, api):
        """1440 at full share beats 2216 and 2137 on the fractionally-loaded branches.

        PRD §3.3: "Each segment implies a sustainable *system* rate: its
        `derated_capacity_cph` multiplied by 10000, divided by its `flow_share_bps`, with
        any fractional remainder discarded."

        Design: Corner/endpoints/segment_list_exposes_the_flow_shares_of_the_latest_run
        """
        design = self._split_design(api)

        run = run_simulation(api, design["project"]["id"], "DEGRADED_AVAILABILITY")
        assert run["effective_throughput_cph"] == 1440
        assert run["bottleneck_segment_code"] == "IB-01"
        assert run["bottleneck_availability_pct"] == 96
        assert run["shortfall_cph"] == 0

    def test_the_listing_exposes_every_share_and_derate_the_run_wrote(self, api):
        """Each row carries the share it received and the degraded capacity it kept.

        PRD §3.3: "Because the run refreshes `flow_share_bps` and `derated_capacity_cph`
        on every segment of the project, those two fields always reflect the method of the
        project's most recent run — a deterministic run overwrites the derated capacities a
        degraded run had written, and vice versa."

        Design: Corner/endpoints/segment_list_exposes_the_flow_shares_of_the_latest_run
        """
        design = self._split_design(api)
        run_simulation(api, design["project"]["id"], "DEGRADED_AVAILABILITY")

        segments, meta = validate_paginated(
            api.list_project_segments(design["project"]["id"], DESIGN_ENGINEER)
        )
        assert meta["total_count"] == 3
        by_code = {segment["segment_code"]: segment for segment in segments}
        assert by_code["IB-01"]["flow_share_bps"] == 10000
        assert by_code["IB-01"]["derated_capacity_cph"] == 1440
        assert by_code["TR-02"]["flow_share_bps"] == 6000
        assert by_code["TR-02"]["derated_capacity_cph"] == 1330
        assert by_code["TR-03"]["flow_share_bps"] == 4000
        assert by_code["TR-03"]["derated_capacity_cph"] == 855

        _, roller_meta = validate_paginated(
            api.list_project_segments(
                design["project"]["id"], DESIGN_ENGINEER, params={"equipment_class": "ROLLER"}
            )
        )
        assert roller_meta["total_count"] == 2


class TestPlanningALotIsConditionalOnTheFreeze:
    """Every reference resolves and the interval is legal; the design state still refuses."""

    def test_a_lot_planned_before_the_freeze_is_refused(self, api):
        """DESIGN is the state the gate names above all others.

        PRD §3.4: "Planning a lot requires a frozen design: the project's
        `delivery_status` must be `DESIGN_FROZEN`, `IN_FABRICATION` or
        `REBASELINE_REQUIRED`, and any other delivery state — `DESIGN` above all — is
        rejected with `ERR_DESIGN_NOT_FROZEN`."

        Design: Corner/endpoints/fabrication_lot_creation_before_design_freeze_returns_design_not_frozen
        """
        project = make_project(api, facility_code="DC-ATL-12")
        make_segment(
            api,
            project["id"],
            segment_code="IB-01",
            equipment_class="BELT",
            rated_capacity_cph=1500,
            availability_pct=96,
            source_share_bps=10000,
        )
        bay = make_staging_bay(api, bay_code="BAY-15", concurrent_capacity=1)

        response = api.create_fabrication_lot(
            create_fabrication_lot_payload(
                project["id"], bay["id"], ["IB-01"], lot_code="LOT-1500"
            ),
            SHOP_SUPERVISOR,
        )
        validate_error(response, ApiErrorId.ERR_DESIGN_NOT_FROZEN.value)

        after = read_project(api, project["id"])
        assert after["delivery_status"] == "DESIGN"
        assert after["design_frozen_at"] is None
        _, meta = validate_paginated(
            api.list_fabrication_lots(SHOP_SUPERVISOR, params={"project_id": project["id"]})
        )
        assert meta["total_count"] == 0
