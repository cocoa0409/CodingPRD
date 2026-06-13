"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "setup failed" errors, not confusing assertion failures.

Identity threading rule: every ownership-gated call uses the actual
Account.id as the AccountHolder X-User-ID via make_account_holder_headers,
never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_account_payload,
    create_funding_source_payload,
    verify_funding_source_payload,
    create_recipient_verification_payload,
    confirm_recipient_verification_payload,
    create_transfer_payload,
    create_split_request_payload,
    create_dispute_payload,
    create_withdrawal_payload,
    seed_credit_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_account_holder_headers,
    make_compliance_officer_headers,
    make_platform_admin_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Clock / ledger seeding ───────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Pin the server clock to a fixed UTC instant."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


def seed_credit(account_id: str, amount_cents: int, memo: str = "seed"):
    """Credit an account's balance directly (simulates an inbound deposit)."""
    return get_success_data(
        api_client.seed_credit(seed_credit_payload(account_id, amount_cents, memo=memo), ADMIN)
    )


# ─── Tier 1: Account creation / state progression ─────────────────────────
def create_account(funded_cents: int = 0, **account_overrides):
    """Register an ACTIVE account; optionally seed a starting balance.

    Returns the account dict (with version reflecting the seed credit if any).
    """
    acct = get_success_data(api_client.create_account(create_account_payload(**account_overrides), ADMIN))
    if funded_cents > 0:
        seed_credit(acct["id"], funded_cents)
        acct = get_success_data(
            api_client.get_account(acct["id"], make_account_holder_headers(acct["id"]))
        )
    return acct


def freeze_account(account_id: str):
    """Drive an account ACTIVE -> FROZEN via a compliance freeze."""
    return get_success_data(api_client.freeze_account(account_id, TEST_USERS["compliance_officer_headers"]))


# ─── Tier 2: Funding sources ──────────────────────────────────────────────
def create_pending_funding_source(account_id: str, kind: str = "BANK", last4: str = "1111"):
    """Create a PENDING FundingSource; returns (funding_source, micro_deposit_code)."""
    fs = get_success_data(
        api_client.create_funding_source(
            create_funding_source_payload(account_id, kind=kind, last4=last4),
            make_account_holder_headers(account_id),
        )
    )
    return fs, fs["micro_deposit_code"]


def create_verified_funding_source(account_id: str, kind: str = "BANK", last4: str = "1111"):
    """Create and VERIFY a FundingSource. Returns the verified funding_source dict."""
    fs, code = create_pending_funding_source(account_id, kind=kind, last4=last4)
    verified = get_success_data(
        api_client.verify_funding_source(
            fs["id"], verify_funding_source_payload(code), make_account_holder_headers(account_id)
        )
    )
    return verified


# ─── Tier 2: Recipient verification ───────────────────────────────────────
def make_recipient_verified(account_id: str, channel: str = "EMAIL"):
    """Create + confirm a RecipientVerification so the account's
    is_recipient_verified becomes true. Returns the confirmed verification dict."""
    rv = get_success_data(
        api_client.create_recipient_verification(
            create_recipient_verification_payload(account_id, channel=channel),
            make_account_holder_headers(account_id),
        )
    )
    confirmed = get_success_data(
        api_client.confirm_recipient_verification(
            rv["id"],
            confirm_recipient_verification_payload(rv["confirm_token"]),
            make_account_holder_headers(account_id),
        )
    )
    return confirmed


# ─── Tier 3: Transfers (settle / hold) ────────────────────────────────────
def get_account_version(account_id: str) -> int:
    acct = get_success_data(api_client.get_account(account_id, make_account_holder_headers(account_id)))
    return acct["version"]


def send_transfer(sender_id: str, recipient_id: str, amount_cents: int, **overrides):
    """Issue a transfer as the sender. Returns the raw response (caller validates
    routing). Useful when the test wants to assert the SETTLED/HELD fork directly."""
    return api_client.create_transfer(
        create_transfer_payload(sender_id, recipient_id, amount_cents, **overrides),
        make_account_holder_headers(sender_id),
    )


def create_settled_transfer(sender_id: str, recipient_id: str, amount_cents: int, **overrides):
    """Create a transfer expected to SETTLE immediately. Returns the transfer dict."""
    return get_success_data(send_transfer(sender_id, recipient_id, amount_cents, **overrides))


def create_held_transfer(sender_id: str, recipient_id: str, amount_cents: int = 100000, **overrides):
    """Create a LARGE_AMOUNT transfer expected to route to HELD with a
    PENDING_REVIEW RiskHold. Returns (transfer, hold_id)."""
    transfer = get_success_data(send_transfer(sender_id, recipient_id, amount_cents, **overrides))
    return transfer, transfer.get("hold_id")


def setup_settled_transfer_pair(amount_cents: int = 2000, sender_funded: int = 100000,
                                clock_iso: str = None):
    """Two accounts (sender funded, recipient verified) plus one SETTLED transfer.

    Returns (sender, recipient, transfer).
    """
    if clock_iso:
        set_clock(clock_iso)
    sender = create_account(funded_cents=sender_funded)
    recipient = create_account()
    make_recipient_verified(recipient["id"])
    transfer = create_settled_transfer(sender["id"], recipient["id"], amount_cents)
    return sender, recipient, transfer


def setup_held_transfer_scenario(amount_cents: int = 100000, sender_funded: int = 500000,
                                 clock_iso: str = None, **account_overrides):
    """Sender (funded) + verified recipient + one HELD transfer with a
    PENDING_REVIEW RiskHold. Returns (sender, recipient, transfer, hold_id)."""
    if clock_iso:
        set_clock(clock_iso)
    sender = create_account(funded_cents=sender_funded, **account_overrides)
    recipient = create_account()
    make_recipient_verified(recipient["id"])
    transfer, hold_id = create_held_transfer(sender["id"], recipient["id"], amount_cents)
    return sender, recipient, transfer, hold_id


