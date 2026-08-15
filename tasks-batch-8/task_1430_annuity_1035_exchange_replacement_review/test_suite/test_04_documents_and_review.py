"""Disclosure document workflow, the info-request review loop, recommendation
gates, and segregation of duties (PRD §3.3, §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_verified_documents,
    approve_case,
    create_analysis,
    get_case,
    list_review_decisions,
    make_principal_headers,
    make_producer_headers,
    make_reviewer_headers,
    rationale_payload,
    recommend_case,
    reject_document,
    register_client,
    register_contract,
    register_producer,
    setup_case_in_review,
    setup_case_pending_principal,
    start_review,
    submit_case,
    submit_document,
    open_case,
    validate_error,
    validate_paginated,
    validate_success,
    verify_document,
)


# ── Info-request cycle and the fork into approval ─────────────────────────


def test_document_resubmission_returns_info_requested_case_to_review(api):
    """PRD §3.3: "When the case was sitting in `INFO_REQUESTED`, the
    resubmission is also the producer's channel for answering the info request:
    the case returns to `SUITABILITY_REVIEW` in the same operation."
    PRD §3.3: "The producer may resubmit the same `doc_type`, which moves the
    document `REJECTED` → `SUBMITTED`, increments its `revision` by exactly 1,
    and clears its `rejection_reason`; this correction loop may repeat any
    number of times."

    Design: Difficulty/non_linear_state_machine/case_info_request_cycle_and_fork
    """
    bundle = setup_case_in_review()
    producer_id = bundle["producer"]["id"]
    case_id = bundle["case_id"]
    docs = [
        submit_document(case_id, producer_id, dt)
        for dt in ("REPLACEMENT_DISCLOSURE", "SUITABILITY_FORM", "IN_FORCE_ILLUSTRATION")
    ]
    rejected = reject_document(docs[1]["id"], "missing signature")
    assert rejected["status"] == "REJECTED"
    validate_success(
        api.request_info(
            case_id, rationale_payload("correct the suitability form"),
            make_reviewer_headers("rev-1"),
        )
    )
    assert get_case(case_id)["status"] == "INFO_REQUESTED"

    resubmitted = validate_success(
        api.create_document(
            case_id,
            {"doc_type": "SUITABILITY_FORM"},
            make_producer_headers(producer_id),
        ),
        expected_status=201,
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision"] == 2, "resubmission increments revision by exactly 1"
    assert resubmitted.get("rejection_reason") is None, "rejection_reason cleared"
    assert get_case(case_id)["status"] == "SUITABILITY_REVIEW", (
        "resubmission returns an INFO_REQUESTED case to review in the same operation"
    )


def test_info_request_cycle_completes_fork_to_approval(api):
    """PRD §3.5: "A successful recommendation appends a review decision at
    stage `SUITABILITY` with decision `APPROVE` and the supplied `rationale`,
    and stamps the case's `reviewed_by_id` with the reviewer's `X-User-ID`."
    PRD §3.5: "Approval appends a review decision at stage `PRINCIPAL` with
    decision `APPROVE` and stamps `approved_by_id`."
    PRD §2.9: "`REQUEST_INFO` is only ever recorded at the `SUITABILITY`
    stage."

    Design: Difficulty/non_linear_state_machine/case_info_request_cycle_and_fork
    """
    bundle = setup_case_in_review()
    producer_id = bundle["producer"]["id"]
    case_id = bundle["case_id"]
    docs = [
        submit_document(case_id, producer_id, dt)
        for dt in ("REPLACEMENT_DISCLOSURE", "SUITABILITY_FORM", "IN_FORCE_ILLUSTRATION")
    ]
    reject_document(docs[1]["id"], "missing signature")
    validate_success(
        api.request_info(
            case_id, rationale_payload("correct the suitability form"),
            make_reviewer_headers("rev-1"),
        )
    )
    resubmitted = validate_success(
        api.create_document(
            case_id, {"doc_type": "SUITABILITY_FORM"},
            make_producer_headers(producer_id),
        ),
        expected_status=201,
    )
    case_v = get_case(case_id)["version"]
    verify_document(docs[0]["id"])
    verify_document(resubmitted["id"])
    verify_document(docs[2]["id"])
    create_analysis(case_id, case_v)

    recommended = recommend_case(case_id)
    assert recommended["status"] == "PENDING_PRINCIPAL"
    assert recommended["reviewed_by_id"] == "rev-1"

    approved = approve_case(case_id)
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_id"] == "prin-1"

    decisions = list_review_decisions(case_id)
    assert len(decisions) == 3
    assert [(d["stage"], d["decision"]) for d in decisions] == [
        ("SUITABILITY", "REQUEST_INFO"),
        ("SUITABILITY", "APPROVE"),
        ("PRINCIPAL", "APPROVE"),
    ], "decision records must appear in creation order"


# ── Document revision loop ────────────────────────────────────────────────


def test_document_revision_loop_increments_on_each_resubmission(api):
    """PRD §3.3: "The producer may resubmit the same `doc_type`, which moves
    the document `REJECTED` → `SUBMITTED`, increments its `revision` by exactly
    1, and clears its `rejection_reason`; this correction loop may repeat any
    number of times."
    PRD §3.3: "Each new document starts `SUBMITTED` at `revision` 1."

    Design: Difficulty/non_linear_state_machine/document_revision_loop
    """
    bundle = setup_case_in_review()
    producer_id = bundle["producer"]["id"]
    case_id = bundle["case_id"]

    first = submit_document(case_id, producer_id, "REPLACEMENT_DISCLOSURE")
    assert first["revision"] == 1
    assert first["status"] == "SUBMITTED"

    reject_document(first["id"], "illegible")
    second = validate_success(
        api.create_document(
            case_id, {"doc_type": "REPLACEMENT_DISCLOSURE"},
            make_producer_headers(producer_id),
        ),
        expected_status=201,
    )
    assert second["revision"] == 2
    assert second["status"] == "SUBMITTED"
    assert second.get("rejection_reason") is None

    reject_document(second["id"], "wrong client name")
    third = validate_success(
        api.create_document(
            case_id, {"doc_type": "REPLACEMENT_DISCLOSURE"},
            make_producer_headers(producer_id),
        ),
        expected_status=201,
    )
    assert third["revision"] == 3


def test_third_resubmission_verifies_at_revision_three(api):
    """PRD §3.3: "The producer may resubmit the same `doc_type`, which moves
    the document `REJECTED` → `SUBMITTED`, increments its `revision` by exactly
    1, and clears its `rejection_reason`; this correction loop may repeat any
    number of times."
    PRD §3.3: "verifying one moves it `SUBMITTED` → `VERIFIED`" — the
    resubmission reopens the same document rather than forking duplicates, so
    the doc_type listing shows exactly one current document.

    Design: Difficulty/non_linear_state_machine/document_revision_loop
    """
    bundle = setup_case_in_review()
    producer_id = bundle["producer"]["id"]
    case_id = bundle["case_id"]

    doc = submit_document(case_id, producer_id, "REPLACEMENT_DISCLOSURE")
    reject_document(doc["id"], "illegible")
    doc = validate_success(
        api.create_document(
            case_id, {"doc_type": "REPLACEMENT_DISCLOSURE"},
            make_producer_headers(producer_id),
        ),
        expected_status=201,
    )
    reject_document(doc["id"], "wrong client name")
    doc = validate_success(
        api.create_document(
            case_id, {"doc_type": "REPLACEMENT_DISCLOSURE"},
            make_producer_headers(producer_id),
        ),
        expected_status=201,
    )

    verified = verify_document(doc["id"])
    assert verified["status"] == "VERIFIED"
    assert verified["revision"] == 3

    docs, meta = validate_paginated(
        api.list_case_documents(
            case_id, TEST_USERS["ops_headers"],
            params={"doc_type": "REPLACEMENT_DISCLOSURE"},
        )
    )
    assert meta["total_count"] == 1, "resubmission reopens the same document"
    assert docs[0]["status"] == "VERIFIED"
    assert docs[0]["revision"] == 3


# ── Cross-entity guard: document adjudication needs the case in review ────


def test_document_verify_rejected_while_case_only_submitted(api):
    """PRD §3.3: "Both adjudications require the parent case to be in
    `SUITABILITY_REVIEW` or `INFO_REQUESTED`, failing with
    `ERR_INVALID_STATE_TRANSITION` otherwise."

    Design: Difficulty/cross_entity_state_dependency/document_verify_requires_case_in_review
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(producer["id"], client["id"])
    case = open_case(producer["id"], client["id"], contract["id"])
    submit_case(case["id"], producer["id"])
    doc = submit_document(case["id"], producer["id"], "REPLACEMENT_DISCLOSURE")

    res = api.verify_document(doc["id"], make_reviewer_headers("rev-1"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    docs, _ = validate_paginated(
        api.list_case_documents(case["id"], TEST_USERS["ops_headers"])
    )
    assert docs[0]["status"] == "SUBMITTED", "failed verify must not move the document"


def test_document_verify_succeeds_once_case_in_review(api):
    """PRD §3.3: "Both adjudications require the parent case to be in
    `SUITABILITY_REVIEW` or `INFO_REQUESTED`, failing with
    `ERR_INVALID_STATE_TRANSITION` otherwise."
    PRD §3.3: "Review begins when a `SuitabilityReviewer` takes a `SUBMITTED`
    case into review, moving `SUBMITTED` → `SUITABILITY_REVIEW`."

    Design: Difficulty/cross_entity_state_dependency/document_verify_requires_case_in_review
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(producer["id"], client["id"])
    case = open_case(producer["id"], client["id"], contract["id"])
    submit_case(case["id"], producer["id"])
    doc = submit_document(case["id"], producer["id"], "REPLACEMENT_DISCLOSURE")

    validate_error(
        api.verify_document(doc["id"], make_reviewer_headers("rev-1")),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    start_review(case["id"])
    verified = verify_document(doc["id"])
    assert verified["status"] == "VERIFIED"


# ── Recommendation gates and their ordering against state legality ────────


def test_recommend_in_info_requested_reports_state_error_not_documents(api):
    """PRD §2.8: "Sixth, state legality of the requested transition is checked
    (`ERR_INVALID_STATE_TRANSITION`, HTTP 409 — or
    `ERR_CONTRACT_NOT_IN_FORCE` for the contract precondition on case
    submission). Seventh, on the one OCC-guarded write, the expected version is
    compared (`ERR_STALE_VERSION`). Only after all seven rungs pass do the
    domain business rules of §3 run, in the orders stated there."
    With the case in INFO_REQUESTED and the document file incomplete, the
    state error fires before the §3.5 document check can.

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_document_safety
    """
    bundle = setup_case_in_review()
    producer_id = bundle["producer"]["id"]
    case_id = bundle["case_id"]
    doc = submit_document(case_id, producer_id, "REPLACEMENT_DISCLOSURE")
    verify_document(doc["id"])
    validate_success(
        api.request_info(
            case_id, rationale_payload("need remaining docs"),
            make_reviewer_headers("rev-1"),
        )
    )

    res = api.recommend_case(
        case_id, rationale_payload("premature"), make_reviewer_headers("rev-1")
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_case(case_id)["status"] == "INFO_REQUESTED"


def test_recommend_in_info_requested_fails_even_with_complete_file(api):
    """PRD §2.8: "Sixth, state legality of the requested transition is checked
    (`ERR_INVALID_STATE_TRANSITION`, HTTP 409 — or
    `ERR_CONTRACT_NOT_IN_FORCE` for the contract precondition on case
    submission). Seventh, on the one OCC-guarded write, the expected version is
    compared (`ERR_STALE_VERSION`). Only after all seven rungs pass do the
    domain business rules of §3 run, in the orders stated there."
    PRD §3.5 names the recommend transition `SUITABILITY_REVIEW` →
    `PENDING_PRINCIPAL`, so even a complete file cannot be recommended from
    INFO_REQUESTED.

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_document_safety
    """
    bundle = setup_case_in_review()
    producer_id = bundle["producer"]["id"]
    case_id = bundle["case_id"]
    add_verified_documents(case_id, producer_id)
    validate_success(
        api.request_info(
            case_id, rationale_payload("one more look"),
            make_reviewer_headers("rev-1"),
        )
    )
    # Analysis creation is still legitimate from INFO_REQUESTED (PRD §3.4).
    create_analysis(case_id, get_case(case_id)["version"])

    res = api.recommend_case(
        case_id, rationale_payload("complete file"), make_reviewer_headers("rev-1")
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_case(case_id)["status"] == "INFO_REQUESTED"


def test_recommend_without_all_documents_verified_rejected(api):
    """PRD §3.5: "Recommendation enforces two checks, in this order: all three
    required document types must have a `VERIFIED` document, else
    `ERR_REQUIRED_DOCUMENTS_INCOMPLETE` (HTTP 409); then a comparison analysis
    in `FINAL` status must exist for the case, else `ERR_ANALYSIS_MISSING`
    (HTTP 409)."

    Design: Corner/validations/docs_incomplete_blocks_recommend
    """
    bundle = setup_case_in_review()
    producer_id = bundle["producer"]["id"]
    case_id = bundle["case_id"]
    for dt in ("REPLACEMENT_DISCLOSURE", "SUITABILITY_FORM"):
        doc = submit_document(case_id, producer_id, dt)
        verify_document(doc["id"])
    # IN_FORCE_ILLUSTRATION never submitted.

    res = api.recommend_case(
        case_id, rationale_payload("premature"), make_reviewer_headers("rev-1")
    )
    validate_error(res, ApiErrorId.ERR_REQUIRED_DOCUMENTS_INCOMPLETE)
    assert get_case(case_id)["status"] == "SUITABILITY_REVIEW"


def test_recommend_without_final_analysis_rejected(api):
    """PRD §3.5: "Recommendation enforces two checks, in this order: all three
    required document types must have a `VERIFIED` document, else
    `ERR_REQUIRED_DOCUMENTS_INCOMPLETE` (HTTP 409); then a comparison analysis
    in `FINAL` status must exist for the case, else `ERR_ANALYSIS_MISSING`
    (HTTP 409)."
    With the document file complete, the documents check passes first and the
    missing analysis is the reported failure.

    Design: Corner/validations/analysis_missing_blocks_recommend
    """
    bundle = setup_case_in_review()
    add_verified_documents(bundle["case_id"], bundle["producer"]["id"])

    res = api.recommend_case(
        bundle["case_id"],
        rationale_payload("no analysis yet"),
        make_reviewer_headers("rev-1"),
    )
    validate_error(res, ApiErrorId.ERR_ANALYSIS_MISSING)
    assert get_case(bundle["case_id"])["status"] == "SUITABILITY_REVIEW"


def test_verified_document_type_locked_against_resubmission(api):
    """PRD §3.3: "Once a document reaches `VERIFIED` it is locked —
    resubmitting that `doc_type` is rejected with `ERR_DOCUMENT_LOCKED`
    (HTTP 409)."

    Design: Corner/validations/document_locked_after_verify
    """
    bundle = setup_case_in_review()
    producer_id = bundle["producer"]["id"]
    case_id = bundle["case_id"]
    doc = submit_document(case_id, producer_id, "REPLACEMENT_DISCLOSURE")
    verify_document(doc["id"])

    res = api.create_document(
        case_id, {"doc_type": "REPLACEMENT_DISCLOSURE"},
        make_producer_headers(producer_id),
    )
    validate_error(res, ApiErrorId.ERR_DOCUMENT_LOCKED)

    docs, meta = validate_paginated(
        api.list_case_documents(
            case_id, TEST_USERS["ops_headers"],
            params={"doc_type": "REPLACEMENT_DISCLOSURE"},
        )
    )
    assert meta["total_count"] == 1
    assert docs[0]["status"] == "VERIFIED"
    assert docs[0]["revision"] == 1, "the VERIFIED document is unchanged"


def test_principal_who_recommended_cannot_approve(api):
    """PRD §3.5: "Segregation of duties is enforced mechanically: the approving
    principal's `X-User-ID` must differ from the case's `reviewed_by_id`, and a
    principal who recommended the case is rejected with
    `ERR_DUTY_SEGREGATION_VIOLATION` (HTTP 409)."

    Design: Corner/validations/segregation_of_duties_violation
    """
    bundle = setup_case_pending_principal()
    case_id = bundle["case_id"]

    res = api.approve_case(
        case_id, rationale_payload("self approval"), make_principal_headers("rev-1")
    )
    validate_error(res, ApiErrorId.ERR_DUTY_SEGREGATION_VIOLATION)
    assert get_case(case_id)["status"] == "PENDING_PRINCIPAL"

    approved = validate_success(
        api.approve_case(
            case_id, rationale_payload("proper approval"),
            make_principal_headers("prin-1"),
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_id"] == "prin-1"
