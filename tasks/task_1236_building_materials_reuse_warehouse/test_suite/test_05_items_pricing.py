"""Item intake, pricing engine, split lineage, parallel status axes (PRD §3.7)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_category,
    create_cleared_job,
    create_donor,
    create_item,
    create_placed_item,
    create_priced_item,
    create_received_offer,
    create_sale,
    create_zone,
    add_line,
    finalize_sale,
    get_success_data,
    price_item,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

INTAKE = TEST_USERS["intake_staff_headers"]
MANAGER = TEST_USERS["store_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / list_price_multi_input_stack
# ---------------------------------------------------------------------------

def _setup_hazmat_flooring_item():
    """12 SQFT grade-C flooring in a hazmat-risk category; a CLEARED screening
    is required at intake for hazmat-exposed items (PRD §3.7)."""
    category = create_category(
        code="FLOORING", display_name="Flooring", pricing_model="PER_SQFT",
        base_rate_cents=200, hazmat_risk_flag=True,
    )
    job, tech, screening = create_cleared_job(title="Screen host", quoted_fee_cents=1000)
    item = create_item(
        category["id"], description_text="oak floor 12sqft", condition_grade="C",
        measure_qty=12, measure_unit="SQFT", pre_1978_flag=False,
        estimated_weight_lbs=60, screening_id=screening["id"],
    )
    return category, item


class TestListPriceMultiInputStack:
    def test_list_price_multi_input_stack_value(self, api):
        """PRD §3.7: "The base comes from the category's `pricing_model`: for `FLAT`
        the base is exactly the category's `base_rate_cents`; for `PER_UNIT`,
        `PER_SQFT`, or `PER_LINEAR_FT` the base is `base_rate_cents` multiplied by
        the item's `measure_qty`. The base is then multiplied by a condition factor
        — 1.00 for grade `A`, 0.75 for `B`, 0.50 for `C`, 0.25 for `D` — and by a
        hazardous-handling factor of 1.15 when the category's `hazmat_risk_flag` is
        set or the item's `pre_1978_flag` is true, 1.00 otherwise. The product is
        rounded half-up to integer cents, and the result is clamped from below at a
        minimum list price of one dollar (100 cents)."

        Design: Difficulty/combinatorial_formula/list_price_multi_input_stack
        """
        category, item = _setup_hazmat_flooring_item()
        item = validate_success(api.price_item(item["id"], {}, MANAGER))
        assert item["list_price_cents"] == 1380, (
            f"round_half_up(200*12*0.50*1.15) = 1380, got {item['list_price_cents']}")

    def test_list_price_initializes_pricing_fields(self, api):
        """PRD §3.7: "Either way, pricing also initializes `current_price_cents` to
        the list price, resets `markdown_step` to 0, clears `disposition_recommended`
        to `NONE`, and records the manager's `X-User-ID` in `priced_by_user_id`."
        PRD §3.7: "Pricing is a `StoreManager` act that moves an item from
        `UNPRICED` to `PRICED` (from any other pricing state,
        `ERR_ITEM_NOT_UNPRICED`)."

        Design: Difficulty/combinatorial_formula/list_price_multi_input_stack
        """
        category, item = _setup_hazmat_flooring_item()
        item = validate_success(api.price_item(item["id"], {}, MANAGER))
        assert item["pricing_status"] == "PRICED"
        assert item["current_price_cents"] == 1380
        assert item["markdown_step"] == 0
        assert item["disposition_recommended"] == "NONE"


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / item_parallel_pricing_sales_axes
# ---------------------------------------------------------------------------

class TestItemParallelPricingSalesAxes:
    def test_place_requires_priced_axis_gate(self, api):
        """PRD §3.8: "Placing an item is a manager's decision with five gates: the
        item must stand in `BACKROOM` (`ERR_ITEM_NOT_BACKROOM`), it must be `PRICED`
        (`ERR_ITEM_NOT_PRICED`), the target zone must be `OPEN`
        (`ERR_ZONE_NOT_OPEN`), a zone with an `allowed_category_id` accepts only
        items of that category (`ERR_ZONE_CATEGORY_MISMATCH`), and a zone whose
        `current_count` already equals its `capacity` is full
        (`ERR_ZONE_AT_CAPACITY`)."
        PRD §3.7: "The pricing dimension runs in parallel to the sales-floor
        dimension: an item's `pricing_status` says nothing about where it
        physically stands, and vice versa."

        Design: Difficulty/non_linear_state_machine/item_parallel_pricing_sales_axes
        """
        category = create_category(code="DOORS", display_name="Doors",
                                   base_rate_cents=8000)
        zone = create_zone(code="Z4", display_name="Zone 4")
        item = create_item(category["id"], description_text="oak door",
                           condition_grade="B", estimated_weight_lbs=45)
        assert item["pricing_status"] == "UNPRICED"
        assert item["sales_status"] == "BACKROOM"

        response = api.place_item(item["id"], {"zone_id": zone["id"]}, MANAGER)
        validate_error(response, ApiErrorId.ERR_ITEM_NOT_PRICED)

        item = price_item(item["id"], 5000)
        assert item["pricing_status"] == "PRICED"
        item = validate_success(api.place_item(item["id"], {"zone_id": zone["id"]}, MANAGER))
        assert item["sales_status"] == "ON_FLOOR"

    def test_sale_finalize_void_leaves_pricing_axis_untouched(self, api):
        """PRD §3.9: "Voiding is a full compensation: every line item standing
        `SOLD` returns to `ON_FLOOR` in the zone it occupied when reserved, with
        `floor_since` restamped to the void's clock time, each restored zone's
        count rises by one and its restock flag recomputes — so finalize followed
        by void leaves zone occupancy exactly unchanged."
        PRD §3.7: "The pricing dimension runs in parallel to the sales-floor
        dimension: an item's `pricing_status` says nothing about where it
        physically stands, and vice versa."

        Design: Difficulty/non_linear_state_machine/item_parallel_pricing_sales_axes
        """
        category = create_category(code="DOORS", display_name="Doors",
                                   base_rate_cents=8000)
        zone = create_zone(code="Z4", display_name="Zone 4")
        item = create_placed_item(category["id"], zone["id"], 5000,
                                  description_text="oak door", condition_grade="B",
                                  estimated_weight_lbs=45)

        sale = create_sale("WALK_IN")
        add_line(sale["id"], item["id"])
        sale = finalize_sale(sale["id"], payment_amount_cents=5350)
        assert sale["total_cents"] == 5350, f"5000 + round(5000*0.07) = 5350, got {sale['total_cents']}"

        item = get_success_data(api.get_item(item["id"], MANAGER))
        assert item["sales_status"] == "SOLD"
        assert item["zone_id"] is None

        validate_success(api.void_sale(sale["id"], {"void_reason": "customer return"}, MANAGER))
        item = get_success_data(api.get_item(item["id"], MANAGER))
        assert item["sales_status"] == "ON_FLOOR", "void returns the item to the floor"
        assert item["zone_id"] == zone["id"], "item restored to the zone it occupied when reserved"
        assert item["pricing_status"] == "PRICED", "pricing axis untouched by the sale round trip"
        assert item["current_price_cents"] == 5000


# ---------------------------------------------------------------------------
# Corner: calculations / list_price_flat_grade_d_min_clamp
# ---------------------------------------------------------------------------

def test_list_price_flat_grade_d_min_clamp(api):
    """PRD §3.7: "The base comes from the category's `pricing_model`: for `FLAT`
    the base is exactly the category's `base_rate_cents`; for `PER_UNIT`,
    `PER_SQFT`, or `PER_LINEAR_FT` the base is `base_rate_cents` multiplied by the
    item's `measure_qty`. The base is then multiplied by a condition factor — 1.00
    for grade `A`, 0.75 for `B`, 0.50 for `C`, 0.25 for `D` — and by a
    hazardous-handling factor of 1.15 when the category's `hazmat_risk_flag` is set
    or the item's `pre_1978_flag` is true, 1.00 otherwise. The product is rounded
    half-up to integer cents, and the result is clamped from below at a minimum
    list price of one dollar (100 cents)."

    Design: Corner/calculations/list_price_flat_grade_d_min_clamp
    """
    category = create_category(code="FLATC", display_name="Flat Cat",
                               pricing_model="FLAT", base_rate_cents=300)
    item = create_item(category["id"], description_text="scrap lot", condition_grade="D")
    item = validate_success(api.price_item(item["id"], {}, MANAGER))
    assert item["list_price_cents"] == 100, (
        f"max(100, round(300*0.25*1.00)=75) clamps to 100, got {item['list_price_cents']}")


# ---------------------------------------------------------------------------
# Corner: validations / split_invalid_quantity_rejected
# ---------------------------------------------------------------------------

def test_split_invalid_quantity_rejected(api):
    """PRD §3.7: "Splitting, by `IntakeStaff` or a `StoreManager`, requires the
    item to stand in `BACKROOM` (`ERR_ITEM_NOT_BACKROOM`) and takes a `split_qty`
    that must be greater than zero and strictly less than the item's `measure_qty`;
    a quantity outside those bounds — or any split of a `UNIT`-measured item —
    fails with `ERR_SPLIT_INVALID_QUANTITY`."

    Design: Corner/validations/split_invalid_quantity_rejected
    """
    category = create_category(code="SPLCAT", display_name="Split Cat",
                               pricing_model="PER_SQFT", base_rate_cents=200)
    item = create_item(category["id"], description_text="splittable",
                       measure_qty=12, measure_unit="SQFT", estimated_weight_lbs=50)
    response = api.split_item(item["id"], {"split_qty": 12}, MANAGER)
    validate_error(response, ApiErrorId.ERR_SPLIT_INVALID_QUANTITY)


# ---------------------------------------------------------------------------
# Corner: validations / split_creates_remainder_lineage
# ---------------------------------------------------------------------------

def test_split_creates_remainder_lineage(api):
    """PRD §3.7: "The parent's `measure_qty` shrinks by the split quantity and its
    `pricing_status` reverts to `UNPRICED` so it is priced afresh, while a new
    remainder item is created with `measure_qty` equal to the split quantity and
    `parent_item_id` pointing back at the parent — a self-referential lineage of
    remainders."
    PRD §3.7: "Every item is born with `pricing_status` `UNPRICED` and
    `sales_status` `BACKROOM`, a `markdown_step` of 0, `disposition_recommended` of
    `NONE`, and no `zone_id`, `floor_since`, `parent_item_id`,
    `price_override_cents`, or `sold_via_sale_id`; `days_on_floor` reads 0 while
    the item has never been placed."

    Design: Corner/validations/split_creates_remainder_lineage
    """
    category = create_category(code="SPLC2", display_name="Split Cat 2",
                               pricing_model="PER_SQFT", base_rate_cents=200)
    item = create_priced_item(category["id"], 2400, description_text="split parent",
                              measure_qty=12, measure_unit="SQFT", estimated_weight_lbs=50)
    remainder = validate_success(api.split_item(item["id"], {"split_qty": 5}, MANAGER),
                                 expected_status=201)
    assert remainder["measure_qty"] == 5
    assert remainder["parent_item_id"] == item["id"]
    assert remainder["pricing_status"] == "UNPRICED"
    assert remainder["sales_status"] == "BACKROOM"

    parent = get_success_data(api.get_item(item["id"], MANAGER))
    assert parent["measure_qty"] == 7, f"12 - 5 = 7, got {parent['measure_qty']}"
    assert parent["pricing_status"] == "UNPRICED", (
        "parent reverts to UNPRICED so it is priced afresh")


# ---------------------------------------------------------------------------
# Corner: errors / hazmat_intake_without_screening_rejected
# ---------------------------------------------------------------------------

def test_hazmat_intake_without_screening_rejected(api):
    """PRD §3.7: "Items with hazmat exposure — the category carries
    `hazmat_risk_flag`, or the item's own `pre_1978_flag` is set — must be cleared
    before intake: an exposed item with no `batch_id` requires a `screening_id`
    naming a screening whose `outcome` is `CLEARED`
    (`ERR_HAZMAT_SCREENING_REQUIRED`), while batch-linked items inherit the job's
    screening and need none of their own."

    Design: Corner/errors/hazmat_intake_without_screening_rejected
    """
    category = create_category(code="HZCAT", display_name="Hz Cat")
    response = api.create_item(
        {
            "category_id": category["id"], "description_text": "old painted door",
            "condition_grade": "B", "measure_qty": 1, "measure_unit": "UNIT",
            "pre_1978_flag": True, "estimated_weight_lbs": 30,
        },
        INTAKE,
    )
    validate_error(response, ApiErrorId.ERR_HAZMAT_SCREENING_REQUIRED)


# ---------------------------------------------------------------------------
# Corner: entities / item_create_body_fk_not_found
# ---------------------------------------------------------------------------

def test_item_create_body_fk_not_found(api):
    """PRD §2.8: "Foreign keys carried in request bodies are checked the same way:
    a payload naming a `donor_id`, `category_id`, `item_id`, `zone_id`,
    `contractor_id`, `agreement_id`, `job_id`, `crew_member_id`, `vehicle_id`,
    `subject_id` (interpreted per its `subject_type`), `screening_id`, `offer_id`,
    `batch_id`, or `supersedes_agreement_id` that does not resolve to an existing
    resource is rejected with the corresponding not-found error from the list
    above."

    Design: Corner/entities/item_create_body_fk_not_found
    """
    category = create_category(code="FKCAT", display_name="FK Cat")
    response = api.create_item(
        {
            "category_id": category["id"], "description_text": "orphan",
            "condition_grade": "A", "measure_qty": 1, "measure_unit": "UNIT",
            "pre_1978_flag": False, "estimated_weight_lbs": 1,
            "offer_id": NON_EXISTENT_UUID,
        },
        INTAKE,
    )
    validate_error(response, ApiErrorId.ERR_OFFER_NOT_FOUND)


# ---------------------------------------------------------------------------
# Corner: entities / item_read_returns_not_found
# ---------------------------------------------------------------------------

def test_item_read_returns_not_found(api):
    """PRD §2.8: "When a path carries resource identifiers, the system confirms
    each identifier exists before evaluating anything further along, and the first
    missing identifier produces that resource's own not-found error:
    `ERR_DONOR_NOT_FOUND`, `ERR_CATEGORY_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, ...
    `ERR_ITEM_NOT_FOUND`, ... each an HTTP 404."

    Design: Corner/entities/item_read_returns_not_found
    """
    response = api.get_item(NON_EXISTENT_UUID, MANAGER)
    validate_error(response, ApiErrorId.ERR_ITEM_NOT_FOUND)


# ---------------------------------------------------------------------------
# Corner: endpoints / items_filtered_list_by_offer_fk
# ---------------------------------------------------------------------------

def test_items_filtered_list_by_offer_fk(api):
    """PRD §3.7: "The catalog lists with filters on `category_id`, `batch_id`,
    `offer_id`, `zone_id`, `sold_via_sale_id`, `parent_item_id`, `screening_id`,
    `sales_status`, and `pricing_status`, and a `slow_only` flag that keeps only
    items whose `days_on_floor` has reached their category's `target_turn_days`."
    PRD §3.7: "An item linked to a received donation offer names its `offer_id`;
    the offer must stand in `RECEIVED` (`ERR_INVALID_OFFER_STATE`) and the item's
    `category_id` must equal the offer's category (`ERR_CATEGORY_MISMATCH`)."

    Design: Corner/endpoints/items_filtered_list_by_offer_fk
    """
    category = create_category(code="FLCAT", display_name="Filter Cat")
    donor = create_donor(full_name="D F")
    offer = create_received_offer(donor["id"], category["id"],
                                  receiver_id="staff-fl-r", description_text="filtered",
                                  estimated_quantity=2)
    linked = [
        create_item(category["id"], description_text="f1", offer_id=offer["id"],
                    estimated_weight_lbs=2),
        create_item(category["id"], description_text="f2", offer_id=offer["id"],
                    estimated_weight_lbs=2),
    ]
    create_item(category["id"], description_text="unrelated", estimated_weight_lbs=2)

    rows, meta = validate_paginated(api.list_items(MANAGER, params={"offer_id": offer["id"]}))
    ids = {row["id"] for row in rows}
    assert ids == {linked[0]["id"], linked[1]["id"]}, (
        f"filter returns exactly the offer's items, got {ids}")
    assert all(row["offer_id"] == offer["id"] for row in rows)
