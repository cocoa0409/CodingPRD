"""Product registration, pack-fact amendment and supplement-facts lines.

A product is the anchor of the whole compliance record: it opens pristine, it
carries the four risk counters and both claim counters, and its panel is
composed one line at a time while the product is still in ``DRAFT``.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_INGREDIENT_NOT_FOUND,
    ERR_PANEL_POSITION_TAKEN,
    ERR_PRODUCT_INGREDIENT_STATE_INVALID,
    ERR_PRODUCT_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_posture,
    assert_risk_index,
)
from test_helpers.constants import (
    LIFECYCLE_DRAFT,
    LINE_STATUS_ACTIVE,
    LINE_STATUS_REMOVED,
    POSTURE_OPEN,
)
from test_helpers.factories import (
    product_ingredient_payload,
    product_payload,
    start_marketing_payload,
)
from test_helpers.fixtures import (
    make_grandfathered_ingredient,
    make_line,
    make_product,
)

PHANTOM_ID = "00000000-0000-4000-8000-000000000001"


def test_product_creation_seeds_every_counter_at_its_opening_value(
    api, specialist_headers
):
    """A brand-new product is pristine on every derived dimension.

    PRD §3.3: "A new product opens in ``lifecycle_status`` ``DRAFT`` with
    ``label_posture`` ``OPEN``, ``marketing_start_date`` null, all four risk
    counters at zero, ``compliance_risk_index`` at its floor value of 10,
    ``active_claim_count`` and ``withdrawn_claim_count`` at zero, and
    ``requires_label_revision`` false." PRD §4 adds that "A request that creates a
    new resource responds with HTTP 201 and the created resource in ``data``".

    Design: Corner/entities/corner_product_create_returns_envelope_with_seeded_counters
    """
    created = validate_success(
        api.create_product(
            product_payload(
                brand_name="NutraCore",
                product_name="Magnesium Glycinate",
                net_quantity_g=120,
                servings_per_container=60,
            ),
            specialist_headers,
        ),
        201,
    )

    assert_common_fields(created, expected_version=1)
    assert created["brand_name"] == "NutraCore"
    assert created["product_name"] == "Magnesium Glycinate"
    assert created["net_quantity_g"] == 120
    assert created["servings_per_container"] == 60
    assert created["lifecycle_status"] == LIFECYCLE_DRAFT
    assert created["marketing_start_date"] is None
    assert created["serious_ae_count"] == 0
    assert created["nonserious_ae_count"] == 0
    assert created["late_notification_count"] == 0
    assert created["rejected_coa_count"] == 0
    assert created["active_claim_count"] == 0
    assert created["withdrawn_claim_count"] == 0
    assert created["requires_label_revision"] is False
    assert_risk_index(created, 10)
    assert_posture(created, POSTURE_OPEN)


def test_product_fetch_returns_the_stored_row_without_touching_it(
    api, specialist_headers, auditor_headers
):
    """A read never counts as a mutation, so neither stamp nor version moves.

    PRD §2.4: "The ``created_at`` timestamp is an ISO 8601 UTC instant with three
    fractional digits, fixed at creation and never rewritten." The same section
    pins that "The ``version`` is an integer that begins at 1 when the resource is
    created and increments by exactly 1 on every mutation of that row".

    Design: Corner/entities/corner_product_get_returns_stored_row_unchanged
    """
    created = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="Magnesium Glycinate",
        net_quantity_g=120,
        servings_per_container=60,
    )

    fetched = validate_success(api.get_product(created["id"], auditor_headers), 200)
    assert fetched["id"] == created["id"]
    assert fetched["version"] == 1
    assert fetched["created_at"] == created["created_at"]
    assert fetched["updated_at"] == created["updated_at"]
    assert fetched["brand_name"] == "NutraCore"
    assert fetched["product_name"] == "Magnesium Glycinate"
    assert fetched["net_quantity_g"] == 120
    assert fetched["servings_per_container"] == 60
    assert fetched["lifecycle_status"] == LIFECYCLE_DRAFT
    assert_posture(fetched, POSTURE_OPEN)


def test_product_amendment_rewrites_only_the_supplied_pack_fact(
    api, specialist_headers
):
    """A one-field PATCH leaves the other three pack facts alone.

    PRD §3.3: "Pack facts remain amendable — ``brand_name``, ``product_name``,
    ``net_quantity_g`` and ``servings_per_container`` may each be revised — but
    only while the product is still in ``DRAFT``". PRD §2.4 pins the bookkeeping:
    the ``version`` "increments by exactly 1 on every mutation of that row".

    Design: Corner/endpoints/corner_product_patch_updates_only_supplied_fields
    """
    created = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="Magnesium Glycinate",
        net_quantity_g=120,
        servings_per_container=60,
    )

    amended = validate_success(
        api.patch_product(
            created["id"], {"brand_name": "NutraCore Labs"}, specialist_headers
        ),
        200,
    )
    assert amended["brand_name"] == "NutraCore Labs"
    assert amended["product_name"] == "Magnesium Glycinate"
    assert amended["net_quantity_g"] == 120
    assert amended["servings_per_container"] == 60
    assert amended["version"] == 2
    assert amended["created_at"] == created["created_at"]
    assert amended["lifecycle_status"] == LIFECYCLE_DRAFT
    assert_risk_index(amended, 10)
    assert_posture(amended, POSTURE_OPEN)


def test_line_daily_value_fields_are_derived_from_the_ingredient_monograph(
    api, specialist_headers
):
    """The client never supplies the printed percentage; the server derives it.

    PRD §3.3: "``dv_established`` is true exactly when the referenced ingredient's
    ``rdi_mg`` is not null, and false when it is null." The same paragraph pins the
    null branch: "When no Daily Value has been established — ``rdi_mg`` null —
    ``dv_established`` is false and ``percent_dv_declared`` is null, and the
    printed panel will instead carry a footnote symbol."

    Design: Corner/entities/corner_product_ingredient_percent_dv_is_computed_not_supplied
    """
    zinc = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Zinc Picolinate",
        ingredient_class="MINERAL",
        daily_intake_mg=15,
        rdi_mg=11,
    )
    maca = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Maca Root Powder",
        ingredient_class="BOTANICAL",
        daily_intake_mg=1500,
        rdi_mg=None,
    )
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="Zinc and Maca",
        net_quantity_g=60,
        servings_per_container=30,
    )

    zinc_line = make_line(
        api,
        product["id"],
        zinc["id"],
        specialist_headers,
        amount_per_serving_mg=11,
        panel_position=1,
    )
    assert zinc_line["dv_established"] is True
    assert zinc_line["percent_dv_declared"] == 100
    assert zinc_line["line_status"] == LINE_STATUS_ACTIVE
    assert_common_fields(zinc_line, expected_version=1)

    maca_line = make_line(
        api,
        product["id"],
        maca["id"],
        specialist_headers,
        amount_per_serving_mg=750,
        panel_position=2,
    )
    assert maca_line["dv_established"] is False
    assert maca_line["percent_dv_declared"] is None
    assert maca_line["line_status"] == LINE_STATUS_ACTIVE
    assert_common_fields(maca_line, expected_version=1)


def test_line_creation_resolves_the_ingredient_foreign_key(api, specialist_headers):
    """A phantom ``ingredient_id`` is a 404 on the ingredient collection.

    PRD §2.7 rank 5: "Then ``ingredient_id`` and, after it,
    ``predecessor_ingredient_id`` must each name an existing ingredient when
    supplied (``ERR_INGREDIENT_NOT_FOUND``) on ingredient registration, ingredient
    amendment, line creation, claim creation, NDI notification drafting and lot
    intake."

    Design: Corner/endpoints/corner_product_ingredient_link_requires_both_referenced_rows
    """
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="Phantom Blend",
        net_quantity_g=60,
        servings_per_container=30,
    )

    refused = api.create_product_ingredient(
        product_ingredient_payload(
            product["id"], PHANTOM_ID, amount_per_serving_mg=500, panel_position=1
        ),
        specialist_headers,
    )
    validate_error(refused, ERR_INGREDIENT_NOT_FOUND, 404)

    _rows, meta = validate_paginated(
        api.list_product_ingredients(specialist_headers, {"product_id": product["id"]})
    )
    assert meta["total_count"] == 0


def test_two_active_lines_may_not_share_a_printed_position(api, specialist_headers):
    """The print order is unique across the product's ``ACTIVE`` lines.

    PRD §3.3: "``panel_position`` must be unique among the product's lines whose
    ``line_status`` is ``ACTIVE``, both when a line is created and when an existing
    line's position is changed; a collision is refused with
    ``ERR_PANEL_POSITION_TAKEN`` (HTTP 409)."

    Design: Corner/validations/corner_duplicate_panel_position_on_same_product_rejected
    """
    ascorbic = make_grandfathered_ingredient(
        api,
        specialist_headers,
        ingredient_name="Ascorbic Acid",
        ingredient_class="VITAMIN",
        daily_intake_mg=500,
        rdi_mg=90,
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
        product_name="C plus Zinc",
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

    collision = api.create_product_ingredient(
        product_ingredient_payload(
            product["id"], zinc["id"], amount_per_serving_mg=11, panel_position=1
        ),
        specialist_headers,
    )
    validate_error(collision, ERR_PANEL_POSITION_TAKEN, 409)

    rows, meta = validate_paginated(
        api.list_product_ingredients(specialist_headers, {"product_id": product["id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["ingredient_id"] == ascorbic["id"]


def test_amending_an_already_removed_line_reports_its_state_not_a_404(
    api, specialist_headers
):
    """A soft-deleted line stays addressable but refuses further edits.

    PRD §3.3: "Amending or removing a line that is already ``REMOVED`` is refused
    with ``ERR_PRODUCT_INGREDIENT_STATE_INVALID``." The same paragraph guarantees
    that "The row stays fully queryable so that a superseded panel remains
    auditable years later", so the fetch still returns the retained row.

    Design: Corner/errors/corner_patch_of_a_removed_panel_line_rejected
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
    line = make_line(
        api,
        product["id"],
        ascorbic["id"],
        specialist_headers,
        amount_per_serving_mg=90,
        panel_position=1,
    )

    removed = validate_success(
        api.delete_product_ingredient(line["id"], specialist_headers), 200
    )
    assert removed["line_status"] == LINE_STATUS_REMOVED
    assert removed["percent_dv_declared"] is None
    assert removed["dv_established"] is False

    refused = api.patch_product_ingredient(
        line["id"], {"amount_per_serving_mg": 120}, specialist_headers
    )
    validate_error(refused, ERR_PRODUCT_INGREDIENT_STATE_INVALID, 409)

    retained = validate_success(
        api.get_product_ingredient(line["id"], specialist_headers), 200
    )
    assert retained["line_status"] == LINE_STATUS_REMOVED
    assert retained["amount_per_serving_mg"] == 90


def test_a_draft_product_cannot_start_marketing(api, specialist_headers, officer_headers):
    """Launching demands a committed label, which a draft product does not have.

    PRD §3.6: "The product's ``lifecycle_status`` must be exactly ``LABEL_LOCKED``
    — a ``DRAFT`` product has no committed label and a ``MARKETED`` product has
    already launched, and either is refused with ``ERR_PRODUCT_STATE_INVALID``."

    Design: Corner/state_machines/corner_start_marketing_from_draft_product_rejected
    """
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="Electrolyte Mix",
        net_quantity_g=400,
        servings_per_container=40,
    )
    assert product["lifecycle_status"] == LIFECYCLE_DRAFT

    refused = api.start_marketing(
        product["id"], start_marketing_payload("2026-09-10"), officer_headers
    )
    validate_error(refused, ERR_PRODUCT_STATE_INVALID, 409)

    reread = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert reread["lifecycle_status"] == LIFECYCLE_DRAFT
    assert reread["marketing_start_date"] is None
