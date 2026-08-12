"""The nine-step price derivation: shipping, the four-position credit stack, the promo."""

from test_helpers import (
    TEST_USERS,
    cycle_lines,
    issue_goodwill_credit,
    make_sku,
    make_subscription,
    read_cycle,
    read_subscription,
    set_clock,
    setup_household,
    unique_code,
    validate_success,
)
from test_helpers.fixtures import (
    activate,
    allocate_cycle,
    charge_cycle,
    claim_gift,
    deliver_cycle,
    dispatch_cycle,
    generate_cycle,
    lock_cycle,
    make_registry,
    make_registry_item,
    pay_gift,
    reserve_gift,
    setup_registry_parties,
)

OPS = TEST_USERS["ops_admin_headers"]


# ==========================================================================
# Step two — shipping, decided from three non-linear inputs
# ==========================================================================
def test_a_heavy_box_below_the_waiver_attracts_the_surcharge(api):
    """PRD §3.7: "Then: if the subscription's `free_shipping_eligible` is true, shipping is
    0. Otherwise, if `subtotal_cents` is at least 4900 cents, shipping is 0 — a subtotal of
    exactly 4900 does qualify for free shipping. Otherwise shipping is a base of 599 cents,
    plus a heavy surcharge of 250 cents when the total unit count is strictly greater than
    240 — a box of exactly 240 units attracts no surcharge."
    PRD §3.7: "First the server counts total units in the box: for each line whose `status`
    is `ALLOCATED` or `SUBSTITUTED`, its `quantity_packs` multiplied by its SKU's
    `pack_size_units`, summed across the cycle."

    Design: Difficulty/combinatorial_formula/shipping_three_input_nonlinear_heavy_surcharge
    """
    ctx = setup_household(
        api,
        email_prefix="heavy",
        plan_overrides={"default_pack_count": 3},
        sku_overrides={"code": unique_code("S2-BULK"), "name": "Stage 2 Bulk",
                       "pack_price_cents": 400, "pack_size_units": 100, "stock_packs": 10},
        subscription_overrides={"pack_count": 3},
    )
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    allocated = allocate_cycle(api, cycle["id"])

    assert allocated["subtotal_cents"] == 1200
    assert allocated["shipping_cents"] == 849, "599 base plus the 250-cent heavy surcharge"
    assert allocated["total_due_cents"] == 2049
    assert read_subscription(api, ctx["subscription"]["id"])["free_shipping_eligible"] is False


def test_the_subtotal_waiver_outranks_the_heavy_surcharge(api):
    """PRD §3.7: "Otherwise, if `subtotal_cents` is at least 4900 cents, shipping is 0 — a
    subtotal of exactly 4900 does qualify for free shipping. Otherwise shipping is a base of
    599 cents, plus a heavy surcharge of 250 cents when the total unit count is strictly
    greater than 240 — a box of exactly 240 units attracts no surcharge."

    Design: Difficulty/combinatorial_formula/shipping_three_input_nonlinear_heavy_surcharge
    """
    ctx = setup_household(
        api,
        email_prefix="heavyfree",
        plan_overrides={"default_pack_count": 3},
        sku_overrides={"code": unique_code("S2-BIG"), "name": "Stage 2 Big",
                       "pack_price_cents": 2000, "pack_size_units": 100, "stock_packs": 10},
        subscription_overrides={"pack_count": 3},
    )
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    allocated = allocate_cycle(api, cycle["id"])

    assert allocated["subtotal_cents"] == 6000
    assert allocated["shipping_cents"] == 0, (
        "the 4900 waiver is decided before the unit count is ever consulted"
    )
    assert allocated["total_due_cents"] == 6000


def test_a_box_of_exactly_two_hundred_and_forty_units_pays_no_surcharge(api):
    """PRD §3.7: "Otherwise shipping is a base of 599 cents, plus a heavy surcharge of 250
    cents when the total unit count is strictly greater than 240 — a box of exactly 240 units
    attracts no surcharge."
    PRD §3.4: "That derived figure is then clamped into the permitted band: no shorter than
    14 days and no longer than 56 days."

    Design: Difficulty/boundary_precision_check/total_units_exactly_at_heavy_threshold_avoids_surcharge
    """
    ctx = setup_household(
        api,
        email_prefix="units",
        plan_overrides={"code": unique_code("CORE3"), "name": "Core Three",
                        "default_pack_count": 3},
        sku_overrides={"code": unique_code("S2-80"), "name": "Stage 2 Eighty",
                       "pack_price_cents": 400, "pack_size_units": 80, "stock_packs": 10},
        subscription_overrides={"pack_count": 3},
    )
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    allocated = allocate_cycle(api, cycle["id"])

    assert allocated["subtotal_cents"] == 1200
    assert allocated["shipping_cents"] == 599
    assert allocated["total_due_cents"] == 1799
    assert read_subscription(api, ctx["subscription"]["id"])["cadence_interval_days"] == 30


