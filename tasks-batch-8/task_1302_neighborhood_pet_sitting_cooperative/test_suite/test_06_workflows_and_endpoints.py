"""Request lifecycle branches, suspension cascades, retrieval shapes, and listing
behavior (PRD §2.3, §3.1, §3.3, §3.4, §3.5, §3.6)."""
import pytest

from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    create_sitting_request_payload, create_cancel_payload,
    make_member_headers,
    bootstrap_founders, create_applicant, create_pet, post_request, claim_request,
    accept_claim, setup_confirmed_sit, setup_completed_sit, setup_settled_sit,
    get_assignment_for_request, get_handoff_for_assignment, get_member, list_ledger,
    set_clock, file_incident, setup_dispute_in_mediation, escalate_dispute,
    resolve_incident_at_fault,
    ADMIN,
)


class TestRequestTerminalBranches:
    def test_three_way_terminal_branching(self, api):
        """PRD §3.3: "A fresh request is `OPEN` and perishable: its `expires_at` is
        set to four hours before `start_at`, and when the logical clock reaches that
        moment with no accepted claim, the request moves to `EXPIRED` on its own."
        PRD §3.4: "Cancelling a request in `OPEN` or `CLAIMED` is the owner's
        prerogative alone (`ERR_FORBIDDEN`); all `PENDING` claims are `REJECTED`,
        and if an accepted claim already existed its assignment becomes
        `CANCELLED_BY_OWNER` with the provisional hours reversed."
        PRD §3.6: "Checkout stamps `actual_end_at` with the current time, appends a
        `CHECK_OUT` entry log, moves the assignment to `COMPLETED_PENDING_REVIEW`,
        and moves the request to `COMPLETED`."

        Design: Difficulty/non_linear_state_machine/request_three_way_terminal_branching
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        r1 = post_request(f["f1"], pet, start_at="2026-09-15T12:00:00Z",
                          end_at="2026-09-15T16:00:00Z", instructions="R1 cancel branch")
        r2 = post_request(f["f1"], pet, start_at="2026-09-16T12:00:00Z",
                          end_at="2026-09-16T16:00:00Z", instructions="R2 expiry branch")
        r3 = post_request(f["f1"], pet, start_at="2026-09-17T10:00:00Z",
                          end_at="2026-09-17T14:00:00Z", instructions="R3 happy path")

        # Branch 1: owner cancel from OPEN.
        get_success_data(api.cancel_sitting_request(
            r1["id"], create_cancel_payload(cancelled_reason="Plans changed"),
            make_member_headers(f["f1"]["id"])))

        # Branch 3 setup: claim + accept before the clock moves.
        claim3 = claim_request(r3, f["f2"], message="I will cover R3")
        accept_claim(r3, claim3, f["f1"])
        asg3 = get_assignment_for_request(r3["id"])
        ho3 = get_handoff_for_assignment(asg3["id"])

        # Branch 2: advance the clock exactly to R2's expires_at (start - 4h).
        set_clock("2026-09-16T08:00:00Z")

        # Drive R3 through its sit day.
        set_clock("2026-09-17T08:30:00Z")
        get_success_data(api.confirm_handoff(ho3["id"], make_member_headers(f["f1"]["id"])))
        set_clock("2026-09-17T10:00:00Z")
        get_success_data(api.create_entry_log(
            asg3["id"], {"event_type": "CHECK_IN", "occurred_at": "2026-09-17T10:00:00Z"},
            make_member_headers(f["f2"]["id"])))
        set_clock("2026-09-17T14:00:00Z")
        get_success_data(api.checkout_assignment(asg3["id"], make_member_headers(f["f2"]["id"])))

        got_r1 = validate_success(api.get_sitting_request(r1["id"], ADMIN), 200)
        assert got_r1["status"] == "CANCELLED"
        assert got_r1["cancelled_reason"] == "Plans changed"

        got_r2 = validate_success(api.get_sitting_request(r2["id"], ADMIN), 200)
        assert got_r2["status"] == "EXPIRED"
        assert get_success_data(api.get_request_assignment(r2["id"], ADMIN)) == []

        got_r3 = validate_success(api.get_sitting_request(r3["id"], ADMIN), 200)
        assert got_r3["status"] == "COMPLETED"
        asg3_after = validate_success(api.get_assignment(asg3["id"], ADMIN), 200)
        assert asg3_after["status"] == "COMPLETED_PENDING_REVIEW"

    def test_expiry_branch_has_no_assignment(self, api):
        """PRD §3.3: "A fresh request is `OPEN` and perishable: its `expires_at` is
        set to four hours before `start_at`, and when the logical clock reaches that
        moment with no accepted claim, the request moves to `EXPIRED` on its own."

        Design: Difficulty/non_linear_state_machine/request_three_way_terminal_branching
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        r2 = post_request(f["f1"], pet, start_at="2026-09-16T12:00:00Z",
                          end_at="2026-09-16T16:00:00Z", instructions="R2 expiry branch")
        set_clock("2026-09-16T08:00:00Z")  # exactly expires_at
        got = validate_success(api.get_sitting_request(r2["id"], ADMIN), 200)
        assert got["status"] == "EXPIRED"
        assert get_success_data(api.get_request_assignment(r2["id"], ADMIN)) == []


