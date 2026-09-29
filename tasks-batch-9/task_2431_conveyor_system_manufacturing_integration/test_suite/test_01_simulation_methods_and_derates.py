"""Throughput simulation: method branching, class derates, flow propagation."""

from test_helpers import (
    DESIGN_ENGINEER,
    assert_segment,
    assert_simulation_run,
    make_branching_design,
    make_merge_sortation_design,
    read_segment,
    run_simulation,
    validate_paginated,
)


class TestSimulationMethodVariants:
    """The two methods diverge on one identical seven-segment topology."""

    def test_deterministic_run_uses_full_nameplate_capacity(self, api):
        """A deterministic run never multiplies by availability_pct.

        PRD §3.3: "If and only if the run's `method` is `DEGRADED_AVAILABILITY`, the
        working capacity is first multiplied by the segment's `availability_pct` and
        divided by 100, discarding any fractional remainder; under
        `DETERMINISTIC_STEADY_STATE` this substep is skipped entirely and
        `availability_pct` never enters the arithmetic at all, so every segment
        contributes its full nameplate capacity."

        Design: Difficulty/dual_variant_calc/simulation_method_variants_diverge_on_same_topology
        """
        design = make_branching_design(api)
        run = run_simulation(api, design["project"]["id"], "DETERMINISTIC_STEADY_STATE")

        assert_simulation_run(run)
        assert run["method"] == "DETERMINISTIC_STEADY_STATE"
        assert run["status"] == "COMPLETE"
        assert run["effective_throughput_cph"] == 1400
        assert run["bottleneck_segment_code"] == "IB-B"
        assert run["shortfall_cph"] == 0

    def test_degraded_run_derates_every_segment_and_reports_the_shortfall(self, api):
        """The conservative basis drops the same line below its promise.

        PRD §3.3: "Finally, `shortfall_cph` records how far the line falls short of
        its promise: the project's `required_throughput_cph` minus
        `effective_throughput_cph`, floored at 0 so that a compliant line reports 0
        rather than a negative figure."

        Design: Difficulty/dual_variant_calc/simulation_method_variants_diverge_on_same_topology
        """
        design = make_branching_design(api)
        run = run_simulation(api, design["project"]["id"], "DEGRADED_AVAILABILITY")

        assert run["method"] == "DEGRADED_AVAILABILITY"
        assert run["status"] == "COMPLETE"
        assert run["effective_throughput_cph"] == 1260
        assert run["shortfall_cph"] == 40
        assert run["bottleneck_segment_code"] == "IB-B"
        assert run["bottleneck_availability_pct"] == 90

    def test_runs_of_different_methods_both_stay_complete(self, api):
        """Supersession is scoped to one method, so the two runs coexist.

        PRD §3.3: "A completed run also supersedes its predecessor of the same
        `method`: the prior run of that project and that `method` whose `status` was
        `COMPLETE` becomes `SUPERSEDED`, and its own `version` increments by 1."

        Design: Difficulty/dual_variant_calc/simulation_method_variants_diverge_on_same_topology
        """
        design = make_branching_design(api)
        project_id = design["project"]["id"]
        deterministic = run_simulation(api, project_id, "DETERMINISTIC_STEADY_STATE")
        degraded = run_simulation(api, project_id, "DEGRADED_AVAILABILITY")

        runs, meta = validate_paginated(api.list_simulation_runs(project_id, DESIGN_ENGINEER))
        assert meta["total_count"] == 2
        by_id = {run["id"]: run for run in runs}
        assert by_id[deterministic["id"]]["status"] == "COMPLETE"
        assert by_id[degraded["id"]]["status"] == "COMPLETE"

    def test_segment_derates_reflect_the_most_recent_run(self, api):
        """A degraded run overwrites the derated capacities a deterministic run wrote.

        PRD §3.3: "Because the run refreshes `flow_share_bps` and
        `derated_capacity_cph` on every segment of the project, those two fields
        always reflect the method of the project's most recent run — a deterministic
        run overwrites the derated capacities a degraded run had written, and vice
        versa."

        Design: Difficulty/dual_variant_calc/simulation_method_variants_diverge_on_same_topology
        """
        design = make_branching_design(api)
        project_id = design["project"]["id"]
        segments = design["segments"]

        run_simulation(api, project_id, "DETERMINISTIC_STEADY_STATE")
        assert read_segment(api, segments["MG-C"]["id"])["derated_capacity_cph"] == 1920
        assert read_segment(api, segments["SX-D"]["id"])["derated_capacity_cph"] == 1746

        run_simulation(api, project_id, "DEGRADED_AVAILABILITY")
        merge = read_segment(api, segments["MG-C"]["id"])
        sortation = read_segment(api, segments["SX-D"]["id"])
        assert merge["derated_capacity_cph"] == 1843
        assert sortation["derated_capacity_cph"] == 1606
        assert read_segment(api, segments["IB-B"]["id"])["flow_share_bps"] == 2000
        assert read_segment(api, segments["OT-E"]["id"])["flow_share_bps"] == 5000


