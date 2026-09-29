"""The two report dimensions, the revision loop, and settle/reverse symmetry."""

from test_helpers import (
    BREEDER,
    OFFICER,
    OFFICER_THREE,
    OFFICER_THREE_USER_ID,
    OFFICER_TWO,
    ApiErrorId,
    add_line_item,
    assert_propagator_ledger_invariant,
    draft_report,
    licensed_quota,
    royalty_chain_with_accepted_report,
    validate_error,
    validate_success,
)


class TestReviewAndSettlementDimensions:
    """review_status cycles; settlement_status advances independently."""

    def _accepted_report(self, api):
        return royalty_chain_with_accepted_report(
            api,
            quality_tier="TIER_A",
            allocated_units=20000,
            requested_units=12000,
            reported_units=12000,
            variety_overrides={
                "denomination": "Harbor Amber",
                "species": "Malus domestica",
                "breeder_code": "HA",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"],
            propagator_name="Harborview Nursery",
        )

    def test_disputing_zeroes_the_booked_amount_without_touching_settlement(self, api):
        """The dispute moves only the review dimension; the settlement dimension
        stays UNSETTLED while the booked amount and the propagator's payable
        balance both drop to zero.

        PRD 3.7: "Disputing sets `booked_amount_cents` to 0 and, at cascade level one caused by that un-booking, re-derives the propagator's `royalty_payable_cents`; the report's `version` and the propagator's `version` each increment by 1."

        Design: Difficulty/non_linear_state_machine/royalty_report_review_and_settlement_dimensions_advance_independently
        """
        chain = self._accepted_report(api)
        before = validate_success(api.get_royalty_report(chain["report_id"], BREEDER))
        assert before["review_status"] == "ACCEPTED"
        assert before["settlement_status"] == "UNSETTLED"
        assert before["booked_amount_cents"] == 458850
        assert before["revision_no"] == 0

        disputed = validate_success(
            api.dispute_royalty_report(
                chain["report_id"], OFFICER_TWO,
                {"dispute_note": "unit reconciliation query"},
            )
        )

        assert disputed["review_status"] == "DISPUTED"
        assert disputed["settlement_status"] == "UNSETTLED"
        assert disputed["booked_amount_cents"] == 0
        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["royalty_payable_cents"] == 0

    def test_revising_clears_the_final_figures_and_keeps_the_provisional_ones(self, api):
        """Revision returns the report to DRAFT, counts the lap, nulls the two
        stamps and the final money fields, and leaves the provisional total and
        the existing lines in place.

        PRD 3.7: "Revision increments `revision_no` by 1, and the fields it clears are exactly specified: `submitted_at`, `accepted_at` and `accepted_by_user_id` return to null, `is_late` returns to false, and `final_total_cents`, `late_fee_cents` and `booked_amount_cents` return to 0."

        Design: Difficulty/non_linear_state_machine/royalty_report_review_and_settlement_dimensions_advance_independently
        """
        chain = self._accepted_report(api)
        validate_success(
            api.dispute_royalty_report(
                chain["report_id"], OFFICER_TWO,
                {"dispute_note": "unit reconciliation query"},
            )
        )

        revised = validate_success(
            api.revise_royalty_report(chain["report_id"], chain["propagator_headers"])
        )

        assert revised["review_status"] == "DRAFT"
        assert revised["revision_no"] == 1
        assert revised["submitted_at"] is None
        assert revised["accepted_at"] is None
        assert revised["final_total_cents"] == 0
        assert revised["settlement_status"] == "UNSETTLED"
        assert revised["provisional_total_cents"] == 458850

    def test_the_review_loop_can_be_run_again_and_then_settled(self, api):
        """A second submit-and-accept lap restores the booked amount at
        revision_no 1, and settling afterwards moves the money without moving
        the review dimension.

        PRD 3.7: "Settling records the acting `X-User-ID` in `settled_by_user_id`, re-derives both `royalty_payable_cents` and `royalty_settled_cents` on the propagator at cascade level one, and increments the report's `version` and the propagator's `version` by 1. It does not touch `review_status`."

        Design: Difficulty/non_linear_state_machine/royalty_report_review_and_settlement_dimensions_advance_independently
        """
        chain = self._accepted_report(api)
        validate_success(
            api.dispute_royalty_report(
                chain["report_id"], OFFICER_TWO,
                {"dispute_note": "unit reconciliation query"},
            )
        )
        validate_success(
            api.revise_royalty_report(chain["report_id"], chain["propagator_headers"])
        )

        resubmitted = validate_success(
            api.submit_royalty_report(chain["report_id"], chain["propagator_headers"])
        )
        assert resubmitted["review_status"] == "SUBMITTED"
        assert resubmitted["provisional_total_cents"] == 458850

        reaccepted = validate_success(
            api.accept_royalty_report(chain["report_id"], OFFICER_TWO)
        )
        assert reaccepted["review_status"] == "ACCEPTED"
        assert reaccepted["final_total_cents"] == 458850
        assert reaccepted["booked_amount_cents"] == 458850
        assert reaccepted["revision_no"] == 1

        settled = validate_success(
            api.settle_royalty_report(chain["report_id"], OFFICER_THREE)
        )
        assert settled["settlement_status"] == "SETTLED"
        assert settled["review_status"] == "ACCEPTED"

        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["royalty_payable_cents"] == 0
        assert propagator["royalty_settled_cents"] == 458850
        assert propagator["compliance_score"] == 100


class TestSettlementReversalRestoresThePayable:
    """Reversing a settlement is exact, not approximate."""

    def _settled_report(self, api):
        chain = royalty_chain_with_accepted_report(
            api,
            quality_tier="TIER_A",
            allocated_units=20000,
            requested_units=12000,
            reported_units=12000,
            variety_overrides={
                "denomination": "Wheatland Gala",
                "species": "Malus domestica",
                "breeder_code": "WG",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"],
            propagator_name="Wheatland Propagation",
        )
        return chain

    def test_settling_moves_the_booked_amount_across_the_ledger(self, api):
        """Before settlement the whole 458850 sits on the payable side; settling
        records the acting officer and moves the identical figure to the settled
        side, with the conservation identity holding at both instants.

        PRD 3.7: "Among those accepted reports, `royalty_payable_cents` is the sum of `booked_amount_cents` over the ones whose `settlement_status` is `UNSETTLED` or `REVERSED`, and `royalty_settled_cents` is the sum of `booked_amount_cents` over the ones whose `settlement_status` is `SETTLED`."

        Design: Difficulty/compensating_invariant/reversing_a_settlement_restores_propagator_royalty_payable_exactly
        """
        chain = self._settled_report(api)
        before = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert before["royalty_payable_cents"] == 458850
        assert before["royalty_settled_cents"] == 0
        assert_propagator_ledger_invariant(before, 458850)

        settled = validate_success(
            api.settle_royalty_report(chain["report_id"], OFFICER_THREE)
        )
        assert settled["settlement_status"] == "SETTLED"
        assert settled["settled_by_user_id"] == OFFICER_THREE_USER_ID

        after = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert after["royalty_payable_cents"] == 0
        assert after["royalty_settled_cents"] == 458850
        assert_propagator_ledger_invariant(after, 458850)

    def test_reversing_returns_the_payable_to_its_exact_pre_settlement_value(self, api):
        """The reversed report re-enters the payable set rather than dropping out
        of the ledger, so the payable balance returns to 458850 exactly and the
        review dimension is untouched.

        PRD 3.7: "Reversal clears `settled_by_user_id` back to null, re-derives `royalty_payable_cents` and `royalty_settled_cents` — the reversed report re-enters the payable set rather than dropping out of the ledger — and increments both versions by 1."

        Design: Difficulty/compensating_invariant/reversing_a_settlement_restores_propagator_royalty_payable_exactly
        """
        chain = self._settled_report(api)
        validate_success(api.settle_royalty_report(chain["report_id"], OFFICER_THREE))

        reversed_report = validate_success(
            api.reverse_royalty_report(
                chain["report_id"], OFFICER_THREE, {"reversal_note": "bank return"}
            )
        )

        assert reversed_report["settlement_status"] == "REVERSED"
        assert reversed_report["settled_by_user_id"] is None
        assert reversed_report["review_status"] == "ACCEPTED"
        assert reversed_report["booked_amount_cents"] == 458850

        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["royalty_payable_cents"] == 458850
        assert propagator["royalty_settled_cents"] == 0
        assert_propagator_ledger_invariant(propagator, 458850)

    def test_the_accepting_officer_may_not_settle_and_reversal_is_terminal(self, api):
        """The officer recorded as accepting is barred from settling, and once the
        settlement dimension has reached REVERSED nothing further may drive it.

        PRD 3.7: "`REVERSED` is terminal on the settlement dimension."

        Design: Difficulty/compensating_invariant/reversing_a_settlement_restores_propagator_royalty_payable_exactly
        """
        chain = self._settled_report(api)

        validate_error(
            api.settle_royalty_report(chain["report_id"], OFFICER_TWO),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )

        validate_success(api.settle_royalty_report(chain["report_id"], OFFICER_THREE))
        validate_success(
            api.reverse_royalty_report(
                chain["report_id"], OFFICER_THREE, {"reversal_note": "bank return"}
            )
        )

        validate_error(
            api.reverse_royalty_report(chain["report_id"], OFFICER_THREE),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            409,
        )


class TestSubmissionNeedsAnActiveAgreement:
    """A suspended head licence blocks submission of a drafted report."""

    def _drafted_then_suspended(self, api):
        chain = licensed_quota(
            api,
            quality_tier="TIER_B",
            territory_class="DOMESTIC",
            allocated_units=20000,
            variety_overrides={
                "denomination": "Lantern Quince",
                "species": "Cydonia oblonga",
                "breeder_code": "LQ",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"],
            propagator_name="Lantern Hill Nursery",
        )
        chain["report"] = draft_report(api, chain)
        chain["report_id"] = chain["report"]["id"]
        chain["line_item"] = add_line_item(api, chain, chain["report_id"], 500)
        chain["report"] = validate_success(
            api.get_royalty_report(chain["report_id"], BREEDER)
        )
        validate_success(api.suspend_agreement(chain["agreement_id"], OFFICER))
        return chain

    def test_submission_is_refused_while_the_agreement_is_suspended(self, api):
        """Suspension withdraws the licence to operate, so the drafted report
        cannot be filed and neither its state nor its version moves.

        PRD 3.5: "In all seven the rejection is `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409), and it applies equally to an agreement still `PENDING_COUNTERSIGN` and to one that is `SUSPENDED` — neither authorizes any downstream production or billing activity."

        Design: Difficulty/cross_entity_state_dependency/report_submission_requires_governing_agreement_active
        """
        chain = self._drafted_then_suspended(api)
        agreement = validate_success(
            api.get_propagator_agreement(chain["agreement_id"], OFFICER)
        )
        assert agreement["status"] == "SUSPENDED"
        assert agreement["suspension_reason"] == "MANUAL"
        quota = validate_success(api.get_production_quota(chain["quota_id"], OFFICER))
        assert quota["status"] == "FROZEN"

        validate_error(
            api.submit_royalty_report(chain["report_id"], chain["propagator_headers"]),
            ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value,
            409,
        )

        unchanged = validate_success(api.get_royalty_report(chain["report_id"], BREEDER))
        assert unchanged["review_status"] == "DRAFT"
        assert unchanged["version"] == chain["report"]["version"]

    def test_reinstatement_thaws_the_quota_and_unblocks_submission(self, api):
        """Reinstatement clears the reason, counts the lap, moves the frozen quota
        back to ACTIVE, and the very same submission then succeeds and prices
        500 units at the 35-cent base.

        PRD 3.5: "A successful reinstatement clears `suspension_reason` back to null, increments `reinstatement_count` by 1 — the count of completed `ACTIVE → SUSPENDED → ACTIVE` laps — and cascades in the mirror image of suspension: every `FROZEN` quota of that agreement moves back to `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/report_submission_requires_governing_agreement_active
        """
        chain = self._drafted_then_suspended(api)

        reinstated = validate_success(
            api.reinstate_agreement(chain["agreement_id"], OFFICER)
        )
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["suspension_reason"] is None
        assert reinstated["reinstatement_count"] == 1
        quota = validate_success(api.get_production_quota(chain["quota_id"], OFFICER))
        assert quota["status"] == "ACTIVE"

        submitted = validate_success(
            api.submit_royalty_report(chain["report_id"], chain["propagator_headers"])
        )
        assert submitted["review_status"] == "SUBMITTED"
        assert submitted["is_late"] is False
        assert submitted["provisional_total_cents"] == 17500
