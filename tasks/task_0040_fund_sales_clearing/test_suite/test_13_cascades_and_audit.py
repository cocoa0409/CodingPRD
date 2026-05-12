"""PRD §2.8 / §3.4 / §3.6 / §3.8: Cross-aggregate cascades and audit log.

Covers:
  - Three-hop SUBSCRIBE confirm cascade (LotEntry -> Holding ->
    Fund.total_outstanding_shares + Investor.cash_balance_cents)
  - Suspension cascade on pending orders
  - Audit log retrieval and content for state changes
"""
from __future__ import annotations
import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    create_subscribe_order_payload,
    find_audit_entries,
    get_fund_fresh,
    get_order_fresh,
    list_audit_logs_for,
    make_investor_headers,
    publish_nav_payload,
    setup_basic_investor_and_fund,
    setup_investor_with_confirmed_subscribe,
    submit_subscribe_order,
    subscribe_confirm,
    validate_success,
)


# =====================================================================
# SUBSCRIBE confirm three-hop cascade (PRD §3.4 / §2.8)
# =====================================================================
class TestSubscribeConfirmCascade:
    def test_three_hop_cascade_after_subscribe_confirm(self, api):
        """PRD §3.4: "for `SUBSCRIBE`, a new `LotEntry` is created with
        `holding_id` referencing the investor's holding for the fund,
        ..., the investor's `Holding.shares` and `Holding.cost_basis_cents`
        are recomputed by re-aggregating the open lots; `Fund.total_outstanding_shares`
        is increased by the confirmed shares; and the investor's
        `cash_balance_cents` is decreased by the order's
        `gross_amount_cents`."

        Claim: after a single SUBSCRIBE confirmation:
          - hop 1: a new LotEntry is created (verified indirectly via
            Holding.shares which aggregates over OPEN lots).
          - hop 2: Holding.shares == confirmed_shares.
          - hop 3: Fund.total_outstanding_shares == confirmed_shares.
          - Investor.cash_balance_cents = previous - gross_amount.

        # difficulty: transitive_cascade/subscribe_confirm_three_hop_cascade
        """
        investor, fund = setup_basic_investor_and_fund(
            cash_cents=200_000,
            fund_overrides={
                "subscription_fee_tiers": [
                    {"min_amount_cents": 0, "max_amount_cents": None,
                     "rate_bps": 150},
                ],
                "back_end_load_enabled": False,
                "management_fee_bps_annual": 0,
                "custodian_fee_bps_annual": 0,
                "sales_service_fee_bps_annual": 0,
            },
        )
        cash_before = investor["cash_balance_cents"]
        assert cash_before == 200_000

        advance_clock_to("2027-12-01T10:00:00.000Z")
        order, nav = subscribe_confirm(
            investor, fund, gross_amount_cents=100_000,
        )
        assert order["status"] == "CONFIRMED"
        # PRD §3.5 front-end model: 100_000 * 150/10000 = 1_500 fee, net
        # = 98_500, shares = 98_500 * 1e8 / 1_000_000 = 9_850_000.
        assert order["confirmed_shares"] == 9_850_000

        # hop 2: Holding.shares aggregates from new lot.
        holdings_res = api.list_investor_holdings(
            investor["id"], make_investor_headers(investor["id"])
        )
        holdings_payload = validate_success(holdings_res)
        # PRD §2.2: list responses use response_type="array" with data
        # field as the array. Here we got the data through validate_success
        # which returns the entire data field; for arrays it returns the
        # list directly.
        holdings = (
            holdings_payload
            if isinstance(holdings_payload, list)
            else holdings_payload.get("items", [])
        )
        # One holding for this fund.
        my_holding = next(
            (h for h in holdings if h.get("fund_id") == fund["id"]),
            None,
        )
        assert my_holding is not None, (
            f"PRD §3.4 cascade hop 2: Holding for (investor, fund) must "
            f"exist after SUBSCRIBE confirm; got {holdings!r}"
        )
        assert my_holding["shares"] == 9_850_000, (
            f"PRD §3.4 cascade hop 2: Holding.shares == confirmed_shares; "
            f"got {my_holding['shares']}"
        )

        # hop 3: Fund.total_outstanding_shares.
        fund_after = get_fund_fresh(fund["id"])
        assert fund_after["total_outstanding_shares"] == 9_850_000, (
            f"PRD §3.4 cascade hop 3: Fund.total_outstanding_shares += "
            f"confirmed_shares; got "
            f"{fund_after['total_outstanding_shares']}"
        )

        # Investor cash debit
        from test_helpers import api_client as ac
        inv_after = validate_success(ac.get_investor(
            investor["id"], TEST_USERS["platform_admin_headers"]
        ))
        assert inv_after["cash_balance_cents"] == cash_before - 100_000, (
            f"PRD §3.4: Investor.cash_balance_cents -= gross_amount; got "
            f"{inv_after['cash_balance_cents']} (expected "
            f"{cash_before - 100_000})"
        )


