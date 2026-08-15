"""Payment: parallel dimension, scrap-credit waterfall, sufficiency guard."""
from test_helpers import (
    ApiErrorId,
    create_completed_order,
    create_customer,
    create_full_sheet,
    create_grade,
    create_machine,
    get_customer,
    get_order,
    list_customer_credits,
    post_scrap_credit,
    rep_headers,
    validate_error,
    validate_success,
)

TINY_PART = {"bbox_width_mm": 20, "bbox_height_mm": 20, "hole_count": 0,
             "corner_fillet_count": 1, "bend_count": 0, "weld_inches": 0,
             "finish": "NONE"}
SIMPLE = {"bbox_width_mm": 50, "bbox_height_mm": 50, "hole_count": 0,
          "corner_fillet_count": 0, "bend_count": 0, "weld_inches": 0,
          "finish": "NONE"}


# --- parallel dimension (Difficulty: order_payment_parallel_dimension_independent)

def test_completed_unpaid_is_a_stable_state(api):
    """PRD §3.9: "Payment is a `CustomerRep` act on a COMPLETED order, and it
    lives on a parallel dimension: the order's lifecycle status stays
    COMPLETED while its `payment_status` moves from UNPAID to PAID."

    Design: Difficulty/non_linear_state_machine/order_payment_parallel_dimension_independent
    """
    grade = create_grade()
    customer = create_customer()
    create_full_sheet(grade["id"])
    create_machine("LASER")
    order = create_completed_order(customer, grade["id"],
                                   line_overrides=SIMPLE)

    before = get_order(order["id"])
    assert before["status"] == "COMPLETED"
    assert before["payment_status"] == "UNPAID"


def test_payment_flips_only_payment_dimension(api):
    """PRD §3.9: "... the order's lifecycle status stays COMPLETED while its
    `payment_status` moves from UNPAID to PAID. Paying an order whose
    lifecycle is not COMPLETED is rejected with `ERR_INVALID_STATE`; paying
    one already PAID is rejected with `ERR_ALREADY_PAID`."

    Design: Difficulty/non_linear_state_machine/order_payment_parallel_dimension_independent
    """
    grade = create_grade()
    customer = create_customer()
    create_full_sheet(grade["id"])
    create_machine("LASER")
    order = create_completed_order(customer, grade["id"],
                                   line_overrides=SIMPLE)

    resp = api.pay_order(order["id"], {}, rep_headers(customer))
    paid = validate_success(resp, 200)
    assert paid["payment_status"] == "PAID"
    assert paid["status"] == "COMPLETED", "payment leaves the lifecycle alone"
    assert paid.get("paid_at"), "paid_at stamped from the logical clock"

    resp = api.pay_order(order["id"], {}, rep_headers(customer))
    validate_error(resp, ApiErrorId.ERR_ALREADY_PAID, 409)


# --- waterfall with split (Difficulty: scrap_credit_waterfall_split_remainder_rounding)

def test_scrap_credit_waterfall_splits_final_row(api):
    """PRD §3.9: "The draw drains the customer's POSTED credit rows in
    first-in-first-out order by `created_at` ascending — never by `id`: whole
    rows are consumed while the remaining amount covers a row's full
    `credit_cents`, and the final partially consumed row is split, creating a
    VOID replacement row carrying the unconsumed remainder while the original
    row becomes APPLIED." PRD §3.9: "The order's `scrap_credit_applied_cents`
    records exactly the applied amount, the customer's
    `scrap_credit_balance_cents` is debited by exactly that amount — so the
    sum of the APPLIED rows plus the remainder VOID row always equals the
    original POSTED total ..."

    Design: Difficulty/combinatorial_formula/scrap_credit_waterfall_split_remainder_rounding
    """
    grade = create_grade()
    customer = create_customer()
    # Two walk-in drop-offs: each credits min(28800, 2880, 90000) = 2880 cm2
    # -> round_half_up(2880 * 0.020) = 58 cents.
    sheet1 = create_full_sheet(grade["id"])
    sheet2 = create_full_sheet(grade["id"])
    credit1 = post_scrap_credit(customer["id"], sheet1["id"])
    credit2 = post_scrap_credit(customer["id"], sheet2["id"])
    assert credit1["credit_cents"] == 58
    assert credit2["credit_cents"] == 58
    assert get_customer(customer["id"])["scrap_credit_balance_cents"] == 116

    create_full_sheet(grade["id"])  # stock for the order's nest
    create_machine("LASER")
    order = create_completed_order(customer, grade["id"],
                                   line_overrides=TINY_PART,
                                   expedite_tier="RUSH")

    resp = api.pay_order(order["id"], {"scrap_credit_to_apply_cents": 100},
                         rep_headers(customer))
    paid = validate_success(resp, 200)
    assert paid["scrap_credit_applied_cents"] == 100
    assert paid["payment_status"] == "PAID"

    assert get_customer(customer["id"])["scrap_credit_balance_cents"] == 16

    rows = list_customer_credits(customer["id"])
    by_id = {r["id"]: r for r in rows}
    assert by_id[credit1["id"]]["status"] == "APPLIED", (
        "FIFO consumes the oldest row whole first"
    )
    assert by_id[credit2["id"]]["status"] == "APPLIED", (
        "the final partially-consumed row becomes APPLIED"
    )
    voids = [r for r in rows if r["status"] == "VOID"]
    assert len(voids) == 1, "the split creates exactly one VOID remainder row"
    assert voids[0]["credit_cents"] == 16
    applied_sum = sum(r["credit_cents"] for r in rows if r["status"] == "APPLIED")
    assert applied_sum + voids[0]["credit_cents"] == 116, (
        "conservation: APPLIED rows plus the VOID remainder equal the POSTED total"
    )


def test_scrap_credit_waterfall_exact_row_boundary_no_split(api):
    """PRD §3.9: "The draw drains the customer's POSTED credit rows in
    first-in-first-out order by `created_at` ascending — never by `id`: whole
    rows are consumed while the remaining amount covers a row's full
    `credit_cents`, and the final partially consumed row is split, creating a
    VOID replacement row carrying the unconsumed remainder while the original
    row becomes APPLIED."

    Design: Difficulty/combinatorial_formula/scrap_credit_waterfall_split_remainder_rounding
    """
    grade = create_grade()
    customer = create_customer()
    sheet1 = create_full_sheet(grade["id"])
    sheet2 = create_full_sheet(grade["id"])
    credit1 = post_scrap_credit(customer["id"], sheet1["id"])  # 58
    credit2 = post_scrap_credit(customer["id"], sheet2["id"])  # 58

    create_full_sheet(grade["id"])
    create_machine("LASER")
    order = create_completed_order(customer, grade["id"],
                                   line_overrides=TINY_PART,
                                   expedite_tier="RUSH")

    # Requesting exactly the oldest row's amount consumes it whole; no split.
    paid = validate_success(
        api.pay_order(order["id"], {"scrap_credit_to_apply_cents": 58},
                      rep_headers(customer)))
    assert paid["scrap_credit_applied_cents"] == 58

    rows = list_customer_credits(customer["id"])
    by_id = {r["id"]: r for r in rows}
    assert by_id[credit1["id"]]["status"] == "APPLIED"
    assert by_id[credit2["id"]]["status"] == "POSTED", (
        "the second row is never touched when the first covers the request"
    )
    assert [r for r in rows if r["status"] == "VOID"] == []
    assert get_customer(customer["id"])["scrap_credit_balance_cents"] == 58


# --- second payment (Corner: error_already_paid_second_payment) -------------

def test_second_payment_rejected_and_paid_at_unchanged(api):
    """PRD §3.9: "Paying an order whose lifecycle is not COMPLETED is rejected
    with `ERR_INVALID_STATE`; paying one already PAID is rejected with
    `ERR_ALREADY_PAID`."

    Design: Corner/errors/error_already_paid_second_payment
    """
    grade = create_grade()
    customer = create_customer()
    create_full_sheet(grade["id"])
    create_machine("LASER")
    order = create_completed_order(customer, grade["id"],
                                   line_overrides=SIMPLE)

    paid = validate_success(api.pay_order(order["id"], {}, rep_headers(customer)))
    paid_at = paid["paid_at"]

    resp = api.pay_order(order["id"], {}, rep_headers(customer))
    validate_error(resp, ApiErrorId.ERR_ALREADY_PAID, 409)
    assert get_order(order["id"])["paid_at"] == paid_at


# --- sufficiency guard (Corner: error_insufficient_scrap_credit_at_payment) -

def test_insufficient_scrap_credit_at_payment(api):
    """PRD §3.9: "The payment may optionally carry
    `scrap_credit_to_apply_cents`, a non-negative amount the customer wishes
    to draw from their scrap-credit balance; requesting more than the
    customer's `scrap_credit_balance_cents` is rejected with
    `ERR_INSUFFICIENT_SCRAP_CREDIT` (HTTP 402)."

    Design: Corner/errors/error_insufficient_scrap_credit_at_payment
    """
    grade = create_grade()
    customer = create_customer()
    credit_sheet = create_full_sheet(grade["id"])
    post_scrap_credit(customer["id"], credit_sheet["id"])  # balance 58
    create_full_sheet(grade["id"])  # nest stock
    create_machine("LASER")
    order = create_completed_order(customer, grade["id"],
                                   line_overrides=SIMPLE)

    resp = api.pay_order(order["id"], {"scrap_credit_to_apply_cents": 100},
                         rep_headers(customer))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SCRAP_CREDIT, 402)

    order_after = get_order(order["id"])
    assert order_after["payment_status"] == "UNPAID"
    assert get_customer(customer["id"])["scrap_credit_balance_cents"] == 58
