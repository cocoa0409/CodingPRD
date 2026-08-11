"""Compensating invariants: the client credit pool is conserved across
generate+void, and accounts receivable across payment+refund."""
from test_helpers import (
    TEST_USERS,
    assert_invoice_money_invariants,
    create_client_with_billing_payer,
    create_completed_ride,
    create_invoice_payload,
    create_payment_payload,
    get_success_data,
    make_billing_admin_headers,
    make_family_member_headers,
    seed_credit_via_payment,
    set_clock,
    validate_success,
    api_client,
)

BILLING = TEST_USERS["billing_admin_headers"]


def _setup_credit_invoice():
    """Client with 3000 credit; completed ride with wait 25 (fare 5250);
    DRAFT invoice applying 2625 credit. Returns (client, member, invoice)."""
    from test_helpers import create_active_rate_card, create_compliant_driver
    client, member = create_client_with_billing_payer()
    create_active_rate_card()
    seed_credit_via_payment(client["id"], 3000, payer_member_id=member["id"])
    driver, _ = create_compliant_driver()
    set_clock("2026-05-20T09:00:00Z")
    create_completed_ride(
        client["id"], driver["id"], "2026-06-01T10:00:00Z",
        estimated_duration_minutes=60, estimated_distance_miles=10,
        actual_distance_miles=10, service_minutes=60,
        wait_segments=((0, 15), (60, 70)))
    invoice = get_success_data(api_client.generate_invoice(
        create_invoice_payload(client["id"], period_start="2026-06-01", period_end="2026-06-08"),
        BILLING))
    return client, member, invoice


def test_generation_debits_credit_and_void_restores_it(api):
    """PRD §3.8: "Voiding is the compensation path: a `DRAFT` or `ISSUED`
    invoice with `paid_cents` of zero may be voided (optionally with a
    `void_reason`), which moves it to `VOIDED`, credits exactly
    `credit_applied_cents` back into the client's pool, and removes it from
    both the waterfall and the receivables sets."
    PRD §3.8: "Generation debits the client's pool by exactly
    `credit_applied_cents` (skipped when zero, leaving the client row
    untouched)"

    Design: Difficulty/compensating_invariant/credit_pool_conserved_across_issue_and_void
    """
    client, _, invoice = _setup_credit_invoice()
    # charges 5250 -> applied min(3000, floor(5250/2)) = 2625; due 2625.
    assert invoice["credit_applied_cents"] == 2625
    assert invoice["total_due_cents"] == 2625
    assert_invoice_money_invariants(invoice)
    mid = validate_success(api_client.get_client(client["id"], BILLING))
    assert mid["credit_balance_cents"] == 375, (
        f"invariant: 375 + 2625 == 3000; got {mid['credit_balance_cents']}")
    get_success_data(api_client.issue_invoice(invoice["id"], BILLING))
    voided = get_success_data(api_client.void_invoice(
        invoice["id"], {"void_reason": "generated in error"}, BILLING))
    assert voided["issuance_status"] == "VOIDED"
    end = validate_success(api_client.get_client(client["id"], BILLING))
    assert end["credit_balance_cents"] == 3000, (
        f"void credited exactly 2625 back: 3000 + 0 == 3000; got "
        f"{end['credit_balance_cents']}")


def test_voided_invoice_leaves_waterfall_and_receivables(api):
    """PRD §3.8: "Voiding is the compensation path: a `DRAFT` or `ISSUED`
    invoice with `paid_cents` of zero may be voided (optionally with a
    `void_reason`), which moves it to `VOIDED`, credits exactly
    `credit_applied_cents` back into the client's pool, and removes it from
    both the waterfall and the receivables sets."
    PRD §3.9: "The tendered amount waterfall-applies to the client's open
    invoices — those `ISSUED` or `PARTIALLY_PAID` with `total_due_cents` still
    above `paid_cents`"

    Design: Difficulty/compensating_invariant/credit_pool_conserved_across_issue_and_void
    """
    client, member, invoice = _setup_credit_invoice()
    get_success_data(api_client.issue_invoice(invoice["id"], BILLING))
    get_success_data(api_client.void_invoice(
        invoice["id"], {"void_reason": "generated in error"}, BILLING))
    # A new payment has no open invoice to fill, so the whole 1000 parks as
    # credit on top of the restored 3000.
    payment = get_success_data(api_client.create_payment(
        create_payment_payload(client["id"], amount_cents=1000),
        make_family_member_headers(member["id"])))
    assert payment["applications"] == [], (
        "voided invoice must leave the waterfall candidate set")
    end = validate_success(api_client.get_client(client["id"], BILLING))
    assert end["credit_balance_cents"] == 4000


