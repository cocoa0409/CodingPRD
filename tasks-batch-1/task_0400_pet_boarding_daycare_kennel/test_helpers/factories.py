"""Payload factories — one per entity, input fields only.

Only ``source: input`` fields appear here; system/computed fields (status,
size_class, deposit_cents, etc.) are server-managed and never sent.
"""
import itertools

# Monotonic counter so generated emails are unique per facility/run.
_email_counter = itertools.count(1)


def unique_email(prefix="owner"):
    return f"{prefix}{next(_email_counter)}@example.com"


# ------------------------------------------------------------------- Facility
def create_facility_payload(**overrides) -> dict:
    defaults = {"name": "Test Kennel"}
    defaults.update(overrides)
    return defaults


# ------------------------------------------------------------------- Owner
def create_owner_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Owner",
        "email": unique_email(),
        "phone": "555-0000",
    }
    defaults.update(overrides)
    return defaults


# ------------------------------------------------------------------- Pet
def create_pet_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Pet",
        "species": "CAT",
        "weight_kg": 6,
        "temperament": "CALM",
    }
    defaults.update(overrides)
    return defaults


# ------------------------------------------------------------------- Vaccination
def create_vaccination_payload(**overrides) -> dict:
    defaults = {
        "vaccine": "RABIES",
        "administered_on": "2025-06-01",
        "expires_on": "2027-06-01",
    }
    defaults.update(overrides)
    return defaults


# ------------------------------------------------------------------- Pet review
def review_payload(decision="CLEAR", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


# ------------------------------------------------------------------- Run
def create_run_payload(**overrides) -> dict:
    defaults = {
        "label": "Suite-A1",
        "kind": "OVERNIGHT_SUITE",
        "size_class": "LARGE",
    }
    defaults.update(overrides)
    return defaults


# ------------------------------------------------------------------- Reservation
def create_reservation_payload(pet_id, service_type, start_date, end_date, **overrides) -> dict:
    defaults = {
        "pet_id": pet_id,
        "service_type": service_type,
        "start_date": start_date,
        "end_date": end_date,
    }
    defaults.update(overrides)
    return defaults


# ------------------------------------------------------------------- pay_deposit
def pay_deposit_payload(cash_cents, **overrides) -> dict:
    defaults = {"cash_cents": cash_cents}
    defaults.update(overrides)
    return defaults


# ------------------------------------------------------------------- Assignment
def create_assignment_payload(run_id, expected_reservation_version, **overrides) -> dict:
    defaults = {
        "run_id": run_id,
        "expected_reservation_version": expected_reservation_version,
    }
    defaults.update(overrides)
    return defaults


# ------------------------------------------------------------------- AddOn
def create_addon_payload(kind, scheduled_date, **overrides) -> dict:
    defaults = {"kind": kind, "scheduled_date": scheduled_date}
    defaults.update(overrides)
    return defaults


# ------------------------------------------------------------------- Package
def create_package_payload(tier="DAYCARE_10", cycle_start_date="2026-01-01", **overrides) -> dict:
    defaults = {"tier": tier, "cycle_start_date": cycle_start_date}
    defaults.update(overrides)
    return defaults


# ------------------------------------------------------------------- Incident
def create_incident_payload(severity="LOW", note="routine note", **overrides) -> dict:
    defaults = {"severity": severity, "note": note}
    defaults.update(overrides)
    return defaults


# ------------------------------------------------------------------- Clock
def advance_clock_payload(to_date, **overrides) -> dict:
    defaults = {"to_date": to_date}
    defaults.update(overrides)
    return defaults
