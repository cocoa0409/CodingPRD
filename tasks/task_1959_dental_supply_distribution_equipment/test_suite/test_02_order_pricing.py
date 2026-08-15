"""Order pricing: computed totals, volume/bundle discounts, promotion attachment gates."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    assert_order,
    create_practice,
    create_product,
    create_order_payload,
    create_bundle_promotion_payload,
    create_rebate_promotion_payload,
    TEST_USERS,
    ApiErrorId,
)

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]


def _create_promo(payload):
    return api_client.create_promotion(payload, ADMIN)


def test_order_computed_and_system_fields_enforced(api):
    """PRD §3.3: "At creation the server prices every line by snapshotting the product's
    current `unit_price_cents` onto the line and computing its `line_total_cents`, so later
    catalog price changes never retroactively alter an open order." and "The `total_cents`
    is the `subtotal_cents` minus the `discount_cents`, and a new order starts in `DRAFT`."

    Design: Corner/entities/order_computed_and_system_fields_enforced
    """
    practice = create_practice(name="P Comp", credit_limit_cents=10000000)
    product = create_product(sku="C-2", name="Bibs", unit_price_cents=10000)
    order = validate_success(
        api.create_order(
            create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 3}]),
            SALES,
        ),
        201,
    )
    assert_order(order)
    assert order["subtotal_cents"] == 30000
    assert order["volume_discount_cents"] == 0, "30000 is below the 200000-cent tier"
    assert order["bundle_discount_cents"] == 0
    assert order["discount_cents"] == 0
    assert order["total_cents"] == 30000
    assert order["status"] == "DRAFT"
    assert order["lines"][0]["unit_price_cents"] == 10000
    assert order["lines"][0]["line_total_cents"] == 30000


def test_order_initial_state_draft_on_create(api):
    """PRD §3.3: "The `total_cents` is the `subtotal_cents` minus the `discount_cents`,
    and a new order starts in `DRAFT`."

    Design: Corner/state_machines/order_initial_state_draft_on_create
    """
    practice = create_practice(name="P Init", credit_limit_cents=1000000)
    product = create_product(sku="C-6", name="Cups", unit_price_cents=500)
    order = validate_success(
        api.create_order(
            create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 1}]),
            SALES,
        ),
        201,
    )
    assert order["status"] == "DRAFT"


def test_volume_discount_tier_at_500000(api):
    """PRD §3.3: "Pricing then runs in a pinned order — tier selection is keyed on the
    pre-discount subtotal, the discount is computed from that same subtotal, and only then
    is the total derived, removing any circular reading." and "a subtotal of at least
    500,000 cents earns ten percent, a subtotal of at least 200,000 cents earns five
    percent, and anything below earns nothing".

    Design: Difficulty/combinatorial_formula/volume_discount_tier_keyed_on_prediscount_subtotal
    """
    practice = create_practice(name="P Vol", credit_limit_cents=10000000)
    product = create_product(sku="C-1", name="Gloves", unit_price_cents=250000)
    order = validate_success(
        api.create_order(
            create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 2}]),
            SALES,
        ),
        201,
    )
    assert order["subtotal_cents"] == 500000
    assert order["volume_discount_cents"] == 50000, (
        "Tier keyed on pre-discount subtotal 500000 earns 10%; keying on the discounted "
        "total 450000 would wrongly earn 5%"
    )
    assert order["total_cents"] == 450000


def test_volume_discount_tier_at_200000(api):
    """PRD §3.3: "a subtotal of at least 500,000 cents earns ten percent, a subtotal of
    at least 200,000 cents earns five percent, and anything below earns nothing".

    Design: Difficulty/combinatorial_formula/volume_discount_tier_keyed_on_prediscount_subtotal
    """
    practice = create_practice(name="P Vol2", credit_limit_cents=10000000)
    p200 = create_product(sku="C-200", name="AtTier2", unit_price_cents=100000)
    order = validate_success(
        api.create_order(
            create_order_payload(practice["id"], [{"product_id": p200["id"], "quantity": 2}]),
            SALES,
        ),
        201,
    )
    assert order["subtotal_cents"] == 200000
    assert order["volume_discount_cents"] == 10000, "Exactly 200000 earns five percent"
    assert order["total_cents"] == 190000

    p_below = create_product(sku="C-199", name="BelowTier2", unit_price_cents=199999)
    below = validate_success(
        api.create_order(
            create_order_payload(practice["id"], [{"product_id": p_below["id"], "quantity": 1}]),
            SALES,
        ),
        201,
    )
    assert below["subtotal_cents"] == 199999
    assert below["volume_discount_cents"] == 0, "One cent below the 200000 tier earns nothing"
    assert below["total_cents"] == 199999


def _setup_bundle_products():
    elite = create_practice(name="P Elite", practice_tier="ELITE", credit_limit_cents=50000000)
    standard = create_practice(name="P Std", practice_tier="STANDARD", credit_limit_cents=50000000)
    pa = create_product(sku="PA", name="A", unit_price_cents=60000)
    pb = create_product(sku="PB", name="B", unit_price_cents=40000)
    pc = create_product(sku="PC", name="C", unit_price_cents=90000)
    pd = create_product(sku="PD", name="D", unit_price_cents=60000)
    promo1 = validate_success(
        _create_promo(create_bundle_promotion_payload([pa["id"], pb["id"]])), 201
    )
    promo2 = validate_success(
        _create_promo(create_bundle_promotion_payload([pc["id"], pd["id"]], name="B2")),
        201,
    )
    return elite, standard, pa, pb, pc, pd, promo1, promo2


def test_bundle_discount_elite_vs_standard(api):
    """PRD §3.3: "add a tier bonus of 0.02 to the promotion's `discount_pct` when the
    ordering practice is `ELITE` (all other tiers add nothing), multiply the component
    subtotal by the combined fraction, round half up to whole cents" and "with a promotion
    whose `stacking_allowed` is false it is the greater of the volume and bundle discounts".

    Design: Difficulty/combinatorial_formula/bundle_discount_tier_bonus_then_cap
    """
    elite, standard, pa, pb, _, _, promo1, _ = _setup_bundle_products()
    lines = [{"product_id": pa["id"], "quantity": 1}, {"product_id": pb["id"], "quantity": 1}]

    elite_order = validate_success(
        api.create_order(
            create_order_payload(elite["id"], lines, kind="BUNDLE", promotion_id=promo1["id"]),
            SALES,
        ),
        201,
    )
    assert elite_order["subtotal_cents"] == 100000
    assert elite_order["bundle_discount_cents"] == 17000, "100000 x (0.15 + 0.02 ELITE bonus)"
    assert elite_order["discount_cents"] == 17000
    assert elite_order["total_cents"] == 83000

    std_order = validate_success(
        api.create_order(
            create_order_payload(standard["id"], lines, kind="BUNDLE", promotion_id=promo1["id"]),
            SALES,
        ),
        201,
    )
    assert std_order["bundle_discount_cents"] == 15000, "100000 x 0.15, no tier bonus for STANDARD"
    assert std_order["total_cents"] == 85000


def test_bundle_discount_capped_by_max_discount(api):
    """PRD §3.3: "and then, if the promotion sets a `max_discount_cents` cap, take the
    lesser of the rounded amount and the cap; an uncapped promotion keeps the rounded
    amount."

    Design: Difficulty/combinatorial_formula/bundle_discount_tier_bonus_then_cap
    """
    elite, _, _, _, pc, pd, _, promo2 = _setup_bundle_products()
    order = validate_success(
        api.create_order(
            create_order_payload(
                elite["id"],
                [{"product_id": pc["id"], "quantity": 1}, {"product_id": pd["id"], "quantity": 1}],
                kind="BUNDLE",
                promotion_id=promo2["id"],
            ),
            SALES,
        ),
        201,
    )
    assert order["subtotal_cents"] == 150000
    assert order["bundle_discount_cents"] == 20000, (
        "raw 150000 x 0.17 = 25500 clamped by the 20000 max_discount_cents cap"
    )
    assert order["total_cents"] == 130000


def test_immediate_consistency_on_order_create(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."

    Design: Corner/consistency_model/immediate_consistency_on_order_create
    """
    practice = create_practice(name="P Ic", credit_limit_cents=10000000)
    product = create_product(sku="C-25", name="Bibs", unit_price_cents=10000)
    order = validate_success(
        api.create_order(
            create_order_payload(practice["id"], [{"product_id": product["id"], "quantity": 3}]),
            SALES,
        ),
        201,
    )
    assert order["total_cents"] == 30000
    fetched = validate_success(api.get_order(order["id"], ADMIN), 200)
    assert fetched["total_cents"] == 30000, "Immediate read must return identical totals"
    assert fetched["subtotal_cents"] == order["subtotal_cents"]
    assert fetched["discount_cents"] == order["discount_cents"]


