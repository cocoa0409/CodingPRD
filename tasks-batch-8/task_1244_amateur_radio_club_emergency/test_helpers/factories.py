"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "LICENSE_EXPIRES_AT": "2030-01-01T00:00:00Z",
    "LICENSE_CLASS": "EXTRA",
    "LEASE_START": "2026-01-01T00:00:00Z",
    "LEASE_END": "2027-12-31T00:00:00Z",
    "REPEATER_FREQUENCY": 146.94,
    "NET_START": "2026-05-01T00:00:00Z",
    "NET_END": "2026-05-02T00:00:00Z",
    "EFFECTIVE_START": "2026-01-01T00:00:00Z",
    "EFFECTIVE_END": "2027-12-31T00:00:00Z",
    "DRILL_START": "2026-05-01T00:00:00Z",
    "DRILL_END": "2026-05-02T00:00:00Z",
    "EVENT_START": "2026-05-01T00:00:00Z",
    "EVENT_END": "2026-05-03T00:00:00Z",
    "EXAM_SCHEDULED_AT": "2026-05-01T00:00:00Z",
    "LOAN_DUE_AT": "2026-06-01T00:00:00Z",
    "LOAN_VALUE_CENTS": 1000,
}


def create_member_payload(**overrides) -> dict:
    defaults = {
        "callsign": "K1AAA",
        "full_name": "Test Operator",
        "license_class": DEFAULTS["LICENSE_CLASS"],
        "license_expires_at": DEFAULTS["LICENSE_EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def renew_member_payload(**overrides) -> dict:
    defaults = {"periods": 1}
    defaults.update(overrides)
    return defaults


def create_antenna_site_agreement_payload(**overrides) -> dict:
    defaults = {
        "site_name": "Hilltop",
        "owner_name": "County",
        "lease_start": DEFAULTS["LEASE_START"],
        "lease_end": DEFAULTS["LEASE_END"],
    }
    defaults.update(overrides)
    return defaults


def create_repeater_payload(site_agreement_id, **overrides) -> dict:
    defaults = {
        "callsign": "W1RPT",
        "output_frequency_mhz": DEFAULTS["REPEATER_FREQUENCY"],
        "site_agreement_id": site_agreement_id,
    }
    defaults.update(overrides)
    return defaults


def create_coordination_request_payload(repeater_id, expected_repeater_version, **overrides) -> dict:
    defaults = {
        "repeater_id": repeater_id,
        "requested_frequency_mhz": DEFAULTS["REPEATER_FREQUENCY"],
        "expected_repeater_version": expected_repeater_version,
    }
    defaults.update(overrides)
    return defaults


def create_net_session_payload(repeater_id, **overrides) -> dict:
    defaults = {
        "name": "ARES Net",
        "repeater_id": repeater_id,
        "scheduled_start": DEFAULTS["NET_START"],
        "scheduled_end": DEFAULTS["NET_END"],
    }
    defaults.update(overrides)
    return defaults


def create_check_in_payload(net_session_id, **overrides) -> dict:
    defaults = {"net_session_id": net_session_id}
    defaults.update(overrides)
    return defaults


def create_served_agency_agreement_payload(**overrides) -> dict:
    defaults = {
        "agency_name": "County OEM",
        "max_operators": 10,
        "effective_start": DEFAULTS["EFFECTIVE_START"],
        "effective_end": DEFAULTS["EFFECTIVE_END"],
    }
    defaults.update(overrides)
    return defaults


def create_emergency_activation_payload(agreement_id, expected_served_agency_agreement_version, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "title": "Flood support",
        "required_operators": 2,
        "expected_served_agency_agreement_version": expected_served_agency_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def create_drill_payload(**overrides) -> dict:
    defaults = {
        "title": "SET Drill",
        "scheduled_start": DEFAULTS["DRILL_START"],
        "scheduled_end": DEFAULTS["DRILL_END"],
    }
    defaults.update(overrides)
    return defaults


def create_drill_message_payload(drill_id, **overrides) -> dict:
    defaults = {"drill_id": drill_id, "precedence": "ROUTINE"}
    defaults.update(overrides)
    return defaults


def create_field_day_event_payload(**overrides) -> dict:
    defaults = {
        "name": "FD 2026",
        "start_at": DEFAULTS["EVENT_START"],
        "end_at": DEFAULTS["EVENT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_field_day_contact_payload(event_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "worked_callsign": "W1AW",
        "band": "B2M",
        "mode": "CW",
        "power_category": "QRP",
    }
    defaults.update(overrides)
    return defaults


def create_exam_session_payload(**overrides) -> dict:
    defaults = {
        "location": "Library",
        "scheduled_at": DEFAULTS["EXAM_SCHEDULED_AT"],
        "max_candidates": 5,
    }
    defaults.update(overrides)
    return defaults


def create_exam_candidate_payload(session_id, **overrides) -> dict:
    defaults = {
        "session_id": session_id,
        "candidate_name": "Candidate One",
        "frn": "0001112223",
        "element": "TECHNICIAN",
    }
    defaults.update(overrides)
    return defaults


def create_equipment_loan_payload(**overrides) -> dict:
    defaults = {
        "item_tag": "HT-1",
        "due_at": DEFAULTS["LOAN_DUE_AT"],
        "estimated_value_cents": DEFAULTS["LOAN_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults
