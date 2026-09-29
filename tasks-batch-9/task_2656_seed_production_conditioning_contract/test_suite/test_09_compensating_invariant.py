"""Three conserved ledgers, each walked forward and then compensated back."""

from __future__ import annotations

import pytest

from test_helpers import (
    GOLDEN_FIGURES,
    TEST_DEFAULTS,
    approved_settlement_state,
    assert_advance_conserved,
    assert_lot_mass_conserved,
    assert_tagged_bag_count_matches_issued_tags,
    bagged_lot_state,
    dispute_settlement_payload,
    get_success_data,
    make_certification_agency_headers,
    make_conditioning_manager_headers,
    make_grower_headers,
    make_program_admin_headers,
    make_settlement_accountant_headers,
    reverse_conditioning_run_payload,
    tagged_lot_state,
    validate_error,
    validate_paginated,
    validate_success,
    void_certification_tag_payload,
)

BAGGED_CUMULATIVE_SHRINK_KG = 6498.75
SIZED_CUMULATIVE_SHRINK_KG = 5000.0
SIZED_CURRENT_KG = 36000.0
BAGGING_SHRINK_KG = 1498.75
BAGGED_DOCKAGE_PCT = 15.85
SIZED_DOCKAGE_PCT = 12.20


class TestBaggingReversalPreservesLotMass:
    def test_reversing_the_bagging_run_restores_the_mass_identity_exactly(self, api):
        """The reversal subtracts exactly the shrink the run added, with zero drift.

        PRD: "Completing a conditioning run moves mass from held to shrink; reversing a completed
        run moves exactly the same quantity back, restoring the identity with zero drift."

        Design: Difficulty/compensating_invariant/bagging_reversal_preserves_lot_mass
        """
        state = bagged_lot_state(api)
        lot_id = state["seed_lot"]["id"]

        before = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert_lot_mass_conserved(before)
        assert before["gross_kg"] == pytest.approx(TEST_DEFAULTS["GROSS_WEIGHT_KG"], abs=0.001)
        assert before["current_kg"] == pytest.approx(TEST_DEFAULTS["BAGGING_OUTPUT_KG"], abs=0.001)
        assert before["cumulative_shrink_kg"] == pytest.approx(BAGGED_CUMULATIVE_SHRINK_KG, abs=0.001)
        assert before["dockage_pct"] == pytest.approx(BAGGED_DOCKAGE_PCT, abs=0.01)

        validate_success(
            api.reverse_conditioning_run(
                state["bagging_run"]["id"],
                reverse_conditioning_run_payload(reversal_reason="Bagger scale mis-tare, re-bag required"),
                make_conditioning_manager_headers(),
            ),
            200,
        )

        after = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert_lot_mass_conserved(after)
        assert after["gross_kg"] == pytest.approx(TEST_DEFAULTS["GROSS_WEIGHT_KG"], abs=0.001)
        assert after["current_kg"] == pytest.approx(SIZED_CURRENT_KG, abs=0.001)
        assert after["cumulative_shrink_kg"] == pytest.approx(SIZED_CUMULATIVE_SHRINK_KG, abs=0.001)
        assert after["dockage_pct"] == pytest.approx(SIZED_DOCKAGE_PCT, abs=0.01)

    def test_the_derived_bag_fields_and_the_earlier_runs_are_restored_not_rewritten(self, api):
        """The bagging-specific fields return to their pre-run nulls; earlier runs stand.

        PRD: "When the reversed run was the bagging run, the lot's `bag_count` returns to 0, its
        `final_clean_units` returns to null, and its `dockage_pct` is recomputed from the restored
        figures."

        Design: Difficulty/compensating_invariant/bagging_reversal_preserves_lot_mass
        """
        state = bagged_lot_state(api)
        reason = "Bagger scale mis-tare, re-bag required"
        validate_success(
            api.reverse_conditioning_run(
                state["bagging_run"]["id"],
                reverse_conditioning_run_payload(reversal_reason=reason),
                make_conditioning_manager_headers(),
            ),
            200,
        )

        headers = make_conditioning_manager_headers()
        lot = get_success_data(api.get_seed_lot(state["seed_lot"]["id"], headers))
        assert lot["bag_count"] == 0
        assert lot["final_clean_units"] is None
        assert lot["conditioning_status"] == "SIZED"
        assert lot["certification_status"] == "UNSAMPLED"

        reversed_run = get_success_data(api.get_conditioning_run(state["bagging_run"]["id"], headers))
        assert reversed_run["status"] == "REVERSED"
        assert reversed_run["reversal_reason"] == reason
        assert reversed_run["shrink_kg"] == pytest.approx(BAGGING_SHRINK_KG, abs=0.001)

        cleaning = get_success_data(api.get_conditioning_run(state["cleaning_run"]["id"], headers))
        sizing = get_success_data(api.get_conditioning_run(state["sizing_run"]["id"], headers))
        assert cleaning["status"] == "COMPLETED"
        assert sizing["status"] == "COMPLETED"


class TestSettlementDisputeRestoresAdvanceConservation:
    def test_disputing_an_approved_settlement_returns_the_whole_recovery(self, api):
        """Approval booked the recovery and the dispute puts back exactly the same cents.

        PRD: "Approving a settlement books its recovery; disputing a settlement that had already
        been approved returns exactly the same amount."

        Design: Difficulty/compensating_invariant/settlement_dispute_restores_advance_conservation
        """
        state = approved_settlement_state(api)
        contract_id = state["contract"]["id"]

        before = get_success_data(api.get_production_contract(contract_id, make_program_admin_headers()))
        assert before["advance_outstanding_cents"] == 0
        assert before["status"] == "SETTLED"
        assert_advance_conserved(before, [state["settlement"]])

        validate_success(
            api.dispute_settlement(
                state["settlement"]["id"],
                dispute_settlement_payload(
                    dispute_reason="Dockage on the bagging pass is contested by the grower"
                ),
                make_grower_headers(state["grower"]["id"]),
            ),
            200,
        )

        after = get_success_data(api.get_production_contract(contract_id, make_program_admin_headers()))
        assert after["advance_outstanding_cents"] == TEST_DEFAULTS["ADVANCE_TOTAL_CENTS"]
        assert after["status"] == "HARVESTED"

        settlement = get_success_data(
            api.get_settlement(state["settlement"]["id"], make_settlement_accountant_headers())
        )
        assert_advance_conserved(after, [settlement])

    def test_the_monetary_lines_are_frozen_and_the_unit_rollup_is_untouched(self, api):
        """The dispute moves money only: every computed line and the certified total stand.

        PRD: "The contract's `certified_units_total` is a derived roll-up over its `TAGGED` lots
        and is never touched by any settlement money movement, in either direction."

        Design: Difficulty/compensating_invariant/settlement_dispute_restores_advance_conservation
        """
        state = approved_settlement_state(api)
        reason = "Dockage on the bagging pass is contested by the grower"
        validate_success(
            api.dispute_settlement(
                state["settlement"]["id"],
                dispute_settlement_payload(dispute_reason=reason),
                make_grower_headers(state["grower"]["id"]),
            ),
            200,
        )

        settlement = get_success_data(
            api.get_settlement(state["settlement"]["id"], make_settlement_accountant_headers())
        )
        assert settlement["status"] == "DISPUTED"
        assert settlement["dispute_reason"] == reason
        assert settlement["approved_by_user_id"] == "acct-2"
        assert settlement["advance_recovery_cents"] == GOLDEN_FIGURES["ADVANCE_RECOVERY_CENTS"]
        assert settlement["net_payable_cents"] == GOLDEN_FIGURES["NET_PAYABLE_CENTS"]
        assert settlement["gross_payable_cents"] == GOLDEN_FIGURES["GROSS_PAYABLE_CENTS"]
        assert settlement["quality_hold"] is False
        assert settlement["settled_units_total"] == pytest.approx(
            GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01
        )

        lot = get_success_data(
            api.get_seed_lot(state["seed_lot"]["id"], make_conditioning_manager_headers())
        )
        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert lot["certification_status"] == "TAGGED"
        assert contract["certified_units_total"] == pytest.approx(
            GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01
        )


