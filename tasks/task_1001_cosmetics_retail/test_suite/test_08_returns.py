"""Returns: the four creation gates, the denial branch, and the approval cascade."""

from test_helpers import (
    ApiErrorId,
    approve_return,
    assert_lot_counters,
    assert_return_request,
    create_return_request_payload,
    first_sale_line,
    make_customer_headers,
    new_customer,
    read_customer,
    read_lot,
    read_order,
    read_order_line,
    read_return_request,
    request_return,
    set_clock,
    setup_catalog,
    setup_requested_return,
    setup_reserved_order,
    setup_shipped_order,
    setup_suspended_customer,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_LINE_ID = "55555555-5555-4555-8555-555555555555"
UNKNOWN_RETURN_ID = "99999999-9999-4999-8999-999999999999"


def _shipped_forty_thousand_cent_order():
    """An INSIDER customer ships a 40,000-cent SEALED order — which rolls them up to
    VIB and earns 400 points — and files a full-line return."""
    catalog = setup_catalog(
        units_received=5,
        product_overrides={"name": "Palette", "base_price_cents": 40000},
        variant_overrides={"shade_name": "Studio", "shade_code": "ST-01",
                           "finish": "MATTE", "undertone": "NEUTRAL",
                           "depth_index": 6, "price_cents": 40000},
    )
    ctx = setup_shipped_order(catalog=catalog, quantity=1)
    ctx["return_request"] = request_return(ctx["line"]["id"], ctx["customer"]["id"], 1)
    return ctx


# ─── The approval cascade ─────────────────────────────

def test_approved_return_settles_the_refund_and_the_clawback(api, associate_headers):
    """PRD §3.9: "`refund_line_cents` is the line's `line_net_cents` multiplied by the
    returned `quantity`, divided by the line's full `quantity`, and that single quotient
    is rounded half up."
    PRD §3.9: "The cash actually refunded, `refund_cents`, is `refund_line_cents` less
    the tier share less `restocking_fee_cents`. The `points_clawback` is derived from
    that cash: the refunded cents are divided by 100 and truncated down to a whole
    number, that whole number is multiplied by the multiplier belonging to the order's
    `tier_at_reserve`, and the product is truncated down again. And the `disposition` is
    decided by hygiene: `RESTOCK` when the line is `SEALED`, `DESTROY` when it is
    `TESTER_APPLIED`."

    Design: Difficulty/transitive_cascade/approve_return_cascades_refund_spend_clawback_and_rolling_tier
    """
    ctx = _shipped_forty_thousand_cent_order()
    assert ctx["order"]["points_earned"] == 400

    decided = validate_success(
        api.decide_return_request(
            ctx["return_request"]["id"], {"decision": "APPROVE"}, associate_headers
        )
    )

    assert_return_request(decided)
    assert decided["status"] == "APPROVED"
    assert decided["refund_line_cents"] == 40000
    assert decided["restocking_fee_cents"] == 0, "a SEALED line carries no restocking fee"
    assert decided["refund_cents"] == 40000, "an INSIDER order surrendered no tier share"
    assert decided["points_clawback"] == 400, "floor(floor(40000/100) * 1.0)"
    assert decided["disposition"] == "RESTOCK"


def test_approved_return_moves_the_order_the_customer_and_the_lot(
    api, associate_headers
):
    """PRD §3.9: "If it reaches or exceeds `total_due_cents`, `payment_status` becomes
    `REFUNDED` and `refunded_cents` is pinned to exactly `total_due_cents` — the order
    can never be refunded for more than it was charged."
    PRD §3.9: "Because the order absorbed a refund, the customer must give back what
    the refunded cash had bought them: `refund_cents` is subtracted from both
    `qualifying_spend_cents` and `lifetime_spend_cents`, and a ledger entry of type
    `CLAWBACK` is appended carrying the negative of `points_clawback` as its
    `delta_points`, dropping the customer's `points_balance` by the same amount."
    PRD §3.9: "The returned `quantity` leaves the lot's `sold_units`. When the
    `disposition` is `RESTOCK`, the same count is added to `on_hand_units`, becoming
    sellable again."
    PRD §3.9: "And because the customer's qualifying spend just dropped, the tier is
    re-evaluated — in **rolling** mode, which means upgrades only."

    Design: Difficulty/transitive_cascade/approve_return_cascades_refund_spend_clawback_and_rolling_tier
    """
    ctx = _shipped_forty_thousand_cent_order()

    approve_return(ctx["return_request"]["id"])

    order = read_order(ctx["order"]["id"])
    assert order["refunded_cents"] == 40000
    assert order["payment_status"] == "REFUNDED"

    customer = read_customer(ctx["customer"]["id"])
    assert customer["qualifying_spend_cents"] == 0
    assert customer["points_balance"] == 0, "400 earned less a 400-point clawback"
    assert customer["tier"] == "VIB", "rolling mode never downgrades inside the cycle"

    lot = read_lot(ctx["lot"]["id"])
    assert_lot_counters(lot, sold_units=0, on_hand_units=5, destroyed_units=0)
    assert read_order_line(ctx["line"]["id"])["returned_quantity"] == 1


def test_refund_settlement_rounds_once_and_charges_the_restocking_fee(
    api, associate_headers
):
    """PRD §3.9: "The proportional share of the line's value is taken **on the whole
    line and rounded half up exactly once**: `refund_line_cents` is the line's
    `line_net_cents` multiplied by the returned `quantity`, divided by the line's full
    `quantity`, and that single quotient is rounded half up. (Rounding a per-unit price
    first and then multiplying by the quantity gives a different figure and is wrong.)
    The customer only ever paid the discounted price, so the tier discount they enjoyed
    must be surrendered proportionally too: the tier share to withhold is the order's
    `tier_discount_cents` multiplied by `refund_line_cents`, divided by the order's
    `subtotal_cents`, again rounded half up exactly once. Next comes
    `restocking_fee_cents`: for a line whose `hygiene_class` is `SEALED` it is 0, and
    for a line whose `hygiene_class` is `TESTER_APPLIED` it is ten percent of
    `refund_line_cents`, rounded half up."

    A VIB customer buys 3 TESTER_APPLIED units at 999 (subtotal 2997, tier discount 300,
    discounted 2697, 39 points earned) and returns 1:
    refund_line = round_half_up(2997/3) = 999; tier share = round_half_up(300*999/2997)
    = 100; fee = round_half_up(99.9) = 100; refund = 799; clawback =
    floor(floor(799/100) * 1.5) = 10; disposition DESTROY.

    Design: Corner/calculations/refund_settlement_rounds_the_line_share_once_and_applies_restocking_fee
    """
    catalog = setup_catalog(
        units_received=10,
        product_overrides={"name": "Brow Pencil", "hygiene_class": "TESTER_APPLIED",
                           "base_price_cents": 999},
        variant_overrides={"shade_name": "Taupe", "shade_code": "BP-01",
                           "finish": "MATTE", "undertone": "NEUTRAL",
                           "depth_index": 6, "price_cents": 999},
    )
    customer = new_customer(initial_tier="VIB")
    ctx = setup_shipped_order(customer=customer, catalog=catalog, quantity=3)

    assert ctx["order"]["subtotal_cents"] == 2997
    assert ctx["order"]["tier_discount_cents"] == 300
    assert ctx["order"]["discounted_subtotal_cents"] == 2697
    assert ctx["order"]["points_earned"] == 39

    rr = request_return(ctx["line"]["id"], customer["id"], 1, reason="WRONG_SHADE")
    decided = validate_success(
        api.decide_return_request(rr["id"], {"decision": "APPROVE"}, associate_headers)
    )

    assert decided["refund_line_cents"] == 999
    assert decided["restocking_fee_cents"] == 100, "round_half_up(999 * 0.10)"
    assert decided["refund_cents"] == 799, "999 less the 100 tier share less the 100 fee"
    assert decided["points_clawback"] == 10, "floor(floor(799/100) * 1.5)"
    assert decided["disposition"] == "DESTROY"

    assert read_customer(customer["id"])["points_balance"] == 29, "39 earned less 10"

    order = read_order(ctx["order"]["id"])
    assert order["refunded_cents"] == 799
    assert order["payment_status"] == "PARTIALLY_REFUNDED", "799 falls short of 2697"

    lot = read_lot(catalog["lot"]["id"])
    assert_lot_counters(lot, sold_units=2, destroyed_units=1, on_hand_units=7)
    assert read_order_line(ctx["line"]["id"])["returned_quantity"] == 1


# ─── The denial branch ────────────────────────────────

def test_hygiene_violation_denial_strikes_without_moving_money(api, associate_headers):
    """PRD §3.9: "A `decision` of `DENY` requires a `deny_reason` — one of
    `HYGIENE_VIOLATION`, `NOT_AS_DESCRIBED` or `OUT_OF_POLICY` — and the request moves
    to `DENIED`. No cash moves, no points move, no inventory moves. But a `deny_reason`
    of `HYGIENE_VIOLATION` is a black mark: the customer's `hygiene_strikes` counter
    increments by one, and once `hygiene_strikes` stands at 3 or more, their
    `return_privilege` flips to `SUSPENDED` — which is exactly the gate that will refuse
    their next request."

    Design: Corner/state_machines/deny_return_with_hygiene_violation_increments_strikes_without_refunding
    """
    ctx = setup_requested_return(quantity=2, return_quantity=1)

    decided = validate_success(
        api.decide_return_request(
            ctx["return_request"]["id"],
            {"decision": "DENY", "deny_reason": "HYGIENE_VIOLATION"},
            associate_headers,
        )
    )
    assert decided["status"] == "DENIED"

    customer = read_customer(ctx["customer"]["id"])
    assert customer["hygiene_strikes"] == 1
    assert customer["return_privilege"] == "ACTIVE", "one strike is not yet three"

    order = read_order(ctx["order"]["id"])
    assert order["refunded_cents"] == 0, "no cash moves on a denial"
    assert order["payment_status"] == "CAPTURED"

    lot = read_lot(ctx["lot"]["id"])
    assert_lot_counters(lot, sold_units=2, on_hand_units=8, destroyed_units=0)
    assert read_order_line(ctx["line"]["id"])["returned_quantity"] == 0


def test_three_hygiene_strikes_suspend_the_return_privilege(api, admin_headers):
    """PRD §3.9: "First, the customer's `return_privilege` must be `ACTIVE`; a customer
    whose privilege has been `SUSPENDED` cannot open a new request at all, and is
    refused with `ERR_RETURN_PRIVILEGE_SUSPENDED` (HTTP 403)."
    PRD §3.9: "But a `deny_reason` of `HYGIENE_VIOLATION` is a black mark: the
    customer's `hygiene_strikes` counter increments by one, and once `hygiene_strikes`
    stands at 3 or more, their `return_privilege` flips to `SUSPENDED` — which is
    exactly the gate that will refuse their next request."

    Design: Corner/validations/return_privilege_suspended_after_three_hygiene_strikes
    """
    ctx = setup_suspended_customer(strikes=3)
    customer = ctx["customer"]

    assert customer["hygiene_strikes"] == 3
    assert customer["return_privilege"] == "SUSPENDED"

    resp = api.create_return_request(
        create_return_request_payload(ctx["line"]["id"], 1, reason="CHANGED_MIND"),
        make_customer_headers(customer["id"]),
    )

    validate_error(resp, ApiErrorId.ERR_RETURN_PRIVILEGE_SUSPENDED.value)

    listed, meta = validate_paginated(
        api.list_return_requests(
            admin_headers, params={"order_line_id": ctx["line"]["id"]}
        )
    )
    assert meta["total_count"] == 3, "only the three denied requests exist"
    assert all(r["status"] == "DENIED" for r in listed)


# ─── The four creation gates ──────────────────────────

def test_direct_contact_return_reports_hygiene_before_the_window(api):
    """PRD §3.9: "Four gates sit in front of the request, and they are checked in this
    order. First, the customer's `return_privilege` must be `ACTIVE`; a customer whose
    privilege has been `SUSPENDED` cannot open a new request at all, and is refused with
    `ERR_RETURN_PRIVILEGE_SUSPENDED` (HTTP 403). Second, the line's snapshotted
    `hygiene_class` must not be `DIRECT_CONTACT` — a direct-contact good is never
    returnable, and the refusal is `ERR_HYGIENE_NON_RETURNABLE` (HTTP 422). Third, the
    return window must still be open: the logical clock must be no later than thirty days
    after the owning order's `fulfilled_at`, and a request beyond that is
    `ERR_RETURN_WINDOW_EXPIRED` (HTTP 422)."

    A return filed 46 days after fulfilment against a DIRECT_CONTACT line breaches both
    the hygiene gate and the window gate; hygiene is checked first, so it is the one
    reported.

    Design: Difficulty/priority_pair_validation_conflict/direct_contact_return_after_window_returns_hygiene_error_not_window_error
    """
    set_clock("2026-05-05T00:00:00Z")
    catalog = setup_catalog(
        units_received=5,
        product_overrides={"name": "Lip Wand", "hygiene_class": "DIRECT_CONTACT",
                           "base_price_cents": 3000},
        variant_overrides={"shade_name": "Berry", "shade_code": "BR-01",
                           "finish": "MATTE", "undertone": "COOL",
                           "depth_index": 7, "price_cents": 3000},
    )
    ctx = setup_shipped_order(catalog=catalog, quantity=1)
    set_clock("2026-06-20T00:00:00Z")  # 46 days past fulfilment

    resp = api.create_return_request(
        create_return_request_payload(ctx["line"]["id"], 1, reason="CHANGED_MIND"),
        make_customer_headers(ctx["customer"]["id"]),
    )

    error = validate_error(resp, ApiErrorId.ERR_HYGIENE_NON_RETURNABLE.value)
    assert error["error_id"] != ApiErrorId.ERR_RETURN_WINDOW_EXPIRED.value


def test_direct_contact_return_creates_no_return_request(api, admin_headers):
    """PRD §2.10: "`DIRECT_CONTACT` is an absolute bar on both policies. A tester
    conversion against a lot whose product is `DIRECT_CONTACT` is rejected with
    `ERR_TESTER_NOT_ALLOWED` (HTTP 422), and a return request against a line whose
    product was `DIRECT_CONTACT` is rejected with `ERR_HYGIENE_NON_RETURNABLE` (HTTP
    422). Because a `DIRECT_CONTACT` line can never reach an approval decision, no
    refund disposition is ever computed for one."

    Design: Difficulty/priority_pair_validation_conflict/direct_contact_return_after_window_returns_hygiene_error_not_window_error
    """
    set_clock("2026-05-05T00:00:00Z")
    catalog = setup_catalog(
        units_received=5,
        product_overrides={"name": "Lip Wand", "hygiene_class": "DIRECT_CONTACT",
                           "base_price_cents": 3000},
        variant_overrides={"shade_name": "Berry", "shade_code": "BR-01",
                           "finish": "MATTE", "undertone": "COOL",
                           "depth_index": 7, "price_cents": 3000},
    )
    ctx = setup_shipped_order(catalog=catalog, quantity=1)
    set_clock("2026-06-20T00:00:00Z")

    validate_error(
        api.create_return_request(
            create_return_request_payload(ctx["line"]["id"], 1, reason="CHANGED_MIND"),
            make_customer_headers(ctx["customer"]["id"]),
        ),
        ApiErrorId.ERR_HYGIENE_NON_RETURNABLE.value,
    )

    listed, meta = validate_paginated(
        api.list_return_requests(
            admin_headers, params={"order_line_id": ctx["line"]["id"]}
        )
    )
    assert meta["total_count"] == 0, "no ReturnRequest row was created"
    assert listed == []


def test_return_after_the_thirty_day_window_is_rejected(api):
    """PRD §3.9: "Third, the return window must still be open: the logical clock must
    be no later than thirty days after the owning order's `fulfilled_at`, and a request
    beyond that is `ERR_RETURN_WINDOW_EXPIRED` (HTTP 422)."
    PRD §3.7: "The order's `fulfilled_at` is stamped with the current logical-clock
    instant, which is what the return window will later be measured from."

    A SEALED line clears the hygiene gate, so the temporal gate surfaces on its own:
    fulfilled at 2026-05-05, a request at 2026-06-06 is 32 days late.

    Design: Corner/validations/return_of_a_sealed_line_after_thirty_days_returns_window_expired
    """
    set_clock("2026-05-05T00:00:00Z")
    ctx = setup_shipped_order(quantity=1)
    assert ctx["order"]["fulfilled_at"].startswith("2026-05-05T00:00:00")

    set_clock("2026-06-06T00:00:00Z")

    resp = api.create_return_request(
        create_return_request_payload(ctx["line"]["id"], 1, reason="CHANGED_MIND"),
        make_customer_headers(ctx["customer"]["id"]),
    )

    validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_EXPIRED.value)


def test_return_beyond_the_remaining_line_quantity_is_rejected(api):
    """PRD §3.9: "Fourth, the units must exist to be returned: the line's
    `returned_quantity` plus the newly requested `quantity` must not exceed the line's
    original `quantity`, and an over-return is `ERR_RETURN_QUANTITY_EXCEEDS_LINE` (HTTP
    422)."

    Design: Corner/validations/return_quantity_beyond_the_line_returns_quantity_exceeds_line
    """
    ctx = setup_requested_return(quantity=2, return_quantity=1)
    approve_return(ctx["return_request"]["id"])
    assert read_order_line(ctx["line"]["id"])["returned_quantity"] == 1

    resp = api.create_return_request(
        create_return_request_payload(ctx["line"]["id"], 2, reason="CHANGED_MIND"),
        make_customer_headers(ctx["customer"]["id"]),
    )

    validate_error(resp, ApiErrorId.ERR_RETURN_QUANTITY_EXCEEDS_LINE.value)
    assert read_order_line(ctx["line"]["id"])["returned_quantity"] == 1


def test_return_before_fulfilment_is_rejected(api):
    """PRD §2.9: "7. State — the target resource is in a state from which the requested
    transition is declared. Order actions (line addition, reserve, payment, fulfilment,
    cancel) report `ERR_INVALID_ORDER_STATE`; booking actions report
    `ERR_INVALID_BOOKING_STATE`; return creation and return decisions report
    `ERR_INVALID_RETURN_STATE`. All are HTTP 409."
    PRD §3.9: "Third, the return window must still be open: the logical clock must be
    no later than thirty days after the owning order's `fulfilled_at`, and a request
    beyond that is `ERR_RETURN_WINDOW_EXPIRED` (HTTP 422)."

    A merely RESERVED order has never been fulfilled, so no line of it is in a state
    from which a return may be raised.

    Design: Corner/validations/return_before_fulfilment_returns_invalid_return_state
    """
    ctx = setup_reserved_order(quantity=1)
    order_line = first_sale_line(ctx["order"]["id"])

    resp = api.create_return_request(
        create_return_request_payload(order_line["id"], 1, reason="CHANGED_MIND"),
        make_customer_headers(ctx["customer"]["id"]),
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_RETURN_STATE.value)


