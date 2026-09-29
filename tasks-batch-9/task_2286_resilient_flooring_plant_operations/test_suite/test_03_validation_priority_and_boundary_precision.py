"""Band-order precedence and inclusive-boundary precision.

These tests exercise the four band interactions PRD §2.5 names explicitly — the
allocation fill (PRD §3.8), SKU certification (PRD §3.5), run scheduling
(PRD §3.6) and recipe review (PRD §3.1, §2.8) — always staging both competing
violations at once and then isolating the lower-precedence one so that it is
proven reachable. The remaining tests pin the inclusive edges of the compounding
approval gates (PRD §3.1), the changeover buffer (PRD §3.6), the zero-output
completion rule (PRD §3.6, §3.7) and laboratory grading (PRD §3.4).
"""

from test_helpers import (
    ApiErrorId,
    CLOCK_BOOT_UTC,
    FORMULATOR,
    PLANT_ADMIN,
    PRODUCTION_PLANNER,
    QA_TECHNICIAN,
    TECHNICAL_DIRECTOR,
    UserRole,
    add_component,
    begin_testing,
    build_approved_formulation,
    build_certified_sku,
    build_licensed_film,
    build_passed_panel,
    build_released_sku,
    build_sku,
    build_user_headers,
    create_allocation,
    create_distributor,
    create_formulation,
    create_panel,
    create_press_line,
    create_print_film,
    create_raw_material,
    create_run,
    create_sku,
    distributor_headers,
    fill_payload,
    get_success_data,
    production_run_payload,
    release_allocation,
    review_decision_payload,
    review_formulation,
    revision_payload,
    run_completion_payload,
    set_clock,
    set_material_status,
    setup_run,
    start_panel,
    start_run,
    submit_formulation,
    test_result_payload as measurement_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# The plasticiser used by the F-STD recipe and by the segregation-of-duties
# recipe. Its properties are supplied explicitly so the blend arithmetic of
# PRD 3.1 is fully determined by the test.
RM_PLAST = {
    "name": "DINP plasticiser",
    "category": "PLASTICIZER",
    "cost_per_kg_cents": 240,
    "indentation_index": 35,
    "thermal_stability_index": 40,
    "plasticizer_migration_index": 62,
    "max_phr": 60,
}

# Readings that PASS every one of SKU-B's five required test types: the
# indentation limit is 0.10 for a CLASS_34_43 recipe, the dimensional-stability
# limit is 0.15 for a click-lock construction, the slip limit is 0.42 for a
# waterproof SKU, the peel limit is 35.0 for IXPE_1MM and the lock-shear limit
# is SKU-B's own 1.20 target (PRD 3.4).
SKU_B_PASSING_RESULTS = (
    ("RESIDUAL_INDENTATION", 0.08),
    ("DIMENSIONAL_STABILITY_HEAT", 0.10),
    ("SLIP_RESISTANCE", 0.55),
    ("PEEL_ADHESION_DELAMINATION", 40.0),
    ("LOCK_SHEAR", 1.50),
)

DUAL_ROLE_USER_ID = "td-dual"


# ---------------------------------------------------------------------------
# Shared staging helpers. Every test calls one and owns all of its own state.
# ---------------------------------------------------------------------------


def _stage_released_sku_without_stock(api):
    """RELEASED SKU-A, a distributor, and no completed run anywhere."""
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_released_sku(api)
    built["distributor"] = create_distributor(api)
    return built


def _stage_testing_sku_on_superseded_recipe(api):
    """SKU-A in TESTING whose recipe F-MIN has been driven to SUPERSEDED."""
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_sku(api)
    begin_testing(api, built["sku"]["id"])
    parent = get_success_data(
        api.get_formulation(built["formulation"]["id"], FORMULATOR)
    )
    revision = get_success_data(
        api.create_formulation_revision(
            parent["id"], revision_payload("F-MIN-R2", parent["version"]), FORMULATOR
        )
    )
    submit_formulation(api, revision["id"])
    approved_revision = review_formulation(api, revision["id"], "APPROVE")
    assert approved_revision["status"] == "APPROVED", (
        "setup: the revision must be APPROVED so that F-MIN is superseded"
    )
    built["revision"] = approved_revision
    return built


def _stage_licence_reserved_at_1200(api):
    """LIC-OAK with 1200.00 reserved by RUN-A1, plus SKU-C on a second film."""
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_certified_sku(api)
    built["press_line"] = create_press_line(api)
    built["run_a1"] = create_run(
        api, built["sku"]["id"], built["press_line"]["id"]
    )
    built["film2"] = create_print_film(
        api,
        built["license"]["id"],
        design_code="PF-OAK-1800",
        pattern_repeat_mm_length=1800.0,
        pattern_repeat_mm_width=300.0,
        registration_tolerance_mm=0.30,
        emboss_plate_code="EMB-OAK-B",
        emboss_alignment_offset_mm=0.12,
        master_roll_sets=2,
    )
    built["sku_c"] = create_sku(
        api,
        built["formulation"]["id"],
        built["film2"]["id"],
        sku_code="SKU-C",
        construction_type="GLUE_DOWN",
        wear_layer_mil=12,
        overall_thickness_mm=2.5,
        royalty_basis_price_cents_per_sqm=2100,
        target_margin_bps=3500,
    )
    begin_testing(api, built["sku_c"]["id"])
    return built


def _stage_author_reviewer_over_restricted_material(api):
    """F-SOD UNDER_REVIEW, authored by td-dual, dosing a RESTRICTED material."""
    set_clock(api, CLOCK_BOOT_UTC)
    author_headers = build_user_headers(DUAL_ROLE_USER_ID, UserRole.FORMULATOR.value)
    resin = create_raw_material(api, "RM-RESIN")
    plast = create_raw_material(api, "RM-PLAST", **RM_PLAST)
    recipe = create_formulation(api, "F-SOD", author_headers)
    add_component(api, recipe["id"], resin["id"], 100, author_headers)
    add_component(api, recipe["id"], plast["id"], 30, author_headers)
    submitted = submit_formulation(api, recipe["id"], author_headers)
    restricted = set_material_status(api, plast["id"], "RESTRICTED")
    return {
        "recipe": recipe,
        "submitted": submitted,
        "material": restricted,
        "author_headers": author_headers,
    }


def _submit_single_resin_recipe(api, code, material_code, **properties):
    """One VINYL_RESIN material dosed at 100 phr into one UNDER_REVIEW recipe."""
    material = create_raw_material(
        api, material_code, category="VINYL_RESIN", max_phr=100, **properties
    )
    recipe = create_formulation(api, code)
    add_component(api, recipe["id"], material["id"], 100)
    return submit_formulation(api, recipe["id"])


def _stage_run_a1_and_click_lock_sku_b(api):
    """RUN-A1 planned on PL-1 plus PROVISIONAL SKU-B on an unrelated recipe."""
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_approved_formulation(api)
    materials = built["materials"]
    plast = create_raw_material(api, "RM-PLAST", **RM_PLAST)
    filler = create_raw_material(api, "RM-FILLER")
    f_std = create_formulation(api, "F-STD")
    add_component(api, f_std["id"], materials["RM-RESIN"]["id"], 100)
    add_component(api, f_std["id"], plast["id"], 22)
    add_component(api, f_std["id"], filler["id"], 240)
    add_component(api, f_std["id"], materials["RM-STAB"]["id"], 3)
    submit_formulation(api, f_std["id"])
    f_std = review_formulation(api, f_std["id"], "APPROVE")
    assert f_std["status"] == "APPROVED", "setup: F-STD must be APPROVED"

    licensed = build_licensed_film(api)
    sku_a = create_sku(
        api, built["formulation"]["id"], licensed["film"]["id"]
    )
    begin_testing(api, sku_a["id"])
    press_line = create_press_line(api)
    run_a1 = create_run(api, sku_a["id"], press_line["id"])

    film2 = create_print_film(
        api,
        licensed["license"]["id"],
        design_code="PF-OAK-1800",
        pattern_repeat_mm_length=1800.0,
        pattern_repeat_mm_width=300.0,
        registration_tolerance_mm=0.30,
        emboss_plate_code="EMB-OAK-B",
        emboss_alignment_offset_mm=0.12,
        master_roll_sets=2,
    )
    sku_b = create_sku(
        api,
        f_std["id"],
        film2["id"],
        sku_code="SKU-B",
        construction_type="CLICK_LOCK_SPC",
        wear_layer_mil=20,
        overall_thickness_mm=5.0,
        waterproof_rated=True,
        attached_underlayment_type="IXPE_1MM",
        profile_family="UNILIN_5G",
        tongue_thickness_target_mm=2.00,
        tolerance_plus_mm=0.15,
        tolerance_minus_mm=0.10,
        target_lock_shear_n_per_mm=1.20,
        royalty_basis_price_cents_per_sqm=3200,
        target_margin_bps=4000,
    )
    begin_testing(api, sku_b["id"])
    panel = build_passed_panel(
        api, sku_b["id"], results=SKU_B_PASSING_RESULTS, panel_code="TP-B"
    )
    return {
        "formulation": built["formulation"],
        "f_std": f_std,
        "license": licensed["license"],
        "film": licensed["film"],
        "film2": film2,
        "sku_a": sku_a,
        "sku_b": sku_b,
        "press_line": press_line,
        "run_a1": run_a1,
        "panel": panel["panel"],
    }


def _stage_running_run_a1(api):
    """CERTIFIED SKU-A with RUN-A1 RUNNING on PL-1 and 1200.00 reserved."""
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_certified_sku(api)
    built["press_line"] = create_press_line(api)
    run = create_run(api, built["sku"]["id"], built["press_line"]["id"])
    setup_run(api, run["id"])
    built["run"] = start_run(api, run["id"])
    assert built["run"]["run_status"] == "RUNNING", "setup: RUN-A1 must be RUNNING"
    return built


def _stage_testing_sku_with_started_panel(api, panel_code):
    """SKU-A in TESTING on a CLASS_34_43 recipe with one IN_TEST panel."""
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_sku(api)
    begin_testing(api, built["sku"]["id"])
    panel = create_panel(api, built["sku"]["id"], panel_code)
    built["panel"] = start_panel(api, panel["id"])
    assert built["panel"]["status"] == "IN_TEST", "setup: the panel must be IN_TEST"
    return built


# ---------------------------------------------------------------------------
# CONFLICT A -- own-entity state (band 7) over business referential (band 14).
# ---------------------------------------------------------------------------


def test_released_allocation_fill_over_empty_pool_returns_allocation_state_error(api):
    """A RELEASED allocation filled against an empty candidate pool answers band 7.

    "Because a single request often breaks several rules at once, the server evaluates validations in a strict ascending order of fifteen bands and **stops at the first violation**; no later band is evaluated, and the response carries only that first rule's error."
    "Filling an allocation that has already been released or cancelled against an empty candidate pool returns `ERR_INVALID_ALLOCATION_STATE` (band 7), not `ERR_NO_ELIGIBLE_BATCH` (band 14)."
    "The allocation must not be `RELEASED` or `CANCELLED`; either is `ERR_INVALID_ALLOCATION_STATE` (HTTP 409)."
    "A batch is the plant's unit of traceability, and it is never created by a client."
    "Releasing an allocation that never drew anything simply moves it to `RELEASED` with nothing to void."
    "If the candidate set is empty, the fill is refused with `ERR_NO_ELIGIBLE_BATCH` (HTTP 409) and the allocation is left completely untouched."

    Design: Difficulty/priority_pair_validation_conflict/allocation_own_state_beats_no_eligible_batch_referential
    """
    built = _stage_released_sku_without_stock(api)
    distributor_id = built["distributor"]["id"]
    headers = distributor_headers(distributor_id)

    allocation = create_allocation(
        api,
        distributor_id,
        built["sku"]["id"],
        allocation_code="AL-P1",
        requested_quantity_sqm=100.00,
        substitution_policy="STRICT_SKU",
    )
    released = release_allocation(api, allocation["id"], distributor_id)
    assert released["status"] == "RELEASED"

    # Band 14 is genuinely live for this request too: no run has completed, so
    # no batch exists and the candidate set of step one is empty.
    _, batch_meta = validate_paginated(api.list_batches(headers, params={"limit": 100}))
    assert batch_meta["total_count"] == 0

    current = get_success_data(api.get_allocation(allocation["id"], headers))
    response = api.fill_allocation(
        allocation["id"], fill_payload(current["version"]), headers
    )
    validate_error(response, ApiErrorId.INVALID_ALLOCATION_STATE.value)

    after = get_success_data(api.get_allocation(allocation["id"], headers))
    assert after["status"] == "RELEASED"
    assert after["allocated_quantity_sqm"] == 0


def test_open_allocation_fill_over_empty_pool_returns_no_eligible_batch(api):
    """With band 7 satisfied the same empty candidate pool surfaces band 14.

    "If the candidate set is empty, the fill is refused with `ERR_NO_ELIGIBLE_BATCH` (HTTP 409) and the allocation is left completely untouched."
    "A batch is a candidate only when its `status` is `IN_STOCK`, its `available_quantity_sqm` is strictly greater than zero, its producing run's `qc_disposition` is `RELEASED`, and its own SKU's `commercial_status` is not `DISCONTINUED`."
    "A new allocation is `OPEN` with `allocated_quantity_sqm` and `upgrade_cost_total_cents` both 0."
    "Most resources additionally carry `updated_at`, in the same format, refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row — including mutations the caller did not directly request, such as a cascade reaching the row from a neighbouring entity."

    Design: Difficulty/priority_pair_validation_conflict/allocation_own_state_beats_no_eligible_batch_referential
    """
    built = _stage_released_sku_without_stock(api)
    distributor_id = built["distributor"]["id"]
    headers = distributor_headers(distributor_id)

    allocation = create_allocation(
        api,
        distributor_id,
        built["sku"]["id"],
        allocation_code="AL-P2",
        requested_quantity_sqm=100.00,
        substitution_policy="STRICT_SKU",
    )
    assert allocation["status"] == "OPEN"

    response = api.fill_allocation(
        allocation["id"], fill_payload(allocation["version"]), headers
    )
    validate_error(response, ApiErrorId.NO_ELIGIBLE_BATCH.value)

    after = get_success_data(api.get_allocation(allocation["id"], headers))
    assert after["status"] == "OPEN"
    assert after["allocated_quantity_sqm"] == 0
    assert after["version"] == allocation["version"]


# ---------------------------------------------------------------------------
# CONFLICT B -- business safety (band 11) over business referential (band 14).
# ---------------------------------------------------------------------------


def test_certify_without_coverage_on_superseded_recipe_returns_coverage_error(api):
    """Missing coverage outranks the superseded recipe on certification.

    "Certifying a SKU that both lacks passing test coverage and whose recipe has been superseded returns `ERR_TEST_COVERAGE_INCOMPLETE` (band 11), not `ERR_FORMULATION_NOT_APPROVED` (band 14)."
    "Its central precondition is complete coverage: for **every** test type in the SKU's required set there must exist a measurement graded `PASS` that was recorded at its panel's current `attempt_no`, on a panel belonging to this SKU whose `status` is `PASSED`. Any required type without such a qualifying measurement is `ERR_TEST_COVERAGE_INCOMPLETE` (HTTP 422), and as noted in §2.5 that error is returned even when the SKU's recipe has meanwhile been superseded."
    "Fourth, if the recipe carries a `supersedes_formulation_id`, the referenced predecessor moves `APPROVED → SUPERSEDED`, and because that predecessor became superseded, every SKU whose `formulation_id` points at it has `pin_stale` set to true."
    "On certification, the SKU pins what it was certified against and stamps its cost."
    "`standard_cost_cents_per_sqm` is computed on the pinned basis described in §3.3 and stored, and `list_price_cents_per_sqm` is derived from it by the `target_margin_bps` gross-up."

    Design: Difficulty/priority_pair_validation_conflict/test_coverage_safety_beats_formulation_referential_on_certify
    """
    built = _stage_testing_sku_on_superseded_recipe(api)
    sku_id = built["sku"]["id"]

    parent = get_success_data(
        api.get_formulation(built["formulation"]["id"], FORMULATOR)
    )
    assert parent["status"] == "SUPERSEDED"

    before = get_success_data(api.get_product_sku(sku_id, PLANT_ADMIN))
    assert before["certification_status"] == "TESTING"
    assert before["pin_stale"] is True
    _, panel_meta = validate_paginated(
        api.list_test_panels(QA_TECHNICIAN, params={"sku_id": sku_id})
    )
    assert panel_meta["total_count"] == 0

    response = api.certify_sku(sku_id, TECHNICAL_DIRECTOR)
    validate_error(response, ApiErrorId.TEST_COVERAGE_INCOMPLETE.value)

    after = get_success_data(api.get_product_sku(sku_id, PLANT_ADMIN))
    assert after["certification_status"] == "TESTING"
    assert after["standard_cost_cents_per_sqm"] is None
    assert after["certified_at"] is None


def test_certify_with_complete_coverage_on_superseded_recipe_returns_recipe_error(api):
    """Once coverage is complete the superseded recipe becomes the answer.

    "Otherwise, if coverage is complete and every outcome at that attempt is `PASS`, the panel moves `IN_TEST → PASSED`."
    "A panel that reaches `PASSED` whose coverage includes both `RESIDUAL_INDENTATION` and `DIMENSIONAL_STABILITY_HEAT` moves the SKU's certification `TESTING → PROVISIONAL`."
    "Certification is a `TechnicalDirector` action reachable from `TESTING` or `PROVISIONAL` — `certification_status` `TESTING → CERTIFIED` and `PROVISIONAL → CERTIFIED` are treated identically."
    "The SKU's recipe must be `APPROVED` and the grant behind its film must be `ACTIVE`."
    "Certifying a SKU that both lacks passing test coverage and whose recipe has been superseded returns `ERR_TEST_COVERAGE_INCOMPLETE` (band 11), not `ERR_FORMULATION_NOT_APPROVED` (band 14)."
    "the SKU's recipe must be `APPROVED`, or the request fails with `ERR_FORMULATION_NOT_APPROVED` (HTTP 409)"
    "`standard_cost_cents_per_sqm` is computed on the pinned basis described in §3.3 and stored, and `list_price_cents_per_sqm` is derived from it by the `target_margin_bps` gross-up."

    Design: Difficulty/priority_pair_validation_conflict/test_coverage_safety_beats_formulation_referential_on_certify
    """
    built = _stage_testing_sku_on_superseded_recipe(api)
    sku_id = built["sku"]["id"]

    covered = build_passed_panel(api, sku_id, panel_code="TP-CB")
    assert covered["panel"]["status"] == "PASSED"

    parent = get_success_data(
        api.get_formulation(built["formulation"]["id"], FORMULATOR)
    )
    assert parent["status"] == "SUPERSEDED"
    before = get_success_data(api.get_product_sku(sku_id, PLANT_ADMIN))
    assert before["certification_status"] == "PROVISIONAL"

    response = api.certify_sku(sku_id, TECHNICAL_DIRECTOR)
    validate_error(response, ApiErrorId.FORMULATION_NOT_APPROVED.value)

    after = get_success_data(api.get_product_sku(sku_id, PLANT_ADMIN))
    assert after["certification_status"] == "PROVISIONAL"
    assert after["standard_cost_cents_per_sqm"] is None


# ---------------------------------------------------------------------------
# CONFLICT C -- business temporal (band 13) over business fiscal (band 15).
# ---------------------------------------------------------------------------


def test_overlapping_run_over_volume_cap_returns_window_conflict(api):
    """A run that both overlaps a window and breaks the cap answers band 13.

    "Scheduling a run that both overlaps an existing window on the line and would break the licensed volume ceiling returns `ERR_PRESS_LINE_WINDOW_CONFLICT` (band 13), not `ERR_LICENSE_VOLUME_CAP_EXCEEDED` (band 15)."
    "**Line occupation** treats a run's window as half-open, from `planned_start_utc` inclusive to `planned_end_utc` exclusive. Two runs on the same line collide when the new run's start is strictly earlier than the other's end **and** the other's start is strictly earlier than the new run's end, counting only runs whose `run_status` is not `ABORTED`."
    "A collision is `ERR_PRESS_LINE_WINDOW_CONFLICT` (HTTP 409)."
    "The grant's projected volume is its `consumed_volume_sqm` plus its `reserved_volume_sqm` plus the new run's `planned_quantity_sqm`, and that projection may not exceed `term_volume_cap_sqm`; equality is admitted, and an excess is `ERR_LICENSE_VOLUME_CAP_EXCEEDED` (HTTP 422)."
    "On success, the run's `planned_quantity_sqm` is added to the grant's `reserved_volume_sqm` and the grant's `version` is advanced."

    Design: Difficulty/priority_pair_validation_conflict/press_window_temporal_beats_license_volume_fiscal
    """
    built = _stage_licence_reserved_at_1200(api)
    licence = get_success_data(api.get_design_license(built["license"]["id"], PLANT_ADMIN))
    assert licence["term_volume_cap_sqm"] == 2000.00
    assert licence["reserved_volume_sqm"] == 1200.00
    assert licence["consumed_volume_sqm"] == 0

    # [05:00, 07:00) sits strictly inside RUN-A1's [01:00, 09:00) window, and
    # 0.00 + 1200.00 + 900.00 == 2100.00 is past the 2000.00 cap.
    response = api.create_production_run(
        production_run_payload(
            built["sku_c"]["id"],
            built["press_line"]["id"],
            run_code="RUN-C-OVERLAP",
            planned_start_utc="2026-08-01T05:00:00Z",
            planned_end_utc="2026-08-01T07:00:00Z",
            planned_quantity_sqm=900.00,
        ),
        PRODUCTION_PLANNER,
    )
    validate_error(response, ApiErrorId.PRESS_LINE_WINDOW_CONFLICT.value)

    after = get_success_data(api.get_design_license(built["license"]["id"], PLANT_ADMIN))
    assert after["reserved_volume_sqm"] == 1200.00
    assert after["consumed_volume_sqm"] == 0


def test_disjoint_run_over_volume_cap_returns_license_volume_cap_exceeded(api):
    """With the window clean the identical quantity answers band 15.

    "The grant's projected volume is its `consumed_volume_sqm` plus its `reserved_volume_sqm` plus the new run's `planned_quantity_sqm`, and that projection may not exceed `term_volume_cap_sqm`; equality is admitted, and an excess is `ERR_LICENSE_VOLUME_CAP_EXCEEDED` (HTTP 422)."
    "Touching endpoints therefore do not collide: a run beginning exactly at another's `planned_end_utc` is disjoint and admissible."
    "Otherwise, take the line's `changeover_minutes` and apply a relatedness multiplier: 0.50 when the predecessor's SKU shares this SKU's `formulation_id`, 0.75 when it instead shares this SKU's `print_film_id`, and 1.00 when it shares neither."
    "Round the multiplied base **up** to a whole minute, and only then add a thickness surcharge: 30 minutes when the absolute difference between the two SKUs' `overall_thickness_mm` values is at least 2.0 millimetres, 10 minutes when that difference is at least 0.5 but below 2.0, and nothing below 0.5."
    "This is a forward-looking projection: volume merely reserved by runs in `PLANNED`, `SETUP` or `RUNNING` counts against the cap even though nothing has physically been produced, which is exactly what makes an admission fail on a grant that has produced nothing at all."

    Design: Difficulty/priority_pair_validation_conflict/press_window_temporal_beats_license_volume_fiscal
    """
    built = _stage_licence_reserved_at_1200(api)

    # [10:00, 12:00) is disjoint from RUN-A1 and the required changeover gap is
    # CEIL(60 * 0.50) + 0 == 30 minutes against an actual 60, so band 13 is
    # clean and only the fiscal projection 1200.00 + 900.00 > 2000.00 remains.
    response = api.create_production_run(
        production_run_payload(
            built["sku_c"]["id"],
            built["press_line"]["id"],
            run_code="RUN-C-DISJOINT",
            planned_start_utc="2026-08-01T10:00:00Z",
            planned_end_utc="2026-08-01T12:00:00Z",
            planned_quantity_sqm=900.00,
        ),
        PRODUCTION_PLANNER,
    )
    validate_error(response, ApiErrorId.LICENSE_VOLUME_CAP_EXCEEDED.value)

    after = get_success_data(api.get_design_license(built["license"]["id"], PLANT_ADMIN))
    assert after["reserved_volume_sqm"] == 1200.00
    assert after["consumed_volume_sqm"] == 0


def test_disjoint_run_exactly_at_volume_cap_is_admitted(api):
    """A projection landing exactly on the cap is admitted and reserves.

    "The grant's projected volume is its `consumed_volume_sqm` plus its `reserved_volume_sqm` plus the new run's `planned_quantity_sqm`, and that projection may not exceed `term_volume_cap_sqm`; equality is admitted, and an excess is `ERR_LICENSE_VOLUME_CAP_EXCEEDED` (HTTP 422)."
    "On success, the run's `planned_quantity_sqm` is added to the grant's `reserved_volume_sqm` and the grant's `version` is advanced."
    "The run is created with `run_status` `PLANNED` and `qc_disposition` `PENDING`, with `changeover_minutes_applied` null, `actual_quantity_sqm` 0, `royalty_accrued_cents` 0, and every measured and derived quality field null."
    "The gap in whole minutes from the predecessor's `planned_end_utc` to the new run's `planned_start_utc` must be at least that required figure; equality passes, and a shortfall is `ERR_CHANGEOVER_GAP_INSUFFICIENT` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/press_window_temporal_beats_license_volume_fiscal
    """
    built = _stage_licence_reserved_at_1200(api)

    # 0.00 + 1200.00 + 800.00 == 2000.00 exactly.
    response = api.create_production_run(
        production_run_payload(
            built["sku_c"]["id"],
            built["press_line"]["id"],
            run_code="RUN-C-FITS",
            planned_start_utc="2026-08-01T10:00:00Z",
            planned_end_utc="2026-08-01T12:00:00Z",
            planned_quantity_sqm=800.00,
        ),
        PRODUCTION_PLANNER,
    )
    run = validate_success(response, 201)
    assert run["run_status"] == "PLANNED"
    assert run["qc_disposition"] == "PENDING"
    assert run["planned_quantity_sqm"] == 800.00
    assert run["changeover_minutes_applied"] is None

    after = get_success_data(api.get_design_license(built["license"]["id"], PLANT_ADMIN))
    assert after["reserved_volume_sqm"] == 2000.00
    assert after["consumed_volume_sqm"] == 0


# ---------------------------------------------------------------------------
# CONFLICT D -- segregation of duties (band 9) over referential (band 14).
# ---------------------------------------------------------------------------


def test_author_reviewing_recipe_with_restricted_material_returns_sod(api):
    """The author's own review answers band 9, not the restricted material.

    "A recipe's own author reviewing a recipe that also contains a no-longer-active raw material returns `ERR_SEGREGATION_OF_DUTIES` (band 9), not `ERR_RAW_MATERIAL_NOT_ACTIVE` (band 14)."
    "All four return `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and all four are evaluated in band 9 — after concurrency and before any cross-entity state check."
    "A recipe review decision is refused when `X-User-ID` equals the recipe's `authored_by_user_id`. Authoring and approving are separated; submitting is not, so the same `Formulator` may author and submit."
    "A newly created recipe is `DRAFT` with `revision` 1, `cost_basis` `LIVE`, `rejection_count` and `open_revision_count` both 0, and `authored_by_user_id` set to the acting `X-User-ID`."
    "Submission is the `Formulator`'s hand-off. It is permitted only from `DRAFT`, taking the recipe `DRAFT → UNDER_REVIEW`, and it stamps `submitted_by_user_id` with the acting user."
    "Moving a material to `RESTRICTED` starts the plant's deepest cascade. Every recipe in `APPROVED` or `SUPERSEDED` that doses the material transitions to `RETIRED` (`APPROVED → RETIRED` or `SUPERSEDED → RETIRED`)."
    "Rejection takes the recipe `UNDER_REVIEW → REJECTED` and increments `rejection_count` by one; nothing else moves, and the recipe remains editable, which is how the revision loop closes."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_raw_material_referential_on_review
    """
    staged = _stage_author_reviewer_over_restricted_material(api)
    recipe_id = staged["recipe"]["id"]
    assert staged["recipe"]["authored_by_user_id"] == DUAL_ROLE_USER_ID
    assert staged["submitted"]["status"] == "UNDER_REVIEW"
    assert staged["material"]["status"] == "RESTRICTED"

    before = get_success_data(api.get_formulation(recipe_id, FORMULATOR))
    assert before["status"] == "UNDER_REVIEW"

    response = api.review_formulation(
        recipe_id,
        review_decision_payload("APPROVE"),
        build_user_headers(DUAL_ROLE_USER_ID, UserRole.TECHNICAL_DIRECTOR.value),
    )
    validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value)

    after = get_success_data(api.get_formulation(recipe_id, FORMULATOR))
    assert after["status"] == "UNDER_REVIEW"
    assert after["rejection_count"] == 0
    assert after["approved_by_user_id"] is None


