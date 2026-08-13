"""Batch staging, sealing, transmission acknowledgment outcomes, and the provider quality hold."""
import pytest

from test_helpers import (
    ApiErrorId,
    EDIT_CODES,
    acknowledge_batch,
    create_batch,
    create_cycle,
    create_encounter,
    create_member,
    create_program,
    create_provider,
    create_validated_encounter,
    get_scorecard_for,
    get_success_data,
    seal_batch,
    setup_basic_scenario,
    stage_encounter,
    transmit_batch,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import OPS, OPS_SEALER, STATE


class TestSealUnseal:
    def test_seal_empty_batch_returns_empty_batch(self):
        """PRD §3.5: "Sealing freezes the batch for review: from `DRAFT` only
        (`ERR_INVALID_STATE_TRANSITION` otherwise) and only with at least one staged
        encounter (`ERR_EMPTY_BATCH` otherwise), the seal snapshots
        `sealed_encounter_count` and `sealed_total_paid_cents` from the live counters and
        records the sealer's `X-User-ID` in `sealed_by_user_id`, moving the batch
        `DRAFT → SEALED`."

        Design: Corner/state_machines/seal_empty_batch_returns_empty_batch
        """
        scenario = setup_basic_scenario(program_name="P-SM5")
        batch = create_batch(scenario["cycle"]["id"])
        resp = api_client.seal_batch(batch["id"], OPS_SEALER)
        validate_error(resp, ApiErrorId.ERR_EMPTY_BATCH)
        after = get_success_data(api_client.get_batch(batch["id"], OPS))
        assert after["status"] == "DRAFT"
        assert after["sealed_encounter_count"] is None

    def test_unseal_reverts_seal_and_clears_snapshot(self):
        """PRD §3.5: "Unsealing reverses the snapshot — from `SEALED` back to `DRAFT`,
        clearing `sealed_encounter_count`, `sealed_total_paid_cents`, and
        `sealed_by_user_id` to null — while the staged encounters remain `STAGED` and the
        live counters keep tracking."

        Design: Corner/state_machines/unseal_reverts_seal_and_clears_snapshot
        """
        scenario = setup_basic_scenario(program_name="P-SM6")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        e1 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E1", paid_amount_cents=10000)
        e2 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E2", service_from_date="2026-08-11",
                                        service_to_date="2026-08-11", paid_amount_cents=4000,
                                        lines=[{"line_number": 1, "procedure_code": "99212", "units": 1,
                                                "billed_amount_cents": 4000, "paid_amount_cents": 4000}])
        batch = create_batch(cycle["id"])
        batch = stage_encounter(batch, e1["id"])
        sealed = seal_batch(batch)
        assert sealed["sealed_encounter_count"] == 1
        assert sealed["sealed_total_paid_cents"] == 10000

        unsealed = validate_success(api_client.unseal_batch(sealed["id"], OPS))
        assert unsealed["status"] == "DRAFT"
        assert unsealed["sealed_encounter_count"] is None
        assert unsealed["sealed_total_paid_cents"] is None
        assert unsealed["sealed_by_user_id"] is None

        e1_after = get_success_data(api_client.get_encounter(e1["id"], OPS))
        assert e1_after["status"] == "STAGED", "staged encounters remain STAGED through unseal"

        reloaded = get_success_data(api_client.get_batch(batch["id"], OPS))
        staged = get_success_data(api_client.add_encounter_to_batch(
            reloaded["id"], {"encounter_id": e2["id"], "expected_batch_version": reloaded["version"]}, OPS))
        assert staged["encounter_count"] == 2


