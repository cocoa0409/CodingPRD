"""Payload factories — one per entity, client-supplied input fields only."""
from .constants import TEST_DEFAULTS, SCREEN_METRIC_CODES


# ─── Athlete (PRD §3.1) ─────────────────────────────────────────────────────

def create_athlete_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Athlete",
        "date_of_birth": TEST_DEFAULTS["DATE_OF_BIRTH"],
        "sport": TEST_DEFAULTS["SPORT"],
        "position": TEST_DEFAULTS["POSITION"],
        "guardian_email": TEST_DEFAULTS["GUARDIAN_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


# ─── Injury record (PRD §3.2) ───────────────────────────────────────────────

def create_injury_record_payload(athlete_id: str, **overrides) -> dict:
    defaults = {
        "athlete_id": athlete_id,
        "body_region": "KNEE",
        "severity": "MODERATE",
        "occurred_on": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


# ─── Test sessions (PRD §3.1, §3.2) ─────────────────────────────────────────

def create_test_session_payload(athlete_id: str, battery_type: str = "MOVEMENT_SCREEN",
                                **overrides) -> dict:
    defaults = {"athlete_id": athlete_id, "battery_type": battery_type}
    defaults.update(overrides)
    return defaults


SCREEN_SIDES = {"SL_HOP_L": "LEFT", "SL_HOP_R": "RIGHT"}


def screen_results_payload(scores=None) -> dict:
    """A MOVEMENT_SCREEN append carries exactly the five screen codes.

    `scores` maps metric_code -> integer 0..3; omitted codes default to 3.
    The single-leg hop codes carry their own `side` marker, the rest are bilateral.
    """
    scores = scores or {}
    return {
        "results": [
            {"metric_code": code, "value": scores.get(code, 3),
             "side": SCREEN_SIDES.get(code, "BILATERAL")}
            for code in SCREEN_METRIC_CODES
        ]
    }


def battery_results_payload(values: dict) -> dict:
    """A PERFORMANCE_BATTERY append carries any non-empty subset of the three codes.

    `values` maps metric_code -> numeric value.
    """
    return {
        "results": [
            {"metric_code": code, "value": value, "side": "BILATERAL"}
            for code, value in values.items()
        ]
    }


# ─── Training programs and blocks (PRD §3.3) ────────────────────────────────

def create_training_program_payload(athlete_id: str, **overrides) -> dict:
    defaults = {
        "athlete_id": athlete_id,
        "sport": TEST_DEFAULTS["SPORT"],
        "position": TEST_DEFAULTS["POSITION"],
        "competition_start_date": "2026-09-01",
        "competition_end_date": "2027-03-01",
    }
    defaults.update(overrides)
    return defaults


def create_program_block_payload(expected_training_program_version: int, **overrides) -> dict:
    defaults = {
        "phase": "GENERAL_PREP",
        "start_week": 1,
        "end_week": 4,
        "target_intensity_pct": 70,
        "weekly_volume_units": 100.0,
        "expected_training_program_version": expected_training_program_version,
    }
    defaults.update(overrides)
    return defaults


# ─── Group sessions (PRD §3.5) ──────────────────────────────────────────────

def create_group_session_payload(**overrides) -> dict:
    defaults = {
        "start_at": "2026-08-10T10:00:00Z",
        "end_at": "2026-08-10T11:00:00Z",
        "site_code": "ONSITE",
        "station_count": 3,
        "phase_focus": "GENERAL_PREP",
        "max_athletes": 10,
    }
    defaults.update(overrides)
    return defaults


def assign_coach_payload(staff_member_id: str, expected_group_session_version: int,
                         coach_role: str = "LEAD", **overrides) -> dict:
    defaults = {
        "staff_member_id": staff_member_id,
        "coach_role": coach_role,
        "expected_group_session_version": expected_group_session_version,
    }
    defaults.update(overrides)
    return defaults


# ─── Enrollments (PRD §3.7) ─────────────────────────────────────────────────

def create_enrollment_payload(athlete_id: str, group_session_id: str, **overrides) -> dict:
    defaults = {"athlete_id": athlete_id, "group_session_id": group_session_id}
    defaults.update(overrides)
    return defaults


# ─── Staff and certifications (PRD §3.4) ────────────────────────────────────

def create_staff_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Coach",
        "role_title": "HEAD_COACH",
        "liability_insurance_expires_on": TEST_DEFAULTS["INSURANCE_EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(staff_member_id: str, **overrides) -> dict:
    defaults = {
        "staff_member_id": staff_member_id,
        "cert_code": "CPR_AED",
        "issued_on": TEST_DEFAULTS["CERT_ISSUED_ON"],
        "expires_on": TEST_DEFAULTS["CERT_EXPIRES_ON"],
        "ceu_credits_required": 6,
    }
    defaults.update(overrides)
    return defaults


# ─── Funding instruments (PRD §3.6) ─────────────────────────────────────────

def create_membership_package_payload(athlete_id: str, **overrides) -> dict:
    defaults = {
        "athlete_id": athlete_id,
        "sessions_purchased": 5,
        "price_cents": 30000,
        "expires_on": TEST_DEFAULTS["PACKAGE_EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_team_contract_payload(**overrides) -> dict:
    defaults = {
        "organization_name": "Test Organization",
        "organization_type": "CLUB",
        "contracted_sessions": 10,
        "base_rate_cents": 18000,
        "offsite_allowance": 0,
        "term_start": "2026-01-01",
        "term_end": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


# ─── Return to sport and clearance (PRD §3.9) ───────────────────────────────

def create_rts_plan_payload(athlete_id: str, injury_record_id: str, **overrides) -> dict:
    defaults = {
        "athlete_id": athlete_id,
        "injury_record_id": injury_record_id,
    }
    defaults.update(overrides)
    return defaults


def create_clearance_document_payload(athlete_id: str, document_type: str,
                                      expires_on: str = "2026-12-31", **overrides) -> dict:
    defaults = {
        "athlete_id": athlete_id,
        "document_type": document_type,
        "expires_on": expires_on,
    }
    defaults.update(overrides)
    return defaults
