"""State-machine transitions: invalid transitions, auto-advance, completion split."""
from test_helpers import (
    get_success_data, validate_error, ApiErrorId,
    create_client, create_ready_for_review_close,
    create_active_client, setup_scoped_catchup,
    create_ar_invoice, dispute_ar_invoice,
    api_client, TEST_USERS,
)

CFO = TEST_USERS["cfo_headers"]
BK = TEST_USERS["bookkeeper_headers"]


class TestInvalidTransitions:
    def test_schedule_kickoff_twice_rejected(self, api):
        """PRD §3.1: "scheduling the kickoff — a `CFO` action permitted only while
        `onboarding_status` is `LEAD` — advances it to `KICKOFF_SCHEDULED`."
        PRD §3.1: "both onboarding actions and engagement actions, when attempted
        from a state the transition is not defined for, are rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/schedule_kickoff_from_already_scheduled_invalid_state
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        get_success_data(api.schedule_kickoff(cid, CFO))
        resp = api.schedule_kickoff(cid, CFO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_start_draft_catchup_rejected(self, api):
        """PRD §3.3: "A `Bookkeeper` then starts the work, moving `SCOPED →
        IN_PROGRESS`"
        PRD §3.3: "Any of these project transitions attempted from a state where it
        is not defined is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/catchup_invalid_from_draft_to_start_invalid_state
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        cp = get_success_data(api.create_catchup_project(
            cid, {"months_behind": 2, "quoted_fee_cents": 200000}, CFO))
        resp = api.start_catchup_project(cp["id"], BK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_finalize_before_review_approved_rejected(self, api):
        """PRD §3.4: "Finalizing the close is a `CFO` action permitted only when
        `status` is `READY_FOR_REVIEW` and `review_status` is `APPROVED`"

        Design: Corner/state_machines/finalize_close_before_review_approved_invalid_state
        """
        # READY_FOR_REVIEW with review_status UNDER_REVIEW (review not yet approved).
        _, close_id, _ = create_ready_for_review_close(period_month=2, txn_count=20)
        resp = api.finalize_close(close_id, CFO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_close_task_invalid_to_status_rejected(self, api):
        """PRD §3.4: "A `to_status` that is not one of the five `CloseTask`
        statuses is rejected with `ERR_INVALID_TASK_STATUS`."

        Design: Corner/state_machines/close_task_invalid_to_status_422
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        close = get_success_data(api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 5, "txn_count": 10}, BK))
        task = get_success_data(api.create_close_task(
            close["id"], {"name": "X", "weight": 1}, BK))
        resp = api.transition_close_task(task["id"], {"to_status": "SHIPPED"}, BK)
        validate_error(resp, ApiErrorId.ERR_INVALID_TASK_STATUS.value)

    def test_offboarded_client_cannot_be_paused(self, api):
        """PRD §3.1: "A `CFO` may pause an `ACTIVE` engagement, moving it to
        `PAUSED`"
        PRD §3.1: "both onboarding actions and engagement actions, when attempted
        from a state the transition is not defined for, are rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/terminal_offboarded_blocks_further_engagement_transitions
        """
        client = create_active_client(retainer_tier="GROWTH")
        cid = client["id"]
        get_success_data(api.offboard(cid, CFO))
        resp = api.pause_engagement(cid, CFO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestValidTransitions:
    def test_close_auto_advances_to_ready_for_review(self, api):
        """PRD §3.4: "Once the final `completion_pct` reaches exactly 100 — meaning
        every task is `DONE` or `WAIVED` — an `IN_PROGRESS` close advances
        `IN_PROGRESS → READY_FOR_REVIEW` and, on the parallel review axis, its
        `review_status` moves to `UNDER_REVIEW`."

        Design: Corner/state_machines/close_auto_advances_to_ready_for_review_on_full_completion
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        close = get_success_data(api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 3, "txn_count": 15}, BK))
        task = get_success_data(api.create_close_task(
            close["id"], {"name": "Only", "weight": 1}, BK))
        get_success_data(api.transition_close_task(task["id"], {"to_status": "DONE"}, BK))
        after = get_success_data(api.get_monthly_close(close["id"], CFO))
        assert after["completion_pct"] == 100.00
        assert after["status"] == "READY_FOR_REVIEW"
        assert after["review_status"] == "UNDER_REVIEW"

    def test_ar_invoice_dispute_then_resolve_round_trip(self, api):
        """PRD §3.5: "From `OPEN`, a `ClientContact` may dispute the invoice (`OPEN →
        DISPUTED`) and a `Bookkeeper` may later resolve the dispute (`DISPUTED →
        OPEN`)."

        Design: Corner/state_machines/ap_bill_dispute_resolve_round_trip
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        ar = create_ar_invoice(cid, amount_cents=100000)
        dispute_ar_invoice(cid, ar["id"])
        resolved = get_success_data(api.resolve_ar_dispute(ar["id"], BK))
        assert resolved["status"] == "OPEN"


class TestCompletionVariants:
    def test_provisional_and_final_completion_diverge(self, api):
        """PRD §3.4: "`completion_pct` — the **final** figure — is the sum of the
        weights of tasks that are `DONE` or `WAIVED`, divided by the total weight,
        multiplied by 100, and rounded half up to two decimal places. The
        `provisional_completion_pct` — the **provisional** figure that drives the
        dashboard — is computed identically except that its numerator also counts
        `IN_REVIEW` tasks as complete"

        Design: Corner/state_machines/close_provisional_vs_final_completion_diverge
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        close = get_success_data(api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 4, "txn_count": 12}, BK))
        t1 = get_success_data(api.create_close_task(
            close["id"], {"name": "A", "weight": 1}, BK))
        t2 = get_success_data(api.create_close_task(
            close["id"], {"name": "B", "weight": 1}, BK))
        get_success_data(api.transition_close_task(t1["id"], {"to_status": "DONE"}, BK))
        get_success_data(api.transition_close_task(t2["id"], {"to_status": "IN_REVIEW"}, BK))
        after = get_success_data(api.get_monthly_close(close["id"], CFO))
        assert after["completion_pct"] == 50.00
        assert after["provisional_completion_pct"] == 100.00