def test_second_reviewer_of_recipe_with_restricted_material_returns_material_error(api):
    """A different reviewer draws band 14 from the identical stored state.

    "A recipe's own author reviewing a recipe that also contains a no-longer-active raw material returns `ERR_SEGREGATION_OF_DUTIES` (band 9), not `ERR_RAW_MATERIAL_NOT_ACTIVE` (band 14)."
    "Approval is the heaviest single operation in the compounding workflow, and its preconditions are evaluated after the segregation check. Every material on the recipe must still be `ACTIVE`."
    "The material being added must itself be `ACTIVE`; a `RESTRICTED` or `DISCONTINUED` material — or any material already on the recipe that has since left `ACTIVE` — makes the operation fail with `ERR_RAW_MATERIAL_NOT_ACTIVE` (HTTP 409)."
    "Rejection takes the recipe `UNDER_REVIEW → REJECTED` and increments `rejection_count` by one; nothing else moves, and the recipe remains editable, which is how the revision loop closes."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_raw_material_referential_on_review
    """
    staged = _stage_author_reviewer_over_restricted_material(api)
    recipe_id = staged["recipe"]["id"]
    assert staged["material"]["status"] == "RESTRICTED"

    response = api.review_formulation(
        recipe_id, review_decision_payload("APPROVE"), TECHNICAL_DIRECTOR
    )
    validate_error(response, ApiErrorId.RAW_MATERIAL_NOT_ACTIVE.value)

    after = get_success_data(api.get_formulation(recipe_id, FORMULATOR))
    assert after["status"] == "UNDER_REVIEW"
    assert after["rejection_count"] == 0
    assert after["approved_by_user_id"] is None


