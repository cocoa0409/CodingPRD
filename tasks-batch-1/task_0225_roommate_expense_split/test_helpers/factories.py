"""Payload factories — one per entity, input fields only."""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix: str = "user") -> str:
    """A process-unique email for profile creation."""
    return f"{prefix}-{next(_email_counter)}@example.com"


def create_profile_payload(**overrides) -> dict:
    """Input fields for POST /roommate-profiles.

    smoker and pets default to false when omitted (PRD §3.1); we include them
    explicitly here so factory-built profiles are deterministic. Tests that want
    to exercise the server default omit them via a bespoke payload.
    """
    defaults = {
        "email": unique_email("profile"),
        "full_name": "Test Roommate",
        "monthly_income_cents": 500_000,
        "cleanliness": 5,
        "sleep_schedule": "FLEXIBLE",
        "smoker": False,
        "pets": False,
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(lister_id: str, **overrides) -> dict:
    """Input fields for POST /room-listings."""
    defaults = {
        "lister_id": lister_id,
        "title": "Test Room",
        "monthly_rent_cents": 200_000,
        "capacity": 3,
        "room_size_sqft": 200,
        "wants_cleanliness": 1,
        "wants_sleep_schedule": "FLEXIBLE",
        "no_smokers": False,
        "no_pets": False,
        "split_policy": "EQUAL",
    }
    defaults.update(overrides)
    return defaults


def create_match_request_payload(listing_id: str, applicant_id: str, **overrides) -> dict:
    """Input fields for POST /match-requests."""
    defaults = {
        "listing_id": listing_id,
        "applicant_id": applicant_id,
        "scoring_mode": "STRICT",
    }
    defaults.update(overrides)
    return defaults


def create_bill_payload(household_id: str, **overrides) -> dict:
    """Input fields for POST /bills."""
    defaults = {
        "household_id": household_id,
        "bill_type": "RENT",
        "total_amount_cents": 200_000,
        "period_start": "2026-06-01T00:00:00.000Z",
        "period_end": "2026-06-30T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_expense_payload(household_id: str, payer_id: str, participant_ids, **overrides) -> dict:
    """Input fields for POST /expenses."""
    defaults = {
        "household_id": household_id,
        "payer_id": payer_id,
        "description": "Test expense",
        "total_amount_cents": 9_000,
        "split_mode": "EQUAL",
        "participant_ids": list(participant_ids),
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(household_id, from_profile_id, to_profile_id, amount_cents, **overrides) -> dict:
    """Input fields for POST /settlements."""
    defaults = {
        "household_id": household_id,
        "from_profile_id": from_profile_id,
        "to_profile_id": to_profile_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_reminder_payload(household_id, due_date, **overrides) -> dict:
    """Input fields for POST /payment-reminders.

    Exactly one of bill_id / settlement_id should be supplied by the caller.
    """
    defaults = {
        "household_id": household_id,
        "due_date": due_date,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(household_id, filed_by_id, reason="disputed", **overrides) -> dict:
    """Input fields for POST /disputes.

    Exactly one of expense_id / settlement_id should be supplied by the caller.
    """
    defaults = {
        "household_id": household_id,
        "filed_by_id": filed_by_id,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults
