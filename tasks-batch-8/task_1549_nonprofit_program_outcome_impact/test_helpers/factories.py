"""Payload factories -- one per entity, input fields only (PRD section 3)."""
from .constants import (
    DEFAULT_CONSENT_EXPIRY, DEFAULT_CERTIFICATION_EXPIRY,
    DEFAULT_CYCLE_END, DEFAULT_CYCLE_START,
    DEFAULT_ENROLLMENT_END, DEFAULT_ENROLLMENT_START,
    DEFAULT_REPORTING_DUE,
)


def program_payload(name="Test Program", code="TP", **overrides) -> dict:
    payload = {"name": name, "code": code}
    payload.update(overrides)
    return payload


def funder_payload(name="Test Funder", code="FND", **overrides) -> dict:
    payload = {"name": name, "code": code}
    payload.update(overrides)
    return payload


def logic_model_payload(title="Logic Model", description="", **overrides) -> dict:
    payload = {"title": title, "description": description}
    payload.update(overrides)
    return payload


def indicator_payload(
    code="I1",
    level="OUTCOME",
    unit="SCORE",
    direction="HIGHER_IS_BETTER",
    baseline_value=0,
    target_value=100,
    weight=1.0,
    measurement_frequency="PER_EVENT",
    **overrides,
) -> dict:
    payload = {
        "code": code,
        "level": level,
        "unit": unit,
        "direction": direction,
        "baseline_value": baseline_value,
        "target_value": target_value,
        "weight": weight,
        "measurement_frequency": measurement_frequency,
    }
    payload.update(overrides)
    return payload


def cycle_payload(
    label="C1",
    enrollment_start=DEFAULT_ENROLLMENT_START,
    enrollment_end=DEFAULT_ENROLLMENT_END,
    cycle_start=DEFAULT_CYCLE_START,
    cycle_end=DEFAULT_CYCLE_END,
    reporting_due_date=DEFAULT_REPORTING_DUE,
    **overrides,
) -> dict:
    payload = {
        "label": label,
        "enrollment_start": enrollment_start,
        "enrollment_end": enrollment_end,
        "cycle_start": cycle_start,
        "cycle_end": cycle_end,
        "reporting_due_date": reporting_due_date,
    }
    payload.update(overrides)
    return payload


def participant_payload(external_ref="P-001", **overrides) -> dict:
    payload = {"external_ref": external_ref}
    payload.update(overrides)
    return payload


def consent_payload(
    form_version=1,
    scope="FULL",
    expires_at=DEFAULT_CONSENT_EXPIRY,
    **overrides,
) -> dict:
    payload = {
        "form_version": form_version,
        "scope": scope,
        "expires_at": expires_at,
    }
    payload.update(overrides)
    return payload


def instrument_payload(code="SURV", title="Survey", **overrides) -> dict:
    payload = {"code": code, "title": title}
    payload.update(overrides)
    return payload


def certification_payload(
    staff_user_id="collector-1",
    instrument_id=None,
    expires_at=DEFAULT_CERTIFICATION_EXPIRY,
    **overrides,
) -> dict:
    payload = {
        "staff_user_id": staff_user_id,
        "instrument_id": instrument_id,
        "expires_at": expires_at,
    }
    payload.update(overrides)
    return payload


def observation_payload(
    indicator_id=None,
    instrument_id=None,
    value=10,
    collected_at="2026-09-05T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "indicator_id": indicator_id,
        "instrument_id": instrument_id,
        "value": value,
        "collected_at": collected_at,
    }
    payload.update(overrides)
    return payload


def milestone_payload(
    indicator_id=None,
    due_date="2026-08-15T00:00:00Z",
    milestone_target=70,
    **overrides,
) -> dict:
    payload = {
        "indicator_id": indicator_id,
        "due_date": due_date,
        "milestone_target": milestone_target,
    }
    payload.update(overrides)
    return payload


def finding_payload(
    finding_type="MISSING_DATA",
    participant_id=None,
    description="",
    **overrides,
) -> dict:
    payload = {
        "finding_type": finding_type,
        "participant_id": participant_id,
        "description": description,
    }
    payload.update(overrides)
    return payload


def report_payload(
    funder_id=None,
    report_type="FUNDER_STANDARD",
    expected_program_cycle_version=None,
    **overrides,
) -> dict:
    payload = {
        "funder_id": funder_id,
        "report_type": report_type,
        "expected_program_cycle_version": expected_program_cycle_version,
    }
    payload.update(overrides)
    return payload


def engagement_payload(
    vendor_name="EvalCo",
    scope_program_cycle_ids=None,
    access_start="2026-09-01T00:00:00Z",
    access_end="2026-10-01T00:00:00Z",
    deliverable_due="2026-10-10T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "vendor_name": vendor_name,
        "scope_program_cycle_ids": list(scope_program_cycle_ids or []),
        "access_start": access_start,
        "access_end": access_end,
        "deliverable_due": deliverable_due,
    }
    payload.update(overrides)
    return payload


def improvement_action_payload(
    title="Tighten SOP",
    description="retrain collectors",
    **overrides,
) -> dict:
    payload = {"title": title, "description": description}
    payload.update(overrides)
    return payload
