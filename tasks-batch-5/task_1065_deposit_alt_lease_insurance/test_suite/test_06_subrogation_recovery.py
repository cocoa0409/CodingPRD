"""Subrogation case lifecycle, recovery-payment repayment, and the recovery-balance
compensating invariant (PRD §3.7, §2.8)."""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID, ApiErrorId,
    setup_active_policy, file_claim, approve_claim, get_payout_for_claim, disburse_payout,
    open_subrogation_case, send_demand, record_recovery_payment, reverse_recovery_payment,
    make_compliance_officer_headers, make_renter_headers,
)


def test_subrogation_case_get_not_found(api, compliance_officer_headers):
    """PRD §2.5: "an unresolvable ... a subrogation case yields `ERR_SUBROGATION_CASE_NOT_FOUND`
    ... all at HTTP 404."

    Design: Corner/entities/subrogation_case_get_not_found
    """
    res = api.get_subrogation_case(NON_EXISTENT_UUID, compliance_officer_headers)
    validate_error(res, ApiErrorId.ERR_SUBROGATION_CASE_NOT_FOUND, expected_status=404)


def test_recovery_payment_reverse_not_found(api, platform_admin_headers):
    """PRD §2.5: "an unresolvable ... a recovery payment yields
    `ERR_RECOVERY_PAYMENT_NOT_FOUND` ... all at HTTP 404."

    Design: Corner/entities/recovery_payment_reverse_not_found
    """
    res = api.reverse_recovery_payment(NON_EXISTENT_UUID, platform_admin_headers)
    validate_error(res, ApiErrorId.ERR_RECOVERY_PAYMENT_NOT_FOUND, expected_status=404)


def test_subrogation_case_blocked_by_undisbursed_payout(api):
    """PRD §3.7: "When a landlord's `UNPAID_RENT` or `BOTH` claim has actually been paid out —
    meaning its payout has reached `DISBURSED`, not merely `APPROVED` — a `ComplianceOfficer` can
    open a subrogation case to pursue recovery directly from the renter...Attempting this before
    the claim's payout has actually disbursed is rejected with
    `ERR_SUBROGATION_REQUIRES_DISBURSED_PAYOUT` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/subrogation_case_blocked_by_undisbursed_payout
    """
    ctx = setup_active_policy(coverage_limit_cents=500000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"], claim_type="UNPAID_RENT",
                        line_items=[{"description": "Unpaid rent - June", "amount_cents": 100000}])
    claim = approve_claim(claim["id"], "adjuster-001")

    res = api.create_subrogation_case(
        claim["id"], {"claim_id": claim["id"], "original_demand_amount_cents": 95000},
        make_compliance_officer_headers(),
    )
    validate_error(res, ApiErrorId.ERR_SUBROGATION_REQUIRES_DISBURSED_PAYOUT, expected_status=409)


def test_subrogation_case_opens_once_payout_disbursed(api):
    """PRD §3.7: "When a landlord's `UNPAID_RENT` or `BOTH` claim has actually been paid out —
    meaning its payout has reached `DISBURSED`, not merely `APPROVED` — a `ComplianceOfficer` can
    open a subrogation case to pursue recovery directly from the renter..." "A new case starts
    `OPEN` with `outstanding_balance_cents` initialized equal to the original demand."

    Design: Difficulty/cross_entity_state_dependency/subrogation_case_blocked_by_undisbursed_payout
    """
    ctx = setup_active_policy(coverage_limit_cents=500000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"], claim_type="UNPAID_RENT",
                        line_items=[{"description": "Unpaid rent - June", "amount_cents": 100000}])
    claim = approve_claim(claim["id"], "adjuster-001")
    payout = get_payout_for_claim(claim["id"], ctx["landlord"]["id"])
    disburse_payout(payout["id"], "adjuster-002")

    case = open_subrogation_case(claim["id"], 90000)
    assert case["status"] == "OPEN"
    assert case["outstanding_balance_cents"] == 90000


def test_subrogation_case_send_demand_twice_invalid(api):
    """PRD §3.7: "From `OPEN`, the compliance officer sends a formal demand, moving the case to
    `DEMAND_SENT` and recording `demand_sent_at`." A case already in `DEMAND_SENT` is not `OPEN`,
    so a second `SEND_DEMAND` cannot re-apply the same declared transition.

    Design: Corner/state_machines/subrogation_case_send_demand_twice_invalid
    """
    ctx = setup_active_policy(coverage_limit_cents=500000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"], claim_type="UNPAID_RENT",
                        line_items=[{"description": "Unpaid rent - July", "amount_cents": 80000}])
    claim = approve_claim(claim["id"], "adjuster-301")
    payout = get_payout_for_claim(claim["id"], ctx["landlord"]["id"])
    disburse_payout(payout["id"], "adjuster-302")
    case = open_subrogation_case(claim["id"], 75000)
    case = send_demand(case["id"])
    assert case["status"] == "DEMAND_SENT"

    res = api.subrogation_case_transition(case["id"], {"action": "SEND_DEMAND"}, make_compliance_officer_headers())
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_subrogation_case(case["id"], make_compliance_officer_headers()), 200)
    assert after["status"] == "DEMAND_SENT"


