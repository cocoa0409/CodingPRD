"""The two large cascades and the admission ladder around them.

The delivery cascade reprices the order under the invoiced variant and can
push the customer onto credit hold; a copper index publication can void a
quote, cancel its order and unwind the reservations behind it.
"""


from test_helpers import (
    ApiErrorId,
    PRODUCT_P1,
    allocate_payload,
    allocations_of_order,
    build_quote,
    commit_cut,
    convert_quote,
    create_branch,
    create_customer,
    create_product,
    create_truck,
    dispatch_run,
    deliver_run,
    issue_quote,
    list_order_lines,
    make_branch_ops_headers,
    make_platform_admin_headers,
    post_credit_adjustment,
    publish_index,
    read_allocation,
    read_customer,
    read_index_entry,
    read_order,
    read_order_line,
    read_quote,
    read_reel,
    read_run,
    receive_reel,
    run_allocator,
    schedule_run,
    set_clock,
    setup_allocated_order,
    validate_error,
)

ADMIN = make_platform_admin_headers()
CUT_137 = {"put_up": "CUT", "requested_length_ft": 137}


# ══════════════════════════════════════════════════════════════════════════
# The order line carries both pricing variants after delivery
# ══════════════════════════════════════════════════════════════════════════

def _order_delivered_under_a_later_settlement():
    """Two identical 137 ft CUT lines quoted at 450 c/lb and delivered on a
    day whose current settlement is 500 c/lb."""
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P1)
    publish_index("2026-07-30", 450)
    truck = create_truck(branch["id"], truck_code="T-1")
    receive_reel(product["id"], branch["id"], 1000)

    quote, _ = build_quote(
        customer["id"], branch["id"], product["id"], [CUT_137, dict(CUT_137)]
    )
    issue_quote(quote["id"], issuer="rep-2")
    order = convert_quote(quote["id"], issuer="rep-2")
    order_lines = list_order_lines(sales_order_id=order["id"])
    run_allocator(order["id"], branch["id"], policy="MINIMIZE_REMNANT")
    allocations = allocations_of_order(order["id"])

    set_clock("2026-08-06T07:00:00Z")
    commit_cut(
        allocations[0]["id"], branch["id"],
        "2026-08-06T08:00:00Z", "2026-08-06T09:00:00Z",
    )
    commit_cut(
        allocations[1]["id"], branch["id"],
        "2026-08-06T10:00:00Z", "2026-08-06T11:00:00Z",
    )
    run = schedule_run(
        order["id"], truck["id"], branch["id"],
        "2026-08-07T08:00:00Z", "2026-08-07T10:00:00Z",
    )
    dispatch_run(run["id"], truck["id"])
    publish_index("2026-08-03", 500)
    set_clock("2026-08-07T09:00:00Z")
    deliver_run(run["id"], truck["id"])

    return {
        "branch": branch, "customer": customer, "order": read_order(order["id"]),
        "order_lines": order_lines, "run": run,
    }


def test_order_lines_carry_both_the_quoted_and_the_invoiced_variant(api):
    """PRD §3.8: "Every order line is repriced by exactly the same per-line
    arithmetic as Section 3.4 — the aluminium zero, the four-decimal
    pass-through, the once-per-line half-up rounding into whole cents, the
    exact integer base, and the unchanged cut charge — with one substitution:
    the index used is no longer the one pinned on the quote, but the copper
    index entry with the greatest `effective_date` on or before the calendar
    date of the order's `delivered_at`, which may well be a different entry."
    PRD §3.8: "The result is written to each line's `invoiced_extended_cents`;
    `base_cents` and the cut charge are identical under both variants, so only
    the metal component moves."

    Design: Difficulty/dual_variant_calc/metal_pass_through_quoted_vs_invoiced_on_order_lines
    """
    world = _order_delivered_under_a_later_settlement()

    for order_line in world["order_lines"]:
        priced = read_order_line(order_line["id"])
        assert priced["quoted_extended_cents"] == 6737
        assert priced["invoiced_extended_cents"] == 6822


