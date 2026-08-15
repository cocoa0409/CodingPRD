"""Computed reads: job costing and dual credit-exposure variants (PRD §2.9, §3.3)."""
from test_helpers import (
    TEST_USERS,
    assert_credit_exposure,
    assert_job_costing,
    create_draft_order,
    create_picked_up_order,
    create_submitted_order,
    make_account,
    make_branch,
    make_product,
    make_stock,
    setup_branch_product_account,
    validate_paginated,
    validate_success,
)


class TestJobCostingVariants:
    def _setup_job7(self):
        """JOB-7 order: P1 x10 (ALLOCATED) + P2 x5 (BACKORDERED, no stock)."""
        branch = make_branch()
        p1 = make_product(sku="P1")
        p2 = make_product(sku="P2", description="Ball valve", category="VALVE",
                          list_price_cents=4000, cost_cents=2000, cubes_per_unit=5)
        account = make_account()
        make_stock(branch["id"], p1["id"], 10)
        make_stock(branch["id"], p2["id"], 0)
        create_submitted_order(
            account["id"], branch["id"],
            [(p1["id"], 10), (p2["id"], 5)],
            job_name="JOB-7", will_call=True,
        )
        return account

    def test_job_cost_provisional_counts_all_open_commitments(self, api, sales_headers):
        """PRD §3.3: "The job-costing read, parameterized by `job_name`, scopes
        itself to the account's orders carrying that `job_name` whose
        `fulfillment_status` is not `CANCELLED`, and reports both cost variants:
        `provisional_cost_cents`, the sum of `line_total_cents` over lines in
        `OPEN`, `ALLOCATED`, `BACKORDERED`, or `FILLED` status, which includes
        unfulfilled commitment value and ignores pending returns".

        GOLD lines: P1 10x9000 = 90000 (ALLOCATED) plus P2 5x3600 = 18000
        (BACKORDERED) — provisional is 108000 over 1 order and 2 lines.

        Design: Difficulty/dual_variant_calc/job_cost_provisional_vs_final
        """
        account = self._setup_job7()
        report = validate_success(
            api.get_job_costing(account["id"], sales_headers, params={"job_name": "JOB-7"})
        )
        assert_job_costing(report)
        assert report["provisional_cost_cents"] == 108000, (
            f"provisional must count ALLOCATED + BACKORDERED lines, got {report['provisional_cost_cents']}"
        )
        assert report["order_count"] == 1 and report["line_count"] == 2

    def test_job_cost_final_counts_only_filled_lines(self, api, sales_headers):
        """PRD §3.3: "and `final_cost_cents`, the sum over `FILLED` lines only, of each line's `line_total_cents` minus its returned value (the `qty_returned` times the line's `unit_price_cents`, times `cut_length_ft` as well for cut items), netting out credited returns. The read also reports `order_count` and `line_count` for the in-scope set; identical inputs can produce different provisional and final totals, which is the point of reporting both."

        Nothing has been staged, so no line is FILLED and final is 0 while
        provisional on the same rows is 108000.

        Design: Difficulty/dual_variant_calc/job_cost_provisional_vs_final
        """
        account = self._setup_job7()
        report = validate_success(
            api.get_job_costing(account["id"], sales_headers, params={"job_name": "JOB-7"})
        )
        assert report["final_cost_cents"] == 0, (
            f"no FILLED lines yet — final must be 0, got {report['final_cost_cents']}"
        )
        assert report["provisional_cost_cents"] != report["final_cost_cents"]

    def test_job_cost_excludes_cancelled_orders(self, api, sales_headers, counterrep_headers):
        """PRD §3.3: "The job-costing read, parameterized by `job_name`, scopes
        itself to the account's orders carrying that `job_name` whose
        `fulfillment_status` is not `CANCELLED`".

        JOB-X holds a submitted order (P1 x2 = 18000) and a cancelled DRAFT
        order (P1 x3); only the submitted order counts.

        Design: Corner/calculations/job_cost_excludes_cancelled_orders
        """
        branch, product, account = setup_branch_product_account(stock=10)
        create_submitted_order(account["id"], branch["id"], [(product["id"], 2)], job_name="JOB-X")
        cancelled, _ = create_draft_order(account["id"], branch["id"], [(product["id"], 3)], job_name="JOB-X")
        validate_success(api.cancel_order(cancelled["id"], counterrep_headers))

        report = validate_success(
            api.get_job_costing(account["id"], sales_headers, params={"job_name": "JOB-X"})
        )
        assert_job_costing(report)
        assert report["provisional_cost_cents"] == 18000, (
            f"cancelled order's 27000 must be excluded, got {report['provisional_cost_cents']}"
        )
        assert report["order_count"] == 1 and report["line_count"] == 1


