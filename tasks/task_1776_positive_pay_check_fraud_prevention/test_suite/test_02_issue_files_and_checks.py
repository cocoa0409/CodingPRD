"""Issued-check file intake: row validation, partial acceptance, idempotent
replay, pagination, and account-state gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_issue_file_upload,
    create_account,
    create_active_enrollment,
    create_enrollment,
    add_user,
    get_check_by_number,
    list_checks,
    make_check_row,
    make_customer_admin_headers,
    present_item,
    setup_paid_item,
    upload_checks,
    validate_error,
    validate_paginated,
    validate_success,
)

BANK_MGR = TEST_USERS["bank_treasury_manager_headers"]
BANK_OPS = TEST_USERS["bank_ops_headers"]


class TestIssuedCheckLifecycle:
    def test_accepted_rows_become_registered_checks(self, api):
        """PRD §3.3: "Every accepted row creates an `IssuedCheck` in
        `REGISTERED` status, linked to its `account_id` and the `issue_file_id`
        of the upload that registered it".
        PRD §3.3: "`ACCEPTED` when every row produced a check".

        Design: Corner/state_machines/issued_check_initial_state_registered
        """
        b = create_active_enrollment("InitCo", "POSITIVE_PAY", "PAY",
                                     account_number="810001")
        upload = upload_checks(b["enrollment"]["id"], b["account"]["id"],
                               "F-INIT", [make_check_row("1")],
                               b["headers"]["ADMIN"])
        assert_issue_file_upload(upload)
        assert upload["status"] == "ACCEPTED"
        assert upload["accepted_row_count"] == 1
        checks = list_checks({"issue_file_id": upload["id"]})
        assert len(checks) == 1
        assert checks[0]["status"] == "REGISTERED"

    def test_void_of_consumed_check_rejected(self, api):
        """PRD §3.3: "the check to still be `REGISTERED` — voiding a
        `CONSUMED`, already-`VOIDED`, or `STALE_DATED` check is rejected with
        `ERR_CHECK_NOT_VOIDABLE`."

        Design: Corner/state_machines/void_consumed_check_rejected
        """
        b = setup_paid_item(800, payee="V CO", business_name="VoidCo",
                            account_number="810002", check_number="701",
                            user_roles=("ADMIN",))
        assert b["check"]["status"] == "CONSUMED"
        resp = api.void_issued_check(b["check"]["id"], b["headers"]["ADMIN"])
        validate_error(resp, ApiErrorId.ERR_CHECK_NOT_VOIDABLE)


class TestIssueFileIdempotency:
    def test_identical_replay_returns_original_upload(self, api):
        """PRD §2.9: "if the reference has been seen before for that enrollment
        and the canonicalized rows hash identically (the server stores this as
        `payload_hash`, a SHA-256 over the canonicalized rows array), the server
        replays the original upload response rather than processing the rows
        again".

        Design: Corner/complexity_layers/issue_file_idempotent_replay
        """
        b = create_active_enrollment("ReplayCo", "POSITIVE_PAY", "PAY",
                                     account_number="860004")
        rows = [make_check_row("1")]
        first = upload_checks(b["enrollment"]["id"], b["account"]["id"],
                              "F-REPLAY", rows, b["headers"]["ADMIN"])
        second = upload_checks(b["enrollment"]["id"], b["account"]["id"],
                               "F-REPLAY", rows, b["headers"]["ADMIN"])
        assert second["id"] == first["id"], (
            "identical replay must return the original upload record")
        checks, meta = validate_paginated(api.list_issued_checks(
            BANK_OPS, params={"account_id": b["account"]["id"]}))
        assert meta["total_count"] == 1, "replay must not create duplicate checks"

    def test_used_reference_with_divergent_rows_conflicts(self, api):
        """PRD §2.9: "if the reference has been seen with a different payload
        hash, the request is rejected with `ERR_IDEMPOTENCY_CONFLICT`
        (HTTP 409)".

        Design: Corner/complexity_layers/issue_file_reference_conflict
        """
        b = create_active_enrollment("ConfCo", "POSITIVE_PAY", "PAY",
                                     account_number="860005")
        upload_checks(b["enrollment"]["id"], b["account"]["id"], "F-CONF",
                      [make_check_row("1")], b["headers"]["ADMIN"])
        resp = api.upload_issue_file(
            {"enrollment_id": b["enrollment"]["id"],
             "account_id": b["account"]["id"], "file_reference": "F-CONF",
             "rows": [make_check_row("2", 200, "Q")]},
            b["headers"]["ADMIN"])
        validate_error(resp, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT)


class TestIssuedCheckPagination:
    def test_default_limit_offset_and_check_number_filter(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §3.3: "The issued-check list can be filtered by `account_id`,
        `issue_file_id`, `consumed_by_item_id`, `status`, and `check_number`."

        Design: Corner/complexity_layers/pagination_issued_checks_defaults
        """
        b = create_active_enrollment("PageCo", "POSITIVE_PAY", "PAY",
                                     account_number="860006")
        rows = [make_check_row(str(i)) for i in range(1, 13)]
        upload = upload_checks(b["enrollment"]["id"], b["account"]["id"],
                               "F-PAGE", rows, b["headers"]["ADMIN"])
        assert upload["accepted_row_count"] == 12

        page1, meta1 = validate_paginated(api.list_issued_checks(
            BANK_OPS, params={"account_id": b["account"]["id"]}))
        assert len(page1) == 10 and meta1["limit"] == 10
        assert meta1["total_count"] == 12 and meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_issued_checks(
            BANK_OPS, params={"account_id": b["account"]["id"], "offset": 10}))
        assert len(page2) == 2 and meta2["total_count"] == 12
        assert meta2["has_more"] is False

        filtered, meta3 = validate_paginated(api.list_issued_checks(
            BANK_OPS, params={"account_id": b["account"]["id"],
                              "check_number": "7"}))
        assert meta3["total_count"] == 1 and len(filtered) == 1


