"""Billing sweep, lapse cascade, reinstatement, payment voids, and refunds."""
from test_helpers import (
    add_full_coverage,
    api_client,
    create_policyholder,
    create_quoted_policy,
    get_first_invoice,
    issue_policy,
    make_policyholder_headers,
    set_clock,
    setup_active_policy,
    setup_lapsed_policy,
    setup_paid_invoice_policy,
    validate_error,
    validate_success,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade — lapse suspends coverage, scheduled item, claim
# ---------------------------------------------------------------------------
def test_lapse_cascade_suspends_coverage_scheduled_and_claim(api):
    """PRD §3.4: "When a policy lapses, several effects fire as one cascade.
    Its `lapse_reason` is set to `NONPAYMENT`."
    PRD §3.4: "Every coverage line currently `OPEN` or `EXHAUSTED` is set to
    `SUSPENDED`; every scheduled item currently `ACTIVE` is set to `SUSPENDED`;
    and every claim currently in `FILED`, `UNDER_REVIEW`, or `APPROVED` is set
    to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/payment_overdue_lapse_suspends_claims_and_coverage_depth4
    """
    s = setup_lapsed_policy(
        email="csc@x.com", add_scheduled=True, add_filed_claim=True,
    )
    policy, lines = s["policy"], s["lines"]
    assert policy["status"] == "LAPSED", policy["status"]
    assert policy["lapse_reason"] == "NONPAYMENT", policy["lapse_reason"]
    cl = validate_success(api.get_policy(policy["id"], UW), 200)
    assert cl  # policy readable
    pp_line = validate_success(
        api.list_coverage_lines(policy["id"], UW), 200
    )
    pp = next(l for l in pp_line if l["coverage_type"] == "PERSONAL_PROPERTY")
    assert pp["status"] == "SUSPENDED", pp["status"]
    si = validate_success(api.list_scheduled_items(policy["id"], UW), 200)[0]
    assert si["status"] == "SUSPENDED", si["status"]
    claim = validate_success(api.get_claim(s["claim"]["id"], UW), 200)
    assert claim["status"] == "SUSPENDED", claim["status"]


def test_lapse_sets_nonpayment_reason_at_grace_boundary(api):
    """PRD §3.4: "the current clock must have reached or passed that invoice's
    `due_date` plus the grace period of fourteen days; if the clock has not yet
    reached that point the sweep is rejected with `ERR_NOT_YET_LAPSABLE`. When
    both conditions hold the policy transitions `ACTIVE → LAPSED`."

    Design: Difficulty/boundary_precision_check/lapse_grace_boundary_exact_day_lapses_via_process_billing
    """
    # due_date is the effective_date (2026-03-01); grace+14 = 2026-03-15.
    # Clock 2026-03-16 has passed the boundary, so the lapse fires.
    set_clock("2026-03-01T00:00:00Z")
    ph = create_policyholder(email="bd2@x.com")
    policy = create_quoted_policy(
        ph["id"], effective_date="2026-03-01T00:00:00Z",
        expiry_date="2027-03-01T00:00:00Z",
    )
    add_full_coverage(policy["id"])
    issue_policy(policy["id"])
    set_clock("2026-03-16T00:00:00Z")
    out = validate_success(api.process_billing(policy["id"], UW), 200)
    assert out["status"] == "LAPSED", out["status"]
    assert out["lapse_reason"] == "NONPAYMENT", out["lapse_reason"]


def test_no_lapse_one_second_before_grace_boundary(api):
    """PRD §3.4: "the current clock must have reached or passed that invoice's
    `due_date` plus the grace period of fourteen days; if the clock has not yet
    reached that point the sweep is rejected with `ERR_NOT_YET_LAPSABLE`."

    One second before due+14 (2026-03-14T23:59:59Z) the sweep still rejects.

    Design: Difficulty/boundary_precision_check/lapse_grace_boundary_exact_day_lapses_via_process_billing
    """
    set_clock("2026-03-01T00:00:00Z")
    ph = create_policyholder(email="bd2b@x.com")
    policy = create_quoted_policy(
        ph["id"], effective_date="2026-03-01T00:00:00Z",
        expiry_date="2027-03-01T00:00:00Z",
    )
    add_full_coverage(policy["id"])
    issue_policy(policy["id"])
    set_clock("2026-03-14T23:59:59Z")  # due+14 = 2026-03-15; this is before it
    validate_error(api.process_billing(policy["id"], UW), "ERR_NOT_YET_LAPSABLE", 409)


def test_lapse_cascade_suspends_overdue_invoice(api):
    """PRD §3.4: "When a policy lapses, several effects fire as one cascade. Its
    `lapse_reason` is set to `NONPAYMENT`. The overdue invoice's `status` is set
    to `OVERDUE`."

    Design: Difficulty/transitive_cascade/payment_overdue_lapse_suspends_claims_and_coverage_depth4
    """
    s = setup_lapsed_policy(email="csc2@x.com")
    assert s["policy"]["status"] == "LAPSED", s["policy"]["status"]
    inv = validate_success(api.get_invoice(s["invoice"]["id"], UW), 200)
    assert inv["status"] == "OVERDUE", inv["status"]


def test_process_billing_before_grace_boundary_not_yet_lapsable(api):
    """PRD §3.4: "the current clock must have reached or passed that invoice's
    `due_date` plus the grace period of fourteen days; if the clock has not yet
    reached that point the sweep is rejected with `ERR_NOT_YET_LAPSABLE`."

    Design: Corner/state_machines/process_billing_not_yet_lapsable_returns_error
    """
    set_clock("2026-03-01T00:00:00Z")
    ph = create_policyholder(email="s11@x.com")
    policy = create_quoted_policy(
        ph["id"], effective_date="2026-03-01T00:00:00Z",
        expiry_date="2027-03-01T00:00:00Z",
    )
    add_full_coverage(policy["id"])
    issue_policy(policy["id"])
    set_clock("2026-03-10T00:00:00Z")  # before due+14 = 2026-03-15
    validate_error(api.process_billing(policy["id"], UW), "ERR_NOT_YET_LAPSABLE", 409)


def test_process_billing_before_expiry_not_yet_expired(api):
    """PRD §3.4: "For an expiry, the current clock must have reached or passed
    the policy's `expiry_date`; if it has not, the expiry is rejected with
    `ERR_NOT_YET_EXPIRED`".

    Design: Corner/errors/process_billing_not_yet_expired_returns_error
    """
    _ph, policy, _lines, invoice = setup_paid_invoice_policy(email="er1@x.com")
    set_clock("2026-06-01T00:00:00Z")  # before expiry 2027-01-01, invoice paid
    validate_error(api.process_billing(policy["id"], UW), "ERR_NOT_YET_EXPIRED", 409)


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine — lapse->reinstate cycle
# ---------------------------------------------------------------------------
def test_policy_lapse_reinstate_cycle_increments_count(api):
    """PRD §3.5: "A successful reinstatement transitions the policy
    `LAPSED → ACTIVE` and reverses the lapse cascade. It clears `lapse_reason`
    back to null, increments `reinstatement_count` by one, and sets the
    formerly overdue invoice's `status` to `PAID`."

    Design: Difficulty/non_linear_state_machine/policy_lapse_reinstate_cycle
    """
    s = setup_lapsed_policy(email="cyc@x.com")
    policy, invoice = s["policy"], s["invoice"]
    # pay down the overdue premium, then reinstate inside the window
    validate_success(
        api.record_payment(invoice["id"], {"amount_cents": 33350, "method": "CARD"},
                           make_policyholder_headers(s["policyholder"]["id"])),
        201,
    )
    out = validate_success(
        api.reinstate_policy(policy["id"], UW, {"reinstatement_fee_paid": True}), 200
    )
    assert out["status"] == "ACTIVE", out["status"]
    assert out["reinstatement_count"] == 1, out["reinstatement_count"]
    assert out["lapse_reason"] is None, out["lapse_reason"]


def test_reinstate_restores_suspended_children(api):
    """PRD §3.5: "Each suspended coverage line is restored: to `OPEN` if its
    `remaining_limit_cents` is greater than zero, or to `EXHAUSTED` if its
    `remaining_limit_cents` is zero. Each suspended scheduled item is restored
    to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/policy_lapse_reinstate_cycle
    """
    s = setup_lapsed_policy(email="cyc2@x.com", add_scheduled=True)
    policy, invoice = s["policy"], s["invoice"]
    # The scheduled item raises this policy's premium above the standard
    # 33350; pay the invoice's full amount so balance_due_cents reaches zero
    # (PRD §3.5 reinstatement precondition).
    validate_success(
        api.record_payment(invoice["id"],
                           {"amount_cents": invoice["amount_cents"], "method": "CARD"},
                           make_policyholder_headers(s["policyholder"]["id"])),
        201,
    )
    validate_success(
        api.reinstate_policy(policy["id"], UW, {"reinstatement_fee_paid": True}), 200
    )
    lines = validate_success(api.list_coverage_lines(policy["id"], UW), 200)
    pp = next(l for l in lines if l["coverage_type"] == "PERSONAL_PROPERTY")
    assert pp["status"] == "OPEN", pp["status"]
    si = validate_success(api.list_scheduled_items(policy["id"], UW), 200)[0]
    assert si["status"] == "ACTIVE", si["status"]


# ---------------------------------------------------------------------------
# Queue B: reinstatement preconditions
# ---------------------------------------------------------------------------
def test_reinstate_with_outstanding_balance_rejected(api):
    """PRD §3.5: "The overdue invoice must be fully paid, meaning its
    `balance_due_cents` is zero; otherwise the reinstatement is rejected with
    `ERR_LAPSE_BALANCE_OUTSTANDING`."

    Design: Corner/state_machines/reinstate_with_outstanding_balance_returns_error
    """
    s = setup_lapsed_policy(email="s10@x.com")
    validate_error(
        api.reinstate_policy(s["policy"]["id"], UW, {"reinstatement_fee_paid": True}),
        "ERR_LAPSE_BALANCE_OUTSTANDING", 409,
    )


def test_reinstate_fee_unpaid_returns_402(api):
    """PRD §3.5: "The reinstatement fee must have been paid — satisfied either
    by a paid-down premium invoice on the same policy with a zero balance, or by
    the request body setting `reinstatement_fee_paid` to `true`; if the fee is
    unpaid the request is rejected with `ERR_REINSTATE_FEE_UNPAID`."

    Design: Corner/state_machines/reinstate_fee_unpaid_returns_402
    """
    s = setup_lapsed_policy(email="s9@x.com")
    validate_success(
        api.record_payment(s["invoice"]["id"], {"amount_cents": 33350, "method": "CARD"},
                           make_policyholder_headers(s["policyholder"]["id"])),
        201,
    )
    # premium fully paid, but no reinstatement fee flag -> 402
    validate_error(
        api.reinstate_policy(s["policy"]["id"], UW, {}),
        "ERR_REINSTATE_FEE_UNPAID", 402,
    )


def test_reinstate_window_closed_rejected(api):
    """PRD §3.5: "the current clock must be no later than the overdue invoice's
    `due_date` plus the fourteen-day grace period plus the reinstatement window
    of thirty additional days; once that combined window has passed the request
    is rejected with `ERR_REINSTATE_WINDOW_CLOSED`."

    Design: Corner/state_machines/reinstate_window_closed_returns_error
    """
    s = setup_lapsed_policy(email="s8@x.com")
    validate_success(
        api.record_payment(s["invoice"]["id"], {"amount_cents": 33350, "method": "CARD"},
                           make_policyholder_headers(s["policyholder"]["id"])),
        201,
    )
    # due 2026-01-01 + 14 grace + 30 window = 2026-02-14; clock 2026-03-01 is past it
    set_clock("2026-03-01T00:00:00Z")
    validate_error(
        api.reinstate_policy(s["policy"]["id"], UW, {"reinstatement_fee_paid": True}),
        "ERR_REINSTATE_WINDOW_CLOSED", 409,
    )


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant — payment void restores invoice balance
# ---------------------------------------------------------------------------
def test_payment_void_restores_invoice_balance_exactly(api):
    """PRD §3.4: "Voiding sets the payment's `status` to `VOIDED` and recomputes
    the invoice's `paid_cents` and `balance_due_cents` so that the balance
    returns to `amount_cents` minus the sum of the remaining cleared payments —
    money is conserved. If that recomputation leaves `balance_due_cents` greater
    than zero, an invoice that had been `PAID` reopens, transitioning
    `PAID → OPEN`."

    Design: Difficulty/compensating_invariant/payment_void_restores_invoice_balance_exactly
    """
    ph, policy, invoice, payment = setup_paid_invoice_policy(email="ci2@x.com")
    out = validate_success(api.void_payment(payment["id"], UW), 200)
    assert out["status"] == "VOIDED", out["status"]
    inv = validate_success(api.get_invoice(invoice["id"], UW), 200)
    assert inv["paid_cents"] == 0, inv["paid_cents"]
    assert inv["balance_due_cents"] == 33350, inv["balance_due_cents"]
    assert inv["status"] == "OPEN", inv["status"]


def test_payment_void_marks_payment_voided_and_reopens_invoice(api):
    """PRD §3.4: "Voiding sets the payment's `status` to `VOIDED` and recomputes
    the invoice's `paid_cents` and `balance_due_cents` so that the balance
    returns to `amount_cents` minus the sum of the remaining cleared payments —
    money is conserved. If that recomputation leaves `balance_due_cents` greater
    than zero, an invoice that had been `PAID` reopens, transitioning
    `PAID → OPEN`."

    Design: Difficulty/compensating_invariant/payment_void_restores_invoice_balance_exactly
    """
    ph, policy, invoice, payment = setup_paid_invoice_policy(email="ci2b@x.com")
    inv_before = validate_success(api.get_invoice(invoice["id"], UW), 200)
    assert inv_before["status"] == "PAID", inv_before["status"]
    out = validate_success(api.void_payment(payment["id"], UW), 200)
    assert out["status"] == "VOIDED", out["status"]
    inv_after = validate_success(api.get_invoice(invoice["id"], UW), 200)
    # money conserved: balance returns to amount minus remaining cleared (none)
    assert inv_after["balance_due_cents"] == inv_after["amount_cents"]
    assert inv_after["status"] == "OPEN", inv_after["status"]


def test_void_already_voided_payment_rejected(api):
    """PRD §3.4: "Voiding is allowed only on a payment whose `status` is
    `CLEARED`; a payment that is already voided cannot be voided again and is
    rejected with `ERR_PAYMENT_NOT_VOIDABLE`."

    Design: Corner/state_machines/payment_void_not_voidable_when_already_voided
    """
    ph, policy, invoice, payment = setup_paid_invoice_policy(email="s12@x.com")
    validate_success(api.void_payment(payment["id"], UW), 200)
    validate_error(api.void_payment(payment["id"], UW), "ERR_PAYMENT_NOT_VOIDABLE", 409)


# ---------------------------------------------------------------------------
# Queue B: immediate consistency — partial payment reflected on next GET
# ---------------------------------------------------------------------------
def test_partial_payment_balance_visible_immediately(api):
    """PRD §3.4: "Recording a cleared payment recomputes the invoice's
    `paid_cents` and `balance_due_cents`".
    PRD §3.3: "its `balance_due_cents` is always its `amount_cents` minus its
    `paid_cents`".

    Design: Corner/consistency_model/derived_balance_visible_in_same_payment_response
    """
    ph, policy, _lines, invoice = setup_active_policy(email="cm1@x.com",
                                                       clock="2026-01-01T00:00:00Z")
    validate_success(
        api.record_payment(invoice["id"], {"amount_cents": 10000, "method": "CARD"},
                           make_policyholder_headers(ph["id"])),
        201,
    )
    inv = validate_success(api.get_invoice(invoice["id"], UW), 200)
    assert inv["paid_cents"] == 10000, inv["paid_cents"]
    assert inv["balance_due_cents"] == 23350, inv["balance_due_cents"]
    assert inv["status"] == "OPEN", inv["status"]
