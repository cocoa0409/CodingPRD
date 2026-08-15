"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def unique_serial() -> str:
    return f"SN-AUTO-{_n():05d}"


def unique_email(prefix: str = "u") -> str:
    return f"{prefix}{_n()}@x.org"


def unique_part_name(prefix: str = "Part") -> str:
    return f"{prefix}-{_n()}"


# --- donors / bikes ---

def create_donor_payload(**overrides) -> dict:
    defaults = {
        "display_name": f"Donor {_n()}",
        "donor_type": "INDIVIDUAL",
        "email": unique_email("donor"),
    }
    defaults.update(overrides)
    return defaults


def create_bike_payload(donor_id: str, **overrides) -> dict:
    defaults = {
        "donor_id": donor_id,
        "serial_number": unique_serial(),
        "bike_type": "ROAD",
        "wheel_size_inches": 27,
    }
    defaults.update(overrides)
    return defaults


def triage_payload(grade: str = "B", frame_damage: bool = False) -> dict:
    return {"condition_grade": grade, "frame_damage": frame_damage}


def route_refurbish_payload(lead_volunteer_id: str) -> dict:
    return {"destination": "REFURBISH", "refurb_lead_volunteer_id": lead_volunteer_id}


# --- parts ---

def create_part_payload(**overrides) -> dict:
    defaults = {
        "name": unique_part_name(),
        "category": "MISC",
        "unit_cost_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def create_helmet_part_payload(**overrides) -> dict:
    defaults = {
        "name": unique_part_name("Helmet"),
        "category": "HELMET",
        "helmet_size": "M",
        "unit_cost_cents": 1500,
    }
    defaults.update(overrides)
    return defaults


# --- volunteers / training ---

def create_volunteer_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Volunteer {_n()}",
        "email": unique_email("vol"),
    }
    defaults.update(overrides)
    return defaults


def create_training_session_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "topic": f"Class {n}",
        "level": "BASIC",
        "scheduled_start": "2026-08-02T10:00:00Z",
        "scheduled_end": "2026-08-02T11:00:00Z",
        "credit_hours": 6,
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(volunteer_id: str, **overrides) -> dict:
    defaults = {
        "volunteer_id": volunteer_id,
        "shift_role": "MECHANIC",
        "scheduled_start": "2026-08-10T09:00:00Z",
        "scheduled_end": "2026-08-10T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# --- participants / hours ---

def create_participant_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Participant {_n()}",
        "contact_email": unique_email("pa"),
        "age_group": "ADULT",
    }
    defaults.update(overrides)
    return defaults


def create_hour_log_payload(**overrides) -> dict:
    defaults = {
        "work_date": "2026-08-02",
        "hours": 4,
        "activity_type": "SHOP_HELP",
    }
    defaults.update(overrides)
    return defaults


# --- sales / giveaways ---

def create_sale_payload(bike_id: str, **overrides) -> dict:
    defaults = {
        "bike_id": bike_id,
        "buyer_name": f"Buyer {_n()}",
        "buyer_email": unique_email("buyer"),
    }
    defaults.update(overrides)
    return defaults


def create_giveaway_payload(bike_id: str, **overrides) -> dict:
    defaults = {
        "bike_id": bike_id,
        "partner_org": f"Org {_n()}",
        "referral_code": f"RC-{_n()}",
        "recipient_age_group": "ADULT",
    }
    defaults.update(overrides)
    return defaults


# --- memberships / sessions ---

def create_membership_payload(**overrides) -> dict:
    defaults = {
        "member_name": f"Member {_n()}",
        "member_email": unique_email("mem"),
        "tier": "BASIC",
        "end_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def book_session_payload(**overrides) -> dict:
    defaults = {
        "stand_number": 1,
        "start_time": "2026-08-10T10:00:00Z",
        "end_time": "2026-08-10T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# --- scrap / helmets ---

def create_scrap_ticket_payload(**overrides) -> dict:
    defaults = {
        "material": "STEEL",
        "weight_kg": 5.0,
        "recycler_name": "RecCo",
    }
    defaults.update(overrides)
    return defaults


def full_checklist(value: bool = True) -> dict:
    return {
        "brakes": value,
        "steering": value,
        "tires": value,
        "drivetrain": value,
        "reflectors": value,
    }
