"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors rather than confusing assertion failures. Every
fixture builds its preconditions from scratch using only PRD-declared endpoints —
the server database is empty at the start of every test.

All four roles are opaque, so each fixture uses the appropriate role's shared
header constant for each step (segregation of duties: the agent books/funds, the
officer screens/decides, the operator dispatches/reports).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_corridor_payload, create_fx_rate_payload, create_sender_payload,
    create_recipient_payload, verify_sender_kyc_payload, submit_kyc_payload,
    decide_kyc_payload, create_quote_payload, create_transfer_payload,
    create_sanctions_list_payload, report_outcome_payload, create_refund_payload,
    set_clock_payload, advance_clock_payload, decide_case_payload,
)
from .constants import CLOCK_ANCHOR_ISO
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["remittance_agent_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
OPERATOR = TEST_USERS["payout_operator_headers"]


# ─── Clock control ────────────────────────────────────────────────────────

def set_clock(to_iso8601: str = CLOCK_ANCHOR_ISO):
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601=to_iso8601), ADMIN))


def advance_clock(seconds: int):
    return api_client.advance_clock(advance_clock_payload(seconds=seconds), ADMIN)


# ─── Tier 1: Base network config (corridor + FX rate, clock anchored) ──────

def setup_corridor(clock_iso: str = CLOCK_ANCHOR_ISO, with_fx: bool = True,
                   fx_overrides=None, **corridor_overrides):
    """Anchor the clock, create a corridor, and (optionally) publish an FX rate
    effective before the clock so quotes can be priced. Returns the corridor dict."""
    api_client.set_clock(set_clock_payload(to_iso8601=clock_iso), ADMIN)
    corridor = get_success_data(
        api_client.create_corridor(create_corridor_payload(**corridor_overrides), ADMIN))
    if with_fx:
        api_client.create_fx_rate(
            create_fx_rate_payload(corridor["id"], **(fx_overrides or {})), ADMIN)
    return corridor


def add_sanctions_entry(listed_name: str, listed_country: str, **overrides):
    return get_success_data(api_client.create_sanctions_list_entry(
        create_sanctions_list_payload(listed_name, listed_country, **overrides), ADMIN))


# ─── Tier 1: Party onboarding ──────────────────────────────────────────────

def setup_sender(kyc_tier: str = None, **overrides):
    """Register a sender; optionally raise its KYC tier via a ComplianceOfficer.
    A fresh sender is TIER0/ACTIVE; pass kyc_tier to verify it up."""
    sender = get_success_data(api_client.create_sender(create_sender_payload(**overrides), AGENT))
    if kyc_tier is not None:
        sender = get_success_data(api_client.verify_sender_kyc(
            sender["id"], verify_sender_kyc_payload(kyc_tier=kyc_tier), OFFICER))
    return sender


def setup_recipient(sender_id: str, verified: bool = False, doc_ref: str = "DOC-1",
                    **overrides):
    """Create a recipient under a sender. If verified=True, walk submit-kyc →
    decide-kyc(APPROVE) to reach VERIFIED."""
    recipient = get_success_data(api_client.create_recipient(
        create_recipient_payload(sender_id, **overrides), AGENT))
    if verified:
        api_client.submit_recipient_kyc(
            recipient["id"], submit_kyc_payload(kyc_doc_ref=doc_ref), AGENT)
        recipient = get_success_data(api_client.decide_recipient_kyc(
            recipient["id"], decide_kyc_payload("APPROVE"), OFFICER))
    return recipient


# ─── Tier 2: Quote lifecycle ───────────────────────────────────────────────

def create_locked_quote(corridor_id: str, sender_id: str,
                        send_principal_minor: int = 50000,
                        payout_method: str = "BANK"):
    """Create a DRAFT quote and lock it. Returns the locked quote dict
    (carries the post-lock version and disclosure figures)."""
    quote = get_success_data(api_client.create_quote(
        create_quote_payload(corridor_id, sender_id, send_principal_minor, payout_method), AGENT))
    locked = get_success_data(api_client.lock_quote(quote["id"], AGENT))
    return locked


def create_transfer_from_quote(quote: dict, recipient_id: str):
    """Consume a locked quote into a transfer using its current version."""
    return get_success_data(api_client.create_transfer(
        create_transfer_payload(quote["id"], recipient_id, quote["version"]), AGENT))


# ─── Tier 3: Transfer lifecycle shortcuts ──────────────────────────────────

def setup_created_transfer(send_principal_minor: int = 50000, sender_kyc_tier: str = "TIER1",
                           recipient_verified: bool = False, payout_method: str = "BANK",
                           corridor_overrides=None, recipient_overrides=None):
    """Corridor + FX + sender + recipient + locked quote consumed into a fresh
    transfer (UNFUNDED / SCREENING / PENDING). Returns (corridor, sender,
    recipient, quote, transfer)."""
    corridor = setup_corridor(**(corridor_overrides or {}))
    sender = setup_sender(kyc_tier=sender_kyc_tier)
    recipient = setup_recipient(sender["id"], verified=recipient_verified,
                                **(recipient_overrides or {}))
    quote = create_locked_quote(corridor["id"], sender["id"],
                                send_principal_minor, payout_method)
    transfer = create_transfer_from_quote(quote, recipient["id"])
    return corridor, sender, recipient, quote, transfer


