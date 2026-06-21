"""Payload factories — one per entity, input fields only.

Defaults are sane minimal payloads; tests pass keyword overrides for fields
they need to control. Unique-ish defaults rely on a short uuid suffix so
parallel test runs against an empty DB do not collide on `code` /
`guardian_email` / `cycle_label` uniqueness constraints.
"""
import uuid


def _suffix() -> str:
    return uuid.uuid4().hex[:6].upper()


def create_district_payload(**overrides) -> dict:
    defaults = {
        "code": f"D{_suffix()[:5]}",  # 3..8 uppercase alphanumeric
        "name": "Test District",
        "poverty_index_pct": 0.00,
    }
    defaults.update(overrides)
    return defaults


def create_school_payload(district_id: str, **overrides) -> dict:
    defaults = {
        "district_id": district_id,
        "code": f"S{_suffix()[:5]}",
        "name": "Test School",
        "school_type": "MAGNET",
        "grade_min": 0,
        "grade_max": 12,
        "total_seats": 5,
    }
    defaults.update(overrides)
    return defaults


def create_boundary_rule_payload(school_id: str, zone_code: str, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "zone_code": zone_code,
        "is_in_boundary": True,
    }
    defaults.update(overrides)
    return defaults


def create_window_payload(
    district_id: str,
    cycle_label: str = "2026-27",
    opens_at: str = "2026-01-02T00:00:00Z",
    closes_at: str = "2026-02-01T00:00:00Z",
    lottery_runs_at: str = "2026-02-02T00:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "district_id": district_id,
        "cycle_label": cycle_label,
        "opens_at": opens_at,
        "closes_at": closes_at,
        "lottery_runs_at": lottery_runs_at,
    }
    defaults.update(overrides)
    return defaults


def create_family_payload(district_id: str, **overrides) -> dict:
    defaults = {
        "guardian_email": f"fam-{_suffix().lower()}@x.com",
        "residence_zone_code": "ZONE1",
        "residence_district_id": district_id,
        "poverty_flag": False,
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(family_id: str, **overrides) -> dict:
    defaults = {
        "family_id": family_id,
        "full_name": f"Student {_suffix()}",
        "grade_for_cycle": 3,
    }
    defaults.update(overrides)
    return defaults


def create_sibling_bond_payload(
    student_id: str, sibling_student_id: str, school_id: str, **overrides
) -> dict:
    defaults = {
        "student_id": student_id,
        "sibling_student_id": sibling_student_id,
        "school_id": school_id,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(
    window_id: str, student_id: str, school_id: str, choice_rank: int = 1, **overrides
) -> dict:
    defaults = {
        "window_id": window_id,
        "student_id": student_id,
        "school_id": school_id,
        "choice_rank": choice_rank,
    }
    defaults.update(overrides)
    return defaults


def run_lottery_payload(expected_window_version: int, **overrides) -> dict:
    defaults = {"expected_window_version": expected_window_version}
    defaults.update(overrides)
    return defaults


def accept_offer_payload(expected_offer_version: int, **overrides) -> dict:
    defaults = {"expected_offer_version": expected_offer_version}
    defaults.update(overrides)
    return defaults
