"""The endpoint surface of the white space: the as-built tagging write, the phase
conditional energise action, the feed junction write, the reconciliation read and the
filtered, paged rack listing."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    EC,
    FP,
    OM,
    advance_phase,
    commission_cooling_unit,
    commission_pdu,
    create_busway,
    create_cooling_unit,
    create_hall,
    create_pdu,
    create_rack,
    create_zone,
    energize_busway,
    install_rack,
    leakage_test,
    place_unit_in_service,
    power_on_rack,
    read_busway,
    read_capacity_summary,
    read_hall,
    read_rack,
    reserve_feed,
)


class TestRackAssetTagWrite:
    """The dedicated tagging write overwrites a position's asset tag on a PLANNED
    position, bumps its version and changes nothing else about it."""

    def _planning_hall_with_a_tagged_position(self):
        hall = create_hall("CX61", design_kw_capacity=400.00)
        zone = create_zone(hall["id"], "CA-1")
        rack = create_rack(
            hall["id"], zone["id"], "1", 1, design_kw=12.00, asset_tag="AT-OLD"
        )
        return {"hall_id": hall["id"], "zone_id": zone["id"], "rack": rack}

    def test_tagging_write_overwrites_the_tag_and_the_read_shows_it(self):
        """Correcting the as-built tag of a PLANNED position returns 200 with the new
        tag, advances the position's version by exactly one, and the following detail
        read publishes the new tag with the status still PLANNED.

        PRD: "As-built documentation is a first-class concern, not an afterthought, so
        the planner may write or correct a position's `asset_tag` at any status through
        a dedicated tagging write."

        PRD: "Thirteen of the fourteen resource types additionally carry `updated_at` —
        an ISO 8601 UTC timestamp refreshed on every mutation — and `version`, an
        integer that starts at 1 when the row is created and increments by exactly one
        on every mutation of that row, including mutations that only touch computed
        fields."

        Design: Corner/endpoints/rack_asset_tag_patch_writes_and_reads_back
        """
        ctx = self._planning_hall_with_a_tagged_position()
        before = ctx["rack"]
        assert before["asset_tag"] == "AT-OLD"
        assert before["status"] == "PLANNED"

        patched = validate_success(
            api_client.patch_rack(before["id"], {"asset_tag": "AT-NEW-61"}, FP), 200
        )
        assert patched["asset_tag"] == "AT-NEW-61", (
            "the tagging write overwrites the stored asset tag"
        )
        assert patched["version"] == before["version"] + 1, (
            "a tagging write is a mutation, so the version advances by exactly one"
        )
        assert patched["status"] == "PLANNED", (
            "tagging is not a lifecycle transition and leaves the status alone"
        )

        read_back = read_rack(before["id"])
        assert read_back["asset_tag"] == "AT-NEW-61"
        assert read_back["status"] == "PLANNED"
        assert read_back["version"] == before["version"] + 1

    def test_tagging_leaves_both_chargeable_figures_exactly_where_they_were(self):
        """The tagged position keeps the 12.54 kW figure fixed at placement, and the
        room still publishes 0.00 kW chargeable because a PLANNED position never joins
        the roll-up.

        PRD: "Each rack's own `chargeable_kw` is computed first, individually, as its
        designed density multiplied by 1.045 and rounded half up to two decimal places.
        Only then are those per-rack figures summed."

        PRD: "`PLANNED` positions never contribute."

        Design: Corner/endpoints/rack_asset_tag_patch_writes_and_reads_back
        """
        ctx = self._planning_hall_with_a_tagged_position()
        patched = validate_success(
            api_client.patch_rack(ctx["rack"]["id"], {"asset_tag": "AT-NEW-61"}, FP),
            200,
        )
        assert patched["chargeable_kw"] == pytest.approx(12.54, abs=0.005), (
            "12.00 kW at the 1.045 overhead factor rounds half up to 12.54"
        )

        hall = read_hall(ctx["hall_id"])
        assert hall["chargeable_kw"] == pytest.approx(0.00, abs=0.005), (
            "the only position of the room is still PLANNED, so nothing rolls up"
        )
        assert hall["rack_total_count"] == 1
        assert hall["custody_fitout_count"] == 1
        assert hall["custody_ops_count"] == 0


class TestBuswayEnergiseAction:
    """The energise action is gated by the parent room's phase, not by anything on the
    run itself, and on success it recomputes the run's design ceiling."""

    def _planning_hall_with_an_installed_run(self):
        hall = create_hall("CX62", design_kw_capacity=400.00)
        pdu_a = create_pdu(hall["id"], "PDU-A1", "A", rated_kw=300.00)
        create_pdu(hall["id"], "PDU-B1", "B", rated_kw=300.00)
        pdu_a = commission_pdu(pdu_a["id"], 1.00)
        busway = create_busway(pdu_a["id"], "BW-A1", 400, 415, "N_PLUS_1")
        create_zone(hall["id"], "CA-1")
        return {"hall_id": hall["id"], "pdu_a": pdu_a, "busway": busway}

    def test_the_same_energise_call_is_refused_in_planning_and_accepted_in_fit_out(self):
        """Energising a run under a commissioned unit is refused while the room is still
        in PLANNING and leaves the run at INSTALLED; the identical call succeeds the
        moment the room reaches FIT_OUT.

        PRD: "Energising a run advances it `INSTALLED → ENERGIZED`. The hall must have
        left `PLANNING` (that is, it must be in `FIT_OUT`, `COMMISSIONING` or `LIVE`),
        or the request is refused with `ERR_HALL_PHASE_INVALID`"

        Design: Corner/endpoints/busway_energize_action_endpoint_is_phase_conditional
        """
        ctx = self._planning_hall_with_an_installed_run()
        assert ctx["pdu_a"]["status"] == "COMMISSIONED"
        assert ctx["busway"]["status"] == "INSTALLED"

        validate_error(
            api_client.energize_busway(ctx["busway"]["id"], EC),
            ApiErrorId.ERR_HALL_PHASE_INVALID.value,
            409,
        )
        assert read_busway(ctx["busway"]["id"])["status"] == "INSTALLED", (
            "the refused action left the run exactly where it was"
        )

        hall = advance_phase(ctx["hall_id"], "FIT_OUT")
        assert hall["status"] == "FIT_OUT"

        energised = validate_success(
            api_client.energize_busway(ctx["busway"]["id"], EC), 200
        )
        assert energised["status"] == "ENERGIZED", (
            "nothing about the run changed between the two calls, only the room's phase"
        )

    def test_energising_publishes_the_raw_capacity_and_the_design_ceiling(self):
        """A 400 A, 415 V, N_PLUS_1 run under a 300.00 kW unit publishes 273.136 kW raw
        and a 196.66 kW design ceiling, because the trunk figure binds below the
        240.000 kW upstream ceiling.

        PRD: "The run's **raw** three-phase capacity, published as `raw_kw`, is the
        current rating multiplied by the line-to-line voltage, multiplied by the
        three-phase constant 1.732, multiplied by the power factor 0.95, then divided by
        1000 to convert volt-amperes to kilowatts, and rounded to three decimal places."

        PRD: "A busway created while its hall is in `PLANNING` or `FIT_OUT` records
        `usable_variant` as `DESIGN`; one created while the hall is in `COMMISSIONING`
        or `LIVE` records it as `COMMISSIONED`."

        Design: Corner/endpoints/busway_energize_action_endpoint_is_phase_conditional
        """
        ctx = self._planning_hall_with_an_installed_run()
        advance_phase(ctx["hall_id"], "FIT_OUT")
        energised = validate_success(
            api_client.energize_busway(ctx["busway"]["id"], EC), 200
        )

        assert energised["raw_kw"] == pytest.approx(273.136, abs=0.0005), (
            "400 A at 415 V, times 1.732, times 0.95, over 1000"
        )
        assert energised["usable_kw"] == pytest.approx(196.66, abs=0.005), (
            "the unrounded trunk figure binds below the 240.000 kW upstream ceiling"
        )
        assert energised["usable_variant"] == "DESIGN", (
            "the run was created while the room was in PLANNING"
        )
        assert energised["committed_kw"] == pytest.approx(0.000, abs=0.0005)
        assert energised["feed_count"] == 0


