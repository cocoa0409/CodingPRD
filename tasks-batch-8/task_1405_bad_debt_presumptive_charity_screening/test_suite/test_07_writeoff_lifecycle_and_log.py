"""Write-off posting cascades (charity and bad debt), reversal unwinding,
state-vs-segregation priority, the Medicare bad-debt log, and OCC on approval.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_write_off_fresh,
    approve_write_off_payload,
    assert_write_off,
    create_account,
    create_evaluated_screening,
    create_pending_write_off,
    issue_statements,
    make_collector_headers,
    make_officer_headers,
    read_account,
    setup_agency_placement_direct,
    setup_posted_bad_debt_writeoff,
    setup_posted_charity_writeoff,
    validate_error,
    validate_paginated,
    validate_success,
)

COLLECTOR = TEST_USERS["collector_headers"]
OFFICER = TEST_USERS["officer_headers"]


class TestCharityWriteoffCascade:
    def test_charity_writeoff_approval_full_cascade(self, api):
        """PRD §3.9: "For `CHARITY_CARE`, the account moves from `OPEN` to
        `CLOSED_CHARITY`, the referenced screening moves from `EVALUATED` to
        `APPLIED`, `charity_writeoff_total_cents` grows by the written-off
        amount, `credit_reporting_status` becomes `SUPPRESSED_BY_CHARITY`"
        PRD §3.9: "the account's `current_balance_cents` goes to zero, and the
        account's `version` increments."
        PRD §3.9: "the written-off `amount_cents` is always a snapshot of the
        account's entire `current_balance_cents` at the moment of approval"

        Design: Difficulty/transitive_cascade/charity_writeoff_approval_cascade_to_screening_and_reporting
        """
        account = create_account(
            balance_cents=120000, guarantor_liability_date="2026-06-01",
            patient_mrn="MRN-E1", patient_name="Eve E")
        screening = create_evaluated_screening(
            account["id"], household_size=1, household_income_cents=1500000)
        assert screening["eligibility_outcome"] == "FULL_CHARITY"
        write_off = create_pending_write_off(
            account["id"], creator_headers=make_collector_headers("collector-1"),
            write_off_kind="CHARITY_CARE", screening_id=screening["id"])

        posted = approve_write_off_fresh(
            write_off["id"], account["id"],
            approver_headers=make_officer_headers("officer-1"))
        assert_write_off(posted)
        assert posted["status"] == "POSTED"
        assert posted["amount_cents"] == 120000
        assert posted["approved_by_user_id"] == "officer-1"

        acct_after = read_account(account["id"])
        assert acct_after["status"] == "CLOSED_CHARITY"
        assert acct_after["current_balance_cents"] == 0
        assert acct_after["charity_writeoff_total_cents"] == 120000
        assert acct_after["credit_reporting_status"] == "SUPPRESSED_BY_CHARITY"

        screening_after = validate_success(
            api.get_screening(screening["id"], COLLECTOR), 200)
        assert screening_after["status"] == "APPLIED"

    def test_partial_charity_writeoff_creates_no_medicare_log(self, api):
        """PRD §3.9: "and — because charity care is never claimable as Medicare
        bad debt — no log entry is created."
        PRD §3.9: "Only full-balance write-offs exist: the written-off
        `amount_cents` is always a snapshot of the account's entire
        `current_balance_cents` at the moment of approval"

        A PARTIAL_CHARITY outcome (writeoff percent 50) still posts a
        full-balance charity write-off and appends nothing to the Medicare log.

        Household of one with 3027060 cents income: floor(3027060*100/1506000)
        = 201 -> above the inclusive 200 full-charity cap -> PARTIAL_CHARITY.

        Design: Difficulty/transitive_cascade/charity_writeoff_approval_cascade_to_screening_and_reporting
        """
        account, screening, posted = setup_posted_charity_writeoff(
            balance_cents=100000, guarantor_liability_date="2026-06-01",
            screening_overrides={"household_size": 1,
                                 "household_income_cents": 3027060})
        assert posted["status"] == "POSTED"
        assert posted["amount_cents"] == 100000

        assert account["status"] == "CLOSED_CHARITY"
        assert account["current_balance_cents"] == 0
        assert account["charity_writeoff_total_cents"] == 100000
        assert account["credit_reporting_status"] == "SUPPRESSED_BY_CHARITY"

        screening_after = validate_success(
            api.get_screening(screening["id"], COLLECTOR), 200)
        assert screening_after["status"] == "APPLIED"
        assert screening_after["charity_writeoff_percent"] == 50

        log_entries, meta = validate_paginated(
            api.list_account_medicare_log_entries(account["id"], OFFICER))
        assert log_entries == []
        assert meta["total_count"] == 0


class TestBadDebtReversal:
    def test_reversal_reverts_written_off_account_to_open(self, api):
        """PRD §3.9: "Reversal restores the account's `current_balance_cents` by
        the full written-off amount and increments its `version`. The account's
        status rewinds along the path it came: from `WRITTEN_OFF` it returns to
        `IN_COLLECTIONS` if an `ACTIVE` agency placement still exists and to
        `OPEN` otherwise"
        PRD §3.9: "A reversed `BAD_DEBT` write-off reduces
        `bad_debt_writeoff_total_cents` by the amount"

        Design: Difficulty/non_linear_state_machine/account_status_branching_with_revert_after_writeoff_reversal
        """
        account, write_off = setup_posted_bad_debt_writeoff(
            balance_cents=80000, guarantor_liability_date="2026-01-01",
            creator_id="collector-1", approver_id="officer-1")
        assert account["status"] == "WRITTEN_OFF"

        reversed_wo = validate_success(api.reverse_write_off(
            write_off["id"], make_officer_headers("officer-2")), 200)
        assert_write_off(reversed_wo)
        assert reversed_wo["status"] == "REVERSED"

        acct_after = read_account(account["id"])
        assert acct_after["status"] == "OPEN"
        assert acct_after["current_balance_cents"] == 80000
        assert acct_after["bad_debt_writeoff_total_cents"] == 0

    def test_reversal_with_active_agency_placement_returns_in_collections(self, api):
        """PRD §3.9: "from `WRITTEN_OFF` it returns to `IN_COLLECTIONS` if an
        `ACTIVE` agency placement still exists and to `OPEN` otherwise"
        PRD §3.9: "an active agency placement is not closed by the write-off: it
        remains `ACTIVE` until recalled, since the balance reaching zero by
        write-off is not a recovery."

        Design: Difficulty/non_linear_state_machine/account_status_branching_with_revert_after_writeoff_reversal
        """
        account, placement = setup_agency_placement_direct(
            balance_cents=80000, guarantor_liability_date="2026-01-01",
            agency_name="AG_X", contingency_fee_bps=2000)
        assert account["status"] == "IN_COLLECTIONS"
        write_off = create_pending_write_off(
            account["id"], creator_headers=make_collector_headers("collector-1"),
            write_off_kind="BAD_DEBT", medicare_cost_report_year=2026)
        posted = approve_write_off_fresh(
            write_off["id"], account["id"],
            approver_headers=make_officer_headers("officer-1"))
        assert posted["status"] == "POSTED"
        assert read_account(account["id"])["status"] == "WRITTEN_OFF"

        validate_success(api.reverse_write_off(
            posted["id"], make_officer_headers("officer-2")), 200)

        acct_after = read_account(account["id"])
        assert acct_after["status"] == "IN_COLLECTIONS"
        placement_after = validate_success(
            api.get_agency_placement(placement["id"], COLLECTOR), 200)
        assert placement_after["status"] == "ACTIVE"


class TestCompensatingInvariant:
    def test_bad_debt_writeoff_reverse_conserves_balance_plus_total(self, api):
        """PRD §3.9: "Reversal restores the account's `current_balance_cents` by
        the full written-off amount and increments its `version`."
        PRD §3.9: "A reversed `BAD_DEBT` write-off reduces
        `bad_debt_writeoff_total_cents` by the amount and voids the linked log
        entry by stamping its `voided_at` — the entry is voided in place, never
        deleted, preserving the append-only audit trail."

        The pair (posting, reversal) conserves the sum current_balance_cents +
        bad_debt_writeoff_total_cents == original 75000.

        Design: Difficulty/compensating_invariant/writeoff_then_reverse_preserves_current_balance_and_totals
        """
        account, write_off = setup_posted_bad_debt_writeoff(
            balance_cents=75000, guarantor_liability_date="2026-01-01",
            creator_id="collector-1", approver_id="officer-1")
        posted_view = read_account(account["id"])
        assert posted_view["current_balance_cents"] == 0
        assert posted_view["bad_debt_writeoff_total_cents"] == 75000
        assert (posted_view["current_balance_cents"]
                + posted_view["bad_debt_writeoff_total_cents"]) == 75000

        validate_success(api.reverse_write_off(
            write_off["id"], make_officer_headers("officer-2")), 200)

        acct_after = read_account(account["id"])
        assert acct_after["current_balance_cents"] == 75000
        assert acct_after["bad_debt_writeoff_total_cents"] == 0
        assert (acct_after["current_balance_cents"]
                + acct_after["bad_debt_writeoff_total_cents"]) == 75000

        log_entries, _meta = validate_paginated(
            api.list_account_medicare_log_entries(account["id"], OFFICER))
        assert len(log_entries) == 1
        assert log_entries[0]["voided_at"] is not None

    def test_charity_writeoff_reverse_rolls_back_screening_and_totals(self, api):
        """PRD §3.9: "A reversed `CHARITY_CARE` write-off reduces
        `charity_writeoff_total_cents` by the amount, rolls the screening from
        `APPLIED` back to `EVALUATED`, and reverts `credit_reporting_status` to
        its pre-write-off value (`REPORTABLE` if the placement was reported,
        `NOT_REPORTED` otherwise)."
        PRD §3.9: "from `CLOSED_CHARITY` it returns to `OPEN`."

        Design: Difficulty/compensating_invariant/writeoff_then_reverse_preserves_current_balance_and_totals
        """
        account, screening, posted = setup_posted_charity_writeoff(
            balance_cents=60000, guarantor_liability_date="2026-06-01",
            creator_id="collector-1", approver_id="officer-1")
        assert account["status"] == "CLOSED_CHARITY"
        assert account["charity_writeoff_total_cents"] == 60000

        validate_success(api.reverse_write_off(
            posted["id"], make_officer_headers("officer-2")), 200)

        acct_after = read_account(account["id"])
        assert acct_after["status"] == "OPEN"
        assert acct_after["current_balance_cents"] == 60000
        assert acct_after["charity_writeoff_total_cents"] == 0
        assert acct_after["credit_reporting_status"] == "NOT_REPORTED"
        assert (acct_after["current_balance_cents"]
                + acct_after["charity_writeoff_total_cents"]) == 60000

        screening_after = validate_success(
            api.get_screening(screening["id"], COLLECTOR), 200)
        assert screening_after["status"] == "EVALUATED"


class TestStateBeatsSegregation:
    def test_approve_posted_writeoff_state_error_beats_sod(self, api):
        """PRD §2.9: "Requests are validated in a fixed priority order, and the
        first failing check produces the response — later checks are not
        evaluated for that request."
        PRD §2.9: "6. **State preconditions.** The target resource must be in a
        state from which the requested transition is defined, else
        `ERR_INVALID_STATE` (HTTP 409)."
        PRD §2.9: "7. **Segregation of duties.** Write-off approval and reversal
        must be performed by a different principal than the prior step, else
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

        The write-off is already POSTED (state violation, rank 6) and the second
        approval is attempted by the creator's user id (SoD violation, rank 7);
        the state error is reported.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_segregation_of_duties
        """
        account, write_off = setup_posted_bad_debt_writeoff(
            balance_cents=50000, guarantor_liability_date="2026-01-01",
            creator_id="collector-1", approver_id="officer-1")
        assert write_off["status"] == "POSTED"

        resp = api.approve_write_off(
            write_off["id"],
            approve_write_off_payload(read_account(account["id"])["version"]),
            make_officer_headers("collector-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_reverse_by_approving_officer_violates_sod(self, api):
        """PRD §3.9: "the reversing officer's `X-User-ID` must differ from the
        `approved_by_user_id` recorded at approval (else
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION`)"

        The write-off is POSTED (state-valid for reversal), so the only violated
        guard in the pair is segregation of duties.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_segregation_of_duties
        """
        account, write_off = setup_posted_bad_debt_writeoff(
            balance_cents=50000, guarantor_liability_date="2026-01-01",
            creator_id="collector-1", approver_id="officer-1")
        assert write_off["approved_by_user_id"] == "officer-1"

        resp = api.reverse_write_off(
            write_off["id"], make_officer_headers("officer-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        unchanged = validate_success(api.get_write_off(write_off["id"], OFFICER), 200)
        assert unchanged["status"] == "POSTED"


class TestMedicareBadDebtLog:
    def test_medicare_log_entry_fields_at_posting(self, api):
        """PRD §3.9: "The Medicare log entry captures the claim's evidentiary
        record at the posting instant: the `write_off_id` and denormalized
        `account_id`, the `cost_report_year` copied from the write-off,
        `claimed_amount_cents` equal to the write-off amount,
        `collection_effort_days` measured as the whole days between the
        `guarantor_liability_date` and the posting date, and an
        `indigence_documented` flag that is true exactly when a screening exists
        for the account with status `EVALUATED` or `APPLIED`, an outcome of
        `FULL_CHARITY` or `PARTIAL_CHARITY`, and a `screened_at` on or before
        the write-off's posting time — superseded screenings never count."

        Liability date 2026-01-01 to the 2026-08-01 posting date is 212 whole
        days; with no charity screening on the account, indigence is not
        documented.

        Design: Corner/calculations/medicare_log_collection_effort_days_computed
        """
        account, write_off = setup_posted_bad_debt_writeoff(
            balance_cents=80000, guarantor_liability_date="2026-01-01",
            cost_report_year=2026)

        log_entries, meta = validate_paginated(
            api.list_account_medicare_log_entries(account["id"], OFFICER))
        assert meta["total_count"] == 1
        entry = log_entries[0]
        assert entry["write_off_id"] == write_off["id"]
        assert entry["account_id"] == account["id"]
        assert entry["collection_effort_days"] == 212
        assert entry["claimed_amount_cents"] == 80000
        assert entry["cost_report_year"] == 2026
        assert entry["indigence_documented"] is False
        assert entry["voided_at"] is None

    def test_collector_cannot_read_medicare_log(self, api):
        """PRD §2.1: "the officer is also the only role that may read the
        Medicare bad-debt log."
        PRD §2.9: "The role must appear in the endpoint's authorized role list,
        else `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/collector_cannot_read_medicare_log
        """
        account, _write_off = setup_posted_bad_debt_writeoff(
            balance_cents=50000, guarantor_liability_date="2026-01-01")
        log_entries, _meta = validate_paginated(
            api.list_account_medicare_log_entries(account["id"], OFFICER))
        assert len(log_entries) == 1

        resp = api.get_medicare_log_entry(log_entries[0]["id"], COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestApprovalRbacAndOcc:
    def test_collector_cannot_approve_writeoff(self, api):
        """PRD §2.1: "A `RevenueIntegrityOfficer` approves and reverses
        write-offs, resolves disputes, terminates defaulted plans, and generates
        vendor performance snapshots"
        PRD §2.9: "The role must appear in the endpoint's authorized role list,
        else `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/errors/insufficient_permissions_when_collector_tries_approve
        """
        account = create_account(
            balance_cents=50000, guarantor_liability_date="2026-01-01",
            patient_mrn="MRN-Q1", patient_name="Q1")
        write_off = create_pending_write_off(
            account["id"], creator_headers=make_collector_headers("collector-1"),
            write_off_kind="BAD_DEBT", medicare_cost_report_year=2026)

        resp = api.approve_write_off(
            write_off["id"],
            approve_write_off_payload(read_account(account["id"])["version"]),
            make_collector_headers("collector-2"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_writeoff_approve_stale_version_rejected(self, api):
        """PRD §2.7: "Two write operations are guarded by optimistic concurrency
        control against the parent self-pay account: creating a presumptive
        charity screening for an account, and approving a pending write-off."
        PRD §2.7: "If the account's current `version` does not equal
        `expected_account_version` at request-handling time — because another
        writer has advanced the account since the client read it — the request
        is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is
        mutated."

        A statement issuance advances the account version between the approver's
        read and the approval call.

        Design: Corner/cross_cutting_layers/occ_on_writeoff_approve_stale_version
        """
        account = create_account(
            balance_cents=50000, guarantor_liability_date="2026-01-01",
            patient_mrn="MRN-S1", patient_name="S1")
        issue_statements(account["id"], count=3)
        write_off = create_pending_write_off(
            account["id"], creator_headers=make_collector_headers("collector-1"),
            write_off_kind="BAD_DEBT", medicare_cost_report_year=2026)
        stale_version = read_account(account["id"])["version"]
        issue_statements(account["id"], count=1)  # advances account.version

        resp = api.approve_write_off(
            write_off["id"], approve_write_off_payload(stale_version),
            make_officer_headers("officer-1"))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        unchanged = validate_success(api.get_write_off(write_off["id"], OFFICER), 200)
        assert unchanged["status"] == "PENDING_APPROVAL"
