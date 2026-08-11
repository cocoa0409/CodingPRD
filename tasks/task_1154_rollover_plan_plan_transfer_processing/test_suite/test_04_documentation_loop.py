"""The documentation loop: review cycles, resubmission, rejection cascades,
and approval gating on document completeness."""
from test_helpers import (
    ApiErrorId,
    api_client,
    get_case,
    list_case_documents,
    make_account,
    make_participant,
    make_participant_headers,
    make_plan,
    make_processor_headers,
    settle_case_documents,
    submit_case,
    validate_error,
    validate_success,
)

PROC1 = make_processor_headers("proc-1")


def _submitted_indirect_case():
    """Plan + SEPARATED SINGLE participant + account + submitted INDIRECT case
    (DOCS_PENDING with SEPARATION_VERIFICATION + IDENTITY_PROOF REQUIRED)."""
    plan = make_plan(clock="2026-05-01T00:00:00Z")
    participant = make_participant()
    account = make_account(participant["id"], plan["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 500000, "basis_cents": 0, "vested_pct": 100},
    ])
    resp = api_client.create_rollover_case(
        {
            "case_type": "INDIRECT_ROLLOVER_OUT",
            "source_account_id": account["id"],
            "receiving_institution_name": "External IRA Trust",
            "withholding_acknowledged": True,
        },
        make_participant_headers(participant["id"]),
    )
    case = validate_success(resp, expected_status=201)
    submit_case(case["id"], participant["id"])
    return plan, participant, account, case


def test_case_review_docs_cycle_revisits_review_state(api):
    """PRD §3.4: "**REQUEST_DOCS** reopens the documentation loop: the case
    returns to `DOCS_PENDING` and new `RequiredDocument` rows are inserted in
    `REQUIRED` status for exactly the document types named in the decision's
    `request_doc_types` input, deduplicated by type. Review may demand more
    documents repeatedly."
    PRD §3.4: "Acceptance records the reviewer's `X-User-ID` as `reviewed_by`
    and bubbles up: if no sibling document on the case remains `REQUIRED`, the
    case advances `DOCS_PENDING → ELIGIBILITY_REVIEW`."

    Design: Difficulty/non_linear_state_machine/case_review_docs_cycle
    """
    _plan, participant, _account, case = _submitted_indirect_case()
    p_headers = make_participant_headers(participant["id"])

    docs = list_case_documents(case["id"])
    assert [d["doc_type"] for d in docs] == ["SEPARATION_VERIFICATION", "IDENTITY_PROOF"]
    for d in docs:
        validate_success(api_client.submit_document(d["id"], p_headers))
    # Accepting the first outstanding document bubbles the case up (no sibling
    # remains REQUIRED): first visit to ELIGIBILITY_REVIEW.
    validate_success(api_client.review_document(docs[0]["id"], {"decision": "ACCEPTED"}, PROC1))
    assert get_case(case["id"])["status"] == "ELIGIBILITY_REVIEW"

    # REQUEST_DOCS loops the cycle: back to DOCS_PENDING with a new REQUIRED doc.
    looped = validate_success(api_client.decide_eligibility(
        case["id"],
        {"decision": "REQUEST_DOCS", "request_doc_types": ["RECEIVING_PLAN_ACCEPTANCE"]},
        PROC1,
    ))
    assert looped["status"] == "DOCS_PENDING", (
        f"REQUEST_DOCS must return the case to DOCS_PENDING, got {looped['status']}"
    )
    docs_after = list_case_documents(case["id"])
    new_docs = [d for d in docs_after if d["doc_type"] == "RECEIVING_PLAN_ACCEPTANCE"]
    assert len(new_docs) == 1 and new_docs[0]["status"] == "REQUIRED"

    # Submit + accept the new document: second visit to ELIGIBILITY_REVIEW.
    validate_success(api_client.submit_document(new_docs[0]["id"], p_headers))
    validate_success(api_client.review_document(new_docs[0]["id"], {"decision": "ACCEPTED"}, PROC1))
    assert get_case(case["id"])["status"] == "ELIGIBILITY_REVIEW"

    # All documents ACCEPTED -> APPROVE completes the cycle at ELIGIBLE.
    validate_success(api_client.review_document(docs[1]["id"], {"decision": "ACCEPTED"}, PROC1))
    approved = validate_success(api_client.decide_eligibility(case["id"], {"decision": "APPROVE"}, PROC1))
    assert approved["status"] == "ELIGIBLE", f"approved case must be ELIGIBLE, got {approved['status']}"


