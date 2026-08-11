"""Invoice construction, the shared-well split and the account ledger."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_close,
    assert_money,
    fixtures,
    find_where,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def _loyalty_world():
    """A PREMIER emergency job whose pre-discount pre-tax figure clears 200000."""
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Harborview Ranch",
        email="ap@harborview.example",
        membership_tier="PREMIER",
        address_line="3 Harborview Rd",
        distance_miles=20.0,
        household_size=5,
        has_vulnerable_occupant=False,
        depth_feet=260.0,
        drawdown=8.0,
        technician_tier="MASTER",
        technician_name="Priya Raman",
    )
    part = fixtures.new_part("CTL-100001", "CONTROL", 100001, on_hand_qty=5)
    ticket = fixtures.diagnosed_ticket(
        world["property_id"],
        world["well_id"],
        world["account_id"],
        world["technician_id"],
        "PRESSURE_TANK_FAILURE",
        300000,
        5.0,
    )
    fixtures.authorize_ticket(ticket["id"], world["account_id"])
    work_order = fixtures.new_work_order(
        world["property_id"], world["well_id"], world["technician_id"], "REPAIR",
        emergency_ticket_id=ticket["id"],
    )
    fixtures.schedule_work_order(
        work_order["id"], "2026-06-03T12:00:00Z", "2026-06-03T14:00:00Z"
    )
    fixtures.set_clock("2026-06-03T12:00:00Z")
    fixtures.start_work_order(work_order["id"], world["technician_id"])
    fixtures.post_parts(work_order["id"], world["technician_id"], part["id"], 2)
    fixtures.complete_work_order(work_order["id"], world["technician_id"], 60)
    world.update({"ticket_id": ticket["id"], "work_order_id": work_order["id"]})
    return world


def test_the_loyalty_discount_eligibility_reads_the_pre_discount_figure(api):
    """PRD 3.11: "The loyalty discount is eligible when the account's `membership_tier` is
    one of `SELECT` or `PREMIER` **and** the pre-discount pre-tax figure from step 6 is at
    least `LOYALTY_DISCOUNT_MIN_PRETAX_CENTS` (200000 cents), the threshold being
    inclusive. When eligible, `loyalty_discount_cents` is `LOYALTY_DISCOUNT_PCT` (5.00
    percent) of the **parts** figure, rounded half up, expressed as a positive number;
    otherwise it is 0. This is the pinned resolution of the circular-looking dependency
    between the discount and the total: the eligibility test reads the pre-discount figure
    and is never revisited."
    PRD 3.11: "`taxable_subtotal_cents` is the parts figure less the parts warranty credit
    less the loyalty discount, floored at 0."

    Design: Difficulty/combinatorial_formula/loyalty_discount_mode_c_eligibility_reads_pre_discount_total
    """
    world = _loyalty_world()
    invoice = fixtures.first_invoice_of(world["work_order_id"])
    assert invoice["variant"] == "ACTUAL_FINAL"
    assert_money(invoice["parts_subtotal_cents"], 236002, "Invoice.parts_subtotal_cents")
    assert_money(invoice["loyalty_discount_cents"], 11800, "Invoice.loyalty_discount_cents")
    assert_money(
        invoice["taxable_subtotal_cents"], 224202, "Invoice.taxable_subtotal_cents"
    )
    assert_money(invoice["tax_cents"], 16255, "Invoice.tax_cents")
    assert_money(invoice["total_cents"], 270457, "Invoice.total_cents")


def test_the_dispatch_figure_carries_the_membership_credit_into_the_invoice(api):
    """PRD 3.11: "The dispatch figure is 0 when the pipeline is `SCHEDULED`. On the
    emergency pipeline it is the ticket's `net_dispatch_charge_cents` plus the property's
    trip fee from its `service_zone` band."
    PRD 3.8: "**Authorising** takes `PENDING → AUTHORIZED`; it may only be performed by
    the account named on the ticket, and the account's `credit_hold` must be false or the
    answer is `ERR_ACCOUNT_ON_CREDIT_HOLD`."
    PRD 3.5: "The base rates are 6500 cents an hour for `APPRENTICE`, 9500 for
    `JOURNEYMAN` and 13500 for `MASTER`."

    Design: Difficulty/combinatorial_formula/loyalty_discount_mode_c_eligibility_reads_pre_discount_total
    """
    world = _loyalty_world()
    ticket = fixtures.get_ticket(world["ticket_id"])
    assert_money(
        ticket["net_dispatch_charge_cents"],
        4000,
        "EmergencyTicket.net_dispatch_charge_cents",
    )
    assert ticket["authorization_status"] == "AUTHORIZED"

    invoice = fixtures.first_invoice_of(world["work_order_id"])
    assert_money(
        invoice["dispatch_subtotal_cents"], 16500, "Invoice.dispatch_subtotal_cents"
    )
    assert_money(invoice["labor_subtotal_cents"], 13500, "Invoice.labor_subtotal_cents")


def _settled_invoice_world():
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Fernbank Holdings",
        email="ap@fernbank.example",
        membership_tier="NONE",
        account_jurisdiction="JUR_BRAVO",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="6 Fernbank",
        drawdown=8.0,
        technician_name="Kit Alvarez",
    )
    part = fixtures.new_part("CTL-3000", "CONTROL", 3000, on_hand_qty=20)
    stage = fixtures.completed_emergency_work_order(
        world, part_id=part["id"], quantity=1, actual_labor_minutes=60
    )
    world["work_order_id"] = stage["work_order_id"]
    world["invoice_id"] = fixtures.first_invoice_of(stage["work_order_id"])["id"]
    return world


def test_the_billing_axis_walks_while_the_fulfilment_axis_stands_still(api):
    """PRD 3.9: "The billing axis also moves without any request of its own:
    `PENDING_INVOICE → INVOICED` when the linked invoice is issued, `INVOICED → SETTLED`
    when that invoice is paid in full, and `INVOICED → WRITTEN_OFF` when that invoice is
    voided."
    PRD 3.9: "A completed work order can sit at `PENDING_INVOICE` indefinitely, and a
    cancelled one can still be written off."

    Design: Difficulty/non_linear_state_machine/work_order_billing_axis_advances_while_fulfillment_axis_stays_completed
    """
    world = _settled_invoice_world()
    before = fixtures.get_work_order(world["work_order_id"])
    assert before["fulfillment_status"] == "COMPLETED"
    assert before["billing_status"] == "PENDING_INVOICE"

    issued = validate_success(api.issue_invoice(world["invoice_id"], BILLING))
    invoiced = fixtures.get_work_order(world["work_order_id"])
    assert invoiced["fulfillment_status"] == "COMPLETED"
    assert invoiced["billing_status"] == "INVOICED"

    paid = validate_success(
        api.record_payment(
            world["invoice_id"],
            {"amount_cents": 37148, "expected_invoice_version": issued["version"]},
            BILLING,
        )
    )
    assert paid["status"] == "PAID_IN_FULL"
    settled = fixtures.get_work_order(world["work_order_id"])
    assert settled["fulfillment_status"] == "COMPLETED"
    assert settled["billing_status"] == "SETTLED"


def test_paying_an_emergency_invoice_in_full_clears_the_account_balance(api):
    """PRD 3.11: "Every payment adds its amount to `amount_paid_cents` and to the account's
    `lifetime_paid_cents`, subtracts it from `balance_cents`, re-derives `credit_hold`, and
    raises the invoice's and the account's `version` by 1 — plus the work order's when the
    invoice settles."
    PRD 3.11: "The invoice moves `DRAFT → ISSUED`, `issued_at` is stamped from the logical
    clock, the account's `balance_cents` and `lifetime_invoiced_cents` each rise by the
    invoice's `total_cents`, `credit_hold` is re-derived, the work order's billing axis
    moves `PENDING_INVOICE → INVOICED`, and the invoice's, the account's and the work
    order's `version` each rise by 1."

    Design: Difficulty/non_linear_state_machine/work_order_billing_axis_advances_while_fulfillment_axis_stays_completed
    """
    world = _settled_invoice_world()
    invoice = fixtures.get_invoice(world["invoice_id"])
    assert_money(invoice["parts_subtotal_cents"], 4800, "Invoice.parts_subtotal_cents")
    assert_money(invoice["labor_subtotal_cents"], 9500, "Invoice.labor_subtotal_cents")
    assert_money(
        invoice["dispatch_subtotal_cents"], 22500, "Invoice.dispatch_subtotal_cents"
    )
    assert_money(invoice["tax_cents"], 348, "Invoice.tax_cents")
    assert_money(invoice["total_cents"], 37148, "Invoice.total_cents")

    issued = fixtures.issue_invoice(world["invoice_id"])
    fixtures.pay_invoice(world["invoice_id"], 37148, issued["version"])

    account = fixtures.get_account(world["account_id"])
    assert_money(account["balance_cents"], 0, "Account.balance_cents")
    assert_money(
        account["lifetime_invoiced_cents"], 37148, "Account.lifetime_invoiced_cents"
    )
    assert_money(account["lifetime_paid_cents"], 37148, "Account.lifetime_paid_cents")


def _conserved_money_world():
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Balance Point Ltd",
        email="ap@balancepoint.example",
        membership_tier="NONE",
        account_jurisdiction="JUR_BRAVO",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="0 Balance Point",
        drawdown=8.0,
        technician_name="Ruth Iyer",
    )
    part = fixtures.new_part("CTL-3000-D", "CONTROL", 3000, on_hand_qty=20)
    stage = fixtures.completed_emergency_work_order(
        world, part_id=part["id"], quantity=1, actual_labor_minutes=60
    )
    world["work_order_id"] = stage["work_order_id"]
    world["invoice_id"] = fixtures.first_invoice_of(stage["work_order_id"])["id"]
    return world


def test_the_account_balance_returns_to_zero_after_a_void(api):
    """PRD 2.12: "An account's `balance_cents` equals the sum, over that account's invoices
    whose status is `ISSUED`, `PARTIALLY_PAID` or `PAID_IN_FULL`, of the invoice's
    `total_cents` less its `amount_paid_cents`. Invoices in `DRAFT` and `VOID` are
    excluded. Issuing is the forward action; voiding is the compensating action and
    removes exactly what issuing and paying added."
    PRD 3.11: "The account's `balance_cents` falls by `total_cents` less
    `amount_paid_cents`, `lifetime_invoiced_cents` falls by `total_cents` and
    `lifetime_paid_cents` falls by `amount_paid_cents`, restoring the balance identity of
    Section 2.12 exactly."

    Design: Difficulty/compensating_invariant/account_money_conserved_across_invoice_issue_partial_payment_and_void
    """
    world = _conserved_money_world()
    assert_money(
        fixtures.get_account(world["account_id"])["balance_cents"],
        0,
        "Account.balance_cents",
    )

    issued = fixtures.issue_invoice(world["invoice_id"])
    assert_money(
        fixtures.get_account(world["account_id"])["balance_cents"],
        37148,
        "Account.balance_cents",
    )

    fixtures.pay_invoice(world["invoice_id"], 10000, issued["version"])
    assert_money(
        fixtures.get_account(world["account_id"])["balance_cents"],
        27148,
        "Account.balance_cents",
    )

    validate_success(api.void_invoice(world["invoice_id"], BILLING))
    account = fixtures.get_account(world["account_id"])
    assert_money(account["balance_cents"], 0, "Account.balance_cents")
    assert_money(account["lifetime_invoiced_cents"], 0, "Account.lifetime_invoiced_cents")
    assert_money(account["lifetime_paid_cents"], 0, "Account.lifetime_paid_cents")


def test_a_void_keeps_the_paid_amount_as_a_historical_record(api):
    """PRD 3.11: "`amount_paid_cents` is deliberately **left on the invoice** as a
    historical record. `credit_hold` is re-derived, the work order's billing axis moves
    `INVOICED → WRITTEN_OFF`, and the invoice's, the account's and the work order's
    `version` each rise by 1."
    PRD 2.12: "On every write that touches `balance_cents`, `credit_hold` is re-derived as
    true when `balance_cents` is **strictly greater** than `CREDIT_HOLD_THRESHOLD_CENTS`
    (500000 cents) and false otherwise; a balance of exactly 500000 does not put an
    account on hold."

    Design: Difficulty/compensating_invariant/account_money_conserved_across_invoice_issue_partial_payment_and_void
    """
    world = _conserved_money_world()
    issued = fixtures.issue_invoice(world["invoice_id"])
    fixtures.pay_invoice(world["invoice_id"], 10000, issued["version"])
    voided = validate_success(api.void_invoice(world["invoice_id"], BILLING))

    assert voided["status"] == "VOID"
    assert_money(voided["total_cents"], 37148, "Invoice.total_cents")
    assert_money(voided["amount_paid_cents"], 10000, "Invoice.amount_paid_cents")
    assert fixtures.get_account(world["account_id"])["credit_hold"] is False
    assert (
        fixtures.get_work_order(world["work_order_id"])["billing_status"] == "WRITTEN_OFF"
    )


def test_the_shared_well_split_sends_the_whole_remainder_to_the_earliest_share(api):
    """PRD 3.11: "Each share's raw amount is the undivided total multiplied by that share's
    `split_pct` divided by 100, taking the **floor**, and the whole remainder — the
    undivided total less the sum of the floored amounts — is added to the **first** share
    by `created_at` ascending, never by `id`. This guarantees the shares add back to the
    undivided total exactly."
    PRD 3.11: "Otherwise one invoice is written per share."

    Design: Corner/calculations/corner_shared_well_split_sends_the_whole_remainder_to_the_earliest_share
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account_a = fixtures.new_account("Split A", "JUR_BRAVO", "sa@corner.example")
    account_b = fixtures.new_account("Split B", "JUR_BRAVO", "sb@corner.example")
    account_c = fixtures.new_account("Split C", "JUR_BRAVO", "sc2@corner.example")
    prop = fixtures.new_property(account_a["id"], "33 Split", "JUR_BRAVO", 20.0, 3)
    well = fixtures.new_well(prop["id"], "JUR_BRAVO", "DRILLED", 200.0)
    fixtures.new_shared_well_agreement(well["id"], account_a["id"], 33.33)
    fixtures.new_shared_well_agreement(well["id"], account_b["id"], 33.33)
    fixtures.new_shared_well_agreement(well["id"], account_c["id"], 33.34)
    technician = fixtures.new_technician("Split Tech", "JOURNEYMAN", "JUR_BRAVO")

    ticket = fixtures.diagnosed_ticket(
        prop["id"], well["id"], account_a["id"], technician["id"], "NON_WELL_CAUSE", 10000
    )
    work_order = fixtures.new_work_order(
        prop["id"], well["id"], technician["id"], "REPAIR",
        emergency_ticket_id=ticket["id"],
    )
    fixtures.schedule_work_order(
        work_order["id"], "2026-06-01T12:00:00Z", "2026-06-01T14:00:00Z"
    )
    fixtures.set_clock("2026-06-01T12:00:00Z")
    fixtures.start_work_order(work_order["id"], technician["id"])
    validate_success(
        api.complete_work_order(
            work_order["id"],
            {"actual_labor_minutes": 60},
            fixtures.make_technician_headers(technician["id"]),
        )
    )

    invoices = fixtures.invoices_of(work_order["id"])
    assert len(invoices) == 3
    first = find_where(invoices, account_id=account_a["id"])
    second = find_where(invoices, account_id=account_b["id"])
    third = find_where(invoices, account_id=account_c["id"])
    assert_money(first["total_cents"], 7334, "Invoice.total_cents")
    assert_close(first["shared_split_pct"], 33.33, "Invoice.shared_split_pct")
    assert_money(second["total_cents"], 7332, "Invoice.total_cents")
    assert_close(second["shared_split_pct"], 33.33, "Invoice.shared_split_pct")
    assert_money(third["total_cents"], 7334, "Invoice.total_cents")
    assert_close(third["shared_split_pct"], 33.34, "Invoice.shared_split_pct")
    assert sum(invoice["total_cents"] for invoice in invoices) == 22000


