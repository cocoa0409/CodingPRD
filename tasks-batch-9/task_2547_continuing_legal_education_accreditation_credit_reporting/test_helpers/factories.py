"""Payload factories — one per record type, client-supplied fields only."""
import itertools

_counter = itertools.count(1)


def unique_suffix() -> str:
    return str(next(_counter)).zfill(4)


DEFAULTS = {
    "PROVIDER_NAME": "Harborline Continuing Education",
    "COURSE_TITLE": "Advanced Civil Procedure",
    "ATTORNEY_NAME": "Dana Whitfield",
    "PRINCIPAL_OFFICE": "ST",
    "STATEMENT": "I affirm that the credits reported for this period are accurate.",
    "ALLEGATION": "The advertised faculty never appeared at the advertised session.",
}


def create_provider_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PROVIDER_NAME"],
        "provider_type": "BAR_ASSOCIATION",
    }
    payload.update(overrides)
    return payload


def accreditation_action_payload(action, expected_provider_version, **overrides) -> dict:
    payload = {
        "action": action,
        "expected_provider_version": expected_provider_version,
    }
    payload.update(overrides)
    return payload


def create_course_payload(**overrides) -> dict:
    payload = {
        "title": DEFAULTS["COURSE_TITLE"],
        "delivery_format": "LIVE_IN_PERSON",
        "total_minutes": 180,
        "presented_at": "2026-06-01T09:00:00Z",
        "attendance_verification_method": "ATTENDANCE_CODE",
        "credit_allocations": [{"category": "GENERAL", "minutes": 180}],
    }
    payload.update(overrides)
    return payload


def credit_allocation_entry(category, minutes) -> dict:
    return {"category": category, "minutes": minutes}


def review_action_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def appellant_action_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def appeal_decision_payload(disposition, **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload


def create_attorney_payload(**overrides) -> dict:
    payload = {
        "bar_number": "BAR-" + unique_suffix(),
        "full_name": DEFAULTS["ATTORNEY_NAME"],
        "admission_date": "2010-01-01T00:00:00Z",
        "compliance_group": "GROUP_1",
        "principal_office_jurisdiction": DEFAULTS["PRINCIPAL_OFFICE"],
    }
    payload.update(overrides)
    return payload


def status_change_payload(status, **overrides) -> dict:
    payload = {"status": status}
    payload.update(overrides)
    return payload


def create_compliance_cycle_payload(**overrides) -> dict:
    payload = {
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2028-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def reinstatement_payload(cycle_id, cure_basis="FEES_AND_CREDITS_CURED", **overrides) -> dict:
    payload = {"cycle_id": cycle_id, "cure_basis": cure_basis}
    payload.update(overrides)
    return payload


def create_affirmation_payload(affirmation_type, **overrides) -> dict:
    payload = {
        "affirmation_type": affirmation_type,
        "statement": DEFAULTS["STATEMENT"],
    }
    payload.update(overrides)
    return payload


def certification_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def create_credit_record_payload(attorney_id, course_id, **overrides) -> dict:
    payload = {
        "attorney_id": attorney_id,
        "course_id": course_id,
        "verification_method": "CERTIFICATE",
        "attended_minutes": 180,
        "completion_date": "2026-06-01T12:00:00Z",
        "certificate_reference": "CERT-" + unique_suffix(),
    }
    payload.update(overrides)
    return payload


def adjudication_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def create_attendance_report_payload(course_id, session_date, entries, **overrides) -> dict:
    payload = {
        "course_id": course_id,
        "session_date": session_date,
        "entries": entries,
    }
    payload.update(overrides)
    return payload


def roster_entry(bar_number, attended_minutes) -> dict:
    return {"bar_number": bar_number, "attended_minutes": attended_minutes}


def create_reciprocity_claim_payload(attorney_id, expected_attorney_version, **overrides) -> dict:
    payload = {
        "attorney_id": attorney_id,
        "basis": "RECIPROCITY",
        "origin_jurisdiction": "CA",
        "origin_course_title": "California Civil Discovery Update",
        "origin_credit_hours": 3.0,
        "origin_category": "GENERAL",
        "completion_date": "2026-06-01T00:00:00Z",
        "expected_attorney_version": expected_attorney_version,
    }
    payload.update(overrides)
    return payload


def determination_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def create_provider_audit_payload(provider_id, **overrides) -> dict:
    payload = {
        "provider_id": provider_id,
        "audit_period_start": "2026-01-01T00:00:00Z",
        "audit_period_end": "2026-06-30T00:00:00Z",
        "trigger_type": "RANDOM",
    }
    payload.update(overrides)
    return payload


def audit_action_payload(action, expected_audit_version, **overrides) -> dict:
    payload = {"action": action, "expected_audit_version": expected_audit_version}
    payload.update(overrides)
    return payload


def create_complaint_payload(subject_type, subject_id, **overrides) -> dict:
    payload = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "allegation": DEFAULTS["ALLEGATION"],
        "allegation_category": "NO_SHOW_FACULTY",
    }
    payload.update(overrides)
    return payload


def disposition_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def settlement_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload
