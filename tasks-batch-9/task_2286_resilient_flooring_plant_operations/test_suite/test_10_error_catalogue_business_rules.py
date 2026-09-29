"""Business-rule refusals across the plant's later validation bands.

These tests drive the quality, uniqueness, referential, temporal and fiscal
gates of the PRD to their declared error codes and, where the same rule has an
admitted side, exercise that side in the same test: the slip-resistance
qualification window of PRD §3.6, the approval constraints of PRD §3.1, the
uniqueness rules of PRD §3.1, the line forming range and licensed-volume ceiling
of PRD §3.6 and §3.2, the allocation fill selector of PRD §3.8, the referential
fitness gates of PRD §3.2, §3.5 and §3.9, and warranty adjudication of PRD §3.9.
"""

from test_helpers import (
    CLICK_LOCK_PASSING_RESULTS,
    CLOCK_BOOT_UTC,
    F_CHALK_COMPONENTS,
    F_STD_COMPONENTS,
    FORMULATOR,
    PLANT_ADMIN,
    PRODUCTION_PLANNER,
    QA_TECHNICIAN,
    TECHNICAL_DIRECTOR,
    WARRANTY_ADJUSTER,
    WARRANTY_ADJUSTER_B,
    ApiErrorId,
    add_component,
    adjudication_payload,
    batch_of_run,
    begin_testing,
    build_approved_formulation,
    build_draft_formulation,
    build_filled_allocation,
    build_licensed_film,
    build_passed_panel,
    build_provisional_sku,
    build_released_sku,
    build_sku,
    build_stock_batch,
    component_payload,
    create_allocation,
    create_click_lock_sku,
    create_distributor,
    create_formulation,
    create_license,
    create_press_line,
    create_print_film,
    create_raw_material,
    create_run,
    create_sku,
    distributor_headers,
    fill_payload,
    formulation_payload,
    get_success_data,
    license_amendment_payload,
    print_film_payload,
    production_run_payload,
    raw_material_payload,
    record_review,
    review_decision_payload,
    run_to_completion,
    set_clock,
    set_film_status,
    set_license_status,
    set_qc_disposition,
    setup_run,
    submit_formulation,
    triage_claim,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_claim_payload,
)


def test_lapsed_slip_qualification_blocks_run_start(api):
    """A waterproof SKU that really qualified is refused at start once the DCOF reading ages out.

    "`SLIP_RESISTANCE` is measured in `DCOF` and higher is better, with a limit
    of 0.42 for a `waterproof_rated` SKU and 0.36 otherwise."
    "`LOCK_SHEAR` is measured in `N_PER_MM`, higher is better, and its limit is
    simply the SKU's `target_lock_shear_n_per_mm`."
    "Otherwise, if coverage is complete and every outcome at that attempt is
    `PASS`, the panel moves `IN_TEST → PASSED`."
    "One safety rule sits here and nowhere else: when the SKU is
    `waterproof_rated`, there must exist a test panel of that SKU whose `status`
    is `PASSED` that both holds a `SLIP_RESISTANCE` measurement graded `PASS` at
    that panel's `attempt_no` and whose `updated_at` is strictly later than the
    logical clock minus 180 days."
    "A SKU that never qualified and a SKU whose slip qualification has aged out
    are both refused with `ERR_SLIP_RESISTANCE_NOT_QUALIFIED` (HTTP 422)."
    "Because the 180-day window is read at start time rather than at scheduling
    time, a run planned comfortably inside the window but started after it
    lapses is rejected, and the qualification must be repeated before the line
    can turn."
    "On success, the run's `planned_quantity_sqm` is added to the grant's
    `reserved_volume_sqm` and the grant's `version` is advanced."

    Design: Corner/errors/lapsed_dcof_qualification_returns_slip_resistance_not_qualified
    """
    set_clock(api, CLOCK_BOOT_UTC)
    formulation = build_approved_formulation(api)["formulation"]
    license_row = create_license(
        api,
        license_code="LIC-WP",
        valid_until="2029-01-01T00:00:00Z",
        term_volume_cap_sqm=5000.00,
    )
    film = create_print_film(
        api,
        license_row["id"],
        design_code="PF-WP-1800",
        pattern_repeat_mm_length=1800,
        pattern_repeat_mm_width=200,
        emboss_plate_code="EP-WP-A",
    )
    sku = create_click_lock_sku(api, formulation["id"], film["id"])
    begin_testing(api, sku["id"])
    panel = build_passed_panel(api, sku["id"], CLICK_LOCK_PASSING_RESULTS, "TP-W1")[
        "panel"
    ]
    assert panel["status"] == "PASSED"

    slip_rows, _ = validate_paginated(
        api.list_test_results(
            panel["id"], QA_TECHNICIAN, params={"test_type": "SLIP_RESISTANCE"}
        )
    )
    assert len(slip_rows) == 1
    assert slip_rows[0]["spec_limit"] == 0.42
    assert slip_rows[0]["outcome"] == "PASS"
    lock_rows, _ = validate_paginated(
        api.list_test_results(
            panel["id"], QA_TECHNICIAN, params={"test_type": "LOCK_SHEAR"}
        )
    )
    assert len(lock_rows) == 1
    assert lock_rows[0]["spec_limit"] == 8.00
    assert lock_rows[0]["outcome"] == "PASS"

    press_line = create_press_line(api)
    run = create_run(
        api,
        sku["id"],
        press_line["id"],
        run_code="RUN-W1",
        planned_start_utc="2027-02-01T01:00:00Z",
        planned_end_utc="2027-02-01T02:00:00Z",
        planned_quantity_sqm=100.00,
    )

    # The panel's updated_at is 2026-08-01; 180 days before the new clock is
    # 2026-08-05T00:30Z, so the qualification has lapsed by the time of start.
    set_clock(api, "2027-02-01T00:30:00Z")
    assert setup_run(api, run["id"])["run_status"] == "SETUP"

    validate_error(
        api.start_production_run(run["id"], PRODUCTION_PLANNER),
        ApiErrorId.SLIP_RESISTANCE_NOT_QUALIFIED.value,
    )

    after = get_success_data(api.get_production_run(run["id"], PRODUCTION_PLANNER))
    assert after["run_status"] == "SETUP"
    utilization = get_success_data(
        api.get_license_utilization(license_row["id"], PRODUCTION_PLANNER)
    )
    assert utilization["reserved_volume_sqm"] == 100.00
    assert utilization["consumed_volume_sqm"] == 0.00