def test_the_payment_gates_and_the_credit_hold_each_own_their_error(api):
    """PRD 3.11: "**Payments** are recorded by a `BillingClerk` against an `ISSUED` or
    `PARTIALLY_PAID` invoice, supplying `amount_cents` and `expected_invoice_version`. A
    zero amount passes the payload gate — it is not negative — and is refused at the
    business gate with `ERR_PAYMENT_AMOUNT_INVALID`. An amount greater than the
    outstanding balance, meaning `total_cents` less `amount_paid_cents`, is refused with
    `ERR_PAYMENT_EXCEEDS_BALANCE`."
    PRD 3.11: "The invoice lifecycle runs `DRAFT`, `ISSUED`, `PARTIALLY_PAID`,
    `PAID_IN_FULL` and `VOID`, the last two terminal; a transition from the wrong state is
    `ERR_INVOICE_INVALID_STATE`."
    PRD 3.8: "**Authorising** takes `PENDING → AUTHORIZED`; it may only be performed by
    the account named on the ticket, and the account's `credit_hold` must be false or the
    answer is `ERR_ACCOUNT_ON_CREDIT_HOLD`."

    Design: Corner/errors/corner_invoice_payment_gates_and_credit_hold_rejected
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Hold Co", "JUR_BRAVO", "hc@corner.example", "NONE")
    prop = fixtures.new_property(account["id"], "11 Hold", "JUR_BRAVO", 10.0, 3)
    well_1 = fixtures.new_well(prop["id"], "JUR_BRAVO", "DRILLED", 200.0)
    well_2 = fixtures.new_well(prop["id"], "JUR_BRAVO", "DRILLED", 210.0)
    technician = fixtures.new_technician("Hold Tech", "JOURNEYMAN", "JUR_BRAVO")
    part = fixtures.new_part("CTL-500000-B", "CONTROL", 500000, on_hand_qty=5)

    ticket_1 = fixtures.diagnosed_ticket(
        prop["id"], well_1["id"], account["id"], technician["id"], "CONTROL_FAILURE", 700000
    )
    fixtures.authorize_ticket(ticket_1["id"], account["id"])
    work_order = fixtures.new_work_order(
        prop["id"], well_1["id"], technician["id"], "REPAIR",
        emergency_ticket_id=ticket_1["id"],
    )
    fixtures.schedule_work_order(
        work_order["id"], "2026-06-01T12:00:00Z", "2026-06-01T14:00:00Z"
    )
    fixtures.set_clock("2026-06-01T12:00:00Z")
    fixtures.start_work_order(work_order["id"], technician["id"])
    fixtures.post_parts(work_order["id"], technician["id"], part["id"], 1)
    fixtures.complete_work_order(work_order["id"], technician["id"], 60)
    invoice = fixtures.first_invoice_of(work_order["id"])

    ticket_2 = fixtures.diagnosed_ticket(
        prop["id"], well_2["id"], account["id"], technician["id"], "PUMP_FAILURE", 200000
    )

    validate_error(
        api.record_payment(
            invoice["id"],
            {"amount_cents": 1000, "expected_invoice_version": invoice["version"]},
            BILLING,
        ),
        ApiErrorId.ERR_INVOICE_INVALID_STATE.value,
        409,
    )
    assert_money(invoice["total_cents"], 664775, "Invoice.total_cents")

    issued = validate_success(api.issue_invoice(invoice["id"], BILLING))
    validate_error(
        api.record_payment(
            invoice["id"],
            {"amount_cents": 0, "expected_invoice_version": issued["version"]},
            BILLING,
        ),
        ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID.value,
        400,
    )
    validate_error(
        api.record_payment(
            invoice["id"],
            {"amount_cents": 664776, "expected_invoice_version": issued["version"]},
            BILLING,
        ),
        ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value,
        422,
    )

    account_row = fixtures.get_account(account["id"])
    assert_money(account_row["balance_cents"], 664775, "Account.balance_cents")
    assert account_row["credit_hold"] is True

    validate_error(
        api.authorize_ticket(ticket_2["id"], fixtures.make_customer_headers(account["id"])),
        ApiErrorId.ERR_ACCOUNT_ON_CREDIT_HOLD.value,
        402,
    )
    assert fixtures.get_ticket(ticket_2["id"])["authorization_status"] == "PENDING"


def test_the_payment_ladder_answers_occ_then_payload_then_business(api):
    """PRD 2.8: "Recording a payment against an invoice requires `expected_invoice_version`
    carrying the client's last observed `version` of that `Invoice`. A mismatch is rejected
    with `ERR_STALE_INVOICE_VERSION` (HTTP 412)."
    PRD 2.6: "A stale `expected_quote_version` accompanying an out-of-range `quantity` gets
    `ERR_STALE_QUOTE_VERSION` (G7), because concurrency is checked before payload."
    PRD 2.7: "`ERR_NEGATIVE_QUANTITY` (HTTP 400) is raised when a quantity, amount or
    pounds body field is **strictly** negative. Zero passes this gate. The closed set of
    endpoints and fields is: `quantity` on a parts-consumption posting and on a quote line;
    `delivered_lbs` on a salt delivery; and `amount_cents` on a payment. A zero payment
    amount therefore passes G8 and is adjudicated later, at G9, with
    `ERR_PAYMENT_AMOUNT_INVALID`."

    Design: Corner/errors/corner_error_payment_gate_ordering_occ_then_payload_then_business
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Payment Gate Co",
        email="pg@corner.example",
        address_line="412 Payment",
        technician_name="Payment Tech",
    )
    part = fixtures.new_part("CTL-5000-P", "CONTROL", 5000, on_hand_qty=10)
    stage = fixtures.completed_emergency_work_order(
        world, part_id=part["id"], quantity=2, actual_labor_minutes=60
    )
    invoice = fixtures.first_invoice_of(stage["work_order_id"])
    issued = fixtures.issue_invoice(invoice["id"])
    current = issued["version"]

    validate_error(
        api.record_payment(
            invoice["id"],
            {"amount_cents": -5, "expected_invoice_version": current - 1},
            BILLING,
        ),
        ApiErrorId.ERR_STALE_INVOICE_VERSION.value,
        412,
    )
    validate_error(
        api.record_payment(
            invoice["id"], {"amount_cents": -5, "expected_invoice_version": current}, BILLING
        ),
        ApiErrorId.ERR_NEGATIVE_QUANTITY.value,
        400,
    )
    validate_error(
        api.record_payment(
            invoice["id"], {"amount_cents": 0, "expected_invoice_version": current}, BILLING
        ),
        ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID.value,
        400,
    )

    stored = fixtures.get_invoice(invoice["id"])
    assert_money(stored["total_cents"], 49160, "Invoice.total_cents")
    assert stored["status"] == "ISSUED"
    assert_money(stored["amount_paid_cents"], 0, "Invoice.amount_paid_cents")
    assert stored["version"] == current

    account = fixtures.get_account(world["account_id"])
    assert_money(account["balance_cents"], 49160, "Account.balance_cents")
    assert account["credit_hold"] is False


