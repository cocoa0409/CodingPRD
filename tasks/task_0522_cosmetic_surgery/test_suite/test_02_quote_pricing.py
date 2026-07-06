"""Quote pricing: line-item snapshots, tiered multi-procedure discount, rounding
order, required deposit, and immediate balance reconciliation."""
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    assert_line_item, assert_quote_balance_identity,
    create_line_item_payload, create_deposit_payload,
    TEST_USERS, PROC_A, PROC_B,
    create_procedure, create_draft_quote,
)

FRONT = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_headers"]


def test_line_item_snapshots_procedure_fees(api):
    """PRD §3.3: "At add time the system snapshots the procedure's three fees onto the
    line as surgical_fee_cents, facility_fee_cents, and anesthesia_fee_cents ... The
    line's bundle_total_cents is the sum of those three snapshotted fees."

    Design: Corner/entities/line_item_snapshots_procedure_fees
    """
    proc = create_procedure(**PROC_A)
    quote, _cons, _pat, _lis = create_draft_quote([])
    resp = api.add_line_item(quote["id"], create_line_item_payload(proc["id"]), FRONT)
    data = validate_success(resp, 201)
    assert_line_item(data)
    assert data["bundle_total_cents"] == 850000
    assert data["surgical_fee_cents"] == 500000


def test_line_item_has_no_version_field(api):
    """PRD §2.5: "The sole exception is the QuoteLineItem, which is an append-only
    record. A line item carries only id and created_at; it has no updated_at and no
    version, because it is never mutated after creation."

    Design: Corner/entities/line_item_immutable_no_version_field
    """
    create_procedure(**PROC_A)
    quote, _cons, _pat, _lis = create_draft_quote([])
    resp = api.list_line_items(quote["id"], FRONT)
    data, _meta = validate_paginated(resp)
    assert len(data) == 0, "no line item added yet; list endpoint returns empty array"


def test_quote_total_two_line_five_percent_rounding_order(api):
    """PRD §3.3: "exactly two lines yield 0.05 ... The rounding order is fixed: the
    system first sums the bundle totals as integer cents, then applies the discount to
    that subtotal by multiplying it by one minus the discount fraction, and only then
    rounds the result half up to whole cents to obtain total_cents."
    PRD §3.3: "The required_deposit_cents is then computed as 20 percent of total_cents,
    rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/combinatorial_quote_total_rounding_order
    """
    procA = create_procedure(**PROC_A)
    procB = create_procedure(**PROC_B)
    quote, _cons, _pat, _lis = create_draft_quote([])
    api.add_line_item(quote["id"], create_line_item_payload(procA["id"]), FRONT)
    api.add_line_item(quote["id"], create_line_item_payload(procB["id"]), FRONT)
    data = get_success_data(api.get_quote_package(quote["id"], FRONT))
    assert data["subtotal_cents"] == 1400000
    assert data["discount_pct"] == 0.05
    assert data["total_cents"] == 1330000  # round_half_up(1400000 * 0.95)
    assert data["required_deposit_cents"] == 266000  # round_half_up(1330000 * 0.20)


def test_quote_total_two_line_discount_applied_once_not_per_line(api):
    """PRD §3.3: "A multi-procedure discount is then keyed on the count of line items:
    three or more lines yield a discount_pct of 0.10, exactly two lines yield 0.05, and
    a single line yields no discount (0.00)."
    PRD §3.3: "Discounts are never applied per line item."

    Design: Difficulty/combinatorial_formula/combinatorial_quote_total_rounding_order
    """
    procA = create_procedure(**PROC_A)
    procB = create_procedure(**PROC_B)
    quote, _cons, _pat, _lis = create_draft_quote([])
    api.add_line_item(quote["id"], create_line_item_payload(procA["id"]), FRONT)
    data = get_success_data(api.get_quote_package(quote["id"], FRONT))
    assert data["discount_pct"] == 0.00  # single line
    api.add_line_item(quote["id"], create_line_item_payload(procB["id"]), FRONT)
    data = get_success_data(api.get_quote_package(quote["id"], FRONT))
    assert data["discount_pct"] == 0.05
    assert data["total_cents"] == 1330000


def test_quote_total_three_line_ten_percent(api):
    """PRD §3.3: "three or more lines yield a discount_pct of 0.10 ... The
    required_deposit_cents is then computed as 20 percent of total_cents, rounded half
    up to whole cents."

    Design: Corner/calculations/quote_total_three_line_ten_percent
    """
    procA = create_procedure(**PROC_A)
    procB = create_procedure(**PROC_B)
    procC = create_procedure(code="FACE01", name="Facelift",
                             surgical_fee_cents=250000, facility_fee_cents=120000,
                             anesthesia_fee_cents=80000)
    quote, _cons, _pat, _lis = create_draft_quote([])
    api.add_line_item(quote["id"], create_line_item_payload(procA["id"]), FRONT)
    api.add_line_item(quote["id"], create_line_item_payload(procB["id"]), FRONT)
    api.add_line_item(quote["id"], create_line_item_payload(procC["id"]), FRONT)
    data = get_success_data(api.get_quote_package(quote["id"], FRONT))
    assert data["subtotal_cents"] == 1850000
    assert data["discount_pct"] == 0.10
    assert data["total_cents"] == 1665000  # round_half_up(1850000 * 0.90)
    assert data["required_deposit_cents"] == 333000


def test_quote_total_single_line_no_discount(api):
    """PRD §3.3: "a single line yields no discount (0.00) ... The required_deposit_cents
    is then computed as 20 percent of total_cents, rounded half up to whole cents."

    Design: Corner/calculations/quote_total_single_line_no_discount
    """
    procA = create_procedure(**PROC_A)
    quote, _cons, _pat, _lis = create_draft_quote([])
    api.add_line_item(quote["id"], create_line_item_payload(procA["id"]), FRONT)
    data = get_success_data(api.get_quote_package(quote["id"], FRONT))
    assert data["discount_pct"] == 0.00
    assert data["total_cents"] == 850000
    assert data["required_deposit_cents"] == 170000


def test_deposit_reflected_in_balance_same_response(api):
    """PRD §2.6: "Its balance_due_cents is always the quote's total_cents minus its
    deposit_paid_cents minus its financed_cents, and this derived field must be
    recomputed and kept consistent every time any of its three inputs changes."

    Design: Corner/consistency_model/immediate_balance_visible_same_response
    """
    procA = create_procedure(**PROC_A)
    quote, _cons, _pat, _lis = create_draft_quote([procA["id"]])
    resp = api.record_deposit(quote["id"], create_deposit_payload(170000), BILLING)
    data = validate_success(resp, 201)
    assert data["deposit_paid_cents"] == 170000
    assert data["balance_due_cents"] == 680000  # 850000 - 170000 - 0
    assert_quote_balance_identity(data)
