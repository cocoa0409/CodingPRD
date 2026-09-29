"""Payload factories: valid-by-default request bodies with per-call overrides.

Every factory returns a plain dict that satisfies the PRD's field rules, so a
test only states the fields it actually cares about. Money is always an integer
count of cents and PDH hours are always numbers, never strings.
"""

import itertools

_counter = itertools.count(1)


def _next():
    return next(_counter)


def unique_email(local="engineer"):
    return f"{local}.{_next()}@example.test"


def unique_firm_name(stem="Testbed Engineering PC"):
    return f"{stem} {_next()}"


def unique_audit_cycle_label(stem="CYCLE"):
    return f"2026-{stem}-{_next()}"


def unique_ncees_record_id(stem="NCEES"):
    return f"{stem}-{_next():05d}"


# ---------------------------------------------------------------------------
# Roster and licences
# ---------------------------------------------------------------------------
def engineer_payload(**overrides):
    n = _next()
    payload = {
        "full_name": f"Test Engineer {n}",
        "email": f"engineer.{n}@example.test",
        "home_jurisdiction": "OR",
    }
    payload.update(overrides)
    return payload


def license_payload(engineer_id, **overrides):
    payload = {
        "engineer_id": engineer_id,
        "license_type": "STANDARD",
        "issued_on": "2026-01-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def reinstate_payload(**overrides):
    payload = {"makeup_pdh": 15, "reinstatement_fee_cents": 45000}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
def application_payload(engineer_id, **overrides):
    payload = {
        "engineer_id": engineer_id,
        "pathway": "STANDARD_EXAM",
        "exam_code": "PE_CIVIL",
        "degree_level": "BS",
    }
    payload.update(overrides)
    return payload


def education_evaluation_payload(**overrides):
    payload = {"degree_level": "BS", "accreditation_finding": "EABET_ACCREDITED"}
    payload.update(overrides)
    return payload


def ncees_verification_payload(**overrides):
    payload = {
        "ncees_record_id": "NCEES-77001",
        "source_jurisdiction": "WA",
        "verified_exam_pass": True,
        "verified_years_licensed": 6,
        "disciplinary_history_count": 0,
        "record_expires_on": "2027-06-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def payment_payload(amount_cents, **overrides):
    payload = {"amount_cents": int(amount_cents)}
    payload.update(overrides)
    return payload


def deficiency_payload(**overrides):
    payload = {"deficiency_reason": "Employment dates require documentation."}
    payload.update(overrides)
    return payload


def deficiency_response_payload(**overrides):
    payload = {"response_note": "Documentation attached."}
    payload.update(overrides)
    return payload


def denial_payload(**overrides):
    payload = {"denial_reason": "Experience remains insufficient."}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Experience and references
# ---------------------------------------------------------------------------
def experience_record_payload(**overrides):
    payload = {
        "employer_name": "Cascade Structural Group",
        "position_title": "Project Engineer",
        "period_start_month": "2022-01",
        "period_end_month": "2025-12",
        "responsibility_level": "RESPONSIBLE_CHARGE",
        "post_degree": True,
    }
    payload.update(overrides)
    return payload


def reference_payload(referee_engineer_id, **overrides):
    payload = {"referee_engineer_id": referee_engineer_id, "relationship": "DIRECT_SUPERVISOR"}
    payload.update(overrides)
    return payload


def reference_submission_payload(**overrides):
    payload = {
        "evaluation_score": 5,
        "months_confirmed": 48,
        "responsibility_confirmed": True,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test centres, exams and appointments
# ---------------------------------------------------------------------------
def test_center_payload(**overrides):
    payload = {
        "name": f"Testbed Assessment Center {_next()}",
        "state_code": "OR",
        "seat_labels": ["S1", "S2"],
    }
    payload.update(overrides)
    return payload


def exam_appointment_payload(exam_authorization_id, test_center_id, **overrides):
    payload = {
        "exam_authorization_id": exam_authorization_id,
        "test_center_id": test_center_id,
        "seat_label": "S1",
        "window_start": "2026-10-05T09:00:00Z",
        "window_end": "2026-10-05T17:00:00Z",
    }
    payload.update(overrides)
    return payload


def score_payload(**overrides):
    payload = {
        "raw_score": 82,
        "administered_at": "2026-10-05T17:00:00Z",
        "ncees_transmission_id": f"NCEES-TX-{_next():05d}",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Firms and plan submissions
# ---------------------------------------------------------------------------
def firm_registration_payload(responsible_charge_license_id, **overrides):
    payload = {
        "firm_name": f"Testbed Engineering PC {_next()}",
        "state_code": "OR",
        "responsible_charge_license_id": responsible_charge_license_id,
    }
    payload.update(overrides)
    return payload


def plan_submission_payload(firm_registration_id, **overrides):
    payload = {
        "firm_registration_id": firm_registration_id,
        "project_name": "Riverside Pump Station",
        "sheet_count": 12,
    }
    payload.update(overrides)
    return payload


def seal_payload(sealing_license_id, **overrides):
    payload = {
        "sealing_license_id": sealing_license_id,
        "responsible_charge_attested": True,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Continuing competency
# ---------------------------------------------------------------------------
def cpc_report_payload(license_id, expected_license_version, **overrides):
    payload = {
        "license_id": license_id,
        "period_start": "2026-01-15T00:00:00Z",
        "period_end": "2028-01-15T00:00:00Z",
        "self_certified_pdh": 30,
        "expected_license_version": expected_license_version,
    }
    payload.update(overrides)
    return payload


def pdh_record_payload(**overrides):
    payload = {
        "activity_type": "COURSE",
        "pdh_hours": 30,
        "completed_on": "2027-05-10T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def cpc_audit_payload(**overrides):
    payload = {
        "audit_cycle_label": f"2026-BIENNIUM-{_next()}",
        "sample_pct": 1.0,
        "as_of_period_end": "2028-01-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------
def case_payload(**overrides):
    payload = {
        "allegation_type": "NEGLIGENCE",
        "complainant_name": "City of Testbed",
        "received_on": "2026-07-20T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def finding_payload(**overrides):
    payload = {
        "finding": "PROBABLE_CAUSE",
        "aggravating_factor_count": 1,
        "mitigating_factor_count": 0,
        "violation_count": 1,
    }
    payload.update(overrides)
    return payload


def consent_order_payload(case_id, expected_case_version, **overrides):
    payload = {
        "case_id": case_id,
        "sanction_type": "REPRIMAND",
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def execute_payload(**overrides):
    payload = {"executed_on": "2026-09-01T00:00:00Z"}
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601):
    return {"to_iso8601": to_iso8601}