# ---------------------------------------------------------------------------
# BOUNDARY -- the two inclusive approval floors of PRD 3.1.
# ---------------------------------------------------------------------------


def test_performance_score_exactly_sixty_at_class_floor_is_approvable(api):
    """A score of exactly 60.00 with an index of exactly 70.000000 approves.

    "The `performance_score` is built from three dosage-weighted blend indices, each carried to six decimal places and each computed as the sum over components of `phr` multiplied by the relevant material property, divided by `total_phr`: the blended indentation index uses `indentation_index` directly; the blended thermal index uses `thermal_stability_index` directly; and the blended migration-resistance index uses 100 minus the material's `plasticizer_migration_index`, so that a migration-prone plasticizer drags the blend down."
    "Those three indices are weighted at forty percent, thirty-five percent and twenty-five percent respectively and added together."
    "The `indentation_resistance_class` is derived from the blended indentation index **alone**, never from `performance_score`: the class is `CLASS_34_43` when that index is at least 88.00, `CLASS_33_42` when it is at least 70.00 but below 88.00, and `CLASS_23_31` otherwise."
    "The recipe's `performance_score` must be at least 60.00 — a score below that minimum is `ERR_PERFORMANCE_SCORE_BELOW_MINIMUM` (HTTP 422), and a score of exactly 60.00 is approvable because the threshold is inclusive."
    "Its `indentation_resistance_class` must not be `CLASS_23_31`; the lowest class is `ERR_INDENTATION_CLASS_TOO_LOW` (HTTP 422)."
    "Second, the recipe's `cost_basis` flips to `PINNED` and `blended_cost_per_kg_cents` is re-derived from those snapshots rather than from live material costs."
    "The blended compound cost, `blended_cost_per_kg_cents`, is a dosage-weighted average expressed in whole cents."

    Design: Difficulty/boundary_precision_check/formulation_score_exactly_sixty_and_indentation_class_floor
    """
    set_clock(api, CLOCK_BOOT_UTC)
    # 0.40 * 70 + 0.35 * 40 + 0.25 * (100 - 28) == 60.00 exactly, with a single
    # component at 100 phr so both penalty ratios are 0.0000.
    submitted = _submit_single_resin_recipe(
        api,
        "F-B60",
        "RM-B60",
        name="Boundary resin at sixty",
        cost_per_kg_cents=120,
        indentation_index=70,
        thermal_stability_index=40,
        plasticizer_migration_index=28,
    )
    assert submitted["performance_score"] == 60.00
    assert submitted["indentation_resistance_class"] == "CLASS_33_42"

    approved = review_formulation(api, submitted["id"], "APPROVE")
    assert approved["status"] == "APPROVED"
    assert approved["cost_basis"] == "PINNED"
    assert approved["blended_cost_per_kg_cents"] == 120