def test_metal_variance_is_the_summed_delta_between_the_two_variants(api):
    """PRD §3.8: "The order's `metal_variance_cents` is the sum across lines
    of `invoiced_extended_cents` less `quoted_extended_cents`."
    PRD §3.8: "The order-level roll-up is then re-run over the invoiced line
    values in the same pinned six-step sequence — subtotal, gross freight from
    the physical reel count and the branch surcharge, rebate tier on subtotal
    plus gross freight, rebate on the subtotal alone, the inclusive
    free-freight waiver on the post-rebate net, and finally the total —
    writing `invoiced_total_cents`."
    PRD §3.8: "Because the order was invoiced, the customer's
    `open_balance_cents` rises by `invoiced_total_cents` plus
    `deposit_charged_cents`, and their `deposit_liability_cents` rises by
    `deposit_charged_cents`."

    Design: Difficulty/dual_variant_calc/metal_pass_through_quoted_vs_invoiced_on_order_lines
    """
    world = _order_delivered_under_a_later_settlement()

    order = read_order(world["order"]["id"])
    assert order["quoted_total_cents"] == 26974
    assert order["invoiced_total_cents"] == 27144
    assert order["metal_variance_cents"] == 170
    assert order["billing_status"] == "INVOICED"

    account = read_customer(world["customer"]["id"])
    assert account["open_balance_cents"] == 27144
    assert account["credit_status"] == "ACTIVE"


# ══════════════════════════════════════════════════════════════════════════
# The five-link delivery cascade, ending on credit hold
# ══════════════════════════════════════════════════════════════════════════

def _delivery_that_tips_the_customer_over_the_limit():
    """A customer whose credit limit is 27,000 cents takes delivery of an
    order that invoices at 27,008 cents, while a second order sits in
    PENDING_ALLOCATION and a third quote is still ISSUED."""
    branch = create_branch()
    customer = create_customer(
        name="Tightline Electric", credit_limit_cents=27_000
    )
    product = create_product(PRODUCT_P1)
    publish_index("2026-07-30", 450)
    truck = create_truck(branch["id"], truck_code="T-1")
    receive_reel(product["id"], branch["id"], 1000)

    quote_a, _ = build_quote(
        customer["id"], branch["id"], product["id"], [CUT_137, dict(CUT_137)]
    )
    issue_quote(quote_a["id"], issuer="rep-2")
    order_a = convert_quote(quote_a["id"], issuer="rep-2")

    quote_b, _ = build_quote(
        customer["id"], branch["id"], product["id"], [dict(CUT_137)]
    )
    issue_quote(quote_b["id"], issuer="rep-2")
    order_b = convert_quote(quote_b["id"], issuer="rep-2")

    quote_c, _ = build_quote(
        customer["id"], branch["id"], product["id"], [dict(CUT_137)]
    )
    issue_quote(quote_c["id"], issuer="rep-2")

    run_allocator(order_a["id"], branch["id"], policy="MINIMIZE_REMNANT")
    allocations = allocations_of_order(order_a["id"])
    set_clock("2026-08-06T07:00:00Z")
    commit_cut(
        allocations[0]["id"], branch["id"],
        "2026-08-06T08:00:00Z", "2026-08-06T09:00:00Z",
    )
    commit_cut(
        allocations[1]["id"], branch["id"],
        "2026-08-06T10:00:00Z", "2026-08-06T11:00:00Z",
    )
    run = schedule_run(
        order_a["id"], truck["id"], branch["id"],
        "2026-08-07T08:00:00Z", "2026-08-07T10:00:00Z",
    )
    dispatch_run(run["id"], truck["id"])
    mild_move = publish_index("2026-08-03", 460)
    set_clock("2026-08-07T09:00:00Z")
    deliver_run(run["id"], truck["id"])

    return {
        "customer": customer, "run": run, "order_a": order_a,
        "order_b": order_b, "quote_a": quote_a, "quote_b": quote_b,
        "quote_c": quote_c, "mild_move": mild_move, "allocations": allocations,
    }


def test_delivery_invoices_the_order_at_the_delivery_day_settlement(api):
    """PRD §3.8: "**Cascade link 1.** The order moves `STAGED → DELIVERED` on
    its fulfilment axis and its own `delivered_at` is stamped with the same
    instant."
    PRD §3.8: "Because the order was delivered, every allocation on it that is
    `COMMITTED` moves `COMMITTED → CONSUMED`."
    PRD §3.8: "In the same link the order's `billing_status` moves `UNBILLED →
    INVOICED`."
    PRD §3.2: "An index shock exists when two conditions both hold: the new
    entry's `effective_date` is later than the pinned entry's
    `effective_date`, and the deviation is strictly greater than the
    volatility tolerance of three percent."

    Design: Difficulty/transitive_cascade/deliver_run_cascade_depth5_to_credit_hold_quote_void_and_order_hold
    """
    world = _delivery_that_tips_the_customer_over_the_limit()

    assert read_index_entry(world["mild_move"]["id"])["voided_quote_count"] == 0, (
        "a 2.22 percent move is below the tolerance and voids nothing"
    )
    assert read_run(world["run"]["id"])["status"] == "DELIVERED"

    order = read_order(world["order_a"]["id"])
    assert order["fulfillment_status"] == "DELIVERED"
    assert order["billing_status"] == "INVOICED"
    assert order["invoiced_total_cents"] == 27008
    assert order["metal_variance_cents"] == 34
    assert order["deposit_charged_cents"] == 0
    for allocation in world["allocations"]:
        assert read_allocation(allocation["id"])["status"] == "CONSUMED"


