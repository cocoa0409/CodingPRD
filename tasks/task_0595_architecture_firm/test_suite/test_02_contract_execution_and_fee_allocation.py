"""Contract execution: the pinned fee-allocation order, its preconditions and its cascades."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error,
    assert_contract, assert_phase, assert_phase_allocation_sums_to_total,
    assert_contract_wip_identity,
    state_payload,
    setup_draft_contract_project, setup_executed_project,
    activate_phase, set_phase_percent, read_contract, read_phase, read_all_phases,
    read_project, PRINCIPAL,
)

# construction_cost_estimate_cents 123456789 at 875 bp -> base_fee_cents 10_802_469.
ROUNDING_CONTRACT = {
    "construction_cost_estimate_cents": 123_456_789,
    "fee_rate_bp": 875,
}
ROUNDING_WEIGHTS = (1667, 1667, 3333, 3333)


class TestPinnedFeeAllocationOrder:

    def test_each_phase_rounds_and_the_last_phase_absorbs_the_remainder(self, api):
        """PRD §3.3: "For every phase **except the last**, set `fee_allocation_cents` to the
        contract's `total_fee_cents` multiplied by that phase's `weight_bp`, divided by 10000,
        rounded half up to whole cents, and keep a running total of the amounts so assigned."
        PRD §3.3: "The last phase in the order — `CA` — is not computed from its own weight at
        all: it receives `total_fee_cents` minus that running total, absorbing whatever remainder
        rounding left behind."
        PRD §3.2: "It freezes `base_fee_cents`: on a `PERCENT_OF_CONSTRUCTION` contract this is
        the `construction_cost_estimate_cents` multiplied by `fee_rate_bp`, divided by 10000,
        rounded half up to whole cents; on an `HOURLY` contract it is simply the
        `not_to_exceed_cents` ceiling."

        Design: Difficulty/combinatorial_formula/phase_fee_allocation_rounds_per_phase_then_last_phase_absorbs_remainder
        """
        bundle = setup_draft_contract_project(
            project_number="RND-001", name="Rounding House",
            weights=ROUNDING_WEIGHTS, contract_overrides=ROUNDING_CONTRACT,
            with_architect=False,
        )

        contract = validate_success(
            api.set_contract_state(bundle["contract_id"], state_payload("EXECUTED"), PRINCIPAL)
        )
        assert_contract(contract)

        assert contract["base_fee_cents"] == 10_802_469
        assert contract["total_fee_cents"] == 10_802_469

        sd = read_phase(bundle, "SD")
        dd = read_phase(bundle, "DD")
        cd = read_phase(bundle, "CD")
        ca = read_phase(bundle, "CA")
        for phase in (sd, dd, cd, ca):
            assert_phase(phase)

        assert sd["fee_allocation_cents"] == 1_800_772
        assert dd["fee_allocation_cents"] == 1_800_772
        assert cd["fee_allocation_cents"] == 3_600_463
        # CA is the remainder phase: 10_802_469 - 7_202_007 == 3_600_462, one cent below the
        # value its own weight would have produced.
        assert ca["fee_allocation_cents"] == 3_600_462

    def test_phase_allocations_sum_to_total_fee_with_no_cent_lost(self, api):
        """PRD §2.9: "the contract's `total_fee_cents` always equals its `base_fee_cents` plus
        the sum of `fee_delta_cents` over that contract's change orders in status `EXECUTED`, and
        the four phases' `fee_allocation_cents` always sum to exactly `total_fee_cents`, with no
        cent lost to rounding."
        PRD §3.3: "Summing the four unrounded shares and rounding the sum is a different and
        incorrect procedure; it can overshoot `total_fee_cents` by a cent, and it is not what
        this system does."

        Design: Difficulty/combinatorial_formula/phase_fee_allocation_rounds_per_phase_then_last_phase_absorbs_remainder
        """
        bundle = setup_executed_project(
            project_number="RND-002", name="Rounding Row",
            weights=ROUNDING_WEIGHTS, contract_overrides=ROUNDING_CONTRACT,
            with_architect=False,
        )

        contract = read_contract(bundle)
        phases = read_all_phases(bundle)

        assert contract["total_fee_cents"] == 10_802_469
        assert contract["total_fee_cents"] == contract["base_fee_cents"]
        assert_phase_allocation_sums_to_total(phases, contract["total_fee_cents"])

        total = sum(p["fee_allocation_cents"] for p in phases)
        assert total == 10_802_469, (
            "the rejected 'round every phase independently' order would total 10_802_470"
        )


class TestExecutionPreconditions:

    def test_execution_with_weights_not_summing_to_10000_is_rejected(self, api):
        """PRD §3.2: "The project must have exactly four phases, one for each of the four codes;
        and those four phases' `weight_bp` values must sum to exactly 10000. A project with three
        phases, or five, or four whose weights sum to 9999, is rejected with
        `ERR_PHASE_WEIGHTS_INVALID`."
        PRD §3.2: "A freshly created contract sits in `DRAFT` with `base_fee_cents`,
        `total_fee_cents`, `earned_to_date_cents`, `billed_fee_to_date_cents` and
        `wip_balance_cents` all at 0."

        Design: Corner/state_machines/contract_execution_with_weights_not_summing_to_10000_is_rejected
        """
        bundle = setup_draft_contract_project(
            project_number="WGT-001", name="Weight Works",
            weights=(2000, 2000, 3000, 2000),  # sums to 9000
            with_architect=False, labor_budget_cents=500_000,
        )

        response = api.set_contract_state(
            bundle["contract_id"], state_payload("EXECUTED"), PRINCIPAL
        )
        validate_error(response, ApiErrorId.ERR_PHASE_WEIGHTS_INVALID.value)

        contract = read_contract(bundle)
        assert contract["status"] == "DRAFT"
        assert contract["base_fee_cents"] == 0
        assert read_phase(bundle, "SD")["fee_allocation_cents"] == 0
        # The DRAFT -> ACTIVE project cascade is driven purely by contract execution.
        assert read_project(bundle)["status"] == "DRAFT"

    def test_transition_out_of_terminated_contract_is_rejected(self, api):
        """PRD §2.9: "A destination that is not reachable from the current state — or is not a
        state of that resource at all — is rejected with `ERR_INVALID_STATE`."
        PRD §3.2: "An executed contract may later be driven to `TERMINATED`, again by a
        `PrincipalArchitect`, but only when no invoice on that contract is still sitting in
        `DRAFT` — the firm may not walk away with an un-issued bill in flight."

        Design: Corner/state_machines/contract_execution_from_terminated_returns_invalid_state
        """
        bundle = setup_executed_project(
            project_number="TRM-001", name="Terminal Terrace",
            with_architect=False, labor_budget_cents=500_000,
        )
        terminated = validate_success(
            api.set_contract_state(bundle["contract_id"], state_payload("TERMINATED"), PRINCIPAL)
        )
        assert terminated["status"] == "TERMINATED"

        response = api.set_contract_state(
            bundle["contract_id"], state_payload("EXECUTED"), PRINCIPAL
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

        contract = read_contract(bundle)
        assert contract["status"] == "TERMINATED"
        assert contract["total_fee_cents"] == 10_000_000


class TestLedgerVersioningAndImmediacy:

    def test_contract_version_increments_on_every_ledger_touching_write(self, api):
        """PRD §2.4: "Most resources additionally carry an `updated_at` timestamp, in the same
        format, and an integer `version` that starts at 1 on creation and increments by exactly 1
        on every mutation of that resource."
        PRD §2.9: "In particular, a great many operations bump `Contract.version` as a *side*
        effect: executing the contract itself, completing a phase, patching a phase's percent
        complete, approving a time entry or reverting one, executing a change order, voiding an
        executed change order, drafting an invoice, issuing an invoice, and voiding an issued
        invoice."

        Design: Corner/cross_cutting_complexity_layers/contract_version_increments_on_every_ledger_touching_write
        """
        bundle = setup_draft_contract_project(project_number="VER-001", name="Version Vault",
                                              with_architect=False)
        assert bundle["contract"]["version"] == 1

        executed = validate_success(
            api.set_contract_state(bundle["contract_id"], state_payload("EXECUTED"), PRINCIPAL)
        )
        assert executed["version"] == 2

        # Phase activation is not on the PRD's list of contract-ledger-touching writes.
        activate_phase(bundle, "SD")
        assert read_contract(bundle)["version"] == 2

        set_phase_percent(bundle, "SD", 30)
        contract = read_contract(bundle)
        assert contract["version"] == 3
        assert contract["earned_to_date_cents"] == 600_000  # 2_000_000 * 30 / 100
        assert contract["wip_balance_cents"] == 600_000
        assert_contract_wip_identity(contract)

    def test_phase_completion_cascade_is_visible_in_the_same_response(self, api):
        """PRD §2.9: "Each hop is a consequence of the previous one, and the whole chain settles
        before the response is written — the API's consistency model is immediate, never eventual."
        PRD §3.3: "When it succeeds, the phase's `percent_complete` is forced to 100 and its
        `earned_cents` consequently becomes its full `fee_allocation_cents`."
        PRD §3.3: "A completion landing exactly on the due instant is `MET`, not `MISSED`."

        Design: Corner/consistency_model/phase_completion_cascade_is_visible_in_the_same_response
        """
        bundle = setup_executed_project(project_number="IMD-001", name="Immediate Inn",
                                        with_architect=False)
        activate_phase(bundle, "SD")

        completed = validate_success(
            api.set_phase_state(
                bundle["phase_ids"]["SD"], state_payload("COMPLETED"), bundle["pm_headers"]
            )
        )
        assert_phase(completed)
        assert completed["percent_complete"] == 100
        assert completed["earned_cents"] == 2_000_000
        # The logical clock is still at its 2026-05-01T00:00:00Z default, well before the
        # SD milestone of 2026-08-01T00:00:00Z.
        assert completed["milestone_status"] == "MET"

        contract = read_contract(bundle)
        assert contract["earned_to_date_cents"] == 2_000_000
        assert contract["wip_balance_cents"] == 2_000_000
        assert_contract_wip_identity(contract)