def test_case_review_docs_cycle_repeated_request_docs_rounds(api):
    """PRD §3.4: "**REQUEST_DOCS** reopens the documentation loop: the case
    returns to `DOCS_PENDING` and new `RequiredDocument` rows are inserted in
    `REQUIRED` status for exactly the document types named in the decision's
    `request_doc_types` input, deduplicated by type. Review may demand more
    documents repeatedly."

    Design: Difficulty/non_linear_state_machine/case_review_docs_cycle
    """
    _plan, participant, _account, case = _submitted_indirect_case()
    settle_case_documents(case["id"], participant["id"])
    assert get_case(case["id"])["status"] == "ELIGIBILITY_REVIEW"

    p_headers = make_participant_headers(participant["id"])
    # First extra round.
    round1 = validate_success(api_client.decide_eligibility(
        case["id"], {"decision": "REQUEST_DOCS", "request_doc_types": ["DISABILITY_PROOF"]}, PROC1,
    ))
    assert round1["status"] == "DOCS_PENDING"
    new1 = [d for d in list_case_documents(case["id"]) if d["doc_type"] == "DISABILITY_PROOF"]
    assert len(new1) == 1 and new1[0]["status"] == "REQUIRED"
    validate_success(api_client.submit_document(new1[0]["id"], p_headers))
    validate_success(api_client.review_document(new1[0]["id"], {"decision": "ACCEPTED"}, PROC1))
    assert get_case(case["id"])["status"] == "ELIGIBILITY_REVIEW"

    # Second extra round: review may demand more documents repeatedly.
    round2 = validate_success(api_client.decide_eligibility(
        case["id"], {"decision": "REQUEST_DOCS", "request_doc_types": ["SPOUSAL_CONSENT"]}, PROC1,
    ))
    assert round2["status"] == "DOCS_PENDING"
    new2 = [d for d in list_case_documents(case["id"]) if d["doc_type"] == "SPOUSAL_CONSENT"]
    assert len(new2) == 1 and new2[0]["status"] == "REQUIRED"
    validate_success(api_client.submit_document(new2[0]["id"], p_headers))
    validate_success(api_client.review_document(new2[0]["id"], {"decision": "ACCEPTED"}, PROC1))
    assert get_case(case["id"])["status"] == "ELIGIBILITY_REVIEW"

    approved = validate_success(api_client.decide_eligibility(case["id"], {"decision": "APPROVE"}, PROC1))
    assert approved["status"] == "ELIGIBLE"


def test_document_resubmit_cycle_clears_reviewer(api):
    """PRD §3.4: "A rejected document may be resubmitted (`REJECTED →
    SUBMITTED`), which clears `reviewed_by` and sets `submitted_by` anew; the
    review may therefore cycle as many times as needed."
    PRD §3.4: "Rejection requires a `review_note` (its absence is a
    malformed-payload `ERR_VALIDATION`), records `reviewed_by`, stores the note"

    Design: Difficulty/non_linear_state_machine/document_resubmit_cycle
    """
    _plan, participant, _account, case = _submitted_indirect_case()
    p_headers = make_participant_headers(participant["id"])
    doc = list_case_documents(case["id"])[0]

    submitted = validate_success(api_client.submit_document(doc["id"], p_headers))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by"] == participant["id"]

    rejected = validate_success(api_client.review_document(
        doc["id"], {"decision": "REJECTED", "review_note": "illegible scan"}, PROC1,
    ))
    assert rejected["status"] == "REJECTED"
    assert rejected["reviewed_by"] == "proc-1"
    assert rejected["review_note"] == "illegible scan"

    resubmitted = validate_success(api_client.submit_document(doc["id"], p_headers))
    assert resubmitted["status"] == "SUBMITTED", (
        f"resubmission must move REJECTED -> SUBMITTED, got {resubmitted['status']}"
    )
    assert resubmitted.get("reviewed_by") is None, (
        f"resubmission must clear reviewed_by, got {resubmitted.get('reviewed_by')}"
    )

    accepted = validate_success(api_client.review_document(doc["id"], {"decision": "ACCEPTED"}, PROC1))
    assert accepted["status"] == "ACCEPTED"


