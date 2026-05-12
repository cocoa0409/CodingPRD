"""Concurrency tests where the PRD explicitly names the loser's error_id.
Covers the race scenarios called out in PRD §3.3, §3.4, §3.6, §3.8.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    AUDITOR_ID,
    PLANNER_ID,
    PLANNER_ID_ALT,
    PLANNER_ID_THIRD,
    add_two_change_orders_with_known_order,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_approved_vendor,
    create_change_order,
    create_change_order_payload,
    create_draft_contract,
    create_offered_quote,
    create_settlement_for_contract,
    create_timeline_slot_payload,
    drive_settlement_to_finalized,
    finalize_settlement,
    make_auditor_headers,
    make_planner_headers,
    run_race,
    send_for_negotiation,
    setup_project_in_planning,
    setup_project_in_settlement_with_one_finalized_and_one_terminated,
    setup_project_with_n_accepted_vendors,
    setup_project_with_one_contract_accepted,
    validate_error_is_one_of,
)


# ===========================================================================
# §3.3 -- Two planners sign the same contract simultaneously.
# ===========================================================================
class TestSignSameContractRace:

    def test_only_one_sign_succeeds(self, api):
        """PRD §3.3: "When two planners attempt to sign the same contract
        simultaneously, the contract's contract_status serializes on a
        first-writer-wins basis: exactly one sign succeeds, and the loser
        sees ERR_CONTRACT_NOT_NEGOTIATING (HTTP 409) because the contract
        has already advanced past NEGOTIATING."

        Claim: two concurrent /sign requests on the same NEGOTIATING
        contract -> exactly one 2xx, one 4xx; loser's error_id ==
        ERR_CONTRACT_NOT_NEGOTIATING.
        """
        project = setup_project_in_planning(total_budget_cents=10_000_000)
        v = create_approved_vendor(category="PHOTOGRAPHY")
        q = create_offered_quote(v, amount_cents=100_000)
        c = create_draft_contract(project["id"], v, q)
        send_for_negotiation(project["id"], c["id"])

        h1 = make_planner_headers(PLANNER_ID)
        # PRD §2.1 says ownership is enforced by string-equality of X-User-ID
        # against project.planner_user_id. Both racing requests must come
        # from the LEGITIMATE planner; the race is between two concurrent
        # invocations of the same actor. We use the same headers twice.
        results = run_race(
            lambda: api.sign_contract(project["id"], c["id"], h1),
            lambda: api.sign_contract(project["id"], c["id"], h1),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # Loser's error must be ERR_CONTRACT_NOT_NEGOTIATING.
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_CONTRACT_NOT_NEGOTIATING.value]
        )


# ===========================================================================
# §3.6 -- Two timeline-slot creations race on the same vendor.
# ===========================================================================
class TestPerVendorTimelineRace:

    def test_per_vendor_overlap_serializes(self, api):
        """PRD §3.6: "When two timeline-slot creations race on the same
        vendor's window, the per-vendor pair (project_id, vendor_id)
        serializes them: the first wins and the second is rejected with
        ERR_TIMELINE_VENDOR_OVERLAP."

        Claim: two concurrent POST /timeline-slots requests on the same
        vendor and overlapping interval -> exactly one 2xx, loser
        error_id == ERR_TIMELINE_VENDOR_OVERLAP.
        """
        project, vendors, _ = setup_project_with_n_accepted_vendors(1)
        v = vendors[0]
        h = make_planner_headers()
        # Two slots that overlap: A=[1000,3000), B=[1500,2500).
        payload_a = create_timeline_slot_payload(
            start_at=1000, end_at=3000,
            vendor_id=v["id"], setup_buffer_seconds=0,
            kind="CEREMONY", label="A",
        )
        payload_b = create_timeline_slot_payload(
            start_at=1500, end_at=2500,
            vendor_id=v["id"], setup_buffer_seconds=0,
            kind="CEREMONY", label="B",
        )
        results = run_race(
            lambda: api.create_timeline_slot(project["id"], payload_a, h),
            lambda: api.create_timeline_slot(project["id"], payload_b, h),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        # Per PRD §3.6 the loser's error_id is ERR_TIMELINE_VENDOR_OVERLAP.
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_TIMELINE_VENDOR_OVERLAP.value]
        )


# ===========================================================================
# §3.6 -- Two timeline-slot creations race for the parallel-CEREMONY cap.
# ===========================================================================
class TestParallelCeremonyCapRace:

    def test_third_concurrent_slot_loses_to_cap(self, api):
        """PRD §3.6: "When two timeline-slot creations race on the project
        as a whole and would together push the count of overlapping
        CEREMONY slots past the cap, the project's identifier serializes
        them: the first wins and the second is rejected with
        ERR_TIMELINE_PARALLEL_CAP_EXCEEDED."

        Claim: project has 1 ACCEPTED CEREMONY slot active at t=2500. Two
        concurrent requests each individually fit (count would reach 2 ==
        cap) but together would push the count to 3. Per PRD, exactly one
        succeeds and the loser sees ERR_TIMELINE_PARALLEL_CAP_EXCEEDED.
        """
        project, vendors, _ = setup_project_with_n_accepted_vendors(3)
        h = make_planner_headers()
        # Pre-create 1 overlapping CEREMONY slot. With cap = 2, each new
        # racing slot individually fits (1 + 1 = 2), but together they
        # would push the count to 3 (1 + 2 = 3) — the race condition PRD
        # §3.6 nails down.
        from test_helpers import create_timeline_slot
        create_timeline_slot(
            project["id"], start_at=1000, end_at=3000,
            vendor_id=vendors[0]["id"], kind="CEREMONY",
            setup_buffer_seconds=0, label="A",
        )
        payload_c = create_timeline_slot_payload(
            start_at=2500, end_at=2800,
            vendor_id=vendors[1]["id"], kind="CEREMONY",
            setup_buffer_seconds=0, label="C",
        )
        payload_d = create_timeline_slot_payload(
            start_at=2400, end_at=2700,
            vendor_id=vendors[2]["id"], kind="CEREMONY",
            setup_buffer_seconds=0, label="D",
        )
        results = run_race(
            lambda: api.create_timeline_slot(project["id"], payload_c, h),
            lambda: api.create_timeline_slot(project["id"], payload_d, h),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_TIMELINE_PARALLEL_CAP_EXCEEDED.value]
        )


# ===========================================================================
# §3.8 -- Auditor finalize vs Planner cancel race on a SETTLEMENT-stage
# project.
# ===========================================================================
class TestFinalizeVsCancelRace:

    def test_first_writer_wins_loser_sees_status_moved(self, api):
        """PRD §3.8: "When an auditor's finalize and a planner's cancel
        race on a project in SETTLEMENT, the project's status field
        serializes the writes on a first-writer-wins basis; exactly one
        wins, and the loser sees ERR_PROJECT_NOT_IN_SETTLEMENT (HTTP 409)
        because the project's status has already moved."

        Claim: concurrent close (auditor) AND cancel (planner) on a
        SETTLEMENT project -> exactly one 2xx; the loser's error is
        ERR_PROJECT_NOT_IN_SETTLEMENT.
        """
        project, _v, _t = (
            setup_project_in_settlement_with_one_finalized_and_one_terminated()
        )
        # close requires Auditor; cancel requires Planner. They race.
        ah = make_auditor_headers(AUDITOR_ID)
        ph = make_planner_headers(PLANNER_ID)
        results = run_race(
            lambda: api.close_project(project["id"], ah),
            lambda: api.cancel_project(project["id"], ph),
        )
        # Race outcome: at least the loser of ONE race must respond 4xx.
        # PRD says "exactly one wins". Validate.
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_PROJECT_NOT_IN_SETTLEMENT.value]
        )
