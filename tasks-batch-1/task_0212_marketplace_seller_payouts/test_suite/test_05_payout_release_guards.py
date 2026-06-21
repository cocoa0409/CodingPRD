"""Payout-release guards: seller-active standing, OCC stale version, segregation
of duties, nothing-to-pay floor, no-verified-method, and the STATE-vs-FISCAL
priority conflict.

Translates queue A (Difficulty) priority_pair_validation_conflict (state/fiscal
instance), boundary_precision_check (empty pool), cross_entity_state_dependency,
and queue B (Corner) errors / rbac / cross_cutting_complexity_layers instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_fee_schedule, create_seller, create_order,
    onboard_active_seller, schedule_payout, current_seller_version,
    seller_with_scheduled_payout, seller_with_matured_order,
    set_clock, advance_clock,
    make_seller_headers, make_reviewer_headers, make_finance_headers,
    create_payout_method_payload, create_payout_payload,
)
from test_helpers import api_client


# ─────────────────────────────────────────────────────────────────────────────
# cross_entity_state_dependency / payout_release_requires_seller_active
#   +  priority_pair_validation_conflict / seller_not_active_outranks_nothing_to_pay
# ─────────────────────────────────────────────────────────────────────────────

def test_release_on_suspended_seller_rejected_seller_not_active(api, reviewer_headers, finance_headers):
    """PRD §3.9: "the seller's `account_status` must be `ACTIVE` (else
    `ERR_SELLER_NOT_ACTIVE`)".
    PRD §2.10: "a payout may be released only while the seller's `account_status` is
    `ACTIVE`. A suspended, onboarding, or closed seller cannot have funds disbursed,
    and an attempted release is rejected with `ERR_SELLER_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/payout_release_requires_seller_active_pair_payout_seller
    """
    seller, order, payout, _pm = seller_with_scheduled_payout(
        gross_amount_cents=10000, settle_iso="2026-06-01T00:00:00Z",
        mature_iso="2026-06-10T00:00:00Z",
    )
    validate_success(api.suspend_seller(seller["id"], reviewer_headers), 200)
    version = current_seller_version(seller["id"])
    res = api.release_payout(
        payout["id"], {"expected_seller_version": version}, make_finance_headers("finance-2")
    )
    validate_error(res, "ERR_SELLER_NOT_ACTIVE", expected_status=409)
    refetched = validate_success(api.get_payout(payout["id"], finance_headers), 200)
    assert refetched["payout_status"] == "SCHEDULED"


def test_release_on_onboarding_seller_rejected_seller_not_active(api, finance_headers):
    """PRD §2.10: "money only leaves the platform for a seller in good standing: a
    payout may be released only while the seller's `account_status` is `ACTIVE`. A
    suspended, onboarding, or closed seller cannot have funds disbursed, and an
    attempted release is rejected with `ERR_SELLER_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/payout_release_requires_seller_active_pair_payout_seller
    """
    # An ONBOARDING seller (never activated) can still have a payout scheduled, but
    # release is gated on the linked Seller.account_status == ACTIVE.
    set_clock("2026-06-15T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    assert seller["account_status"] == "ONBOARDING"
    payout = schedule_payout(seller["id"])
    version = current_seller_version(seller["id"])
    res = api.release_payout(
        payout["id"], {"expected_seller_version": version}, make_finance_headers("finance-2")
    )
    validate_error(res, "ERR_SELLER_NOT_ACTIVE", expected_status=409)
    refetched = validate_success(api.get_payout(payout["id"], finance_headers), 200)
    assert refetched["payout_status"] == "SCHEDULED"


def test_seller_not_active_outranks_nothing_to_pay(api, reviewer_headers, finance_headers):
    """PRD §2.11: "for a payout release, seller-active standing
    (`ERR_SELLER_NOT_ACTIVE`) precedes the stale-version check
    (`ERR_STALE_SELLER_VERSION`), which precedes the nothing-to-pay floor
    (`ERR_NOTHING_TO_PAY`)."

    Design: Difficulty/priority_pair_validation_conflict/seller_not_active_outranks_nothing_to_pay_on_release
    """
    # ACTIVE seller with zero AVAILABLE balance (no matured orders), payout scheduled,
    # then SUSPENDED. Both ERR_SELLER_NOT_ACTIVE and ERR_NOTHING_TO_PAY apply; the
    # higher-priority state check wins.
    set_clock("2026-03-01T00:00:00Z")
    seller, _pm = onboard_active_seller()
    payout = schedule_payout(seller["id"])
    validate_success(api.suspend_seller(seller["id"], reviewer_headers), 200)
    version = current_seller_version(seller["id"])
    res = api.release_payout(
        payout["id"], {"expected_seller_version": version}, make_finance_headers("finance-2")
    )
    validate_error(res, "ERR_SELLER_NOT_ACTIVE", expected_status=409)
    refetched = validate_success(api.get_payout(payout["id"], finance_headers), 200)
    assert refetched["payout_status"] == "SCHEDULED"


def test_active_zero_balance_release_surfaces_lower_priority_nothing_to_pay(api, reviewer_headers, finance_headers):
    """PRD §2.11: "for a payout release, seller-active standing
    (`ERR_SELLER_NOT_ACTIVE`) precedes the stale-version check
    (`ERR_STALE_SELLER_VERSION`), which precedes the nothing-to-pay floor
    (`ERR_NOTHING_TO_PAY`)."

    Design: Difficulty/priority_pair_validation_conflict/seller_not_active_outranks_nothing_to_pay_on_release
    """
    # Same zero-balance payout as the conflict test, but with the seller ACTIVE: the
    # higher-priority active-standing gate no longer fires, so the lower-priority
    # nothing-to-pay floor is the one that surfaces — confirming the precedence.
    set_clock("2026-03-15T00:00:00Z")
    seller, _pm = onboard_active_seller()
    payout = schedule_payout(seller["id"])
    assert seller["account_status"] == "ACTIVE"
    version = current_seller_version(seller["id"])
    res = api.release_payout(
        payout["id"], {"expected_seller_version": version}, make_finance_headers("finance-2")
    )
    validate_error(res, "ERR_NOTHING_TO_PAY", expected_status=422)
    refetched = validate_success(api.get_payout(payout["id"], finance_headers), 200)
    assert refetched["payout_status"] == "SCHEDULED"


# ─────────────────────────────────────────────────────────────────────────────
# boundary_precision_check / payout_release_zero_available_empty_pool_rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_release_with_zero_available_pool_rejected_nothing_to_pay(api, finance_headers):
    """PRD §3.9: "The `gross_available_cents` is the sum of the seller's ledger-entry
    amounts in `AVAILABLE` hold state, already net of any available clawback debits.
    If that pool is not strictly above zero, the release is rejected with
    `ERR_NOTHING_TO_PAY` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/payout_release_zero_available_empty_pool_rejected
    """
    # ACTIVE seller, no matured orders → zero AVAILABLE; payout scheduled.
    set_clock("2026-05-01T00:00:00Z")
    seller, _pm = onboard_active_seller()
    payout = schedule_payout(seller["id"])
    version = current_seller_version(seller["id"])
    res = api.release_payout(
        payout["id"], {"expected_seller_version": version}, make_finance_headers("finance-2")
    )
    validate_error(res, "ERR_NOTHING_TO_PAY", expected_status=422)
    refetched = validate_success(api.get_payout(payout["id"], finance_headers), 200)
    assert refetched["payout_status"] == "SCHEDULED"


def test_release_with_only_pending_proceeds_rejected_nothing_to_pay(api, finance_headers):
    """PRD §3.9: "The `gross_available_cents` is the sum of the seller's ledger-entry
    amounts in `AVAILABLE` hold state ... If that pool is not strictly above zero,
    the release is rejected with `ERR_NOTHING_TO_PAY` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/payout_release_zero_available_empty_pool_rejected
    """
    # An order exists but has not matured, so its proceeds are still PENDING (not
    # AVAILABLE). The AVAILABLE pool is therefore exactly zero → nothing to pay.
    set_clock("2026-05-01T00:00:00Z")
    seller, _pm = onboard_active_seller()
    create_order(seller["id"], gross_amount_cents=10000)  # PENDING, not matured
    payout = schedule_payout(seller["id"])
    version = current_seller_version(seller["id"])
    res = api.release_payout(
        payout["id"], {"expected_seller_version": version}, make_finance_headers("finance-2")
    )
    validate_error(res, "ERR_NOTHING_TO_PAY", expected_status=422)
    refetched = validate_success(api.get_payout(payout["id"], finance_headers), 200)
    assert refetched["payout_status"] == "SCHEDULED"


# ─────────────────────────────────────────────────────────────────────────────
# cross_entity_state_dependency / refund_apply_requires_order_settlement_not_paid
# ─────────────────────────────────────────────────────────────────────────────

def test_refund_apply_on_paid_order_rejected_invalid_state(api, finance_headers):
    """PRD §3.6: "Applying a refund ... requires that ... the order's settlement is
    `PENDING` or `AVAILABLE`."
    PRD §2.11: "Then whether the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/refund_apply_requires_order_settlement_not_paid_pair_refund_order
    """
    # Matured order → released payout → order PAID; then a refund against the PAID order.
    seller, order, payout, _pm = seller_with_scheduled_payout(
        gross_amount_cents=10000, settle_iso="2026-07-01T00:00:00Z",
        mature_iso="2026-07-10T00:00:00Z",
    )
    version = current_seller_version(seller["id"])
    validate_success(
        api.release_payout(payout["id"], {"expected_seller_version": version},
                           make_finance_headers("finance-2")),
        200,
    )
    paid_order = validate_success(api.get_order(order["id"], finance_headers), 200)
    assert paid_order["settlement_status"] == "PAID"
    from test_helpers import create_requested_refund
    refund = create_requested_refund(order["id"], refund_amount_cents=2000)
    res = api.apply_refund(refund["id"], finance_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    still_paid = validate_success(api.get_order(order["id"], finance_headers), 200)
    assert still_paid["settlement_status"] == "PAID"
    assert still_paid["clawback_status"] == "NONE"


def test_refund_apply_on_available_order_permitted(api, finance_headers):
    """PRD §3.6: "Applying a refund ... requires that ... the order's settlement is
    `PENDING` or `AVAILABLE`."
    PRD §3.6: "The order's `clawback_status` moves from `NONE` to `REFUND_CLAWED` ...
    the refund's `refund_status` becomes `APPLIED`".

    Design: Difficulty/cross_entity_state_dependency/refund_apply_requires_order_settlement_not_paid_pair_refund_order
    """
    # The settlement-state dependency admits AVAILABLE: a matured (AVAILABLE, not yet
    # PAID) order accepts the refund, distinguishing it from the rejected PAID case.
    from test_helpers import seller_with_matured_order, create_requested_refund
    seller, order, _pm = seller_with_matured_order(
        gross_amount_cents=10000, settle_iso="2026-07-15T00:00:00Z",
        mature_iso="2026-07-25T00:00:00Z",
    )
    assert order["settlement_status"] == "AVAILABLE"
    refund = create_requested_refund(order["id"], refund_amount_cents=2000)
    applied = validate_success(api.apply_refund(refund["id"], finance_headers), 200)
    assert applied["refund_status"] == "APPLIED"
    refetched = validate_success(api.get_order(order["id"], finance_headers), 200)
    assert refetched["clawback_status"] == "REFUND_CLAWED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / cross_cutting_complexity_layers — OCC stale version
# ─────────────────────────────────────────────────────────────────────────────

def test_occ_stale_seller_version_on_release_returns_412(api, reviewer_headers, finance_headers):
    """PRD §2.9: "A release request must carry `expected_seller_version`, the integer
    `version` of the target seller that the client last observed. If another writer
    has advanced the seller's `version` since the client read it ... then the
    release's view of `available_balance_cents` is stale, and the request is rejected
    with `ERR_STALE_SELLER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_seller_version_on_release_returns_412
    """
    # Two matured orders → available 16260; capture a version, then bump it via a
    # suspend+reinstate cascade so the captured value is stale (current - 1+).
    set_clock("2026-10-01T00:00:00Z")
    seller, _pm = onboard_active_seller()
    sid = seller["id"]
    create_order(sid, gross_amount_cents=10000)
    create_order(sid, gross_amount_cents=10000)
    advance_clock("2026-10-10T00:00:00Z")
    stale_version = current_seller_version(sid)
    payout = schedule_payout(sid)
    # Mutations that advance seller.version after the stale snapshot was taken.
    validate_success(api.suspend_seller(sid, reviewer_headers), 200)
    validate_success(api.reinstate_seller(sid, reviewer_headers), 200)
    res = api.release_payout(
        payout["id"], {"expected_seller_version": stale_version}, make_finance_headers("finance-2")
    )
    validate_error(res, "ERR_STALE_SELLER_VERSION", expected_status=412)
    refetched = validate_success(api.get_payout(payout["id"], finance_headers), 200)
    assert refetched["payout_status"] == "SCHEDULED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / rbac — segregation of duties
# ─────────────────────────────────────────────────────────────────────────────

def test_segregation_of_duties_same_actor_release_rejected(api, finance_headers):
    """PRD §2.10: "the platform records the approving reviewer in `kyc_reviewer_id`
    and refuses a payout release whose acting `X-User-ID` equals that recorded
    reviewer, returning `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "the acting `PlatformFinance` `X-User-ID` must differ from the seller's
    `kyc_reviewer_id` (else `ERR_SEGREGATION_OF_DUTIES`)".

    Design: Corner/rbac/segregation_of_duties_excluded_difficulty_note
    """
    # KYC approved by operator "dual-actor-1"; the same id then attempts the release.
    set_clock("2026-09-01T00:00:00Z")
    seller, order, payout, _pm = seller_with_scheduled_payout(
        gross_amount_cents=10000, settle_iso="2026-09-01T00:00:00Z",
        mature_iso="2026-09-10T00:00:00Z", reviewer_id="dual-actor-1",
    )
    version = current_seller_version(seller["id"])
    res = api.release_payout(
        payout["id"], {"expected_seller_version": version}, make_finance_headers("dual-actor-1")
    )
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
    refetched = validate_success(api.get_payout(payout["id"], finance_headers), 200)
    assert refetched["payout_status"] == "SCHEDULED"
