"""Validation-priority ordering, temporal-overlap geometry, eligibility-gate-on-pay, RBAC.

Queue A (Difficulty) — priority_pair_validation_conflict / state_beats_fiscal_on_settle_refunded_purchase,
                       priority_pair_validation_conflict / referential_beats_fiscal_on_cross_account_payment,
                       cross_entity_state_dependency / pay_settlement_requires_provider_enrolled,
                       resource_temporal_overlap / provider_promotion_half_open_window_overlap_rejected,
                       resource_temporal_overlap / billing_statement_closed_adjacency_overlap_rejected.
Queue B (Corner)     — rbac (forbidden role, ownership isolation, unauthenticated).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_provider_headers,
    make_patient_headers,
    set_clock,
    create_enrolled_provider,
    create_active_plan,
    create_provider_promotion,
    create_active_account,
    authorize_purchase,
    create_authorized_purchase,
    create_settled_purchase,
    apply_refund,
    open_statement,
)

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


def _settle(api, purchase):
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    return validate_success(api.settle_financed_purchase(
        fp["id"], {"expected_financed_purchase_version": fp["version"]}, ADMIN), 201)


# ──────────── Queue A: state beats fiscal on settle of refunded purchase ────────────
def test_settle_refunded_purchase_returns_invalid_state(api):
    """PRD §2.8: "(6) the target's state admitting the requested transition
    (`ERR_INVALID_STATE`) ... (11) fiscal capacity (`ERR_INSUFFICIENT_CREDIT`) ... A
    failure earlier in this list masks any failure later in it".
    PRD §3.5: "Settling is permitted only from `AUTHORIZED`".

    A settle on an already-REFUNDED (terminal) purchase is caught by the state check
    (priority 6) and returns ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_settle_refunded_purchase
    """
    provider, plan, promotion, account, purchase, settlement = create_settled_purchase(
        principal_cents=100_000)
    apply_refund(provider["id"], purchase["id"], "REFUND", 100_000)
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    assert fp["settlement_status"] == "REFUNDED"
    res = api.settle_financed_purchase(
        fp["id"], {"expected_financed_purchase_version": fp["version"]}, ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_settle_voided_purchase_returns_invalid_state(api):
    """PRD §2.8: "(6) the target's state admitting the requested transition
    (`ERR_INVALID_STATE`)".
    PRD §3.5: "Settling is permitted only from `AUTHORIZED`".

    The same state-precedence rule on the VOID terminal: settling a VOID purchase is
    rejected at the state check, never reaching the fiscal gate.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_settle_refunded_purchase
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=100_000)
    apply_refund(provider["id"], purchase["id"], "VOID", 100_000)
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    assert fp["settlement_status"] == "VOID"
    res = api.settle_financed_purchase(
        fp["id"], {"expected_financed_purchase_version": fp["version"]}, ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ──────────── Queue A: ownership beats fiscal on cross-account payment ────────────
def test_cross_account_payment_returns_not_resource_owner(api):
    """PRD §2.8: "(3) ownership for entity-backed roles (`ERR_NOT_RESOURCE_OWNER`) ... (11)
    fiscal capacity (`ERR_INSUFFICIENT_CREDIT`) ... A failure earlier in this list masks
    any failure later in it".
    PRD §2.1: "When an entity-backed actor targets a resource it does not own, the request
    is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Patient Y paying account X with an over-balance amount is rejected on ownership
    (priority 3) before the fiscal balance check (priority 11).

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_cross_account_payment
    """
    set_clock("2026-01-01T00:00:00Z")
    account_x = create_active_account(requested_limit_cents=500_000)
    account_y = create_active_account(requested_limit_cents=500_000)
    res = api.create_payment(
        {"patient_account_id": account_x["id"], "amount_cents": 999_999,
         "payment_type": "MANUAL"},
        make_patient_headers(account_y["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_cross_account_payment_owner_check_precedes_fiscal_even_with_zero_balance(api):
    """PRD §2.8: "(3) ownership for entity-backed roles (`ERR_NOT_RESOURCE_OWNER`)".
    PRD §2.1: "ownership checks compare a resource's account foreign key to `X-User-ID` —
    a patient may pay, manage autopay, and close only its own account".

    Even when the over-amount would obviously breach the (zero) balance, ownership is the
    reported failure — Patient Y still cannot pay account X.

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_cross_account_payment
    """
    set_clock("2026-01-01T00:00:00Z")
    account_x = create_active_account(requested_limit_cents=500_000)  # zero balance
    account_y = create_active_account(requested_limit_cents=500_000)
    res = api.create_payment(
        {"patient_account_id": account_x["id"], "amount_cents": 1, "payment_type": "MANUAL"},
        make_patient_headers(account_y["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


# ──────────── Queue A: pay settlement requires provider enrolled ────────────
def test_pay_settlement_rejected_when_provider_suspended(api):
    """PRD §3.5: "Paying is permitted only from `PENDING` and only while the provider is
    `ENROLLED`."
    PRD §3.6: "A single compliance gate guards origination, settlement, and payment, and
    when it fails it returns `ERR_ACCOUNT_NOT_ELIGIBLE`."

    Suspending the provider after settlement creation blocks pay with
    ERR_ACCOUNT_NOT_ELIGIBLE.

    Design: Difficulty/cross_entity_state_dependency/pay_settlement_requires_provider_enrolled
    """
    provider, plan, promotion, account, purchase, settlement = create_settled_purchase(
        principal_cents=100_000)
    validate_success(api.suspend_provider(provider["id"], ADMIN), 200)
    res = api.pay_settlement(settlement["id"], ADMIN)
    validate_error(res, "ERR_ACCOUNT_NOT_ELIGIBLE", expected_status=409)


def test_pay_settlement_succeeds_while_provider_enrolled(api):
    """PRD §3.5: "Paying is permitted only from `PENDING` and only while the provider is
    `ENROLLED`. Paying moves the settlement to `PAID`".

    The enrolled-provider side of the same gate: pay succeeds and moves PENDING→PAID.

    Design: Difficulty/cross_entity_state_dependency/pay_settlement_requires_provider_enrolled
    """
    provider, plan, promotion, account, purchase, settlement = create_settled_purchase(
        principal_cents=100_000)
    paid = validate_success(api.pay_settlement(settlement["id"], ADMIN), 200)
    assert paid["status"] == "PAID"


# ──────────── Queue A: provider-promotion half-open overlap ────────────
def test_provider_promotion_overlapping_window_rejected(api):
    """PRD §3.1: "A new enrollment is rejected with `ERR_TEMPORAL_CONFLICT` if its
    half-open window overlaps that of an existing `ACTIVE` enrollment for the same provider
    and the same plan category."

    Existing [2026-01-01,2026-07-01); a new [2026-06-01,2026-12-01) overlaps and is
    rejected.

    Design: Difficulty/resource_temporal_overlap/provider_promotion_half_open_window_overlap_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    provider = create_enrolled_provider(specialty="DERMATOLOGY")
    plan = create_active_plan()
    create_provider_promotion(provider["id"], plan["id"],
                              effective_start="2026-01-01T00:00:00Z",
                              effective_end="2026-07-01T00:00:00Z")
    res = api.create_provider_promotion(
        {"provider_id": provider["id"], "promotional_plan_id": plan["id"],
         "effective_start": "2026-06-01T00:00:00Z", "effective_end": "2026-12-01T00:00:00Z"},
        ADMIN)
    validate_error(res, "ERR_TEMPORAL_CONFLICT", expected_status=409)


def test_provider_promotion_adjacent_window_accepted(api):
    """PRD §3.1: "binds a `provider_id` to a `promotional_plan_id` over a half-open
    effective window running from `effective_start` (inclusive) to `effective_end`
    (exclusive)".
    PRD §3.1: "A new enrollment is rejected with `ERR_TEMPORAL_CONFLICT` if its half-open
    window overlaps that of an existing `ACTIVE` enrollment for the same provider and the
    same plan category."

    A window starting exactly at the prior's exclusive end ([2026-07-01,2027-01-01) after
    [2026-01-01,2026-07-01)) does NOT overlap and is accepted, proving half-open semantics.

    Design: Difficulty/resource_temporal_overlap/provider_promotion_half_open_window_overlap_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    provider = create_enrolled_provider(specialty="DERMATOLOGY")
    plan = create_active_plan()
    create_provider_promotion(provider["id"], plan["id"],
                              effective_start="2026-01-01T00:00:00Z",
                              effective_end="2026-07-01T00:00:00Z")
    res = api.create_provider_promotion(
        {"provider_id": provider["id"], "promotional_plan_id": plan["id"],
         "effective_start": "2026-07-01T00:00:00Z", "effective_end": "2027-01-01T00:00:00Z"},
        ADMIN)
    validate_success(res, 201)


# ──────────── Queue A: billing-statement closed-adjacency overlap ────────────
def test_billing_statement_overlapping_period_rejected(api):
    """PRD §3.7: "A new statement period must be closed-adjacent with no overlap — its
    `period_start` must equal the prior statement's `period_end` plus one day — or the
    cycle operation is rejected with `ERR_TEMPORAL_CONFLICT`."

    Opening [2026-01-15,2026-02-15] while [2026-01-01,2026-01-31] is open overlaps and is
    rejected.

    Design: Difficulty/resource_temporal_overlap/billing_statement_closed_adjacency_overlap_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    account = create_active_account()
    open_statement(account["id"], "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z")
    res = api.open_statement(
        {"patient_account_id": account["id"], "period_start": "2026-01-15T00:00:00Z",
         "period_end": "2026-02-15T00:00:00Z"}, ADMIN)
    validate_error(res, "ERR_TEMPORAL_CONFLICT", expected_status=409)


def test_billing_statement_overlapping_earlier_start_rejected(api):
    """PRD §3.7: "A new statement period must be closed-adjacent with no overlap — its
    `period_start` must equal the prior statement's `period_end` plus one day — or the
    cycle operation is rejected with `ERR_TEMPORAL_CONFLICT`."

    A period that simply repeats the open one ([2026-01-01,2026-01-31] again) is not
    closed-adjacent (does not start at period_end + 1 day) and is rejected.

    Design: Difficulty/resource_temporal_overlap/billing_statement_closed_adjacency_overlap_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    account = create_active_account()
    open_statement(account["id"], "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z")
    res = api.open_statement(
        {"patient_account_id": account["id"], "period_start": "2026-01-01T00:00:00Z",
         "period_end": "2026-01-31T00:00:00Z"}, ADMIN)
    validate_error(res, "ERR_TEMPORAL_CONFLICT", expected_status=409)


# ──────────── Queue B: RBAC ────────────
def test_provider_cannot_settle_purchase(api):
    """PRD §2.1: "A request whose role is recognized but not permitted to invoke the
    targeted operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: the settle route `POST /financed-purchases/{id}/settle` is authorized for
    `PlatformAdmin` only.

    Design: Corner/rbac/provider_cannot_settle_purchase
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=100_000)
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    res = api.settle_financed_purchase(
        fp["id"], {"expected_financed_purchase_version": fp["version"]},
        make_provider_headers(provider["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_patient_cannot_pay_other_patients_account(api):
    """PRD §2.1: "ownership checks compare a resource's account foreign key to `X-User-ID`
    — a patient may pay, manage autopay, and close only its own account ... When an
    entity-backed actor targets a resource it does not own, the request is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/patient_cannot_pay_other_patients_account
    """
    provider, plan, promotion, account_x, purchase = create_authorized_purchase(
        principal_cents=100_000)
    account_y = create_active_account(requested_limit_cents=500_000)
    res = api.create_payment(
        {"patient_account_id": account_x["id"], "amount_cents": 50_000,
         "payment_type": "MANUAL"},
        make_patient_headers(account_y["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits a required header, or whose `X-User-Role` is not one
    of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §4: `POST /providers` is authorized for `PlatformAdmin`.

    The unique-derivable 401 trigger is an omitted-header request (the corner instance's
    `as: Anonymous` would, per PRD §2.1 priority 1, pass the auth gate because `Anonymous`
    IS a declared role, so this test exercises the omitted-header branch the prose pins to
    401).

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.create_provider(
        {"legal_name": "NoAuth", "specialty": "DENTAL", "tax_id": "TX-NA-1",
         "base_merchant_discount_rate": 0.08},
        {})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
