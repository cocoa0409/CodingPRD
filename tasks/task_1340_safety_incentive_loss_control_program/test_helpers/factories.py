"""Payload factories — one per creatable entity, input fields only."""
from .constants import (
    DEFAULT_ELR_BY_CLASS,
    DEFAULT_PAYROLL_BY_CLASS,
    TEST_DEFAULTS,
)


def create_program_payload(**overrides) -> dict:
    defaults = {
        "program_year": TEST_DEFAULTS["PROGRAM_YEAR"],
        "scoring_variant": "LEADING_ONLY",
        "incentive_budget_cents": TEST_DEFAULTS["INCENTIVE_BUDGET_CENTS"],
        "observation_target_rate": TEST_DEFAULTS["OBSERVATION_TARGET_RATE"],
        "exposure_hours": TEST_DEFAULTS["EXPOSURE_HOURS"],
        "payroll_by_class": [dict(row) for row in DEFAULT_PAYROLL_BY_CLASS],
        "elr_by_class": [dict(row) for row in DEFAULT_ELR_BY_CLASS],
    }
    defaults.update(overrides)
    return defaults


def create_job_role_payload(title="Laborer", hazard_class="LOW",
                            required_course_ids=None) -> dict:
    payload = {"title": title, "hazard_class": hazard_class}
    if required_course_ids is not None:
        payload["required_course_ids"] = list(required_course_ids)
    return payload


def create_training_course_payload(title="HAZCOM", hazard_class="LOW",
                                   validity_months=12,
                                   renewal_window_days=None) -> dict:
    payload = {"title": title, "hazard_class": hazard_class,
               "validity_months": validity_months}
    if renewal_window_days is not None:
        payload["renewal_window_days"] = renewal_window_days
    return payload


def create_employee_payload(full_name="Ann A", job_role_id=None, hired_on="2026-01-05",
                            committee_member=None) -> dict:
    payload = {"full_name": full_name, "job_role_id": job_role_id,
               "hired_on": hired_on}
    if committee_member is not None:
        payload["committee_member"] = committee_member
    return payload


def create_training_assignment_payload(employee_id, course_id,
                                       due_date="2026-06-20T00:00:00Z") -> dict:
    return {"employee_id": employee_id, "course_id": course_id, "due_date": due_date}


def create_hazard_payload(program_id, location="L1", description="Spill",
                          identified_by=None) -> dict:
    return {"program_id": program_id, "location": location,
            "description": description, "identified_by": identified_by}


def create_control_payload(description="Fix it", implementer_id=None,
                           due_date="2026-06-20T00:00:00Z") -> dict:
    return {"description": description, "implementer_id": implementer_id,
            "due_date": due_date}


def create_observation_payload(program_id, reporter_id, kind="OBSERVATION",
                               description="Observed condition",
                               occurred_at="2026-05-30T00:00:00Z") -> dict:
    return {"program_id": program_id, "reporter_id": reporter_id, "kind": kind,
            "description": description, "occurred_at": occurred_at}


def create_meeting_payload(program_id, scheduled_start="2026-06-10T09:00:00Z",
                           scheduled_end="2026-06-10T10:00:00Z",
                           location="Room 1") -> dict:
    return {"program_id": program_id, "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end, "location": location}


def create_action_item_payload(assignee_id, description="Follow up",
                               due_date="2026-06-20T00:00:00Z",
                               hazard_id=None) -> dict:
    payload = {"assignee_id": assignee_id, "description": description,
               "due_date": due_date}
    if hazard_id is not None:
        payload["hazard_id"] = hazard_id
    return payload


def create_contractor_payload(name="Acme Erectors",
                              contact_email="safety@acme.example", emr=0.50,
                              trir=0.0, safety_audit_pct=80,
                              insurance_cert_expires_on="2026-12-15") -> dict:
    return {"name": name, "contact_email": contact_email, "emr": emr,
            "trir": trir, "safety_audit_pct": safety_audit_pct,
            "insurance_cert_expires_on": insurance_cert_expires_on}


def create_claim_payload(program_id, occurred_on="2026-03-01", kind="INDEMNITY",
                         incurred_cents=100_000, employee_id=None,
                         contractor_org_id=None) -> dict:
    payload = {"program_id": program_id, "occurred_on": occurred_on, "kind": kind,
               "incurred_cents": incurred_cents}
    if employee_id is not None:
        payload["employee_id"] = employee_id
    if contractor_org_id is not None:
        payload["contractor_org_id"] = contractor_org_id
    return payload


def create_recommendation_payload(program_id, carrier_name="Acme Mutual",
                                  priority="HIGH",
                                  description="Install machine guarding",
                                  due_date="2026-09-01T00:00:00Z") -> dict:
    return {"program_id": program_id, "carrier_name": carrier_name,
            "priority": priority, "description": description, "due_date": due_date}


def create_emr_forecast_payload(program_id, expected_program_version,
                                as_of=None) -> dict:
    payload = {"program_id": program_id,
               "expected_program_version": expected_program_version}
    if as_of is not None:
        payload["as_of"] = as_of
    return payload