class TestCreditExposureVariants:
    def _setup_two_orders(self):
        """SILVER account: order A picked up (INVOICED 40500), order B submitted (UNINVOICED 40500)."""
        branch = make_branch()
        p1 = make_product(sku="P1")
        p2 = make_product(sku="P2", description="Ball valve", category="VALVE",
                          list_price_cents=4000, cost_cents=2000, cubes_per_unit=5)
        account = make_account(company_name="Silver Co", pricing_tier="SILVER",
                               credit_limit_cents=1000000)
        make_stock(branch["id"], p1["id"], 10)
        make_stock(branch["id"], p2["id"], 10)
        create_picked_up_order(account["id"], branch["id"], [(p1["id"], 4)], job_name="A")
        create_submitted_order(account["id"], branch["id"], [(p2["id"], 10)], job_name="B", will_call=True)
        return account

    def test_statement_balance_counts_only_invoiced(self, api, sales_headers):
        """PRD §2.9: "The statement view, exposed as `outstanding_balance_cents`,
        is the chronological ledger balance: the sum of `total_cents` over
        orders whose `payment_status` is `INVOICED` or `PAID`, minus the sum of
        all payment `amount_cents` posted to the account, minus the sum of
        `credit_cents` over return requests that have reached `CREDITED`."

        SILVER lines: A is 4x9500 = 38000 + 2500 freight = 40500 INVOICED; B is
        10x3800 = 38000 + 2500 = 40500 still UNINVOICED, so the statement
        balance reads 40500 and the account stays ACTIVE.

        Design: Difficulty/dual_variant_calc/credit_exposure_statement_vs_forward
        """
        account = self._setup_two_orders()
        exposure = validate_success(api.get_credit_exposure(account["id"], sales_headers))
        assert_credit_exposure(exposure)
        assert exposure["statement_balance_cents"] == 40500, (
            f"only the INVOICED order counts chronologically, got {exposure['statement_balance_cents']}"
        )
        assert exposure["status"] == "ACTIVE"

    def test_forward_exposure_adds_committed_uninvoiced(self, api, sales_headers):
        """PRD §2.9: "The forward view, exposed as `forward_exposure_cents`,
        starts from that same statement balance and adds the `total_cents` of
        every order that is committed but not yet invoiced — orders whose
        `payment_status` is `UNINVOICED` and whose `fulfillment_status` is
        neither `DRAFT` nor `CANCELLED`. The account's headroom is
        `available_credit_cents`, defined as `credit_limit_cents` minus
        `forward_exposure_cents`; it may legitimately go negative."

        Forward exposure is 40500 + 40500 = 81000 and available credit is
        1000000 - 81000 = 919000 on the same account state.

        Design: Difficulty/dual_variant_calc/credit_exposure_statement_vs_forward
        """
        account = self._setup_two_orders()
        exposure = validate_success(api.get_credit_exposure(account["id"], sales_headers))
        assert exposure["forward_exposure_cents"] == 81000, (
            f"forward view must add the committed-uninvoiced 40500, got {exposure['forward_exposure_cents']}"
        )
        assert exposure["available_credit_cents"] == 919000
        assert exposure["statement_balance_cents"] != exposure["forward_exposure_cents"]


class TestAccountListFilter:
    def test_account_list_filter_by_status(self, api, sales_headers):
        """PRD §2.3: "Several list endpoints accept additional filter parameters, all of which combine with pagination: the product list accepts `category`, `manufacturer_name`, and `substitute_group`; the account list accepts `status`; the quote list accepts `account_id`, `branch_id`, `status`, and `supersedes_quote_id`; the selection-sheet list accepts `account_id`, `branch_id`, and `status`; the manufacturer-program list accepts `manufacturer_name` and `status`; order lists scoped to an account or a branch accept `fulfillment_status`; the branch inventory list accepts `product_id`; and the branch delivery-slot list accepts `truck_label`."
        PRD §3.3: "`ADJUST_LIMIT` — defined only for an account currently
        `ACTIVE` — carries `new_credit_limit_cents` (at least 0), rewrites
        `credit_limit_cents`, recomputes the exposure views, and immediately
        re-evaluates the automatic hold, so tightening the limit below the
        current balance engages `CREDIT_HOLD` on the spot."

        Filtering by CREDIT_HOLD returns exactly the tightened account; the
        unfiltered list returns both accounts.

        Design: Corner/endpoints/account_list_filter_by_status
        """
        branch, product, acct_h = setup_branch_product_account(
            account_overrides={"company_name": "H Co", "credit_limit_cents": 200000},
            stock=20,
        )
        acct_a = make_account(company_name="A Co", credit_limit_cents=100000)  # noqa: F841 — stays ACTIVE
        create_picked_up_order(acct_h["id"], branch["id"], [(product["id"], 12)])
        tightened = validate_success(api.credit_review(
            acct_h["id"], {"action": "ADJUST_LIMIT", "new_credit_limit_cents": 100000},
            TEST_USERS["manager_headers"],
        ))
        assert tightened["status"] == "CREDIT_HOLD"

        filtered, meta_f = validate_paginated(
            api.list_accounts(sales_headers, params={"status": "CREDIT_HOLD"})
        )
        assert meta_f["total_count"] == 1
        assert [row["id"] for row in filtered] == [acct_h["id"]], (
            f"the filter must exclude ACTIVE account {acct_a['id']}"
        )

        _, meta_all = validate_paginated(api.list_accounts(sales_headers))
        assert meta_all["total_count"] == 2