def test_deciding_an_already_approved_return_is_rejected(api, associate_headers):
    """PRD §3.9: "The request opens in `REQUESTED` and is decided exactly once, ending
    either `APPROVED` or `DENIED`."
    PRD §2.9: "7. State — the target resource is in a state from which the requested
    transition is declared. Order actions (line addition, reserve, payment, fulfilment,
    cancel) report `ERR_INVALID_ORDER_STATE`; booking actions report
    `ERR_INVALID_BOOKING_STATE`; return creation and return decisions report
    `ERR_INVALID_RETURN_STATE`. All are HTTP 409."

    Design: Corner/validations/deciding_an_already_decided_return_returns_invalid_return_state
    """
    ctx = setup_requested_return(quantity=1, return_quantity=1)
    approve_return(ctx["return_request"]["id"])
    assert read_order(ctx["order"]["id"])["refunded_cents"] == 2500

    resp = api.decide_return_request(
        ctx["return_request"]["id"], {"decision": "APPROVE"}, associate_headers
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_RETURN_STATE.value)

    assert read_order(ctx["order"]["id"])["refunded_cents"] == 2500, "not refunded twice"
    assert read_return_request(ctx["return_request"]["id"])["status"] == "APPROVED"
    lot = read_lot(ctx["lot"]["id"])
    assert_lot_counters(lot, on_hand_units=10, sold_units=0, destroyed_units=0)


