"""Representment evidence boundary, the representment-review cycle, second
presentment lockout, escalation stage fees, and the arbitration-won cascade."""
from test_helpers import (
    ApiErrorId,
    create_representment_payload,
    escalate_payload,
    get_case,
    register_representment,
    review_representment,
    setup_filed_chargeback,
    setup_second_presented,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, get_success_data


class TestRepresentmentCycle:
    def test_representment_enters_review_cycle(self, api):
        """PRD §3.6: "it moves the chargeback `FILED` → `REPRESENTED`, the case
        `CHARGEBACK_FILED` → `REPRESENTMENT_REVIEW`, and the transaction
        `CHARGED_BACK` → `RE_PRESENTED`."

        Design: Difficulty/non_linear_state_machine/dispute_case_representment_review_cycle
        """
        _account, _txn, case, chargeback = setup_filed_chargeback(
            balance=50000, amount=12000, claim=12000, claimed_delay=10,
        )
        register_representment(chargeback["id"], merchant_ref="MR-C")
        case_mid = get_case(case["id"])
        assert case_mid["status"] == "REPRESENTMENT_REVIEW", (
            f"case must enter REPRESENTMENT_REVIEW, got {case_mid['status']}"
        )

    def test_reject_loops_back_to_chargeback_filed(self, api):
        """PRD §3.6: "A `REJECT` decision — the issuer stands by its chargeback
        and issues a second presentment — moves the Representment to `REJECTED`,
        the chargeback `REPRESENTED` → `SECOND_PRESENTED`, the transaction
        `RE_PRESENTED` → `CHARGED_BACK`, and the case `REPRESENTMENT_REVIEW` →
        `CHARGEBACK_FILED`."

        Design: Difficulty/non_linear_state_machine/dispute_case_representment_review_cycle
        """
        account, _txn, case, chargeback = setup_filed_chargeback(
            balance=50000, amount=12000, claim=12000, claimed_delay=10,
        )
        register_representment(chargeback["id"], merchant_ref="MR-C")
        cb = review_representment(chargeback["id"], decision="REJECT")
        assert cb["status"] == "SECOND_PRESENTED"
        case_end = get_case(case["id"])
        assert case_end["status"] == "CHARGEBACK_FILED", (
            f"case must loop back to CHARGEBACK_FILED, got {case_end['status']}"
        )
        txns = get_success_data(api.list_account_transactions(
            account["id"], TEST_USERS["chargeback_analyst_headers"],
        ))
        assert txns[0]["status"] == "CHARGED_BACK"


class TestRepresentmentEvidenceBoundary:
    def test_representment_empty_evidence_rejected(self, api):
        """PRD §3.6: "The list must contain at least one entry, each a `doc_type`
        paired with a `reference`; an empty array is rejected with
        `ERR_EVIDENCE_REQUIRED`."

        Design: Difficulty/boundary_precision_check/representment_empty_evidence_rejected
        """
        _account, _txn, _case, chargeback = setup_filed_chargeback(
            balance=50000, amount=12000, claim=12000, claimed_delay=10,
        )
        resp = api.create_representment(
            chargeback["id"],
            {"merchant_ref": "MR-EMPTY", "evidence_documents": []},
            TEST_USERS["chargeback_analyst_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_EVIDENCE_REQUIRED)

    def test_representment_single_document_accepted(self, api):
        """PRD §3.6: "The list must contain at least one entry, each a `doc_type`
        paired with a `reference`".
        PRD §3.6: "Registration creates the Representment in `PENDING_REVIEW`".

        Design: Difficulty/boundary_precision_check/representment_empty_evidence_rejected
        """
        _account, _txn, _case, chargeback = setup_filed_chargeback(
            balance=50000, amount=12000, claim=12000, claimed_delay=10,
        )
        rep = register_representment(chargeback["id"], merchant_ref="MR-ONE",
                                     doc_ref="b-1")
        assert rep["status"] == "PENDING_REVIEW", (
            f"one evidence document crosses the boundary, got {rep['status']}"
        )

    def test_representment_after_second_presented_rejected(self, api):
        """PRD §3.6: "The merchant answers a `FILED` chargeback through a
        representment" — after second presentment the chargeback is no longer
        `FILED`, so the state precondition fails.
        PRD §2.8: "sixth, entity state preconditions for the requested transition
        (`ERR_INVALID_STATE`, with the more specific
        `ERR_DUPLICATE_ACTIVE_DISPUTE` and `ERR_ACCOUNT_RESTRICTED` where
        applicable)".

        Design: Corner/state_machines/representment_after_second_presented_rejected
        """
        _account, _txn, _case, chargeback = setup_second_presented(
            balance=50000, amount=12000, claim=12000, claimed_delay=10,
        )
        resp = api.create_representment(
            chargeback["id"],
            create_representment_payload(
                merchant_ref="MR-4B",
                evidence_documents=[{"doc_type": "RECEIPT", "reference": "4-2"}],
            ),
            TEST_USERS["chargeback_analyst_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestEscalationFees:
    def _two_second_presented(self, api):
        """Two identical-amount SECOND_PRESENTED chargebacks (20000 each)."""
        a = setup_second_presented(
            balance=100000, amount=20000, claim=20000, claimed_delay=10,
        )
        b = setup_second_presented(
            balance=100000, amount=20000, claim=20000, claimed_delay=10,
        )
        return a[3], b[3]  # the two chargebacks

    def test_pre_compliance_fee_projection(self, api):
        """PRD §3.6: "the pre-compliance stage fee is 10,000 cents plus 0.8
        percent of the chargeback `amount_cents`, rounded half-up to whole
        cents".
        PRD §3.5: "a filing fee of 2,500 cents already accrued in
        `fees_total_cents`."

        Design: Difficulty/dual_variant_calc/pre_compliance_vs_arbitration_fee_projection
        """
        cb_a, _cb_b = self._two_second_presented(api)
        resp = api.escalate_chargeback(
            cb_a["id"], escalate_payload("PRE_COMPLIANCE", "WON"),
            TEST_USERS["chargeback_analyst_headers"],
        )
        data = validate_success(resp)
        # 2500 filing + 10000 base + round_half_up(0.008 * 20000) = 160
        assert data["fees_total_cents"] == 12660, (
            f"pre-compliance total must be 12660, got {data['fees_total_cents']}"
        )

    def test_arbitration_fee_projection(self, api):
        """PRD §3.6: "the arbitration stage fee is 25,000 cents plus 1.5 percent
        of the `amount_cents`, likewise rounded half-up on its own."
        PRD §3.6: "arbitration is the more expensive path, so an identical
        `amount_cents` always yields a strictly larger total at arbitration than
        at pre-compliance."

        Design: Difficulty/dual_variant_calc/pre_compliance_vs_arbitration_fee_projection
        """
        _cb_a, cb_b = self._two_second_presented(api)
        resp = api.escalate_chargeback(
            cb_b["id"], escalate_payload("ARBITRATION", "WON"),
            TEST_USERS["chargeback_analyst_headers"],
        )
        data = validate_success(resp)
        # 2500 filing + 25000 base + round_half_up(0.015 * 20000) = 300
        assert data["fees_total_cents"] == 27800, (
            f"arbitration total must be 27800, got {data['fees_total_cents']}"
        )

    def test_per_stage_fee_rounding_then_sum(self, api):
        """PRD §2.6: "each stage fee is individually rounded half-up to whole
        cents first, and only then summed with the filing fee into the
        chargeback's total. The fractional components of different stages are
        never summed before rounding."
        PRD §3.6: "the pre-compliance stage fee is 10,000 cents plus 0.8 percent
        of the chargeback `amount_cents`, rounded half-up to whole cents".

        Design: Difficulty/combinatorial_formula/per_stage_fee_rounding_then_sum
        """
        _account, _txn, _case, chargeback = setup_second_presented(
            balance=50000, amount=33333, claim=33333, claimed_delay=10,
        )
        # Rebuild with explicit chargeback amount 33333 (fixture defaults the
        # chargeback amount to the claim, which is already 33333).
        resp = api.escalate_chargeback(
            chargeback["id"], escalate_payload("PRE_COMPLIANCE", "LOST"),
            TEST_USERS["chargeback_analyst_headers"],
        )
        data = validate_success(resp)
        # round_half_up(0.008 * 33333) = round_half_up(266.664) = 267
        assert data["fees_total_cents"] == 12767, (
            f"2500 + 10000 + 267 must be 12767, got {data['fees_total_cents']}"
        )
        assert data["stage_entered"] == "PRE_COMPLIANCE"

    def test_per_stage_rounding_odd_amount_arbitration(self, api):
        """PRD §2.6: "each stage fee is individually rounded half-up to whole
        cents first, and only then summed with the filing fee into the
        chargeback's total."
        PRD §3.6: "the arbitration stage fee is 25,000 cents plus 1.5 percent of
        the `amount_cents`, likewise rounded half-up on its own."

        Design: Difficulty/combinatorial_formula/per_stage_fee_rounding_then_sum
        """
        _account, _txn, _case, chargeback = setup_second_presented(
            balance=50000, amount=33333, claim=33333, claimed_delay=10,
        )
        resp = api.escalate_chargeback(
            chargeback["id"], escalate_payload("ARBITRATION", "LOST"),
            TEST_USERS["chargeback_analyst_headers"],
        )
        data = validate_success(resp)
        # round_half_up(0.015 * 33333) = round_half_up(499.995) = 500
        assert data["fees_total_cents"] == 28000, (
            f"2500 + 25000 + 500 must be 28000, got {data['fees_total_cents']}"
        )


class TestArbitrationWonCascade:
    def test_arbitration_won_creates_recovery_and_finalizes_credit(self, api):
        """PRD §3.6: "the final credit F (claim minus final liability) finalizes
        any open credit with `final_amount_cents` set to F and a balance
        true-up, a `LOSS_RECOGNIZED` entry of F plus `fees_total_cents` is
        auto-created when that sum is positive, a `RECOVERY_RECEIVED` entry of
        the chargeback's `amount_cents` books the network recovery, and the case
        resolves `RESOLVED_CARDHOLDER_FAVOR`".
        PRD §3.8: "its `outstanding_loss_cents` is the running balance: the sum
        of all `LOSS_RECOGNIZED` entry amounts minus the sum of all
        `RECOVERY_RECEIVED` entry amounts."

        Design: Corner/cross_cutting_layers/arbitration_won_creates_recovery_and_finalizes_credit
        """
        account, txn, case, chargeback = setup_second_presented(
            balance=100000, amount=20000, claim=20000, claimed_delay=10,
            grant_credit_first=True,
        )
        resp = api.escalate_chargeback(
            chargeback["id"], escalate_payload("ARBITRATION", "WON"),
            TEST_USERS["chargeback_analyst_headers"],
        )
        cb = validate_success(resp)
        assert cb["status"] == "CLOSED_WON"
        assert cb["fees_total_cents"] == 27800

        resolved = get_case(case["id"])
        assert resolved["status"] == "RESOLVED_CARDHOLDER_FAVOR"
        assert resolved["cardholder_keeps_cents"] == 20000
        assert resolved["outstanding_loss_cents"] == 27800, (
            "LOSS_RECOGNIZED 47800 (F 20000 + fees 27800) minus "
            f"RECOVERY_RECEIVED 20000 must leave 27800, got "
            f"{resolved['outstanding_loss_cents']}"
        )
        credits = get_success_data(api.list_case_provisional_credits(
            case["id"], TEST_USERS["finance_officer_headers"],
        ))
        assert credits[0]["status"] == "FINALIZED"
        assert credits[0]["final_amount_cents"] == 20000
