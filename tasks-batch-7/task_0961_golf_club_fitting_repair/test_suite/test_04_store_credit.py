"""Store credit: ledger-sum conservation across grant/redeem/refund, the
append-only ledger shape, and the insufficient-credit rejection."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, api_client,
    set_clock, create_customer, create_specialist, create_manager,
    create_completed_session, create_component_trio, create_draft_spec,
    quote_spec, get_spec, submit_appraisal, issue_offer, accept_appraisal,
    customer_headers, staff_headers, list_ledger, get_customer,
    assert_credit_ledger_entry, assert_credit_balance_matches_ledger,
    setup_quoted_spec,
)


def _setup_credit_conservation():
    """Customer with an accepted DRIVER/A appraisal (grant 17999) and a QUOTED
    spec whose final price is 2300 (session COMPLETED, rebate applies)."""
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Sky Stone")
    specialist = create_specialist()
    ctx = create_completed_session(customer, specialist)

    appraisal = submit_appraisal(customer, [{"club_type": "DRIVER", "condition_grade": "A"}])
    appraisal = issue_offer(appraisal, specialist, "GRADE_MATRIX")
    appraisal = accept_appraisal(appraisal, customer)

    items = create_component_trio(
        head_stock=1, shaft_stock=1, grip_stock=1,
        head_unit=5_000, head_msrp=7_000,
        shaft_unit=3_000, shaft_msrp=4_000,
        grip_unit=800, grip_msrp=1_000,
    )
    spec = create_draft_spec(customer, ctx["session"], items, specialist, labor_cents=1_000)
    spec = quote_spec(spec, specialist)
    return {"customer": customer, "specialist": specialist,
            "appraisal": appraisal, "spec": spec}


def test_credit_balance_equals_ledger_sum_at_every_hop(api):
    """PRD §2.8: "A customer's `credit_balance_cents` is always exactly the sum
    of `amount_cents` over every ledger entry for that customer; the ledger is
    the only mechanism that ever mutates the balance, entries carry no status
    filter of any kind, and the balance is recomputed on every ledger write."

    Design: Difficulty/compensating_invariant/store_credit_conserved_across_grant_redeem_refund
    """
    ctx = _setup_credit_conservation()
    customer, spec = ctx["customer"], ctx["spec"]
    ch = customer_headers(customer)

    # After accept: +17999 (round(29999*0.60)).
    bal = get_customer(customer["id"], ch)["credit_balance_cents"]
    assert bal == 17_999, f"after accept expected 17999, got {bal}"
    assert_credit_balance_matches_ledger(get_customer(customer["id"], ch),
                                         list_ledger(customer["id"]))

    # After CREDIT approve: -2300 (final price 8800 + 1000 - 7500).
    spec = get_success_data(
        api_client.approve_build_spec(spec["id"], {"payment_method": "CREDIT"}, ch)
    )
    assert spec["final_price_cents"] == 2_300
    bal = get_customer(customer["id"], ch)["credit_balance_cents"]
    assert bal == 15_699, f"after CREDIT approve expected 15699, got {bal}"
    assert_credit_balance_matches_ledger(get_customer(customer["id"], ch),
                                         list_ledger(customer["id"]))

    # After cancel: +2300 refund exactly compensates the redemption.
    get_success_data(api_client.cancel_build_spec(spec["id"], ch))
    bal = get_customer(customer["id"], ch)["credit_balance_cents"]
    assert bal == 17_999, f"after cancel expected 17999, got {bal}"
    assert_credit_balance_matches_ledger(get_customer(customer["id"], ch),
                                         list_ledger(customer["id"]))


def test_credit_ledger_records_grant_payment_refund(api):
    """PRD §2.8: "Each entry records the `customer_id` it belongs to, a signed
    `amount_cents` (positive grants credit, negative redeems it), a `reason`
    drawn from `TRADE_IN_ACCEPT`, `BUILD_PAYMENT`, `BUILD_REFUND`,
    `WARRANTY_RESOLUTION`, `TICKET_PAYMENT`, or `TICKET_REFUND`". PRD §3.4:
    "a ledger entry of negative `final_price_cents` with reason
    `BUILD_PAYMENT` is written" and "a ledger entry of positive
    `final_price_cents` with reason `BUILD_REFUND` restores the customer's
    balance."

    Design: Difficulty/compensating_invariant/store_credit_conserved_across_grant_redeem_refund
    """
    ctx = _setup_credit_conservation()
    customer, spec = ctx["customer"], ctx["spec"]
    ch = customer_headers(customer)

    spec = get_success_data(
        api_client.approve_build_spec(spec["id"], {"payment_method": "CREDIT"}, ch)
    )
    get_success_data(api_client.cancel_build_spec(spec["id"], ch))

    ledger = list_ledger(customer["id"])
    assert len(ledger) == 3, f"expected exactly 3 ledger entries, got {len(ledger)}"
    amounts = sorted(e["amount_cents"] for e in ledger)
    assert amounts == sorted([17_999, -2_300, 2_300]), (
        f"expected amounts [+17999, -2300, +2300], got {amounts}"
    )
    reasons = sorted(e["reason"] for e in ledger)
    assert reasons == sorted(["TRADE_IN_ACCEPT", "BUILD_PAYMENT", "BUILD_REFUND"]), (
        f"expected reasons TRADE_IN_ACCEPT/BUILD_PAYMENT/BUILD_REFUND, got {reasons}"
    )
    for entry in ledger:
        assert entry["customer_id"] == customer["id"]


def test_credit_ledger_entries_are_append_only_shape(api):
    """PRD §2.4: "One entity deviates from this pattern: a credit ledger entry
    is append-only and carries only `id` and `created_at`; `updated_at` and
    `version` are absent from it by design." PRD §3.6: "a ledger entry of
    positive `offered_value_cents` with reason `TRADE_IN_ACCEPT` grants the
    store credit".

    Design: Corner/entities/credit_ledger_entries_immutable
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Wes Wold")
    specialist = create_specialist()
    appraisal = submit_appraisal(customer, [{"club_type": "PUTTER", "condition_grade": "A"}])
    appraisal = issue_offer(appraisal, specialist, "GRADE_MATRIX")
    accept_appraisal(appraisal, customer)

    ledger = list_ledger(customer["id"])
    assert len(ledger) == 1, f"expected exactly 1 ledger entry, got {len(ledger)}"
    entry = ledger[0]
    # round(14999*0.60) = 8999.
    assert entry["amount_cents"] == 8_999, (
        f"expected grant of 8999, got {entry['amount_cents']}"
    )
    assert entry["reason"] == "TRADE_IN_ACCEPT"
    assert_credit_ledger_entry(entry)


