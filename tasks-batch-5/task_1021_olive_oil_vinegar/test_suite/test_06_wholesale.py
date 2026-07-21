"""Wholesale account lifecycle: the CHANGES_REQUESTED revision cycle, approval gating of
orders, resubmission-from-SUBMITTED rejection, and not-found handling."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_member, create_bottle, create_order, pay_order,
    create_wholesale_account, submit_wholesale_account, decide_wholesale_account,
    unit_line, make_customer_headers, TEST_USERS,
)

APPROVER = TEST_USERS["wholesale_approver_headers"]


# ── Difficulty: non_linear_state_machine / wholesale_account_changes_requested_revision_cycle ──

def test_request_changes_moves_account_to_changes_requested(api):
    """PRD §3.7: "Requesting changes moves `SUBMITTED → CHANGES_REQUESTED` and records the
    reason". PRD §3.7: "an account for which changes were requested may be resubmitted
    `CHANGES_REQUESTED → SUBMITTED`, which clears the `rejection_reason`."

    Design: Difficulty/non_linear_state_machine/wholesale_account_changes_requested_revision_cycle
    """
    member = create_member(api)
    wa = create_wholesale_account(api, member)
    wa = submit_wholesale_account(api, member, wa)
    wa = decide_wholesale_account(api, wa, "REQUEST_CHANGES", rejection_reason="add tax cert")
    assert wa["status"] == "CHANGES_REQUESTED", wa["status"]
    wa = submit_wholesale_account(api, member, wa)
    assert wa["status"] == "SUBMITTED", wa["status"]


def test_approve_after_revision_cycle_sets_tier(api):
    """PRD §3.7: "Approving requires the `tier` to be one of `TIER_1`, `TIER_2`, or `TIER_3`;
    it sets that tier, moves the account `SUBMITTED → APPROVED`, and flips the owning member's
    `member_type` to `WHOLESALE`."

    Design: Difficulty/non_linear_state_machine/wholesale_account_changes_requested_revision_cycle
    """
    member = create_member(api)
    wa = create_wholesale_account(api, member)
    wa = submit_wholesale_account(api, member, wa)
    wa = decide_wholesale_account(api, wa, "REQUEST_CHANGES", rejection_reason="add tax cert")
    wa = submit_wholesale_account(api, member, wa)
    wa = decide_wholesale_account(api, wa, "APPROVE", tier="TIER_2")
    assert wa["status"] == "APPROVED", wa["status"]
    assert wa["tier"] == "TIER_2", wa["tier"]


# ── Difficulty: cross_entity_state_dependency / wholesale_order_requires_account_approved ──
# PRD localizes the wholesale-approval guard to payment (§3.4); order creation with a
# non-approved account is permitted (§3.3 sets the discount rate to zero). The tests therefore
# assert the rule at the PRD-covered endpoint (pay).

def test_pay_wholesale_order_with_submitted_account_rejected(api):
    """PRD §3.4: "If the order names a wholesale account, that account must be `APPROVED`, or the
    payment is rejected with `ERR_WHOLESALE_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/wholesale_order_requires_account_approved
    """
    member = create_member(api)
    product = create_bottle(api, unit_price_cents=3000)
    wa = create_wholesale_account(api, member)
    wa = submit_wholesale_account(api, member, wa)  # SUBMITTED, not APPROVED
    order = create_order(api, member, [unit_line(product["id"], 1)], wholesale_account_id=wa["id"])
    resp = api.pay_order(order["id"], {"expected_order_version": order["version"]},
                         make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_WHOLESALE_NOT_APPROVED.value)


def test_pay_wholesale_order_with_draft_account_rejected(api):
    """PRD §3.4: "If the order names a wholesale account, that account must be `APPROVED`, or the
    payment is rejected with `ERR_WHOLESALE_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/wholesale_order_requires_account_approved
    """
    member = create_member(api)
    product = create_bottle(api, unit_price_cents=3000)
    wa = create_wholesale_account(api, member)  # DRAFT, never submitted
    order = create_order(api, member, [unit_line(product["id"], 1)], wholesale_account_id=wa["id"])
    resp = api.pay_order(order["id"], {"expected_order_version": order["version"]},
                         make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_WHOLESALE_NOT_APPROVED.value)


# ── Corner: state_machines / resubmit_after_submitted_returns_invalid_state ──

def test_resubmit_already_submitted_account_rejected(api):
    """PRD §3.7: "The owner submits the application, moving it `DRAFT → SUBMITTED`; a later
    revision loop is supported, since an account for which changes were requested may be
    resubmitted `CHANGES_REQUESTED → SUBMITTED`, which clears the `rejection_reason`."
    PRD §2.10: "Only after those pass does the system evaluate state legality (whether the
    requested transition is defined from the resource's current state)".

    Design: Corner/state_machines/resubmit_after_submitted_returns_invalid_state
    """
    member = create_member(api)
    wa = create_wholesale_account(api, member)
    wa = submit_wholesale_account(api, member, wa)  # now SUBMITTED
    resp = api.submit_wholesale_account(wa["id"], make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ── Corner: errors / wholesale_account_not_found ──

def test_decision_on_missing_account_returns_not_found(api):
    """PRD §2.8: "When a path contains a resource identifier, the server validates existence left
    to right and rejects the first missing identifier with the matching not-found error (for
    example `ERR_ORDER_NOT_FOUND`, `ERR_FUSTI_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_MEMBER_NOT_FOUND`, `ERR_WHOLESALE_ACCOUNT_NOT_FOUND`, ...), each carrying HTTP 404."

    Design: Corner/errors/wholesale_account_not_found
    """
    resp = api.decide_wholesale_account(
        "00000000-0000-0000-0000-000000000000",
        {"decision": "APPROVE", "tier": "TIER_1", "expected_wholesale_account_version": 1},
        APPROVER)
    validate_error(resp, ApiErrorId.ERR_WHOLESALE_ACCOUNT_NOT_FOUND.value)
