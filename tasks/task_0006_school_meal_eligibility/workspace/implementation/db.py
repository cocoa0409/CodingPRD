"""In-memory data store. Empty on every boot — never seed entities."""
import uuid
from datetime import datetime, timezone


# Per-entity tables keyed by id.
households = {}                # id -> dict
students = {}
allergy_profiles = {}
meal_applications = {}
eligibility_determinations = {}
menu_items = {}
parent_accounts = {}
ledger_entries = {}
service_transactions = {}
reimbursement_claims = {}

# Server logical clock; defaults to real now() until pinned.
_clock_pinned = None  # datetime | None


def new_id() -> str:
    return str(uuid.uuid4())


def server_now():
    if _clock_pinned is not None:
        return _clock_pinned
    return datetime.now(timezone.utc)


def set_clock(dt):
    global _clock_pinned
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _clock_pinned = dt.astimezone(timezone.utc)


def reset_all():
    """Clear everything (used only by potential test endpoints — not seeded)."""
    global _clock_pinned
    households.clear()
    students.clear()
    allergy_profiles.clear()
    meal_applications.clear()
    eligibility_determinations.clear()
    menu_items.clear()
    parent_accounts.clear()
    ledger_entries.clear()
    service_transactions.clear()
    reimbursement_claims.clear()
    _clock_pinned = None