def _setup_issued_credit_invoice():
    """Same construction plus issuance. Returns (client, member, invoice)."""
    client, member, invoice = _setup_credit_invoice()
    invoice = get_success_data(api_client.issue_invoice(invoice["id"], BILLING))
    return client, member, invoice


def test_payment_waterfall_fills_invoice_then_parks_remainder(api):
    """PRD §3.9: "The tendered amount waterfall-applies to the client's open
    invoices — those `ISSUED` or `PARTIALLY_PAID` with `total_due_cents` still
    above `paid_cents` — in `due_date` ascending order with `created_at`
    ascending breaking ties. Each candidate absorbs the smaller of the
    remaining tender and its outstanding balance; the application is recorded
    in the payment's `applications` array as an `invoice_id` / `applied_cents`
    pair in allocation order, the invoice's `paid_cents` (initially zero) grows
    by the applied amount, and its issuance status recomputes"
    PRD §3.9: "Any remainder beyond all open invoices is credited to the
    client's `credit_balance_cents`."

    Design: Difficulty/compensating_invariant/accounts_receivable_conserved_across_payment_and_refund
    """
    client, member, invoice = _setup_issued_credit_invoice()
    payment = get_success_data(api_client.create_payment(
        create_payment_payload(client["id"], amount_cents=5000, method="ACH"),
        make_family_member_headers(member["id"])))
    assert payment["applications"] == [
        {"invoice_id": invoice["id"], "applied_cents": 2625}], (
        f"waterfall fills the only open invoice first; got {payment['applications']}")
    inv = validate_success(api_client.get_invoice(invoice["id"], BILLING))
    assert inv["issuance_status"] == "PAID"
    assert inv["paid_cents"] == 2625
    credit = validate_success(api_client.get_client(client["id"], BILLING))
    assert credit["credit_balance_cents"] == 2750, (
        f"375 left after generation + 2375 remainder; got {credit['credit_balance_cents']}")


def test_full_refund_reverses_applications_and_restores_position(api):
    """PRD §3.9: "The reversal walks the `applications` array newest-first,
    reversing up to the refund amount in total with a partial reversal
    permitted at the tail application; each reversal decrements the target
    invoice's `paid_cents` and recomputes its issuance status — `PAID` drops to
    `PARTIALLY_PAID` when some but not all of the total remains covered, and to
    `ISSUED` when coverage falls to zero."
    PRD §3.9: "On success the pool is debited by the credit portion,
    `refunded_cents` (initially zero) grows by the refund amount, and the
    payment moves to `PARTIALLY_REFUNDED`, or to `REFUNDED` when the cumulative
    refunds equal the original amount."

    Design: Difficulty/compensating_invariant/accounts_receivable_conserved_across_payment_and_refund
    """
    client, member, invoice = _setup_issued_credit_invoice()
    payment = get_success_data(api_client.create_payment(
        create_payment_payload(client["id"], amount_cents=5000, method="ACH"),
        make_family_member_headers(member["id"])))
    refunded = get_success_data(api_client.refund_payment(
        payment["id"], {"amount_cents": 5000, "reason": "duplicate payment"}, BILLING))
    assert refunded["status"] == "REFUNDED"
    assert refunded["refunded_cents"] == 5000
    inv = validate_success(api_client.get_invoice(invoice["id"], BILLING))
    assert inv["issuance_status"] == "ISSUED"
    assert inv["paid_cents"] == 0
    credit = validate_success(api_client.get_client(client["id"], BILLING))
    assert credit["credit_balance_cents"] == 375, (
        f"2750 - 2375 credit portion clawed back = 375 (pre-payment position); "
        f"got {credit['credit_balance_cents']}")
    # AR conserved: total_due - paid == 2625 before payment and after refund.
    assert inv["total_due_cents"] - inv["paid_cents"] == 2625