def test_expired_promotion_rejected_on_order_create(api):
    """PRD §3.3: "then promotion activity — an attached promotion must be `ACTIVE` after
    the lazy expiry check with the logical now inside its inclusive program window, else
    `ERR_PROMOTION_INACTIVE`".
    PRD §2.5: "whenever the promotion is attached to something or read, and the logical now
    is strictly after its `end_date`, an `ACTIVE` promotion flips to `EXPIRED`".

    Design: Corner/validations/expired_promotion_rejected_on_order_create
    """
    practice = create_practice(name="P Pr", credit_limit_cents=10000000)
    pa = create_product(sku="PA-2", name="A", unit_price_cents=60000)
    pb = create_product(sku="PB-2", name="B", unit_price_cents=40000)
    promo = validate_success(
        _create_promo(
            create_bundle_promotion_payload(
                [pa["id"], pb["id"]],
                name="OLD",
                start_date="2026-01-01T00:00:00Z",
                end_date="2026-06-01T00:00:00Z",
            )
        ),
        201,
    )
    res = api.create_order(
        create_order_payload(
            practice["id"],
            [{"product_id": pa["id"], "quantity": 1}, {"product_id": pb["id"], "quantity": 1}],
            kind="BUNDLE",
            promotion_id=promo["id"],
        ),
        SALES,
    )
    validate_error(res, ApiErrorId.ERR_PROMOTION_INACTIVE)

    promo_after = validate_success(api.get_promotion(promo["id"], ADMIN), 200)
    assert promo_after["status"] == "EXPIRED", "Lazy expiry must persist the EXPIRED flip"


