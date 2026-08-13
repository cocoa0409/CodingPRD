"""Recovery posting: balance-to-zero cascades, contingency fee rounding,
post-write-off recovery accounting under the default DIRECT methodology, and
the polymorphic-reference / amount-cap guards."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_early_out_placement,
    assert_recovery_transaction,
    create_account,
    post_recovery,
    read_account,
    setup_agency_placement_direct,
    setup_early_out_placement,
    setup_posted_bad_debt_writeoff,
    validate_error,
    validate_success,
)

COLLECTOR = TEST_USERS["collector_headers"]
AGENCY = TEST_USERS["agency_headers"]


class TestPostWriteoffRecoveryDirectMethodology:
    def test_direct_methodology_keeps_writeoff_total_untouched(self, api):
        """PRD §3.8: "Recoveries against an already-written-off account follow
        one of two accounting treatments, selected by the reserve methodology in
        force for the account — `DIRECT` by default"
        PRD §3.8: "Under the direct method (`NET_AGAINST_RECOVERY`), the
        recovery simply increases `recovery_total_cents` by the gross amount and
        the historical `bad_debt_writeoff_total_cents` is left untouched — the
        write-off stands as fact and the recovery flows into the allowance."

        Two independent written-off accounts under the default methodology each
        receive a 50000-cent post-write-off recovery.

        Design: Difficulty/dual_variant_calc/writeoff_recovery_direct_vs_allowance_methodology
        """
        acct_b1, wo_b1 = setup_posted_bad_debt_writeoff(
            balance_cents=200000, guarantor_liability_date="2026-01-01",
            creator_id="collector-1", approver_id="officer-1")
        acct_b2, wo_b2 = setup_posted_bad_debt_writeoff(
            balance_cents=200000, guarantor_liability_date="2026-01-01",
            creator_id="collector-1", approver_id="officer-1")
        assert acct_b1["status"] == "WRITTEN_OFF"
        assert acct_b2["status"] == "WRITTEN_OFF"

        post_recovery(acct_b1["id"], payment_kind="POST_WRITEOFF_RECOVERY",
                      amount_cents=50000, write_off_id=wo_b1["id"])
        post_recovery(acct_b2["id"], payment_kind="POST_WRITEOFF_RECOVERY",
                      amount_cents=50000, write_off_id=wo_b2["id"])

        after_b1 = read_account(acct_b1["id"])
        assert after_b1["bad_debt_writeoff_total_cents"] == 200000
        assert after_b1["recovery_total_cents"] == 50000

        after_b2 = read_account(acct_b2["id"])
        assert after_b2["bad_debt_writeoff_total_cents"] == 200000
        assert after_b2["recovery_total_cents"] == 50000

    def test_full_post_writeoff_recovery_closes_account(self, api):
        """PRD §3.8: "Both treatments then run the same closure check: when the
        cumulative post-write-off recoveries against a write-off reach or exceed
        that write-off's `amount_cents` and the account is still `WRITTEN_OFF`,
        the account transitions to `CLOSED_PAID` with its `version` incremented
        and its `credit_reporting_status` unchanged."

        Design: Difficulty/dual_variant_calc/writeoff_recovery_direct_vs_allowance_methodology
        """
        account, write_off = setup_posted_bad_debt_writeoff(
            balance_cents=200000, guarantor_liability_date="2026-01-01",
            creator_id="collector-1", approver_id="officer-1")
        assert account["status"] == "WRITTEN_OFF"

        post_recovery(account["id"], payment_kind="POST_WRITEOFF_RECOVERY",
                      amount_cents=200000, write_off_id=write_off["id"])

        after = read_account(account["id"])
        assert after["status"] == "CLOSED_PAID"
        assert after["recovery_total_cents"] == 200000
        # DIRECT methodology: the historical write-off total stands.
        assert after["bad_debt_writeoff_total_cents"] == 200000


class TestBalanceToZeroCascade:
    def test_agency_remittance_full_balance_closes_account_and_placement(self, api):
        """PRD §3.8: "Whenever a posting drives the account's balance to zero,
        the account closes as `CLOSED_PAID` and any active placement closes with
        it — `COMPLETED_PAID` for early-out, `CLOSED_PAID` for agency — with the
        account's `version` incremented."
        PRD §3.8: "The attributed placement's `recovered_cents` grows by the
        gross amount."

        Design: Difficulty/transitive_cascade/recovery_drives_balance_to_zero_cascades_to_placement_closure
        """
        account, placement = setup_agency_placement_direct(
            balance_cents=90000, guarantor_liability_date="2026-01-01",
            agency_name="AG_X", contingency_fee_bps=2000)
        assert account["status"] == "IN_COLLECTIONS"

        transaction = post_recovery(
            account["id"], headers=AGENCY, payment_kind="AGENCY_REMITTANCE",
            amount_cents=90000, attributed_placement_id=placement["id"])
        assert_recovery_transaction(transaction)

        acct_after = read_account(account["id"])
        assert acct_after["current_balance_cents"] == 0
        assert acct_after["status"] == "CLOSED_PAID"

        placement_after = validate_success(
            api.get_agency_placement(placement["id"], COLLECTOR), 200)
        assert placement_after["status"] == "CLOSED_PAID"
        assert placement_after["recovered_cents"] == 90000

    def test_early_out_remittance_full_balance_completes_placement(self, api):
        """PRD §3.8: "Whenever a posting drives the account's balance to zero,
        the account closes as `CLOSED_PAID` and any active placement closes with
        it — `COMPLETED_PAID` for early-out, `CLOSED_PAID` for agency — with the
        account's `version` incremented."
        PRD §3.4: "The placement's `recovered_cents` starts at zero and
        accumulates the gross amount of every early-out remittance later
        attributed to it."

        Design: Difficulty/transitive_cascade/recovery_drives_balance_to_zero_cascades_to_placement_closure
        """
        account, placement = setup_early_out_placement(
            balance_cents=60000, guarantor_liability_date="2026-06-01",
            vendor_name="VENDOR_A", contingency_fee_bps=1500)
        assert account["status"] == "IN_EARLY_OUT"

        post_recovery(
            account["id"], payment_kind="EARLY_OUT_REMITTANCE",
            amount_cents=60000, attributed_placement_id=placement["id"])

        acct_after = read_account(account["id"])
        assert acct_after["current_balance_cents"] == 0
        assert acct_after["status"] == "CLOSED_PAID"

        placement_after = validate_success(
            api.get_early_out_placement(placement["id"], COLLECTOR), 200)
        assert_early_out_placement(placement_after)
        assert placement_after["status"] == "COMPLETED_PAID"
        assert placement_after["recovered_cents"] == 60000


class TestContingencyFee:
    def test_agency_remittance_fee_rounds_half_up(self, api):
        """PRD §3.8: "When the payment is attributed to a placement, the
        vendor's contingency fee is computed as the `amount_cents` multiplied by
        the placement's `contingency_fee_bps` and divided by ten thousand,
        rounded half up to the nearest cent, and the transaction's
        `net_to_hospital_cents` is the gross amount minus that fee"
        PRD §3.8: "A posted transaction reduces the account's
        `current_balance_cents` by the gross `amount_cents` — the patient paid
        gross, so the balance falls by gross even when a fee is skimmed"

        33333 cents at 2000 bps: fee = round_half_up(6666.6) = 6667, so
        net_to_hospital_cents = 33333 - 6667 = 26666.

        Design: Corner/calculations/vendor_contingency_fee_calculation_rounds_half_up
        """
        account, placement = setup_agency_placement_direct(
            balance_cents=100000, guarantor_liability_date="2026-01-01",
            agency_name="AG_Y", contingency_fee_bps=2000)

        transaction = post_recovery(
            account["id"], headers=AGENCY, payment_kind="AGENCY_REMITTANCE",
            amount_cents=33333, attributed_placement_id=placement["id"])
        assert_recovery_transaction(transaction)
        assert transaction["net_to_hospital_cents"] == 26666

        acct_after = read_account(account["id"])
        assert acct_after["current_balance_cents"] == 66667
        assert acct_after["recovery_total_cents"] == 33333

        placement_after = validate_success(
            api.get_agency_placement(placement["id"], COLLECTOR), 200)
        assert placement_after["recovered_cents"] == 33333


class TestRecoveryGuards:
    def test_agency_remittance_with_early_out_reference_rejected(self, api):
        """PRD §3.8: "an `EARLY_OUT_REMITTANCE` must carry an
        `attributed_placement_id` resolving to an early-out placement, an
        `AGENCY_REMITTANCE` must carry an `attributed_placement_id` resolving to
        a collection agency placement, an `INSTALLMENT` must carry a
        `payment_plan_id`, and a `POST_WRITEOFF_RECOVERY` must carry a
        `write_off_id`. A reference that is missing or resolves to the wrong
        family is rejected with `ERR_RECOVERY_FK_MISMATCH`."

        Design: Corner/validations/recovery_fk_mismatch_polymorphic
        """
        account, early_out = setup_early_out_placement(
            balance_cents=80000, guarantor_liability_date="2026-06-01",
            vendor_name="VENDOR_A", contingency_fee_bps=1500)

        resp = api.post_recovery_transaction(
            {"account_id": account["id"], "payment_kind": "AGENCY_REMITTANCE",
             "amount_cents": 5000, "attributed_placement_id": early_out["id"]},
            COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_RECOVERY_FK_MISMATCH)

    def test_lump_sum_above_balance_rejected(self, api):
        """PRD §3.8: "The amount is then checked against the recoverable ceiling
        for its target and rejected with `ERR_RECOVERY_EXCEEDS_BALANCE` when it
        exceeds it: for direct payments the ceiling is the account's
        `current_balance_cents`"

        Design: Corner/validations/recovery_exceeds_balance_rejected
        """
        account = create_account(
            balance_cents=50000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-N9", patient_name="N9")
        resp = api.post_recovery_transaction(
            {"account_id": account["id"], "payment_kind": "LUMP_SUM",
             "amount_cents": 99999},
            COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_RECOVERY_EXCEEDS_BALANCE)
