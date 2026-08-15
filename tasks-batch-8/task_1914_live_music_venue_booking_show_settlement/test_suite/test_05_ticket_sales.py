"""Ticket tiers, roll-up allocation, refunds, and ticket-sale append-only shape."""
from test_helpers import (
    PROM,
    ApiErrorId,
    assert_ticket_sale,
    create_on_sale_show,
    create_show_with_deal,
    create_tier,
    get_show,
    sell_tickets,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_tier_roll_up_zero_availability_boundary(api):
    """PRD §3.4: "If the total availability across the candidate pool falls
    short of the requested quantity, the entire sale is rejected with
    `ERR_INSUFFICIENT_TICKET_CAPACITY` (HTTP 422) — partial fills do not
    exist."

    Design: Difficulty/boundary_precision_check/tier_roll_up_zero_availability_boundary
    """
    set_clock()
    artist, agent, show, deal, _tier = create_on_sale_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=10000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=0, support_budget_cents=0,
            bar_split_pct=0, merch_split_pct=0,
        ),
        show_overrides=dict(total_capacity=15),
        tier_overrides=dict(tier_name="T1", face_price_cents=1000,
                            capacity=10, tier_order=1),
    )
    t2 = create_tier(
        show["id"], tier_name="T2", face_price_cents=2000, capacity=5,
        tier_order=2,
    )
    tiers, _meta = validate_paginated(api.list_ticket_tiers(show["id"], PROM))
    t1 = next(t for t in tiers if t["tier_name"] == "T1")

    # Request exactly the total available (10 + 5 = 15) — succeeds.
    sale = sell_tickets(show["id"], t1["id"], 15)
    assert sale["gross_amount_cents"] == (10 * 1000) + (5 * 2000)
    assert sale["gross_amount_cents"] == 20000

    # After sell-out, one more ticket must fail.
    resp = api.create_ticket_sale(
        show["id"], {"tier_id": t1["id"], "quantity": 1}, PROM,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_TICKET_CAPACITY, 422)

    # Verify per-tier sold counts
    tiers_after, _ = validate_paginated(api.list_ticket_tiers(show["id"], PROM))
    t1_after = next(t for t in tiers_after if t["tier_name"] == "T1")
    t2_after = next(t for t in tiers_after if t["tier_name"] == "T2")
    assert t1_after["sold_count"] == 10
    assert t2_after["sold_count"] == 5
    # Failed sale did not change the show.
    assert get_show(show["id"])["tickets_sold"] == 15


def test_tier_roll_up_composite_gross(api):
    """PRD §3.4: "A successful sale is recorded as a single `TicketSale` row
    whose `gross_amount_cents` is the composite sum across all tiers that
    filled it (for a single-tier fill, simply the quantity multiplied by
    the tier's face price), stamped with the server's `sold_at_utc`, born
    with `refund_status` `NONE`."

    Design: Difficulty/boundary_precision_check/tier_roll_up_zero_availability_boundary
    """
    set_clock()
    artist, agent, show, deal, t1 = create_on_sale_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=10000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=0, support_budget_cents=0,
            bar_split_pct=0, merch_split_pct=0,
        ),
        show_overrides=dict(total_capacity=20),
        tier_overrides=dict(tier_name="T1", face_price_cents=1000,
                            capacity=3, tier_order=1),
    )
    t2 = create_tier(
        show["id"], tier_name="T2", face_price_cents=2000, capacity=5,
        tier_order=2,
    )
    # Request 5 against T1 (capacity 3) — 3 from T1 + 2 from T2.
    sale = sell_tickets(show["id"], t1["id"], 5)
    assert sale["quantity"] == 5
    assert sale["gross_amount_cents"] == (3 * 1000) + (2 * 2000)
    assert sale["gross_amount_cents"] == 7000


