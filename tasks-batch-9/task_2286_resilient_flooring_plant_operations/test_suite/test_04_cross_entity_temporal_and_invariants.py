"""Cross-entity gates, interval geometries and exact ledger compensation.

These tests exercise the setup, scheduling and abort rules of PRD §3.6, the
lazy grant expiry of PRD §3.2, the QC-disposition and stock-hold rules of PRD
§3.7, allocation creation, filling and release in PRD §3.8, and the
compensation discipline that PRD §2.9 places on the licensed-volume, royalty
and finished-stock ledgers.
"""

from test_helpers import (
    CLOCK_BOOT_UTC,
    PLANT_ADMIN,
    PRODUCTION_PLANNER,
    QA_TECHNICIAN,
    QA_TECHNICIAN_B,
    TECHNICAL_DIRECTOR,
    ApiErrorId,
    allocation_payload,
    batch_of_run,
    begin_testing,
    build_approved_formulation,
    build_certified_sku,
    build_provisional_sku,
    build_sku,
    build_stock_batch,
    commercial_status_payload,
    create_allocation,
    create_distributor,
    create_license,
    create_panel,
    create_press_line,
    create_print_film,
    create_run,
    create_sku,
    distributor_headers,
    fill_payload,
    hold_status_payload,
    production_run_payload,
    record_result,
    run_abort_payload,
    run_to_completion,
    set_clock,
    set_qc_disposition,
    start_panel,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Local setup walks. Each one drives PRD-declared endpoints only, through the
# validating composite helpers, so a broken setup fails loudly.
# ---------------------------------------------------------------------------


def _sku_a_in_testing_with_planned_run(api):
    """SKU-A in certification TESTING, PL-1 AVAILABLE, RUN-A1 PLANNED."""
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_sku(api)
    begin_testing(api, built["sku"]["id"])
    line = create_press_line(api)
    run = create_run(api, built["sku"]["id"], line["id"])
    return built, line, run


def _quarantined_batch_of_certified_sku(api):
    """CERTIFIED SKU-A, RUN-A1 COMPLETED at 1200.00 sqm, quarantined by qa-001."""
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_certified_sku(api)
    line = create_press_line(api)
    run = run_to_completion(api, built["sku"]["id"], line["id"], 1200.00)
    disposition = set_qc_disposition(api, run["id"], "QUARANTINED", QA_TECHNICIAN)
    batch = batch_of_run(api, run["id"])
    return built, run, disposition, batch


def _provisional_sku_with_released_stock(api):
    """PROVISIONAL SKU-A with one IN_STOCK batch of 1200.00 sqm and a distributor."""
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_provisional_sku(api)
    line = create_press_line(api)
    run = run_to_completion(api, built["sku"]["id"], line["id"], 1200.00)
    set_qc_disposition(api, run["id"], "RELEASED", QA_TECHNICIAN)
    batch = batch_of_run(api, run["id"])
    distributor = create_distributor(api)
    return built, run, batch, distributor


def _sku_c_on_pl2(api):
    """SKU-C on a two-roll-set film, plus PL-2 with changeover_minutes 0."""
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_approved_formulation(api)
    license_row = create_license(api)
    film = create_print_film(
        api,
        license_row["id"],
        design_code="PF-OAK-1800",
        pattern_repeat_mm_length=1800.0,
        pattern_repeat_mm_width=300.0,
        registration_tolerance_mm=0.30,
        emboss_plate_code="EMB-OAK-B",
        emboss_alignment_offset_mm=0.12,
        master_roll_sets=2,
    )
    sku = create_sku(api, built["formulation"]["id"], film["id"], sku_code="SKU-C")
    begin_testing(api, sku["id"])
    line = create_press_line(
        api,
        line_code="PL-2",
        line_type="CALENDER",
        min_thickness_mm=1.5,
        max_thickness_mm=8.0,
        changeover_minutes=0,
        curl_control_index=95,
    )
    return license_row, film, sku, line


def _sku_d_on_three_lines(api):
    """SKU-D on a single-roll-set film, plus three lines with changeover 0."""
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_approved_formulation(api)
    license_row = create_license(api)
    film = create_print_film(
        api,
        license_row["id"],
        design_code="PF-OAK-900",
        pattern_repeat_mm_length=900.0,
        pattern_repeat_mm_width=200.0,
        registration_tolerance_mm=0.20,
        emboss_plate_code="EMB-OAK-C",
        emboss_alignment_offset_mm=0.08,
        master_roll_sets=1,
    )
    sku = create_sku(api, built["formulation"]["id"], film["id"], sku_code="SKU-D")
    begin_testing(api, sku["id"])
    lines = {}
    for code, line_type in (
        ("PL-A", "CALENDER"),
        ("PL-B", "CALENDER"),
        ("PL-C", "MULTI_DAY_PRESS"),
    ):
        lines[code] = create_press_line(
            api,
            line_code=code,
            line_type=line_type,
            min_thickness_mm=1.5,
            max_thickness_mm=8.0,
            changeover_minutes=0,
            curl_control_index=90,
        )
    return license_row, film, sku, lines


def _sku_e_on_expiring_licence(api):
    """SKU-E under LIC-EXP, whose term ends at 2026-09-01T00:00:00Z."""
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_approved_formulation(api)
    line = create_press_line(api)
    license_row = create_license(
        api,
        license_code="LIC-EXP",
        licensor_name="Terrazzo Studios",
        license_type="EXCLUSIVE",
        royalty_rate_bps=500,
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2026-09-01T00:00:00Z",
        term_volume_cap_sqm=2000.00,
        territory_codes=["US"],
    )
    film = create_print_film(
        api,
        license_row["id"],
        design_code="PF-EXP",
        pattern_repeat_mm_length=1200.0,
        pattern_repeat_mm_width=180.0,
        registration_tolerance_mm=0.25,
        emboss_plate_code="EMB-EXP-A",
        emboss_alignment_offset_mm=0.10,
        master_roll_sets=2,
    )
    sku = create_sku(api, built["formulation"]["id"], film["id"], sku_code="SKU-E")
    begin_testing(api, sku["id"])
    return license_row, film, sku, line


def _certified_sku_a_on_two_lines(api):
    """CERTIFIED SKU-A with two AVAILABLE lines and an untouched grant ledger."""
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_certified_sku(api)
    pl1 = create_press_line(api)
    pl2 = create_press_line(
        api,
        line_code="PL-2",
        line_type="CALENDER",
        min_thickness_mm=1.5,
        max_thickness_mm=8.0,
        changeover_minutes=0,
        curl_control_index=95,
    )
    return built, pl1, pl2


def _released_run_of_certified_sku(api):
    """RUN-A1 COMPLETED at 1200.00 sqm with qc_disposition RELEASED."""
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_certified_sku(api)
    line = create_press_line(api)
    run = run_to_completion(api, built["sku"]["id"], line["id"], 1200.00)
    set_qc_disposition(api, run["id"], "RELEASED", QA_TECHNICIAN)
    batch = batch_of_run(api, run["id"])
    return built, run, batch


# ---------------------------------------------------------------------------
# Cross-entity state dependency.
# ---------------------------------------------------------------------------


def test_run_setup_refused_while_sku_certification_is_only_testing(api):
    """Setup is refused for a PLANNED run whose SKU has only reached TESTING.

    "The SKU must be producible: its `certification_status` must be `TESTING`,
    `PROVISIONAL` or `CERTIFIED` and its `commercial_status` must not be
    `DISCONTINUED`, failing which the request is `ERR_SKU_NOT_PRODUCIBLE`."
    "It requires the SKU's `certification_status` to be `PROVISIONAL` or
    `CERTIFIED` and its `commercial_status` to be `DEVELOPMENT` or `RELEASED` —
    the admission window narrows between scheduling and setup, and a SKU that
    has slipped outside it is `ERR_SKU_NOT_PRODUCIBLE`."
    "And the logical clock must have reached `planned_start_utc` minus 120
    minutes: setup may not begin more than two hours before the planned start,
    and an early attempt is `ERR_SETUP_TOO_EARLY` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/run_setup_blocked_until_sku_certification_reaches_provisional
    """
    built, _line, run = _sku_a_in_testing_with_planned_run(api)

    # The scheduling admission set is wider than the setup admission set: the
    # run itself was created while the SKU was only TESTING.
    assert run["run_status"] == "PLANNED"
    sku = validate_success(api.get_product_sku(built["sku"]["id"], PLANT_ADMIN))
    assert sku["certification_status"] == "TESTING"

    # The clock sits at 2026-08-01T00:00:00Z, later than 01:00 less 120
    # minutes, so the lead-window rule cannot be the reason for the refusal.
    resp = api.setup_production_run(run["id"], PRODUCTION_PLANNER)
    validate_error(resp, ApiErrorId.SKU_NOT_PRODUCIBLE.value)

    after = validate_success(api.get_production_run(run["id"], PRODUCTION_PLANNER))
    assert after["run_status"] == "PLANNED"


def test_run_setup_admitted_once_a_passed_panel_lifts_the_sku_to_provisional(api):
    """The same untouched run sets up once a PASSED panel moves the SKU onward.

    "Otherwise, if coverage is complete and every outcome at that attempt is
    `PASS`, the panel moves `IN_TEST → PASSED`."
    "A panel that reaches `PASSED` whose coverage includes both
    `RESIDUAL_INDENTATION` and `DIMENSIONAL_STABILITY_HEAT` moves the SKU's
    certification `TESTING → PROVISIONAL`."
    "Setup takes the run `PLANNED → SETUP` and is where the changeover
    allowance is persisted."
    "If no such predecessor exists the required gap is zero minutes."
    "The gap computation above is re-evaluated against the current predecessor
    and stored in `changeover_minutes_applied`."

    Design: Difficulty/cross_entity_state_dependency/run_setup_blocked_until_sku_certification_reaches_provisional
    """
    built, _line, run = _sku_a_in_testing_with_planned_run(api)
    sku_id = built["sku"]["id"]

    blocked = api.setup_production_run(run["id"], PRODUCTION_PLANNER)
    validate_error(blocked, ApiErrorId.SKU_NOT_PRODUCIBLE.value)

    panel = create_panel(api, sku_id, "TP-X1")
    start_panel(api, panel["id"])
    record_result(api, panel["id"], "RESIDUAL_INDENTATION", 0.08)
    record_result(api, panel["id"], "DIMENSIONAL_STABILITY_HEAT", 0.12)

    panel_after = validate_success(api.get_test_panel(panel["id"], QA_TECHNICIAN))
    assert panel_after["status"] == "PASSED"
    sku_after = validate_success(api.get_product_sku(sku_id, PLANT_ADMIN))
    assert sku_after["certification_status"] == "PROVISIONAL"

    # Nothing about the run changed; only a neighbouring aggregate advanced.
    setup = validate_success(api.setup_production_run(run["id"], PRODUCTION_PLANNER))
    assert setup["run_status"] == "SETUP"
    assert setup["changeover_minutes_applied"] == 0


def test_held_batch_release_refused_for_the_technician_who_quarantined_it(api):
    """The quarantining technician is refused before the cross-entity gate runs.

    "`PENDING → QUARANTINED` moves the batch `IN_PRODUCTION → HELD` with
    `hold_reason` `QC_QUARANTINE` and `held_by_user_id` set to the acting
    technician — which, by §2.8, means someone else must later release it."
    "Releasing a batch hold is refused when `X-User-ID` equals the batch's
    `held_by_user_id`."
    "All four return `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and all four are
    evaluated in band 9 — after concurrency and before any cross-entity state
    check."
    "When a run completes with positive output, the batch is minted with a
    `batch_code` formed as the producing run's `run_code` followed by the suffix
    `-B1`, a `production_run_id` pointing at that run, a `sku_id` denormalised
    from it for stock selection, a `quantity_sqm` equal to the run's
    `actual_quantity_sqm` that never changes thereafter, an
    `available_quantity_sqm` of 0, and a `wear_layer_measured_mil` copied from
    the run's measurement — the reading that will later serve as warranty defect
    evidence."

    Design: Difficulty/cross_entity_state_dependency/batch_hold_release_gated_by_producing_run_qc_disposition
    """
    _built, _run, disposition, batch = _quarantined_batch_of_certified_sku(api)

    assert disposition["qc_disposition"] == "QUARANTINED"
    assert batch["status"] == "HELD"
    assert batch["hold_reason"] == "QC_QUARANTINE"
    assert batch["held_by_user_id"] == "qa-001"
    assert batch["available_quantity_sqm"] == 0.00

    resp = api.set_batch_hold_status(
        batch["id"], hold_status_payload("RELEASE_HOLD"), QA_TECHNICIAN
    )
    validate_error(resp, ApiErrorId.SEGREGATION_OF_DUTIES.value)

    after = validate_success(api.get_batch(batch["id"], QA_TECHNICIAN))
    assert after["status"] == "HELD"
    assert after["available_quantity_sqm"] == 0.00


def test_held_batch_release_refused_while_the_producing_run_is_quarantined(api):
    """A second technician clears the duties gate and hits the run-state gate.

    "Releasing a batch hold is refused when `X-User-ID` equals the batch's
    `held_by_user_id`."
    "The producing run's `qc_disposition` must be `RELEASED`, or the release is
    `ERR_RUN_NOT_RELEASED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/batch_hold_release_gated_by_producing_run_qc_disposition
    """
    _built, run, _disposition, batch = _quarantined_batch_of_certified_sku(api)

    resp = api.set_batch_hold_status(
        batch["id"], hold_status_payload("RELEASE_HOLD"), QA_TECHNICIAN_B
    )
    validate_error(resp, ApiErrorId.RUN_NOT_RELEASED.value)

    still_held = validate_success(api.get_batch(batch["id"], QA_TECHNICIAN))
    assert still_held["status"] == "HELD"
    run_after = validate_success(api.get_production_run(run["id"], QA_TECHNICIAN))
    assert run_after["qc_disposition"] == "QUARANTINED"


def test_run_qc_release_returns_the_held_batch_to_stock_as_a_side_effect(api):
    """Flipping the run's disposition, not a batch call, returns the stock to sale.

    "`PENDING → RELEASED` and `QUARANTINED → RELEASED` both require all four QC
    gates to hold."
    "Releasing moves the run's batch `IN_PRODUCTION → IN_STOCK` (or `HELD →
    IN_STOCK` when the batch was quarantined earlier) and sets
    `available_quantity_sqm` to the full `quantity_sqm`."
    "Quality disposition is a `QaTechnician` decision expressed as a
    `to_disposition`, with an optional `hold_reason`."

    Design: Difficulty/cross_entity_state_dependency/batch_hold_release_gated_by_producing_run_qc_disposition
    """
    _built, run, _disposition, batch = _quarantined_batch_of_certified_sku(api)

    released = set_qc_disposition(api, run["id"], "RELEASED", QA_TECHNICIAN_B)
    assert released["qc_disposition"] == "RELEASED"
    assert released["run_status"] == "COMPLETED"

    batch_after = validate_success(api.get_batch(batch["id"], QA_TECHNICIAN_B))
    assert batch_after["status"] == "IN_STOCK"
    assert batch_after["available_quantity_sqm"] == 1200.00
    assert batch_after["quantity_sqm"] == 1200.00


def test_allocation_creation_refused_while_sku_certification_is_provisional(api):
    """An allocation may not be raised against a merely PROVISIONAL SKU.

    "The SKU must be `CERTIFIED` at creation time — an allocation may not be
    raised against a SKU that has never been certified or has lost
    certification, and the attempt is `ERR_SKU_NOT_PRODUCIBLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/allocation_create_gated_by_certification_and_fill_gated_by_commercial_status
    """
    built, _run, _batch, distributor = _provisional_sku_with_released_stock(api)
    sku_id = built["sku"]["id"]

    sku = validate_success(api.get_product_sku(sku_id, PLANT_ADMIN))
    assert sku["certification_status"] == "PROVISIONAL"

    resp = api.create_allocation(
        allocation_payload(
            distributor["id"],
            sku_id,
            allocation_code="AL-G1",
            requested_quantity_sqm=300.00,
            substitution_policy="STRICT_SKU",
        ),
        distributor_headers(distributor["id"]),
    )
    validate_error(resp, ApiErrorId.SKU_NOT_PRODUCIBLE.value)


def test_allocation_fill_refused_while_sku_commercial_status_is_development(api):
    """The identical payload creates once CERTIFIED, yet the fill still refuses.

    "Certification is a `TechnicalDirector` action reachable from `TESTING` or
    `PROVISIONAL` — `certification_status` `TESTING → CERTIFIED` and
    `PROVISIONAL → CERTIFIED` are treated identically."
    "`standard_cost_cents_per_sqm` is computed on the pinned basis described in
    §3.3 and stored, and `list_price_cents_per_sqm` is derived from it by the
    `target_margin_bps` gross-up."
    "`standard_cost_cents_per_sqm` is the exact integer sum of those seven
    rounded integers, and `list_price_cents_per_sqm` is that standard cost
    multiplied by the quantity 10000 plus `target_margin_bps`, divided by 10000,
    rounded half up to a whole cent."
    "A new allocation is `OPEN` with `allocated_quantity_sqm` and
    `upgrade_cost_total_cents` both 0."
    "The SKU must currently be `RELEASED` on its commercial dimension, or the
    fill is `ERR_SKU_NOT_PRODUCIBLE`."

    Design: Difficulty/cross_entity_state_dependency/allocation_create_gated_by_certification_and_fill_gated_by_commercial_status
    """
    built, _run, _batch, distributor = _provisional_sku_with_released_stock(api)
    sku_id = built["sku"]["id"]
    headers = distributor_headers(distributor["id"])

    blocked = api.create_allocation(
        allocation_payload(
            distributor["id"],
            sku_id,
            allocation_code="AL-G1",
            requested_quantity_sqm=300.00,
            substitution_policy="STRICT_SKU",
        ),
        headers,
    )
    validate_error(blocked, ApiErrorId.SKU_NOT_PRODUCIBLE.value)

    certified = validate_success(api.certify_sku(sku_id, TECHNICAL_DIRECTOR))
    assert certified["certification_status"] == "CERTIFIED"
    assert certified["commercial_status"] == "DEVELOPMENT"
    assert certified["standard_cost_cents_per_sqm"] == 1157
    assert certified["list_price_cents_per_sqm"] == 1562

    allocation = validate_success(
        api.create_allocation(
            allocation_payload(
                distributor["id"],
                sku_id,
                allocation_code="AL-G1",
                requested_quantity_sqm=300.00,
                substitution_policy="STRICT_SKU",
            ),
            headers,
        ),
        201,
    )
    assert allocation["status"] == "OPEN"
    assert allocation["allocated_quantity_sqm"] == 0

    refused_fill = api.fill_allocation(
        allocation["id"], fill_payload(allocation["version"]), headers
    )
    validate_error(refused_fill, ApiErrorId.SKU_NOT_PRODUCIBLE.value)

    # The rejected fill left the allocation untouched, so the same expected
    # version is still the current one.
    after = validate_success(api.get_allocation(allocation["id"], headers))
    assert after["version"] == allocation["version"]
    assert after["status"] == "OPEN"


def test_allocation_fill_draws_stock_once_the_sku_is_commercially_released(api):
    """The commercial release admits the fill and the waterfall draws 300.00 sqm.

    "`DEVELOPMENT → RELEASED` and `HOLD → RELEASED` are both declared, as is
    `RELEASED → HOLD`, giving a `RELEASED → HOLD → RELEASED` cycle;
    `DISCONTINUED` is reachable from `DEVELOPMENT`, `RELEASED` or `HOLD` and is
    terminal on this dimension."
    "The SKU must currently be `RELEASED` on its commercial dimension, or the
    fill is `ERR_SKU_NOT_PRODUCIBLE`."
    "An `EXACT` candidate is one whose batch carries the requested `sku_id`
    itself."
    "One allocation line is created per drawn batch, carrying the
    `allocation_id` it fills, the `batch_id` drawn on, the `quantity_sqm` drawn,
    and its `substitution_kind`; the batch's `available_quantity_sqm` is
    decremented by that quantity and its `version` advanced, and the remaining
    requirement falls by the same amount."
    "The allocation's resulting `status` follows from the arithmetic: `FILLED`
    when `allocated_quantity_sqm` has reached `requested_quantity_sqm`,
    `PARTIALLY_FILLED` when it is above zero but short of the request, and
    `OPEN` when it is zero."

    Design: Difficulty/cross_entity_state_dependency/allocation_create_gated_by_certification_and_fill_gated_by_commercial_status
    """
    built, _run, batch, distributor = _provisional_sku_with_released_stock(api)
    sku_id = built["sku"]["id"]
    headers = distributor_headers(distributor["id"])

    validate_success(api.certify_sku(sku_id, TECHNICAL_DIRECTOR))
    allocation = validate_success(
        api.create_allocation(
            allocation_payload(
                distributor["id"],
                sku_id,
                allocation_code="AL-G1",
                requested_quantity_sqm=300.00,
                substitution_policy="STRICT_SKU",
            ),
            headers,
        ),
        201,
    )

    refused_fill = api.fill_allocation(
        allocation["id"], fill_payload(allocation["version"]), headers
    )
    validate_error(refused_fill, ApiErrorId.SKU_NOT_PRODUCIBLE.value)

    released = validate_success(
        api.set_sku_commercial_status(
            sku_id, commercial_status_payload("RELEASED"), PLANT_ADMIN
        )
    )
    assert released["commercial_status"] == "RELEASED"

    filled = validate_success(
        api.fill_allocation(
            allocation["id"], fill_payload(allocation["version"]), headers
        )
    )
    assert filled["status"] == "FILLED"
    assert filled["allocated_quantity_sqm"] == 300.00

    batch_after = validate_success(api.get_batch(batch["id"], QA_TECHNICIAN))
    assert batch_after["available_quantity_sqm"] == 900.00

    lines, meta = validate_paginated(
        api.list_allocation_lines(allocation["id"], headers)
    )
    assert meta["total_count"] == 1
    assert lines[0]["substitution_kind"] == "EXACT"


# ---------------------------------------------------------------------------
# Resource temporal overlap.
# ---------------------------------------------------------------------------


def test_press_line_window_conflict_on_a_one_hour_straddle(api):
    """A run overlapping an incumbent window on the same line is refused.

    "Two runs on the same line collide when the new run's start is strictly
    earlier than the other's end **and** the other's start is strictly earlier
    than the new run's end, counting only runs whose `run_status` is not
    `ABORTED`."
    "A collision is `ERR_PRESS_LINE_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/press_line_half_open_window_admits_touching_endpoints
    """
    _license_row, _film, sku, line = _sku_c_on_pl2(api)
    create_run(
        api,
        sku["id"],
        line["id"],
        run_code="RUN-W1",
        planned_start_utc="2026-08-01T02:00:00Z",
        planned_end_utc="2026-08-01T06:00:00Z",
        planned_quantity_sqm=100.00,
    )

    resp = api.create_production_run(
        production_run_payload(
            sku["id"],
            line["id"],
            run_code="RUN-W2",
            planned_start_utc="2026-08-01T05:00:00Z",
            planned_end_utc="2026-08-01T08:00:00Z",
            planned_quantity_sqm=100.00,
        ),
        PRODUCTION_PLANNER,
    )
    validate_error(resp, ApiErrorId.PRESS_LINE_WINDOW_CONFLICT.value)

    _rows, meta = validate_paginated(
        api.list_production_runs(PRODUCTION_PLANNER, params={"press_line_id": line["id"]})
    )
    assert meta["total_count"] == 1


def test_press_line_admits_a_run_starting_exactly_at_another_runs_planned_end(api):
    """The half-open line window admits a run that starts at another's end.

    "**Line occupation** treats a run's window as half-open, from
    `planned_start_utc` inclusive to `planned_end_utc` exclusive."
    "Touching endpoints therefore do not collide: a run beginning exactly at
    another's `planned_end_utc` is disjoint and admissible."
    "The run is created with `run_status` `PLANNED` and `qc_disposition`
    `PENDING`, with `changeover_minutes_applied` null, `actual_quantity_sqm` 0,
    `royalty_accrued_cents` 0, and every measured and derived quality field
    null."

    Design: Difficulty/resource_temporal_overlap/press_line_half_open_window_admits_touching_endpoints
    """
    _license_row, _film, sku, line = _sku_c_on_pl2(api)
    create_run(
        api,
        sku["id"],
        line["id"],
        run_code="RUN-W1",
        planned_start_utc="2026-08-01T02:00:00Z",
        planned_end_utc="2026-08-01T06:00:00Z",
        planned_quantity_sqm=100.00,
    )

    admitted = validate_success(
        api.create_production_run(
            production_run_payload(
                sku["id"],
                line["id"],
                run_code="RUN-W3",
                planned_start_utc="2026-08-01T06:00:00Z",
                planned_end_utc="2026-08-01T08:00:00Z",
                planned_quantity_sqm=100.00,
            ),
            PRODUCTION_PLANNER,
        ),
        201,
    )
    assert admitted["run_status"] == "PLANNED"


def test_press_line_admits_a_run_ending_exactly_at_another_runs_planned_start(api):
    """Touching from below is equally disjoint, and only admitted runs reserve.

    "Touching endpoints therefore do not collide: a run beginning exactly at
    another's `planned_end_utc` is disjoint and admissible."
    "A collision is `ERR_PRESS_LINE_WINDOW_CONFLICT` (HTTP 409)."
    "On success, the run's `planned_quantity_sqm` is added to the grant's
    `reserved_volume_sqm` and the grant's `version` is advanced."

    Design: Difficulty/resource_temporal_overlap/press_line_half_open_window_admits_touching_endpoints
    """
    license_row, _film, sku, line = _sku_c_on_pl2(api)
    create_run(
        api,
        sku["id"],
        line["id"],
        run_code="RUN-W1",
        planned_start_utc="2026-08-01T02:00:00Z",
        planned_end_utc="2026-08-01T06:00:00Z",
        planned_quantity_sqm=100.00,
    )
    straddle = api.create_production_run(
        production_run_payload(
            sku["id"],
            line["id"],
            run_code="RUN-W2",
            planned_start_utc="2026-08-01T05:00:00Z",
            planned_end_utc="2026-08-01T08:00:00Z",
            planned_quantity_sqm=100.00,
        ),
        PRODUCTION_PLANNER,
    )
    validate_error(straddle, ApiErrorId.PRESS_LINE_WINDOW_CONFLICT.value)
    create_run(
        api,
        sku["id"],
        line["id"],
        run_code="RUN-W3",
        planned_start_utc="2026-08-01T06:00:00Z",
        planned_end_utc="2026-08-01T08:00:00Z",
        planned_quantity_sqm=100.00,
    )

    touching_below = validate_success(
        api.create_production_run(
            production_run_payload(
                sku["id"],
                line["id"],
                run_code="RUN-W4",
                planned_start_utc="2026-08-01T01:00:00Z",
                planned_end_utc="2026-08-01T02:00:00Z",
                planned_quantity_sqm=100.00,
            ),
            PRODUCTION_PLANNER,
        ),
        201,
    )
    assert touching_below["run_status"] == "PLANNED"

    _rows, meta = validate_paginated(
        api.list_production_runs(PRODUCTION_PLANNER, params={"press_line_id": line["id"]})
    )
    assert meta["total_count"] == 3

    grant = validate_success(api.get_design_license(license_row["id"], PLANT_ADMIN))
    assert grant["reserved_volume_sqm"] == 300.00


def test_roll_set_capacity_collides_on_a_shared_endpoint_across_press_lines(api):
    """The closed film window collides at a shared endpoint on a different line.

    "**Roll-set capacity** on the print film uses a *closed* interval — from
    `planned_start_utc` through `planned_end_utc` inclusive — because a roll set
    cannot be re-threaded instantaneously, so here touching endpoints *do*
    collide."
    "It is also an aggregate capacity rule rather than a pairwise exclusion:
    count the runs on the same `print_film_id` whose closed windows intersect
    the new run's closed window and whose `run_status` is not `ABORTED`, and
    reject only when that count is at least the film's `master_roll_sets`."
    "The rejection is `ERR_PRINT_FILM_ROLL_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/print_film_closed_interval_aggregate_roll_set_capacity
    """
    _license_row, film, sku, lines = _sku_d_on_three_lines(api)
    create_run(
        api,
        sku["id"],
        lines["PL-A"]["id"],
        run_code="RUN-F1",
        planned_start_utc="2026-08-01T02:00:00Z",
        planned_end_utc="2026-08-01T06:00:00Z",
        planned_quantity_sqm=100.00,
    )

    resp = api.create_production_run(
        production_run_payload(
            sku["id"],
            lines["PL-B"]["id"],
            run_code="RUN-F2",
            planned_start_utc="2026-08-01T06:00:00Z",
            planned_end_utc="2026-08-01T09:00:00Z",
            planned_quantity_sqm=100.00,
        ),
        PRODUCTION_PLANNER,
    )
    validate_error(resp, ApiErrorId.PRINT_FILM_ROLL_CAPACITY_EXCEEDED.value)

    film_after = validate_success(api.get_print_film(film["id"], PLANT_ADMIN))
    assert film_after["master_roll_sets"] == 1


def test_roll_set_capacity_admits_one_minute_of_separation(api):
    """One minute of separation clears the closed film geometry.

    "It is also an aggregate capacity rule rather than a pairwise exclusion:
    count the runs on the same `print_film_id` whose closed windows intersect
    the new run's closed window and whose `run_status` is not `ABORTED`, and
    reject only when that count is at least the film's `master_roll_sets`."
    "and `master_roll_sets` of at least 1 — the number of physical roll sets,
    which caps how many runs may occupy overlapping windows on the design."

    Design: Difficulty/resource_temporal_overlap/print_film_closed_interval_aggregate_roll_set_capacity
    """
    _license_row, _film, sku, lines = _sku_d_on_three_lines(api)
    create_run(
        api,
        sku["id"],
        lines["PL-A"]["id"],
        run_code="RUN-F1",
        planned_start_utc="2026-08-01T02:00:00Z",
        planned_end_utc="2026-08-01T06:00:00Z",
        planned_quantity_sqm=100.00,
    )

    admitted = validate_success(
        api.create_production_run(
            production_run_payload(
                sku["id"],
                lines["PL-B"]["id"],
                run_code="RUN-F3",
                planned_start_utc="2026-08-01T06:01:00Z",
                planned_end_utc="2026-08-01T09:00:00Z",
                planned_quantity_sqm=100.00,
            ),
            PRODUCTION_PLANNER,
        ),
        201,
    )
    assert admitted["run_status"] == "PLANNED"


def test_roll_set_capacity_counts_containment_and_is_freed_by_an_abort(api):
    """Containment counts as intersection, and an abort frees the roll set again.

    "It is also an aggregate capacity rule rather than a pairwise exclusion:
    count the runs on the same `print_film_id` whose closed windows intersect
    the new run's closed window and whose `run_status` is not `ABORTED`, and
    reject only when that count is at least the film's `master_roll_sets`."
    "The rejection is `ERR_PRINT_FILM_ROLL_CAPACITY_EXCEEDED` (HTTP 409)."
    "Aborting is available from `PLANNED`, `SETUP` or `RUNNING` with an
    `abort_reason`, and it is an exact compensation: the run's
    `planned_quantity_sqm` is subtracted from the grant's `reserved_volume_sqm`,
    restoring that figure to its pre-scheduling value bit for bit."

    Design: Difficulty/resource_temporal_overlap/print_film_closed_interval_aggregate_roll_set_capacity
    """
    license_row, film, sku, lines = _sku_d_on_three_lines(api)
    run_f1 = create_run(
        api,
        sku["id"],
        lines["PL-A"]["id"],
        run_code="RUN-F1",
        planned_start_utc="2026-08-01T02:00:00Z",
        planned_end_utc="2026-08-01T06:00:00Z",
        planned_quantity_sqm=100.00,
    )
    create_run(
        api,
        sku["id"],
        lines["PL-B"]["id"],
        run_code="RUN-F3",
        planned_start_utc="2026-08-01T06:01:00Z",
        planned_end_utc="2026-08-01T09:00:00Z",
        planned_quantity_sqm=100.00,
    )

    contained_payload = production_run_payload(
        sku["id"],
        lines["PL-C"]["id"],
        run_code="RUN-F4",
        planned_start_utc="2026-08-01T04:00:00Z",
        planned_end_utc="2026-08-01T05:00:00Z",
        planned_quantity_sqm=100.00,
    )
    contained = api.create_production_run(contained_payload, PRODUCTION_PLANNER)
    validate_error(contained, ApiErrorId.PRINT_FILM_ROLL_CAPACITY_EXCEEDED.value)

    aborted = validate_success(
        api.abort_production_run(
            run_f1["id"],
            run_abort_payload(
                abort_reason="film master roll set reassigned to a trial"
            ),
            PRODUCTION_PLANNER,
        )
    )
    assert aborted["run_status"] == "ABORTED"

    readmitted = validate_success(
        api.create_production_run(
            production_run_payload(
                sku["id"],
                lines["PL-C"]["id"],
                run_code="RUN-F5",
                planned_start_utc="2026-08-01T04:00:00Z",
                planned_end_utc="2026-08-01T05:00:00Z",
                planned_quantity_sqm=100.00,
            ),
            PRODUCTION_PLANNER,
        ),
        201,
    )
    assert readmitted["run_status"] == "PLANNED"

    film_after = validate_success(api.get_print_film(film["id"], PLANT_ADMIN))
    assert film_after["master_roll_sets"] == 1

    grant = validate_success(api.get_design_license(license_row["id"], PLANT_ADMIN))
    assert grant["reserved_volume_sqm"] == 200.00


def test_run_admitted_one_hour_before_the_licence_valid_until(api):
    """A planned start one hour inside the term is admitted and reserves volume.

    "The film must be `AVAILABLE` and the grant must be `ACTIVE` with
    `planned_start_utc` at or after `valid_from` and strictly before
    `valid_until`."
    "On success, the run's `planned_quantity_sqm` is added to the grant's
    `reserved_volume_sqm` and the grant's `version` is advanced."

    Design: Difficulty/resource_temporal_overlap/license_term_window_lazy_expiry_blocks_run_creation_before_status_flips
    """
    license_row, _film, sku, line = _sku_e_on_expiring_licence(api)

    admitted = validate_success(
        api.create_production_run(
            production_run_payload(
                sku["id"],
                line["id"],
                run_code="RUN-E-IN",
                planned_start_utc="2026-08-31T23:00:00Z",
                planned_end_utc="2026-08-31T23:30:00Z",
                planned_quantity_sqm=100.00,
            ),
            PRODUCTION_PLANNER,
        ),
        201,
    )
    assert admitted["run_status"] == "PLANNED"

    grant = validate_success(api.get_design_license(license_row["id"], PLANT_ADMIN))
    assert grant["reserved_volume_sqm"] == 100.00
    assert grant["status"] == "ACTIVE"


def test_run_at_valid_until_refused_while_the_licence_remains_active(api):
    """valid_until is exclusive, and the refusal does not expire the grant.

    "The same code and status apply when a run is scheduled with a
    `planned_start_utc` at or after `valid_until`, or strictly earlier than
    `valid_from`."
    "Grants also expire, but lazily and against the logical clock rather than by
    a background sweep."
    "When run scheduling, run starting, or the start of SKU testing consults a
    grant that is `ACTIVE` and finds the clock at or past its `valid_until`, the
    grant's `status` is first set to `EXPIRED` and its `version` advanced, and
    then the triggering request is rejected with `ERR_LICENSE_EXPIRED` (HTTP
    409)."

    Design: Difficulty/resource_temporal_overlap/license_term_window_lazy_expiry_blocks_run_creation_before_status_flips
    """
    license_row, _film, sku, line = _sku_e_on_expiring_licence(api)
    create_run(
        api,
        sku["id"],
        line["id"],
        run_code="RUN-E-IN",
        planned_start_utc="2026-08-31T23:00:00Z",
        planned_end_utc="2026-08-31T23:30:00Z",
        planned_quantity_sqm=100.00,
    )

    edge = api.create_production_run(
        production_run_payload(
            sku["id"],
            line["id"],
            run_code="RUN-E-EDGE",
            planned_start_utc="2026-09-01T00:00:00Z",
            planned_end_utc="2026-09-01T02:00:00Z",
            planned_quantity_sqm=100.00,
        ),
        PRODUCTION_PLANNER,
    )
    validate_error(edge, ApiErrorId.LICENSE_EXPIRED.value)

    # The requested window is outside the term but the clock is not, so no lazy
    # flip occurs.
    grant = validate_success(api.get_design_license(license_row["id"], PLANT_ADMIN))
    assert grant["status"] == "ACTIVE"
    assert grant["reserved_volume_sqm"] == 100.00


def test_licence_flips_to_expired_only_when_the_clock_reaches_valid_until(api):
    """Advancing the clock to valid_until makes the next scheduling attempt flip it.

    "When run scheduling, run starting, or the start of SKU testing consults a
    grant that is `ACTIVE` and finds the clock at or past its `valid_until`, the
    grant's `status` is first set to `EXPIRED` and its `version` advanced, and
    then the triggering request is rejected with `ERR_LICENSE_EXPIRED` (HTTP
    409)."
    "The gap in whole minutes from the predecessor's `planned_end_utc` to the
    new run's `planned_start_utc` must be at least that required figure;
    equality passes, and a shortfall is `ERR_CHANGEOVER_GAP_INSUFFICIENT` (HTTP
    409)."
    "Collection reads support equality filters drawn from the same vocabulary,
    combined with logical AND when more than one is supplied."

    Design: Difficulty/resource_temporal_overlap/license_term_window_lazy_expiry_blocks_run_creation_before_status_flips
    """
    license_row, _film, sku, line = _sku_e_on_expiring_licence(api)
    create_run(
        api,
        sku["id"],
        line["id"],
        run_code="RUN-E-IN",
        planned_start_utc="2026-08-31T23:00:00Z",
        planned_end_utc="2026-08-31T23:30:00Z",
        planned_quantity_sqm=100.00,
    )
    edge = api.create_production_run(
        production_run_payload(
            sku["id"],
            line["id"],
            run_code="RUN-E-EDGE",
            planned_start_utc="2026-09-01T00:00:00Z",
            planned_end_utc="2026-09-01T02:00:00Z",
            planned_quantity_sqm=100.00,
        ),
        PRODUCTION_PLANNER,
    )
    validate_error(edge, ApiErrorId.LICENSE_EXPIRED.value)

    set_clock(api, "2026-09-01T00:00:00Z")

    late = api.create_production_run(
        production_run_payload(
            sku["id"],
            line["id"],
            run_code="RUN-E-LATE",
            planned_start_utc="2026-09-01T03:00:00Z",
            planned_end_utc="2026-09-01T05:00:00Z",
            planned_quantity_sqm=100.00,
        ),
        PRODUCTION_PLANNER,
    )
    validate_error(late, ApiErrorId.LICENSE_EXPIRED.value)

    grant = validate_success(api.get_design_license(license_row["id"], PLANT_ADMIN))
    assert grant["status"] == "EXPIRED"
    assert grant["reserved_volume_sqm"] == 100.00

    _rows, meta = validate_paginated(
        api.list_production_runs(PRODUCTION_PLANNER, params={"sku_id": sku["id"]})
    )
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Compensating invariants.
# ---------------------------------------------------------------------------


def test_reserved_entitlement_returns_to_zero_across_create_and_abort(api):
    """Two reservations and two aborts leave the entitlement ledger exactly as found.

    "On success, the run's `planned_quantity_sqm` is added to the grant's
    `reserved_volume_sqm` and the grant's `version` is advanced."
    "Aborting is available from `PLANNED`, `SETUP` or `RUNNING` with an
    `abort_reason`, and it is an exact compensation: the run's
    `planned_quantity_sqm` is subtracted from the grant's `reserved_volume_sqm`,
    restoring that figure to its pre-scheduling value bit for bit."
    "When a run that reserved licensed volume is aborted, exactly the volume it
    reserved is released, leaving the reserved figure bit-identical to its
    pre-creation value."
    "No batch is minted and no royalty is accrued, so a schedule-then-abort pair
    leaves the ledger indistinguishable from never having scheduled."
    "A grant's utilization is readable as a computed summary carrying
    `term_volume_cap_sqm`, `reserved_volume_sqm`, `consumed_volume_sqm`, the
    forward-looking `projected_volume_sqm` (consumed plus reserved), the
    `remaining_volume_sqm` left under the cap (the cap less the projection), the
    `accrued_royalty_cents` ledger, and `contributing_run_count`, the number of
    completed runs that have contributed royalty to it."

    Design: Difficulty/compensating_invariant/license_reserved_entitlement_conserved_across_create_and_abort
    """
    built, pl1, pl2 = _certified_sku_a_on_two_lines(api)
    license_id = built["license"]["id"]
    sku_id = built["sku"]["id"]

    before = validate_success(
        api.get_license_utilization(license_id, TECHNICAL_DIRECTOR)
    )
    assert before["reserved_volume_sqm"] == 0.00

    run_i1 = create_run(
        api,
        sku_id,
        pl1["id"],
        run_code="RUN-I1",
        planned_start_utc="2026-08-01T01:00:00Z",
        planned_end_utc="2026-08-01T09:00:00Z",
        planned_quantity_sqm=1200.00,
    )
    run_i2 = create_run(
        api,
        sku_id,
        pl2["id"],
        run_code="RUN-I2",
        planned_start_utc="2026-08-01T09:01:00Z",
        planned_end_utc="2026-08-01T13:00:00Z",
        planned_quantity_sqm=300.00,
    )

    peak = validate_success(api.get_license_utilization(license_id, TECHNICAL_DIRECTOR))
    assert peak["reserved_volume_sqm"] == 1500.00

    validate_success(
        api.abort_production_run(
            run_i2["id"],
            run_abort_payload(abort_reason="calender roll change brought forward"),
            PRODUCTION_PLANNER,
        )
    )
    mid = validate_success(api.get_license_utilization(license_id, TECHNICAL_DIRECTOR))
    assert mid["reserved_volume_sqm"] == 1200.00

    validate_success(
        api.abort_production_run(
            run_i1["id"],
            run_abort_payload(abort_reason="order cancelled by the distributor"),
            PRODUCTION_PLANNER,
        )
    )
    end = validate_success(api.get_license_utilization(license_id, TECHNICAL_DIRECTOR))
    assert end["reserved_volume_sqm"] == 0.00
    assert end["consumed_volume_sqm"] == 0.00
    assert end["accrued_royalty_cents"] == 0
    assert end["projected_volume_sqm"] == 0.00
    assert end["remaining_volume_sqm"] == 2000.00

    _rows, batch_meta = validate_paginated(api.list_batches(PRODUCTION_PLANNER))
    assert batch_meta["total_count"] == 0


def test_aborted_runs_keep_planned_quantity_while_reservation_is_released(api):
    """The ABORTED rows keep their quantities, so the reversal lives in the ledger.

    "The run is created with `run_status` `PLANNED` and `qc_disposition`
    `PENDING`, with `changeover_minutes_applied` null, `actual_quantity_sqm` 0,
    `royalty_accrued_cents` 0, and every measured and derived quality field
    null."
    "Aborting is available from `PLANNED`, `SETUP` or `RUNNING` with an
    `abort_reason`, and it is an exact compensation: the run's
    `planned_quantity_sqm` is subtracted from the grant's `reserved_volume_sqm`,
    restoring that figure to its pre-scheduling value bit for bit."
    "No batch is minted and no royalty is accrued, so a schedule-then-abort pair
    leaves the ledger indistinguishable from never having scheduled."

    Design: Difficulty/compensating_invariant/license_reserved_entitlement_conserved_across_create_and_abort
    """
    built, pl1, pl2 = _certified_sku_a_on_two_lines(api)
    sku_id = built["sku"]["id"]

    run_i1 = create_run(
        api,
        sku_id,
        pl1["id"],
        run_code="RUN-I1",
        planned_start_utc="2026-08-01T01:00:00Z",
        planned_end_utc="2026-08-01T09:00:00Z",
        planned_quantity_sqm=1200.00,
    )
    run_i2 = create_run(
        api,
        sku_id,
        pl2["id"],
        run_code="RUN-I2",
        planned_start_utc="2026-08-01T09:01:00Z",
        planned_end_utc="2026-08-01T13:00:00Z",
        planned_quantity_sqm=300.00,
    )
    validate_success(
        api.abort_production_run(
            run_i2["id"],
            run_abort_payload(abort_reason="calender roll change brought forward"),
            PRODUCTION_PLANNER,
        )
    )
    validate_success(
        api.abort_production_run(
            run_i1["id"],
            run_abort_payload(abort_reason="order cancelled by the distributor"),
            PRODUCTION_PLANNER,
        )
    )

    i1_after = validate_success(api.get_production_run(run_i1["id"], PLANT_ADMIN))
    assert i1_after["run_status"] == "ABORTED"
    assert i1_after["planned_quantity_sqm"] == 1200.00
    assert i1_after["actual_quantity_sqm"] == 0.00
    assert i1_after["royalty_accrued_cents"] == 0

    i2_after = validate_success(api.get_production_run(run_i2["id"], PLANT_ADMIN))
    assert i2_after["run_status"] == "ABORTED"
    assert i2_after["planned_quantity_sqm"] == 300.00
    assert i2_after["actual_quantity_sqm"] == 0.00
    assert i2_after["royalty_accrued_cents"] == 0

    grant = validate_success(api.get_design_license(built["license"]["id"], PLANT_ADMIN))
    assert grant["reserved_volume_sqm"] == 0.00
    assert grant["consumed_volume_sqm"] == 0.00
    assert grant["accrued_royalty_cents"] == 0


def test_qc_scrap_reverses_consumed_area_and_accrued_royalty_exactly(api):
    """A QC scrap removes exactly the area and the money the completion added.

    "Second, the licensed-volume ledger settles on an actual basis: the run's
    `planned_quantity_sqm` is subtracted from the grant's `reserved_volume_sqm`
    and the measured `actual_quantity_sqm` is added to its
    `consumed_volume_sqm`."
    "The run's `actual_quantity_sqm` is multiplied by the SKU's
    `royalty_basis_price_cents_per_sqm` and by the grant's `royalty_rate_bps`
    divided by 10000, and the product is rounded half up to a whole cent."
    "`SCRAPPED` is reachable from `PENDING`, `QUARANTINED` or `RELEASED`, and it
    unwinds the completion exactly."
    "The run's `actual_quantity_sqm` is subtracted from the grant's
    `consumed_volume_sqm`, and the run's stored `royalty_accrued_cents` is
    subtracted from the grant's `accrued_royalty_cents` before the run's own
    figure is set to 0 — the reversal uses the stored integer rather than a
    fresh computation."

    Design: Difficulty/compensating_invariant/royalty_money_and_consumed_area_reversed_exactly_on_qc_scrap
    """
    built, run, _batch = _released_run_of_certified_sku(api)
    license_id = built["license"]["id"]

    before = validate_success(
        api.get_license_utilization(license_id, TECHNICAL_DIRECTOR)
    )
    assert before["consumed_volume_sqm"] == 1200.00
    assert before["accrued_royalty_cents"] == 126000

    scrapped = set_qc_disposition(
        api,
        run["id"],
        "SCRAPPED",
        QA_TECHNICIAN_B,
        hold_reason="gel specks across the whole lot",
    )
    assert scrapped["qc_disposition"] == "SCRAPPED"

    after = validate_success(
        api.get_license_utilization(license_id, TECHNICAL_DIRECTOR)
    )
    assert after["consumed_volume_sqm"] == 0.00
    assert after["accrued_royalty_cents"] == 0
    assert after["reserved_volume_sqm"] == 0.00
    assert after["remaining_volume_sqm"] == 2000.00


def test_qc_scrap_subtracts_the_runs_stored_royalty_and_zeroes_it(api):
    """The reversal is the stored integer, and the batch is scrapped, not deleted.

    "That integer is stored in the run's `royalty_accrued_cents` and added to
    the grant's `accrued_royalty_cents`, one run at a time, per the
    rounding-order rule of §2.6."
    "The run's `actual_quantity_sqm` is subtracted from the grant's
    `consumed_volume_sqm`, and the run's stored `royalty_accrued_cents` is
    subtracted from the grant's `accrued_royalty_cents` before the run's own
    figure is set to 0 — the reversal uses the stored integer rather than a
    fresh computation."
    "When a completed run is scrapped, the consumed volume it added is
    subtracted and the royalty it accrued is subtracted as the stored integer
    that was actually added, never as a fresh calculation that might round
    differently."
    "The run's batch moves to `SCRAPPED` with `available_quantity_sqm` set to
    0."

    Design: Difficulty/compensating_invariant/royalty_money_and_consumed_area_reversed_exactly_on_qc_scrap
    """
    built, run, batch = _released_run_of_certified_sku(api)

    stored = validate_success(api.get_production_run(run["id"], PLANT_ADMIN))
    assert stored["royalty_accrued_cents"] == 126000
    assert stored["actual_quantity_sqm"] == 1200.00

    scrapped = set_qc_disposition(
        api,
        run["id"],
        "SCRAPPED",
        QA_TECHNICIAN_B,
        hold_reason="gel specks across the whole lot",
    )
    # The run's own accrual is zeroed rather than left dangling, and the
    # execution dimension is untouched by a quality decision.
    assert scrapped["royalty_accrued_cents"] == 0
    assert scrapped["run_status"] == "COMPLETED"
    assert scrapped["actual_quantity_sqm"] == 1200.00

    grant = validate_success(api.get_design_license(built["license"]["id"], PLANT_ADMIN))
    assert grant["accrued_royalty_cents"] == 0
    assert grant["consumed_volume_sqm"] == 0.00

    batch_after = validate_success(api.get_batch(batch["id"], QA_TECHNICIAN_B))
    assert batch_after["status"] == "SCRAPPED"
    assert batch_after["available_quantity_sqm"] == 0.00
    assert batch_after["quantity_sqm"] == 1200.00


def test_stock_area_conserved_across_two_fills_and_two_releases(api):
    """Two fills and two releases move the stock split 1200/0 and back to 1200/0.

    "One allocation line is created per drawn batch, carrying the
    `allocation_id` it fills, the `batch_id` drawn on, the `quantity_sqm` drawn,
    and its `substitution_kind`; the batch's `available_quantity_sqm` is
    decremented by that quantity and its `version` advanced, and the remaining
    requirement falls by the same amount."
    "The allocation's resulting `status` follows from the arithmetic: `FILLED`
    when `allocated_quantity_sqm` has reached `requested_quantity_sqm`,
    `PARTIALLY_FILLED` when it is above zero but short of the request, and
    `OPEN` when it is zero."
    "Every `ACTIVE` line becomes `VOIDED` with `void_reason`
    `ALLOCATION_RELEASED` and its `quantity_sqm` is added back to its batch's
    `available_quantity_sqm`, restoring the stock ledger exactly;
    `allocated_quantity_sqm` and `upgrade_cost_total_cents` both become 0, and
    every touched batch has its `version` advanced."
    "Releasing moves the run's batch `IN_PRODUCTION → IN_STOCK` (or `HELD →
    IN_STOCK` when the batch was quarantined earlier) and sets
    `available_quantity_sqm` to the full `quantity_sqm`."

    Design: Difficulty/compensating_invariant/physical_stock_area_conserved_across_fill_and_release
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_stock_batch(api)
    batch_id = built["batch"]["id"]
    distributor = create_distributor(api)
    headers = distributor_headers(distributor["id"])
    al_v1 = create_allocation(
        api,
        distributor["id"],
        built["sku"]["id"],
        allocation_code="AL-V1",
        requested_quantity_sqm=300.00,
        substitution_policy="STRICT_SKU",
    )
    al_v2 = create_allocation(
        api,
        distributor["id"],
        built["sku"]["id"],
        allocation_code="AL-V2",
        requested_quantity_sqm=200.00,
        substitution_policy="STRICT_SKU",
    )

    start = validate_success(api.get_batch(batch_id, PRODUCTION_PLANNER))
    assert start["quantity_sqm"] == 1200.00
    assert start["available_quantity_sqm"] == 1200.00

    filled_v1 = validate_success(
        api.fill_allocation(al_v1["id"], fill_payload(al_v1["version"]), headers)
    )
    assert filled_v1["status"] == "FILLED"
    after_v1 = validate_success(api.get_batch(batch_id, PRODUCTION_PLANNER))
    assert after_v1["available_quantity_sqm"] == 900.00

    filled_v2 = validate_success(
        api.fill_allocation(al_v2["id"], fill_payload(al_v2["version"]), headers)
    )
    assert filled_v2["status"] == "FILLED"
    after_v2 = validate_success(api.get_batch(batch_id, PRODUCTION_PLANNER))
    assert after_v2["available_quantity_sqm"] == 700.00

    released_v1 = validate_success(api.release_allocation(al_v1["id"], headers))
    assert released_v1["status"] == "RELEASED"
    released_v2 = validate_success(api.release_allocation(al_v2["id"], headers))
    assert released_v2["status"] == "RELEASED"

    end = validate_success(api.get_batch(batch_id, PRODUCTION_PLANNER))
    assert end["available_quantity_sqm"] == 1200.00
    assert end["quantity_sqm"] == 1200.00
    assert end["status"] == "IN_STOCK"


def test_allocation_release_voids_lines_with_allocation_released_reason(api):
    """Release voids the drawn lines with ALLOCATION_RELEASED and zeroes the totals.

    "Every `ACTIVE` line becomes `VOIDED` with `void_reason`
    `ALLOCATION_RELEASED` and its `quantity_sqm` is added back to its batch's
    `available_quantity_sqm`, restoring the stock ledger exactly;
    `allocated_quantity_sqm` and `upgrade_cost_total_cents` both become 0, and
    every touched batch has its `version` advanced."
    "Each line's `upgrade_cost_delta_cents` is 0 when its `substitution_kind` is
    `EXACT`."
    "A batch's allocation lines are readable in the reverse direction,
    filterable by line `status`."

    Design: Difficulty/compensating_invariant/physical_stock_area_conserved_across_fill_and_release
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_stock_batch(api)
    batch_id = built["batch"]["id"]
    distributor = create_distributor(api)
    headers = distributor_headers(distributor["id"])
    al_v1 = create_allocation(
        api,
        distributor["id"],
        built["sku"]["id"],
        allocation_code="AL-V1",
        requested_quantity_sqm=300.00,
        substitution_policy="STRICT_SKU",
    )
    al_v2 = create_allocation(
        api,
        distributor["id"],
        built["sku"]["id"],
        allocation_code="AL-V2",
        requested_quantity_sqm=200.00,
        substitution_policy="STRICT_SKU",
    )
    validate_success(
        api.fill_allocation(al_v1["id"], fill_payload(al_v1["version"]), headers)
    )
    validate_success(
        api.fill_allocation(al_v2["id"], fill_payload(al_v2["version"]), headers)
    )

    released_v1 = validate_success(api.release_allocation(al_v1["id"], headers))
    assert released_v1["status"] == "RELEASED"
    assert released_v1["allocated_quantity_sqm"] == 0.00
    assert released_v1["upgrade_cost_total_cents"] == 0

    lines, meta = validate_paginated(api.list_allocation_lines(al_v1["id"], headers))
    assert meta["total_count"] == 1
    assert lines[0]["status"] == "VOIDED"
    assert lines[0]["void_reason"] == "ALLOCATION_RELEASED"

    released_v2 = validate_success(api.release_allocation(al_v2["id"], headers))
    assert released_v2["allocated_quantity_sqm"] == 0.00
    assert released_v2["upgrade_cost_total_cents"] == 0

    _active, active_meta = validate_paginated(
        api.list_batch_allocation_lines(
            batch_id, PRODUCTION_PLANNER, params={"status": "ACTIVE"}
        )
    )
    assert active_meta["total_count"] == 0
