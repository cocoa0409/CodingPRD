"""Collections under 501(r): notification/ECA windows, posture gating, the
assistance freeze, and the collection-action lifecycle."""
from test_helpers import (
    BILLING,
    COLLECTIONS,
    COMPLIANCE,
    ApiErrorId,
    add_member,
    assert_collection_action,
    begin_review,
    create_application,
    create_determination,
    evaluate_posture,
    finalize_determination,
    get_account,
    halt_collection_action,
    issue_notice,
    post_adjustment,
    set_clock,
    setup_account_in_notice_period,
    setup_eca_active_account,
    submit_application,
    upload_and_verify,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    withdraw_application,
)


class TestEcaClearanceWindowBoundary:
    def test_evaluate_one_second_short_of_120_days_rejected(self, api):
        """PRD §2.9: "The notification period requires that the logical clock
        have reached `first_statement_at` plus `notification_period_days`; the
        boundary is inclusive, so a clock exactly at that instant satisfies the
        gate."

        Design: Difficulty/boundary_precision_check/eca_notification_window_120_day_boundary
        """
        ctx = setup_account_in_notice_period(
            patient_name="Window Will", mrn="MRN-WIN-1", ssn_last4="1313",
            statement_at="2026-01-01T00:00:00Z",
        )
        set_clock("2026-04-01T00:00:00Z")
        issue_notice(ctx["account"]["id"], "ECA_WARNING", "MAIL")
        # one second before first_statement_at + 120 days (2026-05-01T00:00:00Z)
        set_clock("2026-04-30T23:59:59Z")
        resp = api.evaluate_posture(ctx["account"]["id"], COLLECTIONS)
        validate_error(resp, ApiErrorId.ERR_ECA_NOTIFICATION_WINDOW_UNMET)
        account = get_account(ctx["account"]["id"])
        assert account["collection_posture"] == "NOTICE_PERIOD", (
            "failed evaluation leaves the posture untouched"
        )

    def test_evaluate_exactly_120_days_passes(self, api):
        """PRD §2.9: "The warning-notice requirement demands that an
        `ECA_WARNING` notice exist for the account whose `issued_at` is at
        least `eca_notice_days` before the current logical-clock instant — that
        is, `issued_at` less than or equal to now minus `eca_notice_days`,
        again inclusive. Both gates together form the ECA clearance window;
        failure of either yields `ERR_ECA_NOTIFICATION_WINDOW_UNMET`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/eca_notification_window_120_day_boundary
        """
        ctx = setup_account_in_notice_period(
            patient_name="Window Will", mrn="MRN-WIN-1", ssn_last4="1313",
            statement_at="2026-01-01T00:00:00Z",
        )
        # warning exactly 30 days before the evaluation instant (inclusive)
        set_clock("2026-04-01T00:00:00Z")
        issue_notice(ctx["account"]["id"], "ECA_WARNING", "MAIL")
        # exactly first_statement_at + 120 days
        set_clock("2026-05-01T00:00:00Z")
        account = validate_success(api.evaluate_posture(ctx["account"]["id"], COLLECTIONS))
        assert account["collection_posture"] == "ECA_ELIGIBLE"


class TestCollectionActionGating:
    def test_action_requires_eca_eligible_posture(self, api):
        """PRD §3.11: "Only an `ECA_ELIGIBLE` account may receive an
        extraordinary collection action; initiating against any other posture
        is rejected with `ERR_ACCOUNT_NOT_ECA_ELIGIBLE` (HTTP 409), and the
        clearance window is re-checked at initiation
        (`ERR_ECA_NOTIFICATION_WINDOW_UNMET`)."

        Design: Difficulty/cross_entity_state_dependency/collection_action_gated_by_account_posture
        """
        # statement 2026-01-01, warning 2026-04-01, clock 2026-05-01 — the
        # clearance window is satisfied, so only the posture gate can fail.
        ctx = setup_account_in_notice_period(
            patient_name="Posture Pete", mrn="MRN-POST-1", ssn_last4="1515",
            statement_at="2026-01-01T00:00:00Z",
        )
        set_clock("2026-04-01T00:00:00Z")
        issue_notice(ctx["account"]["id"], "ECA_WARNING", "MAIL")
        set_clock("2026-05-01T00:00:00Z")
        assert ctx["account"]["collection_posture"] == "NOTICE_PERIOD"
        resp = api.create_collection_action(
            ctx["account"]["id"], {"action_type": "CREDIT_REPORT"}, COLLECTIONS
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ECA_ELIGIBLE)

    def test_action_creation_moves_account_to_eca_active(self, api):
        """PRD §3.11: "Initiation creates the `CollectionAction` in `INITIATED`
        status with `initiated_at` and `initiated_by_user_id` stamped, moves
        the account `ECA_ELIGIBLE → ECA_ACTIVE`, and increments the account's
        `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/collection_action_gated_by_account_posture
        """
        ctx = setup_account_in_notice_period(
            patient_name="Posture Pete", mrn="MRN-POST-1", ssn_last4="1515",
            statement_at="2026-01-01T00:00:00Z",
        )
        set_clock("2026-04-01T00:00:00Z")
        issue_notice(ctx["account"]["id"], "ECA_WARNING", "MAIL")
        set_clock("2026-05-01T00:00:00Z")
        account = evaluate_posture(ctx["account"]["id"])
        assert account["collection_posture"] == "ECA_ELIGIBLE"
        action = validate_success(
            api.create_collection_action(
                ctx["account"]["id"], {"action_type": "CREDIT_REPORT"}, COLLECTIONS
            ),
            201,
        )
        assert_collection_action(action)
        assert action["status"] == "INITIATED"
        assert action["initiated_by_user_id"] == COLLECTIONS["X-User-ID"]
        account = get_account(ctx["account"]["id"])
        assert account["collection_posture"] == "ECA_ACTIVE", (
            "the first collection action bubbles the posture to ECA_ACTIVE"
        )


