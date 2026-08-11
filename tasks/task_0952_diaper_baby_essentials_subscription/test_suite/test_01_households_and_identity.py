"""Household registration, verification, suspension, closure and the header pair."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_account,
    assert_loyalty_account,
    create_account_payload,
    get_success_data,
    make_account_holder_headers,
    make_raw_headers,
    read_account,
    set_clock,
    setup_allocated_cycle,
    setup_household,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)

ANON = TEST_USERS["anonymous_headers"]
OPS = TEST_USERS["ops_admin_headers"]
SUPPORT = TEST_USERS["support_agent_headers"]


def test_registration_persists_pending_verification_with_minted_system_fields(api):
    """PRD §3.1: "The new `Account` is persisted in `PENDING_VERIFICATION`, the initial
    value of its `status`. The server mints a `verification_token` and returns it on the
    created resource — this is the only time the token is handed out."
    PRD §3.1: "It also mints the account's own shareable `referral_code`, which is what
    *other* people will later present as their `referred_by_code`."
    PRD §2.4: "`version`, an integer that begins at 1 on creation and increments by
    exactly 1 on every mutation of that resource."

    Design: Corner/entities/corner_account_create_returns_pending_verification_and_system_fields
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    resp = api.create_account(
        create_account_payload(email=unique_email("new"), full_name="New One"), ANON
    )
    data = validate_success(resp, 201)
    assert_account(data)
    assert data["status"] == "PENDING_VERIFICATION"
    assert data["version"] == 1, f"a freshly created account starts at version 1, got {data['version']}"
    assert isinstance(data["verification_token"], str) and data["verification_token"]
    assert isinstance(data["referral_code"], str) and data["referral_code"]
    assert isinstance(data["loyalty_account_id"], str) and data["loyalty_account_id"]


def test_registration_defaults_payment_method_false_and_referral_null(api):
    """PRD §3.1: "`payment_method_on_file` is a boolean declaring whether a card is
    stored, and it defaults to false when omitted — a household that never sets it true
    can still be served, but can never be charged a non-zero amount."
    PRD §3.1: "`referred_by_code` carries the referral code of whoever recommended the
    service and defaults to null when the household signed up organically."
    PRD §3.1: "When no such cycle exists the estimate is 0."

    Design: Corner/entities/corner_account_defaults_payment_method_false_and_referred_by_null
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    data = validate_success(
        api.create_account(
            {"email": unique_email("defaults"), "full_name": "Default Household"}, ANON
        ),
        201,
    )
    assert data["payment_method_on_file"] is False
    assert data.get("referred_by_code") is None
    assert data["available_credit_cents"] == 0
    assert data["next_charge_estimate_cents"] == 0


def test_registration_creates_the_companion_bronze_loyalty_wallet(api):
    """PRD §3.1: "Finally it creates a companion loyalty wallet: a `LoyaltyAccount` in
    tier `BRONZE` with a `points_balance` of 0, whose identifier is stored on the account
    as `loyalty_account_id`."
    PRD §3.8: "The wallet's `tier_evaluated_at` records the instant of the evaluation and
    is null until the first one."

    Design: Corner/entities/corner_loyalty_account_auto_created_with_account
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    account = validate_success(
        api.create_account(create_account_payload(email=unique_email("wallet")), ANON), 201
    )
    listed, meta = validate_paginated(
        api.list_loyalty_accounts(OPS, {"account_id": account["id"]})
    )
    assert meta["total_count"] == 1, "exactly one wallet is created with the account"
    assert listed[0]["id"] == account["loyalty_account_id"]
    assert listed[0]["tier"] == "BRONZE"

    wallet = validate_success(
        api.get_loyalty_account(account["loyalty_account_id"], OPS)
    )
    assert_loyalty_account(wallet)
    assert wallet["points_balance"] == 0
    assert wallet["trailing_earned_points"] == 0
    assert wallet.get("tier_evaluated_at") is None


def test_verification_with_a_wrong_token_is_rejected(api):
    """PRD §3.1: "The caller supplies `verification_token`; if it does not equal the value
    stored on the account, the request is rejected with `ERR_INVALID_VERIFICATION_TOKEN`
    (HTTP 422)."

    Design: Corner/state_machines/corner_verify_with_wrong_token_rejected
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    account = validate_success(
        api.create_account(create_account_payload(email=unique_email("badtok")), ANON), 201
    )
    resp = api.verify_account(account["id"], "not-the-real-token", ANON)
    validate_error(resp, ApiErrorId.ERR_INVALID_VERIFICATION_TOKEN.value, 422)

    after = read_account(api, account["id"])
    assert after["status"] == "PENDING_VERIFICATION"


def test_a_consumed_verification_token_cannot_be_replayed(api):
    """PRD §3.1: "On success the account moves `PENDING_VERIFICATION → ACTIVE` and the
    stored `verification_token` is set to null, so the same token can never be replayed."

    Design: Corner/state_machines/corner_verify_twice_cannot_replay_consumed_token
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    account = validate_success(
        api.create_account(create_account_payload(email=unique_email("replay")), ANON), 201
    )
    token = account["verification_token"]
    validate_success(api.verify_account(account["id"], token, ANON))

    resp = api.verify_account(account["id"], token, ANON)
    validate_error(resp, ApiErrorId.ERR_INVALID_VERIFICATION_TOKEN.value, 422)

    after = read_account(api, account["id"])
    assert after["status"] == "ACTIVE"
    assert after.get("verification_token") is None


