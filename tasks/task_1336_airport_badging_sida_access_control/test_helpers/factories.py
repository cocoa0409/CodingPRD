"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "SPONSOR_NAME": "AeroFuel",
    "SPONSOR_CODE": "AF",
    "QUOTA": 5,
    "FULL_NAME": "Ana Rios",
    "DATE_OF_BIRTH": "1990-01-01",
    "GOVERNMENT_ID": "G1001",
    "BADGE_CLASS": "STERILE",
    "FINGERPRINT_SUBMITTED_AT": "2026-08-01T00:00:00Z",
    "COMPLETED_AT": "2026-06-01T00:00:00Z",
    "BADGE_NUMBER": "B100",
    "MAX_ESCORTEES": 3,
    "VIOLATION_OCCURRED_AT": "2026-08-02T00:00:00Z",
}


def create_sponsor_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SPONSOR_NAME"],
        "sponsor_code": DEFAULTS["SPONSOR_CODE"],
        "active_badge_quota": DEFAULTS["QUOTA"],
    }
    defaults.update(overrides)
    return defaults


def suspend_sponsor_payload(**overrides) -> dict:
    defaults = {"reason": "security directive"}
    defaults.update(overrides)
    return defaults


def create_applicant_payload(sponsor_id, **overrides) -> dict:
    defaults = {
        "sponsor_id": sponsor_id,
        "full_name": DEFAULTS["FULL_NAME"],
        "date_of_birth": DEFAULTS["DATE_OF_BIRTH"],
        "government_id_number": DEFAULTS["GOVERNMENT_ID"],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_id, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "badge_class": DEFAULTS["BADGE_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def record_chrc_payload(outcome="PASS", **overrides) -> dict:
    defaults = {
        "fingerprint_submitted_at": DEFAULTS["FINGERPRINT_SUBMITTED_AT"],
        "outcome": outcome,
    }
    defaults.update(overrides)
    return defaults


def record_sta_payload(outcome="CLEARED") -> dict:
    return {"outcome": outcome}


def issue_badge_payload(badge_number=None) -> dict:
    return {"badge_number": badge_number or DEFAULTS["BADGE_NUMBER"]}


def training_completion_payload(applicant_id, course_code, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "course_code": course_code,
        "completed_at": DEFAULTS["COMPLETED_AT"],
    }
    defaults.update(overrides)
    return defaults


def suspend_badge_payload(**overrides) -> dict:
    defaults = {"reason": "investigation"}
    defaults.update(overrides)
    return defaults


def revoke_badge_payload(**overrides) -> dict:
    defaults = {"reason": "terminated"}
    defaults.update(overrides)
    return defaults


def report_lost_payload(report_type="LOST") -> dict:
    return {"report_type": report_type}


def replace_badge_payload(badge_number) -> dict:
    return {"badge_number": badge_number}


def grant_escort_privilege_payload(max_escortees, expected_badge_version) -> dict:
    return {
        "max_escortees": max_escortees,
        "expected_badge_version": expected_badge_version,
    }


def access_check_payload(zone_code, badge_id=None, escortee_count=None) -> dict:
    payload = {"zone_code": zone_code}
    if badge_id is not None:
        payload["badge_id"] = badge_id
    if escortee_count is not None:
        payload["escortee_count"] = escortee_count
    return payload


def create_violation_payload(badge_id, violation_type, **overrides) -> dict:
    defaults = {
        "badge_id": badge_id,
        "violation_type": violation_type,
        "occurred_at": DEFAULTS["VIOLATION_OCCURRED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_audit_cycle_payload(window_start, window_end) -> dict:
    return {"window_start": window_start, "window_end": window_end}


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
