"""Composite setup helpers.

Multi-step preconditions (firm -> applicant -> request -> selection ->
fingerprint -> submit -> exams -> approve -> activate) are encapsulated here
so tests focus on assertions. Every helper builds from scratch against a
freshly restarted server and returns server response payloads.

Header users: the submitter and reviewer are always distinct user ids so the
segregation-of-duties rule (PRD Section 2.9) never fires accidentally.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    make_amendment_filing_payload,
    make_applicant_payload,
    make_disclosure_event_payload,
    make_exam_requirement_payload,
    make_exam_window_payload,
    make_fingerprint_submission_payload,
    make_firm_payload,
    make_jurisdiction_selection_payload,
    make_registration_request_payload,
    make_renewal_invoice_payload,
    make_termination_filing_payload,
    make_u5_comment_payload,
)
from .test_users import TEST_USERS, make_user_headers

_RP = TEST_USERS["registration_principal_headers"]
_CO = TEST_USERS["compliance_officer_headers"]
_FC = TEST_USERS["finance_clerk_headers"]
_SO = TEST_USERS["system_operator_headers"]
_REG = TEST_USERS["regulator_headers"]

# Exam sets spawned at submit time per registration category (PRD Section 3.4).
CATEGORY_EXAMS = {
    "RR": ("SIE", "S7", "S63"),
    "IA": ("SIE", "S66"),
    "PRINCIPAL": ("SIE", "S7", "S24"),
}


def set_clock(to_iso8601: str):
    """Advance the desk's logical clock (PRD Section 2.5)."""
    resp = api_client.set_clock(to_iso8601, _SO)
    return get_success_data(resp)


def create_firm(**overrides):
    resp = api_client.create_firm(make_firm_payload(**overrides), _SO)
    return get_success_data(resp)


def create_applicant(**overrides):
    resp = api_client.create_applicant(make_applicant_payload(**overrides), _RP)
    return get_success_data(resp)


def create_registration_request(applicant_id, firm_id, **overrides):
    resp = api_client.create_registration_request(
        make_registration_request_payload(applicant_id, firm_id, **overrides), _RP
    )
    return get_success_data(resp)


def add_jurisdiction_selection(request_id, jurisdiction_code="CA",
                               jurisdiction_type="STATE"):
    resp = api_client.create_jurisdiction_selection(
        make_jurisdiction_selection_payload(
            request_id,
            jurisdiction_code=jurisdiction_code,
            jurisdiction_type=jurisdiction_type,
        ),
        _RP,
    )
    return get_success_data(resp)


def create_fingerprint_submission(request_id, channel="ELECTRONIC"):
    resp = api_client.create_fingerprint_submission(
        make_fingerprint_submission_payload(request_id, submission_channel=channel),
        _RP,
    )
    return get_success_data(resp)


def process_fingerprint(submission_id, outcome="CLEARED", rejection_reason=None):
    payload = {"outcome": outcome}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    resp = api_client.process_fingerprint_submission(submission_id, payload, _SO)
    return get_success_data(resp)


def submit_request(request_id, submitter_user_id="rp-submitter-1"):
    resp = api_client.submit_registration_request(
        request_id, make_user_headers(submitter_user_id, "RegistrationPrincipal")
    )
    return get_success_data(resp)


def add_exam_requirement(request_id, exam_code):
    resp = api_client.create_exam_requirement(
        make_exam_requirement_payload(request_id, exam_code=exam_code), _RP
    )
    return get_success_data(resp)


def list_exam_requirements(request_id):
    resp = api_client.list_exam_requirements(
        _SO, params={"registration_request_id": request_id}
    )
    return get_success_data(resp)


def schedule_exam_window(requirement_id, window_start, window_end):
    resp = api_client.create_exam_window(
        make_exam_window_payload(
            requirement_id, window_start=window_start, window_end=window_end
        ),
        _RP,
    )
    return get_success_data(resp)


def record_exam_result(window_id, result):
    resp = api_client.record_exam_result(window_id, {"result": result}, _SO)
    return get_success_data(resp)


def pass_exam_requirement(requirement_id, window_start, window_end,
                          pass_clock=None):
    """Schedule a window and record PASS inside it. Returns the window."""
    win = schedule_exam_window(requirement_id, window_start, window_end)
    if pass_clock is not None:
        set_clock(pass_clock)
    record_exam_result(win["id"], "PASS")
    return win


