"""Returns and refunds: dual-variant refund math, cascade, digital window."""
from test_helpers import (
    CLOCK_PAST_ADD_DROP,
    ApiErrorId,
    get_success_data,
    make_student_headers,
    place_order,
    set_clock,
    setup_order_with_line,
    setup_sales_open_with_approved_adoption,
    get_first_order_line,
    validate_error,
    validate_success,
)
from test_helpers import MANAGER


def test_refund_within_window_vs_manager_override(api):
    """PRD §3.7: "Within the applicable window, the refund is the full
    `line_total_cents`, returned to the original tenders. Under manager override
    past the add/drop deadline, the refund is 80% of the line total rounded
    half-up to integer cents — the store keeps a 20% restocking share, which
    counts as net revenue."
    PRD §3.7: "Either way, the split between tenders mirrors the original
    waterfall: `aid_refunded_cents` is the smaller of the line's
    `aid_tendered_cents` and the refund amount, and `card_refunded_cents` is the
    remainder of the refund."

    Design: Difficulty/dual_variant_calc/refund_within_window_vs_manager_override
    """
    base = setup_sales_open_with_approved_adoption(
        qty_used=2,
        posted_price_cents=8000,
        title_overrides={"initial_used_stock_qty": 2},
        awarded_aid_cents=100000,
        isbn="9780000000002",
    )
    order_a = place_order(
        base["term"]["id"], base["student"]["id"],
        [{"adoption_id": base["adoption"]["id"], "format": "USED", "qty": 1}],
    )
    order_b = place_order(
        base["term"]["id"], base["student"]["id"],
        [{"adoption_id": base["adoption"]["id"], "format": "USED", "qty": 1}],
    )
    line_a = get_first_order_line(order_a["id"])
    line_b = get_first_order_line(order_b["id"])

    # Within-window return: full line total (USED base 7500) back to aid.
    returned_a = validate_success(
        api.return_order_line(
            order_a["id"], line_a["id"], {},
            make_student_headers(base["student"]["id"]),
        )
    )
    assert returned_a["aid_refunded_cents"] == 7500
    assert returned_a["card_refunded_cents"] == 0

    # Past add/drop deadline with manager override: 80% refund (6000).
    set_clock(CLOCK_PAST_ADD_DROP)
    returned_b = validate_success(
        api.return_order_line(order_b["id"], line_b["id"], {"override": True}, MANAGER)
    )
    assert returned_b["aid_refunded_cents"] == 6000
    assert returned_b["card_refunded_cents"] == 0

    ord_a = get_success_data(api.get_order(order_a["id"], MANAGER))
    ord_b = get_success_data(api.get_order(order_b["id"], MANAGER))
    assert ord_a["refund_total_cents"] == 7500
    assert ord_b["refund_total_cents"] == 6000

    student = get_success_data(api.get_student(base["student"]["id"], MANAGER))
    # 100000 - 7500 - 7500 + 7500 + 6000 = 98500.
    assert student["aid_balance_cents"] == 98500


def test_refund_override_split_with_mixed_tenders(api):
    """PRD §3.7: "Under manager override past the add/drop deadline, the refund
    is 80% of the line total rounded half-up to integer cents — the store keeps
    a 20% restocking share, which counts as net revenue."
    PRD §3.7: "Either way, the split between tenders mirrors the original
    waterfall: `aid_refunded_cents` is the smaller of the line's
    `aid_tendered_cents` and the refund amount, and `card_refunded_cents` is the
    remainder of the refund."

    Design: Difficulty/dual_variant_calc/refund_within_window_vs_manager_override
    """
    # Student aid covers only 3000 of the 7500 USED line; card covers 4500.
    base = setup_sales_open_with_approved_adoption(
        qty_used=1,
        posted_price_cents=8000,
        title_overrides={"initial_used_stock_qty": 1},
        awarded_aid_cents=3000,
        isbn="9780000000033",
    )
    order = place_order(
        base["term"]["id"], base["student"]["id"],
        [{"adoption_id": base["adoption"]["id"], "format": "USED", "qty": 1}],
    )
    assert order["aid_tendered_cents"] == 3000
    assert order["card_tendered_cents"] == 4500
    line = get_first_order_line(order["id"])

    set_clock(CLOCK_PAST_ADD_DROP)
    returned = validate_success(
        api.return_order_line(order["id"], line["id"], {"override": True}, MANAGER)
    )
    # Refund 6000: aid portion capped at the line's aid tender (3000), the
    # remaining 3000 goes back to card.
    assert returned["aid_refunded_cents"] == 3000
    assert returned["card_refunded_cents"] == 3000

    student = get_success_data(api.get_student(base["student"]["id"], MANAGER))
    # 3000 - 3000 + 3000 = 3000.
    assert student["aid_balance_cents"] == 3000


