"""Entity shapes, declared defaults, server-minted fields and graph topology.

These tests cover the persisted-resource contract of PRD §2.4 (server-minted
`id`, logical-clock timestamps, `version` starting at 1 and the `TestResult`
exception that carries neither `updated_at` nor `version`), the list envelope and
pagination bounds of PRD §2.2-§2.3, the shape and existence bands of PRD §2.5,
the declared creation defaults and computed fields of the raw-material,
distributor, recipe and SKU registrations in PRD §3.1, §3.3 and §3.8, the
immutable laboratory measurement of PRD §3.4, and the two navigable edges of the
compounding graph — the recipe/material junction readable from both parents and
the self-referential revision edge of PRD §3.1.
"""

from test_helpers import (
    ApiErrorId,
    CLOCK_BOOT_UTC,
    FORMULATOR,
    FORMULATOR_B,
    NON_EXISTENT_UUID,
    PLANT_ADMIN,
    QA_TECHNICIAN,
    add_component,
    assert_common_fields,
    assert_created_defaults,
    assert_pagination_meta,
    assert_test_result_shape,
    assert_warranty_terms,
    begin_testing,
    build_approved_formulation,
    build_draft_formulation,
    build_licensed_film,
    build_sku,
    click_lock_sku_payload,
    create_formulation,
    create_panel,
    create_raw_material,
    distributor_payload,
    formulation_payload,
    get_success_data,
    product_sku_payload,
    raw_material_payload,
    record_result,
    seed_materials,
    set_clock,
    start_panel,
    validate_error,
    validate_paginated,
    validate_success,
)

# PRD §2.4: "an ISO 8601 UTC timestamp with three fractional digits" stamped
# from the logical clock, which this suite parks at its boot instant.
CLOCK_BOOT_STAMP = "2026-08-01T00:00:00.000Z"


def test_distributor_creation_defaults_status_and_mints_system_fields(api):
    """A minimal distributor body plus the one optional flag: `status` defaults to
    ACTIVE, the four common fields are server-minted and `version` starts at 1.

    "Distributors are the plant's trading partners, registered by a `PlantAdmin`
    with an `account_code` unique across distributors and between 3 and 32
    characters long, a legal `name`, a `territory_code` of exactly two uppercase
    letters naming the territory sold into, and an optional
    `certified_installer_program` flag (false by default) recording participation
    in the certified-installer scheme — the flag that later unlocks a labour
    allowance on warranty settlements."
    "A distributor is created `ACTIVE` unless the request overrides `status`."
    "Every persisted resource carries a server-minted `id` in UUID form, with no
    type prefix and no client control over its value."
    "Every resource also carries `created_at`, an ISO 8601 UTC timestamp with
    three fractional digits, stamped when the row is first written."
    "Most resources additionally carry `updated_at`, in the same format,
    refreshed on every mutation, and `version`, an integer that starts at 1 on
    creation and increases by exactly 1 on every mutation of that row —
    including mutations the caller did not directly request, such as a cascade
    reaching the row from a neighbouring entity."
    "Every timestamp the server stamps — `created_at`, `updated_at`,
    `approved_at`, `certified_at`, `snapshot_at` — and every comparison the
    server makes against "now" reads a **logical clock**, never the host wall
    clock."

    Design: Corner/entities/distributor_create_returns_declared_defaults_and_system_fields
    """
    set_clock(api, CLOCK_BOOT_UTC)

    response = api.create_distributor(
        distributor_payload(
            account_code="D-100",
            name="Northline Floors LLC",
            territory_code="US",
            certified_installer_program=True,
        ),
        PLANT_ADMIN,
    )
    distributor = validate_success(response, 201)

    assert distributor["account_code"] == "D-100"
    assert distributor["name"] == "Northline Floors LLC"
    assert distributor["territory_code"] == "US"
    # The supplied optional flag is honoured rather than defaulted away.
    assert distributor["certified_installer_program"] is True
    assert distributor["status"] == "ACTIVE"

    assert_created_defaults(distributor)
    assert distributor["version"] == 1
    assert distributor["created_at"] == CLOCK_BOOT_STAMP
    assert distributor["updated_at"] == CLOCK_BOOT_STAMP


