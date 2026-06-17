"""Warranty approval REFUND-vs-REPLACE remedies and cross-entity state dependencies
(allocate blocked by ON_HOLD account; core-return reject leaves A/R untouched).

Queue A: dual_variant_calc (warranty credit), cross_entity_state_dependency.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, api_client,
    setup_warranty_claim, setup_open_wholesale_order_with_line, setup_pending_core_return,
    allocate_payload, current_version,
    ApiErrorId,
    TEST_USERS,
)

REP = TEST_USERS["wholesale_rep_headers"]
INV = TEST_USERS["inventory_manager_headers"]
ADMIN = TEST_USERS["warranty_admin_headers"]


# ─── dual_variant_calc: dvc_warranty_refund_vs_replace_on_claim ───────────────

class TestWarrantyRefundVsReplace:
    """Same claim inputs, two remedies: REFUND credits A/R, REPLACE debits stock."""

    def test_refund_claim_credits_unit_merch_price(self, api):
        """PRD §3.7: "On a REFUND resolution the credit credit_cents is the claim qty
        multiplied by the line's snapshot unit_merch_price_cents, and that credit is
        applied against the account - the account's ar_balance_cents is decreased by
        credit_cents, clamped at a floor of zero - with no replacement unit issued."

        Wholesale caliper line unit_merch 14000; APPROVED REFUND -> credit_cents 14000.

        Design: Difficulty/dual_variant_calc/dvc_warranty_refund_vs_replace_on_claim
        """
        part, account, order, line, claim = setup_warranty_claim(
            resolution="REFUND", qty=1, line_qty=1, warranty_days=365)
        approved = get_success_data(api_client.approve_claim(claim["id"], ADMIN))
        assert approved["status"] == "APPROVED"
        assert approved["credit_cents"] == 14000, (
            f"REFUND credit_cents expected 14000, got {approved['credit_cents']}"
        )

    def test_replace_claim_issues_zero_credit(self, api):
        """PRD §3.7: "On a REPLACE resolution the credit_cents is zero and no A/R
        credit is issued; instead a replacement unit is issued by decreasing the
        part's on_hand_qty by the claim qty and recomputing available_qty".

        APPROVED REPLACE on the same caliper line -> credit_cents 0.

        Design: Difficulty/dual_variant_calc/dvc_warranty_refund_vs_replace_on_claim
        """
        part, account, order, line, claim = setup_warranty_claim(
            resolution="REPLACE", qty=1, line_qty=1, warranty_days=365)
        approved = get_success_data(api_client.approve_claim(claim["id"], ADMIN))
        assert approved["status"] == "APPROVED"
        assert approved["credit_cents"] == 0, (
            f"REPLACE credit_cents expected 0, got {approved['credit_cents']}"
        )

    def test_refund_relieves_account_replace_does_not(self, api):
        """PRD §3.7: "On a REFUND resolution the credit credit_cents is the claim qty
        multiplied by the line's snapshot unit_merch_price_cents, and that credit is
        applied against the account - the account's ar_balance_cents is decreased by
        credit_cents, clamped at a floor of zero - with no replacement unit issued."
        PRD §3.7: "On a REPLACE resolution the credit_cents is zero and no A/R credit
        is issued; instead a replacement unit is issued by decreasing the part's
        on_hand_qty by the claim qty and recomputing available_qty".

        REFUND drops A/R from 19400 to 5400; REPLACE debits one on-hand unit and
        leaves A/R unchanged.

        Design: Difficulty/dual_variant_calc/dvc_warranty_refund_vs_replace_on_claim
        """
        # REFUND arm
        p_r, acct_r, ord_r, line_r, claim_r = setup_warranty_claim(
            resolution="REFUND", qty=1, line_qty=1, warranty_days=365)
        ar_before = get_success_data(api_client.get_account(acct_r["id"], REP))["ar_balance_cents"]
        assert ar_before == 19400
        get_success_data(api_client.approve_claim(claim_r["id"], ADMIN))
        ar_after = get_success_data(api_client.get_account(acct_r["id"], REP))["ar_balance_cents"]
        assert ar_after == 5400, f"REFUND should relieve A/R to 5400, got {ar_after}"

        # REPLACE arm
        p_x, acct_x, ord_x, line_x, claim_x = setup_warranty_claim(
            resolution="REPLACE", qty=1, line_qty=1, warranty_days=365, stock_qty=5)
        on_hand_before = get_success_data(api_client.get_part(p_x["id"], INV))["on_hand_qty"]
        ar_x_before = get_success_data(api_client.get_account(acct_x["id"], REP))["ar_balance_cents"]
        get_success_data(api_client.approve_claim(claim_x["id"], ADMIN))
        on_hand_after = get_success_data(api_client.get_part(p_x["id"], INV))["on_hand_qty"]
        ar_x_after = get_success_data(api_client.get_account(acct_x["id"], REP))["ar_balance_cents"]
        assert on_hand_after == on_hand_before - 1, "REPLACE debits one on-hand unit"
        assert ar_x_after == ar_x_before, "REPLACE issues no A/R credit"


# ─── cross_entity_state_dependency: cesd_allocate_blocked_by_account_on_hold ───

class TestAllocateBlockedByAccountHold:
    """Allocate is valid only when the referenced Account.status == ACTIVE."""

    def test_allocate_rejected_when_account_on_hold(self, api):
        """PRD §3.4: "Several preconditions guard the transition, evaluated as a
        group: the order must have at least one line (otherwise ERR_EMPTY_ORDER);
        the buying account must be ACTIVE (otherwise ERR_ACCOUNT_ON_HOLD)".

        Account placed ON_HOLD after the order was opened with a stock line; allocate
        is refused with ERR_ACCOUNT_ON_HOLD.

        Design: Difficulty/cross_entity_state_dependency/cesd_allocate_blocked_by_account_on_hold
        """
        part, account, order, line = setup_open_wholesale_order_with_line(qty=1, stock_qty=5)
        get_success_data(api_client.hold_account(account["id"], REP))
        v = current_version(order["id"])
        resp = api.allocate_order(order["id"], allocate_payload(v), REP)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_ON_HOLD.value)

    def test_order_stays_open_after_blocked_allocate(self, api):
        """PRD §3.4: "the buying account must be ACTIVE (otherwise
        ERR_ACCOUNT_ON_HOLD)".

        A rejected allocate must not advance the order's fulfillment_status; it
        remains OPEN.

        Design: Difficulty/cross_entity_state_dependency/cesd_allocate_blocked_by_account_on_hold
        """
        part, account, order, line = setup_open_wholesale_order_with_line(qty=1, stock_qty=5)
        get_success_data(api_client.hold_account(account["id"], REP))
        v = current_version(order["id"])
        api.allocate_order(order["id"], allocate_payload(v), REP)
        after = get_success_data(api_client.get_sales_order(order["id"], REP))
        assert after["fulfillment_status"] == "OPEN", "order must remain OPEN after blocked allocate"


# ─── cross_entity_state_dependency: cesd_core_accept_blocked_by_line_not_shipped ─

class TestCoreReturnReject:
    """A core return can be rejected from PENDING_INSPECTION, refunding nothing."""

    def test_reject_core_return_issues_no_refund(self, api):
        """PRD §3.6: "Rejecting a return - moving it from PENDING_INSPECTION to
        REJECTED - requires only that the return be PENDING_INSPECTION (otherwise
        ERR_CORE_RETURN_NOT_PENDING); no deposit is refunded and cores_outstanding
        is left unchanged."

        Rejecting a pending core return moves it to REJECTED.

        Design: Difficulty/cross_entity_state_dependency/cesd_core_accept_blocked_by_line_not_shipped
        """
        part, account, order, line, cr = setup_pending_core_return(qty=1, line_qty=1)
        rejected = get_success_data(api_client.reject_core_return(cr["id"], ADMIN))
        assert rejected["status"] == "REJECTED"

    def test_reject_leaves_account_ar_unchanged(self, api):
        """PRD §3.6: "no deposit is refunded and cores_outstanding is left
        unchanged."

        A rejected core return refunds no deposit, so the invoiced order's A/R
        (19400) is untouched.

        Design: Difficulty/cross_entity_state_dependency/cesd_core_accept_blocked_by_line_not_shipped
        """
        part, account, order, line, cr = setup_pending_core_return(qty=1, line_qty=1)
        before = get_success_data(api_client.get_account(account["id"], REP))["ar_balance_cents"]
        get_success_data(api_client.reject_core_return(cr["id"], ADMIN))
        after = get_success_data(api_client.get_account(account["id"], REP))["ar_balance_cents"]
        assert after == before == 19400, "rejected core return must not change A/R"
