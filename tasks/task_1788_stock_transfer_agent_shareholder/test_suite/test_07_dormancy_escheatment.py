"""Dormancy determination, the escheatment pipeline (notice, valuation,
remittance), the reactivation cycle, and the stale-dating cascade."""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    ApiErrorId,
    create_account,
    create_declaration,
    create_issuer,
    get_account,
    get_case,
    get_issuer,
    get_position,
    list_cases,
    remit_case,
    report_case,
    scan_dormancy,
    seed_position,
    send_notice,
    set_clock,
    setup_ca_dormancy_pair,
    setup_dormant_account_with_case,
    setup_reactivated_case,
    setup_report_ready_case,
    setup_reported_case,
    single_case,
    single_payment,
    validate_error,
)


class TestEscheatmentValuationOrder:
    def test_escheatment_report_freezes_price_and_share_leg(self, api):
        """PRD §3.7: "Reporting moves the case `NOTICE_SENT` → `REPORTED` and
        freezes the case's valuation in a pinned order. First the issuer's
        `current_market_price_cents` at that instant is frozen onto the case as
        `report_price_cents`. Second, the share leg `share_value_cents` is
        computed as the sum of `total_shares` across all of the account's
        positions, multiplied by the frozen `report_price_cents`."

        Design: Difficulty/combinatorial_formula/escheatment_valuation_evaluation_order
        """
        ctx = setup_report_ready_case()
        case = report_case(ctx["case"]["id"])

        assert case["status"] == "REPORTED"
        assert case["report_price_cents"] == 6000, "frozen at REPORTED (step 1)"
        assert case["share_value_cents"] == 60000, "10 shares x 6000 (step 2)"

    def test_escheatment_report_cash_leg_and_total(self, api):
        """PRD §3.7: "Third, the cash leg `cash_value_cents` is computed as the
        sum of `gross_cents` over all of the account's payments in
        `STALE_DATED` status. Finally `total_remit_cents` is the sum of the two
        legs."
        PRD §3.7: "all four figures are integer cents with no rounding, since
        integer share counts multiply integer prices."

        Design: Difficulty/combinatorial_formula/escheatment_valuation_evaluation_order
        """
        ctx = setup_report_ready_case()
        case = report_case(ctx["case"]["id"])

        assert case["cash_value_cents"] == 250, (
            "the single STALE_DATED payment's gross (step 3)"
        )
        assert case["total_remit_cents"] == 60250, "60000 + 250 (step 4)"


class TestStaleDatingCascade:
    def _setup_stale_scenario(self):
        issuer = create_issuer(name="Iota Ltd", cusip="000000009",
                               ticker="IOTA", shares_outstanding=10,
                               current_market_price_cents=6000)
        account = create_account(holder_name="Kara Stale", state_code="CA",
                                 city="Los Angeles", postal_code="90002",
                                 tax_id="303-03-0303", tin_status="CERTIFIED")
        seed_position(account["id"], issuer["id"], 10)
        declaration = create_declaration(
            issuer, record_date="2026-08-02T00:00:00Z",
            payable_date="2026-08-03T00:00:00Z",
            amount_per_share_millicents=25000)
        set_clock("2026-08-02T00:00:00Z")
        set_clock("2026-08-03T00:00:00Z")
        return {"issuer": issuer, "account": account, "declaration": declaration}

    def test_stale_dating_marks_payment_and_ledgers_account(self, api):
        """PRD §3.5: "When the logical clock reaches the instant one hundred
        eighty days after a payment's `disbursed_at` — the boundary day itself
        counts — a `DISBURSED` payment moves `DISBURSED` → `STALE_DATED`. The
        account's `stale_dividend_cents` is then increased by the payment's
        `gross_cents`, keeping a running total of unclaimed cash on the
        account."

        Design: Difficulty/transitive_cascade/stale_dating_cascade_payment_account_case
        """
        ctx = self._setup_stale_scenario()
        set_clock("2029-08-01T00:00:00Z")  # disbursed 2026-08-03 + 180d passed

        payment = single_payment(ctx["declaration"]["id"])
        assert payment["status"] == "STALE_DATED", "hop1 stale-dates the payment"
        account = get_account(ctx["account"]["id"])
        assert account["stale_dividend_cents"] == 250, (
            "hop2 adds the payment gross to the unclaimed-cash ledger"
        )

    def test_sweep_after_stale_dating_identifies_case(self, api):
        """PRD §3.7: "For each newly dormant account that still holds property
        — any position with `total_shares` above zero, or a nonzero
        `stale_dividend_cents` balance — and that has no escheatment case
        currently open in `IDENTIFIED`, `NOTICE_SENT`, or `REPORTED` status,
        the sweep opens an `EscheatmentCase` in `IDENTIFIED` status"
        PRD §3.7: "moves each account that has crossed its dormancy horizon
        `ACTIVE` → `DORMANT`"

        Design: Difficulty/transitive_cascade/stale_dating_cascade_payment_account_case
        """
        ctx = self._setup_stale_scenario()
        set_clock("2029-08-01T00:00:00Z")  # CA 3-year anniversary, inclusive
        scan = scan_dormancy()
        assert scan["accounts_marked_dormant"] >= 1

        account = get_account(ctx["account"]["id"])
        assert account["account_status"] == "DORMANT"
        case = single_case(ctx["account"]["id"])
        assert case["status"] == "IDENTIFIED", (
            "hop3: the sweep identifies exactly one case for the account"
        )


