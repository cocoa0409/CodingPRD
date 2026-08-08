"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _unique_case_number(prefix="CASE"):
    return f"{prefix}-{next(_counter):06d}"


def create_defendant_payload(**overrides) -> dict:
    """POST /defendants input fields. indigent is optional (defaults false)."""
    defaults = {
        "case_number": _unique_case_number(),
        "full_name": "Test Defendant",
        "date_of_birth": "1990-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(defendant_id: str, **overrides) -> dict:
    """POST /assessments. pending_violent_charge and substance_flag default false."""
    defaults = {
        "defendant_id": defendant_id,
        "instrument_type": "FULL",
        "prior_failures": 0,
        "pending_charges_count": 0,
        "pending_violent_charge": False,
        "employment_status": "EMPLOYED",
        "residence_stability": "STABLE",
        "substance_flag": False,
    }
    defaults.update(overrides)
    return defaults


def create_release_order_payload(defendant_id: str, assessment_id: str, **overrides) -> dict:
    """POST /release-orders."""
    defaults = {
        "defendant_id": defendant_id,
        "assessment_id": assessment_id,
        "decision": "RELEASE",
        "ordered_conditions": ["CHECK_IN"],
    }
    defaults.update(overrides)
    return defaults


def create_check_in_payload(defendant_id: str, due_at: str = "2026-06-10T12:00:00Z",
                            **overrides) -> dict:
    """POST /check-ins."""
    defaults = {"defendant_id": defendant_id, "due_at": due_at}
    defaults.update(overrides)
    return defaults


def create_em_device_payload(**overrides) -> dict:
    """POST /em-devices."""
    defaults = {"model_name": "Test Device Pool", "total_units": 1}
    defaults.update(overrides)
    return defaults


def create_em_enrollment_payload(defendant_id: str, device_id: str, **overrides) -> dict:
    """POST /em-enrollments."""
    defaults = {"defendant_id": defendant_id, "device_id": device_id}
    defaults.update(overrides)
    return defaults


def create_curfew_window_payload(expected_enrollment_version: int, day_of_week: int,
                                 start_minute: int, end_minute: int, **overrides) -> dict:
    """POST /em-enrollments/{id}/curfew-windows (OCC-guarded)."""
    defaults = {
        "expected_enrollment_version": expected_enrollment_version,
        "day_of_week": day_of_week,
        "start_minute": start_minute,
        "end_minute": end_minute,
    }
    defaults.update(overrides)
    return defaults


def create_ping_payload(pinged_at: str, at_home: bool, **overrides) -> dict:
    """POST /em-enrollments/{id}/pings."""
    defaults = {"pinged_at": pinged_at, "at_home": at_home}
    defaults.update(overrides)
    return defaults


def create_violation_payload(defendant_id: str, violation_type: str = "OTHER",
                             severity: str = "MODERATE", **overrides) -> dict:
    """POST /violations."""
    defaults = {
        "defendant_id": defendant_id,
        "violation_type": violation_type,
        "severity": severity,
    }
    defaults.update(overrides)
    return defaults


def create_court_event_payload(defendant_id: str, hearing_at: str = "2026-06-20T09:00:00Z",
                               **overrides) -> dict:
    """POST /court-events. reminder_lead_days optional (defaults 3)."""
    defaults = {"defendant_id": defendant_id, "hearing_at": hearing_at}
    defaults.update(overrides)
    return defaults


def create_testing_site_payload(**overrides) -> dict:
    """POST /testing-sites."""
    defaults = {"name": "Test Site", "slot_capacity": 5}
    defaults.update(overrides)
    return defaults


def create_drug_test_payload(defendant_id: str, site_id: str,
                             slot_start: str = "2026-06-05T10:00:00Z", **overrides) -> dict:
    """POST /drug-tests."""
    defaults = {
        "defendant_id": defendant_id,
        "site_id": site_id,
        "test_kind": "DRUG",
        "slot_start": slot_start,
    }
    defaults.update(overrides)
    return defaults


def create_fee_payload(supervision_days: int, em_days: int,
                       scheduled_test_count: int, **overrides) -> dict:
    """POST /defendants/{id}/fees."""
    defaults = {
        "supervision_days": supervision_days,
        "em_days": em_days,
        "scheduled_test_count": scheduled_test_count,
    }
    defaults.update(overrides)
    return defaults


def create_ledger_entry_payload(entry_type: str, **overrides) -> dict:
    """POST /defendants/{id}/ledger-entries."""
    defaults = {"entry_type": entry_type}
    defaults.update(overrides)
    return defaults


def create_level_adjustment_payload(expected_defendant_version: int, to_level: str,
                                    **overrides) -> dict:
    """POST /defendants/{id}/level-adjustments (OCC-guarded)."""
    defaults = {
        "expected_defendant_version": expected_defendant_version,
        "to_level": to_level,
    }
    defaults.update(overrides)
    return defaults