def test_document_rejection_requires_review_note(api):
    """PRD §3.4: "Rejection requires a `review_note` (its absence is a
    malformed-payload `ERR_VALIDATION`), records `reviewed_by`, stores the note"
    PRD §3.4: "A `RolloverProcessor` then reviews each `SUBMITTED` document with
    a `decision` of `ACCEPTED` or `REJECTED`."

    Design: Difficulty/non_linear_state_machine/document_resubmit_cycle
    """
    _plan, participant, _account, case = _submitted_indirect_case()
    p_headers = make_participant_headers(participant["id"])
    doc = list_case_documents(case["id"])[0]
    validate_success(api_client.submit_document(doc["id"], p_headers))

    resp = api_client.review_document(doc["id"], {"decision": "REJECTED"}, PROC1)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)

    # The document is untouched by the malformed rejection and may be rejected
    # properly once a note accompanies the decision.
    rejected = validate_success(api_client.review_document(
        doc["id"], {"decision": "REJECTED", "review_note": "name mismatch"}, PROC1,
    ))
    assert rejected["status"] == "REJECTED"
    resubmitted = validate_success(api_client.submit_document(doc["id"], p_headers))
    assert resubmitted["status"] == "SUBMITTED"


def test_document_rejection_reopens_docs_loop(api):
    """PRD §3.4: "Rejection requires a `review_note` (its absence is a
    malformed-payload `ERR_VALIDATION`), records `reviewed_by`, stores the note,
    and cascades in the opposite direction — if the case had already reached
    `ELIGIBILITY_REVIEW`, it is reopened to `DOCS_PENDING`, restarting the
    loop."
    PRD §3.4: "The precondition common to all three is that the case is
    currently in `ELIGIBILITY_REVIEW` (else `ERR_CASE_INVALID_STATE`)."

    Design: Difficulty/transitive_cascade/document_rejection_reopens_docs_loop
    """
    _plan, participant, _account, case = _submitted_indirect_case()
    p_headers = make_participant_headers(participant["id"])
    docs = list_case_documents(case["id"])
    for d in docs:
        validate_success(api_client.submit_document(d["id"], p_headers))
    # Accept the first document: with no sibling left REQUIRED the case bubbles
    # up to ELIGIBILITY_REVIEW while the second document is still SUBMITTED.
    validate_success(api_client.review_document(docs[0]["id"], {"decision": "ACCEPTED"}, PROC1))
    assert get_case(case["id"])["status"] == "ELIGIBILITY_REVIEW"

    rejected = validate_success(api_client.review_document(
        docs[1]["id"], {"decision": "REJECTED", "review_note": "name mismatch"}, PROC1,
    ))
    assert rejected["status"] == "REJECTED"

    regressed = get_case(case["id"])
    assert regressed["status"] == "DOCS_PENDING", (
        f"rejection must reopen the case to DOCS_PENDING, got {regressed['status']}"
    )

    resp = api_client.decide_eligibility(case["id"], {"decision": "APPROVE"}, PROC1)
    validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE, expected_status=409)