class TestReactivationCycle:
    def test_case_rearmed_not_duplicated(self, api):
        """PRD §3.7: "When the account's previous case ended in `REACTIVATED`,
        that same case is re-armed `REACTIVATED` → `IDENTIFIED` with a
        refreshed `dormancy_start_date`, so property may dormancy-cycle
        repeatedly until it is finally remitted."

        Design: Difficulty/non_linear_state_machine/escheatment_case_reactivation_cycle
        """
        ctx = setup_reactivated_case()  # swept at 2029-08-01, then reactivated
        assert ctx["case"]["status"] == "REACTIVATED"
        assert ctx["account"]["account_status"] == "ACTIVE"

        set_clock("2032-08-01T00:00:00Z")  # second 3-year anniversary
        scan_dormancy()
        cases = list_cases(account_id=ctx["account"]["id"])
        assert len(cases) == 1, "the same case is re-armed, not duplicated"
        assert cases[0]["id"] == ctx["case"]["id"]
        assert cases[0]["status"] == "IDENTIFIED"

    def test_rearm_refreshes_dates(self, api):
        """PRD §3.7: "the sweep opens an `EscheatmentCase` in `IDENTIFIED`
        status, recording the account's `last_qualifying_contact_date` at
        identification as the case's `dormancy_start_date`."
        PRD §3.7: "moves a `DORMANT` account back `DORMANT` → `ACTIVE`,
        refreshes its `last_qualifying_contact_date` to the logical clock"

        Design: Difficulty/non_linear_state_machine/escheatment_case_reactivation_cycle
        """
        ctx = setup_reactivated_case()
        set_clock("2032-08-01T00:00:00Z")
        scan_dormancy()

        case = single_case(ctx["account"]["id"])
        assert case["dormancy_start_date"] == "2029-08-01T00:00:00.000Z", (
            "refreshed to the reactivation contact date at re-arm"
        )
        account = get_account(ctx["account"]["id"])
        assert account["account_status"] == "DORMANT"
        assert account["last_qualifying_contact_date"] == "2029-08-01T00:00:00.000Z"


class TestDormancyBoundary:
    def test_dormancy_exact_anniversary_is_dormant(self, api):
        """PRD §3.7: "An `ACTIVE` account becomes dormant when the logical
        clock has reached the instant exactly that many years after its
        `last_qualifying_contact_date`. The boundary is inclusive — an account
        whose last qualifying contact was exactly `dormancy_years` ago, to the
        very second, is dormant"
        PRD §3.7: "The sweep reports back the `accounts_marked_dormant` and
        `cases_created` counts"

        Design: Difficulty/boundary_precision_check/dormancy_boundary_inclusive_year
        """
        ctx = setup_ca_dormancy_pair()
        set_clock("2029-08-01T00:00:00Z")
        scan = scan_dormancy()

        c1 = get_account(ctx["c1"]["id"])
        assert c1["account_status"] == "DORMANT", (
            "2029-08-01 >= 2026-08-01 + 3 years, inclusive boundary"
        )
        assert scan["accounts_marked_dormant"] == 1

    def test_one_day_short_of_anniversary_stays_active(self, api):
        """PRD §3.7: "The boundary is inclusive — an account whose last
        qualifying contact was exactly `dormancy_years` ago, to the very
        second, is dormant — while an account one second short of the
        anniversary is not."

        Design: Difficulty/boundary_precision_check/dormancy_boundary_inclusive_year
        """
        ctx = setup_ca_dormancy_pair()
        set_clock("2029-08-01T00:00:00Z")
        scan_dormancy()

        c2 = get_account(ctx["c2"]["id"])
        assert c2["account_status"] == "ACTIVE", (
            "2029-08-01 is one day short of 2026-08-02 + 3 years"
        )
        assert list_cases(account_id=ctx["c2"]["id"]) == []


