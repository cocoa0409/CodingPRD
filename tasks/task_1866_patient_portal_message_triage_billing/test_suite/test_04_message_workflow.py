"""Message workflow: claiming, working states, replies, completion, cosign."""
from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    message_in_review,
    nurse_pool_practice,
    patient_headers,
    provider_pool_practice,
    reply_payload,
    staff_headers,
    triage_payload,
    validate_error,
    validate_success,
)


class TestWorkflowStateGates:
    def test_complete_from_triaged_rejected(self, api):
        """PRD §3.4: "Completion acts on an `IN_REVIEW` message — any other
        status fails with `ERR_MESSAGE_INVALID_STATE` — and belongs to the
        assignee alone, with any other caller rejected as `ERR_NOT_ASSIGNEE`".

        A TRIAGED message that was never claimed cannot be completed.

        Design: Corner/state_machines/complete_from_triaged_rejected
        """
        ctx = nurse_pool_practice()
        scn = ctx["scn"]
        msg = scn.send_message(ctx["patient"], subject="S", body="B")
        scn.triage(msg["id"], ctx["nurse"], "ROUTINE", "ADMINISTRATIVE",
                   ctx["pool"]["id"])
        resp = api.complete_message(
            msg["id"], {"resolution_summary": "too early"},
            staff_headers(ctx["nurse"]))
        validate_error(resp, ApiErrorId.ERR_MESSAGE_INVALID_STATE)
        after = scn.get_message(msg["id"])
        assert after["status"] == "TRIAGED"

    def test_patient_reply_on_in_review_rejected(self, api):
        """PRD §3.4: "A patient reply on a message in any non-`RESOLVED` status
        — including `REOPENED` itself — is rejected with
        `ERR_MESSAGE_INVALID_STATE`; a reopened message exits only through
        triage."

        Design: Corner/state_machines/patient_reply_on_in_review_rejected
        """
        ctx = nurse_pool_practice()
        scn = ctx["scn"]
        msg = message_in_review(ctx, urgency="ROUTINE",
                                category="ADMINISTRATIVE",
                                assignee_key="nurse")
        resp = api.reply_message(msg["id"], reply_payload("are you there?"),
                                 patient_headers(ctx["patient"]))
        validate_error(resp, ApiErrorId.ERR_MESSAGE_INVALID_STATE)
        after = scn.get_message(msg["id"])
        assert after["status"] == "IN_REVIEW"
        assert after["reopen_count"] == 0
        nurse_after = scn.get_staff(ctx["nurse"]["id"])
        assert nurse_after["open_inbox_count"] == 1, (
            "a rejected patient reply must not change the assignee's count"
        )

    def test_closed_terminal_lockdown(self, api):
        """PRD §3.4: "A successful close lands the message in `CLOSED`, its
        terminal state."
        PRD §3.4: "A patient reply on a message in any non-`RESOLVED` status —
        including `REOPENED` itself — is rejected with
        `ERR_MESSAGE_INVALID_STATE`".
        PRD §3.3: "Triage is valid from exactly three statuses: from `RECEIVED`
        it performs the initial classification, from `TRIAGED` a re-triage
        supersedes the prior classification, overwriting `urgency`, `category`,
        and `assigned_pool_id`, and from `REOPENED` it readmits a reopened
        thread as described below; a message in any other status fails with
        `ERR_MESSAGE_INVALID_STATE`."

        Design: Corner/state_machines/closed_terminal_lockdown
        """
        ctx = nurse_pool_practice()
        scn = ctx["scn"]
        msg = message_in_review(ctx, urgency="ROUTINE",
                                category="ADMINISTRATIVE",
                                assignee_key="nurse")
        scn.complete(msg["id"], ctx["nurse"], summary="done")
        closed = scn.close(msg["id"], ctx["nurse"])
        assert closed["status"] == "CLOSED"

        resp_reply = api.reply_message(msg["id"], reply_payload("ping"),
                                       patient_headers(ctx["patient"]))
        validate_error(resp_reply, ApiErrorId.ERR_MESSAGE_INVALID_STATE)

        fresh_version = scn.get_message(msg["id"])["version"]
        resp_triage = api.triage_message(
            msg["id"],
            triage_payload("ROUTINE", "ADMINISTRATIVE", ctx["pool"]["id"],
                           fresh_version),
            staff_headers(ctx["nurse"]))
        validate_error(resp_triage, ApiErrorId.ERR_MESSAGE_INVALID_STATE)


