"""The five-hop close cascade, the invoicing step and the day's roll-ups."""

from test_helpers import (
    ApiErrorId,
    BARN_ADMIN,
    SETTLEMENT_CLERK,
    add_buyer,
    advance_sale_day,
    assert_append_only_fields,
    assert_money,
    assert_settlement_balances,
    assign_pen,
    check_in_consignment,
    close_sale_day,
    create_consignment,
    create_lot,
    enter_ring,
    hammer_lot,
    invoice_for_registration,
    list_charge_lines,
    mark_lot_ready,
    read_buyer_invoice,
    read_consignment,
    read_lot,
    read_purchase,
    read_sale_day,
    read_settlement,
    require_charge_line,
    set_clock,
    settlement_for_consignment,
    setup_checked_in_consignment,
    setup_yard,
    validate_error,
    validate_success,
    weigh_lot,
)


def _closed_day_with_one_sold_and_one_unfinished_lot():
    """15 head: a sold 10-head lot and a 5-head lot still DRAFT when bidding closes.

    The consignment asks for its settlement to be held until funds clear.
    """
    scn = setup_yard()
    scn.consignment = create_consignment(
        scn.sale_day["id"],
        scn.consignor["id"],
        head_received=15,
        pencil_shrink_pct=0.03,
        yardage_basis="PER_HEAD_DAY",
        commission_basis="TIERED_VALUE",
        ration_type="NONE",
        days_on_feed=0,
        advances_amount=0,
        hold_until_funds=True,
    )
    check_in_consignment(scn.consignment["id"])
    scn.lot_a = create_lot(scn.consignment["id"], head_count=10)
    scn.lot_b = create_lot(scn.consignment["id"], head_count=5)
    assign_pen(scn.lot_a["id"], scn.pen["id"])
    weigh_lot(scn.lot_a["id"], scn.scale["id"], gross_weight_lb=7200, tare_weight_lb=200)
    mark_lot_ready(scn.lot_a["id"])

    add_buyer(scn, bond_type="BONDED", credit_limit=50000)
    advance_sale_day(scn.sale_day["id"], "RINGING")
    enter_ring(scn.lot_a["id"])
    scn.lot = scn.lot_a
    hammer_lot(scn, unit_price=182.50)

    advance_sale_day(scn.sale_day["id"], "BIDDING_CLOSED")
    set_clock("2026-06-02T10:00:00Z")
    scn.sale_day = close_sale_day(scn.sale_day["id"])
    scn.settlement = settlement_for_consignment(scn.consignment["id"])
    scn.invoice = invoice_for_registration(scn.registration["id"])
    return scn


def test_close_settles_the_day_finalizes_lots_and_reconciles_consignments(api):
    """PRD §3.10: "**Hop 1 — the day settles.** The sale day transitions
    `BIDDING_CLOSED → SETTLED`."
    PRD §3.10: "**Hop 2 — unfinished lots are finalized.** Caused by hop 1. Every lot
    of this sale day whose `sale_status` is `DRAFT`, `PENNED`, `READY` or `IN_RING`
    transitions to `NO_SALE`, and every bid on each such lot standing at `WINNING`
    transitions to `VOIDED`."
    PRD §3.10: "**Hop 3 — consignments reconcile.** Caused by hop 2's lot
    finalization. Every consignment of this sale day whose `status` is `CHECKED_IN` or
    `SORTED` recomputes `head_sold`, `head_no_saled`, `head_in_lots` and
    `head_balance_ok`, and transitions to `RECONCILED`."

    Design: Difficulty/transitive_cascade/sale_day_close_five_hop_cascade_to_charge_lines
    """
    scn = _closed_day_with_one_sold_and_one_unfinished_lot()

    assert read_sale_day(scn.sale_day["id"])["status"] == "SETTLED"
    assert read_lot(scn.lot_b["id"])["sale_status"] == "NO_SALE"

    consignment = read_consignment(scn.consignment["id"])
    assert consignment["status"] == "RECONCILED"
    assert consignment["head_sold"] == 10
    assert consignment["head_no_saled"] == 5
    assert consignment["head_balance_ok"] is True


