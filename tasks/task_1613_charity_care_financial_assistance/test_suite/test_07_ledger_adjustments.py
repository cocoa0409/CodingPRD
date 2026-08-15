"""Account ledger: payments, derived-field recomputation, write-off rounding
order, coverage/duplicate guards, and OCC on the account version."""
from test_helpers import (
    BILLING,
    ApiErrorId,
    assert_account_adjustment,
    assert_ledger_invariants,
    assert_patient_account,
    create_account,
    create_patient,
    get_account,
    list_determination_adjustments,
    post_adjustment,
    post_payment,
    setup_final_determination,
    setup_posted_writeoff,
    validate_error,
    validate_success,
)


class TestWriteOffRoundingOrder:
    def _two_account_setup(self):
        """FINAL 50.00% determination (income exactly 300.0000%) covering two
        accounts with patient_responsibility 100001 cents each."""
        return setup_final_determination(
            patient_name="Round Robin", mrn="MRN-ROUND-1", ssn_last4="6666",
            date_of_birth="1965-06-06", reported_income=4500000,
            accounts=((100001, 0), (100001, 0)),
            tax_return_amount=4500000, members=(("SELF", 60),),
        )

    def test_writeoff_rounds_per_account_then_sums(self, api):
        """PRD §3.10: "The write-off leg rounds per account first, then sums —
        this order is pinned. Each covered account's write-off amount is its
        creation-fixed `patient_responsibility_cents` (never the current
        `adjusted_balance_cents`) multiplied by the determination's
        `discount_pct` and divided by 100, rounded half-up to whole integer
        cents. The determination's total write-off is the sum of those
        already-rounded per-account integers, with no second rounding pass."

        Design: Difficulty/combinatorial_formula/adjustment_rounding_mode_b_per_account_then_sum
        """
        ctx = self._two_account_setup()
        det = ctx["determination"]
        assert abs(float(det["discount_pct"]) - 50.00) < 1e-6
        adj1 = post_adjustment(ctx["accounts"][0]["id"], det["id"])
        adj2 = post_adjustment(ctx["accounts"][1]["id"], det["id"])
        # round_half_up(100001 * 50.00 / 100) = round_half_up(50000.5) = 50001
        assert adj1["amount_cents"] == 50001
        assert adj2["amount_cents"] == 50001
        spawned = list_determination_adjustments(det["id"])
        write_offs = [
            a for a in spawned
            if a["adjustment_type"] == "WRITE_OFF" and a["status"] == "POSTED"
        ]
        total = sum(a["amount_cents"] for a in write_offs)
        assert total == 100002, (
            "sum of per-account-rounded integers is 100002; the forbidden "
            "sum-then-round order would give 100001"
        )

    def test_writeoff_recomputes_adjusted_balances(self, api):
        """PRD §2.12: "First, `adjusted_balance_cents` is the account's
        creation-fixed `patient_responsibility_cents` minus the sum of
        `amount_cents` over all of the account's `POSTED` write-off
        adjustments."
        PRD §3.10: "The write-off leg rounds per account first, then sums —
        this order is pinned."

        Design: Difficulty/combinatorial_formula/adjustment_rounding_mode_b_per_account_then_sum
        """
        ctx = self._two_account_setup()
        det_id = ctx["determination"]["id"]
        post_adjustment(ctx["accounts"][0]["id"], det_id)
        post_adjustment(ctx["accounts"][1]["id"], det_id)
        for account in ctx["accounts"]:
            refreshed = get_account(account["id"])
            assert refreshed["adjusted_balance_cents"] == 50000, (
                "100001 - 50001 per-account rounded write-off"
            )
            assert_ledger_invariants(refreshed)