class TestRackFeedJunctionWrite:
    """Reserving a feed is the junction write of the electrical graph: it links an
    existing position to an existing run, copies the side it lands on, and refuses a
    body reference that resolves to nothing without touching the ledger."""

    def _fit_out_hall_with_two_energised_runs(self):
        hall = create_hall("CX63", design_kw_capacity=400.00)
        pdu_a = create_pdu(hall["id"], "PDU-A1", "A", rated_kw=300.00)
        pdu_b = create_pdu(hall["id"], "PDU-B1", "B", rated_kw=300.00)
        commission_pdu(pdu_a["id"], 1.00)
        commission_pdu(pdu_b["id"], 1.00)
        bw_a = create_busway(pdu_a["id"], "BW-A1", 400, 415, "N_PLUS_1")
        bw_b = create_busway(pdu_b["id"], "BW-B1", 400, 415, "N_PLUS_1")
        zone = create_zone(hall["id"], "CA-1")
        rack = create_rack(hall["id"], zone["id"], "1", 1, design_kw=10.00)
        advance_phase(hall["id"], "FIT_OUT")
        energize_busway(bw_a["id"])
        energize_busway(bw_b["id"])
        return {
            "hall_id": hall["id"],
            "bw_a": bw_a,
            "bw_b": bw_b,
            "rack": rack,
        }

    def test_the_junction_write_copies_the_side_from_the_run_it_taps(self):
        """A 5.00 kW reservation on the B-side run comes back with feed_side B copied
        from the run, allocated_kw at 5.000, and both its foreign keys pointing at the
        rows the request named.

        PRD: "The `feed_side` recorded on the feed is copied from the named busway at
        creation, and the busway in turn inherited it from its upstream unit, so a feed's
        side is always the side of the electrical path that actually carries it."

        PRD: "What is stored is `allocated_kw`, the requested figure rounded to three
        decimal places, and that stored figure — not the request — is what all subsequent
        arithmetic uses."

        Design: Corner/endpoints/rack_feed_cross_reference_requires_both_endpoints_to_exist
        """
        ctx = self._fit_out_hall_with_two_energised_runs()
        feed = validate_success(
            api_client.create_rack_feed(
                {
                    "rack_id": ctx["rack"]["id"],
                    "busway_id": ctx["bw_b"]["id"],
                    "feed_side": "B",
                    "requested_kw": 5.00,
                    "breaker_amps": 32,
                },
                EC,
            ),
            201,
        )
        assert feed["feed_side"] == "B", (
            "the side comes off the run, which took it from its upstream unit"
        )
        assert feed["allocated_kw"] == pytest.approx(5.000, abs=0.0005)
        assert feed["status"] == "RESERVED"
        assert feed["rack_id"] == ctx["rack"]["id"]
        assert feed["busway_id"] == ctx["bw_b"]["id"]

        hall = read_hall(ctx["hall_id"])
        assert hall["committed_kw"] == pytest.approx(5.00, abs=0.005)
        assert hall["spare_kw"] == pytest.approx(370.00, abs=0.005), (
            "400.00 design less 5.00 committed less the 25.00 first-tier reserve"
        )
        bw_b = read_busway(ctx["bw_b"]["id"])
        assert bw_b["feed_count"] == 1
        assert bw_b["committed_kw"] == pytest.approx(5.000, abs=0.0005)
        bw_a = read_busway(ctx["bw_a"]["id"])
        assert bw_a["committed_kw"] == pytest.approx(0.000, abs=0.0005), (
            "the untapped run carries nothing"
        )
        assert bw_a["feed_count"] == 0

    def test_a_body_reference_to_no_run_returns_the_busway_404_and_books_nothing(self):
        """A second reservation naming a busway identifier that resolves to no row is
        refused with the busway 404 and leaves the ledger exactly where the first,
        successful reservation left it.

        PRD: "The same 404 vocabulary governs foreign keys supplied in a request body."

        PRD: "On the create operations for power distribution units, busway runs, racks,
        rack feeds, cooling units, containment zones, cages, security devices,
        commissioning packages, load bank tests, methods of procedure and release
        packets, every supplied reference — `hall_id`, `tenant_id`, `pdu_id`,
        `busway_id`, `rack_id`, `containment_zone_id`, `cage_id`, `package_id`, and the
        `supersedes_packet_id` linkage where a prior packet is implicated — must resolve
        to an existing row, and the matching `ERR_<PARENT>_NOT_FOUND` is returned when it
        does not."

        Design: Corner/endpoints/rack_feed_cross_reference_requires_both_endpoints_to_exist
        """
        ctx = self._fit_out_hall_with_two_energised_runs()
        reserve_feed(ctx["rack"]["id"], ctx["bw_b"]["id"], "B", 5.00, 32)

        validate_error(
            api_client.create_rack_feed(
                {
                    "rack_id": ctx["rack"]["id"],
                    "busway_id": NON_EXISTENT_UUID,
                    "feed_side": "A",
                    "requested_kw": 5.00,
                    "breaker_amps": 32,
                },
                EC,
            ),
            ApiErrorId.ERR_BUSWAY_NOT_FOUND.value,
            404,
        )

        hall = read_hall(ctx["hall_id"])
        assert hall["committed_kw"] == pytest.approx(5.00, abs=0.005), (
            "the refused reservation booked nothing against the room"
        )
        assert hall["spare_kw"] == pytest.approx(370.00, abs=0.005)
        rows, meta = validate_paginated(
            api_client.list_rack_feeds(EC, {"rack_id": ctx["rack"]["id"]})
        )
        assert meta["total_count"] == 1, "only the one good reservation exists"
        assert len(rows) == 1
        assert read_busway(ctx["bw_a"]["id"])["feed_count"] == 0