def test_a_box_one_unit_over_the_threshold_pays_the_surcharge(api):
    """PRD §3.7: "Otherwise shipping is a base of 599 cents, plus a heavy surcharge of 250
    cents when the total unit count is strictly greater than 240 — a box of exactly 240 units
    attracts no surcharge."

    Design: Difficulty/boundary_precision_check/total_units_exactly_at_heavy_threshold_avoids_surcharge
    """
    ctx = setup_household(
        api,
        email_prefix="units2",
        plan_overrides={"default_pack_count": 3},
        sku_overrides={"code": unique_code("S2-81"), "name": "Stage 2 Eighty One",
                       "pack_price_cents": 400, "pack_size_units": 81, "stock_packs": 10},
        subscription_overrides={"pack_count": 3},
    )
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    allocated = allocate_cycle(api, cycle["id"])

    assert allocated["subtotal_cents"] == 1200
    assert allocated["shipping_cents"] == 849, "243 units is strictly greater than 240"
    assert allocated["total_due_cents"] == 2049


def test_a_subtotal_of_exactly_forty_nine_hundred_qualifies_for_free_shipping(api):
    """PRD §3.7: "Otherwise, if `subtotal_cents` is at least 4900 cents, shipping is 0 — a
    subtotal of exactly 4900 does qualify for free shipping."
    PRD §3.4: "It also recomputes `cadence_interval_days` and sets `free_shipping_eligible`
    from the household's loyalty tier, which is true exactly when that tier is `SILVER` or
    `GOLD` and false otherwise."

    Design: Corner/cross_cutting_layers/corner_free_shipping_threshold_exactly_at_forty_nine_hundred
    """
    ctx = setup_household(
        api,
        email_prefix="freeship",
        sku_overrides={"code": unique_code("S2-2450"), "name": "Stage 2 Threshold",
                       "pack_price_cents": 2450, "stock_packs": 10},
    )
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    allocated = allocate_cycle(api, cycle["id"])

    assert allocated["subtotal_cents"] == 4900
    assert allocated["shipping_cents"] == 0
    assert allocated["total_due_cents"] == 4900
    assert read_subscription(api, ctx["subscription"]["id"])["free_shipping_eligible"] is False


# ==========================================================================
# Step eight — the promotional discount, rounded per line then summed
# ==========================================================================
def test_the_promotional_discount_rounds_per_line_before_summing(api):
    """PRD §3.7: "The discount is computed per line and then summed, and the order of those
    two operations is pinned. For each line whose `status` is `ALLOCATED` or `SUBSTITUTED`,
    multiply its `line_total_cents` by the plan's `promo_discount_pct` and round half up to
    whole cents; sum those per-line figures."
    PRD §3.7: "To see why the order matters, consider two lines of 1010 cents each on a plan
    with a `promo_discount_pct` of 0.15: rounding per line gives 152 cents twice, for 304;
    summing first and rounding once would give 303. This specification pins 304."

    Design: Difficulty/combinatorial_formula/promo_rounding_per_line_then_sum
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    make_sku(api, code=unique_code("S2-A"), name="Stage 2 A",
             pack_price_cents=1010, pack_size_units=60, stock_packs=1)
    set_clock(api, "2026-06-01T01:00:00Z")
    make_sku(api, code=unique_code("S2-B"), name="Stage 2 B",
             pack_price_cents=1010, pack_size_units=60, stock_packs=5)
    ctx = setup_household(
        api,
        clock="2026-06-01T01:00:00Z",
        with_sku=False,
        email_prefix="promo",
        plan_overrides={"code": unique_code("PROMO15"), "name": "Promo 15",
                        "promo_discount_pct": 0.15},
    )
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    allocated = allocate_cycle(api, cycle["id"])

    assert allocated["subtotal_cents"] == 2020
    assert allocated["shipping_cents"] == 599
    assert allocated["promo_discount_cents"] == 304, (
        "152 per line summed, not 303 from summing before rounding"
    )
    assert allocated["total_due_cents"] == 2315


def test_the_waterfall_splits_the_requirement_across_two_lines(api):
    """PRD §3.5: "Packs are then drawn down the ranking in a waterfall. Starting with a
    remaining requirement equal to the subscription's `pack_count`, the server walks the
    candidates in rank order and takes from each the smaller of the remaining requirement and
    that SKU's `stock_packs`. Each positive take creates a `CycleLine` naming its `cycle_id`
    and `sku_id`, with `quantity_packs` set to the take and `status` `ALLOCATED`, and
    decrements the SKU's `stock_packs` by that amount."

    Design: Difficulty/combinatorial_formula/promo_rounding_per_line_then_sum
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    make_sku(api, code=unique_code("S2-A"), name="Stage 2 A",
             pack_price_cents=1010, pack_size_units=60, stock_packs=1)
    set_clock(api, "2026-06-01T01:00:00Z")
    make_sku(api, code=unique_code("S2-B"), name="Stage 2 B",
             pack_price_cents=1010, pack_size_units=60, stock_packs=5)
    ctx = setup_household(
        api,
        clock="2026-06-01T01:00:00Z",
        with_sku=False,
        email_prefix="promo2",
        plan_overrides={"code": unique_code("PROMO15"), "name": "Promo 15",
                        "promo_discount_pct": 0.15},
    )
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    allocate_cycle(api, cycle["id"])

    lines = cycle_lines(api, cycle["id"])
    assert len(lines) == 2, f"a one-pack SKU cannot cover a two-pack requirement alone; got {len(lines)}"
    for line in lines:
        assert line["quantity_packs"] == 1
        assert line["line_total_cents"] == 1010