def test_rebate_promo_attached_to_order_rejected(api):
    """PRD §3.3: "then promotion applicability — orders accept only `BUNDLE_DISCOUNT`
    promotions, else `ERR_PROMOTION_NOT_APPLICABLE`".

    Design: Corner/validations/rebate_promo_attached_to_order_rejected
    """
    practice = create_practice(name="P Na", credit_limit_cents=1000000)
    product = create_product(sku="C-20", name="Floss", unit_price_cents=1000)
    promo = validate_success(
        _create_promo(create_rebate_promotion_payload([product["id"]])), 201
    )
    res = api.create_order(
        create_order_payload(
            practice["id"],
            [{"product_id": product["id"], "quantity": 1}],
            promotion_id=promo["id"],
        ),
        SALES,
    )
    validate_error(res, ApiErrorId.ERR_PROMOTION_NOT_APPLICABLE)


def test_bundle_incomplete_at_submit(api):
    """PRD §3.3: "when no promotion is attached, or when any product in the promotion's
    `required_product_ids` is absent from the order's lines, the `bundle_discount_cents`
    is zero." and "for a `BUNDLE` order, every product in the attached promotion's
    `required_product_ids` must be present in the lines, else `ERR_BUNDLE_INCOMPLETE`".

    Design: Corner/validations/bundle_incomplete_at_submit
    """
    practice = create_practice(name="P Bnd", credit_limit_cents=10000000)
    pa = create_product(sku="PA-3", name="A", unit_price_cents=60000)
    pb = create_product(sku="PB-3", name="B", unit_price_cents=40000)
    promo = validate_success(
        _create_promo(create_bundle_promotion_payload([pa["id"], pb["id"]], name="BD")),
        201,
    )
    order = validate_success(
        api.create_order(
            create_order_payload(
                practice["id"],
                [{"product_id": pa["id"], "quantity": 1}],
                kind="BUNDLE",
                promotion_id=promo["id"],
            ),
            SALES,
        ),
        201,
    )
    assert order["bundle_discount_cents"] == 0, "Required product absent at creation -> no bundle discount"

    res = api.submit_order(order["id"], SALES)
    validate_error(res, ApiErrorId.ERR_BUNDLE_INCOMPLETE)
    after = validate_success(api.get_order(order["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"
