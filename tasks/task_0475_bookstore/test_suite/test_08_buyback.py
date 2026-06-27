"""Used-book buyback: per-line-then-sum offer rounding, completion issuing
store credit and stock, empty-transaction guard, and suspended-member guard."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    create_buyback_payload, create_buyback_line_payload, create_title_payload,
    make_member, make_title,
    setup_buyback_with_lines, setup_offered_buyback,
)

BOOKSELLER = TEST_USERS["bookseller_headers"]
ADMIN = TEST_USERS["store_admin_headers"]


def test_buyback_offer_rounds_per_line_then_sums(api):
    """PRD §3.6: "The per-copy offer for the line is the title's `list_price_cents`
    multiplied by the rate multiplied by the grade multiplier, rounded half-up to
    whole cents at this point. The line's `line_offer_cents` is that rounded
    per-copy offer multiplied by the line's `quantity`. The transaction's
    `offer_total_cents` is the sum of every line's `line_offer_cents`."
    PRD §3.6: "round each per-copy offer first, then multiply by quantity, then sum
    across lines — summing raw amounts and rounding once at the end would yield a
    different total and is not used."

    Design: Difficulty/combinatorial_formula/buyback_offer_per_line_round_then_sum
    """
    ctx = setup_buyback_with_lines(
        lines=[("LIKE_NEW", 1), ("GOOD", 1)],
        list_prices=[2499, 1599],
        demand_flags=["HIGH", "NORMAL"],
    )
    offered = validate_success(api.offer_buyback(ctx["buyback"]["id"], BOOKSELLER))
    # Line1: 2499*0.40*1.00=999.6 -> 1000. Line2: 1599*0.30*0.70=335.79 -> 336.
    # Total 1336 (NOT 1335 from sum-raw-then-round).
    assert offered["offer_total_cents"] == 1336


def test_buyback_offer_moves_to_offered_state(api):
    """PRD §3.6: "**Making the offer** moves the transaction from `PENDING` to
    `OFFERED` and computes `offer_total_cents`. The offer is allowed only when the
    transaction is `PENDING` and has at least one line".

    Design: Difficulty/combinatorial_formula/buyback_offer_per_line_round_then_sum
    """
    ctx = setup_buyback_with_lines(
        lines=[("LIKE_NEW", 1), ("GOOD", 1)],
        list_prices=[2499, 1599],
        demand_flags=["HIGH", "NORMAL"],
    )
    offered = validate_success(api.offer_buyback(ctx["buyback"]["id"], BOOKSELLER))
    assert offered["state"] == "OFFERED"


def test_buyback_complete_issues_credit_and_stock(api):
    """PRD §3.6: "On completion, for each line the system creates one `StockItem`
    per unit of `quantity` for that line's title, each with `source` `BUYBACK`,
    `state` `AVAILABLE`, and a `cost_cents` equal to the line's offer divided by
    its quantity; it appends a single `CreditLedgerEntry` with `reason` `BUYBACK`
    and a positive `delta_cents` equal to the transaction's `offer_total_cents`
    and recomputes the member's `store_credit_cents`".

    Design: Corner/calculations/buyback_complete_issues_credit_and_stock
    """
    ctx = setup_buyback_with_lines(
        lines=[("GOOD", 2)], list_prices=[1000], demand_flags=["NORMAL"]
    )
    member = ctx["member"]
    title = ctx["titles"][0]
    offered = validate_success(api.offer_buyback(ctx["buyback"]["id"], BOOKSELLER))
    # per_copy = round(1000*0.30*0.70)=210; line 210*2=420; total 420.
    assert offered["offer_total_cents"] == 420
    completed = validate_success(api.complete_buyback(ctx["buyback"]["id"],
                                                      BOOKSELLER))
    assert completed["state"] == "COMPLETED"
    member_now = validate_success(api.get_member(member["id"], ADMIN))
    assert member_now["store_credit_cents"] == 420
    title_now = validate_success(api.get_title(title["id"], BOOKSELLER))
    assert title_now["on_hand_qty"] == 2


def test_empty_buyback_offer_rejected(api):
    """PRD §3.6: "an offer attempt on a transaction with no lines is rejected with
    `ERR_EMPTY_TRANSACTION` (HTTP 422)."

    Design: Corner/validations/empty_buyback_offer_rejected
    """
    member = make_member()
    bb = validate_success(
        api.create_buyback(create_buyback_payload(member["id"]), BOOKSELLER),
        expected_status=201,
    )
    resp = api.offer_buyback(bb["id"], BOOKSELLER)
    validate_error(resp, ApiErrorId.ERR_EMPTY_TRANSACTION)


def test_buyback_complete_suspended_member_rejected(api):
    """PRD §3.6: "**Completing** the buyback moves it from `OFFERED` to
    `COMPLETED` and is allowed only when the transaction is `OFFERED` and the
    selling member is still `ACTIVE`; a completion attempt for a `SUSPENDED`
    member is rejected with `ERR_MEMBER_SUSPENDED` (HTTP 422)."

    Design: Corner/validations/buyback_complete_suspended_member_rejected
    """
    member = make_member()
    title = make_title(list_price_cents=1000)
    validate_success(api.suspend_member(member["id"], ADMIN))
    bb = validate_success(
        api.create_buyback(create_buyback_payload(member["id"]), BOOKSELLER),
        expected_status=201,
    )
    validate_success(
        api.create_buyback_line(
            bb["id"], create_buyback_line_payload(title["id"], "GOOD", 1),
            BOOKSELLER),
        expected_status=201,
    )
    validate_success(api.offer_buyback(bb["id"], BOOKSELLER))
    resp = api.complete_buyback(bb["id"], BOOKSELLER)
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED)
