"""Payment reversal and disbursement void — compensating actions and conserved balances."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    clerk_headers, supervisor_headers, finance_headers,
    make_victim,
    setup_case_with_obligation, post_payment, setup_disbursement_pending,
    api_client,
)


class TestPaymentReversalRestoresTotals:
    def test_reverse_partial_payment_returns_totals_to_zero(self, api):
        """PRD §3.4: "Each obligation the payment touched has its paid_amount_cents
        reduced by the amount that obligation was allocated ... an obligation reverts
        ... from PARTIALLY_PAID to OUTSTANDING when its paid amount returns to zero.
        ... total_paid_cents returns to its pre-posting value."

        Design: Difficulty/compensating_invariant/payment_reverse_restores_case_total_paid
        """
        case, obl = setup_case_with_obligation(case_number="C-INV-PAY", assessed_amount_cents=10000)
        payment = post_payment(case["id"], 6000, "STATUTORY_PRIORITY")

        validate_success(api.reverse_payment(payment["id"], supervisor_headers()))

        case_after = validate_success(api.get_case(case["id"], clerk_headers()))
        obl_after = validate_success(api.get_obligation(obl["id"], clerk_headers()))
        assert case_after["total_paid_cents"] == 0
        assert obl_after["paid_amount_cents"] == 0
        assert obl_after["status"] == "OUTSTANDING"

    def test_reverse_full_payment_clears_allocations_and_reverts_satisfied(self, api):
        """PRD §3.4: "On a successful reversal, the payment moves from POSTED to
        REVERSED. ... the payment's allocations are cleared for accounting purposes.
        Affected obligations revert accordingly — an obligation reverts from SATISFIED
        to PARTIALLY_PAID when some paid amount remains, or from PARTIALLY_PAID to
        OUTSTANDING when its paid amount returns to zero."

        Design: Difficulty/compensating_invariant/payment_reverse_restores_case_total_paid
        """
        case, obl = setup_case_with_obligation(case_number="C-INV-PAY2", assessed_amount_cents=10000)
        payment = post_payment(case["id"], 10000, "STATUTORY_PRIORITY")

        reversed_payment = validate_success(api.reverse_payment(payment["id"], supervisor_headers()))
        assert reversed_payment["status"] == "REVERSED"
        assert reversed_payment["allocations"] == []

        obl_after = validate_success(api.get_obligation(obl["id"], clerk_headers()))
        case_after = validate_success(api.get_case(case["id"], clerk_headers()))
        assert obl_after["status"] == "OUTSTANDING"
        assert case_after["total_paid_cents"] == 0


class TestDisbursementVoidRestoresPayable:
    def test_void_disbursement_credits_victim_payable_back(self, api):
        """PRD §3.5: "A void moves the disbursement to VOIDED and credits the victim's
        payable_balance_cents back by the disbursement's amount_cents."

        Design: Difficulty/compensating_invariant/disbursement_void_restores_victim_payable
        """
        case, victim, obl, payment, disb = setup_disbursement_pending(
            case_number="C-INV-DISB", assessed_amount_cents=10000, disburse_cents=4000,
        )

        voided = validate_success(api.void_disbursement(disb["id"], finance_headers()))
        assert voided["status"] == "VOIDED"

        victim_after = validate_success(api.get_victim(victim["id"], clerk_headers()))
        assert victim_after["payable_balance_cents"] == 10000

    def test_void_frees_funds_for_a_new_disbursement(self, api):
        """PRD §3.5: "an amount_cents that must be greater than zero and must not exceed
        the victim's payable_balance_cents at creation time ... A void moves the
        disbursement to VOIDED and credits the victim's payable_balance_cents back by
        the disbursement's amount_cents."

        Design: Difficulty/compensating_invariant/disbursement_void_restores_victim_payable
        """
        case, victim, obl, payment, disb = setup_disbursement_pending(
            case_number="C-INV-DISB2", assessed_amount_cents=10000, disburse_cents=4000,
        )
        validate_success(api.void_disbursement(disb["id"], finance_headers()))

        resp = api.create_disbursement(
            {"victim_id": victim["id"], "case_id": case["id"], "amount_cents": 10000},
            finance_headers(),
        )
        new_disb = validate_success(resp, expected_status=201)
        assert new_disb["status"] == "PENDING"
        assert new_disb["amount_cents"] == 10000


def test_reverse_already_reversed_payment_rejected(api):
    """PRD §3.4: "Reversal is permitted only while the payment's status is POSTED;
    attempting to reverse an already-reversed payment yields ERR_INVALID_STATE."

    Design: Corner/state_machines/reverse_already_reversed_payment_returns_invalid_state
    """
    case, obl = setup_case_with_obligation(case_number="C-DBLREV", assessed_amount_cents=10000)
    payment = post_payment(case["id"], 5000, "STATUTORY_PRIORITY")
    validate_success(api.reverse_payment(payment["id"], supervisor_headers()))

    resp = api.reverse_payment(payment["id"], supervisor_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_disbursement_exceeding_victim_payable_rejected(api):
    """PRD §3.5: "an amount_cents that must be greater than zero and must not exceed the
    victim's payable_balance_cents at creation time — an over-draw is rejected with
    ERR_AMOUNT_EXCEEDS_BALANCE."

    Design: Corner/endpoints/disbursement_exceeds_victim_payable_returns_amount_exceeds
    """
    case, _obl = setup_case_with_obligation(case_number="C-OVERDISB", assessed_amount_cents=10000)
    victim = make_victim(name="Uma Ray")

    resp = api.create_disbursement(
        {"victim_id": victim["id"], "case_id": case["id"], "amount_cents": 5000},
        finance_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_AMOUNT_EXCEEDS_BALANCE.value)