class TestClaimingAndReplies:
    def test_staff_reply_requires_assignee(self, api):
        """PRD §3.4: "A staff reply must come from the message's assignee —
        anyone else is rejected with `ERR_NOT_ASSIGNEE` — and carries a `body`."

        Design: Corner/validations/staff_reply_requires_assignee
        """
        ctx = nurse_pool_practice()
        scn = ctx["scn"]
        other_nurse = scn.add_staff("NURSE", "Nurse Two")
        msg = message_in_review(ctx, urgency="ROUTINE",
                                category="ADMINISTRATIVE",
                                assignee_key="nurse")
        resp = api.reply_message(msg["id"], reply_payload("I will take this"),
                                 staff_headers(other_nurse))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNEE)
        after = scn.get_message(msg["id"])
        assert after.get("first_response_at") is None, (
            "a rejected reply must not stamp first_response_at"
        )

    def test_start_review_pool_role_mismatch(self, api):
        """PRD §3.4: "First, pool-kind eligibility: `NURSE_TRIAGE` pools accept
        `NURSE` staff, `FRONT_DESK` pools accept `FRONT_DESK` staff, `BILLING`
        pools accept `BILLING_SPECIALIST` staff, and `PROVIDER_INBOX` pools
        accept `PROVIDER` staff — or any staff member who is the delegate on an
        `ACTIVE` delegation grant for that pool; ineligible callers are rejected
        with `ERR_POOL_ROLE_MISMATCH`."

        A FRONT_DESK staff member holding a coverage window on a PROVIDER_INBOX
        pool is still ineligible (pool-kind check fires before coverage).

        Design: Corner/validations/start_review_pool_role_mismatch
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        front_desk = scn.add_staff("FRONT_DESK", "Front F")
        scn.add_coverage(ctx["pool"]["id"], front_desk["id"])
        msg = message_in_review(ctx, urgency="ROUTINE", category="CLINICAL",
                                assignee_key=None)
        resp = api.start_review(msg["id"], staff_headers(front_desk))
        validate_error(resp, ApiErrorId.ERR_POOL_ROLE_MISMATCH)
        after = scn.get_message(msg["id"])
        assert after["status"] == "ASSIGNED"
        assert after.get("assignee_id") is None

    def test_start_review_requires_active_coverage(self, api):
        """PRD §3.4: "Second, active coverage: the caller must either hold a
        coverage window for the message's assigned pool that covers the logical
        now, or be the delegate on an `ACTIVE` grant for that pool whose window
        covers now, else `ERR_NO_ACTIVE_COVERAGE`."

        Design: Corner/validations/start_review_requires_active_coverage
        """
        ctx = provider_pool_practice(with_coverage=False)
        scn = ctx["scn"]
        msg = message_in_review(ctx, urgency="ROUTINE", category="CLINICAL",
                                assignee_key=None)
        resp = api.start_review(msg["id"], staff_headers(ctx["provider"]))
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_COVERAGE)

        scn.add_coverage(ctx["pool"]["id"], ctx["provider"]["id"],
                         "2026-08-03T09:00:00Z", "2026-08-03T17:00:00Z")
        ok = validate_success(
            api.start_review(msg["id"], staff_headers(ctx["provider"])), 200)
        assert ok["status"] == "IN_REVIEW"
        assert ok["assignee_id"] == ctx["provider"]["id"]

    def test_immediate_visibility_after_mutation(self, api):
        """PRD §3.3: "Under `FROM_TRIAGE` the base is the latest `triaged_at`,
        so each re-triage slides the deadline forward."
        PRD §3.4: "The first staff reply stamps `first_response_at` exactly
        once; later replies leave it untouched."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        A GET issued in the same logical instant reflects the mutations: the
        triaged message shows response_due_at = 10:00 + 60 minutes, and the
        reply read-back shows first_response_at with no SLA breach.

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        ctx = nurse_pool_practice()
        scn = ctx["scn"]
        msg = scn.send_message(ctx["patient"], subject="S", body="B")
        resp_triage = api.triage_message(
            msg["id"], triage_payload("URGENT", "ADMINISTRATIVE",
                                      ctx["pool"]["id"], msg["version"]),
            staff_headers(ctx["nurse"]))
        assert resp_triage.status_code == 200
        assert resp_triage.json()["response_type"] == "object"
        assert resp_triage.json()["meta"]["api_request_id"].startswith("req_")

        after_triage = scn.get_message(msg["id"])
        assert after_triage["status"] == "TRIAGED"
        assert_same_instant(after_triage["response_due_at"],
                            "2026-08-03T11:00:00Z",
                            label="response_due_at after URGENT triage")

        scn.assign(msg["id"], ctx["nurse"], staff_id=ctx["nurse"]["id"])
        scn.start_review(msg["id"], ctx["nurse"])
        scn.reply(msg["id"], staff_headers(ctx["nurse"]), body="On it")
        after_reply = scn.get_message(msg["id"])
        assert_same_instant(after_reply["first_response_at"],
                            "2026-08-03T10:00:00Z",
                            label="first_response_at")
        assert after_reply["sla_breached"] is False


