"""Parts counter: per-line tiered pricing, quantity break, stock rules,
returns with restocking fee, and receivable reconciliation (PRD §3.9, §2.9)."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated, get_success_data,
    create_account, create_fleet_account, create_part, create_parts_sale,
    get_sale_lines, drive_ro_to_invoiced, set_clock,
)

MGR = TEST_USERS["sales_manager_headers"]
PARTS_REP = TEST_USERS["parts_counter_rep_headers"]
CONTROLLER = TEST_USERS["controller_headers"]


def _ar(account_id):
    return get_success_data(
        api_client.get_customer_account(account_id, CONTROLLER))["open_ar_cents"]


# ---------------------------------------------------------------- Queue A ---

class TestPartsSalePerLineRoundingThenSum:
    def _setup(self):
        acct = create_fleet_account(tier="GOLD", credit_limit_cents=100000000,
                                    name="GoldFleet")
        part_a = create_part(sku="FLT-A1", part_name="Filter A", list_price_cents=12499,
                             cost_cents=7000, on_hand=20)
        part_b = create_part(sku="FLT-B2", part_name="Alternator B", list_price_cents=999,
                             cost_cents=400, on_hand=5, has_core_charge=True,
                             core_charge_cents=5000)
        sale = create_parts_sale(acct["id"], [{"part_id": part_a["id"], "quantity": 10},
                                              {"part_id": part_b["id"], "quantity": 1}])
        return acct, part_a, part_b, sale

    def test_per_line_unit_net_prices_rounded_before_multiplying(self, api):
        """PRD §3.9: "a quantity of at least 10 on a line adds a further five
        percent; the effective discount is their sum capped at forty percent.
        The line's `unit_net_price_cents` is the part's list price times one
        minus the effective discount, rounded half-up to integer cents, and
        `line_total_cents` is that net unit price times the quantity."
        PRD §3.9: "Pricing is pinned per line, in exact order, and the
        alternative of summing list prices and discounting once is forbidden
        because per-line rounding yields different cents."

        Design: Difficulty/combinatorial_formula/parts_sale_per_line_rounding_then_sum
        """
        _, part_a, part_b, sale = self._setup()
        lines = {l["part_id"]: l for l in get_sale_lines(sale["id"])}
        # GOLD 10% + qty-break 5% = 15%: round_half_up(12499 * 0.85)
        assert lines[part_a["id"]]["unit_net_price_cents"] == 10624
        assert lines[part_a["id"]]["line_total_cents"] == 106240
        # qty 1: GOLD 10% only: round_half_up(999 * 0.90)
        assert lines[part_b["id"]]["unit_net_price_cents"] == 899
        assert lines[part_b["id"]]["line_total_cents"] == 899

    def test_sale_totals_sum_rounded_lines_and_cores_never_discounted(self, api):
        """PRD §3.9: "At the sale level, `subtotal_cents` sums the per-line
        totals, `core_total_cents` sums the core charge times quantity over
        lines whose part carries a core charge, and `total_cents` is subtotal
        plus cores."
        PRD §3.9: "for a `FLEET` account the total lands on the receivable with
        the usual credit-posture re-evaluation."

        Design: Difficulty/combinatorial_formula/parts_sale_per_line_rounding_then_sum
        """
        acct, _, _, sale = self._setup()
        assert sale["subtotal_cents"] == 107139  # 106240 + 899
        assert sale["core_total_cents"] == 5000  # core never discounted
        assert sale["total_cents"] == 112139
        assert sale["status"] == "INVOICED"
        assert _ar(acct["id"]) == 112139


# ---------------------------------------------------------------- Queue B ---

def test_parts_quantity_break_exactly_at_10_vs_9(api):
    """PRD §3.9: "The buyer's fleet tier sets a tier discount — zero for
    `STANDARD`, ten percent for `GOLD`, twenty percent for `PLATINUM` — and a
    quantity of at least 10 on a line adds a further five percent".

    Design: Corner/calculations/parts_quantity_break_exactly_at_10_vs_9
    """
    acct = create_fleet_account(tier="GOLD", credit_limit_cents=100000000, name="BreakCo")
    part = create_part(sku="FLT-Q1", part_name="Filter Q", list_price_cents=12499,
                       cost_cents=7000, on_hand=30)
    sale9 = create_parts_sale(acct["id"], [{"part_id": part["id"], "quantity": 9}])
    sale10 = create_parts_sale(acct["id"], [{"part_id": part["id"], "quantity": 10}])
    # qty 9 -> 10% only: round_half_up(12499 * 0.90)
    assert get_sale_lines(sale9["id"])[0]["unit_net_price_cents"] == 11249
    # qty 10 -> 15%: round_half_up(12499 * 0.85)
    assert get_sale_lines(sale10["id"])[0]["unit_net_price_cents"] == 10624


def test_insufficient_stock_and_discontinued_part(api):
    """PRD §3.9: "Stock decrements per line (`ERR_INSUFFICIENT_STOCK` when
    short)".
    PRD §3.9: "Parts are born `ACTIVE` and may be moved to `DISCONTINUED`,
    which blocks future sales and line references with `ERR_PART_DISCONTINUED`."

    Design: Corner/validations/insufficient_stock_and_discontinued_part
    """
    acct = create_account(name="StockCo")
    part = create_part(sku="STK-3", list_price_cents=1000, cost_cents=500, on_hand=4)
    validate_error(api_client.create_parts_sale(
        {"customer_account_id": acct["id"],
         "lines": [{"part_id": part["id"], "quantity": 5}]}, PARTS_REP),
        ApiErrorId.ERR_INSUFFICIENT_STOCK)
    sale = create_parts_sale(acct["id"], [{"part_id": part["id"], "quantity": 3}])
    assert sale["status"] == "INVOICED"
    assert get_success_data(api_client.get_part(part["id"], PARTS_REP))["on_hand"] == 1
    validate_success(api_client.discontinue_part(part["id"], PARTS_REP), 200)
    validate_error(api_client.create_parts_sale(
        {"customer_account_id": acct["id"],
         "lines": [{"part_id": part["id"], "quantity": 1}]}, PARTS_REP),
        ApiErrorId.ERR_PART_DISCONTINUED)


def test_return_quantity_exceeds_sold_rejected(api):
    """PRD §3.9: "the quantity must be at least one and, together with the
    line's `returned_quantity` so far, must not exceed the quantity sold
    (`ERR_RETURN_EXCEEDS_SOLD`). Each return adds to `returned_quantity`,
    restores that many units to the part's `on_hand`".

    Design: Corner/validations/return_quantity_exceeds_sold_rejected
    """
    acct = create_account(name="RetCo")
    part = create_part(sku="RET-1", list_price_cents=1000, cost_cents=500, on_hand=10)
    sale = create_parts_sale(acct["id"], [{"part_id": part["id"], "quantity": 3}])
    line_id = get_sale_lines(sale["id"])[0]["id"]
    data = validate_success(api_client.return_parts_sale_line(
        line_id, {"quantity": 2}, PARTS_REP), 200)
    assert data["returned_quantity"] == 2
    assert get_success_data(api_client.get_part(part["id"], PARTS_REP))["on_hand"] == 9
    validate_error(api_client.return_parts_sale_line(line_id, {"quantity": 2}, PARTS_REP),
                   ApiErrorId.ERR_RETURN_EXCEEDS_SOLD)
    line = get_success_data(api_client.get_parts_sale_line(line_id, PARTS_REP))
    assert line["returned_quantity"] == 2


def test_ops_run_checkpoint_restocking_fee_after_30_days(api):
    """PRD §3.9: "credits the line's `return_credit_cents` with the net value
    of the returned units — the `unit_net_price_cents` times the quantity,
    rounded half-up — less a restocking fee of fifteen percent of that value
    when the clock has passed `sold_at` by more than 30 days (no fee within the
    window)."
    PRD §3.9: "When some but not all of a sale's quantities have come back the
    sale sits at `PARTIALLY_RETURNED`".

    Design: Corner/cross_cutting_complexity_layers/ops_run_checkpoint_restocking_fee_after_30_days
    """
    acct = create_account(name="FeeCo")
    part = create_part(sku="FEE-1", list_price_cents=1000, cost_cents=500, on_hand=10)
    sale = create_parts_sale(acct["id"], [{"part_id": part["id"], "quantity": 2}])
    line_id = get_sale_lines(sale["id"])[0]["id"]
    set_clock("2026-09-01T00:00:00Z")  # 31 days after the 2026-08-01 sale
    data = validate_success(api_client.return_parts_sale_line(
        line_id, {"quantity": 1}, PARTS_REP), 200)
    # 1000 - 15% restocking fee (150)
    assert data["return_credit_cents"] == 850
    assert data["returned_quantity"] == 1
    sale_after = get_success_data(api_client.get_parts_sale(sale["id"], PARTS_REP))
    assert sale_after["status"] == "PARTIALLY_RETURNED"


def test_derived_open_ar_reconciles_across_invoice_payment_return(api):
    """PRD §2.9: "The receivable moves only through named events: invoicing a
    repair order adds `customer_due_cents`; ... posting a customer payment
    subtracts the amount paid; a parts sale to a fleet account adds the sale
    total; a parts return credits the fleet account's receivable, floored at
    zero".
    PRD §3.9: "once everything is returned — whether in one call or several —
    it is `FULLY_RETURNED`."

    Design: Corner/cross_cutting_complexity_layers/derived_open_ar_reconciles_across_invoice_payment_return
    """
    acct = create_fleet_account(tier="STANDARD", credit_limit_cents=10000000, name="ArCo")
    ctx = drive_ro_to_invoiced(acct["id"], labor_hours=1.0)  # due 17325
    assert _ar(acct["id"]) == 17325
    part = create_part(sku="AR-1", list_price_cents=1000, cost_cents=500, on_hand=10)
    sale = create_parts_sale(acct["id"], [{"part_id": part["id"], "quantity": 3}])
    assert _ar(acct["id"]) == 20325
    line_id = get_sale_lines(sale["id"])[0]["id"]

    validate_success(api_client.post_ro_payment(
        ctx["ro"]["id"], {"amount_cents": 17325}, CONTROLLER), 200)
    ret = validate_success(api_client.return_parts_sale_line(
        line_id, {"quantity": 3}, PARTS_REP), 200)
    # Within 30 days -> no restocking fee; full credit 3000.
    assert ret["return_credit_cents"] == 3000
    assert _ar(acct["id"]) == 0
    assert get_success_data(api_client.get_part(part["id"], PARTS_REP))["on_hand"] == 10
    assert get_success_data(api_client.get_parts_sale(sale["id"], PARTS_REP))["status"] == "FULLY_RETURNED"
