"""Initial states, declared transitions, refused transitions and terminal lockdown."""

from __future__ import annotations

import pytest

from test_helpers import (
    GOLDEN_FIGURES,
    TEST_DEFAULTS,
    assert_production_contract,
    cancel_contract_payload,
    computed_settlement_state,
    create_conditioning_run_payload,
    create_settlement_payload,
    dispute_settlement_payload,
    draft_contract_state,
    get_success_data,
    harvested_lot_state,
    make_conditioning_manager_headers,
    make_field_officer_headers,
    make_grower_headers,
    make_program_admin_headers,
    make_settlement_accountant_headers,
    offered_contract_state,
    paid_settlement_state,
    plan_run,
    read_contract_version,
    reverse_conditioning_run_payload,
    sign_contract_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestContractInitialState:
    def test_a_freshly_drafted_contract_lands_in_draft_with_zeroed_counters(self, api):
        """Every derived counter starts at zero and the advance is seeded in full.

        PRD: "A freshly drafted contract lands in `DRAFT` status with `advance_outstanding_cents`
        initialised to the full `advance_total_cents`, `inspection_round` and `rogueing_rounds_used`
        at 0, `provisional_clean_units_total` and `certified_units_total` at 0,
        `requires_field_officer_review` false, and `eligibility_variant_applied`,
        `eligibility_risk_score`, `planted_on` and `cancel_reason` all null."

        Design: Corner/state_machines/contract_initial_state_is_draft
        """
        state = draft_contract_state(api)
        contract = state["contract"]

        assert_production_contract(contract)
        assert contract["status"] == "DRAFT"
        assert contract["version"] == 1
        assert contract["inspection_round"] == 0
        assert contract["rogueing_rounds_used"] == 0
        assert contract["advance_total_cents"] == TEST_DEFAULTS["ADVANCE_TOTAL_CENTS"]
        assert contract["advance_outstanding_cents"] == TEST_DEFAULTS["ADVANCE_TOTAL_CENTS"]
        assert contract["provisional_clean_units_total"] == pytest.approx(0.0, abs=0.01)
        assert contract["certified_units_total"] == pytest.approx(0.0, abs=0.01)
        assert contract["requires_field_officer_review"] is False
        assert contract["eligibility_variant_applied"] is None
        assert contract["eligibility_risk_score"] is None
        assert contract["planted_on"] is None
        assert contract["cancel_reason"] is None


class TestContractOfferTransition:
    def test_offering_a_clean_draft_records_the_variant_it_applied(self, api):
        """The offer gate passes and writes back which eligibility variant bound the decision.

        PRD: "Offering a drafted contract, which is a `ProgramAdmin` operation, advances the
        contract `DRAFT → OFFERED` only after five gates pass in the priority order of §2.9."

        PRD: "It sets `eligibility_variant_applied` to `STRICT_HISTORY` when the contract's class is
        `FOUNDATION`, `REGISTERED` or `CERTIFIED` and to `DECAY_WEIGHTED` when the class is
        `COMMERCIAL_INCREASE`; it sets `eligibility_risk_score` to the contamination risk score the
        assessment produced; it writes that same score onto the field's `last_assessed_risk_score`
        and increments the field's `version` by 1; and it increments the contract's own `version` by
        1."

        Design: Corner/state_machines/contract_offer_moves_draft_to_offered
        """
        state = draft_contract_state(api)
        before = get_success_data(
            api.get_production_field(state["field"]["id"], make_field_officer_headers())
        )

        offered = validate_success(
            api.offer_production_contract(
                state["contract"]["id"], {}, make_program_admin_headers()
            ),
            200,
        )
        assert offered["status"] == "OFFERED"
        assert offered["version"] == 2
        assert offered["eligibility_variant_applied"] == "STRICT_HISTORY"
        assert offered["eligibility_risk_score"] == pytest.approx(0.00, abs=0.01)

        field = get_success_data(
            api.get_production_field(state["field"]["id"], make_field_officer_headers())
        )
        assert field["last_assessed_risk_score"] == pytest.approx(0.00, abs=0.01)
        assert field["version"] == before["version"] + 1

        grower = get_success_data(api.get_grower(state["grower"]["id"], make_program_admin_headers()))
        assert grower["status"] == "GOOD_STANDING"
        assert grower["compliance_flag_count"] == 0


class TestContractSignBeforeOffer:
    def test_signing_a_contract_that_was_never_offered_is_refused(self, api):
        """Signing is declared only out of `OFFERED`, so a draft cannot be signed.

        PRD: "Signing a contract that is not in `OFFERED` status is refused with
        `ERR_INVALID_CONTRACT_STATE`."

        Design: Corner/state_machines/contract_sign_before_offer_rejected
        """
        state = draft_contract_state(api)

        response = api.sign_production_contract(
            state["contract"]["id"],
            sign_contract_payload(),
            make_grower_headers(state["grower"]["id"]),
        )
        validate_error(response, "ERR_INVALID_CONTRACT_STATE", 409)

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert contract["status"] == "DRAFT"
        assert contract["planted_on"] is None
        assert contract["version"] == 1


class TestContractCancelledIsTerminal:
    def test_a_second_cancellation_is_refused_and_the_stored_reason_stands(self, api):
        """`CANCELLED` is terminal, so the second cancel neither overwrites nor re-bumps.

        PRD: "A cancellation carries a `cancel_reason` and is accepted only while the contract's
        status is `DRAFT`, `OFFERED`, `PLANTED` or `ROGUEING_REQUIRED`; from any other status,
        including `INSPECTION_PASSED` and every terminal status, it is refused with
        `ERR_INVALID_CONTRACT_STATE`."

        PRD: "`CANCELLED` is terminal, as are `REJECTED` and `CLOSED`."

        Design: Corner/state_machines/contract_cancel_twice_second_rejected
        """
        state = offered_contract_state(api)
        first_reason = "Grower withdrew from the program"

        cancelled = validate_success(
            api.cancel_production_contract(
                state["contract"]["id"],
                cancel_contract_payload(cancel_reason=first_reason),
                make_program_admin_headers(),
            ),
            200,
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == first_reason
        assert cancelled["version"] == 3

        response = api.cancel_production_contract(
            state["contract"]["id"],
            cancel_contract_payload(cancel_reason="Duplicate cancellation attempt"),
            make_program_admin_headers(),
        )
        validate_error(response, "ERR_INVALID_CONTRACT_STATE", 409)

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert contract["status"] == "CANCELLED"
        assert contract["cancel_reason"] == first_reason
        assert contract["version"] == 3


class TestOfferGateOnRestrictedHistory:
    def test_a_restricted_prior_crop_inside_the_look_back_blocks_the_offer(self, api):
        """Wheat grown in 2024 is inside the three-year window for a 2026 wheat contract.

        PRD: "The eligibility assessment under the variant selected by the contract's `seed_class`
        must return an eligible verdict, and when it does not the offer is refused with the
        variant's own blocking error — `ERR_FIELD_HISTORY_RESTRICTED` when a restricted prior crop
        is the cause."

        PRD: "The strict variant's blocking error is `ERR_FIELD_HISTORY_RESTRICTED` whenever at
        least one restricted record exists, and `ERR_ISOLATION_DISTANCE_INSUFFICIENT` when there is
        no restricted record but the shortfall is positive — history is examined before isolation,
        so a field failing both reports the history error."

        Design: Corner/state_machines/offer_with_restricted_history_rejected
        """
        state = draft_contract_state(
            api,
            history_overrides={
                "crop_kind": "WHEAT",
                "crop_year": 2024,
                "source_note": "Grower-declared prior crop",
            },
        )

        response = api.offer_production_contract(
            state["contract"]["id"], {}, make_program_admin_headers()
        )
        error = validate_error(response, "ERR_FIELD_HISTORY_RESTRICTED", 422)
        assert error["error_id"] != "ERR_ISOLATION_DISTANCE_INSUFFICIENT"

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert contract["status"] == "DRAFT"
        assert contract["version"] == 1
        assert contract["eligibility_variant_applied"] is None

        history = get_success_data(
            api.get_field_history_record(state["history"]["id"], make_field_officer_headers())
        )
        assert history["crop_kind"] == "WHEAT"
        assert history["crop_year"] == 2024


class TestSettlementPaidIsTerminal:
    def test_a_paid_settlement_cannot_be_disputed_afterwards(self, api):
        """Payment closes the file: the grower's compensating lever is gone.

        PRD: "A `Grower` whose `X-User-ID` equals the contract's `grower_id` may dispute a
        settlement whose status is `COMPUTED` or `APPROVED`, supplying a `dispute_reason`; any other
        status is refused with `ERR_INVALID_SETTLEMENT_STATE`, and a mismatched grower identity is
        refused with `ERR_GROWER_SCOPE_VIOLATION`."

        PRD: "`SUPERSEDED` and `PAID` are the two terminal settlement states."

        Design: Corner/state_machines/settlement_paid_is_terminal_and_blocks_dispute
        """
        state = paid_settlement_state(api)

        response = api.dispute_settlement(
            state["settlement"]["id"],
            dispute_settlement_payload(dispute_reason="Late objection after payment"),
            make_grower_headers(state["grower"]["id"]),
        )
        validate_error(response, "ERR_INVALID_SETTLEMENT_STATE", 409)

        settlement = get_success_data(
            api.get_settlement(state["settlement"]["id"], make_settlement_accountant_headers())
        )
        assert settlement["status"] == "PAID"
        assert settlement["payment_reference"] == TEST_DEFAULTS["PAYMENT_REFERENCE"]
        assert settlement["dispute_reason"] is None
        assert settlement["net_payable_cents"] == GOLDEN_FIGURES["NET_PAYABLE_CENTS"]
        assert settlement["advance_recovery_cents"] == GOLDEN_FIGURES["ADVANCE_RECOVERY_CENTS"]

        contract = get_success_data(
            api.get_production_contract(state["contract"]["id"], make_program_admin_headers())
        )
        assert contract["status"] == "CLOSED"
        assert contract["advance_outstanding_cents"] == 0


class TestPlannedRunReversal:
    def test_aborting_a_planned_run_moves_no_mass_and_frees_the_line_window(self, api):
        """The abort releases the window it held and leaves the lot's ledger alone.

        PRD: "Reversing a run that is still in `PLANNED` status simply aborts it: the supplied
        `reversal_reason` is stored, the run moves `PLANNED → ABORTED`, the line window it held is
        released so a later run may occupy it, and the lot's mass fields are left completely
        untouched."

        PRD: "Only runs in `PLANNED` or `COMPLETED` status occupy a line; runs in `ABORTED` or
        `REVERSED` status have released their window and are ignored by the conflict scan."

        Design: Corner/state_machines/run_planned_reversal_aborts_without_mass_change
        """
        state = harvested_lot_state(api)
        lot_id = state["seed_lot"]["id"]
        line_id = state["line"]["id"]
        reason = "Cleaner rescheduled to the night shift"

        planned = plan_run(api, lot_id, line_id, "CLEANING")
        assert planned["status"] == "PLANNED"

        aborted = validate_success(
            api.reverse_conditioning_run(
                planned["id"],
                reverse_conditioning_run_payload(reversal_reason=reason),
                make_conditioning_manager_headers(),
            ),
            200,
        )
        assert aborted["status"] == "ABORTED"
        assert aborted["reversal_reason"] == reason
        assert aborted["shrink_kg"] is None
        assert aborted["output_kg"] is None

        lot = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert lot["current_kg"] == pytest.approx(TEST_DEFAULTS["GROSS_WEIGHT_KG"], abs=0.001)
        assert lot["cumulative_shrink_kg"] == pytest.approx(0.0, abs=0.001)
        assert lot["dockage_pct"] == pytest.approx(0.00, abs=0.01)
        assert lot["conditioning_status"] == "RAW"

        replanned = validate_success(
            api.create_conditioning_run(
                create_conditioning_run_payload(lot_id, line_id, "CLEANING"),
                make_conditioning_manager_headers(),
            ),
            201,
        )
        assert replanned["status"] == "PLANNED"
        assert replanned["window_start"] == planned["window_start"]
        assert replanned["window_end"] == planned["window_end"]

        line = get_success_data(api.get_conditioning_line(line_id, make_conditioning_manager_headers()))
        assert line["last_run_end_utc"] is None
        assert line["last_cleanout_variety_id"] is None


class TestSettlementSupersession:
    def test_a_second_computation_supersedes_the_first_without_moving_money(self, api):
        """The superseded settlement keeps its figures and the advance stays outstanding.

        PRD: "Creating a settlement legitimately supersedes the contract's earlier work: every
        earlier settlement of that contract whose status is `COMPUTED` or `DISPUTED` moves to
        `SUPERSEDED`, with no monetary movement of any kind, because the superseding settlement
        carries the recomputed figures."

        PRD: "Computing a settlement also increments the contract's `version` by 1, which is what
        makes a second computation against a version the accountant has not re-read fail the version
        pin."

        Design: Corner/state_machines/newer_settlement_supersedes_prior_computed
        """
        state = computed_settlement_state(api)
        contract_id = state["contract"]["id"]
        first_id = state["settlement"]["id"]

        second = validate_success(
            api.create_settlement(
                create_settlement_payload(contract_id, read_contract_version(api, contract_id)),
                make_settlement_accountant_headers(),
            ),
            201,
        )
        assert second["status"] == "COMPUTED"
        assert second["net_payable_cents"] == GOLDEN_FIGURES["NET_PAYABLE_CENTS"]
        assert second["settled_units_total"] == pytest.approx(
            GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01
        )

        first = get_success_data(api.get_settlement(first_id, make_settlement_accountant_headers()))
        assert first["status"] == "SUPERSEDED"
        assert first["net_payable_cents"] == GOLDEN_FIGURES["NET_PAYABLE_CENTS"]

        contract = get_success_data(
            api.get_production_contract(contract_id, make_program_admin_headers())
        )
        assert contract["advance_outstanding_cents"] == TEST_DEFAULTS["ADVANCE_TOTAL_CENTS"]
        assert contract["status"] == "HARVESTED"

        _settlements, meta = validate_paginated(
            api.list_settlements(
                make_settlement_accountant_headers(), {"production_contract_id": contract_id}
            )
        )
        assert meta["total_count"] == 2
