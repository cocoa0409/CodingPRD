"""Financed-purchase authorization, eligibility/fiscal/temporal gates, and OCC.

Queue A (Difficulty) — cross_entity_state_dependency / authorize_requires_provider_enrolled_and_account_active.
Queue B (Corner)     — validations (temporal, insufficient credit, defaulted, duplicate
                       autopay, draft-day range), state_machines (close, void), errors,
                       cross_cutting_complexity_layers (OCC).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    create_financed_purchase_payload,
    create_autopay_enrollment_payload,
    TEST_USERS,
    make_provider_headers,
    make_patient_headers,
    set_clock,
    create_enrolled_provider,
    create_active_plan,
    create_provider_promotion,
    create_active_account,
    setup_provider_plan_promotion,
    setup_full_origination_context,
    authorize_purchase,
    create_authorized_purchase,
    setup_defaulted_account,
)

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ──────────────── Queue A: cross_entity_state_dependency ────────────────
def test_authorize_rejected_when_provider_suspended(api):
    """PRD §3.6: "To originate a new purchase the provider must be `ENROLLED` and the
    account must be `ACTIVE`."
    PRD §3.6: "A single compliance gate guards origination, settlement, and payment, and
    when it fails it returns `ERR_ACCOUNT_NOT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/authorize_requires_provider_enrolled_and_account_active
    """
    set_clock("2026-01-01T00:00:00Z")
    provider, plan, promotion = setup_provider_plan_promotion()
    account = create_active_account()
    validate_success(api.suspend_provider(provider["id"], ADMIN), 200)

    acct = validate_success(api.get_account(account["id"], ADMIN), 200)
    res = api.create_financed_purchase(
        create_financed_purchase_payload(
            provider["id"], account["id"], promotion["id"], 100_000,
            expected_patient_account_version=acct["version"]),
        make_provider_headers(provider["id"]))
    validate_error(res, "ERR_ACCOUNT_NOT_ELIGIBLE", expected_status=409)


def test_authorize_succeeds_when_provider_enrolled_and_account_active(api):
    """PRD §3.6: "To originate a new purchase the provider must be `ENROLLED` and the
    account must be `ACTIVE`."
    PRD §3.3: "On success the purchase is created on two independent state axes carried
    in two separate fields: its settlement axis, held in `settlement_status`, starts
    `AUTHORIZED`, and its promotional axis, held in `promo_status`, starts `DEFERRED`."

    Design: Difficulty/cross_entity_state_dependency/authorize_requires_provider_enrolled_and_account_active
    """
    set_clock("2026-01-01T00:00:00Z")
    provider, plan, promotion, account = setup_full_origination_context()
    acct = validate_success(api.get_account(account["id"], ADMIN), 200)
    res = api.create_financed_purchase(
        create_financed_purchase_payload(
            provider["id"], account["id"], promotion["id"], 100_000,
            expected_patient_account_version=acct["version"]),
        make_provider_headers(provider["id"]))
    purchase = validate_success(res, 201)
    assert purchase["settlement_status"] == "AUTHORIZED"
    assert purchase["promo_status"] == "DEFERRED"


# ──────────────── Queue B: validations ────────────────
def test_authorize_outside_promo_window_returns_temporal_conflict(api):
    """PRD §3.3: "The authorization clock must fall within the enrollment's half-open
    effective window, at or after `effective_start` and strictly before `effective_end`;
    otherwise the request is rejected with `ERR_TEMPORAL_CONFLICT`."

    Design: Corner/validations/authorize_outside_promo_window_returns_temporal_conflict
    """
    set_clock("2026-01-01T00:00:00Z")
    provider = create_enrolled_provider()
    plan = create_active_plan()
    promotion = create_provider_promotion(
        provider["id"], plan["id"],
        effective_start="2026-06-01T00:00:00Z", effective_end="2026-12-01T00:00:00Z")
    account = create_active_account()
    acct = validate_success(api.get_account(account["id"], ADMIN), 200)
    res = api.create_financed_purchase(
        create_financed_purchase_payload(
            provider["id"], account["id"], promotion["id"], 100_000,
            expected_patient_account_version=acct["version"]),
        make_provider_headers(provider["id"]))
    validate_error(res, "ERR_TEMPORAL_CONFLICT", expected_status=409)


def test_authorize_exceeding_available_credit_returns_insufficient(api):
    """PRD §3.3: "the principal must not exceed the account's `available_credit_cents` or
    the request is rejected with `ERR_INSUFFICIENT_CREDIT`."

    Design: Corner/validations/authorize_exceeding_available_credit_returns_insufficient
    """
    set_clock("2026-01-01T00:00:00Z")
    provider, plan, promotion, account = setup_full_origination_context(
        requested_limit_cents=500_000)
    acct = validate_success(api.get_account(account["id"], ADMIN), 200)
    res = api.create_financed_purchase(
        create_financed_purchase_payload(
            provider["id"], account["id"], promotion["id"], 600_000,
            expected_patient_account_version=acct["version"]),
        make_provider_headers(provider["id"]))
    validate_error(res, "ERR_INSUFFICIENT_CREDIT", expected_status=409)


def test_defaulted_account_rejects_new_purchase(api):
    """PRD §3.6: "A `DEFAULTED` or `CLOSED` account may not be debited at all, and a
    `DEFAULTED` account rejects new purchases and every payment other than a `PAYOFF`."

    Design: Corner/validations/defaulted_account_rejects_new_purchase
    """
    provider, plan, promotion, account, purchase, _ = setup_defaulted_account()
    acct = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert acct["status"] == "DEFAULTED"
    res = api.create_financed_purchase(
        create_financed_purchase_payload(
            provider["id"], account["id"], promotion["id"], 100_000,
            expected_patient_account_version=acct["version"]),
        make_provider_headers(provider["id"]))
    validate_error(res, "ERR_ACCOUNT_NOT_ELIGIBLE", expected_status=409)


def test_duplicate_active_autopay_returns_duplicate_resource(api):
    """PRD §3.10: "At most one `ACTIVE` autopay enrollment may exist per account; a
    second one is rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/duplicate_active_autopay_returns_duplicate_resource
    """
    set_clock("2026-01-01T00:00:00Z")
    account = create_active_account()
    validate_success(api.create_autopay_enrollment(
        create_autopay_enrollment_payload(account["id"], funding_token="tok-ap-1",
                                          draft_day_of_month=5),
        make_patient_headers(account["id"])), 201)
    res = api.create_autopay_enrollment(
        create_autopay_enrollment_payload(account["id"], funding_token="tok-ap-2",
                                          draft_day_of_month=6),
        make_patient_headers(account["id"]))
    validate_error(res, "ERR_DUPLICATE_RESOURCE", expected_status=409)


def test_autopay_invalid_draft_day_returns_validation_amount(api):
    """PRD §2.8: "range checks on individual numeric fields are surfaced as
    `ERR_VALIDATION_AMOUNT` (HTTP 422): ... or a `draft_day_of_month` outside the
    inclusive range from 1 through 28."

    Design: Corner/validations/autopay_invalid_draft_day_returns_validation_amount
    """
    set_clock("2026-01-01T00:00:00Z")
    account = create_active_account()
    res = api.create_autopay_enrollment(
        create_autopay_enrollment_payload(account["id"], funding_token="tok-dd",
                                          draft_day_of_month=31),
        make_patient_headers(account["id"]))
    validate_error(res, "ERR_VALIDATION_AMOUNT", expected_status=422)


# ──────────────── Queue B: state machines (account close, void) ────────────────
def test_close_account_with_nonzero_balance_returns_invalid_state(api):
    """PRD §3.10: "Closing is permitted only from `ACTIVE`, only when the account's
    `current_balance_cents` is zero, and only when no `FinancedPurchase` on the account
    is still in `AUTHORIZED` settlement status. ... A request that violates any of these
    preconditions is rejected as an invalid transition with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/close_account_with_nonzero_balance_returns_invalid_state
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=100_000)
    res = api.close_account(account["id"], make_patient_headers(account["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert after["status"] == "ACTIVE"


def test_void_pre_settlement_restores_credit_and_balance(api):
    """PRD §3.9: "A `VOID` is the pre-settlement compensation and is allowed only while
    the purchase is still `AUTHORIZED`".
    PRD §3.9: "The void restores the account's `available_credit_cents` by the full
    `principal_cents` (upholding credit conservation) and decrements the account's
    `current_balance_cents` by the purchase's unpaid principal — its `principal_cents`
    minus its `principal_paid_cents`."

    Design: Corner/state_machines/void_pre_settlement_restores_credit_and_balance
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=100_000, requested_limit_cents=500_000)
    res = api.create_refund(
        {"financed_purchase_id": purchase["id"], "refund_kind": "VOID",
         "amount_cents": 100_000},
        make_provider_headers(provider["id"]))
    validate_success(res, 201)
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    assert fp["settlement_status"] == "VOID"
    acct = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert acct["available_credit_cents"] == 500_000
    assert acct["current_balance_cents"] == 0


def test_void_post_settlement_purchase_rejected(api):
    """PRD §3.9: "A `VOID` is the pre-settlement compensation and is allowed only while
    the purchase is still `AUTHORIZED` ... A refund whose kind does not match the
    purchase's current settlement state is rejected as an invalid transition with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/void_post_settlement_purchase_rejected
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=100_000)
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    validate_success(api.settle_financed_purchase(
        fp["id"], {"expected_financed_purchase_version": fp["version"]}, ADMIN), 201)
    res = api.create_refund(
        {"financed_purchase_id": purchase["id"], "refund_kind": "VOID",
         "amount_cents": 100_000},
        make_provider_headers(provider["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_refund_amount_not_equal_principal_returns_referential_mismatch(api):
    """PRD §3.9: "Only full compensation is allowed: the `amount_cents` must equal the
    purchase's `principal_cents`, and an amount that does not match is rejected with
    `ERR_REFERENTIAL_MISMATCH`."

    Design: Corner/validations/refund_amount_not_equal_principal_returns_referential_mismatch
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=100_000)
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    validate_success(api.settle_financed_purchase(
        fp["id"], {"expected_financed_purchase_version": fp["version"]}, ADMIN), 201)
    res = api.create_refund(
        {"financed_purchase_id": purchase["id"], "refund_kind": "REFUND",
         "amount_cents": 50_000},
        make_provider_headers(provider["id"]))
    validate_error(res, "ERR_REFERENTIAL_MISMATCH", expected_status=409)


# ──────────────── Queue B: OCC cross-cutting ────────────────
def test_occ_stale_account_version_on_authorize(api):
    """PRD §2.7: "The request body must include `expected_patient_account_version`,
    carrying the client's last observed `version` of the target `PatientAccount`. If that
    value does not equal the account's current `version`, the authorization is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_account_version_on_authorize
    """
    set_clock("2026-01-01T00:00:00Z")
    provider, plan, promotion, account = setup_full_origination_context(
        requested_limit_cents=500_000)
    v0 = validate_success(api.get_account(account["id"], ADMIN), 200)["version"]
    # First authorize consumes credit and bumps the account version.
    validate_success(api.create_financed_purchase(
        create_financed_purchase_payload(
            provider["id"], account["id"], promotion["id"], 100_000,
            expected_patient_account_version=v0),
        make_provider_headers(provider["id"])), 201)
    # Second authorize still carrying the now-stale v0 is rejected.
    res = api.create_financed_purchase(
        create_financed_purchase_payload(
            provider["id"], account["id"], promotion["id"], 100_000,
            expected_patient_account_version=v0),
        make_provider_headers(provider["id"]))
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_occ_correct_purchase_version_settle_succeeds(api):
    """PRD §2.7: "The settle request body must include
    `expected_financed_purchase_version`, carrying the client's last observed `version`
    of the target `FinancedPurchase`."
    PRD §3.5: "The settle transition sets the purchase's settlement axis to `SETTLED` and
    bumps the purchase's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_purchase_version_settle_succeeds
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=100_000)
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    settle_res = api.settle_financed_purchase(
        fp["id"], {"expected_financed_purchase_version": fp["version"]}, ADMIN)
    validate_success(settle_res, 201)
    after = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    assert after["settlement_status"] == "SETTLED"
    assert after["version"] > fp["version"]