# ==========================================================================
# The pinned evaluation order between shipping and the discount
# ==========================================================================
def test_a_discount_never_re_introduces_a_waived_shipping_charge(api):
    """PRD §3.7: "Shipping is decided from the pre-credit, pre-discount subtotal and is
    never revisited after any discount is applied."
    PRD §3.7: "Because step two is never re-run after step eight, a promotional discount can
    never re-introduce a shipping charge that step two waived, and can never remove one it
    levied."

    Design: Difficulty/combinatorial_formula/shipping_decided_before_discount_evaluation_order
    """
    ctx = setup_household(
        api,
        email_prefix="order",
        plan_overrides={"code": unique_code("PROMO25"), "name": "Promo 25",
                        "promo_discount_pct": 0.25},
        sku_overrides={"code": unique_code("S2-MID"), "name": "Stage 2 Mid",
                       "pack_price_cents": 2500, "stock_packs": 10},
    )
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    allocated = allocate_cycle(api, cycle["id"])

    assert allocated["subtotal_cents"] == 5000
    assert allocated["shipping_cents"] == 0
    assert allocated["promo_discount_cents"] == 1250
    assert allocated["total_due_cents"] == 3750, (
        "the payable amount falls below 4900 but shipping stays waived"
    )


def test_a_discount_never_removes_a_shipping_charge_already_levied(api):
    """PRD §3.7: "Because step two is never re-run after step eight, a promotional discount
    can never re-introduce a shipping charge that step two waived, and can never remove one
    it levied. Every intermediate value is an integer number of cents."

    Design: Difficulty/combinatorial_formula/shipping_decided_before_discount_evaluation_order
    """
    ctx = setup_household(
        api,
        email_prefix="order2",
        plan_overrides={"code": unique_code("PROMO25"), "name": "Promo 25",
                        "promo_discount_pct": 0.25},
        sku_overrides={"code": unique_code("S2-LOW"), "name": "Stage 2 Low",
                       "pack_price_cents": 2000, "stock_packs": 10},
    )
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    allocated = allocate_cycle(api, cycle["id"])

    assert allocated["subtotal_cents"] == 4000
    assert allocated["shipping_cents"] == 599, "4000 is below the 4900 waiver"
    assert allocated["promo_discount_cents"] == 1000
    assert allocated["total_due_cents"] == 3599


# ==========================================================================
# The four-position credit stack
# ==========================================================================
def test_the_stack_applies_gift_then_the_referral_pool_then_the_promotion(api):
    """PRD §3.7: "`gift_credit_applied_cents` is the smaller of the pool's total
    `remaining_cents` and the base. The cap here is the whole base, so gift credit alone can
    zero a cycle out."
    PRD §3.7: "`referral_credit_applied_cents` is the smallest of three quantities: the
    pool's total `remaining_cents`, the base minus the gift credit already applied, and that
    cap. The cap deliberately reads the *original* base rather than the post-gift remainder,
    which is precisely what makes the ordering of the stack observable from outside."
    PRD §3.7: "A credit's `status` starts at `AVAILABLE` and moves as it is spent. Consuming
    part of it while it remains within its expiry moves it `AVAILABLE → PARTIALLY_CONSUMED`"

    Design: Corner/calculations/corner_credit_stack_applies_gift_then_referral_pool_then_promo
    """
    parties = setup_registry_parties(
        api,
        with_plan=True,
        plan_overrides={"code": unique_code("PROMO10"), "name": "Promo Ten",
                        "promo_discount_pct": 0.1},
        sku_overrides={"code": unique_code("S2-GIFT"), "name": "Stage 2 Gift Pack",
                       "pack_price_cents": 1000, "stock_packs": 0},
    )
    make_sku(api, code=unique_code("S2-STD"), pack_price_cents=1200, stock_packs=50)

    registry = make_registry(api, parties)
    item = make_registry_item(api, parties, registry["id"], requested_quantity=1)
    validate_success(api.open_registry(registry["id"], parties["owner_headers"]))
    gift = reserve_gift(api, parties, item, 1)
    pay_gift(api, parties, gift["id"])
    claim_gift(api, parties, gift["id"], "CREDIT")

    goodwill = issue_goodwill_credit(api, parties["owner_id"], 5000)

    subscription = make_subscription(
        api, parties["owner"], parties["plan"], parties["child"]
    )
    subscription = activate(api, parties["owner_id"], subscription["id"])
    cycle = generate_cycle(api, subscription["id"])
    allocate_cycle(api, cycle["id"])

    charged = charge_cycle(api, cycle["id"])
    assert charged["gift_credit_applied_cents"] == 1000
    assert charged["referral_credit_applied_cents"] == 1500, (
        "the 50 percent cap reads the original 2999 base, not the 1999 post-gift remainder"
    )
    assert charged["loyalty_redemption_applied_cents"] == 0
    assert charged["promo_discount_cents"] == 240
    assert charged["total_due_cents"] == 259
    assert charged["charged_cash_cents"] == 259

    credit = validate_success(
        api.get_credit(goodwill["id"], parties["owner_account_headers"])
    )
    assert credit["consumed_cents"] == 1500
    assert credit["remaining_cents"] == 3500
    assert credit["status"] == "PARTIALLY_CONSUMED"