def test_raw_material_single_read_returns_every_stored_field(api):
    """A single-row read of a registered material returns all nine stored fields
    at their registered values, with `status` at its creation default.

    "Each material is registered with a `material_code` that must be unique
    across the library (a repeat is `ERR_DUPLICATE_CODE`, HTTP 409), a trade
    `name`, a `category` naming its formulation role, a purchase cost held as
    `cost_per_kg_cents` in whole cents per kilogram of at least 1, and four
    technical properties: `indentation_index` and `thermal_stability_index`, both
    scored 0 to 100 with higher being better; `plasticizer_migration_index`, also
    0 to 100 but with higher being *worse*; and `max_phr`, strictly greater than
    zero, the largest parts-per-hundred-resin dosage the material may ever take
    in a recipe."
    "A material is created `ACTIVE` unless the creating request overrides
    `status`."

    Design: Corner/entities/raw_material_retrieval_returns_every_stored_field
    """
    set_clock(api, CLOCK_BOOT_UTC)
    created = create_raw_material(api, "RM-RESIN")

    material = validate_success(api.get_raw_material(created["id"], FORMULATOR))

    assert material["id"] == created["id"]
    assert material["material_code"] == "RM-RESIN"
    assert material["name"] == "Suspension PVC K67"
    assert material["category"] == "VINYL_RESIN"
    assert material["cost_per_kg_cents"] == 180
    assert material["indentation_index"] == 90
    assert material["thermal_stability_index"] == 85
    assert material["plasticizer_migration_index"] == 5
    assert material["max_phr"] == 100
    assert material["status"] == "ACTIVE"
    assert_common_fields(material, expected_version=1)


def test_raw_material_listing_windows_three_rows_two_at_a_time(api):
    """Three materials read two at a time: page one reports total_count 3 with
    has_more true, page two exactly one row with has_more false.

    "Every collection read accepts two optional query parameters."
    "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` (the number of rows matching the filters before the window is
    applied) and `has_more` (true when rows remain beyond the current window)."
    "The `response_type` is either "object" for a single resource or "array" for
    a list of resources."

    Design: Corner/entities/raw_material_listing_paginates_with_total_count_and_has_more
    """
    set_clock(api, CLOCK_BOOT_UTC)
    seed_materials(api, ["RM-RESIN", "RM-STAB", "RM-FILLER"])

    first_response = api.list_raw_materials(FORMULATOR, params={"limit": 2, "offset": 0})
    page_one, meta_one = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert len(page_one) == 2
    assert_pagination_meta(
        meta_one,
        expected_limit=2,
        expected_offset=0,
        expected_total=3,
        expected_has_more=True,
    )

    second_response = api.list_raw_materials(FORMULATOR, params={"limit": 2, "offset": 2})
    page_two, meta_two = validate_paginated(second_response)
    assert len(page_two) == 1
    assert_pagination_meta(
        meta_two,
        expected_limit=2,
        expected_offset=2,
        expected_total=3,
        expected_has_more=False,
    )

    windowed_codes = [row["material_code"] for row in page_one + page_two]
    assert page_one[0]["material_code"] != page_two[0]["material_code"]
    assert len(windowed_codes) == len(set(windowed_codes)), (
        f"a row was repeated across the two windows: {windowed_codes}"
    )
    assert set(windowed_codes) == {"RM-RESIN", "RM-STAB", "RM-FILLER"}


def test_unknown_product_sku_id_returns_entity_specific_not_found(api):
    """A syntactically valid UUID matching no SKU row is refused on a read path
    with the SKU's own not-found code.

    "Path resource existence — the `{id}` (or `{component_id}`) segment must
    address an existing row of the collection named by its own segment;
    otherwise the not-found code for that entity is returned with HTTP 404."
    "The twelve codes are `ERR_DISTRIBUTOR_NOT_FOUND`,
    `ERR_RAW_MATERIAL_NOT_FOUND`, `ERR_FORMULATION_NOT_FOUND`,
    `ERR_FORMULATION_COMPONENT_NOT_FOUND`, `ERR_DESIGN_LICENSE_NOT_FOUND`,
    `ERR_PRINT_FILM_NOT_FOUND`, `ERR_PRODUCT_SKU_NOT_FOUND`,
    `ERR_PRESS_LINE_NOT_FOUND`, `ERR_TEST_PANEL_NOT_FOUND`,
    `ERR_PRODUCTION_RUN_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`,
    `ERR_ALLOCATION_NOT_FOUND` and `ERR_WARRANTY_CLAIM_NOT_FOUND`."

    Design: Corner/entities/product_sku_unknown_id_returns_not_found
    """
    set_clock(api, CLOCK_BOOT_UTC)

    response = api.get_product_sku(NON_EXISTENT_UUID, PLANT_ADMIN)

    error = validate_error(response, ApiErrorId.PRODUCT_SKU_NOT_FOUND.value)
    assert response.json()["response_type"] == "error"
    assert error["message"].strip() != ""