class TestBulkRowValidation:
    def test_partial_acceptance_reports_each_bad_row(self, api):
        """PRD §3.3: "Rows that survive the gates are validated independently,
        in row order, and the upload accepts partial success."
        PRD §3.3: "Per-row rejections are collected on the upload record as
        `row_errors`, an array of objects giving the `row_index`, the offending
        `check_number`, and a human-readable `reason`."
        PRD §3.3: "`PARTIALLY_ACCEPTED` when some did".

        Design: Corner/complexity_layers/issue_file_bulk_partial_accept
        """
        b = create_active_enrollment("PartCo", "POSITIVE_PAY", "PAY",
                                     account_number="860007")
        rows = [make_check_row("1", 100, "GOOD"),
                make_check_row("1", 200, "DUP"),
                make_check_row("3", 0, "BAD")]
        upload = upload_checks(b["enrollment"]["id"], b["account"]["id"],
                               "F-PART", rows, b["headers"]["ADMIN"])
        assert upload["status"] == "PARTIALLY_ACCEPTED"
        assert upload["row_count"] == 3
        assert upload["accepted_row_count"] == 1
        assert upload["rejected_row_count"] == 2
        error_indexes = sorted(e["row_index"] for e in upload["row_errors"])
        assert error_indexes == [1, 2], (
            "row 1 is a within-file duplicate of row 0; row 2 has a "
            "non-positive amount")
        checks, meta = validate_paginated(api.list_issued_checks(
            BANK_OPS, params={"account_id": b["account"]["id"]}))
        assert meta["total_count"] == 1
        assert checks[0]["status"] == "REGISTERED"

    def test_fully_invalid_file_is_rejected_and_creates_nothing(self, api):
        """PRD §3.3: "A row is rejected when its `check_number` is not 1 to 12
        digits, when `amount_cents` is not a positive integer, when `payee_name`
        is not 1 to 80 characters, or when `issue_date` is not a valid ISO
        calendar date on or before the current logical date."
        PRD §3.3: "`REJECTED` when none did."

        Design: Corner/complexity_layers/issue_file_bulk_all_rejected
        """
        b = create_active_enrollment("AllBadCo", "POSITIVE_PAY", "PAY",
                                     account_number="860008")
        rows = [make_check_row("1", -5, "NEG"),
                make_check_row("2", 100, "FUTURE", "2027-01-01")]
        upload = upload_checks(b["enrollment"]["id"], b["account"]["id"],
                               "F-BAD", rows, b["headers"]["ADMIN"])
        assert upload["status"] == "REJECTED"
        assert upload["accepted_row_count"] == 0
        checks, meta = validate_paginated(api.list_issued_checks(
            BANK_OPS, params={"account_id": b["account"]["id"]}))
        assert meta["total_count"] == 0


