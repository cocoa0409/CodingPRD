"""Account registration/reads, funding-source & verification lifecycles, RBAC.

Queue A: resource_temporal_overlap/recipient_verification_live_window_point_overlap.
Queue B: entities (account defaults, missing field, not-found, computed balance,
listing, funding source mint, bad enum, RV immutability, wrong-parent FK),
state_machines (terminal settled cancel, FS verify wrong code, RV confirm after
expiry), calculations (default payout selector), rbac (cross-owner FS, missing auth).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    make_account_holder_headers,
    make_platform_admin_headers,
    create_account,
    make_recipient_verified,
    create_verified_funding_source,
    create_pending_funding_source,
    setup_settled_transfer_pair,
    set_clock,
    seed_credit,
    create_account_payload,
    create_funding_source_payload,
    verify_funding_source_payload,
    create_recipient_verification_payload,
    confirm_recipient_verification_payload,
    assert_account,
    assert_funding_source,
    assert_recipient_verification,
)


# ===========================================================================
# Queue A — resource_temporal_overlap / recipient_verification_live_window_point_overlap
# ===========================================================================
def test_second_pending_verification_in_live_window_rejected(api):
    """PRD §3.2: "Only one live verification may exist per account-and-channel pair:
    starting a new verification for the same `account_id` and `channel` while a
    prior one is still `PENDING` and the current time is before that prior record's
    `expires_at` is rejected with `ERR_VERIFICATION_ALREADY_PENDING`."

    A second EMAIL verification 6h after the first (still inside the 24h live
    window) is rejected.

    Design: Difficulty/resource_temporal_overlap/recipient_verification_live_window_point_overlap
    """
    acct = create_account()
    set_clock("2026-06-01T00:00:00.000Z")
    validate_success(api.create_recipient_verification(
        create_recipient_verification_payload(acct["id"], channel="EMAIL"),
        make_account_holder_headers(acct["id"]),
    ), 201)
    set_clock("2026-06-01T06:00:00.000Z")  # still < expires_at (created + 24h)
    res = api.create_recipient_verification(
        create_recipient_verification_payload(acct["id"], channel="EMAIL"),
        make_account_holder_headers(acct["id"]),
    )
    validate_error(res, ApiErrorId.ERR_VERIFICATION_ALREADY_PENDING.value)


def test_new_verification_allowed_after_prior_window_expires(api):
    """PRD §3.2: "starting a new verification for the same `account_id` and
    `channel` while a prior one is still `PENDING` and the current time is before
    that prior record's `expires_at` is rejected"

    Once the prior record's 24h live window has elapsed, a new EMAIL verification
    for the same account is allowed.

    Design: Difficulty/resource_temporal_overlap/recipient_verification_live_window_point_overlap
    """
    acct = create_account()
    set_clock("2026-06-01T00:00:00.000Z")
    validate_success(api.create_recipient_verification(
        create_recipient_verification_payload(acct["id"], channel="EMAIL"),
        make_account_holder_headers(acct["id"]),
    ), 201)
    set_clock("2026-06-02T01:00:00.000Z")  # > created + 24h, prior window elapsed
    res = api.create_recipient_verification(
        create_recipient_verification_payload(acct["id"], channel="EMAIL"),
        make_account_holder_headers(acct["id"]),
    )
    validate_success(res, 201)


# ===========================================================================
# Queue B — entities
# ===========================================================================
def test_create_account_returns_201_with_defaults(api):
    """PRD §3.1: "On creation the account opens in `ACTIVE` status with both
    `available_balance_cents` and `held_balance_cents` at 0, `risk_score` at 0,
    `risk_tier` at `LOW`, and `is_recipient_verified` false."
    PRD §2.7: "`daily_send_limit_cents` (defaulting to 250000 cents ... and a
    rolling **weekly send ceiling**, `weekly_send_limit_cents` (defaulting to
    1000000 cents"
    PRD §2.4: "an integer `version` that begins at 1 (or 0)"

    POST /accounts yields the documented default field values.

    Design: Corner/entities/create_account_returns_201_with_defaults
    """
    res = api.create_account(create_account_payload(display_name="Fresh"), make_platform_admin_headers())
    acct = validate_success(res, 201)
    assert_account(acct)
    assert acct["status"] == "ACTIVE"
    assert acct["available_balance_cents"] == 0
    assert acct["risk_score"] == 0
    assert acct["risk_tier"] == "LOW"
    assert acct["daily_send_limit_cents"] == 250000
    assert acct["weekly_send_limit_cents"] == 1000000
    assert acct["version"] == 1


def test_create_account_missing_display_name_rejected(api):
    """PRD §3.1: "A new wallet is created by registering an `Account` with an
    `email` and a `display_name`"
    PRD §2.5: "(18) generic request well-formedness, surfacing `ERR_INVALID_REQUEST`"

    Omitting the required display_name is rejected with ERR_INVALID_REQUEST.

    Design: Corner/entities/create_account_missing_display_name_returns_invalid_request
    """
    res = api.create_account({"email": "noname-unique@example.com"}, make_platform_admin_headers())
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_nonexistent_account_returns_not_found(api):
    """PRD §2.5: "(3) existence of every referenced resource, surfacing
    `ERR_NOT_FOUND`"

    GET /accounts/{random-uuid} returns 404 ERR_NOT_FOUND.

    Design: Corner/entities/get_account_nonexistent_returns_not_found
    """
    res = api.get_account(NON_EXISTENT_UUID, make_platform_admin_headers())
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_account_balance_computed_after_seed_credit(api):
    """PRD §2.6: "An account's spendable money, `available_balance_cents`, is
    computed as its settled credits minus its settled debits minus its held funds"
    PRD §3.10: "A ledger-seeding capability credits an account's balance directly to
    simulate an inbound external deposit ... it posts a `CREDIT` ledger entry with
    source kind `ADJUSTMENT`, recomputes the account's `available_balance_cents`"

    After a 7500c seed credit, available_balance_cents reads 7500.

    Design: Corner/entities/account_balance_computed_after_seed_credit
    """
    acct = create_account()
    seed_credit(acct["id"], 7500)
    fetched = validate_success(api.get_account(acct["id"], make_platform_admin_headers()), 200)
    assert fetched["available_balance_cents"] == 7500


def test_list_accounts_pagination_envelope(api):
    """PRD §2.3: "Every list response includes the following fields inside the
    `meta` object: `limit`, `offset`, `total_count`, and `has_more`."

    GET /accounts with limit=1 returns one item with total_count >= 2 and has_more
    true.

    Design: Corner/entities/list_accounts_pagination_envelope
    """
    create_account()
    create_account()
    data, meta = validate_paginated(api.list_accounts(make_platform_admin_headers(), params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True


def test_funding_source_create_mints_micro_deposit_code(api):
    """PRD §3.1: "A newly linked source opens in `PENDING` status, and the server
    mints a four-character `micro_deposit_code` that the holder must later echo
    back."
    PRD §3.1: "exactly that one source has `is_default_payout` true while all
    others are set false." (a brand-new PENDING source is not VERIFIED, so false)

    POST /funding-sources returns PENDING with a non-empty micro_deposit_code and
    is_default_payout false.

    Design: Corner/entities/funding_source_create_mints_micro_deposit_code
    """
    acct = create_account()
    res = api.create_funding_source(
        create_funding_source_payload(acct["id"], kind="DEBIT", last4="9999"),
        make_account_holder_headers(acct["id"]),
    )
    fs = validate_success(res, 201)
    assert_funding_source(fs)
    assert fs["status"] == "PENDING"
    assert fs["is_default_payout"] is False
    assert isinstance(fs["micro_deposit_code"], str) and len(fs["micro_deposit_code"]) > 0


def test_funding_source_bad_enum_kind_rejected(api):
    """PRD §3.1: "the instrument `kind` (either `BANK` or `DEBIT`)"
    PRD §2.5: "(18) generic request well-formedness, surfacing `ERR_INVALID_REQUEST`"

    A kind outside {BANK, DEBIT} is rejected with ERR_INVALID_REQUEST.

    Design: Corner/entities/funding_source_bad_enum_kind_returns_invalid_request
    """
    acct = create_account()
    res = api.create_funding_source(
        create_funding_source_payload(acct["id"], kind="CREDIT", last4="1234"),
        make_account_holder_headers(acct["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_recipient_verification_has_no_version_field(api):
    """PRD §2.4: "A `RecipientVerification` and a `LedgerEntry` each carry only `id`
    and `created_at` — they have no `updated_at` and no `version`"

    A created RecipientVerification opens PENDING and carries no version field.

    Design: Corner/entities/recipient_verification_immutable_no_version_field
    """
    set_clock("2026-06-01T00:00:00.000Z")
    acct = create_account()
    res = api.create_recipient_verification(
        create_recipient_verification_payload(acct["id"], channel="SMS"),
        make_account_holder_headers(acct["id"]),
    )
    rv = validate_success(res, 201)
    assert_recipient_verification(rv)
    assert rv["status"] == "PENDING"
    assert "version" not in rv


def test_funding_source_wrong_parent_account_not_found(api):
    """PRD §2.5: "(3) existence of every referenced resource, surfacing
    `ERR_NOT_FOUND`"
    PRD §3.1: "Creating a `FundingSource` requires the owning `account_id`"

    A funding source referencing a non-existent account_id is rejected 404.

    Design: Corner/entities/funding_source_wrong_parent_account_returns_not_found
    """
    bogus = "00000000-0000-4000-8000-0000000000aa"
    res = api.create_funding_source(
        create_funding_source_payload(bogus, kind="BANK", last4="0000"),
        make_account_holder_headers(bogus),
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Queue B — state_machines
# ===========================================================================
def test_terminal_settled_transfer_cannot_be_cancelled(api):
    """PRD §3.3: "The sending holder may cancel a transfer only while it is in
    `SENT` and `risk_flagged` is false ... `SETTLED` is terminal."
    PRD §2.5: "(6) the target being in a state from which the requested transition
    is defined, surfacing `ERR_INVALID_STATE`"

    Cancelling a SETTLED (terminal) transfer is rejected.

    Design: Corner/state_machines/terminal_settled_transfer_cannot_cancel
    """
    sender, recipient, transfer = setup_settled_transfer_pair(amount_cents=1000, sender_funded=50000)
    assert transfer["status"] == "SETTLED"
    res = api.cancel_transfer(transfer["id"], make_account_holder_headers(sender["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_funding_source_verify_wrong_code_rejected(api):
    """PRD §3.1: "the holder submits a `code`, and the transition succeeds only when
    they own the parent account, the source is still `PENDING`, and the submitted
    `code` exactly equals the stored `micro_deposit_code`; a mismatch is rejected
    with `ERR_VERIFICATION_TOKEN_INVALID`."

    Verifying with a wrong code is rejected and the source stays PENDING.

    Design: Corner/state_machines/funding_source_verify_wrong_code_rejected
    """
    acct = create_account()
    fs, code = create_pending_funding_source(acct["id"], last4="4444")
    bad = "0000" if code != "0000" else "1111"
    res = api.verify_funding_source(fs["id"], verify_funding_source_payload(bad),
                                    make_account_holder_headers(acct["id"]))
    validate_error(res, ApiErrorId.ERR_VERIFICATION_TOKEN_INVALID.value)
    still = validate_success(api.get_funding_source(fs["id"], make_account_holder_headers(acct["id"])), 200)
    assert still["status"] == "PENDING"


def test_recipient_verification_confirm_after_expiry_goes_expired(api):
    """PRD §3.2: "if the submitted token is correct but the current time is at or
    after `expires_at`, the record instead transitions to the terminal `EXPIRED`
    state and the account's `is_recipient_verified` is left unchanged."

    Confirming with the correct token at exactly expires_at yields EXPIRED and
    leaves is_recipient_verified false.

    Design: Corner/state_machines/recipient_verification_confirm_after_expiry_goes_expired
    """
    set_clock("2026-06-01T00:00:00.000Z")
    acct = create_account()
    rv = get_success_data(api.create_recipient_verification(
        create_recipient_verification_payload(acct["id"], channel="EMAIL"),
        make_account_holder_headers(acct["id"]),
    ))
    set_clock("2026-06-02T00:00:00.000Z")  # exactly created + 24h
    res = api.confirm_recipient_verification(
        rv["id"], confirm_recipient_verification_payload(rv["confirm_token"]),
        make_account_holder_headers(acct["id"]),
    )
    confirmed = validate_success(res, 200)
    assert confirmed["status"] == "EXPIRED"
    fetched = validate_success(api.get_account(acct["id"], make_account_holder_headers(acct["id"])), 200)
    assert fetched["is_recipient_verified"] is False


# ===========================================================================
# Queue B — calculations: default payout selector
# ===========================================================================
def test_default_payout_selector_earliest_verified(api):
    """PRD §3.1: "Otherwise the chosen default is the earliest-verified source,
    selected as the minimum by `created_at` ascending — never by `id` — and exactly
    that one source has `is_default_payout` true while all others are set false."

    Of two funding sources verified FS1 then FS2, FS1 (earliest verified) carries
    is_default_payout true and FS2 false.

    Design: Corner/calculations/default_payout_selector_earliest_verified
    """
    acct = create_account()
    fs1 = create_verified_funding_source(acct["id"], last4="7777")
    fs2 = create_verified_funding_source(acct["id"], last4="8888")
    data, _meta = validate_paginated(
        api.list_account_funding_sources(acct["id"], make_account_holder_headers(acct["id"]))
    )
    by_id = {f["id"]: f for f in data}
    assert by_id[fs1["id"]]["is_default_payout"] is True
    assert by_id[fs2["id"]]["is_default_payout"] is False


# ===========================================================================
# Queue B — rbac
# ===========================================================================
def test_account_holder_cannot_act_on_other_holders_funding_source(api):
    """PRD §2.1: "when an `AccountHolder` acts on a transfer, withdrawal, funding
    source, money request, split participation, or dispute, the resource's owning
    `Account.id` must equal `X-User-ID`, or the request is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    AccountHolder B verifying AccountHolder A's funding source is rejected.

    Design: Corner/rbac/account_holder_cannot_act_on_other_holders_funding_source
    """
    a = create_account()
    b = create_account()
    fs, code = create_pending_funding_source(a["id"], last4="1414")
    res = api.verify_funding_source(fs["id"], verify_funding_source_payload(code),
                                    make_account_holder_headers(b["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request that omits either header, or that supplies an
    `X-User-Role` that is not one of the recognized role names, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    A protected GET /accounts/{id} with no auth headers is rejected.

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    acct = create_account()
    res = api.get_account(acct["id"], {})  # no X-User-ID / X-User-Role
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)
