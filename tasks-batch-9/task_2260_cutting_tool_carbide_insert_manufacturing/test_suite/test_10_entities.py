"""Persisted rows: their declared defaults, reads, listings and rejections.

These cover the shape of a freshly created row, reading it back unchanged,
filtering and paging a collection, the entity-specific not-found codes, the
schema and domain rejections that never reach the database, and the reference
resolution that guards a row with three parents plus a self-reference.
"""

from test_helpers import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_carbide_grade,
    assert_coating_recipe,
    assert_customer,
    assert_no_row_with_code,
)
from test_helpers.fixtures import APP, GEO, MET, PLAN
from test_helpers.test_users import make_metallurgy_engineer_headers
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_GRADE_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_BATCH_ID = "11111111-1111-4111-8111-111111111112"
UNKNOWN_GEOMETRY_ID = "11111111-1111-4111-8111-111111111113"
UNKNOWN_RECIPE_ID = "11111111-1111-4111-8111-111111111114"
UNKNOWN_COATING_RUN_ID = "11111111-1111-4111-8111-111111111115"
UNKNOWN_WHEEL_ID = "11111111-1111-4111-8111-111111111116"
UNKNOWN_GRINDING_RUN_ID = "11111111-1111-4111-8111-111111111117"
UNKNOWN_PRODUCT_ID = "11111111-1111-4111-8111-111111111118"
UNKNOWN_DOSSIER_ID = "11111111-1111-4111-8111-111111111119"
UNKNOWN_TRIAL_ID = "11111111-1111-4111-8111-11111111111a"
UNKNOWN_CUSTOMER_ID = "11111111-1111-4111-8111-11111111111b"
UNKNOWN_ORDER_ID = "11111111-1111-4111-8111-11111111111c"
UNKNOWN_JOB_ID = "11111111-1111-4111-8111-11111111111d"


# ─── Creation, retrieval and listing ────────────────────────────────────────

def test_grade_creation_returns_the_declared_opening_values(api):
    """A new grade opens at DRAFT, revision 1, version 1, with the caller recorded.

    PRD §3.1: "The new record opens with `status` at `DRAFT`, `revision` at 1,
    `qualified_product_count` at 0, and `authored_by_user_id` recording the
    creating `X-User-ID`."

    PRD §2.4: "**`version`** (integer): starts at 1 when the row is created and
    increments by exactly 1 on each mutation of that row."

    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/grade_creation_returns_declared_defaults
    """
    headers = make_metallurgy_engineer_headers("me-1")

    response = api.create_carbide_grade(f.carbide_grade_payload(), headers)

    grade = validate_success(response, 201)
    assert_carbide_grade(grade)
    assert grade["status"] == "DRAFT", (
        f"a development record opens at DRAFT, got {grade['status']}"
    )
    assert grade["revision"] == 1, (
        f"the first recipe revision is 1, got {grade['revision']}"
    )
    assert grade["qualified_product_count"] == 0, (
        f"no product has qualified on a new grade, got {grade['qualified_product_count']}"
    )
    assert grade["version"] == 1, (
        f"a freshly written row is at version 1, got {grade['version']}"
    )
    assert grade["authored_by_user_id"] == "me-1", (
        f"the creating X-User-ID is recorded, got {grade['authored_by_user_id']}"
    )
    assert grade["co_binder_pct"] == 6.0, (
        f"the metallurgical target is stored as supplied, got {grade['co_binder_pct']}"
    )
    assert grade["hardness_hv"] == 1600, (
        f"the hardness target is stored as supplied, got {grade['hardness_hv']}"
    )
    assert grade["trs_mpa"] == 2100, (
        f"the strength target is stored as supplied, got {grade['trs_mpa']}"
    )


