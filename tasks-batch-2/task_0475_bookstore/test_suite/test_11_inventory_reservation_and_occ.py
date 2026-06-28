"""Inventory reservation under a finite stock quota, optimistic-concurrency on
reserve, the owner-check precedence on pay, and the credit-redemption guard."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_member_headers,
    create_sales_order_payload, create_order_line_payload,
    make_member, make_title, receive_stock,
    setup_order_with_line,
)

BOOKSELLER = TEST_USERS["bookseller_headers"]
ADMIN = TEST_USERS["store_admin_headers"]


def test_reserve_succeeds_with_live_version_and_bumps_version(api):
    """PRD §3.5: "the request must carry `expected_sales_order_version` matching
    the order's current `version`". And: "increments the order's `version`".

    Design: Corner/cross_cutting_complexity_layers/occ_reserve_correct_version_succeeds_increments
    """
    member = make_member()
    title = make_title(list_price_cents=1000)
    receive_stock(title["id"], 1)
    mh = make_member_headers(member["id"])
    order = validate_success(
        api.create_sales_order(create_sales_order_payload(member["id"]), mh),
        expected_status=201,
    )
    api.create_order_line(order["id"], create_order_line_payload(title["id"], 1), mh)
    current = validate_success(api.get_sales_order(order["id"], BOOKSELLER))
    v_cur = current["version"]
    reserved = validate_success(
        api.reserve_order(order["id"],
                          {"expected_sales_order_version": v_cur}, BOOKSELLER)
    )
    assert reserved["fulfillment_status"] == "RESERVED"
    assert reserved["version"] == v_cur + 1


def test_reserve_depletes_pool_blocking_second_order(api):
    """PRD §3.5: "Reservation is allowed only when the order is `OPEN` and only
    when, for every order line, the line's `Title.on_hand_qty` (its count of
    `AVAILABLE` copies) is at least the line's `quantity`; if any line cannot be
    covered the reserve is rejected with `ERR_INSUFFICIENT_STOCK` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/stock_reservation_exhaustion_on_title_quota
    """
    member = make_member()
    title = make_title(list_price_cents=1000)
    receive_stock(title["id"], 2)
    mh = make_member_headers(member["id"])
    # O1 reserves both copies.
    o1 = validate_success(
        api.create_sales_order(create_sales_order_payload(member["id"]), mh),
        expected_status=201,
    )
    api.create_order_line(o1["id"], create_order_line_payload(title["id"], 2), mh)
    validate_success(
        api.reserve_order(o1["id"],
                          {"expected_sales_order_version": o1["version"]}, BOOKSELLER)
    )
    # O2 needs 1 but pool is depleted to 0.
    o2 = validate_success(
        api.create_sales_order(create_sales_order_payload(member["id"]), mh),
        expected_status=201,
    )
    api.create_order_line(o2["id"], create_order_line_payload(title["id"], 1), mh)
    resp = api.reserve_order(
        o2["id"], {"expected_sales_order_version": o2["version"]}, BOOKSELLER
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)


def test_reserve_insufficient_stock_when_quantity_exceeds_pool(api):
    """PRD §3.5: "if any line cannot be covered the reserve is rejected with
    `ERR_INSUFFICIENT_STOCK` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/stock_reservation_exhaustion_on_title_quota
    """
    member = make_member()
    title = make_title(list_price_cents=1000)
    receive_stock(title["id"], 1)  # only 1 AVAILABLE
    mh = make_member_headers(member["id"])
    order = validate_success(
        api.create_sales_order(create_sales_order_payload(member["id"]), mh),
        expected_status=201,
    )
    api.create_order_line(order["id"], create_order_line_payload(title["id"], 2), mh)
    resp = api.reserve_order(
        order["id"], {"expected_sales_order_version": order["version"]}, BOOKSELLER
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)


def test_pay_by_non_owner_member_rejected_owner_check(api):
    """PRD §2.1: "a `Member` may only act on a sales order, event ticket, buyback
    transaction, or special order whose `member_id` equals their `X-User-ID`; a
    violation is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §2.5: "For a `Member` acting on a specific resource, resource ownership is
    checked next (`ERR_NOT_RESOURCE_OWNER`, 403). ... Domain-specific business
    validations follow".

    Design: Difficulty/priority_pair_validation_conflict/pay_owner_check_beats_insufficient_credit
    """
    owner = make_member()
    intruder = make_member()
    title = make_title(list_price_cents=1000)
    owner_h = make_member_headers(owner["id"])
    order = validate_success(
        api.create_sales_order(
            create_sales_order_payload(owner["id"], credit_redeemed_cents=500),
            owner_h),
        expected_status=201,
    )
    api.create_order_line(order["id"], create_order_line_payload(title["id"], 1),
                          owner_h)
    # Intruder pays: owner-check (prio 3) fires before the credit check (prio 14),
    # even though the order also has insufficient credit (owner holds 0, redeems 500).
    intruder_h = make_member_headers(intruder["id"])
    resp = api.pay_order(order["id"], intruder_h)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_pay_by_owner_with_insufficient_credit_rejected(api):
    """PRD §3.4: "If the `credit_redeemed_cents` the member elected exceeds the
    member's `store_credit_cents`, the payment is rejected with
    `ERR_INSUFFICIENT_CREDIT` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/pay_owner_check_beats_insufficient_credit
    """
    owner = make_member()  # store_credit 0
    title = make_title(list_price_cents=1000)
    owner_h = make_member_headers(owner["id"])
    order = validate_success(
        api.create_sales_order(
            create_sales_order_payload(owner["id"], credit_redeemed_cents=500),
            owner_h),
        expected_status=201,
    )
    api.create_order_line(order["id"], create_order_line_payload(title["id"], 1),
                          owner_h)
    # The OWNER pays (no owner-check failure), so the credit check now governs.
    resp = api.pay_order(order["id"], owner_h)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT)


def test_insufficient_credit_redemption_rejected(api):
    """PRD §3.4: "If the `credit_redeemed_cents` the member elected exceeds the
    member's `store_credit_cents`, the payment is rejected with
    `ERR_INSUFFICIENT_CREDIT` (HTTP 422)."

    Design: Corner/validations/insufficient_credit_redemption_rejected
    """
    member = make_member()  # credit 0
    title = make_title(list_price_cents=1000)
    mh = make_member_headers(member["id"])
    order = validate_success(
        api.create_sales_order(
            create_sales_order_payload(member["id"], credit_redeemed_cents=500), mh),
        expected_status=201,
    )
    api.create_order_line(order["id"], create_order_line_payload(title["id"], 1), mh)
    resp = api.pay_order(order["id"], mh)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT)
