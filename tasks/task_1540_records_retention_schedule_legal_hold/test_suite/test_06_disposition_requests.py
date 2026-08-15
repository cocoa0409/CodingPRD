"""Disposition request lifecycle: creation guards, ownership, approval gates,
revision loop, refresh reconciliation, and patch-driven staleness."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    acknowledge_assignment,
    create_disposition_request_payload,
    create_hold,
    create_request,
    expand_scope,
    find_disposition_item,
    get_record,
    get_request,
    issue_hold,
    make_legal_counsel_headers,
    make_records_manager_headers,
    read_hold_version,
    register_custodian,
    register_record,
    release_hold,
    setup_conflict_blocking_submitted_request,
    setup_schedule,
    setup_schedule_with_record,
    setup_submitted_request,
    setup_submitted_request_with_issued_hold,
    submit_request,
    validate_error,
    validate_paginated,
    validate_success,
    assert_instant_equals,
)

RM = TEST_USERS["records_manager_headers"]
LC = TEST_USERS["legal_counsel_headers"]


class TestRequestCreationGuards:
    def test_short_justification_and_empty_items_rejected(self, api):
        """PRD §3.7: "A `RecordsManager` creates a disposition request by
        supplying `program_id`, a non-empty `record_ids` collection (empty
        yields `ERR_EMPTY_COLLECTION`; any duplicate record id within the
        request yields `ERR_DUPLICATE_REQUEST_ITEM`, HTTP 409; any
        already-destroyed record yields `ERR_RECORD_ALREADY_DESTROYED`), a
        `method` (one of `SECURE_ERASE`, `SHRED`, or `CRYPTO_SHRED` — applied
        uniformly to every item), and a `justification` of at least 20
        characters (shorter yields `ERR_JUSTIFICATION_TOO_SHORT`)."

        Design: Corner/validations/short_justification_and_empty_items_rejected
        """
        ctx, record = setup_schedule_with_record(months=1)
        short = api.create_disposition_request(
            create_disposition_request_payload(
                ctx["program"]["id"], [record["id"]],
                justification="nineteen characters"),
            make_records_manager_headers("rm-1"))
        validate_error(short, ApiErrorId.ERR_JUSTIFICATION_TOO_SHORT)

        empty = api.create_disposition_request(
            create_disposition_request_payload(
                ctx["program"]["id"], [],
                justification="valid length justification here"),
            make_records_manager_headers("rm-1"))
        validate_error(empty, ApiErrorId.ERR_EMPTY_COLLECTION)

    def test_request_with_nonexistent_record_returns_404(self, api):
        """PRD §2.4: "Identifiers referenced inside a request body — such as
        `record_ids`, `custodian_ids`, `record_class_id`, `jurisdiction_id`,
        `supersedes_rule_id`, or `program_id` — are validated for existence
        after the path and before domain state checks: a missing record id
        yields `ERR_REFERENCED_RECORD_NOT_FOUND` (HTTP 404), while a missing
        non-record entity id yields `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP
        404)."

        Design: Corner/errors/request_with_nonexistent_record_returns_404
        """
        ctx = setup_schedule(months=1)
        resp = api.create_disposition_request(
            create_disposition_request_payload(ctx["program"]["id"],
                                               [NON_EXISTENT_UUID]),
            make_records_manager_headers("rm-1"))
        validate_error(resp, ApiErrorId.ERR_REFERENCED_RECORD_NOT_FOUND)

    def test_duplicate_record_in_single_program_request_rejected(self, api):
        """PRD §3.7: "any duplicate record id within the request yields
        `ERR_DUPLICATE_REQUEST_ITEM`, HTTP 409"

        Design: Corner/errors/duplicate_record_in_single_program_request_rejected
        """
        ctx, record = setup_schedule_with_record(months=1)
        resp = api.create_disposition_request(
            create_disposition_request_payload(ctx["program"]["id"],
                                               [record["id"], record["id"]]),
            make_records_manager_headers("rm-1"))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REQUEST_ITEM)

    def test_cross_program_record_beats_duplicate_item_error(self, api):
        """PRD §2.8: "Then the disposition freeze window, same-program
        integrity, uniqueness, held/destroyed record protection, ownership and
        segregation-of-duties checks"
        PRD §2.9: "Whenever a request body references other entities —
        records, custodians, classes, jurisdictions, rules — every referenced
        entity must belong to the same program as the parent resource or
        payload; a cross-program reference is rejected with
        `ERR_CROSS_PROGRAM_REFERENCE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/create_request_cross_program_beats_duplicate
        """
        ctx1, record1 = setup_schedule_with_record(months=1, program_name="P1")
        ctx2, record2 = setup_schedule_with_record(months=1, program_name="P2")

        resp = api.create_disposition_request(
            create_disposition_request_payload(
                ctx1["program"]["id"],
                [record2["id"], record1["id"], record1["id"]],
                method="SHRED", justification="cross program duplicate check"),
            make_records_manager_headers("rm-1"))
        validate_error(resp, ApiErrorId.ERR_CROSS_PROGRAM_REFERENCE)

        _data, meta = validate_paginated(api.list_disposition_requests(RM))
        assert meta["total_count"] == 0, "the rejected create persisted nothing"

    def test_duplicate_alone_yields_duplicate_item_error_control(self, api):
        """PRD §3.7: "any duplicate record id within the request yields
        `ERR_DUPLICATE_REQUEST_ITEM`, HTTP 409"
        PRD §2.9: "every referenced entity must belong to the same program as
        the parent resource or payload; a cross-program reference is rejected
        with `ERR_CROSS_PROGRAM_REFERENCE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/create_request_cross_program_beats_duplicate
        """
        ctx, record = setup_schedule_with_record(months=1, program_name="P1")
        # Control: the duplicate violation alone (no cross-program distractor).
        resp = api.create_disposition_request(
            create_disposition_request_payload(ctx["program"]["id"],
                                               [record["id"], record["id"]]),
            make_records_manager_headers("rm-1"))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REQUEST_ITEM)


class TestSubmitAndOwnership:
    def test_submit_by_non_owner_forbidden(self, api):
        """PRD §3.7: "Submitting a `DRAFT` request is restricted to the
        original requester — any other `X-User-ID` is rejected with
        `ERR_NOT_REQUEST_OWNER` (HTTP 403)"

        Design: Corner/validations/submit_by_non_owner_forbidden
        """
        ctx, record = setup_schedule_with_record(months=1)
        request = create_request(ctx["program"]["id"], [record["id"]],
                                 requester_id="rm-1")
        resp = api.submit_disposition_request(
            request["id"], make_records_manager_headers("rm-2"))
        validate_error(resp, ApiErrorId.ERR_NOT_REQUEST_OWNER)
        assert get_request(request["id"])["status"] == "DRAFT"

    def test_submit_noneligible_record_rejected(self, api):
        """PRD §3.7: "Submitting a `DRAFT` request is restricted to the original
        requester — any other `X-User-ID` is rejected with
        `ERR_NOT_REQUEST_OWNER` (HTTP 403) — and requires every item's record
        to currently be `ELIGIBLE`; the first failing record (in the request's
        creation order) is named in the `ERR_RECORD_NOT_ELIGIBLE` (HTTP 409)
        message."
        PRD §3.7: "On submission the request becomes `SUBMITTED`,
        `submitted_at` is set, each item captures `snapshot_posture`,
        `snapshot_due_date`, and `snapshot_hold_count` from its record"

        Design: Corner/validations/submit_noneligible_record_rejected
        """
        ctx, record = setup_schedule_with_record(months=120,
                                                 event_date="2026-01-15T00:00:00Z")
        assert record["disposition_posture"] == "RETAINED", (
            "due 2036-01-15 is after the default clock"
        )
        request = create_request(ctx["program"]["id"], [record["id"]],
                                 requester_id="rm-1")
        resp = api.submit_disposition_request(
            request["id"], make_records_manager_headers("rm-1"))
        validate_error(resp, ApiErrorId.ERR_RECORD_NOT_ELIGIBLE)

        item = find_disposition_item(record["id"])
        assert item["snapshot_posture"] is None, (
            "no snapshot is captured by a failed submit"
        )
        assert get_request(request["id"])["status"] == "DRAFT"

    def test_withdraw_and_revise_from_submitted_rejected(self, api):
        """PRD §3.7: "A rejected request is not terminal: the original
        requester may return it to `DRAFT` via the revise action"
        PRD §3.7: "A `DRAFT` request may also be abandoned entirely via the
        withdraw action, moving it to `WITHDRAWN`"
        PRD §3.8: "Execution requires the request to be `APPROVED` (else
        `ERR_REQUEST_INVALID_STATE`, HTTP 409)"

        Design: Corner/state_machines/withdraw_and_revise_from_submitted_rejected
        """
        ctx, record, request = setup_submitted_request()
        withdraw = api.withdraw_disposition_request(
            request["id"], make_records_manager_headers("rm-1"))
        validate_error(withdraw, ApiErrorId.ERR_REQUEST_INVALID_STATE)
        revise = api.revise_disposition_request(
            request["id"], make_records_manager_headers("rm-1"))
        validate_error(revise, ApiErrorId.ERR_REQUEST_INVALID_STATE)
        assert get_request(request["id"])["status"] == "SUBMITTED"


class TestApproveGates:
    def test_approve_own_request_rejected_sod(self, api):
        """PRD §3.7: "the approver must not be the original requester:
        matching `X-User-ID` against `requester_user_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/approve_own_request_rejected_sod
        """
        ctx, record, request = setup_submitted_request(requester_id="rm-1")
        resp = api.approve_disposition_request(
            request["id"], make_legal_counsel_headers("rm-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_request(request["id"])["status"] == "SUBMITTED"

    def test_approve_draft_by_requester_returns_state_error_not_sod(self, api):
        """PRD §2.8: "State-machine preconditions come after that — attempting
        an action against a rule not in the required status (for example,
        activating a rule that is not `DRAFT`, withdrawing one that is not
        `PENDING_CONFLICT`, or retiring one that is neither `DRAFT` nor
        `ACTIVE`) is rejected with `ERR_RULE_INVALID_STATE` (HTTP 409), and the
        parallel state preconditions of the other entities surface as their own
        domain-specific state errors. Then the disposition freeze window,
        same-program integrity, uniqueness, held/destroyed record protection,
        ownership and segregation-of-duties checks, the conflict gate on
        disposition approval, eligibility gates, the hold-release gate, the
        APPLY_SHORTEST counsel requirement, the retire-protection rule, and
        finally the freeze-window overlap rule."

        Design: Difficulty/priority_pair_validation_conflict/approve_draft_request_state_beats_sod
        """
        ctx, record = setup_schedule_with_record(months=1)
        request = create_request(ctx["program"]["id"], [record["id"]],
                                 requester_id="rm-1")
        # Both violations armed: the request is DRAFT (state) and the acting
        # user id equals the requester's (segregation of duties).
        resp = api.approve_disposition_request(
            request["id"], make_legal_counsel_headers("rm-1"))
        validate_error(resp, ApiErrorId.ERR_REQUEST_INVALID_STATE)
        assert get_request(request["id"])["status"] == "DRAFT"

    def test_approve_draft_by_other_counsel_also_state_error(self, api):
        """PRD §2.8: "State-machine preconditions come after that — attempting
        an action against a rule not in the required status (for example,
        activating a rule that is not `DRAFT`, withdrawing one that is not
        `PENDING_CONFLICT`, or retiring one that is neither `DRAFT` nor
        `ACTIVE`) is rejected with `ERR_RULE_INVALID_STATE` (HTTP 409), and the
        parallel state preconditions of the other entities surface as their own
        domain-specific state errors. Then the disposition freeze window,
        same-program integrity, uniqueness, held/destroyed record protection,
        ownership and segregation-of-duties checks, the conflict gate on
        disposition approval, eligibility gates, the hold-release gate, the
        APPLY_SHORTEST counsel requirement, the retire-protection rule, and
        finally the freeze-window overlap rule."

        Design: Difficulty/priority_pair_validation_conflict/approve_draft_request_state_beats_sod
        """
        ctx, record = setup_schedule_with_record(months=1)
        request = create_request(ctx["program"]["id"], [record["id"]],
                                 requester_id="rm-1")
        # Control: a different counsel cannot trip the segregation gate, so the
        # surfaced error can only come from the state precondition.
        resp = api.approve_disposition_request(
            request["id"], make_legal_counsel_headers("lc-1"))
        validate_error(resp, ApiErrorId.ERR_REQUEST_INVALID_STATE)
        assert get_request(request["id"])["status"] == "DRAFT"

    def test_approve_rejected_while_open_conflict_covers_item(self, api):
        """PRD §3.7: "First, no `OPEN` retention conflict may cover any item's
        (class, jurisdiction) — otherwise `ERR_DISPOSITION_CONFLICT_BLOCKED`
        (HTTP 409). Second, `stale_item_count` must be 0 — otherwise
        `ERR_STALE_ELIGIBILITY_SNAPSHOT` (HTTP 409)"
        PRD §3.4: "First, if any `OPEN` retention conflict exists for the
        record's (class, jurisdiction), there is no governing rule and the
        record's posture is `CONFLICT_BLOCKED`"

        Design: Difficulty/cross_entity_state_dependency/approve_blocked_by_open_conflict
        """
        ctx, record, request, incumbent, challenger, conflict = (
            setup_conflict_blocking_submitted_request())
        resp = api.approve_disposition_request(
            request["id"], make_legal_counsel_headers("lc-1"))
        validate_error(resp, ApiErrorId.ERR_DISPOSITION_CONFLICT_BLOCKED)

        assert get_record(record["id"])["disposition_posture"] == "CONFLICT_BLOCKED"
        assert get_request(request["id"])["status"] == "SUBMITTED"
        conflict_after = validate_success(
            api.get_retention_conflict(conflict["id"], RM), 200)
        assert conflict_after["status"] == "OPEN"

    def test_approve_succeeds_after_conflict_withdrawn(self, api):
        """PRD §3.2: "A `PENDING_CONFLICT` challenger may be withdrawn by a
        `RecordsManager`, returning it to `DRAFT`; the linked `OPEN` conflict
        becomes `WITHDRAWN`, and records of the contested pair whose posture
        re-enters `ELIGIBLE` because the conflict cleared cause
        `stale_item_count` to be decremented by 1 on containing
        `SUBMITTED`/`APPROVED` requests."
        PRD §3.7: "Refresh requires the requester identity and that every
        item's record is currently `ELIGIBLE` (else `ERR_RECORD_NOT_ELIGIBLE`);
        on success the per-item snapshots are re-captured from current record
        state and `stale_item_count` is reset to 0."

        Design: Difficulty/cross_entity_state_dependency/approve_blocked_by_open_conflict
        """
        ctx, record, request, incumbent, challenger, conflict = (
            setup_conflict_blocking_submitted_request())
        validate_success(api.withdraw_retention_rule(challenger["id"], RM), 200)
        conflict_after = validate_success(
            api.get_retention_conflict(conflict["id"], RM), 200)
        assert conflict_after["status"] == "WITHDRAWN"

        restored = get_record(record["id"])
        assert restored["disposition_posture"] == "ELIGIBLE", (
            "clearing the conflict restores the incumbent's governance"
        )

        # Refresh is the supported path for clearing staleness after a
        # conflict clears; it re-captures snapshots and resets the counter.
        refreshed = validate_success(api.refresh_disposition_request(
            request["id"], make_records_manager_headers("rm-1")), 200)
        assert refreshed["stale_item_count"] == 0

        approved = api.approve_disposition_request(
            request["id"], make_legal_counsel_headers("lc-1"))
        assert validate_success(approved, 200)["status"] == "APPROVED"


class TestStaleSnapshotCascade:
    def test_scope_expansion_marks_record_held_and_stales_request(self, api):
        """PRD §3.5: "Expanding scope creates items immediately in `ACTIVE`:
        for each, the record's `active_hold_count` is incremented by 1,
        `auto_delete_suspended` set to `true`, posture recomputed,
        `stale_item_count` incremented by 1 on containing
        `SUBMITTED`/`APPROVED` requests if the record left `ELIGIBLE`, the
        hold's `active_scope_count` is recomputed"

        Design: Difficulty/transitive_cascade/scope_expansion_cascade_record_to_request
        """
        ctx = setup_schedule(months=1)
        target = register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                                 ctx["jurisdiction"]["id"], title="Target")
        decoy = register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                                ctx["jurisdiction"]["id"], title="Decoy")
        custodian = register_custodian(ctx["program"]["id"])
        request = create_request(ctx["program"]["id"], [target["id"]],
                                 requester_id="rm-1")
        request = submit_request(request["id"], requester_id="rm-1")
        assert request["stale_item_count"] == 0

        hold = create_hold(ctx["program"]["id"], "M-1", [custodian["id"]],
                           [decoy["id"]])
        issue_hold(hold["id"])

        created = expand_scope(hold["id"], [target["id"]])
        assert created[0]["status"] == "ACTIVE", (
            "hop 1: the new scope item is ACTIVE immediately on an ISSUED hold"
        )
        held = get_record(target["id"])
        assert held["active_hold_count"] == 1
        assert held["auto_delete_suspended"] is True
        assert held["disposition_posture"] == "HELD", "hop 2: the record flips"
        assert get_request(request["id"])["stale_item_count"] == 1, (
            "hop 3: leaving ELIGIBLE stales the containing request"
        )
        hold_after = validate_success(api.get_legal_hold(hold["id"], LC), 200)
        assert hold_after["active_scope_count"] == 2

    def test_stale_request_approval_rejected_after_scope_expansion(self, api):
        """PRD §3.7: "Second, `stale_item_count` must be 0 — otherwise
        `ERR_STALE_ELIGIBILITY_SNAPSHOT` (HTTP 409); this is the check that
        forces a refresh after schedule or hold churn."

        Design: Difficulty/transitive_cascade/scope_expansion_cascade_record_to_request
        """
        ctx = setup_schedule(months=1)
        target = register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                                 ctx["jurisdiction"]["id"], title="Target")
        decoy = register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                                ctx["jurisdiction"]["id"], title="Decoy")
        custodian = register_custodian(ctx["program"]["id"])
        request = create_request(ctx["program"]["id"], [target["id"]],
                                 requester_id="rm-1")
        submit_request(request["id"], requester_id="rm-1")
        hold = create_hold(ctx["program"]["id"], "M-1", [custodian["id"]],
                           [decoy["id"]])
        issue_hold(hold["id"])
        expand_scope(hold["id"], [target["id"]])
        assert get_request(request["id"])["stale_item_count"] == 1

        resp = api.approve_disposition_request(
            request["id"], make_legal_counsel_headers("lc-1"))
        validate_error(resp, ApiErrorId.ERR_STALE_ELIGIBILITY_SNAPSHOT)
        assert get_request(request["id"])["status"] == "SUBMITTED"


class TestRejectReviseCycle:
    def test_reject_then_revise_returns_to_draft_and_clears_snapshots(self, api):
        """PRD §3.7: "A rejected request is not terminal: the original
        requester may return it to `DRAFT` via the revise action, which clears
        all per-item snapshots (back to null), clears `rejection_reason`, and
        resets `stale_item_count` to 0."
        PRD §3.7: "Rejection is the sibling decision and is deliberately not
        subject to segregation of duties: any `LegalCounsel` may reject a
        `SUBMITTED` request, supplying a `rejection_reason` of at least 10
        characters"

        Design: Difficulty/non_linear_state_machine/disposition_request_reject_revise_cycle
        """
        ctx, record, request = setup_submitted_request(requester_id="rm-1")
        assert request["status"] == "SUBMITTED"

        rejected = validate_success(api.reject_disposition_request(
            request["id"], {"rejection_reason": "Need counsel review first"},
            make_legal_counsel_headers("lc-9")), 200)
        assert rejected["status"] == "REJECTED"

        revised = validate_success(api.revise_disposition_request(
            request["id"], make_records_manager_headers("rm-1")), 200)
        assert revised["status"] == "DRAFT", "the cycle loops back to DRAFT"
        assert revised["stale_item_count"] == 0
        item = find_disposition_item(record["id"])
        assert item["snapshot_posture"] is None, "revise clears the snapshots"
        assert item["snapshot_due_date"] is None
        assert item["snapshot_hold_count"] is None

    def test_full_cycle_reaches_approved_after_revision(self, api):
        """PRD §3.7: "A rejected request is not terminal: the original
        requester may return it to `DRAFT` via the revise action, which clears
        all per-item snapshots (back to null), clears `rejection_reason`, and
        resets `stale_item_count` to 0."
        PRD §3.7: "the approver must not be the original requester: matching
        `X-User-ID` against `requester_user_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Difficulty/non_linear_state_machine/disposition_request_reject_revise_cycle
        """
        ctx, record, request = setup_submitted_request(requester_id="rm-1")
        validate_success(api.reject_disposition_request(
            request["id"], {"rejection_reason": "Need counsel review first"},
            make_legal_counsel_headers("lc-9")), 200)
        revised = validate_success(api.revise_disposition_request(
            request["id"], make_records_manager_headers("rm-1")), 200)
        assert revised["status"] == "DRAFT"

        resubmitted = validate_success(api.submit_disposition_request(
            request["id"], make_records_manager_headers("rm-1")), 200)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["stale_item_count"] == 0

        approved = validate_success(api.approve_disposition_request(
            request["id"], make_legal_counsel_headers("lc-1")), 200)
        assert approved["status"] == "APPROVED", (
            "the full DRAFT -> SUBMITTED -> REJECTED -> DRAFT -> SUBMITTED -> "
            "APPROVED cycle completes"
        )
        assert approved["decided_by_user_id"] == "lc-1"


class TestRefreshReconciliation:
    def test_refresh_blocked_while_held_then_succeeds_after_release(self, api):
        """PRD §3.7: "Refresh requires the requester identity and that every
        item's record is currently `ELIGIBLE` (else `ERR_RECORD_NOT_ELIGIBLE`);
        on success the per-item snapshots are re-captured from current record
        state and `stale_item_count` is reset to 0."
        PRD §3.5: "Every `ACTIVE` scope item becomes `RELEASED` with
        `released_at` set; per item the record's `active_hold_count` is
        decremented by 1, `auto_delete_suspended` recomputed, posture
        recomputed, and `stale_item_count` decremented by 1 on containing
        `SUBMITTED`/`APPROVED` requests if the record entered `ELIGIBLE`."

        Design: Corner/validations/refresh_blocked_while_held_then_succeeds_after_release
        """
        ctx, record, request, custodian, hold, assignment = (
            setup_submitted_request_with_issued_hold(requester_id="rm-1"))
        assert get_record(record["id"])["disposition_posture"] == "HELD"
        assert get_request(request["id"])["stale_item_count"] == 1

        blocked = api.refresh_disposition_request(
            request["id"], make_records_manager_headers("rm-1"))
        validate_error(blocked, ApiErrorId.ERR_RECORD_NOT_ELIGIBLE)

        acknowledge_assignment(assignment["id"], custodian["id"])
        released = release_hold(hold["id"], read_hold_version(hold["id"]),
                                release_reason="matter closed")
        assert validate_success(released, 200)["status"] == "RELEASED"
        assert get_request(request["id"])["stale_item_count"] == 0, (
            "the release reverse-cascade already decremented the counter"
        )

        refreshed = validate_success(api.refresh_disposition_request(
            request["id"], make_records_manager_headers("rm-1")), 200)
        assert refreshed["status"] == "SUBMITTED"
        assert refreshed["stale_item_count"] == 0

        approved = api.approve_disposition_request(
            request["id"], make_legal_counsel_headers("lc-1"))
        assert validate_success(approved, 200)["status"] == "APPROVED"


class TestPatchCascade:
    def test_patch_record_event_date_recomputes_and_stales(self, api):
        """PRD §3.4: "Changing `event_date` recomputes `retention_due_date`,
        `governing_rule_id`, and posture, and triggers the same
        `stale_item_count` adjustments on containing `SUBMITTED`/`APPROVED`
        disposition requests as rule churn does."

        Design: Corner/endpoints/patch_record_event_date_recomputes_and_stales
        """
        ctx, record, request = setup_submitted_request(requester_id="rm-1")
        assert request["stale_item_count"] == 0

        patched = validate_success(api.patch_record(
            record["id"], {"event_date": "2026-08-15T00:00:00Z"}, RM), 200)
        assert_instant_equals(patched["retention_due_date"], "2026-09-15T00:00:00Z")
        assert patched["disposition_posture"] == "RETAINED", (
            "the new due date is after the default clock 2026-08-01"
        )
        assert get_request(request["id"])["stale_item_count"] == 1, (
            "the record left ELIGIBLE while its request was SUBMITTED"
        )