def test_grade_retrieval_returns_the_stored_row_without_mutating_it(api):
    """A read returns the same row and does not advance its version.

    PRD §2.4: "**`version`** (integer): starts at 1 when the row is created and
    increments by exactly 1 on each mutation of that row."

    PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects."

    Design: Corner/entities/grade_retrieval_returns_stored_row
    """
    created = fx.carbide_grade(api)

    response = api.get_carbide_grade(created["id"], PLAN)

    grade = validate_success(response)
    assert grade["id"] == created["id"], (
        f"the addressed row comes back, got {grade['id']}"
    )
    assert grade["grade_code"] == "WC-P25", (
        f"the business code is stored as supplied, got {grade['grade_code']}"
    )
    assert grade["target_workpiece_group"] == "P", (
        f"the developed group is stored as supplied, got {grade['target_workpiece_group']}"
    )
    assert grade["version"] == 1, (
        f"a read is not a mutation, so the version stands, got {grade['version']}"
    )


def test_grade_listing_filters_before_it_paginates(api):
    """A DRAFT-filtered page counts only the two DRAFT grades, not all three.

    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope, where `total_count` is
    the number of rows matching the request's filters before pagination is
    applied and `has_more` states whether any matching row remains beyond the
    returned page."

    PRD §2.8: "Filters combine conjunctively, and an unsupplied filter constrains
    nothing."

    PRD §2.3: "Unless a specific endpoint says otherwise, list results are
    ordered by `created_at` ascending, so a stable page walk with a fixed `limit`
    and an advancing `offset` visits every row exactly once."

    Design: Corner/entities/grade_listing_filters_by_status_and_paginates
    """
    fx.pilot_grade_with_passed_batch(api)
    fx.carbide_grade(api, **f.stainless_grade_payload())
    fx.carbide_grade(api, **f.endmill_grade_payload())

    drafts, draft_meta = validate_paginated(
        api.list_carbide_grades(PLAN, params={"status": "DRAFT", "limit": 2, "offset": 0})
    )
    tail, tail_meta = validate_paginated(
        api.list_carbide_grades(PLAN, params={"limit": 2, "offset": 2})
    )

    assert draft_meta["total_count"] == 2, (
        "the piloted grade has left DRAFT, so only two rows match the filter, got "
        f"{draft_meta['total_count']}"
    )
    assert draft_meta["has_more"] is False, (
        f"both matching rows fit inside the page, got {draft_meta['has_more']}"
    )
    codes = sorted(row["grade_code"] for row in drafts)
    assert codes == ["WC-K10", "WC-M15"], (
        f"the DRAFT page holds the two unpiloted grades only, got {codes}"
    )
    assert tail_meta["total_count"] == 3, (
        f"unfiltered, all three grades match, got {tail_meta['total_count']}"
    )
    assert len(tail) == 1, (
        f"one row remains beyond an offset of 2, got {len(tail)} rows"
    )
    assert tail_meta["has_more"] is False, (
        f"the walk ends on that row, got {tail_meta['has_more']}"
    )