def test_performance_score_below_sixty_is_refused_on_approval(api):
    """A score of 59.75 falls under the inclusive 60.00 floor and is refused.

    "The recipe's `performance_score` must be at least 60.00 — a score below that minimum is `ERR_PERFORMANCE_SCORE_BELOW_MINIMUM` (HTTP 422), and a score of exactly 60.00 is approvable because the threshold is inclusive."
    "Those three indices are weighted at forty percent, thirty-five percent and twenty-five percent respectively and added together."
    "The result is clamped to the range 0 through 100, taking whichever of the clamp bounds applies, and only then rounded half up to two decimal places."
    "Rejection takes the recipe `UNDER_REVIEW → REJECTED` and increments `rejection_count` by one; nothing else moves, and the recipe remains editable, which is how the revision loop closes."

    Design: Difficulty/boundary_precision_check/formulation_score_exactly_sixty_and_indentation_class_floor
    """
    set_clock(api, CLOCK_BOOT_UTC)
    # 0.40 * 70 + 0.35 * 40 + 0.25 * (100 - 29) == 59.75.
    submitted = _submit_single_resin_recipe(
        api,
        "F-B59",
        "RM-B59",
        name="Boundary resin just under",
        cost_per_kg_cents=115,
        indentation_index=70,
        thermal_stability_index=40,
        plasticizer_migration_index=29,
    )
    assert submitted["performance_score"] == 59.75

    response = api.review_formulation(
        submitted["id"], review_decision_payload("APPROVE"), TECHNICAL_DIRECTOR
    )
    validate_error(response, ApiErrorId.PERFORMANCE_SCORE_BELOW_MINIMUM.value)

    after = get_success_data(api.get_formulation(submitted["id"], FORMULATOR))
    assert after["status"] == "UNDER_REVIEW"
    assert after["rejection_count"] == 0