class TestAdjustmentGuards:
    def test_adjustment_account_not_covered_rejected(self, api):
        """PRD §3.10: "The determination must exist
        (`ERR_DETERMINATION_NOT_FOUND`), must be `FINAL`
        (`ERR_DETERMINATION_NOT_FINAL`), must cover the target account
        (`ERR_ACCOUNT_NOT_COVERED`, HTTP 422), and the account must show
        `adjusted_balance_cents` greater than zero (`ERR_NO_COLLECTIBLE_BALANCE`)."

        Design: Corner/validations/adjustment_account_not_covered_rejected
        """
        ctx = setup_final_determination(
            patient_name="Cover Carl", mrn="MRN-COV-1", ssn_last4="0034",
            reported_income=2000000, accounts=((100000, 0),),
            tax_return_amount=2000000,
        )
        other = create_account(
            ctx["patient"]["id"], total_charges_cents=200000,
            insurance_paid_cents=0, encounter_date="2026-01-11",
        )
        version = get_account(other["id"])["version"]
        resp = api.post_adjustment(
            other["id"],
            {"determination_id": ctx["determination"]["id"],
             "expected_account_version": version},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_COVERED)

    def test_duplicate_writeoff_rejected(self, api):
        """PRD §3.10: "A duplicate guard rejects the operation if any other
        `POSTED` write-off adjustment already exists for the same
        account-and-determination pair (`ERR_DUPLICATE_ADJUSTMENT`, HTTP 409)."

        Design: Corner/validations/duplicate_writeoff_adjustment_rejected
        """
        ctx = setup_posted_writeoff(
            patient_name="Dup Adj", mrn="MRN-DADJ-1", ssn_last4="0035",
            reported_income=3750000, accounts=((1000000, 0),),
            tax_return_amount=3750000,
        )
        account = ctx["accounts"][0]
        assert account["adjusted_balance_cents"] == 250000, (
            "75.00% write-off leaves a collectible balance, isolating the "
            "duplicate guard"
        )
        det_id = ctx["determination"]["id"]
        version = get_account(account["id"])["version"]
        resp = api.post_adjustment(
            account["id"],
            {"determination_id": det_id, "expected_account_version": version},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ADJUSTMENT)


class TestPaymentGuards:
    def test_payment_zero_amount_rejected(self, api):
        """PRD §3.9: "A `BillingAdministrator` or the `Patient` themselves posts
        a payment against an account with `amount_cents` (strictly positive
        integer cents — zero or negative is `ERR_NONPOSITIVE_AMOUNT`,
        HTTP 422), a `paid_at` timestamp (which later drives refund waterfall
        ordering), and a `method` of `CARD`, `CHECK`, `ACH`, or `CASH`."

        Design: Corner/validations/payment_nonpositive_amount_rejected
        """
        patient = create_patient(
            full_name="Pay Pat", date_of_birth="1990-01-01",
            ssn_last4="0028", mrn="MRN-PAY-1",
        )
        account = create_account(
            patient["id"], total_charges_cents=100000, insurance_paid_cents=0
        )
        resp = api.post_payment(
            account["id"],
            {"amount_cents": 0, "paid_at": "2026-02-01T00:00:00Z", "method": "CARD"},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_NONPOSITIVE_AMOUNT)

    def test_payment_on_resolved_account_rejected(self, api):
        """PRD §3.9: "Payments are a fiscal write, so the target account must
        not be `RESOLVED` (`ERR_ACCOUNT_RESOLVED`, HTTP 409)."

        Design: Corner/validations/payment_on_resolved_account_rejected
        """
        patient = create_patient(
            full_name="Res Rita", date_of_birth="1990-01-01",
            ssn_last4="0029", mrn="MRN-RES2-1",
        )
        account = create_account(
            patient["id"], total_charges_cents=100000, insurance_paid_cents=100000
        )
        assert account["collection_posture"] == "RESOLVED"
        resp = api.post_payment(
            account["id"],
            {"amount_cents": 1000, "paid_at": "2026-02-01T00:00:00Z", "method": "CARD"},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_RESOLVED)