def test_credit_hold_latches_above_the_threshold_and_clears_below_it(api):
    """PRD 2.12: "On every write that touches `balance_cents`, `credit_hold` is re-derived
    as true when `balance_cents` is **strictly greater** than `CREDIT_HOLD_THRESHOLD_CENTS`
    (500000 cents) and false otherwise; a balance of exactly 500000 does not put an account
    on hold."
    PRD 3.11: "An amount strictly between zero and the outstanding balance takes the invoice
    `ISSUED → PARTIALLY_PAID`, or leaves a `PARTIALLY_PAID` invoice in `PARTIALLY_PAID` —
    repeated part payments are legitimate, which is exactly why this endpoint carries
    concurrency control."

    Design: Corner/cross_cutting_complexity_layers/corner_rate_threshold_credit_hold_flips_only_above_the_threshold
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Credit Hold Co",
        email="ch@corner.example",
        membership_tier="NONE",
        address_line="500000 Credit",
        technician_tier="MASTER",
        technician_name="Credit Tech",
    )
    part = fixtures.new_part("CTL-100001-C", "CONTROL", 100001, on_hand_qty=10)
    ticket = fixtures.diagnosed_ticket(
        world["property_id"],
        world["well_id"],
        world["account_id"],
        world["technician_id"],
        "CONTROL_FAILURE",
        700000,
    )
    fixtures.authorize_ticket(ticket["id"], world["account_id"])
    work_order = fixtures.new_work_order(
        world["property_id"], world["well_id"], world["technician_id"], "REPAIR",
        emergency_ticket_id=ticket["id"],
    )
    fixtures.schedule_work_order(
        work_order["id"], "2026-06-01T12:00:00Z", "2026-06-01T14:00:00Z"
    )
    fixtures.set_clock("2026-06-01T12:00:00Z")
    fixtures.start_work_order(work_order["id"], world["technician_id"])
    fixtures.post_parts(work_order["id"], world["technician_id"], part["id"], 5)
    fixtures.complete_work_order(work_order["id"], world["technician_id"], 60)

    invoice = fixtures.first_invoice_of(work_order["id"])
    assert_money(invoice["parts_subtotal_cents"], 590005, "Invoice.parts_subtotal_cents")
    assert_money(invoice["labor_subtotal_cents"], 13500, "Invoice.labor_subtotal_cents")
    assert_money(
        invoice["dispatch_subtotal_cents"], 22500, "Invoice.dispatch_subtotal_cents"
    )
    assert_money(invoice["tax_cents"], 42775, "Invoice.tax_cents")
    assert_money(invoice["total_cents"], 668780, "Invoice.total_cents")

    issued = validate_success(api.issue_invoice(invoice["id"], BILLING))
    after_issue = fixtures.get_account(world["account_id"])
    assert_money(after_issue["balance_cents"], 668780, "Account.balance_cents")
    assert after_issue["credit_hold"] is True

    paid = validate_success(
        api.record_payment(
            invoice["id"],
            {"amount_cents": 200000, "expected_invoice_version": issued["version"]},
            BILLING,
        )
    )
    after_pay = fixtures.get_account(world["account_id"])
    assert_money(after_pay["balance_cents"], 468780, "Account.balance_cents")
    assert after_pay["credit_hold"] is False
    assert_money(
        after_pay["lifetime_invoiced_cents"], 668780, "Account.lifetime_invoiced_cents"
    )
    assert_money(after_pay["lifetime_paid_cents"], 200000, "Account.lifetime_paid_cents")
    assert paid["status"] == "PARTIALLY_PAID"
    assert_money(paid["amount_paid_cents"], 200000, "Invoice.amount_paid_cents")


def test_every_accepted_payment_advances_the_invoice_version(api):
    """PRD 2.8: "Recording a payment against an invoice requires `expected_invoice_version`
    carrying the client's last observed `version` of that `Invoice`. A mismatch is rejected
    with `ERR_STALE_INVOICE_VERSION` (HTTP 412). Part payments are legitimately repeatable,
    so the check exists to stop a clerk posting against an outstanding amount it never
    observed."
    PRD 3.11: "An amount exactly equal to the outstanding balance takes the invoice to
    `PAID_IN_FULL` from either `ISSUED` or `PARTIALLY_PAID`, sets `amount_paid_cents` to
    `total_cents`, and moves the work order's billing axis `INVOICED → SETTLED`."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_invoice_payments_advance_the_version_on_every_write
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Payment Version Co",
        email="pv@corner.example",
        address_line="2 Payments",
        technician_name="Payment Version Tech",
    )
    part = fixtures.new_part("CTL-5000-V", "CONTROL", 5000, on_hand_qty=10)
    stage = fixtures.completed_emergency_work_order(
        world, part_id=part["id"], quantity=2, actual_labor_minutes=60
    )
    invoice = fixtures.first_invoice_of(stage["work_order_id"])
    assert_money(invoice["total_cents"], 49160, "Invoice.total_cents")

    issued = validate_success(api.issue_invoice(invoice["id"], BILLING))
    partial = validate_success(
        api.record_payment(
            invoice["id"],
            {"amount_cents": 20000, "expected_invoice_version": issued["version"]},
            BILLING,
        )
    )
    assert partial["status"] == "PARTIALLY_PAID"
    assert partial["version"] == issued["version"] + 1

    final = validate_success(
        api.record_payment(
            invoice["id"],
            {"amount_cents": 29160, "expected_invoice_version": partial["version"]},
            BILLING,
        )
    )
    assert final["version"] == issued["version"] + 2
    assert final["status"] == "PAID_IN_FULL"
    assert_money(final["amount_paid_cents"], 49160, "Invoice.amount_paid_cents")

    assert fixtures.get_work_order(stage["work_order_id"])["billing_status"] == "SETTLED"
    account = fixtures.get_account(world["account_id"])
    assert_money(account["balance_cents"], 0, "Account.balance_cents")
    assert account["credit_hold"] is False
    assert_money(
        account["lifetime_invoiced_cents"], 49160, "Account.lifetime_invoiced_cents"
    )
    assert_money(account["lifetime_paid_cents"], 49160, "Account.lifetime_paid_cents")
