"""Compensating actions restore every ledger term, and refuse to run twice."""

from test_helpers import (
    ApiErrorId,
    assert_expenditure_ledger_conservation,
    assert_released_authority_conservation,
    assert_transfer_authority_conservation,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

TRANSFER_JUSTIFICATION = "Shift authority to P200 for caseload growth"
REVERSAL_REASON = "transfer authority withdrawn by the legislature"


class TestRecallRestoresReleasedCashConservation:
    @staticmethod
    def _released_context():
        ctx = fixtures.setup_appropriation_with_released_cash(
            requested_cents=400_000_000, appropriation_cents=2_000_000_000, quarter=1
        )
        assert ctx["allotment"]["status"] == "RELEASED"
        assert ctx["allotment"]["prepared_by_user_id"] == "analyst-1"
        assert ctx["allotment"]["approved_by_user_id"] == "dir-1"
        return ctx

    def test_recall_returns_all_three_ledger_terms_to_zero(self, api):
        """PRD §2.11: "A cycle's `total_released_cents` equals the sum of `released_cents` over its appropriations, which equals the sum of `released_cents` over all allotments in status `RELEASED` whose appropriation belongs to that cycle."
        PRD §2.11: "A release followed by the recall of that same allotment returns every one of those three figures to its pre-release value."
        PRD §3.5: "On success the allotment's `released_cents` returns to 0 and the same cascade runs in reverse: the appropriation recomputes `released_cents`, `available_cash_cents`, and its cash dimension; the cycle recomputes `total_released_cents`, `cash_utilization_pct`, and `cash_posture`; and a posture returning to `NORMAL` clears `release_hold` on every `GENERAL` `UNRELEASED` appropriation of the cycle."
        PRD §3.5: "On the appropriation, a recall that brings `released_cents` back to exactly zero moves the cash dimension `PARTIALLY_RELEASED → UNRELEASED`, while a recall that leaves `released_cents` still above zero moves it `FULLY_RELEASED → PARTIALLY_RELEASED`; the cash dimension is genuinely cyclic, and a release followed by its recall returns the row to `UNRELEASED`."
        PRD §3.7: "The **cash basis**, `available_cash_cents`, is `released_cents` minus `expended_cents`."

        Design: Difficulty/compensating_invariant/recall_restores_released_cash_conservation_across_all_three_ledger_terms
        """
        ctx = self._released_context()
        appropriation_id = ctx["appropriation"]["id"]

        assert ctx["appropriation"]["released_cents"] == 400_000_000
        assert ctx["appropriation"]["cash_status"] == "PARTIALLY_RELEASED"
        assert ctx["cycle"]["total_released_cents"] == 400_000_000
        assert_released_authority_conservation(
            ctx["cycle"], [ctx["appropriation"]], [ctx["allotment"]]
        )

        recalled = fixtures.recall_allotment(
            ctx["allotment"]["id"], "cash forecast deteriorated"
        )
        assert recalled["status"] == "RECALLED"
        assert recalled["released_cents"] == 0
        assert recalled["recall_reason"] == "cash forecast deteriorated"

        appropriation = fixtures.read_appropriation(appropriation_id)
        cycle = fixtures.read_budget_cycle(ctx["cycle"]["id"])
        assert appropriation["released_cents"] == 0
        assert appropriation["cash_status"] == "UNRELEASED"
        assert cycle["total_released_cents"] == 0
        assert cycle["cash_posture"] == "NORMAL"
        assert_released_authority_conservation(cycle, [appropriation], [recalled])

        summary = fixtures.read_balance_summary(appropriation_id)
        assert summary["available_cash_cents"] == 0
        assert summary["available_authority_cents"] == 2_000_000_000

    def test_a_second_recall_is_refused_and_changes_nothing(self, api, state_controller_headers):
        """PRD §3.5: "`RECALLED` is terminal for the allotment."
        PRD §3.5: "It moves the allotment `RELEASED → RECALLED`, requires the row to be in `RELEASED`, takes a `reason` stored in `recall_reason`, and requires that the recall not push the appropriation's released cash below what it has already spent — formally, that the appropriation's `available_cash_cents` minus the allotment's `released_cents` be at least zero — otherwise `ERR_INSUFFICIENT_CASH_RELEASED`."
        PRD §2.12: "The target row is in a state from which the requested transition is declared — otherwise `ERR_INVALID_STATE` (409). Applies to every action endpoint."

        Design: Difficulty/compensating_invariant/recall_restores_released_cash_conservation_across_all_three_ledger_terms
        """
        ctx = self._released_context()
        allotment_id = ctx["allotment"]["id"]
        fixtures.recall_allotment(allotment_id, "cash forecast deteriorated")

        response = api.recall_allotment(
            allotment_id, {"reason": "cash forecast deteriorated"}, state_controller_headers
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

        allotment = fixtures.read_allotment(allotment_id)
        appropriation = fixtures.read_appropriation(ctx["appropriation"]["id"])
        cycle = fixtures.read_budget_cycle(ctx["cycle"]["id"])
        assert allotment["status"] == "RECALLED"
        assert allotment["released_cents"] == 0
        assert appropriation["released_cents"] == 0
        assert cycle["total_released_cents"] == 0


class TestReverseRestoresTransferAuthorityConservation:
    @staticmethod
    def _executed_context():
        ctx = fixtures.setup_transfer_pair(
            source_cents=1_000_000_000, target_cents=1_000_000_000
        )
        transfer = fixtures.propose_transfer(
            ctx["source"]["id"],
            ctx["target"]["id"],
            amount_cents=100_000_000,
            transfer_type="INTRA_AGENCY",
            justification=TRANSFER_JUSTIFICATION,
        )
        assert transfer["status"] == "PROPOSED"
        assert transfer["proposed_by_user_id"] == "analyst-1"
        approved = fixtures.approve_transfer(transfer["id"])
        assert approved["approved_by_user_id"] == "dir-1"
        ctx["transfer"] = fixtures.execute_transfer(transfer["id"])
        return ctx

    def test_reversal_returns_both_lines_to_their_pre_transfer_figures(self, api):
        """PRD §3.6: "The reversed row stops counting, so both `transfers_out_cents` and `transfers_in_cents` are recomputed; because the source's available authority has recovered, every `AT_RISK` pledge on the source whose overlapping committed total once again fits returns to `COMMITTED`, each affected grant recomputes `committed_match_cents` and `match_status`, and each owning agency recomputes `federal_compliance_flag`."
        PRD §3.6: "It moves the transfer `EXECUTED → REVERSED`, requires the row to be in `EXECUTED`, requires the *target* appropriation's `available_authority_cents` to be at least `amount_cents` (otherwise `ERR_TRANSFER_EXCEEDS_AVAILABLE`, since the target must still hold the authority being taken back), requires the owning cycle to be in `EXECUTION`, and takes a `reason` stored in `decision_reason`."
        PRD §2.11: "Summed across the appropriations of a cycle, `enacted_amount_cents` plus `transfers_in_cents` minus `transfers_out_cents` equals the plain sum of `enacted_amount_cents`: a transfer moves authority between rows and never creates or destroys it."

        Design: Difficulty/compensating_invariant/reverse_restores_cycle_authority_conservation_after_an_executed_transfer
        """
        ctx = self._executed_context()
        assert ctx["transfer"]["status"] == "EXECUTED"

        source_after_execute = fixtures.read_appropriation(ctx["source"]["id"])
        target_after_execute = fixtures.read_appropriation(ctx["target"]["id"])
        assert source_after_execute["transfers_out_cents"] == 100_000_000
        assert target_after_execute["transfers_in_cents"] == 100_000_000
        assert source_after_execute["available_authority_cents"] == 900_000_000
        assert target_after_execute["available_authority_cents"] == 1_100_000_000
        assert_transfer_authority_conservation([source_after_execute, target_after_execute])

        reversed_row = fixtures.reverse_transfer(ctx["transfer"]["id"], REVERSAL_REASON)
        assert reversed_row["status"] == "REVERSED"
        assert reversed_row["decision_reason"] == REVERSAL_REASON

        source = fixtures.read_appropriation(ctx["source"]["id"])
        target = fixtures.read_appropriation(ctx["target"]["id"])
        assert source["transfers_out_cents"] == 0
        assert target["transfers_in_cents"] == 0
        assert source["available_authority_cents"] == 1_000_000_000
        assert target["available_authority_cents"] == 1_000_000_000
        assert source["enacted_amount_cents"] == 1_000_000_000
        assert target["enacted_amount_cents"] == 1_000_000_000
        assert_transfer_authority_conservation([source, target])

    def test_a_second_reversal_is_refused_and_the_ledger_stays_restored(
        self, api, state_controller_headers
    ):
        """PRD §3.6: "`REVERSED` is terminal."
        PRD §2.12: "The target row is in a state from which the requested transition is declared — otherwise `ERR_INVALID_STATE` (409). Applies to every action endpoint."
        PRD §2.11: "Summed across the appropriations of a cycle, `enacted_amount_cents` plus `transfers_in_cents` minus `transfers_out_cents` equals the plain sum of `enacted_amount_cents`: a transfer moves authority between rows and never creates or destroys it."
        PRD §2.11: "This must hold after every transfer execution and every transfer reversal."

        Design: Difficulty/compensating_invariant/reverse_restores_cycle_authority_conservation_after_an_executed_transfer
        """
        ctx = self._executed_context()
        fixtures.reverse_transfer(ctx["transfer"]["id"], REVERSAL_REASON)

        response = api.reverse_budget_transfer(
            ctx["transfer"]["id"], {"reason": REVERSAL_REASON}, state_controller_headers
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

        rows, _meta = validate_paginated(
            api.list_appropriation_budget_transfers(ctx["source"]["id"], fixtures.ANALYST)
        )
        stored = [row for row in rows if row["id"] == ctx["transfer"]["id"]][0]
        assert stored["status"] == "REVERSED"

        source = fixtures.read_appropriation(ctx["source"]["id"])
        target = fixtures.read_appropriation(ctx["target"]["id"])
        assert source["transfers_out_cents"] == 0
        assert target["transfers_in_cents"] == 0
        assert_transfer_authority_conservation([source, target])


class TestVoidRestoresExpenditureLedger:
    @staticmethod
    def _posted_context():
        ctx = fixtures.setup_appropriation_with_released_cash(
            requested_cents=400_000_000, appropriation_cents=2_000_000_000, quarter=1
        )
        grant = fixtures.record_federal_grant(
            ctx["agency"]["id"],
            ctx["cycle"]["id"],
            moe_baseline_cents=200_000_000,
            moe_prior_year1_spend_cents=200_000_000,
            moe_prior_year2_spend_cents=200_000_000,
        )
        expenditure = fixtures.post_expenditure(
            ctx["appropriation"]["id"],
            ctx["agency"]["id"],
            quarter=1,
            amount_cents=250_000_000,
            object_code="5100",
            vendor_reference="INV-77001",
        )
        assert expenditure["status"] == "POSTED"
        ctx["grant"] = grant
        ctx["expenditure"] = expenditure
        return ctx

    def test_voiding_restores_both_bases_and_flips_the_moe_verdict_back(self, api):
        """PRD §2.11: "An appropriation's `expended_cents` equals the sum of `amount_cents` over its expenditures in status `POSTED`. Posting a charge and then voiding it returns `expended_cents`, `available_cash_cents`, and `available_authority_cents` to their pre-posting values."
        PRD §3.7: "The owning appropriation then recomputes `expended_cents`, `available_cash_cents`, and `available_authority_cents`, and every federal grant of the same agency and cycle refreshes `moe_current_spend_cents`."
        PRD §3.8: "The assessment first refreshes `moe_current_spend_cents`: the sum of `amount_cents` over every expenditure in status `POSTED` charged to an appropriation whose `fund_type` is `GENERAL` and whose `agency_id` and `budget_cycle_id` match the grant's; `FEDERAL` and `DEDICATED` charges and `VOIDED` rows are excluded."
        PRD §3.8: "The verdict compares integers, never the reported ratio: `moe_compliance_status` is `COMPLIANT` when the assessed spend is greater than or equal to `moe_baseline_cents` — exact equality is compliant — and `DEFICIENT` otherwise."
        PRD §3.8: "The assessment also writes `moe_compliance_ratio`, the assessed spend divided by `moe_baseline_cents` rounded half up to 6 decimal places, and records the basis used in `moe_assessed_basis`."

        Design: Difficulty/compensating_invariant/void_restores_expenditure_ledger_and_flips_the_moe_verdict_back
        """
        ctx = self._posted_context()
        appropriation_id = ctx["appropriation"]["id"]

        posted_summary = fixtures.read_balance_summary(appropriation_id)
        assert posted_summary["expended_cents"] == 250_000_000
        assert posted_summary["available_cash_cents"] == 150_000_000
        assert posted_summary["available_authority_cents"] == 1_750_000_000

        compliant = fixtures.assess_moe(ctx["grant"]["id"], "SINGLE_YEAR")
        assert compliant["moe_current_spend_cents"] == 250_000_000
        assert compliant["moe_compliance_status"] == "COMPLIANT"
        assert compliant["moe_compliance_ratio"] == 1.25
        assert compliant["moe_assessed_basis"] == "SINGLE_YEAR"

        voided = fixtures.void_expenditure(
            ctx["expenditure"]["id"], "charge posted to the wrong appropriation"
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "charge posted to the wrong appropriation"

        appropriation = fixtures.read_appropriation(appropriation_id)
        assert appropriation["expended_cents"] == 0
        assert_expenditure_ledger_conservation(appropriation, [voided])
        restored_summary = fixtures.read_balance_summary(appropriation_id)
        assert restored_summary["available_cash_cents"] == 400_000_000
        assert restored_summary["available_authority_cents"] == 2_000_000_000

        deficient = fixtures.assess_moe(ctx["grant"]["id"], "SINGLE_YEAR")
        assert deficient["moe_current_spend_cents"] == 0
        assert deficient["moe_compliance_status"] == "DEFICIENT"
        assert deficient["moe_compliance_ratio"] == 0.0

    def test_a_second_void_is_refused_and_released_cash_never_moved(
        self, api, state_controller_headers
    ):
        """PRD §3.7: "`VOIDED` is terminal, and a voided charge counts toward nothing."
        PRD §3.7: "It moves the charge `POSTED → VOIDED`, requires the row to be in `POSTED` and the owning cycle to be in `EXECUTION`, and takes a `reason` stored in `void_reason`."
        PRD §2.12: "The target row is in a state from which the requested transition is declared — otherwise `ERR_INVALID_STATE` (409). Applies to every action endpoint."

        Design: Difficulty/compensating_invariant/void_restores_expenditure_ledger_and_flips_the_moe_verdict_back
        """
        ctx = self._posted_context()
        fixtures.void_expenditure(
            ctx["expenditure"]["id"], "charge posted to the wrong appropriation"
        )

        response = api.void_expenditure(
            ctx["expenditure"]["id"],
            {"reason": "charge posted to the wrong appropriation"},
            state_controller_headers,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

        rows, _meta = validate_paginated(
            api.list_appropriation_expenditures(ctx["appropriation"]["id"], fixtures.ANALYST)
        )
        assert [row["status"] for row in rows] == ["VOIDED"]

        appropriation = fixtures.read_appropriation(ctx["appropriation"]["id"])
        assert appropriation["expended_cents"] == 0
        assert appropriation["released_cents"] == 400_000_000
        cycle = fixtures.read_budget_cycle(ctx["cycle"]["id"])
        assert cycle["total_released_cents"] == 400_000_000
        assert validate_success(
            api.get_appropriation_balance_summary(
                ctx["appropriation"]["id"], fixtures.ANALYST
            )
        )["available_cash_cents"] == 400_000_000
