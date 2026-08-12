"""Case cancellation cascade, OT consultations, and reassessment schedules."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    create_case, create_assessed_case, create_draft_quote, add_quote_line,
    setup_case_with_draft_quote, add_funding_source, approve_funding,
    add_allocation, submit_quote, create_ot_consultation,
    create_reassessment_schedule, set_clock, get_case,
)

IC = TEST_USERS["intake_coordinator_headers"]
AS = TEST_USERS["assessor_headers"]
PM = TEST_USERS["project_manager_headers"]
FC = TEST_USERS["funding_coordinator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: depth-2 cascade from case cancel (supersede -> release)
# ---------------------------------------------------------------------------

def _setup_submitted_with_pending_allocation(api):
    """Case QUOTE_SUBMITTED; SUBMITTED quote total 20000; APPROVED source 20000
    with one PENDING allocation 20000 on the quote; no jobs, no rentals."""
    set_clock()
    case, quote = setup_case_with_draft_quote(unit_price_cents=20000, contingency_pct=0.0)
    src = approve_funding(case["id"], add_funding_source(
        case["id"], 20000, source_type="STATE_GRANT",
        program_name="State Access Grant")["id"], 20000)
    submit_quote(case["id"], quote["id"])
    alloc = add_allocation(case["id"], src["id"], quote["id"], 20000)
    return case, quote, src, alloc


def test_case_cancel_supersedes_submitted_quote(api):
    """PRD §3.8: "Cancellation moves the case to `CANCELLED` and cascades: every
    non-terminal assessment becomes `CANCELLED`, every quote in `DRAFT` or
    `SUBMITTED` becomes `SUPERSEDED`, every `PENDING` funding source becomes
    `WITHDRAWN`, and every `SCHEDULED` OT consultation becomes `CANCELLED`."

    Design: Difficulty/transitive_cascade/case_cancel_cascades_quote_supersede_allocation_release
    """
    case, quote, src, alloc = _setup_submitted_with_pending_allocation(api)
    cancelled = validate_success(api.cancel_case(case["id"], PM), 200)
    assert cancelled["status"] == "CANCELLED"
    q = validate_success(api.get_quote(case["id"], quote["id"], IC), 200)
    assert q["status"] == "SUPERSEDED"


def test_quote_supersede_releases_pending_allocation(api):
    """PRD §3.3: "Creating a new revision has an immediate consequence for its
    predecessor — any existing quote of the same case still in `DRAFT`,
    `SUBMITTED`, or `UNDER_REVIEW` is moved to `SUPERSEDED`, its
    `superseded_by_id` is pointed at the new quote, and every still-`PENDING`
    funding allocation attached to the old quote is `RELEASED`."
    PRD §3.8: "every `PENDING` funding source becomes `WITHDRAWN`" — an APPROVED
    source is not PENDING, so it stays APPROVED, and its `remaining_cents` was
    never decremented because the allocation was still PENDING (PRD §3.3 commits
    allocations only on approval).

    Design: Difficulty/transitive_cascade/case_cancel_cascades_quote_supersede_allocation_release
    """
    case, quote, src, alloc = _setup_submitted_with_pending_allocation(api)
    validate_success(api.cancel_case(case["id"], PM), 200)
    allocs, _ = validate_paginated(api.list_funding_allocations(case["id"], src["id"], IC))
    statuses = {a["id"]: a["status"] for a in allocs}
    assert statuses[alloc["id"]] == "RELEASED", "release is caused by the supersede cascade"
    src_after = validate_success(api.get_funding_source(case["id"], src["id"], IC), 200)
    assert src_after["status"] == "APPROVED", "only PENDING sources are withdrawn"
    assert src_after["remaining_cents"] == 20000


# ---------------------------------------------------------------------------
# Corner: OT consultations and reassessment schedules
# ---------------------------------------------------------------------------

def test_ot_consultation_complete_from_completed_rejected(api):
    """PRD §3.2: "Three endings exist. An `Assessor` completes the consultation by
    submitting the therapist's `recommendations`; the consultation moves to
    `COMPLETED`, its `completed_date` is stamped, and the server records in
    `clearance_given` whether the therapist cleared the client for discharge."
    "`COMPLETED`, `CANCELLED`, and `NO_SHOW` are all terminal."
    PRD §2.6: "5. **Target resource state.** The resource being acted on must be
    in a state from which the requested transition exists; failure is one of
    `ERR_INVALID_STATE_TRANSITION`, `ERR_QUOTE_NOT_DRAFT`,
    `ERR_ASSESSMENT_NOT_SCHEDULED`, or `ERR_JOB_NOT_IN_PROGRESS` (HTTP 409)."

    Design: Corner/state_machines/ot_consultation_complete_from_completed_rejected
    """
    set_clock()
    case = create_case(client_name="Bea Elly", client_address="28 Consult Ln",
                       client_phone="555-0230")
    consult = create_ot_consultation(case["id"])
    validate_success(api.complete_ot_consultation(
        case["id"], consult["id"], {"recommendations": ["grab_bars"]}, AS), 200)
    res = api.complete_ot_consultation(
        case["id"], consult["id"], {"recommendations": ["grab_bars"]}, AS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    after = validate_success(api.get_ot_consultation(case["id"], consult["id"], IC), 200)
    assert after["status"] == "COMPLETED"


def test_reassessment_schedule_after_waived_rejected(api):
    """PRD §3.9: "A `ProjectManager` may waive a schedule in `PENDING`,
    `SCHEDULED`, or `OVERDUE`, moving it to `WAIVED`. `COMPLETED` and `WAIVED`
    are terminal."
    PRD §2.6: "5. **Target resource state.** The resource being acted on must be
    in a state from which the requested transition exists; failure is one of
    `ERR_INVALID_STATE_TRANSITION`, `ERR_QUOTE_NOT_DRAFT`,
    `ERR_ASSESSMENT_NOT_SCHEDULED`, or `ERR_JOB_NOT_IN_PROGRESS` (HTTP 409)."

    Design: Corner/state_machines/reassessment_schedule_after_waived_rejected
    """
    case = create_case(client_name="Cal Fink", client_address="29 Waive Way",
                       client_phone="555-0231")
    sched = create_reassessment_schedule(case["id"], due_date="2026-08-01T00:00:00Z")
    validate_success(api.waive_reassessment(case["id"], sched["id"], PM), 200)
    res = api.schedule_reassessment(case["id"], sched["id"], IC)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    after = validate_success(api.get_reassessment_schedule(case["id"], sched["id"], IC), 200)
    assert after["status"] == "WAIVED"


def test_reassessment_becomes_overdue_after_due_date(api):
    """PRD §2.9: "The time-driven transitions are: a quote in DRAFT, SUBMITTED, or
    UNDER_REVIEW whose `valid_until` has passed becomes EXPIRED; an invoice in
    SENT or PARTIALLY_PAID whose `due_date` has passed with a positive balance
    becomes OVERDUE; an OT consultation still SCHEDULED once its `scheduled_date`
    has passed becomes NO_SHOW; a reassessment schedule in PENDING or SCHEDULED
    whose `due_date` has passed becomes OVERDUE; and an installed rental ramp
    becomes IN_USE automatically while its rental period is active."

    Design: Corner/cross_cutting_complexity_layers/reassessment_becomes_overdue_after_due_date
    """
    set_clock()
    case = create_case(client_name="Sched Due", client_address="75 Due Rd",
                       client_phone="555-0805")
    sched = create_reassessment_schedule(case["id"], due_date="2026-06-01T00:00:00Z",
                                         priority="ROUTINE")
    assert sched["status"] == "PENDING"
    set_clock("2026-06-02T00:00:00Z")
    after = validate_success(api.get_reassessment_schedule(case["id"], sched["id"], IC), 200)
    assert after["status"] == "OVERDUE"


def test_consult_not_found_returns_404(api):
    """PRD §2.7: "The not-found errors are: `ERR_CASE_NOT_FOUND` for a case,
    `ERR_ASSESSMENT_NOT_FOUND` for an assessment, `ERR_QUOTE_NOT_FOUND` for a
    quote, `ERR_FUNDING_SOURCE_NOT_FOUND` for a funding source, `ERR_JOB_NOT_FOUND`
    for an installation job, `ERR_RAMP_NOT_FOUND` for a rental ramp,
    `ERR_UNIT_NOT_FOUND` for an inventory unit, `ERR_INSPECTION_NOT_FOUND` for an
    inspection, `ERR_INVOICE_NOT_FOUND` for an invoice, `ERR_CLAIM_NOT_FOUND` for
    a warranty claim, `ERR_CONSULT_NOT_FOUND` for an OT consultation, and
    `ERR_SCHEDULE_NOT_FOUND` for a reassessment schedule — each with HTTP 404."

    Design: Corner/errors/consult_not_found_returns_404
    """
    case = create_case(client_name="NF Consult", client_address="59 NF Rd",
                       client_phone="555-0609")
    res = api.get_ot_consultation(case["id"], NON_EXISTENT_UUID, IC)
    validate_error(res, ApiErrorId.ERR_CONSULT_NOT_FOUND, expected_status=404)


def test_schedule_not_found_returns_404(api):
    """PRD §2.7: "The not-found errors are: `ERR_CASE_NOT_FOUND` for a case,
    `ERR_ASSESSMENT_NOT_FOUND` for an assessment, `ERR_QUOTE_NOT_FOUND` for a
    quote, `ERR_FUNDING_SOURCE_NOT_FOUND` for a funding source, `ERR_JOB_NOT_FOUND`
    for an installation job, `ERR_RAMP_NOT_FOUND` for a rental ramp,
    `ERR_UNIT_NOT_FOUND` for an inventory unit, `ERR_INSPECTION_NOT_FOUND` for an
    inspection, `ERR_INVOICE_NOT_FOUND` for an invoice, `ERR_CLAIM_NOT_FOUND` for
    a warranty claim, `ERR_CONSULT_NOT_FOUND` for an OT consultation, and
    `ERR_SCHEDULE_NOT_FOUND` for a reassessment schedule — each with HTTP 404."

    Design: Corner/errors/schedule_not_found_returns_404
    """
    case = create_case(client_name="NF Sched", client_address="60 NF Rd",
                       client_phone="555-0610")
    res = api.get_reassessment_schedule(case["id"], NON_EXISTENT_UUID, IC)
    validate_error(res, ApiErrorId.ERR_SCHEDULE_NOT_FOUND, expected_status=404)
