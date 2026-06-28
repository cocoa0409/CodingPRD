"""Payload factories — one per entity, input fields only (Creator Membership PRD §3).

Field names are PRD-exact. Each factory provides minimal valid defaults for the
required fields and accepts **overrides for anything a test needs to control.
Optional fields with server-side defaults (platform_plan, billing_mode,
charge_timing, benefit_labels, min_tier_rank, is_paid_creation, discount_pct)
are NOT supplied by default — only included when explicitly overridden.
"""
import itertools

_email_counter = itertools.count(1)


def _unique_email(prefix: str) -> str:
    return f"{prefix}{next(_email_counter)}@example.com"


# ---------------------------------------------------------------------------
# Creator (input: display_name, email, platform_plan?, payout_account_ref,
#          billing_mode?, charge_timing?)
# ---------------------------------------------------------------------------
def create_creator_payload(**overrides) -> dict:
    defaults = {
        "display_name": "Test Creator",
        "email": _unique_email("creator"),
        "payout_account_ref": "acct_test",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Tier (input: creator_id, name, billing_model, rank, monthly_fee_cents?,
#       per_creation_fee_cents?, per_creation_monthly_cap_cents?, benefit_labels?)
# ---------------------------------------------------------------------------
def create_tier_payload(creator_id, **overrides) -> dict:
    """Defaults to a MONTHLY tier (monthly_fee_cents=1500, rank=1)."""
    defaults = {
        "creator_id": creator_id,
        "name": "Test Tier",
        "billing_model": "MONTHLY",
        "rank": 1,
        "monthly_fee_cents": 1500,
    }
    defaults.update(overrides)
    return defaults


def create_per_creation_tier_payload(creator_id, **overrides) -> dict:
    """Defaults to a PER_CREATION tier (fee=500, cap=1200, rank=1)."""
    defaults = {
        "creator_id": creator_id,
        "name": "PC Tier",
        "billing_model": "PER_CREATION",
        "rank": 1,
        "per_creation_fee_cents": 500,
        "per_creation_monthly_cap_cents": 1200,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Patron (input: display_name, email)
# ---------------------------------------------------------------------------
def create_patron_payload(**overrides) -> dict:
    defaults = {
        "display_name": "Test Patron",
        "email": _unique_email("patron"),
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Pledge (input: patron_id, creator_id, tier_id)
# ---------------------------------------------------------------------------
def create_pledge_payload(patron_id, creator_id, tier_id, **overrides) -> dict:
    defaults = {
        "patron_id": patron_id,
        "creator_id": creator_id,
        "tier_id": tier_id,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Charge (input: pledge_id, charge_kind, gross_amount_cents)
# ---------------------------------------------------------------------------
def create_charge_payload(pledge_id, charge_kind="CYCLE_RENEWAL", gross_amount_cents=1500, **overrides) -> dict:
    defaults = {
        "pledge_id": pledge_id,
        "charge_kind": charge_kind,
        "gross_amount_cents": gross_amount_cents,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Post (input: creator_id, title, body, min_tier_rank?, is_paid_creation?)
# ---------------------------------------------------------------------------
def create_post_payload(creator_id, **overrides) -> dict:
    defaults = {
        "creator_id": creator_id,
        "title": "Test Post",
        "body": "Test body content",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# PostAccess request (input: patron_id)
# ---------------------------------------------------------------------------
def create_post_access_payload(patron_id, **overrides) -> dict:
    defaults = {"patron_id": patron_id}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Conversation (input: creator_id, patron_id)
# ---------------------------------------------------------------------------
def create_conversation_payload(creator_id, patron_id, **overrides) -> dict:
    defaults = {"creator_id": creator_id, "patron_id": patron_id}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Message (input: conversation_id, body)
# ---------------------------------------------------------------------------
def create_message_payload(conversation_id, body="Hello", **overrides) -> dict:
    defaults = {"conversation_id": conversation_id, "body": body}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Payout (input: creator_id, cycle_anchor_date)
# ---------------------------------------------------------------------------
def create_payout_payload(creator_id, cycle_anchor_date, **overrides) -> dict:
    defaults = {"creator_id": creator_id, "cycle_anchor_date": cycle_anchor_date}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# WinBackOffer (input: pledge_id, discount_pct?)
# ---------------------------------------------------------------------------
def create_win_back_offer_payload(pledge_id, **overrides) -> dict:
    defaults = {"pledge_id": pledge_id}
    defaults.update(overrides)
    return defaults