def test_close_opens_a_held_settlement_and_prices_its_charge_lines(api):
    """PRD §3.10: "**Hop 4 — settlements are opened.** Caused by hop 3's
    reconciliation. One settlement row is created for each `RECONCILED` consignment,
    copying `consignment_id` and `consignor_party_id`. When the consignment's
    `hold_until_funds` is true the settlement opens at `HELD` with `hold_reason`
    `AWAITING_FUNDS`; otherwise it opens at `DRAFT` with `hold_reason` `NONE`."
    PRD §3.10: "On a tiered-value basis a rate is selected from the gross and then
    applied to the **whole** gross, not marginally: 5% when the gross is at most
    1000.00, 4% when it is above 1000.00 and at most 5000.00, and 3% above 5000.00."
    PRD §3.10: "On a per-head-day basis the charge is 1.75 dollars multiplied by
    billable head multiplied by the day count, rounded half up to two decimal places, so
    a stay of two days costs twice a stay of one."
    PRD §3.10: "The state share is 0.50 dollars multiplied by sold head, rounded half
    up to two decimal places; the national share is computed identically;
    `statutory_amount` is the two shares added together, and the two are written as
    separate charge lines."

    Design: Difficulty/transitive_cascade/sale_day_close_five_hop_cascade_to_charge_lines
    """
    scn = _closed_day_with_one_sold_and_one_unfinished_lot()
    settlement = read_settlement(scn.settlement["id"])

    assert settlement["status"] == "HELD"
    assert settlement["hold_reason"] == "AWAITING_FUNDS"
    assert_money(settlement["gross_amount"], 12391.75, "gross from the one SOLD lot:")
    assert_money(settlement["net_amount"], 11926.91, "net proceeds after every deduction:")

    lines = list_charge_lines(settlement_id=settlement["id"])
    assert_money(
        require_charge_line(lines, "COMMISSION")["amount"], 371.75, "3% of the gross:"
    )
    yardage = require_charge_line(lines, "YARDAGE")
    assert_money(yardage["amount"], 52.50, "1.75 x 15 billable head x 2 days:")
    assert yardage["head"] == 15
    assert yardage["days"] == 2
    assert_money(
        require_charge_line(lines, "CHECKOFF_STATE")["amount"], 5.00, "0.50 x 10 sold head:"
    )
    assert_money(
        require_charge_line(lines, "CHECKOFF_NATIONAL")["amount"], 5.00, "0.50 x 10 sold head:"
    )
    assert_money(
        require_charge_line(lines, "BRAND_FEE")["amount"], 12.00, "1.20 x 10 sold head:"
    )
    assert_money(
        require_charge_line(lines, "INDEMNITY_FEE")["amount"], 18.59, "0.0015 of the gross:"
    )


def test_close_issues_the_buyer_invoice_and_the_days_books_reconcile(api):
    """PRD §3.10: "Before hop 4 runs, and in the evaluation order that the settlement
    offset depends on, every buyer invoice of this sale day standing at `DRAFT`
    transitions to `ISSUED`. On each one, a `BUYER_FEE` charge line is appended on the
    buyer side, and `buyer_fee`, `total_due` and `balance_due` are computed; every
    purchase on that invoice standing at `CONFIRMED` transitions to `INVOICED`."
    PRD §3.10: "For a `BONDED` or `UNSECURED` buyer it is a bond-processing charge:
    the invoice `subtotal` multiplied by 0.0025, rounded half up to two decimal places,
    capped at 150.00 — it scales with the money bought."
    PRD §2.10: "A sale day's `money_reconciliation_ok` is true when the total
    `total_due` across its buyer invoices equals the total `net_amount` across its
    settlements, plus the total `amount` of every charge line of the sale day on both
    sides excluding lines whose `charge_type` is `DOA_CREDIT`, plus the total
    `advances_amount` across its settlements, plus the total `offset_applied` across its
    settlements, minus the total `credit_memo_total` across its buyer invoices."

    Design: Difficulty/transitive_cascade/sale_day_close_five_hop_cascade_to_charge_lines
    """
    scn = _closed_day_with_one_sold_and_one_unfinished_lot()

    invoice = read_buyer_invoice(scn.invoice["id"])
    assert invoice["status"] == "ISSUED"
    assert_money(invoice["subtotal"], 12391.75, "invoice subtotal:")
    assert_money(invoice["buyer_fee"], 30.98, "0.0025 of the subtotal:")
    assert_money(invoice["total_due"], 12422.73, "subtotal plus the bond fee:")
    assert read_purchase(scn.purchase["id"])["status"] == "INVOICED"

    sale_day = read_sale_day(scn.sale_day["id"])
    assert sale_day["money_reconciliation_ok"] is True
    assert sale_day["head_reconciliation_ok"] is True
    assert_settlement_balances(read_settlement(scn.settlement["id"]))


def test_a_stay_of_exactly_twenty_four_hours_counts_as_one_yardage_day(api):
    """PRD §3.10: "The elapsed seconds are divided by 86400 and the result is rounded
    **up** to a whole day — a partial day always counts as a full day — and the count is
    never fewer than 1 day even for a stay of minutes."
    PRD §3.10: "**Days on the yard** are counted from the consignment's
    `checked_in_at` to an end instant."
    PRD §3.10: "On a per-head-day basis the charge is 1.75 dollars multiplied by
    billable head multiplied by the day count, rounded half up to two decimal places, so
    a stay of two days costs twice a stay of one."

    Design: Corner/calculations/corner_days_on_yard_exactly_twenty_four_hours_counts_as_one_day
    """
    scn = setup_checked_in_consignment(
        head_received=10,
        with_pen=False,
        with_scale=False,
        consignment_overrides={"yardage_basis": "PER_HEAD_DAY"},
    )
    create_lot(scn.consignment["id"], head_count=10)
    advance_sale_day(scn.sale_day["id"], "RINGING")
    advance_sale_day(scn.sale_day["id"], "BIDDING_CLOSED")
    set_clock("2026-06-02T08:00:00Z")
    close_sale_day(scn.sale_day["id"])

    settlement = settlement_for_consignment(scn.consignment["id"])
    assert_money(settlement["yardage_amount"], 17.50, "1.75 x 10 head x exactly one day:")
    assert_money(settlement["net_amount"], -17.50, "nothing sold, so the yardage stands alone:")

    lines = list_charge_lines(settlement_id=settlement["id"], charge_type="YARDAGE")
    yardage = require_charge_line(lines, "YARDAGE")
    assert yardage["days"] == 1
    assert yardage["head"] == 10
    assert_money(yardage["unit_rate"], 1.75, "the per-head-day rate on the line:")


def test_charge_lines_are_append_only_rows_with_no_version(api):
    """PRD §2.4: "Two resources are deliberately leaner: a `ChargeLine` and a
    `LoadLine` carry only `id` and `created_at` — they have neither `updated_at` nor
    `version`, because they are append-and-regenerate artifacts rather than
    independently edited records."
    PRD §2.11: "`COMMISSION`, `YARDAGE`, `FEED` and `INDEMNITY_FEE` are `SELLER`-side
    `BARN_REVENUE`."
    PRD §2.11: "Every charge the barn books is a `ChargeLine`, and each line records
    the `sale_day_id` it belongs to, the `settlement_id` it sits on (null on buyer-side
    lines), the `buyer_invoice_id` it sits on (null on seller-side lines), the `lot_id`
    it was priced against (null on consignment-level lines such as yardage and feed),
    the `head` and `days` it was priced on (zero when the line is not priced that way),
    the `unit_rate` constant used so the line is auditable without re-reading a rate
    table, and the signed `amount`."

    Design: Corner/entities/corner_charge_line_is_append_only_with_no_version_field
    """
    scn = setup_checked_in_consignment(head_received=10, with_pen=False, with_scale=False)
    create_lot(scn.consignment["id"], head_count=10)
    advance_sale_day(scn.sale_day["id"], "RINGING")
    advance_sale_day(scn.sale_day["id"], "BIDDING_CLOSED")
    set_clock("2026-06-01T20:00:00Z")
    close_sale_day(scn.sale_day["id"])

    lines = list_charge_lines(sale_day_id=scn.sale_day["id"])
    assert lines, "the close cascade appends the seller-side charge lines"
    for line in lines:
        assert_append_only_fields(line)

    yardage = require_charge_line(lines, "YARDAGE")
    assert yardage["side"] == "SELLER"
    assert yardage["revenue_class"] == "BARN_REVENUE"
    assert yardage["head"] == 10
    assert yardage["days"] == 1
    assert_money(yardage["unit_rate"], 1.75, "the per-head-day rate on the line:")
    assert_money(yardage["amount"], 17.50, "1.75 x 10 head x one day:")

    single = validate_success(api.get_charge_line(yardage["id"], SETTLEMENT_CLERK))
    assert_append_only_fields(single)


