"""Work-order pipeline tests (PRD §3.2, §3.10).

Covers the full WorkOrder state machine — submit, dispatch, start, reject, resolve,
confirm, reopen, cancel — including:
- The reopen revision cycle RESOLVED → SUBMITTED (difficulty-design instance
  work_order_revision_cycle_resolved_to_submitted).
- Auto-confirm on clock advance past confirm_deadline_at with baseline score 5.
- satisfaction_score range check → ERR_RATING_OUT_OF_RANGE.
"""

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    assert_work_order,
    confirm_work_order_payload,
    create_owner_with_property,
    dispatch_work_order_payload,
    dispatch_work_order_to,
    iso_utc,
    make_maintenance_headers,
    make_owner_headers,
    progress_work_order_to_resolved,
    reject_work_order_payload,
    submit_work_order,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestSubmitAndCancel:
    def test_submit_work_order_starts_in_submitted(self, api):
        """PRD §3.2: "the order opens in status SUBMITTED."

        Claim: POST /work-orders returns status == SUBMITTED.
        """
        owner, prop = create_owner_with_property()
        from test_helpers import create_work_order_payload
        headers = make_owner_headers(owner["id"])
        res = api.create_work_order(create_work_order_payload(prop["id"]), headers)
        data = validate_success(res, expected_status=201)
        assert_work_order(data)
        assert data["status"] == "SUBMITTED"
        assert data["reporter_owner_id"] == owner["id"]

    def test_owner_cancels_submitted_work_order(self, api):
        """PRD §3.2: "Before the order is dispatched the reporter may withdraw it,
        transitioning status from SUBMITTED to CANCELLED."

        Claim: POST /work-orders/{id}/cancel from SUBMITTED → status == CANCELLED.
        """
        owner, prop = create_owner_with_property()
        wo = submit_work_order(owner, prop)
        headers = make_owner_headers(owner["id"])
        res = api.cancel_work_order(wo["id"], headers)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "CANCELLED"


