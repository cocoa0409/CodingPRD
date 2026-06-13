"""Payload factories — one per writable entity, input fields only.

Email values are made unique per call so registration's case-insensitive
uniqueness constraint never collides across the entities a single test builds.
"""
import itertools

_email_counter = itertools.count(1)


def _unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{next(_email_counter)}@example.com"


def create_account_payload(**overrides) -> dict:
    """POST /accounts — email + display_name required; limits optional."""
    defaults = {
        "email": _unique_email("acct"),
        "display_name": "Test Account",
    }
    defaults.update(overrides)
    return defaults


def create_funding_source_payload(account_id: str, **overrides) -> dict:
    """POST /funding-sources — account_id, kind, last4 required."""
    defaults = {
        "account_id": account_id,
        "kind": "BANK",
        "last4": "1111",
    }
    defaults.update(overrides)
    return defaults


def verify_funding_source_payload(code: str, **overrides) -> dict:
    """POST /funding-sources/{id}/verify — the micro-deposit code."""
    defaults = {"code": code}
    defaults.update(overrides)
    return defaults


def create_recipient_verification_payload(account_id: str, **overrides) -> dict:
    """POST /recipient-verifications — account_id + channel."""
    defaults = {
        "account_id": account_id,
        "channel": "EMAIL",
    }
    defaults.update(overrides)
    return defaults


def confirm_recipient_verification_payload(token: str, **overrides) -> dict:
    """POST /recipient-verifications/{id}/confirm — the confirm token."""
    defaults = {"token": token}
    defaults.update(overrides)
    return defaults


def create_transfer_payload(sender_account_id: str, recipient_account_id: str,
                            amount_cents: int, **overrides) -> dict:
    """POST /transfers — sender, recipient, amount required; memo optional."""
    defaults = {
        "sender_account_id": sender_account_id,
        "recipient_account_id": recipient_account_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_money_request_payload(requester_account_id: str, payer_account_id: str,
                                 amount_cents: int, **overrides) -> dict:
    """POST /money-requests — requester, payer, amount required."""
    defaults = {
        "requester_account_id": requester_account_id,
        "payer_account_id": payer_account_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_split_request_payload(organizer_account_id: str, total_amount_cents: int,
                                 participants: list, split_mode: str = "EVEN",
                                 **overrides) -> dict:
    """POST /split-requests — organizer, total, mode, participants list required.

    `participants` is a list of {participant_account_id, weight?} dicts.
    """
    defaults = {
        "organizer_account_id": organizer_account_id,
        "total_amount_cents": total_amount_cents,
        "split_mode": split_mode,
        "participants": participants,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(transfer_id: str, opener_account_id: str,
                           reason: str = "UNAUTHORIZED", **overrides) -> dict:
    """POST /disputes — transfer_id, opener, reason required."""
    defaults = {
        "transfer_id": transfer_id,
        "opener_account_id": opener_account_id,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_withdrawal_payload(account_id: str, funding_source_id: str,
                              gross_amount_cents: int, expected_account_version: int,
                              speed: str = "STANDARD", **overrides) -> dict:
    """POST /withdrawals — account, funding source, gross, speed, expected_account_version."""
    defaults = {
        "account_id": account_id,
        "funding_source_id": funding_source_id,
        "gross_amount_cents": gross_amount_cents,
        "speed": speed,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def seed_credit_payload(account_id: str, amount_cents: int, **overrides) -> dict:
    """POST /_ledger/seed_credit — directly credit an account's balance."""
    defaults = {
        "account_id": account_id,
        "amount_cents": amount_cents,
        "memo": "seed",
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    """POST /_clock/set_current_utc — pin the server clock."""
    return {"to_iso8601": to_iso8601}
