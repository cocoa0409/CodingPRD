"""Payload factories — one per resource, input fields only."""

import itertools

from .constants import CLOCK_EPOCH

_booking_seq = itertools.count(1)


def next_booking_number(prefix: str = "BK") -> str:
    """Unique booking_number per call; booking_number must be unique across all inmates."""
    return f"{prefix}-{next(_booking_seq):05d}"


def book_inmate_payload(**overrides) -> dict:
    defaults = {
        "booking_number": next_booking_number(),
        "full_name": "Test Patient",
        "facility_code": "FAC-01",
        "custody_level": "MEDIUM",
        "booked_at": CLOCK_EPOCH,
    }
    defaults.update(overrides)
    return defaults


def intake_screening_payload(**overrides) -> dict:
    defaults = {"screening_type": "RECEIVING"}
    defaults.update(overrides)
    return defaults


def screening_disposition_payload(**overrides) -> dict:
    defaults = {"disposition": "COMPLETED", "findings_code": "NO_FINDINGS"}
    defaults.update(overrides)
    return defaults


def chronic_enrollment_payload(**overrides) -> dict:
    defaults = {"condition_code": "DIABETES", "severity": "MODERATE"}
    defaults.update(overrides)
    return defaults


def chronic_visit_payload(**overrides) -> dict:
    defaults = {"outcome": "COMPLETED"}
    defaults.update(overrides)
    return defaults


def re_enroll_payload(**overrides) -> dict:
    defaults = {"severity": "MODERATE"}
    defaults.update(overrides)
    return defaults


def sick_call_payload(inmate_id, **overrides) -> dict:
    defaults = {
        "inmate_id": inmate_id,
        "complaint_text": "persistent cough",
        "encounter_type": "SICK_CALL",
    }
    defaults.update(overrides)
    return defaults


def triage_payload(**overrides) -> dict:
    defaults = {"acuity": "ROUTINE"}
    defaults.update(overrides)
    return defaults


def medication_order_payload(inmate_id, expected_inmate_version, **overrides) -> dict:
    defaults = {
        "inmate_id": inmate_id,
        "drug_name": "Sertraline",
        "drug_class": "PSYCHOTROPIC",
        "route_mode": "DOT",
        "doses_per_day": 1,
        "start_date": "2026-05-01T00:00:00Z",
        "end_date": "2026-05-10T00:00:00Z",
        "expected_inmate_version": expected_inmate_version,
    }
    defaults.update(overrides)
    return defaults


def administration_payload(scheduled_at, **overrides) -> dict:
    defaults = {"scheduled_at": scheduled_at}
    defaults.update(overrides)
    return defaults


def record_administration_payload(**overrides) -> dict:
    defaults = {"outcome": "ADMINISTERED"}
    defaults.update(overrides)
    return defaults


def pill_count_payload(**overrides) -> dict:
    defaults = {"units_dispensed_delta": 0, "units_returned_delta": 0}
    defaults.update(overrides)
    return defaults


def hold_status_payload(held: bool) -> dict:
    return {"held": held}


def specialty_referral_payload(inmate_id, **overrides) -> dict:
    defaults = {"inmate_id": inmate_id, "specialty": "CARDIOLOGY", "urgency": "ROUTINE"}
    defaults.update(overrides)
    return defaults


def submit_for_review_payload(**overrides) -> dict:
    defaults = {"retrospective": False}
    defaults.update(overrides)
    return defaults


def review_decision_payload(**overrides) -> dict:
    defaults = {"decision": "APPROVE"}
    defaults.update(overrides)
    return defaults


def peer_decision_payload(**overrides) -> dict:
    defaults = {"peer_decision": "OVERTURN"}
    defaults.update(overrides)
    return defaults


def supply_information_payload(**overrides) -> dict:
    defaults = {"information_text": "clinical justification attached"}
    defaults.update(overrides)
    return defaults


def transport_order_payload(referral_id, appointment_at, expected_referral_version,
                            **overrides) -> dict:
    defaults = {
        "referral_id": referral_id,
        "appointment_at": appointment_at,
        "expected_referral_version": expected_referral_version,
    }
    defaults.update(overrides)
    return defaults


def assign_escort_payload(escort_level, **overrides) -> dict:
    defaults = {"escort_level": escort_level}
    defaults.update(overrides)
    return defaults


def transport_outcome_payload(**overrides) -> dict:
    defaults = {"outcome": "COMPLETED"}
    defaults.update(overrides)
    return defaults


def transport_cancel_payload(**overrides) -> dict:
    defaults = {"cancel_reason": "FACILITY_LOCKDOWN"}
    defaults.update(overrides)
    return defaults


def copay_charge_payload(**overrides) -> dict:
    defaults = {"encounter_type": "SICK_CALL"}
    defaults.update(overrides)
    return defaults


def ledger_entry_payload(amount_cents, **overrides) -> dict:
    defaults = {
        "entry_type": "DEPOSIT",
        "amount_cents": amount_cents,
        "memo": "commissary deposit",
    }
    defaults.update(overrides)
    return defaults


def grievance_payload(grieved_event_at, **overrides) -> dict:
    defaults = {
        "grievance_text": "the charge on my account was wrong",
        "grieved_event_at": grieved_event_at,
    }
    defaults.update(overrides)
    return defaults


def grievance_decision_payload(**overrides) -> dict:
    defaults = {"outcome": "DENIED"}
    defaults.update(overrides)
    return defaults


def release_plan_payload(planned_release_at, **overrides) -> dict:
    defaults = {"release_type": "SCHEDULED", "planned_release_at": planned_release_at}
    defaults.update(overrides)
    return defaults


def death_event_payload(death_at, **overrides) -> dict:
    defaults = {"death_at": death_at, "manner": "NATURAL"}
    defaults.update(overrides)
    return defaults


def corrective_action_payload(**overrides) -> dict:
    defaults = {"action_text": "retrain night shift on hourly checks"}
    defaults.update(overrides)
    return defaults
