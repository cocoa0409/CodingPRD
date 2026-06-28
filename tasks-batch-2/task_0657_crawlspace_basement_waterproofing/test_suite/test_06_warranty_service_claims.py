"""Warranty transfer/void, service-visit scheduling/completion, claim lifecycle including
the reopen cycle, coverage and visit-mismatch guards, conserved open_claim_count, the
transfer ceiling, and the open-claims-block-close rule.

Covers Difficulty queue: transitive_cascade (warranty void depth-2),
non_linear_state_machine (claim resolved->reopen->in_progress cycle),
cross_entity_state_dependency (claim triage requires warranty active),
resource_temporal_overlap (service-visit min-gap buffer),
compensating_invariant (open_claim_count file-then-deny).
Covers Corner queue: warranty transfer holder/count, annual-service clock reset,
structural claim not covered, annual-with-claim-id mismatch, close blocked by open claim,
transfer-limit reached.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_homeowner_payload, create_service_visit_payload, create_claim_payload,
    create_homeowner,
    setup_warranted_job, setup_open_claim, setup_resolved_claim,
    setup_scheduled_annual_visit,
    TEST_USERS,
)

WAR = TEST_USERS["warranty_admin_headers"]


class TestWarrantyTransfer:
    def test_transfer_sets_holder_and_increments_count(self, api):
        """PRD §3.9: "A transfer sets `holder_homeowner_id` to the new holder, increments
        `transfer_count` by 1, and increments the warranty's `version`; the warranty
        momentarily passes through `TRANSFERRED` and settles back to `ACTIVE` within the
        same request".

        Design: Corner/endpoints/warranty_transfer_increments_holder_and_count
        """
        ctx = setup_warranted_job()
        ho2 = create_homeowner(credit_band="NEAR_PRIME", as_headers=WAR)
        wv = validate_success(api.get_warranty(ctx["warranty_id"], WAR), 200)["version"]

        transferred = validate_success(api.transfer_warranty(
            ctx["warranty_id"],
            {"new_holder_homeowner_id": ho2["id"], "expected_warranty_version": wv}, WAR), 200)
        assert transferred["holder_homeowner_id"] == ho2["id"]
        assert transferred["transfer_count"] == 1
        assert transferred["status"] == "ACTIVE"

    def test_transfer_beyond_ceiling_rejected(self, api):
        """PRD §3.9: "Transferring it requires the warranty to be `ACTIVE` and its
        `transfer_count` to be below the ceiling of 3 transfers; a transfer attempted once
        `transfer_count` has reached 3 is rejected with `ERR_TRANSFER_LIMIT_REACHED`
        (HTTP 422)."

        Design: Corner/cross_cutting_complexity_layers/warranty_transfer_limit_reached
        """
        ctx = setup_warranted_job()
        wid = ctx["warranty_id"]
        holders = [create_homeowner(credit_band="PRIME", as_headers=WAR) for _ in range(4)]
        wv = validate_success(api.get_warranty(wid, WAR), 200)["version"]
        for i in range(3):
            res = validate_success(api.transfer_warranty(
                wid, {"new_holder_homeowner_id": holders[i]["id"],
                      "expected_warranty_version": wv}, WAR), 200)
            wv = res["version"]
        # transfer_count is now 3
        w_after = validate_success(api.get_warranty(wid, WAR), 200)
        assert w_after["transfer_count"] == 3

        res = api.transfer_warranty(
            wid, {"new_holder_homeowner_id": holders[3]["id"],
                  "expected_warranty_version": wv}, WAR)
        validate_error(res, "ERR_TRANSFER_LIMIT_REACHED", expected_status=422)


class TestWarrantyVoidCascade:
    def test_void_cancels_scheduled_service_visit(self, api):
        """PRD §3.9: "A `WarrantyAdmin` may void an active warranty, moving it from `ACTIVE`
        to `VOID`; voiding also cancels every `SCHEDULED` service visit on that warranty,
        moving each to `CANCELLED`".

        Design: Difficulty/transitive_cascade/warranty_void_cascade_depth2
        """
        ctx = setup_scheduled_annual_visit(scheduled_for="2026-09-01T10:00:00Z")
        voided = validate_success(api.void_warranty(ctx["warranty_id"], WAR), 200)
        assert voided["status"] == "VOID"
        sv_after = validate_success(api.get_service_visit(ctx["service_visit"]["id"], WAR), 200)
        assert sv_after["status"] == "CANCELLED"


class TestAnnualService:
    def test_complete_annual_resets_service_clock(self, api):
        """PRD §3.10: "completing an `ANNUAL` visit sets the warranty's `last_service_at`
        to the completion instant and resets its `next_service_due` to the completion
        instant plus one year, resetting the annual-service clock".

        Design: Corner/endpoints/annual_service_complete_resets_service_clock
        """
        ctx = setup_scheduled_annual_visit(scheduled_for="2026-09-01T10:00:00Z")
        api.set_clock("2026-09-01T11:00:00Z", WAR)
        completed = validate_success(
            api.complete_service_visit(ctx["service_visit"]["id"], WAR), 200)
        assert completed["status"] == "COMPLETED"
        w_after = validate_success(api.get_warranty(ctx["warranty_id"], WAR), 200)
        assert w_after["next_service_due"] == "2027-09-01T11:00:00.000Z"


class TestServiceVisitGuards:
    def test_annual_with_claim_id_returns_mismatch(self, api):
        """PRD §3.10: "A `CLAIM_REPAIR` visit must carry a non-null `claim_id` whose claim
        exists and is `IN_PROGRESS` at scheduling time, and an `ANNUAL` visit must carry no
        `claim_id`; a `CLAIM_REPAIR` without an in-progress claim, or an `ANNUAL` with a
        claim attached, is rejected with `ERR_VISIT_CLAIM_MISMATCH` (HTTP 422)."

        Design: Corner/validations/visit_claim_mismatch_annual_with_claim_id
        """
        ctx = setup_open_claim(category="PUMP_FAILURE")
        # triage the claim to IN_PROGRESS so the claim is real & in-progress
        validate_success(api.triage_claim(ctx["claim"]["id"], {"accept": True}, WAR), 200)
        res = api.create_service_visit(
            ctx["warranty_id"],
            create_service_visit_payload("ANNUAL", "2026-09-01T10:00:00Z",
                                        claim_id=ctx["claim"]["id"]), WAR)
        validate_error(res, "ERR_VISIT_CLAIM_MISMATCH", expected_status=422)

    def test_second_visit_within_min_gap_rejected(self, api):
        """PRD §3.10: "a new visit must sit at least 7 calendar days from every other
        `SCHEDULED` visit on the same warranty. Each visit is treated as a point in time,
        the gap is the absolute difference between its `scheduled_for` and that of another
        scheduled visit, and so two scheduled visits within the 7-day buffer ... collide and
        the new one is rejected with `ERR_VISIT_TOO_CLOSE` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/service_visit_min_gap_buffer_overlap
        """
        ctx = setup_scheduled_annual_visit(scheduled_for="2026-09-01T10:00:00Z")
        # second ANNUAL only 3 days later -> within 7-day buffer.
        res = api.create_service_visit(
            ctx["warranty_id"],
            create_service_visit_payload("ANNUAL", "2026-09-04T10:00:00Z"), WAR)
        validate_error(res, "ERR_VISIT_TOO_CLOSE", expected_status=409)


class TestClaimCoverageAndCycle:
    def test_triage_accept_structural_not_covered(self, api):
        """PRD §3.11: "Triaging with accept true moves a claim from `OPEN` (or from
        `REOPENED`) to `IN_PROGRESS`, but only when the warranty is `ACTIVE` and the claim's
        category is one the warranty covers — and `STRUCTURAL` claims are explicitly not
        covered. A triage-accept on a category the warranty does not cover (a `STRUCTURAL`
        claim) is rejected with `ERR_CLAIM_NOT_COVERED` (HTTP 422)."

        Design: Corner/validations/claim_structural_not_covered_on_triage_accept
        """
        ctx = setup_open_claim(category="STRUCTURAL")
        res = api.triage_claim(ctx["claim"]["id"], {"accept": True}, WAR)
        validate_error(res, "ERR_CLAIM_NOT_COVERED", expected_status=422)
        claim_after = validate_success(api.get_claim(ctx["claim"]["id"], WAR), 200)
        assert claim_after["status"] == "OPEN"

    def test_triage_requires_warranty_active(self, api):
        """PRD §3.11: "Triaging with accept true moves a claim from `OPEN` (or from
        `REOPENED`) to `IN_PROGRESS`, but only when the warranty is `ACTIVE`".
        PRD §2.7: "the system evaluate whether the target resource is in a legal state for
        the requested transition, yielding `ERR_INVALID_STATE` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/claim_triage_requires_warranty_active
        """
        ctx = setup_open_claim(category="WATER_INTRUSION")
        validate_success(api.void_warranty(ctx["warranty_id"], WAR), 200)
        res = api.triage_claim(ctx["claim"]["id"], {"accept": True}, WAR)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        claim_after = validate_success(api.get_claim(ctx["claim"]["id"], WAR), 200)
        assert claim_after["status"] == "OPEN"

    def test_resolved_claim_reopen_then_triage_loop(self, api):
        """PRD §3.11: "a `Homeowner` may reopen it while the warranty is still `ACTIVE`,
        moving it from `RESOLVED` to `REOPENED`, incrementing its `reopen_count` by 1".
        PRD §3.11: "A reopened claim can be triaged back into `IN_PROGRESS`, closing the
        loop."

        Design: Difficulty/non_linear_state_machine/claim_cyclic_resolved_reopen_loop
        """
        ctx = setup_resolved_claim()
        claim_id = ctx["claim"]["id"]
        assert ctx["claim"]["status"] == "RESOLVED"

        reopened = validate_success(api.reopen_claim(claim_id, ctx["ho_headers"]), 200)
        assert reopened["status"] == "REOPENED"
        assert reopened["reopen_count"] == 1

        triaged = validate_success(api.triage_claim(claim_id, {"accept": True}, WAR), 200)
        assert triaged["status"] == "IN_PROGRESS"


class TestOpenClaimCountConserved:
    def test_file_then_deny_restores_open_claim_count(self, api):
        """PRD §3.11: "Filing creates the claim in status `OPEN`, recomputes the Job's
        `open_claim_count`, and increments the Job's `version`."
        PRD §3.11: "Triaging with accept false moves a claim from `OPEN` to `DENIED`. Either
        triage outcome recomputes the Job's `open_claim_count`".
        PRD §3.11: "the Job's `open_claim_count` is kept equal to the number of this Job's
        claims whose status is `OPEN` or `IN_PROGRESS`."

        Design: Difficulty/compensating_invariant/open_claim_count_conserved_file_then_deny
        """
        ctx = setup_warranted_job()
        filed = validate_success(api.create_claim(
            create_claim_payload(ctx["job_id"], ctx["warranty_id"], "PUMP_FAILURE"),
            ctx["ho_headers"]), 201)
        job_mid = validate_success(api.get_job(ctx["job_id"], WAR), 200)
        assert job_mid["open_claim_count"] == 1

        denied = validate_success(api.triage_claim(filed["id"], {"accept": False}, WAR), 200)
        assert denied["status"] == "DENIED"
        job_after = validate_success(api.get_job(ctx["job_id"], WAR), 200)
        assert job_after["open_claim_count"] == 0


class TestJobClose:
    def test_close_blocked_by_open_claim(self, api):
        """PRD §3.12: "Closure is permitted only when the Job has no open claims — that is,
        when its `open_claim_count` is 0; a close attempted while open claims remain is
        rejected with `ERR_OPEN_CLAIMS_BLOCK_CLOSE` (HTTP 409)".

        Design: Corner/validations/job_close_blocked_by_open_claim
        """
        ctx = setup_warranted_job()
        validate_success(api.create_claim(
            create_claim_payload(ctx["job_id"], ctx["warranty_id"], "WATER_INTRUSION"),
            ctx["ho_headers"]), 201)
        res = api.close_job(ctx["job_id"], WAR)
        validate_error(res, "ERR_OPEN_CLAIMS_BLOCK_CLOSE", expected_status=409)
        job_after = validate_success(api.get_job(ctx["job_id"], WAR), 200)
        assert job_after["lifecycle_status"] == "WARRANTED"