def test_approving_lowest_indentation_class_is_refused_despite_clearing_the_score(api):
    """A chalk-filled recipe clears the 60.00 score floor and is still refused on its class.

    "Those three indices are weighted at forty percent, thirty-five percent and
    twenty-five percent respectively and added together."
    "The brittleness penalty reads the filler ratio — `filler_phr` divided by
    `resin_phr`, also at four decimal places — and is 8 points when that ratio
    is at least 3.00, 3 points when it is at least 2.00 but below 3.00, and zero
    otherwise."
    "The result is clamped to the range 0 through 100, taking whichever of the
    clamp bounds applies, and only then rounded half up to two decimal places."
    "The `indentation_resistance_class` is derived from the blended indentation
    index **alone**, never from `performance_score`: the class is `CLASS_34_43`
    when that index is at least 88.00, `CLASS_33_42` when it is at least 70.00
    but below 88.00, and `CLASS_23_31` otherwise."
    "The recipe's `performance_score` must be at least 60.00 — a score below
    that minimum is `ERR_PERFORMANCE_SCORE_BELOW_MINIMUM` (HTTP 422), and a
    score of exactly 60.00 is approvable because the threshold is inclusive."
    "Its `indentation_resistance_class` must not be `CLASS_23_31`; the lowest
    class is `ERR_INDENTATION_CLASS_TOO_LOW` (HTTP 422)."
    "Those two constraints share a band and are evaluated in that order, so a
    recipe that clears the score but sits in the lowest class returns the class
    error rather than the score error."
    "Rejection takes the recipe `UNDER_REVIEW → REJECTED` and increments
    `rejection_count` by one; nothing else moves, and the recipe remains
    editable, which is how the revision loop closes."

    Design: Corner/errors/approving_a_class_23_31_recipe_returns_indentation_class_too_low
    """
    set_clock(api, CLOCK_BOOT_UTC)
    chalk = build_draft_formulation(api, "F-CHALK", F_CHALK_COMPONENTS)["formulation"]
    assert chalk["performance_score"] == 71.87
    assert chalk["indentation_resistance_class"] == "CLASS_23_31"

    submitted = submit_formulation(api, chalk["id"])
    assert submitted["status"] == "UNDER_REVIEW"

    validate_error(
        api.review_formulation(
            chalk["id"], review_decision_payload("APPROVE"), TECHNICAL_DIRECTOR
        ),
        ApiErrorId.INDENTATION_CLASS_TOO_LOW.value,
    )

    after = get_success_data(api.get_formulation(chalk["id"], TECHNICAL_DIRECTOR))
    assert after["status"] == "UNDER_REVIEW"
    assert after["rejection_count"] == 0


