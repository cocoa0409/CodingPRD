"""The four-charge pricing engine: subtotal, freight tiers, installation,
startup, and the PROVISIONAL/FINAL variants."""
from test_helpers import (
    TEST_USERS,
    accept_quote_flow,
    assert_quote,
    get_success_data,
    setup_project_with_approved_layout,
    setup_quote_presented,
    validate_success,
)

PM = TEST_USERS["project_manager_headers"]
SR = TEST_USERS["sales_rep_headers"]


def test_freight_tier_1_only_below_ceiling(api):
    """PRD §3.3: "subtotals up to and including $50,000 (5,000,000 cents) are
    charged entirely at 6 percent" and "After rounding, if any non-cancelled
    item on the layout has `item_kind` `CUSTOM_FABRICATION`, a flat $1,500
    (150,000 cents) custom-fabrication surcharge is added; otherwise the
    freight equals the rounded tier amount."

    Design: Corner/calculations/freight_tier_1_only_below_ceiling
    """
    _, project, layout, _ = setup_project_with_approved_layout(
        item_overrides_list=[
            {"model_no": "A", "quantity": 1, "unit_price_cents": 1_000_000,
             "lead_time_days": 1}
        ]
    )
    quote = validate_success(
        api.create_quote(project["id"], layout["id"], SR), 201
    )
    assert_quote(quote)
    assert quote["equipment_subtotal_cents"] == 1_000_000
    assert quote["freight_cents"] == 60_000


def test_freight_tier_straddle_marginal_rate_mode_a(api):
    """PRD §3.3: "the portion of a subtotal above $50,000 and up to and
    including $250,000 (25,000,000 cents) is charged at 4.5 percent on top of
    the full first-tier charge" and "a flat $1,500 (150,000 cents)
    custom-fabrication surcharge is added".

    Design: Difficulty/combinatorial_formula/freight_tier_straddle_marginal_rate_mode_a
    """
    _, project, layout, _ = setup_project_with_approved_layout(
        item_overrides_list=[
            {"model_no": "OVEN", "item_kind": "STOCK", "quantity": 6,
             "unit_price_cents": 1_000_000, "lead_time_days": 14},
            {"model_no": "CUSTOM-HOOD", "item_kind": "CUSTOM_FABRICATION",
             "quantity": 1, "unit_price_cents": 0, "lead_time_days": 90},
        ]
    )
    quote = validate_success(
        api.create_quote(project["id"], layout["id"], SR), 201
    )
    assert quote["equipment_subtotal_cents"] == 6_000_000
    # 5,000,000*0.06 + 1,000,000*0.045 = 345,000; + 150,000 surcharge.
    assert quote["freight_cents"] == 495_000


def test_freight_surcharge_absent_for_stock_only(api):
    """PRD §3.3: "if any non-cancelled item on the layout has `item_kind`
    `CUSTOM_FABRICATION`, a flat $1,500 (150,000 cents) custom-fabrication
    surcharge is added; otherwise the freight equals the rounded tier amount."

    Design: Difficulty/combinatorial_formula/freight_tier_straddle_marginal_rate_mode_a
    """
    _, project, layout, _ = setup_project_with_approved_layout(
        item_overrides_list=[
            {"model_no": "OVEN", "item_kind": "STOCK", "quantity": 6,
             "unit_price_cents": 1_000_000, "lead_time_days": 14}
        ]
    )
    quote = validate_success(
        api.create_quote(project["id"], layout["id"], SR), 201
    )
    assert quote["equipment_subtotal_cents"] == 6_000_000
    # Same straddle, no CUSTOM_FABRICATION item -> no surcharge.
    assert quote["freight_cents"] == 345_000


