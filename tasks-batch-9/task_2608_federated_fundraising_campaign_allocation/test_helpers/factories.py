"""Payload builders.

Each builder returns the minimal valid payload the PRD declares for one write,
with every value overridable so a test can pin exactly the figures its
assertion depends on. Defaults are chosen to be uncontroversially valid: they
never sit on a boundary the caller might be probing.
"""

import itertools
import json
from typing import Any, Dict, List, Optional

_COUNTER = itertools.count(1)


def unique_suffix() -> str:
    """A per-process monotonic suffix for globally unique fields."""
    return str(next(_COUNTER)).zfill(4)


def as_number(value: Any) -> Any:
    """Emit a decimal-carrying field as a JSON *number*.

    PRD 2.5: "All monetary amounts are decimal numbers carried to exactly 2
    decimal places and rounded half up." PRD 2.10 gate 3 rejects "every value
    matching its declared type" with `ERR_INVALID_REQUEST`, so a money, ratio or
    numeric-measure field has to travel as a JSON number rather than as a
    quoted string. Test authors write these figures as readable decimal literals
    such as ``"1000.00"``; this converts them to the declared type at the last
    moment while leaving a value that is not numeric at all untouched, so a test
    that deliberately probes the declared-type gate still sends its bad value
    through verbatim.
    """
    if isinstance(value, str):
        try:
            parsed = json.loads(value.strip())
        except ValueError:
            return value
        if isinstance(parsed, bool) or not isinstance(parsed, (int, float)):
            return value
        return parsed
    return value


# ---------------------------------------------------------------------
# Employers and coordinators (PRD 3.1)
# ---------------------------------------------------------------------
def employer_payload(
    legal_name: Optional[str] = None,
    employee_count: int = 500,
    payroll_periods_per_year: Optional[int] = None,
    historical_shrinkage_rate_bps: Optional[int] = None,
    partnership_signed: Optional[bool] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name or f"Northgate Manufacturing {unique_suffix()}",
        "employee_count": employee_count,
    }
    if payroll_periods_per_year is not None:
        payload["payroll_periods_per_year"] = payroll_periods_per_year
    if historical_shrinkage_rate_bps is not None:
        payload["historical_shrinkage_rate_bps"] = historical_shrinkage_rate_bps
    if partnership_signed is not None:
        payload["partnership_signed"] = partnership_signed
    payload.update(extra)
    return payload


def coordinator_payload(
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    coordinator_role: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Dana Whitfield {suffix}",
        "email": email or f"dana.whitfield.{suffix}@northgate.example",
    }
    if coordinator_role is not None:
        payload["coordinator_role"] = coordinator_role
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------
# Campaigns (PRD 3.2)
# ---------------------------------------------------------------------
def campaign_payload(
    employer_id: str,
    campaign_year: int = 2026,
    solicitation_start_date: str = "2026-09-01",
    solicitation_end_date: str = "2026-09-30",
    loss_reserve_amount: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "employer_id": employer_id,
        "campaign_year": campaign_year,
        "solicitation_start_date": solicitation_start_date,
        "solicitation_end_date": solicitation_end_date,
    }
    if loss_reserve_amount is not None:
        payload["loss_reserve_amount"] = as_number(loss_reserve_amount)
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------
# Pledges, designation lines, remittances, write-offs (PRD 3.3 - 3.5)
# ---------------------------------------------------------------------
def designation_line(agency_id: str, designated_amount: str) -> Dict[str, Any]:
    """One element of a `designations` array: exactly two members (PRD 3.3)."""
    return {"agency_id": agency_id, "designated_amount": as_number(designated_amount)}