def test_raw_material_without_max_phr_is_refused_as_malformed(api):
    """`max_phr` is a required input with no declared default, so omitting it is a
    band-3 shape violation and nothing is persisted.

    "Each material is registered with a `material_code` that must be unique
    across the library (a repeat is `ERR_DUPLICATE_CODE`, HTTP 409), a trade
    `name`, a `category` naming its formulation role, a purchase cost held as
    `cost_per_kg_cents` in whole cents per kilogram of at least 1, and four
    technical properties: `indentation_index` and `thermal_stability_index`, both
    scored 0 to 100 with higher being better; `plasticizer_migration_index`, also
    0 to 100 but with higher being *worse*; and `max_phr`, strictly greater than
    zero, the largest parts-per-hundred-resin dosage the material may ever take
    in a recipe."
    "Request shape — missing required fields, wrong JSON types, enum values
    outside their declared sets, numeric ranges and decimal-place limits,
    pagination bounds, and the cross-field shape rules described with the
    workflows they guard."

    Design: Corner/entities/raw_material_missing_required_field_returns_invalid_request
    """
    set_clock(api, CLOCK_BOOT_UTC)

    response = api.create_raw_material(
        raw_material_payload(
            "RM-NOMAX",
            name="Unbounded Filler",
            category="FILLER",
            cost_per_kg_cents=45,
            indentation_index=96,
            thermal_stability_index=92,
            plasticizer_migration_index=1,
            max_phr=None,
        ),
        PLANT_ADMIN,
    )

    validate_error(response, ApiErrorId.INVALID_REQUEST.value)

    _, meta = validate_paginated(api.list_raw_materials(PLANT_ADMIN))
    assert meta["total_count"] == 0, "the rejected material must not have been stored"


def test_product_sku_omitted_optionals_take_their_declared_defaults(api):
    """A SKU created with only its required inputs takes all six declared
    defaults and leaves every derived commercial figure unset.

    "Optional inputs are `waterproof_rated` (false by default),
    `attached_underlayment_type` (`NONE` by default), `profile_family` (`NONE` by
    default), `tongue_thickness_target_mm`, `tolerance_plus_mm`,
    `tolerance_minus_mm`, `target_lock_shear_n_per_mm` (all null by default) and
    `target_margin_bps` (3500 by default, and constrained to the range 0 through
    9000)."
    "A new SKU is created with `certification_status` `UNCERTIFIED` and
    `commercial_status` `DEVELOPMENT`; `pinned_formulation_version`,
    `pinned_print_film_version`, `standard_cost_cents_per_sqm`,
    `list_price_cents_per_sqm`, `certified_at` and `certified_by_user_id` are all
    null, and `pin_stale` is false."

    Design: Corner/entities/product_sku_omitted_optionals_take_declared_defaults
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_draft_formulation(api)
    licensed = build_licensed_film(api)

    response = api.create_product_sku(
        product_sku_payload(built["formulation"]["id"], licensed["film"]["id"]),
        PLANT_ADMIN,
    )
    sku = validate_success(response, 201)

    assert sku["waterproof_rated"] is False
    assert sku["attached_underlayment_type"] == "NONE"
    assert sku["profile_family"] == "NONE"
    assert sku["tongue_thickness_target_mm"] is None
    assert sku["tolerance_plus_mm"] is None
    assert sku["tolerance_minus_mm"] is None
    assert sku["target_lock_shear_n_per_mm"] is None
    assert sku["target_margin_bps"] == 3500
    assert sku["certification_status"] == "UNCERTIFIED"
    assert sku["commercial_status"] == "DEVELOPMENT"
    assert sku["pinned_formulation_version"] is None
    assert sku["pinned_print_film_version"] is None
    assert sku["standard_cost_cents_per_sqm"] is None
    assert sku["list_price_cents_per_sqm"] is None
    assert sku["certified_at"] is None
    assert sku["certified_by_user_id"] is None
    assert sku["pin_stale"] is False


def test_product_sku_warranty_terms_are_computed_not_taken_from_the_body(api):
    """A waterproof CLICK_LOCK_SPC SKU at 20 mil takes 25+5 capped to 30 and 15+5
    capped to 20 from the tier table, never the 99/99 sent in the body.

    "Warranty terms are derived at creation from the wear layer and the
    construction, and they are the figures a warranty settlement years later will
    divide by."
    "The residential term is 25 years when `wear_layer_mil` is at least 20, 20
    years when it is at least 12 but below 20, 15 years when it is at least 6 but
    below 12, and 10 years otherwise."
    "The light-commercial term over the same tiers is 15, 10, 5 and 0 years."
    "A bonus of 5 years is added to both terms when — and only when — the SKU is
    both `waterproof_rated` and built on a `CLICK_LOCK_SPC` or `CLICK_LOCK_WPC`
    construction; a waterproof `GLUE_DOWN` plank earns nothing."
    "The residential result is then capped at 30 years and stored as
    `warranty_years`, and the light-commercial result is capped at 20 years and
    stored as `light_commercial_warranty_years`."
    "All tier thresholds are inclusive, so a wear layer of exactly 20 mil takes
    the top tier and exactly 12 mil gives 20 residential and 10 light-commercial
    years."

    Design: Corner/entities/product_sku_warranty_terms_computed_and_extra_field_rejected_as_input
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_draft_formulation(api)
    licensed = build_licensed_film(api)

    response = api.create_product_sku(
        click_lock_sku_payload(
            built["formulation"]["id"],
            licensed["film"]["id"],
            warranty_years=99,
            light_commercial_warranty_years=99,
        ),
        PLANT_ADMIN,
    )
    sku = validate_success(response, 201)

    assert_warranty_terms(sku, residential=30, light_commercial=20)
    assert sku["warranty_years"] != 99
    assert sku["light_commercial_warranty_years"] != 99