def test_insufficient_credit_rejects_credit_approval(api):
    """PRD §3.4: "If `payment_method` is `CREDIT`, the customer's
    `credit_balance_cents` must cover the resulting `final_price_cents` or
    approval fails with `ERR_INSUFFICIENT_CREDIT` (HTTP 402)".

    Design: Corner/errors/error_insufficient_credit_trigger
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Jeb Joule")
    specialist = create_specialist()

    # Grant a tiny credit balance: MARKET_COMP [125] -> round(125*0.8) = 100.
    appraisal = submit_appraisal(customer, [{"club_type": "WEDGE", "condition_grade": "D"}])
    appraisal = issue_offer(appraisal, specialist, "MARKET_COMP",
                            market_comps_cents=[125])
    accept_appraisal(appraisal, customer)
    bal = get_customer(customer["id"], customer_headers(customer))["credit_balance_cents"]
    assert bal == 100, f"expected credit balance 100, got {bal}"

    ctx = create_completed_session(customer, specialist)
    items = create_component_trio(
        head_stock=1, shaft_stock=1, grip_stock=1,
        head_unit=5_000, head_msrp=7_000,
        shaft_unit=3_000, shaft_msrp=4_000,
        grip_unit=800, grip_msrp=1_000,
    )
    spec = create_draft_spec(customer, ctx["session"], items, specialist, labor_cents=1_000)
    spec = quote_spec(spec, specialist)

    resp = api_client.approve_build_spec(
        spec["id"], {"payment_method": "CREDIT"}, customer_headers(customer)
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT)

    spec_after = get_spec(spec["id"], staff_headers(specialist))
    assert spec_after["status"] == "QUOTED", (
        f"failed approval must leave the spec QUOTED, got {spec_after['status']}"
    )
    manager = create_manager()
    orders = get_success_data(
        api_client.list_component_orders(staff_headers(manager),
                                         params={"build_spec_id": spec["id"]})
    )
    assert orders == [], f"no component order may be created on failed approval, got {orders}"
    ledger = list_ledger(customer["id"])
    assert len(ledger) == 1, "no payment ledger entry may be written on failed approval"