class TestAdjustmentHaltsCollections:
    def _cascade_scenario(self):
        """Account ECA_ACTIVE with an INITIATED action; an application for the
        same patient submitted (hold) and approved TIER_FULL covering the
        account. Returns (account_id, action_id, determination_id)."""
        ctx = setup_eca_active_account(
            patient_name="Cascade Carl", mrn="MRN-CASC-1", ssn_last4="1212",
            total_charges=400000, action_type="CREDIT_REPORT",
        )
        account_id = ctx["account"]["id"]
        action_id = ctx["action"]["id"]
        set_clock("2026-06-01T00:00:00Z")
        app = create_application(
            ctx["patient"]["id"], screening_source="STANDARD",
            reported_annual_income_cents=2000000, reported_liquid_assets_cents=0,
        )
        member = add_member(
            app["id"], full_name="Cascade Carl", relationship="SELF", age=54
        )
        submit_application(app["id"])
        begin_review(app["id"])
        upload_and_verify(
            app["id"], member["id"], doc_type="TAX_RETURN", amount_cents=2000000
        )
        upload_and_verify(
            app["id"], member["id"], doc_type="IDENTITY", amount_cents=0,
            period_start="2026-01-01", period_end="2026-01-01",
        )
        det = create_determination(app["id"], "VERIFIED_APPLICATION", [account_id])
        det = finalize_determination(det["id"])
        assert det["tier"] == "TIER_FULL"
        return account_id, action_id, det["id"]

    def test_writeoff_resolves_account_under_hold(self, api):
        """PRD §3.10: "After both legs, the account's posture resolves: if
        `amount_outstanding_cents` is now zero, an account in `ASSISTANCE_HOLD`
        moves to `RESOLVED` and every `INITIATED` collection action on it is
        halted with `halt_reason` `ACCOUNT_RESOLVED`; if a balance remains, the
        account moves from `ASSISTANCE_HOLD` back to `NOTICE_PERIOD`."

        Design: Difficulty/transitive_cascade/adjustment_post_cascades_account_resolve_and_ecas_halt
        """
        account_id, _action_id, det_id = self._cascade_scenario()
        assert get_account(account_id)["collection_posture"] == "ASSISTANCE_HOLD", (
            "the pending application froze the account before the write-off"
        )
        post_adjustment(account_id, det_id)
        account = get_account(account_id)
        assert account["adjusted_balance_cents"] == 0, "TIER_FULL write-off of 400000"
        assert account["amount_outstanding_cents"] == 0
        assert account["collection_posture"] == "RESOLVED", (
            "the balance recompute caused by the adjustment resolves the account"
        )

    def test_resolve_halts_initiated_actions_with_reason(self, api):
        """PRD §3.10: "After both legs, the account's posture resolves: if
        `amount_outstanding_cents` is now zero, an account in `ASSISTANCE_HOLD`
        moves to `RESOLVED` and every `INITIATED` collection action on it is
        halted with `halt_reason` `ACCOUNT_RESOLVED`; if a balance remains, the
        account moves from `ASSISTANCE_HOLD` back to `NOTICE_PERIOD`."
        PRD §3.11: "A halt moves `INITIATED → HALTED`, stamps `halted_at`, and
        records a `halt_reason`: a `ComplianceOfficer` halts explicitly and may
        supply a free-text `reason`, while the system halts automatically —
        with `halt_reason` `ACCOUNT_RESOLVED` — when the account becomes
        `RESOLVED` through payment or write-off, as described in §3.9 and
        §3.10."

        Design: Difficulty/transitive_cascade/adjustment_post_cascades_account_resolve_and_ecas_halt
        """
        account_id, action_id, det_id = self._cascade_scenario()
        post_adjustment(account_id, det_id)
        actions = validate_success(
            api.list_collection_actions(account_id, COLLECTIONS)
        )
        action = [a for a in actions if a["id"] == action_id][0]
        assert action["status"] == "HALTED", (
            "entering RESOLVED halts the account's INITIATED actions"
        )
        assert action["halt_reason"] == "ACCOUNT_RESOLVED"
        assert action["halted_at"] is not None