def test_every_collection_reports_its_own_not_found_code(api):
    """Thirteen single-resource reads on unknown ids return thirteen distinct codes.

    PRD §2.11: "7. **Path identifier existence.** The identifier in the URL
    matches no row → that entity's not-found code from §2.8. Applies to every
    endpoint with a path parameter."

    PRD §2.8: "The not-found codes are entity-specific: `ERR_GRADE_NOT_FOUND`,
    `ERR_BATCH_NOT_FOUND`, `ERR_GEOMETRY_NOT_FOUND`, `ERR_RECIPE_NOT_FOUND`,
    `ERR_COATING_RUN_NOT_FOUND`, `ERR_WHEEL_NOT_FOUND`,
    `ERR_GRINDING_RUN_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_DOSSIER_NOT_FOUND`, `ERR_TRIAL_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND` and `ERR_JOB_NOT_FOUND`."

    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/entities/path_entity_not_found_across_every_collection
    """
    validate_error(
        api.get_carbide_grade(UNKNOWN_GRADE_ID, PLAN),
        ApiErrorId.ERR_GRADE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_powder_blend_batch(UNKNOWN_BATCH_ID, PLAN),
        ApiErrorId.ERR_BATCH_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_insert_geometry(UNKNOWN_GEOMETRY_ID, PLAN),
        ApiErrorId.ERR_GEOMETRY_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_coating_recipe(UNKNOWN_RECIPE_ID, PLAN),
        ApiErrorId.ERR_RECIPE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_coating_run(UNKNOWN_COATING_RUN_ID, PLAN),
        ApiErrorId.ERR_COATING_RUN_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_grinding_wheel(UNKNOWN_WHEEL_ID, PLAN),
        ApiErrorId.ERR_WHEEL_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_grinding_run(UNKNOWN_GRINDING_RUN_ID, PLAN),
        ApiErrorId.ERR_GRINDING_RUN_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_tool_product(UNKNOWN_PRODUCT_ID, PLAN),
        ApiErrorId.ERR_PRODUCT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_qualification_dossier(UNKNOWN_DOSSIER_ID, PLAN),
        ApiErrorId.ERR_DOSSIER_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_machining_trial(UNKNOWN_TRIAL_ID, APP),
        ApiErrorId.ERR_TRIAL_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_customer(UNKNOWN_CUSTOMER_ID, PLAN),
        ApiErrorId.ERR_CUSTOMER_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_tool_order(UNKNOWN_ORDER_ID, PLAN),
        ApiErrorId.ERR_ORDER_NOT_FOUND,
        404,
    )
    error = validate_error(
        api.get_recondition_job(UNKNOWN_JOB_ID, PLAN),
        ApiErrorId.ERR_JOB_NOT_FOUND,
        404,
    )
    assert error["message"], (
        "the error envelope carries a human-readable message alongside the code"
    )


# ─── Schema, defaults, computed fields and system fields ────────────────────

