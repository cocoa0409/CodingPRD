"""Branching state machines with divergent side-effect sets: a Job forking from
ESTIMATED to LOST (vs CONTRACTED), and a ChangeOrder forking from APPROVED to
VOIDED (vs APPLIED).

Queue A: non_linear_state_machine.
"""
from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
    setup_estimated_job, setup_contracted_job, setup_approved_change_order,
)

FA = TEST_USERS["field_adjuster_headers"]
PM = TEST_USERS["production_manager_headers"]
EST = TEST_USERS["estimator_headers"]


class TestJobBranchLost:
    def test_lose_estimated_job_sets_lost_status_and_reason(self, api):
        """PRD §3.1: "At any point before a contract is bound — that is, while
        the job is in `LEAD`, `INSPECTED`, or `ESTIMATED` — a `FieldAdjuster`
        may abandon the lead, moving the job to the terminal `LOST` status and
        recording the supplied `lost_reason`."

        Design: Difficulty/non_linear_state_machine/job_branch_completed_vs_lost
        """
        job_id, _ = setup_estimated_job()
        data = validate_success(api.lose_job(
            job_id, {"lost_reason": "homeowner went with another bidder"}, FA))
        assert data["status"] == "LOST"
        assert data["lost_reason"] == "homeowner went with another bidder"

    def test_lost_branch_leaves_ledger_untouched(self, api):
        """PRD §2.6: "The anchor is `contract_value_cents`: it is 0 until the
        job is contracted, then it equals the bound estimate's final total plus
        the signed sum of every applied change order's delta."

        Design: Difficulty/non_linear_state_machine/job_branch_completed_vs_lost
        """
        job_id, _ = setup_estimated_job()
        validate_success(api.lose_job(job_id, {"lost_reason": "lost it"}, FA))
        job = get_success_data(api.get_job(job_id, FA))
        # LOST is a pre-contract terminal: contract value never set, no bound estimate.
        assert job["contract_value_cents"] == 0
        assert job["bound_estimate_id"] in (None, "")


class TestChangeOrderBranchVoided:
    def test_void_approved_change_order_sets_voided_status(self, api):
        """PRD §3.8: "A still-`PROPOSED` or `APPROVED` change order may instead
        be voided by a `ProductionManager`, moving it to the terminal `VOIDED`;
        voiding has no precondition beyond the source state."

        Design: Difficulty/non_linear_state_machine/change_order_branch_applied_vs_voided
        """
        job_id, _ = setup_contracted_job()  # contract 110000
        co = setup_approved_change_order(job_id, delta_cents=50_000)
        data = validate_success(api.void_change_order(co["id"], PM))
        assert data["status"] == "VOIDED"

    def test_voided_change_order_does_not_mutate_contract_value(self, api):
        """PRD §3.8: "First, the job's `contract_value_cents` increases by the
        `delta_cents` (the signed amount, so a negative delta reduces it)."

        Design: Difficulty/non_linear_state_machine/change_order_branch_applied_vs_voided
        """
        job_id, _ = setup_contracted_job()  # contract 110000
        co = setup_approved_change_order(job_id, delta_cents=50_000)
        validate_success(api.void_change_order(co["id"], PM))
        job = get_success_data(api.get_job(job_id, PM))
        # Voiding (vs applying) never touches the ledger: contract stays 110000.
        assert job["contract_value_cents"] == 110000
