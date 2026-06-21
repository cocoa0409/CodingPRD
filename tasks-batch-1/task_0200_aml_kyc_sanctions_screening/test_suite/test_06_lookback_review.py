"""Lookback review: enqueue windowing, escalate cascade, compound completion."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_account_payload, create_transaction_payload,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

CO = TEST_USERS["compliance_officer_headers"]
AN = TEST_USERS["analyst_headers"]
SF = TEST_USERS["system_feed_headers"]


# ==========================================================================
# Queue A — transitive_cascade (lookback escalate -> alert -> account)
# ==========================================================================
def test_lookback_escalate_cascade_depth2(api):
    """PRD §3.10: "Escalating an item moves it to `ESCALATED`, increments the
    parent's `escalated_items`, and mints an `Alert` with `rule_code` of
    `HIGH_RISK_GEO` and `status` of `OPEN` against the item's `account_id`,
    recording that alert into the item's `generated_alert_id`; as a cross-entity
    cascade, if that account's `monitoring_status` is `ACTIVE` it advances to
    `UNDER_INVESTIGATION`."

    Design: Difficulty/transitive_cascade/lookback_escalate_cascade_depth2_alert_then_account
    """
    cust, acct, review, item = fx.setup_in_progress_lookback(clock="2026-06-10T00:00:00Z")
    assert item["item_status"] == "QUEUED"
    escalated = validate_success(api.disposition_lookback_item(item["id"], {"decision": "ESCALATE"}, AN))
    assert escalated["item_status"] == "ESCALATED"          # forward action
    assert escalated["generated_alert_id"] is not None      # link 1: alert minted
    acct_after = validate_success(api.get_account(acct["id"], CO))
    assert acct_after["monitoring_status"] == "UNDER_INVESTIGATION"  # link 2, caused by link 1


def test_lookback_escalate_mints_high_risk_geo_alert_on_account(api):
    """PRD §3.10: "Escalating an item moves it to `ESCALATED`, increments the
    parent's `escalated_items`, and mints an `Alert` with `rule_code` of
    `HIGH_RISK_GEO` and `status` of `OPEN` against the item's `account_id`,
    recording that alert into the item's `generated_alert_id`".

    The minted (link-1) alert carries rule_code HIGH_RISK_GEO, status OPEN, and
    is bound to the item's account — the first link of the depth-2 chain.

    Design: Difficulty/transitive_cascade/lookback_escalate_cascade_depth2_alert_then_account
    """
    cust, acct, review, item = fx.setup_in_progress_lookback(clock="2026-06-10T00:00:00Z")
    escalated = validate_success(api.disposition_lookback_item(item["id"], {"decision": "ESCALATE"}, AN))
    gen_alert_id = escalated["generated_alert_id"]
    assert gen_alert_id is not None
    alert = validate_success(api.get_alert(gen_alert_id, AN))
    assert alert["rule_code"] == "HIGH_RISK_GEO"
    assert alert["status"] == "OPEN"
    assert alert["account_id"] == acct["id"]


# ==========================================================================
# Queue A — resource_temporal_overlap (half-open window boundary)
# ==========================================================================
def test_lookback_window_half_open_boundary(api):
    """PRD §3.10: "The window is half-open: a transaction is in-window when its
    `posted_at` is at or after `window_start` and strictly before `window_end` —
    a transaction posted exactly at `window_start` is in-window, while one posted
    exactly at `window_end` is not."
    PRD §3.10: "an account contributes exactly one item no matter how many of its
    transactions fall in the window".

    acct_start has a txn at window_start (in-window); acct_end has a txn at
    window_end (out). Enqueue materializes exactly 1 item.

    Design: Difficulty/resource_temporal_overlap/lookback_window_half_open_boundary_on_review
    """
    cust = fx.create_legal_entity(legal_name="Win2 Co", incorporation_date="2016-06-06")
    acct_start = fx.create_account(cust["id"], account_ref="AC-WSTART")
    acct_end = fx.create_account(cust["id"], account_ref="AC-WEND")
    validate_success(api.post_transaction(
        acct_start["id"], create_transaction_payload(direction="CASH_IN", amount_cents=5000,
                                                     posted_at="2026-06-01T00:00:00Z", counterparty_country="US"), SF), 201)
    validate_success(api.post_transaction(
        acct_end["id"], create_transaction_payload(direction="CASH_IN", amount_cents=5000,
                                                   posted_at="2026-06-08T00:00:00Z", counterparty_country="US"), SF), 201)
    review = fx.create_lookback_review(
        reason="half-open boundary probe", window_start="2026-06-01T00:00:00Z",
        window_end="2026-06-08T00:00:00Z")
    enq = validate_success(api.enqueue_lookback_review(review["id"], CO))
    assert enq["total_items"] == 1
    assert enq["status"] == "IN_PROGRESS"
    start_items, _ = fx._list(api.list_all_lookback_items(AN, params={"account_id": acct_start["id"]}))
    end_items, _ = fx._list(api.list_all_lookback_items(AN, params={"account_id": acct_end["id"]}))
    assert len(start_items) == 1
    assert len(end_items) == 0


def test_lookback_window_start_inclusive_single_account(api):
    """PRD §3.10: "a transaction posted exactly at `window_start` is in-window,
    while one posted exactly at `window_end` is not."
    PRD §3.10: "The review's `total_items` is set to the number of items
    created."

    Inclusive-start facet in isolation: a single account whose only transaction
    is at exactly window_start is in-window, materializing exactly one item and
    advancing the review to IN_PROGRESS.

    Design: Difficulty/resource_temporal_overlap/lookback_window_half_open_boundary_on_review
    """
    cust = fx.create_legal_entity(legal_name="StartInc Co")
    acct = fx.create_account(cust["id"], account_ref="AC-STARTINC")
    validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=5000,
                                               posted_at="2026-06-01T00:00:00Z", counterparty_country="US"), SF), 201)
    review = fx.create_lookback_review(
        reason="start-inclusive probe", window_start="2026-06-01T00:00:00Z",
        window_end="2026-06-08T00:00:00Z")
    enq = validate_success(api.enqueue_lookback_review(review["id"], CO))
    assert enq["total_items"] == 1
    assert enq["status"] == "IN_PROGRESS"


# ==========================================================================
# Queue B — lookback corner instances
# ==========================================================================
def test_lookback_compound_completes_when_all_items_terminal(api):
    """PRD §3.10: "The review is compound: its status is a function of its items.
    The instant the sum of `cleared_items` and `escalated_items` equals
    `total_items` — every item having reached a terminal disposition — the parent
    bubbles from `IN_PROGRESS` to the terminal `COMPLETED` state."

    Design: Corner/state_machines/lookback_compound_completes_when_all_items_terminal
    """
    cust, acct, review, item = fx.setup_in_progress_lookback()
    cleared = validate_success(api.disposition_lookback_item(item["id"], {"decision": "CLEAR"}, AN))
    assert cleared["item_status"] == "CLEARED"
    review_after = validate_success(api.get_lookback_review(review["id"], CO))
    assert review_after["cleared_items"] == 1
    assert review_after["status"] == "COMPLETED"


def test_item_not_queued_disposition_rejected(api):
    """PRD §3.10: "a disposition is only permitted when the item is in `QUEUED`
    and its parent review is in `IN_PROGRESS` (otherwise `ERR_ITEM_NOT_QUEUED`)."

    Re-dispositioning an already-CLEARED item -> ERR_ITEM_NOT_QUEUED.

    Design: Corner/errors/item_not_queued_disposition_rejected
    """
    cust, acct, review, item = fx.setup_in_progress_lookback()
    validate_success(api.disposition_lookback_item(item["id"], {"decision": "CLEAR"}, AN))
    validate_error(api.disposition_lookback_item(item["id"], {"decision": "ESCALATE"}, AN),
                   ApiErrorId.ERR_ITEM_NOT_QUEUED.value)


def test_invalid_window_returns_422(api):
    """PRD §3.10: "the window end must be strictly after the window start, and a
    window that is not is rejected with `ERR_INVALID_WINDOW`."

    Design: Corner/validations/invalid_window_returns_422
    """
    validate_error(api.create_lookback_review(
        {"reason": "bad window", "window_start": "2026-06-01T00:00:00Z",
         "window_end": "2026-06-01T00:00:00Z"}, CO),
        ApiErrorId.ERR_INVALID_WINDOW.value)
