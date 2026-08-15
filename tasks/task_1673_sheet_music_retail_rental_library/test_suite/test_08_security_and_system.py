"""User-context enforcement, role and ownership gates, clock and sweep basics."""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    create_account,
    create_order,
    create_publisher,
    create_rental_set,
    create_work,
    dispatch_order,
    fetch_order,
    make_customer_headers,
    reserve_order,
    setup_draft_invoice,
    validate_error,
    validate_success,
)

from test_helpers import ADMIN, RETURNS


class TestUserContextHeader:
    def test_missing_user_context_header_rejected(self, api):
        """PRD §2.1: "Every request carries two mandatory HTTP headers: `X-User-ID`
        identifies the acting user and `X-User-Role` names their operational
        capacity. ... A request missing either header, or carrying a malformed
        value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)".

        Design: Corner/rbac/missing_user_context_header_rejected
        """
        publisher = create_publisher("Hdr Pub")

        # No X-User-ID / X-User-Role headers at all.
        resp = api.get_publisher(publisher["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

        # Role header present but user id missing is equally malformed.
        resp2 = api.get_publisher(publisher["id"], headers={"X-User-Role": "LibraryAdmin"})
        validate_error(resp2, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleGates:
    def test_returns_clerk_cannot_issue_damage_invoice(self, api):
        """PRD §2.1: "A request whose role is not permitted for the operation is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §3.6: "Issuance moves `DRAFT` → `ISSUED` and enforces segregation of
        duties" — issuance is a `BillingManager` operation.

        Design: Corner/rbac/returns_clerk_cannot_issue_damage_invoice
        """
        ws = setup_draft_invoice(publisher_name="RB Pub", work_title="RB Work",
                                 catalog_number="RB-1", set_code="RB-SET",
                                 account_overrides={"account_name": "RB Acct"})

        resp = api.issue_damage_invoice(ws["invoice"]["id"], RETURNS)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestCustomerOwnership:
    def test_customer_cannot_confirm_other_accounts_order(self, api):
        """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of
        the acting CustomerAccount; ownership checks on any resource that
        references a CustomerAccount compare the resource's `account_id` to
        `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_ACCOUNT`
        (HTTP 403)."
        PRD §3.5: "the acting customer must belong to the order's account
        (`ERR_FORBIDDEN_ACCOUNT`)".

        Design: Corner/rbac/customer_cannot_read_other_accounts_order_actions
        """
        publisher = create_publisher("OW Pub")
        work = create_work(publisher["id"], title="OW Work", catalog_number="OW-1")
        rental_set = create_rental_set(work["id"], set_code="OW-SET", copy_count=5,
                                       replacement_value_cents=40000)
        account_a = create_account("OW A", credit_tier="STANDARD", credit_limit_cents=0)
        account_b = create_account("OW B", credit_tier="STANDARD", credit_limit_cents=0)
        advance_clock()
        order = create_order(account_a["id"], rental_set["id"], copies=1)
        reserve_order(order["id"])
        dispatch_order(order["id"])

        # Account B's contact tries to confirm receipt of account A's order.
        resp = api.confirm_receipt(order["id"], make_customer_headers(account_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ACCOUNT)
        assert fetch_order(order["id"])["status"] == "DISPATCHED"


class TestClockAndSweep:
    def test_clock_default_and_sweep_empty_run(self, api):
        """PRD §2.6: "At startup the logical clock reads exactly
        2026-08-01T00:00:00Z, and it never falls back to wall-clock time
        thereafter."
        PRD §2.6: "The sweep responds with tallies of its work: `swept_rentals`,
        `swept_perusals`, `swept_pos`, and `standing_flips`."

        Design: Corner/endpoints/clock_default_and_sweep_empty_run
        """
        tallies = validate_success(api.run_daily_sweep(ADMIN))
        assert tallies["swept_rentals"] == 0
        assert tallies["swept_perusals"] == 0
        assert tallies["swept_pos"] == 0
        assert tallies["standing_flips"] == 0
