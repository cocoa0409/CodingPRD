"""Cardholder and Account intake — PRD §3.1.

Coverage:
- POST /cardholders returns a Cardholder with PRD §2.4 common fields.
- Email uniqueness -> ERR_VALIDATION.
- POST /accounts seeds the deterministic field set described in PRD §3.1.
- Account fetch returns the live snapshot.
- Cardholder ownership: a Cardholder can read their own account.
- Cardholder cannot read another cardholder's account -> ERR_FORBIDDEN.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    SIGNUP_WINDOW_DAYS,
    assert_account,
    assert_cardholder,
    create_account_payload,
    create_cardholder,
    create_cardholder_and_account,
    create_cardholder_payload,
    make_cardholder_headers,
    open_account,
    parse_iso,
    setup_clock_at,
    validate_error,
    validate_success,
)


# ===========================================================================
# Cardholder CRUD — PRD §3.1
# ===========================================================================
class TestCardholderCreation:
    """PRD §3.1 + PRD §2.4 common fields."""

    def test_create_cardholder_returns_full_entity(self, api, admin_headers):
        """PRD §3.1: "A PlatformAdmin provisions a Cardholder by
        supplying the cardholder's email (a lowercase, unique RFC 5322
        address used for login lookup) and display_name (the
        human-readable name printed on receipts and statements)."

        Claim: POST /cardholders returns the persisted entity with
        email, display_name, and PRD §2.4 common fields.
        """
        resp = api.create_cardholder(
            create_cardholder_payload(
                email="alice@example.test", display_name="Alice",
            ),
            admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_cardholder(data)
        assert data["email"] == "alice@example.test"
        assert data["display_name"] == "Alice"
        # PRD §2.4: "an integer version that starts at 1 on creation".
        assert data["version"] == 1

    def test_duplicate_email_rejected(self, api, admin_headers):
        """PRD §3.1: "Email uniqueness is enforced at creation; a
        duplicate is rejected with ERR_VALIDATION."

        Claim: a second POST /cardholders with the same email returns
        ERR_VALIDATION.
        """
        resp_a = api.create_cardholder(
            create_cardholder_payload(email="dup@example.test"),
            admin_headers,
        )
        validate_success(resp_a, expected_status=201)
        resp_b = api.create_cardholder(
            create_cardholder_payload(email="dup@example.test"),
            admin_headers,
        )
        validate_error(resp_b, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Account open — PRD §3.1
# ===========================================================================
class TestAccountOpen:
    """PRD §3.1 deterministic seeding."""

    def test_open_account_seeds_deterministic_state(
        self, api, admin_headers,
    ):
        """PRD §3.1: "Account creation is a deterministic act: the
        server mints opened_at from its current logical clock, sets
        signup_bonus_deadline_at to exactly ninety days after opened_at,
        seeds signup_bonus_state to PENDING, seeds
        signup_bonus_qualifying_spend_cents to zero, seeds
        points_balance and ytd_qualifying_spend_cents to zero, seeds
        spending_tier to STANDARD, seeds lifecycle_state to ACTIVE, and
        primes last_qualifying_activity_at to the same value as
        opened_at so that the expiration clock is anchored from day
        one."

        Claim: every named field is seeded to the stated value.
        """
        setup_clock_at(2026, 1, 2)
        ch = create_cardholder()
        resp = api.create_account(
            create_account_payload(cardholder_id=ch["id"]),
            admin_headers,
        )
        acc = validate_success(resp, expected_status=201)
        assert_account(acc)
        assert acc["cardholder_id"] == ch["id"]
        assert acc["lifecycle_state"] == "ACTIVE"
        assert acc["spending_tier"] == "STANDARD"
        assert acc["signup_bonus_state"] == "PENDING"
        assert acc["signup_bonus_qualifying_spend_cents"] == 0
        assert acc["points_balance"] == 0
        assert acc["ytd_qualifying_spend_cents"] == 0
        assert acc["last_qualifying_activity_at"] == acc["opened_at"]

    def test_signup_bonus_deadline_is_ninety_days_after_opened_at(
        self, api, admin_headers,
    ):
        """PRD §3.1: "sets signup_bonus_deadline_at to exactly ninety
        days after opened_at".
        PRD §2.12: "signup_bonus_deadline_at is precisely 90 days after
        opened_at".

        Claim: signup_bonus_deadline_at - opened_at == 90 days.
        """
        setup_clock_at(2026, 1, 2)
        _ch, acc = create_cardholder_and_account()
        opened = parse_iso(acc["opened_at"])
        deadline = parse_iso(acc["signup_bonus_deadline_at"])
        delta = deadline - opened
        assert delta.days == SIGNUP_WINDOW_DAYS, (
            f"signup_bonus_deadline_at must be {SIGNUP_WINDOW_DAYS} days "
            f"after opened_at, got {delta.days} days"
        )

    def test_account_version_starts_at_one(self, api, admin_headers):
        """PRD §2.4: "an integer version that starts at 1 on creation
        and increments by one with every mutation".

        Claim: a freshly-opened account has version == 1.
        """
        setup_clock_at(2026, 1, 2)
        _ch, acc = create_cardholder_and_account()
        assert acc["version"] == 1

    def test_open_account_with_missing_cardholder_returns_reference_not_found(
        self, api, admin_headers,
    ):
        """PRD §2.5: "A request body that names a foreign key —
        cardholder_id, account_id, category_id, partner_id, or
        original_transaction_id — is checked after path resolution
        succeeds; if the referenced resource does not exist, the
        request is rejected with ERR_REFERENCE_NOT_FOUND."

        Claim: POST /accounts with bogus cardholder_id ->
        ERR_REFERENCE_NOT_FOUND.
        """
        resp = api.create_account(
            create_account_payload(
                cardholder_id="00000000-0000-0000-0000-000000000000",
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


# ===========================================================================
# Cardholder ownership — PRD §2.1
# ===========================================================================
class TestCardholderOwnership:
    """PRD §2.1 ownership enforcement on entity-backed Cardholder
    role."""

    def test_cardholder_can_read_own_account(self, api):
        """PRD §2.1: "When X-User-Role is Cardholder, X-User-ID is the
        id of the acting Cardholder entity; ownership checks on any
        resource that references a Cardholder compare the resource's
        cardholder_id foreign key (resolved either directly, as on an
        Account, or transitively through the account_id chain for
        Transaction, PointsTransfer, StatementCredit,
        QuarterlyActivation, and PointsLedgerEntry) to X-User-ID."

        Claim: a Cardholder with X-User-ID set to their own id can GET
        their own account.
        """
        setup_clock_at(2026, 1, 2)
        ch, acc = create_cardholder_and_account()
        own_headers = make_cardholder_headers(ch["id"])
        resp = api.get_account(acc["id"], own_headers)
        data = validate_success(resp)
        assert data["id"] == acc["id"]
        assert data["cardholder_id"] == ch["id"]

    def test_cardholder_cannot_read_other_account(self, api):
        """PRD §2.1: "A Cardholder attempting to operate on another
        cardholder's account — whether by closing it, posting a
        transaction against it, transferring its points, redeeming its
        points, or activating a category for it — is rejected with
        ERR_FORBIDDEN."

        Claim: a Cardholder using their own id cannot GET another
        cardholder's account.
        """
        setup_clock_at(2026, 1, 2)
        ch_a, acc_a = create_cardholder_and_account()
        ch_b, acc_b = create_cardholder_and_account()
        # B reads A's account using B's own id -> forbidden.
        b_headers = make_cardholder_headers(ch_b["id"])
        resp = api.get_account(acc_a["id"], b_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
