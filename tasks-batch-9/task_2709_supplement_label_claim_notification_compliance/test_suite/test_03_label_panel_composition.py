"""Drafting, amending and validating the supplement facts panel.

Validation is where the printed-label rules actually bite: the serving statement,
the servings reconciliation, the computed warning-code set, the disclaimer and
the printed line budget all run in the fixed order of PRD §3.5.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_INVALID_DATE_RANGE,
    ERR_PANEL_STATE_INVALID,
    ERR_PRODUCT_HAS_NO_ACTIVE_LINES,
    ERR_SERVING_COUNT_MISMATCH,
    ERR_SERVING_SIZE_FORMAT_INVALID,
    ERR_STALE_PRODUCT_VERSION,
    ERR_VALIDATION,
)
from test_helpers.assertions import assert_instant, assert_panel_computed
from test_helpers.constants import (
    PANEL_FORMAT_SIMPLIFIED,
    PANEL_FORMAT_STANDARD,
    PANEL_STATUS_DRAFT,
    PANEL_STATUS_VALIDATED,
    WARNING_PEDIATRIC,
)
from test_helpers.factories import label_panel_payload
from test_helpers.fixtures import (
    make_draft_panel,
    make_grandfathered_ingredient,
    make_line,
    make_product,
    product_version,
)


def test_panel_draft_without_a_serving_statement_is_rejected(api, specialist_headers):
    """``serving_size_text`` is a required input, not an optional one.

    PRD §3.5 lists what a draft must carry: "a ``serving_size_text`` giving the
    printed serving statement; a ``serving_weight_g`` mass for one serving in
    grams, strictly positive". PRD §2.7 rank 4 screens that "Every required input
    field is present" and reports the failure as ``ERR_VALIDATION`` (HTTP 422).

    Design: Corner/entities/corner_panel_create_missing_serving_size_text_rejected
    """
    ascorbic = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Ascorbic Acid",
        ingredient_class="VITAMIN",
        daily_intake_mg=500,
        rdi_mg=90,
    )
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="C-500",
        net_quantity_g=120,
        servings_per_container=60,
    )
    make_line(
        api,
        product["id"],
        ascorbic["id"],
        specialist_headers,
        amount_per_serving_mg=500,
        panel_position=1,
    )
    before = product_version(api, product["id"], specialist_headers)

    payload = label_panel_payload(product["id"], before)
    payload.pop("serving_size_text")
    refused = api.create_label_panel(payload, specialist_headers)
    validate_error(refused, ERR_VALIDATION, 422)

    _rows, meta = validate_paginated(
        api.list_label_panels(specialist_headers, {"product_id": product["id"]})
    )
    assert meta["total_count"] == 0
    assert product_version(api, product["id"], specialist_headers) == before


def test_a_reversed_effective_window_is_rejected(api, specialist_headers):
    """The field-pair sanity check runs before anything is created.

    PRD §2.7 rank 7: "On panel creation and panel amendment, ``effective_from``
    must not be later than ``effective_until``; equal dates describe a legal
    one-day window. A reversed pair is ``ERR_INVALID_DATE_RANGE`` (HTTP 422)."

    Design: Corner/validations/corner_panel_effective_until_before_effective_from_rejected
    """
    ascorbic = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Ascorbic Acid",
        ingredient_class="VITAMIN",
        daily_intake_mg=500,
        rdi_mg=90,
    )
    product = make_product(
        api,
        specialist_headers,
        brand_name="VitaTrust",
        product_name="Daily C",
        net_quantity_g=60,
        servings_per_container=30,
    )
    make_line(
        api,
        product["id"],
        ascorbic["id"],
        specialist_headers,
        amount_per_serving_mg=45,
        panel_position=1,
    )
    before = product_version(api, product["id"], specialist_headers)

    refused = api.create_label_panel(
        label_panel_payload(
            product["id"],
            before,
            servings_per_container_declared=30,
            effective_from="2027-01-01",
            effective_until="2026-12-31",
        ),
        specialist_headers,
    )
    validate_error(refused, ERR_INVALID_DATE_RANGE, 422)

    _rows, meta = validate_paginated(
        api.list_label_panels(specialist_headers, {"product_id": product["id"]})
    )
    assert meta["total_count"] == 0
    assert product_version(api, product["id"], specialist_headers) == before


def test_validation_requires_at_least_one_active_line(api, specialist_headers):
    """A product with no printed line has no panel to validate.

    PRD §3.5: "The product must also have at least one supplement-facts line in
    ``ACTIVE``; a panel for a product with no active lines is refused with
    ``ERR_PRODUCT_HAS_NO_ACTIVE_LINES`` (HTTP 409)."

    Design: Corner/validations/corner_panel_validate_without_active_lines_rejected
    """
    product = make_product(
        api,
        specialist_headers,
        brand_name="VitaTrust",
        product_name="Empty Formula",
        net_quantity_g=60,
        servings_per_container=30,
    )
    panel = make_draft_panel(
        api,
        product["id"],
        specialist_headers,
        servings_per_container_declared=30,
    )
    assert panel["panel_status"] == PANEL_STATUS_DRAFT

    refused = api.validate_label_panel(panel["id"], specialist_headers)
    validate_error(refused, ERR_PRODUCT_HAS_NO_ACTIVE_LINES, 409)

    reread = validate_success(api.get_label_panel(panel["id"], specialist_headers), 200)
    assert reread["panel_status"] == PANEL_STATUS_DRAFT
    assert reread["panel_lines_required"] is None
    assert reread["panel_total_dv_coverage_pct"] is None
    assert reread["validated_at"] is None


def test_serving_size_format_is_screened_before_the_serving_count(
    api, specialist_headers
):
    """Two failures are staged, and the earlier screen reports first.

    PRD §2.7 rank 12 pins the order: "Mandatory label content and panel capacity,
    evaluated in this order: serving-size format, then servings-per-container
    reconciliation, then mandatory warning coverage, then disclaimer presence,
    then the printed line budget." PRD §3.5 supplies both codes — a malformed
    statement "is refused with ``ERR_SERVING_SIZE_FORMAT_INVALID`` (HTTP 422)" and
    "Failing either comparison is refused with ``ERR_SERVING_COUNT_MISMATCH``
    (HTTP 422)".

    Design: Corner/validations/corner_serving_size_format_error_precedes_serving_count_error
    """
    ascorbic = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Ascorbic Acid",
        ingredient_class="VITAMIN",
        daily_intake_mg=500,
        rdi_mg=90,
    )
    product = make_product(
        api,
        specialist_headers,
        brand_name="VitaTrust",
        product_name="Daily C",
        net_quantity_g=60,
        servings_per_container=30,
    )
    make_line(
        api,
        product["id"],
        ascorbic["id"],
        specialist_headers,
        amount_per_serving_mg=45,
        panel_position=1,
    )
    panel = make_draft_panel(
        api,
        product["id"],
        specialist_headers,
        serving_size_text="two capsules",
        serving_weight_g=2,
        servings_per_container_declared=25,
    )

    first = api.validate_label_panel(panel["id"], specialist_headers)
    validate_error(first, ERR_SERVING_SIZE_FORMAT_INVALID, 422)

    validate_success(
        api.patch_label_panel(
            panel["id"], {"serving_size_text": "2 capsules"}, specialist_headers
        ),
        200,
    )

    second = api.validate_label_panel(panel["id"], specialist_headers)
    validate_error(second, ERR_SERVING_COUNT_MISMATCH, 422)

    reread = validate_success(api.get_label_panel(panel["id"], specialist_headers), 200)
    assert reread["panel_status"] == PANEL_STATUS_DRAFT
    assert reread["validated_at"] is None


def test_two_lines_carrying_the_same_allergen_collapse_to_one_sorted_code(
    api, specialist_headers
):
    """The warning set has set semantics and a byte-stable sort order.

    PRD §3.5: "The collection has set semantics: two lines carrying the same
    allergen collapse to one code. ``required_warning_codes`` is then that set
    sorted in ascending lexicographic order, which makes the stored array
    byte-stable." The same paragraph permits the extra declared storage code:
    "extra declared codes are permitted and are not an error", and PRD §3.5 adds
    that "Extra codes declared beyond the required set consume no budget."

    Design: Corner/calculations/corner_required_warning_codes_collapse_duplicates_and_sort_ascending
    """
    soy_protein = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Soy Protein Isolate",
        ingredient_class="BOTANICAL",
        daily_intake_mg=500,
        rdi_mg=None,
        allergen_code="SOYBEAN",
    )
    soy_extract = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Fermented Soy Extract",
        ingredient_class="BOTANICAL",
        daily_intake_mg=120,
        rdi_mg=120,
        allergen_code="SOYBEAN",
        contraindication_code="ANTICOAGULANT",
    )
    product = make_product(
        api,
        specialist_headers,
        brand_name="VitaTrust",
        product_name="Soy Duo",
        net_quantity_g=60,
        servings_per_container=30,
    )
    make_line(
        api,
        product["id"],
        soy_protein["id"],
        specialist_headers,
        amount_per_serving_mg=500,
        panel_position=1,
    )
    make_line(
        api,
        product["id"],
        soy_extract["id"],
        specialist_headers,
        amount_per_serving_mg=60,
        panel_position=2,
    )
    panel = make_draft_panel(
        api,
        product["id"],
        specialist_headers,
        panel_format=PANEL_FORMAT_STANDARD,
        serving_size_text="1 scoop",
        serving_weight_g=2,
        servings_per_container_declared=30,
        effective_from="2026-09-01",
        effective_until="2027-08-31",
        declared_warning_codes=[
            "ALLERGEN_SOYBEAN",
            "CONTRAINDICATION_ANTICOAGULANT",
            WARNING_PEDIATRIC,
            "STORAGE_KEEP_COOL_AND_DRY",
        ],
    )

    validated = validate_success(
        api.validate_label_panel(panel["id"], specialist_headers), 200
    )
    assert validated["panel_status"] == PANEL_STATUS_VALIDATED
    assert_panel_computed(
        validated,
        required_warning_codes=[
            "ALLERGEN_SOYBEAN",
            "CONTRAINDICATION_ANTICOAGULANT",
            WARNING_PEDIATRIC,
        ],
        panel_lines_required=10,
        panel_lines_allowed=20,
        panel_total_dv_coverage_pct=50,
    )


def test_a_removed_line_leaves_the_warning_and_coverage_input_sets(
    api, specialist_headers
):
    """Soft-deleting a line takes its allergen and its Daily Value with it.

    PRD §3.3: "a ``REMOVED`` line leaves every panel computation at once: it
    contributes no printed line, no warning code, no Daily Value coverage, and no
    supplier to the product's derived supplier set." PRD §3.5 repeats it from the
    panel side: "``REMOVED`` lines contribute nothing."

    Design: Corner/calculations/corner_removed_line_drops_out_of_warning_and_coverage_input_sets
    """
    soy_protein = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Soy Protein Isolate",
        ingredient_class="BOTANICAL",
        daily_intake_mg=500,
        rdi_mg=None,
        allergen_code="SOYBEAN",
    )
    zinc = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Zinc Picolinate",
        ingredient_class="MINERAL",
        daily_intake_mg=15,
        rdi_mg=11,
    )
    product = make_product(
        api,
        specialist_headers,
        brand_name="VitaTrust",
        product_name="Zinc Focus",
        net_quantity_g=60,
        servings_per_container=30,
    )
    soy_line = make_line(
        api,
        product["id"],
        soy_protein["id"],
        specialist_headers,
        amount_per_serving_mg=500,
        panel_position=1,
    )
    validate_success(
        api.delete_product_ingredient(soy_line["id"], specialist_headers), 200
    )
    make_line(
        api,
        product["id"],
        zinc["id"],
        specialist_headers,
        amount_per_serving_mg=11,
        panel_position=2,
    )
    panel = make_draft_panel(
        api,
        product["id"],
        specialist_headers,
        panel_format=PANEL_FORMAT_STANDARD,
        serving_size_text="1 capsule",
        serving_weight_g=2,
        servings_per_container_declared=30,
        declared_warning_codes=[WARNING_PEDIATRIC],
    )

    validated = validate_success(
        api.validate_label_panel(panel["id"], specialist_headers), 200
    )
    assert validated["panel_status"] == PANEL_STATUS_VALIDATED
    assert_panel_computed(
        validated,
        required_warning_codes=[WARNING_PEDIATRIC],
        panel_lines_required=6,
        panel_lines_allowed=20,
        panel_total_dv_coverage_pct=100,
    )


def test_simplified_line_budget_is_capped_before_the_floor_is_applied(
    api, specialist_headers
):
    """A 600 g pack would earn 38 lines but the cap clamps it to 24.

    PRD §3.5: "A ``SIMPLIFIED`` panel does the same with different constants:
    ``net_quantity_g`` divided by 20 with the fraction discarded, plus 8, capped at
    24, then raised to 12 if below." The preceding sentence pins the order for the
    standard format as "the floor division first, then the upper cap, then the
    lower floor, in exactly that order".

    Design: Corner/calculations/corner_simplified_panel_budget_clamped_at_twenty_four_lines
    """
    zinc = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Zinc Picolinate",
        ingredient_class="MINERAL",
        daily_intake_mg=15,
        rdi_mg=11,
    )
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="Zinc Drink Mix",
        net_quantity_g=600,
        servings_per_container=30,
    )
    make_line(
        api,
        product["id"],
        zinc["id"],
        specialist_headers,
        amount_per_serving_mg=11,
        panel_position=1,
    )
    panel = make_draft_panel(
        api,
        product["id"],
        specialist_headers,
        panel_format=PANEL_FORMAT_SIMPLIFIED,
        serving_size_text="20 g",
        serving_weight_g=20,
        servings_per_container_declared=30,
        declared_warning_codes=[WARNING_PEDIATRIC],
    )

    validated = validate_success(
        api.validate_label_panel(panel["id"], specialist_headers), 200
    )
    assert validated["panel_status"] == PANEL_STATUS_VALIDATED
    assert_panel_computed(
        validated,
        required_warning_codes=[WARNING_PEDIATRIC],
        panel_lines_required=6,
        panel_lines_allowed=24,
        panel_total_dv_coverage_pct=100,
    )
    assert_instant(validated["validated_at"], "2026-08-01T00:00:00Z")


def test_a_validated_panel_can_be_neither_revalidated_nor_amended(
    api, specialist_headers
):
    """``VALIDATED`` closes both the validation door and the amendment door.

    PRD §2.7 rank 9: "A panel must be in ``DRAFT`` to be validated or amended and
    in ``VALIDATED`` to be locked, otherwise ``ERR_PANEL_STATE_INVALID``." PRD §3.5
    frames the amendment window the same way: "Before validation, a draft panel's
    printed content is freely amendable".

    Design: Corner/errors/corner_second_validate_of_a_validated_panel_rejected
    """
    ascorbic = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Ascorbic Acid",
        ingredient_class="VITAMIN",
        daily_intake_mg=500,
        rdi_mg=90,
    )
    product = make_product(
        api,
        specialist_headers,
        brand_name="VitaTrust",
        product_name="Daily C",
        net_quantity_g=60,
        servings_per_container=30,
    )
    make_line(
        api,
        product["id"],
        ascorbic["id"],
        specialist_headers,
        amount_per_serving_mg=90,
        panel_position=1,
    )
    panel = make_draft_panel(
        api,
        product["id"],
        specialist_headers,
        panel_format=PANEL_FORMAT_STANDARD,
        serving_size_text="1 capsule",
        serving_weight_g=2.0,
        servings_per_container_declared=30,
        effective_from="2026-09-01",
        effective_until="2026-12-31",
        declared_warning_codes=[WARNING_PEDIATRIC],
    )
    validated = validate_success(
        api.validate_label_panel(panel["id"], specialist_headers), 200
    )
    assert validated["panel_status"] == PANEL_STATUS_VALIDATED
    assert validated["panel_lines_required"] == 6
    assert validated["panel_lines_allowed"] == 20

    again = api.validate_label_panel(panel["id"], specialist_headers)
    validate_error(again, ERR_PANEL_STATE_INVALID, 409)

    amend = api.patch_label_panel(
        panel["id"], {"serving_size_text": "2 capsules"}, specialist_headers
    )
    validate_error(amend, ERR_PANEL_STATE_INVALID, 409)

    reread = validate_success(api.get_label_panel(panel["id"], specialist_headers), 200)
    assert reread["panel_status"] == PANEL_STATUS_VALIDATED
    assert reread["serving_size_text"] == "1 capsule"
    assert reread["panel_lines_required"] == 6


def test_panel_creation_refuses_a_stale_product_version(api, specialist_headers):
    """A pack-fact amendment invalidates the version the client had read.

    PRD §2.6: "A request that drafts a supplement facts panel must carry
    ``expected_product_version``, a non-optional field holding the ``version`` the
    client last read from the target ``Product``. If that value does not equal the
    product's current ``version``, the request is rejected with
    ``ERR_STALE_PRODUCT_VERSION`` (HTTP 412) and nothing is created."

    Design: Corner/cross_cutting_complexity_layers/corner_panel_create_with_stale_product_version_rejected
    """
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="Magnesium Glycinate",
        net_quantity_g=120,
        servings_per_container=60,
    )
    stale_version = product["version"]
    assert stale_version == 1

    amended = validate_success(
        api.patch_product(
            product["id"], {"brand_name": "NutraCore Labs"}, specialist_headers
        ),
        200,
    )
    assert amended["version"] == 2

    refused = api.create_label_panel(
        label_panel_payload(
            product["id"],
            stale_version,
            panel_format=PANEL_FORMAT_STANDARD,
            serving_size_text="2 capsules",
            serving_weight_g=2.0,
            servings_per_container_declared=60,
            effective_from="2026-09-01",
            effective_until="2026-12-31",
        ),
        specialist_headers,
    )
    validate_error(refused, ERR_STALE_PRODUCT_VERSION, 412)

    _rows, meta = validate_paginated(
        api.list_label_panels(specialist_headers, {"product_id": product["id"]})
    )
    assert meta["total_count"] == 0
    fresh_version = product_version(api, product["id"], specialist_headers)
    assert fresh_version == 2

    created = validate_success(
        api.create_label_panel(
            label_panel_payload(
                product["id"],
                fresh_version,
                panel_format=PANEL_FORMAT_STANDARD,
                serving_size_text="2 capsules",
                serving_weight_g=2.0,
                servings_per_container_declared=60,
                effective_from="2026-09-01",
                effective_until="2026-12-31",
            ),
            specialist_headers,
        ),
        201,
    )
    assert created["panel_status"] == PANEL_STATUS_DRAFT
    assert created["panel_lines_required"] is None
    assert created["panel_lines_allowed"] is None
