"""Stripping the bed and closing the run's books."""

from test_helpers import (
    ENERGY_COST_MODELED_CENTS,
    JACK_FORCE_C40_KIPS,
    TEST_USERS,
    assert_cost_allocation_is_exact,
    assert_decimal,
    assert_project_counters,
    assert_whole_cents,
    decide_disposition,
    open_ncr,
    read_bed_run,
    read_casting_bed,
    read_piece,
    read_project,
    setup_production_line,
    validate_success,
)

SUPERVISOR = TEST_USERS["production_supervisor_headers"]


def test_overhead_tier_is_keyed_on_the_direct_subtotal(api):
    """PRD §3.6: "`direct_subtotal_cents` is the sum of those four figures —
    concrete, strand, energy and form setup. The overhead tier is then keyed on
    `direct_subtotal_cents`, the pre-overhead figure, and deliberately never on
    the total, which would be circular."
    PRD §3.6: "`overhead_rate_pct` is 22.0 when `direct_subtotal_cents` is below
    500000 cents, 18.0 when it is at least 500000 cents but below 1000000 cents,
    and 14.0 when it is at least 1000000 cents."
    PRD §3.6: "`overhead_cents` is `direct_subtotal_cents` multiplied by
    `overhead_rate_pct` divided by 100, rounded half up to whole cents.
    `total_cost_cents` is `direct_subtotal_cents` plus `overhead_cents`."

    Design: Difficulty/combinatorial_formula/overhead_tier_keyed_on_direct_subtotal_not_total
    """
    ctx = setup_production_line(stage="released", piece_specs=[{}, {}, {}])

    stripped = validate_success(api.strip_bed_run(ctx["run"]["id"], SUPERVISOR))

    assert_whole_cents(stripped["concrete_cost_cents"], 543750, "bed_run.concrete_cost_cents")
    assert_whole_cents(stripped["strand_cost_cents"], 111360, "bed_run.strand_cost_cents")
    assert_whole_cents(
        stripped["energy_cost_cents"], ENERGY_COST_MODELED_CENTS, "bed_run.energy_cost_cents"
    )
    assert_whole_cents(stripped["form_setup_cents"], 180000, "bed_run.form_setup_cents")
    assert_whole_cents(stripped["direct_subtotal_cents"], 848636, "bed_run.direct_subtotal_cents")
    assert_decimal(stripped["overhead_rate_pct"], 18.0, 1, "bed_run.overhead_rate_pct")
    assert_whole_cents(stripped["overhead_cents"], 152754, "bed_run.overhead_cents")
    assert_whole_cents(stripped["total_cost_cents"], 1001390, "bed_run.total_cost_cents")
    assert stripped["total_cost_cents"] != 967445, (
        "967445 cents is what keying the tier on the total would have produced"
    )
    assert stripped["status"] == "STRIPPED"


def test_run_total_is_split_across_pieces_to_the_cent(api):
    """PRD §3.6: "The base share is the total divided by the number of those
    pieces, taken as a floor rather than a round. The remainder is the total
    minus the base share multiplied by the piece count, and the whole remainder
    is given to the first piece in that ordering: that piece receives the base
    share plus the remainder, and every other piece receives exactly the base
    share. Each piece's figure is written to its `allocated_cost_cents`."
    PRD §3.6: "The pieces that share the cost are those on the run whose
    `production_status` is `CAST`, taken in order of `erection_sequence_no`
    ascending and, where two share a sequence number, `created_at` ascending."
    PRD §2.11: "`committed_cost_cents` sums `allocated_cost_cents` over the
    project's pieces for which that value has been written"

    Design: Difficulty/combinatorial_formula/overhead_tier_keyed_on_direct_subtotal_not_total
    """
    ctx = setup_production_line(stage="released", piece_specs=[{}, {}, {}])

    validate_success(api.strip_bed_run(ctx["run"]["id"], SUPERVISOR))

    pieces = [read_piece(p["id"]) for p in ctx["pieces"]]
    assert_whole_cents(pieces[0]["allocated_cost_cents"], 333798, "piece.allocated_cost_cents")
    assert_whole_cents(pieces[1]["allocated_cost_cents"], 333796, "piece.allocated_cost_cents")
    assert_whole_cents(pieces[2]["allocated_cost_cents"], 333796, "piece.allocated_cost_cents")
    assert_cost_allocation_is_exact(pieces, 1001390)
    for piece in pieces:
        assert piece["production_status"] == "STRIPPED"
    assert_project_counters(read_project(ctx["project"]["id"]), committed_cost_cents=1001390)


