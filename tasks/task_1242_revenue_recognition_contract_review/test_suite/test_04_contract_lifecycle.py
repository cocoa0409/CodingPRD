"""Contract lifecycle: review loop, review gate, cancellation, absorption
(PRD §3.2, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    create_customer, create_contract, create_ssp, add_pob, add_clause,
    submit_contract, approve_contract, activate_contract, get_contract, get_pob,
    make_reviewer_headers, setup_contract_in_review_with_clause,
)


class TestRevisionCycle:
    def test_review_loop_statuses(self, api, accountant_headers, manager_headers):
        """PRD §3.1: "the contract's `status` walks the review loop `DRAFT →
        IN_REVIEW → APPROVED → ACTIVE`, with the revision detour `IN_REVIEW →
        CHANGES_REQUESTED → IN_REVIEW`".

        Design: Difficulty/non_linear_state_machine/contract_review_revision_cycle
        """
        create_ssp("WIDGET", region="US", ssp_cents=100000)
        customer = create_customer(legal_name="Cycle Co", external_ref="CYC-1")
        contract = create_contract(customer["id"], contract_ref="C-CYCLE")
        add_pob(contract["id"], pob_ref="P1")

        assert validate_success(api.submit_contract(contract["id"], accountant_headers))["status"] == "IN_REVIEW"
        returned = validate_success(
            api.return_contract(contract["id"], {"reason": "pricing questions"}, manager_headers)
        )
        assert returned["status"] == "CHANGES_REQUESTED"
        resubmitted = validate_success(api.submit_contract(contract["id"], accountant_headers))
        assert resubmitted["status"] == "IN_REVIEW", "revision loop must return to IN_REVIEW"
        approved = validate_success(api.approve_contract(contract["id"], manager_headers))
        assert approved["status"] == "APPROVED"
        activated = validate_success(api.activate_contract(contract["id"], manager_headers))
        assert activated["status"] == "ACTIVE"

    def test_revision_loop_bumps_version_each_mutation(self, api, accountant_headers, manager_headers):
        """PRD §2.4: "submitting, returning, approving, activating, holding,
        resuming, cancelling, and absorbing a contract; proposing a modification
        and approving one; approving an estimate; issuing and voiding an
        invoice; and posting a reversal each increment the owning contract's
        `version` by one and refresh its `updated_at`."

        Design: Difficulty/non_linear_state_machine/contract_review_revision_cycle
        """
        create_ssp("WIDGET", region="US", ssp_cents=100000)
        customer = create_customer()
        contract = create_contract(customer["id"])
        add_pob(contract["id"], pob_ref="P1")
        assert contract["version"] == 1
        assert submit_contract(contract["id"])["version"] == 2
        assert validate_success(
            api.return_contract(contract["id"], {"reason": "r"}, manager_headers)
        )["version"] == 3
        assert submit_contract(contract["id"])["version"] == 4
        assert approve_contract(contract["id"])["version"] == 5
        assert activate_contract(contract["id"])["version"] == 6

    def test_return_requires_reason(self, api, accountant_headers, manager_headers):
        """PRD §3.2: "A `RevenueManager` who is unsatisfied returns the contract
        — `IN_REVIEW → CHANGES_REQUESTED` — supplying a `reason`".
        PRD §2.8: "At this same tier, required request fields must be present
        — including pattern-conditional fields such as the service dates for a
        straight-line obligation or `estimated_total_cost_cents` for an
        input-cost obligation — values must be well-formed, and enum fields must
        hold declared members; failures of this kind return `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Difficulty/non_linear_state_machine/contract_review_revision_cycle
        """
        create_ssp("WIDGET", region="US", ssp_cents=100000)
        customer = create_customer()
        contract = create_contract(customer["id"])
        add_pob(contract["id"], pob_ref="P1")
        submit_contract(contract["id"])
        resp = api.return_contract(contract["id"], {}, manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestInvalidTransitions:
    def test_submit_from_approved_rejected(self, api, accountant_headers, manager_headers):
        """PRD §3.4: "Any attempt to drive a contract through a transition that
        does not exist from its current state is rejected with
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/submit_from_approved_returns_invalid_state_transition
        """
        create_ssp("WIDGET", region="US", ssp_cents=100000)
        customer = create_customer(legal_name="Tr Co", external_ref="TR-1")
        contract = create_contract(customer["id"], contract_ref="C-TR")
        add_pob(contract["id"], pob_ref="P1")
        submit_contract(contract["id"])
        approve_contract(contract["id"])
        resp = api.submit_contract(contract["id"], accountant_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    def test_contract_stays_approved_after_rejected_submit(self, api, accountant_headers, manager_headers):
        """PRD §3.4: "Any attempt to drive a contract through a transition that
        does not exist from its current state is rejected with
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/submit_from_approved_returns_invalid_state_transition
        """
        create_ssp("WIDGET", region="US", ssp_cents=100000)
        customer = create_customer()
        contract = create_contract(customer["id"])
        add_pob(contract["id"], pob_ref="P1")
        submit_contract(contract["id"])
        approve_contract(contract["id"])
        validate_error(api.submit_contract(contract["id"], accountant_headers),
                       ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        assert get_contract(contract["id"])["status"] == "APPROVED"


class TestReviewGate:
    def test_approve_blocked_while_task_outstanding(self, api, manager_headers):
        """PRD §3.4: "every clause of the contract must be `APPROVED`, so a
        single clause still `PENDING_REVIEW` or already `REJECTED` blocks
        approval with `ERR_REVIEW_OUTSTANDING` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/dependency_contract_approve_requires_decided_review_tasks
        """
        setup = setup_contract_in_review_with_clause(
            {"clause_code": "NS-1", "clause_type": "RIGHT_OF_RETURN"}
        )
        resp = api.approve_contract(setup["contract"]["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_REVIEW_OUTSTANDING, 409)
        assert get_contract(setup["contract"]["id"])["status"] == "IN_REVIEW"

    def test_approve_succeeds_after_clause_decided(self, api, manager_headers):
        """PRD §3.4: "When a `RevenueManager` approves a contract in `IN_REVIEW`,
        the system first enforces the review gate: every clause of the contract
        must be `APPROVED`".
        PRD §3.2: "A decision of `APPROVED` or `REJECTED` moves the task
        `RECOMMENDED → DECIDED`, records `decided_by_user_id`, and sets the
        reviewed clause's `status` to `APPROVED` or `REJECTED` accordingly."

        Design: Difficulty/cross_entity_state_dependency/dependency_contract_approve_requires_decided_review_tasks
        """
        setup = setup_contract_in_review_with_clause(
            {"clause_code": "NS-1", "clause_type": "RIGHT_OF_RETURN"}
        )
        task_id = setup["task"]["id"]
        rev1 = make_reviewer_headers("rev-1")
        rev2 = make_reviewer_headers("rev-2")
        validate_success(api.start_review_task(task_id, rev1))
        validate_success(api.recommend_review_task(task_id, {"recommendation": "APPROVE"}, rev1))
        validate_success(api.decide_review_task(task_id, {"decision": "APPROVED"}, rev2))
        approved = validate_success(api.approve_contract(setup["contract"]["id"], manager_headers))
        assert approved["status"] == "APPROVED"


class TestStandardClause:
    def test_standard_clause_starts_approved(self, api, accountant_headers):
        """PRD §3.2: "A clause's initial `status` depends entirely on that flag:
        non-standard clauses start in `PENDING_REVIEW` and must pass legal
        review, while standard clauses start already `APPROVED`."

        Design: Corner/endpoints/standard_clause_spawns_no_review_task
        """
        create_ssp("WIDGET", region="US", ssp_cents=100000)
        customer = create_customer(legal_name="Std Co", external_ref="STD-1")
        contract = create_contract(customer["id"], contract_ref="C-STD")
        add_pob(contract["id"], pob_ref="P1")
        clause = add_clause(
            contract["id"], clause_code="S1",
            clause_type="EXTENDED_PAYMENT_TERMS", is_non_standard=False,
        )
        assert clause["status"] == "APPROVED"

    def test_standard_clause_spawns_no_task_and_approves_immediately(self, api, accountant_headers, manager_headers, reviewer_headers):
        """PRD §3.2: "As the contract enters review, the system spawns one
        review task per clause that is non-standard and still `PENDING_REVIEW`;
        each task is created in `ASSIGNED` status with its `clause_id` pointing
        at the clause under review, its `contract_id` pointing at the owning
        contract, and its `reviewer_user_id` still null. Clauses already
        `APPROVED` keep their status and spawn no new task, so a re-submission
        after revisions only re-opens review for what actually changed."

        Design: Corner/endpoints/standard_clause_spawns_no_review_task
        """
        create_ssp("WIDGET", region="US", ssp_cents=100000)
        customer = create_customer()
        contract = create_contract(customer["id"])
        add_pob(contract["id"], pob_ref="P1")
        add_clause(contract["id"], clause_code="S1",
                   clause_type="EXTENDED_PAYMENT_TERMS", is_non_standard=False)
        submit_contract(contract["id"])
        tasks = validate_paginated(
            api.list_review_tasks(reviewer_headers, params={"contract_id": contract["id"]})
        )[0]
        assert tasks == [], "standard clauses must not spawn review tasks"
        approved = validate_success(api.approve_contract(contract["id"], manager_headers))
        assert approved["status"] == "APPROVED"


class TestCancellation:
    def test_cancel_cascades_pobs_and_locks_terminal(self, api, accountant_headers):
        """PRD §3.4: "from `DRAFT`, `IN_REVIEW`, or `CHANGES_REQUESTED`, a
        `RevenueAccountant` cancels the contract with a `reason`, moving it to
        the terminal `CANCELLED` state, cascading every obligation still
        `PENDING` or `IN_PROGRESS` to `CANCELLED`, and bumping the contract's
        `version`."
        PRD §3.4: "Any attempt to drive a contract through a transition that
        does not exist from its current state is rejected with
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/cancel_cascades_pobs_and_locks_terminal
        """
        create_ssp("WIDGET", region="US", ssp_cents=100000)
        customer = create_customer(legal_name="Term Co", external_ref="TERM-1")
        contract = create_contract(customer["id"], contract_ref="C-TERM")
        pob = add_pob(contract["id"], pob_ref="P1")
        cancelled = validate_success(
            api.cancel_contract(contract["id"], {"reason": "deal dead"}, accountant_headers)
        )
        assert cancelled["status"] == "CANCELLED"
        assert get_pob(pob["id"])["status"] == "CANCELLED"
        resp = api.submit_contract(contract["id"], accountant_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    def test_cancel_from_in_review_allowed(self, api, accountant_headers):
        """PRD §3.4: "from `DRAFT`, `IN_REVIEW`, or `CHANGES_REQUESTED`, a
        `RevenueAccountant` cancels the contract with a `reason`, moving it to
        the terminal `CANCELLED` state".

        Design: Corner/state_machines/cancel_cascades_pobs_and_locks_terminal
        """
        create_ssp("WIDGET", region="US", ssp_cents=100000)
        customer = create_customer()
        contract = create_contract(customer["id"])
        add_pob(contract["id"], pob_ref="P1")
        submit_contract(contract["id"])
        cancelled = validate_success(
            api.cancel_contract(contract["id"], {"reason": "withdrawn"}, accountant_headers)
        )
        assert cancelled["status"] == "CANCELLED"
        listed = validate_paginated(api.list_pobs(contract["id"], accountant_headers))[0]
        assert all(p["status"] == "CANCELLED" for p in listed)


class TestAbsorption:
    def _setup(self):
        create_ssp("WIDGET", region="US", ssp_cents=100000)
        customer = create_customer(legal_name="Comb Co", external_ref="COMB-1")
        c1 = create_contract(customer["id"], contract_ref="C1",
                             signed_date="2026-05-10", fixed_consideration_cents=100000,
                             package_negotiated_flag=True)
        c2 = create_contract(customer["id"], contract_ref="C2",
                             signed_date="2026-06-09", fixed_consideration_cents=50000)
        pob2 = add_pob(c2["id"], pob_ref="P2")
        c3 = create_contract(customer["id"], contract_ref="C3",
                             signed_date="2026-06-10", fixed_consideration_cents=70000)
        return customer, c1, c2, pob2, c3

    def test_thirty_one_day_gap_rejected(self, api, manager_headers):
        """PRD §3.4: "their `signed_date` values differ by at most thirty days —
        a gap of exactly thirty days is still combinable, and thirty-one is
        not" and "a signature gap beyond thirty days is rejected with
        `ERR_COMBINATION_WINDOW_EXCEEDED` (HTTP 409)".

        Design: Corner/calculations/combination_window_boundary_30_ok_31_rejected
        """
        _, c1, _, _, c3 = self._setup()
        resp = api.absorb_contract(c1["id"], {"absorbed_contract_id": c3["id"]}, manager_headers)
        validate_error(resp, ApiErrorId.ERR_COMBINATION_WINDOW_EXCEEDED, 409)
        assert get_contract(c3["id"])["status"] == "DRAFT"

    def test_thirty_day_gap_absorbs_and_moves_obligations(self, api, manager_headers):
        """PRD §3.4: "On absorption, the absorbed contract becomes `ABSORBED`
        with its `combined_into_contract_id` set to the survivor, every one of
        its obligations has its `contract_id` re-pointed to the survivor, the
        survivor's `fixed_consideration_cents` is increased by the absorbed
        contract's fixed consideration, the survivor's `transaction_price_cents`
        is recomputed, and the surviving contract's `version` is bumped."

        Design: Corner/calculations/combination_window_boundary_30_ok_31_rejected
        """
        _, c1, c2, pob2, _ = self._setup()
        survivor = validate_success(
            api.absorb_contract(c1["id"], {"absorbed_contract_id": c2["id"]}, manager_headers)
        )
        assert survivor["fixed_consideration_cents"] == 150000
        assert survivor["transaction_price_cents"] == 150000
        absorbed = get_contract(c2["id"])
        assert absorbed["status"] == "ABSORBED"
        assert absorbed["combined_into_contract_id"] == c1["id"]
        assert get_pob(pob2["id"])["contract_id"] == c1["id"]

    def test_different_customers_rejected(self, api, manager_headers):
        """PRD §3.4: "Two contracts are combinable only when all of the
        following hold: they belong to the same customer; their `signed_date`
        values differ by at most thirty days — a gap of exactly thirty days is
        still combinable, and thirty-one is not; at least one of the two carries
        `package_negotiated_flag` set to true; and both are still pre-approval,
        in `DRAFT`, `IN_REVIEW`, or `CHANGES_REQUESTED`. Absorbing across
        different customers, or with neither contract flagged as
        package-negotiated, is rejected with
        `ERR_COMBINATION_CRITERIA_NOT_MET` (HTTP 422)".

        Design: Corner/validations/combination_criteria_violations_rejected
        """
        u1 = create_customer(legal_name="U1 Co", external_ref="U1")
        u2 = create_customer(legal_name="U2 Co", external_ref="U2")
        c1 = create_contract(u1["id"], contract_ref="CC-1", signed_date="2026-05-10",
                             package_negotiated_flag=True)
        c2 = create_contract(u2["id"], contract_ref="CC-2", signed_date="2026-05-12",
                             fixed_consideration_cents=50000)
        resp = api.absorb_contract(c1["id"], {"absorbed_contract_id": c2["id"]}, manager_headers)
        validate_error(resp, ApiErrorId.ERR_COMBINATION_CRITERIA_NOT_MET, 422)

    def test_package_flag_is_or_over_the_pair(self, api, manager_headers):
        """PRD §3.4: "at least one of the two carries `package_negotiated_flag`
        set to true".

        Design: Corner/validations/combination_criteria_violations_rejected
        """
        u1 = create_customer(legal_name="U1 Co", external_ref="U1B")
        c1 = create_contract(u1["id"], contract_ref="CC-1B", signed_date="2026-05-10",
                             package_negotiated_flag=True)
        c3 = create_contract(u1["id"], contract_ref="CC-3", signed_date="2026-05-12",
                             fixed_consideration_cents=70000, package_negotiated_flag=False)
        # C3 has no flag, but the OR criterion is satisfied by C1.
        survivor = validate_success(
            api.absorb_contract(c3["id"], {"absorbed_contract_id": c1["id"]}, manager_headers)
        )
        assert survivor["fixed_consideration_cents"] == 170000
        assert get_contract(c1["id"])["status"] == "ABSORBED"