# ─── Existence on the return surface ──────────────────

def test_return_with_an_unknown_order_line_returns_order_line_not_found(api):
    """PRD §2.9: "5. Body-reference existence — every foreign key inside the request
    body resolves to an existing row, reported with the same 404 family as step 3
    (`ERR_STORE_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_ARTIST_NOT_FOUND`). This
    applies to order creation, line addition, inventory-lot creation, service-booking
    creation, return-request creation and promotion creation."

    Body-reference existence is step 5 and so runs before the §3.9 hygiene, window and
    privilege gates.

    Design: Corner/errors/error_order_line_not_found_on_return_with_unknown_line
    """
    customer = new_customer()

    resp = api.create_return_request(
        create_return_request_payload(UNKNOWN_LINE_ID, 1, reason="DAMAGED"),
        make_customer_headers(customer["id"]),
    )

    validate_error(resp, ApiErrorId.ERR_ORDER_LINE_NOT_FOUND.value)


def test_decision_on_an_unknown_return_returns_return_not_found(api, associate_headers):
    """PRD §2.11: "The same discipline applies to every action hung off an order, a
    lot, a booking or a return request: the parent named in the path must exist before
    any body field, any state rule or any business rule is considered."
    PRD §2.9: "3. Path existence — every resource named in the URL path exists, checked
    left to right, so that the leftmost missing identifier is the one reported."

    Design: Corner/errors/error_return_not_found_on_decision_with_unknown_return
    """
    resp = api.decide_return_request(
        UNKNOWN_RETURN_ID, {"decision": "APPROVE"}, associate_headers
    )

    validate_error(resp, ApiErrorId.ERR_RETURN_NOT_FOUND.value)
