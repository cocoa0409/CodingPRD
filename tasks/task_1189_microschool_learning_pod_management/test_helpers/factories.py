"""Payload factories — one per entity, input fields only (PRD section 3).

Each factory accepts **overrides so tests can control exactly the values
their claim depends on while sensible defaults fill everything else.
"""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}{next(_counter)}"


EMERGENCY_PLAN_TEXT = (
    "Emergency preparedness plan. " * 12
)  # well over the 200-character minimum (PRD 3.2)


def create_facility_site_payload(**overrides) -> dict:
    defaults = {
        "site_name": _uniq("Site "),
        "address_line1": "1 Main St",
        "jurisdiction_code": TEST_DEFAULTS["JURISDICTION_CODE"],
        "zoning_class": "RESIDENTIAL_SINGLE",
        "max_occupancy": 40,
        "indoor_sqft": 1500,
    }
    defaults.update(overrides)
    return defaults


def create_pod_payload(facility_site_id: str, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "name": f"Pod {n}",
        "pod_code": f"POD{n:04d}X",
        "academic_year": TEST_DEFAULTS["ACADEMIC_YEAR"],
        "term_start_date": TEST_DEFAULTS["TERM_START_DATE"],
        "term_end_date": TEST_DEFAULTS["TERM_END_DATE"],
        "seat_capacity": TEST_DEFAULTS["SEAT_CAPACITY"],
        "tuition_full_year_cents": TEST_DEFAULTS["TUITION_FULL_YEAR_CENTS"],
        "min_guides_required": TEST_DEFAULTS["MIN_GUIDES_REQUIRED"],
        "facility_site_id": facility_site_id,
    }
    defaults.update(overrides)
    return defaults


def create_safety_policy_payload(**overrides) -> dict:
    defaults = {
        "policy_version": 1,
        "emergency_plan_text": EMERGENCY_PLAN_TEXT,
        "immunization_policy": "REQUIRED",
        "background_check_required": True,
        "drill_cadence_days": TEST_DEFAULTS["DRILL_CADENCE_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_curriculum_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_name": _uniq("Plan "),
        "grade_bands_covered": ["LOWER_EL", "UPPER_EL", "MIDDLE", "HIGH"],
        "multi_age_grouping": True,
        "total_instructional_minutes_per_week": TEST_DEFAULTS["PLAN_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_licensing_determination_payload(**overrides) -> dict:
    defaults = {
        "jurisdiction_code": TEST_DEFAULTS["JURISDICTION_CODE"],
        "submission_kind": "EXEMPTION_CLAIM",
    }
    defaults.update(overrides)
    return defaults


def create_guide_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "full_name": f"Guide {n}",
        "email": f"guide{n}@example.com",
        "certification_tier": "CERTIFIED",
    }
    defaults.update(overrides)
    return defaults


def create_guide_assignment_payload(guide_id: str, **overrides) -> dict:
    defaults = {
        "guide_id": guide_id,
        "window_start_date": TEST_DEFAULTS["TERM_START_DATE"],
        "window_end_date": TEST_DEFAULTS["TERM_END_DATE"],
        "weekly_hours": TEST_DEFAULTS["WEEKLY_HOURS"],
        "is_primary": True,
    }
    defaults.update(overrides)
    return defaults


def create_family_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "family_name": f"Family{n}",
        "primary_contact_email": f"family{n}@example.com",
        "billing_address_state": TEST_DEFAULTS["BILLING_STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "legal_first_name": f"Stu{n}",
        "legal_last_name": "Learner",
        "date_of_birth": "2017-03-15",
    }
    defaults.update(overrides)
    return defaults


def create_voucher_account_payload(**overrides) -> dict:
    defaults = {
        "program_code": TEST_DEFAULTS["VOUCHER_PROGRAM_CODE"],
        "awarded_annual_cents": 600000,
    }
    defaults.update(overrides)
    return defaults


def create_seat_payload(student_id: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "enrolled_on": TEST_DEFAULTS["TERM_START_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {
        "billing_period_start": "2026-08-01",
        "billing_period_end": "2026-08-31",
        "line_items": [
            {
                "description": "Tuition",
                "quantity": 1,
                "unit_amount_cents": 100000,
                "kind": "TUITION",
            }
        ],
        "due_date": "2026-09-15",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "source_kind": "FAMILY",
        "amount_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_progress_conference_payload(seat_id: str, curriculum_plan_id: str, **overrides) -> dict:
    defaults = {
        "seat_id": seat_id,
        "curriculum_plan_id": curriculum_plan_id,
        "scheduled_start": "2026-09-01T15:00:00Z",
        "scheduled_end": "2026-09-01T15:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_refund_claim_payload(seat_id: str, **overrides) -> dict:
    defaults = {
        "seat_id": seat_id,
        "claim_kind": "OVERPAYMENT",
    }
    defaults.update(overrides)
    return defaults
