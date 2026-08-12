"""Accounting reports: CASH vs ACCRUAL divergence, returned-row exclusion,
contiguity (gap/overlap), overdue submit, RBAC on accept."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, make_admin_headers, make_financial_officer_headers,
    make_case_manager_headers, make_auditor_headers,
    create_client, create_active_client, create_account, create_active_bond,
    create_and_post_deposit, create_budget_plan_for_client,
    create_approved_budget_plan, create_disbursement,
    create_approved_disbursement, create_released_disbursement,
    create_submitted_report, set_clock,
    create_accounting_report_payload, create_deposit_payload,
)
from test_helpers.api_client import api_client as api

ADMIN = make_admin_headers()
FO = make_financial_officer_headers()
CM = make_case_manager_headers()
AUD = make_auditor_headers()


class TestCashVsAccrualDivergence:
    def test_report_cash_vs_accrual_basis_divergence(self, api):
        """PRD §3.8: "Under the `CASH` basis — the SSA-6233 filing view —
        `receipts_total_cents` sums the amounts of the client's deposits in
        `POSTED` status whose `posted_at` date falls within the closed period,
        and `disbursements_total_cents` sums the amounts of the client's
        disbursements in `RELEASED` status whose `released_at` date falls
        within the period. Under the `ACCRUAL` basis — the court annual view —
        receipts additionally include deposits still in `RECEIVED` status whose
        `received_date` falls within the period, and disbursements additionally
        include disbursements still in `APPROVED` status whose
        `scheduled_release_date` falls within the period."
        PRD §3.8: "The statutory `due_date` is derived immediately: thirty days
        after `period_end_date`."

        Design: Difficulty/dual_variant_calc/report_cash_vs_accrual_basis_divergence
        """
        set_clock("2026-05-05T00:00:00Z")
        client, ent = create_active_client()
        acct = create_account(client["id"])
        create_active_bond()
        # D1 posted 100000
        create_and_post_deposit(acct["id"], 100000, source="SSA_BENEFIT",
                                received_date="2026-05-05", entitlement_id=ent["id"])
        # Budget approved for 2026-05
        plan = create_approved_budget_plan(client["id"], period_month="2026-05",
                                           source_benefit_cents=200000)
        # W1 released 30000 on 2026-05-12
        w1 = create_approved_disbursement(client["id"], acct["id"], plan["id"],
                                          amount_cents=30000, payee_name="Landlord LLC",
                                          scheduled_release_date="2026-05-12")
        set_clock("2026-05-12T00:00:00Z")
        get_success_data(api.release_disbursement(w1["id"], FO))
        # D2 received-but-not-posted 50000 on 2026-05-20
        get_success_data(api.create_deposit(
            create_deposit_payload(account_id=acct["id"], source="PENSION",
                                   amount_cents=50000, received_date="2026-05-20"), FO
        ))
        # W2 approved-not-released 12000 scheduled 2026-05-25
        create_approved_disbursement(client["id"], acct["id"], plan["id"],
                                     amount_cents=12000, payee_name="Pharmacy Inc",
                                     scheduled_release_date="2026-05-25")
        set_clock("2026-06-10T00:00:00Z")
        r_cash = get_success_data(api.create_accounting_report(
            create_accounting_report_payload(
                client_id=client["id"], report_type="SSA_6233",
                period_start_date="2026-05-01", period_end_date="2026-05-31",
                basis="CASH"), CM))
        r_acc = get_success_data(api.create_accounting_report(
            create_accounting_report_payload(
                client_id=client["id"], report_type="COURT_ANNUAL",
                period_start_date="2026-05-01", period_end_date="2026-05-31",
                basis="ACCRUAL"), CM))
        cash = get_success_data(api.submit_accounting_report(r_cash["id"], FO))
        acc = get_success_data(api.submit_accounting_report(r_acc["id"], FO))
        assert cash["receipts_total_cents"] == 100000
        assert cash["disbursements_total_cents"] == 30000
        assert cash["opening_balance_cents"] == 0
        assert cash["ending_balance_cents"] == 70000
        assert acc["receipts_total_cents"] == 150000
        assert acc["disbursements_total_cents"] == 42000
        assert acc["ending_balance_cents"] == 108000
        assert cash["due_date"] == "2026-06-30"

    def test_report_cash_opening_balance_replays_prior_ledger(self, api):
        """PRD §3.8: "The `opening_balance_cents`, identical under both bases,
        replays the ledger entries of every account of the client with
        `created_at` before `period_start_date` in chronological order and sums
        their signed amounts."

        Design: Difficulty/dual_variant_calc/report_cash_vs_accrual_basis_divergence
        """
        set_clock("2026-05-05T00:00:00Z")
        client, ent = create_active_client()
        acct = create_account(client["id"])
        create_active_bond()
        # Prior-period deposit (posted in May 2026, before the June report period)
        create_and_post_deposit(acct["id"], 40000, received_date="2026-05-05")
        set_clock("2026-06-10T00:00:00Z")
        r = get_success_data(api.create_accounting_report(
            create_accounting_report_payload(
                client_id=client["id"], report_type="SSA_6233",
                period_start_date="2026-06-01", period_end_date="2026-06-30",
                basis="CASH"), CM))
        submitted = get_success_data(api.submit_accounting_report(r["id"], FO))
        assert submitted["opening_balance_cents"] == 40000
        assert submitted["receipts_total_cents"] == 0
        assert submitted["disbursements_total_cents"] == 0
        assert submitted["ending_balance_cents"] == 40000


class TestReturnedRowsExcluded:
    def test_report_excludes_returned_rows(self, api):
        """PRD §3.8: "Returned flows never appear: `RETURNED` deposits and
        `RETURNED` disbursements are excluded from both bases, since they net
        to zero through the ledger while the report shows gross flows."

        Design: Corner/calculations/report_excludes_returned_rows
        """
        set_clock("2026-06-10T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"])
        create_active_bond()
        d1 = create_and_post_deposit(acct["id"], 40000, received_date="2026-06-05")
        plan = create_approved_budget_plan(client["id"], period_month="2026-06",
                                           source_benefit_cents=100000)
        w = create_released_disbursement(client["id"], acct["id"], plan["id"],
                                         amount_cents=20000, payee_name="Filter Payee")
        get_success_data(api.return_disbursement(w["id"], FO))
        get_success_data(api.return_deposit(d1["id"], FO))
        create_and_post_deposit(acct["id"], 10000, received_date="2026-06-08")
        set_clock("2026-06-25T00:00:00Z")
        r = get_success_data(api.create_accounting_report(
            create_accounting_report_payload(
                client_id=client["id"], report_type="SSA_6233",
                period_start_date="2026-06-01", period_end_date="2026-06-30",
                basis="CASH"), CM))
        submitted = get_success_data(api.submit_accounting_report(r["id"], FO))
        assert submitted["receipts_total_cents"] == 10000
        assert submitted["disbursements_total_cents"] == 0
        assert submitted["opening_balance_cents"] == 0
        assert submitted["ending_balance_cents"] == 10000


class TestContiguity:
    def test_report_period_closed_interval_contiguity(self, api):
        """PRD §3.8: "Reports for the same client and report type form a
        contiguous chain over those in `SUBMITTED` or `ACCEPTED` status: a new
        report's `period_start_date` must be exactly the day after the previous
        report's `period_end_date`. A period that collides with an existing
        submitted or accepted report is rejected with
        `ERR_REPORT_PERIOD_OVERLAP`; a period that starts later than the
        required next day, leaving a gap, is rejected with
        `ERR_REPORT_PERIOD_GAP`."

        Design: Difficulty/resource_temporal_overlap/report_period_closed_interval_contiguity
        """
        set_clock("2026-06-15T00:00:00Z")
        client, _ = create_active_client(effective_start_date="2025-01-01")
        r1 = get_success_data(api.create_accounting_report(
            create_accounting_report_payload(
                client_id=client["id"], report_type="SSA_6233",
                period_start_date="2025-06-01", period_end_date="2026-05-31",
                basis="CASH"), CM))
        get_success_data(api.submit_accounting_report(r1["id"], FO))
        # Adjacent (start == prior end + 1 day): created.
        r2 = get_success_data(api.create_accounting_report(
            create_accounting_report_payload(
                client_id=client["id"], report_type="SSA_6233",
                period_start_date="2026-06-01", period_end_date="2026-06-30",
                basis="CASH"), CM))
        assert r2["status"] == "DRAFTING"
        # Gap: start 2026-07-02 skips required 2026-06-01 (R2 is DRAFTING and
        # does not count toward the chain, so the required start is still
        # 2026-06-01).
        resp_gap = api.create_accounting_report(
            create_accounting_report_payload(
                client_id=client["id"], report_type="SSA_6233",
                period_start_date="2026-07-02", period_end_date="2026-07-31",
                basis="CASH"), CM)
        validate_error(resp_gap, ApiErrorId.ERR_REPORT_PERIOD_GAP)
        # Overlap: start 2026-05-15 intersects R1's closed interval.
        resp_ovl = api.create_accounting_report(
            create_accounting_report_payload(
                client_id=client["id"], report_type="SSA_6233",
                period_start_date="2026-05-15", period_end_date="2026-06-15",
                basis="CASH"), CM)
        validate_error(resp_ovl, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)

    def test_report_contiguity_first_report_no_prior_required(self, api):
        """PRD §3.8: "Reports for the same client and report type form a
        contiguous chain over those in `SUBMITTED` or `ACCEPTED` status: a new
        report's `period_start_date` must be exactly the day after the previous
        report's `period_end_date`."

        Design: Difficulty/resource_temporal_overlap/report_period_closed_interval_contiguity
        """
        set_clock("2026-06-15T00:00:00Z")
        client, _ = create_active_client(effective_start_date="2025-01-01")
        # First report for the (client, report_type) pair: no prior link, any
        # period allowed.
        r = get_success_data(api.create_accounting_report(
            create_accounting_report_payload(
                client_id=client["id"], report_type="SSA_6233",
                period_start_date="2025-06-01", period_end_date="2026-05-31",
                basis="CASH"), CM))
        assert r["status"] == "DRAFTING"
        assert r["due_date"] == "2026-06-30"

    def test_report_submit_overdue_rejected(self, api):
        """PRD §3.8: "Submission is a `FinancialOfficer` action moving the
        report `DRAFTING` → `SUBMITTED`, and it carries two gates: the client
        must be `ACTIVE` or `SUSPENDED` (otherwise `ERR_CLIENT_NOT_ACTIVE`),
        and the current logical clock date must be on or before the `due_date`
        (otherwise `ERR_REPORT_OVERDUE`)."
        PRD §3.8: "The statutory `due_date` is derived immediately: thirty days
        after `period_end_date`."

        Design: Corner/validations/report_submit_overdue_rejected
        """
        set_clock("2026-06-15T00:00:00Z")
        client, _ = create_active_client()
        r = get_success_data(api.create_accounting_report(
            create_accounting_report_payload(
                client_id=client["id"], report_type="SSA_6233",
                period_start_date="2026-04-01", period_end_date="2026-04-30",
                basis="CASH"), CM))
        assert r["due_date"] == "2026-05-30"
        resp = api.submit_accounting_report(r["id"], FO)
        validate_error(resp, ApiErrorId.ERR_REPORT_OVERDUE)
