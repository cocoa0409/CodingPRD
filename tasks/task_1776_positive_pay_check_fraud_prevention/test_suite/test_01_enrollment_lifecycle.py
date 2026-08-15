"""Enrollment lifecycle: creation defaults, training gate, suspension cycle,
termination gates, OCC, and tier migration."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    activate_enrollment,
    add_user,
    assert_enrollment,
    complete_training,
    create_account,
    create_active_enrollment,
    create_enrollment,
    create_enrollment_payload,
    create_enrollment_user_payload,
    daily_sweep,
    decide,
    get_enrollment,
    get_exception,
    is_valid_uuid,
    make_check_row,
    make_customer_admin_headers,
    make_customer_decision_maker_headers,
    present_item,
    schedule_training,
    set_clock,
    setup_open_exception,
    setup_reverse_tier_exceptions,
    upload_checks,
    validate_error,
    validate_success,
)

BANK_MGR = TEST_USERS["bank_treasury_manager_headers"]
BANK_OPS = TEST_USERS["bank_ops_headers"]


# ----------------------------------------------------------------------
# Enrollment creation
# ----------------------------------------------------------------------

class TestEnrollmentCreate:
    def test_create_applies_documented_defaults(self, api):
        """PRD §3.1: "`deadline_mode` selects the deadline variant and defaults
        to `SAME_DAY_CUTOFF` (the alternative is `ROLLING_HOURS`);
        `decision_window_hours` defaults to 24 and must lie between 1 and 72
        inclusive; `amount_tolerance_cents` defaults to 0 and must be
        non-negative; `payee_score_threshold` defaults to 85 and must lie
        between 0 and 100 inclusive."
        PRD §3.1: "A new enrollment starts in `PENDING_ACTIVATION` with its
        counters zeroed: `open_exception_count` at zero,
        `provisional_credit_outstanding_cents` at zero, and
        `ytd_bank_loss_cents` at zero."

        Design: Corner/entities/enrollment_create_defaults_applied
        """
        data = validate_success(api.create_enrollment(
            create_enrollment_payload(business_name="DefCo"), BANK_MGR), 201)
        assert_enrollment(data)
        assert data["deadline_mode"] == "SAME_DAY_CUTOFF"
        assert data["decision_window_hours"] == 24
        assert data["amount_tolerance_cents"] == 0
        assert data["payee_score_threshold"] == 85
        assert data["stale_days"] == 180
        assert data["status"] == "PENDING_ACTIVATION"
        assert data["open_exception_count"] == 0
        assert data["provisional_credit_outstanding_cents"] == 0
        assert data["ytd_bank_loss_cents"] == 0

    def test_create_rejects_out_of_enum_tier(self, api):
        """PRD §2.10: "required fields present, types correct, enum membership
        valid, amounts positive integers, row schema valid ... shape failures
        yield `ERR_INVALID_REQUEST`".

        Design: Corner/entities/enrollment_create_invalid_enum_rejected
        """
        resp = api.create_enrollment(
            create_enrollment_payload(business_name="BadCo", tier="BASIC"),
            BANK_MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_ignores_client_supplied_system_fields(self, api):
        """PRD §2.4: "`id` (string): a server-minted UUID, with no type prefix."

        Design: Corner/entities/enrollment_system_fields_input_ignored
        """
        payload = create_enrollment_payload(business_name="SysCo")
        payload["id"] = NON_EXISTENT_UUID
        payload["version"] = 99
        data = validate_success(api.create_enrollment(payload, BANK_MGR), 201)
        assert data["id"] != NON_EXISTENT_UUID, (
            "id must be server-minted, not the client-supplied value")
        assert is_valid_uuid(data["id"])
        assert isinstance(data["version"], int)

    def test_create_ignores_client_supplied_computed_fields(self, api):
        """PRD §3.1: "A new enrollment starts in `PENDING_ACTIVATION` with its
        counters zeroed: `open_exception_count` at zero,
        `provisional_credit_outstanding_cents` at zero, and
        `ytd_bank_loss_cents` at zero."

        Design: Corner/entities/enrollment_computed_field_input_ignored
        """
        payload = create_enrollment_payload(business_name="CmpCo")
        payload["open_exception_count"] = 77
        data = validate_success(api.create_enrollment(payload, BANK_MGR), 201)
        assert data["open_exception_count"] == 0

    def test_get_missing_enrollment_returns_not_found(self, api):
        """PRD §2.11: "Identifiers appearing in the URL path or referenced in
        the request body (such as an `enrollment_id`, `account_id`, or
        `presented_item_id`) are validated for existence in left-to-right order,
        and the first identifier that does not resolve to an existing resource
        rejects the request with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_missing_enrollment_returns_404
        """
        resp = api.get_enrollment(NON_EXISTENT_UUID, BANK_MGR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_user_create_with_missing_enrollment_returns_not_found(self, api):
        """PRD §2.11: "Body-referenced links — the account an upload targets,
        the item a liability claim is filed against, the users recorded as
        training attendees — are checked the same way after the path
        identifiers."

        Design: Corner/entities/user_create_with_missing_enrollment_returns_not_found
        """
        resp = api.create_enrollment_user(
            create_enrollment_user_payload(NON_EXISTENT_UUID,
                                           display_name="Ghost",
                                           user_role="ADMIN"), BANK_MGR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ----------------------------------------------------------------------
# Training gate on first activation
# ----------------------------------------------------------------------

class TestActivationTrainingGate:
    def test_activation_without_any_session_rejected(self, api):
        """PRD §3.1: "Activation from `PENDING_ACTIVATION` to `ACTIVE` is
        performed by a `BankTreasuryManager` and requires at least one
        `COMPLETED` training session for the enrollment; without one the request
        is rejected with `ERR_ENROLLMENT_NOT_ACTIVATABLE`."

        Design: Difficulty/cross_entity_state_dependency/activation_requires_completed_training
        """
        enr = create_enrollment("GateCo", "POSITIVE_PAY", "PAY")
        add_user(enr["id"], "Admin", "ADMIN")
        resp = api.activate_enrollment(enr["id"], BANK_MGR)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVATABLE)

    def test_activation_with_uncompleted_session_then_completed(self, api):
        """PRD §3.1: "Activation from `PENDING_ACTIVATION` to `ACTIVE` is
        performed by a `BankTreasuryManager` and requires at least one
        `COMPLETED` training session for the enrollment; without one the request
        is rejected with `ERR_ENROLLMENT_NOT_ACTIVATABLE`."

        Design: Difficulty/cross_entity_state_dependency/activation_requires_completed_training
        """
        enr = create_enrollment("GateCo2", "POSITIVE_PAY", "PAY")
        adm = add_user(enr["id"], "Admin", "ADMIN")
        sess = schedule_training(enr["id"])
        resp = api.activate_enrollment(enr["id"], BANK_MGR)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVATABLE)
        completed = validate_success(api.complete_training_session(
            sess["id"], [adm["id"]], BANK_OPS))
        assert completed["status"] == "COMPLETED"
        activated = validate_success(api.activate_enrollment(enr["id"], BANK_MGR))
        assert activated["status"] == "ACTIVE"


# ----------------------------------------------------------------------
# Suspend / reactivate cycle
# ----------------------------------------------------------------------

class TestSuspendReactivateCycle:
    def _setup(self):
        return setup_open_exception(tier="REVERSE_POSITIVE_PAY",
                                    default_decision="PAY",
                                    business_name="CycleCo")

    def test_decision_rejected_while_suspended(self, api):
        """PRD §3.1: "While an enrollment is `SUSPENDED`, all customer-side
        writes are rejected with `ERR_ENROLLMENT_NOT_ACTIVE`: issue-file
        uploads, check voids, exception decisions, ACH rule writes, and
        liability filings all fail, while item matching, sweeps, and default
        processing continue to run."

        Design: Difficulty/non_linear_state_machine/enrollment_suspend_reactivate_cycle_gates_decisions
        """
        b = self._setup()
        suspended = validate_success(
            api.suspend_enrollment(b["enrollment"]["id"], BANK_MGR))
        assert suspended["status"] == "SUSPENDED"
        resp = api.decide_exception(b["exception_id"], "PAY",
                                    b["headers"]["DECISION_MAKER"])
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)

    def test_reactivation_skips_training_gate_and_decision_succeeds(self, api):
        """PRD §3.1: "Re-activation from `SUSPENDED` does not re-check the
        training gate — that gate applies only to the initial activation."
        PRD §3.5: "A `PAY` decision moves the exception to `DECISIONED_PAY`".

        Design: Difficulty/non_linear_state_machine/enrollment_suspend_reactivate_cycle_gates_decisions
        """
        b = self._setup()
        validate_success(api.suspend_enrollment(b["enrollment"]["id"], BANK_MGR))
        reactivated = validate_success(
            api.activate_enrollment(b["enrollment"]["id"], BANK_MGR))
        assert reactivated["status"] == "ACTIVE"
        decided = decide(b["exception_id"], "PAY",
                         b["headers"]["DECISION_MAKER"])
        assert decided["status"] == "DECISIONED_PAY"


# ----------------------------------------------------------------------
# Decision blocked by parent enrollment state
# ----------------------------------------------------------------------

class TestDecisionBlockedWhileSuspended:
    def test_decision_on_open_exception_rejected_when_suspended(self, api):
        """PRD §3.5: "The decision enforces four preconditions, evaluated in
        order — enrollment state first (a `TERMINATED` enrollment rejects with
        `ERR_ENROLLMENT_TERMINATED`, any other non-`ACTIVE` status with
        `ERR_ENROLLMENT_NOT_ACTIVE`)".

        Design: Difficulty/cross_entity_state_dependency/decision_blocked_while_enrollment_suspended
        """
        b = setup_open_exception(tier="REVERSE_POSITIVE_PAY",
                                 default_decision="PAY", business_name="GateCo2")
        validate_success(api.suspend_enrollment(b["enrollment"]["id"], BANK_MGR))
        resp = api.decide_exception(b["exception_id"], "PAY",
                                    b["headers"]["DECISION_MAKER"])
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)

    def test_suspension_blocks_without_resolving_exception(self, api):
        """PRD §3.1: "While an enrollment is `SUSPENDED`, all customer-side
        writes are rejected with `ERR_ENROLLMENT_NOT_ACTIVE` ... while item
        matching, sweeps, and default processing continue to run."

        Design: Difficulty/cross_entity_state_dependency/decision_blocked_while_enrollment_suspended
        """
        b = setup_open_exception(tier="REVERSE_POSITIVE_PAY",
                                 default_decision="PAY", business_name="GateCo3")
        validate_success(api.suspend_enrollment(b["enrollment"]["id"], BANK_MGR))
        api.decide_exception(b["exception_id"], "PAY",
                             b["headers"]["DECISION_MAKER"])
        exc = get_exception(b["exception_id"])
        assert exc["status"] == "OPEN", (
            "suspension blocks the decision; it must not resolve the exception")


# ----------------------------------------------------------------------
# Termination
# ----------------------------------------------------------------------

class TestTermination:
    def test_terminate_blocked_with_open_exception(self, api):
        """PRD §3.1: "Termination moves an enrollment from `ACTIVE` or
        `SUSPENDED` to the terminal `TERMINATED` state, but only once the book
        is settled: every account of the enrollment must be `CLOSED` and the
        enrollment's `open_exception_count` must be zero, otherwise the request
        is rejected with `ERR_ENROLLMENT_NOT_SETTLED`."

        Design: Corner/state_machines/terminate_blocked_with_open_exception
        """
        b = setup_open_exception(tier="REVERSE_POSITIVE_PAY",
                                 default_decision="PAY", business_name="TermCo")
        resp = api.terminate_enrollment(b["enrollment"]["id"], BANK_MGR)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_SETTLED)
        enr = get_enrollment(b["enrollment"]["id"])
        assert enr["open_exception_count"] == 1

    def test_terminated_enrollment_rejects_upload(self, api):
        """PRD §3.3: "the enrollment must be `ACTIVE` (a write against a
        `TERMINATED` enrollment fails first with `ERR_ENROLLMENT_TERMINATED`,
        and any other non-active status fails with `ERR_ENROLLMENT_NOT_ACTIVE`)".

        Design: Corner/state_machines/terminate_then_upload_rejected
        """
        b = create_active_enrollment("DeadCo", "POSITIVE_PAY", "PAY")
        closed = validate_success(
            api.close_account(b["account"]["id"], BANK_MGR))
        assert closed["status"] == "CLOSED"
        terminated = validate_success(
            api.terminate_enrollment(b["enrollment"]["id"], BANK_MGR))
        assert terminated["status"] == "TERMINATED"
        resp = api.upload_issue_file(
            {"enrollment_id": b["enrollment"]["id"],
             "account_id": b["account"]["id"], "file_reference": "F-DEAD",
             "rows": [make_check_row("1")]},
            b["headers"]["ADMIN"])
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_TERMINATED)

    def test_customer_write_blocked_on_pending_enrollment(self, api):
        """PRD §3.3: "Whole-file gates run before any row is processed: the
        enrollment must be `ACTIVE` (a write against a `TERMINATED` enrollment
        fails first with `ERR_ENROLLMENT_TERMINATED`, and any other non-active
        status fails with `ERR_ENROLLMENT_NOT_ACTIVE`)".

        Design: Corner/validations/customer_write_blocked_on_pending_enrollment
        """
        enr = create_enrollment("PendCo", "POSITIVE_PAY", "PAY")
        acct = create_account(enr["id"], "830002")
        adm = add_user(enr["id"], "Admin", "ADMIN")
        resp = api.upload_issue_file(
            {"enrollment_id": enr["id"], "account_id": acct["id"],
             "file_reference": "F-PEND", "rows": [make_check_row("1")]},
            make_customer_admin_headers(adm["id"]))
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)


# ----------------------------------------------------------------------
# Optimistic concurrency on enrollment writes
# ----------------------------------------------------------------------

class TestEnrollmentOcc:
    def test_stale_config_patch_rejected_then_current_succeeds(self, api):
        """PRD §2.7: "If the supplied expected version does not equal the parent
        entity's current `version` — because another accepted write has advanced
        the version since the client last read the entity — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.4: "`version` (integer): starts at creation and increments by one
        on every mutation of the resource."

        Design: Corner/complexity_layers/occ_enrollment_patch_stale
        """
        enr = create_enrollment("OccCo", "POSITIVE_PAY", "PAY")
        v1 = enr["version"]
        patched = validate_success(api.patch_enrollment(
            enr["id"], {"expected_enrollment_version": v1,
                        "decision_window_hours": 30}, BANK_MGR))
        assert patched["version"] == v1 + 1
        resp = api.patch_enrollment(
            enr["id"], {"expected_enrollment_version": v1,
                        "decision_window_hours": 36}, BANK_MGR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        patched2 = validate_success(api.patch_enrollment(
            enr["id"], {"expected_enrollment_version": patched["version"],
                        "decision_window_hours": 36}, BANK_MGR))
        assert patched2["version"] == patched["version"] + 1
        assert patched2["decision_window_hours"] == 36

    def test_stale_tier_change_rejected_then_current_succeeds(self, api):
        """PRD §2.7: "A tier change on an enrollment must likewise carry
        `expected_enrollment_version` matching the enrollment's current
        `version`."
        PRD §3.1: "An accepted tier change sets `tier` to `new_tier` and
        increments the enrollment's `version`."

        Design: Corner/complexity_layers/occ_change_tier_stale
        """
        b = create_active_enrollment("OccTCo", "POSITIVE_PAY", "PAY",
                                     with_account=False)
        v2 = b["enrollment"]["version"]
        patched = validate_success(api.patch_enrollment(
            b["enrollment"]["id"], {"expected_enrollment_version": v2,
                                    "decision_window_hours": 30}, BANK_MGR))
        assert patched["version"] == v2 + 1
        resp = api.change_tier(
            b["enrollment"]["id"],
            {"new_tier": "REVERSE_POSITIVE_PAY",
             "expected_enrollment_version": v2}, BANK_MGR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        migrated = validate_success(api.change_tier(
            b["enrollment"]["id"],
            {"new_tier": "REVERSE_POSITIVE_PAY",
             "expected_enrollment_version": patched["version"]}, BANK_MGR))
        assert migrated["tier"] == "REVERSE_POSITIVE_PAY"

    def test_shape_failure_beats_stale_version(self, api):
        """PRD §2.10: "shape failures yield `ERR_INVALID_REQUEST` and surface
        before any resource lookup" and request shape (priority 4) is evaluated
        before optimistic concurrency (priority 6): "6. **Optimistic
        concurrency** — the expected-version checks of §2.7, yielding
        `ERR_STALE_VERSION`."

        Design: Corner/validations/shape_beats_occ_stale_version
        """
        enr = create_enrollment("OrdCo", "POSITIVE_PAY", "PAY")
        v1 = enr["version"]
        patched = validate_success(api.patch_enrollment(
            enr["id"], {"expected_enrollment_version": v1,
                        "decision_window_hours": 30}, BANK_MGR))
        assert patched["version"] == v1 + 1
        resp = api.patch_enrollment(
            enr["id"], {"expected_enrollment_version": v1,
                        "default_decision": "HOLD"}, BANK_MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ----------------------------------------------------------------------
# Tier migration
# ----------------------------------------------------------------------

class TestTierMigration:
    def test_change_tier_then_upload_forbidden(self, api):
        """PRD §3.3: "the tier must not be `REVERSE_POSITIVE_PAY`, since
        reverse-tier customers by definition submit no issue files
        (`ERR_TIER_FORBIDS_ISSUE_FILES`)".
        PRD §3.1: "An accepted tier change sets `tier` to `new_tier`".

        Design: Corner/endpoints/change_tier_happy_path_then_upload_forbidden
        """
        b = create_active_enrollment("MigCo", "POSITIVE_PAY", "PAY")
        v = b["enrollment"]["version"]
        migrated = validate_success(api.change_tier(
            b["enrollment"]["id"],
            {"new_tier": "REVERSE_POSITIVE_PAY",
             "expected_enrollment_version": v}, BANK_MGR))
        assert migrated["tier"] == "REVERSE_POSITIVE_PAY"
        resp = api.upload_issue_file(
            {"enrollment_id": b["enrollment"]["id"],
             "account_id": b["account"]["id"], "file_reference": "F-MIG",
             "rows": [make_check_row("1")]},
            b["headers"]["ADMIN"])
        validate_error(resp, ApiErrorId.ERR_TIER_FORBIDS_ISSUE_FILES)

    def test_change_tier_blocked_by_open_exception(self, api):
        """PRD §3.1: "Two gates apply, both rejecting with
        `ERR_TIER_CHANGE_NOT_ALLOWED`: the enrollment's `open_exception_count`
        must be zero".

        Design: Corner/endpoints/change_tier_blocked_by_open_exceptions
        """
        b = setup_open_exception(tier="REVERSE_POSITIVE_PAY",
                                 default_decision="PAY", business_name="BlkTierCo")
        v = b["enrollment"]["version"]
        resp = api.change_tier(
            b["enrollment"]["id"],
            {"new_tier": "POSITIVE_PAY", "expected_enrollment_version": v},
            BANK_MGR)
        validate_error(resp, ApiErrorId.ERR_TIER_CHANGE_NOT_ALLOWED)

    def test_reverse_tier_volume_boundary_75_vs_76(self, api):
        """PRD §3.1: "a migration to `REVERSE_POSITIVE_PAY` is permitted only
        when the enrollment's issued-check volume over the trailing ninety days
        — counted across all of its accounts, inclusive of both window
        endpoints, and counting rows in every status including `REGISTERED`,
        `CONSUMED`, `VOIDED`, and `STALE_DATED` — is at most 75 rows; a 76th row
        in the window makes the enrollment ineligible."

        Design: Corner/complexity_layers/reverse_tier_volume_boundary
        """
        bundles = {}
        for label, count, acct_no, trainer in (("A", 75, "870001", "tr-A"),
                                               ("B", 76, "870002", "tr-B")):
            b = create_active_enrollment(f"Vol{label}", "POSITIVE_PAY", "PAY",
                                         account_number=acct_no,
                                         trainer_id=trainer)
            rows = [make_check_row(str(i)) for i in range(1, count + 1)]
            upload = upload_checks(b["enrollment"]["id"], b["account"]["id"],
                                   f"F-VOL{label}", rows, b["headers"]["ADMIN"])
            assert upload["accepted_row_count"] == count
            bundles[label] = b
        migrated = validate_success(api.change_tier(
            bundles["A"]["enrollment"]["id"],
            {"new_tier": "REVERSE_POSITIVE_PAY",
             "expected_enrollment_version": bundles["A"]["enrollment"]["version"]},
            BANK_MGR))
        assert migrated["tier"] == "REVERSE_POSITIVE_PAY"
        resp = api.change_tier(
            bundles["B"]["enrollment"]["id"],
            {"new_tier": "REVERSE_POSITIVE_PAY",
             "expected_enrollment_version": bundles["B"]["enrollment"]["version"]},
            BANK_MGR)
        validate_error(resp, ApiErrorId.ERR_TIER_CHANGE_NOT_ALLOWED)


# ----------------------------------------------------------------------
# Default-decision snapshot pinning
# ----------------------------------------------------------------------

class TestDefaultDecisionSnapshot:
    def test_snapshot_governs_sweep_after_config_edit(self, api):
        """PRD §3.1: "Editing `default_decision` changes only future exceptions —
        the `default_decision_snapshot` pinned on each existing `OPEN` exception
        is not retro-changed."
        PRD §3.5: "An exception still `OPEN` whose `decision_deadline_at` is
        strictly earlier than the logical clock is defaulted according to its
        `default_decision_snapshot`".

        Design: Corner/complexity_layers/default_decision_snapshot_pinned
        """
        b = setup_open_exception(tier="REVERSE_POSITIVE_PAY",
                                 default_decision="RETURN",
                                 business_name="SnapCo")
        exc = get_exception(b["exception_id"])
        assert exc["default_decision_snapshot"] == "RETURN"
        validate_success(api.patch_enrollment(
            b["enrollment"]["id"],
            {"expected_enrollment_version": b["enrollment"]["version"],
             "default_decision": "PAY"}, BANK_MGR))
        set_clock("2026-08-04T09:00:00Z")
        daily_sweep(b["enrollment"]["id"])
        exc = get_exception(b["exception_id"])
        assert exc["status"] == "DEFAULTED_RETURN", (
            "the snapshot pinned at creation must govern the sweep outcome, "
            "not the enrollment's new PAY default")
