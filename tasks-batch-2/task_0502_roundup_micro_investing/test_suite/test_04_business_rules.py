"""Domain business rules: bucket entitlements, beneficiary, referral windows,
hold periods, fiscal sufficiency, IRA cap, temporal overlaps, day collisions,
cross-entity state dependencies, and validation-priority conflicts.

Queue A (Difficulty) — resource_temporal_overlap, cross_entity_state_dependency,
priority_pair_validation_conflict.
Queue B (Corner) — sections: validations, endpoints, errors.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiClient, ApiErrorId,
    TEST_USERS, make_investor_headers, make_guardian_headers,
    create_plan, create_portfolio, create_verified_account, register_account,
    open_bucket, create_draft_order, submit_order,
    create_offer, create_found_money_offer_payload,
    create_found_money_reward_payload, create_bucket_payload,
    create_recurring_contribution_payload, create_order_payload, create_referral_payload,
    issue_referral, redeem_referral, set_clock,
    setup_funded_invest_ready, create_settled_invest_order, fund_account_via_found_money,
)
from test_helpers import api_client as _ac  # noqa

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Queue B: validations ─────────────────────────────────────────────────
def test_utma_bucket_requires_beneficiary(api: ApiClient):
    """PRD §3.6: "A UTMA bucket created without a `beneficiary_name` is rejected
    with `ERR_BENEFICIARY_REQUIRED`."

    Design: Corner/validations/utma_bucket_requires_beneficiary
    """
    plan = create_plan(tier="FAMILY", monthly_fee_cents=900,
                       allows_custodial=True, allows_ira=True)
    portfolio = create_portfolio()
    acct, _, _ = create_verified_account(plan=plan, portfolio=portfolio)
    res = api.create_bucket(
        create_bucket_payload(acct["id"], bucket_type="UTMA"),
        make_guardian_headers(acct["id"]),
    )
    validate_error(res, ApiErrorId.ERR_BENEFICIARY_REQUIRED.value)


def test_ira_bucket_not_allowed_by_lite_plan(api: ApiClient):
    """PRD §3.6: "opening an `IRA` bucket requires the plan to set `allows_ira`; a
    bucket whose type the plan does not permit is rejected with
    `ERR_BUCKET_NOT_ALLOWED_BY_PLAN`."

    Design: Corner/validations/ira_bucket_not_allowed_by_lite_plan
    """
    plan = create_plan(tier="LITE", monthly_fee_cents=300,
                       allows_custodial=False, allows_ira=False)
    portfolio = create_portfolio()
    acct, _, _ = create_verified_account(plan=plan, portfolio=portfolio)
    res = api.create_bucket(
        create_bucket_payload(acct["id"], bucket_type="IRA"),
        make_investor_headers(acct["id"]),
    )
    validate_error(res, ApiErrorId.ERR_BUCKET_NOT_ALLOWED_BY_PLAN.value)


def test_self_referral_rejected(api: ApiClient):
    """PRD §3.11: "A redeemer who is the referrer is rejected with
    `ERR_SELF_REFERRAL`; a redemption attempted after the thirty-day window has
    elapsed is rejected with `ERR_REFERRAL_WINDOW`."

    Design: Corner/validations/self_referral_rejected
    """
    plan = create_plan()
    portfolio = create_portfolio()
    referrer = register_account(plan["id"], portfolio["id"])
    referral = issue_referral(referrer["id"], code="SELF-T")
    res = api.redeem_referral(
        referral["id"], {"referred_account_id": referrer["id"]},
        make_investor_headers(referrer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_SELF_REFERRAL.value)
    refetch = validate_success(api.get_referral(referral["id"], ADMIN))
    assert refetch["status"] == "ISSUED"


def test_found_money_confirm_before_hold_rejected(api: ApiClient):
    """PRD §3.10: "A confirm attempted before `eligible_at` is rejected with
    `ERR_HOLD_PERIOD_ACTIVE`, and one attempted against a non-verified account
    with `ERR_KYC_NOT_VERIFIED`."

    Design: Corner/validations/found_money_confirm_before_hold_rejected
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    offer = create_offer(rebate_mode="FLAT", rebate_flat_cents=500,
                         max_rebate_cents=500, min_spend_cents=0, hold_days=30)
    reward = validate_success(api.create_found_money_reward(
        create_found_money_reward_payload(acct["id"], offer["id"], qualifying_spend_cents=5000),
        inv,
    ), expected_status=201)
    # Clock stays at default 2026-01-01; eligible_at is 2026-01-31.
    res = api.confirm_found_money_reward(reward["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_HOLD_PERIOD_ACTIVE.value)
    refetch = validate_success(api.get_found_money_reward(reward["id"], inv))
    assert refetch["status"] == "PENDING"


# ─── Queue B: endpoints ───────────────────────────────────────────────────
def test_referral_redeem_after_window_rejected(api: ApiClient):
    """PRD §3.11: "a redemption attempted after the thirty-day window has
    elapsed is rejected with `ERR_REFERRAL_WINDOW`."

    Design: Corner/endpoints/referral_redeem_after_window_rejected
    """
    plan = create_plan()
    portfolio = create_portfolio()
    referrer = register_account(plan["id"], portfolio["id"])
    redeemer = register_account(plan["id"], portfolio["id"])
    referral = issue_referral(referrer["id"], code="WIN-T")
    set_clock("2026-03-01T00:00:00Z")  # > created_at + 30d
    res = api.redeem_referral(
        referral["id"], {"referred_account_id": redeemer["id"]},
        make_investor_headers(redeemer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_REFERRAL_WINDOW.value)
    refetch = validate_success(api.get_referral(referral["id"], ADMIN))
    assert refetch["status"] == "ISSUED"


def test_list_orders_filtered_by_bucket(api: ApiClient):
    """PRD §3.12: "Orders are listed filtered by `account_id`, `bucket_id`, `status`,
    and `order_kind`. ... All list endpoints honor the pagination and sort rules
    of §2.3."

    Design: Corner/endpoints/list_orders_filtered_by_bucket
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    bucket = open_bucket(acct["id"], bucket_type="TAXABLE")
    order = create_draft_order(acct["id"], bucket["id"], requested_amount_cents=100)
    res = api.list_orders(inv, params={"bucket_id": bucket["id"]})
    data, meta = validate_paginated(res)
    assert any(o["id"] == order["id"] for o in data), "filtered list contains the order"
    assert "total_count" in meta and "has_more" in meta


# ─── Queue B: errors ──────────────────────────────────────────────────────
def test_insufficient_cash_on_invest_settle(api: ApiClient):
    """PRD §3.7: "For an invest, the account's `cash_balance_cents` must be at
    least the order's `requested_amount_cents`, otherwise `ERR_INSUFFICIENT_CASH`."

    Design: Corner/errors/insufficient_cash_on_invest_settle
    """
    acct, _, _ = create_verified_account()  # cash 0
    bucket = open_bucket(acct["id"], bucket_type="TAXABLE")
    order = create_draft_order(acct["id"], bucket["id"], order_kind="INVEST",
                               requested_amount_cents=5000)
    submit_order(acct["id"], bucket["id"], order["id"])
    res = api.settle_order(order["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_CASH.value)
    refetch = validate_success(api.get_order(order["id"], make_investor_headers(acct["id"])))
    assert refetch["status"] == "SUBMITTED"


def test_duplicate_referral_code_rejected(api: ApiClient):
    """PRD §3.11: "a duplicate `code` is rejected with `ERR_DUPLICATE_TIER`."

    Design: Corner/errors/duplicate_referral_code_rejected
    """
    plan = create_plan()
    portfolio = create_portfolio()
    referrer = register_account(plan["id"], portfolio["id"])
    inv = make_investor_headers(referrer["id"])
    validate_success(api.create_referral(
        create_referral_payload(referrer["id"], "DUP-CODE-1", bonus_cents=1000), inv
    ), expected_status=201)
    res = api.create_referral(
        create_referral_payload(referrer["id"], "DUP-CODE-1", bonus_cents=2000), inv
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_TIER.value)


# ─── Queue A: resource_temporal_overlap ───────────────────────────────────
def test_found_money_offer_window_overlap_rejected(api: ApiClient):
    """PRD §3.1: "A new offer's window must not overlap the window of any
    existing `ACTIVE` offer of the same `brand_name` ... but any genuine overlap is
    rejected with `ERR_OFFER_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/found_money_offer_half_open_window_overlap_same_brand
    """
    base = create_found_money_offer_payload(
        brand_name="ACME-OV", rebate_mode="FLAT", rebate_flat_cents=100,
        max_rebate_cents=100, min_spend_cents=0, hold_days=0,
        active_from="2026-05-01T00:00:00Z", active_until="2026-07-01T00:00:00Z",
    )
    validate_success(api.create_found_money_offer(base, ADMIN), expected_status=201)
    overlapping = create_found_money_offer_payload(
        brand_name="ACME-OV", rebate_mode="FLAT", rebate_flat_cents=100,
        max_rebate_cents=100, min_spend_cents=0, hold_days=0,
        active_from="2026-06-01T00:00:00Z", active_until="2026-08-01T00:00:00Z",
    )
    res = api.create_found_money_offer(overlapping, ADMIN)
    validate_error(res, ApiErrorId.ERR_OFFER_WINDOW_OVERLAP.value)


def test_found_money_offer_boundary_touch_allowed(api: ApiClient):
    """PRD §3.1: "because the interval is half-open, two windows that merely
    touch at a boundary — where one offer's `active_until` equals another's
    `active_from` — do not overlap and are allowed, but any genuine overlap is
    rejected with `ERR_OFFER_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/found_money_offer_half_open_window_overlap_same_brand
    """
    base = create_found_money_offer_payload(
        brand_name="ACME-TOUCH", rebate_mode="FLAT", rebate_flat_cents=100,
        max_rebate_cents=100, min_spend_cents=0, hold_days=0,
        active_from="2026-05-01T00:00:00Z", active_until="2026-07-01T00:00:00Z",
    )
    validate_success(api.create_found_money_offer(base, ADMIN), expected_status=201)
    touching = create_found_money_offer_payload(
        brand_name="ACME-TOUCH", rebate_mode="FLAT", rebate_flat_cents=100,
        max_rebate_cents=100, min_spend_cents=0, hold_days=0,
        active_from="2026-07-01T00:00:00Z", active_until="2026-09-01T00:00:00Z",
    )
    validate_success(api.create_found_money_offer(touching, ADMIN), expected_status=201)


def test_recurring_contribution_buffered_day_collision(api: ApiClient):
    """PRD §3.9: "a new `ACTIVE` contribution's `run_day_index` must not fall within
    a plus-or-minus-one inclusive buffer of any existing `ACTIVE` contribution's
    `run_day_index` on the same account ... and a collision is rejected with
    `ERR_CONTRIBUTION_DAY_COLLISION`."

    Design: Difficulty/resource_temporal_overlap/recurring_contribution_buffered_day_collision
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    validate_success(api.create_recurring_contribution(
        create_recurring_contribution_payload(acct["id"], amount_cents=1000,
                                               cadence="MONTHLY", run_day_index=10), inv
    ), expected_status=201)
    res = api.create_recurring_contribution(
        create_recurring_contribution_payload(acct["id"], amount_cents=2000,
                                               cadence="MONTHLY", run_day_index=11), inv
    )
    validate_error(res, ApiErrorId.ERR_CONTRIBUTION_DAY_COLLISION.value)


def test_recurring_contribution_outside_buffer_allowed(api: ApiClient):
    """PRD §3.9: "the closed buffered interval from one less than to one more
    than an existing day is reserved — and a collision is rejected with
    `ERR_CONTRIBUTION_DAY_COLLISION`."

    Design: Difficulty/resource_temporal_overlap/recurring_contribution_buffered_day_collision
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    validate_success(api.create_recurring_contribution(
        create_recurring_contribution_payload(acct["id"], amount_cents=1000,
                                               cadence="MONTHLY", run_day_index=10), inv
    ), expected_status=201)
    # day 12 is outside [9, 11]: accepted.
    validate_success(api.create_recurring_contribution(
        create_recurring_contribution_payload(acct["id"], amount_cents=2000,
                                               cadence="MONTHLY", run_day_index=12), inv
    ), expected_status=201)


# ─── Queue A: cross_entity_state_dependency ───────────────────────────────
def test_order_submit_requires_bucket_open(api: ApiClient):
    """PRD §3.7: "Submitting an order is an `Investor` or `CustodialGuardian` action
    that moves it from `DRAFT` to `SUBMITTED`. It is permitted only when the order
    is `DRAFT`, the target bucket is `OPEN`, and the owning account is `VERIFIED`;
    a non-verified account here yields `ERR_KYC_NOT_VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_bucket_open
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    bucket = open_bucket(acct["id"], bucket_type="TAXABLE")
    order = create_draft_order(acct["id"], bucket["id"], requested_amount_cents=100)
    validate_success(api.freeze_bucket(bucket["id"], ADMIN))
    frozen = validate_success(api.get_bucket(bucket["id"], inv))
    res = api.submit_order(order["id"], {"expected_bucket_version": frozen["version"]}, inv)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    refetch = validate_success(api.get_order(order["id"], inv))
    assert refetch["status"] == "DRAFT"


def test_order_submit_into_open_bucket_succeeds(api: ApiClient):
    """PRD §3.7: "Submitting an order is an `Investor` or `CustodialGuardian` action
    that moves it from `DRAFT` to `SUBMITTED`. It is permitted only when the order
    is `DRAFT`, the target bucket is `OPEN`, and the owning account is `VERIFIED`;
    a non-verified account here yields `ERR_KYC_NOT_VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_bucket_open
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    bucket = open_bucket(acct["id"], bucket_type="TAXABLE")  # OPEN
    order = create_draft_order(acct["id"], bucket["id"], requested_amount_cents=100)
    fresh = validate_success(api.get_bucket(bucket["id"], inv))
    # Same edge, but the FK-linked bucket is OPEN: the transition is permitted.
    res = api.submit_order(order["id"], {"expected_bucket_version": fresh["version"]}, inv)
    data = validate_success(res)
    assert data["status"] == "SUBMITTED"


def test_referral_qualify_requires_referred_account_invested(api: ApiClient):
    """PRD §3.11: "qualification is permitted only while the referral is
    `REDEEMED` and the referred account's `lifetime_invested_cents` is at least 500
    cents."

    Design: Difficulty/cross_entity_state_dependency/referral_qualify_requires_referred_account_invested
    """
    plan = create_plan()
    portfolio = create_portfolio()
    referrer = register_account(plan["id"], portfolio["id"])
    referred, _, _ = create_verified_account(plan=plan, portfolio=portfolio)
    referral = issue_referral(referrer["id"], code="QUAL-NO-INV")
    redeem_referral(referral["id"], referred["id"])  # referred lifetime_invested == 0
    res = api.qualify_referral(referral["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    refetch = validate_success(api.get_referral(referral["id"], ADMIN))
    assert refetch["status"] == "REDEEMED"


def test_referral_qualify_succeeds_when_referred_account_invested(api: ApiClient):
    """PRD §3.11: "qualification is permitted only while the referral is
    `REDEEMED` and the referred account's `lifetime_invested_cents` is at least 500
    cents."

    Design: Difficulty/cross_entity_state_dependency/referral_qualify_requires_referred_account_invested
    """
    from test_helpers import setup_referred_invested_redeemed
    # Referred B has a settled INVEST of 600 (>= 500); the FK dependency is now satisfied.
    referral, referrer, referred = setup_referred_invested_redeemed(bonus_cents=1000, invest_cents=600)
    data = validate_success(api.qualify_referral(referral["id"], ADMIN))
    assert data["status"] == "QUALIFIED", "qualify succeeds once referred lifetime_invested >= 500"


# ─── Queue A: priority_pair_validation_conflict ───────────────────────────
def test_kyc_gate_beats_insufficient_cash_on_submit(api: ApiClient):
    """PRD §3.7: "It is permitted only when the order is `DRAFT`, the target
    bucket is `OPEN`, and the owning account is `VERIFIED`; a non-verified account
    here yields `ERR_KYC_NOT_VERIFIED`."
    PRD §2.9: "Domain-specific business rules — bucket-type permission, the KYC
    gate, plan entitlements, temporal windows, fiscal sufficiency, and the like —
    are evaluated after these structural guards, and the optimistic-concurrency
    stale-version check sits among them as a state-category guard."

    Design: Difficulty/priority_pair_validation_conflict/kyc_safety_beats_insufficient_cash_fiscal
    """
    plan = create_plan()
    portfolio = create_portfolio()
    acct = register_account(plan["id"], portfolio["id"])  # NOT verified, cash 0
    inv = make_investor_headers(acct["id"])
    bucket = open_bucket(acct["id"], bucket_type="TAXABLE")
    order = create_draft_order(acct["id"], bucket["id"], order_kind="INVEST",
                               requested_amount_cents=100)
    fresh = validate_success(api.get_bucket(bucket["id"], inv))
    # Submit on an unverified account: KYC gate fires at submit; cash is only
    # checked at settle, so the only PRD-consistent outcome here is the KYC error.
    res = api.submit_order(order["id"], {"expected_bucket_version": fresh["version"]}, inv)
    validate_error(res, ApiErrorId.ERR_KYC_NOT_VERIFIED.value)
    refetch = validate_success(api.get_order(order["id"], inv))
    assert refetch["status"] == "DRAFT"


def test_kyc_gate_not_cash_governs_submit_on_verified_zero_cash(api: ApiClient):
    """PRD §3.7: "It is permitted only when the order is `DRAFT`, the target
    bucket is `OPEN`, and the owning account is `VERIFIED`; a non-verified account
    here yields `ERR_KYC_NOT_VERIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/kyc_safety_beats_insufficient_cash_fiscal
    """
    # Verified account with cash 0: submit checks only the KYC gate (not cash),
    # so the transition to SUBMITTED is permitted; cash is examined only at settle.
    acct, _, _ = create_verified_account()  # cash 0
    inv = make_investor_headers(acct["id"])
    bucket = open_bucket(acct["id"], bucket_type="TAXABLE")
    order = create_draft_order(acct["id"], bucket["id"], order_kind="INVEST",
                               requested_amount_cents=100)
    fresh = validate_success(api.get_bucket(bucket["id"], inv))
    data = validate_success(api.submit_order(
        order["id"], {"expected_bucket_version": fresh["version"]}, inv))
    assert data["status"] == "SUBMITTED", "verified account submits despite zero cash"


def test_invalid_state_beats_ira_cap_on_double_settle(api: ApiClient):
    """PRD §2.9: "seventh, that the target resource is in a legal state for the
    requested transition (`ERR_INVALID_STATE`). Domain-specific business rules —
    bucket-type permission, the KYC gate, plan entitlements, temporal windows,
    fiscal sufficiency, and the like — are evaluated after these structural
    guards, and the optimistic-concurrency stale-version check sits among them as
    a state-category guard."
    PRD §3.7: "the running `ytd_ira_contributed_cents` plus this net principal
    must not exceed 700000 cents ... and a settle that would breach the cap is
    rejected with `ERR_IRA_CAP_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_ira_cap_fiscal_on_double_settle
    """
    plan = create_plan(tier="FAMILY", monthly_fee_cents=900,
                       allows_custodial=True, allows_ira=True, management_fee_bps=0)
    portfolio = create_portfolio()
    acct, _, _ = create_verified_account(plan=plan, portfolio=portfolio,
                                         sweep_threshold_cents=99999999)
    fund_account_via_found_money(acct["id"], 700000)
    bucket = open_bucket(acct["id"], bucket_type="IRA")
    order = create_settled_invest_order(acct["id"], bucket["id"], 700000)  # at the cap
    assert order["status"] == "SETTLED"
    # A second settle of the already-SETTLED order: state guard fires before IRA cap.
    res = api.settle_order(order["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    refetch_bucket = validate_success(api.get_bucket(bucket["id"], make_investor_headers(acct["id"])))
    assert refetch_bucket["ytd_ira_contributed_cents"] == 700000, "unchanged by rejected re-settle"


def test_ira_cap_binds_on_fresh_submitted_invest_over_cap(api: ApiClient):
    """PRD §3.7: "the running `ytd_ira_contributed_cents` plus this net principal
    must not exceed 700000 cents (seven thousand dollars), and a settle that
    would breach the cap is rejected with `ERR_IRA_CAP_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_ira_cap_fiscal_on_double_settle
    """
    plan = create_plan(tier="FAMILY", monthly_fee_cents=900,
                       allows_custodial=True, allows_ira=True, management_fee_bps=0)
    portfolio = create_portfolio()
    acct, _, _ = create_verified_account(plan=plan, portfolio=portfolio,
                                         sweep_threshold_cents=99999999)
    inv = make_investor_headers(acct["id"])
    fund_account_via_found_money(acct["id"], 700001)
    bucket = open_bucket(acct["id"], bucket_type="IRA")
    # A single fresh SUBMITTED order whose net principal (700001 @0bps) exceeds the cap:
    # state is legal (SUBMITTED), so the IRA-cap fiscal guard is the one that fires.
    order = create_draft_order(acct["id"], bucket["id"], order_kind="INVEST",
                               requested_amount_cents=700001)
    submit_order(acct["id"], bucket["id"], order["id"])
    res = api.settle_order(order["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_IRA_CAP_EXCEEDED.value)
