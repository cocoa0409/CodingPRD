"""Payload factories.

Each factory returns only client-supplied input fields; server-generated fields
(identifiers, timestamps, version tokens, derived money and FTE figures) are
never included.  Every factory accepts keyword overrides so a test can bend one
field without restating the rest.
"""

from .constants import (
    CANONICAL_COST_REPORT,
    CANONICAL_OTHER_PROVIDER,
    CANONICAL_PROVIDER,
    CANONICAL_UCC_DATA_SET,
    CANONICAL_WAGE_SUBMISSION,
)


def _merge(base, overrides):
    payload = dict(base)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


def provider_payload(**overrides):
    return _merge(CANONICAL_PROVIDER, overrides)


def other_provider_payload(**overrides):
    return _merge(CANONICAL_OTHER_PROVIDER, overrides)


# ---------------------------------------------------------------------------
# CostReport
# ---------------------------------------------------------------------------


def cost_report_payload(provider_id, **overrides):
    base = dict(CANONICAL_COST_REPORT)
    base["provider_id"] = provider_id
    return _merge(base, overrides)


# ---------------------------------------------------------------------------
# CostCenter
# ---------------------------------------------------------------------------


def cost_center_payload(
    code="03000",
    name="Adults and Pediatrics",
    center_type="ROUTINE",
    allocation_basis=None,
    stepdown_order=None,
    statistics=None,
    **overrides,
):
    payload = {
        "code": code,
        "name": name,
        "center_type": center_type,
        "statistics": dict(statistics) if statistics else {},
    }
    if allocation_basis is not None:
        payload["allocation_basis"] = allocation_basis
    if stepdown_order is not None:
        payload["stepdown_order"] = stepdown_order
    return _merge(payload, overrides)


def general_service_center_payload(
    code="00100",
    name="Administrative and General",
    allocation_basis="SQUARE_FEET",
    stepdown_order=1,
    statistics=None,
    **overrides,
):
    return cost_center_payload(
        code=code,
        name=name,
        center_type="GENERAL_SERVICE",
        allocation_basis=allocation_basis,
        stepdown_order=stepdown_order,
        statistics=statistics if statistics is not None else {},
        **overrides,
    )


# ---------------------------------------------------------------------------
# TrialBalanceLine
# ---------------------------------------------------------------------------


def trial_balance_line_payload(
    gl_account="6200",
    description="Nursing salaries",
    amount_cents=200000000,
    **overrides,
):
    payload = {
        "gl_account": gl_account,
        "description": description,
        "amount_cents": amount_cents,
    }
    return _merge(payload, overrides)


def map_payload(cost_center_id, **overrides):
    return _merge({"cost_center_id": cost_center_id}, overrides)


# ---------------------------------------------------------------------------
# WorkpaperEntry
# ---------------------------------------------------------------------------


def workpaper_leg(cost_center_id, amount_cents):
    return {"cost_center_id": cost_center_id, "amount_cents": amount_cents}


def reclassification_payload(
    legs,
    code="A6-4",
    description="Move administration effort to nursing and surgery",
    **overrides,
):
    payload = {
        "entry_type": "RECLASSIFICATION",
        "code": code,
        "description": description,
        "legs": list(legs),
    }
    return _merge(payload, overrides)


def adjustment_payload(
    legs,
    code="A8-1",
    description="Remove non allowable advertising cost",
    is_non_allowable=True,
    **overrides,
):
    payload = {
        "entry_type": "ADJUSTMENT",
        "code": code,
        "description": description,
        "legs": list(legs),
        "is_non_allowable": is_non_allowable,
    }
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# StepdownRun
# ---------------------------------------------------------------------------


def stepdown_run_payload(
    expected_cost_report_version, method="SINGLE_APPORTIONMENT", **overrides
):
    payload = {
        "expected_cost_report_version": expected_cost_report_version,
        "method": method,
    }
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# WageIndexSubmission and the occupational mix survey
# ---------------------------------------------------------------------------


