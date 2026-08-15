"""Payload factories — one per entity, input fields only (PRD §3).

Factories accept keyword overrides; optional fields are included only when
explicitly supplied so tests can exercise server-side defaults.
"""
from .constants import STANDARD_MATRIX

DEFAULTS = {
    "EASEMENT_NAME": "Test Easement",
    "GRANTOR_NAME": "Grantor",
    "PARCEL_ACREAGE": 500,
    "OWNER_NAME": "Owner One",
    "CONTACT_EMAIL": "owner@example.org",
    "PREPARED_BY": "staff-prep-1",
    "CONDITION_NARRATIVE": "Intact forest and wetland values documented.",
    "MONITOR_USER_ID": "mon-1",
    "DETECTED_BY": "coord-9",
    "SUBMITTED_BY": "coord-1",
    "JUSTIFICATION": "Selective low-impact use consistent with conservation values.",
    "APPRAISER_USER_ID": "appr-1",
    "SPENDING_RATE_BPS": 400,
    "PRINCIPAL_FLOOR_CENTS": 100000,
}


def create_easement_payload(
    easement_name=None,
    grantor_name=None,
    parcel_acreage=None,
    permitted_use_matrix=None,
    monitoring_interval_months=None,
    **overrides,
) -> dict:
    payload = {
        "easement_name": easement_name or DEFAULTS["EASEMENT_NAME"],
        "grantor_name": grantor_name or DEFAULTS["GRANTOR_NAME"],
        "parcel_acreage": parcel_acreage if parcel_acreage is not None else DEFAULTS["PARCEL_ACREAGE"],
        "permitted_use_matrix": dict(permitted_use_matrix or STANDARD_MATRIX),
    }
    if monitoring_interval_months is not None:
        payload["monitoring_interval_months"] = monitoring_interval_months
    payload.update(overrides)
    return payload


