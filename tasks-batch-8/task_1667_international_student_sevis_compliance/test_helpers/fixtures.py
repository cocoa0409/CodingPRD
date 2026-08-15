"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server with an empty database).
Lenient get_success_data is used internally so setup failures surface as
clear "Setup failed" errors instead of confusing assertion failures.

Student-role calls that are ownership-gated (own financial documents,
address reports, employment periods, OPT FILE) always thread the acting
student's id through make_student_headers (PRD §2.1).
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS
from .factories import (
    create_address_report_payload,
    create_employment_authorization_payload,
    create_employment_period_payload,
    create_i20_form_payload,
    create_program_extension_payload,
    create_rcl_payload,
    create_sevis_record_payload,
    create_status_violation_payload,
    create_student_payload,
    create_term_enrollment_payload,
    create_transfer_request_payload,
    create_travel_endorsement_payload,
    extension_decision_payload,
    review_document_payload,
    rcl_decision_payload,
)
from .test_users import TEST_USERS, make_student_headers

PDSO = TEST_USERS["pdso_headers"]
DSO = TEST_USERS["dso_headers"]

DEFAULT_PROGRAM_START = TEST_DEFAULTS["PROGRAM_START"]
DEFAULT_PROGRAM_END = TEST_DEFAULTS["PROGRAM_END"]
DEFAULT_TERM_START = TEST_DEFAULTS["TERM_START"]
DEFAULT_TERM_END = TEST_DEFAULTS["TERM_END"]


# ---------------------------------------------------------------------------
# Primitive steps
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, PDSO))


def create_student(**overrides) -> dict:
    return get_success_data(api_client.create_student(create_student_payload(**overrides), DSO))


def get_student(student_id: str) -> dict:
    return get_success_data(api_client.get_student(student_id, DSO))


def submit_document(student_id: str, amount_usd_cents: int = TEST_DEFAULTS["FUNDING_CENTS"],
                    issue_date: str = TEST_DEFAULTS["FUNDING_ISSUE_DATE"],
                    document_type: str = "BANK_STATEMENT") -> dict:
    payload = {
        "document_type": document_type,
        "amount_usd_cents": amount_usd_cents,
        "issue_date": issue_date,
    }
    return get_success_data(
        api_client.submit_financial_document(student_id, payload, DSO)
    )


def review_document(document_id: str, decision: str = "VERIFIED",
                    note: Optional[str] = None) -> dict:
    return get_success_data(
        api_client.review_financial_document(
            document_id, review_document_payload(decision, note), DSO,
        )
    )


def submit_verified_document(student_id: str,
                             amount_usd_cents: int = TEST_DEFAULTS["FUNDING_CENTS"],
                             issue_date: str = TEST_DEFAULTS["FUNDING_ISSUE_DATE"],
                             document_type: str = "BANK_STATEMENT") -> dict:
    doc = submit_document(student_id, amount_usd_cents, issue_date, document_type)
    return review_document(doc["id"], "VERIFIED")


def create_sevis_record(student_id: str,
                        program_start_date: str = DEFAULT_PROGRAM_START,
                        program_end_date: str = DEFAULT_PROGRAM_END) -> dict:
    payload = create_sevis_record_payload(
        program_start_date=program_start_date, program_end_date=program_end_date,
    )
    return get_success_data(api_client.create_sevis_record(student_id, payload, DSO))


def get_record(student_id: str) -> dict:
    """The student's single SEVIS record (1:1)."""
    data, _meta = validate_paginated(api_client.list_sevis_records(student_id, DSO))
    assert len(data) == 1, f"expected exactly one SEVIS record, got {len(data)}"
    return data[0]


def initialize_record(record_id: str) -> dict:
    return get_success_data(api_client.initialize_sevis_record(record_id, DSO))


def create_i20_form(student_id: str, sevis_record_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_i20_form(
            student_id, create_i20_form_payload(sevis_record_id, **overrides), DSO,
        )
    )


def issue_i20_form(i20_id: str) -> dict:
    return get_success_data(api_client.issue_i20_form(i20_id, DSO))


def get_i20_form(i20_id: str) -> dict:
    return get_success_data(api_client.get_i20_form(i20_id, DSO))


def create_term_enrollment(student_id: str, term_code: str = TEST_DEFAULTS["TERM_CODE"],
                           term_start_date: str = DEFAULT_TERM_START,
                           term_end_date: str = DEFAULT_TERM_END,
                           enrolled_credits: int = TEST_DEFAULTS["ENROLLED_CREDITS"]
                           ) -> dict:
    payload = create_term_enrollment_payload(
        student_id,
        term_code=term_code,
        term_start_date=term_start_date,
        term_end_date=term_end_date,
        enrolled_credits=enrolled_credits,
    )
    return get_success_data(api_client.create_term_enrollment(payload, DSO))


