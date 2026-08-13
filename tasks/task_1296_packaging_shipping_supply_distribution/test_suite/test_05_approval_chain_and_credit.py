"""The corporate PO_REVIEW approval chain: routing threshold, credit-check
boundary, suspension priority, and the reject-resubmit loop."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_line,
    assert_order,
    create_draft_order,
    create_inventory,
    create_stock_product,
    make_approver_headers,
    make_buyer_headers,
    set_clock,
    setup_warehouse_and_account,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _setup_po_review_order(api, credit_limit_cents=100_000_000, po_number="PO-77"):
    """11 units of a 100000-cent product -> grand 1,118,005 > 1,000,000, so the
    submit routes to PO_REVIEW. Returns (account, order, submit_response)."""
    wh, acct = setup_warehouse_and_account(po_required=True,
                                           credit_limit_cents=credit_limit_cents)
    prod = create_stock_product(sku="BX-900", name="Gaylord Box", base_price_cents=100000,
                                pallet_qty=1000)
    create_inventory(prod["id"], wh["id"], 100)
    set_clock("2026-08-03T10:00:00Z")
    order = create_draft_order(acct["id"], ship_zone=5, po_number=po_number)
    add_line(order["id"], acct["id"], prod["id"], 11)
    submitted = validate_success(api.submit_order(order["id"], make_buyer_headers(acct["id"])))
    assert submitted["status"] == "PO_REVIEW", (
        f"Setup failed: expected PO_REVIEW routing, got {submitted['status']}")
    return acct, order, submitted


class TestPoReviewRejectResubmitCycle:
    def test_reject_resubmit_status_cycle(self, api):
        """PRD section 3.4: "on a `po_required` corporate account whose computed
        `grand_total_cents` exceeds one million cents — ten thousand dollars —
        the order moves to `PO_REVIEW` and the allocation pass is deferred
        until approval (§3.5)."
        PRD section 3.5: "Rejection, which may carry an optional `reason`,
        returns the order to `DRAFT`: no reservation was ever taken, the
        invoice stays `OPEN` with totals recomputed, and the `version`
        increments — a deliberate revise-and-resubmit loop between buyer and
        approver."
        PRD section 3.5: "On success the deferred allocation pass runs exactly
        as it would have at submit — sourcing selection, reservations, the
        backorder split check with the same `ERR_NO_WAREHOUSE_CAPABLE` and
        `ERR_BACKORDER_NOT_ALLOWED` outcomes, custom job creation, and a full
        pricing and provisional freight recompute — followed by an
        open-receivable refresh and a `version` increment."

        Design: Difficulty/non_linear_state_machine/order_po_review_reject_resubmit_cycle
        """
        acct, order, submitted = _setup_po_review_order(api)
        assert submitted["status"] == "PO_REVIEW"

        rejected = validate_success(api.reject_order(
            order["id"], {"reason": "price too high"}, make_approver_headers(acct["id"])))
        assert_order(rejected)
        assert rejected["status"] == "DRAFT"
        assert rejected["invoice_status"] == "OPEN"

        resubmitted = validate_success(api.submit_order(order["id"], make_buyer_headers(acct["id"])))
        assert resubmitted["status"] == "PO_REVIEW"

        approved = validate_success(api.approve_order(order["id"], make_approver_headers(acct["id"])))
        assert approved["status"] == "STOCK_RESERVED"

    def test_version_increments_once_per_lifecycle_transition(self, api):
        """PRD section 2.4: "`version` (integer): a system-managed integer that
        increments by one on every mutation of the resource, and underpins
        optimistic concurrency control where it applies."
        PRD section 3.5: "Rejection, which may carry an optional `reason`,
        returns the order to `DRAFT`: no reservation was ever taken, the
        invoice stays `OPEN` with totals recomputed, and the `version`
        increments — a deliberate revise-and-resubmit loop between buyer and
        approver."

        Design: Difficulty/non_linear_state_machine/order_po_review_reject_resubmit_cycle
        """
        acct, order, submitted = _setup_po_review_order(api)
        v_create = order["version"]
        assert submitted["version"] == v_create + 1

        rejected = validate_success(api.reject_order(
            order["id"], {"reason": "price too high"}, make_approver_headers(acct["id"])))
        assert rejected["version"] == submitted["version"] + 1

        resubmitted = validate_success(api.submit_order(order["id"], make_buyer_headers(acct["id"])))
        assert resubmitted["version"] == rejected["version"] + 1

        approved = validate_success(api.approve_order(order["id"], make_approver_headers(acct["id"])))
        assert approved["version"] == resubmitted["version"] + 1


class TestSuspendedOutranksCreditLimit:
    def _setup(self, api):
        acct, order, submitted = _setup_po_review_order(api, credit_limit_cents=100,
                                                        po_number="PO-CR")
        validate_success(api.suspend_account(acct["id"], ADMIN))
        return acct, order, submitted

    def test_approve_while_suspended_reports_suspension_not_credit(self, api):
        """PRD section 3.5: "Approval first confirms the order is actually in
        `PO_REVIEW` (any other state yields `ERR_INVALID_STATE`), that the
        account is still `ACTIVE` (else `ERR_ACCOUNT_SUSPENDED`), and then runs
        the credit check: the account's `open_receivable_cents` plus the
        order's `grand_total_cents` must be at or below the account's
        `credit_limit_cents`."
        PRD section 2.9: "Only then do the domain rules fire, in this relative
        order: suspended-account gating (`ERR_ACCOUNT_SUSPENDED`), empty-order
        gating (`ERR_ORDER_EMPTY`), purchase-order presence (`ERR_PO_REQUIRED`),
        purchase-order uniqueness (`ERR_DUPLICATE_PO`), case-quantity multiples
        (`ERR_CASE_QTY_MISMATCH`), custom-print artwork and tolerance
        (`ERR_ARTWORK_REQUIRED`), duplicate restock subscriptions
        (`ERR_DUPLICATE_SUBSCRIPTION`), overlapping price windows
        (`ERR_OVERLAPPING_PRICE_WINDOW`), warehouse sourcing capability
        (`ERR_NO_WAREHOUSE_CAPABLE`), uncovered non-backorderable lines
        (`ERR_BACKORDER_NOT_ALLOWED`), press occupancy (`ERR_PRESS_OCCUPIED`),
        the credit check (`ERR_CREDIT_LIMIT_EXCEEDED`)"

        Design: Difficulty/priority_pair_validation_conflict/suspended_account_outranks_credit_limit
        """
        acct, order, submitted = self._setup(api)
        resp = api.approve_order(order["id"], make_approver_headers(acct["id"]))
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)

    def test_credit_limit_surfaces_once_suspension_clears(self, api):
        """PRD section 3.5: "Approval first confirms the order is actually in
        `PO_REVIEW` (any other state yields `ERR_INVALID_STATE`), that the
        account is still `ACTIVE` (else `ERR_ACCOUNT_SUSPENDED`), and then runs
        the credit check: the account's `open_receivable_cents` plus the
        order's `grand_total_cents` must be at or below the account's
        `credit_limit_cents`. Sitting exactly at the limit passes; exceeding it
        rejects the approval with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/suspended_account_outranks_credit_limit
        """
        acct, order, submitted = self._setup(api)
        validate_error(api.approve_order(order["id"], make_approver_headers(acct["id"])),
                       ApiErrorId.ERR_ACCOUNT_SUSPENDED)
        validate_success(api.reactivate_account(acct["id"], ADMIN))
        # Prospective 0 + 1,118,005 > 100 -> the unmasked credit check fires.
        resp = api.approve_order(order["id"], make_approver_headers(acct["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


class TestCreditLimitBoundary:
    """101 units at 10000 cents + provisional freight 165317 -> grand exactly
    1,175,317 cents; open receivable is 0 while parked in PO_REVIEW."""

    def _setup(self, api):
        wh, acct = setup_warehouse_and_account(po_required=True,
                                               credit_limit_cents=1_175_317)
        prod = create_stock_product(sku="BX-200", name="Book Box", base_price_cents=10000,
                                    pallet_qty=1000)
        create_inventory(prod["id"], wh["id"], 1000)
        set_clock("2026-08-03T10:00:00Z")
        order = create_draft_order(acct["id"], ship_zone=5, po_number="PO-EQ")
        add_line(order["id"], acct["id"], prod["id"], 101)
        submitted = validate_success(api.submit_order(order["id"], make_buyer_headers(acct["id"])))
        assert submitted["status"] == "PO_REVIEW"
        assert submitted["grand_total_cents"] == 1_175_317
        return acct, order, submitted

    def test_approve_one_cent_below_limit_fails(self, api):
        """PRD section 3.5: "the credit check: the account's
        `open_receivable_cents` plus the order's `grand_total_cents` must be at
        or below the account's `credit_limit_cents`. Sitting exactly at the
        limit passes; exceeding it rejects the approval with
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/credit_limit_equality_passes_one_cent_below_fails
        """
        acct, order, submitted = self._setup(api)
        validate_success(api.patch_account(acct["id"], {"credit_limit_cents": 1_175_316}, ADMIN))
        resp = api.approve_order(order["id"], make_approver_headers(acct["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

    def test_approve_exactly_at_limit_passes(self, api):
        """PRD section 3.5: "the credit check: the account's
        `open_receivable_cents` plus the order's `grand_total_cents` must be at
        or below the account's `credit_limit_cents`. Sitting exactly at the
        limit passes; exceeding it rejects the approval with
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."
        PRD section 3.5: "On success the deferred allocation pass runs exactly
        as it would have at submit"

        Design: Difficulty/boundary_precision_check/credit_limit_equality_passes_one_cent_below_fails
        """
        acct, order, submitted = self._setup(api)
        validate_success(api.patch_account(acct["id"], {"credit_limit_cents": 1_175_316}, ADMIN))
        validate_error(api.approve_order(order["id"], make_approver_headers(acct["id"])),
                       ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        # Restore the exact-limit value: equality must pass.
        validate_success(api.patch_account(acct["id"], {"credit_limit_cents": 1_175_317}, ADMIN))
        approved = validate_success(api.approve_order(order["id"], make_approver_headers(acct["id"])))
        assert approved["status"] == "STOCK_RESERVED"
