"""The two order dimensions, points accrual, and the two tier-evaluation modes."""

from test_helpers import (
    ApiErrorId,
    add_line_payload,
    approve_return,
    assert_ledger_entry_sequence,
    assert_points_ledger_conserved,
    line,
    new_customer,
    new_lot,
    new_product,
    new_store,
    new_variant,
    read_customer,
    read_ledger,
    read_lines,
    read_order,
    request_return,
    setup_catalog,
    setup_reserved_order,
    setup_shipped_order,
    validate_error,
    validate_success,
)

SLOT_14 = "2026-06-05T14:00:00Z"


# ─── Parallel state dimensions on the same record ─────

def test_payment_dimension_advances_without_touching_fulfilment(api, associate_headers):
    """PRD §3.7: "An order carries **two independent state dimensions on the same
    record**, and they evolve separately while guarding each other."
    PRD §3.7: "`AUTHORIZE` takes `payment_status` from `UNPAID` to `AUTHORIZED`, and is
    permitted only while `fulfillment_status` is `RESERVED`."
    PRD §3.7: "`MARK_READY` takes a `BOPIS` order from `RESERVED` to
    `READY_FOR_PICKUP`, and requires that payment be at least authorised —
    `payment_status` must be `AUTHORIZED` or `CAPTURED`."

    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_dimensions_advance_independently
    """
    ctx = setup_reserved_order(
        quantity=1, channel="BOPIS", pickup_slot_start=SLOT_14
    )
    order_id = ctx["order"]["id"]

    after_auth = validate_success(api.pay_order(order_id, "AUTHORIZE", associate_headers))
    assert after_auth["payment_status"] == "AUTHORIZED"
    assert after_auth["fulfillment_status"] == "RESERVED", (
        "advancing payment must not move the fulfilment dimension"
    )

    after_ready = validate_success(
        api.fulfill_order(order_id, "MARK_READY", associate_headers)
    )
    assert after_ready["fulfillment_status"] == "READY_FOR_PICKUP"
    assert after_ready["payment_status"] == "AUTHORIZED", (
        "advancing fulfilment must not move the payment dimension"
    )


def test_hand_over_is_blocked_by_the_other_dimension(api, associate_headers):
    """PRD §3.7: "`HAND_OVER` takes a `BOPIS` order from `READY_FOR_PICKUP` to
    `PICKED_UP` and demands full payment: `payment_status` must be `CAPTURED`. `SHIP`
    takes a `SHIP_FROM_STORE` order from `RESERVED` straight to `SHIPPED`, and likewise
    demands `CAPTURED`. Attempting hand-over or shipment before capture is
    `ERR_PAYMENT_NOT_CAPTURED` (HTTP 409)."

    READY_FOR_PICKUP is a perfectly legal from-state for HAND_OVER; the call is
    refused purely by the *other* dimension, which is still only AUTHORIZED.

    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_dimensions_advance_independently
    """
    ctx = setup_reserved_order(
        quantity=1, channel="BOPIS", pickup_slot_start=SLOT_14
    )
    order_id = ctx["order"]["id"]
    validate_success(api.pay_order(order_id, "AUTHORIZE", associate_headers))
    validate_success(api.fulfill_order(order_id, "MARK_READY", associate_headers))

    resp = api.fulfill_order(order_id, "HAND_OVER", associate_headers)

    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_CAPTURED.value)

    after = read_order(order_id)
    assert after["fulfillment_status"] == "READY_FOR_PICKUP", (
        "the blocked hand-over changed nothing"
    )
    assert after["payment_status"] == "AUTHORIZED"


# ─── Validation precedence: state before the fiscal rule ──