def test_submit_requires_resin_normalised_to_exactly_one_hundred_phr(api):
    """Both failure modes of the normalisation rule: 90.00 phr of resin, and no components.

    "The recipe must have at least one component and its `resin_phr` must be
    exactly 100.00 — a recipe with no components, or one whose resin dosage is
    anything other than exactly 100.00, is refused with
    `ERR_RESIN_PHR_NOT_NORMALIZED` (HTTP 422)."
    "A recipe with no components has `total_phr` of 0.00 and every other derived
    figure null."
    "Submission is the `Formulator`'s hand-off. It is permitted only from
    `DRAFT`, taking the recipe `DRAFT → UNDER_REVIEW`, and it stamps
    `submitted_by_user_id` with the acting user."

    Design: Corner/errors/submit_without_normalised_resin_returns_resin_phr_not_normalized
    """
    set_clock(api, CLOCK_BOOT_UTC)
    resin = create_raw_material(api, "RM-RESIN")

    under_dosed = create_formulation(api, "F-BAD")
    add_component(api, under_dosed["id"], resin["id"], 90.00)
    under_dosed = get_success_data(api.get_formulation(under_dosed["id"], FORMULATOR))
    assert under_dosed["resin_phr"] == 90.00

    empty = create_formulation(api, "F-EMPTY")
    assert empty["total_phr"] == 0.00

    validate_error(
        api.submit_formulation(under_dosed["id"], FORMULATOR),
        ApiErrorId.RESIN_PHR_NOT_NORMALIZED.value,
    )
    validate_error(
        api.submit_formulation(empty["id"], FORMULATOR),
        ApiErrorId.RESIN_PHR_NOT_NORMALIZED.value,
    )

    assert (
        get_success_data(api.get_formulation(under_dosed["id"], FORMULATOR))["status"]
        == "DRAFT"
    )
    assert (
        get_success_data(api.get_formulation(empty["id"], FORMULATOR))["status"]
        == "DRAFT"
    )


def test_duplicate_code_covers_natural_keys_and_a_repeated_material(api):
    """One code serves both collection-level uniqueness and the per-recipe material rule.

    "Each material is registered with a `material_code` that must be unique
    across the library (a repeat is `ERR_DUPLICATE_CODE`, HTTP 409), a trade
    `name`, a `category` naming its formulation role, a purchase cost held as
    `cost_per_kg_cents` in whole cents per kilogram of at least 1, and four
    technical properties: `indentation_index` and `thermal_stability_index`,
    both scored 0 to 100 with higher being better;
    `plasticizer_migration_index`, also 0 to 100 but with higher being *worse*;
    and `max_phr`, strictly greater than zero, the largest
    parts-per-hundred-resin dosage the material may ever take in a recipe."
    "Recipes are authored by a `Formulator`, who supplies a `formulation_code`
    unique across recipes and, when the new recipe is intended to replace an
    existing approved one, the `supersedes_formulation_id` of that predecessor;
    for an original recipe the field is null."
    "Two components on one recipe may not reference the same material: a
    duplicate dosage returns `ERR_DUPLICATE_CODE` (HTTP 409)."

    Design: Corner/errors/duplicate_natural_key_and_repeated_material_return_duplicate_code
    """
    set_clock(api, CLOCK_BOOT_UTC)
    resin = create_raw_material(api, "RM-RESIN")
    formulation = create_formulation(api, "F-MIN")
    add_component(api, formulation["id"], resin["id"], 100.00)

    validate_error(
        api.create_raw_material(
            raw_material_payload(
                "RM-RESIN",
                name="Suspension PVC K67 second source",
                cost_per_kg_cents=175,
            ),
            PLANT_ADMIN,
        ),
        ApiErrorId.DUPLICATE_CODE.value,
    )
    validate_error(
        api.create_formulation(formulation_payload("F-MIN"), FORMULATOR),
        ApiErrorId.DUPLICATE_CODE.value,
    )
    validate_error(
        api.add_formulation_component(
            formulation["id"], component_payload(resin["id"], 40.00), FORMULATOR
        ),
        ApiErrorId.DUPLICATE_CODE.value,
    )

    rows, meta = validate_paginated(api.list_raw_materials(PLANT_ADMIN))
    assert meta["total_count"] == 1
    assert rows[0]["cost_per_kg_cents"] == 180
    after = get_success_data(api.get_formulation(formulation["id"], FORMULATOR))
    assert after["resin_phr"] == 100.00


