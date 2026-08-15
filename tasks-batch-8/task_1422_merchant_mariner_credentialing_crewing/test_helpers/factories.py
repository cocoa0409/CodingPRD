"""Payload factories — one per entity, input fields only (PRD section 3)."""
import uuid

from . import constants as C


def _uniq() -> str:
    return uuid.uuid4().hex[:10].upper()


def create_mariner_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Test Mariner {_uniq()}",
        "mariner_reference_number": f"MRN-{_uniq()}",
        "home_port_code": "SFO",
        "hire_channel": "DIRECT",
        "rank_track": "DECK",
        "rank_grade": 5,
        "primary_endorsement_code": "DECK_AB",
    }
    defaults.update(overrides)
    return defaults


def create_vessel_payload(**overrides) -> dict:
    defaults = {
        "vessel_name": f"SS Test {_uniq()}",
        "imo_number": f"IMO-{_uniq()}",
        "vessel_class": "CONTAINER",
        "flag_state": "US",
    }
    defaults.update(overrides)
    return defaults


def create_manning_slot_payload(**overrides) -> dict:
    defaults = {
        "position_code": "AB",
        "rank_track": "DECK",
        "min_rank_grade": 2,
        "required_endorsement_code": "DECK_AB",
        "is_critical_position": False,
        "standard_tour_days": 90,
    }
    defaults.update(overrides)
    return defaults


def create_rotation_plan_payload(expected_vessel_version, **overrides) -> dict:
    defaults = {
        "effective_from": C.STD_PLAN_EFFECTIVE_FROM,
        "effective_to": C.STD_PLAN_EFFECTIVE_TO,
        "standard_tour_days": C.STD_PLAN_TOUR_DAYS,
        "max_handover_overlap_days": C.STD_PLAN_MAX_HANDOVER_DAYS,
        "expected_vessel_version": expected_vessel_version,
    }
    defaults.update(overrides)
    return defaults


def create_credential_payload(**overrides) -> dict:
    defaults = {
        "credential_type": "MMC_BASE",
        "endorsement_code": "DECK_AB",
        "issue_date": C.STD_CREDENTIAL_ISSUE,
        "expiry_date": C.STD_CREDENTIAL_EXPIRY,
    }
    defaults.update(overrides)
    return defaults


def create_sea_service_record_payload(vessel_id, **overrides) -> dict:
    defaults = {
        "vessel_id": vessel_id,
        "position_code": "AB",
        "rank_track": "DECK",
        "rank_grade": 5,
        "service_region": "OCEAN",
        "watch_schedule": "EIGHT_HOUR",
        "start_date": "2025-01-01T00:00:00Z",
        "end_date": "2025-01-30T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_medical_certificate_payload(**overrides) -> dict:
    defaults = {
        "cert_type": "USCG_MEDICAL",
        "issue_date": C.STD_MEDICAL_ISSUE,
        "expiry_date": C.STD_MEDICAL_EXPIRY,
    }
    defaults.update(overrides)
    return defaults


def create_drug_test_payload(**overrides) -> dict:
    defaults = {
        "test_type": "PRE_EMPLOYMENT",
        "scheduled_date": C.STD_DRUG_SCHEDULED,
    }
    defaults.update(overrides)
    return defaults


def record_drug_result_payload(**overrides) -> dict:
    defaults = {
        "result": "NEGATIVE",
        "collected_date": C.STD_DRUG_COLLECTED,
    }
    defaults.update(overrides)
    return defaults


def create_course_payload(**overrides) -> dict:
    defaults = {
        "course_code": f"COURSE-{_uniq()}",
        "title": f"Course {_uniq()}",
        "provider": "MaritimeEd",
        "start_date": C.STD_COURSE_START,
        "end_date": C.STD_COURSE_END,
        "seat_capacity": 5,
        "cost_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_union_hall_payload(**overrides) -> dict:
    tag = _uniq()
    defaults = {
        "local_number": f"LOCAL-{tag}",
        "name": f"Union Hall {tag}",
        "region": "WC",
    }
    defaults.update(overrides)
    return defaults


def create_union_registration_payload(mariner_id, **overrides) -> dict:
    defaults = {
        "mariner_id": mariner_id,
        "seniority_date": "2026-01-01T00:00:00Z",
        "shipping_card_number": f"SC-{_uniq()}",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(mariner_id, manning_slot_id, **overrides) -> dict:
    defaults = {
        "mariner_id": mariner_id,
        "manning_slot_id": manning_slot_id,
        "assignment_channel": "DIRECT_HIRE",
        "sign_on_date": C.STD_SIGN_ON,
        "planned_relief_date": C.STD_PLANNED_RELIEF,
        "local_join": True,
    }
    defaults.update(overrides)
    return defaults


def travel_leg_payload(**overrides) -> dict:
    defaults = {
        "carrier": "UA",
        "from_port": "SFO",
        "to_port": "SIN",
        "depart_at": "2026-08-09T10:00:00Z",
        "arrive_at": "2026-08-10T02:00:00Z",
        "base_fare_cents": 10_000,
        "markup_bps": 500,
    }
    defaults.update(overrides)
    return defaults


def create_join_booking_payload(legs=None, **overrides) -> dict:
    defaults = {
        "direction": "JOIN",
        "payer": "VESSEL_OWNER",
        "legs": legs if legs is not None else [travel_leg_payload()],
    }
    defaults.update(overrides)
    return defaults