def test_hand_over_from_reserved_and_unpaid_reports_the_state_error(
    api, associate_headers
):
    """PRD §2.9: "When more than one rule could reject a request, the rules are
    evaluated in a fixed order and the *first* failure is the one reported."
    PRD §2.9: "7. State — the target resource is in a state from which the requested
    transition is declared. Order actions (line addition, reserve, payment, fulfilment,
    cancel) report `ERR_INVALID_ORDER_STATE`; booking actions report
    `ERR_INVALID_BOOKING_STATE`; return creation and return decisions report
    `ERR_INVALID_RETURN_STATE`. All are HTTP 409."
    PRD §2.9: "Everything else — the business rules of §3 — is evaluated after these
    eight, and §3 states the relative ordering wherever two business rules could both
    fire on the same request."
    PRD §3.7: "`HAND_OVER` takes a `BOPIS` order from `READY_FOR_PICKUP` to
    `PICKED_UP` and demands full payment: `payment_status` must be `CAPTURED`."

    A HAND_OVER on an order that is RESERVED *and* still UNPAID breaches both rules;
    the state check is step 7 and the payment rule is a §3 business rule, so the state
    error is the one reported.

    Design: Difficulty/priority_pair_validation_conflict/hand_over_from_reserved_and_unpaid_returns_invalid_order_state
    """
    ctx = setup_reserved_order(
        quantity=1, channel="BOPIS", pickup_slot_start=SLOT_14
    )

    resp = api.fulfill_order(ctx["order"]["id"], "HAND_OVER", associate_headers)

    error = validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE.value)
    assert error["error_id"] != ApiErrorId.ERR_PAYMENT_NOT_CAPTURED.value


def test_the_blocked_hand_over_leaves_both_dimensions_untouched(api, associate_headers):
    """PRD §2.9: "When more than one rule could reject a request, the rules are
    evaluated in a fixed order and the *first* failure is the one reported."
    PRD §3.7: "`fulfillment_status` runs `DRAFT`, `RESERVED`, `READY_FOR_PICKUP`,
    `PICKED_UP`, `SHIPPED` and `CANCELLED`, with `PICKED_UP`, `SHIPPED` and `CANCELLED`
    terminal. `payment_status` runs `UNPAID`, `AUTHORIZED`, `CAPTURED`,
    `PARTIALLY_REFUNDED`, `REFUNDED` and `VOIDED`, with `REFUNDED` and `VOIDED`
    terminal."

    Design: Difficulty/priority_pair_validation_conflict/hand_over_from_reserved_and_unpaid_returns_invalid_order_state
    """
    ctx = setup_reserved_order(
        quantity=1, channel="BOPIS", pickup_slot_start=SLOT_14
    )

    validate_error(
        api.fulfill_order(ctx["order"]["id"], "HAND_OVER", associate_headers),
        ApiErrorId.ERR_INVALID_ORDER_STATE.value,
    )

    after = read_order(ctx["order"]["id"])
    assert after["fulfillment_status"] == "RESERVED"
    assert after["payment_status"] == "UNPAID"
    assert after["fulfilled_at"] is None, "a rejected hand-over stamps nothing"


# ─── Points accrual ───────────────────────────────────

def _skincare_basket_shipped(api, associate_headers):
    """A VIB customer ships an order carrying a 6000-cent SKINCARE line and a
    2000-cent MAKEUP line. Returns (customer, order after SHIP)."""
    store = new_store(name="SEP-TX", region_code="TX")
    skincare = new_product(
        name="Repair Serum", category="SKINCARE", base_price_cents=6000
    )
    v_skin = new_variant(
        skincare["id"], shade_name="Serum 30ml", shade_code="SR-30", finish="DEWY",
        undertone="NEUTRAL", depth_index=6, price_cents=6000,
    )
    makeup = new_product(name="Blush", category="MAKEUP", base_price_cents=2000)
    v_makeup = new_variant(
        makeup["id"], shade_name="Peach", shade_code="PC-01", finish="SATIN",
        undertone="WARM", depth_index=5, price_cents=2000,
    )
    new_lot(store["id"], v_skin["id"], units_received=5)
    new_lot(store["id"], v_makeup["id"], units_received=5)
    customer = new_customer(initial_tier="VIB")

    order = validate_success(
        api.create_order(
            {
                "customer_id": customer["id"], "store_id": store["id"],
                "channel": "SHIP_FROM_STORE",
                "lines": [line(v_skin["id"], 1), line(v_makeup["id"], 1)],
            },
            associate_headers,
        ),
        201,
    )
    validate_success(api.reserve_order(order["id"], associate_headers))
    validate_success(api.pay_order(order["id"], "AUTHORIZE", associate_headers))
    validate_success(api.pay_order(order["id"], "CAPTURE", associate_headers))
    shipped = validate_success(
        api.fulfill_order(order["id"], "SHIP", associate_headers)
    )
    return customer, shipped