def get_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.get_term_enrollment(enrollment_id, DSO))


def register_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.register_term_enrollment(enrollment_id, DSO))


def create_rcl(enrollment_id: str, reason_category: str = "ACADEMIC",
               requested_credits: int = 6) -> dict:
    return get_success_data(
        api_client.create_reduced_course_load(
            create_rcl_payload(
                enrollment_id,
                reason_category=reason_category,
                requested_credits=requested_credits,
            ),
            DSO,
        )
    )


def decide_rcl(rcl_id: str, decision: str = "APPROVED") -> dict:
    return get_success_data(
        api_client.decide_reduced_course_load(
            rcl_id, rcl_decision_payload(decision), DSO,
        )
    )


def create_authorization(student_id: str, auth_type: str = "CPT", **overrides) -> dict:
    payload = create_employment_authorization_payload(
        student_id, auth_type=auth_type, **overrides,
    )
    return get_success_data(api_client.create_employment_authorization(payload, DSO))


def transition_authorization(auth_id: str, action: str, outcome: Optional[str] = None,
                             uscis_receipt_number: Optional[str] = None,
                             headers=None) -> dict:
    payload = {"action": action}
    if outcome is not None:
        payload["outcome"] = outcome
    if uscis_receipt_number is not None:
        payload["uscis_receipt_number"] = uscis_receipt_number
    return get_success_data(
        api_client.transition_employment_authorization(
            auth_id, payload, headers or DSO,
        )
    )


def get_authorization(auth_id: str) -> dict:
    return get_success_data(api_client.get_employment_authorization(auth_id, DSO))


def report_period(auth_id: str, student_id: str, employer_name: str = "Acme Corp",
                  start_date: str = "2027-01-01", end_date: Optional[str] = "2027-01-31",
                  hours_per_week: int = 40) -> dict:
    payload = create_employment_period_payload(
        employer_name=employer_name, start_date=start_date,
        hours_per_week=hours_per_week,
    )
    if end_date is not None:
        payload["end_date"] = end_date
    return get_success_data(
        api_client.create_employment_period(
            auth_id, payload, make_student_headers(student_id),
        )
    )


def issue_endorsement(i20_id: str, travel_departure_date: str = "2026-12-12",
                      travel_return_date: str = "2027-01-10") -> dict:
    """Issue a travel endorsement, threading the form's current version (OCC)."""
    form = get_i20_form(i20_id)
    payload = create_travel_endorsement_payload(
        form["version"],
        travel_departure_date=travel_departure_date,
        travel_return_date=travel_return_date,
    )
    return get_success_data(api_client.create_travel_endorsement(i20_id, payload, DSO))


def create_transfer_request(student_id: str, direction: str = "OUT",
                            target_school_code: str = "ABC123",
                            release_date: str = "2026-09-01") -> dict:
    payload = create_transfer_request_payload(
        direction=direction, target_school_code=target_school_code,
        release_date=release_date,
    )
    return get_success_data(
        api_client.create_transfer_request(student_id, payload, DSO)
    )


def create_extension(student_id: str, new_program_end_date: str,
                     reason: str = "Thesis completion") -> dict:
    """Request a program extension, threading the record's current version."""
    record = get_record(student_id)
    payload = create_program_extension_payload(
        new_program_end_date, record["version"], reason=reason,
    )
    return get_success_data(
        api_client.create_program_extension(student_id, payload, DSO)
    )


def decide_extension(extension_id: str, decision: str = "APPROVED") -> dict:
    return get_success_data(
        api_client.decide_program_extension(
            extension_id, extension_decision_payload(decision), DSO,
        )
    )


def create_violation(student_id: str,
                     violation_type: str = "UNAUTHORIZED_EMPLOYMENT",
                     description: str = "Worked off campus without authorization"
                     ) -> dict:
    return get_success_data(
        api_client.create_status_violation(
            student_id,
            create_status_violation_payload(
                violation_type=violation_type, description=description,
            ),
            DSO,
        )
    )


def transition_violation(violation_id: str, action: str,
                         outcome: Optional[str] = None, headers=None) -> dict:
    payload = {"action": action}
    if outcome is not None:
        payload["outcome"] = outcome
    return get_success_data(
        api_client.transition_status_violation(violation_id, payload, headers or DSO)
    )


def terminate_record(record_id: str, reason: str = "Unauthorized employment") -> dict:
    return get_success_data(
        api_client.terminate_sevis_record(
            record_id, {"termination_reason": reason}, PDSO,
        )
    )


# ---------------------------------------------------------------------------
# Composite setups — staged student journey (PRD §3.1–§3.3)
# ---------------------------------------------------------------------------