def test_scheduling_a_thin_sku_on_a_thick_line_is_out_of_range(api):
    """The 2.50 mm plank is refused on a 6.00 mm press and admitted on a 1.50 mm line.

    "The SKU's `overall_thickness_mm` must lie within the line's forming range,
    at least `min_thickness_mm` and no greater than `max_thickness_mm`; outside
    that range the request is `ERR_THICKNESS_OUT_OF_LINE_RANGE` (HTTP 422)."
    "The run is created with `run_status` `PLANNED` and `qc_disposition`
    `PENDING`, with `changeover_minutes_applied` null, `actual_quantity_sqm` 0,
    `royalty_accrued_cents` 0, and every measured and derived quality field
    null."

    Design: Corner/errors/sku_thinner_than_the_line_minimum_returns_thickness_out_of_line_range
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_sku(api)
    begin_testing(api, built["sku"]["id"])
    assert built["sku"]["overall_thickness_mm"] == 2.50

    thick_line = create_press_line(
        api,
        line_code="PL-2",
        line_type="MULTI_DAY_PRESS",
        min_thickness_mm=6.00,
        max_thickness_mm=8.00,
        changeover_minutes=90,
        curl_control_index=95,
    )
    wide_line = create_press_line(api)

    payload = production_run_payload(
        built["sku"]["id"],
        thick_line["id"],
        run_code="RUN-THIN",
        planned_start_utc="2026-08-01T01:00:00Z",
        planned_end_utc="2026-08-01T02:00:00Z",
        planned_quantity_sqm=100.00,
    )
    validate_error(
        api.create_production_run(payload, PRODUCTION_PLANNER),
        ApiErrorId.THICKNESS_OUT_OF_LINE_RANGE.value,
    )

    _, meta = validate_paginated(
        api.list_production_runs(
            PRODUCTION_PLANNER, params={"press_line_id": thick_line["id"]}
        )
    )
    assert meta["total_count"] == 0

    admitted = validate_success(
        api.create_production_run(
            {**payload, "press_line_id": wide_line["id"]}, PRODUCTION_PLANNER
        ),
        201,
    )
    assert admitted["run_status"] == "PLANNED"


def test_refilling_a_satisfied_allocation_is_over_request(api):
    """A FILLED allocation passes the lifecycle band and is refused on the remaining requirement.

    "A `FILLED` allocation is deliberately *not* rejected on those state grounds
    — it is a legitimate fill target as far as the lifecycle is concerned — and
    is instead refused later, on the constraint that its
    `allocated_quantity_sqm` has already reached its `requested_quantity_sqm`
    and there is nothing left to draw: `ERR_ALLOCATION_OVER_REQUEST` (HTTP
    422)."
    "The allocation's resulting `status` follows from the arithmetic: `FILLED`
    when `allocated_quantity_sqm` has reached `requested_quantity_sqm`,
    `PARTIALLY_FILLED` when it is above zero but short of the request, and
    `OPEN` when it is zero."
    "Filling an allocation requires `expected_allocation_version` in the request
    body as a non-optional field, carrying the client's last observed `version`
    of the allocation."

    Design: Corner/errors/refilling_a_satisfied_allocation_returns_allocation_over_request
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_filled_allocation(api)
    allocation = get_success_data(
        api.get_allocation(built["allocation"]["id"], PLANT_ADMIN)
    )
    assert allocation["status"] == "FILLED"
    assert allocation["allocated_quantity_sqm"] == 100.00
    assert allocation["version"] == 2

    batch = get_success_data(api.get_batch(built["batch"]["id"], QA_TECHNICIAN))
    assert batch["available_quantity_sqm"] == 1100.00

    validate_error(
        api.fill_allocation(
            allocation["id"],
            fill_payload(allocation["version"]),
            distributor_headers(built["distributor"]["id"]),
        ),
        ApiErrorId.ALLOCATION_OVER_REQUEST.value,
    )

    batch_after = get_success_data(api.get_batch(built["batch"]["id"], QA_TECHNICIAN))
    assert batch_after["available_quantity_sqm"] == 1100.00
    _, meta = validate_paginated(
        api.list_allocation_lines(allocation["id"], PLANT_ADMIN)
    )
    assert meta["total_count"] == 1