def test_points_accrual_applies_floors_multiplier_and_skincare_bonus(
    api, associate_headers
):
    """PRD §3.7: "That base is divided by 100 and truncated down to a whole number,
    giving the base points — 100 cents earns one point, and the remainder is discarded.
    The base points are then multiplied by the multiplier belonging to
    `tier_at_reserve` — one times for `INSIDER`, one-and-a-half times for `VIB`, twice
    for `ROUGE` — and the product is again truncated down to a whole number."
    PRD §3.7: "On top of that, a skincare bonus of 50 points is added if **any** sale
    line on the order names a product in the `SKINCARE` category **and** that same
    line's `line_net_cents` is at least 5,000 cents (fifty dollars); the bonus is a
    flat 50 points and is awarded at most once per order, however many qualifying lines
    there are."
    PRD §3.7: "The sum of the multiplied base points and the skincare bonus is finally
    capped: an order can never award more than 5,000 points, and `points_earned` is the
    smaller of the computed sum and that ceiling."

    subtotal 8000 -> VIB discount 800 -> discounted 7200 -> total_due 7200.
    floor(7200/100) = 72; floor(72 * 1.5) = 108; + 50 skincare bonus = 158; under the
    5000 cap.

    Design: Difficulty/combinatorial_formula/points_accrual_nested_floor_multiplier_bonus_and_cap
    """
    customer, shipped = _skincare_basket_shipped(api, associate_headers)

    assert shipped["subtotal_cents"] == 8000
    assert shipped["tier_discount_cents"] == 800, "ten percent for a VIB"
    assert shipped["total_due_cents"] == 7200
    assert shipped["tier_at_reserve"] == "VIB"
    assert shipped["points_earned"] == 158, (
        f"floor(floor(7200/100) * 1.5) + 50 == 158; got {shipped['points_earned']}"
    )
    assert read_customer(customer["id"])["points_balance"] == 158


def test_points_accrual_writes_a_single_earn_ledger_entry(api, associate_headers):
    """PRD §3.7: "The accrual calculation runs, writing `points_earned` onto the order;
    a ledger entry of type `EARN` is appended with that many points as its
    `delta_points`, and the customer's `points_balance` rises by the same amount."
    PRD §2.7: "There is no way to move a balance except by appending an entry, and
    every entry records `balance_after` — the customer's `points_balance` immediately
    after that entry was appended — so the ledger is self-auditing."

    Design: Difficulty/combinatorial_formula/points_accrual_nested_floor_multiplier_bonus_and_cap
    """
    customer, shipped = _skincare_basket_shipped(api, associate_headers)

    entries = read_ledger(customer["id"])
    assert_ledger_entry_sequence(entries, [("EARN", 158)])
    assert entries[0]["balance_after"] == 158
    assert entries[0]["order_id"] == shipped["id"]

    assert_points_ledger_conserved(read_customer(customer["id"]), entries)


def test_tier_upgrade_fires_at_exactly_the_vib_threshold(api, associate_headers):
    """PRD §3.4: "The target tier for any spend figure is `ROUGE` when the spend is at
    least 100,000 cents — one thousand dollars — `VIB` when it is at least 35,000 cents
    and short of the ROUGE line, and `INSIDER` otherwise. Both thresholds are
    inclusive: a customer sitting at exactly 35,000 cents *is* a `VIB`, and one at
    exactly 100,000 cents *is* a `ROUGE`."
    PRD §3.7: "The base points are then multiplied by the multiplier belonging to
    `tier_at_reserve` — one times for `INSIDER`, one-and-a-half times for `VIB`, twice
    for `ROUGE` — and the product is again truncated down to a whole number. Note that
    this is the tier the order was reserved at, *not* the tier the order itself may
    have just unlocked."

    Design: Corner/calculations/tier_threshold_fires_at_exactly_35000_qualifying_spend
    """
    catalog = setup_catalog(
        units_received=5,
        product_overrides={"name": "Gift Set", "base_price_cents": 35000},
        variant_overrides={"shade_name": "Set", "shade_code": "GS-01",
                           "finish": "SATIN", "undertone": "NEUTRAL",
                           "depth_index": 6, "price_cents": 35000},
    )
    ctx = setup_shipped_order(catalog=catalog, quantity=1)
    order, customer = ctx["order"], ctx["customer"]

    assert order["tier_at_reserve"] == "INSIDER"
    assert order["total_due_cents"] == 35000
    assert order["points_earned"] == 350, (
        "the multiplier is 1.0 from tier_at_reserve, not the 1.5 this order just unlocked"
    )

    after = read_customer(customer["id"])
    assert after["qualifying_spend_cents"] == 35000
    assert after["tier"] == "VIB", "the 35,000-cent threshold is inclusive"


# ─── The two tier-evaluation modes ────────────────────

