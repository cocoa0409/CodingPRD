"""Two calculations that legitimately give two answers to the same question.

A quote can be asked live (what may we promise now?) or pinned at creation (what
did we promise on this order?), and a statement can be read as the money a gross
channel remits or as the money a net channel remits after withholding.
"""
from test_helpers import (
    assert_instant,
    assert_order,
    assert_preview_shape,
    assert_quote_shape,
    assert_remittance_statement,
    assert_statement_pipeline,
    create_accepted_adjustment,
    env_partner_headers,
    minutes_between,
    place_order,
    place_ready_order,
    preview_statement,
    read_order,
    read_statement,
    setup_published_store,
    setup_statement_with_orders,
    validate_success,
)


def _quote(api, env, fulfillment_mode="DELIVERY"):
    params = {"channel_id": env["channel"]["id"], "fulfillment_mode": fulfillment_mode}
    return api.get_quote(env["store"]["id"], env_partner_headers(env), params=params)


def test_provisional_quote_counts_the_store_s_open_orders_right_now(api):
    """A live quote pads preparation by two minutes for each open order it counts.

    PRD: "In this variant `load_count` is the number of orders at the store,
    evaluated at request time, whose `injection_status` is `PENDING`,
    `INJECTION_HELD`, `ACCEPTED` or `TABLET_FALLBACK` and whose
    `fulfillment_status` is `PREPARING`", and "The preparation figure
    `prep_minutes` starts at the store's `base_prep_minutes`, adds 2 minutes for
    each order counted in the load figure `load_count`, and adds a further 8
    minutes when the store's posture is `THROTTLED`". "The travel figure
    `travel_minutes` is 11 minutes when the `fulfillment_mode` is `DELIVERY` and
    0 when it is `PICKUP`."

    Design: Difficulty/dual_variant_calc/dual_variant_quote_provisional_versus_confirmed_on_store
    """
    env = setup_published_store()
    place_order(env, external_ref="MP-1001")

    quote = validate_success(_quote(api, env))

    assert_quote_shape(quote, "PROVISIONAL")
    assert quote["store_id"] == env["store"]["id"]
    assert quote["channel_id"] == env["channel"]["id"]
    assert quote["load_count"] == 1, f"one open order is in the kitchen, got load_count {quote['load_count']}"
    assert quote["prep_minutes"] == 14, f"12 base plus 2 for one order, got {quote['prep_minutes']}"
    assert quote["travel_minutes"] == 11, f"delivery travel is 11 minutes, got {quote['travel_minutes']}"
    assert quote["total_minutes"] == 25, f"14 preparation plus 11 travel, got {quote['total_minutes']}"
    assert quote["bucket_index"] == 44, f"local minute 660 divided by 15, got {quote['bucket_index']}"
    assert quote["bucket_load"] == 1, f"one order occupies the bucket, got {quote['bucket_load']}"
    assert_instant(quote["quoted_ready_at"], "2026-08-03T16:25:00Z", "quoted_ready_at")


def test_confirmed_quote_pinned_on_the_order_ignores_the_order_itself(api):
    """The promise pinned on an order counts only orders older than it.

    PRD: "The **`CONFIRMED`** variant answers "what shall we promise on this
    particular order?", and its answer is pinned onto the order as
    `promised_ready_at` at the moment of creation. Here `load_count` is a
    chronological replay rather than a live snapshot: it counts only those
    qualifying orders that were created strictly before the new order's own
    `created_at`". "Once pinned, `promised_ready_at` is never recomputed — a
    later throttle change, a later order, or a later clock movement does not move
    it, which is what makes the promise auditable against the channel."

    Design: Difficulty/dual_variant_calc/dual_variant_quote_provisional_versus_confirmed_on_store
    """
    env = setup_published_store()
    order = place_order(env, external_ref="MP-1001")

    assert_order(order)
    assert_instant(order["promised_ready_at"], "2026-08-03T16:23:00Z", "promised_ready_at")

    quote = validate_success(_quote(api, env))
    assert quote["variant"] == "PROVISIONAL"
    assert minutes_between(order["promised_ready_at"], quote["quoted_ready_at"]) == 2, (
        "the live quote counts the new order itself and is therefore one load pad later"
    )
    assert_instant(
        read_order(order["id"])["promised_ready_at"], "2026-08-03T16:23:00Z",
        "promised_ready_at after a later quote",
    )