def test_the_invoice_tips_the_customer_onto_credit_hold_and_the_hold_cascades(api):
    """PRD §3.8: "**Cascade link 5.** If that recomputation leaves
    `available_credit_cents` below 0 while the customer is `ACTIVE`, the
    customer moves `ACTIVE → CREDIT_HOLD`, and the consequences described in
    Section 3.9 follow within the same request: every one of that customer's
    quotes in `ISSUED` status is voided with `void_reason` `CREDIT_HOLD`, and
    every one of their orders in `PENDING_ALLOCATION` moves to `HELD`."
    PRD §3.9: "Going on hold has two consequences that fire in the same
    request. Every quote of that customer in `ISSUED` status moves to `VOIDED`
    with `void_reason` `CREDIT_HOLD`, and every order of that customer whose
    `fulfillment_status` is `PENDING_ALLOCATION` moves to `HELD`."

    Design: Difficulty/transitive_cascade/deliver_run_cascade_depth5_to_credit_hold_quote_void_and_order_hold
    """
    world = _delivery_that_tips_the_customer_over_the_limit()

    account = read_customer(world["customer"]["id"])
    assert account["open_balance_cents"] == 27008
    assert account["available_credit_cents"] == -8
    assert account["credit_status"] == "CREDIT_HOLD"

    voided = read_quote(world["quote_c"]["id"])
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "CREDIT_HOLD"
    assert read_quote(world["quote_a"]["id"])["status"] == "CONVERTED"
    assert read_quote(world["quote_b"]["id"])["status"] == "CONVERTED"

    held = read_order(world["order_b"]["id"])
    assert held["fulfillment_status"] == "HELD"
    assert held["billing_status"] == "UNBILLED"


# ══════════════════════════════════════════════════════════════════════════
# The index-shock cascade
# ══════════════════════════════════════════════════════════════════════════

def _partially_allocated_order_then_an_index_shock():
    scn = setup_allocated_order(
        [{"put_up": "CUT", "requested_length_ft": 300}],
        reels=[{"nominal_length_ft": 200}],
    )
    scn["shock"] = publish_index("2026-08-03", 500)
    return scn


def test_index_shock_voids_the_quote_and_cancels_its_order(api):
    """PRD §3.2: "**Cascade link 1.** A quote that shocks moves `ISSUED →
    VOIDED`, or `CONVERTED → VOIDED` when the candidate was a converted quote
    whose order is still uncommitted, with `void_reason` set to
    `INDEX_SHOCK`, and the newly published entry's `voided_quote_count` is
    incremented by one for each quote it voids."
    PRD §3.2: "**Cascade link 2.** Because those quotes became `VOIDED`, every
    sales order converted from one of them whose `fulfillment_status` is
    `PENDING_ALLOCATION`, `PARTIALLY_ALLOCATED` or `HELD` moves to
    `CANCELLED`, and its `billing_status` moves from `UNBILLED` to `VOIDED` in
    the same step."

    Design: Difficulty/transitive_cascade/index_shock_publication_cascade_depth3_to_released_reservations
    """
    scn = _partially_allocated_order_then_an_index_shock()

    assert read_index_entry(scn["shock"]["id"])["voided_quote_count"] == 1
    quote = read_quote(scn["quote"]["id"])
    assert quote["status"] == "VOIDED"
    assert quote["void_reason"] == "INDEX_SHOCK"

    order = read_order(scn["order"]["id"])
    assert order["fulfillment_status"] == "CANCELLED"
    assert order["billing_status"] == "VOIDED"