class TestUploadAccountStateGates:
    def _setup_closed_account(self, api):
        b = create_active_enrollment("CloseCo", "PAYEE_POSITIVE_PAY", "PAY",
                                     account_number="990005")
        closed = validate_success(api.close_account(b["account"]["id"], BANK_MGR))
        assert closed["status"] == "CLOSED"
        return b

    def test_upload_to_closed_account_rejected(self, api):
        """PRD §3.3: "the target account must belong to the named enrollment and
        be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE` — ingesting against a `CLOSED`
        account fails the same way)".

        Design: Difficulty/cross_entity_state_dependency/upload_blocked_when_account_closed
        """
        b = self._setup_closed_account(api)
        resp = api.upload_issue_file(
            {"enrollment_id": b["enrollment"]["id"],
             "account_id": b["account"]["id"], "file_reference": "F-CLOSED",
             "rows": [make_check_row("1")]},
            b["headers"]["ADMIN"])
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)

    def test_rejected_upload_creates_no_upload_record(self, api):
        """PRD §3.3: "Whole-file gates run before any row is processed: the
        enrollment must be `ACTIVE` (a write against a `TERMINATED` enrollment
        fails first with `ERR_ENROLLMENT_TERMINATED`, and any other non-active
        status fails with `ERR_ENROLLMENT_NOT_ACTIVE`); the tier must not be
        `REVERSE_POSITIVE_PAY`, since reverse-tier customers by definition
        submit no issue files (`ERR_TIER_FORBIDS_ISSUE_FILES`); and the target
        account must belong to the named enrollment and be `ACTIVE`
        (`ERR_ACCOUNT_NOT_ACTIVE` — ingesting against a `CLOSED` account fails
        the same way)."

        Design: Difficulty/cross_entity_state_dependency/upload_blocked_when_account_closed
        """
        b = self._setup_closed_account(api)
        validate_error(api.upload_issue_file(
            {"enrollment_id": b["enrollment"]["id"],
             "account_id": b["account"]["id"], "file_reference": "F-CLOSED",
             "rows": [make_check_row("1")]},
            b["headers"]["ADMIN"]), ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)
        uploads, meta = validate_paginated(api.list_issue_files(
            BANK_OPS, params={"enrollment_id": b["enrollment"]["id"]}))
        assert meta["total_count"] == 0, "a gated upload must not create a record"


class TestStateBeatsIdempotency:
    def _setup_suspended_with_used_reference(self, api):
        b = create_active_enrollment("DupCo", "PAYEE_POSITIVE_PAY", "RETURN",
                                     account_number="980002")
        upload_checks(b["enrollment"]["id"], b["account"]["id"], "DUP-REF",
                      [make_check_row("501", 1000, "ALPHA")],
                      b["headers"]["ADMIN"])
        validate_success(api.suspend_enrollment(b["enrollment"]["id"], BANK_MGR))
        return b

    def test_divergent_replay_while_suspended_yields_state_error(self, api):
        """PRD §3.3: "Whole-file gates run before any row is processed: the
        enrollment must be `ACTIVE` ... Idempotent replay is then resolved on
        `file_reference` exactly as §2.9 describes."
        PRD §2.10: state preconditions (priority 7) precede uniqueness and
        policy constraints (priority 9), which include
        `ERR_IDEMPOTENCY_CONFLICT`.

        Design: Difficulty/priority_pair_validation_conflict/enrollment_suspended_beats_idempotency_conflict
        """
        b = self._setup_suspended_with_used_reference(api)
        resp = api.upload_issue_file(
            {"enrollment_id": b["enrollment"]["id"],
             "account_id": b["account"]["id"], "file_reference": "DUP-REF",
             "rows": [make_check_row("502", 2000, "BETA")]},
            b["headers"]["ADMIN"])
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)

    def test_identical_replay_while_suspended_yields_state_error(self, api):
        """PRD §3.3: "Whole-file gates run before any row is processed: the
        enrollment must be `ACTIVE` (a write against a `TERMINATED` enrollment
        fails first with `ERR_ENROLLMENT_TERMINATED`, and any other non-active
        status fails with `ERR_ENROLLMENT_NOT_ACTIVE`)" — the gate precedes
        replay resolution, so even an identical replay is rejected while
        suspended.

        Design: Difficulty/priority_pair_validation_conflict/enrollment_suspended_beats_idempotency_conflict
        """
        b = self._setup_suspended_with_used_reference(api)
        resp = api.upload_issue_file(
            {"enrollment_id": b["enrollment"]["id"],
             "account_id": b["account"]["id"], "file_reference": "DUP-REF",
             "rows": [make_check_row("501", 1000, "ALPHA")]},
            b["headers"]["ADMIN"])
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)
