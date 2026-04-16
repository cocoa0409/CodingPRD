"""Payload factories from scaffold Table 1 input fields."""
import uuid
from datetime import datetime, timedelta, timezone


def _unique_suffix():
    return uuid.uuid4().hex[:8]


def _iso_utc(dt: datetime) -> str:
    """Return ISO 8601 UTC timestamp with milliseconds: 2026-04-16T09:14:27.842Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


def iso_now_offset(days=0, hours=0, minutes=0, seconds=0) -> str:
    """Return an ISO 8601 UTC timestamp offset from current time."""
    now = datetime.now(timezone.utc)
    dt = now + timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    return _iso_utc(dt)


def future_date(days=1) -> str:
    """Return an ISO 8601 UTC timestamp strictly in the future."""
    return iso_now_offset(days=days)


def past_date(days=1) -> str:
    """Return an ISO 8601 UTC timestamp strictly in the past."""
    return iso_now_offset(days=-days)


# ---------------------------------------------------------------------------
# Shelter
# ---------------------------------------------------------------------------

def create_shelter_payload(**overrides) -> dict:
    defaults = {
        "name": f"Test Shelter {_unique_suffix()}",
        "address": "123 Shelter Lane, Testville",
        "contact_email": f"shelter+{_unique_suffix()}@example.com",
        "boarding_capacity": 10,
        "tax_rate": 0.10,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Animal
# ---------------------------------------------------------------------------

def create_animal_payload(shelter_id, **overrides) -> dict:
    defaults = {
        "shelter_id": shelter_id,
        "name": f"Test Animal {_unique_suffix()}",
        "species": "DOG",
        "breed": "Mixed",
        "age_months": 24,
        "weight_kg": 15.5,
        "temperament": "CALM",
        "special_needs": [],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# VaccinationRecord
# ---------------------------------------------------------------------------

def create_vaccination_record_payload(
    animal_id,
    vaccine_name="RABIES",
    administered_days_ago=30,
    expiry_days_from_now=365,
    **overrides,
) -> dict:
    defaults = {
        "animal_id": animal_id,
        "vaccine_name": vaccine_name,
        "administered_date": past_date(days=administered_days_ago),
        "expiry_date": future_date(days=expiry_days_from_now),
        "batch_number": f"BATCH-{_unique_suffix()}",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Adopter
# ---------------------------------------------------------------------------

def create_adopter_payload(shelter_id, **overrides) -> dict:
    suffix = _unique_suffix()
    defaults = {
        "shelter_id": shelter_id,
        "full_name": f"Test Adopter {suffix}",
        "email": f"adopter+{suffix}@example.com",
        "phone": f"+1555{uuid.uuid4().hex[:7]}",
        "home_type": "HOUSE",
        "has_yard": True,
        "has_other_pets": False,
        "other_pet_species": [],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# AdoptionApplication
# ---------------------------------------------------------------------------

def create_adoption_application_payload(animal_id, adopter_id, **overrides) -> dict:
    defaults = {
        "animal_id": animal_id,
        "adopter_id": adopter_id,
        "reason": "I want to provide a loving home for this animal.",
    }
    defaults.update(overrides)
    return defaults


def reject_application_payload(rejection_reason="Not a fit", **overrides) -> dict:
    defaults = {"rejection_reason": rejection_reason}
    defaults.update(overrides)
    return defaults


def blacklist_adopter_payload(reason="Policy violation", **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# HomeVisit
# ---------------------------------------------------------------------------

def create_home_visit_payload(application_id, scheduled_days_from_now=3, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "scheduled_date": future_date(days=scheduled_days_from_now),
    }
    defaults.update(overrides)
    return defaults


def complete_home_visit_payload(
    yard_adequate=True,
    space_adequate=True,
    safety_hazards_found=False,
    existing_pets_compatible=True,
    notes="Home visit notes",
    **overrides,
) -> dict:
    defaults = {
        "yard_adequate": yard_adequate,
        "space_adequate": space_adequate,
        "safety_hazards_found": safety_hazards_found,
        "existing_pets_compatible": existing_pets_compatible,
        "notes": notes,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# BoardingReservation
# ---------------------------------------------------------------------------

def create_boarding_reservation_payload(
    shelter_id,
    animal_id,
    check_in_days_from_now=0,
    duration_days=3,
    check_in_already_past=False,
    **overrides,
) -> dict:
    """Build a boarding reservation payload.

    If ``check_in_already_past`` is True, the check_in_date is set to an earlier
    moment of *today* (midnight) so that creation still satisfies the PRD rule
    ``check_in_date >= current day`` (a date-level check) while subsequent
    ``/check-in`` calls can succeed without a real clock-time wait — the
    PRD only requires ``current_time >= check_in_date`` at check-in.
    """
    if check_in_already_past:
        now = datetime.now(timezone.utc)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        check_in_date = _iso_utc(midnight)
        # check_out_date must still be strictly > check_in_date and represent
        # the planned-duration window.
        check_out_date = future_date(days=max(1, duration_days))
    elif check_in_days_from_now > 0:
        check_in_date = future_date(days=check_in_days_from_now)
        check_out_date = future_date(days=check_in_days_from_now + duration_days)
    else:
        check_in_date = iso_now_offset(minutes=1)
        check_out_date = future_date(days=check_in_days_from_now + duration_days)
    defaults = {
        "shelter_id": shelter_id,
        "animal_id": animal_id,
        "owner_name": f"Owner {_unique_suffix()}",
        "owner_contact": f"+1555{uuid.uuid4().hex[:7]}",
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "special_instructions": "Handle with care",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# FeeInvoice payment
# ---------------------------------------------------------------------------

def pay_invoice_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# ComplianceHold
# ---------------------------------------------------------------------------

def create_compliance_hold_payload(
    animal_id,
    hold_type="HEALTH_CONCERN",
    severity="MEDIUM",
    reason="Test hold reason",
    **overrides,
) -> dict:
    defaults = {
        "animal_id": animal_id,
        "hold_type": hold_type,
        "severity": severity,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def resolve_hold_payload(resolution_notes="Resolved per protocol", **overrides) -> dict:
    defaults = {"resolution_notes": resolution_notes}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# FeeSchedule
# ---------------------------------------------------------------------------

def create_fee_schedule_payload(
    shelter_id,
    fee_type="ADOPTION_BASE",
    species="ALL",
    amount_cents=10000,
    effective_days_ago=1,
    effective_to_days_from_now=None,
    **overrides,
) -> dict:
    defaults = {
        "shelter_id": shelter_id,
        "fee_type": fee_type,
        "species": species,
        "amount_cents": amount_cents,
        "effective_from": past_date(days=effective_days_ago),
    }
    if effective_to_days_from_now is not None:
        defaults["effective_to"] = future_date(days=effective_to_days_from_now)
    else:
        defaults["effective_to"] = None
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# SettlementBatch
# ---------------------------------------------------------------------------

def create_settlement_batch_payload(
    shelter_id,
    period_start_days_ago=7,
    period_end_days_from_now=1,
    **overrides,
) -> dict:
    defaults = {
        "shelter_id": shelter_id,
        "period_start": past_date(days=period_start_days_ago),
        "period_end": future_date(days=period_end_days_from_now),
    }
    defaults.update(overrides)
    return defaults