def create_landowner_payload(easement_id, owner_name=None, contact_email=None, **overrides) -> dict:
    payload = {
        "easement_id": easement_id,
        "owner_name": owner_name or DEFAULTS["OWNER_NAME"],
        "contact_email": contact_email or DEFAULTS["CONTACT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_baseline_report_payload(
    easement_id,
    prepared_by_user_id=None,
    condition_narrative=None,
    photo_point_count=5,
    **overrides,
) -> dict:
    payload = {
        "easement_id": easement_id,
        "prepared_by_user_id": prepared_by_user_id or DEFAULTS["PREPARED_BY"],
        "condition_narrative": condition_narrative or DEFAULTS["CONDITION_NARRATIVE"],
        "photo_point_count": photo_point_count,
    }
    payload.update(overrides)
    return payload


def create_monitoring_visit_payload(
    easement_id,
    monitor_user_id=None,
    window_start_on="2026-09-01",
    window_end_on="2026-09-10",
    **overrides,
) -> dict:
    payload = {
        "easement_id": easement_id,
        "monitor_user_id": monitor_user_id or DEFAULTS["MONITOR_USER_ID"],
        "window_start_on": window_start_on,
        "window_end_on": window_end_on,
    }
    payload.update(overrides)
    return payload


def complete_visit_payload(
    actual_visit_on="2026-09-05",
    findings_summary="All quiet on the parcel.",
    stewardship_cost_cents=18000,
    **overrides,
) -> dict:
    payload = {
        "actual_visit_on": actual_visit_on,
        "findings_summary": findings_summary,
        "stewardship_cost_cents": stewardship_cost_cents,
    }
    payload.update(overrides)
    return payload


def create_violation_payload(
    easement_id,
    detected_by_user_id=None,
    violation_type="SUBDIVISION",
    severity="MINOR",
    detected_on="2026-08-02",
    monitoring_visit_id=None,
    **overrides,
) -> dict:
    payload = {
        "easement_id": easement_id,
        "detected_by_user_id": detected_by_user_id or DEFAULTS["DETECTED_BY"],
        "violation_type": violation_type,
        "severity": severity,
        "detected_on": detected_on,
    }
    if monitoring_visit_id is not None:
        payload["monitoring_visit_id"] = monitoring_visit_id
    payload.update(overrides)
    return payload


def create_amendment_request_payload(
    easement_id,
    expected_easement_version,
    submitted_by_user_id=None,
    requested_changes=None,
    affected_acreage=100,
    **overrides,
) -> dict:
    if requested_changes is None:
        requested_changes = [{"use_type": "SUBDIVISION", "new_level": "DISCRETIONARY"}]
    payload = {
        "easement_id": easement_id,
        "expected_easement_version": expected_easement_version,
        "submitted_by_user_id": submitted_by_user_id or DEFAULTS["SUBMITTED_BY"],
        "requested_changes": requested_changes,
        "affected_acreage": affected_acreage,
    }
    payload.update(overrides)
    return payload


def resubmit_amendment_payload(requested_changes, affected_acreage, **overrides) -> dict:
    payload = {
        "requested_changes": requested_changes,
        "affected_acreage": affected_acreage,
    }
    payload.update(overrides)
    return payload


def create_use_authorization_payload(
    easement_id,
    use_type="TIMBER_HARVEST",
    justification=None,
    **overrides,
) -> dict:
    payload = {
        "easement_id": easement_id,
        "use_type": use_type,
        "justification": justification or DEFAULTS["JUSTIFICATION"],
    }
    payload.update(overrides)
    return payload


def decide_use_authorization_payload(decision, conditions=None, decision_reason=None, **overrides) -> dict:
    payload = {"decision": decision}
    if conditions is not None:
        payload["conditions"] = conditions
    if decision_reason is not None:
        payload["decision_reason"] = decision_reason
    payload.update(overrides)
    return payload


def create_succession_notice_payload(
    easement_id,
    successor_owner_name="Owner Two",
    successor_contact_email="successor@example.org",
    transfer_on="2026-09-15",
    **overrides,
) -> dict:
    payload = {
        "easement_id": easement_id,
        "successor_owner_name": successor_owner_name,
        "successor_contact_email": successor_contact_email,
        "transfer_on": transfer_on,
    }
    payload.update(overrides)
    return payload


def record_succession_notice_payload(expected_easement_version, **overrides) -> dict:
    payload = {"expected_easement_version": expected_easement_version}
    payload.update(overrides)
    return payload


def create_appraisal_payload(
    easement_id,
    appraiser_user_id=None,
    effective_on="2026-08-15",
    gift_on="2026-09-01",
    contiguous_enhancement_applies=False,
    **overrides,
) -> dict:
    payload = {
        "easement_id": easement_id,
        "appraiser_user_id": appraiser_user_id or DEFAULTS["APPRAISER_USER_ID"],
        "effective_on": effective_on,
        "gift_on": gift_on,
        "contiguous_enhancement_applies": contiguous_enhancement_applies,
    }
    payload.update(overrides)
    return payload


def deliver_appraisal_payload(
    before_value_cents=90000000,
    after_value_cents=55000000,
    enhancement_value_cents=None,
    **overrides,
) -> dict:
    payload = {
        "before_value_cents": before_value_cents,
        "after_value_cents": after_value_cents,
    }
    if enhancement_value_cents is not None:
        payload["enhancement_value_cents"] = enhancement_value_cents
    payload.update(overrides)
    return payload


def create_endowment_fund_payload(
    easement_id,
    spending_rate_bps=None,
    principal_floor_cents=None,
    **overrides,
) -> dict:
    payload = {
        "easement_id": easement_id,
        "spending_rate_bps": spending_rate_bps if spending_rate_bps is not None else DEFAULTS["SPENDING_RATE_BPS"],
        "principal_floor_cents": principal_floor_cents if principal_floor_cents is not None else DEFAULTS["PRINCIPAL_FLOOR_CENTS"],
    }
    payload.update(overrides)
    return payload


def post_amount_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def post_draw_payload(amount_cents, purpose, expected_fund_version, **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "purpose": purpose,
        "expected_fund_version": expected_fund_version,
    }
    payload.update(overrides)
    return payload


def execute_enforcement_payload(
    agreement_terms="Restore the disturbed area within 60 days.",
    remediation_cost_cents=12000000,
    **overrides,
) -> dict:
    payload = {
        "agreement_terms": agreement_terms,
        "remediation_cost_cents": remediation_cost_cents,
    }
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
