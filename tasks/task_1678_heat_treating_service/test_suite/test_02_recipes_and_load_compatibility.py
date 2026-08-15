"""Recipe authoring rules and furnace/recipe compatibility gates at load
creation and assignment (PRD §3.2, §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_approved_recipe,
    create_customer,
    create_furnace,
    create_load,
    create_recipe_payload,
    create_work_order,
    get_load,
    validate_error,
    validate_success,
)

CSR = TEST_USERS["customer_service_rep"]
SCHED = TEST_USERS["shop_scheduler"]
QE = TEST_USERS["quality_engineer"]


# ---------------------------------------------------------------------------
# Corner: entities / invalid_enum_value_rejected
# ---------------------------------------------------------------------------

def test_invalid_quench_media_rejected(api):
    """PRD §3.2: "`quench_media` is one of `OIL`, `WATER`, `POLYMER`, `AIR`,
    or `GAS`."
    PRD §2.8: "The order is: (1) user-context headers present and non-empty
    (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); (2) role permitted for the
    endpoint (`ERR_INSUFFICIENT_PERMISSIONS`); (3) customer-ownership scoping
    (`ERR_OWNERSHIP_MISMATCH`); (4) resource existence — path identifiers
    validated left to right, then request-body foreign keys (the
    `ERR_*_NOT_FOUND` family); (5) state-machine preconditions and
    optimistic-concurrency checks (the state errors such as
    `ERR_LOAD_NOT_BUILDING`, plus `ERR_STALE_VERSION`); (6) business safety
    gates — furnace qualification, furnace-class rank, quench-media
    compatibility, segregation of duties; (7) recipe referential consistency —
    approval state, recipe match between order and load, alloy/spec
    uniqueness; (8) temporal rules — rush guarantee window, pyrometry validity
    containment, schedule overlap and purge gap; (9) constraint checks — load
    weight capacity, non-empty load, re-treat ceiling, required fields and
    enum validity; (10) fiscal standing (`ERR_CUSTOMER_CREDIT_HOLD`)."

    Design: Corner/entities/invalid_enum_value_rejected
    """
    res = api.create_furnace_recipe(
        create_recipe_payload(quench_media="BRINE"), QE
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Corner: validations / duplicate_recipe_rejected
# ---------------------------------------------------------------------------

def test_duplicate_recipe_rejected(api):
    """PRD §3.2: "`alloy_code` and `spec_code` identify the
    alloy/specification pairing (for example, 4140 under AMS2759); the pair
    must be unique across all recipes, and a duplicate is rejected with
    `ERR_DUPLICATE_RECIPE` (HTTP 409)."

    Design: Corner/validations/duplicate_recipe_rejected
    """
    first = validate_success(
        api.create_furnace_recipe(create_recipe_payload(), QE), 201
    )
    assert first["status"] == "DRAFT"
    res = api.create_furnace_recipe(
        create_recipe_payload(
            soak_temp_f=1700, soak_tolerance_f=15, min_soak_minutes=90,
            quench_media="WATER", required_furnace_class="CLASS_5",
            max_retreats=0, fixture_distortion_allowance_in=0.01,
            hardness_min_hrc=30, hardness_max_hrc=40,
        ),
        QE,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_RECIPE.value)


# ---------------------------------------------------------------------------
# Corner: validations / draft_recipe_cannot_back_load
# ---------------------------------------------------------------------------

def test_draft_recipe_cannot_back_load(api):
    """PRD §3.2: "A new recipe starts in `DRAFT`."
    PRD §3.5: "Creation already enforces three compatibility gates: the recipe
    must be `APPROVED` (`ERR_RECIPE_NOT_APPROVED`, HTTP 409); the furnace's
    class rank must be less than or equal to the rank of the recipe's
    `required_furnace_class` (`ERR_RECIPE_CLASS_MISMATCH`, HTTP 422); and the
    furnace's `quench_media_supported` must include the recipe's
    `quench_media` (`ERR_QUENCH_MEDIA_INCOMPATIBLE`, HTTP 422)."

    Design: Corner/validations/draft_recipe_cannot_back_load
    """
    recipe = validate_success(
        api.create_furnace_recipe(create_recipe_payload(), QE), 201
    )
    assert recipe["status"] == "DRAFT"
    furnace = create_furnace()
    res = api.create_load_batch(
        {
            "furnace_id": furnace["id"],
            "recipe_id": recipe["id"],
            "scheduled_start_at": "2026-08-02T08:00:00Z",
            "scheduled_end_at": "2026-08-02T12:00:00Z",
        },
        SCHED,
    )
    validate_error(res, ApiErrorId.ERR_RECIPE_NOT_APPROVED.value)


# ---------------------------------------------------------------------------
# Corner: validations / recipe_class_and_quench_mismatch_at_load_create
# ---------------------------------------------------------------------------

def test_recipe_class_and_quench_mismatch_at_load_create(api):
    """PRD §3.2: "Furnace classes are ranked `CLASS_1` as 1, `CLASS_2` as 2,
    `CLASS_3` as 3, and `CLASS_5` as 5; a furnace may serve a recipe only when
    the furnace's class rank is less than or equal to the rank of the recipe's
    `required_furnace_class` — a `CLASS_1` furnace can run a `CLASS_3` recipe,
    but a `CLASS_3` furnace cannot run a `CLASS_1` recipe."
    PRD §3.5: "Creation already enforces three compatibility gates: the recipe
    must be `APPROVED` (`ERR_RECIPE_NOT_APPROVED`, HTTP 409); the furnace's
    class rank must be less than or equal to the rank of the recipe's
    `required_furnace_class` (`ERR_RECIPE_CLASS_MISMATCH`, HTTP 422); and the
    furnace's `quench_media_supported` must include the recipe's
    `quench_media` (`ERR_QUENCH_MEDIA_INCOMPATIBLE`, HTTP 422)."

    Design: Corner/validations/recipe_class_and_quench_mismatch_at_load_create
    """
    recipe = create_approved_recipe()  # CLASS_3 OIL recipe
    furnace_c5 = create_furnace(furnace_code="F-C5", furnace_class="CLASS_5")
    furnace_water = create_furnace(
        furnace_code="F-W", furnace_class="CLASS_3",
        quench_media_supported=["WATER"],
    )
    window = {
        "scheduled_start_at": "2026-08-02T08:00:00Z",
        "scheduled_end_at": "2026-08-02T12:00:00Z",
    }
    class_res = api.create_load_batch(
        {"furnace_id": furnace_c5["id"], "recipe_id": recipe["id"], **window},
        SCHED,
    )
    validate_error(class_res, ApiErrorId.ERR_RECIPE_CLASS_MISMATCH.value)
    quench_res = api.create_load_batch(
        {"furnace_id": furnace_water["id"], "recipe_id": recipe["id"], **window},
        SCHED,
    )
    validate_error(quench_res, ApiErrorId.ERR_QUENCH_MEDIA_INCOMPATIBLE.value)


# ---------------------------------------------------------------------------
# Corner: validations / recipe_mismatch_on_assignment
# ---------------------------------------------------------------------------

def test_recipe_mismatch_on_assignment(api):
    """PRD §3.5: "The order's `processing_status` must be `RECEIVED` or
    `AWAITING_RETREAT` (`ERR_WORK_ORDER_NOT_ASSIGNABLE`, HTTP 409), and the
    order's `recipe_id` must equal the load's `recipe_id`
    (`ERR_RECIPE_MISMATCH`, HTTP 422)."

    Design: Corner/validations/recipe_mismatch_on_assignment
    """
    customer = create_customer(name="Mix Co")
    recipe_a = create_approved_recipe()  # 4140 / AMS2759
    recipe_b = create_approved_recipe(
        alloy_code="8620", soak_temp_f=1600, hardness_min_hrc=30,
        hardness_max_hrc=40,
    )
    furnace = create_furnace()
    order = create_work_order(customer["id"], recipe_b["id"])
    load = create_load(furnace["id"], recipe_a["id"])
    version_before = get_load(load["id"])["version"]

    res = api.create_load_assignment(
        load["id"],
        {
            "work_order_id": order["id"],
            "expected_load_batch_version": version_before,
        },
        SCHED,
    )
    validate_error(res, ApiErrorId.ERR_RECIPE_MISMATCH.value)
    assert get_load(load["id"])["version"] == version_before, (
        "a rejected assignment must not advance the load version"
    )
