"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Each factory provides sensible defaults; tests pass
**overrides for the values they need to control.
"""
import itertools

from .constants import CATALOG_DEFAULTS

# Monotonic counter so default emails are unique within a test run.
_email_counter = itertools.count(1)


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}{next(_email_counter)}@example.com"


# ─── Customer ─────────────────────────────────────────────────
def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": unique_email("cust"),
    }
    defaults.update(overrides)
    return defaults


# ─── ServiceCatalog ───────────────────────────────────────────
def create_service_catalog_payload(**overrides) -> dict:
    defaults = dict(CATALOG_DEFAULTS)
    defaults.update(overrides)
    return defaults


# ─── Crew ─────────────────────────────────────────────────────
def create_crew_payload(**overrides) -> dict:
    defaults = {
        "crew_name": "Test Rig",
        "supported_service_type": "STEAM",
        "turnaround_buffer_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


# ─── RecurringPlan ────────────────────────────────────────────
def create_recurring_plan_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "cadence": "MONTHLY",
    }
    defaults.update(overrides)
    return defaults


# ─── CleaningJob ──────────────────────────────────────────────
def create_cleaning_job_payload(customer_id: str, service_catalog_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "service_catalog_id": service_catalog_id,
    }
    defaults.update(overrides)
    return defaults


# ─── RoomAssessment ───────────────────────────────────────────
def create_room_payload(**overrides) -> dict:
    defaults = {
        "area_label": "Living Room",
        "area_sqft": 100,
        "soiling_level": "LIGHT",
    }
    defaults.update(overrides)
    return defaults


# ─── AddOn ────────────────────────────────────────────────────
def create_addon_payload(addon_type: str = "STAIN", **overrides) -> dict:
    defaults = {"addon_type": addon_type}
    defaults.update(overrides)
    return defaults


# ─── Booking / Reschedule ─────────────────────────────────────
def create_booking_payload(crew_id: str, start_minute: int, end_minute: int,
                           expected_crew_version: int, **overrides) -> dict:
    defaults = {
        "crew_id": crew_id,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "expected_crew_version": expected_crew_version,
    }
    defaults.update(overrides)
    return defaults


# ─── Complete ─────────────────────────────────────────────────
def create_complete_payload(completed_at_minute: int, **overrides) -> dict:
    defaults = {"completed_at_minute": completed_at_minute}
    defaults.update(overrides)
    return defaults


# ─── Payment ──────────────────────────────────────────────────
def create_payment_payload(amount_cents: int, expected_invoice_version: int,
                           method: str = "CARD", **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "method": method,
        "expected_invoice_version": expected_invoice_version,
    }
    defaults.update(overrides)
    return defaults


# ─── GuaranteeClaim ───────────────────────────────────────────
def create_claim_payload(cleaning_job_id: str, filed_at_minute: int,
                         reason: str = "Still soiled", **overrides) -> dict:
    defaults = {
        "cleaning_job_id": cleaning_job_id,
        "reason": reason,
        "filed_at_minute": filed_at_minute,
    }
    defaults.update(overrides)
    return defaults
