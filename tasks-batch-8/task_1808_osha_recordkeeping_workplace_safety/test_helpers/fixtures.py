"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Clock discipline: the server logical clock starts at 2026-08-01T00:00:00Z
(PRD §2.4). Classifications must land within the case's seven-day
recordability window, so helpers that classify accept an explicit clock
position and place it just after `occurred_at`.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    case_version_payload,
    certify_payload,
    classify_payload,
    complete_payload,
    create_case_payload,
    create_citation_payload,
    create_company_payload,
    create_corrective_action_payload,
    create_employee_payload,
    create_establishment_payload,
    create_hour_log_payload,
    create_inspection_payload,
    create_investigation_payload,
    create_summary_payload,
    day_entry_payload,
    root_cause_payload,
    severe_report_payload,
)
from .test_users import (
    TEST_USERS,
    make_investigating_supervisor_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["safety_officer_headers"]
COORDINATOR = TEST_USERS["recordkeeping_coordinator_headers"]
SUPERVISOR = TEST_USERS["investigating_supervisor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Reposition the server logical clock (PRD §2.4). Returns the payload."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_company(legal_name="Test Company", fein="12-3456789"):
    return get_success_data(
        api_client.create_company(
            create_company_payload(legal_name=legal_name, fein=fein), ADMIN))


def create_establishment(company_id, site_name="Plant 1",
                         naics_code="332710", state_code="OH",
                         size_class="STANDARD", is_partially_exempt=None):
    overrides = {}
    if is_partially_exempt is not None:
        overrides["is_partially_exempt"] = is_partially_exempt
    return get_success_data(api_client.create_establishment(
        create_establishment_payload(
            company_id, site_name=site_name, naics_code=naics_code,
            state_code=state_code, size_class=size_class, **overrides),
        ADMIN))


def create_employee(company_id, full_name="Test Worker", job_title="Operator",
                    hire_date="2024-01-01", employment_status=None):
    overrides = {}
    if employment_status is not None:
        overrides["employment_status"] = employment_status
    return get_success_data(api_client.create_employee(
        create_employee_payload(
            company_id, full_name=full_name, job_title=job_title,
            hire_date=hire_date, **overrides),
        COORDINATOR))


def setup_org(fein, legal_name="Org Co", site_name="Site 1",
              naics_code="332710", state_code="OH", size_class="STANDARD",
              is_partially_exempt=None, worker_name="Test Worker",
              job_title="Operator", hire_date="2024-01-01"):
    """Company + establishment + employee. Returns (company, establishment,
    employee)."""
    company = create_company(legal_name=legal_name, fein=fein)
    establishment = create_establishment(
        company["id"], site_name=site_name, naics_code=naics_code,
        state_code=state_code, size_class=size_class,
        is_partially_exempt=is_partially_exempt)
    employee = create_employee(company["id"], full_name=worker_name,
                               job_title=job_title, hire_date=hire_date)
    return company, establishment, employee


# ---------------------------------------------------------------------------
# Tier 1.5: case intake and classification
# ---------------------------------------------------------------------------

def create_case(establishment_id, employee_id, occurred_at,
                description="Workplace injury", body_part="arm",
                event_type="INJURY", is_privacy_case=None,
                is_severe_event=None, headers=OFFICER):
    """Create a case (lands in PENDING_REVIEW). Returns the case."""
    overrides = {}
    if is_privacy_case is not None:
        overrides["is_privacy_case"] = is_privacy_case
    if is_severe_event is not None:
        overrides["is_severe_event"] = is_severe_event
    return get_success_data(api_client.create_case(
        create_case_payload(
            establishment_id, employee_id, occurred_at,
            description=description, body_part=body_part,
            event_type=event_type, **overrides),
        headers))


def get_case(case_id, headers=OFFICER):
    return get_success_data(api_client.get_case(case_id, headers))


def fresh_case_version(case_id):
    return get_case(case_id)["version"]


def classify_case(case_id, classification, headers=OFFICER):
    """Classify a case, threading the case's current version (PRD §2.8)."""
    version = fresh_case_version(case_id)
    return get_success_data(api_client.classify_case(
        case_id, classify_payload(classification, version), headers))


def create_classified_case(establishment_id, employee_id, occurred_at,
                           classification="MEDICAL_TREATMENT",
                           clock_iso=None, **case_flags):
    """Create a case and classify it. If clock_iso is given, the logical clock
    is positioned there first (keeps the seven-day window satisfied)."""
    if clock_iso is not None:
        set_clock(clock_iso)
    case = create_case(establishment_id, employee_id, occurred_at,
                       **case_flags)
    return classify_case(case["id"], classification)


def reclassify_case(case_id, headers=OFFICER):
    """Open the reclassification loop (RECORDABLE -> RECLASSIFIED)."""
    version = fresh_case_version(case_id)
    return get_success_data(api_client.reclassify_case(
        case_id, case_version_payload(version), headers))


def close_day_count(case_id, headers=OFFICER):
    version = fresh_case_version(case_id)
    return get_success_data(api_client.close_day_count(
        case_id, case_version_payload(version), headers))


def finalize_case(case_id, headers=OFFICER):
    version = fresh_case_version(case_id)
    return get_success_data(api_client.finalize_case(
        case_id, case_version_payload(version), headers))


# ---------------------------------------------------------------------------
# Tier 2: day-count entries
# ---------------------------------------------------------------------------

def add_day_entry(case_id, day_type, start_date, end_date):
    return get_success_data(api_client.add_day_entry(
        case_id, day_entry_payload(day_type, start_date, end_date), OFFICER))


def list_day_entries(case_id, status=None):
    params = {"status": status} if status else None
    return get_success_data(api_client.list_day_entries(case_id, OFFICER,
                                                        params=params))


def void_day_entry(case_id, entry_id):
    return get_success_data(
        api_client.void_day_entry(case_id, entry_id, OFFICER))


# ---------------------------------------------------------------------------
# Tier 2: investigations
# ---------------------------------------------------------------------------

def open_investigation(case_id, lead_supervisor_id):
    return get_success_data(api_client.create_investigation(
        create_investigation_payload(case_id, lead_supervisor_id), OFFICER))


def submit_root_cause(investigation_id, lead_id,
                      root_cause="EQUIPMENT",
                      contributing_factors="Guard removed from machine"):
    """Submit root cause as the recorded lead (PRD §3.4)."""
    return get_success_data(api_client.submit_root_cause(
        investigation_id,
        root_cause_payload(root_cause, contributing_factors),
        make_investigating_supervisor_headers(lead_id)))


def reopen_investigation_as_lead(investigation_id, lead_id):
    return get_success_data(api_client.reopen_investigation(
        investigation_id, make_investigating_supervisor_headers(lead_id)))


def close_investigation(investigation_id):
    return get_success_data(api_client.close_investigation(investigation_id,
                                                           OFFICER))


def setup_closed_investigation(case_id, lead_id="sup-1",
                               root_cause="EQUIPMENT"):
    """Open an investigation, submit root cause as the lead, close it."""
    investigation = open_investigation(case_id, lead_id)
    submit_root_cause(investigation["id"], lead_id, root_cause=root_cause)
    return close_investigation(investigation["id"])


# ---------------------------------------------------------------------------
# Tier 2: corrective actions
# ---------------------------------------------------------------------------

def create_corrective_action(establishment_id, description="Abate the hazard",
                             assigned_to="op-fix-1", due_date="2026-09-01",
                             priority="LOW", case_id=None, citation_id=None):
    overrides = {}
    if case_id is not None:
        overrides["case_id"] = case_id
    if citation_id is not None:
        overrides["citation_id"] = citation_id
    return get_success_data(api_client.create_corrective_action(
        create_corrective_action_payload(
            establishment_id, description=description,
            assigned_to=assigned_to, due_date=due_date, priority=priority,
            **overrides),
        OFFICER))


def get_corrective_action(action_id):
    return get_success_data(api_client.get_corrective_action(action_id,
                                                             OFFICER))


def complete_corrective_action(action_id, completed_by):
    return get_success_data(api_client.complete_corrective_action(
        action_id, complete_payload(completed_by), OFFICER))


def verify_corrective_action(action_id, verifier_headers=None):
    """Verify as an operator distinct from the completer and the case's
    investigation lead (PRD §3.5 segregation of duties)."""
    return get_success_data(api_client.verify_corrective_action(
        action_id, verifier_headers or OFFICER))


def cancel_corrective_action(action_id):
    return get_success_data(api_client.cancel_corrective_action(action_id,
                                                                OFFICER))


# ---------------------------------------------------------------------------
# Tier 2/4: hour logs (single and full-year approved)
# ---------------------------------------------------------------------------

def create_hour_log(establishment_id, year, month, hours_worked=5000,
                    employment_count=10):
    return get_success_data(api_client.create_hour_log(
        create_hour_log_payload(establishment_id, year, month,
                                hours_worked=hours_worked,
                                employment_count=employment_count),
        COORDINATOR))


def approve_hour_log(hour_log_id, headers=COORDINATOR):
    return get_success_data(api_client.approve_hour_log(hour_log_id, headers))


def create_approved_hour_log(establishment_id, year, month, hours_worked=5000,
                             employment_count=10):
    log = create_hour_log(establishment_id, year, month,
                          hours_worked=hours_worked,
                          employment_count=employment_count)
    return approve_hour_log(log["id"])


def setup_year_hour_logs(establishment_id, year=2026, hours_worked=5000,
                         employment=10):
    """Create and approve all twelve monthly logs for (establishment, year).

    `employment` may be a single int (same every month) or a list of twelve
    monthly figures. Returns the approved logs in month order.
    """
    figures = employment if isinstance(employment, list) else [employment] * 12
    assert len(figures) == 12, "employment list must cover twelve months"
    return [
        create_approved_hour_log(establishment_id, year, month,
                                 hours_worked=hours_worked,
                                 employment_count=figures[month - 1])
        for month in range(1, 13)
    ]


# ---------------------------------------------------------------------------
# Tier 3/5: annual summary lifecycle
# ---------------------------------------------------------------------------

def create_summary(establishment_id, year, headers=COORDINATOR):
    return get_success_data(api_client.create_summary(
        create_summary_payload(establishment_id, year), headers))


def get_summary(summary_id, headers=COORDINATOR):
    return get_success_data(api_client.get_summary(summary_id, headers))


def fresh_summary_version(summary_id):
    return get_summary(summary_id)["version"]


def prepare_summary(summary_id, headers=COORDINATOR):
    return get_success_data(api_client.prepare_summary(summary_id, headers))


def certify_summary(summary_id, certifier_headers=None):
    """Certify a PREPARED summary, threading its current version (PRD §2.8).
    The default certifier is the shared SafetyOfficer, whose operator id
    differs from the shared coordinator's, satisfying segregation (PRD §3.7).
    """
    version = fresh_summary_version(summary_id)
    return get_success_data(api_client.certify_summary(
        summary_id, certify_payload(version),
        certifier_headers or OFFICER))


def setup_prepared_summary(establishment_id, year=2026, hours_worked=5000,
                           employment=10, preparer_headers=None):
    """Twelve approved logs + draft summary + prepare. Returns PREPARED
    summary data."""
    setup_year_hour_logs(establishment_id, year, hours_worked=hours_worked,
                         employment=employment)
    preparer = preparer_headers or COORDINATOR
    summary = create_summary(establishment_id, year, headers=preparer)
    return prepare_summary(summary["id"], headers=preparer)


def setup_certified_summary(establishment_id, year=2026, hours_worked=5000,
                            employment=10, preparer_headers=None,
                            certifier_headers=None):
    """Full cycle through CERTIFIED: twelve approved logs, prepare, certify.
    Returns CERTIFIED summary data."""
    prepared = setup_prepared_summary(
        establishment_id, year, hours_worked=hours_worked,
        employment=employment, preparer_headers=preparer_headers)
    return certify_summary(prepared["id"],
                           certifier_headers=certifier_headers)


# ---------------------------------------------------------------------------
# Tier 2: severe-injury reports
# ---------------------------------------------------------------------------

def file_severe_report(case_id, report_kind, occurred_at,
                       reported_to_agency_at):
    return get_success_data(api_client.create_severe_report(
        case_id,
        severe_report_payload(report_kind, occurred_at,
                              reported_to_agency_at),
        OFFICER))


# ---------------------------------------------------------------------------
# Tier 2: inspections and citations
# ---------------------------------------------------------------------------

def create_inspection(establishment_id, opened_on="2026-08-03",
                      inspection_type="PROGRAMMED", scope="PARTIAL"):
    return get_success_data(api_client.create_inspection(
        create_inspection_payload(
            establishment_id, opened_on=opened_on,
            inspection_type=inspection_type, scope=scope),
        OFFICER))


def create_citation(inspection_id, standard_cited="29 CFR 1910.147",
                    violation_type="SERIOUS", proposed_penalty_usd=5000,
                    abatement_due_date="2026-09-01"):
    return get_success_data(api_client.create_citation(
        create_citation_payload(
            inspection_id, standard_cited=standard_cited,
            violation_type=violation_type,
            proposed_penalty_usd=proposed_penalty_usd,
            abatement_due_date=abatement_due_date),
        OFFICER))


def get_citation(citation_id):
    return get_success_data(api_client.get_citation(citation_id, OFFICER))


def get_establishment(establishment_id):
    return get_success_data(api_client.get_establishment(establishment_id,
                                                         OFFICER))
