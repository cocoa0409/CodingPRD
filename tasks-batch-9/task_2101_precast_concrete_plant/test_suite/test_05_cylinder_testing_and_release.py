"""Cylinder break testing, the two strength variants and the detensioning release."""

from test_helpers import (
    ApiErrorId,
    LBF_3000_PSI,
    LBF_3200_PSI,
    LBF_3400_PSI,
    LBF_3499_PSI,
    LBF_3500_PSI,
    LBF_3500_PSI_6IN,
    LBF_3550_PSI,
    LBF_3600_PSI,
    LBF_4100_PSI,
    LBF_5000_PSI,
    QC_TECHNICIAN_USER,
    TEST_USERS,
    add_bed_and_run,
    assert_cylinder_break,
    assert_cylinder_set,
    assert_decimal,
    assert_piece_dimensions_status,
    assert_project_counters,
    complete_curing_cycle,
    create_cylinder_set,
    cylinder_break_payload,
    list_cylinder_breaks,
    read_bed_run,
    read_cylinder_set,
    read_piece,
    read_project,
    record_break,
    set_clock,
    setup_production_line,
    validate_error,
    validate_paginated,
    validate_success,
)

QC = TEST_USERS["qc_technician_headers"]
ENGINEER = TEST_USERS["quality_engineer_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]


def _curing_run_with_release_set(specimen_count=2, piece_count=1, complete_cycle=True):
    """A CURING run whose pieces are on release-strength hold, carrying one
    RELEASE cylinder set and one curing cycle."""
    ctx = setup_production_line(
        stage="curing",
        piece_specs=[{} for _ in range(piece_count)],
        with_cylinder_set=True,
        cylinder_set_overrides={"specimen_count": specimen_count},
    )
    if complete_cycle:
        complete_curing_cycle(ctx["curing_cycle"]["id"])
    return ctx


def test_trimmed_average_discards_the_weak_cylinder_and_clears_the_threshold(api):
    """PRD §3.5: "An acceptance band is built around `raw_mean_psi` using the
    outlier tolerance of 10.0 percent: the lower bound is `raw_mean_psi`
    multiplied by 1 minus one tenth, and the upper bound is `raw_mean_psi`
    multiplied by 1 plus one tenth."
    PRD §3.5: "The two variants can disagree materially: three cylinders reading
    3600, 3550 and 2900 psi yield 3575 under `TRIMMED_AVERAGE`, because the 2900
    falls outside the band, but would yield 3350 under `SET_AVERAGE` — the same
    three cylinders either clear or fail a 3500 psi release threshold depending
    on which variant applies."
    PRD §3.5: "A break keeps `inclusion_status` `VALID` when its `computed_psi`
    is greater than or equal to the lower bound and less than or equal to the
    upper bound; otherwise its `inclusion_status` becomes `DISCARDED_OUTLIER`."

    Design: Difficulty/dual_variant_calc/trimmed_average_vs_set_average_release_strength
    """
    ctx = _curing_run_with_release_set(specimen_count=3)
    set_id = ctx["cylinder_set"]["id"]

    weak = record_break(set_id, 36443)
    strong = record_break(set_id, LBF_3600_PSI)
    middle = record_break(set_id, LBF_3550_PSI)

    assert weak["computed_psi"] == 2900
    assert strong["computed_psi"] == 3600
    assert middle["computed_psi"] == 3550

    cylinder_set = read_cylinder_set(set_id)
    assert_cylinder_set(cylinder_set)
    assert_decimal(cylinder_set["raw_mean_psi"], 3350.00, 2, "cylinder_set.raw_mean_psi")
    assert cylinder_set["valid_break_count"] == 2
    assert cylinder_set["qualified_strength_psi"] == 3575, (
        "the trimmed mean of 3600 and 3550 is 3575, not the untrimmed 3350"
    )
    assert cylinder_set["strength_variant"] == "TRIMMED_AVERAGE"
    assert cylinder_set["status"] == "RELEASE_MET"

    breaks = {b["id"]: b for b in list_cylinder_breaks(set_id)}
    assert breaks[weak["id"]]["inclusion_status"] == "DISCARDED_OUTLIER"
    assert breaks[strong["id"]]["inclusion_status"] == "VALID"
    assert breaks[middle["id"]]["inclusion_status"] == "VALID"
    assert read_bed_run(ctx["run"]["id"])["status"] == "RELEASE_READY"


def test_two_break_band_leaves_no_valid_specimen_before_the_third_break(api):
    """PRD §3.5: "`raw_mean_psi` is the arithmetic mean of `computed_psi` over
    *all* recorded breaks, regardless of inclusion, rounded half up to two
    decimal places."
    PRD §3.5: "If fewer than 2 breaks survive, the evidence set is too thin and
    `qualified_strength_psi` is null; otherwise `qualified_strength_psi` is the
    arithmetic mean of `computed_psi` over the included breaks, rounded half up
    to whole psi."
    PRD §3.5: "The set is `TESTING` when `valid_break_count` is below 2."

    Design: Difficulty/dual_variant_calc/trimmed_average_vs_set_average_release_strength
    """
    ctx = _curing_run_with_release_set(specimen_count=3)
    set_id = ctx["cylinder_set"]["id"]

    record_break(set_id, 36443)
    record_break(set_id, LBF_3600_PSI)

    cylinder_set = read_cylinder_set(set_id)
    assert_decimal(cylinder_set["raw_mean_psi"], 3250.00, 2, "cylinder_set.raw_mean_psi")
    assert cylinder_set["valid_break_count"] == 0, (
        "the +/-10 percent band around 3250.00 excludes both 2900 and 3600"
    )
    assert cylinder_set["qualified_strength_psi"] is None
    assert cylinder_set["status"] == "TESTING"
    assert read_bed_run(ctx["run"]["id"])["status"] == "CURING"


def test_break_psi_and_age_hours_use_the_six_inch_area_and_the_clock(api):
    """PRD §3.5: "`computed_psi` is the failure load divided by the cylinder's
    cross-sectional area and rounded half up to whole psi, where the area in
    square inches is pi times the square of half the `diameter_in`, taking pi as
    3.14159265358979 — which makes the area of a 4.00-inch cylinder
    12.566370614359172 square inches and that of a 6.00-inch cylinder
    28.274333882308138 square inches."
    PRD §3.5: "`age_hours` is the elapsed time from the set's `cast_at` to this
    break's `break_at`, expressed in hours by dividing the elapsed seconds by
    3600 and rounding half up to two decimal places."
    PRD §3.5: "The acting `X-User-ID` is written on the break as
    `recorded_by_user_id` and appended to the set's `recorded_by_user_ids` list
    when it is not already present, so that the list holds the distinct
    identifiers that have touched the set, in first-record order."

    Design: Corner/calculations/cylinder_break_psi_and_age_hours_use_six_inch_area_and_clock
    """
    ctx = setup_production_line(stage="scheduled", piece_specs=[])
    cylinder_set = create_cylinder_set(
        ctx["run"]["id"], purpose="INFORMATION", specimen_count=2, cured_with_member=False
    )
    set_clock("2026-08-04T00:00:00Z")

    response = api.record_cylinder_break(
        cylinder_set["id"], cylinder_break_payload(LBF_3500_PSI_6IN, diameter_in=6.00), QC
    )
    cylinder_break = validate_success(response, 201)

    assert_cylinder_break(cylinder_break)
    assert cylinder_break["computed_psi"] == 3500, (
        f"98960 lbf over the 6.00 in area is 3500 psi, got {cylinder_break['computed_psi']}"
    )
    assert_decimal(cylinder_break["age_hours"], 18.00, 2, "cylinder_break.age_hours")
    assert cylinder_break["break_at"].startswith("2026-08-04T00:00:00")
    assert cylinder_break["inclusion_status"] == "VALID"
    assert cylinder_break["recorded_by_user_id"] == QC_TECHNICIAN_USER

    reread = read_cylinder_set(cylinder_set["id"])
    assert reread["status"] == "TESTING"
    assert reread["valid_break_count"] == 1
    assert reread["qualified_strength_psi"] is None
    assert reread["recorded_by_user_ids"] == [QC_TECHNICIAN_USER]
    assert read_bed_run(ctx["run"]["id"])["status"] == "SCHEDULED", (
        "an INFORMATION set never drives the release cascade"
    )


def test_retest_loop_walks_met_not_met_and_back_to_met(api):
    """PRD §3.5: "A later, stronger cylinder can lift a set `RELEASE_NOT_MET →
    RELEASE_MET`, and a later, weaker one can push it `RELEASE_MET →
    RELEASE_NOT_MET`; that pair is the retest loop."
    PRD §3.5: "The set is `TESTING` when `valid_break_count` is below 2. It is
    `RELEASE_MET` when `qualified_strength_psi` is greater than or equal to the
    `required_release_psi` of the run's mix design. It is `RELEASE_NOT_MET`
    otherwise."
    PRD §3.5: "The first break always takes a set out of `CAST` into `TESTING`,
    and from there the set may move `TESTING → RELEASE_MET` or `TESTING →
    RELEASE_NOT_MET` as soon as two specimens survive."

    Design: Difficulty/non_linear_state_machine/cylinder_set_retest_loop_met_then_not_met_then_met
    """
    ctx = setup_production_line(stage="scheduled", piece_specs=[])
    cylinder_set = create_cylinder_set(
        ctx["run"]["id"], purpose="RELEASE", specimen_count=4, cured_with_member=False
    )
    set_id = cylinder_set["id"]

    record_break(set_id, LBF_3600_PSI)
    after_one = read_cylinder_set(set_id)
    assert after_one["status"] == "TESTING"
    assert after_one["qualified_strength_psi"] is None
    assert after_one["valid_break_count"] == 1

    record_break(set_id, LBF_3400_PSI)
    after_two = read_cylinder_set(set_id)
    assert after_two["status"] == "RELEASE_MET"
    assert_decimal(after_two["raw_mean_psi"], 3500.00, 2, "cylinder_set.raw_mean_psi")
    assert after_two["qualified_strength_psi"] == 3500

    record_break(set_id, LBF_3200_PSI)
    after_three = read_cylinder_set(set_id)
    assert after_three["status"] == "RELEASE_NOT_MET"
    assert_decimal(after_three["raw_mean_psi"], 3400.00, 2, "cylinder_set.raw_mean_psi")
    assert after_three["qualified_strength_psi"] == 3400
    assert after_three["valid_break_count"] == 3

    record_break(set_id, LBF_4100_PSI)
    after_four = read_cylinder_set(set_id)
    assert after_four["status"] == "RELEASE_MET"
    assert_decimal(after_four["raw_mean_psi"], 3575.00, 2, "cylinder_set.raw_mean_psi")
    assert after_four["qualified_strength_psi"] == 3500
    assert after_four["valid_break_count"] == 2
    assert read_bed_run(ctx["run"]["id"])["status"] == "SCHEDULED", (
        "the run was never cast, so no release cascade can interfere"
    )


def test_retest_loop_rewrites_inclusion_status_of_earlier_breaks(api):
    """PRD §3.5: "Every new break then triggers a **complete recomputation of the
    whole set from scratch**, including the `inclusion_status` of breaks recorded
    earlier."
    PRD §3.5: "The band is computed once, from `raw_mean_psi` taken over every
    break, and is never recomputed from the surviving subset — this is a single
    pass, not an iteration to convergence."
    PRD §3.5: "A set with a `specimen_count` of 3 or more is evaluated under the
    `TRIMMED_AVERAGE` variant."

    Design: Difficulty/non_linear_state_machine/cylinder_set_retest_loop_met_then_not_met_then_met
    """
    ctx = setup_production_line(stage="scheduled", piece_specs=[])
    cylinder_set = create_cylinder_set(
        ctx["run"]["id"], purpose="RELEASE", specimen_count=4, cured_with_member=False
    )
    set_id = cylinder_set["id"]

    high = record_break(set_id, LBF_3600_PSI)
    mid = record_break(set_id, LBF_3400_PSI)
    low = record_break(set_id, LBF_3200_PSI)
    assert read_cylinder_set(set_id)["valid_break_count"] == 3
    top = record_break(set_id, LBF_4100_PSI)

    breaks = {b["id"]: b for b in list_cylinder_breaks(set_id)}
    assert breaks[high["id"]]["inclusion_status"] == "VALID"
    assert breaks[mid["id"]]["inclusion_status"] == "VALID"
    assert breaks[low["id"]]["inclusion_status"] == "DISCARDED_OUTLIER", (
        "the 3200 psi break was valid after break 3 and is re-discarded after break 4"
    )
    assert breaks[top["id"]]["inclusion_status"] == "DISCARDED_OUTLIER"
    assert read_cylinder_set(set_id)["strength_variant"] == "TRIMMED_AVERAGE"


def test_qualified_strength_exactly_at_the_requirement_releases(api):
    """PRD §3.5: "It is `RELEASE_MET` when `qualified_strength_psi` is greater
    than or equal to the `required_release_psi` of the run's mix design."
    PRD §3.5: "If that set's `purpose` is `RELEASE`, the owning run's status is
    `CURING`, and every curing cycle of that run has reached `COMPLETED`, the run
    moves `CURING → RELEASE_READY` automatically — no client request names the
    run."
    PRD §3.5: "A set with a `specimen_count` of exactly 2 is evaluated under the
    `SET_AVERAGE` variant."

    Design: Difficulty/boundary_precision_check/release_strength_at_exactly_required_psi_passes
    """
    ctx = _curing_run_with_release_set(specimen_count=2)
    set_id = ctx["cylinder_set"]["id"]

    record_break(set_id, LBF_3500_PSI)
    record_break(set_id, LBF_3500_PSI)

    cylinder_set = read_cylinder_set(set_id)
    assert cylinder_set["qualified_strength_psi"] == 3500, (
        "3500 psi is exactly the mix's required_release_psi"
    )
    assert cylinder_set["status"] == "RELEASE_MET"
    assert cylinder_set["strength_variant"] == "SET_AVERAGE"
    assert read_bed_run(ctx["run"]["id"])["status"] == "RELEASE_READY"
    assert read_piece(ctx["pieces"][0]["id"])["qc_status"] == "CLEARED"


def test_qualified_strength_one_psi_short_does_not_release(api):
    """PRD §3.5: "It is `RELEASE_MET` when `qualified_strength_psi` is greater
    than or equal to the `required_release_psi` of the run's mix design. It is
    `RELEASE_NOT_MET` otherwise."
    PRD §3.5: "Whenever a set reaches `RELEASE_MET`, a second hop is attempted."

    Design: Difficulty/boundary_precision_check/release_strength_at_exactly_required_psi_passes
    """
    ctx = setup_production_line(stage="scheduled", piece_specs=[])
    _, run_b = add_bed_and_run(ctx, bed_code="B2")
    short_set = create_cylinder_set(run_b["id"], purpose="RELEASE", specimen_count=2)

    record_break(short_set["id"], LBF_3499_PSI)
    record_break(short_set["id"], LBF_3499_PSI)

    cylinder_set = read_cylinder_set(short_set["id"])
    assert cylinder_set["qualified_strength_psi"] == 3499, (
        "3499 psi is one psi short of the 3500 psi requirement"
    )
    assert cylinder_set["status"] == "RELEASE_NOT_MET"
    assert_decimal(cylinder_set["raw_mean_psi"], 3499.00, 2, "cylinder_set.raw_mean_psi")
    assert read_bed_run(run_b["id"])["status"] == "SCHEDULED"


def test_specimen_limit_rejects_a_third_break_on_a_two_specimen_set(api):
    """PRD §3.5: "The set's `recorded_break_count` must be strictly less than its
    `specimen_count`; a set with no unbroken specimen left is refused with
    `ERR_SPECIMEN_LIMIT_REACHED`."

    Design: Corner/validations/specimen_limit_reached_rejects_extra_break
    """
    ctx = setup_production_line(stage="scheduled", piece_specs=[])
    cylinder_set = create_cylinder_set(ctx["run"]["id"], purpose="RELEASE", specimen_count=2)
    record_break(cylinder_set["id"], LBF_3500_PSI)
    record_break(cylinder_set["id"], LBF_3500_PSI)

    response = api.record_cylinder_break(
        cylinder_set["id"], cylinder_break_payload(LBF_5000_PSI), QC
    )
    validate_error(response, ApiErrorId.ERR_SPECIMEN_LIMIT_REACHED.value, 422)

    reread = read_cylinder_set(cylinder_set["id"])
    assert reread["recorded_break_count"] == 2
    assert reread["qualified_strength_psi"] == 3500
    assert reread["status"] == "RELEASE_MET"
    _, meta = validate_paginated(api.list_cylinder_breaks(cylinder_set["id"], QC))
    assert meta["total_count"] == 2


def test_release_gates_fire_in_the_declared_order(api):
    """PRD §3.5: "The run must have a cylinder set whose `purpose` is `RELEASE`,
    or the request fails with `ERR_RELEASE_SET_MISSING`."
    PRD §3.5: "Every curing cycle on the run must have reached `COMPLETED`, and
    the run must have at least one — a run with no cycle at all, or with any
    cycle still `SCHEDULED` or `RUNNING`, fails with `ERR_CURING_NOT_COMPLETE`."
    PRD §3.5: "And `qualified_strength_psi` must be greater than or equal to the
    mix design's `required_release_psi`, or the request fails with
    `ERR_RELEASE_STRENGTH_NOT_MET`; a qualified strength exactly equal to the
    requirement passes."

    Design: Corner/state_machines/request_release_quality_gates_fire_in_declared_order
    """
    ctx = setup_production_line(stage="curing", with_cylinder_set=False)

    no_set = api.request_release(ctx["run"]["id"], ENGINEER)
    validate_error(no_set, ApiErrorId.ERR_RELEASE_SET_MISSING.value, 422)

    cylinder_set = create_cylinder_set(ctx["run"]["id"], purpose="RELEASE", specimen_count=2)
    still_curing = api.request_release(ctx["run"]["id"], ENGINEER)
    validate_error(still_curing, ApiErrorId.ERR_CURING_NOT_COMPLETE.value, 422)

    complete_curing_cycle(ctx["curing_cycle"]["id"])
    record_break(cylinder_set["id"], LBF_3499_PSI)
    record_break(cylinder_set["id"], LBF_3499_PSI)
    too_weak = api.request_release(ctx["run"]["id"], ENGINEER)
    validate_error(too_weak, ApiErrorId.ERR_RELEASE_STRENGTH_NOT_MET.value, 422)

    reread = read_cylinder_set(cylinder_set["id"])
    assert reread["qualified_strength_psi"] == 3499
    assert reread["status"] == "RELEASE_NOT_MET"
    run = read_bed_run(ctx["run"]["id"])
    assert run["status"] == "CURING"
    assert run["released_at"] is None
    assert_piece_dimensions_status(
        read_piece(ctx["pieces"][0]["id"]), "CAST", "HOLD", "AWAITING_RELEASE_STRENGTH"
    )
    assert_project_counters(
        read_project(ctx["project"]["id"]), held_piece_count=1, cleared_piece_count=0
    )


def test_release_refused_when_the_trim_leaves_no_valid_specimen(api):
    """PRD §3.5: "That release set's `qualified_strength_psi` must not be null, or
    the request fails with `ERR_NO_VALID_SPECIMENS`."
    PRD §3.5: "If fewer than 2 breaks survive, the evidence set is too thin and
    `qualified_strength_psi` is null; otherwise `qualified_strength_psi` is the
    arithmetic mean of `computed_psi` over the included breaks, rounded half up
    to whole psi."

    Design: Difficulty/boundary_precision_check/zero_valid_specimens_blocks_release_on_empty_evidence_set
    """
    ctx = _curing_run_with_release_set(specimen_count=3)
    set_id = ctx["cylinder_set"]["id"]
    record_break(set_id, LBF_5000_PSI)
    record_break(set_id, LBF_3000_PSI)
    record_break(set_id, LBF_3000_PSI)

    response = api.request_release(ctx["run"]["id"], ENGINEER)
    validate_error(response, ApiErrorId.ERR_NO_VALID_SPECIMENS.value, 422)

    cylinder_set = read_cylinder_set(set_id)
    assert cylinder_set["recorded_break_count"] == 3
    assert cylinder_set["valid_break_count"] == 0
    assert_decimal(cylinder_set["raw_mean_psi"], 3666.67, 2, "cylinder_set.raw_mean_psi")
    assert cylinder_set["qualified_strength_psi"] is None
    assert cylinder_set["status"] == "TESTING"
    for cylinder_break in list_cylinder_breaks(set_id):
        assert cylinder_break["inclusion_status"] == "DISCARDED_OUTLIER"


def test_empty_evidence_set_is_not_reported_as_release_strength_not_met(api):
    """PRD §3.5: "Past that gate, the quality conditions are checked in the fixed
    order of step 10 in §2.8."
    PRD §2.8: "**Quality and safety gates.** These guard four operations —
    casting a run, tensioning a run, requesting a release and adding a line to a
    shipment — and within this step the order is itself fixed:
    `ERR_NO_PIECES_ASSIGNED` first, then `ERR_ELONGATION_OUT_OF_TOLERANCE`, then
    `ERR_RELEASE_SET_MISSING`, then `ERR_CURING_NOT_COMPLETE`, then
    `ERR_NO_VALID_SPECIMENS`, then `ERR_RELEASE_STRENGTH_NOT_MET`, then
    `ERR_PIECE_QC_HOLD`."

    Design: Difficulty/boundary_precision_check/zero_valid_specimens_blocks_release_on_empty_evidence_set
    """
    ctx = _curing_run_with_release_set(specimen_count=3)
    set_id = ctx["cylinder_set"]["id"]
    record_break(set_id, LBF_5000_PSI)
    record_break(set_id, LBF_3000_PSI)
    record_break(set_id, LBF_3000_PSI)

    response = api.request_release(ctx["run"]["id"], ENGINEER)
    error = validate_error(response, ApiErrorId.ERR_NO_VALID_SPECIMENS.value, 422)

    assert error["error_id"] != ApiErrorId.ERR_RELEASE_STRENGTH_NOT_MET.value, (
        "a null qualified strength cannot be compared against the requirement"
    )
    assert read_bed_run(ctx["run"]["id"])["status"] == "CURING"
    assert_piece_dimensions_status(
        read_piece(ctx["pieces"][0]["id"]), "CAST", "HOLD", "AWAITING_RELEASE_STRENGTH"
    )


def test_release_ready_run_does_not_revert_when_a_later_break_drops_the_set(api):
    """PRD §3.5: "A set that later falls back out of `RELEASE_MET` does **not**
    drag the run back: a run that has already reached `RELEASE_READY` or
    `RELEASED` stays where it is."
    PRD §3.5: "Two further hops follow the run's move: every piece on the run
    whose `qc_status` is `HOLD` and whose `qc_hold_reason` is
    `AWAITING_RELEASE_STRENGTH` moves `HOLD → CLEARED` with `qc_hold_reason`
    cleared to null, and then every project owning such a piece recomputes both
    `held_piece_count` and `cleared_piece_count`."

    Design: Corner/state_machines/release_ready_run_does_not_revert_when_a_later_break_drops_the_set
    """
    ctx = _curing_run_with_release_set(specimen_count=3)
    set_id = ctx["cylinder_set"]["id"]

    record_break(set_id, LBF_3600_PSI)
    record_break(set_id, LBF_3400_PSI)
    assert read_cylinder_set(set_id)["qualified_strength_psi"] == 3500
    assert read_cylinder_set(set_id)["status"] == "RELEASE_MET"
    assert read_bed_run(ctx["run"]["id"])["status"] == "RELEASE_READY"
    assert read_piece(ctx["pieces"][0]["id"])["qc_status"] == "CLEARED"

    record_break(set_id, LBF_3200_PSI)

    dropped = read_cylinder_set(set_id)
    assert dropped["qualified_strength_psi"] == 3400
    assert dropped["status"] == "RELEASE_NOT_MET"
    assert read_bed_run(ctx["run"]["id"])["status"] == "RELEASE_READY", (
        "the cascade never runs backwards"
    )
    assert_piece_dimensions_status(read_piece(ctx["pieces"][0]["id"]), "CAST", "CLEARED", None)
    assert_project_counters(
        read_project(ctx["project"]["id"]), cleared_piece_count=1, held_piece_count=0
    )


def test_release_strength_cascade_clears_every_held_piece(api):
    """PRD §3.5: "Whenever a set reaches `RELEASE_MET`, a second hop is attempted.
    If that set's `purpose` is `RELEASE`, the owning run's status is `CURING`,
    and every curing cycle of that run has reached `COMPLETED`, the run moves
    `CURING → RELEASE_READY` automatically — no client request names the run."
    PRD §3.5: "Two further hops follow the run's move: every piece on the run
    whose `qc_status` is `HOLD` and whose `qc_hold_reason` is
    `AWAITING_RELEASE_STRENGTH` moves `HOLD → CLEARED` with `qc_hold_reason`
    cleared to null, and then every project owning such a piece recomputes both
    `held_piece_count` and `cleared_piece_count`."

    Design: Difficulty/transitive_cascade/release_strength_cascade_set_to_run_to_piece_to_project
    """
    ctx = _curing_run_with_release_set(specimen_count=2, piece_count=2)
    set_id = ctx["cylinder_set"]["id"]
    record_break(set_id, LBF_3500_PSI)
    assert read_cylinder_set(set_id)["qualified_strength_psi"] is None
    assert_project_counters(
        read_project(ctx["project"]["id"]), held_piece_count=2, cleared_piece_count=0
    )

    record_break(set_id, LBF_3500_PSI)

    cylinder_set = read_cylinder_set(set_id)
    assert cylinder_set["status"] == "RELEASE_MET"
    assert cylinder_set["qualified_strength_psi"] == 3500
    assert cylinder_set["strength_variant"] == "SET_AVERAGE"

    run = read_bed_run(ctx["run"]["id"])
    assert run["status"] == "RELEASE_READY"
    assert run["released_at"] is None, "RELEASE_READY is not RELEASED"

    for piece in ctx["pieces"]:
        assert_piece_dimensions_status(read_piece(piece["id"]), "CAST", "CLEARED", None)


def test_release_strength_cascade_recomputes_project_counters(api):
    """PRD §2.11: "`held_piece_count` counts the project's pieces whose
    `qc_status` is `HOLD`"
    PRD §2.11: "`cleared_piece_count` counts the project's pieces whose
    `qc_status` is either `CLEARED` or `REPAIRED`"
    PRD §3.5: "Two further hops follow the run's move: every piece on the run
    whose `qc_status` is `HOLD` and whose `qc_hold_reason` is
    `AWAITING_RELEASE_STRENGTH` moves `HOLD → CLEARED` with `qc_hold_reason`
    cleared to null, and then every project owning such a piece recomputes both
    `held_piece_count` and `cleared_piece_count`."

    Design: Difficulty/transitive_cascade/release_strength_cascade_set_to_run_to_piece_to_project
    """
    ctx = _curing_run_with_release_set(specimen_count=2, piece_count=2)
    set_id = ctx["cylinder_set"]["id"]

    record_break(set_id, LBF_3500_PSI)
    record_break(set_id, LBF_3500_PSI)

    assert_project_counters(
        read_project(ctx["project"]["id"]), cleared_piece_count=2, held_piece_count=0
    )
    assert read_piece(ctx["pieces"][0]["id"])["production_status"] == "CAST", (
        "the production dimension is untouched by the release cascade"
    )
