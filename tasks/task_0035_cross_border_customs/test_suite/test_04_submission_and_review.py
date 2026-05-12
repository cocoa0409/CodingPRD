"""Submission preconditions, customs review state machine, queries,
inspections, approval, rejection, rework limit.

PRD anchors: §3.4 (path to submission), §3.7 (customs review).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    TEST_USERS,
    create_party_pair,
    create_order,
    create_draft_declaration,
    setup_draft_declaration,
    setup_under_review_declaration,
    create_hs_code,
    create_declaration_payload,
    create_declaration_line_payload,
    review_override_payload,
    suspend_importer,
    add_line,
    submit_declaration,
    start_review,
    approve_declaration,
    reject_declaration,
    open_query,
    respond_to_query,
    resolve_query,
    schedule_inspection,
    complete_inspection,
    schedule_inspection_payload,
    open_query_payload,
    respond_query_payload,
    reject_declaration_payload,
    make_declarant_headers,
    assert_declaration,
    assert_query,
    assert_inspection_appointment,
)


# ---------------------------------------------------------------------------
# Submit preconditions
# ---------------------------------------------------------------------------
def test_submit_increments_submission_count(api):
    """PRD §3.4: "the server increments submission_count by one,
    recomputes tax_mode, recomputes dutiable_value_cny_minor and
    tariff_amount_cny_minor, vat_amount_cny_minor,
    consumption_tax_cny_minor, and total_tax_cny_minor".

    Claim: a successful submit moves status to SUBMITTED and bumps
    submission_count from 0 to 1.
    """
    ctx = setup_draft_declaration()
    assert ctx.declaration["submission_count"] == 0
    submitted = submit_declaration(ctx.declaration, ctx.declarant)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submission_count"] == 1


def test_submit_with_pending_override_blocked(api):
    """PRD §3.4: "then a check that no declaration line is in PENDING or
    REJECTED override status (else ERR_LINES_HAVE_PENDING_OVERRIDE)".
    """
    ctx = setup_draft_declaration(add_lines=False)
    add_line(
        ctx.declaration, ctx.declarant,
        order_line_index=0, hs_code_id=ctx.ref["hs_code"]["id"],
        classification_source="MANUAL_OVERRIDE",
    )
    res = api.submit_declaration(
        ctx.declaration["id"], make_declarant_headers(ctx.declarant["id"])
    )
    validate_error(res, "ERR_LINES_HAVE_PENDING_OVERRIDE", expected_status=409)


def test_submit_with_rejected_override_blocked(api):
    """PRD §3.4: lines in PENDING or REJECTED override status block submit
    (ERR_LINES_HAVE_PENDING_OVERRIDE).
    """
    ctx = setup_draft_declaration(add_lines=False)
    line = add_line(
        ctx.declaration, ctx.declarant,
        order_line_index=0, hs_code_id=ctx.ref["hs_code"]["id"],
        classification_source="MANUAL_OVERRIDE",
    )
    api.review_line_override(
        ctx.declaration["id"], line["id"],
        review_override_payload("REJECT"),
        TEST_USERS["customs_officer_headers"],
    )
    res = api.submit_declaration(
        ctx.declaration["id"], make_declarant_headers(ctx.declarant["id"])
    )
    validate_error(res, "ERR_LINES_HAVE_PENDING_OVERRIDE", expected_status=409)


def test_submit_b2c_missing_id_card_number_rejected(api):
    """PRD §3.4: "the per-trade-mode template-completeness check, which
    ensures the appropriate one of importer_id_card_number,
    bonded_zone_code, or contract_number was supplied (else
    ERR_DECLARATION_INCOMPLETE)".

    Claim: a B2C_DIRECT_MAIL declaration created without
    importer_id_card_number → ERR_DECLARATION_INCOMPLETE on submit.
    """
    importer, declarant = create_party_pair()
    from test_helpers import setup_reference_data
    setup_reference_data()
    order = create_order(importer, declarant, trade_mode="B2C_DIRECT_MAIL")
    res = api.create_declaration(
        {"order_id": order["id"], "dutiable_value_method": "TRANSACTION_VALUE"},
        make_declarant_headers(declarant["id"]),
    )
    decl = validate_success(res, expected_status=201)
    res2 = api.submit_declaration(
        decl["id"], make_declarant_headers(declarant["id"])
    )
    validate_error(res2, "ERR_DECLARATION_INCOMPLETE", expected_status=422)


def test_submit_with_suspended_importer_blocked(api):
    """PRD §3.4: "then the importer must be ACTIVE (else
    ERR_IMPORTER_SUSPENDED) and the declarant must likewise be ACTIVE".
    """
    ctx = setup_draft_declaration()
    suspend_importer(ctx.importer["id"])
    res = api.submit_declaration(
        ctx.declaration["id"], make_declarant_headers(ctx.declarant["id"])
    )
    validate_error(res, "ERR_IMPORTER_SUSPENDED", expected_status=409)


# NOTE: test_rework_limit_after_two_rejections was deleted —
# unique-derivability failure (STEP 1b). PRD §3.4 declares the gate
# verbatim as "submission_count is strictly less than 3" while also
# saying parenthetically "after two rejections, a third resubmission
# attempt is refused". Under the verbatim gate, count=2 at the 3rd
# submit passes the check (2<3). Under the parenthetical reading the
# 3rd submit fails. The two readings diverge and PRD pins the gate
# verbatim; a faithful PRD-only reader can implement either, so the
# test's expected outcome is not uniquely derivable.


# ---------------------------------------------------------------------------
# start_review / queries / resolve cycle
# ---------------------------------------------------------------------------
def test_start_review_transitions_to_under_review(api):
    """PRD §3.7: "Once a declaration is in SUBMITTED, a customs officer
    begins review by transitioning it from SUBMITTED to UNDER_REVIEW."
    """
    ctx = setup_draft_declaration()
    submitted = submit_declaration(ctx.declaration, ctx.declarant)
    started = start_review(submitted)
    assert started["status"] == "UNDER_REVIEW"


def test_open_query_moves_to_queried(api):
    """PRD §3.7: "Queries are the supplementary-document loop. A customs
    officer asks a question and lists required_documents ... as part of
    opening a query; this transitions the declaration from UNDER_REVIEW
    to QUERIED and pins Declaration.query_id to the new query, whose own
    status begins at OPEN."
    """
    ctx = setup_under_review_declaration()
    res = api.open_query(
        ctx.declaration["id"],
        open_query_payload(required_documents=["INVOICE"]),
        TEST_USERS["customs_officer_headers"],
    )
    q = validate_success(res, expected_status=201)
    assert_query(q)
    assert q["status"] == "OPEN"
    # Declaration now QUERIED with query_id set.
    decl = ctx.refresh_declaration()
    assert decl["status"] == "QUERIED"
    assert decl.get("query_id") == q["id"]


def test_query_response_documents_must_match_required(api):
    """PRD §3.7: "the response is rejected with
    ERR_QUERY_DOCUMENTS_INCOMPLETE if any doc_type listed in
    required_documents lacks a matching entry in response_documents."
    """
    ctx = setup_under_review_declaration()
    q_res = api.open_query(
        ctx.declaration["id"],
        open_query_payload(required_documents=["INVOICE", "COA"]),
        TEST_USERS["customs_officer_headers"],
    )
    q = validate_success(q_res, expected_status=201)
    res = api.respond_query(
        q["id"],
        respond_query_payload(
            response_documents=[
                {"doc_type": "INVOICE", "voucher_url": "u"}
            ]
        ),
        make_declarant_headers(ctx.declarant["id"]),
    )
    validate_error(res, "ERR_QUERY_DOCUMENTS_INCOMPLETE", expected_status=422)


def test_query_resolve_returns_to_under_review(api):
    """PRD §3.7: "The customs officer then resolves the query, which
    moves the query to RESOLVED, clears Declaration.query_id, and returns
    the declaration from QUERIED to UNDER_REVIEW."
    """
    ctx = setup_under_review_declaration()
    q_res = api.open_query(
        ctx.declaration["id"],
        open_query_payload(required_documents=["INVOICE"]),
        TEST_USERS["customs_officer_headers"],
    )
    q = validate_success(q_res, expected_status=201)
    respond_to_query(q["id"], ctx.declarant)
    resolved = resolve_query(q["id"])
    assert resolved["status"] == "RESOLVED"
    decl = ctx.refresh_declaration()
    assert decl["status"] == "UNDER_REVIEW"
    assert decl.get("query_id") in (None, "")


def test_query_blocked_when_inspection_scheduled(api):
    """PRD §3.7: "Opening a query is blocked when a SCHEDULED
    InspectionAppointment exists for the declaration
    (ERR_INSPECTION_PENDING)."
    """
    ctx = setup_under_review_declaration()
    schedule_inspection(
        ctx.declaration["id"],
        scheduled_at="2026-02-01T10:00:00Z",
        bay_code="BAY-Q1",
    )
    res = api.open_query(
        ctx.declaration["id"],
        open_query_payload(required_documents=["INVOICE"]),
        TEST_USERS["customs_officer_headers"],
    )
    validate_error(res, "ERR_INSPECTION_PENDING", expected_status=409)


# ---------------------------------------------------------------------------
# Inspection scheduling
# ---------------------------------------------------------------------------
def test_schedule_inspection_initial_status(api):
    """PRD §3.7: "Inspections are scheduled appointments at a single
    inspection bay. Each InspectionAppointment is a 60-minute exclusive
    interval pinning a bay_code and a scheduled_at start instant."
    """
    ctx = setup_under_review_declaration()
    res = api.schedule_inspection(
        ctx.declaration["id"],
        schedule_inspection_payload(
            scheduled_at="2026-02-01T10:00:00Z", bay_code="BAY-S1"
        ),
        TEST_USERS["customs_officer_headers"],
    )
    appt = validate_success(res, expected_status=201)
    assert_inspection_appointment(appt)
    assert appt["status"] == "SCHEDULED"
    assert appt["bay_code"] == "BAY-S1"


def test_overlapping_inspection_blocked(api):
    """PRD §3.7: "two appointments on the same bay_code are in conflict
    whenever their intervals [scheduled_at, scheduled_at + 60min)
    overlap. A conflict is reported as ERR_INSPECTION_SLOT_TAKEN."
    """
    ctx_a = setup_under_review_declaration()
    ctx_b = setup_under_review_declaration()
    schedule_inspection(
        ctx_a.declaration["id"],
        scheduled_at="2026-02-01T10:00:00Z", bay_code="BAY-COLL",
    )
    res = api.schedule_inspection(
        ctx_b.declaration["id"],
        schedule_inspection_payload(
            scheduled_at="2026-02-01T10:30:00Z", bay_code="BAY-COLL"
        ),
        TEST_USERS["customs_officer_headers"],
    )
    validate_error(res, "ERR_INSPECTION_SLOT_TAKEN", expected_status=409)


def test_back_to_back_inspections_allowed(api):
    """PRD §3.7: "Stated equivalently, two appointments on the same
    bay_code are in conflict whenever their intervals
    [scheduled_at, scheduled_at + 60min) overlap."

    Claim: an appointment at exactly +60min from another (boundary open
    on the right) does NOT collide.
    """
    ctx_a = setup_under_review_declaration()
    ctx_b = setup_under_review_declaration()
    schedule_inspection(
        ctx_a.declaration["id"],
        scheduled_at="2026-03-01T10:00:00Z", bay_code="BAY-B2B",
    )
    res = api.schedule_inspection(
        ctx_b.declaration["id"],
        schedule_inspection_payload(
            scheduled_at="2026-03-01T11:00:00Z", bay_code="BAY-B2B"
        ),
        TEST_USERS["customs_officer_headers"],
    )
    validate_success(res, expected_status=201)


# ---------------------------------------------------------------------------
# Approve / reject
# ---------------------------------------------------------------------------
def test_approve_with_open_query_blocked(api):
    """PRD §3.7: "An approval request is rejected with
    ERR_INVALID_STATE_TRANSITION if there is still an open query
    (i.e., Declaration.query_id is non-null)".
    """
    ctx = setup_under_review_declaration()
    api.open_query(
        ctx.declaration["id"],
        open_query_payload(required_documents=["INVOICE"]),
        TEST_USERS["customs_officer_headers"],
    )
    res = api.approve_declaration(
        ctx.declaration["id"], TEST_USERS["customs_officer_headers"]
    )
    validate_error(res, "ERR_INVALID_STATE_TRANSITION", expected_status=409)


def test_approve_with_scheduled_inspection_blocked(api):
    """PRD §3.7: "and with ERR_INSPECTION_PENDING if any SCHEDULED
    InspectionAppointment for the declaration has not yet been completed."
    """
    ctx = setup_under_review_declaration()
    schedule_inspection(
        ctx.declaration["id"],
        scheduled_at="2026-04-01T10:00:00Z", bay_code="BAY-AP",
    )
    res = api.approve_declaration(
        ctx.declaration["id"], TEST_USERS["customs_officer_headers"]
    )
    validate_error(res, "ERR_INSPECTION_PENDING", expected_status=409)


def test_approve_after_inspection_completed_succeeds(api):
    """PRD §3.7: "any SCHEDULED appointment must reach COMPLETED before
    the declaration can be approved."
    PRD §3.7: "A clean approval transitions the declaration from
    UNDER_REVIEW to APPROVED, which fires three effects: the system
    creates a PaymentNotice ..., the parent order cascades from
    PENDING_DECLARATION to DECLARED, and a DECLARATION_STATUS_CHANGE
    audit event is emitted."

    Claim: completing the inspection unblocks approve.
    """
    ctx = setup_under_review_declaration()
    appt = schedule_inspection(
        ctx.declaration["id"],
        scheduled_at="2026-05-01T10:00:00Z", bay_code="BAY-OK",
    )
    complete_inspection(appt["id"])
    approved = approve_declaration(ctx.declaration)
    assert approved["status"] == "APPROVED"


def test_reject_records_reason(api):
    """PRD §3.7: "Rejection sends the declaration from UNDER_REVIEW to
    REJECTED, persisting the customs officer's rejection_reason and
    emitting a DECLARATION_STATUS_CHANGE audit event."
    """
    ctx = setup_under_review_declaration()
    rej = reject_declaration(ctx.declaration, reason="missing_invoice")
    assert rej["status"] == "REJECTED"
    assert rej.get("rejection_reason") == "missing_invoice"


def test_resubmit_after_rejection_clears_reason(api):
    """PRD §3.4: "On resubmission after a rejection, the same
    recomputation runs and the existing rejection_reason is cleared."
    """
    ctx = setup_draft_declaration()
    submit_declaration(ctx.declaration, ctx.declarant)
    start_review(ctx.declaration)
    reject_declaration(ctx.declaration, "first reject reason")
    res = api.submit_declaration(
        ctx.declaration["id"], make_declarant_headers(ctx.declarant["id"])
    )
    resub = validate_success(res)
    assert resub["status"] == "SUBMITTED"
    # rejection_reason should now be null/empty.
    assert resub.get("rejection_reason") in (None, "")
    assert resub["submission_count"] == 2