def test_equipment_subtotal_per_line_rounding_mode_b(api):
    """PRD §3.3: "each line contributes its `quantity` multiplied by its
    `unit_price_cents`, with that per-line product first rounded half-up to
    whole cents and only then summed. Rounding per line before summing —
    rather than summing raw products and rounding once — is pinned".

    Design: Difficulty/combinatorial_formula/equipment_subtotal_per_line_rounding_mode_b
    """
    _, project, layout, _ = setup_project_with_approved_layout(
        item_overrides_list=[
            {"model_no": "SPOON", "quantity": 1, "unit_price_cents": 1,
             "lead_time_days": 1},
            {"model_no": "FORK", "quantity": 1, "unit_price_cents": 1,
             "lead_time_days": 1},
            {"model_no": "KNIFE", "quantity": 1, "unit_price_cents": 1,
             "lead_time_days": 1},
        ]
    )
    quote = validate_success(
        api.create_quote(project["id"], layout["id"], SR), 201
    )
    assert quote["equipment_subtotal_cents"] == 3


def test_equipment_subtotal_per_line_quantity_multiplied(api):
    """PRD §3.3: "each line contributes its `quantity` multiplied by its
    `unit_price_cents`" and "`equipment_subtotal_cents` sums every equipment
    item on the referenced layout whose status is not `CANCELLED`".

    Design: Difficulty/combinatorial_formula/equipment_subtotal_per_line_rounding_mode_b
    """
    _, project, layout, _ = setup_project_with_approved_layout(
        item_overrides_list=[
            {"model_no": "A", "quantity": 3, "unit_price_cents": 150,
             "lead_time_days": 1},
            {"model_no": "B", "quantity": 2, "unit_price_cents": 250,
             "lead_time_days": 1},
        ]
    )
    quote = validate_success(
        api.create_quote(project["id"], layout["id"], SR), 201
    )
    assert quote["equipment_subtotal_cents"] == 3 * 150 + 2 * 250


def test_installation_county_uplift_applied(api):
    """PRD §3.3: "When — and only when — the project's `health_jurisdiction`
    is exactly `COUNTY_HEALTH`, the summed base is multiplied by 1.10 (a 10
    percent county uplift) and the result rounded half-up once to whole cents;
    `CITY_HEALTH` and `STATE_HEALTH` projects pay the un-uplifted base."

    Design: Corner/calculations/installation_county_uplift_applied
    """
    from test_helpers import create_customer, create_project, create_layout
    from test_helpers import add_equipment_item

    customer = create_customer()
    installs = {}
    for jurisdiction, name in (("CITY_HEALTH", "City"), ("COUNTY_HEALTH", "County")):
        project = create_project(
            customer["id"], project_name=name, health_jurisdiction=jurisdiction
        )
        layout = create_layout(project["id"])
        add_equipment_item(
            project["id"], layout["id"], model_no="A", quantity=1,
            unit_price_cents=100_000, lead_time_days=1
        )
        get_success_data(api.submit_layout(project["id"], layout["id"], TEST_USERS["kitchen_designer_headers"]))
        get_success_data(api.approve_layout(project["id"], layout["id"], PM))
        quote = validate_success(
            api.create_quote(project["id"], layout["id"], SR), 201
        )
        installs[jurisdiction] = quote["installation_cents"]

    # base = 250,000 + 1*45,000 + 0 = 295,000; county: round_half_up(295000*1.10)
    assert installs["CITY_HEALTH"] == 295_000
    assert installs["COUNTY_HEALTH"] == 324_500


def test_installation_hood_premium_per_hood_item(api):
    """PRD §3.3: "`installation_cents` starts from a base of $2,500 (250,000
    cents) per quote, plus $450 (45,000 cents) per unit of total equipment
    `quantity` across non-cancelled items, plus a $1,200 (120,000 cents)
    premium for each non-cancelled item whose `requires_hood` is true."

    Design: Corner/calculations/installation_county_uplift_applied
    """
    _, project, layout, _ = setup_project_with_approved_layout(
        item_overrides_list=[
            {"model_no": "RANGE", "quantity": 2, "unit_price_cents": 100_000,
             "lead_time_days": 1, "requires_hood": True},
            {"model_no": "SINK", "quantity": 1, "unit_price_cents": 50_000,
             "lead_time_days": 1, "requires_hood": False},
        ],
        layout_overrides={"hood_required": True},
    )
    quote = validate_success(
        api.create_quote(project["id"], layout["id"], SR), 201
    )
    # base = 250,000 + (2+1)*45,000 + 1*120,000 = 505,000; CITY_HEALTH: no uplift.
    assert quote["installation_cents"] == 505_000