def approve_request(request_id, reviewer_user_id="co-reviewer-1"):
    resp = api_client.approve_registration_request(
        request_id, make_user_headers(reviewer_user_id, "ComplianceOfficer")
    )
    return get_success_data(resp)


def create_disclosure_event(applicant_id, **overrides):
    resp = api_client.create_disclosure_event(
        make_disclosure_event_payload(applicant_id, **overrides), _RP
    )
    return get_success_data(resp)


def file_amendment(disclosure_event_id, narrative_text=None,
                   filer_user_id=None):
    """File a U4 amendment; returns the created AmendmentFiling."""
    payload = make_amendment_filing_payload(disclosure_event_id)
    if narrative_text is not None:
        payload["narrative_text"] = narrative_text
    headers = (
        make_user_headers(filer_user_id, "RegistrationPrincipal")
        if filer_user_id
        else _RP
    )
    resp = api_client.create_amendment_filing(payload, headers)
    return get_success_data(resp)


def issue_renewal_invoice(request_id, cycle_year=2027):
    resp = api_client.create_renewal_invoice(
        make_renewal_invoice_payload(request_id, cycle_year=cycle_year), _FC
    )
    return get_success_data(resp)


def create_termination_filing(request_id, filer_user_id=None, **overrides):
    payload = make_termination_filing_payload(request_id, **overrides)
    headers = (
        make_user_headers(filer_user_id, "RegistrationPrincipal")
        if filer_user_id
        else _RP
    )
    resp = api_client.create_termination_filing(payload, headers)
    return get_success_data(resp)


def add_u5_comment(termination_filing_id, comment_text, role="ComplianceOfficer",
                   user_id=None):
    headers = make_user_headers(user_id or f"{role.lower()}-commenter-1", role)
    resp = api_client.create_u5_comment(
        make_u5_comment_payload(termination_filing_id, comment_text=comment_text),
        headers,
    )
    return get_success_data(resp)


def get_request(request_id):
    return get_success_data(api_client.get_registration_request(request_id, _SO))


def get_invoice(invoice_id):
    return get_success_data(api_client.get_renewal_invoice(invoice_id, _SO))


def get_selection(selection_id):
    return get_success_data(api_client.get_jurisdiction_selection(selection_id, _SO))


def get_event(event_id):
    return get_success_data(api_client.get_disclosure_event(event_id, _SO))


def get_firm(firm_id):
    return get_success_data(api_client.get_firm(firm_id, _SO))


def get_affiliation(affiliation_id):
    return get_success_data(api_client.get_affiliation_request(affiliation_id, _SO))


def get_termination_filing(filing_id):
    return get_success_data(api_client.get_termination_filing(filing_id, _SO))


def get_exam_requirement(requirement_id):
    return get_success_data(api_client.get_exam_requirement(requirement_id, _SO))


def create_firm_applicant_request(
    category="RR",
    jurisdictions=("CA",),
    firm_overrides=None,
    request_overrides=None,
):
    """Tier 2: firm + applicant + DRAFT request + selections.

    Returns (firm, applicant, request, selections_dict keyed by code).
    """
    firm = create_firm(**(firm_overrides or {}))
    applicant = create_applicant()
    request = create_registration_request(
        applicant["id"], firm["id"],
        **({"registration_category": category} if category else {}),
        **(request_overrides or {}),
    )
    selections = {}
    for code in jurisdictions:
        jtype = "SRO" if code in ("FINRA", "NYSE", "NASDAQ") else "STATE"
        sel = add_jurisdiction_selection(request["id"], code, jtype)
        selections[code] = sel
    return firm, applicant, request, selections


def create_submitted_request(
    category="RR",
    jurisdictions=("CA",),
    submitter_user_id="rp-submitter-1",
    firm_overrides=None,
):
    """Tier 1/2: DRAFT request with selections, then submitted.

    Returns a dict with firm, applicant, request (post-submit), selections,
    submitter_user_id, and submit-created exam requirements keyed by code.
    """
    firm, applicant, request, selections = create_firm_applicant_request(
        category=category, jurisdictions=jurisdictions,
        firm_overrides=firm_overrides,
    )
    submitted = submit_request(request["id"], submitter_user_id)
    exams = {
        row["exam_code"]: row
        for row in list_exam_requirements(request["id"])
    }
    return {
        "firm": firm,
        "applicant": applicant,
        "request": submitted,
        "selections": selections,
        "exams": exams,
        "submitter_user_id": submitter_user_id,
    }


