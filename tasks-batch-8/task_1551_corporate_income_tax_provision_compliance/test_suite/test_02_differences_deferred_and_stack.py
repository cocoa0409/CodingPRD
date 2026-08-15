"""Book-to-tax differences, the deferred tax rollforward, and the current
tax stack.

Covers the review/rework/lock/reject lifecycle, the deferred-item cascade
(hops 1-3b), the permanent/zero input-set exclusion, the LIABILITY sign
convention, terminal-state lockdown, the post-lock posture gate, per-lock
reconciliation, and the pinned state-then-federal evaluation order.
"""
from test_helpers import (
    ApiErrorId,
    assert_rollforward_invariant,
    create_draft_allowance,
    create_filing_record,
    create_fy2026_tax_year,
    create_locked_difference,
    create_reviewed_difference,
    create_us_ca_jurisdiction,
    create_us_fed_jurisdiction,
    get_tax_year,
    list_deferred_items,
    make_tax_accountant_headers,
    setup_locked_year_with_filing,
    setup_open_year_with_jurisdiction,
    validate_error,
    validate_success,
)


class TestDifferenceCreation:
    def test_creation_computes_difference_and_stamps_creator(
            self, api, tax_accountant_headers):
        """PRD §3.2: "The server computes `difference_cents` as
        `book_amount_cents` minus `tax_amount_cents` — an exact integer
        subtraction, no rounding"
        PRD §3.2: "The new record lands in status `IDENTIFIED`, with
        `created_by_user_id` captured from the caller's `X-User-ID`."

        Design: Corner/entities/difference_creation_computed_fields_immediate
        """
        ty, jur = setup_open_year_with_jurisdiction()
        creator = make_tax_accountant_headers("acct-7")
        payload = {
            "tax_year_id": ty["id"],
            "jurisdiction_id": jur["id"],
            "description": "accrued warranty",
            "book_amount_cents": 5000000,
            "tax_amount_cents": 2000000,
            "difference_type": "TEMPORARY",
        }
        diff = validate_success(
            api.create_book_tax_difference(payload, creator), 201)
        assert diff["difference_cents"] == 3000000
        assert diff["status"] == "IDENTIFIED"
        assert diff["created_by_user_id"] == "acct-7"


class TestReworkCycle:
    def test_rework_loop_returns_to_identified_and_clears_reviewer(
            self, api, tax_manager_headers):
        """PRD §3.2: "Returning it for rework cycles it back to `IDENTIFIED`
        and clears `reviewed_by_user_id` to null."
        PRD §2.4: "a `version` integer that starts at its initial value and
        increments on mutation."

        Design: Difficulty/non_linear_state_machine/book_tax_difference_review_rework_cycle
        """
        ty, jur = setup_open_year_with_jurisdiction()
        diff = create_reviewed_difference(ty["id"], jur["id"])
        assert diff["status"] == "REVIEWED"
        reviewed_version = diff["version"]
        assert diff["reviewed_by_user_id"] == "mgr-1"

        reworked = validate_success(
            api.return_difference_for_rework(diff["id"], tax_manager_headers),
            200)
        assert reworked["status"] == "IDENTIFIED"
        assert reworked.get("reviewed_by_user_id") is None
        assert reworked["version"] > reviewed_version, \
            "the rework transition is a mutation and must increment version"

    def test_cycle_terminates_in_lock_with_single_deferred_item(
            self, api, tax_manager_headers):
        """PRD §3.2: "Locking it — a motion shared by `TaxManager` and
        `TaxDirector` — moves it to `LOCKED` and fires the deferred-tax
        cascade."
        PRD §3.2: "Hop 1: when the locked difference is `TEMPORARY` with a
        nonzero `difference_cents`, the server upserts a `DeferredTaxItem`
        whose `source_difference_id` points back to the difference"

        Design: Difficulty/non_linear_state_machine/book_tax_difference_review_rework_cycle
        """
        ty, jur = setup_open_year_with_jurisdiction()
        diff = create_reviewed_difference(ty["id"], jur["id"])
        validate_success(
            api.return_difference_for_rework(diff["id"], tax_manager_headers),
            200)
        reviewed_again = validate_success(
            api.review_difference(diff["id"], tax_manager_headers), 200)
        locked = validate_success(
            api.lock_difference(diff["id"], tax_manager_headers), 200)

        assert reviewed_again["status"] == "REVIEWED"
        assert locked["status"] == "LOCKED"
        assert locked["version"] > reviewed_again["version"]

        items = list_deferred_items(
            params={"source_difference_id": diff["id"]})
        assert len(items) == 1, \
            "the cascade fires exactly once, on the final lock"
        assert items[0]["item_kind"] == "ASSET"
        assert items[0]["closing_balance_cents"] == 630000
        assert_rollforward_invariant(items[0])