# ─── Tier 3: Disputes ─────────────────────────────────────────────────────
def open_dispute(transfer_id: str, opener_account_id: str, reason: str = "UNAUTHORIZED"):
    """Open a dispute as the opener (sender). Returns the dispute dict."""
    return get_success_data(
        api_client.create_dispute(
            create_dispute_payload(transfer_id, opener_account_id, reason),
            make_account_holder_headers(opener_account_id),
        )
    )


def setup_open_dispute(amount_cents: int = 2000, clock_iso: str = "2026-06-01T00:00:00.000Z",
                       reason: str = "UNAUTHORIZED"):
    """Settled transfer O->R inside the dispute window plus an OPEN dispute by O.

    Returns (opener, recipient, transfer, dispute).
    """
    opener, recipient, transfer = setup_settled_transfer_pair(
        amount_cents=amount_cents, clock_iso=clock_iso
    )
    dispute = open_dispute(transfer["id"], opener["id"], reason)
    return opener, recipient, transfer, dispute


# ─── Tier 3: Withdrawals ──────────────────────────────────────────────────
def create_withdrawal(account_id: str, funding_source_id: str, gross_amount_cents: int,
                      speed: str = "STANDARD", expected_account_version: int = None):
    """Create a withdrawal, auto-reading the current account version unless one
    is supplied (so OCC tests can pass a deliberately stale value)."""
    if expected_account_version is None:
        expected_account_version = get_account_version(account_id)
    return api_client.create_withdrawal(
        create_withdrawal_payload(
            account_id, funding_source_id, gross_amount_cents,
            expected_account_version, speed=speed,
        ),
        make_account_holder_headers(account_id),
    )


def setup_account_with_verified_funding(funded_cents: int = 500000, last4: str = "1111"):
    """Account (funded) + one VERIFIED funding source. Returns (account, funding_source)."""
    acct = create_account(funded_cents=funded_cents)
    fs = create_verified_funding_source(acct["id"], last4=last4)
    return acct, fs


def setup_requested_standard_withdrawal(gross_amount_cents: int = 10000, funded_cents: int = 50000,
                                        last4: str = "1515"):
    """Account + VERIFIED funding source + one REQUESTED STANDARD withdrawal.

    Returns (account, funding_source, withdrawal).
    """
    acct, fs = setup_account_with_verified_funding(funded_cents=funded_cents, last4=last4)
    wd = get_success_data(
        create_withdrawal(acct["id"], fs["id"], gross_amount_cents, speed="STANDARD")
    )
    return acct, fs, wd


# ─── Tier 3: Splits ───────────────────────────────────────────────────────
def setup_split_request(total_amount_cents: int, participant_account_ids: list,
                        split_mode: str = "EVEN", weights: list = None,
                        organizer_account_id: str = None):
    """Create a split over the supplied participant accounts.

    Returns (split_request, [participant dicts in created order]).
    The participant list comes from GET /split-requests/{id}/participants.
    """
    if organizer_account_id is None:
        organizer_account_id = create_account()["id"]
    participants = []
    for i, pid in enumerate(participant_account_ids):
        entry = {"participant_account_id": pid}
        if weights is not None:
            entry["weight"] = weights[i]
        participants.append(entry)
    sr = get_success_data(
        api_client.create_split_request(
            create_split_request_payload(
                organizer_account_id, total_amount_cents, participants, split_mode=split_mode
            ),
            make_account_holder_headers(organizer_account_id),
        )
    )
    parts, _meta = _list_participants(sr["id"], organizer_account_id)
    return sr, parts


def setup_even_split_with_new_accounts(total_amount_cents: int, n_participants: int,
                                       organizer_funded: int = 0):
    """Create N fresh participant accounts (created in order) + an EVEN split.

    Returns (organizer, [participant accounts], split_request, [participant records]).
    """
    organizer = create_account(funded_cents=organizer_funded)
    participant_accounts = [create_account() for _ in range(n_participants)]
    sr, parts = setup_split_request(
        total_amount_cents,
        [p["id"] for p in participant_accounts],
        split_mode="EVEN",
        organizer_account_id=organizer["id"],
    )
    return organizer, participant_accounts, sr, parts


def setup_weighted_split_with_new_accounts(total_amount_cents: int, weights: list,
                                           organizer_funded: int = 0):
    """Create len(weights) fresh participant accounts (in order) + a WEIGHTED split.

    Returns (organizer, [participant accounts], split_request, [participant records]).
    """
    organizer = create_account(funded_cents=organizer_funded)
    participant_accounts = [create_account() for _ in weights]
    sr, parts = setup_split_request(
        total_amount_cents,
        [p["id"] for p in participant_accounts],
        split_mode="WEIGHTED",
        weights=weights,
        organizer_account_id=organizer["id"],
    )
    return organizer, participant_accounts, sr, parts


def _list_participants(split_request_id: str, actor_account_id: str):
    """List a split's participants as a (data, meta) tuple, sorted by created_at."""
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(
        api_client.list_split_participants(
            split_request_id, make_account_holder_headers(actor_account_id)
        )
    )


def list_participants(split_request_id: str, actor_account_id: str):
    """Public wrapper returning the participant list (data only)."""
    data, _meta = _list_participants(split_request_id, actor_account_id)
    return data


def participant_by_account(participants: list, account_id: str) -> dict:
    """Find the participant record owed by a given account."""
    for p in participants:
        if p["participant_account_id"] == account_id:
            return p
    raise AssertionError(f"No participant found for account {account_id}")
