"""Claims, adjudication, parallel order dimensions, the DENIED_FINAL cascade,
and the append-only HSA ledger."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_hsa_ledger_entry,
    create_payer_plan,
    create_active_patient,
    create_program,
    create_manual_order,
    add_order_line,
    submit_order,
    create_claim,
    submit_claim,
    adjudicate_claim,
    appeal_claim,
    get_order,
    get_hsa_account,
    get_hsa_balance,
    post_hsa_debit,
    post_hsa_credit,
    setup_active_patient_with_item,
    build_submitted_order,
    build_delivered_order,
    INTAKE,
    BILLING,
    make_patient_headers,
)


def _delivered_insured_order(api, quantity=10, hsa_credit=0, **kwargs):
    ctx = setup_active_patient_with_item(on_hand_qty=500,
                                         hsa_initial_credit_cents=hsa_credit, **kwargs)
    return build_delivered_order(ctx, quantity=quantity)


class TestClaimPricingVariants:
    def test_claim_pricing_insured_variant(self, api):
        """PRD §3.8: "for an insured plan (`MEDICARE_DMEPOS` or `COMMERCIAL`)
        each line contributes its `line_allowed_cents`". PRD §3.8: "Under the
        insured variant, each line's coinsurance is computed as the line's
        allowed amount multiplied by the plan's `coinsurance_pct`, rounded half
        up to 2 decimal places **per line**, and those rounded per-line amounts
        are then summed". PRD §3.8: "A `PAID` outcome ... `insurer_paid_cents`
        is set to `total_allowed_cents` minus `patient_resp_cents`".

        Design: Difficulty/dual_variant_calc/claim_pricing_insured_vs_cash_variant
        """
        ctx = _delivered_insured_order(api, quantity=10)
        claim = create_claim(ctx["order"]["id"])
        # 185.00 unit allowance x 10 = 1850.00 allowed; 20% coinsurance = 370.00.
        assert claim["total_allowed_cents"] == pytest.approx(1850.00, abs=0.001)
        assert claim["patient_resp_cents"] == pytest.approx(370.00, abs=0.001)

        submit_claim(claim["id"])
        paid = adjudicate_claim(claim["id"], "PAID")
        assert paid["status"] == "PAID"
        assert paid["insurer_paid_cents"] == pytest.approx(1480.00, abs=0.001)

    def test_claim_pricing_cash_hsa_variant(self, api):
        """PRD §3.8: "for a `CASH_HSA` plan each line contributes the item's
        `retail_price_cents` multiplied by the line `quantity`, rounded half up
        to 2 decimal places". PRD §3.8: "Under the `CASH_HSA` variant the
        patient pays one hundred percent: `patient_resp_cents` equals
        `total_allowed_cents` on the retail basis, and `insurer_paid_cents` is
        0."

        Design: Difficulty/dual_variant_calc/claim_pricing_insured_vs_cash_variant
        """
        ctx = _delivered_insured_order(
            api, quantity=10, hsa_credit=500000,
            plan_type="CASH_HSA", coinsurance_pct=1.00, cycle_months=1,
        )
        claim = create_claim(ctx["order"]["id"])
        # Retail basis: 300 x 10 = 3000.00; the patient pays 100%.
        assert claim["total_allowed_cents"] == pytest.approx(3000.00, abs=0.001)
        assert claim["patient_resp_cents"] == pytest.approx(3000.00, abs=0.001)
        assert claim["insurer_paid_cents"] == pytest.approx(0, abs=0.001)


class TestOrderParallelDimensions:
    def _setup_submitted_claim(self, api):
        ctx = _delivered_insured_order(api, quantity=10)
        claim = create_claim(ctx["order"]["id"])
        submit_claim(claim["id"])
        return ctx, claim

    def test_fulfillment_terminal_while_billing_walks_denial(self, api):
        """PRD §3.5: "Every order carries **two parallel state dimensions** that
        evolve independently on one row." PRD §3.8: "A `DENIED` outcome on a
        `SUBMITTED` claim moves it to `DENIED`, stamps `adjudicated_at`, and
        moves the order's billing to `CLAIM_DENIED`".

        Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_billing_dimensions
        """
        ctx, claim = self._setup_submitted_claim(api)
        assert ctx["order"]["fulfillment_status"] == "FULFILLED"

        adjudicate_claim(claim["id"], "DENIED")
        order = get_order(ctx["order"]["id"])
        assert order["fulfillment_status"] == "FULFILLED"
        assert order["billing_status"] == "CLAIM_DENIED"

    def test_billing_reaches_paid_settled_after_appeal(self, api):
        """PRD §3.8: "A `DENIED` claim may be appealed by a `BillingSpecialist`,
        moving it to `APPEALED` and the order's billing to `APPEAL_PENDING`".
        PRD §3.8: "A `PAID` outcome on a claim in `SUBMITTED` or `APPEALED`
        status moves the claim to the terminal `PAID` state ... the order's
        billing moves to `PAID_SETTLED`".

        Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_billing_dimensions
        """
        ctx, claim = self._setup_submitted_claim(api)
        adjudicate_claim(claim["id"], "DENIED")
        appeal_claim(claim["id"])
        order_mid = get_order(ctx["order"]["id"])
        assert order_mid["billing_status"] == "APPEAL_PENDING"
        assert order_mid["fulfillment_status"] == "FULFILLED"

        paid = adjudicate_claim(claim["id"], "PAID")
        assert paid["status"] == "PAID"
        assert paid["insurer_paid_cents"] == pytest.approx(1480.00, abs=0.001)
        order_end = get_order(ctx["order"]["id"])
        assert order_end["billing_status"] == "PAID_SETTLED"
        assert order_end["fulfillment_status"] == "FULFILLED"


class TestDeniedFinalCascade:
    def _setup_appealed_claim(self, api):
        ctx = _delivered_insured_order(api, quantity=10, hsa_credit=2000)
        # An ACTIVE program that must be suspended by the floor-breach cascade.
        program = create_program(ctx["patient"]["id"], category="INCONTINENCE",
                                 frequency_days=30, start_date="2026-05-01")
        claim = create_claim(ctx["order"]["id"])
        submit_claim(claim["id"])
        adjudicate_claim(claim["id"], "DENIED")
        appeal_claim(claim["id"])
        account = get_hsa_account(ctx["patient"]["id"])
        return ctx, claim, program, account

    def test_denied_final_repricing_and_patient_billed(self, api):
        """PRD §3.8: "The claim moves to the terminal `DENIED_FINAL` state and
        is re-priced under the denial variant above, so the full allowed amount
        shifts to the patient. The order's billing moves to `PATIENT_BILLED`."

        Design: Difficulty/transitive_cascade/denial_final_hsa_floor_cascade
        """
        ctx, claim, _program, _account = self._setup_appealed_claim(api)
        final = adjudicate_claim(claim["id"], "DENIED")
        assert final["status"] == "DENIED_FINAL"
        assert final["patient_resp_cents"] == pytest.approx(1850.00, abs=0.001), (
            f"full allowed amount shifts to the patient, got {final['patient_resp_cents']}"
        )
        order = get_order(ctx["order"]["id"])
        assert order["billing_status"] == "PATIENT_BILLED"

    def test_denied_final_hsa_debit_and_floor_suspension(self, api):
        """PRD §3.8: "The system then posts a `DEBIT` entry to the patient's HSA
        ledger for the full `patient_resp_cents`". PRD §3.8: "After the debit
        posts, if the account's `balance_cents` has fallen below the reorder
        floor of 500 cents, every `ACTIVE` resupply program of the patient is
        suspended with `suspend_reason` `HSA_FLOOR_BREACH`".

        Design: Difficulty/transitive_cascade/denial_final_hsa_floor_cascade
        """
        ctx, claim, program, account = self._setup_appealed_claim(api)
        adjudicate_claim(claim["id"], "DENIED")

        # 2000 - 1850 debit = 150, below the 500-cent reorder floor.
        assert get_hsa_balance(account["id"]) == pytest.approx(150, abs=0.001)
        program_after = validate_success(
            api.get_resupply_program(program["id"], INTAKE), expected_status=200
        )
        assert program_after["status"] == "SUSPENDED"
        assert program_after["suspend_reason"] == "HSA_FLOOR_BREACH"


class TestClaimPreconditions:
    def test_claim_appeal_from_paid_rejected(self, api):
        """PRD §3.8: "appealing a claim that is not `DENIED` — including a
        `PAID` one — is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/claim_appeal_from_paid_rejected
        """
        ctx = _delivered_insured_order(api, quantity=10)
        claim = create_claim(ctx["order"]["id"])
        submit_claim(claim["id"])
        adjudicate_claim(claim["id"], "PAID")

        resp = api.appeal_claim(claim["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_claim_on_unfulfilled_order_rejected(self, api):
        """PRD §3.8: "Claim creation requires the order's fulfillment to be
        `FULFILLED`, its billing to be `UNBILLED`, and no existing claim for the
        order; any violation rejects creation with `ERR_CLAIM_NOT_SUBMITTABLE`
        (HTTP 409)."

        Design: Corner/validations/claim_on_unfulfilled_order_rejected
        """
        ctx = setup_active_patient_with_item(on_hand_qty=100)
        ctx = build_submitted_order(ctx, quantity=5)
        resp = api.create_claim({"order_id": ctx["order"]["id"]}, BILLING)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SUBMITTABLE)


class TestHsaDebitBoundary:
    def _cash_patient_with_hsa(self, api, credit):
        plan = create_payer_plan(plan_type="CASH_HSA", coinsurance_pct=1.00, cycle_months=1)
        patient = create_active_patient(plan["id"], hsa_initial_credit_cents=credit)
        return patient, get_hsa_account(patient["id"])

    def test_hsa_debit_exactly_equal_to_balance_succeeds(self, api):
        """PRD §3.8: "A debit is accepted only when the amount does not exceed
        the account's `balance_cents` — equality is allowed and leaves the
        balance at exactly zero".

        Design: Difficulty/boundary_precision_check/hsa_debit_exact_balance_boundary
        """
        _patient, account = self._cash_patient_with_hsa(api, 200000)
        entry = post_hsa_debit(account["id"], 200000, reason="full balance debit")
        assert_hsa_ledger_entry(entry)
        assert entry["entry_type"] == "DEBIT"
        assert get_hsa_balance(account["id"]) == pytest.approx(0, abs=0.001)

    def test_hsa_debit_one_cent_over_zero_balance_rejected(self, api):
        """PRD §3.8: "A debit is accepted only when the amount does not exceed
        the account's `balance_cents` ... otherwise the posting is rejected
        with `ERR_INSUFFICIENT_HSA`."

        Design: Difficulty/boundary_precision_check/hsa_debit_exact_balance_boundary
        """
        _patient, account = self._cash_patient_with_hsa(api, 200000)
        post_hsa_debit(account["id"], 200000, reason="full balance debit")
        resp = api.post_hsa_debit(account["id"],
                                  {"amount_cents": 1, "reason": "overdraw attempt"}, BILLING)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_HSA)


class TestHsaReversalConservation:
    def _cash_patient_with_hsa(self, api, credit):
        plan = create_payer_plan(plan_type="CASH_HSA", coinsurance_pct=1.00, cycle_months=1)
        patient = create_active_patient(plan["id"], hsa_initial_credit_cents=credit)
        return patient, get_hsa_account(patient["id"])

    def test_debit_reversal_pair_restores_balance(self, api):
        """PRD §3.8: "the `initial_credit_cents`, plus the sum of `amount_cents`
        over all `POSTED` entries of type `CREDIT` or `REVERSAL`, minus the sum
        over all `POSTED` `DEBIT` entries" — a 500 DEBIT paired with its 500
        REVERSAL restores the 2000 balance exactly.

        Design: Difficulty/compensating_invariant/hsa_debit_reversal_conservation
        """
        _patient, account = self._cash_patient_with_hsa(api, 2000)
        debit = post_hsa_debit(account["id"], 500, reason="copay")
        post_hsa_credit(account["id"], 500, reason="reversal",
                        reverses_entry_id=debit["id"])
        assert get_hsa_balance(account["id"]) == pytest.approx(2000, abs=0.001)

    def test_reversal_is_append_only(self, api):
        """PRD §2.4: "A ledger entry is immutable and append-only". PRD §3.8:
        "Every entry is born `POSTED` — the ledger has no other status" — the
        reversed DEBIT remains as a POSTED row alongside the REVERSAL.

        Design: Difficulty/compensating_invariant/hsa_debit_reversal_conservation
        """
        _patient, account = self._cash_patient_with_hsa(api, 2000)
        debit = post_hsa_debit(account["id"], 500, reason="copay")
        reversal = post_hsa_credit(account["id"], 500, reason="reversal",
                                   reverses_entry_id=debit["id"])
        assert reversal["entry_type"] == "REVERSAL"

        entries = validate_success(api.list_hsa_entries(account["id"], BILLING),
                                   expected_status=200)
        assert len(entries) == 2
        by_type = {e["entry_type"]: e for e in entries}
        assert set(by_type) == {"DEBIT", "REVERSAL"}
        for entry in entries:
            assert_hsa_ledger_entry(entry)


class TestHsaLedgerRules:
    def test_hsa_running_balance_mixed_entries(self, api):
        """PRD §3.8: "the `initial_credit_cents`, plus the sum of `amount_cents`
        over all `POSTED` entries of type `CREDIT` or `REVERSAL`, minus the sum
        over all `POSTED` `DEBIT` entries; each posting recomputes it" —
        1000 + 300 - 100 - 50 = 1150.

        Design: Corner/calculations/hsa_running_balance_mixed_entries
        """
        plan = create_payer_plan(plan_type="CASH_HSA", coinsurance_pct=1.00, cycle_months=1)
        patient = create_active_patient(plan["id"], hsa_initial_credit_cents=1000)
        account = get_hsa_account(patient["id"])

        post_hsa_credit(account["id"], 300, reason="deposit")
        post_hsa_debit(account["id"], 100, reason="copay")
        post_hsa_debit(account["id"], 50, reason="copay2")

        assert get_hsa_balance(account["id"]) == pytest.approx(1150, abs=0.001)

    def test_reversal_of_non_debit_entry_rejected(self, api):
        """PRD §3.8: "A reversal is accepted only when `reverses_entry_id`
        references a `POSTED` `DEBIT` entry of the same account, otherwise the
        posting is rejected with `ERR_HSA_ENTRY_NOT_REVERSIBLE` (HTTP 409)."

        Design: Corner/validations/reversal_of_non_debit_entry_rejected
        """
        plan = create_payer_plan(plan_type="CASH_HSA", coinsurance_pct=1.00, cycle_months=1)
        patient = create_active_patient(plan["id"], hsa_initial_credit_cents=1000)
        account = get_hsa_account(patient["id"])
        credit = post_hsa_credit(account["id"], 100, reason="deposit")

        resp = api.post_hsa_credit(
            account["id"],
            {"amount_cents": 100, "reason": "bogus reversal",
             "reverses_entry_id": credit["id"]},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_HSA_ENTRY_NOT_REVERSIBLE)
