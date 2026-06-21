"""Payload factories — one per entity, input fields only (PRD §3 / §4).

Each factory returns a dict of the source:input fields for a POST; pass
**overrides to control any field. Foreign keys that a test must thread (center_id,
donor_id, slot_id, donation_id, appointment_id) are explicit positional args.
"""


# ─── Centers & clock ──────────────────────────────────────────────────────────
def create_center_payload(**overrides) -> dict:
    defaults = {"name": "Metro Blood", "region_code": "US-CA"}
    defaults.update(overrides)
    return defaults


def advance_clock_payload(to_iso8601: str, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults


# ─── Donors ───────────────────────────────────────────────────────────────────
def create_donor_payload(center_id: str, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "full_name": "Dana Donor",
        "date_of_birth": "1990-05-01",
        "weight_kg": 70,
        "blood_type": "O_POS",
    }
    defaults.update(overrides)
    return defaults


# ─── Deferrals ────────────────────────────────────────────────────────────────
def create_deferral_payload(donor_id: str, **overrides) -> dict:
    defaults = {
        "donor_id": donor_id,
        "category": "TRAVEL",
        "kind": "TEMPORARY",
        "reason": "endemic region trip",
        "duration_days": 21,
    }
    defaults.update(overrides)
    return defaults


# ─── Slots ────────────────────────────────────────────────────────────────────
def create_slot_payload(center_id: str, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "donation_type": "WHOLE",
        "starts_at": "2025-01-02T08:00:00.000Z",
        "ends_at": "2025-01-02T18:00:00.000Z",
        "capacity": 5,
    }
    defaults.update(overrides)
    return defaults


# ─── Appointments ─────────────────────────────────────────────────────────────
def create_appointment_payload(donor_id: str, slot_id: str, expected_slot_version: int, **overrides) -> dict:
    defaults = {
        "donor_id": donor_id,
        "slot_id": slot_id,
        "expected_slot_version": expected_slot_version,
    }
    defaults.update(overrides)
    return defaults


def create_donation_payload(**overrides) -> dict:
    defaults = {"volume_ml": 450}
    defaults.update(overrides)
    return defaults


# ─── Health screenings ────────────────────────────────────────────────────────
def create_health_screening_payload(appointment_id: str, **overrides) -> dict:
    defaults = {
        "appointment_id": appointment_id,
        "hemoglobin_g_dl": 14.0,
        "systolic_bp": 120,
        "pulse_bpm": 70,
        "weight_kg": 70,
        "recent_travel_risk": False,
        "disqualifying_medication": False,
    }
    defaults.update(overrides)
    return defaults


# ─── Test results ─────────────────────────────────────────────────────────────
def create_test_result_payload(**overrides) -> dict:
    defaults = {"panel_outcome": "NEGATIVE"}
    defaults.update(overrides)
    return defaults


# ─── Blood units ──────────────────────────────────────────────────────────────
def create_blood_unit_payload(donation_id: str, **overrides) -> dict:
    defaults = {
        "donation_id": donation_id,
        "component": "RBC",
        "din": "DIN-0001",
    }
    defaults.update(overrides)
    return defaults


# ─── Adverse reactions ────────────────────────────────────────────────────────
def create_adverse_reaction_payload(donation_id: str, **overrides) -> dict:
    defaults = {
        "donation_id": donation_id,
        "severity": "MILD",
        "symptom": "light dizziness",
    }
    defaults.update(overrides)
    return defaults


# ─── Recall / lookback ────────────────────────────────────────────────────────
def create_recall_event_payload(center_id: str, donor_id: str, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "donor_id": donor_id,
        "reason": "OTHER",
        "lookback_days": 30,
    }
    defaults.update(overrides)
    return defaults


# ─── Inventory buckets ────────────────────────────────────────────────────────
def create_inventory_bucket_payload(center_id: str, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "blood_type": "O_POS",
        "component": "RBC",
    }
    defaults.update(overrides)
    return defaults
