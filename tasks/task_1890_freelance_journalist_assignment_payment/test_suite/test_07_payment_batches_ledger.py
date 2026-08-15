"""Payment batches and the ledger: parallel assignment dimensions, release
cascades, YTD threshold boundaries, late-fee step accrual, cancel
compensation, batch OCC, and batch segregation of duties."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    add_invoice_to_batch,
    approve_invoice,
    assert_ledger_entry,
    bootstrap_desk,
    create_batch,
    create_verified_tax_document,
    get_assignment,
    get_batch,
    get_contributor,
    get_expense_claim,
    get_invoice,
    get_success_data,
    kill_assignment,
    lock_batch,
    make_finance_headers,
    release_batch,
    setup_accepted_assignment,
    setup_accepted_with_reimbursable_expense,
    setup_assignment_in_state,
    setup_approved_invoice,
    setup_batched_invoice,
    setup_paid_invoice,
    setup_verified_invoice,
    submit_invoice,
    validate_error,
    validate_success,
    verify_invoice,
)
from test_helpers import api_client as _api
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["desk_admin_headers"]
EDITOR = TEST_USERS["editor_headers"]


def _parse_ts(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestAssignmentParallelDimensions:

    def _killed_assignment(self, api):
        """Killed-from-IN_PROGRESS assignment (kill fee 25% of 80000)."""
        contributor, _agr, assignment = setup_assignment_in_state(
            "IN_PROGRESS", legal_name="Killed Kate", email="kate@x.com",
            pricing_mode="FLAT", flat_fee_cents=80000)
        create_verified_tax_document(contributor["id"], doc_kind="W9",
                                     tin_last4="5555")
        killed = kill_assignment(assignment["id"])
        assert killed["final_fee_cents"] == 20000
        return contributor, killed

    def test_killed_assignment_can_be_invoiced(self, api):
        """PRD section 3.4: "In both branches `payment_status` stays
        `UNINVOICED`, so a killed assignment can still be invoiced for its
        kill fee."
        PRD section 3.8: "The submission sets `submitted_by_contributor_id`
        from `X-User-ID` and moves `payment_status` from `UNINVOICED` to
        `INVOICED`."

        Design: Difficulty/non_linear_state_machine/assignment_parallel_dimensions
        """
        contributor, killed = self._killed_assignment(api)
        invoice = submit_invoice(killed["id"], contributor["id"], 20000, 0)
        assert invoice["status"] == "SUBMITTED"

        after = get_assignment(killed["id"])
        assert after["editorial_status"] == "KILLED", (
            "terminal on the editorial axis")
        assert after["payment_status"] == "INVOICED", (
            "mid-pipeline on the payment axis")

    def test_killed_assignment_reaches_payable(self, api):
        """PRD section 3.4: "In both branches `payment_status` stays
        `UNINVOICED`, so a killed assignment can still be invoiced for its
        kill fee."
        PRD section 3.8: "Approval moves the invoice to `APPROVED` and
        cascades the assignment's `payment_status` from `INVOICED` to
        `PAYABLE`."

        Design: Difficulty/non_linear_state_machine/assignment_parallel_dimensions
        """
        contributor, killed = self._killed_assignment(api)
        invoice = submit_invoice(killed["id"], contributor["id"], 20000, 0)
        verify_invoice(invoice["id"], "VERIFY")
        approve_invoice(invoice["id"])

        after = get_assignment(killed["id"])
        assert after["editorial_status"] == "KILLED"
        assert after["payment_status"] == "PAYABLE"
        assert after["final_fee_cents"] == 20000


class TestBatchReleaseCascade:

    def _setup_locked_batch(self, api):
        ctx, claim = setup_accepted_with_reimbursable_expense(
            legal_name="Paid Pam", email="pam@x.com", pricing_mode="FLAT",
            flat_fee_cents=50000, category="TRAVEL", requested_cents=5000,
            claimed_cents=5000, receipt_attached=True)
        create_verified_tax_document(ctx["contributor"]["id"],
                                     doc_kind="W9", tin_last4="1111")
        invoice = submit_invoice(ctx["assignment"]["id"],
                                 ctx["contributor"]["id"], 50000, 5000)
        verified = verify_invoice(invoice["id"], "VERIFY")
        assert verified["gross_cents"] == 55000
        assert verified["withholding_cents"] == 0, "valid W9: rate zero"
        approve_invoice(invoice["id"])
        batch = create_batch("2026-08-20T00:00:00Z")
        add_invoice_to_batch(batch["id"], invoice["id"])
        locked = lock_batch(batch["id"])
        return ctx, claim, invoice, locked

    def test_release_pays_invoice_expense_and_assignment(self, api):
        """PRD section 3.9: "Each member invoice then posts its ledger
        entries and moves to `PAID`: a `FEE_CREDIT` entry of plus
        `fee_claim_cents`, an `EXPENSE_CREDIT` entry of plus
        `expense_claim_cents`, a `WITHHOLDING_DEBIT` entry of minus
        `withholding_cents`, and a `LATE_FEE_CREDIT` entry of plus
        `late_fee_cents` when that amount is positive."
        PRD section 3.9: "Every covered expense claim flips to `PAID`, and
        the assignment's `payment_status` cascades to `PAID`."

        Design: Difficulty/transitive_cascade/batch_release_depth2_cascade
        """
        ctx, claim, invoice, locked = self._setup_locked_batch(api)
        released = release_batch(locked["id"], locked["version"])
        assert released["status"] == "RELEASED"

        assert get_invoice(invoice["id"])["status"] == "PAID"
        assert get_expense_claim(claim["id"])["status"] == "PAID"
        assert (get_assignment(ctx["assignment"]["id"])["payment_status"]
                == "PAID")

    def test_release_posts_ledger_and_recomputes_ytd(self, api):
        """PRD section 3.9: "Each member invoice then posts its ledger
        entries and moves to `PAID`: a `FEE_CREDIT` entry of plus
        `fee_claim_cents`, an `EXPENSE_CREDIT` entry of plus
        `expense_claim_cents`, a `WITHHOLDING_DEBIT` entry of minus
        `withholding_cents`, and a `LATE_FEE_CREDIT` entry of plus
        `late_fee_cents` when that amount is positive."
        PRD section 3.9: "`ytd_gross_cents` is the sum of `amount_cents` over
        all the contributor's ledger entries whose `entry_kind` is
        `FEE_CREDIT`, `EXPENSE_CREDIT`, `LATE_FEE_CREDIT`, or
        `REUSE_ROYALTY_CREDIT` — `WITHHOLDING_DEBIT` entries never count
        toward gross — and whose `posted_at` falls within the current
        calendar year in UTC, inclusive of both January 1 00:00:00.000Z and
        December 31 23:59:59.999Z."

        Design: Difficulty/transitive_cascade/batch_release_depth2_cascade
        """
        ctx, _claim, invoice, locked = self._setup_locked_batch(api)
        release_batch(locked["id"], locked["version"])

        entries = get_success_data(
            _api.list_contributor_ledger_entries(
                ctx["contributor"]["id"], make_finance_headers("fin-1")))
        by_kind = {}
        for entry in entries:
            assert_ledger_entry(entry)
            by_kind.setdefault(entry["entry_kind"], []).append(
                entry["amount_cents"])
        assert by_kind.get("FEE_CREDIT") == [50000]
        assert by_kind.get("EXPENSE_CREDIT") == [5000]
        assert by_kind.get("WITHHOLDING_DEBIT") == [0]
        assert "LATE_FEE_CREDIT" not in by_kind, "batch pays before due date"

        contributor = get_contributor(ctx["contributor"]["id"])
        assert contributor["ytd_gross_cents"] == 55000
        assert contributor["reportable_threshold_crossed"] is False


class TestReportableThresholdCrossing:

    def _pay_contributor(self, api, legal_name, email, flat_fee_cents):
        ctx = setup_paid_invoice(legal_name=legal_name, email=email,
                                 pricing_mode="FLAT",
                                 flat_fee_cents=flat_fee_cents)
        return get_contributor(ctx["contributor"]["id"])

    def test_one_cent_below_threshold_not_flagged(self, api):
        """PRD section 3.1: "`reportable_threshold_crossed` flips to true
        once `ytd_gross_cents` reaches the desk's `reporting_threshold_cents`
        (default 60000 cents, i.e. $600); the comparison is inclusive, so a
        contributor whose year-to-date gross lands exactly on the threshold
        is flagged."

        Design: Difficulty/boundary_precision_check/reportable_threshold_exact_crossing
        """
        contributor = self._pay_contributor(api, "Under T", "t1@x.com",
                                            59999)
        assert contributor["ytd_gross_cents"] == 59999
        assert contributor["reportable_threshold_crossed"] is False

    def test_exact_threshold_crossing_flagged(self, api):
        """PRD section 3.1: "`reportable_threshold_crossed` flips to true
        once `ytd_gross_cents` reaches the desk's `reporting_threshold_cents`
        (default 60000 cents, i.e. $600); the comparison is inclusive, so a
        contributor whose year-to-date gross lands exactly on the threshold
        is flagged."

        Design: Difficulty/boundary_precision_check/reportable_threshold_exact_crossing
        """
        contributor = self._pay_contributor(api, "Exact T", "t2@x.com",
                                            60000)
        assert contributor["ytd_gross_cents"] == 60000
        assert contributor["reportable_threshold_crossed"] is True, (
            "boundary inclusive: >= 60000 crosses")


class TestLateFeeStepAccrual:

    def test_release_exactly_at_due_date_accrues_nothing(self, api):
        """PRD section 3.9: "the days overdue is the integer number of days
        between the invoice's `due_date_utc` and the scheduled pay date,
        clamped at zero (a release exactly at the due date accrues nothing);
        the fee is the invoice's `net_payable_cents` multiplied by the desk's
        `late_fee_daily_bps` (default 50, i.e. 0.5% per day), multiplied by
        the days overdue, divided by 10000, floor-divided."
        PRD section 3.8: "`due_date_utc` is set to now plus
        `payment_terms_days`."

        Design: Difficulty/resource_temporal_overlap/expense_window_elapsed_vs_invoice_terms
        """
        ctx = setup_batched_invoice(
            legal_name="OnTime Ott", email="ott@x.com", pricing_mode="FLAT",
            flat_fee_cents=100000,
            scheduled_pay_date="2026-08-31T00:00:00Z")
        invoice = ctx["invoice"]
        assert invoice["due_date_utc"].startswith("2026-08-31T00:00:00"), (
            "verified at the 2026-08-01 startup clock plus 30 term days")

        released = release_batch(ctx["batch"]["id"], ctx["batch_version"])
        assert released["status"] == "RELEASED"
        paid = get_invoice(invoice["id"])
        assert paid["status"] == "PAID"
        assert paid["late_fee_cents"] == 0, "0 days overdue at the boundary"

    def test_release_ten_days_late_accrues_daily_step_fee(self, api):
        """PRD section 3.9: "the days overdue is the integer number of days
        between the invoice's `due_date_utc` and the scheduled pay date,
        clamped at zero (a release exactly at the due date accrues nothing);
        the fee is the invoice's `net_payable_cents` multiplied by the desk's
        `late_fee_daily_bps` (default 50, i.e. 0.5% per day), multiplied by
        the days overdue, divided by 10000, floor-divided."
        PRD section 3.9: "a `LATE_FEE_CREDIT` entry of plus `late_fee_cents`
        when that amount is positive."

        Design: Difficulty/resource_temporal_overlap/expense_window_elapsed_vs_invoice_terms
        """
        ctx = setup_batched_invoice(
            legal_name="Late Lou", email="lou@x.com", pricing_mode="FLAT",
            flat_fee_cents=100000,
            scheduled_pay_date="2026-09-10T00:00:00Z")
        released = release_batch(ctx["batch"]["id"], ctx["batch_version"])
        assert released["status"] == "RELEASED"

        paid = get_invoice(ctx["invoice"]["id"])
        assert paid["status"] == "PAID"
        # floor(100000 net * 50 bps * 10 days / 10000) == 5000
        assert paid["late_fee_cents"] == 5000

        entries = get_success_data(
            _api.list_invoice_ledger_entries(ctx["invoice"]["id"],
                                             make_finance_headers("fin-1")))
        late_entries = [e for e in entries
                        if e["entry_kind"] == "LATE_FEE_CREDIT"]
        assert len(late_entries) == 1
        assert late_entries[0]["amount_cents"] == 5000
        assert_ledger_entry(late_entries[0])


class TestBatchCancelCompensation:

    def _setup_batched(self, api):
        """OPEN batch holding one APPROVED invoice (not locked): PRD 3.9
        allows cancellation only from OPEN."""
        ctx = setup_approved_invoice(legal_name="Cancel Carl",
                                     email="carl@x.com", pricing_mode="FLAT",
                                     flat_fee_cents=50000)
        batch = create_batch("2026-08-20T00:00:00Z")
        ctx["batch"] = add_invoice_to_batch(batch["id"],
                                            ctx["invoice"]["id"])
        return ctx

    def test_cancel_restores_invoice_membership(self, api):
        """PRD section 3.9: "Cancellation is allowed only from `OPEN`, moves
        the batch to `CANCELLED`, and compensates every member invoice back
        from `BATCHED` to `APPROVED` with `payment_batch_id` cleared to
        null."

        Design: Difficulty/compensating_invariant/batch_cancel_membership_invariant
        """
        ctx = self._setup_batched(api)
        cancelled = validate_success(
            _api.cancel_batch(ctx["batch"]["id"],
                              make_finance_headers("fin-1")))
        assert cancelled["status"] == "CANCELLED"

        invoice = get_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "APPROVED", "compensation to pre-add state"
        assert invoice["payment_batch_id"] is None
        assert (get_assignment(ctx["assignment"]["id"])["payment_status"]
                == "PAYABLE"), "add/cancel never touches the payment axis"

    def test_cancelled_membership_posts_nothing_and_can_rebatch(self, api):
        """PRD section 3.9: "Cancellation is allowed only from `OPEN`, moves
        the batch to `CANCELLED`, and compensates every member invoice back
        from `BATCHED` to `APPROVED` with `payment_batch_id` cleared to
        null."
        PRD section 3.9: "Each member invoice then posts its ledger entries
        and moves to `PAID`" (only on release).

        Design: Difficulty/compensating_invariant/batch_cancel_membership_invariant
        """
        ctx = self._setup_batched(api)
        validate_success(
            _api.cancel_batch(ctx["batch"]["id"],
                              make_finance_headers("fin-1")))

        entries = get_success_data(
            _api.list_invoice_ledger_entries(ctx["invoice"]["id"],
                                             make_finance_headers("fin-1")))
        assert entries == [], "add/cancel round trip posts no ledger rows"

        # The compensated invoice is a clean member of a fresh batch.
        new_batch = create_batch("2026-08-21T00:00:00Z")
        readded = validate_success(
            _api.add_invoice_to_batch(
                new_batch["id"], {"invoice_id": ctx["invoice"]["id"]},
                make_finance_headers("fin-1")))
        assert readded["status"] == "OPEN"
        assert get_invoice(ctx["invoice"]["id"])["status"] == "BATCHED"


def test_batch_release_with_stale_version_rejected(api):
    """PRD section 3.9: "It requires the batch `LOCKED`, a releasing
    `FinanceUser` whose `X-User-ID` differs from `locked_by_user_id`
    (segregation of duties), and `expected_batch_version` matching the
    batch's current `version` — a stale value is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD section 3.9: "Adding an invoice requires the caller to supply the
    `invoice_id` of an `APPROVED` invoice and requires the batch to be
    `OPEN` — otherwise `ERR_BATCH_NOT_OPEN` — and sets the invoice's
    `payment_batch_id`, moves the invoice to `BATCHED`, recomputes the batch
    totals, and bumps the batch `version`."
    PRD section 3.9: "Locking the batch moves it to `LOCKED`, records
    `locked_by_user_id` from the caller's `X-User-ID`, freezes the three
    totals, and bumps the version; locking an empty batch is rejected with
    `ERR_BATCH_NOT_OPEN`."

    Design: Corner/cross_cutting_layers/occ_batch_release_stale_version
    """
    ctx = setup_approved_invoice(legal_name="Occ Otto", email="otto@x.com",
                                 pricing_mode="FLAT", flat_fee_cents=50000)
    batch = create_batch("2026-08-20T00:00:00Z")
    added = add_invoice_to_batch(batch["id"], ctx["invoice"]["id"])
    pre_lock_version = added["version"]
    locked = lock_batch(batch["id"])
    assert locked["version"] > pre_lock_version, "lock bumps the version"

    resp = _api.release_batch(
        batch["id"], {"expected_batch_version": pre_lock_version},
        make_finance_headers("fin-2"))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
    assert get_batch(batch["id"])["status"] == "LOCKED"

    # Control: the current version releases cleanly.
    released = release_batch(batch["id"], locked["version"])
    assert released["status"] == "RELEASED"


def test_batch_locker_cannot_release(api):
    """PRD section 2.8: "The `FinanceUser` whose identifier was recorded in
    `locked_by_user_id` when a batch was locked may not release that batch."
    PRD section 3.9: "It requires the batch `LOCKED`, a releasing
    `FinanceUser` whose `X-User-ID` differs from `locked_by_user_id`
    (segregation of duties), and `expected_batch_version` matching the
    batch's current `version` — a stale value is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/validations/sod_batch_release_same_locker
    """
    ctx = setup_batched_invoice(legal_name="Lock Lee", email="lee@x.com",
                                pricing_mode="FLAT", flat_fee_cents=50000)
    assert ctx["batch"]["locked_by_user_id"] == "fin-1"

    resp = _api.release_batch(
        ctx["batch"]["id"],
        {"expected_batch_version": ctx["batch_version"]},
        make_finance_headers("fin-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    assert get_batch(ctx["batch"]["id"])["status"] == "LOCKED"

    released = release_batch(ctx["batch"]["id"], ctx["batch_version"],
                             user_id="fin-2")
    assert released["status"] == "RELEASED"


def test_locking_empty_batch_rejected(api):
    """PRD section 3.9: "locking an empty batch is rejected with
    `ERR_BATCH_NOT_OPEN`."

    Design: Corner/errors/batch_lock_empty_rejected
    """
    bootstrap_desk()
    batch = create_batch("2026-08-20T00:00:00Z")
    resp = _api.lock_batch(batch["id"], make_finance_headers("fin-1"))
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_OPEN, 409)
    assert get_batch(batch["id"])["status"] == "OPEN"


def test_ledger_entries_are_append_only_postings(api):
    """PRD section 2.4: "`LedgerEntry` is the single exception: it carries
    `id` and `created_at` only; `updated_at` and `version` are absent because
    postings are immutable."
    PRD section 3.9: "Each member invoice then posts its ledger entries and
    moves to `PAID`: a `FEE_CREDIT` entry of plus `fee_claim_cents`, an
    `EXPENSE_CREDIT` entry of plus `expense_claim_cents`, a
    `WITHHOLDING_DEBIT` entry of minus `withholding_cents`, and a
    `LATE_FEE_CREDIT` entry of plus `late_fee_cents` when that amount is
    positive."

    Design: Corner/entities/ledger_entry_immutability
    """
    ctx = setup_paid_invoice(legal_name="Ledger Liz", email="liz@x.com",
                             pricing_mode="FLAT", flat_fee_cents=50000)
    entries = get_success_data(
        _api.list_contributor_ledger_entries(ctx["contributor"]["id"],
                                             make_finance_headers("fin-1")))
    assert len(entries) >= 2
    by_kind = {}
    for entry in entries:
        assert_ledger_entry(entry)  # id + created_at only; no version
        by_kind.setdefault(entry["entry_kind"], []).append(
            entry["amount_cents"])
        # posted_at is server-stamped from the logical clock at release
        # (the clock was never advanced: startup default 2026-08-01).
        assert _parse_ts(entry["posted_at"]) == datetime(
            2026, 8, 1, tzinfo=timezone.utc)
    assert by_kind["FEE_CREDIT"] == [50000]
    assert by_kind["WITHHOLDING_DEBIT"] == [0], "valid W9 withholds zero"


def test_add_invoice_response_shows_recomputed_totals(api):
    """PRD section 3.9: "Adding an invoice requires the caller to supply the
    `invoice_id` of an `APPROVED` invoice and requires the batch to be
    `OPEN` — otherwise `ERR_BATCH_NOT_OPEN` — and sets the invoice's
    `payment_batch_id`, moves the invoice to `BATCHED`, recomputes the batch
    totals, and bumps the batch `version`."
    PRD section 3.8: "For a `DOMESTIC_US` contributor, if
    `backup_withholding_flag` is true or no such valid document exists, the
    rate is the desk's `backup_withholding_rate_bps` (default 2400, i.e.
    24%); otherwise the rate is zero."

    Design: Corner/consistency_model/immediate_consistency_batch_totals
    """
    ctx, claim = setup_accepted_with_reimbursable_expense(
        legal_name="Imm Ivan", email="ivan@x.com", pricing_mode="FLAT",
        flat_fee_cents=50000, category="TRAVEL", requested_cents=5000,
        claimed_cents=5000, receipt_attached=True)
    invoice = submit_invoice(ctx["assignment"]["id"],
                             ctx["contributor"]["id"], 50000, 5000)
    # Verified before any tax document exists: backup branch (24% on fee).
    verified = verify_invoice(invoice["id"], "VERIFY")
    assert verified["gross_cents"] == 55000
    assert verified["withholding_cents"] == 12000, "floor(50000 * 2400 / 10000)"
    assert verified["net_payable_cents"] == 43000
    # A VERIFIED document must exist at approval time (PRD 3.8).
    create_verified_tax_document(ctx["contributor"]["id"], doc_kind="W9",
                                 tin_last4="4321")
    approve_invoice(invoice["id"])

    batch = create_batch("2026-08-20T00:00:00Z")
    resp = _api.add_invoice_to_batch(
        batch["id"], {"invoice_id": invoice["id"]},
        make_finance_headers("fin-1"))
    data = validate_success(resp, 200)
    assert data["total_gross_cents"] == 55000
    assert data["total_withholding_cents"] == 12000
    assert data["total_net_cents"] == 43000
    # Immediate consistency: the membership change is visible on re-read.
    assert get_invoice(invoice["id"])["status"] == "BATCHED"