def test_index_shock_releases_the_reservation_back_into_branch_stock(api):
    """PRD §3.2: "**Cascade link 3.** Because those orders became `CANCELLED`,
    every allocation on their lines still in `RESERVED` status moves to
    `RELEASED`, decrementing the holding reel's `allocated_length_ft` by the
    released footage. A reel whose `allocated_length_ft` falls back to 0 as a
    result moves from `ALLOCATED_PARTIAL` back to `IN_STOCK`. No physical
    footage is consumed by this cascade — only reservations are unwound."

    Design: Difficulty/transitive_cascade/index_shock_publication_cascade_depth3_to_released_reservations
    """
    scn = _partially_allocated_order_then_an_index_shock()

    assert read_allocation(scn["allocations"][0]["id"])["status"] == "RELEASED"

    reel = read_reel(scn["reels"][0]["id"])
    assert reel["status"] == "IN_STOCK"
    assert reel["allocated_length_ft"] == 0
    assert reel["current_length_ft"] == 200


# ══════════════════════════════════════════════════════════════════════════
# The admission ladder: state before fiscal
# ══════════════════════════════════════════════════════════════════════════

def _fully_allocated_order_whose_customer_went_on_hold():
    scn = setup_allocated_order(
        [{"put_up": "CUT", "requested_length_ft": 300}],
        reels=[{"nominal_length_ft": 1000}],
        customer_overrides={"credit_limit_cents": 100_000},
    )
    post_credit_adjustment(
        scn["customer"]["id"], delta_open_balance_cents=150_000,
        reason="manual invoice posted",
    )
    return scn


def test_order_not_allocatable_is_reported_before_the_credit_hold(api):
    """PRD §2.7: "Checks are evaluated in the fixed order below; the first
    violated check determines the response, and no later check is evaluated.
    The lowest number wins."
    PRD §2.7: "Transition admissibility. The target resource is in a state
    that admits the requested transition: a quote must be `DRAFT` for line-add
    and issue; `ISSUED` for reprice and convert; an order's
    `fulfillment_status` must be `PENDING_ALLOCATION` or
    `PARTIALLY_ALLOCATED` for the allocation run, and `PARTIALLY_ALLOCATED` or
    `ALLOCATED` for the release; an allocation's `status` must be `RESERVED`
    for cut and pick; a run's `status` must be `SCHEDULED` for dispatch and
    `DISPATCHED` for completion; an order's `fulfillment_status` must be
    `DELIVERED` for a reel return."
    PRD §2.7: "The customer's `credit_status` is `ACTIVE` — otherwise
    `ERR_CUSTOMER_CREDIT_HOLD` (402). This check guards two operations: quote
    conversion and the order allocation run."

    Design: Difficulty/priority_pair_validation_conflict/order_not_allocatable_state_beats_customer_credit_hold_fiscal
    """
    scn = _fully_allocated_order_whose_customer_went_on_hold()
    current_version = read_order(scn["order"]["id"])["version"]

    response = api.allocate_sales_order(
        scn["order"]["id"],
        allocate_payload(current_version),
        make_branch_ops_headers(scn["branch"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ORDER_NOT_ALLOCATABLE.value)
    account = read_customer(scn["customer"]["id"])
    assert account["credit_status"] == "CREDIT_HOLD"
    assert account["available_credit_cents"] == -50000


def test_an_allocated_order_is_not_moved_to_held_by_a_credit_adjustment(api):
    """PRD §3.9: "Going on hold has two consequences that fire in the same
    request. Every quote of that customer in `ISSUED` status moves to `VOIDED`
    with `void_reason` `CREDIT_HOLD`, and every order of that customer whose
    `fulfillment_status` is `PENDING_ALLOCATION` moves to `HELD`."
    PRD §3.9: "A `CreditManager` adjustment can push a customer either way — a
    positive `delta_open_balance_cents` or a negative
    `delta_credit_limit_cents` may put them on hold, while a write-off or a
    limit increase may take them off it — and both directions carry their full
    cascades, the hold direction voiding issued quotes and holding pending
    orders, the release direction returning `HELD` orders to
    `PENDING_ALLOCATION`."

    Design: Difficulty/priority_pair_validation_conflict/order_not_allocatable_state_beats_customer_credit_hold_fiscal
    """
    scn = _fully_allocated_order_whose_customer_went_on_hold()

    assert read_order(scn["order"]["id"])["fulfillment_status"] == "ALLOCATED"
    assert read_reel(scn["reels"][0]["id"])["allocated_length_ft"] == 300