def test_begin_testing_requires_an_approved_recipe(api):
    """A SKU may be defined on a DRAFT recipe; the gate lands when testing begins.

    "An approved recipe is deliberately *not* required at this point; that
    requirement arrives when testing begins."
    "A new SKU is created with `certification_status` `UNCERTIFIED` and
    `commercial_status` `DEVELOPMENT`; `pinned_formulation_version`,
    `pinned_print_film_version`, `standard_cost_cents_per_sqm`,
    `list_price_cents_per_sqm`, `certified_at` and `certified_by_user_id` are all
    null, and `pin_stale` is false."
    "Three referenced rows must be fit: the SKU's recipe must be `APPROVED`, or
    the request fails with `ERR_FORMULATION_NOT_APPROVED` (HTTP 409); the SKU's
    print film must be `AVAILABLE`, or `ERR_PRINT_FILM_NOT_AVAILABLE`; and the
    film's grant must be `ACTIVE` with the logical clock at or after
    `valid_from` and strictly before `valid_until`, failing which the request
    returns `ERR_LICENSE_NOT_ACTIVE` for a non-active grant or
    `ERR_LICENSE_EXPIRED` for a term that has run out — the latter also lazily
    flipping the grant to `EXPIRED` first."

    Design: Corner/errors/begin_testing_on_a_draft_recipe_returns_formulation_not_approved
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_draft_formulation(api, "F-STD", F_STD_COMPONENTS)
    assert built["formulation"]["status"] == "DRAFT"
    licensed = build_licensed_film(api)
    sku = create_sku(
        api,
        built["formulation"]["id"],
        licensed["film"]["id"],
        sku_code="SKU-DRAFT",
        royalty_basis_price_cents_per_sqm=2000,
    )
    assert sku["certification_status"] == "UNCERTIFIED"
    assert sku["commercial_status"] == "DEVELOPMENT"

    validate_error(
        api.begin_sku_testing(sku["id"], QA_TECHNICIAN),
        ApiErrorId.FORMULATION_NOT_APPROVED.value,
    )

    after = get_success_data(api.get_product_sku(sku["id"], PLANT_ADMIN))
    assert after["certification_status"] == "UNCERTIFIED"


def test_scheduling_a_run_on_a_restricted_film_is_refused(api):
    """Restricting the decor blocks new runs while leaving both SKU dimensions untouched.

    "A `PlantAdmin` may therefore drive a film's own status with a `to_status`
    of `RESTRICTED`, `AVAILABLE` or `WITHDRAWN`."
    "A film that is not `AVAILABLE` can found no new work — it blocks the start
    of SKU testing, the scheduling of a run and the starting of a run, each with
    `ERR_PRINT_FILM_NOT_AVAILABLE` (HTTP 409) — while runs already `PLANNED`
    keep their reserved windows."
    "The film must be `AVAILABLE` and the grant must be `ACTIVE` with
    `planned_start_utc` at or after `valid_from` and strictly before
    `valid_until`."
    "On success, the run's `planned_quantity_sqm` is added to the grant's
    `reserved_volume_sqm` and the grant's `version` is advanced."

    Design: Corner/errors/run_creation_on_a_restricted_film_returns_print_film_not_available
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_sku(api)
    begin_testing(api, built["sku"]["id"])
    press_line = create_press_line(api)

    film = set_film_status(api, built["film"]["id"], "RESTRICTED")
    assert film["status"] == "RESTRICTED"
    sku = get_success_data(api.get_product_sku(built["sku"]["id"], PLANT_ADMIN))
    assert sku["certification_status"] == "TESTING"
    assert sku["commercial_status"] == "DEVELOPMENT"

    validate_error(
        api.create_production_run(
            production_run_payload(
                built["sku"]["id"],
                press_line["id"],
                run_code="RUN-NOFILM",
                planned_start_utc="2026-08-01T01:00:00Z",
                planned_end_utc="2026-08-01T02:00:00Z",
                planned_quantity_sqm=100.00,
            ),
            PRODUCTION_PLANNER,
        ),
        ApiErrorId.PRINT_FILM_NOT_AVAILABLE.value,
    )

    utilization = get_success_data(
        api.get_license_utilization(built["license"]["id"], PRODUCTION_PLANNER)
    )
    assert utilization["reserved_volume_sqm"] == 0.00