def test_batch_creation_without_the_planned_mass_is_a_schema_rejection(api):
    """Omitting planned_mass_kg fails the body schema and writes no batch.

    PRD §2.11: "3. **Body schema.** A required input field is missing, a field
    has the wrong JSON type, or an unknown field is supplied →
    `ERR_INVALID_REQUEST`. Applies to every endpoint with a request body."

    PRD §3.1: "the request names the `grade_id` whose recipe the batch realises,
    a `batch_code` unique across all batches, and the `planned_mass_kg` of
    blended powder, which must be greater than 0 and is carried to two decimal
    places."

    Design: Corner/entities/batch_create_missing_required_planned_mass_rejected
    """
    grade = fx.carbide_grade(api)

    response = api.create_powder_blend_batch(
        {"grade_id": grade["id"], "batch_code": "BLD-1"}, MET
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
    rows, _meta = validate_paginated(api.list_powder_blend_batches(MET))
    assert rows == [], (
        f"a rejected creation writes nothing, got {len(rows)} batches"
    )


def test_customer_credit_defaults_to_zero_when_it_is_not_supplied(api):
    """An opening balance is optional, and omitting it yields 0 rather than null.

    PRD §3.8: "A customer account is registered by a `ProductionPlanner` or an
    `ApplicationEngineer` with a `customer_code` unique across all customers, a
    `name`, a commercial `tier` of `STANDARD`, `PREFERRED` or `STRATEGIC`, and
    optionally an opening `regrind_credit_cents` balance, which defaults to 0."

    PRD §3.8: "The account opens at `account_status` `ACTIVE` with
    `reserved_credit_cents` at 0."

    Design: Corner/entities/customer_regrind_credit_defaults_to_zero
    """
    response = api.create_customer(
        {"customer_code": "CU-2", "name": "Beta Tool Room", "tier": "STANDARD"}, PLAN
    )

    customer = validate_success(response, 201)
    assert_customer(customer)
    assert customer["regrind_credit_cents"] == 0, (
        f"an unsupplied opening balance defaults to 0, got {customer['regrind_credit_cents']}"
    )
    assert customer["reserved_credit_cents"] == 0, (
        f"a new account reserves nothing, got {customer['reserved_credit_cents']}"
    )
    assert customer["account_status"] == "ACTIVE", (
        f"a new account opens ACTIVE, got {customer['account_status']}"
    )
    assert customer["version"] == 1, (
        f"a freshly written row is at version 1, got {customer['version']}"
    )


def test_recipe_total_thickness_is_summed_from_the_layer_stack(api):
    """A 2.0 um plus 1.5 um stack totals 3.50 um and starts unproven.

    PRD §3.3: "On acceptance, `total_thickness_um` is computed as the sum of the
    entries' `thickness_um` values carried to two decimal places, `revision` is
    1, `adhesion_class` is null and `is_validated` is false."

    PRD §3.3: "A recipe therefore starts life unproven: nothing in the recipe
    definition asserts that the stack will adhere."

    Design: Corner/entities/recipe_total_thickness_is_computed_from_layers
    """
    response = api.create_coating_recipe(
        f.duo_layer_recipe_payload(recipe_code="PVD-DUO-35"), fx.COAT
    )

    recipe = validate_success(response, 201)
    assert_coating_recipe(recipe)
    assert recipe["total_thickness_um"] == 3.50, (
        f"2.0 plus 1.5 is 3.50 micrometres, got {recipe['total_thickness_um']}"
    )
    assert len(recipe["layers"]) == 2, (
        f"the stack holds two entries, got {len(recipe['layers'])}"
    )
    assert recipe["revision"] == 1, (
        f"the first stack revision is 1, got {recipe['revision']}"
    )
    assert recipe["is_validated"] is False, (
        f"nothing has been deposited yet, got {recipe['is_validated']}"
    )
    assert recipe["adhesion_class"] is None, (
        f"the evidence pool is empty, got {recipe['adhesion_class']}"
    )


def test_client_supplied_system_fields_on_a_grade_are_not_honoured(api):
    """A request that also carries id, version, status and revision is not obeyed.

    PRD §2.4: "**`id`** (string): a server-minted UUID. It carries no type
    prefix, no sequence number and no domain-flavoured decoration."

    PRD §2.4: "**`created_at`** (string): an ISO 8601 UTC timestamp with three
    fractional digits, for example `2026-08-01T00:00:00.000Z`, recording when the
    row was first written."

    PRD §3.1: "The new record opens with `status` at `DRAFT`, `revision` at 1,
    `qualified_product_count` at 0, and `authored_by_user_id` recording the
    creating `X-User-ID`."

    PRD §2.11: "3. **Body schema.** A required input field is missing, a field has
    the wrong JSON type, or an unknown field is supplied → `ERR_INVALID_REQUEST`.
    Applies to every endpoint with a request body."

    Design: Corner/entities/grade_client_supplied_system_fields_must_not_be_honored
    """
    smuggled = api.create_carbide_grade(
        f.carbide_grade_payload(
            grade_code="SYS-1",
            id="deadbeef-0000-4000-8000-000000000000",
            version=99,
            status="QUALIFIED",
            revision=7,
        ),
        MET,
    )
    validate_error(smuggled, ApiErrorId.ERR_INVALID_REQUEST, 400)

    grade = validate_success(
        api.create_carbide_grade(f.carbide_grade_payload(grade_code="SYS-2"), MET), 201
    )
    assert grade["id"] != "deadbeef-0000-4000-8000-000000000000", (
        f"the id is server-minted, got the client's own value {grade['id']}"
    )
    assert grade["version"] == 1, (
        f"a freshly written row is at version 1, got {grade['version']}"
    )
    assert grade["status"] == "DRAFT", (
        f"the opening status is the server's, got {grade['status']}"
    )
    assert grade["revision"] == 1, (
        f"the opening revision is the server's, got {grade['revision']}"
    )
    assert grade["created_at"].endswith("Z"), (
        f"created_at is a server ISO 8601 UTC timestamp, got {grade['created_at']}"
    )


# ─── Domains and references ─────────────────────────────────────────────────

def test_geometry_creation_rejects_an_unknown_class_and_a_negative_nose_radius(api):
    """An out-of-enum application class and a negative radius are both domain failures.

    PRD §2.11: "4. **Enum and numeric domain.** An enum field carries a value
    outside its declared set, or a numeric field falls outside its declared
    domain → `ERR_INVALID_REQUEST`."

    PRD §3.2: "an `application_class` that is one of `ROUGHING`, `MEDIUM` or
    `FINISHING`."

    PRD §3.2: "`nose_radius_mm`, at least 0.05 and at most 3.2;"

    Design: Corner/entities/geometry_invalid_application_class_rejected
    """
    bad_enum = api.create_insert_geometry(
        f.insert_geometry_payload(geometry_code="BAD-1", application_class="EXTREME"),
        GEO,
    )
    bad_range = api.create_insert_geometry(
        f.insert_geometry_payload(geometry_code="BAD-2", nose_radius_mm=-0.8), GEO
    )

    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST, 400)
    validate_error(bad_range, ApiErrorId.ERR_INVALID_REQUEST, 400)
    rows, _meta = validate_paginated(api.list_insert_geometries(GEO))
    assert_no_row_with_code(rows, "geometry_code", "BAD-1")
    assert_no_row_with_code(rows, "geometry_code", "BAD-2")