def test_formulation_author_and_revision_come_from_the_server_not_the_body(api):
    """`authored_by_user_id` is stamped from `X-User-ID` and `revision` is minted
    as 1, whatever the request body claims.

    "Recipes are authored by a `Formulator`, who supplies a `formulation_code`
    unique across recipes and, when the new recipe is intended to replace an
    existing approved one, the `supersedes_formulation_id` of that predecessor;
    for an original recipe the field is null."
    "A newly created recipe is `DRAFT` with `revision` 1, `cost_basis` `LIVE`,
    `rejection_count` and `open_revision_count` both 0, and
    `authored_by_user_id` set to the acting `X-User-ID`."
    "Its `submitted_by_user_id`, `approved_by_user_id` and `approved_at` are
    null."

    Design: Corner/entities/formulation_author_stamped_from_header_with_ignored_input
    """
    set_clock(api, CLOCK_BOOT_UTC)

    response = api.create_formulation(
        formulation_payload(
            "F-SYS",
            authored_by_user_id="form-999",
            revision=7,
            status="APPROVED",
        ),
        FORMULATOR_B,
    )
    formulation = validate_success(response, 201)

    assert formulation["authored_by_user_id"] == "form-002"
    assert formulation["authored_by_user_id"] != "form-999"
    assert formulation["revision"] == 1
    assert formulation["status"] == "DRAFT"
    assert formulation["cost_basis"] == "LIVE"
    assert formulation["rejection_count"] == 0
    assert formulation["open_revision_count"] == 0
    assert formulation["supersedes_formulation_id"] is None
    assert formulation["submitted_by_user_id"] is None
    assert formulation["approved_by_user_id"] is None
    assert formulation["approved_at"] is None