def test_startup_calc_per_item_scaling(api):
    """PRD §3.3: "`startup_cents` is a flat $1,800 (180,000 cents) per project
    plus $300 (30,000 cents) per non-cancelled equipment item on the layout".

    Design: Corner/calculations/startup_calc_per_item_scaling
    """
    _, project, layout, _ = setup_project_with_approved_layout(
        item_overrides_list=[
            {"model_no": "A", "quantity": 1, "unit_price_cents": 100_000,
             "lead_time_days": 1},
            {"model_no": "B", "quantity": 1, "unit_price_cents": 100_000,
             "lead_time_days": 1},
            {"model_no": "C", "quantity": 1, "unit_price_cents": 100_000,
             "lead_time_days": 1},
        ]
    )
    quote = validate_success(
        api.create_quote(project["id"], layout["id"], SR), 201
    )
    assert quote["startup_cents"] == 180_000 + 3 * 30_000


def test_freight_tier_boundary_at_ceiling_inclusive(api):
    """PRD §3.3: "Tier bounds are inclusive at the bottom and exclusive at the
    top of each band — a subtotal of exactly $50,000 is charged entirely at
    the 6-percent rate."

    Design: Difficulty/boundary_precision_check/freight_tier_boundary_at_ceiling_inclusive
    """
    _, project, layout, _ = setup_project_with_approved_layout(
        item_overrides_list=[
            {"model_no": "OVEN", "quantity": 5, "unit_price_cents": 1_000_000,
             "lead_time_days": 7}
        ]
    )
    quote = validate_success(
        api.create_quote(project["id"], layout["id"], SR), 201
    )
    assert quote["equipment_subtotal_cents"] == 5_000_000
    assert quote["freight_cents"] == 300_000