def test_score_at_floor_but_index_under_class_floor_returns_class_error(api):
    """An index of 69.000000 fails the class floor even at a score of 60.00.

    "The `indentation_resistance_class` is derived from the blended indentation index **alone**, never from `performance_score`: the class is `CLASS_34_43` when that index is at least 88.00, `CLASS_33_42` when it is at least 70.00 but below 88.00, and `CLASS_23_31` otherwise."
    "Two recipes with an identical score can therefore land in different classes."
    "The recipe's `performance_score` must be at least 60.00 — a score below that minimum is `ERR_PERFORMANCE_SCORE_BELOW_MINIMUM` (HTTP 422), and a score of exactly 60.00 is approvable because the threshold is inclusive."
    "Its `indentation_resistance_class` must not be `CLASS_23_31`; the lowest class is `ERR_INDENTATION_CLASS_TOO_LOW` (HTTP 422). Those two constraints share a band and are evaluated in that order, so a recipe that clears the score but sits in the lowest class returns the class error rather than the score error."

    Design: Difficulty/boundary_precision_check/formulation_score_exactly_sixty_and_indentation_class_floor
    """
    set_clock(api, CLOCK_BOOT_UTC)
    # 0.40 * 69 + 0.35 * 64 + 0.25 * (100 - 60) == 60.00 exactly, while the
    # blended indentation index of 69.000000 is one point under the class floor.
    submitted = _submit_single_resin_recipe(
        api,
        "F-B69",
        "RM-B69",
        name="Boundary resin under class floor",
        cost_per_kg_cents=100,
        indentation_index=69,
        thermal_stability_index=64,
        plasticizer_migration_index=60,
    )
    assert submitted["performance_score"] == 60.00
    assert submitted["indentation_resistance_class"] == "CLASS_23_31"

    response = api.review_formulation(
        submitted["id"], review_decision_payload("APPROVE"), TECHNICAL_DIRECTOR
    )
    validate_error(response, ApiErrorId.INDENTATION_CLASS_TOO_LOW.value)

    after = get_success_data(api.get_formulation(submitted["id"], FORMULATOR))
    assert after["status"] == "UNDER_REVIEW"


