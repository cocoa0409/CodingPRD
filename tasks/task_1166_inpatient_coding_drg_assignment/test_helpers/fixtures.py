"""Composite setup helpers for multi-step test prerequisites.

All helpers build preconditions from scratch (the runner restarts the server
before every test) and use get_success_data() so setup failures surface as
clear errors rather than confusing assertion failures. Ownership-gated calls
always thread the acting Coder's real id through make_coder_headers /
make_auditor_headers.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_assignment_payload,
    create_audit_payload,
    create_bill_payload,
    create_chart_payload,
    create_coder_payload,
    create_deficiency_payload,
    create_diagnosis_line_payload,
    create_finding_payload,
    create_patient_account_payload,
    create_procedure_line_payload,
    create_rebill_request_payload,
    create_review_payload,
    discharge_account_payload,
    record_payment_payload,
    resolve_finding_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_auditor_headers,
    make_clerk_headers,
    make_coder_headers,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]


# ─── Tier 1: single-resource creation shortcuts ─────────────────────────────

def make_coder(employee_no: str, credential: str = "CCS", full_name: str = "Test Coder") -> dict:
    res = api_client.create_coder(
        create_coder_payload(employee_no=employee_no, credential=credential, full_name=full_name),
        MANAGER,
    )
    return get_success_data(res)


def make_account(
    mrn: str,
    total_charges_cents: int = 900000,
    admit_at: str = "2026-04-20T08:00:00Z",
    patient_class: str = "INPATIENT",
    financial_class: str = "MEDICARE",
) -> dict:
    res = api_client.create_patient_account(
        create_patient_account_payload(
            mrn=mrn,
            admit_at=admit_at,
            patient_class=patient_class,
            financial_class=financial_class,
            total_charges_cents=total_charges_cents,
        ),
        MANAGER,
    )
    return get_success_data(res)


def make_chart(account_id: str, acuity: str = "MEDICAL_LOW") -> dict:
    res = api_client.create_chart(
        create_chart_payload(account_id, acuity=acuity), MANAGER
    )
    return get_success_data(res)


def discharge_account(
    account_id: str,
    discharge_at: str = "2026-04-25T10:00:00Z",
    discharge_disposition: str = "HOME",
) -> dict:
    res = api_client.discharge_patient_account(
        account_id,
        discharge_account_payload(
            discharge_at=discharge_at, discharge_disposition=discharge_disposition
        ),
        MANAGER,
    )
    return get_success_data(res)


def make_deficiency(chart_id: str, type: str = "MISSING_DISCHARGE_SUMMARY",
                    due_at: str = "2026-04-30T00:00:00Z") -> dict:
    res = api_client.create_deficiency(
        create_deficiency_payload(chart_id, type=type, due_at=due_at), MANAGER
    )
    return get_success_data(res)


def set_clock(to_iso8601: str = DEFAULT_CLOCK) -> dict:
    res = api_client.set_clock(set_clock_payload(to_iso8601), MANAGER)
    return get_success_data(res)


# ─── Tier 2: chart readiness hierarchy ──────────────────────────────────────

def setup_ready_chart(
    mrn: str,
    acuity: str = "MEDICAL_LOW",
    total_charges_cents: int = 900000,
    discharge_at: str = "2026-04-25T10:00:00Z",
    admit_at: str = "2026-04-20T08:00:00Z",
    financial_class: str = "MEDICARE",
    patient_class: str = "INPATIENT",
):
    """Discharged account + clean chart (auto-readied at discharge).

    Returns (account, chart) with chart.status == READY_FOR_CODING.
    """
    account = make_account(
        mrn,
        total_charges_cents=total_charges_cents,
        admit_at=admit_at,
        patient_class=patient_class,
        financial_class=financial_class,
    )
    chart = make_chart(account["id"], acuity=acuity)
    account = discharge_account(account["id"], discharge_at=discharge_at)
    chart = get_success_data(api_client.get_chart(chart["id"], MANAGER))
    assert chart["status"] == "READY_FOR_CODING", (
        f"setup failed: chart {chart['id']} is {chart['status']}, expected READY_FOR_CODING"
    )
    return account, chart


# ─── Tier 3: assignment lifecycle shortcuts ─────────────────────────────────

def make_assignment(chart_id: str, coder_id: str = None,
                    due_at: str = "2026-05-10T00:00:00Z") -> dict:
    payload = create_assignment_payload(chart_id, due_at=due_at)
    if coder_id is not None:
        payload["coder_id"] = coder_id
    res = api_client.create_assignment(payload, MANAGER)
    return get_success_data(res)


def start_assignment(assignment_id: str, coder_id: str) -> dict:
    res = api_client.start_assignment(assignment_id, make_coder_headers(coder_id))
    return get_success_data(res)


def setup_assigned(
    mrn: str,
    employee_no: str,
    acuity: str = "MEDICAL_LOW",
    credential: str = "CCS",
    total_charges_cents: int = 900000,
    discharge_at: str = "2026-04-25T10:00:00Z",
    due_at: str = "2026-05-10T00:00:00Z",
    **account_kwargs,
):
    """Ready chart + coder + ASSIGNED assignment.

    Returns dict(account, chart, coder, assignment).
    """
    account, chart = setup_ready_chart(
        mrn,
        acuity=acuity,
        total_charges_cents=total_charges_cents,
        discharge_at=discharge_at,
        **account_kwargs,
    )
    coder = make_coder(employee_no, credential=credential)
    assignment = make_assignment(chart["id"], coder_id=coder["id"], due_at=due_at)
    return {
        "account": account,
        "chart": chart,
        "coder": coder,
        "assignment": assignment,
    }


def setup_in_progress(mrn: str, employee_no: str, **kwargs):
    """setup_assigned + coder started the assignment (chart IN_CODING)."""
    ctx = setup_assigned(mrn, employee_no, **kwargs)
    ctx["assignment"] = start_assignment(ctx["assignment"]["id"], ctx["coder"]["id"])
    ctx["chart"] = get_success_data(api_client.get_chart(ctx["chart"]["id"], MANAGER))
    assert ctx["chart"]["status"] == "IN_CODING", "setup failed: chart not IN_CODING"
    return ctx


def add_diagnosis(chart_id: str, coder_id: str, icd_code: str = "I21.09",
                  poa: str = "Y", sequence: int = 1, **overrides) -> dict:
    payload = create_diagnosis_line_payload(
        chart_id, icd_code=icd_code, poa=poa, sequence=sequence, **overrides
    )
    res = api_client.create_diagnosis_line(payload, make_coder_headers(coder_id))
    return get_success_data(res)


def add_procedure(chart_id: str, coder_id: str, pcs_code: str = "0DJ08ZZ",
                  performed_at: str = "2026-04-22T09:00:00Z", **overrides) -> dict:
    payload = create_procedure_line_payload(
        chart_id, pcs_code=pcs_code, performed_at=performed_at, **overrides
    )
    res = api_client.create_procedure_line(payload, make_coder_headers(coder_id))
    return get_success_data(res)


def get_coded_case_for_chart(chart_id: str, headers=None) -> dict:
    """Discovery channel: the coded case created at submit is found via listing."""
    headers = headers or MANAGER
    res = api_client.list_coded_cases(headers, params={"chart_id": chart_id})
    data, _meta = validate_paginated(res)
    assert len(data) == 1, f"expected exactly one coded case for chart {chart_id}"
    return data[0]


def setup_submitted_case(
    mrn: str,
    employee_no: str,
    acuity: str = "MEDICAL_LOW",
    credential: str = "CCS",
    total_charges_cents: int = 900000,
    discharge_at: str = "2026-04-25T10:00:00Z",
    dx_lines=None,
    proc_lines=None,
    due_at: str = "2026-05-10T00:00:00Z",
    **account_kwargs,
):
    """Full chain through SUBMITTED: ready chart -> assign -> start -> lines -> submit.

    dx_lines: list of kwargs dicts for add_diagnosis (default: one principal
    I21.09 poa=Y seq=1). proc_lines: list of kwargs dicts for add_procedure.
    Returns dict(account, chart, coder, assignment, case, dx_line_ids).
    """
    if dx_lines is None:
        dx_lines = [{"icd_code": "I21.09", "poa": "Y", "sequence": 1, "is_principal": True}]
    ctx = setup_in_progress(
        mrn,
        employee_no,
        acuity=acuity,
        credential=credential,
        total_charges_cents=total_charges_cents,
        discharge_at=discharge_at,
        due_at=due_at,
        **account_kwargs,
    )
    coder_id = ctx["coder"]["id"]
    chart_id = ctx["chart"]["id"]
    dx_line_ids = []
    for spec in dx_lines:
        line = add_diagnosis(chart_id, coder_id, **spec)
        dx_line_ids.append(line["id"])
    for spec in (proc_lines or []):
        add_procedure(chart_id, coder_id, **spec)
    ctx["assignment"] = get_success_data(
        api_client.submit_assignment(ctx["assignment"]["id"], make_coder_headers(coder_id))
    )
    ctx["case"] = get_coded_case_for_chart(chart_id)
    ctx["dx_line_ids"] = dx_line_ids
    ctx["chart"] = get_success_data(api_client.get_chart(chart_id, MANAGER))
    assert ctx["chart"]["status"] == "SUBMITTED", "setup failed: chart not SUBMITTED"
    return ctx


def setup_accepted_case(mrn: str, employee_no: str, **kwargs):
    """setup_submitted_case + manager accept. Chart CODED, assignment ACCEPTED."""
    ctx = setup_submitted_case(mrn, employee_no, **kwargs)
    ctx["assignment"] = get_success_data(
        api_client.accept_assignment(ctx["assignment"]["id"], MANAGER)
    )
    ctx["chart"] = get_success_data(api_client.get_chart(ctx["chart"]["id"], MANAGER))
    assert ctx["chart"]["status"] == "CODED", "setup failed: chart not CODED"
    return ctx


# ─── Tier 4: billing chain ──────────────────────────────────────────────────

def make_bill(account_id: str) -> dict:
    res = api_client.create_bill(create_bill_payload(account_id), CLERK)
    return get_success_data(res)


def setup_ready_bill(mrn: str, employee_no: str, **kwargs):
    """Accepted case + bill born READY (chart already CODED at creation)."""
    ctx = setup_accepted_case(mrn, employee_no, **kwargs)
    ctx["bill"] = make_bill(ctx["account"]["id"])
    assert ctx["bill"]["status"] == "READY", (
        f"setup failed: bill is {ctx['bill']['status']}, expected READY"
    )
    return ctx


def setup_paid_bill(
    mrn: str,
    employee_no: str,
    paid_at: str = "2026-05-01T00:00:00Z",
    **kwargs,
):
    """Full lifecycle through PAID: ready bill -> finalize -> record payment in full."""
    ctx = setup_ready_bill(mrn, employee_no, **kwargs)
    expected = ctx["bill"]["expected_reimbursement_cents"]
    ctx["bill"] = get_success_data(api_client.finalize_bill(ctx["bill"]["id"], CLERK))
    ctx["bill"] = get_success_data(
        api_client.record_payment(
            ctx["bill"]["id"],
            record_payment_payload(paid_amount_cents=expected, paid_at=paid_at),
            CLERK,
        )
    )
    assert ctx["bill"]["status"] == "PAID", "setup failed: bill not PAID"
    return ctx


def setup_open_review(
    mrn: str,
    employee_no: str,
    claimed_delta_cents: int = -200000,
    payer_ref: str = "PR-FIXTURE",
    paid_at: str = "2026-05-01T00:00:00Z",
    **kwargs,
):
    """PAID bill + OPEN post-payment review. Adds review + bill_version keys."""
    ctx = setup_paid_bill(mrn, employee_no, paid_at=paid_at, **kwargs)
    ctx["review"] = get_success_data(
        api_client.create_post_payment_review(
            ctx["bill"]["id"],
            create_review_payload(
                payer_ref=payer_ref, claimed_delta_cents=claimed_delta_cents
            ),
            CLERK,
        )
    )
    bill = get_success_data(api_client.get_bill(ctx["bill"]["id"], CLERK))
    ctx["bill"] = bill
    ctx["bill_version"] = bill["version"]
    assert bill["status"] == "POST_PAYMENT_REVIEW", "setup failed: review not open"
    return ctx


def setup_pending_rebill(
    mrn: str,
    employee_no: str,
    claimed_delta_cents: int = -200000,
    requested_by: str = "clerk-fixture",
    **kwargs,
):
    """OPEN review + PENDING rebill request; bill REBILL_REQUIRED."""
    ctx = setup_open_review(mrn, employee_no, claimed_delta_cents=claimed_delta_cents, **kwargs)
    ctx["rebill"] = get_success_data(
        api_client.create_rebill_request(
            create_rebill_request_payload(
                ctx["review"]["id"], claimed_delta_cents, ctx["bill_version"]
            ),
            make_clerk_headers(requested_by),
        )
    )
    ctx["bill"] = get_success_data(api_client.get_bill(ctx["bill"]["id"], CLERK))
    assert ctx["bill"]["status"] == "REBILL_REQUIRED", "setup failed: bill not REBILL_REQUIRED"
    return ctx


# ─── Tier 5: audit chain ────────────────────────────────────────────────────

def make_audit(subject_coder_id: str, auditor_id: str,
               window_start: str = "2026-04-01T00:00:00Z",
               window_end: str = "2026-06-01T00:00:00Z",
               sample_size: int = 5) -> dict:
    res = api_client.create_audit(
        create_audit_payload(
            subject_coder_id,
            window_start=window_start,
            window_end=window_end,
            sample_size=sample_size,
        ),
        make_auditor_headers(auditor_id),
    )
    return get_success_data(res)


def add_finding(audit_id: str, auditor_id: str, coded_case_id: str,
                finding_type: str = "POA_CORRECTION", **overrides) -> dict:
    payload = create_finding_payload(
        coded_case_id, finding_type=finding_type, **overrides
    )
    res = api_client.create_finding(
        audit_id, payload, make_auditor_headers(auditor_id)
    )
    return get_success_data(res)


def resolve_finding(finding_id: str, auditor_id: str, resolution: str = "APPLY") -> dict:
    res = api_client.resolve_finding(
        finding_id, resolve_finding_payload(resolution=resolution),
        make_auditor_headers(auditor_id),
    )
    return get_success_data(res)


def setup_audit_on_accepted_case(
    mrn: str,
    subject_employee_no: str,
    auditor_employee_no: str,
    window_start: str = "2026-04-01T00:00:00Z",
    window_end: str = "2026-06-01T00:00:00Z",
    sample_size: int = 5,
    **case_kwargs,
):
    """Accepted case + a separate RHIA auditor + IN_REVIEW audit sampling the case.

    Findings are created by the caller via add_finding() because corrective
    findings reference specific diagnosis lines only known after setup.
    Returns dict(account, chart, coder, assignment, case, dx_line_ids,
    auditor, audit).
    """
    ctx = setup_accepted_case(mrn, subject_employee_no, **case_kwargs)
    auditor = make_coder(auditor_employee_no, credential="RHIA", full_name="Aud Itor")
    ctx["auditor"] = auditor
    ctx["audit"] = make_audit(
        ctx["coder"]["id"], auditor["id"],
        window_start=window_start, window_end=window_end, sample_size=sample_size,
    )
    return ctx
