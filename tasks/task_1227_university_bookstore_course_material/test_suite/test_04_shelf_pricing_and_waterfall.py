"""Shelf pricing tiers, HEOA cap, and the aid tender waterfall."""
from test_helpers import (
    CLOCK_IN_AID_WINDOW,
    TERM_FALL_2026,
    ApiErrorId,
    assert_order,
    create_approved_adoption,
    create_faculty,
    create_order_payload,
    create_publisher_with_agreement,
    create_section,
    create_student,
    create_term,
    create_title,
    get_success_data,
    make_student_headers,
    open_section,
    open_term_adoption,
    place_order,
    reset_clock,
    set_clock,
    setup_sales_open_with_approved_adoption,
    drive_term_to_sales_open,
    validate_error,
    validate_success,
)


def test_shelf_price_format_tier_and_posted_cap(api):
    """PRD §3.6: "For `NEW`, the base is the title's `list_price_cents`. For
    `USED`, the base is 75% of the list price, rounded half-up to integer cents.
    For `RENTAL`, the base is a percentage of list that depends on the term's
    `length_weeks`: 40% when the term runs at most 8 weeks, 50% when it runs 9
    to 16 weeks, and 60% when it runs 17 weeks or more — the chosen product
    rounded half-up to integer cents. For `DIGITAL`, the base is the list price
    reduced by the active agreement's `digital_discount_pct`, rounded half-up to
    integer cents. The HEOA price cap then applies: `unit_price_cents` is the
    smaller of the format base and the adoption's `posted_price_cents`, so the
    posted transparency price is a hard upper bound on what a student can be
    charged."
    PRD §3.6: "If `aid_only` is true and the summed aid falls short of
    `total_cents`, the placement fails with `ERR_INSUFFICIENT_AID` (HTTP 402).
    Otherwise the student's `aid_balance_cents` is debited by the order's
    `aid_tendered_cents`."

    Design: Difficulty/combinatorial_formula/shelf_price_format_tier_and_posted_cap
    """
    base = setup_sales_open_with_approved_adoption(
        qty_new=5, qty_used=5, qty_rental=5, qty_digital=5,
        posted_price_cents=7000,
        title_overrides={
            "initial_new_stock_qty": 5,
            "initial_used_stock_qty": 5,
            "initial_rental_stock_qty": 5,
        },
        awarded_aid_cents=100000,
        isbn="9780000000003",
    )
    adoption_id = base["adoption"]["id"]
    order = place_order(
        base["term"]["id"], base["student"]["id"],
        [
            {"adoption_id": adoption_id, "format": "NEW", "qty": 1},
            {"adoption_id": adoption_id, "format": "USED", "qty": 1},
            {"adoption_id": adoption_id, "format": "RENTAL", "qty": 1},
            {"adoption_id": adoption_id, "format": "DIGITAL", "qty": 1},
        ],
    )
    assert_order(order)
    # HEOA cap (posted 7000) binds per line: NEW base 10000 -> 7000;
    # USED base 7500 -> 7000; RENTAL 50% at 16 weeks -> 5000 (below cap);
    # DIGITAL base 10000 * (1 - 0.25) = 7500 -> 7000.
    assert order["total_cents"] == 26000
    assert order["aid_tendered_cents"] == 26000
    assert order["card_tendered_cents"] == 0

    lines = get_success_data(api.list_order_lines(order["id"], make_student_headers(base["student"]["id"])))
    by_format = {line["format"]: line for line in lines}
    assert by_format["NEW"]["unit_price_cents"] == 7000
    assert by_format["USED"]["unit_price_cents"] == 7000
    assert by_format["RENTAL"]["unit_price_cents"] == 5000
    assert by_format["DIGITAL"]["unit_price_cents"] == 7000