class TestCapacitySummaryProjection:
    """The reconciliation read is a pure projection of the room: it publishes the power
    ledger, both cooling variants, the custody partition and the postures at once."""

    def _fit_out_hall_with_one_powered_position(self):
        hall = create_hall("CX64", design_kw_capacity=400.00, cooling_redundancy="N")
        pdu_a = create_pdu(hall["id"], "PDU-A1", "A", rated_kw=300.00)
        create_pdu(hall["id"], "PDU-B1", "B", rated_kw=300.00)
        commission_pdu(pdu_a["id"], 1.00)
        bw_a = create_busway(pdu_a["id"], "BW-A1", 400, 415, "N_PLUS_1")
        zone = create_zone(hall["id"], "CA-1")
        unit = create_cooling_unit(
            hall["id"],
            "CU-1",
            rated_sensible_kw=200.00,
            design_airflow_cfm=22000,
            supply_delta_t_f=18.0,
        )
        rack = create_rack(
            hall["id"], zone["id"], "1", 1, design_kw=15.00, required_feed_count=1
        )
        advance_phase(hall["id"], "FIT_OUT")
        energize_busway(bw_a["id"])
        leakage_test(zone["id"], 5.00, 20.0)
        commission_cooling_unit(unit["id"], 22000)
        place_unit_in_service(unit["id"])
        reserve_feed(rack["id"], bw_a["id"], "A", 15.00, 60)
        install_rack(rack["id"], "AT-0064")
        power_on_rack(rack["id"])
        return {"hall_id": hall["id"], "rack": rack, "unit": unit, "zone": zone}

    def test_the_summary_publishes_every_derived_figure_of_the_room_at_once(self):
        """One 15.00 kW position powered on a single 60 A feed leaves the room at 15.00
        committed, 25.00 reserved, 360.00 spare, 15.68 chargeable and 12.75 of thermal
        load, with the airflow variant binding at 119.08 and a 106.33 margin.

        PRD: "`thermal_load_kw` is the sum of `design_kw` over the hall's racks whose
        status is `POWERED`, `AT_RISK` or `RELEASED`, multiplied by the diversity factor
        0.85 — no hall ever runs every cabinet at its designed density simultaneously —
        and rounded to two decimal places."

        PRD: "`cooling_capacity_kw` is the smaller of the two variants, and
        `cooling_margin_kw` is that gating capacity less `thermal_load_kw`, rounded to
        two decimal places."

        Design: Corner/endpoints/capacity_summary_computed_read_matches_hall_projection
        """
        ctx = self._fit_out_hall_with_one_powered_position()
        summary = validate_success(
            api_client.get_capacity_summary(ctx["hall_id"], OM), 200
        )

        assert summary["hall_id"] == ctx["hall_id"]
        assert summary["status"] == "FIT_OUT"
        assert summary["committed_kw"] == pytest.approx(15.00, abs=0.005)
        assert summary["commissioning_reserve_kw"] == pytest.approx(25.00, abs=0.005)
        assert summary["spare_kw"] == pytest.approx(360.00, abs=0.005)
        assert summary["chargeable_kw"] == pytest.approx(15.68, abs=0.005), (
            "15.00 kW at the 1.045 overhead factor rounds half up to 15.68"
        )
        assert summary["thermal_load_kw"] == pytest.approx(12.75, abs=0.005), (
            "15.00 kW of designed density at the 0.85 diversity factor"
        )
        assert summary["cooling_capacity_nameplate_kw"] == pytest.approx(
            200.00, abs=0.005
        ), "one in-service unit and an N stance withholds nothing"
        assert summary["cooling_capacity_airflow_kw"] == pytest.approx(
            119.08, abs=0.005
        ), "22000 cfm at five percent leakage over a 18.0 F delta-T"
        assert summary["cooling_capacity_kw"] == pytest.approx(119.08, abs=0.005), (
            "the airflow variant is the smaller of the two and therefore gates"
        )
        assert summary["cooling_margin_kw"] == pytest.approx(106.33, abs=0.005)
        assert summary["thermal_posture"] == "NOMINAL"
        assert summary["release_posture"] == "OPEN"
        assert summary["worst_leakage_pct"] == pytest.approx(5.00, abs=0.005)
        assert summary["rack_total_count"] == 1
        assert summary["custody_ops_count"] == 1
        assert summary["custody_fitout_count"] == 0
        assert summary["at_risk_rack_count"] == 0
        assert summary["open_mop_count"] == 0

    def test_every_shared_summary_field_equals_the_same_field_on_the_hall_read(self):
        """The reconciliation read invents nothing: each figure it publishes for the room
        is the very same value the plain hall read publishes under the same name.

        PRD: "Alongside the plain hall read, a computed capacity-summary read returns the
        whole reconciliation picture in one payload: `hall_id`, `status`,
        `design_kw_capacity`, `committed_kw`, `commissioning_reserve_kw`, `spare_kw`,
        `chargeable_kw`, `thermal_load_kw`, `cooling_capacity_nameplate_kw`,
        `cooling_capacity_airflow_kw`, `cooling_capacity_kw`, `cooling_margin_kw`,
        `thermal_posture`, `release_posture`, `rack_total_count`, `custody_ops_count`,
        `custody_fitout_count`, `at_risk_rack_count`, `open_mop_count`, and
        `worst_leakage_pct`"

        Design: Corner/endpoints/capacity_summary_computed_read_matches_hall_projection
        """
        ctx = self._fit_out_hall_with_one_powered_position()
        summary = read_capacity_summary(ctx["hall_id"])
        hall = read_hall(ctx["hall_id"])

        assert summary["hall_id"] == hall["id"]
        for field in (
            "status",
            "thermal_posture",
            "release_posture",
            "rack_total_count",
            "custody_ops_count",
            "custody_fitout_count",
            "at_risk_rack_count",
            "open_mop_count",
        ):
            assert summary[field] == hall[field], (
                f"the summary's {field} must be the hall's own {field}"
            )
        for field in (
            "design_kw_capacity",
            "committed_kw",
            "commissioning_reserve_kw",
            "spare_kw",
            "chargeable_kw",
            "thermal_load_kw",
            "cooling_capacity_nameplate_kw",
            "cooling_capacity_airflow_kw",
            "cooling_capacity_kw",
            "cooling_margin_kw",
        ):
            assert summary[field] == pytest.approx(hall[field], abs=0.005), (
                f"the summary's {field} must be the hall's own {field}"
            )