class TestMergeAndSortationDerateNesting:
    """Three feeders into one merge, then a two-way sortation."""

    def test_link_counts_track_the_graph_as_edges_are_added(self, api):
        """Each new edge bumps the upstream fan-out and the downstream fan-in.

        PRD §3.2: "Creating a link increments the upstream segment's
        `outbound_link_count` by 1 and the downstream segment's `inbound_link_count`
        by 1."

        Design: Difficulty/combinatorial_formula/merge_and_sortation_derate_nesting_order_pinned
        """
        design = make_merge_sortation_design(api)
        merge = read_segment(api, design["segments"]["MG-X"]["id"])
        sortation = read_segment(api, design["segments"]["SX-Y"]["id"])

        assert_segment(merge)
        assert merge["inbound_link_count"] == 3
        assert merge["outbound_link_count"] == 1
        assert sortation["inbound_link_count"] == 1
        assert sortation["outbound_link_count"] == 2

    def test_two_way_sortation_takes_no_class_derate(self, api):
        """With only two outbound links the divert loss does not apply.

        PRD §3.3: "Segments of class `BELT` and `ROLLER`, and `SORTATION` segments
        with fewer than 3 outbound links, take no class derate whatsoever."

        Design: Difficulty/combinatorial_formula/merge_and_sortation_derate_nesting_order_pinned
        """
        design = make_merge_sortation_design(api)
        run = run_simulation(api, design["project"]["id"], "DETERMINISTIC_STEADY_STATE")

        assert run["effective_throughput_cph"] == 1600
        assert run["bottleneck_segment_code"] == "SX-Y"
        assert run["shortfall_cph"] == 0
        assert read_segment(api, design["segments"]["SX-Y"]["id"])["derated_capacity_cph"] == 1600

    def test_merge_derate_is_applied_after_the_availability_derate(self, api):
        """Availability first, then the merge's per-extra-input loss.

        PRD §3.3: "For a `MERGE` segment, the working capacity is multiplied by the
        quantity 10000 minus 400 multiplied by one less than the segment's
        `inbound_link_count`, then divided by 10000 with the remainder discarded — a
        merge loses 400 basis points, four hundredths of the whole, for every input
        beyond its first."

        Design: Difficulty/combinatorial_formula/merge_and_sortation_derate_nesting_order_pinned
        """
        design = make_merge_sortation_design(api)
        run = run_simulation(api, design["project"]["id"], "DEGRADED_AVAILABILITY")

        merge = read_segment(api, design["segments"]["MG-X"]["id"])
        sortation = read_segment(api, design["segments"]["SX-Y"]["id"])
        assert merge["derated_capacity_cph"] == 1433
        assert sortation["derated_capacity_cph"] == 1520
        assert run["effective_throughput_cph"] == 1433
        assert run["bottleneck_segment_code"] == "MG-X"

    def test_flow_shares_merge_then_split_across_the_graph(self, api):
        """Three source shares converge to the whole, then divide on the sortation.

        PRD §3.3: "Every other segment's `flow_share_bps` is the sum, taken over each
        of its inbound links, of the upstream segment's `flow_share_bps` multiplied by
        that link's `split_share_bps` and then divided by 10000 with any fractional
        remainder discarded."

        Design: Difficulty/combinatorial_formula/merge_and_sortation_derate_nesting_order_pinned
        """
        design = make_merge_sortation_design(api)
        run_simulation(api, design["project"]["id"], "DEGRADED_AVAILABILITY")
        segments = design["segments"]

        assert read_segment(api, segments["SR-1"]["id"])["flow_share_bps"] == 4000
        assert read_segment(api, segments["MG-X"]["id"])["flow_share_bps"] == 10000
        assert read_segment(api, segments["SX-Y"]["id"])["flow_share_bps"] == 10000
        assert read_segment(api, segments["OT-1"]["id"])["flow_share_bps"] == 6000
        assert read_segment(api, segments["OT-2"]["id"])["flow_share_bps"] == 4000