class TestDerivedFieldReconciliation:
    def test_derived_fields_recompute_on_payment(self, api):
        """PRD §2.12: "Second, `effective_payments_cents` is the sum of
        `amount_cents` minus `refunded_cents` over every payment row of the
        account regardless of status — a fully refunded payment therefore
        contributes zero. Third, `overpayment_cents` is the amount by which
        effective payments exceed the adjusted balance, floored at zero.
        Fourth, `amount_outstanding_cents` is the amount by which the adjusted
        balance exceeds effective payments, also floored at zero."

        Design: Corner/cross_cutting_layers/derived_fields_recompute_on_payment_and_adjustment
        """
        patient = create_patient(
            full_name="Derived Deb", date_of_birth="1990-01-01",
            ssn_last4="0057", mrn="MRN-DER-1",
        )
        account = create_account(
            patient["id"], total_charges_cents=100000, insurance_paid_cents=0
        )
        post_payment(account["id"], 60000, paid_at="2026-02-05T00:00:00Z")
        account = get_account(account["id"])
        assert account["effective_payments_cents"] == 60000
        assert account["amount_outstanding_cents"] == 40000
        assert account["overpayment_cents"] == 0
        assert_ledger_invariants(account)

    def test_derived_fields_after_adjustment_and_refund(self, api):
        """PRD §3.10: "An account is retro-eligible when the application's
        `submitted_at` is at or before the account's `first_statement_at` plus
        the pinned policy's `retroactive_window_days`; if `first_statement_at`
        is still null the window has not started and the account is always
        eligible. The refund due is the account's post-write-off
        `overpayment_cents` computed per §2.12 — for a non-eligible account the
        refund due is zero, though the write-off still applies to the balance."

        Design: Corner/cross_cutting_layers/derived_fields_recompute_on_payment_and_adjustment
        """
        ctx = setup_final_determination(
            patient_name="Derived Deb", mrn="MRN-DER-1", ssn_last4="0057",
            reported_income=4200000, accounts=((100000, 0),),
            tax_return_amount=4200000,
        )
        account = ctx["accounts"][0]
        post_payment(account["id"], 60000, paid_at="2026-02-05T00:00:00Z")
        det = ctx["determination"]
        # 4200000 * 100 / 1500000 = 280.0000 -> 50 + (300-280)*(50)/(100) = 60.00
        assert abs(float(det["discount_pct"]) - 60.00) < 1e-6
        adjustment = post_adjustment(account["id"], det["id"])
        assert_account_adjustment(adjustment)
        assert adjustment["amount_cents"] == 60000, "60.00% of 100000 responsibility"
        account = get_account(account["id"])
        assert account["adjusted_balance_cents"] == 40000
        # overpayment 60000-40000 = 20000 is refunded (always retro-eligible
        # with first_statement_at null); effective payments drop to 40000.
        assert account["effective_payments_cents"] == 40000
        assert account["amount_outstanding_cents"] == 0
        assert account["overpayment_cents"] == 0
        assert_ledger_invariants(account)
        spawned = list_determination_adjustments(det["id"])
        refunds = [a for a in spawned if a["adjustment_type"] == "REFUND"]
        assert sum(a["amount_cents"] for a in refunds) == 20000


class TestAdjustmentOcc:
    def test_stale_account_version_rejected(self, api):
        """PRD §2.11: "Posting an account adjustment requires the request to
        carry `expected_account_version`, the client-observed `version` of the
        target account. Payments, statement issuance, and prior adjustments all
        advance the account's `version`; a mismatch against the account's
        current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) so
        that no write-off posts against a ledger the client has not observed."

        Design: Corner/errors/occ_stale_account_version_on_adjustment_create
        """
        ctx = setup_final_determination(
            patient_name="Stale Acc", mrn="MRN-SACC-1", ssn_last4="0048",
            reported_income=3750000, accounts=((1000000, 0),),
            tax_return_amount=3750000,
        )
        account_id = ctx["accounts"][0]["id"]
        stale_version = get_account(account_id)["version"]
        post_payment(account_id, 100000, paid_at="2026-02-15T00:00:00Z")
        resp = api.post_adjustment(
            account_id,
            {"determination_id": ctx["determination"]["id"],
             "expected_account_version": stale_version},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        fresh_version = get_account(account_id)["version"]
        adjustment = validate_success(
            api.post_adjustment(
                account_id,
                {"determination_id": ctx["determination"]["id"],
                 "expected_account_version": fresh_version},
                BILLING,
            ),
            201,
        )
        assert_account_adjustment(adjustment)
        account = get_account(account_id)
        assert account["adjusted_balance_cents"] == 250000, (
            "75.00% write-off of 1000000 responsibility"
        )


class TestImmediateConsistency:
    def test_adjustment_response_matches_immediate_read(self, api):
        """PRD §2.5: "`version` (integer): a system-managed integer that
        increments by 1 on every mutation of the resource, including mutations
        caused by cascades from other entities."
        PRD §3.10: "Posting the write-off creates an `AccountAdjustment` of
        `adjustment_type` `WRITE_OFF` in `POSTED` status with the rounded
        `amount_cents`, recomputes the account's `adjusted_balance_cents`, and
        increments the account's `version` by 1."

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_same_response
        """
        ctx = setup_final_determination(
            patient_name="Immediate Ida", mrn="MRN-IMM9-1", ssn_last4="0059",
            reported_income=2000000, accounts=((100000, 0),),
            tax_return_amount=2000000,
        )
        account_id = ctx["accounts"][0]["id"]
        before = get_account(account_id)
        adjustment = validate_success(
            api.post_adjustment(
                account_id,
                {"determination_id": ctx["determination"]["id"],
                 "expected_account_version": before["version"]},
                BILLING,
            ),
            201,
        )
        assert adjustment["amount_cents"] == 100000
        assert adjustment["adjustment_type"] == "WRITE_OFF"
        assert adjustment["status"] == "POSTED"
        after = get_account(account_id)
        assert_patient_account(after)
        assert after["adjusted_balance_cents"] == 0, (
            "the mutation is fully visible in the immediate follow-up read"
        )
        assert after["collection_posture"] == "RESOLVED"
        assert after["version"] == before["version"] + 1