def test_cash_only_buyer_fee_and_flat_yardage_are_the_selected_variants(api):
    """PRD §3.10: "For a `CASH_ONLY` buyer it is a cash-handling charge instead: 0.75
    dollars for every invoiced head, rounded half up to two decimal places, with a floor
    of 5.00 — where invoiced head is the total `head_count` across the invoice's
    purchases whose status is `CONFIRMED`, `INVOICED`, `ADJUSTED` or `PAID`."
    PRD §3.10: "On a flat-per-head basis it is 5.00 dollars multiplied by billable
    head, rounded half up to two decimal places, ignoring the day count entirely — so the
    same stay produces a different number under the two bases."
    PRD §3.7: "The multiplier is 1.5 for a `BONDED` buyer, 1.0 for an `UNSECURED`
    buyer, and 0.0 for a `CASH_ONLY` buyer — meaning a cash-only bidder's whole line is
    the cash they posted plus any override, and their nominal credit line counts for
    nothing."
    PRD §3.10: "Only `SOLD` head count — no-sale head, withdrawn head, death loss and
    condemned head are all excluded."

    Design: Corner/calculations/corner_cash_only_buyer_fee_and_flat_yardage_variants_selected
    """
    scn = setup_yard()
    scn.consignment = create_consignment(
        scn.sale_day["id"],
        scn.consignor["id"],
        head_received=15,
        pencil_shrink_pct=0.03,
        yardage_basis="FLAT_PER_HEAD",
        commission_basis="TIERED_VALUE",
        ration_type="NONE",
        days_on_feed=0,
    )
    check_in_consignment(scn.consignment["id"])
    scn.lot_a = create_lot(scn.consignment["id"], head_count=10)
    scn.lot_b = create_lot(scn.consignment["id"], head_count=5)
    assign_pen(scn.lot_a["id"], scn.pen["id"])
    weigh_lot(scn.lot_a["id"], scn.scale["id"], gross_weight_lb=7200, tare_weight_lb=200)
    mark_lot_ready(scn.lot_a["id"])

    add_buyer(
        scn,
        bond_type="CASH_ONLY",
        credit_limit=0,
        buyer_number=55,
        cash_deposit_amount=20000,
        buyer_party_overrides={
            "legal_name": "Cash Corner Cattle",
            "party_type": "INDIVIDUAL",
            "origin_county": "Custer",
            "tax_id": "47-7777777",
        },
    )
    assert_money(
        scn.registration["effective_limit"],
        20000.00,
        "a cash-only line is the deposit alone:",
    )

    advance_sale_day(scn.sale_day["id"], "RINGING")
    enter_ring(scn.lot_a["id"])
    scn.lot = scn.lot_a
    hammer_lot(scn, unit_price=182.50)
    advance_sale_day(scn.sale_day["id"], "BIDDING_CLOSED")
    set_clock("2026-06-02T10:00:00Z")
    close_sale_day(scn.sale_day["id"])

    invoice = read_buyer_invoice(scn.invoice["id"])
    assert_money(invoice["buyer_fee"], 7.50, "0.75 for every one of 10 invoiced head:")
    assert_money(invoice["subtotal"], 12391.75, "invoice subtotal:")
    assert_money(invoice["total_due"], 12399.25, "subtotal plus the cash-handling fee:")

    settlement = settlement_for_consignment(scn.consignment["id"])
    assert_money(settlement["yardage_amount"], 75.00, "5.00 x 15 billable head, no day count:")
    assert_money(settlement["commission_amount"], 371.75, "3% of the gross:")
    assert_money(settlement["statutory_amount"], 10.00, "1.00 for every sold head:")
    assert_money(settlement["brand_fee_amount"], 12.00, "1.20 x 10 sold head:")
    assert_money(settlement["indemnity_fee_amount"], 18.59, "0.0015 of the gross:")
    assert_money(settlement["net_amount"], 11904.41, "net proceeds:")
    assert settlement["status"] == "DRAFT"
    assert settlement["hold_reason"] == "NONE"
    assert read_sale_day(scn.sale_day["id"])["money_reconciliation_ok"] is True


def test_a_settled_sale_day_admits_no_further_advance(api):
    """PRD §3.2: "`SETTLED` and `CANCELLED` are both terminal."
    PRD §3.2: "The day is not necessarily finished at that point: `BIDDING_CLOSED →
    RINGING` reopens the ring, increments `reopen_count` by one and switches gate G3
    back off."

    Design: Corner/state_machines/corner_settled_sale_day_rejects_further_advance
    """
    scn = setup_checked_in_consignment(head_received=10, with_pen=False, with_scale=False)
    create_lot(scn.consignment["id"], head_count=10)
    advance_sale_day(scn.sale_day["id"], "RINGING")
    advance_sale_day(scn.sale_day["id"], "BIDDING_CLOSED")
    set_clock("2026-06-01T20:00:00Z")
    close_sale_day(scn.sale_day["id"])

    response = api.advance_sale_day(
        scn.sale_day["id"], {"to_status": "RINGING"}, BARN_ADMIN
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    sale_day = read_sale_day(scn.sale_day["id"])
    assert sale_day["status"] == "SETTLED"
    assert sale_day["reopen_count"] == 0
