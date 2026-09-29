"""Payload factories: request bodies built from *input* fields only.

Every factory returns a plain dict containing only client-supplied fields; all
system-generated, computed and roll-up fields are deliberately absent so that
tests never smuggle a server-owned value into a request. ``**overrides`` lets a
recipe pin or delete any field (pass ``None`` explicitly where the PRD allows a
null).
"""

from .constants import (
    FILING_DEADLINE_DATE,
    FURNISHING_DEADLINE_DATE,
    TAX_YEAR,
    TIER2_CUTOFF_DATE,
)

_UNSET = object()


def _merge(base, overrides):
    payload = dict(base)
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _UNSET}


# ---------------------------------------------------------------------------
# FilingSeason (PRD §3.1)
# ---------------------------------------------------------------------------
def filing_season_payload(**overrides):
    return _merge(
        {
            "tax_year": TAX_YEAR,
            "furnishing_deadline_date": FURNISHING_DEADLINE_DATE,
            "filing_deadline_date": FILING_DEADLINE_DATE,
            "tier2_cutoff_date": TIER2_CUTOFF_DATE,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# ControlledGroup (PRD §3.1)
# ---------------------------------------------------------------------------
def controlled_group_payload(filing_season_id, **overrides):
    return _merge(
        {"filing_season_id": filing_season_id, "name": "Northwind Aggregated Group"},
        overrides,
    )


def ale_determination_payload(expected_controlled_group_version, **overrides):
    return _merge(
        {
            "basis": "AGGREGATED",
            "expected_controlled_group_version": expected_controlled_group_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# GroupMember (PRD §3.1)
# ---------------------------------------------------------------------------
def group_member_payload(controlled_group_id, ein="123456789", **overrides):
    return _merge(
        {
            "controlled_group_id": controlled_group_id,
            "ein": ein,
            "legal_name": "Northwind Operating LLC",
            "ownership_pct": 100.0,
            "measurement_method": "MONTHLY",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# MonthlyHeadcount batch (PRD §3.1, §2.11)
# ---------------------------------------------------------------------------
def monthly_headcounts_payload(
    group_member_id,
    months,
    count_year="PRIOR_YEAR",
    full_time_employee_count=40,
    part_time_hours_total=1200,
    total_employee_count=60,
    **overrides,
):
    """One call creates one row per entry of ``months``, all sharing the counts."""
    return _merge(
        {
            "group_member_id": group_member_id,
            "count_year": count_year,
            "months": list(months),
            "full_time_employee_count": full_time_employee_count,
            "part_time_hours_total": part_time_hours_total,
            "total_employee_count": total_employee_count,
        },
        overrides,
    )


def full_year_headcounts_payload(group_member_id, count_year="PRIOR_YEAR", **overrides):
    return monthly_headcounts_payload(
        group_member_id, list(range(1, 13)), count_year=count_year, **overrides
    )


# ---------------------------------------------------------------------------
# MeasurementCycle (PRD §3.3)
# ---------------------------------------------------------------------------
def measurement_cycle_payload(group_member_id, **overrides):
    return _merge(
        {
            "group_member_id": group_member_id,
            "employee_id": None,
            "cycle_type": "STANDARD",
            "measurement_start_date": "2025-01-01",
            "measurement_end_date": "2025-12-31",
            "admin_period_end_date": "2025-12-31",
            "stability_start_date": "2026-01-01",
            "stability_end_date": "2026-12-31",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Employee (PRD §3.3)
# ---------------------------------------------------------------------------
def employee_payload(group_member_id, full_name="Dana Rivers", **overrides):
    return _merge(
        {
            "group_member_id": group_member_id,
            "full_name": full_name,
            "ssn_last4": "4321",
            "hire_date": "2025-01-01",
            "employment_type": "FULL_TIME",
            "is_hourly": True,
            "hourly_rate_cents": 1500,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# HoursRecord batch (PRD §3.3, §2.11)
# ---------------------------------------------------------------------------
def hours_records_payload(
    employee_id,
    measurement_year,
    months,
    hours_of_service=160,
    paid_leave_hours=0,
    special_unpaid_leave_hours=0,
    **overrides,
):
    """One call creates one row per entry of ``months``, all sharing the hours."""
    return _merge(
        {
            "employee_id": employee_id,
            "measurement_year": measurement_year,
            "months": list(months),
            "hours_of_service": hours_of_service,
            "paid_leave_hours": paid_leave_hours,
            "special_unpaid_leave_hours": special_unpaid_leave_hours,
        },
        overrides,
    )


def full_year_hours_payload(employee_id, measurement_year, **overrides):
    return hours_records_payload(employee_id, measurement_year, list(range(1, 13)), **overrides)


# ---------------------------------------------------------------------------
# EmploymentEvent (PRD §3.4)
# ---------------------------------------------------------------------------
def employment_event_payload(employee_id, event_type, effective_date, **overrides):
    return _merge(
        {
            "employee_id": employee_id,
            "event_type": event_type,
            "effective_date": effective_date,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# CoverageOffer (PRD §3.6)
# ---------------------------------------------------------------------------
def coverage_offer_payload(
    employee_id,
    offer_kind="MEC_MV_FAMILY",
    effective_start_date="2026-01-01",
    effective_end_date="2027-01-01",
    **overrides,
):
    return _merge(
        {
            "employee_id": employee_id,
            "offer_kind": offer_kind,
            "minimum_value": True,
            "lowest_cost_self_only_cents": 17800,
            "effective_start_date": effective_start_date,
            "effective_end_date": effective_end_date,
            "offers_spouse": True,
            "offers_dependents": True,
            "conditional_spouse_offer": False,
            "enrolled": False,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# FurnishingConsent (PRD §3.7)
# ---------------------------------------------------------------------------
def furnishing_consent_payload(employee_id, **overrides):
    return _merge(
        {"employee_id": employee_id, "electronic_address": "dana.rivers@example.com"},
        overrides,
    )


def furnish_payload(delivery_channel="PAPER", **overrides):
    return _merge({"delivery_channel": delivery_channel}, overrides)


# ---------------------------------------------------------------------------
# Form1095C (PRD §3.6)
# ---------------------------------------------------------------------------
def form_1095c_payload(employee_id, plan_start_month=1, safe_harbor_preference="W2", **overrides):
    return _merge(
        {
            "employee_id": employee_id,
            "plan_start_month": plan_start_month,
            "safe_harbor_preference": safe_harbor_preference,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Transmittal (PRD §3.8)
# ---------------------------------------------------------------------------
def transmittal_payload(
    group_member_id, expected_group_member_version, transmission_type="ORIGINAL", **overrides
):
    return _merge(
        {
            "group_member_id": group_member_id,
            "transmission_type": transmission_type,
            "expected_group_member_version": expected_group_member_version,
        },
        overrides,
    )


def attach_forms_payload(form_ids, **overrides):
    return _merge({"form_ids": list(form_ids)}, overrides)


def detach_form_payload(form_id, **overrides):
    return _merge({"form_id": form_id}, overrides)


def transmit_payload(channel="PAPER", **overrides):
    return _merge({"channel": channel}, overrides)


def agency_response_payload(response_status, receipt_id, errors=None, **overrides):
    return _merge(
        {
            "response_status": response_status,
            "receipt_id": receipt_id,
            "errors": errors if errors is not None else [],
        },
        overrides,
    )


def agency_error_row(form_1095c_id, error_code="AIRTN500", error_field="ssn_last4",
                     severity="ERROR", **overrides):
    return _merge(
        {
            "form_1095c_id": form_1095c_id,
            "error_code": error_code,
            "error_field": error_field,
            "severity": severity,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# TransmittalError (PRD §3.8)
# ---------------------------------------------------------------------------
def transmittal_error_payload(transmittal_id, form_1095c_id=None, **overrides):
    return _merge(
        {
            "transmittal_id": transmittal_id,
            "form_1095c_id": form_1095c_id,
            "error_code": "AIRTN500",
            "error_field": "ssn_last4",
            "severity": "ERROR",
        },
        overrides,
    )


def resolve_error_payload(resolution, **overrides):
    return _merge({"resolution": resolution}, overrides)


# ---------------------------------------------------------------------------
# PenaltyNotice (PRD §3.9)
# ---------------------------------------------------------------------------
def penalty_notice_payload(
    controlled_group_id,
    notice_number,
    asserted_a_months=None,
    asserted_b_employee_months=None,
    **overrides,
):
    return _merge(
        {
            "controlled_group_id": controlled_group_id,
            "notice_number": notice_number,
            "notice_date": "2027-05-01",
            "response_due_date": "2027-06-30",
            "proposed_amount_cents": 1000000,
            "asserted_a_months": asserted_a_months if asserted_a_months is not None else [],
            "asserted_b_employee_months": (
                asserted_b_employee_months if asserted_b_employee_months is not None else []
            ),
        },
        overrides,
    )


def asserted_b_pair(employee_id, month):
    return {"employee_id": employee_id, "month": month}


def penalty_evidence_payload(evidence_type, month, **overrides):
    return _merge(
        {
            "evidence_type": evidence_type,
            "month": month,
            "employee_id": None,
            "document_ref": "DOC-0001",
        },
        overrides,
    )


def agency_determination_payload(determination, **overrides):
    return _merge({"determination": determination}, overrides)


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
def clock_payload(to_iso8601):
    return {"to_iso8601": to_iso8601}