def test_settlement_preview_shows_both_modes_side_by_side(api):
    """One adjusted volume, two remittance answers, reported together.

    PRD: "On a `GROSS_MODE` channel the partner remits the adjusted volume and
    the brand is invoiced for commission separately, so `net_payable_cents` is
    `tier_base_cents` plus `rebate_cents`; `commission_cents` is still computed
    and still reported, but it is not withheld. On a `NET_MODE` channel the
    partner withholds its commission before remitting, so `net_payable_cents` is
    `tier_base_cents` minus `commission_cents` plus `rebate_cents`." The preview
    "additionally shows both mode outcomes side by side as
    `gross_mode_net_payable_cents` and `net_mode_net_payable_cents` so a partner
    can see what the other mode would have paid".

    Design: Difficulty/dual_variant_calc/dual_variant_settlement_gross_versus_net_on_statement
    """
    env = setup_published_store()
    first = place_ready_order(env, external_ref="MP-1001")
    second = place_ready_order(env, external_ref="MP-1002")
    create_accepted_adjustment(read_order(first["id"]), amount_cents=1000)
    statement = setup_statement_with_orders(env, [first, second])

    preview = preview_statement(statement)

    assert_preview_shape(preview)
    assert preview["settlement_mode"] == "NET_MODE"
    assert preview["gross_sales_cents"] == 6578, f"two sales of 3289, got {preview['gross_sales_cents']}"
    assert preview["adjustment_total_cents"] == 1000
    assert preview["tier_base_cents"] == 5578
    assert preview["tier"] == "TIER_1"
    assert preview["effective_commission_bps"] == 2500
    assert preview["commission_cents"] == 1395
    assert preview["rebate_cents"] == 0
    assert preview["gross_mode_net_payable_cents"] == 5578, (
        f"a gross channel remits the adjusted volume, got {preview['gross_mode_net_payable_cents']}"
    )
    assert preview["net_mode_net_payable_cents"] == 4183, (
        f"a net channel withholds 1395, got {preview['net_mode_net_payable_cents']}"
    )
    assert (
        preview["gross_mode_net_payable_cents"] - preview["net_mode_net_payable_cents"]
        == preview["commission_cents"]
    ), "the two modes differ by exactly the commission"


def test_statement_persists_the_net_mode_answer_for_a_net_mode_channel(api):
    """The stored figure is the one the channel's own settlement mode dictates.

    PRD: "Seventh and last, `net_payable_cents` is derived from the channel's
    `settlement_mode`." "On a `NET_MODE` channel the partner withholds its
    commission before remitting, so `net_payable_cents` is `tier_base_cents`
    minus `commission_cents` plus `rebate_cents`."

    Design: Difficulty/dual_variant_calc/dual_variant_settlement_gross_versus_net_on_statement
    """
    env = setup_published_store()
    first = place_ready_order(env, external_ref="MP-1001")
    second = place_ready_order(env, external_ref="MP-1002")
    create_accepted_adjustment(read_order(first["id"]), amount_cents=1000)
    statement = setup_statement_with_orders(env, [first, second])

    statement = read_statement(statement["id"])
    assert_remittance_statement(statement)
    assert statement["order_count"] == 2
    assert statement["gross_sales_cents"] == 6578
    assert statement["adjustment_total_cents"] == 1000
    assert statement["tier_base_cents"] == 5578
    assert statement["tier"] == "TIER_1"
    assert statement["commission_cents"] == 1395
    assert statement["rebate_cents"] == 0
    assert statement["net_payable_cents"] == 4183, (
        f"5578 less the withheld 1395, got {statement['net_payable_cents']}"
    )
    assert_statement_pipeline(statement, commission_bps=2500, settlement_mode="NET_MODE")