# ---------------------------------------------------------------------------
# BOUNDARY -- the changeover buffer at exactly the required gap.
# ---------------------------------------------------------------------------


def test_changeover_gap_one_minute_short_of_ninety_is_refused(api):
    """An 89-minute gap against a required 90 is refused.

    "The relevant predecessor is the run on the same line with the greatest `planned_end_utc` that is no later than the new run's `planned_start_utc` and whose `run_status` is not `ABORTED`, with ties broken by the earlier `created_at`; an aborted predecessor is skipped entirely, so the gap is measured against whatever ran before it."
    "Otherwise, take the line's `changeover_minutes` and apply a relatedness multiplier: 0.50 when the predecessor's SKU shares this SKU's `formulation_id`, 0.75 when it instead shares this SKU's `print_film_id`, and 1.00 when it shares neither."
    "Round the multiplied base **up** to a whole minute, and only then add a thickness surcharge: 30 minutes when the absolute difference between the two SKUs' `overall_thickness_mm` values is at least 2.0 millimetres, 10 minutes when that difference is at least 0.5 but below 2.0, and nothing below 0.5."
    "The gap in whole minutes from the predecessor's `planned_end_utc` to the new run's `planned_start_utc` must be at least that required figure; equality passes, and a shortfall is `ERR_CHANGEOVER_GAP_INSUFFICIENT` (HTTP 409)."
    "On success, the run's `planned_quantity_sqm` is added to the grant's `reserved_volume_sqm` and the grant's `version` is advanced."

    Design: Difficulty/boundary_precision_check/changeover_gap_exactly_required_versus_one_minute_short
    """
    staged = _stage_run_a1_and_click_lock_sku_b(api)
    assert staged["run_a1"]["run_status"] == "PLANNED"

    # RUN-A1 ends at 09:00; a start at 10:29 leaves 89 minutes against the
    # CEIL(60 * 1.00) + 30 == 90 minutes this pairing requires.
    response = api.create_production_run(
        production_run_payload(
            staged["sku_b"]["id"],
            staged["press_line"]["id"],
            run_code="RUN-B-89",
            planned_start_utc="2026-08-01T10:29:00Z",
            planned_end_utc="2026-08-01T12:29:00Z",
            planned_quantity_sqm=300.00,
        ),
        PRODUCTION_PLANNER,
    )
    validate_error(response, ApiErrorId.CHANGEOVER_GAP_INSUFFICIENT.value)

    licence = get_success_data(
        api.get_design_license(staged["license"]["id"], PLANT_ADMIN)
    )
    assert licence["reserved_volume_sqm"] == 1200.00


def test_changeover_gap_exactly_ninety_is_admitted_and_persisted_at_setup(api):
    """A gap of exactly 90 minutes is admitted and stored by setup as 90.

    "The gap in whole minutes from the predecessor's `planned_end_utc` to the new run's `planned_start_utc` must be at least that required figure; equality passes, and a shortfall is `ERR_CHANGEOVER_GAP_INSUFFICIENT` (HTTP 409)."
    "Round the multiplied base **up** to a whole minute, and only then add a thickness surcharge: 30 minutes when the absolute difference between the two SKUs' `overall_thickness_mm` values is at least 2.0 millimetres, 10 minutes when that difference is at least 0.5 but below 2.0, and nothing below 0.5."
    "Setup takes the run `PLANNED → SETUP` and is where the changeover allowance is persisted."
    "The gap computation above is re-evaluated against the current predecessor and stored in `changeover_minutes_applied`."
    "And the logical clock must have reached `planned_start_utc` minus 120 minutes: setup may not begin more than two hours before the planned start, and an early attempt is `ERR_SETUP_TOO_EARLY` (HTTP 409)."
    "The resulting list is stored in the canonical order `RESIDUAL_INDENTATION`, `DIMENSIONAL_STABILITY_HEAT`, `SLIP_RESISTANCE`, `PEEL_ADHESION_DELAMINATION`, `LOCK_SHEAR`, regardless of the order in which the conditions fired."
    "A panel that reaches `PASSED` whose coverage includes both `RESIDUAL_INDENTATION` and `DIMENSIONAL_STABILITY_HEAT` moves the SKU's certification `TESTING → PROVISIONAL`."
    "The residential term is 25 years when `wear_layer_mil` is at least 20, 20 years when it is at least 12 but below 20, 15 years when it is at least 6 but below 12, and 10 years otherwise. The light-commercial term over the same tiers is 15, 10, 5 and 0 years."
    "A bonus of 5 years is added to both terms when — and only when — the SKU is both `waterproof_rated` and built on a `CLICK_LOCK_SPC` or `CLICK_LOCK_WPC` construction; a waterproof `GLUE_DOWN` plank earns nothing. The residential result is then capped at 30 years and stored as `warranty_years`, and the light-commercial result is capped at 20 years and stored as `light_commercial_warranty_years`."
    "On success, the run's `planned_quantity_sqm` is added to the grant's `reserved_volume_sqm` and the grant's `version` is advanced."

    Design: Difficulty/boundary_precision_check/changeover_gap_exactly_required_versus_one_minute_short
    """
    staged = _stage_run_a1_and_click_lock_sku_b(api)
    assert staged["panel"]["required_test_types"] == [
        "RESIDUAL_INDENTATION",
        "DIMENSIONAL_STABILITY_HEAT",
        "SLIP_RESISTANCE",
        "PEEL_ADHESION_DELAMINATION",
        "LOCK_SHEAR",
    ]
    assert staged["panel"]["status"] == "PASSED"
    sku_b = get_success_data(api.get_product_sku(staged["sku_b"]["id"], PLANT_ADMIN))
    assert sku_b["certification_status"] == "PROVISIONAL"
    assert sku_b["warranty_years"] == 30
    assert sku_b["light_commercial_warranty_years"] == 20

    response = api.create_production_run(
        production_run_payload(
            staged["sku_b"]["id"],
            staged["press_line"]["id"],
            run_code="RUN-B-90",
            planned_start_utc="2026-08-01T10:30:00Z",
            planned_end_utc="2026-08-01T12:30:00Z",
            planned_quantity_sqm=300.00,
        ),
        PRODUCTION_PLANNER,
    )
    run = validate_success(response, 201)
    assert run["run_status"] == "PLANNED"
    assert run["changeover_minutes_applied"] is None

    # 10:30 minus the 120-minute setup lead is exactly 08:30.
    set_clock(api, "2026-08-01T08:30:00Z")
    in_setup = setup_run(api, run["id"])
    assert in_setup["run_status"] == "SETUP"
    assert in_setup["changeover_minutes_applied"] == 90

    persisted = get_success_data(api.get_production_run(run["id"], PRODUCTION_PLANNER))
    assert persisted["changeover_minutes_applied"] == 90

    licence = get_success_data(
        api.get_design_license(staged["license"]["id"], PLANT_ADMIN)
    )
    assert licence["reserved_volume_sqm"] == 1500.00