def test_recovery_payment_exceeding_outstanding_balance_rejected(api):
    """PRD §3.7: "each `RecoveryPayment` submits `subrogation_case_id` and a positive
    `amount_cents`, and the payment is rejected with `ERR_RECOVERY_PAYMENT_EXCEEDS_BALANCE`
    (HTTP 422) if it would exceed the case's current outstanding balance."

    Design: Corner/validations/recovery_payment_exceeding_outstanding_balance_rejected
    """
    ctx = setup_active_policy(coverage_limit_cents=500000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"], claim_type="UNPAID_RENT",
                        line_items=[{"description": "Unpaid rent - two months", "amount_cents": 150000}])
    claim = approve_claim(claim["id"], "adjuster-701")
    payout = get_payout_for_claim(claim["id"], ctx["landlord"]["id"])
    disburse_payout(payout["id"], "adjuster-702")
    case = open_subrogation_case(claim["id"], 145000)
    case = send_demand(case["id"])

    res = api.create_recovery_payment(
        case["id"], {"subrogation_case_id": case["id"], "amount_cents": 999999},
        make_renter_headers(ctx["renter"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_RECOVERY_PAYMENT_EXCEEDS_BALANCE, expected_status=422)
    after = validate_success(api.get_subrogation_case(case["id"], make_compliance_officer_headers()), 200)
    assert after["outstanding_balance_cents"] == 145000


def test_recovery_payment_succeed_reverse_conserves_subrogation_outstanding_balance(api):
    """PRD §2.8: "A parallel invariant governs subrogation: a case's original demand amount
    always equals its current outstanding balance plus the sum of every non-reversed, succeeded
    recovery payment against that case, and reversing a recovery payment is the compensating
    action there too — it restores the outstanding balance..."

    Design: Difficulty/compensating_invariant/recovery_payment_succeed_reverse_conserves_subrogation_outstanding_balance
    """
    ctx = setup_active_policy(coverage_limit_cents=500000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"], claim_type="UNPAID_RENT",
                        line_items=[{"description": "Unpaid rent - three months", "amount_cents": 150000}])
    claim = approve_claim(claim["id"], "adjuster-001")
    payout = get_payout_for_claim(claim["id"], ctx["landlord"]["id"])
    disburse_payout(payout["id"], "adjuster-002")
    case = open_subrogation_case(claim["id"], 145000)
    case = send_demand(case["id"])

    payment = record_recovery_payment(case["id"], ctx["renter"]["id"], 50000)
    case_after_payment = validate_success(api.get_subrogation_case(case["id"], make_compliance_officer_headers()), 200)
    assert case_after_payment["outstanding_balance_cents"] == 95000

    reversed_payment = reverse_recovery_payment(payment["id"])
    assert reversed_payment["status"] == "REVERSED"
    case_after_reversal = validate_success(api.get_subrogation_case(case["id"], make_compliance_officer_headers()), 200)
    assert case_after_reversal["outstanding_balance_cents"] == 145000


def test_recovery_payment_reversal_reverts_case_from_paid_in_full_to_demand_sent(api):
    """PRD §3.7: "A `PlatformAdmin` may reverse an individual `SUCCEEDED` recovery payment...
    which moves that payment to `REVERSED`, records `reversed_at`, and restores the case's
    outstanding balance...and if the case had already reached `PAID_IN_FULL`, the reversal
    reverts it back to `DEMAND_SENT` since the balance is no longer fully satisfied."

    Design: Difficulty/compensating_invariant/recovery_payment_succeed_reverse_conserves_subrogation_outstanding_balance
    """
    ctx = setup_active_policy(coverage_limit_cents=500000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"], claim_type="UNPAID_RENT",
                        line_items=[{"description": "Unpaid rent - one month", "amount_cents": 105000}])
    claim = approve_claim(claim["id"], "adjuster-001")
    payout = get_payout_for_claim(claim["id"], ctx["landlord"]["id"])
    disburse_payout(payout["id"], "adjuster-002")
    case = open_subrogation_case(claim["id"], 100000)
    case = send_demand(case["id"])

    payment = record_recovery_payment(case["id"], ctx["renter"]["id"], 100000)
    fully_paid_case = validate_success(api.get_subrogation_case(case["id"], make_compliance_officer_headers()), 200)
    assert fully_paid_case["status"] == "PAID_IN_FULL"
    assert fully_paid_case["outstanding_balance_cents"] == 0

    reverse_recovery_payment(payment["id"])
    reverted_case = validate_success(api.get_subrogation_case(case["id"], make_compliance_officer_headers()), 200)
    assert reverted_case["status"] == "DEMAND_SENT"
    assert reverted_case["outstanding_balance_cents"] == 100000
