"""Payload factories — one per write endpoint, input fields only (PRD §4)."""

DEFAULTS = {
    "MEMBER_FULL_NAME": "Test Member",
    "DOG_NAME": "Rex",
    "DOG_SIZE_CLASS": "LARGE",
    "LICENSE_NUMBER": "LIC-0001",
    "VACCINATION_EXPIRES_ON": "2027-06-01",
    "AREA_NAME": "Main Field",
    "AREA_SIZE_CLASS": "LARGE",
    "AREA_CAPACITY": 4,
    "PASS_SIZE_CLASS": "SMALL",
    "PASS_VALID_ON": "2026-08-03",
    "INCIDENT_SEVERITY": "MINOR",
    "INCIDENT_DESCRIPTION": "rough play near the gate",
    "INCIDENT_OCCURRED_AT": "2026-08-01T10:00:00Z",
    "CLOSURE_REASON": "maintenance work",
    "STATION_NAME": "North Bin",
}

_member_seq = [0]


def _next(prefix: str) -> str:
    _member_seq[0] += 1
    return f"{prefix}-{_member_seq[0]}@example.com"


def create_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["MEMBER_FULL_NAME"],
        "email": _next("member"),
    }
    defaults.update(overrides)
    return defaults


def create_dog_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["DOG_NAME"],
        "size_class": DEFAULTS["DOG_SIZE_CLASS"],
        "license_number": DEFAULTS["LICENSE_NUMBER"],
        "vaccination_expires_on": DEFAULTS["VACCINATION_EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def verify_dog_payload(decision="VERIFIED", reason=None) -> dict:
    payload = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    return payload


def resubmit_dog_payload(vaccination_expires_on="2027-06-01",
                         license_number="LIC-0002") -> dict:
    return {
        "vaccination_expires_on": vaccination_expires_on,
        "license_number": license_number,
    }


def patch_member_payload(expected_member_version, **overrides) -> dict:
    payload = {"expected_member_version": expected_member_version}
    payload.update(overrides)
    return payload


def renew_membership_payload(expected_membership_version) -> dict:
    return {"expected_membership_version": expected_membership_version}


def purchase_guest_pass_payload(**overrides) -> dict:
    defaults = {
        "guest_dog_size_class": DEFAULTS["PASS_SIZE_CLASS"],
        "valid_on": DEFAULTS["PASS_VALID_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_area_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["AREA_NAME"],
        "size_class_restriction": DEFAULTS["AREA_SIZE_CLASS"],
        "capacity": DEFAULTS["AREA_CAPACITY"],
        "peak_capacity": DEFAULTS["AREA_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_closure_payload(starts_at="2026-08-10T00:00:00Z",
                           ends_at="2026-08-12T00:00:00Z",
                           reason=DEFAULTS["CLOSURE_REASON"]) -> dict:
    return {"starts_at": starts_at, "ends_at": ends_at, "reason": reason}


def check_in_payload(area_id, dog_id=None, guest_pass_id=None) -> dict:
    payload = {"area_id": area_id}
    if dog_id is not None:
        payload["dog_id"] = dog_id
    if guest_pass_id is not None:
        payload["guest_pass_id"] = guest_pass_id
    return payload


def file_incident_payload(subject_member_id, **overrides) -> dict:
    defaults = {
        "subject_member_id": subject_member_id,
        "severity": DEFAULTS["INCIDENT_SEVERITY"],
        "occurred_at": DEFAULTS["INCIDENT_OCCURRED_AT"],
        "description": DEFAULTS["INCIDENT_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def advance_report_payload(to, resolution_note=None) -> dict:
    payload = {"to": to}
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    return payload


def create_waste_station_payload(name=DEFAULTS["STATION_NAME"]) -> dict:
    return {"name": name}
