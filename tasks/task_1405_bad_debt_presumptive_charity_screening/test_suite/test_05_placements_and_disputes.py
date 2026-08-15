"""Early-out and agency placement lifecycles: exclusivity, recall deadlines,
escalation, credit-reporting side effects, vendor performance windows, and the
dispute guards that interact with placement."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_days,
    advance_clock,
    assert_agency_placement,
    create_account,
    create_agency_placement_payload,
    create_early_out_placement_payload,
    create_vendor_snapshot,
    file_open_dispute,
    iso_at_start_of,
    issue_statements,
    make_agency_headers,
    post_recovery,
    read_account,
    setup_agency_placement_direct,
    setup_early_out_placement,
    validate_error,
    validate_success,
    LOGICAL_CLOCK_START_DATE,
)

COLLECTOR = TEST_USERS["collector_headers"]
OFFICER = TEST_USERS["officer_headers"]


class TestEscalationDeadlineDependency:
    def test_escalation_before_recall_deadline_rejected(self, api):
        """PRD §3.5: "The escalation path applies when the account is
        `IN_EARLY_OUT` with an `ACTIVE` early-out placement: escalation is
        permitted only once the logical clock's date has passed that placement's
        `recall_deadline` — attempting it earlier is rejected with
        `ERR_RECALL_WINDOW_STILL_OPEN` — and it moves the early-out placement to
        `ESCALATED_TO_AGENCY` as it places the account with the agency."

        The clock is advanced to the placement's own recall_deadline (a date on
        which the deadline has not yet passed), then escalation is attempted.

        Design: Difficulty/cross_entity_state_dependency/agency_placement_recall_window_depends_on_earlyout_recall_deadline
        """
        account, placement = setup_early_out_placement(
            balance_cents=80000, guarantor_liability_date="2026-06-01",
            vendor_name="VENDOR_A", contingency_fee_bps=1500)
        assert placement["recall_deadline"] >= LOGICAL_CLOCK_START_DATE
        advance_clock(iso_at_start_of(placement["recall_deadline"]))

        resp = api.create_agency_placement(
            create_agency_placement_payload(
                account["id"], agency_name="AG_Z", contingency_fee_bps=2500),
            COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_RECALL_WINDOW_STILL_OPEN)

        unchanged_placement = validate_success(
            api.get_early_out_placement(placement["id"], COLLECTOR), 200)
        assert unchanged_placement["status"] == "ACTIVE"
        assert read_account(account["id"])["status"] == "IN_EARLY_OUT"

    def test_escalation_after_recall_deadline_succeeds(self, api):
        """PRD §3.5: "The escalation path applies when the account is
        `IN_EARLY_OUT` with an `ACTIVE` early-out placement: escalation is
        permitted only once the logical clock's date has passed that placement's
        `recall_deadline`"
        PRD §3.5: "A successful placement moves the account to `IN_COLLECTIONS`,
        increments its `version`, snapshots `placement_balance_cents`, stamps
        `placed_at`, computes `recall_window_closes_at` as the placement date
        plus the configured agency recall-window day count"

        The clock is advanced one day past the placement's recall_deadline, then
        escalation succeeds and the early-out placement closes as escalated.

        Design: Difficulty/cross_entity_state_dependency/agency_placement_recall_window_depends_on_earlyout_recall_deadline
        """
        account, placement = setup_early_out_placement(
            balance_cents=80000, guarantor_liability_date="2026-06-01",
            vendor_name="VENDOR_A", contingency_fee_bps=1500)
        day_after = add_days(placement["recall_deadline"], 1)
        advance_clock(iso_at_start_of(day_after))

        agency = validate_success(api.create_agency_placement(
            create_agency_placement_payload(
                account["id"], agency_name="AG_Z", contingency_fee_bps=2500),
            COLLECTOR), 201)
        assert_agency_placement(agency)
        assert agency["status"] == "ACTIVE"

        early_out_after = validate_success(
            api.get_early_out_placement(placement["id"], COLLECTOR), 200)
        assert early_out_after["status"] == "ESCALATED_TO_AGENCY"
        assert read_account(account["id"])["status"] == "IN_COLLECTIONS"


class TestPlacementExclusivity:
    def test_second_early_out_placement_rejected(self, api):
        """PRD §3.4: "Placement requires the account to be `OPEN` and in
        `BUCKET_30` or `BUCKET_60`"
        PRD §2.9: "The target resource must be in a state from which the
        requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409)."

        With a placement already ACTIVE the account sits in IN_EARLY_OUT, a
        state from which no early-out placement transition is defined.

        Design: Difficulty/resource_temporal_overlap/only_one_active_placement_per_account_family_exclusive
        """
        account, first = setup_early_out_placement(
            balance_cents=60000, guarantor_liability_date="2026-06-01",
            vendor_name="VENDOR_A", contingency_fee_bps=1500)

        resp = api.create_early_out_placement(
            create_early_out_placement_payload(
                account["id"], vendor_name="VENDOR_B", contingency_fee_bps=1800),
            COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        first_after = validate_success(
            api.get_early_out_placement(first["id"], COLLECTOR), 200)
        assert first_after["status"] == "ACTIVE"

    def test_second_agency_placement_rejected(self, api):
        """PRD §3.5: "no other agency placement may be `ACTIVE` for the account
        (`ERR_ACTIVE_PLACEMENT_EXISTS`)"
        PRD §2.9: "The target resource must be in a state from which the
        requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409)."

        The direct path is defined from OPEN; with an agency placement ACTIVE
        the account sits in IN_COLLECTIONS and the second placement is rejected
        by the state precondition that §2.9 evaluates before the business
        guards.

        Design: Difficulty/resource_temporal_overlap/only_one_active_placement_per_account_family_exclusive
        """
        account, first = setup_agency_placement_direct(
            balance_cents=90000, guarantor_liability_date="2026-01-01",
            agency_name="AG_X", contingency_fee_bps=2000)

        resp = api.create_agency_placement(
            create_agency_placement_payload(
                account["id"], agency_name="AG_Y", contingency_fee_bps=2500),
            COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        first_after = validate_success(
            api.get_agency_placement(first["id"], COLLECTOR), 200)
        assert first_after["status"] == "ACTIVE"


class TestOpenDisputeVersusAging:
    def test_open_dispute_error_beats_aging_bucket_error(self, api):
        """PRD §2.9: "Requests are validated in a fixed priority order, and the
        first failing check produces the response — later checks are not
        evaluated for that request."
        PRD §2.9: "9. **Open-dispute guard.** An `OPEN` dispute on the account
        blocks collection-agency placement with
        `ERR_OPEN_DISPUTE_BLOCKS_PLACEMENT` (HTTP 409)"
        PRD §2.9: "11. **Aging and statement-cycle prerequisites.**"

        The account has an OPEN dispute (guard 9) and is also outside
        BUCKET_120_PLUS (guard 11); the open-dispute guard fires first.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_open_dispute_vs_business_temporal_aging
        """
        account = create_account(
            balance_cents=70000, guarantor_liability_date="2026-06-15",
            patient_mrn="MRN-F2", patient_name="F2")
        file_open_dispute(account["id"], dispute_reason="billing error",
                          dispute_amount_cents=10000)

        resp = api.create_agency_placement(
            create_agency_placement_payload(
                account["id"], agency_name="AG_Y", contingency_fee_bps=2500),
            COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_OPEN_DISPUTE_BLOCKS_PLACEMENT)

    def test_aging_bucket_error_when_dispute_resolved(self, api):
        """PRD §3.5: "The direct path applies when the account is `OPEN`: it
        requires the account to be in `BUCKET_120_PLUS` (else
        `ERR_ACCOUNT_NOT_IN_AGENCY_BUCKET`)"

        With the dispute resolved (guard 9 satisfied) and the statement-cycle
        minimum met, only the aging-band prerequisite remains violated.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_open_dispute_vs_business_temporal_aging
        """
        account = create_account(
            balance_cents=70000, guarantor_liability_date="2026-06-15",
            patient_mrn="MRN-F2R", patient_name="F2 Resolved")
        dispute = file_open_dispute(account["id"], dispute_amount_cents=10000)
        validate_success(api.resolve_dispute(
            dispute["id"], {"resolution_outcome": "UPHELD_PROVIDER"}, OFFICER), 200)
        issue_statements(account["id"], count=3)

        resp = api.create_agency_placement(
            create_agency_placement_payload(
                account["id"], agency_name="AG_Y", contingency_fee_bps=2500),
            COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_IN_AGENCY_BUCKET)


class TestRecallOutcomes:
    def test_early_out_recall_after_deadline_rejected(self, api):
        """PRD §3.4: "Recalling an early-out placement is permitted only while
        the logical clock's date is on or before the `recall_deadline`; a recall
        attempted after that date is rejected with
        `ERR_RECALL_DEADLINE_PASSED`."

        The clock is advanced one day past the placement's recall_deadline
        before the recall attempt.

        Design: Corner/state_machines/earlyout_recall_after_deadline_returns_recall_deadline_passed
        """
        _account, placement = setup_early_out_placement(
            balance_cents=80000, guarantor_liability_date="2026-06-01",
            vendor_name="VENDOR_A", contingency_fee_bps=1500)
        advance_clock(iso_at_start_of(add_days(placement["recall_deadline"], 1)))

        resp = api.recall_early_out_placement(placement["id"], COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_RECALL_DEADLINE_PASSED)

    def test_agency_recall_within_window_is_no_fee(self, api):
        """PRD §3.5: "If the logical clock's date is on or before
        `recall_window_closes_at`, the placement closes as `RECALLED_NO_FEE`."

        The recall happens on the same logical date the placement was created,
        which is on or before any recall window closing date computed from the
        placement date.

        Design: Corner/calculations/agency_recall_fee_boundary_zero_when_within_window
        """
        account, placement = setup_agency_placement_direct(
            balance_cents=50000, guarantor_liability_date="2026-01-01",
            agency_name="AG_X", contingency_fee_bps=2000)

        recalled = validate_success(
            api.recall_agency_placement(placement["id"], COLLECTOR), 200)
        assert_agency_placement(recalled)
        assert recalled["status"] == "RECALLED_NO_FEE"
        assert read_account(account["id"])["status"] == "OPEN"


class TestCreditReportingSideEffect:
    def test_direct_agency_placement_sets_reportable(self, api):
        """PRD §3.5: "A successful placement moves the account to
        `IN_COLLECTIONS`, increments its `version`, snapshots
        `placement_balance_cents`, stamps `placed_at`, computes
        `recall_window_closes_at` as the placement date plus the configured
        agency recall-window day count, and — significantly for the patient's
        credit — moves `credit_reporting_status` to `REPORTABLE`."

        Design: Corner/endpoints/agency_placement_marks_credit_reportable
        """
        account, placement = setup_agency_placement_direct(
            balance_cents=50000, guarantor_liability_date="2026-01-01",
            agency_name="AG_Z", contingency_fee_bps=2500)
        assert_agency_placement(placement)
        after = read_account(account["id"])
        assert after["credit_reporting_status"] == "REPORTABLE"
        assert after["status"] == "IN_COLLECTIONS"


class TestTerminalLockdown:
    def test_early_out_placement_on_closed_paid_account_rejected(self, api):
        """PRD §3.4: "Placement requires the account to be `OPEN` and in
        `BUCKET_30` or `BUCKET_60`"
        PRD §2.9: "The target resource must be in a state from which the
        requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409)."

        A payment drives the balance to zero, closing the account; CLOSED_PAID
        is terminal and admits no placement transition.

        Design: Corner/state_machines/account_status_terminal_lockdown_closed_paid
        """
        account = create_account(
            balance_cents=50000, guarantor_liability_date="2026-06-01",
            patient_mrn="MRN-L5", patient_name="L5")
        post_recovery(account["id"], payment_kind="LUMP_SUM", amount_cents=50000)
        assert read_account(account["id"])["status"] == "CLOSED_PAID"

        resp = api.create_early_out_placement(
            create_early_out_placement_payload(
                account["id"], vendor_name="VENDOR_X", contingency_fee_bps=1500),
            COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPlacementRbac:
    def test_agency_user_cannot_place_early_out(self, api):
        """PRD §2.1: "A `CollectionAgencyUser` is an external agency operator
        who posts remittances, marks placements as credit-reported, and reads
        accounts and placements."
        PRD §2.9: "The role must appear in the endpoint's authorized role list,
        else `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/agency_user_cannot_place_early_out
        """
        account = create_account(
            balance_cents=50000, guarantor_liability_date="2026-06-01",
            patient_mrn="MRN-R1", patient_name="R1")
        resp = api.create_early_out_placement(
            create_early_out_placement_payload(
                account["id"], vendor_name="VENDOR_A", contingency_fee_bps=1500),
            make_agency_headers())
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestVendorPerformanceWindows:
    def test_snapshot_windows_half_open_no_double_count(self, api):
        """PRD §3.4: "Vendor oversight is measured through performance
        snapshots, generated by a `RevenueIntegrityOfficer` for a named
        `vendor_name` over a window from `snapshot_period_start` (inclusive) to
        `snapshot_period_end` (exclusive). The snapshot counts
        `placements_in_window` — that vendor's early-out placements whose
        `placed_at` falls inside the window"

        The placement is created at the boot clock 2026-08-01T00:00:00Z, which
        is the exclusive end of [2026-07-01, 2026-08-01) and the inclusive start
        of [2026-08-01, 2026-09-01): it lands in exactly one window.

        Design: Difficulty/resource_temporal_overlap/vendor_performance_snapshot_windows_disjoint
        """
        account, placement = setup_early_out_placement(
            balance_cents=100000, guarantor_liability_date="2026-06-01",
            vendor_name="VENDOR_A", contingency_fee_bps=1500)
        assert placement["placed_at"].startswith(LOGICAL_CLOCK_START_DATE)

        first = create_vendor_snapshot(
            vendor_name="VENDOR_A", snapshot_period_start="2026-07-01",
            snapshot_period_end="2026-08-01")
        second = create_vendor_snapshot(
            vendor_name="VENDOR_A", snapshot_period_start="2026-08-01",
            snapshot_period_end="2026-09-01")

        assert first["placements_in_window"] == 0
        assert second["placements_in_window"] == 1

    def test_snapshot_recovery_rate_and_threshold(self, api):
        """PRD §3.4: "The `recovery_rate_bps` is ten thousand times the
        recovered sum divided by the summed `placement_balance_cents` of the
        in-window placements, rounded down to a whole basis point; when no
        placement balance exists in the window the rate is zero. The snapshot's
        `meets_minimum_threshold` is true when the rate is at least 1,200 basis
        points — a twelve percent recovery floor."

        A 100000-cent placement recovering 20000 cents in-window yields
        floor(20000 * 10000 / 100000) = 2000 bps, at or above the 1200 floor.

        Design: Difficulty/resource_temporal_overlap/vendor_performance_snapshot_windows_disjoint
        """
        account, placement = setup_early_out_placement(
            balance_cents=100000, guarantor_liability_date="2026-06-01",
            vendor_name="VENDOR_A", contingency_fee_bps=1500)
        post_recovery(
            account["id"], payment_kind="EARLY_OUT_REMITTANCE",
            amount_cents=20000, attributed_placement_id=placement["id"])

        snapshot = create_vendor_snapshot(
            vendor_name="VENDOR_A", snapshot_period_start="2026-08-01",
            snapshot_period_end="2026-09-01")
        assert snapshot["placements_in_window"] == 1
        assert snapshot["recovered_in_window_cents"] == 20000
        assert snapshot["recovery_rate_bps"] == 2000
        assert snapshot["meets_minimum_threshold"] is True


class TestDisputeFilingAndResolution:
    def test_dispute_amount_above_balance_rejected(self, api):
        """PRD §3.6: "The disputed amount must be greater than zero and no more
        than the account's `current_balance_cents` at filing; violations are
        rejected with `ERR_DISPUTE_AMOUNT_INVALID`."

        Design: Corner/validations/dispute_amount_exceeding_balance_returns_422
        """
        account = create_account(
            balance_cents=50000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-N3", patient_name="N3")
        resp = api.file_dispute(
            {"account_id": account["id"], "dispute_reason": "test",
             "dispute_amount_cents": 99999},
            COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_DISPUTE_AMOUNT_INVALID)

    def test_resolve_resolved_dispute_rejected(self, api):
        """PRD §3.6: "Resolution is the exclusive province of a
        `RevenueIntegrityOfficer`, who supplies a `resolution_outcome` of
        `UPHELD_PATIENT` or `UPHELD_PROVIDER`; anything else fails payload
        validation, and resolving a dispute that is no longer `OPEN` is rejected
        with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/dispute_resolve_from_resolved_returns_invalid_state
        """
        account = create_account(
            balance_cents=50000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-L4", patient_name="L4")
        dispute = file_open_dispute(account["id"], dispute_reason="test",
                                    dispute_amount_cents=5000)
        validate_success(api.resolve_dispute(
            dispute["id"], {"resolution_outcome": "UPHELD_PROVIDER"}, OFFICER), 200)

        resp = api.resolve_dispute(
            dispute["id"], {"resolution_outcome": "UPHELD_PATIENT"}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
