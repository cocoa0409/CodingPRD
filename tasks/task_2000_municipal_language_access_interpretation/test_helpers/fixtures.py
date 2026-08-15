"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: DepartmentLiaison calls are entity-backed by Department,
and Interpreter/QualityReviewer calls are entity-backed by Interpreter. Every
ownership-gated call uses a per-instance header built from the real entity id
via the make_* builders; the shared constants are never used for
ownership-gated calls.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BUSINESS_START_ISO, RATE_CARD
from .factories import (
    create_assessment_payload,
    create_complaint_payload,
    create_department_payload,
    create_document_payload,
    create_interpreter_payload,
    create_plan_payload,
    create_request_payload,
    create_translation_job_payload,
    create_vendor_contract_payload,
)
from .test_users import (
    TEST_USERS,
    make_interpreter_headers,
    make_liaison_headers,
    make_officer_headers,
    make_reviewer_headers,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
OFFICER = TEST_USERS["officer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and simple transitions
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Move the server logical clock (PRD §2.5). Returns {current_utc}."""
    return get_success_data(api_client.set_clock(to_iso8601, COORDINATOR))


def create_department(name="Dept Test", service_area_code="SA-1",
                      annual_budget_cents=1_000_000, signage_status=None):
    """Create a department (born with zero spend, score 1000, GOOD_STANDING)."""
    payload = create_department_payload(
        name=name, service_area_code=service_area_code,
        annual_budget_cents=annual_budget_cents)
    if signage_status is not None:
        payload["signage_status"] = signage_status
    return get_success_data(api_client.create_department(payload, COORDINATOR), 201)


def get_department(department_id):
    return get_success_data(api_client.get_department(department_id, COORDINATOR))


def create_contract(vendor_name="Vendor Test", ceiling_cents=500_000, **rate_overrides):
    """Create a DRAFT vendor contract with the standard rate card."""
    rates = dict(RATE_CARD)
    rates.update(rate_overrides)
    payload = create_vendor_contract_payload(
        vendor_name=vendor_name, ceiling_cents=ceiling_cents, **rates)
    return get_success_data(api_client.create_vendor_contract(payload, COORDINATOR), 201)


def activate_contract(contract_id):
    return get_success_data(api_client.activate_vendor_contract(contract_id, COORDINATOR))


def create_active_contract(**kwargs):
    """Create a contract and activate it (DRAFT -> ACTIVE)."""
    contract = create_contract(**kwargs)
    return activate_contract(contract["id"])


def get_contract(contract_id):
    return get_success_data(api_client.get_vendor_contract(contract_id, COORDINATOR))


def create_document(department_id, title="Test Document", document_type="FORM",
                    base_language=None):
    payload = create_document_payload(department_id, title=title,
                                      document_type=document_type)
    if base_language is not None:
        payload["base_language"] = base_language
    return get_success_data(api_client.create_document(payload, COORDINATOR), 201)


def create_interpreter(vendor_contract_id, full_name="Test Interpreter",
                       language_codes=("es",), modalities=("PHONE",),
                       tier="REGISTERED", sign_confidentiality=True):
    """Add an interpreter to the roster; optionally record a current
    confidentiality signature (PRD §3.5). Returns the interpreter."""
    payload = create_interpreter_payload(
        vendor_contract_id, full_name=full_name,
        language_codes=list(language_codes), modalities=list(modalities), tier=tier)
    interpreter = get_success_data(
        api_client.create_interpreter(payload, COORDINATOR), 201)
    if sign_confidentiality:
        interpreter = sign_confidentiality_now(interpreter["id"])
    return interpreter


def sign_confidentiality_now(interpreter_id):
    """Record a confidentiality signature stamped at the current logical time."""
    return get_success_data(api_client.patch_interpreter(
        interpreter_id, {"confidentiality_signed": True}, COORDINATOR))


def get_interpreter(interpreter_id):
    return get_success_data(api_client.get_interpreter(interpreter_id, COORDINATOR))


def create_assessment(department_id, **overrides):
    """Liaison files an assessment for their own department (born DRAFT)."""
    payload = create_assessment_payload(department_id, **overrides)
    return get_success_data(api_client.create_assessment(
        payload, make_liaison_headers(department_id)), 201)


def certify_assessment(assessment_id, officer_id="test-officer-1"):
    return get_success_data(api_client.review_assessment(
        assessment_id, {"decision": "CERTIFY"}, make_officer_headers(officer_id)))


def create_plan(plan_year=2026, summary=None):
    payload = create_plan_payload(plan_year=plan_year)
    if summary is not None:
        payload["summary"] = summary
    return get_success_data(api_client.create_language_access_plan(payload, COORDINATOR), 201)


def create_translation_job(document_id, vendor_contract_id,
                           target_language_code="es", word_count=100, rush=None):
    """Queue a translation job (born QUEUED, provisional committed)."""
    payload = create_translation_job_payload(
        document_id, vendor_contract_id,
        target_language_code=target_language_code, word_count=word_count)
    if rush is not None:
        payload["rush"] = rush
    return get_success_data(api_client.create_translation_job(payload, COORDINATOR), 201)


def get_translation_job(job_id):
    return get_success_data(api_client.get_translation_job(job_id, COORDINATOR))


def assign_translator(job_id, translator_id):
    """QUEUED -> IN_TRANSLATION."""
    return get_success_data(api_client.assign_translation_job(
        job_id, {"translator_id": translator_id}, COORDINATOR))


def submit_translation(job_id, translator_id, submitted_word_count):
    """IN_TRANSLATION -> QUALITY_REVIEW, called by the assigned translator."""
    return get_success_data(api_client.submit_translation(
        job_id, {"submitted_word_count": submitted_word_count},
        make_interpreter_headers(translator_id)))


def review_job(job_id, reviewer_id, decision):
    """QUALITY_REVIEW -> APPROVED (APPROVE) or -> IN_TRANSLATION (REQUEST_REVISION)."""
    return get_success_data(api_client.review_translation_job(
        job_id, {"decision": decision}, make_reviewer_headers(reviewer_id)))


def create_request(department_id, language_code="es", modality="PHONE",
                   encounter_setting="GENERAL", scheduled_start=BUSINESS_START_ISO,
                   scheduled_duration_minutes=30):
    """Create an on-demand request as the owning department's liaison and
    return the raw-validated record (ASSIGNED or UNFULFILLED)."""
    payload = create_request_payload(
        department_id, language_code=language_code, modality=modality,
        encounter_setting=encounter_setting,
        scheduled_duration_minutes=scheduled_duration_minutes)
    if scheduled_start is not None:
        payload["scheduled_start"] = scheduled_start
    return get_success_data(api_client.create_interpretation_request(
        payload, make_liaison_headers(department_id)), 201)


def create_assigned_request(department_id, **kwargs):
    """Create a request and require the dispatch selector to have assigned it."""
    request = create_request(department_id, **kwargs)
    assert request["status"] == "ASSIGNED", (
        f"Setup expected ASSIGNED, got {request['status']}: {request}"
    )
    assert request["interpreter_id"], "Setup expected an assigned interpreter"
    return request


def complete_request(request_id, interpreter_id, actual_minutes):
    """ASSIGNED -> COMPLETED, called by the assigned interpreter."""
    return get_success_data(api_client.complete_interpretation_request(
        request_id, {"actual_minutes": actual_minutes},
        make_interpreter_headers(interpreter_id)))


def record_complaint(department_id, category="OTHER", description="test complaint",
                     interpretation_request_id=None, officer_id=None):
    """Intake a complaint. By default the owning department's liaison records
    it; pass officer_id to use the ComplianceOfficer intake desk instead."""
    payload = create_complaint_payload(
        department_id, category=category, description=description)
    if interpretation_request_id is not None:
        payload["interpretation_request_id"] = interpretation_request_id
    headers = (make_officer_headers(officer_id) if officer_id is not None
               else make_liaison_headers(department_id))
    return get_success_data(api_client.create_complaint(payload, headers), 201)


def adjudicate_complaint(complaint_id, outcome="SUBSTANTIATED", remedy=None,
                         officer_id="test-officer-1"):
    payload = {"outcome": outcome}
    if remedy is not None:
        payload["remedy"] = remedy
    return get_success_data(api_client.adjudicate_complaint(
        complaint_id, payload, make_officer_headers(officer_id)))


# ---------------------------------------------------------------------------
# Tier 2: workspace bundles (department + contract + roster + document)
# ---------------------------------------------------------------------------

def setup_translation_workspace(dept_budget=1_000_000, ceiling_cents=500_000,
                                word_rate=20, translator_tier="REGISTERED",
                                reviewer_tier="CERTIFIED", language_codes=("es",),
                                document_type="FORM", sign=True):
    """Department + ACTIVE contract + translator + reviewer + ACTIVE document.

    Returns a dict with the created records. The translator and reviewer are
    distinct interpreters so the segregation-of-duties rule is satisfied.
    """
    department = create_department(name="Dept Translation", annual_budget_cents=dept_budget)
    contract = create_active_contract(
        vendor_name="Vendor Translation", ceiling_cents=ceiling_cents,
        translation_per_word_cents=word_rate)
    translator = create_interpreter(
        contract["id"], full_name="Tom Translator", language_codes=language_codes,
        tier=translator_tier, sign_confidentiality=sign)
    reviewer = create_interpreter(
        contract["id"], full_name="Rita Reviewer", language_codes=language_codes,
        tier=reviewer_tier, sign_confidentiality=True)
    document = create_document(department["id"], title="Workspace Doc",
                               document_type=document_type)
    return {
        "department": department,
        "contract": contract,
        "translator": translator,
        "reviewer": reviewer,
        "document": document,
    }


def create_job_in_quality_review(workspace, word_count=100,
                                 submitted_word_count=None,
                                 target_language_code="es", rush=None,
                                 document=None):
    """Queue a job in the workspace, assign the translator, and submit work.

    Returns the job in QUALITY_REVIEW.
    """
    document = document or workspace["document"]
    job = create_translation_job(
        document["id"], workspace["contract"]["id"],
        target_language_code=target_language_code, word_count=word_count, rush=rush)
    assign_translator(job["id"], workspace["translator"]["id"])
    return submit_translation(
        job["id"], workspace["translator"]["id"],
        submitted_word_count if submitted_word_count is not None else word_count)


def setup_interpretation_workspace(dept_budget=1_000_000, ceiling_cents=1_000_000,
                                   tier="CERTIFIED", language_codes=("es",),
                                   modalities=("PHONE",), sign=True,
                                   interpreter_name="Test Interpreter",
                                   **rate_overrides):
    """Department + ACTIVE contract + one interpreter (signed by default).

    Returns a dict with the created records.
    """
    department = create_department(name="Dept Requests", annual_budget_cents=dept_budget)
    contract = create_active_contract(
        vendor_name="Vendor Dispatch", ceiling_cents=ceiling_cents, **rate_overrides)
    interpreter = create_interpreter(
        contract["id"], full_name=interpreter_name, language_codes=language_codes,
        modalities=modalities, tier=tier, sign_confidentiality=sign)
    return {
        "department": department,
        "contract": contract,
        "interpreter": interpreter,
    }


def setup_certified_assessment(department_id, plan_year=2026, language_code="es",
                               period_start=None, period_end=None):
    """File and certify one assessment for the department and plan year."""
    overrides = {"language_code": language_code, "plan_year": plan_year}
    if period_start is not None:
        overrides["period_start"] = period_start
    if period_end is not None:
        overrides["period_end"] = period_end
    assessment = create_assessment(department_id, **overrides)
    return certify_assessment(assessment["id"])


# ---------------------------------------------------------------------------
# Tier 5: complaint-driven cascade scenarios
# ---------------------------------------------------------------------------

def setup_complaint_cascade_scenario():
    """Department + ACTIVE contract + one CERTIFIED phone interpreter with
    three COMPLETED 30-minute sessions and a fourth still ASSIGNED, plus three
    RECEIVED complaints linked to the completed sessions.

    Sessions are scheduled inside business hours so a 30-minute PHONE call by a
    CERTIFIED interpreter on a 50c/min card prices at exactly 1725 cents
    (PRD §3.6 five-step pricing). The clock starts at the PRD §2.5 default for
    the completions and is then advanced one day before the fourth request.

    Returns a dict: department, contract, interpreter, completed (R1..R3),
    pending (R4), complaints (C1..C3).
    """
    ws = setup_interpretation_workspace(dept_budget=1_000_000, ceiling_cents=1_000_000,
                                        tier="CERTIFIED", modalities=("PHONE",),
                                        interpreter_name="Xavier Phone")
    dept_id = ws["department"]["id"]
    interpreter_id = ws["interpreter"]["id"]
    completed = []
    for _ in range(3):
        request = create_assigned_request(
            dept_id, modality="PHONE", scheduled_duration_minutes=30,
            scheduled_start="2026-08-01T10:00:00Z")
        completed.append(complete_request(request["id"], interpreter_id, 30))
    set_clock("2026-08-02T00:00:00Z")
    pending = create_assigned_request(
        dept_id, modality="PHONE", scheduled_duration_minutes=30,
        scheduled_start="2026-08-02T10:00:00Z")
    complaints = [
        record_complaint(dept_id, category="POOR_QUALITY", description=f"c{i}",
                         interpretation_request_id=completed[i]["id"])
        for i in range(3)
    ]
    return {
        "department": ws["department"],
        "contract": ws["contract"],
        "interpreter": ws["interpreter"],
        "completed": completed,
        "pending": pending,
        "complaints": complaints,
    }


def setup_completed_session_with_linked_complaint(duration_minutes=130):
    """Department + ACTIVE contract + one CERTIFIED phone interpreter; one
    session ASSIGNED and COMPLETED with actual minutes equal to the planned
    duration; one RECEIVED complaint linked to that session.

    The session is scheduled inside business hours so a 130-minute PHONE call
    by a CERTIFIED interpreter on a 50c/min card prices at exactly 7590 cents
    (132 billable minutes x 50c x 1.15, PRD §3.6).

    Returns a dict: department, contract, interpreter, request, complaint.
    """
    ws = setup_interpretation_workspace(dept_budget=1_000_000, ceiling_cents=1_000_000,
                                        tier="CERTIFIED", modalities=("PHONE",),
                                        interpreter_name="Mia Minutes")
    dept_id = ws["department"]["id"]
    interpreter_id = ws["interpreter"]["id"]
    request = create_assigned_request(
        dept_id, modality="PHONE", scheduled_duration_minutes=duration_minutes,
        scheduled_start="2026-08-01T10:00:00Z")
    completed = complete_request(request["id"], interpreter_id, duration_minutes)
    complaint = record_complaint(
        dept_id, category="POOR_QUALITY", description="bad session",
        interpretation_request_id=completed["id"])
    return {
        "department": ws["department"],
        "contract": ws["contract"],
        "interpreter": ws["interpreter"],
        "request": completed,
        "complaint": complaint,
    }