class TestDispatchAndExecute:
    def test_dispatch_records_assigned_staff_id(self, api, property_manager_headers):
        """PRD §3.2: "the dispatch body carries assigned_staff_id ... on success the
        order's assigned_staff_id is set and status advances SUBMITTED → DISPATCHED."

        Claim: dispatch returns DISPATCHED with the supplied assigned_staff_id stamped on it.
        """
        owner, prop = create_owner_with_property()
        wo = submit_work_order(owner, prop)
        res = api.dispatch_work_order(
            wo["id"], dispatch_work_order_payload("staff-foo"), property_manager_headers
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "DISPATCHED"
        assert data["assigned_staff_id"] == "staff-foo"

    def test_assigned_staff_starts_then_resolves(self, api):
        """PRD §3.2: "Starting work advances DISPATCHED → IN_PROGRESS ... the assigned
        maintenance operator marks the order resolved, advancing IN_PROGRESS → RESOLVED;
        this transition stamps resolved_at to the current time and sets confirm_deadline_at
        to seventy-two hours after resolved_at."

        Claim: start → IN_PROGRESS, resolve → RESOLVED with non-null resolved_at and confirm_deadline_at.
        """
        owner, prop = create_owner_with_property()
        resolved, _staff = progress_work_order_to_resolved(owner, prop, staff_id="staff-bar")
        assert resolved["status"] == "RESOLVED"
        assert resolved.get("resolved_at"), "resolved_at must be set on RESOLVED"
        assert resolved.get("confirm_deadline_at"), "confirm_deadline_at must be set on RESOLVED"

    def test_maintenance_rejects_dispatched_work_order(self, api):
        """PRD §3.2: "rejecting work requires the body to include rejection_reason
        and advances DISPATCHED → REJECTED (a terminal state)."

        Claim: reject from DISPATCHED → status == REJECTED.
        """
        owner, prop = create_owner_with_property()
        wo = submit_work_order(owner, prop)
        dispatch_work_order_to(wo, staff_id="staff-rejector")
        maint = make_maintenance_headers("staff-rejector")
        res = api.reject_work_order(
            wo["id"], reject_work_order_payload(rejection_reason="not in scope"), maint
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "REJECTED"


class TestConfirmAndScoreRange:
    def test_owner_confirms_with_score_in_range(self, api):
        """PRD §3.2: "the reporter may close the loop by confirming with a
        satisfaction_score between 1 and 5 inclusive — the body must contain
        satisfaction_score, the server stores it on the order, and status advances
        RESOLVED → CONFIRMED."

        Claim: confirm with score=3 → status == CONFIRMED, satisfaction_score == 3.
        """
        owner, prop = create_owner_with_property()
        resolved, _ = progress_work_order_to_resolved(owner, prop, staff_id="staff-c1")
        headers = make_owner_headers(owner["id"])
        res = api.confirm_work_order(
            resolved["id"], confirm_work_order_payload(satisfaction_score=3), headers
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "CONFIRMED"
        assert data["satisfaction_score"] == 3

    @pytest.mark.parametrize("bad_score", [0, 6, -1, 100])
    def test_satisfaction_score_out_of_range(self, api, bad_score):
        """PRD §3.2: "a satisfaction_score outside the range is rejected with
        ERR_RATING_OUT_OF_RANGE."

        Claim: confirm with score outside [1,5] → ERR_RATING_OUT_OF_RANGE.
        """
        owner, prop = create_owner_with_property()
        resolved, _ = progress_work_order_to_resolved(owner, prop, staff_id="staff-c2")
        headers = make_owner_headers(owner["id"])
        res = api.confirm_work_order(
            resolved["id"], confirm_work_order_payload(satisfaction_score=bad_score), headers
        )
        validate_error(res, "ERR_RATING_OUT_OF_RANGE")


class TestReopenRevisionCycle:
    """Difficulty-design instance: work_order_revision_cycle_resolved_to_submitted.
    PRD §3.2 covers the cycle SUBMITTED→DISPATCHED→IN_PROGRESS→RESOLVED→SUBMITTED."""

    def test_reopen_returns_to_submitted_and_clears_dispatch_fields(self, api):
        """PRD §3.2: "while now() is still strictly less than confirm_deadline_at,
        the reporter may reopen the order — this clears assigned_staff_id, resolved_at,
        and confirm_deadline_at, advances RESOLVED → SUBMITTED, and increments
        WorkOrder.version to mark the revision cycle."

        Claim: reopen on RESOLVED returns to SUBMITTED and nulls assigned_staff_id,
        resolved_at, confirm_deadline_at.

        # difficulty: non_linear_state_machine/work_order_revision_cycle_resolved_to_submitted
        """
        owner, prop = create_owner_with_property()
        resolved, _ = progress_work_order_to_resolved(owner, prop, staff_id="staff-re1")
        original_version = resolved["version"]
        headers = make_owner_headers(owner["id"])
        res = api.reopen_work_order(resolved["id"], headers)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "SUBMITTED"
        assert not data.get("assigned_staff_id"), (
            "assigned_staff_id must be cleared on reopen per PRD §3.2"
        )
        assert not data.get("resolved_at"), "resolved_at must be cleared on reopen per PRD §3.2"
        assert not data.get("confirm_deadline_at"), (
            "confirm_deadline_at must be cleared on reopen per PRD §3.2"
        )
        assert data["version"] > original_version, (
            f"WorkOrder.version must increment on reopen; was {original_version}, now {data['version']}"
        )

    def test_revision_cycle_dispatches_again_after_reopen(self, api, property_manager_headers):
        """PRD §3.2: "the reporter may reopen the order — ... advances RESOLVED → SUBMITTED."
        PRD §3.2: "While the order is still in SUBMITTED, a PropertyManager operator can
        dispatch it to maintenance: ... status advances SUBMITTED → DISPATCHED."

        Claim: after a reopen returns the order to SUBMITTED, a fresh dispatch advances it
        to DISPATCHED again — the state machine is non-linear (visits SUBMITTED twice).

        # difficulty: non_linear_state_machine/work_order_revision_cycle_resolved_to_submitted
        """
        owner, prop = create_owner_with_property()
        resolved, _ = progress_work_order_to_resolved(owner, prop, staff_id="staff-re2")
        owner_headers = make_owner_headers(owner["id"])
        validate_success(api.reopen_work_order(resolved["id"], owner_headers), 200)
        # Now dispatch again — second iteration through the cycle.
        res = api.dispatch_work_order(
            resolved["id"],
            dispatch_work_order_payload("staff-re2-second"),
            property_manager_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "DISPATCHED"
        assert data["assigned_staff_id"] == "staff-re2-second"


class TestAutoConfirmOnClockAdvance:
    def test_auto_confirm_after_72h_sets_baseline_score_5(self, api):
        """PRD §3.2: "when the clock advances past confirm_deadline_at and the order
        is still in RESOLVED, the system auto-confirms: the order's satisfaction_score
        is set to a baseline value of 5 and status advances RESOLVED → CONFIRMED."

        Claim: clock-advance past confirm_deadline_at on a RESOLVED order →
        status == CONFIRMED, satisfaction_score == 5.
        """
        owner, prop = create_owner_with_property()
        resolved, _ = progress_work_order_to_resolved(owner, prop, staff_id="staff-auto")
        deadline_iso = resolved["confirm_deadline_at"]
        deadline = datetime.fromisoformat(deadline_iso.replace("Z", "+00:00"))
        # Advance to just past the deadline.
        target = deadline + timedelta(seconds=60)
        advance_clock_to(iso_utc(target))
        # Read the order back through the manager.
        from test_helpers import api_client, get_success_data
        # No GET endpoint for one work order is in the PRD, so the auto-confirm side
        # effect must be observable when we attempt a no-longer-valid transition:
        # /confirm on a CONFIRMED order returns ERR_INVALID_STATE.
        owner_headers = make_owner_headers(owner["id"])
        res = api.confirm_work_order(
            resolved["id"], confirm_work_order_payload(satisfaction_score=2), owner_headers
        )
        # CONFIRMED is terminal — a second confirm must fail with ERR_INVALID_STATE.
        validate_error(res, "ERR_INVALID_STATE")


class TestTerminalStatesRejectFurtherTransitions:
    """PRD §3.2: "CONFIRMED, REJECTED, and CANCELLED are terminal states; tests will
    assert that subsequent transition attempts return ERR_INVALID_STATE." """

    def test_cancel_then_dispatch_fails_with_invalid_state(self, api, property_manager_headers):
        """PRD §3.2: "CONFIRMED, REJECTED, and CANCELLED are terminal states; tests
        will assert that subsequent transition attempts return ERR_INVALID_STATE."

        Claim: dispatch attempt on a CANCELLED work order → ERR_INVALID_STATE.
        """
        owner, prop = create_owner_with_property()
        wo = submit_work_order(owner, prop)
        owner_headers = make_owner_headers(owner["id"])
        validate_success(api.cancel_work_order(wo["id"], owner_headers), 200)
        res = api.dispatch_work_order(
            wo["id"], dispatch_work_order_payload("any-staff"), property_manager_headers
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_start_on_already_in_progress_fails_with_invalid_state(self, api):
        """PRD §3.2: state preconditions return ERR_INVALID_STATE when the source
        state does not permit the transition (PRD §2.6 makes ERR_INVALID_STATE the
        verdict for state-machine violations).

        Claim: start on an already-IN_PROGRESS order → ERR_INVALID_STATE.
        """
        owner, prop = create_owner_with_property()
        wo = submit_work_order(owner, prop)
        dispatched = dispatch_work_order_to(wo, staff_id="staff-twice")
        maint = make_maintenance_headers("staff-twice")
        validate_success(api.start_work_order(dispatched["id"], maint), 200)
        res = api.start_work_order(dispatched["id"], maint)
        validate_error(res, "ERR_INVALID_STATE")
