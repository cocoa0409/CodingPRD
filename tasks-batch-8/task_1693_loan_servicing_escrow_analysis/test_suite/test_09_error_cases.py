"""RESPA error resolution: deadlines, SoD, terminal lockdown, cascade."""
from test_helpers import (
    CO1,
    CO2,
    EA1,
    ApiErrorId,
    advance_case_to_investigating,
    assert_error_case,
    create_active_bare_loan,
    file_error_case,
    get_account,
    get_ledger,
    get_success_data,
    make_borrower_headers,
    resolve_case,
    send_notice,
    set_clock,
    setup_effective_analysis,
    validate_error,
    validate_success,
)


class TestErrorCaseFiling:
    def test_duplicate_active_case_rejected_other_type_allowed(self, api):
        """PRD: "A second non-terminal case with the same loan and `error_type`
        is rejected with `ERR_DUPLICATE_ACTIVE_CASE`."

        Design: Corner/validations/duplicate_active_case_rejected
        """
        loan = create_active_bare_loan(loan_number="LN-VAL-1",
                                       borrower_name="Dup Case")
        first = file_error_case(loan["id"], error_type="ANALYSIS_ERROR",
                                description="first")
        assert_error_case(first)
        assert first["status"] == "RECEIVED"

        resp = api.create_error_case(
            loan["id"], {"error_type": "ANALYSIS_ERROR", "description": "duplicate"},
            make_borrower_headers(loan["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_CASE)

        other = file_error_case(loan["id"], error_type="UNTIMELY_DISBURSEMENT",
                                description="different type ok")
        assert other["status"] == "RECEIVED", (
            "a different error_type on the same loan is allowed")


class TestBusinessDayDeadlines:
    def test_ack_deadline_skips_weekends_and_labor_day(self, api):
        """PRD: "`ack_deadline` is five business days after receipt — so a case
        received Friday 2026-08-07 has an acknowledgment deadline of Friday
        2026-08-14, and one received Friday 2026-09-04 lands on Monday
        2026-09-14 because Labor Day is skipped."
        PRD: "stamping `acknowledged_at` and deriving `ack_timeliness` as
        `ON_TIME` when the acknowledgment date is on or before `ack_deadline`,
        else `LATE` — a late acknowledgment is flagged, never blocked."

        Design: Corner/calculations/business_day_ack_deadline_skips_holiday
        """
        loan = create_active_bare_loan(loan_number="LN-CAL-7",
                                       borrower_name="Biz Day")
        set_clock("2026-08-07T00:00:00Z")
        case_aug = file_error_case(loan["id"], error_type="DISBURSEMENT_FAILURE",
                                   description="Tax bill not paid")
        set_clock("2026-09-04T00:00:00Z")
        case_sep = file_error_case(loan["id"], error_type="ANALYSIS_ERROR",
                                   description="Analysis wrong")
        assert case_sep["ack_deadline"] == "2026-09-14", (
            "weekend plus Labor Day 2026-09-07 are skipped")
        assert case_aug["ack_deadline"] == "2026-08-14"

        set_clock("2026-09-14T00:00:00Z")
        acked_sep = validate_success(api.acknowledge_case(case_sep["id"], CO1), 200)
        assert acked_sep["ack_timeliness"] == "ON_TIME", (
            "acknowledged on the deadline day")

        set_clock("2026-09-15T00:00:00Z")
        acked_aug = validate_success(api.acknowledge_case(case_aug["id"], CO1), 200)
        assert acked_aug["ack_timeliness"] == "LATE", (
            "acknowledged a month past its 2026-08-14 deadline; flagged, not blocked")
        assert acked_aug["status"] == "ACKNOWLEDGED"


class TestExtensionWindow:
    def test_extend_after_thirty_business_day_deadline_rejected(self, api):
        """PRD: "Extension (`INVESTIGATING` → `EXTENDED`) must be requested on
        or before the original thirty-business-day deadline — afterwards it is
        `ERR_EXTENSION_WINDOW_PASSED`"
        PRD: "`resolution_deadline` is thirty business days after receipt, or
        forty-five once extended."

        Design: Corner/validations/extension_after_30bd_deadline_rejected
        """
        loan = create_active_bare_loan(loan_number="LN-VAL-12",
                                       borrower_name="Ex Tend")
        set_clock("2026-08-07T00:00:00Z")
        case = file_error_case(loan["id"], error_type="FORCE_PLACEMENT_ERROR",
                               description="Wrongly force-placed")
        advance_case_to_investigating(case["id"], investigator="ea_9")

        # Thirty business days after Friday 2026-08-07 (Labor Day skipped) is
        # Monday 2026-09-21; the extension on 2026-09-22 is past the window.
        case_mid = validate_success(api.get_error_case(case["id"], CO1), 200)
        assert case_mid["resolution_deadline"] == "2026-09-21"

        set_clock("2026-09-22T00:00:00Z")
        resp = api.extend_case(case["id"], CO1)
        validate_error(resp, ApiErrorId.ERR_EXTENSION_WINDOW_PASSED)

        case_after = validate_success(api.get_error_case(case["id"], CO1), 200)
        assert case_after["status"] == "INVESTIGATING", "rejected extension changes nothing"
        assert case_after["resolution_deadline"] == "2026-09-21"


class TestResolutionSoD:
    def test_investigator_cannot_resolve_own_case(self, api):
        """PRD: "Resolution is the third segregation-of-duties checkpoint: the
        resolving `ComplianceOfficer`'s `X-User-ID` must differ from
        `assigned_to_user_id`, else `ERR_SOD_VIOLATION`."
        PRD: "An `outcome` of `NO_ERROR` lands in `RESOLVED_NO_ERROR` with
        `resolved_at`, `resolved_by_user_id`, and `resolution_timeliness` —
        `ON_TIME` when the resolution date is on or before
        `resolution_deadline`, else `LATE` — and no ledger activity."

        Design: Corner/rbac/sod_resolver_is_investigator_rejected
        """
        loan = create_active_bare_loan(loan_number="LN-RBAC-4",
                                       borrower_name="Sod Resolve")
        # Filed at the default clock 2026-08-01.
        case = file_error_case(loan["id"], error_type="UNTIMELY_DISBURSEMENT",
                               description="late tax payment")
        advance_case_to_investigating(case["id"], investigator="co_2")

        resp = api.resolve_case(case["id"],
                                {"outcome": "NO_ERROR",
                                 "resolution_note": "self-review attempt"}, CO2)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        resolved = resolve_case(case["id"], outcome="NO_ERROR",
                                resolution_note="independent review")
        assert resolved["status"] == "RESOLVED_NO_ERROR"
        assert resolved["resolved_by_user_id"] == "co_1"
        assert resolved["resolution_deadline"] == "2026-09-14", (
            "thirty business days after 2026-08-01")
        assert resolved["resolution_timeliness"] == "ON_TIME", (
            "resolved 2026-08-01, on or before the 2026-09-14 deadline")


class TestTerminalCaseLockdown:
    def test_resolve_already_resolved_case_rejected(self, api):
        """PRD: "`RESOLVED_CORRECTED`, `RESOLVED_NO_ERROR`, and
        `DISMISSED_NOT_COVERED` are all terminal"
        PRD: "then terminal-state lockout (`ERR_ALREADY_TERMINAL`, HTTP 409)"

        Design: Corner/state_machines/terminal_case_lockdown
        """
        loan = create_active_bare_loan(loan_number="LN-SM-3",
                                       borrower_name="Ter Minal")
        case = file_error_case(loan["id"], error_type="PAYMENT_APPLICATION_ERROR",
                               description="Payment misapplied")
        advance_case_to_investigating(case["id"], investigator="ea_9")
        resolve_case(case["id"], outcome="NO_ERROR",
                     resolution_note="Ledger verified correct")

        resp = api.resolve_case(case["id"],
                                {"outcome": "NO_ERROR", "resolution_note": "again"}, CO1)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

        case_after = validate_success(api.get_error_case(case["id"], CO1), 200)
        assert case_after["status"] == "RESOLVED_NO_ERROR", "terminal state unchanged"


class TestErrorCorrectionCascade:
    def _setup_effective_with_case(self, api):
        """Finalized analysis (shortage scenario, balance 60000), notice SENT,
        and an ANALYSIS_ERROR case INVESTIGATING (assignee ea_9)."""
        ctx = setup_effective_analysis(loan_number="LN-CAS-1")
        send_notice(ctx["notice"]["id"])
        case = file_error_case(ctx["loan"]["id"], error_type="ANALYSIS_ERROR",
                               description="Tax installment understated in annual analysis",
                               asserted_amount_cents=25_000)
        advance_case_to_investigating(case["id"], investigator="ea_9")
        return ctx, case

    def test_correction_posts_entry_and_recomputes_balance(self, api):
        """PRD: "it then fires the four-link correction cascade: an
        `ERROR_CORRECTION` ledger entry of positive `correction_amount_cents`
        posts effective today; the account's `balance_cents` is recomputed"
        PRD: "An `outcome` of `CORRECTED` requires `correction_amount_cents` to
        be present and positive (`ERR_INVALID_AMOUNT`)"

        Design: Difficulty/transitive_cascade/error_correction_depth4_cascade
        """
        ctx, case = self._setup_effective_with_case(api)
        resolved = resolve_case(case["id"], outcome="CORRECTED",
                                correction_amount_cents=25_000,
                                resolution_note="Recomputed with corrected tax bill")
        assert resolved["status"] == "RESOLVED_CORRECTED"
        assert resolved["resolved_by_user_id"] == "co_1"

        entries = get_ledger(ctx["account"]["id"])
        corrections = [e for e in entries if e["entry_type"] == "ERROR_CORRECTION"]
        assert len(corrections) == 1, "link 1: the correction entry is posted"
        assert corrections[0]["amount_cents"] == 25_000
        assert corrections[0]["source_entity_id"] == case["id"]

        account = get_account(ctx["account"]["id"])
        assert account["balance_cents"] == 85_000, (
            "link 2: 60000 + 25000 after recomputation")

    def test_correction_reopens_analysis_and_voids_notice(self, api):
        """PRD: "any `EFFECTIVE` analysis cycle of the account moves to
        `REOPENED`; and each of that analysis's notices in `DRAFT`, `SENT`, or
        `ACKNOWLEDGED` moves to `VOIDED`."

        Design: Difficulty/transitive_cascade/error_correction_depth4_cascade
        """
        ctx, case = self._setup_effective_with_case(api)
        resolve_case(case["id"], outcome="CORRECTED",
                     correction_amount_cents=25_000,
                     resolution_note="Recomputed with corrected tax bill")

        analysis = validate_success(api.get_analysis(ctx["analysis"]["id"], EA1), 200)
        assert analysis["status"] == "REOPENED", (
            "link 3: the EFFECTIVE cycle reopens")

        notice = validate_success(api.get_notice(ctx["notice"]["id"], EA1), 200)
        assert notice["status"] == "VOIDED", (
            "link 4: the SENT notice is voided by the reopen cascade")
