"""Disposition execution, destruction certificates, auto-delete sweeps, and
freeze windows."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_destruction_certificate,
    assert_instant_equals,
    create_freeze_window,
    create_freeze_window_payload,
    create_hold,
    create_request,
    find_disposition_item,
    get_record,
    get_request,
    issue_hold,
    list_all_certificates,
    make_records_manager_headers,
    register_custodian,
    register_record,
    run_auto_delete_sweep,
    setup_approved_request,
    setup_schedule,
    setup_schedule_with_record,
    submit_request,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RM = TEST_USERS["records_manager_headers"]
LC = TEST_USERS["legal_counsel_headers"]


class TestConditionalExecution:
    def test_execute_request_per_item_conditional_skip(self, api):
        """PRD §3.8: "Execution processes the request's items one by one in
        request creation order (the order the `record_ids` were supplied). For
        each item, the outcome is conditional and skips do not fail the
        request. If the record is already `DESTROYED` at execution time, the
        item becomes `SKIPPED_ALREADY_DESTROYED`. Else if the record's posture
        is not `ELIGIBLE` at execution — typically `HELD` or
        `CONFLICT_BLOCKED` because a hold or conflict landed between approval
        and execution — the item becomes `SKIPPED_HELD`. Otherwise the record
        is destroyed: its status becomes `DESTROYED` with `destroyed_at` set to
        now, the item becomes `DESTROYED` with its own `destroyed_at`, and a
        `DestructionCertificate` is written. After all items are processed the
        request becomes `EXECUTED` with `executed_at` set."

        Design: Corner/state_machines/execute_request_per_item_conditional_skip
        """
        ctx = setup_schedule(months=1)
        r1 = register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                             ctx["jurisdiction"]["id"], title="R1")
        r2 = register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                             ctx["jurisdiction"]["id"], title="R2")
        custodian = register_custodian(ctx["program"]["id"])
        request = create_request(ctx["program"]["id"], [r1["id"], r2["id"]],
                                 requester_id="rm-1")
        submit_request(request["id"], requester_id="rm-1")
        approved = validate_success(api.approve_disposition_request(
            request["id"], TEST_USERS["legal_counsel_headers"]), 200)
        assert approved["status"] == "APPROVED"

        # A hold lands between approval and execution, covering only R1.
        hold = create_hold(ctx["program"]["id"], "M-LATE", [custodian["id"]],
                           [r1["id"]], title="Late Hold", reason="Late investigation")
        issue_hold(hold["id"])
        assert get_record(r1["id"])["disposition_posture"] == "HELD"

        executed = validate_success(api.execute_disposition_request(
            request["id"], make_records_manager_headers("rm-9")), 200)
        assert executed["status"] == "EXECUTED", (
            "partial execution does not fail the batch"
        )

        assert find_disposition_item(r1["id"])["status"] == "SKIPPED_HELD"
        assert find_disposition_item(r2["id"])["status"] == "DESTROYED"
        assert get_record(r1["id"])["status"] == "ACTIVE", (
            "the hold preserved R1"
        )
        assert get_record(r2["id"])["status"] == "DESTROYED"

        certs = list_all_certificates()
        assert len(certs) == 1, "exactly one certificate for the request"
        assert certs[0]["record_id"] == r2["id"]


class TestAutoDeleteSweep:
    def test_sweep_auto_delete_skips_held_and_disabled(self, api):
        """PRD §3.8: "The sweep destroys every record of the program whose
        posture is `ELIGIBLE`, whose `auto_delete_enabled` is `true`, and whose
        `auto_delete_suspended` is `false`."
        PRD §3.8: "the sweep returns `destroyed_count` and the list of
        `certificate_ids`."

        Design: Corner/state_machines/sweep_auto_delete_skips_held_and_disabled
        """
        ctx = setup_schedule(months=1)
        ra = register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                             ctx["jurisdiction"]["id"], title="RA")
        rb = register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                             ctx["jurisdiction"]["id"], title="RB",
                             auto_delete_enabled=False)
        rc = register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                             ctx["jurisdiction"]["id"], title="RC")
        custodian = register_custodian(ctx["program"]["id"])
        hold = create_hold(ctx["program"]["id"], "M-SWP", [custodian["id"]],
                           [rc["id"]], title="Sweep Hold", reason="Audit")
        issue_hold(hold["id"])

        sweep = run_auto_delete_sweep(ctx["program"]["id"], method="CRYPTO_SHRED")
        assert sweep["destroyed_count"] == 1, "only RA qualifies"
        assert len(sweep["certificate_ids"]) == 1

        rafter = get_record(ra["id"])
        assert rafter["status"] == "DESTROYED"
        assert_instant_equals(rafter["destroyed_at"], "2026-08-01T00:00:00Z")
        assert get_record(rb["id"])["status"] == "ACTIVE", (
            "auto_delete_enabled false survives"
        )
        rc_after = get_record(rc["id"])
        assert rc_after["status"] == "ACTIVE"
        assert rc_after["auto_delete_suspended"] is True, (
            "the hold's suspension is honored"
        )


class TestDestructionCertificate:
    def test_certificate_immutable_system_stamped_documentation(self, api):
        """PRD §3.8: "It captures the `program_id`, the executing `request_id`,
        the `disposition_item_id`, the destroyed `record_id` (a tombstone
        reference), and snapshots of `record_title`, `record_class_code`,
        `jurisdiction_code`, and `retention_due_date` as they stood at
        destruction. It records the destruction `method` (one of
        `SECURE_ERASE`, `SHRED`, `CRYPTO_SHRED`), the `destroyed_at` timestamp
        on the logical clock, a system-generated `content_hash` (a SHA-256 hex
        digest computed over the record id, the title, and the destruction
        timestamp), the executing operator's `X-User-ID` as `witness_user_id`,
        and a `certificate_seq` — a per-program monotonically increasing
        sequence starting at 1, assigned in destruction order (by `created_at`
        ascending within a batch). Certificates are immutable and read-only."
        PRD §2.4: "`DestructionCertificate` and `ReminderLog` are append-only
        records: each carries only `id` and `created_at`; both `updated_at` and
        `version` are absent on them."

        Design: Corner/entities/certificate_immutable_system_stamped_documentation
        """
        # Destruction via request execution: the §3.8 certificate-contents
        # sentence (executing request_id, disposition_item_id) describes this
        # pathway; the sweep pathway has no executing request.
        ctx, record, request = setup_approved_request(
            requester_id="rm-1", approver_id="lc-1",
            months=1, title="Cert Me", method="SHRED")
        executed = validate_success(api.execute_disposition_request(
            request["id"], make_records_manager_headers("rm-7")), 200)
        assert executed["status"] == "EXECUTED"

        certs = list_all_certificates()
        assert len(certs) == 1
        cert = certs[0]
        assert_destruction_certificate(cert)
        assert cert["record_id"] == record["id"]
        assert cert["request_id"] == request["id"]
        assert cert["certificate_seq"] == 1, "first certificate in the program"
        assert cert["method"] == "SHRED"
        assert cert["witness_user_id"] == "rm-7"
        assert cert["record_title"] == "Cert Me"
        assert cert["record_class_code"] == "GEN"
        assert cert["jurisdiction_code"] == "US-FED"
        assert_instant_equals(cert["retention_due_date"], "2026-07-01T00:00:00Z")
        digest = cert["content_hash"]
        assert len(digest) == 64 and all(
            ch in "0123456789abcdefABCDEF" for ch in digest), (
            "content_hash is a SHA-256 hex digest"
        )
        assert "version" not in cert and "updated_at" not in cert


class TestFreezeWindows:
    def test_shared_boundary_freeze_window_rejected(self, api):
        """PRD §3.10: "a new window overlaps an existing `ACTIVE` window
        exactly when one's `start_at` is on or before the other's `end_at` and
        the other's `start_at` is on or before the one's `end_at` — a shared
        boundary timestamp counts as overlap and is rejected with
        `ERR_FREEZE_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/freeze_window_closed_interval_shared_boundary
        """
        ctx = setup_schedule(months=1)
        first = create_freeze_window(ctx["program"]["id"],
                                     "2026-09-01T00:00:00Z",
                                     "2026-09-10T00:00:00Z")
        assert first["status"] == "ACTIVE"

        shared = api.create_freeze_window(
            create_freeze_window_payload(ctx["program"]["id"],
                                         "2026-09-10T00:00:00Z",
                                         "2026-09-20T00:00:00Z",
                                         reason="Adjacent share"),
            ADMIN)
        validate_error(shared, ApiErrorId.ERR_FREEZE_WINDOW_OVERLAP)

        after = validate_success(api.get_freeze_window(first["id"], ADMIN), 200)
        assert after["status"] == "ACTIVE", "the rejected window changes nothing"

    def test_window_starting_one_second_after_boundary_accepted(self, api):
        """PRD §3.10: "a new window overlaps an existing `ACTIVE` window
        exactly when one's `start_at` is on or before the other's `end_at` and
        the other's `start_at` is on or before the one's `end_at` — a shared
        boundary timestamp counts as overlap and is rejected with
        `ERR_FREEZE_WINDOW_OVERLAP` (HTTP 409)."
        PRD §2.10: "Disposition freeze windows, by contrast, use closed
        interval semantics: a window covers the current moment when `start_at`
        is on or before now and now is on or before `end_at`"

        Design: Difficulty/resource_temporal_overlap/freeze_window_closed_interval_shared_boundary
        """
        ctx = setup_schedule(months=1)
        create_freeze_window(ctx["program"]["id"], "2026-09-01T00:00:00Z",
                             "2026-09-10T00:00:00Z")
        later = api.create_freeze_window(
            create_freeze_window_payload(ctx["program"]["id"],
                                         "2026-09-10T00:00:01Z",
                                         "2026-09-20T00:00:00Z",
                                         reason="One second later"),
            ADMIN)
        created = validate_success(later, 201)
        assert created["status"] == "ACTIVE", (
            "one second past the shared endpoint the closed intervals no longer meet"
        )

    def test_freeze_window_cancel_lockdown_and_reuse(self, api):
        """PRD §3.10: "A `PlatformAdmin` may cancel an `ACTIVE` window, setting
        `cancelled_at` and moving it to `CANCELLED`; cancelling a non-`ACTIVE`
        window is rejected with `ERR_FREEZE_WINDOW_NOT_ACTIVE` (HTTP 409)."
        PRD §3.10: "a new window overlaps an existing `ACTIVE` window exactly
        when one's `start_at` is on or before the other's `end_at` and the
        other's `start_at` is on or before the one's `end_at`"

        Design: Corner/state_machines/freeze_window_cancel_lockdown_and_reuse
        """
        ctx = setup_schedule(months=1)
        window = create_freeze_window(ctx["program"]["id"],
                                      "2026-09-01T00:00:00Z",
                                      "2026-09-10T00:00:00Z")
        cancelled = validate_success(api.cancel_freeze_window(window["id"], ADMIN), 200)
        assert cancelled["status"] == "CANCELLED"

        again = api.cancel_freeze_window(window["id"], ADMIN)
        validate_error(again, ApiErrorId.ERR_FREEZE_WINDOW_NOT_ACTIVE)

        reused = api.create_freeze_window(
            create_freeze_window_payload(ctx["program"]["id"],
                                         "2026-09-05T00:00:00Z",
                                         "2026-09-15T00:00:00Z",
                                         reason="New window over cancelled range"),
            ADMIN)
        replacement = validate_success(reused, 201)
        assert replacement["status"] == "ACTIVE", (
            "a CANCELLED window no longer participates in overlap detection"
        )

    def test_freeze_window_invalid_date_range(self, api):
        """PRD §3.10: "`end_at` must be on or after `start_at` (else
        `ERR_INVALID_DATE_RANGE`)"
        PRD §3.2: "When `effective_to` is supplied it must be strictly after
        `effective_from`; otherwise the request is rejected with
        `ERR_INVALID_DATE_RANGE` (HTTP 400)."

        Design: Corner/validations/freeze_window_invalid_date_range
        """
        ctx = setup_schedule(months=1)
        backwards = api.create_freeze_window(
            create_freeze_window_payload(ctx["program"]["id"],
                                         "2026-09-10T00:00:00Z",
                                         "2026-09-01T00:00:00Z",
                                         reason="Backwards"),
            ADMIN)
        validate_error(backwards, ApiErrorId.ERR_INVALID_DATE_RANGE)

        empty_window = api.create_retention_rule(
            {
                "program_id": ctx["program"]["id"],
                "record_class_id": ctx["record_class"]["id"],
                "jurisdiction_id": ctx["jurisdiction"]["id"],
                "rule_code": "R-BAD",
                "retention_months": 12,
                "trigger_basis": "EVENT_DATE",
                "effective_from": "2025-01-01T00:00:00Z",
                "effective_to": "2025-01-01T00:00:00Z",
            },
            RM,
        )
        validate_error(empty_window, ApiErrorId.ERR_INVALID_DATE_RANGE)

    def test_execute_and_sweep_blocked_during_freeze(self, api):
        """PRD §3.10: "A freeze window blocks two operations while `ACTIVE`:
        disposition-request execution and the auto-deletion sweep, both
        rejected with `ERR_DISPOSITION_FREEZE_ACTIVE`."
        PRD §3.8: "Execution requires the request to be `APPROVED` (else
        `ERR_REQUEST_INVALID_STATE`, HTTP 409) and requires that no `ACTIVE`
        disposition freeze window covers the current logical time for the
        program — if one does, the execution is rejected wholesale with
        `ERR_DISPOSITION_FREEZE_ACTIVE` (HTTP 409)."

        Design: Corner/validations/execute_and_sweep_blocked_during_freeze
        """
        ctx, record, request = setup_approved_request()
        # [2026-07-01, 2026-08-31] covers the default clock 2026-08-01.
        window = create_freeze_window(ctx["program"]["id"],
                                      "2026-07-01T00:00:00Z",
                                      "2026-08-31T00:00:00Z",
                                      reason="Audit season freeze")

        blocked_execute = api.execute_disposition_request(request["id"], RM)
        validate_error(blocked_execute, ApiErrorId.ERR_DISPOSITION_FREEZE_ACTIVE)
        blocked_sweep = api.run_auto_delete_sweep(ctx["program"]["id"],
                                                  "SECURE_ERASE", RM)
        validate_error(blocked_sweep, ApiErrorId.ERR_DISPOSITION_FREEZE_ACTIVE)

        validate_success(api.cancel_freeze_window(window["id"], ADMIN), 200)
        executed = validate_success(api.execute_disposition_request(request["id"], RM), 200)
        assert executed["status"] == "EXECUTED"
        assert get_record(record["id"])["status"] == "DESTROYED"

    def test_execute_draft_request_state_beats_freeze(self, api):
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
        PRD §3.8: "Execution requires the request to be `APPROVED` (else
        `ERR_REQUEST_INVALID_STATE`, HTTP 409)"

        Design: Corner/validations/execute_draft_request_state_beats_freeze
        """
        ctx, record = setup_schedule_with_record(months=1)
        request = create_request(ctx["program"]["id"], [record["id"]],
                                 requester_id="rm-1")
        create_freeze_window(ctx["program"]["id"], "2026-07-01T00:00:00Z",
                             "2026-08-31T00:00:00Z", reason="Freeze")

        resp = api.execute_disposition_request(request["id"], RM)
        validate_error(resp, ApiErrorId.ERR_REQUEST_INVALID_STATE)
        assert get_request(request["id"])["status"] == "DRAFT"