def test_shelf_price_posted_cap_binds_only_when_below_base(api):
    """PRD §3.6: "The HEOA price cap then applies: `unit_price_cents` is the
    smaller of the format base and the adoption's `posted_price_cents`, so the
    posted transparency price is a hard upper bound on what a student can be
    charged."
    PRD §3.6: "For `USED`, the base is 75% of the list price, rounded half-up
    to integer cents."

    Design: Difficulty/combinatorial_formula/shelf_price_format_tier_and_posted_cap
    """
    base = setup_sales_open_with_approved_adoption(
        qty_new=1, qty_used=1,
        posted_price_cents=12000,
        title_overrides={"initial_new_stock_qty": 1, "initial_used_stock_qty": 1},
        awarded_aid_cents=0,
        isbn="9780000000032",
    )
    adoption_id = base["adoption"]["id"]
    order = place_order(
        base["term"]["id"], base["student"]["id"],
        [
            {"adoption_id": adoption_id, "format": "NEW", "qty": 1},
            {"adoption_id": adoption_id, "format": "USED", "qty": 1},
        ],
    )
    # Posted 12000 sits above both bases (10000, 7500), so the bases win.
    assert order["total_cents"] == 17500
    lines = get_success_data(api.list_order_lines(order["id"], make_student_headers(base["student"]["id"])))
    by_format = {line["format"]: line for line in lines}
    assert by_format["NEW"]["unit_price_cents"] == 10000
    assert by_format["USED"]["unit_price_cents"] == 7500


def test_rental_tier_boundary_8_vs_9_weeks(api):
    """PRD §3.6: "For `RENTAL`, the base is a percentage of list that depends
    on the term's `length_weeks`: 40% when the term runs at most 8 weeks, 50%
    when it runs 9 to 16 weeks, and 60% when it runs 17 weeks or more — the
    chosen product rounded half-up to integer cents."

    Design: Corner/calculations/rental_tier_boundary_8_vs_9_weeks
    """
    reset_clock()
    term8 = create_term({
        "code": "2026-SUMMER",
        "length_weeks": 8,
        "registration_open_at": "2026-05-15T00:00:00Z",
        "price_posting_deadline_at": "2026-05-20T00:00:00Z",
        "adoption_deadline_at": "2026-06-01T23:59:59Z",
        "aid_charge_window_start_at": "2026-07-01T00:00:00Z",
        "aid_charge_window_end_at": "2026-07-31T23:59:59Z",
        "add_drop_return_deadline_at": "2026-07-25T23:59:59Z",
        "census_at": "2026-07-27T00:00:00Z",
        "ia_opt_out_deadline_at": "2026-07-26T23:59:59Z",
        "buyback_window_start_at": "2026-08-10T00:00:00Z",
        "buyback_window_end_at": "2026-08-20T23:59:59Z",
        "buy_budget_cents": 100000000,
    })
    term9 = create_term(dict(TERM_FALL_2026, length_weeks=9))
    pub, _agr = create_publisher_with_agreement()
    title = create_title(
        pub["id"], isbn="9780000001009", has_new=False, has_used=False,
        has_digital=False, initial_rental_stock_qty=2,
    )
    faculty = create_faculty()
    student = create_student(awarded_aid_cents=0)
    sec8 = create_section(term8["id"], faculty["id"])
    sec9 = create_section(term9["id"], faculty["id"])
    open_term_adoption(term8["id"])
    open_term_adoption(term9["id"])
    opened8 = open_section(sec8["id"])
    opened9 = open_section(sec9["id"])
    ado8 = create_approved_adoption(
        sec8["id"], title["id"], faculty["id"], opened8["version"],
        qty_rental=1, posted_price_cents=12000,
    )
    ado9 = create_approved_adoption(
        sec9["id"], title["id"], faculty["id"], opened9["version"],
        qty_rental=1, posted_price_cents=12000,
    )
    drive_term_to_sales_open(term8["id"])
    drive_term_to_sales_open(term9["id"])
    # Both aid windows contain this instant; student has no aid, so all card.
    set_clock("2026-07-10T00:00:00Z")

    order8 = place_order(
        term8["id"], student["id"],
        [{"adoption_id": ado8["id"], "format": "RENTAL", "qty": 1}],
    )
    order9 = place_order(
        term9["id"], student["id"],
        [{"adoption_id": ado9["id"], "format": "RENTAL", "qty": 1}],
    )
    assert order8["total_cents"] == 4000
    assert order9["total_cents"] == 5000


