"""Installation jobs, inspections, warranty claims, and the depth-3 pass cascade."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, assert_installation_job, assert_inspection,
    create_case, create_assessed_case, create_draft_quote, add_quote_line,
    setup_case_with_draft_quote, setup_under_review_quote,
    setup_installation_job, setup_job_in_progress, setup_completed_job,
    create_inspection_payload, create_warranty_claim,
    set_clock, get_case,
)

IC = TEST_USERS["intake_coordinator_headers"]
PM = TEST_USERS["project_manager_headers"]
FC = TEST_USERS["funding_coordinator_headers"]
CL = TEST_USERS["crew_lead_headers"]
INSP = TEST_USERS["inspector_headers"]
CLIENT = TEST_USERS["client_headers"]


# ---------------------------------------------------------------------------
# Difficulty: depth-3 cascade from FINAL inspection pass
# ---------------------------------------------------------------------------

def _setup_final_inspection_pending(api):
    """Case fully funded (20000 == quote total), job COMPLETED, FINAL inspection
    PENDING for 2026-05-02 against the completed job."""
    set_clock()
    case, quote, job, src, alloc = setup_completed_job(quote_total=20000)
    insp = validate_success(api.create_inspection(
        case["id"],
        create_inspection_payload(inspection_type="FINAL", inspector_id="insp-1",
                                  scheduled_date="2026-05-02T00:00:00Z",
                                  installation_job_id=job["id"]),
        INSP), 201)
    return case, quote, job, insp


def test_inspection_pass_updates_inspection_and_job(api):
    """PRD §3.5: "Passing requires that no safety-critical deficiencies stand; the
    inspection moves from `PENDING` to `PASSED`, its `completed_date` is stamped,
    and `ada_compliant` is set to true. When the passed inspection is of `FINAL`
    type, two cascades follow: the installation job's `inspection_status` becomes
    `PASSED`, and the case advances from `INSTALLED` to `INSPECTED` and then,
    automatically and without further action, to `WARRANT_ACTIVE` as the warranty
    period begins."

    Design: Difficulty/transitive_cascade/inspection_pass_cascades_job_case_warranty
    """
    case, quote, job, insp = _setup_final_inspection_pending(api)
    passed = validate_success(api.pass_inspection(case["id"], insp["id"], INSP), 200)
    assert passed["outcome"] == "PASSED"
    assert passed["ada_compliant"] is True
    job_after = validate_success(api.get_installation_job(case["id"], job["id"], IC), 200)
    assert job_after["inspection_status"] == "PASSED"


def test_inspection_pass_cascades_case_to_warranty_active(api):
    """PRD §3.5: "the case advances from `INSTALLED` to `INSPECTED` and then,
    automatically and without further action, to `WARRANT_ACTIVE` as the warranty
    period begins."
    PRD §3.9: "One is created automatically, with `auto_generated` set to true and
    `trigger_event` of `POST_INSTALL`, whenever an installation job completes: its
    `due_date` falls 30 days after the job's completion."

    Design: Difficulty/transitive_cascade/inspection_pass_cascades_job_case_warranty
    """
    case, quote, job, insp = _setup_final_inspection_pending(api)
    validate_success(api.pass_inspection(case["id"], insp["id"], INSP), 200)
    c = get_case(case["id"])
    assert c["status"] == "WARRANT_ACTIVE", (
        "INSPECTED -> WARRANTY_ACTIVE is automatic on inspection pass")
    schedules, _ = validate_paginated(api.list_reassessment_schedules(case["id"], IC))
    post_install = [s for s in schedules
                    if s["trigger_event"] == "POST_INSTALL" and s["auto_generated"] is True]
    assert post_install, "job completion must auto-create a POST_INSTALL reassessment schedule"


# ---------------------------------------------------------------------------
# Difficulty: FINAL inspection before job completion (interval precedence)
# ---------------------------------------------------------------------------

def test_final_inspection_before_job_completion_rejected(api):
    """PRD §3.5: "An `Inspector` or `ProjectManager` schedules one with an
    `inspection_type` of `PRE_INSTALL`, `ROUGH`, `FINAL`, `WARRANTY`, or
    `REASSESSMENT`, the `inspector_id`, a `scheduled_date`, and optionally the
    `installation_job_id` being inspected; a `FINAL` inspection whose
    `scheduled_date` does not fall after the job's `actual_end` is rejected with
    `ERR_INSPECTION_BEFORE_COMPLETION`."

    Design: Difficulty/resource_temporal_overlap/final_inspection_before_job_completion_rejected
    """
    set_clock()
    case, quote, job, src, alloc = setup_job_in_progress(quote_total=20000)
    assert job["actual_end"] is None
    res = api.create_inspection(
        case["id"],
        create_inspection_payload(inspection_type="FINAL", inspector_id="insp-9",
                                  scheduled_date="2026-05-02T00:00:00Z",
                                  installation_job_id=job["id"]),
        INSP)
    validate_error(res, ApiErrorId.ERR_INSPECTION_BEFORE_COMPLETION, expected_status=422)


def test_final_inspection_rejection_leaves_job_untouched(api):
    """PRD §3.5: "a `FINAL` inspection whose `scheduled_date` does not fall after
    the job's `actual_end` is rejected with `ERR_INSPECTION_BEFORE_COMPLETION`."
    A rejected create persists nothing, so the job's `inspection_status` stays
    `NOT_SCHEDULED`.

    Design: Difficulty/resource_temporal_overlap/final_inspection_before_job_completion_rejected
    """
    set_clock()
    case, quote, job, src, alloc = setup_job_in_progress(quote_total=20000)
    validate_error(api.create_inspection(
        case["id"],
        create_inspection_payload(inspection_type="FINAL", inspector_id="insp-9",
                                  scheduled_date="2026-05-02T00:00:00Z",
                                  installation_job_id=job["id"]),
        INSP), ApiErrorId.ERR_INSPECTION_BEFORE_COMPLETION, expected_status=422)
    job_after = validate_success(api.get_installation_job(case["id"], job["id"], IC), 200)
    assert job_after["inspection_status"] == "NOT_SCHEDULED"
    inspections, _ = validate_paginated(api.list_inspections(case["id"], IC))
    assert inspections == [], "no inspection may be persisted for a rejected request"


# ---------------------------------------------------------------------------
# Corner: job defaults, transitions, completion side effects, close guard
# ---------------------------------------------------------------------------

def test_job_warranty_months_defaults_to_12(api):
    """PRD §3.5: "The create request names the governing `quote_id`, the
    `scheduled_start` and `scheduled_end` dates, the `crew_lead_id` of the lead
    installer, and optionally the `permit_number` and a `warranty_months` duration
    that defaults to 12 months when omitted."

    Design: Corner/entities/job_warranty_months_defaults_to_12
    """
    set_clock()
    case, quote, job, src, alloc = setup_installation_job(
        quote_total=10000, scheduled_start="2026-05-02T00:00:00Z",
        scheduled_end="2026-05-09T00:00:00Z", crew_lead_id="crew-d")
    assert job["warranty_months"] == 12, "default must be applied when omitted"
    assert job["status"] == "SCHEDULED"


def test_job_start_from_scheduled_rejected(api):
    """PRD §3.5: "The `ProjectManager` marks materials ordered, moving the job
    from `SCHEDULED` to `MATERIALS_ORDERED`. On or after the `scheduled_start`
    date the `CrewLead` starts work: the job moves from `MATERIALS_ORDERED` to
    `IN_PROGRESS` and `actual_start` is stamped."
    PRD §2.6: "5. **Target resource state.** The resource being acted on must be
    in a state from which the requested transition exists; failure is one of
    `ERR_INVALID_STATE_TRANSITION`, `ERR_QUOTE_NOT_DRAFT`,
    `ERR_ASSESSMENT_NOT_SCHEDULED`, or `ERR_JOB_NOT_IN_PROGRESS` (HTTP 409)."

    Design: Corner/state_machines/job_start_from_scheduled_rejected
    """
    set_clock()
    case, quote, job, src, alloc = setup_installation_job(quote_total=10000)
    res = api.start_installation(case["id"], job["id"], CL)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    job_after = validate_success(api.get_installation_job(case["id"], job["id"], IC), 200)
    assert job_after["status"] == "SCHEDULED"
    assert job_after["actual_start"] is None


def test_job_cancel_after_actual_start_rejected(api):
    """PRD §3.5: "A job that has not yet started — `actual_start` still null — may
    be cancelled by the `ProjectManager` from `SCHEDULED` or `MATERIALS_ORDERED`".
    PRD §2.6: "5. **Target resource state.** The resource being acted on must be
    in a state from which the requested transition exists; failure is one of
    `ERR_INVALID_STATE_TRANSITION`, `ERR_QUOTE_NOT_DRAFT`,
    `ERR_ASSESSMENT_NOT_SCHEDULED`, or `ERR_JOB_NOT_IN_PROGRESS` (HTTP 409)."

    Design: Corner/state_machines/job_cancel_after_actual_start_rejected
    """
    set_clock()
    case, quote, job, src, alloc = setup_job_in_progress(quote_total=10000)
    assert job["actual_start"] is not None
    res = api.cancel_installation_job(case["id"], job["id"], PM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    job_after = validate_success(api.get_installation_job(case["id"], job["id"], IC), 200)
    assert job_after["status"] == "IN_PROGRESS"


def test_job_complete_side_effects_warranty_and_reassessment(api):
    """PRD §3.5: "A successful completion stamps `actual_end`, sets the job's
    `warranty_start_date` equal to `actual_end`, moves the job to `COMPLETED`,
    moves the case from `INSTALLATION_SCHEDULED` to `INSTALLED`, and automatically
    creates a post-install reassessment schedule due 30 days after completion (see
    §3.9)."
    PRD §3.9: "One is created automatically, with `auto_generated` set to true and
    `trigger_event` of `POST_INSTALL`, whenever an installation job completes".

    Design: Corner/state_machines/job_complete_side_effects_warranty_and_reassessment
    """
    set_clock()
    case, quote, job, src, alloc = setup_job_in_progress(quote_total=10000, punch_list=True)
    completed = validate_success(api.complete_installation(case["id"], job["id"], CL), 200)
    assert completed["status"] == "COMPLETED"
    assert completed["actual_end"] is not None
    assert completed["warranty_start_date"] == completed["actual_end"]
    assert get_case(case["id"])["status"] == "INSTALLED"
    schedules, _ = validate_paginated(api.list_reassessment_schedules(case["id"], IC))
    post_install = [s for s in schedules
                    if s["trigger_event"] == "POST_INSTALL" and s["auto_generated"] is True]
    assert post_install, "an auto-generated POST_INSTALL schedule must exist"


def test_inspection_double_pass_rejected(api):
    """PRD §3.5: "`PASSED` and `FAILED` are terminal outcomes."
    PRD §2.6: "5. **Target resource state.** The resource being acted on must be
    in a state from which the requested transition exists; failure is one of
    `ERR_INVALID_STATE_TRANSITION`, `ERR_QUOTE_NOT_DRAFT`,
    `ERR_ASSESSMENT_NOT_SCHEDULED`, or `ERR_JOB_NOT_IN_PROGRESS` (HTTP 409)."

    Design: Corner/state_machines/inspection_double_pass_rejected
    """
    set_clock()
    case = create_case(client_name="Wes York", client_address="23 Inspect Ave",
                       client_phone="555-0225")
    insp = validate_success(api.create_inspection(
        case["id"], create_inspection_payload(inspection_type="PRE_INSTALL",
                                              inspector_id="insp-2"), INSP), 201)
    validate_success(api.pass_inspection(case["id"], insp["id"], INSP), 200)
    res = api.pass_inspection(case["id"], insp["id"], INSP)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    after = validate_success(api.get_inspection(case["id"], insp["id"], IC), 200)
    assert after["outcome"] == "PASSED"


def test_case_close_from_intake_rejected(api):
    """PRD §3.8: "Closing the whole case is a `ProjectManager` action available
    once the case is `WARRANT_ACTIVE`". From INTAKE the close transition does not
    exist.
    PRD §2.6: "5. **Target resource state.** The resource being acted on must be
    in a state from which the requested transition exists; failure is one of
    `ERR_INVALID_STATE_TRANSITION`, `ERR_QUOTE_NOT_DRAFT`,
    `ERR_ASSESSMENT_NOT_SCHEDULED`, or `ERR_JOB_NOT_IN_PROGRESS` (HTTP 409)."

    Design: Corner/state_machines/case_close_from_intake_rejected
    """
    case = create_case(client_name="Dot Goss", client_address="30 Close St",
                       client_phone="555-0232")
    res = api.close_case(case["id"], PM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    assert get_case(case["id"])["status"] == "INTAKE"


def test_warranty_claim_deny_from_in_progress_rejected(api):
    """PRD §3.8: "A `ProjectManager` may instead deny a claim in `OPEN` or
    `ASSIGNED`, moving it to `DENIED`, or close a claim in `OPEN`, `ASSIGNED`, or
    `IN_PROGRESS`, moving it to `CLOSED`."
    PRD §2.6: "5. **Target resource state.** The resource being acted on must be
    in a state from which the requested transition exists; failure is one of
    `ERR_INVALID_STATE_TRANSITION`, `ERR_QUOTE_NOT_DRAFT`,
    `ERR_ASSESSMENT_NOT_SCHEDULED`, or `ERR_JOB_NOT_IN_PROGRESS` (HTTP 409)."

    Design: Corner/state_machines/warranty_claim_deny_from_in_progress_rejected
    """
    set_clock()
    case, quote, job, src, alloc = setup_installation_job(quote_total=10000)
    claim = create_warranty_claim(case["id"], job["id"],
                                  issue_description="Loose rail", severity="MEDIUM")
    validate_success(api.assign_warranty_claim(case["id"], claim["id"], PM), 200)
    validate_success(api.start_warranty_work(case["id"], claim["id"], CL), 200)
    res = api.deny_warranty_claim(case["id"], claim["id"], PM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    after = validate_success(api.get_warranty_claim(case["id"], claim["id"], IC), 200)
    assert after["status"] == "IN_PROGRESS"


def test_job_create_without_funding_returns_409(api):
    """PRD §3.5: "With funding secured — the case in `FUNDING_APPROVED`, or an
    approved self-pay source covering the work — a `ProjectManager` schedules the
    build. Scheduling against a case without approved funding fails with
    `ERR_CASE_NOT_FUNDED`".

    Design: Corner/errors/job_create_without_funding_returns_409
    """
    set_clock()
    case, quote = setup_case_with_draft_quote(unit_price_cents=10000,
                                              contingency_pct=None, n_lines=0)
    res = api.create_installation_job(
        case["id"],
        {"quote_id": quote["id"], "scheduled_start": "2026-05-02T00:00:00Z",
         "scheduled_end": "2026-05-09T00:00:00Z", "crew_lead_id": "crew-7"},
        PM)
    validate_error(res, ApiErrorId.ERR_CASE_NOT_FUNDED, expected_status=409)


def test_punch_list_from_scheduled_returns_409(api):
    """PRD §3.5: "When the remaining work reduces to corrective items the
    `CrewLead` enters the punch-list phase, moving the job from `IN_PROGRESS` to
    `PUNCH_LIST` — requesting that transition while the job is not `IN_PROGRESS`
    fails with `ERR_JOB_NOT_IN_PROGRESS`."

    Design: Corner/errors/punch_list_from_scheduled_returns_409
    """
    set_clock()
    case, quote, job, src, alloc = setup_installation_job(quote_total=10000)
    res = api.enter_punch_list(case["id"], job["id"], CL)
    validate_error(res, ApiErrorId.ERR_JOB_NOT_IN_PROGRESS, expected_status=409)
    job_after = validate_success(api.get_installation_job(case["id"], job["id"], IC), 200)
    assert job_after["status"] == "SCHEDULED"


def test_quote_approve_with_insufficient_funding_returns_402(api):
    """PRD §3.3: "Approving the quote requires that sufficient funding has been
    allocated — or that self-pay has been approved — to cover the total; an
    approval attempt without sufficient funding behind it is rejected with
    `ERR_INSUFFICIENT_FUNDING` (HTTP 402)."

    Design: Corner/errors/quote_approve_with_insufficient_funding_returns_402
    """
    set_clock()
    # Quote total 20000, but only 5000 approved and allocated.
    case, quote, src, alloc = setup_under_review_quote(quote_total=20000,
                                                       approved_cents=5000)
    res = api.approve_quote(case["id"], quote["id"], FC)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_FUNDING, expected_status=402)
    q = validate_success(api.get_quote(case["id"], quote["id"], IC), 200)
    assert q["status"] == "UNDER_REVIEW"


def test_job_not_found_returns_404(api):
    """PRD §2.7: "The not-found errors are: `ERR_CASE_NOT_FOUND` for a case,
    `ERR_ASSESSMENT_NOT_FOUND` for an assessment, `ERR_QUOTE_NOT_FOUND` for a
    quote, `ERR_FUNDING_SOURCE_NOT_FOUND` for a funding source, `ERR_JOB_NOT_FOUND`
    for an installation job, `ERR_RAMP_NOT_FOUND` for a rental ramp,
    `ERR_UNIT_NOT_FOUND` for an inventory unit, `ERR_INSPECTION_NOT_FOUND` for an
    inspection, `ERR_INVOICE_NOT_FOUND` for an invoice, `ERR_CLAIM_NOT_FOUND` for
    a warranty claim, `ERR_CONSULT_NOT_FOUND` for an OT consultation, and
    `ERR_SCHEDULE_NOT_FOUND` for a reassessment schedule — each with HTTP 404."

    Design: Corner/errors/job_not_found_returns_404
    """
    case = create_case(client_name="NF Job", client_address="54 NF Rd",
                       client_phone="555-0604")
    res = api.get_installation_job(case["id"], NON_EXISTENT_UUID, IC)
    validate_error(res, ApiErrorId.ERR_JOB_NOT_FOUND, expected_status=404)


def test_inspection_not_found_returns_404(api):
    """PRD §2.7: "The not-found errors are: `ERR_CASE_NOT_FOUND` for a case,
    `ERR_ASSESSMENT_NOT_FOUND` for an assessment, `ERR_QUOTE_NOT_FOUND` for a
    quote, `ERR_FUNDING_SOURCE_NOT_FOUND` for a funding source, `ERR_JOB_NOT_FOUND`
    for an installation job, `ERR_RAMP_NOT_FOUND` for a rental ramp,
    `ERR_UNIT_NOT_FOUND` for an inventory unit, `ERR_INSPECTION_NOT_FOUND` for an
    inspection, `ERR_INVOICE_NOT_FOUND` for an invoice, `ERR_CLAIM_NOT_FOUND` for
    a warranty claim, `ERR_CONSULT_NOT_FOUND` for an OT consultation, and
    `ERR_SCHEDULE_NOT_FOUND` for a reassessment schedule — each with HTTP 404."

    Design: Corner/errors/inspection_not_found_returns_404
    """
    case = create_case(client_name="NF Insp", client_address="56 NF Rd",
                       client_phone="555-0606")
    res = api.get_inspection(case["id"], NON_EXISTENT_UUID, IC)
    validate_error(res, ApiErrorId.ERR_INSPECTION_NOT_FOUND, expected_status=404)


def test_claim_not_found_returns_404(api):
    """PRD §2.7: "The not-found errors are: `ERR_CASE_NOT_FOUND` for a case,
    `ERR_ASSESSMENT_NOT_FOUND` for an assessment, `ERR_QUOTE_NOT_FOUND` for a
    quote, `ERR_FUNDING_SOURCE_NOT_FOUND` for a funding source, `ERR_JOB_NOT_FOUND`
    for an installation job, `ERR_RAMP_NOT_FOUND` for a rental ramp,
    `ERR_UNIT_NOT_FOUND` for an inventory unit, `ERR_INSPECTION_NOT_FOUND` for an
    inspection, `ERR_INVOICE_NOT_FOUND` for an invoice, `ERR_CLAIM_NOT_FOUND` for
    a warranty claim, `ERR_CONSULT_NOT_FOUND` for an OT consultation, and
    `ERR_SCHEDULE_NOT_FOUND` for a reassessment schedule — each with HTTP 404."

    Design: Corner/errors/claim_not_found_returns_404
    """
    case = create_case(client_name="NF Claim", client_address="58 NF Rd",
                       client_phone="555-0608")
    res = api.get_warranty_claim(case["id"], NON_EXISTENT_UUID, IC)
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_FOUND, expected_status=404)
