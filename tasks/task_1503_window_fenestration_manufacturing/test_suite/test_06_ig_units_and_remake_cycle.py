"""IG unit fabrication, QC gates, and the remake cycle (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    advance_unit_to_gas_filled,
    find_remake_of,
    get_success_data,
    list_line_units,
    lock_and_release,
    produce_line,
    qc_unit,
    setup_order_in_production,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
PL = TEST_USERS["production_lead_headers"]


def test_argon_exactly_min_passes(api):
    """PRD §3.5: "The fill gate requires the measured argon to be at least the
    glass package's `argon_min_pct`; the boundary is inclusive, so an exact
    match passes."
    PRD §3.5: "A unit that clears both gates becomes `QC_PASSED` with its
    `argon_measured_pct` recorded"

    Design: Difficulty/boundary_precision_check/argon_min_boundary_90_passes_89_breaks
    """
    env = setup_order_in_production(quantity=1)
    unit = env["units"][0]
    advance_unit_to_gas_filled(unit["id"])
    passed = qc_unit(unit["id"], 90)  # GP1 argon_min_pct is 90
    assert passed["status"] == "QC_PASSED"
    assert passed["argon_measured_pct"] == 90


def test_argon_one_below_min_breaks(api):
    """PRD §3.5: "A unit that fails either gate becomes `BROKEN` with
    `break_cause` set to `GAS_NONCOMPLIANCE`."
    PRD §3.5: "Both failure paths run the same three-hop cascade. The unit
    becomes `BROKEN`, and a replacement unit is created immediately at `QUEUED`
    with its `remake_of_id` pointing at the broken unit — the auto-remake
    guarantee that keeps the line whole."
    PRD §3.5: "The parent line then drops from `IN_PRODUCTION` to `GLASS_HOLD`
    (hop one), and the wave's allocation is recomputed without the held line
    (hop two)."

    Design: Difficulty/boundary_precision_check/argon_min_boundary_90_passes_89_breaks
    """
    env = setup_order_in_production(quantity=2)
    units = list_line_units(env["line"]["id"])
    advance_unit_to_gas_filled(units[0]["id"])
    advance_unit_to_gas_filled(units[1]["id"])
    qc_unit(units[0]["id"], 90)  # inclusive pass
    failed = validate_success(
        api.qc_check_ig_unit(units[1]["id"], {"argon_measured_pct": 89}, PL), 200
    )
    assert failed["status"] == "BROKEN"
    assert failed["break_cause"] == "GAS_NONCOMPLIANCE"

    remake = find_remake_of(units[1]["id"])
    assert remake["status"] == "QUEUED"
    assert remake["remake_of_id"] == units[1]["id"]

    line = validate_success(api.get_order_line(env["line"]["id"], PL), 200)
    assert line["status"] == "GLASS_HOLD", (
        "one passed sibling does not prevent the hold for the failed unit"
    )


def test_ig_unit_remake_cycle_entity_loop(api):
    """PRD §3.5: "Both failure paths run the same three-hop cascade. The unit
    becomes `BROKEN`, and a replacement unit is created immediately at `QUEUED`
    with its `remake_of_id` pointing at the broken unit — the auto-remake
    guarantee that keeps the line whole."
    PRD §3.5: "Resuming requires the line to actually be `GLASS_HOLD`
    (`ERR_LINE_NOT_ON_GLASS_HOLD`), requires every `BROKEN` unit of the line to
    already have a remake (guaranteed by the auto-remake), and re-admits the
    line into its wave: the wave must be `RELEASED` (`ERR_INVALID_STATE`)"

    Design: Difficulty/non_linear_state_machine/ig_unit_remake_cycle_entity_loop
    """
    env = setup_order_in_production(quantity=1)
    unit = env["units"][0]
    advance_unit_to_gas_filled(unit["id"])

    broken = validate_success(api.report_ig_breakage(
        unit["id"], {"break_cause": "HANDLING"}, PL
    ), 200)
    assert broken["status"] == "BROKEN"

    remake = find_remake_of(unit["id"])
    assert remake["remake_of_id"] == unit["id"]

    # the hold auto-unlocked the wave (allocation fell below half capacity);
    # re-lock and re-release so the wave is RELEASED for the resume gate
    lock_and_release(env["wave"]["id"])
    resumed = validate_success(api.resume_line_production(env["line"]["id"], PL), 200)
    assert resumed["status"] == "IN_PRODUCTION"

    advance_unit_to_gas_filled(remake["id"])
    passed = qc_unit(remake["id"], 96)
    assert passed["status"] == "QC_PASSED"

    original = validate_success(api.get_ig_unit(unit["id"], PL), 200)
    assert original["status"] == "BROKEN", "BROKEN is terminal for the original unit"
    line = validate_success(api.get_order_line(env["line"]["id"], PL), 200)
    assert line["status"] == "COMPLETED"


def test_wave_rerelease_creates_no_duplicate_ig_units(api):
    """PRD §3.4: "Release cascades: each assigned order in `RELEASED` moves to
    `IN_PROGRESS` (orders already `IN_PROGRESS` are untouched), each line in
    `RELEASED` moves to `IN_PRODUCTION`, and insulating glass units are created
    only for the lines that transitioned — one per unit of `quantity`, each
    starting `QUEUED` with `spacer_type` copied from the line's glass package,
    `unit_index` running from 1 through the line's `quantity`, and
    `remake_of_id` null."
    PRD §3.4: "Lines on `GLASS_HOLD` are untouched by release, and re-releasing
    a wave never creates duplicate units for lines already in production."

    Design: Difficulty/non_linear_state_machine/ig_unit_remake_cycle_entity_loop
    """
    env = setup_order_in_production(quantity=1)
    unit = env["units"][0]
    advance_unit_to_gas_filled(unit["id"])
    validate_success(api.report_ig_breakage(unit["id"], {"break_cause": "HANDLING"}, PL), 200)

    # breakage dropped allocation to zero, auto-unlocking RELEASED -> OPEN
    wave = get_success_data(api.get_wave(env["wave"]["id"], PL))
    assert wave["status"] == "OPEN"

    lock_and_release(env["wave"]["id"])  # re-release with the line on GLASS_HOLD
    units = list_line_units(env["line"]["id"])
    assert len(units) == 2, (
        f"re-release must not create duplicate units, found {len(units)}"
    )
    statuses = sorted(u["status"] for u in units)
    assert statuses == ["BROKEN", "QUEUED"]


def test_breakage_remake_conserves_live_ig_count(api):
    """PRD §3.4: "insulating glass units are created only for the lines that
    transitioned — one per unit of `quantity`, each starting `QUEUED` with
    `spacer_type` copied from the line's glass package, `unit_index` running
    from 1 through the line's `quantity`, and `remake_of_id` null."
    PRD §3.5: "The unit becomes `BROKEN`, and a replacement unit is created
    immediately at `QUEUED` with its `remake_of_id` pointing at the broken unit
    — the auto-remake guarantee that keeps the line whole."

    Design: Difficulty/compensating_invariant/breakage_remake_conserves_live_ig_count
    """
    env = setup_order_in_production(quantity=3)
    line_id = env["line"]["id"]
    units = list_line_units(line_id)
    live = [u for u in units if u["status"] not in ("BROKEN", "SCRAPPED")]
    assert len(live) == 3, "release creates exactly one QUEUED unit per quantity"

    victim = units[0]
    validate_success(api.report_ig_breakage(
        victim["id"], {"break_cause": "SHIPPING_DAMAGE"}, PL
    ), 200)

    after = list_line_units(line_id)
    assert len(after) == 4
    broken = [u for u in after if u["status"] == "BROKEN"]
    live_after = [u for u in after if u["status"] not in ("BROKEN", "SCRAPPED")]
    assert len(broken) == 1 and broken[0]["id"] == victim["id"]
    assert len(live_after) == 3, "live unit count is conserved by the auto-remake"
    remake = [u for u in after if u.get("remake_of_id") == victim["id"]]
    assert len(remake) == 1


def test_release_created_units_carry_package_spacer_and_indices(api):
    """PRD §3.4: "insulating glass units are created only for the lines that
    transitioned — one per unit of `quantity`, each starting `QUEUED` with
    `spacer_type` copied from the line's glass package, `unit_index` running
    from 1 through the line's `quantity`, and `remake_of_id` null."

    Design: Difficulty/compensating_invariant/breakage_remake_conserves_live_ig_count
    """
    env = setup_order_in_production(quantity=3)
    units = list_line_units(env["line"]["id"])
    assert len(units) == 3
    assert sorted(u["unit_index"] for u in units) == [1, 2, 3]
    for unit in units:
        assert unit["status"] == "QUEUED"
        assert unit["spacer_type"] == "ALUMINUM"  # copied from the GP1 package
        assert unit["remake_of_id"] is None


def test_qc_check_on_queued_unit_returns_not_ready(api):
    """PRD §3.5: "Quality control happens at the `GAS_FILLED` stage — running
    the check on a unit in any other state is rejected with
    `ERR_IG_NOT_READY_FOR_QC`."

    Design: Corner/state_machines/qc_check_on_queued_unit_returns_not_ready
    """
    env = setup_order_in_production(quantity=1)
    unit = env["units"][0]
    res = api.qc_check_ig_unit(unit["id"], {"argon_measured_pct": 95}, PL)
    validate_error(res, ApiErrorId.ERR_IG_NOT_READY_FOR_QC, expected_status=409)
    after = validate_success(api.get_ig_unit(unit["id"], PL), 200)
    assert after["status"] == "QUEUED"


def test_advance_terminal_broken_unit_returns_invalid_state(api):
    """PRD §3.5: "Every insulating glass unit walks the same production line:
    `QUEUED → GLASS_CUT → SEALED → GAS_FILLED`, one stage per advance by a
    `ProductionLead` or `PlantManager`."
    PRD §2.10: "Any transition attempted from a state in which it is not defined
    is rejected with `ERR_INVALID_STATE` unless a more specific state error
    applies."

    Design: Corner/state_machines/advance_terminal_broken_unit_returns_invalid_state
    """
    env = setup_order_in_production(quantity=1)
    unit = env["units"][0]
    validate_success(api.report_ig_breakage(unit["id"], {"break_cause": "HANDLING"}, PL), 200)

    res = api.advance_ig_unit(unit["id"], PL)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_ig_unit(unit["id"], PL), 200)
    assert after["status"] == "BROKEN"


def test_remake_limit_exceeded_on_fourth_break(api):
    """PRD §3.5: "A remake chain is finite: at most three remakes may descend
    from one original unit, and a breakage or quality-control failure that would
    spawn a fourth is rejected with `ERR_REMAKE_LIMIT_EXCEEDED`."

    Design: Corner/state_machines/remake_limit_exceeded_on_fourth_break
    """
    env = setup_order_in_production(quantity=1)
    wave_id = env["wave"]["id"]
    line_id = env["line"]["id"]
    current = env["units"][0]["id"]

    for _ in range(3):
        validate_success(api.report_ig_breakage(current, {"break_cause": "HANDLING"}, PL), 200)
        current = find_remake_of(current)["id"]
        # the hold auto-unlocked the wave; cycle it back to RELEASED and resume
        lock_and_release(wave_id)
        validate_success(api.resume_line_production(line_id, PL), 200)

    res = api.report_ig_breakage(current, {"break_cause": "HANDLING"}, PL)
    validate_error(res, ApiErrorId.ERR_REMAKE_LIMIT_EXCEEDED, expected_status=409)

    unit = validate_success(api.get_ig_unit(current, PL), 200)
    assert unit["status"] == "QUEUED", "rejected break must not mutate the unit"
    line = validate_success(api.get_order_line(line_id, PL), 200)
    assert line["status"] == "IN_PRODUCTION", "rejected break must not fire the cascade"


def test_ig_advance_blocked_while_line_on_glass_hold(api):
    """PRD §3.5: "Each advance requires the unit's parent line to be
    `IN_PRODUCTION`; advancing a unit whose line is in any other state is
    rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/ig_advance_blocked_while_line_on_glass_hold
    """
    env = setup_order_in_production(quantity=2)
    unit = env["units"][0]
    validate_success(api.report_ig_breakage(unit["id"], {"break_cause": "HANDLING"}, PL), 200)
    remake = find_remake_of(unit["id"])

    res = api.advance_ig_unit(remake["id"], PL)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_ig_unit(remake["id"], PL), 200)
    assert after["status"] == "QUEUED"


def test_ig_advance_succeeds_after_line_resumed(api):
    """PRD §3.5: "Each advance requires the unit's parent line to be
    `IN_PRODUCTION`; advancing a unit whose line is in any other state is
    rejected with `ERR_INVALID_STATE`."
    PRD §3.5: "On success the line returns `GLASS_HOLD → IN_PRODUCTION` and the
    wave's allocation is recomputed with the line counted again."

    Design: Difficulty/cross_entity_state_dependency/ig_advance_blocked_while_line_on_glass_hold
    """
    env = setup_order_in_production(quantity=2)
    unit = env["units"][0]
    validate_success(api.report_ig_breakage(unit["id"], {"break_cause": "HANDLING"}, PL), 200)
    remake = find_remake_of(unit["id"])

    # auto-unlocked wave (allocation 0 < half of 10) must be re-locked/released
    lock_and_release(env["wave"]["id"])
    validate_success(api.resume_line_production(env["line"]["id"], PL), 200)

    advanced = validate_success(api.advance_ig_unit(remake["id"], PL), 200)
    assert advanced["status"] == "GLASS_CUT"


def test_resume_line_not_on_glass_hold_returns_error(api):
    """PRD §3.5: "Resuming requires the line to actually be `GLASS_HOLD`
    (`ERR_LINE_NOT_ON_GLASS_HOLD`), requires every `BROKEN` unit of the line to
    already have a remake (guaranteed by the auto-remake), and re-admits the
    line into its wave: the wave must be `RELEASED` (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/resume_line_not_on_glass_hold_returns_error
    """
    env = setup_order_in_production(quantity=1)
    res = api.resume_line_production(env["line"]["id"], PL)
    validate_error(res, ApiErrorId.ERR_LINE_NOT_ON_GLASS_HOLD, expected_status=409)


def test_ig_units_list_empty_initially(api):
    """PRD §3.4: "insulating glass units are created only for the lines that
    transitioned" (there is no other creation path).
    PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/ig_unit_system_fields_input_ignored
    """
    data, meta = validate_paginated(api.list_ig_units(PL))
    assert data == []
    assert meta["total_count"] == 0
