"""Request-payload factories.

Each factory returns a payload that satisfies the required fields the PRD
declares for that operation. Any field can be overridden by keyword, and
passing ``None`` explicitly keeps the key with a null value so that
required-field and null-handling behaviour can both be exercised.
"""

import itertools

_SEQ = itertools.count(1)


def _next() -> int:
    return next(_SEQ)


def _merge(base: dict, overrides: dict) -> dict:
    payload = dict(base)
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit:
    def __repr__(self):  # pragma: no cover - debugging aid only
        return "<omit>"


_OMIT = _Omit()
OMIT = _OMIT


# --------------------------------------------------------------------- program
def program_payload(**overrides):
    n = _next()
    return _merge(
        {
            "name": f"Cancer Program {n}",
            "coc_program_id": f"COC-{10000 + n}",
            "annual_analytic_caseload": 300,
            "reference_year": 2024,
        },
        overrides,
    )


def survey_schedule_payload(**overrides):
    return _merge({"survey_date": "2026-12-01"}, overrides)


def survey_complete_payload(**overrides):
    return _merge({"completed_on": "2026-08-01"}, overrides)


def accreditation_decision_payload(**overrides):
    return _merge({"decision": "ACCREDIT"}, overrides)


# ------------------------------------------------------------------ abstractor
def abstractor_payload(program_id, **overrides):
    n = _next()
    return _merge(
        {
            "program_id": program_id,
            "name": f"Registrar {n}",
            "credential": "CTR",
            "productivity_target_cases_per_day": 2.0,
            "certification_expires_on": "2027-12-31",
        },
        overrides,
    )


def employment_status_payload(employment_status, **overrides):
    return _merge({"employment_status": employment_status}, overrides)


# ----------------------------------------------------------- casefinding source
def casefinding_source_payload(program_id, **overrides):
    return _merge(
        {
            "program_id": program_id,
            "source_type": "PATHOLOGY",
            "expected_monthly_volume": 40,
        },
        overrides,
    )


# ------------------------------------------------------------ casefinding entry
def casefinding_entry_payload(**overrides):
    n = _next()
    return _merge(
        {
            "patient_mrn": f"MRN-{100000 + n}",
            "accession_date": "2026-07-15",
            "primary_site_code": "C50.9",
            "histology_code": "8500/3",
            "behavior_code": "MALIGNANT_3",
            "diagnosis_date": "2026-06-01",
            "first_contact_date": "2026-06-05",
            "diagnosed_at_facility": True,
            "first_treatment_at_facility": True,
        },
        overrides,
    )


def reportability_decision_payload(decision="REPORTABLE", **overrides):
    return _merge(
        {"decision": decision, "decision_reason_code": "SEER_REPORTABLE_BEHAVIOR"},
        overrides,
    )


def entry_reopen_payload(**overrides):
    return _merge({"reopen_reason": "Duplicate line item on the casefinding list"}, overrides)


# ----------------------------------------------------------------- tumor case
def assign_payload(abstractor_id, **overrides):
    return _merge({"abstractor_id": abstractor_id}, overrides)


def unassign_payload(**overrides):
    return _merge({"unassign_reason": "Reallocating the worklist"}, overrides)


def follow_up_contact_payload(**overrides):
    return _merge(
        {
            "contact_date": "2026-08-01",
            "contact_method": "CLINIC_VISIT",
            "outcome": "CONTACT_MADE",
            "vital_status_at_contact": "ALIVE",
        },
        overrides,
    )


# ----------------------------------------------------------------- abstraction
def abstraction_payload(case_id, abstractor_id, expected_case_version, **overrides):
    """A complete abstract: every required field present, nothing UNKNOWN."""
    return _merge(
        {
            "case_id": case_id,
            "abstractor_id": abstractor_id,
            "expected_case_version": expected_case_version,
            "stage_source": "PATHOLOGIC",
            "t_category": "T2",
            "n_category": "N0",
            "m_category": "M0",
            "stage_group": "STAGE_II",
            "first_treatment_date": "2026-06-20",
            "treatment_modalities": ["SURGERY"],
            "diagnostic_confirmation_code": "1",
            "outcome_status": "ALIVE_NO_EVIDENCE",
            "last_contact_date": "2026-07-01",
        },
        overrides,
    )


def submit_qa_payload(**overrides):
    return _merge({"submit_note": "Abstract complete"}, overrides)


def qa_decision_payload(verdict, **overrides):
    return _merge({"verdict": verdict}, overrides)


def reopen_draft_payload(**overrides):
    return _merge({}, overrides)