# ---------------------------------------------------------------------------
# BOUNDARY -- zero actual output on completion.
# ---------------------------------------------------------------------------


def test_completion_at_exactly_zero_output_mints_no_batch_and_accrues_nothing(api):
    """Zero output completes the run, mints no batch and accrues no royalty.

    "Fourth, provided `actual_quantity_sqm` is strictly greater than zero, exactly one batch is minted. A run that reports exactly zero output accrues zero royalty and mints no batch at all."
    "Second, the licensed-volume ledger settles on an actual basis: the run's `planned_quantity_sqm` is subtracted from the grant's `reserved_volume_sqm` and the measured `actual_quantity_sqm` is added to its `consumed_volume_sqm`."
    "Third, the run's royalty is accrued. The run's `actual_quantity_sqm` is multiplied by the SKU's `royalty_basis_price_cents_per_sqm` and by the grant's `royalty_rate_bps` divided by 10000, and the product is rounded half up to a whole cent."
    "`pattern_waste_sqm` is the run's `actual_quantity_sqm` multiplied by the larger of the film's two pattern repeats, divided by 60000, multiplied by 0.35, rounded half up to two decimal places."
    "`registration_within_tolerance` holds when the absolute value of `registration_drift_mm` is no greater than the film's `registration_tolerance_mm`."
    "`emboss_within_tolerance` holds when the absolute difference between the run's `emboss_alignment_offset_mm` and the film's nominal `emboss_alignment_offset_mm` is no greater than 0.30 millimetres."
    "The curl allowance is 2.00 millimetres multiplied by the quantity 100 minus the line's `curl_control_index`, divided by 100, rounded half up to two decimal places, and `curl_within_tolerance` holds when the absolute value of `curl_deviation_mm` is no greater than that allowance — so a better-controlled line permits less curl deviation, and a line with a `curl_control_index` of 100 permits none at all."
    "`tongue_within_tolerance` is forced true when the SKU's `profile_family` is `NONE`, ignoring `measured_tongue_thickness_mm` entirely; otherwise it holds when `measured_tongue_thickness_mm` is at least `tongue_thickness_target_mm` minus `tolerance_minus_mm` and no greater than `tongue_thickness_target_mm` plus `tolerance_plus_mm`."
    "`auto_disposition_recommendation` is set to `RELEASED` when all four gates hold and `QUARANTINED` otherwise; it is advisory only."
    "A grant's utilization is readable as a computed summary carrying `term_volume_cap_sqm`, `reserved_volume_sqm`, `consumed_volume_sqm`, the forward-looking `projected_volume_sqm` (consumed plus reserved), the `remaining_volume_sqm` left under the cap (the cap less the projection), the `accrued_royalty_cents` ledger, and `contributing_run_count`, the number of completed runs that have contributed royalty to it."

    Design: Difficulty/boundary_precision_check/zero_actual_quantity_mints_no_batch_and_accrues_no_royalty
    """
    built = _stage_running_run_a1(api)
    run_id = built["run"]["id"]

    completed = validate_success(
        api.complete_production_run(
            run_id,
            run_completion_payload(
                0.00,
                registration_drift_mm=0.10,
                curl_deviation_mm=0.05,
                emboss_alignment_offset_mm=0.15,
                wear_layer_measured_mil=12.0,
            ),
            PRODUCTION_PLANNER,
        )
    )
    assert completed["run_status"] == "COMPLETED"
    assert completed["actual_quantity_sqm"] == 0
    assert completed["royalty_accrued_cents"] == 0
    assert completed["pattern_waste_sqm"] == 0
    assert completed["auto_disposition_recommendation"] == "RELEASED"
    assert completed["registration_within_tolerance"] is True
    assert completed["emboss_within_tolerance"] is True
    assert completed["curl_within_tolerance"] is True
    assert completed["tongue_within_tolerance"] is True

    rows, meta = validate_paginated(
        api.list_batches(QA_TECHNICIAN, params={"production_run_id": run_id})
    )
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
    assert rows == []

    utilization = get_success_data(
        api.get_license_utilization(built["license"]["id"], PRODUCTION_PLANNER)
    )
    assert utilization["reserved_volume_sqm"] == 0
    assert utilization["consumed_volume_sqm"] == 0
    assert utilization["accrued_royalty_cents"] == 0
    assert utilization["projected_volume_sqm"] == 0
    assert utilization["remaining_volume_sqm"] == 2000.00


def test_completion_one_increment_above_zero_mints_a_batch_and_accrues_royalty(api):
    """The smallest positive output crosses the exclusive zero boundary.

    "Fourth, provided `actual_quantity_sqm` is strictly greater than zero, exactly one batch is minted. A run that reports exactly zero output accrues zero royalty and mints no batch at all."
    "Third, the run's royalty is accrued. The run's `actual_quantity_sqm` is multiplied by the SKU's `royalty_basis_price_cents_per_sqm` and by the grant's `royalty_rate_bps` divided by 10000, and the product is rounded half up to a whole cent."
    "Second, the licensed-volume ledger settles on an actual basis: the run's `planned_quantity_sqm` is subtracted from the grant's `reserved_volume_sqm` and the measured `actual_quantity_sqm` is added to its `consumed_volume_sqm`."
    "When a run completes with positive output, the batch is minted with a `batch_code` formed as the producing run's `run_code` followed by the suffix `-B1`, a `production_run_id` pointing at that run, a `sku_id` denormalised from it for stock selection, a `quantity_sqm` equal to the run's `actual_quantity_sqm` that never changes thereafter, an `available_quantity_sqm` of 0, and a `wear_layer_measured_mil` copied from the run's measurement — the reading that will later serve as warranty defect evidence. Its `status` is `IN_PRODUCTION` and `hold_reason` and `held_by_user_id` are null."
    "All quantities in square metres are carried to two decimal places."

    Design: Difficulty/boundary_precision_check/zero_actual_quantity_mints_no_batch_and_accrues_no_royalty
    """
    built = _stage_running_run_a1(api)
    run_id = built["run"]["id"]

    # 0.01 * 2100 * 500 / 10000 == 1.05 cents, rounded half up to 1.
    completed = validate_success(
        api.complete_production_run(
            run_id,
            run_completion_payload(
                0.01,
                registration_drift_mm=0.10,
                curl_deviation_mm=0.05,
                emboss_alignment_offset_mm=0.15,
                wear_layer_measured_mil=12.0,
            ),
            PRODUCTION_PLANNER,
        )
    )
    assert completed["run_status"] == "COMPLETED"
    assert completed["actual_quantity_sqm"] == 0.01
    assert completed["royalty_accrued_cents"] == 1

    rows, meta = validate_paginated(
        api.list_batches(QA_TECHNICIAN, params={"production_run_id": run_id})
    )
    assert meta["total_count"] == 1
    batch = rows[0]
    assert batch["batch_code"] == "RUN-A1-B1"
    assert batch["production_run_id"] == run_id
    assert batch["sku_id"] == built["sku"]["id"]
    assert batch["quantity_sqm"] == 0.01
    assert batch["available_quantity_sqm"] == 0
    assert batch["status"] == "IN_PRODUCTION"
    assert batch["hold_reason"] is None

    utilization = get_success_data(
        api.get_license_utilization(built["license"]["id"], PRODUCTION_PLANNER)
    )
    assert utilization["reserved_volume_sqm"] == 0
    assert utilization["consumed_volume_sqm"] == 0.01
    assert utilization["accrued_royalty_cents"] == 1


