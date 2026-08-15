"""Fee assessments, payments, the allocation waterfall, idempotency, overpayment."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    api_client, ApiErrorId,
    create_fee_catalog_item_payload,
    setup_open_year, setup_year_with_fee, add_student_with_account,
    setup_account_with_assessment, setup_account_with_plan,
    pay_and_settle, current_account_version, set_clock,
    make_family_headers, NON_EXISTENT_UUID,
)


class TestAssessmentVoid:
    def test_assessment_void_success_then_activity_blocked(self, bookkeeper_headers):
        """PRD §3.5: "A `Bookkeeper` may void an assessment only while it is still
        `ASSESSED` and completely untouched: allocated_cents and refunded_cents
        must both be zero, otherwise `ERR_ASSESSMENT_HAS_ACTIVITY` (HTTP 409);
        a voided assessment is excluded from all account aggregates and the
        account recomputes."
        PRD §3.5: "Whatever remains flows to the account's fee assessments that
        have outstanding_cents above zero and status `ASSESSED`, `PARTIALLY_PAID`,
        or `DELINQUENT`, ordered by created_at ascending"

        Design: Corner/state_machines/assessment_void_success_then_activity_blocked
        """
        env = setup_year_with_fee(fee_amount=1000)
        student, account = add_student_with_account(env["year"]["id"])
        a1 = get_success_data(api_client.create_fee_assessment(
            account["id"], {"fee_item_id": env["fee_item"]["id"],
                            "assessed_amount_cents": 2500}, bookkeeper_headers))
        # Advance the logical clock so the second assessment carries a strictly
        # later created_at — stage-2 orders by created_at ascending (PRD §3.5),
        # and under a frozen clock the amount-desc tie-break would fire instead.
        set_clock("2026-08-02T00:00:00Z")
        a2 = get_success_data(api_client.create_fee_assessment(
            account["id"], {"fee_item_id": env["fee_item"]["id"],
                            "assessed_amount_cents": 4000}, bookkeeper_headers))
        pay_and_settle(account["id"], 1500, idempotency_key="k1")
        a1_now = get_success_data(api_client.get_fee_assessment(
            account["id"], a1["id"], bookkeeper_headers))
        assert a1_now["allocated_cents"] == 1500, (
            f"Waterfall fills the oldest assessment first; got {a1_now['allocated_cents']}")
        assert a1_now["status"] == "PARTIALLY_PAID"
        # Voiding the touched assessment fails
        resp = api_client.void_fee_assessment(account["id"], a1["id"], bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_HAS_ACTIVITY)
        # Voiding the untouched one succeeds and shrinks assessed_cents
        voided = get_success_data(api_client.void_fee_assessment(
            account["id"], a2["id"], bookkeeper_headers))
        assert voided["status"] == "VOID"
        account = get_success_data(api_client.get_student_account(account["id"], bookkeeper_headers))
        assert account["assessed_cents"] == 2500, (
            f"VOID rows contribute nothing: 6500 - 4000 = 2500, got {account['assessed_cents']}")

    def test_assessment_void_clean_assessment_excluded(self, bookkeeper_headers):
        """PRD §3.5: "a voided assessment is excluded from all account aggregates
        and the account recomputes."

        Design: Corner/state_machines/assessment_void_success_then_activity_blocked
        """
        env = setup_account_with_assessment(assessed_amount_cents=2500)
        voided = get_success_data(api_client.void_fee_assessment(
            env["account"]["id"], env["assessment"]["id"], bookkeeper_headers))
        assert voided["status"] == "VOID"
        account = get_success_data(api_client.get_student_account(
            env["account"]["id"], bookkeeper_headers))
        assert account["assessed_cents"] == 0
        assert account["balance_cents"] == 0


class TestPaymentBasics:
    def test_invalid_request_zero_amount(self, family_headers):
        """PRD §2.10: "Required fields must be present, enums valid, and integers
        in range — amount_cents greater than zero, a school year's end_date
        strictly after its start_date, refund_partial_days strictly greater than
        refund_full_days, basis-point percentages within zero to ten thousand,
        capacity at least 1 — otherwise `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.5: "A **payment** is initiated by a `FamilyMember` with an
        amount_cents greater than zero"

        Design: Corner/validations/invalid_request_zero_amount
        """
        from test_helpers import setup_open_year, add_student_with_account
        env = setup_open_year()
        student, account = add_student_with_account(env["year"]["id"])
        resp = api_client.create_payment(
            account["id"],
            {"amount_cents": 0, "method": "CARD", "idempotency_key": "k0"},
            family_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_payment_key_rejected(self, family_headers):
        """PRD §3.5: "a client-supplied idempotency_key that must be unique per
        account among payments that are not `FAILED` — a reused key is rejected
        with `ERR_DUPLICATE_PAYMENT` (HTTP 409)."

        Design: Corner/validations/duplicate_payment_key_rejected
        """
        env = setup_account_with_assessment(assessed_amount_cents=3000)
        account_id = env["account"]["id"]
        payment = get_success_data(api_client.create_payment(
            account_id, {"amount_cents": 3000, "method": "CARD",
                         "idempotency_key": "k-dup"}, family_headers))
        get_success_data(api_client.settle_payment(
            account_id, payment["id"], {"outcome": "SUCCEEDED"}, family_headers))
        resp = api_client.create_payment(
            account_id, {"amount_cents": 500, "method": "CARD",
                         "idempotency_key": "k-dup"}, family_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PAYMENT)

    def test_failed_payment_key_reuse_allowed(self, family_headers):
        """PRD §3.5: "a client-supplied idempotency_key that must be unique per
        account among payments that are not `FAILED`"

        Design: Corner/validations/failed_payment_key_reuse_allowed
        """
        env = setup_account_with_assessment(assessed_amount_cents=3000)
        account_id = env["account"]["id"]
        p1 = get_success_data(api_client.create_payment(
            account_id, {"amount_cents": 3000, "method": "CARD",
                         "idempotency_key": "k-reuse"}, family_headers))
        get_success_data(api_client.settle_payment(
            account_id, p1["id"], {"outcome": "FAILED"}, family_headers))
        resp = api_client.create_payment(
            account_id, {"amount_cents": 3000, "method": "CARD",
                         "idempotency_key": "k-reuse"}, family_headers)
        data = validate_success(resp, 201)
        assert data["status"] == "PENDING"

    def test_payment_failed_settle_no_side_effects(self, bookkeeper_headers, family_headers):
        """PRD §3.5: "An outcome of `FAILED` moves the payment to `FAILED` and
        writes nothing — no allocations, no ledger rows."

        Design: Corner/state_machines/payment_failed_settle_no_side_effects
        """
        env = setup_account_with_assessment(assessed_amount_cents=3000)
        account_id = env["account"]["id"]
        payment = get_success_data(api_client.create_payment(
            account_id, {"amount_cents": 3000, "method": "CARD",
                         "idempotency_key": "k1"}, family_headers))
        resp = api_client.settle_payment(account_id, payment["id"],
                                         {"outcome": "FAILED"}, family_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "FAILED"
        allocs, alloc_meta = validate_paginated(api_client.list_payment_allocations(
            account_id, payment["id"], bookkeeper_headers))
        assert alloc_meta["total_count"] == 0 and allocs == []
        account = get_success_data(api_client.get_student_account(account_id, bookkeeper_headers))
        assert account["balance_cents"] == 3000
        assert account["paid_cents"] == 0
        ledger, ledger_meta = validate_paginated(api_client.list_ledger_entries(
            account_id, bookkeeper_headers))
        assert ledger_meta["total_count"] == 0 and ledger == []

    def test_settle_immediately_visible_on_read(self, bookkeeper_headers, family_headers):
        """PRD §2.8: "Derived state is recomputed eagerly. Whenever an event changes
        an account's underlying rows — an assessment created or voided, a waiver
        applied or revoked, a payment settled, a refund executed, a write-off, an
        aging sweep — the account's aggregates (assessed_cents, waived_cents,
        paid_cents, balance_cents, family_balance_cents) and its posture are
        recomputed immediately"

        Design: Corner/consistency_model/settle_immediately_visible_on_read
        """
        env = setup_account_with_assessment(assessed_amount_cents=3000)
        account_id = env["account"]["id"]
        payment = get_success_data(api_client.create_payment(
            account_id, {"amount_cents": 3000, "method": "CARD",
                         "idempotency_key": "k1"}, family_headers))
        get_success_data(api_client.settle_payment(account_id, payment["id"],
                                                   {"outcome": "SUCCEEDED"}, family_headers))
        account = get_success_data(api_client.get_student_account(account_id, bookkeeper_headers))
        assert account["balance_cents"] == 0
        assert account["paid_cents"] == 3000
        fa = get_success_data(api_client.get_fee_assessment(
            account_id, env["assessment"]["id"], bookkeeper_headers))
        assert fa["status"] == "PAID"


class TestWaterfallOrdering:
    def test_waterfall_proportional_split_rounding_remainder(self, bookkeeper_headers, family_headers):
        """PRD §2.6: "When a stage-1 installment payment is spread across a plan's
        covered assessments, each per-assessment share is rounded half-up to a
        whole cent, and any residual cent of over- or under-allocation is assigned
        to the covered assessment with the earliest created_at."
        PRD §3.5: "That take is spread across the plan's covered assessments
        proportionally to their outstanding obligations captured at plan creation
        (creation-time snapshot weights, frozen even as balances later move)."

        Design: Difficulty/combinatorial_formula/waterfall_proportional_split_rounding_remainder
        """
        # Fees 3333 (created first) and 6667 on disjoint offerings, both covered
        # by one plan of 2 x 5000; settling 5000 takes Stage-1 installment 1.
        from test_helpers import create_offering_payload
        env = setup_year_with_fee(fee_amount=3333)
        year_id, dept_id = env["year"]["id"], env["department"]["id"]
        f1 = env["fee_item"]
        f2 = get_success_data(api_client.create_fee_catalog_item(
            year_id, create_fee_catalog_item_payload(
                name="F2", amount_cents=6667, department_id=dept_id), bookkeeper_headers))
        o1 = get_success_data(api_client.create_offering(year_id, create_offering_payload(
            title="Chem", department_id=dept_id, fee_item_id=f1["id"],
            start_date="2026-09-01", end_date="2026-12-15"), bookkeeper_headers))
        o2 = get_success_data(api_client.create_offering(year_id, create_offering_payload(
            title="Bio", department_id=dept_id, fee_item_id=f2["id"],
            start_date="2027-01-05", end_date="2027-04-30"), bookkeeper_headers))
        student, account = add_student_with_account(year_id)
        get_success_data(api_client.create_enrollment(account["id"], {"offering_id": o1["id"]},
                                                      bookkeeper_headers))
        get_success_data(api_client.create_enrollment(account["id"], {"offering_id": o2["id"]},
                                                      bookkeeper_headers))
        a_v = current_account_version(account["id"])
        plan = get_success_data(api_client.create_payment_plan(
            account["id"], {"installment_count": 2, "first_due_date": "2026-09-05",
                            "interval_days": 30, "expected_account_version": a_v},
            bookkeeper_headers))
        payment = get_success_data(api_client.create_payment(
            account["id"], {"amount_cents": 5000, "method": "CARD",
                            "idempotency_key": "k1"}, family_headers))
        get_success_data(api_client.settle_payment(account["id"], payment["id"],
                                                   {"outcome": "SUCCEEDED"}, family_headers))
        allocs, meta = validate_paginated(api_client.list_payment_allocations(
            account["id"], payment["id"], bookkeeper_headers))
        assert meta["total_count"] == 2
        # half_up(5000*3333/10000)=1667 and half_up(5000*6667/10000)=3334 sum to
        # 5001; the 1-cent overage lands on the earliest-created assessment.
        assert allocs[0]["allocated_cents"] == 1666, (
            f"Earliest-created covered assessment must absorb the remainder: {allocs[0]['allocated_cents']}")
        assert allocs[1]["allocated_cents"] == 3334
        assert all(a["allocation_rule"] == "INSTALLMENT_DUE" for a in allocs)
        installments = get_success_data(api_client.list_plan_installments(
            account["id"], plan["id"], bookkeeper_headers))
        assert installments[0]["paid_cents"] == 5000
        assert installments[0]["status"] == "PAID"

    def test_waterfall_stage2_oldest_first(self, bookkeeper_headers, family_headers):
        """PRD §3.5: "Whatever remains flows to the account's fee assessments that
        have outstanding_cents above zero and status `ASSESSED`, `PARTIALLY_PAID`,
        or `DELINQUENT`, ordered by created_at ascending, ties broken by
        assessed_amount_cents descending, and any further tie resolved by
        created_at ascending again — identifiers are never consulted."
        PRD §3.5: "Each visited assessment takes the smaller of the money remaining
        and its outstanding_cents, writing a PaymentAllocation row — again keyed
        by payment_id and fee_assessment_id with the take as its allocated_cents —
        with allocation_rule `OLDEST_OUTSTANDING`."

        Design: Difficulty/combinatorial_formula/waterfall_proportional_split_rounding_remainder
        """
        env = setup_year_with_fee(fee_amount=1000)
        student, account = add_student_with_account(env["year"]["id"])
        a1 = get_success_data(api_client.create_fee_assessment(
            account["id"], {"fee_item_id": env["fee_item"]["id"],
                            "assessed_amount_cents": 2500}, bookkeeper_headers))
        # Advance the logical clock so a1 is strictly older by created_at —
        # the PRD §3.5 primary sort key — rather than tying and falling to
        # the assessed_amount_cents-descending tie-break.
        set_clock("2026-08-02T00:00:00Z")
        a2 = get_success_data(api_client.create_fee_assessment(
            account["id"], {"fee_item_id": env["fee_item"]["id"],
                            "assessed_amount_cents": 4000}, bookkeeper_headers))
        # 3000 covers A1 fully (2500) then 500 into A2
        payment = get_success_data(api_client.create_payment(
            account["id"], {"amount_cents": 3000, "method": "CARD",
                            "idempotency_key": "k1"}, family_headers))
        get_success_data(api_client.settle_payment(account["id"], payment["id"],
                                                   {"outcome": "SUCCEEDED"}, family_headers))
        allocs, meta = validate_paginated(api_client.list_payment_allocations(
            account["id"], payment["id"], bookkeeper_headers))
        assert meta["total_count"] == 2
        assert allocs[0]["fee_assessment_id"] == a1["id"]
        assert allocs[0]["allocated_cents"] == 2500
        assert allocs[0]["allocation_rule"] == "OLDEST_OUTSTANDING"
        assert allocs[1]["fee_assessment_id"] == a2["id"]
        assert allocs[1]["allocated_cents"] == 500
        fa1 = get_success_data(api_client.get_fee_assessment(account["id"], a1["id"],
                                                             bookkeeper_headers))
        fa2 = get_success_data(api_client.get_fee_assessment(account["id"], a2["id"],
                                                             bookkeeper_headers))
        assert fa1["status"] == "PAID"
        assert fa2["status"] == "PARTIALLY_PAID"
        assert fa2["outstanding_cents"] == 3500


class TestOverpayment:
    def test_overpayment_reject_policy_enforced(self, bookkeeper_headers, family_headers):
        """PRD §3.5: "The `REJECT` check is a pre-check with atomicity: when the
        policy is `REJECT`, the allocatable ceiling — stage-1 installment capacity
        plus stage-2 outstanding — is computed up front, an amount_cents above
        that ceiling is rejected before any allocation row is written, and the
        payment stays unsettled."

        Design: Corner/validations/overpayment_reject_policy_enforced
        """
        env = setup_account_with_assessment(assessed_amount_cents=3000)
        account_id = env["account"]["id"]
        payment = get_success_data(api_client.create_payment(
            account_id, {"amount_cents": 5000, "method": "CARD",
                         "idempotency_key": "k1", "overpayment_policy": "REJECT"},
            family_headers))
        resp = api_client.settle_payment(account_id, payment["id"],
                                         {"outcome": "SUCCEEDED"}, family_headers)
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT_REJECTED)
        allocs, meta = validate_paginated(api_client.list_payment_allocations(
            account_id, payment["id"], bookkeeper_headers))
        assert meta["total_count"] == 0, "REJECT pre-check must be atomic: no rows written"
        payment_now = get_success_data(api_client.get_payment(account_id, payment["id"],
                                                              bookkeeper_headers))
        assert payment_now["status"] == "PENDING"

    def test_overpayment_credit_then_manual_return_roundtrip(self, bookkeeper_headers, family_headers):
        """PRD §3.5: "under `CREDIT_BALANCE` the remainder stays unallocated and
        flows into balance_cents as a negative credit through the paid_cents
        recompute."
        PRD §3.2: "paid_cents — the sum of amount_cents over `SUCCEEDED` payments
        on the account, minus the refund_cents of `EXECUTED` refunds on the
        account."
        PRD §3.7: "A `Bookkeeper` may also create an overpayment return manually
        against a credit balance by supplying amount_cents; the amount must be
        greater than zero and no more than the negation of the account's
        balance_cents — the size of the credit — else `ERR_INVALID_REQUEST`
        (HTTP 400), and the created refund sits `PENDING` with refund_cents set
        to exactly that amount, no proration involved."

        Design: Corner/calculations/overpayment_credit_then_manual_return_roundtrip
        """
        env = setup_account_with_assessment(assessed_amount_cents=3000)
        account_id = env["account"]["id"]
        payment = get_success_data(api_client.create_payment(
            account_id, {"amount_cents": 5000, "method": "CARD",
                         "idempotency_key": "k1",
                         "overpayment_policy": "CREDIT_BALANCE"}, family_headers))
        settled = get_success_data(api_client.settle_payment(
            account_id, payment["id"], {"outcome": "SUCCEEDED"}, family_headers))
        assert settled["allocated_cents"] == 3000, (
            f"Only the outstanding 3000 is allocated; got {settled['allocated_cents']}")
        account = get_success_data(api_client.get_student_account(account_id, bookkeeper_headers))
        assert account["balance_cents"] == -2000, (
            f"Overpayment becomes a negative credit balance; got {account['balance_cents']}")
        refund = get_success_data(api_client.create_refund(
            account_id, {"amount_cents": 2000}, bookkeeper_headers))
        assert refund["reason"] == "OVERPAYMENT_RETURN"
        get_success_data(api_client.execute_refund(account_id, refund["id"], bookkeeper_headers))
        account = get_success_data(api_client.get_student_account(account_id, bookkeeper_headers))
        assert account["balance_cents"] == 0
        assert account["paid_cents"] == 3000, (
            f"5000 gross - 2000 returned = 3000; got {account['paid_cents']}")