def pledge_payload(
    donor_reference: Optional[str] = None,
    giving_method: str = "PAYROLL_DEDUCTION",
    gross_amount: str = "1000.00",
    designations: Optional[List[Dict[str, Any]]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "donor_reference": donor_reference or f"DONOR-{unique_suffix()}",
        "giving_method": giving_method,
        "gross_amount": as_number(gross_amount),
    }
    if designations is not None:
        payload["designations"] = designations
    payload.update(extra)
    return payload


def amend_payload(
    expected_pledge_version: int,
    designations: List[Dict[str, Any]],
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_pledge_version": expected_pledge_version,
        "designations": designations,
    }
    payload.update(extra)
    return payload


def collection_payload(
    amount: str,
    remitted_on: str = "2026-08-01",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount": as_number(amount), "remitted_on": remitted_on}
    payload.update(extra)
    return payload


def write_off_payload(reason_code: str = "TERMINATION", **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason_code": reason_code}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------
# Agencies and financial reviews (PRD 3.6)
# ---------------------------------------------------------------------
_EIN_COUNTER = itertools.count(100000001)


def unique_ein() -> str:
    """Exactly nine digits, globally unique across all agencies (PRD 3.6)."""
    return str(next(_EIN_COUNTER))


def agency_payload(
    legal_name: Optional[str] = None,
    ein: Optional[str] = None,
    primary_priority_area: str = "BASIC_NEEDS",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name or f"Riverside Community Services {unique_suffix()}",
        "ein": ein or unique_ein(),
        "primary_priority_area": primary_priority_area,
    }
    payload.update(extra)
    return payload


def agency_review_payload(
    fiscal_year: int = 2025,
    program_expense_ratio: str = "0.7800",
    admin_expense_ratio: str = "0.1900",
    months_operating_reserve: str = "4.00",
    governance_checklist_passed_count: int = 8,
    audit_opinion: str = "UNQUALIFIED",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "fiscal_year": fiscal_year,
        "program_expense_ratio": as_number(program_expense_ratio),
        "admin_expense_ratio": as_number(admin_expense_ratio),
        "months_operating_reserve": as_number(months_operating_reserve),
        "governance_checklist_passed_count": governance_checklist_passed_count,
        "audit_opinion": audit_opinion,
    }
    payload.update(extra)
    return payload


def certify_payload(
    audited_program_expense_ratio: str = "0.7800",
    audited_admin_expense_ratio: str = "0.1900",
    audited_months_operating_reserve: str = "4.00",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "audited_program_expense_ratio": as_number(audited_program_expense_ratio),
        "audited_admin_expense_ratio": as_number(audited_admin_expense_ratio),
        "audited_months_operating_reserve": as_number(audited_months_operating_reserve),
    }
    payload.update(extra)
    return payload


def reinstate_payload(
    justification: str = "Corrective action plan completed and verified.",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"justification": justification}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------
# Panelists, cycles and panel seats (PRD 3.7)
# ---------------------------------------------------------------------
def panelist_payload(
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    expertise_area: str = "BASIC_NEEDS",
    **extra: Any,
) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Marisol Vega {suffix}",
        "email": email or f"marisol.vega.{suffix}@volunteers.example",
        "expertise_area": expertise_area,
    }
    payload.update(extra)
    return payload


_CYCLE_YEAR_COUNTER = itertools.count(2026)


def unique_cycle_year() -> int:
    """`cycle_year` is unique across all cycles (PRD 3.7)."""
    return next(_CYCLE_YEAR_COUNTER)


def allocation_cycle_payload(
    cycle_year: Optional[int] = None,
    focus_priority_area: str = "BASIC_NEEDS",
    opening_undesignated_pool: str = "500000.00",
    max_award_per_agency: str = "200000.00",
    request_window_start: str = "2026-07-01",
    request_window_end: str = "2026-12-31",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_year": unique_cycle_year() if cycle_year is None else cycle_year,
        "focus_priority_area": focus_priority_area,
        "opening_undesignated_pool": as_number(opening_undesignated_pool),
        "max_award_per_agency": as_number(max_award_per_agency),
        "request_window_start": request_window_start,
        "request_window_end": request_window_end,
    }
    payload.update(extra)
    return payload


def panel_assignment_payload(
    panelist_id: str,
    conflict_declared: Optional[bool] = None,
    assignment_role: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"panelist_id": panelist_id}
    if conflict_declared is not None:
        payload["conflict_declared"] = conflict_declared
    if assignment_role is not None:
        payload["assignment_role"] = assignment_role
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------
# Allocation requests, scores and awards (PRD 3.7 - 3.8)
# ---------------------------------------------------------------------
def allocation_request_payload(
    cycle_id: str,
    agency_id: str,
    requested_amount: str = "40000.00",
    priority_area: str = "BASIC_NEEDS",
    narrative_summary: str = "Expanding the emergency food pantry to six days a week.",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_id": cycle_id,
        "agency_id": agency_id,
        "requested_amount": as_number(requested_amount),
        "priority_area": priority_area,
        "narrative_summary": narrative_summary,
    }
    payload.update(extra)
    return payload


def panel_score_payload(
    priority_alignment_score: int = 80,
    outcome_evidence_score: int = 80,
    capacity_score: int = 80,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "priority_alignment_score": priority_alignment_score,
        "outcome_evidence_score": outcome_evidence_score,
        "capacity_score": capacity_score,
    }
    payload.update(extra)
    return payload


def award_payload(
    request_id: str,
    expected_allocation_cycle_version: int,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "request_id": request_id,
        "expected_allocation_cycle_version": expected_allocation_cycle_version,
    }
    payload.update(extra)
    return payload


def rescind_payload(reason_code: str = "AGENCY_WITHDRAWAL", **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason_code": reason_code}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------
# Outcome reports and monitoring site visits (PRD 3.9)
# ---------------------------------------------------------------------
def outcome_report_payload(
    reporting_period_end: str = "2026-12-31",
    persons_served: int = 1200,
    outcome_metric_name: str = "Households achieving food security",
    outcome_metric_value: str = "870",
    funds_expended: str = "0.00",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reporting_period_end": reporting_period_end,
        "persons_served": persons_served,
        "outcome_metric_name": outcome_metric_name,
        "outcome_metric_value": as_number(outcome_metric_value),
        "funds_expended": as_number(funds_expended),
    }
    payload.update(extra)
    return payload


def site_visit_payload(
    site_visit_window_start: str,
    site_visit_window_end: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_visit_window_start": site_visit_window_start,
        "site_visit_window_end": site_visit_window_end,
    }
    payload.update(extra)
    return payload


def site_visit_findings_payload(
    site_visit_findings: str = "Pantry operations observed; records reconcile to the report.",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"site_visit_findings": site_visit_findings}
    payload.update(extra)
    return payload


def revision_request_payload(
    revision_note: str = "Restate funds expended to exclude the capital purchase.",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"revision_note": revision_note}
    payload.update(extra)
    return payload


def resubmit_payload(
    persons_served: int = 1200,
    outcome_metric_value: str = "870",
    funds_expended: str = "0.00",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "persons_served": persons_served,
        "outcome_metric_value": as_number(outcome_metric_value),
        "funds_expended": as_number(funds_expended),
    }
    payload.update(extra)
    return payload


def clock_payload(to_iso8601: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(extra)
    return payload