# ---------------------------------------------------------------------------
# BOUNDARY -- grading at the spec limit, the marginal edge and one beyond.
# ---------------------------------------------------------------------------


def test_indentation_reading_exactly_on_the_spec_limit_passes(api):
    """0.1000 mm against an inclusive 0.10 limit grades PASS.

    "`RESIDUAL_INDENTATION` is measured in `mm` and lower is better, with a limit of 0.10 when the SKU's recipe sits in `CLASS_34_43`, 0.20 for `CLASS_33_42` and 0.30 for `CLASS_23_31`."
    "For a lower-is-better test the marginal edge is the limit multiplied by 1.05, rounded half up to four decimal places; a `measured_value` no greater than the limit is `PASS`, a value above the limit but no greater than the marginal edge is `MARGINAL`, and anything larger is `FAIL`."
    "Both limits are inclusive, so a reading exactly on the limit passes, and a reading exactly on the marginal edge is `MARGINAL` while one increment beyond it fails."
    "A measurement is created carrying the panel's `test_panel_id`, the `attempt_no` in force when it was taken, the `recorded_by_user_id` of the acting technician, and three server-computed fields: `unit`, `spec_limit` and `outcome`."
    "Each recorded measurement leaves the panel `IN_TEST` while coverage of `required_test_types` at the current `attempt_no` is still incomplete."
    "Every panel requires `RESIDUAL_INDENTATION` and `DIMENSIONAL_STABILITY_HEAT`."
    "A new panel is `SCHEDULED` with `attempt_no` 1, `retest_count` 0, `void_reason` and `started_by_user_id` null, and `required_test_types` derived from the SKU."

    Design: Difficulty/boundary_precision_check/test_result_pass_at_spec_limit_versus_marginal_edge_versus_one_increment_beyond
    """
    built = _stage_testing_sku_with_started_panel(api, "TP-E1")
    assert built["formulation"]["indentation_resistance_class"] == "CLASS_34_43"

    result = validate_success(
        api.record_test_result(
            built["panel"]["id"],
            measurement_payload("RESIDUAL_INDENTATION", 0.1000),
            QA_TECHNICIAN,
        ),
        201,
    )
    assert result["spec_limit"] == 0.10
    assert result["unit"] == "mm"
    assert result["outcome"] == "PASS"

    panel = get_success_data(api.get_test_panel(built["panel"]["id"], QA_TECHNICIAN))
    assert panel["status"] == "IN_TEST"
    assert panel["attempt_no"] == 1

    sku = get_success_data(api.get_product_sku(built["sku"]["id"], PLANT_ADMIN))
    assert sku["certification_status"] == "TESTING"


def test_indentation_reading_exactly_on_the_marginal_edge_is_marginal(api):
    """0.1050 mm is exactly ROUND_HALF_UP(0.10 * 1.05, 4) and grades MARGINAL.

    "Grading uses a marginal band of 500 basis points — five percent — on the permissive side of the limit."
    "For a lower-is-better test the marginal edge is the limit multiplied by 1.05, rounded half up to four decimal places; a `measured_value` no greater than the limit is `PASS`, a value above the limit but no greater than the marginal edge is `MARGINAL`, and anything larger is `FAIL`."
    "Both limits are inclusive, so a reading exactly on the limit passes, and a reading exactly on the marginal edge is `MARGINAL` while one increment beyond it fails."
    "Each recorded measurement leaves the panel `IN_TEST` while coverage of `required_test_types` at the current `attempt_no` is still incomplete."
    "If coverage is complete, no outcome is `FAIL`, and at least one is `MARGINAL`, the panel moves `IN_TEST → RETEST_REQUIRED` and `retest_count` is incremented by one — unconditionally, with no cap applied at this edge."
    "A `MARGINAL` never fails a panel; the only cap in the retest loop lives on the restart, as described above."

    Design: Difficulty/boundary_precision_check/test_result_pass_at_spec_limit_versus_marginal_edge_versus_one_increment_beyond
    """
    built = _stage_testing_sku_with_started_panel(api, "TP-E2")
    assert built["formulation"]["indentation_resistance_class"] == "CLASS_34_43"

    result = validate_success(
        api.record_test_result(
            built["panel"]["id"],
            measurement_payload("RESIDUAL_INDENTATION", 0.1050),
            QA_TECHNICIAN,
        ),
        201,
    )
    assert result["spec_limit"] == 0.10
    assert result["outcome"] == "MARGINAL"

    panel = get_success_data(api.get_test_panel(built["panel"]["id"], QA_TECHNICIAN))
    assert panel["status"] == "IN_TEST"
    assert panel["retest_count"] == 0

    sku = get_success_data(api.get_product_sku(built["sku"]["id"], PLANT_ADMIN))
    assert sku["certification_status"] == "TESTING"


def test_indentation_reading_one_increment_beyond_the_edge_fails_the_panel(api):
    """0.1051 mm is one fourth-decimal increment past the edge and FAILs.

    "For a lower-is-better test the marginal edge is the limit multiplied by 1.05, rounded half up to four decimal places; a `measured_value` no greater than the limit is `PASS`, a value above the limit but no greater than the marginal edge is `MARGINAL`, and anything larger is `FAIL`."
    "Both limits are inclusive, so a reading exactly on the limit passes, and a reading exactly on the marginal edge is `MARGINAL` while one increment beyond it fails."
    "Each recorded measurement leaves the panel `IN_TEST` while coverage of `required_test_types` at the current `attempt_no` is still incomplete. The instant coverage completes, the panel resolves in one of three ways, and a `FAIL` short-circuits the other two: any measurement graded `FAIL` takes the panel `IN_TEST → FAILED` immediately, without waiting for coverage."
    "A panel that reaches `FAILED` collapses the SKU's certification: `TESTING → UNCERTIFIED`, or `PROVISIONAL → SUSPENDED`, or `CERTIFIED → SUSPENDED`."
    "Recording a measurement is permitted only while the panel is `IN_TEST`, and the operation names a `test_type` and a `measured_value` of at least zero with at most four decimal places."

    Design: Difficulty/boundary_precision_check/test_result_pass_at_spec_limit_versus_marginal_edge_versus_one_increment_beyond
    """
    built = _stage_testing_sku_with_started_panel(api, "TP-E3")
    assert built["formulation"]["indentation_resistance_class"] == "CLASS_34_43"

    result = validate_success(
        api.record_test_result(
            built["panel"]["id"],
            measurement_payload("RESIDUAL_INDENTATION", 0.1051),
            QA_TECHNICIAN,
        ),
        201,
    )
    assert result["spec_limit"] == 0.10
    assert result["outcome"] == "FAIL"

    panel = get_success_data(api.get_test_panel(built["panel"]["id"], QA_TECHNICIAN))
    assert panel["status"] == "FAILED"

    sku = get_success_data(api.get_product_sku(built["sku"]["id"], PLANT_ADMIN))
    assert sku["certification_status"] == "UNCERTIFIED"