class TestDormancyTable:
    def test_ny_five_year_dormancy_vs_tx_three_year(self, api):
        """PRD §3.7: "the platform determines that period from the account's
        `state_code` via its computed `dormancy_years`: three years for `CA`,
        five years for `NY`, three years for `TX`, and five years for every
        other state."

        Design: Corner/calculations/ny_five_year_dormancy_vs_tx_three_year
        """
        issuer = create_issuer(name="Kappa Dormant", cusip="000000034",
                               ticker="KDOR", shares_outstanding=2)
        ny = create_account(holder_name="NY Nancy", state_code="NY",
                            city="Albany", postal_code="12202",
                            tax_id="322-12-1212")
        tx = create_account(holder_name="TX Tara", state_code="TX",
                            city="Dallas", postal_code="75204",
                            tax_id="332-12-1212")
        seed_position(ny["id"], issuer["id"], 1)
        seed_position(tx["id"], issuer["id"], 1)

        set_clock("2030-08-01T00:00:00Z")  # 4 years elapsed
        scan_dormancy()
        assert get_account(tx["id"])["account_status"] == "DORMANT", (
            "TX 3-year entry crossed"
        )
        ny_read = get_account(ny["id"])
        assert ny_read["account_status"] == "ACTIVE", "4 years < NY 5-year entry"
        assert ny_read["dormancy_years"] == 5
        assert get_account(tx["id"])["dormancy_years"] == 3

        set_clock("2031-08-01T00:00:00Z")  # NY 5-year anniversary
        scan_dormancy()
        assert get_account(ny["id"])["account_status"] == "DORMANT"


class TestNoticeWindow:
    def test_report_before_notice_window_rejected(self, api):
        """PRD §3.7: "Reporting to the state comes next, but only after the
        notice window has run: the logical clock must have reached the instant
        sixty days after `notice_sent_at`, the boundary day itself being
        eligible, and an earlier report is refused with
        `ERR_NOTICE_WINDOW_NOT_ELAPSED`."

        Design: Corner/validations/report_before_notice_window_rejected
        """
        ctx = setup_dormant_account_with_case(state_code="CA", shares=5,
                                              holder_name="Notice Ned")
        send_notice(ctx["case"]["id"])  # notice_sent_at = 2029-08-01
        set_clock("2029-09-15T00:00:00Z")  # 45 days later

        resp = api.report_case(ctx["case"]["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_NOT_ELAPSED)
        assert get_case(ctx["case"]["id"])["status"] == "NOTICE_SENT"


class TestEscheatedLockdown:
    def test_escheated_account_terminal_lockdown(self, api):
        """PRD §3.7: "The account then moves `DORMANT` → `ESCHEATED` — a
        terminal state, audited as `account.escheated` — and every one of its
        `ACTIVE` positions moves `ACTIVE` → `CLOSED` with `book_entry_shares`,
        `restricted_shares`, and `certificated_shares` all zeroed, while every
        one of its `STALE_DATED` payments moves to `ESCHEATED`, each such
        payment relieving the account's `stale_dividend_cents` by its own
        `gross_cents`."
        PRD §3.7: "An `ESCHEATED` account is dead to the register: any later
        mutation targeting it is refused with `ERR_ACCOUNT_ESCHEATED`."

        Design: Corner/state_machines/escheated_account_terminal_lockdown
        """
        ctx = setup_reported_case()
        remitted = remit_case(ctx["case"]["id"])
        assert remitted["status"] == "REMITTED"

        account = get_account(ctx["account"]["id"])
        assert account["account_status"] == "ESCHEATED", "terminal state"
        assert account["stale_dividend_cents"] == 0, "the stale cash is relieved"

        position = get_position(ctx["account"]["id"], ctx["issuer"]["id"])
        assert position["status"] == "CLOSED"
        assert position["book_entry_shares"] == 0
        assert position["certificated_shares"] == 0
        assert position["total_shares"] == 0

        payment = single_payment(ctx["declaration"]["id"])
        assert payment["status"] == "ESCHEATED"

        issuer = get_issuer(ctx["issuer"]["id"])
        assert issuer["total_book_entry_shares"] == 0, (
            "the issuer aggregates are recomputed after the remit cascade"
        )

        resp = api.patch_account(ctx["account"]["id"],
                                 {"address_line1": "12 Back St"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_ESCHEATED)
