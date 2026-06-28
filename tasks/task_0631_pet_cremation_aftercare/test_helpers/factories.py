"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Only fields the client supplies on creation appear here;
computed and system fields are never sent.
"""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix="owner"):
    """Owner email must be globally unique among PetOwners (PRD §3.1)."""
    return f"{prefix}{next(_email_counter)}@example.com"


def create_clinic_payload(**overrides) -> dict:
    """POST /clinics. credit_limit_cents is optional (default 500000)."""
    defaults = {
        "name": "Test Clinic",
        "account_code": f"AC-{next(_email_counter)}",
    }
    defaults.update(overrides)
    return defaults


def create_petowner_payload(**overrides) -> dict:
    """POST /petowners. full_name, email, phone all required."""
    defaults = {
        "full_name": "Test Owner",
        "email": unique_email(),
        "phone": "555-0000",
    }
    defaults.update(overrides)
    return defaults


def create_cooler_payload(**overrides) -> dict:
    """POST /coolers. label and total_capacity (>= 1) required."""
    defaults = {
        "label": "COOLER-T",
        "total_capacity": 3,
    }
    defaults.update(overrides)
    return defaults


def create_retort_payload(**overrides) -> dict:
    """POST /retorts. label and max_load_lbs (>= 1) required."""
    defaults = {
        "label": "RETORT-T",
        "max_load_lbs": 400,
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(retort_id, **overrides) -> dict:
    """POST /batches. retort_id, service_type, scheduled_start, scheduled_end required."""
    defaults = {
        "retort_id": retort_id,
        "service_type": "PRIVATE",
        "scheduled_start": "2026-03-01T08:00:00Z",
        "scheduled_end": "2026-03-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(owner_id, **overrides) -> dict:
    """POST /cases. owner_id, pet_name, species, weight_lbs, service_type, pickup_kind,
    bill_to required. clinic_id and expedited optional."""
    defaults = {
        "owner_id": owner_id,
        "pet_name": "Test Pet",
        "species": "DOG",
        "weight_lbs": 40,
        "service_type": "PRIVATE",
        "pickup_kind": "HOME",
        "bill_to": "OWNER",
    }
    defaults.update(overrides)
    return defaults


def create_transport_leg_payload(**overrides) -> dict:
    """POST /cases/{id}/transport-legs. origin_kind, origin_label, driver_name required."""
    defaults = {
        "origin_kind": "HOME",
        "origin_label": "1 Test St",
        "driver_name": "Driver T",
    }
    defaults.update(overrides)
    return defaults


def create_ready_return_payload(**overrides) -> dict:
    """POST /cases/{id}/ready-return. return_method, destination_label required."""
    defaults = {
        "return_method": "PICKUP_AT_FACILITY",
        "destination_label": "Front desk",
    }
    defaults.update(overrides)
    return defaults


def create_memorial_addon_payload(**overrides) -> dict:
    """POST /cases/{id}/memorial-addons. addon_type required; viewing fields conditional."""
    defaults = {
        "addon_type": "ONLINE_MEMORIAL",
    }
    defaults.update(overrides)
    return defaults
