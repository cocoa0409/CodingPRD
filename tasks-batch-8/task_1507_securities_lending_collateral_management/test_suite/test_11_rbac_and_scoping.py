"""RBAC denials, segregation of duties, and entity-backed scoping."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_borrower,
    create_limit_override_payload,
    create_owner,
    create_position,
    create_regulatory_report_payload,
    create_security,
    make_borrower_rep_headers,
    make_desk_admin_headers,
    make_desk_trader_headers,
    make_ops_settler_headers,
    make_owner_rep_headers,
    run_month_end_close,
    setup_booked_loan,
    setup_desk,
    validate_error,
    validate_success,
    create_and_book_loan,
)

TRADER = TEST_USERS["desk_trader_headers"]
RISK = TEST_USERS["risk_officer_headers"]
OPS = TEST_USERS["ops_settler_headers"]
ADMIN = TEST_USERS["desk_admin_headers"]


class TestRoleDenied:
    def test_borrower_rep_cannot_create_loan(self, api):
        """PRD §2.1: "If the role is valid but not permitted on the target
        endpoint, the request is rejected with `ERR_FORBIDDEN`."
        PRD §4: `POST /api/loans` — "Open a direct loan proposal (no borrow
        request)" is authorized for `DeskTrader` only.

        Design: Corner/rbac/borrower_rep_cannot_create_loan
        """
        security, owner, borrower, position = setup_desk(
            security_symbol="RB1", quantity_total=10000)
        resp = api.create_loan(
            {"owner_id": owner["id"], "borrower_id": borrower["id"],
             "security_id": security["id"], "position_id": position["id"],
             "quantity": 100, "collateral_type": "CASH", "rate_bps": 0},
            make_borrower_rep_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_desk_trader_cannot_approve_override(self, api):
        """PRD §3.8: "Only a `RiskOfficer` decides."
        PRD §2.1: "If the role is valid but not permitted on the target
        endpoint, the request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/desk_trader_cannot_approve_own_or_any_override
        """
        borrower = create_borrower(display_name="Borrower Rb2")
        override = validate_success(api.create_limit_override(
            borrower["id"],
            create_limit_override_payload(new_limit_cents=200_000_000),
            make_desk_trader_headers("trader-1")), expected_status=201)
        resp = api.approve_limit_override(
            override["id"], make_desk_trader_headers("trader-2"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert validate_success(
            api.get_limit_override(override["id"],
                                   RISK))["status"] == "REQUESTED"

    def test_ops_settler_cannot_file_report(self, api):
        """PRD §3.9: "Filing is the `DeskAdmin`'s act"
        PRD §2.1: "`OpsSettler` — operations and settlement: runs the daily
        mark-to-market and the month-end close, marks reinvestment NAVs,
        drafts and finalizes regulatory reports (never files them)."
        PRD §2.1: "If the role is valid but not permitted on the target
        endpoint, the request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/ops_settler_cannot_file_report
        """
        run_month_end_close("2026-08")
        report = validate_success(api.create_regulatory_report(
            create_regulatory_report_payload(
                period="2026-08", report_type="COLLATERAL_SUMMARY"), OPS),
            expected_status=201)
        validate_success(api.finalize_regulatory_report(
            report["id"], make_ops_settler_headers("ops-1")))
        resp = api.file_regulatory_report(
            report["id"], make_ops_settler_headers("ops-2"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestSegregationOfDuties:
    def test_report_file_by_finalizing_user_rejected_sod(self, api):
        """PRD §3.9: "Filing is the `DeskAdmin`'s act and carries the desk's
        second segregation-of-duties rule: the filer's `X-User-ID` must
        differ from the `finalized_by_user_id`, or the filing is rejected
        with `ERR_SOD_VIOLATION`."

        Design: Corner/rbac/report_file_by_finalizing_user_rejected_sod
        """
        run_month_end_close("2026-08")
        report = validate_success(api.create_regulatory_report(
            create_regulatory_report_payload(
                period="2026-08", report_type="MONTHLY_LOAN_ACTIVITY"), OPS),
            expected_status=201)
        validate_success(api.finalize_regulatory_report(
            report["id"], make_ops_settler_headers("ops-1")))
        resp = api.file_regulatory_report(
            report["id"], make_desk_admin_headers("ops-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        assert validate_success(
            api.get_regulatory_report(report["id"], ADMIN),
            )["status"] == "FINALIZED"


class TestOwnershipScoping:
    def _two_borrower_setup(self, api):
        security, owner, _, position = setup_desk(security_symbol="RB3",
                                                  quantity_total=100000)
        b1 = create_borrower(display_name="Borrower Rb3a")
        b2 = create_borrower(display_name="Borrower Rb3b")
        l1 = create_and_book_loan(owner, b1, security, position,
                                  quantity=1000)
        l2 = create_and_book_loan(owner, b2, security, position,
                                  quantity=2000)
        return b1, b2, l1, l2

    def test_borrower_scoped_reads_hide_other_borrowers(self, api):
        """PRD §2.1: "Entity-backed scoping extends to list reads. When a
        `BorrowerRep` or `OwnerRep` queries a list endpoint that supports a
        filter on their backing foreign key (for example, a `BorrowerRep`
        listing loans with the `borrower_id` filter, or an `OwnerRep` listing
        positions with the `owner_id` filter), they must pass their own `id`
        as that filter value; passing another party's `id` is rejected with
        `ERR_FORBIDDEN`. If the filter is omitted entirely, the result set is
        automatically scoped to the caller's own `id`."

        Design: Corner/rbac/borrower_scoped_reads_hide_other_borrowers
        """
        b1, b2, l1, l2 = self._two_borrower_setup(api)
        headers = make_borrower_rep_headers(b1["id"])
        loans = validate_success(api.list_loans(headers))
        assert len(loans) == 1
        assert loans[0]["id"] == l1["id"]

        resp = api.list_loans(headers, params={"borrower_id": b2["id"]})
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_owner_cannot_create_position_for_another_owner(self, api):
        """PRD §3.2: "The create payload carries the `owner_id` — which must
        equal the caller's `X-User-ID`, since an owner representative may
        only offer their own inventory"
        PRD §2.7: "for `OwnerRep` and `BorrowerRep` callers, the
        caller's `X-User-ID` equals the `owner_id` or `borrower_id` of the
        resource acted on (or supplied in the body), and list filters follow
        the auto-scoping rule; otherwise `ERR_FORBIDDEN`."

        Design: Corner/rbac/owner_cannot_create_position_for_another_owner
        """
        security = create_security(symbol="RB4", price_cents=1000)
        owner_a = create_owner(display_name="Owner Rb4a")
        owner_b = create_owner(display_name="Owner Rb4b")
        resp = api.create_lendable_position(
            {"owner_id": owner_b["id"], "security_id": security["id"],
             "quantity_total": 1000, "min_fee_bps": 25},
            make_owner_rep_headers(owner_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
