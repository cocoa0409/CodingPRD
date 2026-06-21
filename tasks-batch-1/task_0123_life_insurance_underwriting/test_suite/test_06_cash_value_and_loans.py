"""Cash-value ledger cascades, loan eligibility boundaries, the loan
draw/repay conservation invariant, and policy-loan OCC.

Covers difficulty rules transitive_cascade, boundary_precision_check (loan boundary
instance), and compensating_invariant (loan conservation instance), plus the corner
loan-exceeds-value and OCC-stale-policy instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    setup_issued_policy, setup_issued_policy_with_gross_11250,
    make_on_cycle_payment, fetch_policy, draw_loan,
    make_policyowner_headers,
    EXAM_STANDARD,
)


def test_issue_cascade_depth3_policy_cashvalue_gross_net(api):
    """PRD §3.6: "The act of issuing also lays down the first cash-value accrual: a
    `CashValueEntry` with reason `PREMIUM_ACCRUAL` is created for the first year, which
    recomputes `gross_cash_value_cents` and reconciles `net_cash_value_cents` as described
    in Section 2.8."
    PRD §3.7: "The accrual increment is the running cumulative premium paid — taken after
    this payment has been added — multiplied by the product's `cash_value_accrual_rate_bps`,
    divided by ten thousand, and rounded half up to a whole cent."

    Design: Difficulty/transitive_cascade/issue_cascade_depth3_policy_cashvalue_gross_net
    """
    # STANDARD final premium 125000; accrual round(125000*300/10000)=3750.
    ctx = setup_issued_policy(issue_clock="2026-06-01T00:00:00Z", exam_overrides=dict(EXAM_STANDARD))
    policy = ctx["policy"]
    policy_id = policy["id"]
    applicant_id = ctx["applicant"]["id"]
    assert policy["cumulative_premium_paid_cents"] == 125000, policy
    assert policy["gross_cash_value_cents"] == 3750, policy
    assert policy["net_cash_value_cents"] == 3750, policy
    entries, _ = validate_paginated(
        api.list_cash_value_entries(policy_id, make_policyowner_headers(applicant_id))
    )
    assert len(entries) == 1, entries
    assert entries[0]["reason"] == "PREMIUM_ACCRUAL", entries
    assert entries[0]["amount_cents"] == 3750, entries


def test_payment_cascade_depth2_cumulative_accrual_gross(api):
    """PRD §3.7: "the amount is added to `cumulative_premium_paid_cents`; and a cash-value
    accrual fires."
    PRD §3.7: "A new `CashValueEntry` with reason `PREMIUM_ACCRUAL` for that increment is
    appended, after which `gross_cash_value_cents` is recomputed as the exact sum of all the
    policy's entry amounts and `net_cash_value_cents` is reconciled."

    Design: Difficulty/transitive_cascade/payment_cascade_depth2_cumulative_accrual_gross
    """
    ctx = setup_issued_policy(issue_clock="2026-06-01T00:00:00Z", exam_overrides=dict(EXAM_STANDARD))
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    # Second on-cycle premium: cum 250000, accrual round(250000*300/10000)=7500, gross 11250.
    make_on_cycle_payment(policy_id, applicant_id, 125000)
    policy = fetch_policy(policy_id, applicant_id)
    assert policy["cumulative_premium_paid_cents"] == 250000, policy
    assert policy["gross_cash_value_cents"] == 11250, policy
    assert policy["net_cash_value_cents"] == 11250, policy


def test_loan_principal_equals_available_value_inclusive_boundary(api):
    """PRD §3.9: "The cap is the gross cash value multiplied by the product's
    `max_loan_to_cash_value_pct`, divided by 100, rounded half up to a whole cent; the amount
    actually available is that cap less the already-outstanding loan principal, never below
    zero. A requested principal that exceeds the available amount is rejected with
    `ERR_LOAN_EXCEEDS_VALUE`, while a principal exactly equal to the available amount is
    permitted."

    Design: Difficulty/boundary_precision_check/loan_principal_equals_available_value_inclusive_boundary
    """
    ctx = setup_issued_policy_with_gross_11250()
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    # gross 11250, cap round(11250*90/100)=10125; principal == available is permitted.
    loan = validate_success(
        api.create_policy_loan(policy_id, {"principal_cents": 10125,
                                           "expected_policy_version": ctx["policy_version"]},
                               make_policyowner_headers(applicant_id)),
        expected_status=201,
    )
    assert loan["principal_cents"] == 10125, loan
    assert loan["status"] == "ACTIVE", loan
    policy = fetch_policy(policy_id, applicant_id)
    assert policy["outstanding_loan_principal_cents"] == 10125, policy
    assert policy["net_cash_value_cents"] == 1125, policy


def test_loan_exceeds_available_value_rejected(api):
    """PRD §3.9: "A requested principal that exceeds the available amount is rejected with
    `ERR_LOAN_EXCEEDS_VALUE`, while a principal exactly equal to the available amount is
    permitted."

    Design: Corner/calculations/loan_exceeds_available_value_rejected
    """
    ctx = setup_issued_policy_with_gross_11250()
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    # cap 10125; 10126 exceeds available by 1 -> rejected.
    resp = api.create_policy_loan(
        policy_id, {"principal_cents": 10126, "expected_policy_version": ctx["policy_version"]},
        make_policyowner_headers(applicant_id),
    )
    validate_error(resp, ApiErrorId.ERR_LOAN_EXCEEDS_VALUE.value)
    policy = fetch_policy(policy_id, applicant_id)
    assert policy["outstanding_loan_principal_cents"] == 0, policy


def test_loan_draw_then_repay_conserves_gross_cash_value(api):
    """PRD §3.9: "Drawing a loan adds its principal to `outstanding_loan_principal_cents`,
    reconciles `net_cash_value_cents`, and increments the policy's `version`."
    PRD §3.9: "Repayment is a compensating action: it subtracts the loan's principal from
    the policy's `outstanding_loan_principal_cents`, reconciles `net_cash_value_cents` back
    toward its pre-loan level, increments the policy's `version`, and increments the loan's
    own `version`."

    Design: Difficulty/compensating_invariant/loan_draw_then_repay_conserves_gross_cash_value
    """
    ctx = setup_issued_policy_with_gross_11250()
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    po_h = make_policyowner_headers(applicant_id)
    # Draw a 5000 loan: gross unchanged at 11250, net drops to 6250.
    loan = draw_loan(policy_id, applicant_id, 5000, ctx["policy_version"])
    during = fetch_policy(policy_id, applicant_id)
    assert during["gross_cash_value_cents"] == 11250, during
    assert during["net_cash_value_cents"] == 6250, during
    assert during["outstanding_loan_principal_cents"] == 5000, during
    # Repay: gross still 11250, net back to 11250, outstanding back to 0.
    repaid = validate_success(api.repay_policy_loan(loan["id"], po_h))
    assert repaid["status"] == "REPAID", repaid
    after = fetch_policy(policy_id, applicant_id)
    assert after["gross_cash_value_cents"] == 11250, after
    assert after["net_cash_value_cents"] == 11250, after
    assert after["outstanding_loan_principal_cents"] == 0, after


def test_stale_policy_version_on_loan_draw_rejected(api):
    """PRD §2.9: "If a prior writer has advanced the policy's version since the client last
    read it — for instance, by drawing another loan that legitimately reduced the available
    loan value — the create is rejected with `ERR_STALE_POLICY_VERSION` at HTTP 412, because
    the client's notion of available loan value is no longer trustworthy."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_policy_version_on_loan_draw
    """
    ctx = setup_issued_policy_with_gross_11250()
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    po_h = make_policyowner_headers(applicant_id)
    stale_version = ctx["policy_version"]
    # First loan succeeds at the observed version and advances Policy.version.
    draw_loan(policy_id, applicant_id, 1000, stale_version)
    # Second loan reusing the now-stale version is rejected.
    resp = api.create_policy_loan(
        policy_id, {"principal_cents": 1000, "expected_policy_version": stale_version}, po_h
    )
    validate_error(resp, ApiErrorId.ERR_STALE_POLICY_VERSION.value)
    policy = fetch_policy(policy_id, applicant_id)
    assert policy["outstanding_loan_principal_cents"] == 1000, policy
