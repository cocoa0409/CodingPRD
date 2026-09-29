"""Validation-band behaviour and endpoint reads across the plant chain.

This module exercises the PRD's dosage ceiling and resin-normalisation rules on
recipes (PRD 3.1), the conditional milling field group and the tolerance band on
SKU definition (PRD 3.3), pin staleness and the cross-dimension release guard
(PRD 3.5), press-line registration, availability and roll-set capacity on run
scheduling (PRD 3.2, 3.6), the QC gate enforcement that guards a release
(PRD 3.6, 3.7), the reverse read of allocation lines from finished stock
(PRD 3.8), the computed SKU cost summary (PRD 3.3) and the warranty coverage
boundary at adjudication (PRD 3.9).
"""

from test_helpers import (
    FORMULATOR,
    PLANT_ADMIN,
    PRODUCTION_PLANNER,
    QA_TECHNICIAN,
    QA_TECHNICIAN_B,
    TECHNICAL_DIRECTOR,
    WARRANTY_ADJUSTER_B,
    ApiErrorId,
    add_component,
    assert_pagination_meta,
    assert_version_unchanged,
    adjudication_payload,
    batch_of_run,
    begin_testing,
    build_approved_formulation,
    build_certified_sku,
    build_draft_formulation,
    build_filled_allocation,
    build_licensed_film,
    build_provisional_sku,
    build_stock_batch,
    commercial_status_payload,
    component_payload,
    create_distributor,
    create_claim,
    create_formulation,
    create_license,
    create_press_line,
    create_print_film,
    create_raw_material,
    create_run,
    create_sku,
    get_success_data,
    is_valid_uuid,
    press_line_payload,
    press_line_status_payload,
    product_sku_payload,
    production_run_payload,
    qc_disposition_payload,
    record_review,
    revision_payload,
    run_to_completion,
    set_clock,
    set_material_status,
    triage_claim,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Recipe dosage rules (PRD 3.1).
# ---------------------------------------------------------------------------


def test_phr_above_material_ceiling_is_a_business_constraint_not_a_shape_error(api):
    """A 61 phr charge against a max_phr of 60 is refused by the band-12 ceiling
    rule with ERR_PHR_EXCEEDS_MATERIAL_MAX and leaves the recipe untouched.

    "And the dosage may not exceed the material's own ceiling — a `phr` greater
    than `max_phr` is `ERR_PHR_EXCEEDS_MATERIAL_MAX` (HTTP 422)."
    "Note that this ceiling is a stored-state comparison evaluated in band 12,
    not a shape rule: a syntactically valid dosage that happens to be too large
    for that particular material is a 422, never a 400."
    "The `error_id` is a unique, machine-readable string that identifies the
    specific error."
    "The `message` provides a human-readable explanation of what went wrong."
    "`total_phr` is the sum of `phr` across all components, likewise at two
    decimal places."

    Design: Corner/validations/phr_above_material_ceiling_returns_phr_exceeds_material_max
    """
    resin = create_raw_material(api, "RM-RESIN")
    plasticiser = create_raw_material(api, "RM-SOFT")
    formulation = create_formulation(api, "F-MIN")
    add_component(api, formulation["id"], resin["id"], 100)

    refused = api.add_formulation_component(
        formulation["id"],
        component_payload(plasticiser["id"], 61.00),
        FORMULATOR,
    )
    error_data = validate_error(refused, ApiErrorId.PHR_EXCEEDS_MATERIAL_MAX.value)
    assert sorted(error_data.keys()) == ["error_id", "message"], (
        "the error data block carries only error_id and message, got "
        f"{sorted(error_data.keys())}"
    )

    rows, meta = validate_paginated(
        api.list_formulation_components(formulation["id"], FORMULATOR)
    )
    assert_pagination_meta(meta, expected_total=1)
    assert len(rows) == 1, "the refused dosage must not have been persisted"

    recipe = validate_success(api.get_formulation(formulation["id"], FORMULATOR))
    assert recipe["total_phr"] == 100.00, (
        f"total_phr moved to {recipe['total_phr']} on a refused dosage"
    )


def test_phr_exactly_at_material_ceiling_is_admitted_and_moves_the_blend(api):
    """A 60.00 phr charge against a max_phr of exactly 60.00 is accepted, and the
    accepted component drives the recipe's derived blend figures.

    "And the dosage may not exceed the material's own ceiling — a `phr` greater
    than `max_phr` is `ERR_PHR_EXCEEDS_MATERIAL_MAX` (HTTP 422)."
    "`total_phr` is the sum of `phr` across all components, likewise at two
    decimal places."
    "The `performance_score` is built from three dosage-weighted blend indices,
    each carried to six decimal places and each computed as the sum over
    components of `phr` multiplied by the relevant material property, divided by
    `total_phr`: the blended indentation index uses `indentation_index`
    directly; the blended thermal index uses `thermal_stability_index`
    directly; and the blended migration-resistance index uses 100 minus the
    material's `plasticizer_migration_index`, so that a migration-prone
    plasticizer drags the blend down."
    "Those three indices are weighted at forty percent, thirty-five percent and
    twenty-five percent respectively and added together."
    "The softness penalty reads the plasticizer ratio — `plasticizer_phr`
    divided by `resin_phr`, rounded half up to four decimal places — and is 12
    points when that ratio is greater than 0.35, 5 points when it is greater
    than 0.25 but not greater than 0.35, and zero otherwise."
    "The result is clamped to the range 0 through 100, taking whichever of the
    clamp bounds applies, and only then rounded half up to two decimal places."
    "The recipe's `performance_score` must be at least 60.00 — a score below
    that minimum is `ERR_PERFORMANCE_SCORE_BELOW_MINIMUM` (HTTP 422), and a
    score of exactly 60.00 is approvable because the threshold is inclusive."

    Design: Corner/validations/phr_exactly_at_material_ceiling_is_admitted
    """
    resin = create_raw_material(api, "RM-RESIN")
    plasticiser = create_raw_material(api, "RM-SOFT")
    formulation = create_formulation(api, "F-MIN")
    add_component(api, formulation["id"], resin["id"], 100)

    admitted = api.add_formulation_component(
        formulation["id"],
        component_payload(plasticiser["id"], 60.00),
        FORMULATOR,
    )
    validate_success(admitted, 201)

    rows, meta = validate_paginated(
        api.list_formulation_components(formulation["id"], FORMULATOR)
    )
    assert_pagination_meta(meta, expected_total=2)
    edge = [row for row in rows if row["raw_material_id"] == plasticiser["id"]]
    assert len(edge) == 1, "the 60.00 phr charge must have entered the recipe"
    assert edge[0]["phr"] == 60.00, f"phr is {edge[0]['phr']}, expected 60.00"
    assert is_valid_uuid(edge[0]["id"]), f"component id is not a UUID: {edge[0]['id']!r}"

    recipe = validate_success(api.get_formulation(formulation["id"], FORMULATOR))
    assert recipe["resin_phr"] == 100.00
    assert recipe["plasticizer_phr"] == 60.00
    assert recipe["total_phr"] == 160.00, (
        f"total_phr is {recipe['total_phr']}, expected 160.00"
    )
    assert recipe["performance_score"] == 51.44, (
        "the 0.6000 plasticizer ratio takes the full 12-point softness penalty, "
        f"leaving 51.44; got {recipe['performance_score']}"
    )
    assert recipe["performance_score"] < 60.00


def test_restricted_material_blocks_submit_of_an_otherwise_valid_recipe(api):
    """A recipe whose resin dosage is a valid 100.00 is still refused at submit
    because a material two hops away left ACTIVE after the dosage was recorded.

    "Moving a material to `RESTRICTED` starts the plant's deepest cascade."
    "The recipe must have at least one component and its `resin_phr` must be
    exactly 100.00 — a recipe with no components, or one whose resin dosage is
    anything other than exactly 100.00, is refused with
    `ERR_RESIN_PHR_NOT_NORMALIZED` (HTTP 422)."
    "And every material on the recipe must still be `ACTIVE`, or the submission
    fails with `ERR_RAW_MATERIAL_NOT_ACTIVE`."
    "Submission is the `Formulator`'s hand-off. It is permitted only from
    `DRAFT`, taking the recipe `DRAFT → UNDER_REVIEW`, and it stamps
    `submitted_by_user_id` with the acting user."
    "Its `submitted_by_user_id`, `approved_by_user_id` and `approved_at` are
    null."

    Design: Corner/validations/restricted_raw_material_blocks_formulation_submit_cross_entity
    """
    resin = create_raw_material(api, "RM-RESIN")
    stabiliser = create_raw_material(api, "RM-STAB")
    formulation = create_formulation(api, "F-MIN")
    add_component(api, formulation["id"], resin["id"], 100)
    add_component(api, formulation["id"], stabiliser["id"], 3)

    restricted = set_material_status(api, stabiliser["id"], "RESTRICTED")
    assert restricted["status"] == "RESTRICTED"

    before = validate_success(api.get_formulation(formulation["id"], FORMULATOR))
    assert before["status"] == "DRAFT"
    assert before["resin_phr"] == 100.00, "the resin dosage is a normalised 100.00"

    refused = api.submit_formulation(formulation["id"], FORMULATOR)
    validate_error(refused, ApiErrorId.RAW_MATERIAL_NOT_ACTIVE.value)

    after = validate_success(api.get_formulation(formulation["id"], FORMULATOR))
    assert after["status"] == "DRAFT", (
        f"the refused submit moved the recipe to {after['status']}"
    )
    assert after["submitted_by_user_id"] is None
    assert_version_unchanged(before, after)


# ---------------------------------------------------------------------------
# Warranty coverage boundary (PRD 3.9).
# ---------------------------------------------------------------------------


def test_warranty_coverage_boundary_admits_239_months_and_rejects_240(api):
    """Two byte-identical claims one calendar month apart: 239 elapsed months
    settle on the stepped schedule while exactly 240 is refused as expired.

    "The residential term is 25 years when `wear_layer_mil` is at least 20, 20
    years when it is at least 12 but below 20, 15 years when it is at least 6
    but below 12, and 10 years otherwise."
    "`elapsed_months` is the number of whole calendar months from `installed_on`
    to `reported_on`, floored, so a partial month does not count."
    "The coverage term is the SKU's `warranty_years` multiplied by 12, and an
    approval whose `elapsed_months` has reached or passed that figure is refused
    with `ERR_WARRANTY_EXPIRED` (HTTP 409) before any settlement is computed — a
    claim at exactly the coverage boundary has no remaining months and is
    expired."
    "The `replacement_value_cents` is the `claimed_area_sqm` multiplied by the
    SKU's `royalty_basis_price_cents_per_sqm`, rounded half up to a whole cent."
    "A `DELAMINATION` or `LOCK_FAILURE` claim uses `STEPPED_SCHEDULE`: take the
    elapsed whole years as `elapsed_months` divided by twelve rounded down, then
    apply 100 percent when that figure is 1 or less, 80 percent when it is 2 or
    3, 60 percent when it is 4 through 7, 40 percent when it is 8 through 12,
    and 20 percent beyond that, rounding the result half up to a whole cent."
    "A measurement exactly equal to the specified thickness less 0.5 is *not* a
    defect, because the comparison is strict."
    "The `labor_allowance_cents` is the `claimed_area_sqm` multiplied by 350
    cents per square metre, rounded half up to a whole cent, when
    `installed_by_certified_installer` is true, and 0 otherwise."
    "The `settlement_amount_cents` is the covered value plus the
    `labor_allowance_cents`, added as two already-rounded integers."
    "An approval takes it `ADJUDICATION_READY → APPROVED` and requires two
    further things: every required review outcome must be `DEFECT_CONFIRMED`,
    and any arm answered `NO_DEFECT` or `INCONCLUSIVE` makes the approval
    `ERR_REVIEW_OUTCOME_CONFLICT` (HTTP 409); and the warranty coverage must not
    be exhausted."

    Design: Corner/validations/warranty_coverage_month_boundary_admits_239_and_rejects_240
    """
    built = build_stock_batch(api)
    sku = built["sku"]
    assert sku["wear_layer_mil"] == 12
    assert sku["warranty_years"] == 20, (
        "a 12 mil wear layer gives a 20-year residential term, so coverage is "
        f"240 months; got warranty_years {sku['warranty_years']}"
    )
    batch_id = built["batch"]["id"]
    distributor = create_distributor(api)
    set_clock(api, "2046-08-05T00:00:00Z")

    claims = {}
    for code, reported_on in (
        ("WC-239", "2046-07-05T00:00:00Z"),
        ("WC-240", "2046-08-05T00:00:00Z"),
    ):
        claim = create_claim(
            api,
            batch_id,
            distributor["id"],
            claim_code=code,
            claim_type="LOCK_FAILURE",
            claimed_area_sqm=25.50,
            installed_on="2026-08-05T00:00:00Z",
            reported_on=reported_on,
        )
        triage_claim(api, claim["id"])
        record_review(api, claim["id"], "MATERIALS", "DEFECT_CONFIRMED")
        claim = record_review(api, claim["id"], "FIELD", "DEFECT_CONFIRMED")
        assert claim["status"] == "ADJUDICATION_READY"
        claims[code] = claim

    approved = validate_success(
        api.adjudicate_warranty_claim(
            claims["WC-239"]["id"], adjudication_payload("APPROVE"), WARRANTY_ADJUSTER_B
        )
    )
    assert approved["elapsed_months"] == 239, (
        f"elapsed_months is {approved['elapsed_months']}, expected 239"
    )
    assert approved["status"] == "APPROVED"
    assert approved["settlement_variant"] == "STEPPED_SCHEDULE"
    assert approved["replacement_value_cents"] == 53550, (
        "25.50 sqm at 2100 cents per sqm is 53550 cents, got "
        f"{approved['replacement_value_cents']}"
    )
    assert approved["labor_allowance_cents"] == 0
    assert approved["settlement_amount_cents"] == 10710, (
        "19 elapsed whole years takes the 20 percent step of 53550, got "
        f"{approved['settlement_amount_cents']}"
    )

    expired = api.adjudicate_warranty_claim(
        claims["WC-240"]["id"], adjudication_payload("APPROVE"), WARRANTY_ADJUSTER_B
    )
    validate_error(expired, ApiErrorId.WARRANTY_EXPIRED.value)

    unsettled = validate_success(
        api.get_warranty_claim(claims["WC-240"]["id"], WARRANTY_ADJUSTER_B)
    )
    assert unsettled["status"] == "ADJUDICATION_READY", (
        f"the refused claim moved to {unsettled['status']}"
    )
    assert unsettled["settlement_amount_cents"] is None, (
        "the refusal happens before any settlement is computed"
    )


# ---------------------------------------------------------------------------
# Roll-set capacity on scheduling (PRD 3.6).
# ---------------------------------------------------------------------------


def test_roll_set_capacity_admits_two_intersecting_runs_and_refuses_the_third(api):
    """With master_roll_sets 2 the first two runs whose windows intersect on one
    film are admitted and only the third is refused, each on its own press line.

    "**Roll-set capacity** on the print film uses a *closed* interval — from
    `planned_start_utc` through `planned_end_utc` inclusive — because a roll set
    cannot be re-threaded instantaneously, so here touching endpoints *do*
    collide."
    "It is also an aggregate capacity rule rather than a pairwise exclusion:
    count the runs on the same `print_film_id` whose closed windows intersect
    the new run's closed window and whose `run_status` is not `ABORTED`, and
    reject only when that count is at least the film's `master_roll_sets`."
    "The rejection is `ERR_PRINT_FILM_ROLL_CAPACITY_EXCEEDED` (HTTP 409)."
    "Two runs on the same line collide when the new run's start is strictly
    earlier than the other's end **and** the other's start is strictly earlier
    than the new run's end, counting only runs whose `run_status` is not
    `ABORTED`."
    "The run is created with `run_status` `PLANNED` and `qc_disposition`
    `PENDING`, with `changeover_minutes_applied` null, `actual_quantity_sqm` 0,
    `royalty_accrued_cents` 0, and every measured and derived quality field
    null."

    Design: Corner/validations/print_film_roll_set_capacity_counts_intersecting_runs_in_aggregate
    """
    built = build_approved_formulation(api)
    licensed = create_license(api)
    film = create_print_film(
        api,
        licensed["id"],
        design_code="PF-DUO-600",
        pattern_repeat_mm_length=600,
        pattern_repeat_mm_width=150,
        master_roll_sets=2,
    )
    assert film["master_roll_sets"] == 2
    sku = create_sku(
        api,
        built["formulation"]["id"],
        film["id"],
        sku_code="SKU-DUO",
        royalty_basis_price_cents_per_sqm=2000,
    )
    begin_testing(api, sku["id"])
    line_a = create_press_line(api)
    line_b = create_press_line(api, line_code="PL-B")
    line_c = create_press_line(api, line_code="PL-C")

    window = {
        "planned_start_utc": "2026-08-01T01:00:00Z",
        "planned_end_utc": "2026-08-01T02:00:00Z",
        "planned_quantity_sqm": 10.00,
    }
    first = create_run(api, sku["id"], line_a["id"], run_code="RUN-D1", **window)
    second = create_run(api, sku["id"], line_b["id"], run_code="RUN-D2", **window)
    assert first["run_status"] == "PLANNED"
    assert second["run_status"] == "PLANNED"
    assert first["id"] != second["id"], "two distinct runs were admitted"

    third = api.create_production_run(
        production_run_payload(
            sku["id"], line_c["id"], run_code="RUN-D3", **window
        ),
        PRODUCTION_PLANNER,
    )
    validate_error(third, ApiErrorId.PRINT_FILM_ROLL_CAPACITY_EXCEEDED.value)

    rows, meta = validate_paginated(
        api.list_production_runs(PRODUCTION_PLANNER, params={"press_line_id": line_c["id"]})
    )
    assert_pagination_meta(meta, expected_total=0)
    assert rows == [], "no run was created on the third line"


# ---------------------------------------------------------------------------
# The conditional milling field group (PRD 3.3).
# ---------------------------------------------------------------------------


def test_milling_field_group_is_conditionally_required_and_forbidden(api):
    """The four milling fields are forbidden while profile_family is NONE,
    mandatory once it is set, and a click-lock construction may not stay at
    NONE; a complete group then meets the separate tolerance-band constraint.

    "Optional inputs are `waterproof_rated` (false by default),
    `attached_underlayment_type` (`NONE` by default), `profile_family` (`NONE`
    by default), `tongue_thickness_target_mm`, `tolerance_plus_mm`,
    `tolerance_minus_mm`, `target_lock_shear_n_per_mm` (all null by default) and
    `target_margin_bps` (3500 by default, and constrained to the range 0 through
    9000)."
    "If `profile_family` is anything other than `NONE`, all four of
    `tongue_thickness_target_mm`, `tolerance_plus_mm`, `tolerance_minus_mm` and
    `target_lock_shear_n_per_mm` must be present; if `profile_family` is `NONE`,
    all four must be absent; and a `construction_type` of `CLICK_LOCK_SPC` or
    `CLICK_LOCK_WPC` may not be combined with a `profile_family` of `NONE`. Any
    of those three conditions returns `ERR_INVALID_REQUEST` (HTTP 400)."
    "When `profile_family` is not `NONE`, `tolerance_minus_mm` must be strictly
    smaller than `tongue_thickness_target_mm` — a lower tolerance that would
    consume the whole tongue is nonsense — and the two tolerances added together
    may not exceed 0.50 millimetres, half a millimetre being the widest total
    band the milling heads can hold. Either violation is
    `ERR_TOLERANCE_BAND_INVALID` (HTTP 422)."

    Design: Corner/validations/click_profile_field_group_is_conditionally_required_and_conditionally_forbidden
    """
    built = build_draft_formulation(api)
    licensed = build_licensed_film(api)
    formulation_id = built["formulation"]["id"]
    film_id = licensed["film"]["id"]

    control = validate_success(
        api.create_product_sku(
            product_sku_payload(formulation_id, film_id, sku_code="SKU-V1"),
            PLANT_ADMIN,
        ),
        201,
    )
    assert control["profile_family"] == "NONE"
    for field in (
        "tongue_thickness_target_mm",
        "tolerance_plus_mm",
        "tolerance_minus_mm",
        "target_lock_shear_n_per_mm",
    ):
        assert control[field] is None, f"{field} is {control[field]!r}, expected null"

    forbidden_field = api.create_product_sku(
        product_sku_payload(
            formulation_id,
            film_id,
            sku_code="SKU-V2",
            tongue_thickness_target_mm=1.80,
        ),
        PLANT_ADMIN,
    )
    validate_error(forbidden_field, ApiErrorId.INVALID_REQUEST.value)

    click_lock_at_none = api.create_product_sku(
        product_sku_payload(
            formulation_id,
            film_id,
            sku_code="SKU-V3",
            construction_type="CLICK_LOCK_SPC",
            wear_layer_mil=20,
            overall_thickness_mm=5.00,
            royalty_basis_price_cents_per_sqm=2600,
            profile_family="NONE",
        ),
        PLANT_ADMIN,
    )
    validate_error(click_lock_at_none, ApiErrorId.INVALID_REQUEST.value)

    wide_band = api.create_product_sku(
        product_sku_payload(
            formulation_id,
            film_id,
            sku_code="SKU-V4",
            construction_type="CLICK_LOCK_SPC",
            wear_layer_mil=20,
            overall_thickness_mm=5.00,
            royalty_basis_price_cents_per_sqm=2600,
            profile_family="UNILIN_5G",
            tongue_thickness_target_mm=1.80,
            tolerance_plus_mm=0.15,
            tolerance_minus_mm=0.40,
            target_lock_shear_n_per_mm=8.00,
        ),
        PLANT_ADMIN,
    )
    validate_error(wide_band, ApiErrorId.TOLERANCE_BAND_INVALID.value)


# ---------------------------------------------------------------------------
# Pin staleness cascading into the release guard (PRD 3.1, 3.5).
# ---------------------------------------------------------------------------


def test_opening_a_revision_makes_the_pin_stale_and_blocks_commercial_release(api):
    """Opening a revision advances the parent recipe's version, which turns the
    certified SKU's pin stale and makes the declared DEVELOPMENT -> RELEASED
    transition fail on the producibility guard instead.

    "Creating a revision of a recipe requires `expected_formulation_version` in
    the request body as a non-optional field, carrying the client's last
    observed `version` of the recipe being revised."
    "The parent's `open_revision_count` is incremented and its `version`
    advanced, but the parent **stays** `APPROVED`; it only becomes `SUPERSEDED`
    when the revision is itself approved."
    "Whenever the SKU's recipe moves to `SUPERSEDED` or `RETIRED`, or its
    `version` ceases to equal the SKU's `pinned_formulation_version`,
    `pin_stale` becomes true."
    "The **pinned basis** takes the core-compound component from the
    per-component `material_cost_snapshot_cents` captured when the recipe was
    approved — equivalently, from a pinned recipe's `blended_cost_per_kg_cents`,
    which is what the SKU's `pinned_formulation_version` refers to."
    "The **live basis** re-blends the core compound from the *current*
    `cost_per_kg_cents` of every component material, ignoring the snapshots
    entirely: it sums each component's `phr` multiplied by its material's
    current cost, divides by `total_phr`, and rounds half up to a whole cent
    before the thickness and specific-gravity multiplication."
    "`DEVELOPMENT → RELEASED` and `HOLD → RELEASED` are both declared, as is
    `RELEASED → HOLD`, giving a `RELEASED → HOLD → RELEASED` cycle;
    `DISCONTINUED` is reachable from `DEVELOPMENT`, `RELEASED` or `HOLD` and is
    terminal on this dimension."
    "Reaching `RELEASED` is additionally guarded across the dimension boundary:
    the SKU's `certification_status` must be exactly `CERTIFIED` and its
    `pin_stale` must be false, and a violation of either is
    `ERR_SKU_NOT_PRODUCIBLE` (HTTP 409)."

    Design: Corner/validations/formulation_revision_makes_pin_stale_and_cascades_into_release_refusal
    """
    built = build_certified_sku(api)
    sku_id = built["sku"]["id"]
    formulation_id = built["formulation"]["id"]

    before = validate_success(api.get_sku_cost_summary(sku_id, TECHNICAL_DIRECTOR))
    assert before["pin_stale"] is False
    assert before["pinned_basis_standard_cost_cents_per_sqm"] == 1157, (
        "the pinned basis stamped at certification is 1157, got "
        f"{before['pinned_basis_standard_cost_cents_per_sqm']}"
    )

    parent_before = validate_success(api.get_formulation(formulation_id, FORMULATOR))
    assert parent_before["status"] == "APPROVED"
    revision = get_success_data(
        api.create_formulation_revision(
            formulation_id,
            revision_payload("F-MIN-R2", parent_before["version"]),
            FORMULATOR,
        )
    )
    assert revision["supersedes_formulation_id"] == formulation_id

    parent_after = validate_success(api.get_formulation(formulation_id, FORMULATOR))
    assert parent_after["status"] == "APPROVED", "the parent stays APPROVED"
    assert parent_after["open_revision_count"] == 1
    assert parent_after["version"] == parent_before["version"] + 1, (
        "opening a revision advances the parent's version by exactly one"
    )

    after = validate_success(api.get_sku_cost_summary(sku_id, TECHNICAL_DIRECTOR))
    assert after["pin_stale"] is True, (
        "the SKU's pinned_formulation_version no longer equals the recipe's version"
    )
    assert after["basis_delta_cents_per_sqm"] == 0, (
        "no material was revalued, so the two bases still agree; got "
        f"{after['basis_delta_cents_per_sqm']}"
    )

    refused = api.set_sku_commercial_status(
        sku_id, commercial_status_payload("RELEASED"), PLANT_ADMIN
    )
    validate_error(refused, ApiErrorId.SKU_NOT_PRODUCIBLE.value)

    sku_after = validate_success(api.get_product_sku(sku_id, PLANT_ADMIN))
    assert sku_after["commercial_status"] == "DEVELOPMENT", (
        f"the refused release moved the SKU to {sku_after['commercial_status']}"
    )
    assert sku_after["certification_status"] == "CERTIFIED"
    assert sku_after["pin_stale"] is True


# ---------------------------------------------------------------------------
# Press lines: creation, reads and the availability action (PRD 3.6).
# ---------------------------------------------------------------------------


def test_press_line_create_read_and_filtered_list_round_trip(api):
    """A registered line reads back exactly as written, and the line_type filter
    narrows the collection while the pagination envelope still reports the
    matching total.

    "A press line is registered by a `PlantAdmin` with a `line_code` unique
    across lines, a `line_type` naming its forming technology, a
    `min_thickness_mm` greater than zero and a `max_thickness_mm` strictly
    greater than it (otherwise `ERR_INVALID_REQUEST`, HTTP 400), a
    `changeover_minutes` allowance of at least zero, and a `curl_control_index`
    between 0 and 100 that sets how tight a curl band the line can hold."
    "Lines are created `AVAILABLE` unless the request overrides `status`, and a
    `PlantAdmin` may later drive `status` with a `to_status` of `AVAILABLE`,
    `MAINTENANCE` or `DOWN`."
    "Most resources additionally carry `updated_at`, in the same format,
    refreshed on every mutation, and `version`, an integer that starts at 1 on
    creation and increases by exactly 1 on every mutation of that row —
    including mutations the caller did not directly request, such as a cascade
    reaching the row from a neighbouring entity."
    "Collection reads support equality filters drawn from the same vocabulary,
    combined with logical AND when more than one is supplied."
    "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` (the number of rows matching the filters before the window is
    applied) and `has_more` (true when rows remain beyond the current window)."

    Design: Corner/endpoints/press_line_create_read_and_filtered_list_round_trip
    """
    calender = create_press_line(api)
    assert calender["line_code"] == "PL-1"
    assert calender["line_type"] == "CALENDER"

    created = validate_success(
        api.create_press_line(
            press_line_payload(
                line_code="PL-2",
                line_type="MULTI_DAY_PRESS",
                min_thickness_mm=6.00,
                max_thickness_mm=8.00,
                changeover_minutes=90,
                curl_control_index=95,
            ),
            PLANT_ADMIN,
        ),
        201,
    )
    assert created["status"] == "AVAILABLE", (
        f"a new line is AVAILABLE, got {created['status']}"
    )
    assert created["version"] == 1

    read = validate_success(api.get_press_line(created["id"], PRODUCTION_PLANNER))
    assert read["line_code"] == "PL-2"
    assert read["curl_control_index"] == 95
    assert read["min_thickness_mm"] == 6.00
    assert read["max_thickness_mm"] == 8.00
    assert read["changeover_minutes"] == 90
    assert read["line_type"] == "MULTI_DAY_PRESS"

    rows, meta = validate_paginated(
        api.list_press_lines(
            PRODUCTION_PLANNER,
            params={"line_type": "CALENDER", "limit": 10, "offset": 0},
        )
    )
    assert_pagination_meta(
        meta, expected_limit=10, expected_offset=0, expected_total=1, expected_has_more=False
    )
    assert len(rows) == 1
    assert rows[0]["line_code"] == "PL-1", (
        "the MULTI_DAY_PRESS line is excluded by the line_type filter"
    )

    _, unfiltered_meta = validate_paginated(api.list_press_lines(PRODUCTION_PLANNER))
    assert_pagination_meta(unfiltered_meta, expected_total=2)


def test_press_line_maintenance_status_blocks_new_run_scheduling(api):
    """Taking a line to MAINTENANCE bumps its version and makes the identical
    run payload that was accepted a moment earlier fail, without disturbing the
    window already reserved on it.

    "Lines are created `AVAILABLE` unless the request overrides `status`, and a
    `PlantAdmin` may later drive `status` with a `to_status` of `AVAILABLE`,
    `MAINTENANCE` or `DOWN`."
    "A line that is not `AVAILABLE` blocks run scheduling, run setup and run
    starting with `ERR_PRESS_LINE_UNAVAILABLE` (HTTP 409), while windows already
    reserved on it stay reserved."
    "Most resources additionally carry `updated_at`, in the same format,
    refreshed on every mutation, and `version`, an integer that starts at 1 on
    creation and increases by exactly 1 on every mutation of that row —
    including mutations the caller did not directly request, such as a cascade
    reaching the row from a neighbouring entity."
    "The run is created with `run_status` `PLANNED` and `qc_disposition`
    `PENDING`, with `changeover_minutes_applied` null, `actual_quantity_sqm` 0,
    `royalty_accrued_cents` 0, and every measured and derived quality field
    null."

    Design: Corner/endpoints/press_line_status_action_takes_the_line_out_of_service
    """
    built = build_certified_sku(api)
    sku_id = built["sku"]["id"]
    line = create_press_line(api)
    assert line["status"] == "AVAILABLE"

    admitted = create_run(
        api,
        sku_id,
        line["id"],
        run_code="RUN-E1",
        planned_start_utc="2026-08-01T01:00:00Z",
        planned_end_utc="2026-08-01T02:00:00Z",
        planned_quantity_sqm=10.00,
    )
    assert admitted["run_status"] == "PLANNED"

    out_of_service = validate_success(
        api.set_press_line_status(
            line["id"], press_line_status_payload("MAINTENANCE"), PLANT_ADMIN
        )
    )
    assert out_of_service["status"] == "MAINTENANCE"
    assert out_of_service["version"] == 2, (
        f"the status action is a write and bumps the version, got {out_of_service['version']}"
    )

    refused = api.create_production_run(
        production_run_payload(
            sku_id,
            line["id"],
            run_code="RUN-E2",
            planned_start_utc="2026-08-01T05:00:00Z",
            planned_end_utc="2026-08-01T06:00:00Z",
            planned_quantity_sqm=10.00,
        ),
        PRODUCTION_PLANNER,
    )
    validate_error(refused, ApiErrorId.PRESS_LINE_UNAVAILABLE.value)

    untouched = validate_success(
        api.get_production_run(admitted["id"], PRODUCTION_PLANNER)
    )
    assert untouched["run_status"] == "PLANNED", (
        "the window already reserved on the line stays reserved"
    )


# ---------------------------------------------------------------------------
# The computed SKU cost summary (PRD 3.3).
# ---------------------------------------------------------------------------


def test_sku_cost_summary_exposes_all_seven_components_without_writing(api):
    """Immediately after certification the summary reports every component, both
    bases agree exactly, and the read leaves the SKU row untouched.

    "Add those products together, divide the total by `total_phr`, and round
    half up to a whole cent."
    "The cost of a square metre is assembled from seven named components, each
    rounded half up to a whole cent on its own before any addition happens."
    "The core-compound component is the compound's blended cost per kilogram
    multiplied by 1.90 — the specific gravity in kilograms per square metre per
    millimetre — multiplied by the SKU's `overall_thickness_mm`."
    "The wear-layer component is `wear_layer_mil` multiplied by 3.5 cents per
    mil per square metre."
    "The print-film component is a base of 18 cents plus a repeat surcharge
    determined by the larger of the design's two pattern repeats: 6 cents when
    that larger repeat is at least 1800 millimetres, 2 cents when it is at least
    1200 but below 1800, and nothing below 1200."
    "The underlayment component is 0 cents for `NONE`, 22 for `IXPE_1MM`, 17 for
    `EVA_1_5MM` and 41 for `CORK_2MM`."
    "The waterproofing component is 9 cents when the SKU is `waterproof_rated`
    and zero otherwise."
    "The conversion component is a base of 35 cents plus 12 cents of click-lock
    milling when `construction_type` is `CLICK_LOCK_SPC` or `CLICK_LOCK_WPC`."
    "The seventh component is the royalty: the SKU's
    `royalty_basis_price_cents_per_sqm` multiplied by the governing grant's
    `royalty_rate_bps` divided by 10000, rounded half up to a whole cent."
    "`standard_cost_cents_per_sqm` is the exact integer sum of those seven
    rounded integers, and `list_price_cents_per_sqm` is that standard cost
    multiplied by the quantity 10000 plus `target_margin_bps`, divided by 10000,
    rounded half up to a whole cent."
    "The summary is an indicative quote readable at any certification state, so
    it never writes anything to the SKU."
    "`standard_cost_cents_per_sqm` is computed on the pinned basis described in
    §3.3 and stored, and `list_price_cents_per_sqm` is derived from it by the
    `target_margin_bps` gross-up."

    Design: Corner/endpoints/sku_cost_summary_computed_read_exposes_all_seven_components
    """
    built = build_certified_sku(api)
    sku_id = built["sku"]["id"]
    before = validate_success(api.get_product_sku(sku_id, PLANT_ADMIN))

    summary = validate_success(api.get_sku_cost_summary(sku_id, FORMULATOR))
    assert summary["pinned_basis_blended_cost_per_kg_cents"] == 201
    assert summary["pinned_basis_core_cost_cents"] == 955, (
        "201 * 1.90 * 2.50 rounded once is 955, got "
        f"{summary['pinned_basis_core_cost_cents']}"
    )
    assert summary["wear_layer_cost_cents"] == 42
    assert summary["print_film_cost_cents"] == 20
    assert summary["underlayment_cost_cents"] == 0
    assert summary["waterproof_cost_cents"] == 0
    assert summary["conversion_cost_cents"] == 35
    assert summary["royalty_cost_cents"] == 105
    assert summary["pinned_basis_standard_cost_cents_per_sqm"] == 1157, (
        "the seven independently rounded components sum to 1157, got "
        f"{summary['pinned_basis_standard_cost_cents_per_sqm']}"
    )
    assert summary["pinned_basis_list_price_cents_per_sqm"] == 1562
    assert summary["live_basis_blended_cost_per_kg_cents"] == 201
    assert summary["live_basis_core_cost_cents"] == 955
    assert summary["live_basis_standard_cost_cents_per_sqm"] == 1157
    assert summary["live_basis_list_price_cents_per_sqm"] == 1562
    assert summary["basis_delta_cents_per_sqm"] == 0, (
        "no material has been revalued since approval, so the bases agree"
    )
    assert summary["pin_stale"] is False

    after = validate_success(api.get_product_sku(sku_id, FORMULATOR))
    assert after["standard_cost_cents_per_sqm"] == 1157
    assert after["list_price_cents_per_sqm"] == 1562
    assert_version_unchanged(before, after)


# ---------------------------------------------------------------------------
# Reading allocation lines from the stock side (PRD 3.8).
# ---------------------------------------------------------------------------


def test_batch_allocation_lines_are_listable_from_the_stock_side(api):
    """The line created as a side effect of a fill is listable from the batch it
    drew against, with the drawn quantity agreeing with the batch's remaining
    stock, and the status filter narrows the sub-collection.

    "One allocation line is created per drawn batch, carrying the
    `allocation_id` it fills, the `batch_id` drawn on, the `quantity_sqm` drawn,
    and its `substitution_kind`; the batch's `available_quantity_sqm` is
    decremented by that quantity and its `version` advanced, and the remaining
    requirement falls by the same amount."
    "An `EXACT` candidate is one whose batch carries the requested `sku_id`
    itself."
    "Each line's `upgrade_cost_delta_cents` is 0 when its `substitution_kind` is
    `EXACT`."
    "The allocation's `allocated_quantity_sqm` is then the sum of its `ACTIVE`
    lines' quantities at two decimal places, and its `upgrade_cost_total_cents`
    is the exact sum of those already-rounded per-line integers."
    "Releasing moves the run's batch `IN_PRODUCTION → IN_STOCK` (or `HELD →
    IN_STOCK` when the batch was quarantined earlier) and sets
    `available_quantity_sqm` to the full `quantity_sqm`."
    "A batch's allocation lines are readable in the reverse direction,
    filterable by line `status`."

    Design: Corner/endpoints/batch_allocation_lines_reverse_link_from_stock_to_demand
    """
    built = build_filled_allocation(api, requested_quantity_sqm=100.00)
    batch_id = built["batch"]["id"]
    allocation = built["allocation"]
    assert allocation["allocated_quantity_sqm"] == 100.00

    rows, meta = validate_paginated(
        api.list_batch_allocation_lines(batch_id, PLANT_ADMIN)
    )
    assert_pagination_meta(meta, expected_total=1)
    assert len(rows) == 1
    line = rows[0]
    assert line["batch_id"] == batch_id
    assert line["allocation_id"] == allocation["id"]
    assert line["quantity_sqm"] == 100.00
    assert line["status"] == "ACTIVE"
    assert line["substitution_kind"] == "EXACT"
    assert line["upgrade_cost_delta_cents"] == 0

    batch = validate_success(api.get_batch(batch_id, PLANT_ADMIN))
    assert batch["quantity_sqm"] == 1200.00
    assert batch["available_quantity_sqm"] == 1100.00, (
        "the 100.00 drawn by the line came out of the batch's available stock, got "
        f"{batch['available_quantity_sqm']}"
    )

    voided_rows, voided_meta = validate_paginated(
        api.list_batch_allocation_lines(batch_id, PLANT_ADMIN, params={"status": "VOIDED"})
    )
    assert_pagination_meta(voided_meta, expected_total=0)
    assert voided_rows == []


# ---------------------------------------------------------------------------
# QC disposition against the four gates (PRD 3.6, 3.7).
# ---------------------------------------------------------------------------


def test_qc_release_refused_when_curl_gate_fails_and_quarantine_admitted(api):
    """One curl reading beyond the line's allowance closes the RELEASED
    disposition while QUARANTINED remains available, and the quarantine holds
    the batch.

    "The curl allowance is 2.00 millimetres multiplied by the quantity 100 minus
    the line's `curl_control_index`, divided by 100, rounded half up to two
    decimal places, and `curl_within_tolerance` holds when the absolute value of
    `curl_deviation_mm` is no greater than that allowance — so a
    better-controlled line permits less curl deviation, and a line with a
    `curl_control_index` of 100 permits none at all."
    "`registration_within_tolerance` holds when the absolute value of
    `registration_drift_mm` is no greater than the film's
    `registration_tolerance_mm`."
    "`emboss_within_tolerance` holds when the absolute difference between the
    run's `emboss_alignment_offset_mm` and the film's nominal
    `emboss_alignment_offset_mm` is no greater than 0.30 millimetres."
    "`tongue_within_tolerance` is forced true when the SKU's `profile_family` is
    `NONE`, ignoring `measured_tongue_thickness_mm` entirely; otherwise it holds
    when `measured_tongue_thickness_mm` is at least `tongue_thickness_target_mm`
    minus `tolerance_minus_mm` and no greater than `tongue_thickness_target_mm`
    plus `tolerance_plus_mm`."
    "`auto_disposition_recommendation` is set to `RELEASED` when all four gates
    hold and `QUARANTINED` otherwise; it is advisory only."
    "`PENDING → RELEASED` and `QUARANTINED → RELEASED` both require all four QC
    gates to hold. A run with any of `registration_within_tolerance`,
    `emboss_within_tolerance`, `curl_within_tolerance` or
    `tongue_within_tolerance` false may not be released, and the attempt is
    `ERR_QC_GATES_NOT_MET` (HTTP 422)."
    "The advisory recommendation runs one way only: a technician may still
    quarantine a run whose gates all hold, but may not release one whose gates
    do not."
    "`PENDING → QUARANTINED` moves the batch `IN_PRODUCTION → HELD` with
    `hold_reason` `QC_QUARANTINE` and `held_by_user_id` set to the acting
    technician — which, by §2.8, means someone else must later release it."

    Design: Corner/endpoints/qc_release_action_is_conditional_on_the_four_gate_booleans
    """
    built = build_provisional_sku(api)
    line = create_press_line(api)
    assert line["curl_control_index"] == 92

    run = run_to_completion(
        api,
        built["sku"]["id"],
        line["id"],
        completion_overrides={
            "registration_drift_mm": 0.20,
            "curl_deviation_mm": 0.30,
            "emboss_alignment_offset_mm": 0.10,
            "wear_layer_measured_mil": 12.0,
        },
    )
    assert run["registration_within_tolerance"] is True
    assert run["emboss_within_tolerance"] is True
    assert run["tongue_within_tolerance"] is True, (
        "profile_family NONE forces the tongue gate true"
    )
    assert run["curl_within_tolerance"] is False, (
        "0.30 exceeds the 0.16 curl allowance of a line at curl_control_index 92"
    )
    assert run["auto_disposition_recommendation"] == "QUARANTINED"

    refused = api.set_run_qc_disposition(
        run["id"], qc_disposition_payload("RELEASED"), QA_TECHNICIAN_B
    )
    validate_error(refused, ApiErrorId.QC_GATES_NOT_MET.value)

    quarantined = validate_success(
        api.set_run_qc_disposition(
            run["id"],
            qc_disposition_payload("QUARANTINED"),
            QA_TECHNICIAN_B,
        )
    )
    assert quarantined["qc_disposition"] == "QUARANTINED"

    batch = batch_of_run(api, run["id"], QA_TECHNICIAN)
    assert batch["status"] == "HELD"
    assert batch["hold_reason"] == "QC_QUARANTINE"
    assert batch["available_quantity_sqm"] == 0.00, (
        "a quarantined batch never reached stock, got "
        f"{batch['available_quantity_sqm']}"
    )
