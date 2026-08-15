"""Share account opening, par-value floors, transaction posting bounds, and
the chronological ledger replay."""
from test_helpers import (
    ApiErrorId,
    assert_share_account,
    assert_share_transaction,
    create_member,
    create_share_account_payload,
    create_transaction_payload,
    flag_review,
    get_member,
    list_account_transactions,
    post_transaction,
    set_clock,
    setup_charter,
    setup_member_with_primary,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

FILER = TEST_USERS["membership_officer_headers"]
DECIDER = TEST_USERS["membership_officer_2_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]
OPS = TEST_USERS["operations_officer_headers"]


class TestParValueFloors:
    def test_par_value_boundary_on_open_and_withdrawal(self, api):
        """PRD §3.5: "The PRIMARY account is where par value bites: its opening
        deposit must be at least the charter's `par_value_cents`, with a
        deposit of exactly par qualifying, and anything less rejected with
        `ERR_BELOW_PAR_VALUE`."
        PRD §3.5: "A WITHDRAWAL on a PRIMARY account must leave the balance at
        no less than the charter's `par_value_cents` — a withdrawal that would
        take the account below par is rejected with `ERR_PAR_VALUE_BREACH`"

        Design: Corner/validations/par_value_boundary_on_open_and_withdrawal
        """
        set_clock("2026-08-01")
        _charter, seg_ids = setup_charter()
        member_id = create_member(segment_id=seg_ids[0], name="Par Pam")

        below = api.create_share_account(
            create_share_account_payload(member_id, initial_deposit_cents=499),
            FILER)
        validate_error(below, ApiErrorId.ERR_BELOW_PAR_VALUE)

        account = validate_success(api.create_share_account(
            create_share_account_payload(member_id, initial_deposit_cents=500),
            FILER), 201)
        assert_share_account(account)
        assert account["balance_cents"] == 500, "Exact-par opening qualifies"

        post_transaction(account["id"], "DEPOSIT", 99_500, "2026-08-01")
        at_par = post_transaction(account["id"], "WITHDRAWAL", 99_500,
                                  "2026-08-01")
        assert at_par["running_balance_cents"] == 500, (
            "Withdrawing down to exactly par is allowed")

        breach = api.post_share_transaction(
            account["id"],
            create_transaction_payload("WITHDRAWAL", 1, "2026-08-01"), OPS)
        validate_error(breach, ApiErrorId.ERR_PAR_VALUE_BREACH)

    def test_primary_account_uniqueness_and_close_guard(self, api):
        """PRD §3.5: "Every member holds exactly one PRIMARY account; a second
        attempt is rejected with `ERR_PRIMARY_ACCOUNT_EXISTS`."
        PRD §3.5: "a manual close of the PRIMARY account is permitted only
        while the owning member is not ACTIVE; attempting it for an ACTIVE
        member fails with `ERR_PRIMARY_ACCOUNT_REQUIRED`."

        Design: Corner/validations/primary_account_uniqueness_and_close_guard
        """
        set_clock("2026-08-01")
        ctx = setup_member_with_primary(deposit=100_000, name="Primary Pete")
        member_id = ctx["member_id"]
        account = ctx["account"]

        dup = api.create_share_account(
            create_share_account_payload(member_id, initial_deposit_cents=500),
            FILER)
        validate_error(dup, ApiErrorId.ERR_PRIMARY_ACCOUNT_EXISTS)

        close = api.close_share_account(account["id"], FILER)
        validate_error(close, ApiErrorId.ERR_PRIMARY_ACCOUNT_REQUIRED)


class TestTransactionPosting:
    def test_transaction_posted_date_bounds(self, api):
        """PRD §3.5: "Backdating is permitted within bounds: the `posted_date`
        must be on or after the account's `opened_date` and on or before the
        current clock date, otherwise `ERR_INVALID_TRANSACTION_DATE`."

        Design: Corner/validations/transaction_posted_date_bounds
        """
        set_clock("2026-08-01")
        ctx = setup_member_with_primary(deposit=100_000, name="Date Drew")
        account = ctx["account"]
        assert account["opened_date"] == "2026-08-01"

        future = api.post_share_transaction(
            account["id"],
            create_transaction_payload("DEPOSIT", 100, "2026-08-02"), OPS)
        validate_error(future, ApiErrorId.ERR_INVALID_TRANSACTION_DATE)

        before_open = api.post_share_transaction(
            account["id"],
            create_transaction_payload("DEPOSIT", 100, "2026-07-31"), OPS)
        validate_error(before_open, ApiErrorId.ERR_INVALID_TRANSACTION_DATE)

    def test_withdrawal_insufficient_funds_boundary(self, api):
        """PRD §3.5: "a SUPPLEMENTAL account merely bottoms out at zero, with a
        withdrawal exceeding the balance rejected with
        `ERR_INSUFFICIENT_FUNDS`."

        Design: Corner/validations/withdrawal_insufficient_funds_boundary
        """
        set_clock("2026-08-01")
        ctx = setup_member_with_primary(deposit=50_000, name="Fund Fred",
                                        account_type="SUPPLEMENTAL")
        account = ctx["account"]

        over = api.post_share_transaction(
            account["id"],
            create_transaction_payload("WITHDRAWAL", 50_001, "2026-08-01"), OPS)
        validate_error(over, ApiErrorId.ERR_INSUFFICIENT_FUNDS)

        exact = post_transaction(account["id"], "WITHDRAWAL", 50_000,
                                 "2026-08-01")
        assert exact["running_balance_cents"] == 0, (
            "An exact-balance withdrawal is allowed (floor zero)")

    def test_transaction_on_closed_account_rejected(self, api):
        """PRD §3.5: "The account must be OPEN, otherwise
        `ERR_ACCOUNT_NOT_OPEN`."
        PRD §3.5: "A `MembershipOfficer` may manually close an OPEN account —
        closing one in any other state fails with `ERR_ACCOUNT_NOT_OPEN`"

        Design: Corner/state_machines/transaction_on_closed_account_rejected
        """
        set_clock("2026-08-01")
        ctx = setup_member_with_primary(deposit=5_000, name="Closed Carl",
                                        account_type="SUPPLEMENTAL")
        account = ctx["account"]
        closed = validate_success(api.close_share_account(account["id"], FILER))
        assert closed["status"] == "CLOSED"
        assert closed["closure_reason"] == "MANUAL"
        assert closed["balance_cents"] == 0

        resp = api.post_share_transaction(
            account["id"],
            create_transaction_payload("DEPOSIT", 100, "2026-08-01"), OPS)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_OPEN)


class TestLedgerReplay:
    def test_share_balance_replay_same_day_ordering(self, api):
        """PRD §3.5: "All of an account's ShareTransaction rows are ordered by
        `posted_date` ascending with ties broken by `created_at` ascending;
        replaying in that order, DEPOSIT and DIVIDEND_CREDIT rows add their
        `amount_cents` while WITHDRAWAL and CLOSURE_DISBURSEMENT rows subtract
        theirs; each row's `running_balance_cents` captures the balance
        immediately after it, and the account's `balance_cents` equals the
        running balance of the final row."

        Design: Corner/calculations/share_balance_replay_same_day_ordering
        """
        set_clock("2026-08-01")
        ctx = setup_member_with_primary(deposit=100_000, name="Order Ollie")
        account = ctx["account"]

        deposit = post_transaction(account["id"], "DEPOSIT", 50_000,
                                   "2026-08-01")
        assert deposit["running_balance_cents"] == 150_000

        withdrawal = validate_success(api.post_share_transaction(
            account["id"],
            create_transaction_payload("WITHDRAWAL", 30_000, "2026-08-01"),
            OPS), 201)
        assert withdrawal["running_balance_cents"] == 120_000, (
            "Same-date rows replay in creation order")

        rows = list_account_transactions(account["id"])
        assert [r["running_balance_cents"] for r in rows] == [
            100_000, 150_000, 120_000]
        refreshed = validate_success(api.get_share_account(account["id"], OPS))
        assert refreshed["balance_cents"] == 120_000

    def test_derived_running_balance_after_backdated_insert(self, api):
        """PRD §3.5: "A backdated insert re-runs the full replay and rewrites
        the running balances of every later row, so history is always
        internally consistent. The transaction list returns rows in exactly
        this replay order, and each row's `share_account_id` ties it to its
        account."

        Design: Corner/cross_cutting_layers/derived_running_balance_after_backdated_insert
        """
        set_clock("2026-08-01")
        ctx = setup_member_with_primary(deposit=100_000, name="Replay Ray")
        account = ctx["account"]

        set_clock("2026-08-03")
        post_transaction(account["id"], "WITHDRAWAL", 20_000, "2026-08-03")

        backdated = validate_success(api.post_share_transaction(
            account["id"],
            create_transaction_payload("DEPOSIT", 50_000, "2026-08-02"),
            OPS), 201)
        assert backdated["running_balance_cents"] == 150_000, (
            "The backdated row replays into its posted_date position")

        rows = list_account_transactions(account["id"])
        assert [r["posted_date"] for r in rows] == [
            "2026-08-01", "2026-08-02", "2026-08-03"]
        assert [r["running_balance_cents"] for r in rows] == [
            100_000, 150_000, 130_000], (
            "The later withdrawal's running balance was rewritten")

        refreshed = validate_success(api.get_share_account(account["id"], OPS))
        assert refreshed["balance_cents"] == 130_000

    def test_share_transaction_immutable_event_shape(self, api):
        """PRD §2.4: "a ShareTransaction and a Ballot are immutable ledger
        records that carry only `id` and `created_at`; both `updated_at` and
        `version` are absent from them."
        PRD §3.5: "Opening writes the account's first ledger entry — a
        ShareTransaction of kind DEPOSIT with `origin` SYSTEM, posted on the
        current clock date"
        PRD §3.5: "Every endpoint-posted row carries `origin` MANUAL"

        Design: Corner/entities/share_transaction_immutable_event_shape
        """
        set_clock("2026-08-01")
        ctx = setup_member_with_primary(deposit=100_000, name="Event Eve")
        account = ctx["account"]
        post_transaction(account["id"], "DEPOSIT", 2_500, "2026-08-01")

        rows = list_account_transactions(account["id"])
        assert len(rows) == 2
        opening, manual = rows[0], rows[1]
        assert opening["kind"] == "DEPOSIT"
        assert opening["origin"] == "SYSTEM"
        assert opening["running_balance_cents"] == 100_000
        assert opening["posted_date"] == "2026-08-01"
        assert manual["kind"] == "DEPOSIT"
        assert manual["origin"] == "MANUAL"
        assert manual["running_balance_cents"] == 102_500
        for row in rows:
            assert_share_transaction(row)  # also asserts updated_at/version absent
            assert row["share_account_id"] == account["id"]


class TestAccountOpenValidationPriority:
    def _setup_ineligible_member(self, api):
        set_clock("2026-07-01")
        _charter, seg_ids = setup_charter()
        member_id = create_member(segment_id=seg_ids[0], name="Dual Fail",
                                  date_of_birth="1990-09-09")
        flag_review(member_id)  # member -> INELIGIBLE_UNDER_REVIEW
        return member_id

    def test_member_state_error_precedes_par_value_error(self, api):
        """PRD §2.6: "Every request passes through an ordered ladder of
        validation tiers. The first tier that fails determines the error
        returned; later tiers are never consulted for a request that has
        already been rejected."
        PRD §2.6 tier 7: "The member must be ACTIVE for account opening,
        enrollment, ballot casting, or manual review creation
        (`ERR_MEMBER_NOT_ACTIVE`)"; tier 12: "Opening-deposit and withdrawal
        floors — `ERR_BELOW_PAR_VALUE`, `ERR_PAR_VALUE_BREACH`,
        `ERR_INSUFFICIENT_FUNDS` (all 422)."

        Design: Difficulty/priority_pair_validation_conflict/account_open_member_state_vs_par_value_fiscal
        """
        member_id = self._setup_ineligible_member(api)
        assert get_member(member_id)["status"] == "INELIGIBLE_UNDER_REVIEW"

        resp = api.create_share_account(
            create_share_account_payload(member_id, initial_deposit_cents=100),
            FILER)
        # A 100-cent opening is also below the 500-cent par value, but the
        # state precondition tier is evaluated before the funds tier.
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)

    def test_rejected_account_opening_persists_nothing(self, api):
        """PRD §2.6: "The first tier that fails determines the error returned;
        later tiers are never consulted for a request that has already been
        rejected."
        PRD §3.5: "Membership becomes real when a `MembershipOfficer` opens a
        share account for an ACTIVE member — any other posture fails with
        `ERR_MEMBER_NOT_ACTIVE`"

        Design: Difficulty/priority_pair_validation_conflict/account_open_member_state_vs_par_value_fiscal
        """
        member_id = self._setup_ineligible_member(api)

        resp = api.create_share_account(
            create_share_account_payload(member_id, initial_deposit_cents=100),
            FILER)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)

        accounts, meta = validate_paginated(
            api.list_member_share_accounts(member_id, FILER))
        assert meta["total_count"] == 0
        assert accounts == [], "No ShareAccount is created by the rejection"
