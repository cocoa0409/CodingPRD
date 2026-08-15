"""Composite setup helpers.

The test harness restarts the API server before every test, so each test
rebuilds its preconditions from scratch through these helpers. All helpers
use the lenient get_success_data() validator so setup failures surface as
clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    complete_component_payload,
    create_campaign_payload,
    create_cycle_payload,
    create_employee_payload,
    create_event_payload,
    create_exposure_case_payload,
    create_injury_payload,
    create_work_restriction_payload,
    cycle_completion_payload,
    enroll_contact_payload,
)
from .test_users import TEST_USERS, make_staff_employee_headers

NURSE = TEST_USERS["nurse_headers"]
PHYSICIAN = TEST_USERS["physician_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
SAFETY = TEST_USERS["safety_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + employee primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str, headers=None) -> dict:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, headers or COMPLIANCE)
    return get_success_data(resp)


def register_employee(employee_ref: str, headers=None, **overrides) -> dict:
    payload = create_employee_payload(employee_ref=employee_ref, **overrides)
    resp = api_client.create_employee(payload, headers or NURSE)
    return get_success_data(resp)


def get_employee(employee_id: str, headers=None) -> dict:
    resp = api_client.get_employee(employee_id, headers or PHYSICIAN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: screening progression (PREPLACEMENT -> ACTIVE)
# ---------------------------------------------------------------------------

def open_screening(employee: dict, headers=None) -> dict:
    """Open a screening threading the employee's currently observed version
    (PRD §2.7 optimistic concurrency)."""
    payload = {"expected_employee_version": employee["version"]}
    resp = api_client.create_screening(employee["id"], payload, headers or NURSE)
    return get_success_data(resp)


def complete_screening_components(screening_id: str, include_med_eval: bool = False,
                                  headers=None) -> None:
    for component, completed_at in (
        ("PHYSICAL", "2026-07-20T09:00:00Z"),
        ("TB_BASELINE", "2026-07-21T09:00:00Z"),
    ):
        resp = api_client.complete_screening_component(
            screening_id, complete_component_payload(component, completed_at=completed_at),
            headers or NURSE,
        )
        get_success_data(resp)
    if include_med_eval:
        resp = api_client.complete_screening_component(
            screening_id,
            complete_component_payload("MED_EVAL", completed_at="2026-07-21T12:00:00Z"),
            headers or NURSE,
        )
        get_success_data(resp)


def record_titer(employee_id: str, disease: str, numeric_value=15.0,
                 assay_type="QUANTITATIVE", resulted_at="2026-07-22T09:00:00Z",
                 screening_id=None, qualitative_result=None, headers=None) -> dict:
    payload = {
        "disease": disease,
        "assay_type": assay_type,
        "resulted_at": resulted_at,
    }
    if assay_type == "QUALITATIVE":
        payload["qualitative_result"] = qualitative_result or "REACTIVE"
        if numeric_value is not None:
            payload["numeric_value"] = numeric_value
    else:
        payload["numeric_value"] = numeric_value
    if screening_id is not None:
        payload["screening_id"] = screening_id
    resp = api_client.create_titer_result(employee_id, payload, headers or NURSE)
    return get_success_data(resp)


def record_immune_titers(employee_id: str, screening_id=None, headers=None) -> None:
    """Latest IMMUNE titers for both required diseases (HEP_B 15.0 >= 10.0,
    VARICELLA 2.5 >= 1.0), satisfying the CLEARED-decision immunity gate."""
    record_titer(employee_id, "HEP_B", numeric_value=15.0,
                 resulted_at="2026-07-22T09:00:00Z",
                 screening_id=screening_id, headers=headers)
    record_titer(employee_id, "VARICELLA", numeric_value=2.5,
                 resulted_at="2026-07-22T09:30:00Z",
                 screening_id=screening_id, headers=headers)


def decide_screening(screening_id: str, outcome: str, headers=None) -> dict:
    resp = api_client.decide_screening(screening_id, {"outcome": outcome}, headers or PHYSICIAN)
    return get_success_data(resp)


def make_cleared_employee(employee_ref: str, requires_respirator: bool = False,
                          hire_date: str = "2025-01-05T00:00:00Z",
                          department: str = "ICU", job_category: str = "NURSE",
                          full_name: str = None) -> dict:
    """Full pre-placement pipeline: register -> open screening -> complete
    components (incl. MED_EVAL when respirator-required) -> IMMUNE titers ->
    physician CLEARED. Returns the fresh (ACTIVE) employee record."""
    overrides = {
        "requires_respirator": requires_respirator,
        "hire_date": hire_date,
        "department": department,
        "job_category": job_category,
    }
    if full_name is not None:
        overrides["full_name"] = full_name
    emp = register_employee(employee_ref, **overrides)
    scr = open_screening(emp)
    complete_screening_components(scr["id"], include_med_eval=requires_respirator)
    record_immune_titers(emp["id"])
    decide_screening(scr["id"], "CLEARED")
    return get_employee(emp["id"])


# ---------------------------------------------------------------------------
# Tier 2: annual cycles + compliance holds
# ---------------------------------------------------------------------------

def open_cycle(employee_id: str, cycle_year: int = 2026,
               cycle_mode: str = "CALENDAR_YEAR", headers=None) -> dict:
    resp = api_client.create_cycle(
        employee_id, create_cycle_payload(cycle_year=cycle_year, cycle_mode=cycle_mode),
        headers or COMPLIANCE,
    )
    return get_success_data(resp)


def complete_cycle_requirement(cycle_id: str, requirement_type: str,
                               completed_at: str, headers=None) -> dict:
    resp = api_client.record_cycle_completion(
        cycle_id,
        cycle_completion_payload(requirement_type, completed_at=completed_at),
        headers or NURSE,
    )
    return get_success_data(resp)


def list_holds(employee_id: str, status: str = None, headers=None) -> list:
    params = {"employee_id": employee_id}
    if status:
        params["status"] = status
    resp = api_client.list_holds(headers or COMPLIANCE, params=params)
    data, _meta = validate_paginated(resp)
    return data


def get_cycle(cycle_id: str, headers=None) -> dict:
    resp = api_client.get_cycle(cycle_id, headers or COMPLIANCE)
    return get_success_data(resp)


def setup_overdue_cycle_hold(employee_ref: str, cycle_year: int = 2025,
                             hire_date: str = "2024-06-01T00:00:00Z",
                             overdue_clock: str = "2026-08-01T00:00:01Z") -> tuple:
    """ACTIVE employee + CALENDAR_YEAR cycle whose TB due date has passed:
    advances the clock so the cycle flips OVERDUE and the hold cascade fires.
    Returns (employee, cycle, hold) with the employee SUSPENDED."""
    emp = make_cleared_employee(employee_ref, hire_date=hire_date)
    cycle = open_cycle(emp["id"], cycle_year=cycle_year, cycle_mode="CALENDAR_YEAR")
    set_clock(overdue_clock)
    holds = list_holds(emp["id"], status="ACTIVE")
    assert len(holds) == 1, f"Setup: expected exactly one ACTIVE hold, got {len(holds)}"
    return get_employee(emp["id"]), get_cycle(cycle["id"]), holds[0]


# ---------------------------------------------------------------------------
# Tier 3: exposure cases, PEP regimens, serology follow-ups
# ---------------------------------------------------------------------------

def create_exposure_case(employee_id: str, exposure_type="PERCUTANEOUS",
                         exposure_datetime="2026-07-30T10:00:00Z",
                         source_known=False, body_fluid="BLOOD",
                         source_patient_ref=None, headers=None) -> dict:
    overrides = {
        "exposure_type": exposure_type,
        "exposure_datetime": exposure_datetime,
        "source_known": source_known,
        "body_fluid": body_fluid,
    }
    if source_patient_ref is not None:
        overrides["source_patient_ref"] = source_patient_ref
    resp = api_client.create_exposure_case(
        employee_id, create_exposure_case_payload(**overrides), headers or NURSE
    )
    return get_success_data(resp)


def get_exposure_case(case_id: str, headers=None) -> dict:
    resp = api_client.get_exposure_case(case_id, headers or NURSE)
    return get_success_data(resp)


def list_case_pep(case_id: str, headers=None) -> list:
    resp = api_client.list_pep_regimens(
        headers or PHYSICIAN, params={"exposure_case_id": case_id}
    )
    data, _meta = validate_paginated(resp)
    return data


def get_case_pep(case_id: str, headers=None) -> dict:
    rows = list_case_pep(case_id, headers=headers)
    assert len(rows) == 1, f"Setup: expected exactly one PEP regimen, got {len(rows)}"
    return rows[0]


def list_case_followups(case_id: str, milestone: str = None, headers=None) -> list:
    params = {"exposure_case_id": case_id}
    if milestone:
        params["milestone"] = milestone
    resp = api_client.list_serology_followups(headers or NURSE, params=params)
    data, _meta = validate_paginated(resp)
    return data


def get_case_followup(case_id: str, milestone: str, headers=None) -> dict:
    rows = list_case_followups(case_id, milestone=milestone, headers=headers)
    assert len(rows) == 1, (
        f"Setup: expected exactly one {milestone} follow-up, got {len(rows)}"
    )
    return rows[0]


def start_pep(pep_id: str, started_at: str, headers=None) -> dict:
    resp = api_client.transition_pep_regimen(
        pep_id, {"to_state": "STARTED", "started_at": started_at}, headers or PHYSICIAN
    )
    return get_success_data(resp)


def setup_case_with_pep_started(employee_ref: str,
                                exposure_datetime="2026-07-30T10:00:00Z",
                                clock_at_start="2026-08-01T12:00:00Z",
                                source_known=False,
                                source_patient_ref=None) -> tuple:
    """MEDIUM/HIGH exposure case whose PEP regimen is STARTED. Returns
    (employee, case, pep)."""
    emp = register_employee(employee_ref)
    case = create_exposure_case(
        emp["id"], exposure_datetime=exposure_datetime, source_known=source_known,
        body_fluid="BLOOD", source_patient_ref=source_patient_ref,
    )
    set_clock(clock_at_start)
    pep = get_case_pep(case["id"])
    pep = start_pep(pep["id"], clock_at_start)
    return emp, get_exposure_case(case["id"]), pep


def transition_case(case_id: str, to_state: str, headers=None) -> dict:
    resp = api_client.transition_exposure_case(case_id, {"to_state": to_state}, headers or PHYSICIAN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: work restrictions + return-to-work clearances
# ---------------------------------------------------------------------------

def create_restriction(employee_id: str, restriction_type="MODIFIED_DUTY",
                       start_date="2026-08-02T00:00:00Z", end_date=None,
                       exposure_case_id=None, headers=None) -> dict:
    overrides = {"restriction_type": restriction_type, "start_date": start_date}
    if end_date is not None:
        overrides["end_date"] = end_date
    if exposure_case_id is not None:
        overrides["exposure_case_id"] = exposure_case_id
    resp = api_client.create_work_restriction(
        employee_id, create_work_restriction_payload(**overrides), headers or PHYSICIAN
    )
    return get_success_data(resp)


def get_restriction(restriction_id: str, headers=None) -> dict:
    resp = api_client.get_work_restriction(restriction_id, headers or PHYSICIAN)
    return get_success_data(resp)


def request_clearance(restriction_id: str, headers=None) -> dict:
    resp = api_client.create_clearance(restriction_id, {}, headers or NURSE)
    return get_success_data(resp)


def decide_clearance(clearance_id: str, outcome: str, decision_note=None,
                     headers=None) -> dict:
    payload = {"outcome": outcome}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    resp = api_client.decide_clearance(clearance_id, payload, headers or PHYSICIAN)
    return get_success_data(resp)


def list_restrictions(employee_id: str, status: str = None, headers=None) -> list:
    params = {"employee_id": employee_id}
    if status:
        params["status"] = status
    resp = api_client.list_work_restrictions(headers or PHYSICIAN, params=params)
    data, _meta = validate_paginated(resp)
    return data


# ---------------------------------------------------------------------------
# Tier 5: communicable events + contact tracing
# ---------------------------------------------------------------------------

def create_event(index_employee_id: str, disease="COVID",
                 onset_date="2026-08-01T00:00:00Z", headers=None) -> dict:
    resp = api_client.create_communicable_event(
        create_event_payload(
            index_employee_id=index_employee_id, disease=disease, onset_date=onset_date,
        ),
        headers or SAFETY,
    )
    return get_success_data(resp)


def advance_event(event_id: str, to_state: str, headers=None) -> dict:
    resp = api_client.advance_communicable_event(
        event_id, {"to_state": to_state}, headers or SAFETY
    )
    return get_success_data(resp)


def enroll_contact(event_id: str, contact_employee_id: str,
                   contact_date="2026-08-02T00:00:00Z", headers=None) -> dict:
    resp = api_client.enroll_contact(
        event_id,
        enroll_contact_payload(
            contact_employee_id=contact_employee_id, contact_date=contact_date,
        ),
        headers or SAFETY,
    )
    return get_success_data(resp)


def get_contact(contact_id: str, headers=None) -> dict:
    resp = api_client.get_exposure_contact(contact_id, headers or SAFETY)
    return get_success_data(resp)


def get_event(event_id: str, headers=None) -> dict:
    resp = api_client.get_communicable_event(event_id, headers or SAFETY)
    return get_success_data(resp)


def setup_tracing_event_with_contact(index_ref: str, contact_ref: str,
                                     disease="COVID",
                                     onset_date="2026-08-01T00:00:00Z",
                                     contact_date="2026-08-02T00:00:00Z",
                                     clock_at_enroll="2026-08-05T00:00:00Z",
                                     advance_to_monitoring: bool = False) -> tuple:
    """Index + contact employees, event advanced to TRACING, clock moved, one
    contact enrolled. Returns (index_emp, contact_emp, event, contact)."""
    ix = register_employee(index_ref)
    ec = register_employee(contact_ref, job_category="TECH")
    event = create_event(ix["id"], disease=disease, onset_date=onset_date)
    advance_event(event["id"], "TRACING")
    set_clock(clock_at_enroll)
    contact = enroll_contact(event["id"], ec["id"], contact_date=contact_date)
    if advance_to_monitoring:
        event = advance_event(event["id"], "MONITORING")
    return ix, ec, get_event(event["id"]), contact


# ---------------------------------------------------------------------------
# Tier 6: injury reports / workers' compensation
# ---------------------------------------------------------------------------

def create_injury(employee_id: str, injury_type="FALL",
                  injury_datetime="2026-07-15T14:00:00Z",
                  exposure_case_id=None, headers=None) -> dict:
    overrides = {"injury_type": injury_type, "injury_datetime": injury_datetime}
    if exposure_case_id is not None:
        overrides["exposure_case_id"] = exposure_case_id
    resp = api_client.create_injury_report(
        employee_id, create_injury_payload(**overrides), headers or SAFETY
    )
    return get_success_data(resp)


def transition_injury(injury_id: str, to_state: str, headers=None) -> dict:
    resp = api_client.transition_injury_report(
        injury_id, {"to_state": to_state}, headers or SAFETY
    )
    return get_success_data(resp)


def get_injury(injury_id: str, headers=None) -> dict:
    resp = api_client.get_injury_report(injury_id, headers or SAFETY)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 7: vaccination campaigns
# ---------------------------------------------------------------------------

def create_campaign(vaccine_type="INFLUENZA", window_start="2026-09-01T00:00:00Z",
                    window_end="2026-09-30T23:59:59Z", department_scope=None,
                    headers=None) -> dict:
    resp = api_client.create_campaign(
        create_campaign_payload(
            vaccine_type=vaccine_type, window_start=window_start,
            window_end=window_end,
            department_scope=department_scope if department_scope is not None else ["ALL"],
        ),
        headers or COMPLIANCE,
    )
    return get_success_data(resp)


def transition_campaign(campaign_id: str, to_state: str, headers=None) -> dict:
    resp = api_client.transition_campaign(
        campaign_id, {"to_state": to_state}, headers or COMPLIANCE
    )
    return get_success_data(resp)


def get_campaign(campaign_id: str, headers=None) -> dict:
    resp = api_client.get_campaign(campaign_id, headers or COMPLIANCE)
    return get_success_data(resp)


def find_participation(campaign_id: str, employee_id: str, headers=None) -> dict:
    resp = api_client.list_participations(
        headers or NURSE, params={"campaign_id": campaign_id, "employee_id": employee_id}
    )
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, (
        f"Setup: expected exactly one participation for employee, got {len(data)}"
    )
    return data[0]


def get_participation(participation_id: str, headers=None) -> dict:
    resp = api_client.get_participation(participation_id, headers or NURSE)
    return get_success_data(resp)


def staff_headers_for(employee_id: str) -> dict:
    """Ownership-gated StaffEmployee headers keyed to a real Employee id."""
    return make_staff_employee_headers(employee_id)