# =====================================================================
# Audit log: SUBSCRIBE confirm produces ORDER_STATUS_CHANGE rows
# =====================================================================
class TestAuditLogOrderStatusChange:
    def test_audit_log_records_subscribe_to_accepted(self, api):
        """PRD §3.3: "an `AuditLog` row with `action`
        `ORDER_STATUS_CHANGE` and `from_state`/`to_state` pair
        `SUBMITTED` / `ACCEPTED` is written."

        PRD §3.8: "Compliance and platform-administration roles can
        query the log filtered by `action` (one of `ORDER_STATUS_CHANGE`,
        `NAV_PUBLISHED`, `NAV_ADJUSTED`, `DIVIDEND_EXECUTED`,
        `RECONCILIATION_RESOLVED`, `FUND_SHELF_CHANGE`), by
        `subject_entity` (the entity name affected), and by `subject_id`
        (the id of the affected entity)."

        Claim: after submitting an order that reaches ACCEPTED, an
        ORDER_STATUS_CHANGE audit row exists with from_state=SUBMITTED
        and to_state=ACCEPTED for that order id.
        """
        investor, fund = setup_basic_investor_and_fund()
        advance_clock_to("2027-12-10T10:00:00.000Z")
        order = submit_subscribe_order(investor, fund, 1_000)
        assert order["status"] == "ACCEPTED"

        rows = list_audit_logs_for(
            action="ORDER_STATUS_CHANGE",
            subject_id=order["id"],
        )
        accepted_rows = find_audit_entries(
            rows,
            action="ORDER_STATUS_CHANGE",
            subject_id=order["id"],
            from_state="SUBMITTED",
            to_state="ACCEPTED",
        )
        assert len(accepted_rows) >= 1, (
            f"PRD §3.3: AuditLog ORDER_STATUS_CHANGE SUBMITTED -> ACCEPTED "
            f"row must be written; got rows={rows!r}"
        )


# =====================================================================
# (deleted) PRD §3.2 suspension cascade specifically targets orders in
# `SUBMITTED` status, but PRD §3.3 specifies that a single submission
# atomically traverses SUBMITTED -> ACCEPTED in the same request. A
# client therefore cannot observe an order in `SUBMITTED` to drive the
# cascade — the asserted scenario is unreachable from the API surface,
# which is a STEP 1b unique-derivability failure (BRANCH-ASYMMETRIC
# SIDE EFFECT pattern). Removed per the cardinal rule that skipped
# tests must be deleted, not preserved.
# =====================================================================


# =====================================================================
# Audit log: NAV publication
# =====================================================================
class TestAuditLogNavPublished:
    def test_audit_log_records_nav_published(self, api):
        """PRD §3.4: "A successful publication writes the snapshot with
        `status` `PUBLISHED`, sets `published_at` to the server clock at
        publication time, and writes an `AuditLog` `NAV_PUBLISHED` row
        with the `PROVISIONAL → PUBLISHED` pair."

        Claim: after a NAV publish call, a NAV_PUBLISHED audit row
        exists with from_state=PROVISIONAL and to_state=PUBLISHED for
        the snapshot.
        """
        investor, fund, order, nav = setup_investor_with_confirmed_subscribe(
            gross_amount_cents=1_000,
            submit_at="2027-12-15T10:00:00.000Z",
        )
        # Use the snapshot id (PRD §2.4: NavSnapshot has only id +
        # created_at) as subject_id of the audit lookup.
        rows = list_audit_logs_for(
            action="NAV_PUBLISHED",
            subject_id=nav["id"],
        )
        published_rows = find_audit_entries(
            rows,
            action="NAV_PUBLISHED",
            subject_id=nav["id"],
            from_state="PROVISIONAL",
            to_state="PUBLISHED",
        )
        assert len(published_rows) >= 1, (
            f"PRD §3.4: AuditLog NAV_PUBLISHED PROVISIONAL -> PUBLISHED "
            f"row must be written for snapshot {nav['id']!r}; got "
            f"rows={rows!r}"
        )


# =====================================================================
# Audit log: FUND_SHELF_CHANGE on approve-shelf
# =====================================================================
class TestAuditLogFundShelfChange:
    def test_approve_shelf_writes_audit_log(self, api):
        """PRD §3.2: "On approval, the fund advances `UNDER_REVIEW →
        ON_SHELF`, ... An `AuditLog` row is written with `action`
        `FUND_SHELF_CHANGE` and the `from_state` / `to_state` pair
        `UNDER_REVIEW` / `ON_SHELF`."

        Claim: after approve-shelf, an audit row with the documented
        from_state/to_state exists.
        """
        from test_helpers import create_on_shelf_fund
        fund = create_on_shelf_fund()
        rows = list_audit_logs_for(
            action="FUND_SHELF_CHANGE",
            subject_id=fund["id"],
        )
        approval_rows = find_audit_entries(
            rows,
            action="FUND_SHELF_CHANGE",
            subject_id=fund["id"],
            from_state="UNDER_REVIEW",
            to_state="ON_SHELF",
        )
        assert len(approval_rows) >= 1, (
            f"PRD §3.2: AuditLog FUND_SHELF_CHANGE UNDER_REVIEW -> "
            f"ON_SHELF row must be written; got rows={rows!r}"
        )