def setup_funded_transfer(send_principal_minor: int = 50000, sender_kyc_tier: str = "TIER1",
                          recipient_verified: bool = False, corridor_overrides=None):
    """A FUNDED transfer (UNFUNDED -> FUNDED). Returns
    (corridor, sender, recipient, quote, transfer)."""
    corridor, sender, recipient, quote, transfer = setup_created_transfer(
        send_principal_minor=send_principal_minor, sender_kyc_tier=sender_kyc_tier,
        recipient_verified=recipient_verified, corridor_overrides=corridor_overrides)
    transfer = get_success_data(api_client.fund_transfer(transfer["id"], AGENT))
    return corridor, sender, recipient, quote, transfer


def setup_funded_screened_transfer(send_principal_minor: int = 50000,
                                   recipient_verified: bool = True,
                                   corridor_overrides=None):
    """A FUNDED + screened transfer with an empty sanctions list, so screening
    auto-CLEARS. Returns (corridor, sender, recipient, quote, transfer)."""
    corridor, sender, recipient, quote, transfer = setup_funded_transfer(
        send_principal_minor=send_principal_minor, recipient_verified=recipient_verified,
        corridor_overrides=corridor_overrides)
    transfer = get_success_data(api_client.screen_transfer(transfer["id"], OFFICER))
    return corridor, sender, recipient, quote, transfer


def setup_held_transfer_with_case(listed_name: str = "Ivan Petrov",
                                  listed_country: str = "PH",
                                  recipient_name: str = "Ivan Petrov",
                                  recipient_country: str = "PH",
                                  recipient_verified: bool = True,
                                  send_principal_minor: int = 50000):
    """A FUNDED transfer that screens to HELD (recipient name/country matches a
    listed entry), leaving an OPEN ComplianceCase. Returns
    (corridor, sender, recipient, transfer, case)."""
    corridor = setup_corridor()
    add_sanctions_entry(listed_name, listed_country)
    sender = setup_sender(kyc_tier="TIER1")
    recipient = setup_recipient(sender["id"], verified=recipient_verified,
                                full_name=recipient_name, country=recipient_country,
                                payout_method="BANK")
    quote = create_locked_quote(corridor["id"], sender["id"], send_principal_minor)
    transfer = create_transfer_from_quote(quote, recipient["id"])
    transfer = get_success_data(api_client.fund_transfer(transfer["id"], AGENT))
    transfer = get_success_data(api_client.screen_transfer(transfer["id"], OFFICER))
    case = _first_case_for_transfer(transfer["id"])
    return corridor, sender, recipient, transfer, case


def _first_case_for_transfer(transfer_id: str) -> dict:
    """Return the first compliance case opened for a transfer (by created_at)."""
    data, _meta = _list(api_client.list_compliance_cases(OFFICER, params={"transfer_id": transfer_id}))
    return data[0] if data else None


def _list(response):
    """Unwrap a paginated list response into (data_list, meta) leniently."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


# ─── Tier 3: Dispatch / delivery ───────────────────────────────────────────

def setup_dispatched_transfer(send_principal_minor: int = 50000):
    """A FUNDED, CLEARED, VERIFIED-recipient transfer dispatched into IN_TRANSIT
    with one PENDING payout attempt. Returns (corridor, transfer, attempt)."""
    corridor, sender, recipient, quote, transfer = setup_funded_screened_transfer(
        send_principal_minor=send_principal_minor, recipient_verified=True)
    transfer = get_success_data(api_client.dispatch_transfer(transfer["id"], OPERATOR))
    attempt = _pending_attempt(transfer["id"])
    return corridor, transfer, attempt


def _pending_attempt(transfer_id: str) -> dict:
    data, _meta = _list(api_client.list_payout_attempts(
        OPERATOR, params={"transfer_id": transfer_id, "outcome": "PENDING"}))
    return data[0] if data else None


def setup_transfer_with_failed_attempts(num_failed: int, send_principal_minor: int = 50000):
    """A FUNDED, CLEARED, VERIFIED transfer that has been dispatched and failed
    `num_failed` times (delivery_status FAILED). Returns (corridor, transfer)."""
    corridor, transfer, attempt = setup_dispatched_transfer(
        send_principal_minor=send_principal_minor)
    for i in range(num_failed):
        if i > 0:
            transfer = get_success_data(api_client.dispatch_transfer(transfer["id"], OPERATOR))
            attempt = _pending_attempt(transfer["id"])
        api_client.report_payout_outcome(
            attempt["id"], report_outcome_payload("FAILED", "INVALID_ACCOUNT"), OPERATOR)
    transfer = get_success_data(api_client.get_transfer(transfer["id"], OPERATOR))
    return corridor, transfer


# ─── Convenience readers ───────────────────────────────────────────────────

def ledger_entries_for(transfer_id: str, entry_type: str = None) -> list:
    params = {"transfer_id": transfer_id}
    if entry_type is not None:
        params["entry_type"] = entry_type
    data, _meta = _list(api_client.list_ledger_entries(OFFICER, params=params))
    return data


def get_corridor(corridor_id: str) -> dict:
    return get_success_data(api_client.get_corridor(corridor_id, ADMIN))


def get_transfer(transfer_id: str) -> dict:
    return get_success_data(api_client.get_transfer(transfer_id, AGENT))


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_compliance_case(case_id, OFFICER))
