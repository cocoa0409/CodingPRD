"""Hardship approval pipeline: cyclic review via REQUEST_DOCS, substantiation
gates at final approval, and the priority-9-beats-priority-10 conflict
(PRD §3.9, §2.8)."""
from prd_bench_local_runner.testing import (
    build_user_headers,
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_hardship_fully,
    create_hardship_request_payload,
    create_plan_payload,
    enroll_participant,
    list_hardship_tasks,
    make_participant_headers,
    setup_paid_hardship,
    setup_plan_and_participant,
    upload_document,
)

ADMIN = TEST_USERS["admin_headers"]
SPONSOR = TEST_USERS["sponsor_headers"]


# ---------------------------------------------------------------------------
# Difficulty: hardship_review_document_cycle
# ---------------------------------------------------------------------------


def test_hardship_review_document_cycle_pending_documents(api):
    """PRD §3.9: "An approver who needs more evidence decides the task with
    `REQUEST_DOCS` — valid only for `HARDSHIP` subjects ... — which moves the
    task to `DOCS_REQUESTED` and the request from `UNDER_REVIEW` to
    `PENDING_DOCUMENTS`."

    Design: Difficulty/non_linear_state_machine/hardship_review_document_cycle
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=20_000_000)
    request = validate_success(
        api.create_hardship_request(
            participant["id"],
            create_hardship_request_payload(
                reason_category="MEDICAL", amount_cents=800_000, amount_semantics="GROSS"
            ),
            make_participant_headers(participant["id"]),
        ),
        201,
    )
    tasks = list_hardship_tasks(request["id"])
    # Step 1 (PLAN_SPONSOR) decides REQUEST_DOCS
    validate_success(
        api.decide_approval_task(tasks[0]["id"], {"decision": "REQUEST_DOCS"}, SPONSOR),
        200,
    )
    mid = validate_success(api.get_hardship_request(request["id"], ADMIN), 200)
    assert mid["status"] == "PENDING_DOCUMENTS"

    # Upload a document -> request returns to UNDER_REVIEW; task reopens PENDING
    upload_document(
        participant, request["id"], amount_cents=800_000,
        document_type="MEDICAL_BILL",
    )
    back = validate_success(api.get_hardship_request(request["id"], ADMIN), 200)
    assert back["status"] == "UNDER_REVIEW"
    task1 = validate_success(api.get_approval_task(tasks[0]["id"], ADMIN), 200)
    assert task1["status"] == "PENDING"


def test_hardship_review_document_cycle_reopen_and_approve(api):
    """PRD §3.9: "When the participant then uploads a document, the request
    returns to `UNDER_REVIEW` and the `DOCS_REQUESTED` task returns to `PENDING`
    with its `decided_by` and `decided_on` cleared: the step reopens for a
    fresh decision, and the earlier request-documents decision does not count
    toward segregation of duties."

    Design: Difficulty/non_linear_state_machine/hardship_review_document_cycle
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=20_000_000)
    request = validate_success(
        api.create_hardship_request(
            participant["id"],
            create_hardship_request_payload(
                reason_category="MEDICAL", amount_cents=800_000, amount_semantics="GROSS"
            ),
            make_participant_headers(participant["id"]),
        ),
        201,
    )
    tasks = list_hardship_tasks(request["id"])
    validate_success(
        api.decide_approval_task(tasks[0]["id"], {"decision": "REQUEST_DOCS"}, SPONSOR),
        200,
    )
    upload_document(
        participant, request["id"], amount_cents=800_000,
        document_type="MEDICAL_BILL",
    )
    # Step 1 sponsor re-decides APPROVE; step 2 admin approves -> APPROVED
    approve_hardship_fully(request["id"])
    final = validate_success(api.get_hardship_request(request["id"], ADMIN), 200)
    assert final["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Difficulty: safety_beats_temporal_on_hardship_final_approval
# ---------------------------------------------------------------------------


def _setup_priority_conflict(api):
    """H2 created BEFORE H1 is paid; H1 then paid (opening a suspension); H2 has
    no documents and its final APPROVE is attempted under an ACTIVE suspension
    (priority-9 substantiation vs priority-10 suspension overlap)."""
    plan, participant = setup_plan_and_participant(vested_balance_cents=20_000_000)
    # H2 created FIRST so it doesn't trip the suspension gate at create
    h2 = validate_success(
        api.create_hardship_request(
            participant["id"],
            create_hardship_request_payload(
                reason_category="FUNERAL", amount_cents=300_000, amount_semantics="GROSS"
            ),
            make_participant_headers(participant["id"]),
        ),
        201,
    )
    h1 = validate_success(
        api.create_hardship_request(
            participant["id"],
            create_hardship_request_payload(
                reason_category="MEDICAL", amount_cents=200_000, amount_semantics="GROSS"
            ),
            make_participant_headers(participant["id"]),
        ),
        201,
    )
    # Document H1 and approve both steps
    upload_document(participant, h1["id"], amount_cents=200_000,
                    document_type="MEDICAL_BILL")
    approve_hardship_fully(h1["id"])
    # Pay H1 -> opens suspension window
    get_success_data(api.pay_hardship_request(h1["id"], ADMIN))
    # H2 step 1 approved by sponsor; H2 still has no documents
    h2_tasks = list_hardship_tasks(h2["id"])
    validate_success(
        api.decide_approval_task(h2_tasks[0]["id"], {"decision": "APPROVE"}, SPONSOR),
        200,
    )
    return plan, participant, h1, h2, h2_tasks


def test_safety_beats_temporal_on_hardship_final_approval_error_id(api):
    """PRD §2.8: "Every request is evaluated against a fixed cascade of check
    groups, applied in the priority order below; the first failing group
    determines the error response". Priority 9 (substantiation) precedes
    priority 10 (suspension overlap), so the zero-document substantiation
    failure wins.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_hardship_final_approval
    """
    _, _, _, h2, h2_tasks = _setup_priority_conflict(api)
    res = api.decide_approval_task(
        h2_tasks[1]["id"], {"decision": "APPROVE"}, TEST_USERS["admin_headers"]
    )
    validate_error(
        res, ApiErrorId.ERR_SUBSTANTIATION_INCOMPLETE, expected_status=422
    )


def test_safety_beats_temporal_on_hardship_final_approval_state_unchanged(api):
    """PRD §3.9: "When the final step approves, the request moves from
    `UNDER_REVIEW` to `APPROVED`" — a rejected final approval leaves the
    request in `UNDER_REVIEW`.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_hardship_final_approval
    """
    _, _, _, h2, h2_tasks = _setup_priority_conflict(api)
    res = api.decide_approval_task(
        h2_tasks[1]["id"], {"decision": "APPROVE"}, TEST_USERS["admin_headers"]
    )
    validate_error(res, ApiErrorId.ERR_SUBSTANTIATION_INCOMPLETE)
    h2_after = validate_success(api.get_hardship_request(h2["id"], ADMIN), 200)
    assert h2_after["status"] == "UNDER_REVIEW"


# ---------------------------------------------------------------------------
# Corner: self_certify_plan_requires_attestation_at_approval
# ---------------------------------------------------------------------------


def test_self_certify_plan_requires_attestation_at_approval_missing(api):
    """PRD §2.8 priority 9: "Under a `FULL_DOCUMENTATION` standard, at least one
    uploaded document must exist; under `SELF_CERTIFY`, the request's
    `attestation` must be true. Otherwise `ERR_SUBSTANTIATION_INCOMPLETE`."

    Design: Corner/validations/self_certify_plan_requires_attestation_at_approval
    """
    plan = validate_success(
        api.create_plan(
            create_plan_payload(
                substantiation_standard="SELF_CERTIFY",
                hardship_approval_chain=["RECORDKEEPER_ADMIN"],
            ),
            ADMIN,
        ),
        201,
    )
    participant = enroll_participant(plan["id"], vested_balance_cents=20_000_000)
    # No attestation on the request
    h = validate_success(
        api.create_hardship_request(
            participant["id"],
            create_hardship_request_payload(
                reason_category="MEDICAL", amount_cents=200_000,
                amount_semantics="GROSS",
            ),
            make_participant_headers(participant["id"]),
        ),
        201,
    )
    tasks = list_hardship_tasks(h["id"])
    res = api.decide_approval_task(
        tasks[0]["id"], {"decision": "APPROVE"}, ADMIN
    )
    validate_error(
        res, ApiErrorId.ERR_SUBSTANTIATION_INCOMPLETE, expected_status=422
    )


def test_self_certify_plan_requires_attestation_at_approval_attested(api):
    """PRD §2.8 priority 9: "under `SELF_CERTIFY`, the request's `attestation`
    must be true" — with attestation true the final approval succeeds.

    Design: Corner/validations/self_certify_plan_requires_attestation_at_approval
    """
    plan = validate_success(
        api.create_plan(
            create_plan_payload(
                substantiation_standard="SELF_CERTIFY",
                hardship_approval_chain=["RECORDKEEPER_ADMIN"],
            ),
            ADMIN,
        ),
        201,
    )
    participant = enroll_participant(plan["id"], vested_balance_cents=20_000_000)
    h = validate_success(
        api.create_hardship_request(
            participant["id"],
            create_hardship_request_payload(
                reason_category="MEDICAL", amount_cents=200_000,
                amount_semantics="GROSS", attestation=True,
            ),
            make_participant_headers(participant["id"]),
        ),
        201,
    )
    tasks = list_hardship_tasks(h["id"])
    task_after = validate_success(
        api.decide_approval_task(tasks[0]["id"], {"decision": "APPROVE"}, ADMIN),
        200,
    )
    assert task_after["status"] == "APPROVED"
    h_after = validate_success(api.get_hardship_request(h["id"], ADMIN), 200)
    assert h_after["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Corner: hardship_need_cap_exceeded_at_final_approval
# ---------------------------------------------------------------------------


def test_hardship_need_cap_exceeded_at_final_approval(api):
    """PRD §3.9: "Under `FULL_DOCUMENTATION`, at least one uploaded document
    must exist, else the decision is rejected with
    `ERR_SUBSTANTIATION_INCOMPLETE`, and the uploaded documents' `amount_cents`
    values must sum to at least the requested `amount_cents`, else
    `ERR_HARDSHIP_AMOUNT_EXCEEDS_NEED`."

    Design: Corner/validations/hardship_need_cap_exceeded_at_final_approval
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=20_000_000)
    h = validate_success(
        api.create_hardship_request(
            participant["id"],
            create_hardship_request_payload(
                reason_category="MEDICAL", amount_cents=800_000, amount_semantics="GROSS"
            ),
            make_participant_headers(participant["id"]),
        ),
        201,
    )
    # One document 1 cent short of the requested amount
    upload_document(
        participant, h["id"], amount_cents=799_999, document_type="MEDICAL_BILL"
    )
    tasks = list_hardship_tasks(h["id"])
    validate_success(
        api.decide_approval_task(tasks[0]["id"], {"decision": "APPROVE"}, SPONSOR),
        200,
    )
    res = api.decide_approval_task(
        tasks[1]["id"], {"decision": "APPROVE"}, ADMIN
    )
    validate_error(
        res, ApiErrorId.ERR_HARDSHIP_AMOUNT_EXCEEDS_NEED, expected_status=422
    )
    h_after = validate_success(api.get_hardship_request(h["id"], ADMIN), 200)
    assert h_after["status"] == "UNDER_REVIEW"