def test_batch_creation_against_an_unknown_grade_reports_the_parent_code(api):
    """A body reference to a grade that does not exist is the parent's own 404.

    PRD §2.11: "8. **Body reference existence.** A foreign key in the body
    matches no row → that entity's not-found code. Applies to blend-batch
    creation, coating-run creation, grinding-run creation, product creation,
    trial creation, order creation, reconditioning-job intake and reconditioning
    refurbish."

    PRD §2.8: "The first identifier that matches no row terminates the request
    with that entity's own not-found code, and no later reference is examined."

    Design: Corner/entities/batch_create_with_unknown_grade_rejected
    """
    response = api.create_powder_blend_batch(
        f.powder_blend_batch_payload(
            "22222222-2222-4222-8222-222222222222", batch_code="BLD-ORPHAN"
        ),
        MET,
    )

    validate_error(response, ApiErrorId.ERR_GRADE_NOT_FOUND, 404)
    rows, _meta = validate_paginated(api.list_powder_blend_batches(MET))
    assert_no_row_with_code(rows, "batch_code", "BLD-ORPHAN")


def test_product_creation_resolves_each_of_its_references_to_its_own_code(api):
    """An unknown geometry reports the geometry's 404; an unknown base product the product's.

    PRD §2.11: "8. **Body reference existence.** A foreign key in the body
    matches no row → that entity's not-found code."

    PRD §2.8: "Identifiers are nevertheless resolved in a fixed order: the path
    identifier first, then each foreign key supplied in the request body in the
    order the body's fields are documented."

    PRD §3.5: "A `SPECIAL` product must supply `base_catalog_product_id`, that
    identifier must not be the product's own, and the product it names must itself
    be `CATALOG` — a special derived from another special is refused."

    Design: Corner/entities/product_graph_references_are_validated_on_create
    """
    grade = fx.carbide_grade(api)
    geometry = fx.insert_geometry(api)
    recipe = fx.coating_recipe(api)

    orphan_geometry = api.create_tool_product(
        f.tool_product_payload(
            grade["id"], "33333333-3333-4333-8333-333333333333", sku="ORPHAN-GEO"
        ),
        GEO,
    )
    orphan_base = api.create_tool_product(
        f.special_product_payload(
            grade["id"],
            geometry["id"],
            recipe["id"],
            "44444444-4444-4444-8444-444444444444",
            sku="ORPHAN-BASE",
        ),
        APP,
    )

    validate_error(orphan_geometry, ApiErrorId.ERR_GEOMETRY_NOT_FOUND, 404)
    validate_error(orphan_base, ApiErrorId.ERR_PRODUCT_NOT_FOUND, 404)
    rows, _meta = validate_paginated(api.list_tool_products(APP))
    assert_no_row_with_code(rows, "sku", "ORPHAN-GEO")
    assert_no_row_with_code(rows, "sku", "ORPHAN-BASE")