def test_ticket_sale_refund_conserves_gross_revenue(api):
    """PRD §3.4: "A `Promoter` refunding a sale flips its `refund_status`
    from `NONE` to `REFUNDED`, decrements the tier's `sold_count` by the
    sale's `quantity`, increments the tier's `refund_count` by the same, and
    recomputes the show's `tickets_sold` and `gross_ticket_revenue_cents` so
    that refunded money disappears from every downstream calculation — the
    settlement waterfall of §3.7 counts only sales whose `refund_status` is
    still `NONE`."

    Design: Difficulty/compensating_invariant/ticket_sale_refund_conserves_gross_revenue
    """
    set_clock()
    artist, agent, show, deal, tier = create_on_sale_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=10000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=0, support_budget_cents=0,
            bar_split_pct=0, merch_split_pct=0,
        ),
        tier_overrides=dict(face_price_cents=2000, capacity=500, tier_order=1),
    )
    sale1 = sell_tickets(show["id"], tier["id"], 10)
    sale2 = sell_tickets(show["id"], tier["id"], 4)
    # Pre-refund state: (10+4) × 2000 = 28000.
    pre = get_show(show["id"])
    assert pre["gross_ticket_revenue_cents"] == 28000
    assert pre["tickets_sold"] == 14

    # Refund sale2 (4 × 2000 = 8000).
    refunded = validate_success(
        api.refund_ticket_sale(show["id"], sale2["id"], PROM), 200,
    )
    assert refunded["refund_status"] == "REFUNDED"

    post = get_show(show["id"])
    assert post["gross_ticket_revenue_cents"] == 20000
    assert post["tickets_sold"] == 10

    # Invariant: live gross + refunded gross == sum of created gross.
    sum_created = sale1["gross_amount_cents"] + sale2["gross_amount_cents"]
    assert post["gross_ticket_revenue_cents"] + sale2["gross_amount_cents"] == sum_created


def test_refund_recomputes_tier_counters(api):
    """PRD §3.4: "A `Promoter` refunding a sale flips its `refund_status`
    from `NONE` to `REFUNDED`, decrements the tier's `sold_count` by the
    sale's `quantity`, increments the tier's `refund_count` by the same, and
    recomputes the show's `tickets_sold` and `gross_ticket_revenue_cents` so
    that refunded money disappears from every downstream calculation — the
    settlement waterfall of §3.7 counts only sales whose `refund_status` is
    still `NONE`."

    Design: Difficulty/compensating_invariant/ticket_sale_refund_conserves_gross_revenue
    """
    set_clock()
    artist, agent, show, deal, tier = create_on_sale_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=10000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=0, support_budget_cents=0,
            bar_split_pct=0, merch_split_pct=0,
        ),
        tier_overrides=dict(face_price_cents=1000, capacity=100, tier_order=1),
    )
    sale = sell_tickets(show["id"], tier["id"], 7)
    validate_success(api.refund_ticket_sale(show["id"], sale["id"], PROM), 200)

    tiers, _ = validate_paginated(api.list_ticket_tiers(show["id"], PROM))
    t_after = tiers[0]
    assert t_after["sold_count"] == 0
    assert t_after["refund_count"] == 7


def test_ticket_sale_immutable_no_version_field(api):
    """PRD §2.4: "Three ledger-style records are the exception, and the
    exception is explicit: a `TicketSale`, an `AncillaryRevenue` row, and a
    `CancellationEvent` each carry only `id` and `created_at`. Both
    `updated_at` and `version` are absent from these three entities — they
    are append-only records of the night, never mutated in place, and no
    concurrency protocol ever reads their version."

    Design: Corner/entities/ticket_sale_immutable_no_version_field
    """
    set_clock()
    artist, agent, show, deal, tier = create_on_sale_show(
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=10000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=0, support_budget_cents=0,
            bar_split_pct=0, merch_split_pct=0,
        ),
    )
    sale = sell_tickets(show["id"], tier["id"], 1)
    assert_ticket_sale(sale)


def test_tier_capacity_exceeded_on_create(api):
    """PRD §3.4: "Two constraints guard the manifest, both reported as
    `ERR_TIER_CAPACITY_EXCEEDED` (HTTP 422): the sum of tier capacities must
    not exceed the show's `total_capacity`, and `tier_order` must be unique
    within the show."

    Design: Corner/validations/tier_capacity_exceeded_on_create
    """
    set_clock()
    artist, agent, show, deal = create_show_with_deal(
        show_overrides=dict(total_capacity=100),
    )
    # First tier fits (60 of 100)
    create_tier(show["id"], tier_name="T1", face_price_cents=1000,
                capacity=60, tier_order=1)
    # Second tier (50) pushes the sum to 110 > 100.
    resp = api.create_ticket_tier(
        show["id"],
        {"tier_name": "T2", "face_price_cents": 2000, "capacity": 50,
         "tier_order": 2},
        PROM,
    )
    validate_error(resp, ApiErrorId.ERR_TIER_CAPACITY_EXCEEDED, 422)