def wage_index_submission_payload(**overrides):
    return _merge(CANONICAL_WAGE_SUBMISSION, overrides)


def occ_mix_response_payload(
    category="RN", reported_hours=1200000.00, reported_salaries_cents=4200000000, **overrides
):
    payload = {
        "category": category,
        "reported_hours": reported_hours,
        "reported_salaries_cents": reported_salaries_cents,
    }
    return _merge(payload, overrides)


def review_decision_payload(
    decision="ACCEPT", review_note="Desk review of the wage data is complete", **overrides
):
    payload = {"decision": decision, "review_note": review_note}
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Resident and RotationAssignment
# ---------------------------------------------------------------------------


def resident_payload(
    full_name="Dana Okafor", program="Internal Medicine", irp_status=None, **overrides
):
    payload = {"full_name": full_name, "program": program}
    if irp_status is not None:
        payload["irp_status"] = irp_status
    return _merge(payload, overrides)


def rotation_assignment_payload(
    cost_center_id,
    start_date="2025-07-01",
    end_date="2026-01-01",
    fte_fraction=0.6000,
    **overrides,
):
    payload = {
        "cost_center_id": cost_center_id,
        "start_date": start_date,
        "end_date": end_date,
        "fte_fraction": fte_fraction,
    }
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# UccDataSet
# ---------------------------------------------------------------------------


def ucc_data_set_payload(**overrides):
    return _merge(CANONICAL_UCC_DATA_SET, overrides)


# ---------------------------------------------------------------------------
# Settlement, AuditAdjustment, AppealCase
# ---------------------------------------------------------------------------


def settlement_payload(stage="TENTATIVE", **overrides):
    return _merge({"stage": stage}, overrides)


def audit_adjustment_payload(
    target_cost_center_id,
    code="AE-14",
    rationale="Operating room supplies overstated against invoices",
    proposed_amount_cents=-5000000,
    **overrides,
):
    payload = {
        "target_cost_center_id": target_cost_center_id,
        "code": code,
        "rationale": rationale,
        "proposed_amount_cents": proposed_amount_cents,
    }
    return _merge(payload, overrides)


def audit_response_payload(
    response="PROTEST",
    provider_response_note="Provider disputes the sampled supply invoices",
    **overrides,
):
    payload = {"response": response, "provider_response_note": provider_response_note}
    return _merge(payload, overrides)


def audit_resolution_payload(outcome="INCORPORATE", **overrides):
    return _merge({"outcome": outcome}, overrides)


def appeal_case_payload(
    settlement_id,
    kind="PRRB_APPEAL",
    issue_description="Disagreement over the allocation of laundry cost",
    amount_at_issue_cents=5000000,
    **overrides,
):
    payload = {
        "settlement_id": settlement_id,
        "kind": kind,
        "issue_description": issue_description,
        "amount_at_issue_cents": amount_at_issue_cents,
    }
    return _merge(payload, overrides)


def appeal_decision_payload(
    outcome="HEAR", decision_note="Board sets the matter down for hearing", **overrides
):
    payload = {"outcome": outcome, "decision_note": decision_note}
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# InterimRateRequest
# ---------------------------------------------------------------------------


def interim_rate_request_payload(
    provider_id,
    basis_cost_report_id,
    expected_provider_version,
    projected_discharges=500,
    trend_factor=0.2000,
    effective_from="2026-10-01",
    effective_to="2027-09-30",
    **overrides,
):
    payload = {
        "provider_id": provider_id,
        "expected_provider_version": expected_provider_version,
        "basis_cost_report_id": basis_cost_report_id,
        "projected_discharges": projected_discharges,
        "trend_factor": trend_factor,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    return _merge(payload, overrides)


def interim_rate_decision_payload(
    decision="APPROVE", decision_note="Rate approved for the requested period", **overrides
):
    payload = {"decision": decision, "decision_note": decision_note}
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def clock_payload(instant, **overrides):
    return _merge({"current_utc": instant}, overrides)