def test_scrapped_pieces_pay_nothing_and_leave_the_run_volume(api):
    """PRD §3.6: "First the run's poured volume is taken as the sum of
    `concrete_volume_cy` over the pieces on the run whose `production_status` is
    `CAST` at the moment of the strip call, rounded half up to two decimal
    places; scrapped pieces are excluded from the run's volume and pay nothing."
    PRD §3.6: "Four further effects complete the strip. Those same `CAST` pieces
    move `production_status` `CAST → STRIPPED`. Every project owning one of them
    recomputes `committed_cost_cents`. The bed's `committed_strand_force_kips`
    decreases by this run's `computed_jacking_force_kips`, releasing the abutment
    capacity for the next pour. And the bed moves `OCCUPIED → AVAILABLE` while
    its `cumulative_cycle_count` increases by 1 — the count of complete casting
    cycles that bed has turned."

    Design: Corner/calculations/cost_allocation_excludes_scrapped_pieces
    """
    ctx = setup_production_line(stage="released", piece_specs=[{}, {}])
    survivor, condemned = ctx["pieces"]
    ncr = open_ncr(
        condemned["id"],
        defect_type="CRACK",
        severity="STRUCTURAL",
        description="Shear crack across the web",
    )
    decide_disposition(ncr["id"], "REJECT_RECAST")

    stripped = validate_success(api.strip_bed_run(ctx["run"]["id"], SUPERVISOR))

    assert_whole_cents(stripped["concrete_cost_cents"], 181250, "bed_run.concrete_cost_cents")
    assert_whole_cents(stripped["strand_cost_cents"], 111360, "bed_run.strand_cost_cents")
    assert_whole_cents(
        stripped["energy_cost_cents"], ENERGY_COST_MODELED_CENTS, "bed_run.energy_cost_cents"
    )
    assert_whole_cents(stripped["form_setup_cents"], 180000, "bed_run.form_setup_cents")
    assert_whole_cents(stripped["direct_subtotal_cents"], 486136, "bed_run.direct_subtotal_cents")
    assert_decimal(stripped["overhead_rate_pct"], 22.0, 1, "bed_run.overhead_rate_pct")
    assert_whole_cents(stripped["overhead_cents"], 106950, "bed_run.overhead_cents")
    assert_whole_cents(stripped["total_cost_cents"], 593086, "bed_run.total_cost_cents")

    kept = read_piece(survivor["id"])
    scrapped = read_piece(condemned["id"])
    assert_whole_cents(kept["allocated_cost_cents"], 593086, "piece.allocated_cost_cents")
    assert kept["production_status"] == "STRIPPED"
    assert scrapped["allocated_cost_cents"] is None, "a scrapped piece pays nothing"
    assert scrapped["production_status"] == "SCRAPPED"

    project = read_project(ctx["project"]["id"])
    assert_project_counters(project, committed_cost_cents=593086, scrapped_piece_count=1)

    bed = read_casting_bed(ctx["bed"]["id"])
    assert bed["cumulative_cycle_count"] == 1
    assert bed["committed_strand_force_kips"] == 0
    assert bed["status"] == "AVAILABLE"
    assert read_bed_run(ctx["run"]["id"])["computed_jacking_force_kips"] == JACK_FORCE_C40_KIPS