class TestTagVoidRestoresBagAccounting:
    def test_voiding_the_only_tag_walks_both_ledgers_back(self, api):
        """The bag ledger and the contract roll-up both return, and the physical bags remain.

        PRD: "Voiding stores the reason, moves the tag `ISSUED → VOIDED`, and subtracts the tag's
        `bag_count` back out of the lot's `tagged_bag_count`, restoring the invariant that the
        lot's tagged bag count equals the sum of bag counts over its still-issued tags."

        Design: Difficulty/compensating_invariant/tag_void_restores_bag_accounting
        """
        state = tagged_lot_state(api)
        lot_id = state["seed_lot"]["id"]
        reason = "Tag stock printed with the wrong lot code"

        assert_tagged_bag_count_matches_issued_tags(state["seed_lot"], [state["tag"]])
        assert state["seed_lot"]["tagged_bag_count"] == GOLDEN_FIGURES["BAG_COUNT"]
        assert state["contract"]["certified_units_total"] == pytest.approx(
            GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01
        )

        voided = validate_success(
            api.void_certification_tag(
                state["tag"]["id"],
                void_certification_tag_payload(void_reason=reason),
                make_certification_agency_headers(),
            ),
            200,
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == reason

        lot = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert_tagged_bag_count_matches_issued_tags(lot, [voided])
        assert lot["tagged_bag_count"] == 0
        assert lot["certification_status"] == "PASSED"
        assert lot["adjusted_price_per_unit_cents"] == GOLDEN_FIGURES["ADJUSTED_PRICE_PER_UNIT_CENTS"]
        assert lot["bag_count"] == GOLDEN_FIGURES["BAG_COUNT"]
        assert lot["current_kg"] == pytest.approx(TEST_DEFAULTS["BAGGING_OUTPUT_KG"], abs=0.001)
        assert lot["final_clean_units"] == pytest.approx(GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01)

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert contract["certified_units_total"] == pytest.approx(0.0, abs=0.01)

        _tags, meta = validate_paginated(
            api.list_certification_tags(
                make_certification_agency_headers(), {"seed_lot_id": lot_id, "status": "ISSUED"}
            )
        )
        assert meta["total_count"] == 0

    def test_a_second_void_is_refused_so_the_compensation_is_never_applied_twice(self, api):
        """The already-voided guard is what keeps the bag ledger from being walked back twice.

        PRD: "The operator supplies a `void_reason`; a tag that is already `VOIDED` is refused with
        `ERR_TAG_ALREADY_VOIDED`."

        Design: Difficulty/compensating_invariant/tag_void_restores_bag_accounting
        """
        state = tagged_lot_state(api)
        lot_id = state["seed_lot"]["id"]
        first = validate_success(
            api.void_certification_tag(
                state["tag"]["id"],
                void_certification_tag_payload(),
                make_certification_agency_headers(),
            ),
            200,
        )

        response = api.void_certification_tag(
            state["tag"]["id"],
            void_certification_tag_payload(void_reason="Duplicate void attempt"),
            make_certification_agency_headers(),
        )
        validate_error(response, "ERR_TAG_ALREADY_VOIDED", 409)

        tag = get_success_data(api.get_certification_tag(state["tag"]["id"], make_certification_agency_headers()))
        assert tag["status"] == "VOIDED"
        assert tag["void_reason"] == first["void_reason"]
        assert tag["version"] == first["version"]

        lot = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert lot["tagged_bag_count"] == 0
        assert lot["certification_status"] == "PASSED"

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert contract["certified_units_total"] == pytest.approx(0.0, abs=0.01)