class TestStagingGates:
    def test_add_received_encounter_returns_not_stageable(self):
        """PRD §3.5: "The encounter must be `VALIDATED` with a null `batch_id`,
        otherwise `ERR_ENCOUNTER_NOT_STAGEABLE`."

        Design: Corner/validations/add_received_encounter_returns_not_stageable
        """
        scenario = setup_basic_scenario(program_name="P-V9")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        encounter = create_encounter(program["id"], member["id"], provider["id"], encounter_ref="E1")
        assert encounter["status"] == "RECEIVED"
        batch = create_batch(cycle["id"])
        resp = api_client.add_encounter_to_batch(
            batch["id"], {"encounter_id": encounter["id"], "expected_batch_version": batch["version"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_ENCOUNTER_NOT_STAGEABLE)

    def test_add_encounter_to_batch_of_different_cycle_returns_cycle_mismatch(self):
        """PRD §3.5: "Finally the encounter's `attributed_cycle_id` must equal the
        batch's `cycle_id`, otherwise `ERR_CYCLE_MISMATCH`."

        Design: Corner/validations/add_encounter_to_batch_of_different_cycle_returns_cycle_mismatch
        """
        program = create_program(name="P-V8")
        aug = create_cycle(program["id"])
        sep = create_cycle(program["id"], label="2026-09",
                           window_start_at="2026-09-01T00:00:00Z",
                           window_end_at="2026-10-01T00:00:00Z",
                           submission_deadline_at="2026-10-15T00:00:00Z")
        member = create_member(program["id"])
        provider = create_provider(program["id"])
        e1 = create_validated_encounter(program["id"], aug["id"], member["id"], provider["id"],
                                        encounter_ref="E1")
        batch = create_batch(sep["id"])
        resp = api_client.add_encounter_to_batch(
            batch["id"], {"encounter_id": e1["id"], "expected_batch_version": batch["version"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_CYCLE_MISMATCH)
        after_batch = get_success_data(api_client.get_batch(batch["id"], OPS))
        assert after_batch["encounter_count"] == 0
        after_e1 = get_success_data(api_client.get_encounter(e1["id"], OPS))
        assert after_e1["status"] == "VALIDATED"

    def test_encounter_staging_gated_by_provider_scorecard_tier(self):
        """PRD §3.5: "The provider quality gate follows: if the scorecard for the
        encounter's provider and attributed cycle is tier `RED` and that scorecard's
        status is not `ACKNOWLEDGED`, staging is held with `ERR_PROVIDER_QUALITY_HOLD`."
        PRD §3.4: "The `tier` is `RED` when the error rate reaches or exceeds the
        program's `provider_red_threshold` (0.05 by default), `YELLOW` when it reaches or
        exceeds `provider_yellow_threshold` (0.02 by default) without reaching the red
        line, and `GREEN` otherwise; both comparisons are inclusive at the boundary."

        Design: Difficulty/cross_entity_state_dependency/encounter_staging_gated_by_provider_scorecard_tier
        """
        scenario = setup_basic_scenario(program_name="P-X2")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        e1 = create_encounter(program["id"], member["id"], provider["id"], encounter_ref="E1",
                              diagnosis_codes=["9XX"])
        rejected = get_success_data(api_client.validate_encounter(e1["id"], OPS))
        assert rejected["status"] == "REJECTED", "Setup failed: e1 must be REJECTED"
        e2 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E2", service_from_date="2026-08-11",
                                        service_to_date="2026-08-11")

        scorecard = get_scorecard_for(provider["id"], cycle["id"])
        assert scorecard["tier"] == "RED", "1 FATAL in 1 run => error_rate 1.0 >= 0.05"

        batch = create_batch(cycle["id"])
        resp = api_client.add_encounter_to_batch(
            batch["id"], {"encounter_id": e2["id"], "expected_batch_version": batch["version"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_QUALITY_HOLD)
        e2_after = get_success_data(api_client.get_encounter(e2["id"], OPS))
        assert e2_after["status"] == "VALIDATED"
        batch_after = get_success_data(api_client.get_batch(batch["id"], OPS))
        assert batch_after["encounter_count"] == 0

    def test_remediation_acknowledgment_lifts_red_staging_hold(self):
        """PRD §3.6: "The scorecard moves `OPEN → ACKNOWLEDGED`, the staging hold for
        that provider-and-cycle pair lifts, and the tier itself remains `RED` as the
        historical measurement of the cycle."

        Design: Difficulty/cross_entity_state_dependency/encounter_staging_gated_by_provider_scorecard_tier
        """
        scenario = setup_basic_scenario(program_name="P-X2B")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        e1 = create_encounter(program["id"], member["id"], provider["id"], encounter_ref="E1",
                              diagnosis_codes=["9XX"])
        get_success_data(api_client.validate_encounter(e1["id"], OPS))
        e2 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E2", service_from_date="2026-08-11",
                                        service_to_date="2026-08-11")
        scorecard = get_scorecard_for(provider["id"], cycle["id"])
        assert scorecard["tier"] == "RED"
        acked = validate_success(api_client.acknowledge_scorecard_remediation(scorecard["id"], OPS))
        assert acked["status"] == "ACKNOWLEDGED"
        assert acked["tier"] == "RED", "tier remains RED as the historical measurement"

        batch = create_batch(cycle["id"])
        staged = get_success_data(api_client.add_encounter_to_batch(
            batch["id"], {"encounter_id": e2["id"], "expected_batch_version": batch["version"]}, OPS))
        assert staged["encounter_count"] == 1
        e2_after = get_success_data(api_client.get_encounter(e2["id"], OPS))
        assert e2_after["status"] == "STAGED"


class TestOccBatchStaging:
    def test_occ_batch_add_stale_version_rejected_then_current_succeeds(self):
        """PRD §2.7: "Staging an encounter into a batch requires the request to carry
        `expected_batch_version`, holding the batch `version` the client last observed.
        If the batch's current `version` has advanced beyond that observed value —
        because any other mutation has touched the batch since — the staging request is
        rejected with `ERR_STALE_VERSION` (HTTP 412), and neither the encounter nor the
        batch changes."

        Design: Corner/cross_cutting_complexity_layers/occ_batch_add_stale_version_rejected_then_current_succeeds
        """
        scenario = setup_basic_scenario(program_name="P-OCC1")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        e1 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E1", paid_amount_cents=10000)
        e2 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E2", service_from_date="2026-08-11",
                                        service_to_date="2026-08-11", paid_amount_cents=4000,
                                        lines=[{"line_number": 1, "procedure_code": "99212", "units": 1,
                                                "billed_amount_cents": 4000, "paid_amount_cents": 4000}])
        batch = create_batch(cycle["id"])
        version_at_create = batch["version"]
        batch = stage_encounter(batch, e1["id"])
        assert batch["version"] == version_at_create + 1

        resp = api_client.add_encounter_to_batch(
            batch["id"], {"encounter_id": e2["id"], "expected_batch_version": version_at_create}, OPS)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        retried = get_success_data(api_client.add_encounter_to_batch(
            batch["id"], {"encounter_id": e2["id"], "expected_batch_version": batch["version"]}, OPS))
        assert retried["version"] == version_at_create + 2
        assert retried["encounter_count"] == 2
        e2_after = get_success_data(api_client.get_encounter(e2["id"], OPS))
        assert e2_after["status"] == "STAGED"


class TestAcknowledgment:
    def test_acknowledge_incomplete_coverage_returns_error(self):
        """PRD §3.6: "The outcome set must cover each submitted encounter exactly once,
        with no missing entries and no extras, and every denial must carry a well-formed
        code; any gap is rejected with `ERR_ACK_INCOMPLETE`."

        Design: Corner/state_machines/acknowledge_incomplete_coverage_returns_error
        """
        scenario = setup_basic_scenario(program_name="P-SM7")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        e1 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E1", paid_amount_cents=10000)
        e2 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E2", service_from_date="2026-08-11",
                                        service_to_date="2026-08-11", paid_amount_cents=4000,
                                        lines=[{"line_number": 1, "procedure_code": "99212", "units": 1,
                                                "billed_amount_cents": 4000, "paid_amount_cents": 4000}])
        batch = create_batch(cycle["id"])
        batch = stage_encounter(batch, e1["id"])
        batch = stage_encounter(batch, e2["id"])
        batch = seal_batch(batch)
        batch = transmit_batch(batch)

        resp = api_client.acknowledge_batch(
            batch["id"], {"outcomes": [{"encounter_id": e1["id"], "outcome": "ACCEPTED"}]}, STATE)
        validate_error(resp, ApiErrorId.ERR_ACK_INCOMPLETE)

        after_batch = get_success_data(api_client.get_batch(batch["id"], STATE))
        assert after_batch["status"] == "TRANSMITTED"
        for eid in (e1["id"], e2["id"]):
            enc = get_success_data(api_client.get_encounter(eid, OPS))
            assert enc["status"] == "SUBMITTED", "no encounter may change state on a rejected acknowledgment"

    def test_acknowledge_all_denied_auto_returns_batch_to_draft(self):
        """PRD §3.6: "When every entry is `DENIED`, the batch moves `TRANSMITTED →
        REJECTED_BATCH` and then, within the same request, immediately back to `DRAFT`:
        the per-encounter denial side effects do not fire on a whole-file rejection;
        instead every staged encounter returns to `VALIDATED` with its `batch_id`
        cleared for rework, the seal snapshots and `sealed_by_user_id` are cleared, and
        the batch's `version` increments."

        Design: Corner/state_machines/acknowledge_all_denied_auto_returns_batch_to_draft
        """
        scenario = setup_basic_scenario(program_name="P-SM8")
        program, cycle, member, provider = (
            scenario["program"], scenario["cycle"], scenario["member"], scenario["provider"])
        e1 = create_validated_encounter(program["id"], cycle["id"], member["id"], provider["id"],
                                        encounter_ref="E1")
        batch = create_batch(cycle["id"])
        batch = stage_encounter(batch, e1["id"])
        batch = seal_batch(batch)
        batch = transmit_batch(batch)

        resp = api_client.acknowledge_batch(
            batch["id"],
            {"outcomes": [{"encounter_id": e1["id"], "outcome": "DENIED",
                           "edit_code": EDIT_CODES["STATE_FILE_REJECT"]}]},
            STATE)
        batch_after = validate_success(resp)
        assert batch_after["status"] == "DRAFT", "REJECTED_BATCH auto-transition executes in the same request"

        e1_after = get_success_data(api_client.get_encounter(e1["id"], OPS))
        assert e1_after["status"] == "VALIDATED"
        assert e1_after["batch_id"] is None

        _findings, fmeta = validate_paginated(api_client.list_encounter_findings(e1["id"], OPS))
        assert fmeta["total_count"] == 0, "whole-file rejection records no per-encounter denial finding"

        cycle_after = get_success_data(api_client.get_cycle(cycle["id"], STATE))
        assert cycle_after["net_accepted_encounter_count"] == 0
