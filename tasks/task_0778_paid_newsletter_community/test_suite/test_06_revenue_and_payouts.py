"""Revenue analytics and payout ledger.

Difficulty (queue A): MRR-forward vs recognized-chronological; per-invoice fee
rounding order; suspended-state beats insufficient-fiscal; money invariant on a
failed payout. Corner (queue B): insufficient balance; settle idempotency; stale
publication version; version increment on payout create.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    new_publication, new_tier, new_paid_subscriber, new_trialing_paid_subscriber,
    setup_publication_with_pro_balance, pub_version, get_pub,
    assert_money_conservation,
)

ADMIN = TEST_USERS["admin_headers"]
CREATOR = TEST_USERS["creator_headers"]


# ---------------------------------------------------------------------------
# Difficulty A2 — forward MRR vs chronological recognized revenue
# ---------------------------------------------------------------------------

def _setup_mrr_scenario(api):
    pub = new_publication(api, platform_fee_bps=1000)
    pro = new_tier(api, pub["id"], tier_rank=2, monthly_price_cents=2500, trial_days=0, name="Pro")
    plus = new_tier(api, pub["id"], tier_rank=1, monthly_price_cents=1000, trial_days=14, name="Plus")
    new_paid_subscriber(api, pub["id"], pro["id"], email="a@x.com", display_name="A")
    new_trialing_paid_subscriber(api, pub["id"], plus["id"], email="b@x.com", display_name="B")
    return pub


def test_mrr_counts_active_and_trialing_full_price(api):
    """PRD §3.9: "The **forward-looking monthly recurring revenue**, `mrr_cents`,
    is the sum of `monthly_price_cents` across every subscription of the
    publication whose status is `ACTIVE` or `TRIALING`; a trialing subscription
    contributes its full tier price even though nothing has been collected yet."

    Design: Difficulty/dual_variant_calc/publication_mrr_forward_vs_recognized_chronological
    """
    pub = _setup_mrr_scenario(api)
    data = validate_success(api.get_analytics(pub["id"], CREATOR), expected_status=200)
    assert data["mrr_cents"] == 3500, f"expected 3500, got {data['mrr_cents']}"


def test_recognized_revenue_counts_only_collected_net(api):
    """PRD §3.9: "The **recognized revenue**, `recognized_revenue_cents`, is
    instead the sum of `creator_net_cents` across every invoice of the
    publication whose `payment_status` is `PAID` and whose `paid_at` is at or
    before the current clock; a trialing subscription that has collected nothing
    contributes zero."

    Design: Difficulty/dual_variant_calc/publication_mrr_forward_vs_recognized_chronological
    """
    pub = _setup_mrr_scenario(api)
    data = validate_success(api.get_analytics(pub["id"], CREATOR), expected_status=200)
    assert data["recognized_revenue_cents"] == 2250, (
        f"expected 2250, got {data['recognized_revenue_cents']}"
    )
    assert data["active_member_count"] == 2


# ---------------------------------------------------------------------------
# Difficulty A4 — per-invoice fee rounding (round-then-sum, not sum-then-fee)
# ---------------------------------------------------------------------------

def _setup_two_1005_paid(api):
    pub = new_publication(api, platform_fee_bps=1000)
    t1 = new_tier(api, pub["id"], tier_rank=1, monthly_price_cents=1005, name="T1")
    t2 = new_tier(api, pub["id"], tier_rank=2, monthly_price_cents=1005, name="T2")
    new_paid_subscriber(api, pub["id"], t1["id"], email="a@x.com", display_name="A")
    new_paid_subscriber(api, pub["id"], t2["id"], email="b@x.com", display_name="B")
    return pub


def test_payout_balance_uses_per_invoice_rounding(api):
    """PRD §2.6: "two invoices of 1005 cents each at 1000 basis points credit
    1808 cents of creator net (each invoice yields a fee of 101 cents rounded
    half up from 100.5, leaving 904 cents, summed to 1808), which differs from
    the 1809 cents a sum-then-fee computation would produce."

    Design: Difficulty/combinatorial_formula/payout_balance_per_invoice_fee_rounding_mode_b
    """
    pub = _setup_two_1005_paid(api)
    data = get_pub(api, pub["id"])
    assert data["payout_balance_cents"] == 1808, (
        f"expected 1808 (per-invoice rounding), got {data['payout_balance_cents']}"
    )


def test_lifetime_net_uses_per_invoice_rounding(api):
    """PRD §2.6: "The rounding order is pinned and consequential: the fee is
    rounded **per invoice** and the resulting creator net is added to the
    publication's running totals one invoice at a time. The system must never sum
    several invoices' amounts and then take a single fee over the sum."

    Design: Difficulty/combinatorial_formula/payout_balance_per_invoice_fee_rounding_mode_b
    """
    pub = _setup_two_1005_paid(api)
    data = get_pub(api, pub["id"])
    assert data["lifetime_net_cents"] == 1808, (
        f"expected 1808 (per-invoice rounding), got {data['lifetime_net_cents']}"
    )


# ---------------------------------------------------------------------------
# Difficulty A9 — suspended state (priority 7) beats insufficient fiscal (12)
# ---------------------------------------------------------------------------

def _suspended_pub_zero_balance(api):
    pub = new_publication(api, platform_fee_bps=1000)
    api.suspend_publication(pub["id"], ADMIN)
    return pub


def test_suspended_publication_beats_insufficient_balance(api):
    """PRD §2.5: "the target resource is in a state that permits the operation,
    and payout creation and subscription (re)activation additionally require the
    owning publication to be `ACTIVE`; otherwise `ERR_INVALID_STATE`,
    `ERR_ALREADY_REGISTERED`, or `ERR_PUBLICATION_SUSPENDED` (409)."
    PRD §2.5: "a later, more specific error must never mask an earlier, more
    fundamental one."

    Design: Difficulty/priority_pair_validation_conflict/payout_suspended_state_beats_insufficient_fiscal
    """
    pub = _suspended_pub_zero_balance(api)
    v = pub_version(api, pub["id"])
    resp = api.create_payout(
        pub["id"], {"amount_cents": 5000, "expected_publication_version": v}, CREATOR
    )
    validate_error(resp, ApiErrorId.ERR_PUBLICATION_SUSPENDED.value)


def test_suspended_payout_precedence_creates_no_payout(api):
    """PRD §2.5: "the checks are evaluated in a fixed priority order, and the
    first failing check determines the returned error."
    PRD §2.5: "**Fiscal** — a payout may not exceed available balance, else
    `ERR_INSUFFICIENT_BALANCE` (402)."

    Design: Difficulty/priority_pair_validation_conflict/payout_suspended_state_beats_insufficient_fiscal
    """
    pub = _suspended_pub_zero_balance(api)
    v = pub_version(api, pub["id"])
    resp = api.create_payout(
        pub["id"], {"amount_cents": 5000, "expected_publication_version": v}, CREATOR
    )
    err = validate_error(resp, ApiErrorId.ERR_PUBLICATION_SUSPENDED.value)
    assert err["error_id"] != ApiErrorId.ERR_INSUFFICIENT_BALANCE.value
    payouts, _meta = validate_paginated(api.list_payouts(pub["id"], CREATOR))
    assert payouts == [], "a rejected payout request must not persist a payout"


# ---------------------------------------------------------------------------
# Difficulty A17 — money invariant: failed payout restores balance
# ---------------------------------------------------------------------------

def _request_then_fail_payout(api):
    bundle = setup_publication_with_pro_balance(api)  # payout_balance 2250
    pub_id = bundle["pub_id"]
    v = pub_version(api, pub_id)
    payout = validate_success(
        api.create_payout(pub_id, {"amount_cents": 2250, "expected_publication_version": v}, CREATOR),
        expected_status=201,
    )
    api.settle_payout(payout["id"], {"outcome": "FAILED"}, ADMIN)
    return pub_id


def test_failed_payout_releases_hold_to_balance(api):
    """PRD §2.7: "When a payout settles as failed, `pending_payout_cents`
    decreases and `payout_balance_cents` increases by the amount, releasing the
    held funds back to available balance."

    Design: Difficulty/compensating_invariant/money_invariant_payout_fail_restores_balance
    """
    pub_id = _request_then_fail_payout(api)
    pub = get_pub(api, pub_id)
    assert pub["payout_balance_cents"] == 2250
    assert pub["pending_payout_cents"] == 0


def test_failed_payout_conserves_ledger_invariant(api):
    """PRD §2.7: "At all times the sum of `payout_balance_cents`,
    `pending_payout_cents`, and `lifetime_paid_out_cents` equals
    `lifetime_net_cents`."

    Design: Difficulty/compensating_invariant/money_invariant_payout_fail_restores_balance
    """
    pub_id = _request_then_fail_payout(api)
    pub = get_pub(api, pub_id)
    assert pub["lifetime_paid_out_cents"] == 0
    assert pub["lifetime_net_cents"] == 2250
    assert_money_conservation(pub)


# ---------------------------------------------------------------------------
# Corner — insufficient balance
# ---------------------------------------------------------------------------

def test_payout_insufficient_balance_rejected(api):
    """PRD §3.9: "A creator withdraws earnings by requesting a **payout** for an
    `amount_cents`, which must be positive and must not exceed the publication's
    `payout_balance_cents`; an over-draw is rejected with
    `ERR_INSUFFICIENT_BALANCE`."

    Design: Corner/validations/payout_insufficient_balance_returns_402
    """
    pub = new_publication(api, platform_fee_bps=1000)
    v = pub_version(api, pub["id"])
    resp = api.create_payout(
        pub["id"], {"amount_cents": 100, "expected_publication_version": v}, CREATOR
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value)


# ---------------------------------------------------------------------------
# Corner — settle an already-PAID payout (idempotency lockdown)
# ---------------------------------------------------------------------------

def test_settle_already_paid_payout_rejected(api):
    """PRD §3.9: "Settling as paid moves the payout from `REQUESTED` to the
    terminal `PAID`, decreases `pending_payout_cents` and increases
    `lifetime_paid_out_cents` by the payout's `amount_cents`, and stamps
    `settled_at`."
    PRD §2.5: "the target resource is in a state that permits the operation ...
    otherwise `ERR_INVALID_STATE` ... (409)."

    Design: Corner/state_machines/settle_already_paid_payout_idempotency_rejected
    """
    bundle = setup_publication_with_pro_balance(api)
    pub_id = bundle["pub_id"]
    v = pub_version(api, pub_id)
    payout = validate_success(
        api.create_payout(pub_id, {"amount_cents": 2250, "expected_publication_version": v}, CREATOR),
        expected_status=201,
    )
    api.settle_payout(payout["id"], {"outcome": "PAID"}, ADMIN)
    resp = api.settle_payout(payout["id"], {"outcome": "PAID"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    pub = get_pub(api, pub_id)
    assert pub["lifetime_paid_out_cents"] == 2250, "balances must not be double-moved"


# ---------------------------------------------------------------------------
# Corner — stale publication version on payout create (OCC)
# ---------------------------------------------------------------------------

def test_payout_create_stale_publication_version_rejected(api):
    """PRD §2.8: "If this value does not match the target publication's current
    `version` — because another payout or a refund has already moved the balance
    since the client last read the publication — the request is rejected with
    `ERR_STALE_PUBLICATION_VERSION` (HTTP 412) ... A successful payout request
    increments the publication's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/payout_create_stale_publication_version_rejected
    """
    bundle = setup_publication_with_pro_balance(api)
    pub_id = bundle["pub_id"]
    stale_v = pub_version(api, pub_id)
    validate_success(
        api.create_payout(pub_id, {"amount_cents": 1000, "expected_publication_version": stale_v}, CREATOR),
        expected_status=201,
    )
    resp = api.create_payout(
        pub_id, {"amount_cents": 1000, "expected_publication_version": stale_v}, CREATOR
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PUBLICATION_VERSION.value)


# ---------------------------------------------------------------------------
# Corner — publication version increments on payout create
# ---------------------------------------------------------------------------

def test_publication_version_increments_on_payout_create(api):
    """PRD §2.8: "A successful payout request increments the publication's
    `version` by one."
    PRD §3.9: "A successful request creates a payout in `REQUESTED`, moves the
    requested amount out of `payout_balance_cents` and into `pending_payout_cents`
    ..."

    Design: Corner/cross_cutting_complexity_layers/publication_version_increments_on_payout_create
    """
    bundle = setup_publication_with_pro_balance(api)
    pub_id = bundle["pub_id"]
    before = pub_version(api, pub_id)
    validate_success(
        api.create_payout(pub_id, {"amount_cents": 1000, "expected_publication_version": before}, CREATOR),
        expected_status=201,
    )
    pub = get_pub(api, pub_id)
    assert pub["version"] == before + 1
    assert pub["pending_payout_cents"] == 1000
    assert pub["payout_balance_cents"] == 1250