class TestCosignReturn:
    def test_cosign_return_loops_back_to_in_review(self, api):
        """PRD §3.4: "Cosign is required exactly when the message's `category`
        is `CLINICAL` and the assignee's `staff_type` is not `PROVIDER`."
        PRD §3.4: "`RETURN` sends the message back to `IN_REVIEW`, clears
        `pending_cosign_by_id`, and retains the assignee with no count change,
        since both statuses are counted."

        Design: Corner/state_machines/cosign_return_loops_back_to_in_review
        """
        ctx = provider_pool_practice(with_biller=False)
        scn = ctx["scn"]
        delegate = scn.add_staff("NURSE", "Nurse D")
        delegator = scn.add_staff("PROVIDER", "Dr P2")
        scn.add_grant(delegator, delegate["id"], ctx["pool"]["id"])
        msg = message_in_review(ctx, urgency="ROUTINE", category="CLINICAL",
                                assignee_key=None)
        scn.assign(msg["id"], ctx["nurse"], staff_id=delegate["id"])
        scn.start_review(msg["id"], delegate)
        pending = scn.complete(msg["id"], delegate, summary="draft advice")
        assert pending["status"] == "PENDING_COSIGN"
        assert pending["pending_cosign_by_id"] == delegator["id"], (
            "the cosigner must be the delegator of the ACTIVE grant linking "
            "the assignee to the pool"
        )

        returned = scn.cosign(msg["id"], delegator, "RETURN")
        assert returned["status"] == "IN_REVIEW"
        assert returned.get("pending_cosign_by_id") is None
        assert returned["assignee_id"] == delegate["id"], (
            "RETURN must retain the delegate as assignee"
        )
        delegate_after = scn.get_staff(delegate["id"])
        assert delegate_after["open_inbox_count"] == 1, (
            "both PENDING_COSIGN and IN_REVIEW are counted statuses"
        )


class TestReopenRetriageCycle:
    def _setup_resolved_then_reopened(self):
        """Administrative message resolved by the nurse, then reopened by a
        patient reply a day later."""
        ctx = nurse_pool_practice()
        scn = ctx["scn"]
        msg = message_in_review(ctx, urgency="ROUTINE",
                                category="ADMINISTRATIVE", subject="Refill",
                                assignee_key="nurse")
        first_due = scn.get_message(msg["id"])["response_due_at"]
        scn.complete(msg["id"], ctx["nurse"], summary="Refill routed")
        scn.set_clock("2026-08-04T09:00:00Z")
        reopened = scn.reply(msg["id"], patient_headers(ctx["patient"]),
                             body="still no refill")
        return ctx, msg, first_due, reopened

    def test_patient_reply_reopens_resolved_message(self, api):
        """PRD §3.4: "A patient reply means something different: on their own
        message in `RESOLVED` status, it reopens the thread, moving the message
        to `REOPENED`, incrementing `reopen_count`, retaining `resolved_by_id`
        and `resolved_at` as history, restoring one to the retained assignee's
        `open_inbox_count` with `inbox_overloaded` re-evaluated, and clearing
        `response_due_at` until the next triage."

        Design: Difficulty/non_linear_state_machine/message_resolved_reopen_retriage_cycle
        """
        ctx, msg, _first_due, reopened = self._setup_resolved_then_reopened()
        assert reopened["status"] == "REOPENED"
        assert reopened["reopen_count"] == 1
        assert reopened["assignee_id"] == ctx["nurse"]["id"], (
            "the assignee is retained across the reopen"
        )
        assert reopened.get("response_due_at") is None, (
            "reopen clears response_due_at until the next triage"
        )
        nurse_after = ctx["scn"].get_staff(ctx["nurse"]["id"])
        assert nurse_after["open_inbox_count"] == 1, (
            "the retained assignee's count is restored by one"
        )

    def test_retriage_after_reopen_moves_deadline_and_resolves(self, api):
        """PRD §3.3: "Under `FROM_TRIAGE` the base is the latest `triaged_at`,
        so each re-triage slides the deadline forward."
        PRD §3.4: "a reopened message exits only through triage."

        The message cycles RESOLVED -> REOPENED -> TRIAGED -> ASSIGNED ->
        IN_REVIEW -> RESOLVED; the re-triage at 09:00 moves the deadline from
        2026-08-03T14:00:00Z to 2026-08-04T13:00:00Z.

        Design: Difficulty/non_linear_state_machine/message_resolved_reopen_retriage_cycle
        """
        ctx, msg, first_due, _reopened = self._setup_resolved_then_reopened()
        scn = ctx["scn"]
        assert_same_instant(first_due, "2026-08-03T14:00:00Z",
                            label="first response_due_at")
        retriaged = scn.triage(msg["id"], ctx["nurse"], "ROUTINE",
                               "ADMINISTRATIVE", ctx["pool"]["id"])
        assert_same_instant(retriaged["response_due_at"],
                            "2026-08-04T13:00:00Z",
                            label="re-triage response_due_at")
        assert retriaged["response_due_at"] != first_due
        scn.assign(msg["id"], ctx["nurse"], staff_id=ctx["nurse"]["id"])
        scn.start_review(msg["id"], ctx["nurse"])
        final = scn.complete(msg["id"], ctx["nurse"], summary="Refilled")
        assert final["status"] == "RESOLVED"