def test_raw_material_shape_faults_and_pagination_bound_are_all_malformed(api):
    """An index above its declared range, an enum outside its declared set and a
    pagination limit above 100 are all band-3 shape faults, while limit 100 is
    itself legal.

    "Each material is registered with a `material_code` that must be unique
    across the library (a repeat is `ERR_DUPLICATE_CODE`, HTTP 409), a trade
    `name`, a `category` naming its formulation role, a purchase cost held as
    `cost_per_kg_cents` in whole cents per kilogram of at least 1, and four
    technical properties: `indentation_index` and `thermal_stability_index`, both
    scored 0 to 100 with higher being better; `plasticizer_migration_index`, also
    0 to 100 but with higher being *worse*; and `max_phr`, strictly greater than
    zero, the largest parts-per-hundred-resin dosage the material may ever take
    in a recipe."
    "Every enumerated value in this system is an exact uppercase string, and a
    value outside the declared set is a shape error (`ERR_INVALID_REQUEST`, HTTP
    400) rather than a business error."
    "A raw material's `category` is `VINYL_RESIN`, `PLASTICIZER`, `FILLER` or
    `STABILIZER`; its `status` is `ACTIVE`, `RESTRICTED` or `DISCONTINUED`."
    "`limit` defaults to 10, may be no smaller than 1 and no larger than 100."
    "A `limit` outside the range 1 through 100, or a negative `offset`, is a
    malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/raw_material_out_of_range_index_returns_invalid_request
    """
    set_clock(api, CLOCK_BOOT_UTC)

    out_of_range = api.create_raw_material(
        raw_material_payload(
            "RM-BAD1",
            name="Impossible Resin",
            category="VINYL_RESIN",
            cost_per_kg_cents=180,
            indentation_index=101,
            thermal_stability_index=85,
            plasticizer_migration_index=5,
            max_phr=100,
        ),
        PLANT_ADMIN,
    )
    validate_error(out_of_range, ApiErrorId.INVALID_REQUEST.value)

    bad_enum = api.create_raw_material(
        raw_material_payload(
            "RM-BAD2",
            name="Mystery Powder",
            category="GLITTER",
            cost_per_kg_cents=180,
            indentation_index=90,
            thermal_stability_index=85,
            plasticizer_migration_index=5,
            max_phr=100,
        ),
        PLANT_ADMIN,
    )
    validate_error(bad_enum, ApiErrorId.INVALID_REQUEST.value)

    over_limit = api.list_raw_materials(PLANT_ADMIN, params={"limit": 101})
    validate_error(over_limit, ApiErrorId.INVALID_REQUEST.value)

    at_limit = api.list_raw_materials(PLANT_ADMIN, params={"limit": 100})
    rows, meta = validate_paginated(at_limit)
    assert meta["limit"] == 100
    assert meta["total_count"] == 0
    assert rows == []


