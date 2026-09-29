"""Cross-cutting behaviour of the plant-operations API.

Covers the stale-view protection of PRD 2.7 on the two endpoints that carry an
expected-version field (recipe revisions and allocation fills), the pinned
versus live cost-basis divergence of PRD 3.1 and 3.3 that a material
revaluation opens up, the row-version counter of PRD 2.4 on entities that are
versioned without being concurrency-guarded, and the immediate consistency of
PRD 2.9 as observed in a mutating response body and in the first read of every
neighbour it touched.
"""

from test_helpers import (
    F_STD_COMPONENTS,
    FORMULATOR,
    PLANT_ADMIN,
    QA_TECHNICIAN,
    QA_TECHNICIAN_B,
    TECHNICAL_DIRECTOR,
    ApiErrorId,
    CLOCK_BOOT_UTC,
    assert_version_advanced,
    assert_version_unchanged,
    batch_of_run,
    build_approved_formulation,
    build_certified_sku,
    build_draft_formulation,
    build_open_allocation,
    build_stock_batch,
    complete_run,
    create_allocation,
    create_distributor,
    create_license,
    create_press_line,
    create_raw_material,
    create_run,
    distributor_headers,
    fill_allocation,
    fill_payload,
    revalue_material,
    revision_payload,
    set_clock,
    set_license_status,
    set_material_status,
    set_press_line_status,
    set_qc_disposition,
    setup_run,
    start_run,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_formulation_revision_rejects_the_stale_version_then_admits_the_refreshed_one(
    api,
):
    """A second revision of a still-APPROVED recipe is refused only by the version check.

    "Creating a revision of a recipe requires `expected_formulation_version` in
    the request body as a non-optional field, carrying the client's last
    observed `version` of the recipe being revised."
    "If that value does not equal the recipe's current `version`, the request is
    rejected with `ERR_STALE_FORMULATION_VERSION` (HTTP 412)."
    "This check cannot be replaced by a state precondition: the parent recipe
    remains `APPROVED` after a revision is created — only its
    `open_revision_count` and `version` move — so a second revision request is
    perfectly legitimate under the product semantics, and only the version
    comparison distinguishes a client that is working from an outdated view of
    the recipe it intends to supersede."
    "The new row is created in `DRAFT` with `revision` equal to the parent's
    `revision` plus one and `supersedes_formulation_id` pointing at the parent,
    and every component of the parent is copied across carrying its `phr` only —
    no cost snapshots travel with the copy, so the revision starts on a `LIVE`
    cost basis."
    "The parent's `open_revision_count` is incremented and its `version`
    advanced, but the parent **stays** `APPROVED`; it only becomes `SUPERSEDED`
    when the revision is itself approved."
    "Most resources additionally carry `updated_at`, in the same format,
    refreshed on every mutation, and `version`, an integer that starts at 1 on
    creation and increases by exactly 1 on every mutation of that row —
    including mutations the caller did not directly request, such as a cascade
    reaching the row from a neighbouring entity."
    "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` (the number of rows matching the filters before the window is
    applied) and `has_more` (true when rows remain beyond the current window)."

    Design: Corner/cross_cutting_layers/formulation_revision_occ_rejects_the_outdated_view_then_admits_the_refreshed_one
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_approved_formulation(api)
    parent = built["formulation"]
    parent_id = parent["id"]
    assert parent["status"] == "APPROVED"
    observed_version = parent["version"]

    first_revision = validate_success(
        api.create_formulation_revision(
            parent_id, revision_payload("F-MIN-R2", observed_version), FORMULATOR
        ),
        201,
    )
    assert first_revision["revision"] == 2
    parent_after_first = validate_success(api.get_formulation(parent_id, FORMULATOR))
    assert_version_advanced(parent, parent_after_first)
    assert parent_after_first["open_revision_count"] == 1
    assert parent_after_first["status"] == "APPROVED"

    # The same body replayed from the pre-revision view of the recipe.
    stale = api.create_formulation_revision(
        parent_id, revision_payload("F-MIN-R3", observed_version), FORMULATOR
    )
    validate_error(stale, ApiErrorId.STALE_FORMULATION_VERSION.value)

    parent_after_stale = validate_success(api.get_formulation(parent_id, FORMULATOR))
    assert_version_unchanged(parent_after_first, parent_after_stale)
    assert parent_after_stale["open_revision_count"] == 1
    assert parent_after_stale["status"] == "APPROVED"
    _, siblings_meta = validate_paginated(
        api.list_formulations(
            FORMULATOR, params={"supersedes_formulation_id": parent_id}
        )
    )
    assert siblings_meta["total_count"] == 1

    # Identical payload, refreshed version: two sibling revisions are legal.
    retried = validate_success(
        api.create_formulation_revision(
            parent_id,
            revision_payload("F-MIN-R3", parent_after_stale["version"]),
            FORMULATOR,
        ),
        201,
    )
    assert retried["id"] != first_revision["id"]
    assert retried["revision"] == 2
    assert retried["status"] == "DRAFT"
    assert retried["cost_basis"] == "LIVE"
    assert retried["supersedes_formulation_id"] == parent_id

    parent_final = validate_success(api.get_formulation(parent_id, FORMULATOR))
    assert_version_advanced(parent_after_stale, parent_final)
    assert parent_final["open_revision_count"] == 2
    assert parent_final["status"] == "APPROVED"
    _, siblings_meta = validate_paginated(
        api.list_formulations(
            FORMULATOR, params={"supersedes_formulation_id": parent_id}
        )
    )
    assert siblings_meta["total_count"] == 2


def test_allocation_fill_rejects_the_stale_version_even_though_fresh_stock_arrived(api):
    """A partially filled allocation refuses a replayed fill on the version alone.

    "Filling an allocation requires `expected_allocation_version` in the request
    body as a non-optional field, carrying the client's last observed `version`
    of the allocation."
    "A mismatch with the allocation's current `version` is rejected with
    `ERR_STALE_ALLOCATION_VERSION` (HTTP 412)."
    "Again a state precondition would not suffice: a partially filled allocation
    legitimately accepts a further fill, so nothing in the lifecycle rejects the
    second request."
    "Because a single request often breaks several rules at once, the server
    evaluates validations in a strict ascending order of fifteen bands and
    **stops at the first violation**; no later band is evaluated, and the
    response carries only that first rule's error."
    "Walking the candidates in rank order while the remaining requirement is
    strictly positive, each candidate contributes the smaller of the remaining
    requirement and its own `available_quantity_sqm`."
    "The allocation's resulting `status` follows from the arithmetic: `FILLED`
    when `allocated_quantity_sqm` has reached `requested_quantity_sqm`,
    `PARTIALLY_FILLED` when it is above zero but short of the request, and
    `OPEN` when it is zero."
    "Most resources additionally carry `updated_at`, in the same format,
    refreshed on every mutation, and `version`, an integer that starts at 1 on
    creation and increases by exactly 1 on every mutation of that row —
    including mutations the caller did not directly request, such as a cascade
    reaching the row from a neighbouring entity."

    Design: Corner/cross_cutting_layers/allocation_fill_occ_rejects_the_outdated_remaining_quantity
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_stock_batch(api)
    distributor = create_distributor(api)
    dist_id = distributor["id"]
    dist_headers = distributor_headers(dist_id)

    allocation = create_allocation(
        api,
        dist_id,
        built["sku"]["id"],
        headers=PLANT_ADMIN,
        allocation_code="ALLOC-OCC",
        requested_quantity_sqm=1500.00,
    )
    assert allocation["version"] == 1
    observed_version = allocation["version"]

    first_fill = fill_allocation(api, allocation["id"], dist_id, observed_version)
    assert first_fill["status"] == "PARTIALLY_FILLED"
    assert first_fill["allocated_quantity_sqm"] == 1200.00
    assert first_fill["version"] == 2

    # Fresh stock arrives, so the replayed fill would otherwise succeed.
    fresh_run = create_run(
        api,
        built["sku"]["id"],
        built["press_line"]["id"],
        run_code="RUN-A3",
        planned_start_utc="2026-08-01T09:30:00Z",
        planned_end_utc="2026-08-01T12:00:00Z",
        planned_quantity_sqm=300.00,
    )
    set_clock(api, "2026-08-01T07:30:00Z")
    setup_run(api, fresh_run["id"])
    start_run(api, fresh_run["id"])
    complete_run(
        api,
        fresh_run["id"],
        300.00,
        registration_drift_mm=0.10,
        curl_deviation_mm=0.05,
    )
    set_qc_disposition(api, fresh_run["id"], "RELEASED", QA_TECHNICIAN_B)
    fresh_batch = batch_of_run(api, fresh_run["id"])
    assert fresh_batch["available_quantity_sqm"] == 300.00

    stale = api.fill_allocation(
        allocation["id"], fill_payload(observed_version), dist_headers
    )
    validate_error(stale, ApiErrorId.STALE_ALLOCATION_VERSION.value)

    after_stale = validate_success(api.get_allocation(allocation["id"], dist_headers))
    assert after_stale["status"] == "PARTIALLY_FILLED"
    assert after_stale["allocated_quantity_sqm"] == 1200.00
    assert after_stale["version"] == 2
    _, lines_meta = validate_paginated(
        api.list_allocation_lines(allocation["id"], dist_headers)
    )
    assert lines_meta["total_count"] == 1
    fresh_batch_after_stale = validate_success(
        api.get_batch(fresh_batch["id"], QA_TECHNICIAN)
    )
    assert fresh_batch_after_stale["available_quantity_sqm"] == 300.00

    retried = validate_success(
        api.fill_allocation(
            allocation["id"], fill_payload(after_stale["version"]), dist_headers
        )
    )
    assert retried["status"] == "FILLED"
    assert retried["allocated_quantity_sqm"] == 1500.00
    assert retried["version"] == 3


def test_material_revaluation_freezes_the_pinned_recipe_and_moves_the_live_one(api):
    """One revaluation, two recipes on the same material, opposite outcomes.

    "A `PlantAdmin` may revalue a material by supplying a new
    `cost_per_kg_cents`."
    "Otherwise, every recipe whose `cost_basis` is `LIVE` (that is, every recipe
    in `DRAFT`, `UNDER_REVIEW` or `REJECTED`) that doses the material has its
    blend figures recomputed and its `version` advanced; the material's own
    `version` advances too."
    "Recipes whose `cost_basis` is `PINNED` are untouched, which means their
    `blended_cost_per_kg_cents` and every SKU standard cost stamped from them
    stay exactly as they were."
    "First, **cost pinning**: every component of the recipe receives
    `material_cost_snapshot_cents` set to its material's `cost_per_kg_cents` as
    of that instant, and `snapshot_at` set to the logical clock."
    "Second, the recipe's `cost_basis` flips to `PINNED` and
    `blended_cost_per_kg_cents` is re-derived from those snapshots rather than
    from live material costs."
    "For each component, multiply its `phr` by the per-kilogram cost that the
    recipe's cost basis dictates: while `cost_basis` is `LIVE`, that is the
    material's current `cost_per_kg_cents`; once `cost_basis` is `PINNED`, it is
    the component's own `material_cost_snapshot_cents`."
    "Add those products together, divide the total by `total_phr`, and round
    half up to a whole cent."

    Design: Corner/cross_cutting_layers/cost_revaluation_moves_live_recipes_and_leaves_pinned_snapshots_frozen
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_certified_sku(api)
    resin_id = built["materials"]["RM-RESIN"]["id"]
    stabilizer_id = built["materials"]["RM-STAB"]["id"]

    pinned = validate_success(
        api.get_formulation(built["formulation"]["id"], FORMULATOR)
    )
    assert pinned["cost_basis"] == "PINNED"
    assert pinned["blended_cost_per_kg_cents"] == 201

    live = build_draft_formulation(
        api, "F-STD", F_STD_COMPONENTS, materials=built["materials"]
    )["formulation"]
    assert live["cost_basis"] == "LIVE"
    assert live["blended_cost_per_kg_cents"] == 165

    material = revalue_material(api, resin_id, 200)
    assert material["cost_per_kg_cents"] == 200
    assert material["version"] == 2

    pinned_after = validate_success(api.get_formulation(pinned["id"], FORMULATOR))
    assert pinned_after["cost_basis"] == "PINNED"
    assert pinned_after["blended_cost_per_kg_cents"] == 201
    assert pinned_after["status"] == "APPROVED"
    assert_version_unchanged(pinned, pinned_after)

    components, _ = validate_paginated(
        api.list_formulation_components(pinned["id"], FORMULATOR)
    )
    snapshots = {
        row["raw_material_id"]: row["material_cost_snapshot_cents"]
        for row in components
    }
    assert snapshots[resin_id] == 180
    assert snapshots[stabilizer_id] == 900

    live_after = validate_success(api.get_formulation(live["id"], FORMULATOR))
    assert live_after["cost_basis"] == "LIVE"
    assert live_after["blended_cost_per_kg_cents"] == 178
    assert_version_advanced(live, live_after)


def test_material_revaluation_splits_the_two_cost_bases_on_the_sku_cost_summary(api):
    """The revaluation moves the live basis only and the stamped cost stays frozen.

    "The **pinned basis** takes the core-compound component from the
    per-component `material_cost_snapshot_cents` captured when the recipe was
    approved — equivalently, from a pinned recipe's `blended_cost_per_kg_cents`,
    which is what the SKU's `pinned_formulation_version` refers to."
    "The **live basis** re-blends the core compound from the *current*
    `cost_per_kg_cents` of every component material, ignoring the snapshots
    entirely: it sums each component's `phr` multiplied by its material's
    current cost, divides by `total_phr`, and rounds half up to a whole cent
    before the thickness and specific-gravity multiplication."
    "A material revaluation moves the live basis immediately, even for an
    approved recipe, and leaves the pinned basis bit-identical; the gap between
    the two is the plant's replacement-cost exposure."
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
    "Whenever the SKU's recipe moves to `SUPERSEDED` or `RETIRED`, or its
    `version` ceases to equal the SKU's `pinned_formulation_version`,
    `pin_stale` becomes true."

    Design: Corner/cross_cutting_layers/cost_revaluation_moves_live_recipes_and_leaves_pinned_snapshots_frozen
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_certified_sku(api)
    sku_id = built["sku"]["id"]
    assert built["sku"]["standard_cost_cents_per_sqm"] == 1157
    assert built["sku"]["list_price_cents_per_sqm"] == 1562

    revalue_material(api, built["materials"]["RM-RESIN"]["id"], 200)

    sku = validate_success(api.get_product_sku(sku_id, PLANT_ADMIN))
    assert sku["standard_cost_cents_per_sqm"] == 1157
    assert sku["list_price_cents_per_sqm"] == 1562
    assert sku["pin_stale"] is False

    summary = validate_success(api.get_sku_cost_summary(sku_id, TECHNICAL_DIRECTOR))
    assert summary["pinned_basis_blended_cost_per_kg_cents"] == 201
    assert summary["live_basis_blended_cost_per_kg_cents"] == 220
    assert summary["pinned_basis_core_cost_cents"] == 955
    assert summary["live_basis_core_cost_cents"] == 1045
    assert summary["wear_layer_cost_cents"] == 42
    assert summary["print_film_cost_cents"] == 20
    assert summary["underlayment_cost_cents"] == 0
    assert summary["waterproof_cost_cents"] == 0
    assert summary["conversion_cost_cents"] == 35
    assert summary["royalty_cost_cents"] == 105
    assert summary["pinned_basis_standard_cost_cents_per_sqm"] == 1157
    assert summary["live_basis_standard_cost_cents_per_sqm"] == 1247
    assert summary["basis_delta_cents_per_sqm"] == 90
    assert summary["pinned_basis_list_price_cents_per_sqm"] == 1562
    assert summary["live_basis_list_price_cents_per_sqm"] == 1683
    assert summary["pin_stale"] is False

    sku_after_summary = validate_success(api.get_product_sku(sku_id, PLANT_ADMIN))
    assert sku_after_summary["standard_cost_cents_per_sqm"] == 1157
    assert_version_unchanged(sku, sku_after_summary)


def test_version_counter_advances_once_per_write_and_never_on_a_read(api):
    """Three entities that carry no expected-version input still count every write.

    "Most resources additionally carry `updated_at`, in the same format,
    refreshed on every mutation, and `version`, an integer that starts at 1 on
    creation and increases by exactly 1 on every mutation of that row —
    including mutations the caller did not directly request, such as a cascade
    reaching the row from a neighbouring entity."
    "No other endpoint in the system takes a version field."
    "A `PlantAdmin` may revalue a material by supplying a new
    `cost_per_kg_cents`."
    "Moving a material to `RESTRICTED` starts the plant's deepest cascade."
    "Lines are created `AVAILABLE` unless the request overrides `status`, and a
    `PlantAdmin` may later drive `status` with a `to_status` of `AVAILABLE`,
    `MAINTENANCE` or `DOWN`."
    "`ACTIVE → SUSPENDED` is a `PlantAdmin` action and cascades three hops:
    every `AVAILABLE` film on the grant moves to `RESTRICTED`; because those
    films were restricted, every SKU on one of them whose `commercial_status` is
    `RELEASED` moves to `HOLD`; and because those SKUs went on hold, each of
    their `IN_STOCK` batches moves to `HELD` with `hold_reason` `SKU_ON_HOLD`."
    "`SUSPENDED → ACTIVE` is the reverse edge, permitted only while the logical
    clock is strictly earlier than the grant's `valid_until`; it returns
    `RESTRICTED` films to `AVAILABLE` and stops there."
    "A grant's utilization is readable as a computed summary carrying
    `term_volume_cap_sqm`, `reserved_volume_sqm`, `consumed_volume_sqm`, the
    forward-looking `projected_volume_sqm` (consumed plus reserved), the
    `remaining_volume_sqm` left under the cap (the cap less the projection), the
    `accrued_royalty_cents` ledger, and `contributing_run_count`, the number of
    completed runs that have contributed royalty to it."

    Design: Corner/cross_cutting_layers/version_counter_advances_on_every_write_and_never_on_a_read
    """
    set_clock(api, CLOCK_BOOT_UTC)

    material = create_raw_material(api, "RM-FILLER")
    assert material["version"] == 1
    revalued = revalue_material(api, material["id"], 50)
    assert revalued["cost_per_kg_cents"] == 50
    assert revalued["version"] == 2

    first_read = validate_success(api.get_raw_material(material["id"], PLANT_ADMIN))
    assert first_read["version"] == 2
    second_read = validate_success(api.get_raw_material(material["id"], PLANT_ADMIN))
    assert second_read["version"] == 2

    restricted = set_material_status(api, material["id"], "RESTRICTED")
    assert restricted["status"] == "RESTRICTED"
    assert restricted["version"] == 3
    read_after_status = validate_success(
        api.get_raw_material(material["id"], PLANT_ADMIN)
    )
    assert read_after_status["version"] == 3

    line = create_press_line(api)
    assert line["version"] == 1
    maintenance = set_press_line_status(api, line["id"], "MAINTENANCE")
    assert maintenance["status"] == "MAINTENANCE"
    assert maintenance["version"] == 2
    line_read = validate_success(api.get_press_line(line["id"], PLANT_ADMIN))
    assert line_read["version"] == 2

    grant = create_license(api)
    assert grant["version"] == 1
    suspended = set_license_status(api, grant["id"], "SUSPENDED")
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == 2
    reactivated = set_license_status(api, grant["id"], "ACTIVE")
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["version"] == 3

    # A computed read of the same row must not advance the counter either.
    validate_success(api.get_license_utilization(grant["id"], PLANT_ADMIN))
    grant_read = validate_success(api.get_design_license(grant["id"], PLANT_ADMIN))
    assert grant_read["status"] == "ACTIVE"
    assert grant_read["version"] == 3


def test_fill_response_already_carries_every_derived_consequence(api):
    """The fill response, and the first read of each neighbour, are already settled.

    "Consistency in this system is immediate: when an operation's effects reach
    other entities, those effects land inside the same request, and a client
    reading any touched row immediately afterwards sees the settled state."
    "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."
    "An `EXACT` candidate is one whose batch carries the requested `sku_id`
    itself."
    "One allocation line is created per drawn batch, carrying the
    `allocation_id` it fills, the `batch_id` drawn on, the `quantity_sqm` drawn,
    and its `substitution_kind`; the batch's `available_quantity_sqm` is
    decremented by that quantity and its `version` advanced, and the remaining
    requirement falls by the same amount."
    "Each line's `upgrade_cost_delta_cents` is 0 when its `substitution_kind` is
    `EXACT`."
    "The allocation's `allocated_quantity_sqm` is then the sum of its `ACTIVE`
    lines' quantities at two decimal places, and its `upgrade_cost_total_cents`
    is the exact sum of those already-rounded per-line integers."
    "The allocation's resulting `status` follows from the arithmetic: `FILLED`
    when `allocated_quantity_sqm` has reached `requested_quantity_sqm`,
    `PARTIALLY_FILLED` when it is above zero but short of the request, and
    `OPEN` when it is zero."
    "Releasing moves the run's batch `IN_PRODUCTION → IN_STOCK` (or `HELD →
    IN_STOCK` when the batch was quarantined earlier) and sets
    `available_quantity_sqm` to the full `quantity_sqm`."
    "Second, the licensed-volume ledger settles on an actual basis: the run's
    `planned_quantity_sqm` is subtracted from the grant's `reserved_volume_sqm`
    and the measured `actual_quantity_sqm` is added to its
    `consumed_volume_sqm`."
    "The run's `actual_quantity_sqm` is multiplied by the SKU's
    `royalty_basis_price_cents_per_sqm` and by the grant's `royalty_rate_bps`
    divided by 10000, and the product is rounded half up to a whole cent."

    Design: Corner/consistency_model/every_derived_consequence_is_visible_in_the_same_response
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_open_allocation(api)
    allocation = built["allocation"]
    batch_id = built["batch"]["id"]
    dist_headers = distributor_headers(built["distributor"]["id"])
    assert allocation["status"] == "OPEN"
    assert allocation["version"] == 1

    # The mutating response body itself, with no follow-up read.
    filled = validate_success(
        api.fill_allocation(
            allocation["id"], fill_payload(allocation["version"]), dist_headers
        )
    )
    assert filled["status"] == "FILLED"
    assert filled["allocated_quantity_sqm"] == 100.00
    assert filled["upgrade_cost_total_cents"] == 0
    assert filled["version"] == 2

    lines, lines_meta = validate_paginated(
        api.list_allocation_lines(allocation["id"], dist_headers)
    )
    assert lines_meta["total_count"] == 1
    assert lines[0]["batch_id"] == batch_id
    assert lines[0]["quantity_sqm"] == 100.00
    assert lines[0]["status"] == "ACTIVE"
    assert lines[0]["substitution_kind"] == "EXACT"
    assert lines[0]["upgrade_cost_delta_cents"] == 0

    batch = validate_success(api.get_batch(batch_id, QA_TECHNICIAN))
    assert batch["quantity_sqm"] == 1200.00
    assert batch["available_quantity_sqm"] == 1100.00

    utilization = validate_success(
        api.get_license_utilization(built["license"]["id"], TECHNICAL_DIRECTOR)
    )
    assert utilization["reserved_volume_sqm"] == 0
    assert utilization["consumed_volume_sqm"] == 1200.00
    assert utilization["accrued_royalty_cents"] == 126000
