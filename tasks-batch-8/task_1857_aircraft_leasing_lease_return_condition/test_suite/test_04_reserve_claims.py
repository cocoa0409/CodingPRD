"""Reserve claims: approve/reject, pay door (state check before balance
check), equality boundary, and payment reversal restoring the ledger."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_lease_reserve_invariants,
    create_active_lease,
    create_approved_claim,
    create_lease_with_accepted_report,
    create_paid_claim,
    make_lessee_rep_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["lessor_admin_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


class TestClaimDecide:
    def test_approve_stamps_amount_and_reject_is_terminal(self, api):
        """PRD §3.4: "Approving requires an `approved_amount_cents` that is
        greater than zero and no more than `claimed_amount_cents` — an
        out-of-range amount is `ERR_INVALID_REQUEST` — and stamps that amount
        on the claim, where it had been null until decided, as the claim
        moves `SUBMITTED → APPROVED`. Rejecting moves the claim `SUBMITTED →
        REJECTED`, terminally."

        Design: Difficulty/priority_pair_validation_conflict/pay_wrong_state_and_over_balance_state_wins
        """
        lease, _aircraft, lessee = create_active_lease()
        claim = validate_success(
            api.create_reserve_claim(
                lease["id"],
                {"maintenance_event_ref": "ENG-SHOP-1", "claimed_amount_cents": 60000},
                make_lessee_rep_headers(lessee["id"])),
            expected_status=201)
        assert claim["status"] == "SUBMITTED"
        assert claim["approved_amount_cents"] is None

        decided = validate_success(
            api.decide_reserve_claim(
                claim["id"], {"decision": "APPROVE", "approved_amount_cents": 45000}, ADMIN))
        assert decided["status"] == "APPROVED"
        assert decided["approved_amount_cents"] == 45000

    def test_approve_out_of_range_amount_rejected(self, api):
        """PRD §3.4: "Approving requires an `approved_amount_cents` that is
        greater than zero and no more than `claimed_amount_cents` — an
        out-of-range amount is `ERR_INVALID_REQUEST`"

        Design: Difficulty/priority_pair_validation_conflict/pay_wrong_state_and_over_balance_state_wins
        """
        lease, _aircraft, lessee = create_active_lease()
        claim = validate_success(
            api.create_reserve_claim(
                lease["id"],
                {"maintenance_event_ref": "ENG-SHOP-2", "claimed_amount_cents": 60000},
                make_lessee_rep_headers(lessee["id"])),
            expected_status=201)
        resp = api.decide_reserve_claim(
            claim["id"], {"decision": "APPROVE", "approved_amount_cents": 60001}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestClaimPay:
    def test_pay_wrong_state_and_over_balance_state_wins(self, api):
        """PRD §3.4: "Payment is finance's job, and it is a two-check door in
        the order fixed by §2.8: the claim must be `APPROVED` — otherwise
        `ERR_CLAIM_NOT_PAYABLE` — and the lease's `reserve_balance_cents`
        must be at least `approved_amount_cents`, with equality explicitly
        payable; a shortfall is `ERR_RESERVE_BALANCE_EXCEEDED`."
        PRD §2.8: "paying a claim evaluates the payable-state check before
        the balance check."

        Design: Difficulty/priority_pair_validation_conflict/pay_wrong_state_and_over_balance_state_wins
        """
        # Balance 560000; claim A approved for the whole balance then PAID.
        lease, _aircraft, lessee, _report = create_lease_with_accepted_report(
            {"period_month": "2026-08", "flight_hours": 100.0, "flight_cycles": 20},
            reserve_rate_per_fh_cents=4000, reserve_rate_per_fc_cents=8000)
        claim_a = create_paid_claim(lease["id"], lessee["id"], 560000,
                                    maintenance_event_ref="ENG-SHOP-A")
        assert claim_a["status"] == "PAID"
        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["reserve_balance_cents"] == 0

        # Re-paying the PAID claim violates both the state precondition and
        # the balance check; the state error must win.
        resp = api.pay_reserve_claim(claim_a["id"], FINANCE)
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_CLAIM_NOT_PAYABLE", (
            f"state check (priority 5) must win over fiscal check (priority 10); "
            f"got {body['data']['error_id']!r}")
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_PAYABLE, expected_status=409)

    def test_pay_submitted_claim_not_payable(self, api):
        """PRD §3.4: "Payment is finance's job, and it is a two-check door in
        the order fixed by §2.8: the claim must be `APPROVED` — otherwise
        `ERR_CLAIM_NOT_PAYABLE` — and the lease's `reserve_balance_cents`
        must be at least `approved_amount_cents`, with equality explicitly
        payable; a shortfall is `ERR_RESERVE_BALANCE_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/pay_wrong_state_and_over_balance_state_wins
        """
        # Isolated state-check failure: a SUBMITTED claim has no approved
        # amount, so only the payable-state check can fire.
        lease, _aircraft, lessee = create_active_lease()
        claim = validate_success(
            api.create_reserve_claim(
                lease["id"],
                {"maintenance_event_ref": "ENG-SHOP-B", "claimed_amount_cents": 1000},
                make_lessee_rep_headers(lessee["id"])),
            expected_status=201)
        assert claim["status"] == "SUBMITTED"
        resp = api.pay_reserve_claim(claim["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_PAYABLE, expected_status=409)

    def test_pay_equal_to_balance_allowed_then_over_rejected(self, api):
        """PRD §3.4: "the claim must be `APPROVED` — otherwise
        `ERR_CLAIM_NOT_PAYABLE` — and the lease's `reserve_balance_cents`
        must be at least `approved_amount_cents`, with equality explicitly
        payable; a shortfall is `ERR_RESERVE_BALANCE_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/pay_claim_equal_to_balance_allowed
        """
        lease, _aircraft, lessee, _report = create_lease_with_accepted_report(
            {"period_month": "2026-08", "flight_hours": 100.0, "flight_cycles": 20},
            reserve_rate_per_fh_cents=4000, reserve_rate_per_fc_cents=8000)
        claim_a = create_approved_claim(lease["id"], lessee["id"], 560000,
                                        maintenance_event_ref="APU-1")
        claim_b = create_approved_claim(lease["id"], lessee["id"], 1,
                                        maintenance_event_ref="APU-2")

        paid = validate_success(api.pay_reserve_claim(claim_a["id"], FINANCE))
        assert paid["status"] == "PAID"
        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["reserve_balance_cents"] == 0, (
            f"paying exactly the balance must succeed (>= is inclusive); "
            f"balance now {lease_now['reserve_balance_cents']}")

        # 1 cent against balance 0 is a shortfall.
        resp = api.pay_reserve_claim(claim_b["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_RESERVE_BALANCE_EXCEEDED, expected_status=422)

    def test_pay_one_cent_over_balance_rejected(self, api):
        """PRD §3.4: "the lease's `reserve_balance_cents` must be at least
        `approved_amount_cents`, with equality explicitly payable; a
        shortfall is `ERR_RESERVE_BALANCE_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/pay_claim_equal_to_balance_allowed
        """
        # Approved amount exactly one cent over the current balance.
        lease, _aircraft, lessee, _report = create_lease_with_accepted_report(
            {"period_month": "2026-08", "flight_hours": 100.0, "flight_cycles": 20},
            reserve_rate_per_fh_cents=4000, reserve_rate_per_fc_cents=8000)
        claim = create_approved_claim(lease["id"], lessee["id"], 560001,
                                      maintenance_event_ref="APU-OVER")
        resp = api.pay_reserve_claim(claim["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_RESERVE_BALANCE_EXCEEDED, expected_status=422)
        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["reserve_balance_cents"] == 560000, (
            "the rejected payment must not touch the ledger")


class TestClaimReversal:
    def test_pay_then_reverse_restores_balance(self, api):
        """PRD §3.4: "Should a wire bounce or a payment prove mistaken, a
        `FinanceManager` may reverse it: the claim returns `PAID → APPROVED`,
        the approved amount comes back out of `reserve_reimbursed_cents`,
        and the balance is recomputed."
        PRD §2.9: "`reserve_balance_cents` is a derived invariant, always
        equal to `reserve_accrued_cents` minus `reserve_reimbursed_cents`
        minus `reserve_forfeited_cents`."

        Design: Difficulty/compensating_invariant/reserve_pay_reverse_restores_balance
        """
        lease, _aircraft, lessee, _report = create_lease_with_accepted_report(
            {"period_month": "2026-08", "flight_hours": 100.0, "flight_cycles": 20},
            reserve_rate_per_fh_cents=4000, reserve_rate_per_fc_cents=8000)
        claim = create_paid_claim(lease["id"], lessee["id"], 60000,
                                  maintenance_event_ref="LG-OH-1")
        assert claim["status"] == "PAID"
        lease_mid = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_mid["reserve_balance_cents"] == 500000

        reversed_claim = validate_success(api.reverse_claim_payment(claim["id"], FINANCE))
        assert reversed_claim["status"] == "APPROVED"

        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["reserve_accrued_cents"] == 560000
        assert lease_now["reserve_reimbursed_cents"] == 0
        assert lease_now["reserve_forfeited_cents"] == 0
        assert lease_now["reserve_balance_cents"] == 560000
        assert_lease_reserve_invariants(lease_now)

    def test_reverse_payment_reimbursed_counter_returns_to_zero(self, api):
        """PRD §3.4: "Paying moves the claim to `PAID`, adds the approved
        amount to `reserve_reimbursed_cents`, and recomputes the balance.
        Should a wire bounce or a payment prove mistaken, a `FinanceManager`
        may reverse it: the claim returns `PAID → APPROVED`, the approved
        amount comes back out of `reserve_reimbursed_cents`, and the balance
        is recomputed."

        Design: Difficulty/compensating_invariant/reserve_pay_reverse_restores_balance
        """
        lease, _aircraft, lessee, _report = create_lease_with_accepted_report(
            {"period_month": "2026-08", "flight_hours": 100.0, "flight_cycles": 20},
            reserve_rate_per_fh_cents=4000, reserve_rate_per_fc_cents=8000)
        claim = create_paid_claim(lease["id"], lessee["id"], 200000,
                                  maintenance_event_ref="LG-OH-2")
        lease_mid = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_mid["reserve_reimbursed_cents"] == 200000
        assert lease_mid["reserve_balance_cents"] == 360000

        reversed_claim = validate_success(api.reverse_claim_payment(claim["id"], FINANCE))
        assert reversed_claim["status"] == "APPROVED"
        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["reserve_reimbursed_cents"] == 0
        assert lease_now["reserve_balance_cents"] == 560000
        assert_lease_reserve_invariants(lease_now)