class TestRackListingFiltersAndPages:
    """The rack listing combines a parent filter with paging in one request, and the
    filter is applied before the window is cut."""

    def _two_halls_of_rack_positions(self):
        hall_a = create_hall("CX65", design_kw_capacity=400.00)
        zone_a = create_zone(hall_a["id"], "CA-1")
        racks_a = [
            create_rack(hall_a["id"], zone_a["id"], "1", col, design_kw=10.00)
            for col in (1, 2, 3)
        ]
        hall_b = create_hall("CX66", design_kw_capacity=400.00)
        zone_b = create_zone(hall_b["id"], "CA-2")
        rack_b = create_rack(hall_b["id"], zone_b["id"], "1", 1, design_kw=10.00)
        return {
            "hall_a_id": hall_a["id"],
            "hall_b_id": hall_b["id"],
            "racks_a": racks_a,
            "rack_b": rack_b,
        }

    def test_page_and_page_size_walk_the_filtered_window(self):
        """With three positions in one room, page 1 at page_size 2 returns two rows at
        offset 0 with more to come, and page 2 returns the last row at offset 2 with
        nothing beyond it; both pages report the unpaginated total of 3.

        PRD: "Two aliases are also accepted on every list endpoint for the convenience of
        page-oriented clients: `page_size` is a synonym for `limit` and obeys the same
        default, minimum and maximum, and `page` is a one-based page index whose effect is
        an offset of the page index minus one, multiplied by the effective page size."

        PRD: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count` and `has_more`, where `total_count` counts every row matching the
        request's filters before pagination is applied and `has_more` is true exactly when
        rows remain beyond the returned window."

        Design: Corner/endpoints/security_device_and_rack_listings_filter_and_paginate
        """
        ctx = self._two_halls_of_rack_positions()
        page_1, meta_1 = validate_paginated(
            api_client.list_racks(
                FP, {"hall_id": ctx["hall_a_id"], "page": 1, "page_size": 2}
            )
        )
        assert len(page_1) == 2, "page_size 2 cuts the window at two rows"
        assert meta_1["limit"] == 2, "page_size is a synonym for limit"
        assert meta_1["offset"] == 0, "page 1 is an offset of zero"
        assert meta_1["total_count"] == 3, (
            "the total counts every filtered row before the window is cut"
        )
        assert meta_1["has_more"] is True

        page_2, meta_2 = validate_paginated(
            api_client.list_racks(
                FP, {"hall_id": ctx["hall_a_id"], "page": 2, "page_size": 2}
            )
        )
        assert len(page_2) == 1, "one position remains beyond the first window"
        assert meta_2["limit"] == 2
        assert meta_2["offset"] == 2, "page 2 at page_size 2 skips two rows"
        assert meta_2["total_count"] == 3
        assert meta_2["has_more"] is False

    def test_the_hall_filter_excludes_the_neighbouring_room_from_both_pages(self):
        """Neither page shows the position that belongs to the other room, and the union
        of the two pages is exactly the three positions of the filtered room, in
        placement order and with no duplicates.

        PRD: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count` and `has_more`, where `total_count` counts every row matching the
        request's filters before pagination is applied and `has_more` is true exactly when
        rows remain beyond the returned window."

        PRD: "List results are ordered by `created_at` ascending."

        Design: Corner/endpoints/security_device_and_rack_listings_filter_and_paginate
        """
        ctx = self._two_halls_of_rack_positions()
        page_1, _ = validate_paginated(
            api_client.list_racks(
                FP, {"hall_id": ctx["hall_a_id"], "page": 1, "page_size": 2}
            )
        )
        page_2, _ = validate_paginated(
            api_client.list_racks(
                FP, {"hall_id": ctx["hall_a_id"], "page": 2, "page_size": 2}
            )
        )
        union = page_1 + page_2
        seen = [row["id"] for row in union]

        assert ctx["rack_b"]["id"] not in seen, (
            "the other room's position never matches the filter"
        )
        assert all(row["hall_id"] == ctx["hall_a_id"] for row in union)
        assert len(seen) == len(set(seen)), "no row is served on both pages"
        assert seen == [rack["id"] for rack in ctx["racks_a"]], (
            "the two windows join up in creation order"
        )
