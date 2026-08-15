"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "LEGAL_NAME": "Test Company",
    "FEIN": "12-3456789",
    "SITE_NAME": "Plant 1",
    "NAICS_CODE": "332710",
    "STATE_CODE": "OH",
    "SIZE_CLASS": "STANDARD",
    "FULL_NAME": "Test Worker",
    "JOB_TITLE": "Operator",
    "HIRE_DATE": "2024-01-01",
    "DESCRIPTION": "Workplace injury",
    "BODY_PART": "arm",
    "EVENT_TYPE": "INJURY",
    "YEAR": 2026,
    "MONTHLY_HOURS": 5000,
    "MONTHLY_EMPLOYMENT": 10,
    "CA_DESCRIPTION": "Abate the hazard",
    "CA_ASSIGNED_TO": "op-fix-1",
    "CA_DUE_DATE": "2026-09-01",
    "CA_PRIORITY": "LOW",
    "STANDARD_CITED": "29 CFR 1910.147",
    "VIOLATION_TYPE": "SERIOUS",
    "PROPOSED_PENALTY": 5000,
    "ABATEMENT_DUE_DATE": "2026-09-01",
    "OPENED_ON": "2026-08-03",
    "INSPECTION_TYPE": "PROGRAMMED",
    "INSPECTION_SCOPE": "PARTIAL",
    "ROOT_CAUSE": "EQUIPMENT",
    "CONTRIBUTING_FACTORS": "Guard removed from machine",
}


def create_company_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "fein": DEFAULTS["FEIN"],
    }
    defaults.update(overrides)
    return defaults


def create_establishment_payload(company_id, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "site_name": DEFAULTS["SITE_NAME"],
        "naics_code": DEFAULTS["NAICS_CODE"],
        "state_code": DEFAULTS["STATE_CODE"],
        "size_class": DEFAULTS["SIZE_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(company_id, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "full_name": DEFAULTS["FULL_NAME"],
        "job_title": DEFAULTS["JOB_TITLE"],
        "hire_date": DEFAULTS["HIRE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def update_employee_payload(**fields) -> dict:
    """PATCH payload: any of full_name / job_title / employment_status."""
    return {k: v for k, v in fields.items() if v is not None}


def create_case_payload(establishment_id, employee_id, occurred_at,
                        **overrides) -> dict:
    defaults = {
        "establishment_id": establishment_id,
        "employee_id": employee_id,
        "occurred_at": occurred_at,
        "description": DEFAULTS["DESCRIPTION"],
        "body_part": DEFAULTS["BODY_PART"],
        "event_type": DEFAULTS["EVENT_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def classify_payload(classification, expected_case_version, **overrides) -> dict:
    defaults = {
        "classification": classification,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def case_version_payload(expected_case_version) -> dict:
    return {"expected_case_version": expected_case_version}


def day_entry_payload(day_type, start_date, end_date) -> dict:
    return {
        "day_type": day_type,
        "start_date": start_date,
        "end_date": end_date,
    }


def create_investigation_payload(case_id, lead_supervisor_id) -> dict:
    return {"case_id": case_id, "lead_supervisor_id": lead_supervisor_id}


def root_cause_payload(root_cause=DEFAULTS["ROOT_CAUSE"],
                       contributing_factors=DEFAULTS["CONTRIBUTING_FACTORS"]
                       ) -> dict:
    return {
        "root_cause": root_cause,
        "contributing_factors": contributing_factors,
    }


def create_corrective_action_payload(establishment_id, **overrides) -> dict:
    defaults = {
        "establishment_id": establishment_id,
        "description": DEFAULTS["CA_DESCRIPTION"],
        "assigned_to": DEFAULTS["CA_ASSIGNED_TO"],
        "due_date": DEFAULTS["CA_DUE_DATE"],
        "priority": DEFAULTS["CA_PRIORITY"],
    }
    defaults.update(overrides)
    return defaults


def complete_payload(completed_by) -> dict:
    return {"completed_by": completed_by}


def create_summary_payload(establishment_id, year) -> dict:
    return {"establishment_id": establishment_id, "year": year}


def certify_payload(expected_summary_version) -> dict:
    return {"expected_summary_version": expected_summary_version}


def create_hour_log_payload(establishment_id, year, month,
                            hours_worked=DEFAULTS["MONTHLY_HOURS"],
                            employment_count=DEFAULTS["MONTHLY_EMPLOYMENT"]
                            ) -> dict:
    return {
        "establishment_id": establishment_id,
        "year": year,
        "month": month,
        "hours_worked": hours_worked,
        "employment_count": employment_count,
    }


def severe_report_payload(report_kind, occurred_at,
                          reported_to_agency_at) -> dict:
    return {
        "report_kind": report_kind,
        "occurred_at": occurred_at,
        "reported_to_agency_at": reported_to_agency_at,
    }


def create_inspection_payload(establishment_id, **overrides) -> dict:
    defaults = {
        "establishment_id": establishment_id,
        "opened_on": DEFAULTS["OPENED_ON"],
        "inspection_type": DEFAULTS["INSPECTION_TYPE"],
        "scope": DEFAULTS["INSPECTION_SCOPE"],
    }
    defaults.update(overrides)
    return defaults


def create_citation_payload(inspection_id, **overrides) -> dict:
    defaults = {
        "inspection_id": inspection_id,
        "standard_cited": DEFAULTS["STANDARD_CITED"],
        "violation_type": DEFAULTS["VIOLATION_TYPE"],
        "proposed_penalty_usd": DEFAULTS["PROPOSED_PENALTY"],
        "abatement_due_date": DEFAULTS["ABATEMENT_DUE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def resolve_contest_payload(outcome, final_penalty_usd=None) -> dict:
    payload = {"outcome": outcome}
    if final_penalty_usd is not None:
        payload["final_penalty_usd"] = final_penalty_usd
    return payload


def abate_payload(abatement_evidence="Hazard abated; photos attached") -> dict:
    return {"abatement_evidence": abatement_evidence}