def test_document_rejection_reopen_then_complete_after_resubmit(api):
    """PRD §3.4: "Rejection requires a `review_note` (its absence is a
    malformed-payload `ERR_VALIDATION`), records `reviewed_by`, stores the note,
    and cascades in the opposite direction — if the case had already reached
    `ELIGIBILITY_REVIEW`, it is reopened to `DOCS_PENDING`, restarting the
    loop."
    PRD §3.4: "**APPROVE** requires that every `RequiredDocument` row on the
    case be in `ACCEPTED` status (else `ERR_DOCUMENTS_OUTSTANDING`)."

    Design: Difficulty/transitive_cascade/document_rejection_reopens_docs_loop
    """
    _plan, participant, _account, case = _submitted_indirect_case()
    p_headers = make_participant_headers(participant["id"])
    docs = list_case_documents(case["id"])
    for d in docs:
        validate_success(api_client.submit_document(d["id"], p_headers))
    validate_success(api_client.review_document(docs[0]["id"], {"decision": "ACCEPTED"}, PROC1))
    assert get_case(case["id"])["status"] == "ELIGIBILITY_REVIEW"

    rejected = validate_success(api_client.review_document(
        docs[1]["id"], {"decision": "REJECTED", "review_note": "missing signature"}, PROC1,
    ))
    assert rejected["reviewed_by"] == "proc-1"
    assert rejected["review_note"] == "missing signature"
    assert get_case(case["id"])["status"] == "DOCS_PENDING"

    # Resubmit the rejected document, accept it, and approval becomes possible.
    validate_success(api_client.submit_document(docs[1]["id"], p_headers))
    validate_success(api_client.review_document(docs[1]["id"], {"decision": "ACCEPTED"}, PROC1))
    approved = validate_success(api_client.decide_eligibility(case["id"], {"decision": "APPROVE"}, PROC1))
    assert approved["status"] == "ELIGIBLE"
    assert approved["eligibility_decided_by"] == "proc-1"


def test_approve_with_documents_outstanding_rejected(api):
    """PRD §3.4: "**APPROVE** requires that every `RequiredDocument` row on the
    case be in `ACCEPTED` status (else `ERR_DOCUMENTS_OUTSTANDING`)."
    PRD §3.4: "Acceptance records the reviewer's `X-User-ID` as `reviewed_by`
    and bubbles up: if no sibling document on the case remains `REQUIRED`, the
    case advances `DOCS_PENDING → ELIGIBILITY_REVIEW`."

    Design: Corner/validations/approve_with_documents_outstanding_rejected
    """
    _plan, participant, _account, case = _submitted_indirect_case()
    p_headers = make_participant_headers(participant["id"])
    docs = list_case_documents(case["id"])
    for d in docs:
        validate_success(api_client.submit_document(d["id"], p_headers))
    # Accept one document so the case bubbles up while the other is only
    # SUBMITTED: reaching review is not approval-readiness.
    validate_success(api_client.review_document(docs[0]["id"], {"decision": "ACCEPTED"}, PROC1))
    assert get_case(case["id"])["status"] == "ELIGIBILITY_REVIEW"

    resp = api_client.decide_eligibility(case["id"], {"decision": "APPROVE"}, PROC1)
    validate_error(resp, ApiErrorId.ERR_DOCUMENTS_OUTSTANDING, expected_status=409)


def test_document_submit_on_accepted_rejected(api):
    """PRD §3.4: "The participant moves a document `REQUIRED → SUBMITTED` by
    submitting it, but only while the owning case is in `DOCS_PENDING`
    (otherwise `ERR_CASE_INVALID_STATE`) and only while the document is in
    `REQUIRED` or `REJECTED` (otherwise `ERR_DOCUMENT_INVALID_STATE`)"

    Design: Corner/state_machines/document_submit_on_accepted_rejected
    """
    _plan, participant, _account, case = _submitted_indirect_case()
    p_headers = make_participant_headers(participant["id"])
    doc = list_case_documents(case["id"])[0]
    validate_success(api_client.submit_document(doc["id"], p_headers))
    accepted = validate_success(api_client.review_document(doc["id"], {"decision": "ACCEPTED"}, PROC1))
    assert accepted["status"] == "ACCEPTED"

    resp = api_client.submit_document(doc["id"], p_headers)
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_INVALID_STATE, expected_status=409)


def test_participant_cannot_review_document(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403); the
    full role-to-endpoint mapping is given in §4."
    PRD §4: the document review endpoint is authorized for `RolloverProcessor`
    only.

    Design: Corner/rbac/participant_cannot_review_document
    """
    _plan, participant, _account, case = _submitted_indirect_case()
    p_headers = make_participant_headers(participant["id"])
    doc = list_case_documents(case["id"])[0]
    validate_success(api_client.submit_document(doc["id"], p_headers))

    resp = api_client.review_document(doc["id"], {"decision": "ACCEPTED"}, p_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    still = [d for d in list_case_documents(case["id"]) if d["id"] == doc["id"]][0]
    assert still["status"] == "SUBMITTED", "unauthorized review must not mutate the document"