# -------------------------------------------------------------------- qa audit
def qa_audit_payload(abstraction_id, auditor_id, **overrides):
    return _merge(
        {
            "abstraction_id": abstraction_id,
            "auditor_id": auditor_id,
            "audit_type": "ROUTINE_10PCT",
            "window_start": "2026-08-01",
            "window_end": "2026-08-31",
        },
        overrides,
    )


def audit_score_payload(
    audited_field_count=40,
    minor_discrepancy_count=0,
    major_discrepancy_count=0,
    critical_discrepancy_count=0,
    **overrides,
):
    return _merge(
        {
            "audited_field_count": audited_field_count,
            "minor_discrepancy_count": minor_discrepancy_count,
            "major_discrepancy_count": major_discrepancy_count,
            "critical_discrepancy_count": critical_discrepancy_count,
        },
        overrides,
    )


def audit_void_payload(**overrides):
    return _merge({"void_reason": "Audit opened against the wrong abstract"}, overrides)


# ------------------------------------------------------------------ submission
def submission_payload(program_id, **overrides):
    return _merge(
        {
            "program_id": program_id,
            "period_start": "2026-01-01",
            "period_end": "2026-06-30",
            "deadline_date": "2026-12-31",
        },
        overrides,
    )


def submission_item_payload(case_id, expected_submission_version, **overrides):
    return _merge(
        {"case_id": case_id, "expected_submission_version": expected_submission_version},
        overrides,
    )


def transmit_payload(**overrides):
    return _merge({}, overrides)


def edit_results_payload(item_results, **overrides):
    return _merge({"item_results": item_results}, overrides)


def item_result(case_id, edit_status="ACCEPTED", edit_codes=None):
    return {
        "case_id": case_id,
        "edit_status": edit_status,
        "edit_codes": list(edit_codes or []),
    }


def resolve_item_payload(**overrides):
    return _merge({"resolution_note": "Corrected the flagged fields"}, overrides)


def retransmit_payload(**overrides):
    return _merge({}, overrides)


def assessment_payment_payload(amount_cents, **overrides):
    return _merge({"amount_cents": amount_cents}, overrides)


# ---------------------------------------------------------- conference session
def conference_session_payload(program_id, **overrides):
    return _merge(
        {
            "program_id": program_id,
            "start_at": "2026-08-05T13:00:00Z",
            "end_at": "2026-08-05T14:00:00Z",
            "required_disciplines": [
                "SURGERY",
                "MEDICAL_ONCOLOGY",
                "RADIATION_ONCOLOGY",
                "PATHOLOGY",
                "RADIOLOGY",
            ],
        },
        overrides,
    )


def attendance_payload(attendee_ref, discipline, attended_minutes=45, **overrides):
    return _merge(
        {
            "attendee_ref": attendee_ref,
            "discipline": discipline,
            "attended_minutes": attended_minutes,
        },
        overrides,
    )


def hold_session_payload(cases_presented_count, prospective_case_count, **overrides):
    return _merge(
        {
            "cases_presented_count": cases_presented_count,
            "prospective_case_count": prospective_case_count,
        },
        overrides,
    )


def credit_session_payload(disposition, **overrides):
    return _merge({"disposition": disposition}, overrides)


# ------------------------------------------------------------- quality measure
def quality_measure_payload(program_id, **overrides):
    return _merge(
        {
            "program_id": program_id,
            "measure_code": "BCSRT",
            "measurement_year": 2025,
            "threshold_pct": 75.0,
        },
        overrides,
    )


def stratum(stage_group, eligible_case_count, compliant_case_count):
    return {
        "stage_group": stage_group,
        "eligible_case_count": eligible_case_count,
        "compliant_case_count": compliant_case_count,
    }


def evaluate_measure_payload(strata, **overrides):
    return _merge({"strata": list(strata)}, overrides)


def improvement_project_payload(action, **overrides):
    return _merge({"action": action}, overrides)


# ----------------------------------------------------------------- deficiency
def deficiency_payload(program_id, severity="MAJOR", **overrides):
    return _merge(
        {
            "program_id": program_id,
            "standard_code": "STD 6.1",
            "severity": severity,
            "cited_on": "2026-08-01",
        },
        overrides,
    )


def deficiency_response_payload(**overrides):
    return _merge(
        {"response_narrative": "Corrective action plan filed with evidence"}, overrides
    )


def deficiency_review_payload(outcome, **overrides):
    return _merge({"outcome": outcome}, overrides)


# ---------------------------------------------------------------------- clock
def clock_payload(current_utc, **overrides):
    return _merge({"current_utc": current_utc}, overrides)
