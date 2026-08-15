"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_badge_seq = itertools.count(1000)
_label_seq = itertools.count(1)
_name_seq = itertools.count(1)


def _next_badge() -> str:
    return f"B-{next(_badge_seq)}"


def _next_label() -> str:
    return f"EOP-2026-{next(_label_seq)}"


def _next_name(prefix: str) -> str:
    return f"{prefix}-{next(_name_seq)}"


def hazard_entry(entry_key="HZ", hazard_name="Earthquake", category="NATURAL",
                 probability=2, severity=3, preparedness=1, **overrides):
    entry = {
        "entry_key": entry_key,
        "hazard_name": hazard_name,
        "category": category,
        "probability": probability,
        "severity": severity,
        "preparedness": preparedness,
    }
    entry.update(overrides)
    return entry


def create_staff_member_payload(**overrides):
    defaults = {
        "full_name": _next_name("Staff"),
        "badge_number": _next_badge(),
        "department": "EMERGENCY",
        "role_qualifications": [],
    }
    defaults.update(overrides)
    return defaults


def create_hazard_assessment_payload(**overrides):
    defaults = {
        "fiscal_year": "FY2026",
        "scoring_model": "TWO_FACTOR",
    }
    defaults.update(overrides)
    return defaults


def create_plan_revision_payload(**overrides):
    defaults = {
        "revision_label": _next_label(),
        "change_summary": "routine update",
        "effective_date": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_exercise_payload(plan_revision_id, **overrides):
    defaults = {
        "exercise_name": _next_name("Exercise"),
        "exercise_type": "TABLETOP",
        "scenario_category": "NATURAL",
        "scheduled_start": "2026-09-10T10:00:00Z",
        "scheduled_end": "2026-09-10T12:00:00Z",
        "plan_revision_id": plan_revision_id,
    }
    defaults.update(overrides)
    return defaults


def create_after_action_report_payload(subject_type, subject_id, **overrides):
    defaults = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "summary": "after-action findings",
    }
    defaults.update(overrides)
    return defaults


def create_improvement_task_payload(after_action_report_id, **overrides):
    defaults = {
        "after_action_report_id": after_action_report_id,
        "description": "corrective action",
        "priority": "MEDIUM",
        "due_date": "2026-08-10T00:00:00Z",
        "assigned_department": "LOGISTICS",
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides):
    defaults = {
        "incident_name": _next_name("MCI"),
        "incident_type": "NATURAL",
        "declared_at": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_command_assignment_payload(incident_id, staff_member_id, command_role,
                                      expected_incident_version, **overrides):
    defaults = {
        "incident_id": incident_id,
        "staff_member_id": staff_member_id,
        "command_role": command_role,
        "expected_incident_version": expected_incident_version,
    }
    defaults.update(overrides)
    return defaults


def create_callback_request_payload(incident_id, **overrides):
    defaults = {"incident_id": incident_id}
    defaults.update(overrides)
    return defaults


def create_supply_item_payload(**overrides):
    defaults = {
        "item_name": _next_name("Item"),
        "category": "PPE",
        "unit": "box",
        "reorder_min_days": 1,
    }
    defaults.update(overrides)
    return defaults


def create_stock_transaction_payload(supply_item_id, transaction_type, quantity,
                                     occurred_at="2026-07-30T09:00:00Z", **overrides):
    defaults = {
        "supply_item_id": supply_item_id,
        "transaction_type": transaction_type,
        "quantity": quantity,
        "occurred_at": occurred_at,
    }
    defaults.update(overrides)
    return defaults


def create_alternate_care_site_payload(**overrides):
    defaults = {
        "site_name": _next_name("Site"),
        "address": "1 Relief Way",
        "bed_capacity": 40,
    }
    defaults.update(overrides)
    return defaults


def create_site_commitment_payload(incident_id, window_start="2026-07-31T00:00:00Z",
                                   window_end="2026-08-05T00:00:00Z", **overrides):
    defaults = {
        "incident_id": incident_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_patient_record_payload(incident_id, patient_ref, **overrides):
    defaults = {
        "incident_id": incident_id,
        "patient_ref": patient_ref,
        "triage_category": "MINOR",
        "arrival_at": "2026-08-01T00:05:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_family_inquiry_payload(incident_id, sought_patient_ref, **overrides):
    defaults = {
        "incident_id": incident_id,
        "inquirer_name": _next_name("Caller"),
        "inquirer_phone": "555-0100",
        "sought_patient_ref": sought_patient_ref,
    }
    defaults.update(overrides)
    return defaults


def create_external_report_payload(**overrides):
    defaults = {
        "audience": "STATE_DOH",
        "report_type": "SITREP",
        "period_start": "2026-08-09T00:00:00Z",
        "period_end": "2026-08-10T00:00:00Z",
        "body_summary": "situation report body",
    }
    defaults.update(overrides)
    return defaults
