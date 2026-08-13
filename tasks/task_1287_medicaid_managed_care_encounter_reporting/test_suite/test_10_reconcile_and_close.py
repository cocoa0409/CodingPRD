"""Batch reconciliation branches, cycle close preconditions, and read-your-writes
consistency of the cycle net-accepted ledger."""
import pytest

from test_helpers import (
    ApiErrorId,
    EDIT_CODES,
    acknowledge_batch,
    create_acknowledged_encounter,
    create_audit,
    create_batch,
    create_cycle,
    create_program,
    create_statement,
    create_validated_encounter,
    determine_audit,
    get_success_data,
    replace_encounter,
    seal_batch,
    set_clock,
    setup_basic_scenario,
    setup_partial_batch_with_denial,
    stage_encounter,
    transmit_batch,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import FIN, OPS, STATE


class TestPartialBatchReconcile:
    def test_batch_partial_branch_blocks_reconcile_until_denials_resolved(self):
        """PRD §3.7: "A `PARTIAL` batch may only reconcile once every one of its
        `DENIED` encounters has been resolved — each replaced or voided first — and
        reconciling with any denial outstanding is rejected with
        `ERR_BATCH_HAS_UNRESOLVED_DENIALS`."
        PRD §3.7: "The original moves to the terminal `SUPERSEDED` state and its
        `version` increments; the replacement is born in `RECEIVED` with
        `replaces_encounter_id` pointing at the original, `correction_sequence` one
        higher than the original's, and the member, provider, and submitter inherited."

        Design: Difficulty/non_linear_state_machine/batch_partial_branch_blocks_reconcile_until_denials_resolved
        """
        scenario = setup_basic_scenario(program_name="P-BRN", with_rate_schedule=True)
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        e1 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E1", paid_amount_cents=10000)
        e2 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E2", service_from_date="2026-08-11",
                                        service_to_date="2026-08-11", paid_amount_cents=12000,
                                        lines=[{"line_number": 1, "procedure_code": "99214", "units": 1,
                                                "billed_amount_cents": 12000, "paid_amount_cents": 12000}])
        e3 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E3", service_from_date="2026-08-12",
                                        service_to_date="2026-08-12", paid_amount_cents=8000,
                                        lines=[{"line_number": 1, "procedure_code": "99212", "units": 1,
                                                "billed_amount_cents": 8000, "paid_amount_cents": 8000}])
        batch = create_batch(cycle["id"])
        for enc in (e1, e2, e3):
            batch = stage_encounter(batch, enc["id"])
        batch = seal_batch(batch)
        batch = transmit_batch(batch)
        batch = acknowledge_batch(batch, [
            {"encounter_id": e1["id"], "outcome": "ACCEPTED"},
            {"encounter_id": e2["id"], "outcome": "DENIED", "edit_code": EDIT_CODES["STATE_DENIAL"]},
            {"encounter_id": e3["id"], "outcome": "ACCEPTED"},
        ])
        assert batch["status"] == "PARTIAL", "Setup failed: mixed outcome must fork to PARTIAL"

        resp = api_client.reconcile_batch(batch["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_BATCH_HAS_UNRESOLVED_DENIALS)

        replacement = replace_encounter(e2["id"], encounter_ref="E2R",
                                        service_from_date="2026-08-11", service_to_date="2026-08-11",
                                        paid_amount_cents=12000,
                                        lines=[{"line_number": 1, "procedure_code": "99214", "units": 1,
                                                "billed_amount_cents": 12000, "paid_amount_cents": 12000}])
        original = get_success_data(api_client.get_encounter(e2["id"], OPS))
        assert original["status"] == "SUPERSEDED"
        assert replacement["correction_sequence"] == 1
        assert replacement["replaces_encounter_id"] == e2["id"]

        reconciled = validate_success(api_client.reconcile_batch(batch["id"], OPS))
        assert reconciled["status"] == "RECONCILED"

        cycle_after = get_success_data(api_client.get_cycle(cycle["id"], STATE))
        assert cycle_after["net_accepted_encounter_count"] == 2
        assert cycle_after["net_accepted_paid_cents"] == 18000, "e1 10000 + e3 8000; denied e2 never contributed"

    def test_partial_reconcile_blocked_until_every_denial_resolved(self):
        """PRD §3.7: "A `PARTIAL` batch may only reconcile once every one of its
        `DENIED` encounters has been resolved — each replaced or voided first — and
        reconciling with any denial outstanding is rejected with
        `ERR_BATCH_HAS_UNRESOLVED_DENIALS`."

        Design: Difficulty/non_linear_state_machine/batch_partial_branch_blocks_reconcile_until_denials_resolved
        """
        scenario = setup_basic_scenario(program_name="P-BRN2")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        e1 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E1")
        e2 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E2", service_from_date="2026-08-11",
                                        service_to_date="2026-08-11")
        e3 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E3", service_from_date="2026-08-12",
                                        service_to_date="2026-08-12")
        batch = create_batch(cycle["id"])
        for enc in (e1, e2, e3):
            batch = stage_encounter(batch, enc["id"])
        batch = seal_batch(batch)
        batch = transmit_batch(batch)
        batch = acknowledge_batch(batch, [
            {"encounter_id": e1["id"], "outcome": "ACCEPTED"},
            {"encounter_id": e2["id"], "outcome": "DENIED", "edit_code": EDIT_CODES["STATE_DENIAL"]},
            {"encounter_id": e3["id"], "outcome": "DENIED", "edit_code": EDIT_CODES["STATE_DENIAL"]},
        ])
        assert batch["status"] == "PARTIAL", "Setup failed"

        # One of two denials resolved: still blocked.
        replace_encounter(e2["id"], encounter_ref="E2R", service_from_date="2026-08-11",
                          service_to_date="2026-08-11")
        resp = api_client.reconcile_batch(batch["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_BATCH_HAS_UNRESOLVED_DENIALS)

        # Both resolved: reconcile succeeds.
        replace_encounter(e3["id"], encounter_ref="E3R", service_from_date="2026-08-12",
                          service_to_date="2026-08-12")
        reconciled = validate_success(api_client.reconcile_batch(batch["id"], OPS))
        assert reconciled["status"] == "RECONCILED"


class TestCycleClose:
    def test_cycle_close_before_deadline_returns_not_closable(self):
        """PRD §3.9: "Four preconditions must all hold, any miss drawing
        `ERR_CYCLE_NOT_CLOSABLE`: the cycle is `OPEN`; the logical clock has moved
        strictly past the `effective_deadline_at`; no batch of the cycle sits in
        `SEALED`, `TRANSMITTED`, `ACKNOWLEDGED`, or `PARTIAL`; an audit for the cycle
        exists in `DETERMINED`; and a capitation statement for the cycle exists in
        `RECONCILED`."
        PRD §2.4: "Before any client call, the logical clock reads exactly
        2026-08-01T00:00:00Z (a fixed startup default)."

        Design: Corner/state_machines/cycle_close_before_deadline_returns_not_closable
        """
        program = create_program(name="P-SM9")
        cycle = create_cycle(program["id"])
        resp = api_client.close_cycle(cycle["id"], STATE)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_CLOSABLE)
        after = get_success_data(api_client.get_cycle(cycle["id"], STATE))
        assert after["status"] == "OPEN"

    def test_cycle_close_full_lifecycle_and_post_close_batch_rejected(self):
        """PRD §3.9: "Four preconditions must all hold, any miss drawing
        `ERR_CYCLE_NOT_CLOSABLE`: the cycle is `OPEN`; the logical clock has moved
        strictly past the `effective_deadline_at`; no batch of the cycle sits in
        `SEALED`, `TRANSMITTED`, `ACKNOWLEDGED`, or `PARTIAL`; an audit for the cycle
        exists in `DETERMINED`; and a capitation statement for the cycle exists in
        `RECONCILED`."
        PRD §3.9: "A `CLOSED` cycle is terminal; batch creation and transmission against
        it fail with `ERR_CYCLE_CLOSED`."

        Design: Corner/state_machines/cycle_close_full_lifecycle_and_post_close_batch_rejected
        """
        scenario = setup_basic_scenario(program_name="P-SM10", with_rate_schedule=True)
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        outcome = create_acknowledged_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                                encounter_ref="E1")
        reconciled_batch = validate_success(api_client.reconcile_batch(outcome["batch"]["id"], OPS))
        assert reconciled_batch["status"] == "RECONCILED"

        validate_success(api_client.compute_risk_scores(cycle["id"], FIN))
        statement = create_statement(cycle["id"])
        reconciled_stmt = validate_success(api_client.reconcile_statement(statement["id"], FIN))
        assert reconciled_stmt["final_amount_cents"] == 50000
        assert reconciled_stmt["adjustment_cents"] == 0

        audit = create_audit(cycle["id"], sample_size=10, defect_count=0)
        determined = validate_success(api_client.determine_audit(audit["id"], STATE))
        assert determined["determination"] == "PASS"

        set_clock("2026-09-16T00:00:00Z")
        closed = validate_success(api_client.close_cycle(cycle["id"], STATE))
        assert closed["status"] == "CLOSED"

        resp = api_client.create_batch({"cycle_id": cycle["id"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_CYCLE_CLOSED)


class TestImmediateConsistency:
    def test_immediate_visibility_of_ack_side_effects(self):
        """PRD §3.6: "When every entry is `ACCEPTED`, the batch moves `TRANSMITTED →
        ACKNOWLEDGED` and each encounter moves `SUBMITTED → ACKNOWLEDGED`, incrementing
        the cycle's `net_accepted_encounter_count` by one and its
        `net_accepted_paid_cents` by that encounter's `paid_amount_cents` per accepted
        leg."

        Design: Corner/consistency_model/immediate_visibility_of_ack_side_effects
        """
        scenario = setup_basic_scenario(program_name="P-CON")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        e1 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E1")
        batch = create_batch(cycle["id"])
        batch = stage_encounter(batch, e1["id"])
        batch = seal_batch(batch)
        batch = transmit_batch(batch)
        batch_after = validate_success(api_client.acknowledge_batch(
            batch["id"], {"outcomes": [{"encounter_id": e1["id"], "outcome": "ACCEPTED"}]}, STATE))
        assert batch_after["status"] == "ACKNOWLEDGED"

        # The very next reads observe the ledger and encounter state (read-your-writes).
        cycle_after = get_success_data(api_client.get_cycle(cycle["id"], STATE))
        assert cycle_after["net_accepted_encounter_count"] == 1
        assert cycle_after["net_accepted_paid_cents"] == 10000
        e1_after = get_success_data(api_client.get_encounter(e1["id"], OPS))
        assert e1_after["status"] == "ACKNOWLEDGED"