class TestStatementAndActionLockdown:
    def test_second_statement_rejected(self, api):
        """PRD §3.2: "That operation requires `first_statement_at` to still be
        null — a second issuance attempt is rejected with
        `ERR_FIRST_STATEMENT_ALREADY_ISSUED` (HTTP 409) — and on success it
        stamps `first_statement_at` with the logical-clock now, creates a
        `FIRST_STATEMENT` `NotificationRecord` against the account with
        `is_plain_language` true, moves the account's posture
        `NOT_IN_COLLECTIONS → NOTICE_PERIOD`, and increments the account's
        `version`."

        Design: Corner/state_machines/statement_issued_twice_rejected
        """
        ctx = setup_account_in_notice_period(
            patient_name="Stmt Steve", mrn="MRN-STMT-1", ssn_last4="0013",
            statement_at="2026-01-01T00:00:00Z",
        )
        resp = api.issue_statement(ctx["account"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_FIRST_STATEMENT_ALREADY_ISSUED)

    def test_halted_action_is_terminal_for_halt_and_complete(self, api):
        """PRD §3.11: "Completion by a `CollectionsAgent` requires the action
        to be `INITIATED` and the owning account to be in `ECA_ACTIVE` or
        `ECA_ELIGIBLE` (`ERR_ACTION_NOT_INITIATED` and
        `ERR_ACCOUNT_NOT_IN_COLLECTIONS` respectively, both HTTP 409), moving
        the action to `COMPLETED`."
        PRD §3.11: "Halting an action that is not `INITIATED` is rejected with
        `ERR_ACTION_NOT_INITIATED`."

        Design: Corner/state_machines/collection_action_halt_and_complete_terminal_lockdown
        """
        ctx = setup_eca_active_account(
            patient_name="Halt Hank", mrn="MRN-HALT-1", ssn_last4="0016",
            action_type="LAWSUIT",
        )
        action_id = ctx["action"]["id"]
        halted = halt_collection_action(action_id, reason="regulatory review")
        assert halted["status"] == "HALTED"
        resp = api.complete_collection_action(action_id, COLLECTIONS)
        validate_error(resp, ApiErrorId.ERR_ACTION_NOT_INITIATED)
        resp = api.halt_collection_action(action_id, {"reason": "again"}, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_ACTION_NOT_INITIATED)


class TestAssistanceHoldFreeze:
    def test_submit_freezes_collections_until_withdrawal(self, api):
        """PRD §3.4: "And it freezes collections: every account of this patient
        whose posture is `NOTICE_PERIOD`, `ECA_ELIGIBLE`, or `ECA_ACTIVE`
        transitions to `ASSISTANCE_HOLD`."
        PRD §2.9: "While any application of the patient is open — in
        `SUBMITTED`, `UNDER_REVIEW`, or `PENDING_DOCUMENTS` — posture
        evaluation and collection-action initiation for that patient's accounts
        are frozen, surfacing `ERR_ASSISTANCE_HOLD_ACTIVE` (HTTP 409)."
        PRD §3.4: "Withdrawal moves the application to `WITHDRAWN` and releases
        the freeze: every account of the patient in `ASSISTANCE_HOLD` returns
        to `NOTICE_PERIOD`."

        Design: Corner/cross_cutting_layers/assistance_hold_freezes_eca_on_submit
        """
        ctx = setup_eca_active_account(
            patient_name="Hold Hal", mrn="MRN-HOLD-1", ssn_last4="0056",
            action_type="WAGE_GARNISHMENT",
        )
        account_id = ctx["account"]["id"]
        app = create_application(
            ctx["patient"]["id"], screening_source="STANDARD",
            reported_annual_income_cents=1000000, reported_liquid_assets_cents=0,
        )
        add_member(app["id"], full_name="Hold Hal", relationship="SELF", age=40)
        submit_application(app["id"])
        account = get_account(account_id)
        assert account["collection_posture"] == "ASSISTANCE_HOLD", (
            "submit flips ECA_ACTIVE to ASSISTANCE_HOLD"
        )
        resp = api.create_collection_action(
            account_id, {"action_type": "LIEN"}, COLLECTIONS
        )
        # the account is neither ECA_ELIGIBLE nor free of an open application;
        # either guard's error satisfies the freeze contract.
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_ACCOUNT_NOT_ECA_ELIGIBLE, ApiErrorId.ERR_ASSISTANCE_HOLD_ACTIVE],
        )
        withdraw_application(app["id"])
        account = get_account(account_id)
        assert account["collection_posture"] == "NOTICE_PERIOD", (
            "withdrawal releases the hold back to NOTICE_PERIOD"
        )
        # the 501(r) gates are still met at the same clock (statement
        # 2026-01-01, warning 2026-04-01, clock 2026-05-01)
        account = validate_success(api.evaluate_posture(account_id, COLLECTIONS))
        assert account["collection_posture"] == "ECA_ELIGIBLE"