class TestSuspensionCascade:
    def test_member_suspend_transitive_chain(self, api):
        """PRD §3.1: "Suspension cascades immediately: every `OPEN` sitting request
        the member owns is `CANCELLED` with its `cancelled_reason` recorded as
        `OWNER_SUSPENDED`; every `PENDING` claim the member has made moves to
        `WITHDRAWN`; and every `CONFIRMED` assignment touching the member is
        cancelled — `CANCELLED_BY_SITTER` when the member was the sitter,
        `CANCELLED_BY_OWNER` when they were the owner — with the sitter's
        `provisional_credit_hours` reversed in each case."

        Design: Difficulty/transitive_cascade/member_suspend_transitive_request_claim_assignment_chain
        """
        f = bootstrap_founders()
        # F2 is the sitter on F1's canonical request (CONFIRMED, provisional 4.00).
        sit = setup_confirmed_sit(founders=f)
        # F2 owns an OPEN request with a PENDING claim from F3.
        pet2 = create_pet(f["f2"], pet_name="Mochi", species="CAT",
                          routine_notes="Indoor cat, feed wet food.")
        req2 = post_request(f["f2"], pet2, start_at="2026-09-20T10:00:00Z",
                            end_at="2026-09-20T14:00:00Z", instructions="F2's own request")
        claim_f3 = claim_request(req2, f["f3"], message="F3 can cover")

        res = api.suspend_member(f["f2"]["id"], {"suspension_reason": "Repeated no-shows reported"}, ADMIN)
        suspended = validate_success(res, 200)
        assert suspended["vetting_status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "Repeated no-shows reported"

        req2_after = validate_success(api.get_sitting_request(req2["id"], ADMIN), 200)
        assert req2_after["status"] == "CANCELLED"
        assert req2_after["cancelled_reason"] == "OWNER_SUSPENDED"

        claim_after = validate_success(api.get_claim(claim_f3["id"], ADMIN), 200)
        assert claim_after["status"] == "REJECTED"

        asg_after = validate_success(api.get_assignment(sit["assignment"]["id"], ADMIN), 200)
        assert asg_after["status"] == "CANCELLED_BY_SITTER"

        f2 = get_member(f["f2"]["id"])
        assert f2["provisional_credit_hours"] == pytest.approx(0.0, abs=0.001)
        assert f2["credit_balance_hours"] == pytest.approx(10.0, abs=0.001)
        assert f2["reliability_score"] == 50

    def test_suspend_reverses_provisional_without_penalty(self, api):
        """PRD §3.1: "...and every `CONFIRMED` assignment touching the member is
        cancelled — `CANCELLED_BY_SITTER` when the member was the sitter,
        `CANCELLED_BY_OWNER` when they were the owner — with the sitter's
        `provisional_credit_hours` reversed in each case."
        PRD §3.4: "A sitter who cancels late pays for it: when fewer than 24 hours
        remain before `scheduled_start_at` — exactly 24 hours out is not late — ..."

        Design: Difficulty/transitive_cascade/member_suspend_transitive_request_claim_assignment_chain
        """
        f = bootstrap_founders()
        sit = setup_confirmed_sit(founders=f)
        assert get_member(f["f2"]["id"])["provisional_credit_hours"] == pytest.approx(4.0, abs=0.001)

        validate_success(api.suspend_member(
            f["f2"]["id"], {"suspension_reason": "Repeated no-shows reported"}, ADMIN), 200)
        f2 = get_member(f["f2"]["id"])
        assert f2["provisional_credit_hours"] == pytest.approx(0.0, abs=0.001)
        assert f2["credit_balance_hours"] == pytest.approx(10.0, abs=0.001)
        assert list_ledger(f["f2"]["id"], params={"entry_type": "CANCELLATION_PENALTY"}) == []
        asg = validate_success(api.get_assignment(sit["assignment"]["id"], ADMIN), 200)
        assert asg["status"] == "CANCELLED_BY_SITTER"


class TestRetrievalShapes:
    def test_assignment_and_handoff_reverse_get_arrays(self, api):
        """PRD §3.4: "When acceptance succeeds, a cascade fires in one motion. ...
        a new assignment is persisted in `CONFIRMED` with `scheduled_start_at` and
        `scheduled_end_at` copied from the request, the owner denormalized onto
        `owner_member_id`, and the sitter taken from the accepted claim as
        `sitter_member_id`; an access handoff is created in `PENDING`; ..."

        Design: Corner/endpoints/assignment_and_handoff_reverse_get_arrays
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        fresh = post_request(f["f1"], pet, start_at="2026-09-12T10:00:00Z",
                             end_at="2026-09-12T14:00:00Z", instructions="Fresh open request")
        assert get_success_data(api.get_request_assignment(fresh["id"], ADMIN)) == []

        sit = setup_confirmed_sit(founders=f, owner=f["f1"], pet=pet)
        assignments = get_success_data(api.get_request_assignment(sit["request"]["id"], ADMIN))
        assert len(assignments) == 1
        assert assignments[0]["sitting_request_id"] == sit["request"]["id"]
        assert assignments[0]["status"] == "CONFIRMED"

        handoffs = get_success_data(api.get_assignment_handoff(assignments[0]["id"], ADMIN))
        assert len(handoffs) == 1
        assert handoffs[0]["sitting_assignment_id"] == assignments[0]["id"]
        assert handoffs[0]["status"] == "PENDING"


class TestListings:
    def test_members_list_pagination_and_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items and defaults to 0."
        PRD §2.3: "Several collections support equality filters beyond pagination,
        each named after the field it matches: the member list filters by
        `vetting_status`; ..."

        Design: Corner/endpoints/members_list_pagination_and_envelope
        """
        bootstrap_founders()
        for i in range(1, 10):
            create_applicant(f"Applicant A{i}", f"a{i}@coop.test", f"+1555040{i}")

        data, meta = validate_paginated(api.list_members(ADMIN))
        assert len(data) == 10, f"Default page must return 10 rows, got {len(data)}"
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert meta["limit"] == 10 and meta["offset"] == 0

        data2, meta2 = validate_paginated(api.list_members(ADMIN, params={"offset": 10}))
        assert len(data2) == 2
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 12

        _, meta3 = validate_paginated(api.list_members(ADMIN, params={"vetting_status": "VETTED"}))
        assert meta3["total_count"] == 3

    def test_sitting_requests_filter_by_status_and_owner(self, api):
        """PRD §2.3: "Several collections support equality filters beyond
        pagination, each named after the field it matches: ... sitting requests
        filter by `status` and by `owner_member_id`; ..."

        Design: Corner/endpoints/sitting_requests_filter_by_status_and_owner
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        r1 = post_request(f["f1"], pet)
        get_success_data(api.cancel_sitting_request(
            r1["id"], create_cancel_payload(cancelled_reason="Cancelling R1"),
            make_member_headers(f["f1"]["id"])))
        r2 = post_request(f["f1"], pet, start_at="2026-09-12T10:00:00Z",
                          end_at="2026-09-12T14:00:00Z", instructions="R2 stays open")

        open_rows = get_success_data(api.list_sitting_requests(ADMIN, params={"status": "OPEN"}))
        assert [r["id"] for r in open_rows] == [r2["id"]]
        cancelled = get_success_data(api.list_sitting_requests(ADMIN, params={"status": "CANCELLED"}))
        assert [r["id"] for r in cancelled] == [r1["id"]]
        by_f2, meta = validate_paginated(api.list_sitting_requests(
            ADMIN, params={"owner_member_id": f["f2"]["id"]}))
        assert by_f2 == []
        assert meta["total_count"] == 0

    def test_entry_logs_filter_by_event_type(self, api):
        """PRD §2.3: "Several collections support equality filters beyond
        pagination, each named after the field it matches: ... entry logs filter by
        `event_type`; ..."
        PRD §3.5: "Entry logs are an audit trail — immutable once written, filterable
        by `event_type`, and carrying only `id` and `created_at` as system fields."

        Design: Corner/endpoints/entry_logs_filter_by_event_type
        """
        from test_helpers import setup_in_progress_sit, create_entry_log_payload
        sit = setup_in_progress_sit()
        get_success_data(api.create_entry_log(
            sit["assignment"]["id"],
            create_entry_log_payload("PET_FED", "2026-09-10T12:00:00Z", notes="Lunch served"),
            make_member_headers(sit["sitter"]["id"])))

        fed = get_success_data(api.list_entry_logs(
            sit["assignment"]["id"], ADMIN, params={"event_type": "PET_FED"}))
        assert len(fed) == 1
        assert fed[0]["occurred_at"].startswith("2026-09-10T12:00:00")
        checkins = get_success_data(api.list_entry_logs(
            sit["assignment"]["id"], ADMIN, params={"event_type": "CHECK_IN"}))
        assert len(checkins) == 1
        assert checkins[0]["occurred_at"].startswith("2026-09-10T10:00:00")
        all_logs = get_success_data(api.list_entry_logs(sit["assignment"]["id"], ADMIN))
        assert len(all_logs) == 2

    def test_credit_ledger_filter_by_entry_type(self, api):
        """PRD §2.3: "Several collections support equality filters beyond
        pagination, each named after the field it matches: ... and a member's credit
        ledger filters by `entry_type`."
        PRD §2.4: "Entries that arise from a sitting record the assignment's
        `sitting_assignment_id`; the field is null for entries unrelated to an
        assignment."

        Design: Corner/endpoints/credit_ledger_filter_by_entry_type
        """
        sit = setup_settled_sit()
        earned = get_success_data(api.list_credit_ledger(
            sit["sitter"]["id"], ADMIN, params={"entry_type": "SIT_EARNED"}))
        assert len(earned) == 1
        assert earned[0]["delta_hours"] == pytest.approx(4.0, abs=0.001)
        assert earned[0]["sitting_assignment_id"] == sit["assignment"]["id"]

        grants = get_success_data(api.list_credit_ledger(
            sit["sitter"]["id"], ADMIN, params={"entry_type": "JOINING_GRANT"}))
        assert len(grants) == 1
        assert grants[0]["delta_hours"] == pytest.approx(10.0, abs=0.001)

        all_rows = get_success_data(api.list_credit_ledger(sit["sitter"]["id"], ADMIN))
        assert len(all_rows) == 2
        assert [r["entry_type"] for r in all_rows] == ["JOINING_GRANT", "SIT_EARNED"]

    def test_removal_zeroing_preserves_ledger_replay(self, api):
        """PRD §3.1: "Removal records the supplied `removal_reason`, zeroes both
        `credit_balance_hours` and `provisional_credit_hours` — appending a
        `MEDIATION_ADJUSTMENT` ledger entry equal to the negated pre-removal balance
        when that balance was non-zero — deactivates every pet profile the member
        owns, cancels all non-terminal sitting requests, and cancels all
        non-terminal assignments with provisional reversal."
        PRD §2.4: "A member's `credit_balance_hours` is not stored as an independent
        fact: it is derived by replaying that member's ledger entries in
        chronological order — `created_at` ascending, with the entry's `id`
        ascending as the tiebreaker — and summing `delta_hours`."

        Design: Difficulty/compensating_invariant/removal_zeroing_preserves_ledger_replay
        """
        f = bootstrap_founders()
        dispute = setup_dispute_in_mediation(
            f, initiator_key="f1", respondent_key="f2", dispute_type="BEHAVIOR",
            statement="Aggressive conduct toward other members during handoffs.")
        escalate_dispute(dispute, f["f3"])
        validate_success(api.remove_member(
            f["f2"]["id"], {"removal_reason": "Escalated behavior removal"}, ADMIN), 200)

        f2 = get_member(f["f2"]["id"])
        assert f2["credit_balance_hours"] == pytest.approx(0.0, abs=0.001)
        assert f2["provisional_credit_hours"] == pytest.approx(0.0, abs=0.001)
        assert f2["vetting_status"] == "REMOVED"
        assert f2["reliability_score"] == 25  # escalation side effect retained

        rows = list_ledger(f["f2"]["id"])
        assert [r["entry_type"] for r in rows] == ["JOINING_GRANT", "MEDIATION_ADJUSTMENT"]
        assert rows[0]["delta_hours"] == pytest.approx(10.0, abs=0.001)
        assert rows[1]["delta_hours"] == pytest.approx(-10.0, abs=0.001)
        assert sum(r["delta_hours"] for r in rows) == pytest.approx(
            f2["credit_balance_hours"], abs=0.001)

    def test_removal_zeroing_adjustment_matches_grant(self, api):
        """PRD §3.1: "Removal records the supplied `removal_reason`, zeroes both
        `credit_balance_hours` and `provisional_credit_hours` — appending a
        `MEDIATION_ADJUSTMENT` ledger entry equal to the negated pre-removal balance
        when that balance was non-zero — deactivates every pet profile the member
        owns, cancels all non-terminal sitting requests, and cancels all
        non-terminal assignments with provisional reversal."

        Design: Difficulty/compensating_invariant/removal_zeroing_preserves_ledger_replay
        """
        f = bootstrap_founders()
        dispute = setup_dispute_in_mediation(
            f, initiator_key="f1", respondent_key="f2", dispute_type="BEHAVIOR",
            statement="Sustained pattern of hostile conduct toward neighbors.")
        escalate_dispute(dispute, f["f3"])
        validate_success(api.remove_member(
            f["f2"]["id"], {"removal_reason": "Escalated behavior removal"}, ADMIN), 200)
        adj = list_ledger(f["f2"]["id"], params={"entry_type": "MEDIATION_ADJUSTMENT"})
        assert len(adj) == 1
        assert adj[0]["delta_hours"] == pytest.approx(-10.0, abs=0.001)
        assert get_member(f["f2"]["id"])["credit_balance_hours"] == pytest.approx(0.0, abs=0.001)


class TestReliabilityEventwiseClamp:
    def test_eventwise_clamp_vs_recompute(self, api):
        """PRD §2.5: "Trust in the cooperative is quantified as each member's
        `reliability_score`, an integer that begins at 50 when the membership
        application is created and can never leave the range 0 to 100 — adjustments
        that would cross either boundary are clamped. The score moves event by event
        rather than being recomputed: settling a completed sit adds 2 points to the
        sitter; a sitter cancelling less than 24 hours before the scheduled start
        costs 8 points; being found at fault for an incident costs 15 points; an
        access handoff reported lost costs the sitter 10 points; and a dispute
        escalated to the removal track costs the respondent 25 points."

        Design: Difficulty/dual_variant_calc/reliability_eventwise_clamp_vs_recompute_divergence
        """
        f = bootstrap_founders()
        sit = setup_confirmed_sit(founders=f)
        # Four at-fault resolutions while the assignment is still CONFIRMED:
        # 50 -> 35 -> 20 -> 5 -> 0 under event-wise clamping.
        for desc in ("Pet escaped yard during sitting visit.",
                     "Gate left open, pet wandered off.",
                     "Wrong food served despite allergy note.",
                     "Missed evening medication dose entirely."):
            inc = file_incident(sit["assignment"]["id"], f["f1"],
                                description=desc,
                                vet_involved=(desc.startswith("Missed")))
            resolve_incident_at_fault(inc["id"], f["f2"]["id"])
        assert get_member(f["f2"]["id"])["reliability_score"] == 0

        # Complete the sit at full duration and settle: +2 lands on the clamped 0.
        set_clock("2026-09-10T08:30:00Z")
        get_success_data(api.confirm_handoff(
            sit["handoff"]["id"], make_member_headers(f["f1"]["id"])))
        set_clock("2026-09-10T10:00:00Z")
        get_success_data(api.create_entry_log(
            sit["assignment"]["id"],
            {"event_type": "CHECK_IN", "occurred_at": "2026-09-10T10:00:00Z"},
            make_member_headers(f["f2"]["id"])))
        set_clock("2026-09-10T14:00:00Z")
        get_success_data(api.checkout_assignment(
            sit["assignment"]["id"], make_member_headers(f["f2"]["id"])))
        settled = validate_success(api.settle_assignment(sit["assignment"]["id"], ADMIN), 200)
        assert settled["status"] == "SETTLED"
        assert settled["credit_hours_settled"] == pytest.approx(4.0, abs=0.001)

        f2 = get_member(f["f2"]["id"])
        # Event-wise clamp: 0 + 2 == 2; a single terminal clamp of 50-60+2 would be 0.
        assert f2["reliability_score"] == 2
        assert f2["credit_balance_hours"] == pytest.approx(14.0, abs=0.001)
        assert list_ledger(f["f2"]["id"], params={"entry_type": "INCIDENT_PENALTY"}) == []

    def test_intermediate_clamp_observable_before_settle(self, api):
        """PRD §2.5: "Trust in the cooperative is quantified as each member's
        `reliability_score`, an integer that begins at 50 when the membership
        application is created and can never leave the range 0 to 100 — adjustments
        that would cross either boundary are clamped. The score moves event by event
        rather than being recomputed: settling a completed sit adds 2 points to the
        sitter; a sitter cancelling less than 24 hours before the scheduled start
        costs 8 points; being found at fault for an incident costs 15 points; an
        access handoff reported lost costs the sitter 10 points; and a dispute
        escalated to the removal track costs the respondent 25 points."

        Design: Difficulty/dual_variant_calc/reliability_eventwise_clamp_vs_recompute_divergence
        """
        f = bootstrap_founders()
        sit = setup_confirmed_sit(founders=f)
        for desc in ("Pet escaped yard during sitting visit.",
                     "Gate left open, pet wandered off.",
                     "Wrong food served despite allergy note.",
                     "Missed evening medication dose entirely."):
            inc = file_incident(sit["assignment"]["id"], f["f1"], description=desc)
            resolve_incident_at_fault(inc["id"], f["f2"]["id"])
        # Clamped at each event: 50 -> 35 -> 20 -> 5 -> 0.
        assert get_member(f["f2"]["id"])["reliability_score"] == 0
        # No ledger penalties: the assignment was never SETTLED at resolve time.
        assert list_ledger(f["f2"]["id"], params={"entry_type": "INCIDENT_PENALTY"}) == []
        assert get_member(f["f2"]["id"])["credit_balance_hours"] == pytest.approx(10.0, abs=0.001)