def test_recorded_measurement_carries_no_version_and_cannot_be_rewritten(api):
    """A `TestResult` carries only `id` and `created_at` alongside its data, and
    re-posting the same test type at the same attempt is refused rather than
    overwriting the stored measurement.

    "A laboratory measurement is immutable once recorded: a `TestResult` row
    carries only `id` and `created_at`."
    "It has neither `updated_at` nor `version`, and no operation ever rewrites
    one."
    "A new panel is `SCHEDULED` with `attempt_no` 1, `retest_count` 0,
    `void_reason` and `started_by_user_id` null, and `required_test_types`
    derived from the SKU."
    "A measurement is created carrying the panel's `test_panel_id`, the
    `attempt_no` in force when it was taken, the `recorded_by_user_id` of the
    acting technician, and three server-computed fields: `unit`, `spec_limit` and
    `outcome`."
    "`RESIDUAL_INDENTATION` is measured in `mm` and lower is better, with a limit
    of 0.10 when the SKU's recipe sits in `CLASS_34_43`, 0.20 for `CLASS_33_42`
    and 0.30 for `CLASS_23_31`."
    "For a lower-is-better test the marginal edge is the limit multiplied by
    1.05, rounded half up to four decimal places; a `measured_value` no greater
    than the limit is `PASS`, a value above the limit but no greater than the
    marginal edge is `MARGINAL`, and anything larger is `FAIL`."
    "The `test_type` must be a member of the panel's `required_test_types`, and
    no measurement of that type may already exist at the panel's current
    `attempt_no`; either violation is `ERR_INVALID_REQUEST` (HTTP 400), evaluated
    against stored state in band 12 rather than at shape time."

    Design: Corner/entities/test_result_is_immutable_and_carries_no_version
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_sku(api)
    begin_testing(api, built["sku"]["id"])
    panel = create_panel(api, built["sku"]["id"], "TP-A1")
    start_panel(api, panel["id"])
    record_result(api, panel["id"], "RESIDUAL_INDENTATION", 0.0800)

    rows, meta = validate_paginated(api.list_test_results(panel["id"], QA_TECHNICIAN))
    assert meta["total_count"] == 1
    measurement = rows[0]
    assert_test_result_shape(measurement)
    assert measurement["outcome"] == "PASS"
    assert measurement["recorded_by_user_id"] == "qa-001"
    assert measurement["attempt_no"] == 1

    duplicate = api.record_test_result(
        panel["id"],
        {"test_type": "RESIDUAL_INDENTATION", "measured_value": 0.0500},
        QA_TECHNICIAN,
    )
    validate_error(duplicate, ApiErrorId.INVALID_REQUEST.value)

    after_rows, after_meta = validate_paginated(
        api.list_test_results(panel["id"], QA_TECHNICIAN)
    )
    assert after_meta["total_count"] == 1
    assert after_rows[0]["measured_value"] == 0.0800
    assert after_rows[0]["id"] == measurement["id"]


def test_component_creation_resolves_path_parent_before_body_reference(api):
    """A component's two parents fail with their own not-found codes: the body's
    unknown material in band 5 and the path's unknown recipe in band 4.

    "Path resource existence — the `{id}` (or `{component_id}`) segment must
    address an existing row of the collection named by its own segment;
    otherwise the not-found code for that entity is returned with HTTP 404."
    "Body reference existence — every foreign key in the body must address an
    existing row, or that entity's not-found code from the list above is returned
    with HTTP 404: `formulation_id` and `supersedes_formulation_id` against
    recipes, `raw_material_id` against materials, `license_id` and
    `supersedes_license_id` against design grants, `print_film_id` against films,
    `sku_id` against SKUs, `press_line_id` against lines, `distributor_id`
    against distributors, `batch_id` against batches, and `production_run_id`
    against runs."
    "A recipe with no components has `total_phr` of 0.00 and every other derived
    figure null."

    Design: Corner/entities/formulation_component_with_unknown_material_returns_not_found
    """
    set_clock(api, CLOCK_BOOT_UTC)
    material = create_raw_material(api, "RM-RESIN")
    formulation = create_formulation(api, "F-MIN")

    unknown_material = api.add_formulation_component(
        formulation["id"],
        {"raw_material_id": NON_EXISTENT_UUID, "phr": 100},
        FORMULATOR,
    )
    validate_error(unknown_material, ApiErrorId.RAW_MATERIAL_NOT_FOUND.value)

    unknown_recipe = api.add_formulation_component(
        NON_EXISTENT_UUID,
        {"raw_material_id": material["id"], "phr": 100},
        FORMULATOR,
    )
    validate_error(unknown_recipe, ApiErrorId.FORMULATION_NOT_FOUND.value)

    _, meta = validate_paginated(
        api.list_formulation_components(formulation["id"], FORMULATOR)
    )
    assert meta["total_count"] == 0
    unchanged = validate_success(api.get_formulation(formulation["id"], FORMULATOR))
    assert unchanged["total_phr"] == 0.00


def test_recipe_material_junction_is_listable_from_both_parents(api):
    """The many-to-many recipe/material junction reads from either side, and one
    material is visible from the two different recipes that dose it.

    "Dosing a recipe means adding components."
    "Each component names the `raw_material_id` being dosed and the `phr` dosed,
    strictly greater than zero with at most two decimal places."
    "A material's component usages are readable in the reverse direction, so an
    administrator can see which recipes a candidate restriction would retire
    before issuing it."
    "Several reads address a child collection through its parent — a recipe's
    components, a raw material's component usages, a panel's results, a batch's
    allocation lines, an allocation's lines, a grant's utilization summary, a
    SKU's cost summary."

    Design: Corner/entities/formulation_component_junction_reachable_from_both_parents
    """
    set_clock(api, CLOCK_BOOT_UTC)
    materials = seed_materials(api, ["RM-RESIN", "RM-STAB", "RM-FILLER", "RM-SOFT"])

    f_min = create_formulation(api, "F-MIN")
    add_component(api, f_min["id"], materials["RM-RESIN"]["id"], 100)
    add_component(api, f_min["id"], materials["RM-STAB"]["id"], 3)

    f_std = create_formulation(api, "F-STD")
    add_component(api, f_std["id"], materials["RM-RESIN"]["id"], 100)
    add_component(api, f_std["id"], materials["RM-SOFT"]["id"], 25)
    add_component(api, f_std["id"], materials["RM-FILLER"]["id"], 40)

    min_rows, min_meta = validate_paginated(
        api.list_formulation_components(f_min["id"], FORMULATOR)
    )
    assert min_meta["total_count"] == 2
    assert [row["formulation_id"] for row in min_rows] == [f_min["id"], f_min["id"]]

    _, std_meta = validate_paginated(
        api.list_formulation_components(f_std["id"], FORMULATOR)
    )
    assert std_meta["total_count"] == 3

    resin_rows, resin_meta = validate_paginated(
        api.list_raw_material_formulation_components(
            materials["RM-RESIN"]["id"], FORMULATOR
        )
    )
    assert resin_meta["total_count"] == 2
    assert all(row["raw_material_id"] == materials["RM-RESIN"]["id"] for row in resin_rows)
    assert {row["formulation_id"] for row in resin_rows} == {f_min["id"], f_std["id"]}

    soft_rows, soft_meta = validate_paginated(
        api.list_raw_material_formulation_components(
            materials["RM-SOFT"]["id"], FORMULATOR
        )
    )
    assert soft_meta["total_count"] == 1
    assert soft_rows[0]["formulation_id"] == f_std["id"]


def test_revision_edge_is_navigable_from_the_superseded_predecessor(api):
    """A revision derives its `revision` from the parent, points back at it, and
    is reachable through the declared `supersedes_formulation_id` filter while
    the parent stays APPROVED.

    "A `Formulator` may open a revision of an approved recipe by supplying a new
    `formulation_code` together with `expected_formulation_version` as described
    in §2.7."
    "The new row is created in `DRAFT` with `revision` equal to the parent's
    `revision` plus one and `supersedes_formulation_id` pointing at the parent,
    and every component of the parent is copied across carrying its `phr` only —
    no cost snapshots travel with the copy, so the revision starts on a `LIVE`
    cost basis."
    "The parent's `open_revision_count` is incremented and its `version`
    advanced, but the parent **stays** `APPROVED`; it only becomes `SUPERSEDED`
    when the revision is itself approved."
    "Collection reads support equality filters drawn from the same vocabulary,
    combined with logical AND when more than one is supplied."
    "Distributors filter on `status` and `territory_code`; raw materials on
    `category` and `status`; recipes on `status`, `supersedes_formulation_id` and
    `indentation_resistance_class`; design grants on `status`,
    `supersedes_license_id` and `license_type`; print films on `status` and
    `license_id`; SKUs on `certification_status`, `commercial_status`,
    `formulation_id`, `print_film_id` and `construction_type`; press lines on
    `status` and `line_type`; test panels on `status` and `sku_id`; panel results
    on `test_type`; production runs on `run_status`, `qc_disposition`, `sku_id`
    and `press_line_id`; batches on `status`, `sku_id` and `production_run_id`;
    batch allocation-line and allocation-line reads on `status`; allocations on
    `status`, `distributor_id` and `sku_id`; warranty claims on `status`,
    `batch_id`, `distributor_id` and `claim_type`."

    Design: Corner/entities/formulation_self_referential_revision_edge_listable_from_predecessor
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_approved_formulation(api)
    parent = built["formulation"]

    response = api.create_formulation_revision(
        parent["id"],
        {
            "formulation_code": "F-MIN-R2",
            "expected_formulation_version": parent["version"],
        },
        FORMULATOR,
    )
    revision = validate_success(response, 201)

    assert revision["revision"] == 2
    assert revision["supersedes_formulation_id"] == parent["id"]
    assert revision["status"] == "DRAFT"
    assert revision["cost_basis"] == "LIVE"

    copied, copied_meta = validate_paginated(
        api.list_formulation_components(revision["id"], FORMULATOR)
    )
    assert copied_meta["total_count"] == 2
    assert all(row["material_cost_snapshot_cents"] is None for row in copied)

    listed, listed_meta = validate_paginated(
        api.list_formulations(
            FORMULATOR, params={"supersedes_formulation_id": parent["id"]}
        )
    )
    assert listed_meta["total_count"] == 1
    assert listed[0]["id"] == revision["id"]

    reread_parent = get_success_data(api.get_formulation(parent["id"], FORMULATOR))
    assert reread_parent["status"] == "APPROVED"
    assert reread_parent["open_revision_count"] == 1
