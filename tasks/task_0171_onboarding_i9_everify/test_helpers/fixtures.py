"""Composite setup helpers — multi-step preambles tests can reuse.

The Onboarding I-9 / E-Verify lifecycle takes 5–15 API calls to reach
interesting states (an employee with Section 1 done, a form ready to
sign Section 2 with valid List-A documents, a PENDING / TNC E-Verify
case, a contested case looping back to PENDING, a Section-3 supersession
chain with an open ReverificationEvent). Each fixture composes the
lower-level steps so test bodies focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

    "When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the
    acting `Employee`; any ownership check on a resource that references
    an employee compares the resource's `employee_id` to `X-User-ID`."

After an Employee is created, fixtures act as that employee by minting
headers via `make_employee_headers(employee["id"])`. HRStaff, EmployerRep,
and System are opaque per PRD §2.1; helpers use the shared placeholders
for those roles by default but `make_employer_rep_headers(operator_id)`
is available when a test needs multiple distinct EmployerRep operators
(for segregation-of-duties tests).

SEGREGATION OF DUTIES — PRD §2.1:

    "An `EmployerRep` who signs Section 2 with the same `X-User-ID` as
    the `Employee` who attested Section 1 is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

Section-2 fixtures default to `EMPLOYER_REP_SHARED_ID`, which differs
from any Employee.id minted as a UUID. Tests that need to force a
collision pass the employee's id as the EmployerRep operator id.

CLOCK ANCHORING — PRD §2.6:

    "All deadlines are measured against `SystemClock.current_time`, a
    single logical timestamp that is advanced only via an admin-only
    test-driving capability that accepts a target instant in the `to`
    field."

Fixtures advance the clock to deterministic moments using System
headers and never rely on wall-clock time.

Setup calls use `get_success_data` (lenient 2xx validator) so a failed
setup surfaces as 'Setup failed' rather than a confusing assertion
failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    add_days,
    add_minutes,
    clock_advance_payload,
    close_case_payload,
    create_employee_payload,
    create_i9_document_payload,
    create_i9_form_payload,
    deliver_result_payload,
    section1_payload,
    section2_payload,
    submit_everify_payload,
    tnc_decision_payload,
    unique_idempotency_key,
    update_employee_payload,
    void_form_payload,
)
from .test_users import (
    EMPLOYER_REP_SECONDARY_ID,
    EMPLOYER_REP_SHARED_ID,
    HR_STAFF_SECONDARY_ID,
    HR_STAFF_SHARED_ID,
    TEST_USERS,
    make_employee_headers,
    make_employer_rep_headers,
    make_hr_staff_headers,
)


# ===========================================================================
# Clock + sweep helpers — PRD §2.6, §2.11
# ===========================================================================
def advance_clock_to(target_iso: str) -> None:
    """Advance the logical clock to `target_iso` (PRD §2.6)."""
    resp = api_client.clock_advance(
        clock_advance_payload(to=target_iso), TEST_USERS["system_headers"],
    )
    get_success_data(resp)


def run_sweep() -> None:
    """Run the deadline sweep (PRD §2.11)."""
    resp = api_client.run_sweep(TEST_USERS["system_headers"])
    get_success_data(resp)


# ===========================================================================
# Read helpers — used by tests and other fixtures
# ===========================================================================
def get_employee(employee_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["hr_staff_headers"]
    return get_success_data(api_client.get_employee(employee_id, h))


def get_everify_case(case_id: str,
                     headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["employer_rep_headers"]
    return get_success_data(api_client.get_everify_case(case_id, h))


def list_audit_events(
    employee_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    h = headers or TEST_USERS["hr_staff_headers"]
    body = get_success_data(
        api_client.list_audit_events(employee_id, h, params={"limit": 100}),
    )
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "results", "data", "events"):
            v = body.get(key)
            if isinstance(v, list):
                return v
    return []


def list_reverification_events(
    employee_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    h = headers or TEST_USERS["hr_staff_headers"]
    body = get_success_data(
        api_client.list_reverification_events(
            employee_id, h, params={"limit": 100},
        ),
    )
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "results", "data", "events"):
            v = body.get(key)
            if isinstance(v, list):
                return v
    return []


def list_i9_forms(
    employee_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    h = headers or TEST_USERS["hr_staff_headers"]
    body = get_success_data(
        api_client.list_i9_forms(employee_id, h, params={"limit": 100}),
    )
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "results", "data", "forms"):
            v = body.get(key)
            if isinstance(v, list):
                return v
    return []


# ===========================================================================
# Tier 0 — Foundation creators
# ===========================================================================
def create_employee(
    *,
    legal_name: Optional[str] = None,
    citizenship_status: str = "US_CITIZEN",
    start_date: str = "2026-06-01",
    work_authorization_expiry: Optional[str] = None,
    visa_class: Optional[str] = None,
    ssn: Optional[str] = None,
    date_of_birth: str = "1990-01-15",
) -> Dict[str, Any]:
    """HRStaff creates an Employee (PRD §3.1: "Onboarding begins when
    `HRStaff` creates an `Employee` record")."""
    payload = create_employee_payload(
        legal_name=legal_name,
        citizenship_status=citizenship_status,
        start_date=start_date,
        work_authorization_expiry=work_authorization_expiry,
        visa_class=visa_class,
        ssn=ssn,
        date_of_birth=date_of_birth,
    )
    return get_success_data(
        api_client.create_employee(payload, TEST_USERS["hr_staff_headers"]),
    )


def create_i9_form(
    *,
    employee_id: str,
    form_kind: str = "INITIAL",
    supersedes_form_id: Optional[str] = None,
) -> Dict[str, Any]:
    """HRStaff creates an I9Form (PRD §3.3)."""
    return get_success_data(
        api_client.create_i9_form(
            employee_id,
            create_i9_form_payload(
                form_kind=form_kind,
                supersedes_form_id=supersedes_form_id,
            ),
            TEST_USERS["hr_staff_headers"],
        ),
    )


def attest_section1(
    *,
    employee_id: str,
    form_id: str,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """Employee attests Section 1 (PRD §3.3: "This step is exclusive to
    the `Employee` role, and `X-User-ID` must equal the `Employee.id`")."""
    h = make_employee_headers(employee_id)
    return get_success_data(
        api_client.attest_section1(
            employee_id, form_id, section1_payload(version=version), h,
        ),
    )


def register_document(
    *,
    employee_id: str,
    category: str,
    document_title: Optional[str] = None,
    expiration_date: Optional[str] = None,
    receipt: Optional[bool] = None,
    document_number: Optional[str] = None,
    issuing_authority: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Register an I9Document (PRD §3.2: "Either `HRStaff` or an
    `EmployerRep` may register a document against an employee")."""
    h = headers or TEST_USERS["hr_staff_headers"]
    payload = create_i9_document_payload(
        category=category,
        document_title=document_title,
        document_number=document_number,
        issuing_authority=issuing_authority,
        expiration_date=expiration_date,
        receipt=receipt,
    )
    return get_success_data(
        api_client.create_i9_document(employee_id, payload, h),
    )


def sign_section2(
    *,
    employee_id: str,
    form_id: str,
    version: Optional[int] = None,
    list_a_document_id: Optional[str] = None,
    list_b_document_id: Optional[str] = None,
    list_c_document_id: Optional[str] = None,
    enforce_deadline: Optional[bool] = None,
    employer_rep_id: str = EMPLOYER_REP_SHARED_ID,
) -> Dict[str, Any]:
    """EmployerRep signs Section 2 (PRD §3.3: "Section 2 is the
    document-examination step and is exclusive to an `EmployerRep`").

    PRD §2.1: segregation of duties requires the signing X-User-ID to
    differ from the Section 1 attester's X-User-ID. By default this
    fixture uses `EMPLOYER_REP_SHARED_ID` as the operator id, which is
    distinct from any Employee.id minted as a UUID. To force a
    collision, pass `employer_rep_id=<the employee's id>`.
    """
    h = make_employer_rep_headers(employer_rep_id)
    payload = section2_payload(
        version=version,
        list_a_document_id=list_a_document_id,
        list_b_document_id=list_b_document_id,
        list_c_document_id=list_c_document_id,
        enforce_deadline=enforce_deadline,
    )
    return get_success_data(
        api_client.sign_section2(employee_id, form_id, payload, h),
    )


def void_form(*, form_id: str,
              version: Optional[int] = None) -> Dict[str, Any]:
    """HRStaff voids a DRAFT or SECTION_1_DONE form (PRD §3.3)."""
    return get_success_data(
        api_client.void_i9_form(
            form_id, void_form_payload(version=version),
            TEST_USERS["hr_staff_headers"],
        ),
    )


def submit_everify_case(
    *,
    employee_id: str,
    i9_form_id: str,
    idempotency_key: Optional[str] = None,
    employer_rep_id: str = EMPLOYER_REP_SHARED_ID,
) -> Dict[str, Any]:
    """EmployerRep submits an E-Verify case (PRD §3.5)."""
    h = make_employer_rep_headers(employer_rep_id)
    payload = submit_everify_payload(
        i9_form_id=i9_form_id,
        idempotency_key=idempotency_key or unique_idempotency_key(),
    )
    return get_success_data(
        api_client.submit_everify_case(employee_id, payload, h),
    )


def deliver_result(
    *,
    case_id: str,
    result: str,
    tnc_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """System delivers an E-Verify outcome (PRD §3.5)."""
    return get_success_data(
        api_client.deliver_everify_result(
            case_id,
            deliver_result_payload(result=result, tnc_kind=tnc_kind),
            TEST_USERS["system_headers"],
        ),
    )


def submit_tnc_decision(
    *,
    case_id: str,
    employee_id: str,
    decision: str,
) -> Dict[str, Any]:
    """Employee submits TNC decision (PRD §3.5)."""
    h = make_employee_headers(employee_id)
    return get_success_data(
        api_client.submit_tnc_decision(
            case_id, tnc_decision_payload(decision=decision), h,
        ),
    )


def close_case(
    *,
    case_id: str,
    employer_rep_id: str = EMPLOYER_REP_SHARED_ID,
) -> Dict[str, Any]:
    """EmployerRep closes the case (PRD §3.6)."""
    h = make_employer_rep_headers(employer_rep_id)
    return get_success_data(
        api_client.close_everify_case(case_id, close_case_payload(), h),
    )


# ===========================================================================
# Tier 1 — Documents bundled for a List-A or List-B+C scenario.
# ===========================================================================
def register_list_a_document(
    *,
    employee_id: str,
    document_title: Optional[str] = None,
    expiration_date: Optional[str] = "2030-01-01",
    receipt: Optional[bool] = None,
) -> Dict[str, Any]:
    return register_document(
        employee_id=employee_id,
        category="LIST_A",
        document_title=document_title or TEST_DEFAULTS["DOCUMENT_TITLE_PASSPORT"],
        expiration_date=expiration_date,
        receipt=receipt,
    )


def register_list_b_document(
    *,
    employee_id: str,
    document_title: Optional[str] = None,
    expiration_date: Optional[str] = "2030-01-01",
) -> Dict[str, Any]:
    return register_document(
        employee_id=employee_id,
        category="LIST_B",
        document_title=document_title or TEST_DEFAULTS["DOCUMENT_TITLE_DL"],
        expiration_date=expiration_date,
    )


def register_list_c_document(
    *,
    employee_id: str,
    document_title: Optional[str] = None,
    expiration_date: Optional[str] = None,
) -> Dict[str, Any]:
    return register_document(
        employee_id=employee_id,
        category="LIST_C",
        document_title=document_title or TEST_DEFAULTS["DOCUMENT_TITLE_SSN_CARD"],
        expiration_date=expiration_date,
    )


def register_ead_document(
    *,
    employee_id: str,
    expiration_date: str,
) -> Dict[str, Any]:
    """Register an EAD I-766 LIST_A document — required for OPT EAD /
    work-auth-expiry reverification scenarios (PRD §3.4: "when
    `visa_class` is `F1_OPT` and the `LIST_A` document is an
    'EAD I-766', that document's `expiration_date`")."""
    return register_document(
        employee_id=employee_id,
        category="LIST_A",
        document_title=TEST_DEFAULTS["DOCUMENT_TITLE_EAD"],
        expiration_date=expiration_date,
        issuing_authority=TEST_DEFAULTS["DOCUMENT_ISSUING_AUTHORITY_USCIS"],
    )


# ===========================================================================
# Tier 2 — Form lifecycle helpers
# ===========================================================================
def create_form_at_section1_done(
    *,
    employee_id: str,
    form_kind: str = "INITIAL",
    supersedes_form_id: Optional[str] = None,
) -> Dict[str, Any]:
    """HR creates a form + Employee attests Section 1.

    Returns the form post Section 1 attestation (form_status=SECTION_1_DONE).
    PRD §3.3: DRAFT -> SECTION_1_DONE.
    """
    form = create_i9_form(
        employee_id=employee_id,
        form_kind=form_kind,
        supersedes_form_id=supersedes_form_id,
    )
    return attest_section1(employee_id=employee_id, form_id=form["id"])


def create_form_at_section2_done(
    *,
    employee_id: str,
    form_kind: str = "INITIAL",
    supersedes_form_id: Optional[str] = None,
    list_a_document_id: Optional[str] = None,
    list_b_document_id: Optional[str] = None,
    list_c_document_id: Optional[str] = None,
    employer_rep_id: str = EMPLOYER_REP_SHARED_ID,
) -> Dict[str, Any]:
    """Build a form all the way through Section 2 sign.

    If no document ids are passed, registers a LIST_A passport
    (expiring 2030) and uses it. Returns the form post Section 2
    sign (form_status=SECTION_2_DONE).
    """
    form = create_form_at_section1_done(
        employee_id=employee_id,
        form_kind=form_kind,
        supersedes_form_id=supersedes_form_id,
    )
    if (list_a_document_id is None
            and list_b_document_id is None
            and list_c_document_id is None):
        doc = register_list_a_document(employee_id=employee_id)
        list_a_document_id = doc["id"]
    return sign_section2(
        employee_id=employee_id,
        form_id=form["id"],
        list_a_document_id=list_a_document_id,
        list_b_document_id=list_b_document_id,
        list_c_document_id=list_c_document_id,
        employer_rep_id=employer_rep_id,
    )


# ===========================================================================
# Tier 3 — Employee + completed Section 2 (most common test prereq)
# ===========================================================================
def setup_employee_with_section2_done(
    *,
    start_date: str = "2026-06-01",
    clock_iso: Optional[str] = "2026-06-02T08:00:00.000Z",
    citizenship_status: str = "US_CITIZEN",
    work_authorization_expiry: Optional[str] = None,
    visa_class: Optional[str] = None,
    list_a_document_title: Optional[str] = None,
    list_a_expiration_date: str = "2030-01-01",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build an Employee, an INITIAL form, attest Section 1, sign
    Section 2 with a LIST_A passport.

    Returns (employee, form, list_a_document). Clock is anchored to
    `clock_iso` before any mutation when provided.
    """
    if clock_iso is not None:
        advance_clock_to(clock_iso)
    employee = create_employee(
        start_date=start_date,
        citizenship_status=citizenship_status,
        work_authorization_expiry=work_authorization_expiry,
        visa_class=visa_class,
    )
    form = create_i9_form(
        employee_id=employee["id"], form_kind="INITIAL",
    )
    form = attest_section1(employee_id=employee["id"], form_id=form["id"])
    doc = register_list_a_document(
        employee_id=employee["id"],
        document_title=list_a_document_title,
        expiration_date=list_a_expiration_date,
    )
    form = sign_section2(
        employee_id=employee["id"],
        form_id=form["id"],
        list_a_document_id=doc["id"],
    )
    return employee, form, doc


def setup_employee_with_ead_section2_done(
    *,
    start_date: str = "2026-06-01",
    clock_iso: str = "2026-06-02T08:00:00.000Z",
    ead_expiration_date: str = "2026-08-01",
    visa_class: str = "F1_OPT",
    work_authorization_expiry: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build an ALIEN_AUTHORIZED Employee whose Section 2 is signed
    with an EAD I-766 — automatically opens a WORK_AUTH_EXPIRY
    ReverificationEvent (PRD §3.4)."""
    advance_clock_to(clock_iso)
    employee = create_employee(
        citizenship_status="ALIEN_AUTHORIZED",
        start_date=start_date,
        work_authorization_expiry=(
            work_authorization_expiry or ead_expiration_date
        ),
        visa_class=visa_class,
    )
    form = create_i9_form(
        employee_id=employee["id"], form_kind="INITIAL",
    )
    form = attest_section1(employee_id=employee["id"], form_id=form["id"])
    doc = register_ead_document(
        employee_id=employee["id"], expiration_date=ead_expiration_date,
    )
    form = sign_section2(
        employee_id=employee["id"],
        form_id=form["id"],
        list_a_document_id=doc["id"],
    )
    return employee, form, doc


# ===========================================================================
# Tier 4 — E-Verify case lifecycle
# ===========================================================================
def setup_employee_with_pending_case(
    *,
    start_date: str = "2026-06-01",
    clock_iso: str = "2026-06-02T08:00:00.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build employee + Section 2 done + submit an E-Verify case.

    Returns (employee, form, case) where case.case_status='PENDING'.
    """
    employee, form, _doc = setup_employee_with_section2_done(
        start_date=start_date, clock_iso=clock_iso,
    )
    case = submit_everify_case(
        employee_id=employee["id"],
        i9_form_id=form["id"],
    )
    return employee, form, case


def setup_employee_with_tnc_case(
    *,
    tnc_kind: str = "SSA",
    tnc_opened_at: str = "2026-06-15T09:00:00.000Z",
    start_date: str = "2026-06-01",
    initial_clock_iso: str = "2026-06-02T08:00:00.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build employee + PENDING case + deliver TNC result.

    Returns (employee, form, case) where case.case_status='TNC' and
    tnc_opened_at is anchored to `tnc_opened_at`.
    """
    employee, form, case = setup_employee_with_pending_case(
        start_date=start_date, clock_iso=initial_clock_iso,
    )
    advance_clock_to(tnc_opened_at)
    case = deliver_result(
        case_id=case["id"], result="TNC", tnc_kind=tnc_kind,
    )
    return employee, form, case


def setup_employee_with_employment_authorized_case(
    *,
    start_date: str = "2026-06-01",
    initial_clock_iso: str = "2026-06-02T08:00:00.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build employee + Section 2 done + EMPLOYMENT_AUTHORIZED case
    (pre-close)."""
    employee, form, case = setup_employee_with_pending_case(
        start_date=start_date, clock_iso=initial_clock_iso,
    )
    case = deliver_result(
        case_id=case["id"], result="EMPLOYMENT_AUTHORIZED",
    )
    return employee, form, case


def setup_employee_with_fnc_case(
    *,
    start_date: str = "2026-06-01",
    initial_clock_iso: str = "2026-06-02T08:00:00.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build employee + Section 2 done + FNC case (pre-close)."""
    employee, form, case = setup_employee_with_pending_case(
        start_date=start_date, clock_iso=initial_clock_iso,
    )
    case = deliver_result(case_id=case["id"], result="FNC")
    return employee, form, case


# ===========================================================================
# Tier 5 — Section 3 / Reverification lifecycle
# ===========================================================================
def setup_ead_employee_with_open_reverification(
    *,
    ead_expiration_date: str = "2026-08-01",
    start_date: str = "2026-06-01",
    initial_clock_iso: str = "2026-06-02T08:00:00.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """Build an F1_OPT employee whose Section 2 is signed with an EAD
    I-766. Per PRD §3.4 this opens a ReverificationEvent
    {reason=WORK_AUTH_EXPIRY, resolution_deadline=EAD expiry}.

    Returns (employee, form, ead_document, reverification_event).
    """
    employee, form, ead = setup_employee_with_ead_section2_done(
        clock_iso=initial_clock_iso,
        start_date=start_date,
        ead_expiration_date=ead_expiration_date,
    )
    events = list_reverification_events(employee["id"])
    # The single open event triggered by the EAD.
    open_events = [
        e for e in events
        if e.get("triggering_form_id") == form["id"]
        and e.get("reason") == "WORK_AUTH_EXPIRY"
    ]
    assert open_events, (
        f"Setup failed: expected ReverificationEvent with reason="
        f"WORK_AUTH_EXPIRY triggered by form {form['id']!r}; "
        f"got events {events!r}"
    )
    return employee, form, ead, open_events[0]


def supersede_with_reverification_form(
    *,
    employee_id: str,
    predecessor_form_id: str,
    new_ead_expiration_date: str = "2030-01-01",
    clock_iso: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a REVERIFICATION form that supersedes the predecessor;
    walk Section 1 attestation, register a new LIST_A document, sign
    Section 2.

    PRD §3.3 / §3.4: successor reaching SECTION_2_DONE flips predecessor
    to SUPERSEDED and resolves any open WORK_AUTH_EXPIRY
    ReverificationEvent triggered by the predecessor.

    Returns (new_form, new_doc).
    """
    if clock_iso is not None:
        advance_clock_to(clock_iso)
    new_form = create_i9_form(
        employee_id=employee_id,
        form_kind="REVERIFICATION",
        supersedes_form_id=predecessor_form_id,
    )
    new_form = attest_section1(
        employee_id=employee_id, form_id=new_form["id"],
    )
    new_doc = register_ead_document(
        employee_id=employee_id,
        expiration_date=new_ead_expiration_date,
    )
    # Use a distinct EmployerRep operator id so segregation of duties
    # is satisfied if the test had Employee=attester earlier.
    new_form = sign_section2(
        employee_id=employee_id,
        form_id=new_form["id"],
        list_a_document_id=new_doc["id"],
        employer_rep_id=EMPLOYER_REP_SECONDARY_ID,
    )
    return new_form, new_doc


# ===========================================================================
# Tier 6 — Difficulty-design composite scenarios.
# Each fixture matches the test_recipe.setup of one or more instances in
# SCAFFOLD_DIFFICULTY_DESIGN.yaml so the Stage 2 tests can import setup
# by name and assert.
# ===========================================================================
def setup_initial_then_rehire_scenario() -> Dict[str, Any]:
    """Difficulty-design recipe: dual_variant_calc /
    section2_deadline_initial_vs_rehire.

    Build Employee A through an INITIAL Section 2 done on 2026-06-02,
    later (after clock advance) PATCH the start_date and open a REHIRE
    form. Returns context with initial_form, initial_deadline,
    rehire_form, rehire_deadline.
    """
    advance_clock_to("2026-05-15T08:00:00.000Z")
    employee = create_employee(
        start_date="2026-06-01", citizenship_status="US_CITIZEN",
    )
    initial_employee_after_create = employee  # holds initial section2_deadline
    form = create_i9_form(
        employee_id=employee["id"], form_kind="INITIAL",
    )
    form = attest_section1(employee_id=employee["id"], form_id=form["id"])
    # Advance to 2026-06-02 to allow Section 2 sign on day 1.
    advance_clock_to("2026-06-02T08:00:00.000Z")
    doc = register_list_a_document(
        employee_id=employee["id"], expiration_date="2030-01-01",
    )
    form = sign_section2(
        employee_id=employee["id"], form_id=form["id"],
        list_a_document_id=doc["id"],
    )
    # Snapshot employee post-initial Section 2 (deadline still derived
    # from the initial start_date).
    post_initial_employee = get_employee(employee["id"])
    # Rehire flow.
    advance_clock_to("2026-07-08T08:00:00.000Z")
    patched = get_success_data(
        api_client.update_employee(
            employee["id"],
            update_employee_payload(
                version=post_initial_employee["version"],
                start_date="2026-07-10",
            ),
            TEST_USERS["hr_staff_headers"],
        ),
    )
    rehire_form = create_i9_form(
        employee_id=employee["id"],
        form_kind="REHIRE",
        supersedes_form_id=form["id"],
    )
    return {
        "employee_initial_view": initial_employee_after_create,
        "employee_after_section2": post_initial_employee,
        "employee_after_patch": patched,
        "initial_form": form,
        "rehire_form": rehire_form,
        "doc": doc,
    }


def setup_juneteenth_holiday_scenario() -> Dict[str, Any]:
    """Difficulty-design recipe: combinatorial_formula /
    section2_deadline_3_working_days_holiday_skip.

    Start date 2026-06-19 (Juneteenth, federal holiday) → expected
    section2_deadline 2026-06-24T23:59:59.999Z.
    """
    advance_clock_to("2026-06-10T08:00:00.000Z")
    employee = create_employee(
        start_date="2026-06-19", citizenship_status="US_CITIZEN",
    )
    return {"employee": employee}


def setup_tnc_juneteenth_scenario() -> Dict[str, Any]:
    """Difficulty-design recipe: combinatorial_formula /
    tnc_contest_10_working_days_holiday_skip.

    TNC opened at 2026-06-15T09:00:00.000Z → expected
    tnc_contest_deadline 2026-06-30T23:59:59.999Z (skipping Juneteenth
    2026-06-19).
    """
    employee, form, _doc = setup_employee_with_section2_done(
        start_date="2026-06-01", clock_iso="2026-06-02T08:00:00.000Z",
    )
    advance_clock_to("2026-06-15T09:00:00.000Z")
    case = submit_everify_case(
        employee_id=employee["id"], i9_form_id=form["id"],
    )
    case = deliver_result(
        case_id=case["id"], result="TNC", tnc_kind="DHS",
    )
    return {"employee": employee, "form": form, "case": case}


def setup_tnc_cycle_scenario() -> Dict[str, Any]:
    """Difficulty-design recipe: non_linear_state_machine /
    everify_case_tnc_branching_with_cycle.

    Build TNC case + Employee submits CONTEST → cycle TNC -> PENDING.
    """
    employee, form, case = setup_employee_with_tnc_case(
        tnc_kind="SSA",
        tnc_opened_at="2026-06-15T09:00:00.000Z",
    )
    return {"employee": employee, "form": form, "case": case}


def setup_supersession_with_ead_scenario() -> Dict[str, Any]:
    """Difficulty-design recipe: non_linear_state_machine /
    i9_form_lineage_self_referential_branching AND transitive_cascade /
    section2_supersession_cascade_depth_2.

    Build EAD-backed employee + initial Section 2 with EAD expiring
    2026-08-01 (auto-opens ReverificationEvent). Then on 2026-07-25,
    HR opens a REVERIFICATION form, Employee attests Section 1,
    EmployerRep#2 signs Section 2 with a fresh LIST_A doc.
    """
    employee, initial_form, ead, rever = (
        setup_ead_employee_with_open_reverification(
            ead_expiration_date="2026-08-01",
        )
    )
    new_form, new_doc = supersede_with_reverification_form(
        employee_id=employee["id"],
        predecessor_form_id=initial_form["id"],
        new_ead_expiration_date="2030-01-01",
        clock_iso="2026-07-25T08:00:00.000Z",
    )
    return {
        "employee": employee,
        "initial_form": initial_form,
        "initial_ead": ead,
        "open_reverification": rever,
        "new_form": new_form,
        "new_doc": new_doc,
    }


def setup_sweep_cascade_scenario() -> Dict[str, Any]:
    """Difficulty-design recipe: transitive_cascade /
    tnc_sweep_cascade_depth_3.

    Build TNC employee with EAD I-766 expiring 2026-08-01 (also opens
    a WORK_AUTH_EXPIRY ReverificationEvent). TNC opened 2026-06-15 ->
    tnc_contest_deadline 2026-06-30. Advance past deadline (07-01) and
    run sweep.
    """
    advance_clock_to("2026-06-02T08:00:00.000Z")
    employee = create_employee(
        citizenship_status="ALIEN_AUTHORIZED",
        start_date="2026-06-01",
        work_authorization_expiry="2026-08-01",
        visa_class="F1_OPT",
    )
    form = create_i9_form(
        employee_id=employee["id"], form_kind="INITIAL",
    )
    form = attest_section1(employee_id=employee["id"], form_id=form["id"])
    ead = register_ead_document(
        employee_id=employee["id"], expiration_date="2026-08-01",
    )
    form = sign_section2(
        employee_id=employee["id"], form_id=form["id"],
        list_a_document_id=ead["id"],
    )
    case = submit_everify_case(
        employee_id=employee["id"], i9_form_id=form["id"],
    )
    advance_clock_to("2026-06-15T09:00:00.000Z")
    case = deliver_result(
        case_id=case["id"], result="TNC", tnc_kind="SSA",
    )
    return {
        "employee": employee, "form": form, "ead": ead, "case": case,
    }


def setup_two_tnc_employees_for_dual_close() -> Dict[str, Any]:
    """Difficulty-design recipe: dual_variant_calc /
    tnc_close_voluntary_vs_sweep_default.

    Build two parallel TNC employees B and C with TNC opened
    2026-06-15T09:00:00.000Z, tnc_kind=SSA, deadline 2026-06-30.
    """
    employee_b, form_b, case_b = setup_employee_with_tnc_case(
        tnc_kind="SSA",
        tnc_opened_at="2026-06-15T09:00:00.000Z",
        initial_clock_iso="2026-06-02T08:00:00.000Z",
    )
    # Clock now at 2026-06-15. Build a second employee on the same
    # clock — their TNC will be opened a millisecond later but with
    # the same federal-working-day computation.
    employee_c = create_employee(
        start_date="2026-06-01", citizenship_status="US_CITIZEN",
    )
    form_c = create_i9_form(
        employee_id=employee_c["id"], form_kind="INITIAL",
    )
    form_c = attest_section1(
        employee_id=employee_c["id"], form_id=form_c["id"],
    )
    doc_c = register_list_a_document(
        employee_id=employee_c["id"], expiration_date="2030-01-01",
    )
    form_c = sign_section2(
        employee_id=employee_c["id"],
        form_id=form_c["id"],
        list_a_document_id=doc_c["id"],
    )
    case_c = submit_everify_case(
        employee_id=employee_c["id"], i9_form_id=form_c["id"],
    )
    case_c = deliver_result(
        case_id=case_c["id"], result="TNC", tnc_kind="SSA",
    )
    return {
        "employee_b": employee_b, "form_b": form_b, "case_b": case_b,
        "employee_c": employee_c, "form_c": form_c, "case_c": case_c,
    }


def setup_section2_deadline_boundary_scenario(
    *,
    advance_to_deadline: bool = True,
) -> Dict[str, Any]:
    """Difficulty-design recipe: boundary_precision_check /
    section2_deadline_inclusive_boundary.

    Build employee L with start_date 2026-06-01 →
    section2_deadline = 2026-06-04T23:59:59.999Z. Attest Section 1,
    register a LIST_A passport expiring 2030-01-01. If
    advance_to_deadline is True, push the clock to exactly the deadline
    so the test can sign at the boundary.
    """
    advance_clock_to("2026-05-30T08:00:00.000Z")
    employee = create_employee(
        start_date="2026-06-01", citizenship_status="US_CITIZEN",
    )
    form = create_i9_form(
        employee_id=employee["id"], form_kind="INITIAL",
    )
    form = attest_section1(
        employee_id=employee["id"], form_id=form["id"],
    )
    doc = register_list_a_document(
        employee_id=employee["id"], expiration_date="2030-01-01",
    )
    if advance_to_deadline:
        advance_clock_to("2026-06-04T23:59:59.999Z")
    return {"employee": employee, "form": form, "doc": doc}


def setup_form_at_section1_done_with_expired_list_a(
) -> Dict[str, Any]:
    """Difficulty-design recipe: priority_pair_validation_conflict /
    doc_list_rule_vs_document_expired_on_section2 AND
    cross_entity_state_dependency / section2_requires_document_not_expired.

    Build an employee at SECTION_1_DONE, register an expired LIST_A
    passport (2025-12-01) and a fresh LIST_B driver's license. Clock
    set to 2026-06-10 so the LIST_A is expired.
    """
    advance_clock_to("2026-05-30T08:00:00.000Z")
    employee = create_employee(
        start_date="2026-06-01", citizenship_status="US_CITIZEN",
    )
    form = create_i9_form(
        employee_id=employee["id"], form_kind="INITIAL",
    )
    form = attest_section1(
        employee_id=employee["id"], form_id=form["id"],
    )
    doc_a = register_list_a_document(
        employee_id=employee["id"], expiration_date="2025-12-01",
    )
    doc_b = register_list_b_document(
        employee_id=employee["id"], expiration_date="2030-01-01",
    )
    advance_clock_to("2026-06-10T08:00:00.000Z")
    return {
        "employee": employee, "form": form,
        "expired_list_a": doc_a, "valid_list_b": doc_b,
    }


def setup_form_at_section2_done_then_dup_attempt() -> Dict[str, Any]:
    """Difficulty-design recipe: priority_pair_validation_conflict /
    state_vs_segregation_of_duties_on_section2.

    Build employee J. J attests Section 1 with X-User-ID = J.id.
    EmployerRep#1 signs Section 2. Form is now SECTION_2_DONE. Returns
    employee and form ready for the dup-sign attempt by the Section 1
    attester.
    """
    employee, form, doc = setup_employee_with_section2_done(
        clock_iso="2026-05-30T08:00:00.000Z",
    )
    return {"employee": employee, "form": form, "doc": doc}


def setup_employee_for_initial_form_uniqueness() -> Dict[str, Any]:
    """Difficulty-design recipe: resource_temporal_overlap /
    at_most_one_initial_i9form_per_employee.

    Returns employee R + the first INITIAL form (DRAFT). Tests can then
    attempt a second INITIAL or void the first to verify the rule.
    """
    employee = create_employee(
        start_date="2026-06-01", citizenship_status="US_CITIZEN",
    )
    form = create_i9_form(
        employee_id=employee["id"], form_kind="INITIAL",
    )
    return {"employee": employee, "first_initial_form": form}


def setup_employee_with_single_open_case(
) -> Dict[str, Any]:
    """Difficulty-design recipe: resource_temporal_overlap /
    at_most_one_open_everify_case_per_employee.

    Build employee Q through SECTION_2_DONE + one PENDING case.
    Returns (employee, form, first_case).
    """
    employee, form, case = setup_employee_with_pending_case(
        clock_iso="2026-06-02T08:00:00.000Z",
    )
    return {"employee": employee, "form": form, "first_case": case}


def setup_employee_at_section1_only_for_everify_attempt(
) -> Dict[str, Any]:
    """Difficulty-design recipe: cross_entity_state_dependency /
    everify_submit_requires_i9form_section2_done.

    Build employee N with form_status=SECTION_1_DONE only (Section 2
    NOT signed). Returns (employee, form).
    """
    advance_clock_to("2026-06-02T08:00:00.000Z")
    employee = create_employee(
        start_date="2026-06-01", citizenship_status="US_CITIZEN",
    )
    form = create_i9_form(
        employee_id=employee["id"], form_kind="INITIAL",
    )
    form = attest_section1(
        employee_id=employee["id"], form_id=form["id"],
    )
    return {"employee": employee, "form": form}


def setup_employee_for_idempotent_replay() -> Dict[str, Any]:
    """Difficulty-design recipe: compensating_invariant /
    idempotent_replay_preserves_case_count.

    Build employee S through SECTION_2_DONE. Caller will submit
    multiple POSTs with the same idempotency_key.
    """
    employee, form, _doc = setup_employee_with_section2_done(
        clock_iso="2026-06-02T08:00:00.000Z",
    )
    return {"employee": employee, "form": form}


def setup_employee_for_section3_supersession() -> Dict[str, Any]:
    """Difficulty-design recipe: compensating_invariant /
    section3_supersession_preserves_reverification_resolution_count.

    Build EAD-backed employee T with one open WORK_AUTH_EXPIRY event,
    then drive the Section-3 supersession to RESOLVED. Returns
    employee, initial_form, ead, open_reverification (pre-cascade),
    new_form, new_doc.
    """
    employee, initial_form, ead, rever = (
        setup_ead_employee_with_open_reverification(
            ead_expiration_date="2026-08-01",
        )
    )
    new_form, new_doc = supersede_with_reverification_form(
        employee_id=employee["id"],
        predecessor_form_id=initial_form["id"],
        new_ead_expiration_date="2030-01-01",
        clock_iso="2026-07-25T08:00:00.000Z",
    )
    return {
        "employee": employee,
        "initial_form": initial_form,
        "initial_ead": ead,
        "open_reverification_pre_cascade": rever,
        "new_form": new_form,
        "new_doc": new_doc,
    }


__all__ = [
    # Clock / sweep
    "advance_clock_to", "run_sweep",
    # Read helpers
    "get_employee", "get_everify_case",
    "list_audit_events", "list_reverification_events", "list_i9_forms",
    # Foundation creators
    "create_employee",
    "create_i9_form",
    "attest_section1",
    "register_document",
    "sign_section2",
    "void_form",
    "submit_everify_case",
    "deliver_result",
    "submit_tnc_decision",
    "close_case",
    # Document helpers
    "register_list_a_document",
    "register_list_b_document",
    "register_list_c_document",
    "register_ead_document",
    # Form lifecycle helpers
    "create_form_at_section1_done",
    "create_form_at_section2_done",
    # Employee + Section 2 done
    "setup_employee_with_section2_done",
    "setup_employee_with_ead_section2_done",
    # E-Verify lifecycle
    "setup_employee_with_pending_case",
    "setup_employee_with_tnc_case",
    "setup_employee_with_employment_authorized_case",
    "setup_employee_with_fnc_case",
    # Section 3 / Reverification
    "setup_ead_employee_with_open_reverification",
    "supersede_with_reverification_form",
    # Difficulty-design composite scenarios
    "setup_initial_then_rehire_scenario",
    "setup_juneteenth_holiday_scenario",
    "setup_tnc_juneteenth_scenario",
    "setup_tnc_cycle_scenario",
    "setup_supersession_with_ead_scenario",
    "setup_sweep_cascade_scenario",
    "setup_two_tnc_employees_for_dual_close",
    "setup_section2_deadline_boundary_scenario",
    "setup_form_at_section1_done_with_expired_list_a",
    "setup_form_at_section2_done_then_dup_attempt",
    "setup_employee_for_initial_form_uniqueness",
    "setup_employee_with_single_open_case",
    "setup_employee_at_section1_only_for_everify_attempt",
    "setup_employee_for_idempotent_replay",
    "setup_employee_for_section3_supersession",
]