def test_the_redemption_floor_applied_to_the_burned_points_zeroes_the_redemption(api):
    """PRD §3.7: "This position is capped at 30 percent of that remainder, computed as the
    remainder multiplied by 0.30 and rounded half up to whole cents."
    PRD §3.7: "The floor is then applied a *second* time, to the points actually burned: if
    that figure is below 500, the redemption is abandoned and both fields are 0 again. A
    wallet holding 600 points facing a cap of 3 cents therefore redeems nothing at all."

    Design: Corner/calculations/corner_loyalty_redemption_zeroed_by_double_floor_at_charge
    """
    ctx = setup_household(
        api,
        email_prefix="floor",
        sku_overrides={"code": unique_code("S2-PREM"), "name": "Stage 2 Premium",
                       "pack_price_cents": 25000, "stock_packs": 2},
    )
    cheap = make_sku(api, code=unique_code("S2-CHEAP"), name="Stage 2 Cheap",
                     pack_price_cents=400, stock_packs=0)

    first = generate_cycle(api, ctx["subscription"]["id"])
    allocate_cycle(api, first["id"])
    set_clock(api, "2026-06-08T00:00:00Z")
    lock_cycle(api, first["id"])
    charge_cycle(api, first["id"])
    dispatch_cycle(api, first["id"])
    deliver_cycle(api, first["id"])

    wallet = validate_success(api.get_loyalty_account(ctx["loyalty_account_id"], OPS))
    assert wallet["points_balance"] == 500

    validate_success(api.adjust_sku_stock(cheap["id"], 50, OPS))
    second = generate_cycle(api, ctx["subscription"]["id"])
    allocate_cycle(api, second["id"])

    charged = charge_cycle(api, second["id"])
    assert charged["subtotal_cents"] == 800
    assert charged["shipping_cents"] == 599
    assert charged["loyalty_redemption_applied_cents"] == 0
    assert charged["loyalty_points_redeemed"] == 0
    assert charged["total_due_cents"] == 1399


def test_the_conservative_estimate_ignores_credits_and_the_points_balance(api):
    """PRD §3.1: "When `include_credits` is supplied as false — the conservative variant —
    every credit and the points balance are ignored entirely and the estimate reports the
    target cycle's `subtotal_cents` plus its `shipping_cents`. The two answers differ
    whenever the household holds any usable credit."
    PRD §3.1: "When `include_credits` is omitted or true — the optimistic variant, and the
    same one stored on the account itself — the estimate assumes every currently available
    credit and the whole points balance will still apply at charge time, and reports the
    target cycle's `total_due_cents`."

    Design: Corner/calculations/corner_next_charge_estimate_conservative_ignores_credits
    """
    ctx = setup_household(api, email_prefix="estimate")
    issue_goodwill_credit(api, ctx["account_id"], 5000)
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    allocated = allocate_cycle(api, cycle["id"])

    assert allocated["referral_credit_applied_cents"] == 1500
    assert allocated["total_due_cents"] == 1499

    conservative = validate_success(
        api.get_credit_summary(ctx["account_id"], ctx["headers"], {"include_credits": "false"})
    )
    assert conservative["next_charge_estimate_cents"] == 2999

    optimistic = validate_success(api.get_credit_summary(ctx["account_id"], ctx["headers"]))
    assert optimistic["next_charge_estimate_cents"] == 1499
    assert optimistic["available_credit_cents"] == 5000