def test_freight_tier_one_cent_below_ceiling(api):
    """PRD §3.3: "subtotals up to and including $50,000 (5,000,000 cents) are
    charged entirely at 6 percent".

    Design: Difficulty/boundary_precision_check/freight_tier_boundary_at_ceiling_inclusive
    """
    _, project, layout, _ = setup_project_with_approved_layout(
        item_overrides_list=[
            {"model_no": "OVEN", "quantity": 49, "unit_price_cents": 102_040,
             "lead_time_days": 7},
            {"model_no": "FORK", "quantity": 1, "unit_price_cents": 39,
             "lead_time_days": 1},
        ]
    )
    quote = validate_success(
        api.create_quote(project["id"], layout["id"], SR), 201
    )
    # 49*102,040 + 39 = 4,999,960 + 39 = 4,999,999 -> one cent below ceiling.
    subtotal = quote["equipment_subtotal_cents"]
    assert subtotal == 5_000_000 - 1
    from decimal import Decimal, ROUND_HALF_UP
    expected = int(
        (Decimal(subtotal) * Decimal("0.06")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    assert quote["freight_cents"] == expected


def test_quote_pricing_provisional_values_pinned(api):
    """PRD §2.5: "A quote in the `PROVISIONAL` variant is priced off the
    layout snapshot as it existed when the quote was created — the per-line
    equipment prices, item kinds, and counts are read once and frozen into the
    quote's monetary fields at creation and again at presentation without
    re-reading current item prices."

    Design: Difficulty/dual_variant_calc/quote_pricing_provisional_vs_final_on_price_change
    """
    _, project, layout, items, quote = setup_quote_presented(
        item_overrides_list=[
            {"model_no": "RANGE-36", "item_kind": "STOCK", "quantity": 2,
             "unit_price_cents": 100_000, "lead_time_days": 7,
             "requires_hood": False}
        ]
    )
    assert quote["variant"] == "PROVISIONAL"
    assert quote["equipment_subtotal_cents"] == 200_000
    assert quote["freight_cents"] == 12_000
    assert quote["installation_cents"] == 340_000
    # PRD 3.3: startup is $300 per non-cancelled equipment ITEM (not per
    # unit): 180,000 + 1*30,000 = 210,000 for one item line of quantity 2.
    assert quote["startup_cents"] == 210_000
    assert quote["grand_total_cents"] == 762_000


def test_quote_final_variant_recomputes_same_snapshot(api):
    """PRD §2.5: "A quote that flips to the `FINAL` variant at acceptance is
    fully recomputed against the current `unit_price_cents`, `item_kind`, and
    item composition at the moment the acceptance call runs."

    Design: Difficulty/dual_variant_calc/quote_pricing_provisional_vs_final_on_price_change
    """
    customer, project, layout, items, quote = setup_quote_presented(
        item_overrides_list=[
            {"model_no": "RANGE-36", "item_kind": "STOCK", "quantity": 2,
             "unit_price_cents": 100_000, "lead_time_days": 7,
             "requires_hood": False}
        ]
    )
    accepted = accept_quote_flow(project, quote, customer)
    assert accepted["variant"] == "FINAL"
    # Item state unchanged between create and accept -> recomputation agrees.
    # (Startup is per ITEM per PRD 3.3: 180,000 + 1*30,000 = 210,000.)
    assert accepted["grand_total_cents"] == 762_000
    assert accepted["equipment_subtotal_cents"] == 200_000
    assert accepted["freight_cents"] == 12_000
    assert accepted["installation_cents"] == 340_000
    assert accepted["startup_cents"] == 210_000


def test_quote_get_returns_computed_money_fields(api):
    """PRD §3.3: "the referenced layout must be `APPROVED` or creation fails
    with `ERR_LAYOUT_NOT_APPROVED`. The quote is born in `DRAFT` with `variant`
    `PROVISIONAL`, the next `revision_no` within the project, and all five
    monetary fields computed from the pricing engine below." And "The
    `grand_total_cents` is then the sum of `equipment_subtotal_cents`,
    `freight_cents`, `installation_cents`, and `startup_cents`."

    Design: Corner/endpoints/quote_get_returns_computed_money_fields
    """
    _, project, layout, _ = setup_project_with_approved_layout(
        item_overrides_list=[
            {"model_no": "A", "quantity": 1, "unit_price_cents": 100_000,
             "lead_time_days": 1}
        ]
    )
    created = get_success_data(api.create_quote(project["id"], layout["id"], SR))
    quote = validate_success(api.get_quote(project["id"], created["id"], SR), 200)
    assert_quote(quote)
    # subtotal 100,000; freight 6,000; install 295,000; startup 210,000.
    assert quote["grand_total_cents"] == 611_000
    assert quote["grand_total_cents"] == (
        quote["equipment_subtotal_cents"]
        + quote["freight_cents"]
        + quote["installation_cents"]
        + quote["startup_cents"]
    )
    assert quote["variant"] == "PROVISIONAL"


def test_equipment_subtotal_excludes_cancelled_items(api):
    """PRD §3.3: "`equipment_subtotal_cents` sums every equipment item on the
    referenced layout whose status is not `CANCELLED`". PRD §3.9: "Every
    non-terminal quote becomes `SUPERSEDED`; ... every non-terminal equipment
    item becomes `CANCELLED`".

    Design: Corner/calculations/equipment_subtotal_excludes_cancelled_items
    """
    customer, project, layout, items, quote = setup_quote_presented(
        item_overrides_list=[
            {"model_no": "A", "quantity": 1, "unit_price_cents": 100_000,
             "lead_time_days": 1},
            {"model_no": "B", "quantity": 1, "unit_price_cents": 200_000,
             "lead_time_days": 1},
        ]
    )
    assert quote["equipment_subtotal_cents"] == 300_000

    validate_success(api.cancel_project(project["id"], PM), 200)
    quote_after = get_success_data(api.get_quote(project["id"], quote["id"], SR))
    assert quote_after["status"] == "SUPERSEDED"
    for item in items:
        refreshed = get_success_data(
            api.get_equipment_item(project["id"], item["id"], PM)
        )
        assert refreshed["status"] == "CANCELLED"