def test_aid_waterfall_partial_split_order_sensitive(api):
    """PRD §3.6: "Tendering then runs as a waterfall over the new order's lines
    in request-array order."
    PRD §3.6: "Walking the lines in array order, each line's
    `aid_tendered_cents` is the smaller of its `line_total_cents` and the
    remaining aid; its `card_tendered_cents` is the remainder of the line total;
    and the remaining aid decreases by the aid just applied. The order's
    `aid_tendered_cents` and `card_tendered_cents` are the per-line sums."

    Design: Corner/calculations/aid_waterfall_partial_split_order_sensitive
    """
    base = setup_sales_open_with_approved_adoption(
        qty_new=1, qty_used=1,
        posted_price_cents=12000,
        title_overrides={"initial_new_stock_qty": 1, "initial_used_stock_qty": 1},
        awarded_aid_cents=12000,
        isbn="9780000001008",
    )
    order = place_order(
        base["term"]["id"], base["student"]["id"],
        [
            {"adoption_id": base["adoption"]["id"], "format": "NEW", "qty": 1},
            {"adoption_id": base["adoption"]["id"], "format": "USED", "qty": 1},
        ],
    )
    assert order["total_cents"] == 17500
    assert order["aid_tendered_cents"] == 12000
    assert order["card_tendered_cents"] == 5500

    lines = get_success_data(api.list_order_lines(order["id"], make_student_headers(base["student"]["id"])))
    by_format = {line["format"]: line for line in lines}
    assert by_format["NEW"]["aid_tendered_cents"] == 10000
    assert by_format["NEW"]["card_tendered_cents"] == 0
    assert by_format["USED"]["aid_tendered_cents"] == 2000
    assert by_format["USED"]["card_tendered_cents"] == 5500

    student = get_success_data(api.get_student(base["student"]["id"], make_student_headers(base["student"]["id"])))
    assert student["aid_balance_cents"] == 0


def test_order_response_immediately_reflects_tender_split(api):
    """PRD §3.6: "The order's `aid_tendered_cents` and `card_tendered_cents`
    are the per-line sums. If `aid_only` is true and the summed aid falls short
    of `total_cents`, the placement fails with `ERR_INSUFFICIENT_AID` (HTTP
    402). Otherwise the student's `aid_balance_cents` is debited by the order's
    `aid_tendered_cents`."
    PRD §3.6: "An order is born directly in `SETTLED` — there is no pending
    state — and each of its lines is born `FULFILLED`."

    Design: Corner/consistency_model/order_response_immediately_reflects_tender_split
    """
    base = setup_sales_open_with_approved_adoption(
        qty_new=1, qty_used=1,
        posted_price_cents=12000,
        title_overrides={"initial_new_stock_qty": 1, "initial_used_stock_qty": 1},
        awarded_aid_cents=12000,
        isbn="9780000001027",
    )
    resp = api.create_order(
        create_order_payload(
            term_id=base["term"]["id"],
            lines=[
                {"adoption_id": base["adoption"]["id"], "format": "NEW", "qty": 1},
                {"adoption_id": base["adoption"]["id"], "format": "USED", "qty": 1},
            ],
        ),
        make_student_headers(base["student"]["id"]),
    )
    order = validate_success(resp, expected_status=201)
    assert order["total_cents"] == 17500
    assert order["aid_tendered_cents"] == 12000
    assert order["card_tendered_cents"] == 5500
    assert order["status"] == "SETTLED"