def test_suspending_an_unverified_account_is_rejected(api):
    """PRD §3.1: "Support operators may suspend and reinstate accounts, and the pair is a
    genuine cycle — an account may be suspended and reinstated repeatedly. Suspension
    requires the account to be `ACTIVE` and carries a `reason`, which is stored on
    `suspended_reason`; the account moves `ACTIVE → SUSPENDED`."
    PRD §3.1: "checks that the owning account's `status` is `ACTIVE` and otherwise returns
    `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/state_machines/corner_suspend_unverified_account_rejected
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    account = validate_success(
        api.create_account(create_account_payload(email=unique_email("unver")), ANON), 201
    )
    resp = api.suspend_account(account["id"], "Too early", SUPPORT)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value, 409)

    after = read_account(api, account["id"])
    assert after["status"] == "PENDING_VERIFICATION"
    assert after.get("suspended_reason") is None


def test_closing_a_household_that_still_holds_an_active_subscription_is_rejected(api):
    """PRD §3.1: "An account may be closed from `ACTIVE` by its own `AccountHolder` or from
    `SUSPENDED` by a `SupportAgent`, and in both directions the precondition is the same:
    no `Subscription` of that account may be in `lifecycle_state` `ACTIVE` or `PAUSED`. An
    account that still has one is refused with `ERR_ACCOUNT_HAS_ACTIVE_SUBSCRIPTIONS`
    (HTTP 409)."

    Design: Corner/state_machines/corner_close_account_holding_active_subscription_rejected
    """
    ctx = setup_household(api, with_sku=False, email_prefix="close1")
    resp = api.close_account(ctx["account_id"], ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_HAS_ACTIVE_SUBSCRIPTIONS.value, 409)

    after = read_account(api, ctx["account_id"])
    assert after["status"] == "ACTIVE"
    child = validate_success(api.get_child(ctx["child"]["id"], ctx["headers"]))
    assert child["archived"] is False


def test_reinstatement_clears_the_reason_and_restores_charging(api):
    """PRD §3.1: "Reinstatement requires the account to be `SUSPENDED`, moves it
    `SUSPENDED → ACTIVE`, and clears `suspended_reason` back to null."
    PRD §3.7: "An `OpsAdmin` charges a cycle whose `payment_status` is `UNCHARGED` and
    whose `status` is `ALLOCATED` or `CUTOFF_LOCKED`; the owning account must be `ACTIVE`."

    Design: Corner/endpoints/corner_reinstate_restores_charging_after_suspension
    """
    ctx, cycle = setup_allocated_cycle(api, email_prefix="reinst")
    suspended = validate_success(
        api.suspend_account(ctx["account_id"], "Fraud review", SUPPORT)
    )
    assert suspended["suspended_reason"] == "Fraud review"
    assert suspended["status"] == "SUSPENDED"

    reinstated = validate_success(api.reinstate_account(ctx["account_id"], SUPPORT))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated.get("suspended_reason") is None

    charged = validate_success(api.charge_cycle(cycle["id"], OPS))
    assert charged["charged_cash_cents"] == 2999
    assert charged["payment_status"] == "CHARGED"


def test_a_request_carrying_neither_identity_header_is_unauthenticated(api):
    """PRD §2.1: "A request that omits `X-User-Role` is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401), as is a request that omits `X-User-ID` while naming
    any role other than `Anonymous` — the anonymous self-registration and verification
    paths are the only two places where a caller has no identity yet."

    Design: Corner/rbac/corner_request_without_role_header_is_unauthenticated
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    account = validate_success(
        api.create_account(create_account_payload(email=unique_email("noauth")), ANON), 201
    )
    resp = api.get_account(account["id"], make_raw_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_an_unrecognised_role_name_is_rejected_as_unknown(api):
    """PRD §2.1: "Six roles exist and their spelling is exact: `Anonymous`,
    `AccountHolder`, `RegistryOwner`, `GiftPurchaser`, `SupportAgent` and `OpsAdmin`."
    PRD §2.1: "A request whose `X-User-Role` is not one of the six names above is rejected
    with `ERR_UNKNOWN_ROLE`, also HTTP 401."

    Design: Corner/rbac/corner_unknown_role_header_value_rejected
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    account = validate_success(
        api.create_account(create_account_payload(email=unique_email("wizard")), ANON), 201
    )
    resp = api.get_account(account["id"], make_raw_headers(account["id"], "Wizard"))
    validate_error(resp, ApiErrorId.ERR_UNKNOWN_ROLE.value, 401)


def test_a_second_registration_reusing_an_address_is_refused(api):
    """PRD §3.1: "The e-mail must contain an at-sign and must be unique across all
    accounts; a second registration reusing an existing address is refused with
    `ERR_DUPLICATE_EMAIL` (HTTP 409)."

    Design: Corner/errors/corner_duplicate_account_email_rejected
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    address = unique_email("dup")
    first = validate_success(
        api.create_account({"email": address, "full_name": "First Household"}, ANON), 201
    )
    resp = api.create_account({"email": address, "full_name": "Second Household"}, ANON)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value, 409)

    listed, meta = validate_paginated(api.list_accounts(OPS, {"email": address}))
    assert meta["total_count"] == 1, "the duplicate registration must not have persisted"
    assert listed[0]["id"] == first["id"]