class TestDeferredCascadeDepth:
    def test_lock_creates_asset_item_and_recomputes_year_deferred(
            self, api, tax_manager_headers):
        """PRD §3.2: "`movement_cents` is the absolute value of
        `difference_cents` multiplied by the parent year's
        `enacted_federal_rate_bp` and divided by 10000, rounded half up
        exactly once to integer cents, always a nonnegative magnitude"
        PRD §3.2: "Hop 2: the parent year's `deferred_expense_cents` — the sum
        of `LIABILITY` movements minus the sum of `ASSET` movements across the
        year's items, negative meaning a net benefit — and
        `net_deferred_asset_cents` — the sum of `ASSET` closing balances minus
        the sum of `LIABILITY` closing balances, gross before any valuation
        allowance — recompute."

        Design: Difficulty/transitive_cascade/difference_lock_cascade_depth3
        """
        ty, jur = setup_open_year_with_jurisdiction()
        va = create_draft_allowance(
            ty["id"], more_likely_than_not=True,
            projected_taxable_income_cents=1000000, reversing_dtl_cents=100000)
        assert va["allowance_amount_cents"] == 0, "empty DTA pool -> 0"
        diff = create_reviewed_difference(ty["id"], jur["id"])

        validate_success(api.lock_difference(diff["id"], tax_manager_headers),
                         200)

        items = list_deferred_items(params={"tax_year_id": ty["id"]})
        assert len(items) == 1
        item = items[0]
        assert item["item_kind"] == "ASSET"
        assert item["movement_cents"] == 630000
        assert item["opening_balance_cents"] == 0
        assert item["closing_balance_cents"] == 630000
        assert_rollforward_invariant(item)

        year = get_tax_year(ty["id"])
        assert year["deferred_expense_cents"] == -630000
        assert year["net_deferred_asset_cents"] == 630000

    def test_lock_recomputes_forecast_etr_and_draft_allowance(
            self, api, tax_manager_headers, auditor_headers):
        """PRD §3.2: "Hop 3a: `forecast_etr_bp` recomputes, since the forecast
        variant consumes `deferred_expense_cents`. Hop 3b: if the year has a
        valuation allowance assessment in `DRAFT` or `SUBMITTED`, its
        `allowance_amount_cents` recomputes against the updated deferred-asset
        pool (§3.3)."
        PRD §3.6: "The forecast variant — the in-year planning view, always
        maintained — sets forecast total tax to `current_provision_cents` plus
        `deferred_expense_cents` plus `utp_liability_cents` plus
        `valuation_allowance_cents`, then `forecast_etr_bp` is that total
        multiplied by 10000 and divided by `pretax_book_income_cents`, rounded
        half up."

        Design: Difficulty/transitive_cascade/difference_lock_cascade_depth3
        """
        ty, jur = setup_open_year_with_jurisdiction()
        va = create_draft_allowance(
            ty["id"], more_likely_than_not=True,
            projected_taxable_income_cents=1000000, reversing_dtl_cents=100000)
        diff = create_reviewed_difference(ty["id"], jur["id"])

        validate_success(api.lock_difference(diff["id"], tax_manager_headers),
                         200)

        year = get_tax_year(ty["id"])
        # (0 - 630,000 + 0 + 0) * 10000 / 100,000,000 = -63
        assert year["forecast_etr_bp"] == -63

        va_after = validate_success(
            api.get_valuation_allowance(va["id"], auditor_headers), 200)
        # max(0, 630,000 - min(630,000, 100,000 + round(1,000,000*2100/10000)))
        assert va_after["allowance_amount_cents"] == 320000
        assert va_after["status"] == "DRAFT"


class TestDeferredInputSetFiltering:
    def test_permanent_and_zero_differences_produce_no_items(
            self, api, tax_manager_headers):
        """PRD §3.2: "A `TEMPORARY` difference whose `difference_cents` is
        exactly zero produces no item at all, and `PERMANENT` differences
        never do."

        Design: Corner/calculations/permanent_and_zero_differences_produce_no_deferred_items
        """
        ty, jur = setup_open_year_with_jurisdiction()
        d_perm = create_reviewed_difference(
            ty["id"], jur["id"], book_amount_cents=2000000,
            tax_amount_cents=0, difference_type="PERMANENT",
            description="meals 50pct limitation")
        d_zero = create_reviewed_difference(
            ty["id"], jur["id"], book_amount_cents=1500000,
            tax_amount_cents=1500000, difference_type="TEMPORARY",
            description="timing-neutral accrual")
        validate_success(api.lock_difference(d_perm["id"],
                                             tax_manager_headers), 200)
        validate_success(api.lock_difference(d_zero["id"],
                                             tax_manager_headers), 200)

        items = list_deferred_items(params={"tax_year_id": ty["id"]})
        assert items == [], \
            "PERMANENT and zero TEMPORARY differences generate no rollforward line"
        year = get_tax_year(ty["id"])
        assert year["net_deferred_asset_cents"] == 0
        assert year["deferred_expense_cents"] == 0

    def test_negative_difference_produces_liability_item(
            self, api, tax_manager_headers):
        """PRD §3.2: "`item_kind` is `ASSET` when `difference_cents` is
        positive (a future deduction) and `LIABILITY` when negative"
        PRD §3.2: "`net_deferred_asset_cents` — the sum of `ASSET` closing
        balances minus the sum of `LIABILITY` closing balances, gross before
        any valuation allowance"

        Design: Corner/state_machines/negative_difference_produces_liability_item
        """
        ty, jur = setup_open_year_with_jurisdiction()
        diff = create_reviewed_difference(
            ty["id"], jur["id"], book_amount_cents=2000000,
            tax_amount_cents=4000000, difference_type="TEMPORARY",
            description="prepaid expense amortization")
        validate_success(api.lock_difference(diff["id"],
                                             tax_manager_headers), 200)

        items = list_deferred_items(params={"tax_year_id": ty["id"]})
        assert len(items) == 1
        # difference_cents = 2,000,000 - 4,000,000 = -2,000,000 -> LIABILITY
        # movement = round_half_up(2,000,000 * 2100 / 10000) = 420,000
        assert items[0]["item_kind"] == "LIABILITY"
        assert items[0]["movement_cents"] == 420000
        assert items[0]["closing_balance_cents"] == 420000
        assert_rollforward_invariant(items[0])

        year = get_tax_year(ty["id"])
        assert year["net_deferred_asset_cents"] == -420000
        # LIABILITY movements minus ASSET movements: a DTL build is expense-positive
        assert year["deferred_expense_cents"] == 420000

    def test_rejected_difference_excluded_from_calculations(
            self, api, tax_manager_headers):
        """PRD §3.2: "Rejecting it moves it to `REJECTED`, terminal: rejected
        differences never produce deferred items and never enter any
        calculation input set."

        Design: Corner/state_machines/difference_reject_excludes_from_calculations
        """
        ty, jur = setup_open_year_with_jurisdiction()
        diff = create_reviewed_difference(ty["id"], jur["id"])
        rejected = validate_success(
            api.reject_difference(diff["id"], tax_manager_headers), 200)
        assert rejected["status"] == "REJECTED"

        items = list_deferred_items(params={"tax_year_id": ty["id"]})
        assert items == []
        year = get_tax_year(ty["id"])
        assert year["net_deferred_asset_cents"] == 0

    def test_locked_difference_is_terminal(self, api, tax_manager_headers):
        """PRD §3.2: "A reviewed difference has three exits." (rework, reject,
        lock; `LOCKED` and `REJECTED` are terminal)
        PRD §2.6: "every other illegal transition surfaces
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/locked_difference_terminal_lockdown_rejected
        """
        ty, jur = setup_open_year_with_jurisdiction()
        diff = create_locked_difference(
            ty["id"], jur["id"], book_amount_cents=2000000,
            tax_amount_cents=0, difference_type="PERMANENT",
            description="meals 50pct limitation")
        assert diff["status"] == "LOCKED"
        version_at_lock = diff["version"]

        res = api.reject_difference(diff["id"], tax_manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION,
                       expected_status=409)

        after = validate_success(
            api.get_book_tax_difference(diff["id"], tax_manager_headers), 200)
        assert after["status"] == "LOCKED"
        assert after["version"] == version_at_lock, \
            "the rejected transition must not mutate the difference"