def _vib_customer_after_full_refund(api, associate_headers):
    """Ship a 40,000-cent order (upgrading the customer to VIB), then return the whole
    line and approve it — driving qualifying_spend_cents back to 0."""
    catalog = setup_catalog(
        units_received=5,
        product_overrides={"name": "Palette", "base_price_cents": 40000},
        variant_overrides={"shade_name": "Studio", "shade_code": "ST-01",
                           "finish": "MATTE", "undertone": "NEUTRAL",
                           "depth_index": 6, "price_cents": 40000},
    )
    ctx = setup_shipped_order(catalog=catalog, quantity=1)
    rr = request_return(ctx["line"]["id"], ctx["customer"]["id"], 1)
    approve_return(rr["id"])
    return ctx["customer"]


def test_rolling_evaluation_keeps_the_tier_after_a_full_refund(api, associate_headers):
    """PRD §3.4: "It is monotone: it compares the target tier for the customer's
    current `qualifying_spend_cents` against the customer's present tier by rank, and
    it writes the new tier **only when the target ranks strictly higher**. A tier, once
    earned, is sticky for the remainder of the cycle — a refund that drags
    `qualifying_spend_cents` back below the threshold never claws the tier back."
    PRD §3.9: "And because the customer's qualifying spend just dropped, the tier is
    re-evaluated — in **rolling** mode, which means upgrades only."

    Design: Difficulty/dual_variant_calc/tier_evaluation_rolling_keeps_vib_checkpoint_downgrades_to_insider
    """
    customer = _vib_customer_after_full_refund(api, associate_headers)

    after = read_customer(customer["id"])
    assert after["qualifying_spend_cents"] == 0, "the refund wiped the cycle spend"
    assert after["tier"] == "VIB", (
        "rolling mode refuses to downgrade, even at zero qualifying spend"
    )
    assert after["points_balance"] == 0, "400 EARN points less a 400-point CLAWBACK"


def test_checkpoint_downgrades_the_same_spend_figure_to_insider(api, admin_headers):
    """PRD §3.4: "The **checkpoint** mode runs only when a `MerchandisingAdmin`
    explicitly closes the cycle. It re-derives the tier from exactly the same
    `qualifying_spend_cents` figure using exactly the same thresholds, but it writes the
    result unconditionally, so it *does* downgrade: a `ROUGE` customer who ended the
    cycle between 35,000 and 100,000 cents (at least 35,000 and strictly below 100,000)
    becomes `VIB`; a `ROUGE` or a `VIB` customer who ended below 35,000 cents becomes
    `INSIDER`."
    PRD §3.4: "Having re-derived the tier, the checkpoint zeroes `qualifying_spend_cents`
    and stamps `cycle_started_at` with the current logical-clock instant, and the
    customer's `version` increments."

    The same qualifying_spend_cents of 0 that rolling mode left at VIB is re-derived by
    the checkpoint into INSIDER — same input field, opposite tier.

    Design: Difficulty/dual_variant_calc/tier_evaluation_rolling_keeps_vib_checkpoint_downgrades_to_insider
    """
    customer = _vib_customer_after_full_refund(api, admin_headers)

    before = read_customer(customer["id"])
    assert before["tier"] == "VIB" and before["qualifying_spend_cents"] == 0

    after = validate_success(api.tier_checkpoint(customer["id"], admin_headers))

    assert after["tier"] == "INSIDER", "the checkpoint downgrades where rolling would not"
    assert after["qualifying_spend_cents"] == 0, "the checkpoint zeroes the cycle spend"
    assert after["points_balance"] == 0


def test_add_line_to_a_reserved_order_is_rejected(api, associate_headers):
    """PRD §3.5: "A line may only be added to a `DRAFT` order — an attempt against an
    order in any other fulfilment state is `ERR_INVALID_ORDER_STATE` — and it may not
    name a `DISCONTINUED` variant, which fails with `ERR_VARIANT_NOT_SELLABLE`."

    The supplied `expected_order_version` is in fact current, so the OCC check (step 8)
    could not have fired: the state check at step 7 is what rejects this.

    Design: Corner/state_machines/add_line_to_a_reserved_order_returns_invalid_order_state
    """
    ctx = setup_reserved_order(quantity=1)
    order, variant = ctx["order"], ctx["variant"]

    resp = api.add_order_line(
        order["id"],
        add_line_payload(variant["id"], 1, order["version"]),
        associate_headers,
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE.value)
    assert len(read_lines(order["id"])) == 1, "the order still has exactly one line"