def test_registering_a_film_under_a_suspended_grant_is_refused(api):
    """A film may only be registered while the grant it names is ACTIVE.

    "A film may only be registered while its grant is `ACTIVE`; a grant in any
    other state yields `ERR_LICENSE_NOT_ACTIVE` (HTTP 409)."
    "`ACTIVE → SUSPENDED` is a `PlantAdmin` action and cascades three hops:
    every `AVAILABLE` film on the grant moves to `RESTRICTED`; because those
    films were restricted, every SKU on one of them whose `commercial_status` is
    `RELEASED` moves to `HOLD`; and because those SKUs went on hold, each of
    their `IN_STOCK` batches moves to `HELD` with `hold_reason` `SKU_ON_HOLD`."

    Design: Corner/errors/creating_a_film_under_a_suspended_grant_returns_license_not_active
    """
    set_clock(api, CLOCK_BOOT_UTC)
    license_row = create_license(api)
    suspended = set_license_status(api, license_row["id"], "SUSPENDED")
    assert suspended["status"] == "SUSPENDED"

    validate_error(
        api.create_print_film(
            print_film_payload(
                license_row["id"],
                design_code="PF-OAK-1500",
                pattern_repeat_mm_length=1500,
                pattern_repeat_mm_width=200,
                emboss_plate_code="EP-OAK-C",
            ),
            PLANT_ADMIN,
        ),
        ApiErrorId.LICENSE_NOT_ACTIVE.value,
    )

    _, meta = validate_paginated(
        api.list_print_films(PLANT_ADMIN, params={"license_id": license_row["id"]})
    )
    assert meta["total_count"] == 0


def test_claim_on_stock_still_in_production_is_not_traceable(api):
    """A snapshot-bearing batch still in production cannot found a claim; QC release admits it.

    "Its `status` is `IN_PRODUCTION` and `hold_reason` and `held_by_user_id` are
    null."
    "The batch must be traceable: a batch without a `traceability_snapshot`, or
    a batch still in `IN_PRODUCTION` — stock that never reached the market cannot
    found a field claim — is `ERR_BATCH_NOT_TRACEABLE` (HTTP 409)."
    "New claims are `SUBMITTED` with `required_reviews`, both review outcomes,
    `assigned_adjuster_user_id`, `elapsed_months`, `settlement_variant`,
    `replacement_value_cents`, `labor_allowance_cents`,
    `settlement_amount_cents` and `denial_reason` all unset."
    "Releasing moves the run's batch `IN_PRODUCTION → IN_STOCK` (or `HELD →
    IN_STOCK` when the batch was quarantined earlier) and sets
    `available_quantity_sqm` to the full `quantity_sqm`."

    Design: Corner/errors/claim_on_stock_still_in_production_returns_batch_not_traceable
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_provisional_sku(api)
    press_line = create_press_line(api)
    run = run_to_completion(api, built["sku"]["id"], press_line["id"])
    batch = batch_of_run(api, run["id"])
    assert batch["status"] == "IN_PRODUCTION"
    assert batch["available_quantity_sqm"] == 0.00
    assert batch["hold_reason"] is None
    assert isinstance(batch["traceability_snapshot"], dict)
    assert batch["traceability_snapshot"]

    distributor = create_distributor(api)
    payload = warranty_claim_payload(
        batch["id"],
        distributor["id"],
        claim_code="WC-UNTRACEABLE",
        claim_type="DELAMINATION",
        claimed_area_sqm=10.00,
        installed_on="2026-08-05T00:00:00Z",
        reported_on="2027-08-05T00:00:00Z",
    )
    validate_error(
        api.create_warranty_claim(payload, WARRANTY_ADJUSTER),
        ApiErrorId.BATCH_NOT_TRACEABLE.value,
    )

    set_qc_disposition(api, run["id"], "RELEASED")
    released_batch = get_success_data(api.get_batch(batch["id"], QA_TECHNICIAN))
    assert released_batch["status"] == "IN_STOCK"
    assert released_batch["available_quantity_sqm"] == 1200.00

    admitted = validate_success(
        api.create_warranty_claim(payload, WARRANTY_ADJUSTER), 201
    )
    assert admitted["status"] == "SUBMITTED"
    assert admitted["assigned_adjuster_user_id"] is None


def test_filling_against_an_empty_candidate_pool_finds_no_eligible_batch(api):
    """A released SKU that never produced anything leaves the fill selector with nothing to draw.

    "A batch is a candidate only when its `status` is `IN_STOCK`, its
    `available_quantity_sqm` is strictly greater than zero, its producing run's
    `qc_disposition` is `RELEASED`, and its own SKU's `commercial_status` is not
    `DISCONTINUED`."
    "If the candidate set is empty, the fill is refused with
    `ERR_NO_ELIGIBLE_BATCH` (HTTP 409) and the allocation is left completely
    untouched."
    "A new allocation is `OPEN` with `allocated_quantity_sqm` and
    `upgrade_cost_total_cents` both 0."

    Design: Corner/errors/filling_against_empty_stock_returns_no_eligible_batch
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_released_sku(api)
    distributor = create_distributor(api)
    allocation = create_allocation(
        api,
        distributor["id"],
        built["sku"]["id"],
        headers=PLANT_ADMIN,
        allocation_code="ALLOC-EMPTY",
        requested_quantity_sqm=25.00,
    )
    assert allocation["status"] == "OPEN"
    assert allocation["allocated_quantity_sqm"] == 0.00
    assert allocation["version"] == 1

    _, batch_meta = validate_paginated(
        api.list_batches(PLANT_ADMIN, params={"sku_id": built["sku"]["id"]})
    )
    assert batch_meta["total_count"] == 0

    validate_error(
        api.fill_allocation(
            allocation["id"],
            fill_payload(allocation["version"]),
            distributor_headers(distributor["id"]),
        ),
        ApiErrorId.NO_ELIGIBLE_BATCH.value,
    )

    after = get_success_data(api.get_allocation(allocation["id"], PLANT_ADMIN))
    assert after["status"] == "OPEN"
    assert after["allocated_quantity_sqm"] == 0.00
    assert after["version"] == 1


