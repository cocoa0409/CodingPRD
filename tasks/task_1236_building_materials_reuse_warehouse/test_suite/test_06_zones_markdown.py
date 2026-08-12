"""Store zones, markdown sweeps, slow-stock filter, occupancy invariants (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    create_category,
    create_item,
    create_placed_item,
    create_priced_item,
    create_sale,
    create_zone,
    add_line,
    finalize_sale,
    get_success_data,
    set_clock,
    setup_walk_in_sale_with_line,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

MANAGER = TEST_USERS["store_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / zone_capacity_exact_boundary
# ---------------------------------------------------------------------------

class TestZoneCapacityExactBoundary:
    def _setup(self):
        category = create_category(code="WINDOWS", display_name="Windows",
                                   base_rate_cents=9000)
        zone = create_zone(code="ZCAP", display_name="Cap Zone", capacity=2,
                           restock_threshold=0)
        items = [create_priced_item(category["id"], 9000, description_text=f"w{i}",
                                    estimated_weight_lbs=25)
                 for i in (1, 2, 3)]
        return zone, items

    def test_zone_capacity_exact_boundary_rejection(self, api):
        """PRD §3.8: "Placing an item is a manager's decision with five gates: ...
        and a zone whose `current_count` already equals its `capacity` is full
        (`ERR_ZONE_AT_CAPACITY`)."

        Design: Difficulty/boundary_precision_check/zone_capacity_exact_boundary
        """
        zone, items = self._setup()
        validate_success(api.place_item(items[0]["id"], {"zone_id": zone["id"]}, MANAGER))
        placed = validate_success(api.place_item(items[1]["id"], {"zone_id": zone["id"]}, MANAGER))
        assert placed["sales_status"] == "ON_FLOOR", "second place fills the zone exactly (2 == 2)"

        response = api.place_item(items[2]["id"], {"zone_id": zone["id"]}, MANAGER)
        validate_error(response, ApiErrorId.ERR_ZONE_AT_CAPACITY)

    def test_zone_capacity_count_stable_after_rejection(self, api):
        """PRD §3.8: "A zone's `current_count` is derived, never set: it counts the
        items whose `zone_id` names the zone and whose `sales_status` is `ON_FLOOR`
        or `RESERVED` — a reserved item still occupies its slot."

        Design: Difficulty/boundary_precision_check/zone_capacity_exact_boundary
        """
        zone, items = self._setup()
        validate_success(api.place_item(items[0]["id"], {"zone_id": zone["id"]}, MANAGER))
        validate_success(api.place_item(items[1]["id"], {"zone_id": zone["id"]}, MANAGER))
        validate_error(api.place_item(items[2]["id"], {"zone_id": zone["id"]}, MANAGER),
                       ApiErrorId.ERR_ZONE_AT_CAPACITY)
        zone = get_success_data(api.get_store_zone(zone["id"], MANAGER))
        assert zone["current_count"] == 2, (
            f"rejection leaves no drift: expected 2, got {zone['current_count']}")


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / markdown_day_exact_boundary
# ---------------------------------------------------------------------------

class TestMarkdownDayExactBoundary:
    def _setup(self):
        category = create_category(
            code="MDCAT", display_name="Markdown Cat", base_rate_cents=10000,
            markdown_after_days=10, markdown_step_pct=0.20,
            markdown_interval_days=5, max_markdown_steps=2, floor_price_pct=0.40,
        )
        zone = create_zone(code="ZMD", display_name="MD Zone")
        item = create_placed_item(category["id"], zone["id"], 10000,
                                  description_text="md item", estimated_weight_lbs=5)
        return item

    def test_markdown_day_before_threshold_ineligible(self, api):
        """PRD §3.8: "An item is eligible when it is `PRICED`, `ON_FLOOR`, carries
        no disposition recommendation, and its `days_on_floor` is at least the
        category's `markdown_after_days` plus the item's current `markdown_step`
        times the category's `markdown_interval_days` — the comparison is
        inclusive, so an item standing exactly on the boundary day is marked down
        that day, not the day after."
        PRD §3.8: "`items_evaluated` is the number of items standing `PRICED` and
        `ON_FLOOR` at sweep time, `items_marked_down` the number whose
        `markdown_step` increased"

        Design: Difficulty/boundary_precision_check/markdown_day_exact_boundary
        """
        item = self._setup()  # placed at the 2026-05-01 startup clock
        set_clock("2026-05-10T00:00:00Z")  # 9 whole days on the floor
        run = validate_success(api.create_markdown_run({}, MANAGER), expected_status=201)
        assert run["items_evaluated"] == 1
        assert run["items_marked_down"] == 0, (
            "day 9 is below markdown_after_days 10: not eligible")

    def test_markdown_day_exact_boundary_eligible(self, api):
        """PRD §3.8: "An item is eligible when it is `PRICED`, `ON_FLOOR`, carries
        no disposition recommendation, and its `days_on_floor` is at least the
        category's `markdown_after_days` plus the item's current `markdown_step`
        times the category's `markdown_interval_days` — the comparison is
        inclusive, so an item standing exactly on the boundary day is marked down
        that day, not the day after."
        PRD §3.8: "An item below its category's `max_markdown_steps` steps up by
        one, and its new `current_price_cents` is the `list_price_cents` multiplied
        by (1 − `markdown_step_pct`) raised to the power of the new step count,
        rounded half-up to integer cents — the exponent always applies to the list
        price, never to the previous current price — but never below the markdown
        floor, the `list_price_cents` multiplied by `floor_price_pct` and itself
        rounded half-up; the effective price is the larger of the two."

        Design: Difficulty/boundary_precision_check/markdown_day_exact_boundary
        """
        item = self._setup()  # placed at the 2026-05-01 startup clock
        set_clock("2026-05-10T00:00:00Z")
        validate_success(api.create_markdown_run({}, MANAGER), expected_status=201)
        set_clock("2026-05-11T00:00:00Z")  # exactly 10 whole days on the floor
        run = validate_success(api.create_markdown_run({}, MANAGER), expected_status=201)
        assert run["items_marked_down"] == 1, "day 10 == threshold: eligible (>= inclusive)"

        item = get_success_data(api.get_item(item["id"], MANAGER))
        assert item["days_on_floor"] == 10
        assert item["markdown_step"] == 1
        assert item["current_price_cents"] == 8000, (
            f"round(10000*(1-0.20)^1) = 8000, got {item['current_price_cents']}")


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / zone_occupancy_finalize_void_invariant
# ---------------------------------------------------------------------------

class TestZoneOccupancyFinalizeVoidInvariant:
    def test_finalize_decrements_zone_occupancy(self, api):
        """PRD §3.9: "Each line's item moves from `RESERVED` to `SOLD` with
        `sold_via_sale_id` set and its `zone_id` and `floor_since` cleared; each
        such item's former zone loses one from its `current_count` and recomputes
        `restock_recommended`."
        PRD §3.8: "Whenever that count sits at or below the threshold, the zone's
        `restock_recommended` flag is true; the flag is recomputed on every
        occupancy change."

        Design: Difficulty/compensating_invariant/zone_occupancy_finalize_void_invariant
        """
        ctx = setup_walk_in_sale_with_line(5000, category_overrides={
            "code": "VANITIES", "display_name": "Vanities", "base_rate_cents": 5000})
        zone_before = get_success_data(api.get_store_zone(ctx["zone"]["id"], MANAGER))
        assert zone_before["current_count"] == 1

        finalize_sale(ctx["sale"]["id"], payment_amount_cents=5350)
        zone = get_success_data(api.get_store_zone(ctx["zone"]["id"], MANAGER))
        assert zone["current_count"] == 0, "sold item stops occupying its slot"
        assert zone["restock_recommended"] is True, "0 <= threshold 0"

    def test_void_restores_zone_occupancy(self, api):
        """PRD §3.9: "Voiding is a full compensation: every line item standing
        `SOLD` returns to `ON_FLOOR` in the zone it occupied when reserved, with
        `floor_since` restamped to the void's clock time, each restored zone's
        count rises by one and its restock flag recomputes — so finalize followed
        by void leaves zone occupancy exactly unchanged."

        Design: Difficulty/compensating_invariant/zone_occupancy_finalize_void_invariant
        """
        ctx = setup_walk_in_sale_with_line(5000, category_overrides={
            "code": "VANITIES", "display_name": "Vanities", "base_rate_cents": 5000})
        finalize_sale(ctx["sale"]["id"], payment_amount_cents=5350)
        validate_success(api.void_sale(ctx["sale"]["id"], {"void_reason": "return"}, MANAGER))

        zone = get_success_data(api.get_store_zone(ctx["zone"]["id"], MANAGER))
        assert zone["current_count"] == 1, (
            "finalize + void conserves occupancy exactly at the pre-sale value")
        assert zone["restock_recommended"] is False
        item = get_success_data(api.get_item(ctx["item"]["id"], MANAGER))
        assert item["sales_status"] == "ON_FLOOR"
        assert item["zone_id"] == ctx["zone"]["id"]


# ---------------------------------------------------------------------------
# Corner: errors / capacity_patch_below_occupancy_rejected
# ---------------------------------------------------------------------------

def test_capacity_patch_below_occupancy_rejected(api):
    """PRD §3.8: "Shrinking a zone's `capacity` below its current occupancy is
    refused with `ERR_CAPACITY_BELOW_OCCUPANCY`."

    Design: Corner/errors/capacity_patch_below_occupancy_rejected
    """
    category = create_category(code="OCCAT", display_name="Occ Cat")
    zone = create_zone(code="ZOCC", display_name="Zone Occ", capacity=5,
                       restock_threshold=0)
    create_placed_item(category["id"], zone["id"], 100, description_text="o1",
                       estimated_weight_lbs=1)
    create_placed_item(category["id"], zone["id"], 100, description_text="o2",
                       estimated_weight_lbs=1)
    response = api.update_store_zone(zone["id"], {"capacity": 1}, MANAGER)
    validate_error(response, ApiErrorId.ERR_CAPACITY_BELOW_OCCUPANCY)
    zone = get_success_data(api.get_store_zone(zone["id"], MANAGER))
    assert zone["capacity"] == 5, "rejected patch leaves capacity unchanged"


# ---------------------------------------------------------------------------
# Corner: errors / zone_category_mismatch_rejected
# ---------------------------------------------------------------------------

def test_zone_category_mismatch_rejected(api):
    """PRD §3.8: "Placing an item is a manager's decision with five gates: ... a
    zone with an `allowed_category_id` accepts only items of that category
    (`ERR_ZONE_CATEGORY_MISMATCH`) ..."

    Design: Corner/errors/zone_category_mismatch_rejected
    """
    cat_a = create_category(code="ZCA", display_name="Zone Cat A")
    cat_b = create_category(code="ZCB", display_name="Zone Cat B")
    zone = create_zone(code="ZREST", display_name="Restricted Zone", capacity=5,
                       allowed_category_id=cat_a["id"], restock_threshold=0)
    item = create_priced_item(cat_b["id"], 100, description_text="wrong cat item",
                              estimated_weight_lbs=1)
    response = api.place_item(item["id"], {"zone_id": zone["id"]}, MANAGER)
    validate_error(response, ApiErrorId.ERR_ZONE_CATEGORY_MISMATCH)
    item = get_success_data(api.get_item(item["id"], MANAGER))
    assert item["sales_status"] == "BACKROOM"


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers / slow_only_filter_uses_target_turn_days
# ---------------------------------------------------------------------------

def test_slow_only_filter_uses_target_turn_days(api):
    """PRD §3.7: "The catalog lists with filters on `category_id`, `batch_id`,
    `offer_id`, `zone_id`, `sold_via_sale_id`, `parent_item_id`, `screening_id`,
    `sales_status`, and `pricing_status`, and a `slow_only` flag that keeps only
    items whose `days_on_floor` has reached their category's `target_turn_days`."
    PRD §3.8: "From then on the item's `days_on_floor` reads the whole days
    between `floor_since` and the logical clock."

    Design: Corner/cross_cutting_layers/slow_only_filter_uses_target_turn_days
    """
    category = create_category(code="SLOWCAT", display_name="Slow Cat",
                               target_turn_days=20)
    zone = create_zone(code="ZSLOW", display_name="Zone Slow", capacity=5)
    slow = create_placed_item(category["id"], zone["id"], 100,
                              description_text="slow item", estimated_weight_lbs=2)
    back = create_priced_item(category["id"], 100, description_text="backroom item",
                              estimated_weight_lbs=2)
    set_clock("2026-05-22T00:00:00Z")  # 21 whole days since the 05-01 placement

    rows, meta = validate_paginated(api.list_items(MANAGER, params={"slow_only": True}))
    ids = {row["id"] for row in rows}
    assert slow["id"] in ids, "21 days on floor >= target_turn_days 20: slow"
    assert back["id"] not in ids, "never placed: days_on_floor reads 0, not slow"
