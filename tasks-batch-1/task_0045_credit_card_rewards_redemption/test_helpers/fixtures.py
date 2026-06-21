"""Composite setup helpers for the Credit Card Rewards & Redemption benchmark.

Each fixture builds its preconditions from scratch through PRD-declared endpoints
(see PRD §3.x). The runner restarts the API server before every individual pytest
test, so each fixture starts from an empty database — no entities, no clock state.

Fixtures use `get_success_data()` (lenient validator) so setup failures surface
as clear "Setup failed" traces rather than cryptic assertion failures.

Identity threading: the Cardholder role is entity-backed (PRD §2.1). Any
ownership-gated call against a Cardholder-owned resource (redemption create,
category activation, account close, own-resource reads) MUST use
`make_cardholder_headers(account["id"])`, never the shared
`TEST_USERS["cardholder_headers"]` fallback (which carries a placeholder
X-User-ID that never matches a real account row).
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    set_clock_payload,
    create_product_payload,
    create_cashback_category_payload,
    create_quarterly_category_payload,
    create_transfer_partner_payload,
    create_account_payload,
    create_transaction_payload,
    create_redemption_payload,
    create_category_activation_payload,
)
from .test_users import TEST_USERS, make_cardholder_headers


_ADMIN = TEST_USERS["program_admin_headers"]
_OPS = TEST_USERS["rewards_ops_headers"]


# ─── Tier 0: clock (PRD §3.10) ──────────────────────────────────
# The logical clock is a single pinned instant (PRD §3.10). A transaction's
# `transacted_at` must be no later than that instant (PRD §3.3). The fixtures
# track the last value the suite pinned the clock to, so the transaction
# helpers can advance the clock forward to the transaction time before
# recording a purchase — exactly the "record a purchase as of now" pattern the
# correctly-authored tests already do by hand. The advance is forward-only so
# a clock a test deliberately pinned ahead of the transaction (e.g. a window
# boundary probe) is never rewound.
_pinned_clock = None  # str ISO-8601 or None (real wall clock)


def _parse(iso8601: str) -> datetime:
    return datetime.fromisoformat(iso8601.replace("Z", "+00:00")).astimezone(timezone.utc)


def set_clock(iso8601: str) -> dict:
    """Set the logical server clock to a fixed UTC instant (PRD §3.10)."""
    global _pinned_clock
    _pinned_clock = iso8601
    return get_success_data(api_client.set_clock(set_clock_payload(iso8601), _ADMIN))


def _advance_clock_to(iso8601: str) -> None:
    """Advance the pinned clock forward to `iso8601` if it currently sits
    behind it, so a purchase recorded at `iso8601` is not 'in the future'
    relative to the server clock (PRD §3.3). Forward-only: never rewinds."""
    if _pinned_clock is None or _parse(iso8601) > _parse(_pinned_clock):
        set_clock(iso8601)


# ─── Tier 1: leaf creators (PRD §3.1, §3.2) ─────────────────────
def create_product(**overrides) -> dict:
    """Create an ACTIVE card product (PRD §3.1)."""
    return get_success_data(api_client.create_product(create_product_payload(**overrides), _ADMIN))


def retire_product(product_id: str) -> dict:
    return get_success_data(api_client.retire_product(product_id, _ADMIN))


def create_cashback_category(card_product_id, code, earn_multiplier_bps, **overrides) -> dict:
    return get_success_data(
        api_client.create_cashback_category(
            create_cashback_category_payload(card_product_id, code, earn_multiplier_bps, **overrides),
            _ADMIN,
        )
    )


def create_quarterly_category(card_product_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_quarterly_category(
            create_quarterly_category_payload(card_product_id, **overrides), _ADMIN
        )
    )


def create_transfer_partner(**overrides) -> dict:
    """Create an ACTIVE transfer partner (PRD §3.1)."""
    return get_success_data(
        api_client.create_transfer_partner(create_transfer_partner_payload(**overrides), _ADMIN)
    )


def suspend_transfer_partner(partner_id: str) -> dict:
    return get_success_data(api_client.suspend_transfer_partner(partner_id, _ADMIN))


def create_account(card_product_id, **overrides) -> dict:
    """Open a PENDING account under a product (PRD §3.2)."""
    return get_success_data(
        api_client.create_account(create_account_payload(card_product_id, **overrides), _ADMIN)
    )


# ─── Tier 1.5: account state progression (PRD §3.2) ─────────────
def create_active_account(card_product_id=None, **acct_overrides) -> dict:
    """Create product (if not given) + open + activate an account. Returns the
    ACTIVE account (PRD §3.2)."""
    if card_product_id is None:
        card_product_id = create_product()["id"]
    acct = create_account(card_product_id, **acct_overrides)
    return get_success_data(api_client.activate_account(acct["id"], _ADMIN))


def setup_active_account(product_overrides=None, account_overrides=None):
    """Create an ACTIVE account and return (product, account) (PRD §3.1, §3.2)."""
    product = create_product(**(product_overrides or {}))
    acct = create_account(product["id"], **(account_overrides or {}))
    acct = get_success_data(api_client.activate_account(acct["id"], _ADMIN))
    return product, acct


def get_account(account_id, headers=None) -> dict:
    return get_success_data(api_client.get_account(account_id, headers or _ADMIN))


def account_version(account_id) -> int:
    """Read the current CardAccount.version (PRD §2.7 OCC guard input)."""
    return get_account(account_id)["version"]


# ─── Tier 2: transaction lifecycle (PRD §3.3, §3.4) ─────────────
def create_pending_transaction(account_id, amount_cents, **overrides) -> dict:
    """Record a PENDING transaction (PRD §3.3).

    Advances the pinned clock forward to the transaction's `transacted_at`
    first, so the purchase is recorded 'as of now' and never lands in the
    future relative to the server clock (PRD §3.3 temporal range)."""
    payload = create_transaction_payload(account_id, amount_cents, **overrides)
    _advance_clock_to(payload["transacted_at"])
    return get_success_data(api_client.create_transaction(payload, _ADMIN))


def post_transaction(txn_id) -> dict:
    """Post a PENDING transaction to POSTED (PRD §3.4)."""
    return get_success_data(api_client.post_transaction(txn_id, _ADMIN))


def create_and_post_transaction(account_id, amount_cents, **overrides) -> dict:
    """Record + post a transaction; returns the POSTED transaction (PRD §3.4)."""
    txn = create_pending_transaction(account_id, amount_cents, **overrides)
    return post_transaction(txn["id"])


def setup_account_with_balance(amount_cents=100_000, product_overrides=None, account_overrides=None):
    """ACTIVE account whose single POSTED OTHER transaction has minted points.

    Returns (account, transaction). With the default base 100bps product and
    amount_cents == 100000 this yields points_balance == 1000 (PRD §3.5).
    """
    product, acct = setup_active_account(product_overrides, account_overrides)
    txn = create_and_post_transaction(acct["id"], amount_cents)
    acct = get_account(acct["id"])
    return acct, txn


# ─── Tier 3: redemption lifecycle (PRD §3.8) ────────────────────
def create_redemption(account_id, redemption_type, points_requested, expected_version,
                      transfer_partner_id=None, **overrides) -> dict:
    """Create a PENDING redemption as the owning Cardholder (PRD §3.8).

    Identity-threaded: uses make_cardholder_headers(account_id)."""
    return get_success_data(
        api_client.create_redemption(
            create_redemption_payload(
                account_id, redemption_type, points_requested, expected_version,
                transfer_partner_id=transfer_partner_id, **overrides,
            ),
            make_cardholder_headers(account_id),
        )
    )


def confirm_redemption(red_id) -> dict:
    """Confirm a PENDING redemption (RewardsOps, PRD §3.8)."""
    return get_success_data(api_client.confirm_redemption(red_id, _OPS))


def create_and_confirm_redemption(account_id, redemption_type, points_requested,
                                  transfer_partner_id=None, **overrides) -> dict:
    """Create a redemption at the account's current version then confirm it.
    Returns the CONFIRMED redemption (PRD §3.8)."""
    v = account_version(account_id)
    red = create_redemption(
        account_id, redemption_type, points_requested, v,
        transfer_partner_id=transfer_partner_id, **overrides,
    )
    return confirm_redemption(red["id"])


# ─── Tier 4: quarterly category + activation (PRD §3.1, §3.9) ───
def setup_account_with_activated_quarterly(
    quarterly_overrides=None, product_overrides=None, account_overrides=None,
):
    """ACTIVE account + a quarterly category on its product + an ACTIVE
    activation for it. Returns (product, account, quarterly_category) (PRD §3.9).
    """
    product = create_product(**(product_overrides or {}))
    qcat = create_quarterly_category(product["id"], **(quarterly_overrides or {}))
    acct = create_account(product["id"], **(account_overrides or {}))
    acct = get_success_data(api_client.activate_account(acct["id"], _ADMIN))
    get_success_data(
        api_client.create_category_activation(
            create_category_activation_payload(acct["id"], qcat["id"]),
            make_cardholder_headers(acct["id"]),
        )
    )
    acct = get_account(acct["id"])
    return product, acct, qcat


# ─── Tier 5: lot inspection helpers (PRD §3.4) ──────────────────
def list_account_lots(account_id) -> list:
    """All PointsLot rows for an account (PRD §3.4)."""
    data = get_success_data(
        api_client.list_points_lots(_ADMIN, params={"card_account_id": account_id})
    )
    return data if isinstance(data, list) else data.get("data", data)


def list_lots_by_source_txn(txn_id) -> list:
    """PointsLot rows minted by a given source transaction (PRD §3.4)."""
    data = get_success_data(
        api_client.list_points_lots(_ADMIN, params={"source_transaction_id": txn_id})
    )
    return data if isinstance(data, list) else data.get("data", data)


def close_period() -> dict:
    """Run the RewardsOps period-close epoch (PRD §3.10)."""
    return get_success_data(api_client.close_period(_OPS))