def create_active_registration(
    category="IA",
    jurisdictions=("CA",),
    approve_date="2026-06-02",
    window_start="2026-06-01T00:00:00Z",
    window_end="2026-06-03T00:00:00Z",
    submitter_user_id="rp-submitter-1",
    reviewer_user_id="co-reviewer-1",
    firm_overrides=None,
):
    """Tier 3/5: full lifecycle through ACTIVE.

    Path: firm -> applicant -> request -> selections -> fingerprint CLEARED ->
    submit -> pass every submit-created exam (SIE first) -> approve on
    approve_date -> roll the clock to the next calendar day so the deferred
    APPROVED -> ACTIVE transition fires.

    The approval satisfies the regulatory gate (PRD Section 3.5): exams
    PASSED, one fingerprint CLEARED (so fingerprint_required reads false),
    no YES disclosures pending.

    Returns a dict with firm, applicant, request (post-activation read),
    selections (post-approval reads), exams, and the actor ids used.
    """
    firm, applicant, request, selections = create_firm_applicant_request(
        category=category, jurisdictions=jurisdictions,
        firm_overrides=firm_overrides,
    )
    fp = create_fingerprint_submission(request["id"])
    process_fingerprint(fp["id"], "CLEARED")
    submit_request(request["id"], submitter_user_id)
    exams = {
        row["exam_code"]: row
        for row in list_exam_requirements(request["id"])
    }
    # SIE first: every non-SIE exam requires SIE in SCHEDULED/PASSED/WAIVED.
    ordered = [c for c in ("SIE", "S7", "S63", "S66", "S24") if c in exams]
    for code in ordered:
        pass_exam_requirement(
            exams[code]["id"], window_start, window_end,
            pass_clock=window_start,
        )
    set_clock(f"{approve_date}T00:00:00Z")
    approve_request(request["id"], reviewer_user_id)
    # Deferred activation: clock strictly past the approval date (PRD 3.5).
    y, m, d = (int(p) for p in approve_date.split("-"))
    from datetime import date, timedelta
    next_day = (date(y, m, d) + timedelta(days=1)).isoformat()
    set_clock(f"{next_day}T00:00:00Z")
    active = get_request(request["id"])
    refreshed_selections = {code: get_selection(sel["id"])
                            for code, sel in selections.items()}
    return {
        "firm": firm,
        "applicant": applicant,
        "request": active,
        "selections": refreshed_selections,
        "exams": exams,
        "submitter_user_id": submitter_user_id,
        "reviewer_user_id": reviewer_user_id,
        "approve_date": approve_date,
    }


def create_active_registration_with_invoice(
    cycle_year=2027,
    invoice_clock=None,
    category="IA",
    jurisdictions=("CA",),
    submitter_user_id="rp-submitter-1",
    reviewer_user_id="co-reviewer-1",
):
    """ACTIVE registration plus one ISSUED renewal invoice for cycle_year.

    invoice_clock: ISO instant the clock is parked at when the invoice is
    issued (drives the late-surcharge block count per PRD Section 3.7).
    """
    ctx = create_active_registration(
        category=category,
        jurisdictions=jurisdictions,
        submitter_user_id=submitter_user_id,
        reviewer_user_id=reviewer_user_id,
    )
    if invoice_clock is not None:
        set_clock(invoice_clock)
    invoice = issue_renewal_invoice(ctx["request"]["id"], cycle_year)
    ctx["invoice"] = invoice
    return ctx


def create_terminated_registration(
    termination_reason="VOLUNTARY",
    termination_date="2026-07-31",
    filing_clock="2026-08-01T00:00:00Z",
    filer_user_id="rp-u5-filer-1",
    **active_kwargs,
):
    """ACTIVE registration, then a U5 filed against it.

    Returns the active-registration context plus 'u5' (the filing) and
    'terminated' (the request read back after the cascade).
    """
    ctx = create_active_registration(**active_kwargs)
    set_clock(filing_clock)
    u5 = create_termination_filing(
        ctx["request"]["id"],
        filer_user_id=filer_user_id,
        termination_reason=termination_reason,
        termination_date=termination_date,
    )
    ctx["u5"] = u5
    ctx["u5_filer_user_id"] = filer_user_id
    ctx["terminated"] = get_request(ctx["request"]["id"])
    return ctx
