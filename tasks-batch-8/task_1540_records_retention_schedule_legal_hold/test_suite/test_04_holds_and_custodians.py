"""Legal hold lifecycle: creation guards, issuance, scope, release, acknowledgment."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    acknowledge_assignment,
    assert_record_hold_invariant,
    create_hold,
    create_legal_hold_payload,
    expand_scope,
    get_record,
    issue_hold,
    list_all_assignments,
    list_all_scope_items,
    make_custodian_headers,
    read_hold_version,
    register_custodian,
    register_record,
    release_hold,
    run_auto_delete_sweep,
    setup_issued_hold,
    setup_schedule,
    setup_schedule_with_record,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RM = TEST_USERS["records_manager_headers"]
LC = TEST_USERS["legal_counsel_headers"]


class TestHoldCreationGuards:
    def test_duplicate_scope_record_and_matter_ref_rejected(self, api):
        """PRD §3.5: "The `matter_ref` must be unique within the program among
        holds in `DRAFT` or `ISSUED`; a collision is rejected with
        `ERR_DUPLICATE_MATTER_REF` (HTTP 409). No custodian may appear twice on
        one hold (rejected with `ERR_DUPLICATE_CUSTODIAN`), and no record may
        appear twice within one hold's scope or carry status `DESTROYED`
        (rejected with `ERR_DUPLICATE_SCOPE_RECORD` or
        `ERR_RECORD_ALREADY_DESTROYED` respectively)."

        Design: Corner/validations/duplicate_scope_record_and_matter_ref_rejected
        """
        ctx, record = setup_schedule_with_record(months=120,
                                                 event_date="2026-01-15T00:00:00Z")
        custodian = register_custodian(ctx["program"]["id"])
        first = create_hold(ctx["program"]["id"], "M-DUP", [custodian["id"]],
                            [record["id"]])
        assert first["status"] == "DRAFT"

        dup_scope = api.create_legal_hold(
            create_legal_hold_payload(
                ctx["program"]["id"], "M-DUPSCOPE", [custodian["id"]],
                [record["id"], record["id"]], title="Bad scope", reason="Case 2"),
            LC)
        validate_error(dup_scope, ApiErrorId.ERR_DUPLICATE_SCOPE_RECORD)

        dup_matter = api.create_legal_hold(
            create_legal_hold_payload(
                ctx["program"]["id"], "M-DUP", [custodian["id"]],
                [record["id"]], title="Second", reason="Case 3"),
            LC)
        validate_error(dup_matter, ApiErrorId.ERR_DUPLICATE_MATTER_REF)

        cancelled = validate_success(api.cancel_legal_hold(first["id"], LC), 200)
        assert cancelled["status"] == "CANCELLED"
        reused = api.create_legal_hold(
            create_legal_hold_payload(
                ctx["program"]["id"], "M-DUP", [custodian["id"]],
                [record["id"]], title="Third", reason="Case 4"),
            LC)
        third = validate_success(reused, 201)
        assert third["matter_ref"] == "M-DUP", (
            "a CANCELLED hold no longer occupies its matter_ref"
        )

    def test_scope_destroyed_record_rejected(self, api):
        """PRD §3.4: "A record whose status is `DESTROYED` can no longer be
        patched, scoped into a hold, or added to a new disposition request; all
        three attempts are rejected with `ERR_RECORD_ALREADY_DESTROYED` (HTTP
        409)."

        Design: Corner/validations/scope_destroyed_record_rejected
        """
        ctx, record = setup_schedule_with_record(months=1)
        sweep = run_auto_delete_sweep(ctx["program"]["id"])
        assert sweep["destroyed_count"] == 1
        assert get_record(record["id"])["status"] == "DESTROYED"

        custodian = register_custodian(ctx["program"]["id"])
        resp = api.create_legal_hold(
            create_legal_hold_payload(
                ctx["program"]["id"], "M-GONE", [custodian["id"]],
                [record["id"]], title="Hold", reason="Case"),
            LC)
        validate_error(resp, ApiErrorId.ERR_RECORD_ALREADY_DESTROYED)

    def test_cross_program_hold_scope_rejected(self, api):
        """PRD §2.9: "Whenever a request body references other entities —
        records, custodians, classes, jurisdictions, rules — every referenced
        entity must belong to the same program as the parent resource or
        payload; a cross-program reference is rejected with
        `ERR_CROSS_PROGRAM_REFERENCE` (HTTP 409)."

        Design: Corner/validations/cross_program_hold_scope_rejected
        """
        ctx1 = setup_schedule(months=120)
        ctx2 = setup_schedule(months=120, program_name="P2")
        foreign = register_record(
            ctx2["program"]["id"], ctx2["record_class"]["id"],
            ctx2["jurisdiction"]["id"], title="Foreign",
            event_date="2026-01-15T00:00:00Z")
        custodian = register_custodian(ctx1["program"]["id"])

        resp = api.create_legal_hold(
            create_legal_hold_payload(
                ctx1["program"]["id"], "M-XP", [custodian["id"]],
                [foreign["id"]], title="Hold", reason="Case"),
            LC)
        validate_error(resp, ApiErrorId.ERR_CROSS_PROGRAM_REFERENCE)

        _data, meta = validate_paginated(api.list_legal_holds(LC))
        assert meta["total_count"] == 0, "the rejected creation persisted no hold"

    def test_issue_hold_without_scope_rejected(self, api):
        """PRD §3.5: "Issuing a `DRAFT` hold requires at least one scope item
        in `PENDING_ISSUANCE` and at least one assignment in
        `AWAITING_ISSUANCE`; a hold lacking either is rejected with
        `ERR_EMPTY_HOLD_SCOPE` (HTTP 409)."
        PRD §3.5: "Removing a scope item from a `DRAFT` hold cancels it
        outright with no record cascade (it was never `ACTIVE`)."

        Design: Corner/validations/issue_hold_without_scope_rejected
        """
        ctx, record = setup_schedule_with_record(months=120,
                                                 event_date="2026-01-15T00:00:00Z")
        custodian = register_custodian(ctx["program"]["id"])
        hold = create_hold(ctx["program"]["id"], "M-EMPTY", [custodian["id"]],
                           [record["id"]])

        items = list_all_scope_items()
        assert len(items) == 1 and items[0]["status"] == "PENDING_ISSUANCE"
        removed = api.delete_scope_item(hold["id"], items[0]["id"], LC)
        assert removed.status_code == 204, (
            "the scope-item exclusion returns 204 with an empty `data`"
        )
        assert get_record(record["id"])["active_hold_count"] == 0, (
            "a DRAFT-hold removal runs no record cascade"
        )

        issue = api.issue_legal_hold(hold["id"], LC)
        validate_error(issue, ApiErrorId.ERR_EMPTY_HOLD_SCOPE)
        assert validate_success(api.get_legal_hold(hold["id"], LC), 200)["status"] == "DRAFT"


class TestHoldTerminalLockdown:
    def test_hold_invalid_and_terminal_transitions_rejected(self, api):
        """PRD §3.5: "Attempting scope or custodian edits on a hold that is not
        `DRAFT` or `ISSUED`, or excluding an item that is not `ACTIVE`, is
        rejected with `ERR_HOLD_INVALID_STATE` (HTTP 409)."
        PRD §2.8: "the parallel state preconditions of the other entities
        surface as their own domain-specific state errors"
        PRD §4 endpoint table: cancel is defined as "Cancel a DRAFT hold" and
        release as "Release an ISSUED hold", so both reject the other's states.

        Design: Corner/state_machines/hold_invalid_and_terminal_transitions_rejected
        """
        scen = setup_issued_hold(custodian_count=1, record_count=1,
                                 matter_ref="M-H1")
        hold1 = scen["hold"]
        custodian = scen["custodians"][0]
        acknowledge_assignment(scen["assignments"][0]["id"], custodian["id"])
        # A second, still-unacknowledged ISSUED hold in the same program.
        record2 = register_record(
            scen["ctx"]["program"]["id"], scen["ctx"]["record_class"]["id"],
            scen["ctx"]["jurisdiction"]["id"], title="R2",
            event_date="2026-01-15T00:00:00Z", source_system="MAIL")
        hold2 = create_hold(scen["ctx"]["program"]["id"], "M-H2",
                            [custodian["id"]], [record2["id"]])
        hold2 = issue_hold(hold2["id"])

        cancel_issued = api.cancel_legal_hold(hold2["id"], LC)
        validate_error(cancel_issued, ApiErrorId.ERR_HOLD_INVALID_STATE)

        released = release_hold(hold1["id"], read_hold_version(hold1["id"]))
        assert validate_success(released, 200)["status"] == "RELEASED"

        re_release = api.release_legal_hold(
            hold1["id"],
            {"release_reason": "matter closed",
             "expected_legal_hold_version": read_hold_version(hold1["id"])},
            LC)
        validate_error(re_release, ApiErrorId.ERR_HOLD_INVALID_STATE)

        cancel_released = api.cancel_legal_hold(hold1["id"], LC)
        validate_error(cancel_released, ApiErrorId.ERR_HOLD_INVALID_STATE)


class TestReleaseGate:
    def test_release_rejected_while_any_assignment_pending(self, api):
        """PRD §3.5: "every custodian assignment must be in `ACKNOWLEDGED` —
        any assignment still `PENDING` or `ESCALATED` rejects the release with
        `ERR_HOLD_HAS_UNACKNOWLEDGED_CUSTODIANS` (HTTP 409)."
        PRD §2.7: "a hold's `all_acknowledged` is true exactly when at least
        one assignment exists and every assignment is in `ACKNOWLEDGED` or
        `RELEASED`"

        Design: Difficulty/cross_entity_state_dependency/release_blocked_by_pending_custodian
        """
        scen = setup_issued_hold(custodian_count=2, record_count=1,
                                 program_overrides={"ack_deadline_days": 14},
                                 matter_ref="M-GATE")
        hold = scen["hold"]
        c1, c2 = scen["custodians"]
        a1, a2 = scen["assignments"]

        acknowledge_assignment(a1["id"], c1["id"])
        mid = validate_success(api.get_legal_hold(hold["id"], LC), 200)
        assert mid["all_acknowledged"] is False, "C2 has not acknowledged yet"

        blocked = release_hold(hold["id"], mid["version"],
                               release_reason="matter settled fully")
        validate_error(blocked, ApiErrorId.ERR_HOLD_HAS_UNACKNOWLEDGED_CUSTODIANS)

    def test_release_succeeds_after_all_acknowledge_and_frees_record(self, api):
        """PRD §3.5: "every custodian assignment must be in `ACKNOWLEDGED` —
        any assignment still `PENDING` or `ESCALATED` rejects the release with
        `ERR_HOLD_HAS_UNACKNOWLEDGED_CUSTODIANS` (HTTP 409)."
        PRD §3.5: "Every `ACTIVE` scope item becomes `RELEASED` with
        `released_at` set; per item the record's `active_hold_count` is
        decremented by 1, `auto_delete_suspended` recomputed, posture
        recomputed"
        PRD §3.6: "the hold's `version` is incremented by 1"

        Design: Difficulty/cross_entity_state_dependency/release_blocked_by_pending_custodian
        """
        scen = setup_issued_hold(custodian_count=2, record_count=1,
                                 program_overrides={"ack_deadline_days": 14},
                                 matter_ref="M-GATE")
        hold = scen["hold"]
        record = scen["records"][0]
        c1, c2 = scen["custodians"]
        a1, a2 = scen["assignments"]

        acknowledge_assignment(a1["id"], c1["id"])
        mid_version = read_hold_version(hold["id"])
        acknowledge_assignment(a2["id"], c2["id"])
        final = validate_success(api.get_legal_hold(hold["id"], LC), 200)
        assert final["all_acknowledged"] is True
        assert final["version"] > mid_version, "each acknowledgment bumps the version"

        released = release_hold(hold["id"], final["version"],
                                release_reason="matter settled fully")
        assert validate_success(released, 200)["status"] == "RELEASED"

        freed = get_record(record["id"])
        assert freed["active_hold_count"] == 0
        assert freed["auto_delete_suspended"] is False
        assert freed["disposition_posture"] == "RETAINED", (
            "the never-due record returns to RETAINED once the hold releases"
        )


class TestScopeInvariants:
    def test_scope_expansion_on_issued_hold_suspends_record(self, api):
        """PRD §3.5: "Expanding scope creates items immediately in `ACTIVE`:
        for each, the record's `active_hold_count` is incremented by 1,
        `auto_delete_suspended` set to `true`, posture recomputed"

        Design: Difficulty/compensating_invariant/scope_expand_exclude_conserves_record_hold_count
        """
        ctx = setup_schedule(months=1)
        target = register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                                 ctx["jurisdiction"]["id"], title="Inv Rec")
        other = register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                                ctx["jurisdiction"]["id"], title="Other Rec")
        custodian = register_custodian(ctx["program"]["id"])
        hold = create_hold(ctx["program"]["id"], "M-INV", [custodian["id"]],
                           [other["id"]])
        issue_hold(hold["id"])

        baseline = get_record(target["id"])
        assert baseline["active_hold_count"] == 0
        assert baseline["disposition_posture"] == "ELIGIBLE"

        created = expand_scope(hold["id"], [target["id"]])
        assert len(created) == 1 and created[0]["status"] == "ACTIVE", (
            "expansion on an ISSUED hold activates items immediately"
        )
        mid = get_record(target["id"])
        assert mid["active_hold_count"] == 1
        assert mid["auto_delete_suspended"] is True
        assert mid["disposition_posture"] == "HELD"
        assert_record_hold_invariant(mid, list_all_scope_items())

    def test_scope_exclusion_restores_baseline(self, api):
        """PRD §3.5: "Excluding an `ACTIVE` scope item moves it to `EXCLUDED`
        with `released_at` set; the record's `active_hold_count` is decremented
        by 1, `auto_delete_suspended` recomputed (it remains true exactly while
        `active_hold_count` stays above 0), posture recomputed"
        PRD §3.5: "the hold's `active_scope_count` recomputed, the hold's
        `version` bumped by 1, and `last_activity_at` refreshed."

        Design: Difficulty/compensating_invariant/scope_expand_exclude_conserves_record_hold_count
        """
        ctx = setup_schedule(months=1)
        target = register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                                 ctx["jurisdiction"]["id"], title="Inv Rec")
        other = register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                                ctx["jurisdiction"]["id"], title="Other Rec")
        custodian = register_custodian(ctx["program"]["id"])
        hold = create_hold(ctx["program"]["id"], "M-INV", [custodian["id"]],
                           [other["id"]])
        issue_hold(hold["id"])

        created = expand_scope(hold["id"], [target["id"]])
        excluded = api.delete_scope_item(hold["id"], created[0]["id"], LC)
        assert excluded.status_code == 204

        restored = get_record(target["id"])
        assert restored["active_hold_count"] == 0, "exclusion is the compensating action"
        assert restored["auto_delete_suspended"] is False
        assert restored["disposition_posture"] == "ELIGIBLE"
        assert_record_hold_invariant(restored, list_all_scope_items())

        hold_after = validate_success(api.get_legal_hold(hold["id"], LC), 200)
        assert hold_after["active_scope_count"] == 1, "only the untouched record remains"


class TestObligationInvariant:
    def test_issue_then_ack_drains_obligation_count(self, api):
        """PRD §3.5: "Every `AWAITING_ISSUANCE` assignment becomes `PENDING`
        with `ack_due_date` set to `issued_at` plus the program's
        `ack_deadline_days`, and each custodian's `open_obligation_count` is
        incremented by 1 per newly pending assignment."
        PRD §3.6: "The custodian's `open_obligation_count` is decremented by 1"

        Design: Difficulty/compensating_invariant/hold_issue_release_conserves_custodian_obligations
        """
        scen = setup_issued_hold(custodian_count=2, record_count=1,
                                 program_overrides={"ack_deadline_days": 14},
                                 matter_ref="M-OBL")
        c1, c2 = scen["custodians"]
        after_issue_1 = validate_success(api.get_custodian(c1["id"], RM), 200)
        after_issue_2 = validate_success(api.get_custodian(c2["id"], RM), 200)
        assert after_issue_1["open_obligation_count"] == 1
        assert after_issue_2["open_obligation_count"] == 1

        acked = acknowledge_assignment(scen["assignments"][0]["id"], c1["id"])
        assert acked["status"] == "ACKNOWLEDGED"
        assert acked["was_late"] is False, "on-time ack at the default clock"
        drained = validate_success(api.get_custodian(c1["id"], RM), 200)
        assert drained["open_obligation_count"] == 0, (
            "ACKNOWLEDGED is not an open obligation"
        )

    def test_release_after_full_ack_conserves_obligations(self, api):
        """PRD §3.5: "Every `ACKNOWLEDGED` assignment becomes `RELEASED` with
        no change to the custodian's `open_obligation_count` (acknowledged
        assignments were not counted)."
        PRD §2.7: "a custodian's `open_obligation_count` counts their
        assignments in `PENDING` or `ESCALATED`"

        Design: Difficulty/compensating_invariant/hold_issue_release_conserves_custodian_obligations
        """
        scen = setup_issued_hold(custodian_count=2, record_count=1,
                                 program_overrides={"ack_deadline_days": 14},
                                 matter_ref="M-OBL")
        hold = scen["hold"]
        c1, c2 = scen["custodians"]
        a1, a2 = scen["assignments"]

        acknowledge_assignment(a1["id"], c1["id"])
        acknowledge_assignment(a2["id"], c2["id"])
        released = release_hold(hold["id"], read_hold_version(hold["id"]),
                                release_reason="litigation hold closed")
        assert validate_success(released, 200)["status"] == "RELEASED"

        end_1 = validate_success(api.get_custodian(c1["id"], RM), 200)
        end_2 = validate_success(api.get_custodian(c2["id"], RM), 200)
        assert end_1["open_obligation_count"] == 0
        assert end_2["open_obligation_count"] == 0, (
            "the issue + full-ack + release pair conserves per-custodian totals"
        )
        lingering = [a for a in list_all_assignments()
                     if a.get("custodian_id") == c2["id"] and a.get("status") == "PENDING"]
        assert lingering == [], "obligations reconciled to the empty set"


class TestAcknowledgmentGuards:
    def test_acknowledge_by_wrong_custodian_forbidden(self, api):
        """PRD §2.1: "Concretely, acknowledging a `HoldCustodian` assignment is
        permitted only when the assignment's `custodian_id` equals `X-User-ID`;
        otherwise the request is rejected with
        `ERR_NOT_CUSTODIAN_OF_ASSIGNMENT` (HTTP 403)."

        Design: Corner/validations/acknowledge_by_wrong_custodian_forbidden
        """
        scen = setup_issued_hold(custodian_count=1, record_count=1,
                                 matter_ref="M-OWN")
        # A second custodian exists in the program but is not on the hold.
        c2 = register_custodian(scen["ctx"]["program"]["id"], email="c2@x.com",
                                full_name="Two", department="HR")
        assignment = scen["assignments"][0]

        wrong = api.acknowledge_hold_custodian(
            assignment["id"], make_custodian_headers(c2["id"]))
        validate_error(wrong, ApiErrorId.ERR_NOT_CUSTODIAN_OF_ASSIGNMENT)
        still = validate_success(api.get_hold_custodian(assignment["id"], LC), 200)
        assert still["status"] == "PENDING"

    def test_double_acknowledge_rejected(self, api):
        """PRD §3.6: "the assignment must be in `PENDING` or `ESCALATED` (else
        `ERR_ASSIGNMENT_NOT_ACKNOWLEDGEABLE`, HTTP 409)."
        PRD §3.6: "When `was_late` is true, the hold's `late_ack_count` is
        incremented by 1."

        Design: Corner/state_machines/double_acknowledge_rejected
        """
        scen = setup_issued_hold(custodian_count=1, record_count=1,
                                 program_overrides={"ack_deadline_days": 14},
                                 matter_ref="M-DACK")
        hold = scen["hold"]
        custodian = scen["custodians"][0]
        assignment = scen["assignments"][0]

        first = acknowledge_assignment(assignment["id"], custodian["id"])
        assert first["status"] == "ACKNOWLEDGED"
        assert first["was_late"] is False, "ack at the default clock is on time"

        hold_mid = validate_success(api.get_legal_hold(hold["id"], LC), 200)
        version_mid, late_mid = hold_mid["version"], hold_mid["late_ack_count"]
        assert late_mid == 0

        second = api.acknowledge_hold_custodian(
            assignment["id"], make_custodian_headers(custodian["id"]))
        validate_error(second, ApiErrorId.ERR_ASSIGNMENT_NOT_ACKNOWLEDGEABLE)

        hold_after = validate_success(api.get_legal_hold(hold["id"], LC), 200)
        assert hold_after["version"] == version_mid, (
            "the rejected ack mutates nothing"
        )
        assert hold_after["late_ack_count"] == late_mid


class TestReleaseConcurrency:
    def test_release_with_stale_version_rejected(self, api):
        """PRD §2.6: "The second protected write is the release of an issued
        legal hold: the release request must carry `expected_legal_hold_version`
        equal to the hold's current `version`. Scope expansion, scope
        exclusion, custodian addition, and custodian acknowledgment all bump
        the hold's `version`, so a release decision made against an older
        observed scope is stale even when the hold's status is still `ISSUED`,
        and is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/release_with_stale_version_rejected
        """
        scen = setup_issued_hold(custodian_count=1, record_count=1,
                                 matter_ref="M-OCC")
        hold = scen["hold"]
        custodian = scen["custodians"][0]
        # A second record exists outside the hold's scope, ready to be added.
        extra = register_record(
            scen["ctx"]["program"]["id"], scen["ctx"]["record_class"]["id"],
            scen["ctx"]["jurisdiction"]["id"], title="R2",
            event_date="2026-01-15T00:00:00Z", source_system="MAIL")
        acknowledge_assignment(scen["assignments"][0]["id"], custodian["id"])
        observed = read_hold_version(hold["id"])

        # A scope expansion lands between the client's read and its release.
        expand_scope(hold["id"], [extra["id"]])
        stale = release_hold(hold["id"], observed, release_reason="matter closed")
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = read_hold_version(hold["id"])
        assert fresh > observed, "the scope expansion bumped the hold version"
        released = release_hold(hold["id"], fresh, release_reason="matter closed")
        assert validate_success(released, 200)["status"] == "RELEASED"
