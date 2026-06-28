"""Account lifecycle: open, verify, freeze, close, and the parallel
lifecycle_status x contribution_posture state dimensions.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_account, assert_tax_form, ApiErrorId,
    create_account_payload,
    TEST_USERS, make_accountholder_headers,
)
from test_helpers.fixtures import (
    ADMIN, set_clock, create_accountholder, open_account, attest_coverage,
    verify_account, setup_active_account, setup_active_account_with_cash,
    request_distribution, issue_and_activate_card, generate_tax_form,
)

ADMIN_HDR = ADMIN


# ── account_computed_balances_initialized_zero_on_open (Corner/entities) ──────

def test_open_account_balances_initialized_zero(api):
    """PRD §3.2: "At open time the account starts in `lifecycle_status`
    `PENDING_VERIFICATION`; its `contribution_posture` is `LOCKED` until it becomes
    active; `cash_balance_cents`, `invested_balance_cents`, `contributions_ytd_cents`,
    and `applicable_limit_cents` all start at zero; and the platform mints a one-time
    `verification_token`."

    Design: Corner/entities/account_computed_balances_initialized_zero_on_open
    """
    holder = create_accountholder(date_of_birth="1980-02-02")
    res = api.create_account(create_account_payload(holder["id"], plan_year=2026),
                             ADMIN_HDR)
    account = validate_success(res, 201)
    assert_account(account)
    assert account["cash_balance_cents"] == 0
    assert account["invested_balance_cents"] == 0
    assert account["contributions_ytd_cents"] == 0
    assert account["applicable_limit_cents"] == 0
    assert account["lifecycle_status"] == "PENDING_VERIFICATION"


def test_open_account_posture_locked_until_active(api):
    """PRD §3.2: "its `contribution_posture` is `LOCKED` until it becomes active".

    Design: Corner/entities/account_computed_balances_initialized_zero_on_open
    """
    holder = create_accountholder(date_of_birth="1980-02-02")
    account = validate_success(
        api.create_account(create_account_payload(holder["id"], plan_year=2026),
                           ADMIN_HDR), 201)
    assert account["contribution_posture"] == "LOCKED"
    assert isinstance(account["verification_token"], str) and account["verification_token"]


# ── verify_bad_token_returns_invalid_token (Corner/state_machines) ────────────

def test_verify_with_wrong_token_rejected(api):
    """PRD §3.2: "The submitted token must equal the account's stored
    `verification_token`, else the request is rejected with `ERR_INVALID_TOKEN`."

    Design: Corner/state_machines/verify_bad_token_returns_invalid_token
    """
    holder = create_accountholder(date_of_birth="1980-05-05")
    account = open_account(holder["id"], plan_year=2026)
    attest_coverage(account["id"], "SELF_ONLY", 1, 12)
    res = api.verify_account(account["id"], {"verification_token": "wrong-token"},
                             make_accountholder_headers(holder["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_TOKEN)
    after = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert after["lifecycle_status"] == "PENDING_VERIFICATION"


def test_verify_with_wrong_token_keeps_account_pending(api):
    """PRD §3.2: "On success the account moves from `PENDING_VERIFICATION` to `ACTIVE`".

    A wrong-token verify must not advance lifecycle; it stays PENDING_VERIFICATION.

    Design: Corner/state_machines/verify_bad_token_returns_invalid_token
    """
    holder = create_accountholder(date_of_birth="1980-05-05")
    account = open_account(holder["id"], plan_year=2026)
    attest_coverage(account["id"], "FAMILY", 1, 12)
    validate_error(
        api.verify_account(account["id"], {"verification_token": "totally-wrong"},
                           make_accountholder_headers(holder["id"])),
        ApiErrorId.ERR_INVALID_TOKEN)
    after = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert after["lifecycle_status"] == "PENDING_VERIFICATION"
    assert after["contribution_posture"] == "LOCKED"


# ── verify_without_coverage_returns_hdhp_required (Corner/state_machines) ─────

def test_verify_without_coverage_rejected(api):
    """PRD §3.2: "Activation also requires that the account already have at least one
    `ATTESTED` coverage period proving HDHP coverage; if none exists, activation is
    rejected with `ERR_HDHP_REQUIRED`."

    Design: Corner/state_machines/verify_without_coverage_returns_hdhp_required
    """
    holder = create_accountholder(date_of_birth="1980-06-06")
    account = open_account(holder["id"], plan_year=2026)
    res = api.verify_account(account["id"],
                             {"verification_token": account["verification_token"]},
                             make_accountholder_headers(holder["id"]))
    validate_error(res, ApiErrorId.ERR_HDHP_REQUIRED)
    after = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert after["lifecycle_status"] == "PENDING_VERIFICATION"


def test_verify_without_coverage_does_not_activate(api):
    """PRD §3.2: "if none exists, activation is rejected with `ERR_HDHP_REQUIRED`."

    Design: Corner/state_machines/verify_without_coverage_returns_hdhp_required
    """
    holder = create_accountholder(date_of_birth="1980-06-06")
    account = open_account(holder["id"], plan_year=2026)
    validate_error(
        api.verify_account(account["id"],
                           {"verification_token": account["verification_token"]},
                           make_accountholder_headers(holder["id"])),
        ApiErrorId.ERR_HDHP_REQUIRED)
    after = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert after["lifecycle_status"] != "ACTIVE"


# ── verify_already_active_returns_invalid_state (Corner/state_machines) ───────

def test_reverify_active_account_rejected(api):
    """PRD §3.2: "On success the account moves from `PENDING_VERIFICATION` to `ACTIVE`".
    PRD §3.6 (transition framing): an activation attempt from a state other than the
    defined source is rejected with `ERR_INVALID_STATE`.

    Re-verifying an already-ACTIVE account (the PENDING_VERIFICATION->ACTIVE transition
    is not defined from ACTIVE) returns ERR_INVALID_STATE; lifecycle stays ACTIVE.

    Design: Corner/state_machines/verify_already_active_returns_invalid_state
    """
    account, holder = setup_active_account()
    res = api.verify_account(account["id"],
                             {"verification_token": account["verification_token"]},
                             make_accountholder_headers(holder["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert after["lifecycle_status"] == "ACTIVE"


# ── account_parallel_lifecycle_x_posture (Difficulty/non_linear_state_machine) ─

def test_freeze_moves_lifecycle_and_forces_posture_locked(api):
    """PRD §3.2: "An admin may freeze an active account, moving `lifecycle_status` from
    `ACTIVE` to `FROZEN`; this is permitted only from `ACTIVE` (else `ERR_INVALID_STATE`),
    and freezing forces `contribution_posture` to `LOCKED` regardless of whether any
    excess exists."

    Design: Difficulty/non_linear_state_machine/account_parallel_lifecycle_x_posture
    """
    account, holder = setup_active_account()
    assert account["contribution_posture"] == "OPEN"
    assert account["excess_contribution_cents"] == 0
    frozen = validate_success(api.freeze_account(account["id"], ADMIN_HDR), 200)
    assert frozen["lifecycle_status"] == "FROZEN"
    assert frozen["contribution_posture"] == "LOCKED"


def test_freeze_forces_posture_locked_even_with_zero_excess(api):
    """PRD §3.2: "freezing forces `contribution_posture` to `LOCKED` regardless of
    whether any excess exists."

    The two account dimensions move independently: lifecycle ACTIVE->FROZEN AND posture
    OPEN->LOCKED on one freeze, even though excess_contribution_cents stays 0.

    Design: Difficulty/non_linear_state_machine/account_parallel_lifecycle_x_posture
    """
    account, holder = setup_active_account()
    frozen = validate_success(api.freeze_account(account["id"], ADMIN_HDR), 200)
    assert frozen["excess_contribution_cents"] == 0
    assert frozen["lifecycle_status"] == "FROZEN"
    assert frozen["contribution_posture"] == "LOCKED"


# ── contribution_post_requires_account_active_open (Difficulty/cross_entity) ──

def test_post_contribution_on_frozen_account_rejected(api):
    """PRD §3.4: "A post is permitted only when the account's `lifecycle_status` is
    `ACTIVE` (else `ERR_INVALID_STATE`) and the account's `contribution_posture` is
    `OPEN` at post time (else `ERR_POSTURE_LOCKED`)."

    Design: Difficulty/cross_entity_state_dependency/contribution_post_requires_account_active_open
    """
    set_clock("2026-03-01T00:00:00Z")
    account, holder = setup_active_account()
    contrib = validate_success(
        api.create_contribution(account["id"],
                                {"channel": "INDIVIDUAL", "amount_cents": 50000},
                                ADMIN_HDR), 201)
    validate_success(api.freeze_account(account["id"], ADMIN_HDR), 200)
    res = api.post_contribution(account["id"], contrib["id"], ADMIN_HDR)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_post_on_frozen_account_leaves_contribution_pending_and_no_cash(api):
    """PRD §3.4: "On a successful post the contribution moves from `PENDING` to
    `POSTED`, its `posted_at` is stamped from the logical clock, and the account's
    `cash_balance_cents` increases by the contribution's `amount_cents`."

    A post rejected on a FROZEN account must not settle: contribution stays PENDING and
    cash stays 0.

    Design: Difficulty/cross_entity_state_dependency/contribution_post_requires_account_active_open
    """
    set_clock("2026-03-01T00:00:00Z")
    account, holder = setup_active_account()
    contrib = validate_success(
        api.create_contribution(account["id"],
                                {"channel": "INDIVIDUAL", "amount_cents": 50000},
                                ADMIN_HDR), 201)
    validate_success(api.freeze_account(account["id"], ADMIN_HDR), 200)
    validate_error(api.post_contribution(account["id"], contrib["id"], ADMIN_HDR),
                   ApiErrorId.ERR_INVALID_STATE)
    listed, _meta = validate_paginated(api.list_contributions(account["id"], ADMIN_HDR))
    target = next(c for c in listed if c["id"] == contrib["id"])
    assert target["status"] == "PENDING"
    acct = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert acct["cash_balance_cents"] == 0


# ── close_with_open_distribution_returns_open_distribution (Corner) ──────────

def test_close_with_open_distribution_rejected(api):
    """PRD §3.2: "Closing an account is permitted only from `ACTIVE` (else
    `ERR_INVALID_STATE`) and additionally requires that no distribution is in an
    unfinished state — specifically, no distribution may be `REQUESTED`, and no
    distribution may be `CLEARED` while still unsubstantiated; a violation is rejected
    with `ERR_OPEN_DISTRIBUTION`."

    Design: Corner/state_machines/close_with_open_distribution_returns_open_distribution
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=50000)
    request_distribution(account["id"], holder["id"], "REIMBURSEMENT", 20000)
    res = api.close_account(account["id"], ADMIN_HDR)
    validate_error(res, ApiErrorId.ERR_OPEN_DISTRIBUTION)
    after = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert after["lifecycle_status"] == "ACTIVE"