def setup_student_with_draft_record(student_overrides: Optional[dict] = None,
                                    program_start_date: str = DEFAULT_PROGRAM_START,
                                    program_end_date: str = DEFAULT_PROGRAM_END,
                                    clock: str = DEFAULT_CLOCK) -> dict:
    """Student + DRAFT SEVIS record."""
    set_clock(clock)
    student = create_student(**(student_overrides or {}))
    record = create_sevis_record(student["id"], program_start_date, program_end_date)
    return {"student": student, "record": record}


def setup_student_with_draft_i20(funding_cents: int = TEST_DEFAULTS["FUNDING_CENTS"],
                                 funding_issue_date: str = TEST_DEFAULTS["FUNDING_ISSUE_DATE"],
                                 i20_overrides: Optional[dict] = None,
                                 verify_document: bool = True,
                                 **record_kwargs) -> dict:
    """Student + DRAFT record + funding document + DRAFT I-20 (unissued)."""
    ctx = setup_student_with_draft_record(**record_kwargs)
    document = submit_document(ctx["student"]["id"], funding_cents, funding_issue_date)
    if verify_document:
        document = review_document(document["id"], "VERIFIED")
    i20 = create_i20_form(
        ctx["student"]["id"], ctx["record"]["id"], **(i20_overrides or {}),
    )
    ctx.update({"document": document, "i20": i20})
    return ctx


def setup_student_with_issued_i20(**kwargs) -> dict:
    """... + I-20 ISSUED (record still DRAFT)."""
    ctx = setup_student_with_draft_i20(**kwargs)
    ctx["i20"] = issue_i20_form(ctx["i20"]["id"])
    return ctx


def setup_initialized_student(**kwargs) -> dict:
    """... + record INITIAL."""
    ctx = setup_student_with_issued_i20(**kwargs)
    ctx["record"] = initialize_record(ctx["record"]["id"])
    return ctx


def setup_active_student(term_code: str = TEST_DEFAULTS["TERM_CODE"],
                         term_start_date: str = DEFAULT_TERM_START,
                         term_end_date: str = DEFAULT_TERM_END,
                         enrolled_credits: int = TEST_DEFAULTS["ENROLLED_CREDITS"],
                         register: bool = True,
                         **kwargs) -> dict:
    """... + term enrollment (+ registration) -> record ACTIVE.

    With register=False the chain stops at INITIAL with the enrollment PENDING.
    """
    ctx = setup_initialized_student(**kwargs)
    enrollment = create_term_enrollment(
        ctx["student"]["id"], term_code, term_start_date, term_end_date,
        enrolled_credits,
    )
    ctx["enrollment"] = enrollment
    if register:
        ctx["enrollment"] = register_enrollment(enrollment["id"])
        ctx["record"] = get_record(ctx["student"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Composite setups — OPT_POST authorization walked to APPROVED (PRD §3.5)
# ---------------------------------------------------------------------------

def setup_opt_post_approved(eval_clock: str,
                            program_start_date: str = "2025-08-25",
                            program_end_date: str = "2026-12-18",
                            auth_start_date: str = "2026-12-19",
                            auth_end_date: str = "2027-12-18",
                            file_clock: str = "2026-10-01",
                            **active_kwargs) -> dict:
    """ACTIVE student + OPT_POST authorization DRAFT -> RECOMMENDED -> FILED
    -> APPROVED, with the logical clock left at `eval_clock`.

    The FILE step is performed by the owning student (PRD §3.5).
    """
    ctx = setup_active_student(
        program_start_date=program_start_date,
        program_end_date=program_end_date,
        **active_kwargs,
    )
    auth = create_authorization(
        ctx["student"]["id"],
        auth_type="OPT_POST",
        hours_per_week=40,
        start_date=auth_start_date,
        end_date=auth_end_date,
    )
    auth = transition_authorization(auth["id"], "RECOMMEND")
    set_clock(file_clock)
    auth = transition_authorization(
        auth["id"], "FILE", uscis_receipt_number="IOE1234567890",
        headers=make_student_headers(ctx["student"]["id"]),
    )
    auth = transition_authorization(auth["id"], "ADJUDICATE", outcome="APPROVED")
    set_clock(eval_clock)
    ctx["authorization"] = auth
    return ctx


# ---------------------------------------------------------------------------
# Composite setups — program extension REQUESTED (PRD §3.8)
# ---------------------------------------------------------------------------

def setup_extension_requested(new_program_end_date: str,
                              reason: str = "Research delay",
                              **active_kwargs) -> dict:
    """ACTIVE student + ProgramExtension in REQUESTED."""
    ctx = setup_active_student(**active_kwargs)
    extension = create_extension(ctx["student"]["id"], new_program_end_date, reason)
    ctx["extension"] = extension
    ctx["record"] = get_record(ctx["student"]["id"])
    return ctx