def test_order_line_return_two_hop_cascade(api):
    """PRD §3.7: "Restocking mirrors placement: a returned `NEW` line adds
    `qty` back to the title's `new_stock_qty`, `USED` to `used_stock_qty`,
    `RENTAL` to `rental_stock_qty`, and `DIGITAL` restocks nothing."
    PRD §3.7: "CASCADE-2 then recomputes the parent order: `refund_total_cents`
    becomes the sum of all line refunds, and the order's status is re-derived —
    the first return against a `SETTLED` order moves it to `PARTIALLY_REFUNDED`,
    the order stays `PARTIALLY_REFUNDED` while more lines remain open, and when
    the last open line is returned the order reaches terminal `REFUNDED`."

    Design: Difficulty/transitive_cascade/order_line_return_two_hop_cascade
    """
    base = setup_order_with_line(
        fmt="USED", qty=1, posted_price_cents=8000,
        title_overrides={"initial_used_stock_qty": 1, "has_rental": False,
                         "has_digital": False},
        qty_used=1,
        isbn="9780000000007",
    )
    returned = validate_success(
        api.return_order_line(
            base["order"]["id"], base["line"]["id"], {},
            make_student_headers(base["student"]["id"]),
        )
    )
    assert returned["status"] == "RETURNED"
    assert returned["aid_refunded_cents"] == 7500

    title = get_success_data(api.get_title(base["title"]["id"], MANAGER))
    assert title["used_stock_qty"] == 1

    order = get_success_data(api.get_order(base["order"]["id"], MANAGER))
    assert order["refund_total_cents"] == 7500
    assert order["status"] == "REFUNDED"

    student = get_success_data(api.get_student(base["student"]["id"], MANAGER))
    assert student["aid_balance_cents"] == 100000


def test_first_return_moves_order_to_partially_refunded(api):
    """PRD §3.7: "CASCADE-2 then recomputes the parent order:
    `refund_total_cents` becomes the sum of all line refunds, and the order's
    status is re-derived — the first return against a `SETTLED` order moves it
    to `PARTIALLY_REFUNDED`, the order stays `PARTIALLY_REFUNDED` while more
    lines remain open, and when the last open line is returned the order
    reaches terminal `REFUNDED`."

    Design: Difficulty/transitive_cascade/order_line_return_two_hop_cascade
    """
    base = setup_sales_open_with_approved_adoption(
        qty_new=2,
        posted_price_cents=12000,
        title_overrides={"initial_new_stock_qty": 2, "has_used": False,
                         "has_rental": False, "has_digital": False},
        awarded_aid_cents=100000,
        isbn="9780000000034",
    )
    order = place_order(
        base["term"]["id"], base["student"]["id"],
        [{"adoption_id": base["adoption"]["id"], "format": "NEW", "qty": 1},
         {"adoption_id": base["adoption"]["id"], "format": "NEW", "qty": 1}],
    )
    lines = get_success_data(api.list_order_lines(order["id"], MANAGER))
    assert len(lines) == 2

    validate_success(
        api.return_order_line(
            order["id"], lines[0]["id"], {},
            make_student_headers(base["student"]["id"]),
        )
    )
    mid = get_success_data(api.get_order(order["id"], MANAGER))
    assert mid["status"] == "PARTIALLY_REFUNDED"
    assert mid["refund_total_cents"] == 10000

    validate_success(
        api.return_order_line(
            order["id"], lines[1]["id"], {},
            make_student_headers(base["student"]["id"]),
        )
    )
    final = get_success_data(api.get_order(order["id"], MANAGER))
    assert final["status"] == "REFUNDED"
    assert final["refund_total_cents"] == 20000


def test_digital_return_after_48h_rejected(api):
    """PRD §3.7: "A `DIGITAL` line is returnable only within 48 hours of the
    order's `created_at`; beyond that, the return is rejected with
    `ERR_DIGITAL_NOT_RETURNABLE`."

    Design: Corner/validations/digital_return_after_48h_rejected
    """
    base = setup_order_with_line(
        fmt="DIGITAL", qty=1, posted_price_cents=12000,
        title_overrides={"has_new": False, "has_used": False,
                         "has_rental": False},
        qty_digital=1,
        isbn="9780000001012",
    )
    set_clock("2026-08-23T00:00:01Z")
    resp = api.return_order_line(
        base["order"]["id"], base["line"]["id"], {},
        make_student_headers(base["student"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DIGITAL_NOT_RETURNABLE)
    line = get_success_data(api.get_order_line(base["line"]["id"], MANAGER))
    assert line["status"] == "FULFILLED"
