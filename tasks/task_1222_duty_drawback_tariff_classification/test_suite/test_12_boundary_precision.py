"""Boundary precision: the inclusive statutory filing deadline second and the
exact-equality invoice payment boundary."""
from test_helpers import ApiErrorId, add_claim, add_claim_line, set_clock, setup_trade_scenario, setup_two_paid_claims, TEST_USERS, validate_error, validate_success

ADMIN = TEST_USERS["firm_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
BROKER = TEST_USERS["broker_headers"]


def _setup_claim_at_deadline_boundary():
    """DIRECT claim whose only entry entered on 2026-05-01T00:00:00Z, so the
    statutory filing deadline is exactly 2031-05-01T00:00:00Z."""
    ctx = setup_trade_scenario(
        entry_overrides={"entry_date": "2026-05-01T00:00:00Z"},
        export_overrides={"export_date": "2026-05-02T00:00:00Z"},
    )
    claim = add_claim(
        ctx["client"]["id"],
        period_start="2026-05-01T00:00:00Z",
        period_end="2026-05-31T00:00:00Z",
    )
    line = add_claim_line(
        claim["id"], ctx["entry"]["id"], ctx["export"]["id"], matched_quantity=40
    )
    ctx.update({"claim": claim, "line": line})
    return ctx


def test_filing_at_the_exact_deadline_second_is_allowed(api):
    """PRD 3.4: "The deadline itself is statutory: five years after the earliest
    `entry_date` among the entries referenced by the claim's `ACTIVE` lines, and
    the comparison is inclusive — filing at the exact deadline second is still
    permitted."

    Design: Difficulty/boundary_precision_check/filing_deadline_inclusive_second
    """
    ctx = _setup_claim_at_deadline_boundary()
    set_clock("2031-05-01T00:00:00Z")

    filed = validate_success(api.file_claim(ctx["claim"]["id"], BROKER))
    assert filed["status"] == "FILED"
    assert filed["filed_at"] == "2031-05-01T00:00:00Z", (
        "the deadline second is inclusive: filing succeeds at exactly "
        "entry_date + 5 years"
    )
    assert filed["claimed_duty_cents"] == 32670


def test_filing_one_second_before_the_deadline_is_also_allowed(api):
    """PRD 3.4: "The deadline itself is statutory: five years after the earliest
    `entry_date` among the entries referenced by the claim's `ACTIVE` lines, and
    the comparison is inclusive — filing at the exact deadline second is still
    permitted."
    PRD 3.4: "the logical clock must not have passed the claim's
    `filing_deadline` (`ERR_FILING_DEADLINE_PASSED`)."

    Design: Difficulty/boundary_precision_check/filing_deadline_inclusive_second
    """
    ctx = _setup_claim_at_deadline_boundary()
    set_clock("2031-04-30T23:59:59Z")

    filed = validate_success(api.file_claim(ctx["claim"]["id"], BROKER))
    assert filed["status"] == "FILED"
    assert filed["filed_at"] == "2031-04-30T23:59:59Z"
    assert filed["claimed_duty_cents"] == 32670


def test_payment_exactly_equal_to_balance_settles_to_paid(api):
    """PRD 3.7: "A `FirmAdmin` records client payments against it; each
    `amount_cents` must be positive and may not exceed the current
    `balance_cents` (`ERR_PAYMENT_EXCEEDS_BALANCE`). A payment smaller than the
    balance moves the invoice `ISSUED → PARTIALLY_PAID` (or keeps it in
    `PARTIALLY_PAID`), while a payment exactly equal to the balance — the
    exact-equality boundary — settles it to `PAID`."

    Design: Difficulty/boundary_precision_check/invoice_payment_exact_balance
    """
    ctx = setup_two_paid_claims()
    inv_a = ctx["invoice_a"]
    assert inv_a["fee_cents"] == 8168
    assert inv_a["balance_cents"] == 8168

    paid = validate_success(
        api.pay_invoice(inv_a["id"], {"amount_cents": 8168}, ADMIN)
    )
    assert paid["status"] == "PAID", "payment == balance exactly is accepted"
    assert paid["balance_cents"] == 0
    assert paid["amount_paid_cents"] == 8168


def test_payment_one_cent_above_balance_is_rejected_without_trace(api):
    """PRD 3.7: "each `amount_cents` must be positive and may not exceed the
    current `balance_cents` (`ERR_PAYMENT_EXCEEDS_BALANCE`)."

    Design: Difficulty/boundary_precision_check/invoice_payment_exact_balance
    """
    ctx = setup_two_paid_claims()
    inv_b = ctx["invoice_b"]
    assert inv_b["balance_cents"] == 8168

    res = api.pay_invoice(inv_b["id"], {"amount_cents": 8169}, ADMIN)
    validate_error(res, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)

    after = validate_success(api.get_invoice(inv_b["id"], ADMIN))
    assert after["status"] == "ISSUED", "the rejection left no trace"
    assert after["amount_paid_cents"] == 0
    assert after["balance_cents"] == 8168
