"""Listing/pagination envelopes, reverse-reachability, and RBAC enforcement."""
from test_helpers import (
    get_success_data, validate_error, validate_paginated, ApiErrorId,
    create_client, create_active_ledger_account,
    create_approved_review_close, create_handoff_in_books_review,
    build_user_headers,
    api_client, TEST_USERS,
)

CFO = TEST_USERS["cfo_headers"]
BK = TEST_USERS["bookkeeper_headers"]


class TestPagination:
    def test_list_clients_envelope_and_total(self, api):
        """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` inside the `meta` object of the envelope."

        Design: Corner/endpoints/list_clients_pagination_envelope
        """
        create_client(retainer_tier="GROWTH", legal_name="L1")
        create_client(retainer_tier="GROWTH", legal_name="L2")
        resp = api.list_clients(CFO, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert meta["has_more"] is True

    def test_list_clients_limit_above_max_rejected(self, api):
        """PRD §2.3: "A `limit` outside the inclusive range of 1 through 100, or a
        negative `offset`, is rejected with `ERR_VALIDATION_LIMIT`."

        Design: Corner/endpoints/list_clients_limit_out_of_range_400
        """
        resp = api.list_clients(CFO, params={"limit": 101})
        validate_error(resp, ApiErrorId.ERR_VALIDATION_LIMIT.value)


class TestReverseReachability:
    def test_ledger_account_children_listing(self, api):
        """PRD §2.8: "List endpoints that hang off a parent — a client's ledger
        accounts, a close's tasks, a run's allocations (each `PayrollAllocation`
        referencing its run by `payroll_run_id`), a forecast's lines (each
        `ForecastLine` referencing its forecast by `forecast_id`), and the like —
        return only the children that reference the named parent, providing reverse
        reachability from a parent down to the rows that point back to it."

        Design: Corner/endpoints/ledger_children_reverse_reachability
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        parent = create_active_ledger_account(
            cid, account_code="1000", account_type="ASSET", name="Assets")
        create_active_ledger_account(
            cid, account_code="1100", account_type="ASSET", name="Cash",
            parent_account_id=parent["id"])
        resp = api.list_ledger_account_children(parent["id"], BK)
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1

    def test_payroll_runs_by_close_listing(self, api):
        """PRD §2.8: "List endpoints that hang off a parent — a client's ledger
        accounts, a close's tasks, a run's allocations (each `PayrollAllocation`
        referencing its run by `payroll_run_id`), a forecast's lines (each
        `ForecastLine` referencing its forecast by `forecast_id`), and the like —
        return only the children that reference the named parent, providing reverse
        reachability from a parent down to the rows that point back to it."

        Design: Corner/endpoints/payroll_runs_by_close_reverse_reachability
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        close = get_success_data(api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 1, "txn_count": 10}, BK))
        get_success_data(api.create_payroll_run(cid, {
            "monthly_close_id": close["id"], "pay_date": "2026-01-31T00:00:00Z",
            "pay_period_start": "2026-01-01T00:00:00Z",
            "pay_period_end": "2026-02-01T00:00:00Z",
            "total_employer_cost_cents": 100000}, BK))
        resp = api.list_close_payroll_runs(close["id"], CFO)
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1


class TestRbac:
    def test_missing_role_header_unauthenticated(self, api):
        """PRD §2.1: "Every request must be authenticated with two mandatory HTTP
        headers: `X-User-ID`, identifying the acting user, and `X-User-Role`,
        declaring the capacity in which they act. If either header is absent, or if
        `X-User-Role` is not one of the recognized roles, the request is rejected
        with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_headers_unauthenticated_401
        """
        resp = api.create_client(
            {"legal_name": "Anon Co", "state_code": "CA", "retainer_tier": "GROWTH"},
            {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_bookkeeper_cannot_finalize_close(self, api):
        """PRD §2.1: "When a recognized role attempts an operation the RBAC matrix
        does not grant it, the request is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §3.4: "Finalizing the close is a `CFO` action permitted only when
        `status` is `READY_FOR_REVIEW` and `review_status` is `APPROVED`"

        Design: Corner/rbac/bookkeeper_cannot_finalize_close_forbidden_403
        """
        _, close_id, _ = create_approved_review_close(period_month=2, txn_count=20)
        resp = api.finalize_close(close_id, BK)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_cfo_cannot_books_signoff(self, api):
        """PRD §2.1: "When a recognized role attempts an operation the RBAC matrix
        does not grant it, the request is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §3.9: "A `Bookkeeper` signs off the books branch"

        Design: Corner/rbac/cfo_cannot_books_signoff_forbidden_403
        """
        cid, th_id = create_handoff_in_books_review(tax_year=2025)
        resp = api.books_signoff(th_id, CFO)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