class TestPostLockPosture:
    def test_difference_create_after_lock_returns_tax_year_not_open(
            self, api, tax_accountant_headers):
        """PRD §2.6: "**Tax-year posture** — creating differences, filings, or
        valuation allowances, and the difference and valuation-allowance
        lifecycle actions, require the year to be `OPEN`
        (`ERR_TAX_YEAR_NOT_OPEN`)"

        Design: Corner/validations/difference_create_after_lock_returns_tax_year_not_open
        """
        scenario = setup_locked_year_with_filing()
        ty = scenario["tax_year"]
        jur = scenario["jurisdiction"]
        assert ty["status"] == "PROVISION_LOCKED"

        payload = {
            "tax_year_id": ty["id"],
            "jurisdiction_id": jur["id"],
            "description": "late-found difference",
            "book_amount_cents": 100000,
            "tax_amount_cents": 0,
            "difference_type": "PERMANENT",
        }
        res = api.create_book_tax_difference(payload, tax_accountant_headers)
        validate_error(res, ApiErrorId.ERR_TAX_YEAR_NOT_OPEN,
                       expected_status=409)


class TestPerLockReconciliation:
    def test_net_deferred_asset_reconciles_after_each_lock(
            self, api, tax_manager_headers):
        """PRD §2.10: "Derived fields on `TaxYear` are recomputed eagerly,
        atomically within the triggering request."
        PRD §3.2: "Hop 2: the parent year's `deferred_expense_cents` — the sum
        of `LIABILITY` movements minus the sum of `ASSET` movements across the
        year's items, negative meaning a net benefit — and
        `net_deferred_asset_cents` — the sum of `ASSET` closing balances minus
        the sum of `LIABILITY` closing balances, gross before any valuation
        allowance — recompute."

        Design: Corner/cross_cutting_layers/net_deferred_asset_reconciles_after_each_lock
        """
        ty, jur = setup_open_year_with_jurisdiction()
        d1 = create_reviewed_difference(ty["id"], jur["id"])  # +3,000,000
        d2 = create_reviewed_difference(
            ty["id"], jur["id"], book_amount_cents=3000000,
            tax_amount_cents=2000000, description="deferred revenue")  # +1M

        validate_success(api.lock_difference(d1["id"], tax_manager_headers),
                         200)
        year1 = get_tax_year(ty["id"])
        assert year1["net_deferred_asset_cents"] == 630000
        assert year1["deferred_expense_cents"] == -630000

        validate_success(api.lock_difference(d2["id"], tax_manager_headers),
                         200)
        year2 = get_tax_year(ty["id"])
        # second item movement = round(1,000,000 * 2100 / 10000) = 210,000
        assert year2["net_deferred_asset_cents"] == 840000
        assert year2["deferred_expense_cents"] == -840000

        for item in list_deferred_items(params={"tax_year_id": ty["id"]}):
            assert_rollforward_invariant(item)


class TestCurrentTaxStack:
    def test_state_deduction_order_pins_provision(
            self, api, tax_manager_headers):
        """PRD §3.6: "Second, for each jurisdiction of `level` `STATE` or
        `FOREIGN` that has at least one filing in the year, the state
        component is the sum of `pretax_book_income_cents` and `perm_total`,
        multiplied by that jurisdiction's `apportionment_pct_bp` and by its
        `statutory_rate_bp`, divided by 100 million (10^8), rounded half up
        exactly once after the full product — no intermediate rounding. Third,
        the federal base is `pretax_book_income_cents` plus `perm_total` minus
        the sum of all state components. Fourth, when a `FEDERAL` jurisdiction
        has at least one filing in the year, the federal component is the
        federal base multiplied by `enacted_federal_rate_bp` and divided by
        10000, rounded half up once after the deduction; otherwise the federal
        component is 0. Fifth, `current_provision_cents` is the sum of all
        state components plus the federal component"

        Design: Corner/calculations/current_tax_stack_state_deduction_order
        """
        ty = create_fy2026_tax_year()
        jur_fed = create_us_fed_jurisdiction()
        jur_ca = create_us_ca_jurisdiction()
        diff = create_reviewed_difference(
            ty["id"], jur_fed["id"], book_amount_cents=2000000,
            tax_amount_cents=0, difference_type="PERMANENT",
            description="meals 50pct limitation")
        create_filing_record(ty["id"], jur_fed["id"])
        create_filing_record(ty["id"], jur_ca["id"])

        validate_success(api.lock_difference(diff["id"],
                                             tax_manager_headers), 200)

        year = get_tax_year(ty["id"])
        # CA: round((100,000,000 + 2,000,000) * 2500 * 884 / 1e8) = 2,254,200
        # FED base: 102,000,000 - 2,254,200 = 99,745,800
        # FED: round(99,745,800 * 2100 / 10000) = 20,946,618
        assert year["current_provision_cents"] == 23200818