# ── account_close_cascades_active_cards_to_closed (Corner/state_machines) ─────

def test_close_account_cascades_active_card_to_closed(api):
    """PRD §3.2: "A successful close moves the account to `CLOSED`, forces
    `contribution_posture` to `LOCKED`, and cascades every `ACTIVE` debit card on the
    account to `CLOSED`."

    Design: Corner/state_machines/account_close_cascades_active_cards_to_closed
    """
    account, holder = setup_active_account()
    card = issue_and_activate_card(account["id"], holder["id"], "9999")
    assert card["status"] == "ACTIVE"
    closed = validate_success(api.close_account(account["id"], ADMIN_HDR), 200)
    assert closed["lifecycle_status"] == "CLOSED"
    cards = validate_success(api.list_cards(account["id"], ADMIN_HDR), 200)
    target = next(c for c in cards if c["id"] == card["id"])
    assert target["status"] == "CLOSED"


# ── taxform_immutable_no_version_field (Corner/entities) ─────────────────────

def test_taxform_is_immutable_snapshot_no_version(api):
    """PRD §2.4: "A `TaxForm` is an immutable snapshot: it carries only `id` and
    `created_at` and has neither an `updated_at` nor a `version`, because once generated
    it is never updated."

    Design: Corner/entities/taxform_immutable_no_version_field
    """
    account, holder = setup_active_account(coverage_tier="SELF_ONLY")
    res = api.create_tax_form(account["id"],
                              {"form_type": "FORM_5498_SA", "tax_year": 2026}, ADMIN_HDR)
    form = validate_success(res, 201)
    assert_tax_form(form)
    assert form["form_type"] == "FORM_5498_SA"
    assert "version" not in form
    assert "updated_at" not in form
    assert form["gross_amount_cents"] == 0
    assert form["fair_market_value_cents"] == 0
    assert form["nonqualified_amount_cents"] == 0
