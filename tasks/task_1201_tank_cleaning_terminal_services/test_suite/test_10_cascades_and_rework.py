"""Cross-entity cascades and the cyclic rework loop (PRD §3.1, §3.6, §3.7)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_entry_permit_payload,
    new_ctx, create_job, schedule_job, activate_window_and_take_oos,
    setup_ctx_entry_in_progress, setup_ctx_gas_free_certified,
    setup_ctx_inspection_accepted,
    add_permit, add_inspector, create_inspection, issue_certificate,
    record_sludge, request_gas_free, begin_entry, complete_entry,
    run_inspection, contractor_headers, inspector_headers, get_job,
)

OPERATOR = TEST_USERS["operator_headers"]
CHEMIST = TEST_USERS["chemist_headers"]
EHS = TEST_USERS["ehs_headers"]
EHS2 = TEST_USERS["ehs2_headers"]

MINOR_FINDING = {"severity": "MINOR", "description": "coating blister",
                 "requires_repair": False}


class TestCertificateRevocationCascade:
    def test_revoke_cascades_permit_pause_inspection_depth3(self, api):
        """PRD §3.6: "When a `MarineChemist` revokes a `VALID` certificate — or the clock sweep expires one — every entry permit anchored to that certificate in `ISSUED` or `ACTIVE` moves to `SUSPENDED`. If the job then holds at least one suspended permit and no permit at all in `ISSUED` or `ACTIVE`, and the job stands in `GAS_FREE_CERTIFIED`, `ENTRY_IN_PROGRESS`, or `ENTRY_COMPLETE`, the job moves to `PAUSED`, recording in `paused_from` the status it held and in `pause_reason` the cause — `CERT_REVOKED` or `CERT_EXPIRED` for these cascades, with `MANUAL` rounding out the field's declared values. Whenever a job lands in `PAUSED`, all of its `SCHEDULED` inspections are cancelled."

        Design: Difficulty/transitive_cascade/cert_revoke_cascade_depth3
        """
        ctx = setup_ctx_entry_in_progress()
        add_inspector(ctx)
        inspection = create_inspection(ctx)  # SCHEDULED on the in-entry job
        cert = ctx["cert"]
        permit = ctx["permit"]

        revoked = validate_success(api.revoke_certificate(cert["id"], CHEMIST), 200)
        assert revoked["status"] == "REVOKED"

        permit_after = validate_success(
            api.get_entry_permit(permit["id"], OPERATOR), 200)
        assert permit_after["status"] == "SUSPENDED"

        job = get_job(ctx)
        assert job["status"] == "PAUSED"
        assert job["paused_from"] == "ENTRY_IN_PROGRESS"
        assert job["pause_reason"] == "CERT_REVOKED"

        inspection_after = validate_success(
            api.get_inspection(inspection["id"], OPERATOR), 200)
        assert inspection_after["status"] == "CANCELLED"

    def test_revoke_without_issued_permits_reverts_job_to_gas_free_pending(self, api):
        """PRD §3.6: "If instead the job held no `ISSUED` or `ACTIVE` permits at all and stood in `GAS_FREE_CERTIFIED`, it reverts to `GAS_FREE_PENDING` and must be re-certified; permits still `REQUESTED` that reference the dead certificate remain `REQUESTED` but can never issue against it."

        Design: Difficulty/transitive_cascade/cert_revoke_cascade_depth3
        """
        ctx = setup_ctx_gas_free_certified()
        permit = add_permit(ctx, issue=False)  # REQUESTED only
        validate_success(api.revoke_certificate(ctx["cert"]["id"], CHEMIST), 200)

        assert get_job(ctx)["status"] == "GAS_FREE_PENDING"
        permit_after = validate_success(
            api.get_entry_permit(permit["id"], OPERATOR), 200)
        assert permit_after["status"] == "REQUESTED"


class TestReworkCycle:
    def test_full_rework_cycle_returns_to_inspection_accepted(self, api):
        """PRD §3.7: "Ordering rework moves the job `INSPECTION_ACCEPTED` to `REWORK_CLEANING`, supersedes every `VALID` gas-free certificate of the job — the atmosphere is invalidated by the rework — and voids every permit in `REQUESTED`, `ISSUED`, or `SUSPENDED`. The job then loops back through sludge removal, gas-free certification, entry, and inspection exactly as on its first pass."

        Design: Difficulty/non_linear_state_machine/cleaning_job_rework_cycle
        """
        ctx = setup_ctx_inspection_accepted(findings=[MINOR_FINDING])
        cert1 = ctx["cert"]
        v_first_accept = get_job(ctx)["version"]

        reworked = validate_success(api.order_rework(ctx["job"]["id"], OPERATOR), 200)
        assert reworked["status"] == "REWORK_CLEANING"

        # Loop edge: REWORK_CLEANING -> SLUDGE_REMOVED via the same endpoint.
        job = record_sludge(ctx, 0)
        assert job["status"] == "SLUDGE_REMOVED"
        request_gas_free(ctx)
        issue_certificate(ctx)
        permit2 = add_permit(ctx, issue=True, activate=True,
                             issue_headers=EHS2, max_entrants=2)
        begin_entry(ctx)
        complete_entry(ctx)
        assert validate_success(
            api.get_entry_permit(permit2["id"], OPERATOR), 200)["status"] == "CLOSED"

        create_inspection(ctx, "2026-05-04T00:00:00Z", "2026-05-04T08:00:00Z")
        inspection2 = run_inspection(ctx, accept=True)
        assert inspection2["status"] == "ACCEPTED"

        job = get_job(ctx)
        assert job["status"] == "INSPECTION_ACCEPTED"
        assert job["version"] > v_first_accept
        cert1_after = validate_success(
            api.get_gas_free_certificate(cert1["id"], OPERATOR), 200)
        assert cert1_after["status"] == "SUPERSEDED"

    def test_order_rework_supersedes_cert_and_voids_requested_permits(self, api):
        """PRD §3.7: "Ordering rework moves the job `INSPECTION_ACCEPTED` to `REWORK_CLEANING`, supersedes every `VALID` gas-free certificate of the job — the atmosphere is invalidated by the rework — and voids every permit in `REQUESTED`, `ISSUED`, or `SUSPENDED`."

        Design: Difficulty/non_linear_state_machine/cleaning_job_rework_cycle
        """
        ctx = setup_ctx_inspection_accepted(findings=[MINOR_FINDING])
        cert1 = ctx["cert"]
        # A fresh permit request referencing the still-VALID first certificate.
        spare = validate_success(api.create_entry_permit(
            create_entry_permit_payload(ctx["job"]["id"], cert1["id"],
                                        max_entrants=2),
            contractor_headers(ctx)), 201)

        reworked = validate_success(api.order_rework(ctx["job"]["id"], OPERATOR), 200)
        assert reworked["status"] == "REWORK_CLEANING"

        cert1_after = validate_success(
            api.get_gas_free_certificate(cert1["id"], OPERATOR), 200)
        assert cert1_after["status"] == "SUPERSEDED"
        spare_after = validate_success(
            api.get_entry_permit(spare["id"], OPERATOR), 200)
        assert spare_after["status"] == "VOIDED"


class TestTankStatusBubbleUp:
    def test_take_out_of_service_then_cancel_restores_tank(self, api):
        """PRD §3.1: "its `status` never changes through a direct write: it moves to `OUT_OF_SERVICE` only as a side effect of a cleaning job taking the tank out of service, and returns to `IN_SERVICE` when that job returns the tank to service or is cancelled."
        PRD §3.8: "From `TANK_OOS` the tank returns to `IN_SERVICE` with its `version` advanced by one, and the linked window is cancelled."

        Design: Corner/state_machines/tank_status_bubble_up_from_job
        """
        ctx = new_ctx()
        create_job(ctx, heel_volume_liters_sounding=100,
                   base_service_fee_cents=1000)
        schedule_job(ctx)
        activate_window_and_take_oos(ctx)

        tank = validate_success(api.get_tank(ctx["tank"]["id"], OPERATOR), 200)
        assert tank["status"] == "OUT_OF_SERVICE"

        cancelled = validate_success(api.cancel_job(ctx["job"]["id"], OPERATOR), 200)
        assert cancelled["status"] == "CANCELLED"
        tank = validate_success(api.get_tank(ctx["tank"]["id"], OPERATOR), 200)
        assert tank["status"] == "IN_SERVICE"
        window = validate_success(
            api.get_service_window(ctx["window"]["id"], OPERATOR), 200)
        assert window["status"] == "CANCELLED"
