"""Role-based access control, optimistic concurrency, and immediate consistency.

Queue B (Corner) — sections: rbac, cross_cutting_complexity_layers
(occ_stale_bucket_version_on_order_submit), consistency_model.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiClient, ApiErrorId,
    TEST_USERS, make_investor_headers, make_guardian_headers,
    build_user_headers,
    create_plan, create_portfolio, create_verified_account, register_account,
    open_bucket, create_draft_order,
    create_bucket_payload, create_linked_card_payload, create_order_payload,
    setup_funded_invest_ready, submit_order,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Queue B: rbac ────────────────────────────────────────────────────────
def test_investor_cannot_verify_kyc(api: ApiClient):
    """PRD §3.2: "A `PlatformAdmin` marks an account verified, moving it from
    `PENDING_KYC` to `VERIFIED`; this is permitted only while the account is
    currently `PENDING_KYC`, and it bumps the account version."
    PRD §2.1: "If the headers are present but the declared role is not permitted
    to invoke the endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/investor_cannot_verify_kyc
    """
    plan = create_plan()
    portfolio = create_portfolio()
    acct = register_account(plan["id"], portfolio["id"])
    res = api.verify_kyc(acct["id"], make_investor_headers(acct["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    refetch = validate_success(api.get_account(acct["id"], ADMIN))
    assert refetch["kyc_status"] == "PENDING_KYC"


def test_custodial_guardian_cannot_open_taxable_bucket(api: ApiClient):
    """PRD §3.6: "A `CustodialGuardian` may act only on buckets whose `bucket_type`
    is `UTMA`; a guardian acting on a non-UTMA bucket ... is rejected with
    `ERR_BUCKET_TYPE_NOT_PERMITTED`."

    Design: Corner/rbac/custodial_guardian_cannot_open_taxable_bucket
    """
    plan = create_plan(tier="FAMILY", monthly_fee_cents=900,
                       allows_custodial=True, allows_ira=True)
    portfolio = create_portfolio()
    acct, _, _ = create_verified_account(plan=plan, portfolio=portfolio)
    res = api.create_bucket(
        create_bucket_payload(acct["id"], bucket_type="TAXABLE"),
        make_guardian_headers(acct["id"]),
    )
    validate_error(res, ApiErrorId.ERR_BUCKET_TYPE_NOT_PERMITTED.value)


def test_missing_auth_on_protected_endpoint(api: ApiClient):
    """PRD §2.1: "If the `X-User-Role` header (or, for roles that require it, the
    `X-User-ID` header) is absent on a protected endpoint, the request is rejected
    with `ERR_MISSING_AUTH`."

    Design: Corner/rbac/missing_auth_on_protected_endpoint
    """
    plan = create_plan()
    portfolio = create_portfolio()
    acct = register_account(plan["id"], portfolio["id"])
    # No X-User-Role / X-User-ID headers at all.
    res = api.create_linked_card(
        create_linked_card_payload(acct["id"], last_four="0000", roundup_multiplier=1),
        {"Content-Type": "application/json"},
    )
    validate_error(res, ApiErrorId.ERR_MISSING_AUTH.value)


def test_investor_not_resource_owner_rejected(api: ApiClient):
    """PRD §2.1: "A caller who is otherwise authenticated and role-permitted but
    is acting on an account they do not own is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/investor_not_resource_owner_rejected
    """
    plan = create_plan()
    portfolio = create_portfolio()
    acct_a = register_account(plan["id"], portfolio["id"])
    acct_b = register_account(plan["id"], portfolio["id"])
    # Caller is A (X-User-ID == A.id) but creates a card for B's account.
    res = api.create_linked_card(
        create_linked_card_payload(acct_b["id"], last_four="0000", roundup_multiplier=1),
        make_investor_headers(acct_a["id"]),
    )
    validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ─── Queue B: cross_cutting (OCC) ─────────────────────────────────────────
def test_occ_stale_bucket_version_on_order_submit(api: ApiClient):
    """PRD §2.8: "If the bucket's current `version` has advanced beyond that value
    — because a prior submit, settle, or freeze on the same bucket legitimately
    bumped it — the submit is rejected with `ERR_STALE_VERSION` (HTTP 412),
    preventing the client from acting on a bucket whose state it has not
    observed."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_bucket_version_on_order_submit
    """
    acct, _, _ = create_verified_account()
    inv = make_investor_headers(acct["id"])
    bucket = open_bucket(acct["id"], bucket_type="TAXABLE")
    stale_version = bucket["version"]
    order = create_draft_order(acct["id"], bucket["id"], requested_amount_cents=100)
    # Freeze + unfreeze advance the bucket version twice; stale_version is now behind.
    validate_success(api.freeze_bucket(bucket["id"], ADMIN))
    validate_success(api.unfreeze_bucket(bucket["id"], ADMIN))
    res = api.submit_order(order["id"], {"expected_bucket_version": stale_version}, inv)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)
    refetch = validate_success(api.get_order(order["id"], inv))
    assert refetch["status"] == "DRAFT"


# ─── Queue B: consistency_model ───────────────────────────────────────────
def test_immediate_invest_visible_in_same_response(api: ApiClient):
    """PRD §3.7: "The `management_fee_cents` withheld is the gross multiplied by
    the plan's `management_fee_bps`, divided by 10000, floored. The net principal
    is the gross minus that fee. The order's `settled_amount_cents` is set to the
    net principal."

    Design: Corner/consistency_model/immediate_invest_visible_in_same_response
    """
    acct, bucket = setup_funded_invest_ready(cash_cents=10000, management_fee_bps=25)
    inv = make_investor_headers(acct["id"])
    order = create_draft_order(acct["id"], bucket["id"], order_kind="INVEST",
                               requested_amount_cents=10000)
    submit_order(acct["id"], bucket["id"], order["id"])
    settled = validate_success(api.settle_order(order["id"], ADMIN))
    # The settle response itself carries the computed outcomes (immediate consistency).
    assert settled["status"] == "SETTLED"
    assert settled["settled_amount_cents"] == 9975
    assert settled["management_fee_cents"] == 25
    after = validate_success(api.get_account(acct["id"], inv))
    assert after["cash_balance_cents"] == 0, "full 10000 gross debited"