def test_approving_a_claim_carrying_a_no_defect_arm_conflicts_while_denial_stands(api):
    """The join needs both arms answered, not agreed; the approval conflicts and the denial lands.

    "Triage stamps `assigned_adjuster_user_id` with the acting adjuster and
    **forks** the investigation by setting `required_reviews`: a `DELAMINATION`
    or `LOCK_FAILURE` claim requires both a materials review and a field review,
    while a `WEAR_LAYER_WEARTHROUGH` or `DIMENSIONAL_MOVEMENT` claim requires the
    field review only."
    "The claim stays in `TRIAGE` while any required arm is unanswered; the
    instant every required arm carries a non-null outcome, the claim joins
    `TRIAGE → ADJUDICATION_READY`."
    "An approval takes it `ADJUDICATION_READY → APPROVED` and requires two
    further things: every required review outcome must be `DEFECT_CONFIRMED`, and
    any arm answered `NO_DEFECT` or `INCONCLUSIVE` makes the approval
    `ERR_REVIEW_OUTCOME_CONFLICT` (HTTP 409); and the warranty coverage must not
    be exhausted."
    "A denial takes the claim `ADJUDICATION_READY → DENIED`, records
    `denial_reason` and leaves `settlement_amount_cents` null."

    Design: Corner/errors/approving_over_a_no_defect_review_returns_review_outcome_conflict
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_stock_batch(api)
    distributor = create_distributor(api)
    set_clock(api, "2029-08-05T00:00:00Z")

    claim = get_success_data(
        api.create_warranty_claim(
            warranty_claim_payload(
                built["batch"]["id"],
                distributor["id"],
                claim_code="WC-RAW",
                claim_type="DELAMINATION",
            ),
            WARRANTY_ADJUSTER,
        )
    )
    claim = triage_claim(api, claim["id"])
    required = claim["required_reviews"]
    assert len(required) == 2

    record_review(api, claim["id"], required[0], "DEFECT_CONFIRMED")
    claim = record_review(
        api,
        claim["id"],
        required[1],
        "NO_DEFECT",
        note="Installed over an unlevelled slab",
    )
    assert claim["status"] == "ADJUDICATION_READY"

    validate_error(
        api.adjudicate_warranty_claim(
            claim["id"], adjudication_payload("APPROVE"), WARRANTY_ADJUSTER_B
        ),
        ApiErrorId.REVIEW_OUTCOME_CONFLICT.value,
    )

    denied = validate_success(
        api.adjudicate_warranty_claim(
            claim["id"],
            adjudication_payload(
                "DENY", denial_reason="Field review found no manufacturing defect"
            ),
            WARRANTY_ADJUSTER_B,
        )
    )
    assert denied["status"] == "DENIED"
    assert denied["settlement_amount_cents"] is None


def test_term_volume_cap_admits_equality_then_refuses_excess_and_a_smaller_cap(api):
    """Reservations reaching exactly the cap are admitted; a hundredth more is not, nor is a smaller cap.

    "The grant's projected volume is its `consumed_volume_sqm` plus its
    `reserved_volume_sqm` plus the new run's `planned_quantity_sqm`, and that
    projection may not exceed `term_volume_cap_sqm`; equality is admitted, and an
    excess is `ERR_LICENSE_VOLUME_CAP_EXCEEDED` (HTTP 422)."
    "On success, the run's `planned_quantity_sqm` is added to the grant's
    `reserved_volume_sqm` and the grant's `version` is advanced."
    "The new cap may not be smaller than the volume the grant has already
    committed — that is, it must be at least the sum of `consumed_volume_sqm` and
    `reserved_volume_sqm` — and a smaller cap is refused with
    `ERR_LICENSE_VOLUME_CAP_EXCEEDED` (HTTP 422)."
    "On success a successor grant is created `ACTIVE` with
    `supersedes_license_id` pointing at the amended one, carrying
    `reserved_volume_sqm`, `consumed_volume_sqm` and `accrued_royalty_cents`
    across unchanged; every film of the amended grant is repointed at the
    successor and has its `version` advanced; and the amended grant moves
    `ACTIVE → SUPERSEDED`."
    "A grant's utilization is readable as a computed summary carrying
    `term_volume_cap_sqm`, `reserved_volume_sqm`, `consumed_volume_sqm`, the
    forward-looking `projected_volume_sqm` (consumed plus reserved), the
    `remaining_volume_sqm` left under the cap (the cap less the projection), the
    `accrued_royalty_cents` ledger, and `contributing_run_count`, the number of
    completed runs that have contributed royalty to it."

    Design: Corner/errors/term_cap_admits_exact_equality_then_returns_license_volume_cap_exceeded
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_sku(api)
    begin_testing(api, built["sku"]["id"])
    assert built["license"]["term_volume_cap_sqm"] == 2000.00
    press_line = create_press_line(api)

    create_run(
        api,
        built["sku"]["id"],
        press_line["id"],
        run_code="RUN-CAP-1",
        planned_start_utc="2026-08-01T01:00:00Z",
        planned_end_utc="2026-08-01T02:00:00Z",
        planned_quantity_sqm=1500.00,
    )
    at_the_cap = create_run(
        api,
        built["sku"]["id"],
        press_line["id"],
        run_code="RUN-CAP-2",
        planned_start_utc="2026-08-01T03:00:00Z",
        planned_end_utc="2026-08-01T04:00:00Z",
        planned_quantity_sqm=500.00,
    )
    assert at_the_cap["run_status"] == "PLANNED"

    validate_error(
        api.create_production_run(
            production_run_payload(
                built["sku"]["id"],
                press_line["id"],
                run_code="RUN-CAP-3",
                planned_start_utc="2026-08-01T05:00:00Z",
                planned_end_utc="2026-08-01T06:00:00Z",
                planned_quantity_sqm=0.01,
            ),
            PRODUCTION_PLANNER,
        ),
        ApiErrorId.LICENSE_VOLUME_CAP_EXCEEDED.value,
    )
    validate_error(
        api.create_license_amendment(
            built["license"]["id"],
            license_amendment_payload(
                "LIC-OAK-A2",
                1000.00,
                amendment_note="Attempted downward revision",
            ),
            TECHNICAL_DIRECTOR,
        ),
        ApiErrorId.LICENSE_VOLUME_CAP_EXCEEDED.value,
    )

    utilization = get_success_data(
        api.get_license_utilization(built["license"]["id"], PRODUCTION_PLANNER)
    )
    assert utilization["reserved_volume_sqm"] == 2000.00
    assert utilization["consumed_volume_sqm"] == 0.00
    assert utilization["remaining_volume_sqm"] == 0.00
    assert utilization["contributing_run_count"] == 0
    license_row = get_success_data(
        api.get_design_license(built["license"]["id"], PLANT_ADMIN)
    )
    assert license_row["status"] == "ACTIVE"
