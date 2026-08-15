"""Intake review, document verification, and the approve/deny decision path
(PRD §3.2–§3.3), including the segregation-of-duties guards."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_application_payload,
    create_document_payload,
    get_success_data,
    make_cardholder_headers,
    make_eligibility_specialist_headers,
    make_program_administrator_headers,
    onboard_cardholder,
    set_clock,
    start_review,
    submit_initial_application,
    upload_and_verify_document,
    validate_error,
    validate_success,
    verify_document,
)

APPLICANT_HEADERS = TEST_USERS["applicant_headers"]


def test_info_request_then_resume_closes_review_cycle(api, eligibility_specialist_headers):
    """PRD §3.2: "When examination reveals a gap, the specialist sends the
    application back for more information with a payload `reason`; the
    application moves from `UNDER_REVIEW` to `INFO_REQUESTED` and the reason
    is recorded in `info_request_reason`."
    PRD §3.2: "Starting review moves the application from `SUBMITTED` to
    `UNDER_REVIEW` and stamps `reviewed_by_user_id` with the specialist's
    `X-User-ID`; the same action resumes an application that was previously
    sent back for information, moving it from `INFO_REQUESTED` back to
    `UNDER_REVIEW` and refreshing `reviewed_by_user_id` to the resuming
    specialist."
    PRD §3.2: "Supporting evidence arrives as verification documents attached
    to the application by the applicant (or, for recertifications, by the
    cardholder)."

    Design: Difficulty/non_linear_state_machine/application_info_request_review_cycle
    """
    set_clock("2026-08-01T00:00:00Z")
    app = submit_initial_application(full_name="Cycla Review",
                                     date_of_birth="1960-05-05",
                                     residency_address="6 Cedar St")
    start_review(app["id"])
    upload_and_verify_document(app["id"], "PROOF_OF_AGE", "C-AGE")

    info = validate_success(
        api.request_info(app["id"], "need income and residency documents",
                         eligibility_specialist_headers), 200)
    assert info["status"] == "INFO_REQUESTED"
    assert info["info_request_reason"] == "need income and residency documents"

    # Evidence can still arrive while the application is back with the applicant.
    doc2 = validate_success(
        api.add_document(app["id"],
                         create_document_payload("PROOF_OF_INCOME", "C-INC"),
                         APPLICANT_HEADERS), 201)
    assert doc2["status"] == "SUBMITTED"

    resumed = validate_success(
        api.start_review(app["id"], eligibility_specialist_headers), 200)
    assert resumed["status"] == "UNDER_REVIEW", (
        "start-review resumes INFO_REQUESTED back to UNDER_REVIEW (cycle closed)")


def test_info_request_cycle_ends_in_approval(api, eligibility_specialist_headers,
                                             program_administrator_headers):
    """PRD §3.2: "Starting review moves the application from `SUBMITTED` to
    `UNDER_REVIEW` and stamps `reviewed_by_user_id` with the specialist's
    `X-User-ID`; the same action resumes an application that was previously
    sent back for information, moving it from `INFO_REQUESTED` back to
    `UNDER_REVIEW` and refreshing `reviewed_by_user_id` to the resuming
    specialist."
    PRD §3.3: "Approval of an `INITIAL` application enrolls the applicant. The
    system creates a `Cardholder` record in `ACTIVE` status, copying
    `full_name`, `date_of_birth`, `annual_income_cents`, and
    `residency_address` from the approved application, and sets the
    application's `cardholder_id` to the new record."

    Design: Difficulty/non_linear_state_machine/application_info_request_review_cycle
    """
    set_clock("2026-08-01T00:00:00Z")
    app = submit_initial_application(full_name="Cycla Review",
                                     date_of_birth="1960-05-05",
                                     residency_address="6 Cedar St")
    start_review(app["id"])
    upload_and_verify_document(app["id"], "PROOF_OF_AGE", "C-AGE")
    validate_success(
        api.request_info(app["id"], "need income and residency documents",
                         eligibility_specialist_headers), 200)
    doc2 = get_success_data(
        api.add_document(app["id"],
                         create_document_payload("PROOF_OF_INCOME", "C-INC"),
                         APPLICANT_HEADERS))
    validate_success(api.start_review(app["id"], eligibility_specialist_headers), 200)
    verify_document(app["id"], doc2["id"])
    upload_and_verify_document(app["id"], "PROOF_OF_RESIDENCY", "C-RES")

    approved = validate_success(
        api.approve_application(app["id"], program_administrator_headers), 200)
    assert approved["status"] == "APPROVED"
    assert approved["cardholder_id"], (
        "approval after the info-request loop still enrolls the applicant — "
        "the loop did not corrupt the approval path")


def test_approve_submitted_application_rejected(api, program_administrator_headers):
    """PRD §3.3: "Approval is guarded by four checks evaluated in the pinned
    order of §2.10 — the application must be `UNDER_REVIEW` (otherwise
    `ERR_APPLICATION_INVALID_STATE`); the segregation-of-duties guard then
    requires the approving administrator's `X-User-ID` to differ from the
    application's `reviewed_by_user_id` and from the `reviewed_by_user_id` of
    every `VERIFIED` document on the application, so that no one who examined
    the case can decide it (violations surface as `ERR_SEGREGATION_OF_DUTIES`,
    HTTP 403); document completeness then requires at least one `VERIFIED`
    document of each of the three types `PROOF_OF_AGE`, `PROOF_OF_INCOME`, and
    `PROOF_OF_RESIDENCY` (otherwise `ERR_MISSING_REQUIRED_DOCUMENTS`, HTTP
    422); and for a `RECERTIFICATION` application the linked cardholder must
    stand in `RECERTIFICATION_DUE` or `LAPSED` at decision time (otherwise
    `ERR_RECERTIFICATION_NOT_DUE`)."

    Design: Corner/state_machines/approve_submitted_application_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    app = submit_initial_application(full_name="Early Approve",
                                     residency_address="26 Rush St")
    res = api.approve_application(app["id"], program_administrator_headers)
    validate_error(res, ApiErrorId.ERR_APPLICATION_INVALID_STATE)
    after = validate_success(
        api.get_application(app["id"], program_administrator_headers), 200)
    assert after["status"] == "SUBMITTED", "the failed approve decides nothing"
    assert after["decided_by_user_id"] is None


def test_deny_approved_application_rejected(api, program_administrator_headers):
    """PRD §3.3: "Denial is the simpler path: the administrator supplies a
    `reason` (its absence is an `ERR_INVALID_REQUEST`), the application moves
    from `UNDER_REVIEW` to `DENIED`, and the record captures `denial_reason`
    and `decided_by_user_id`."
    PRD §3.3: "A decided application is terminal, and `decided_by_user_id`
    records who decided it."

    Design: Corner/state_machines/deny_approved_application_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    onboard = onboard_cardholder(full_name="Terminal Deny",
                                 residency_address="27 Lock St")
    app_id = onboard["application"]["id"]
    assert onboard["application"]["status"] == "APPROVED"
    res = api.deny_application(app_id, "late denial", program_administrator_headers)
    validate_error(res, ApiErrorId.ERR_APPLICATION_INVALID_STATE)


def test_document_double_review_rejected(api, eligibility_specialist_headers,
                                         program_administrator_headers):
    """PRD §3.2: "Document review is guarded by two state checks evaluated
    parent-first: the parent application must be in `UNDER_REVIEW` or
    `INFO_REQUESTED` (otherwise `ERR_APPLICATION_INVALID_STATE`), and the
    document itself must still be `SUBMITTED`, since a document already
    `VERIFIED` or `REJECTED` is final and re-review is rejected with
    `ERR_DOCUMENT_ALREADY_REVIEWED` (HTTP 409)."

    Design: Corner/state_machines/document_double_review_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    app = submit_initial_application(full_name="Double Review",
                                     residency_address="28 Twice Ln")
    start_review(app["id"])
    doc = upload_and_verify_document(app["id"], "PROOF_OF_AGE", "DR-AGE")

    res = api.review_document(app["id"], doc["id"], "REJECTED",
                              eligibility_specialist_headers,
                              rejection_reason="changed my mind")
    validate_error(res, ApiErrorId.ERR_DOCUMENT_ALREADY_REVIEWED)

    docs = validate_success(
        api.list_documents(app["id"], program_administrator_headers), 200)
    kept = [d for d in docs if d["id"] == doc["id"]][0]
    assert kept["status"] == "VERIFIED", "a verified document is final"
    assert kept["reviewed_by_user_id"] == "spec-1", (
        "the original review stamp survives the rejected re-review")


def test_document_invalid_type_rejected(api, applicant_headers):
    """PRD §3.2: "Each document declares a `document_type` — one of
    `PROOF_OF_AGE`, `PROOF_OF_INCOME`, or `PROOF_OF_RESIDENCY` — and a
    free-form `document_reference` such as a license or notice number, and is
    attached to its application via `application_id`."
    PRD §3.1: "Both gates apply identically to `INITIAL` and `RECERTIFICATION`
    submissions, and malformed payloads — missing fields, wrong types,
    negative income, an invalid `kind` — are rejected with
    `ERR_INVALID_REQUEST` (HTTP 400) before any gate runs."

    Design: Corner/entities/document_invalid_enum_type_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    app = submit_initial_application(full_name="Doc Enum",
                                     residency_address="23 Doc Ln")
    res = api.add_document(app["id"],
                           create_document_payload("PASSPORT", "P-123"),
                           applicant_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_approver_who_reviewed_is_segregated(api):
    """PRD §3.3: "Approval is guarded by four checks evaluated in the pinned
    order of §2.10 — the application must be `UNDER_REVIEW` (otherwise
    `ERR_APPLICATION_INVALID_STATE`); the segregation-of-duties guard then
    requires the approving administrator's `X-User-ID` to differ from the
    application's `reviewed_by_user_id` and from the `reviewed_by_user_id` of
    every `VERIFIED` document on the application, so that no one who examined
    the case can decide it (violations surface as `ERR_SEGREGATION_OF_DUTIES`,
    HTTP 403); document completeness then requires at least one `VERIFIED`
    document of each of the three types `PROOF_OF_AGE`, `PROOF_OF_INCOME`,
    and `PROOF_OF_RESIDENCY` (otherwise `ERR_MISSING_REQUIRED_DOCUMENTS`, HTTP
    422); and for a `RECERTIFICATION` application the linked cardholder must
    stand in `RECERTIFICATION_DUE` or `LAPSED` at decision time (otherwise
    `ERR_RECERTIFICATION_NOT_DUE`)."
    Segregation is keyed on the person, not the presented role: the user id
    that reviewed the case cannot approve it even when presenting the
    ProgramAdministrator role.

    Design: Corner/validations/approver_who_reviewed_documents_segregation_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    app = submit_initial_application(full_name="Seg Duty",
                                     residency_address="43 Split St")
    spec1 = make_eligibility_specialist_headers("spec-1")
    start_review(app["id"], spec1)
    upload_and_verify_document(app["id"], "PROOF_OF_AGE", "SD-AGE",
                               specialist_headers=spec1)
    upload_and_verify_document(app["id"], "PROOF_OF_INCOME", "SD-INC",
                               specialist_headers=spec1)
    upload_and_verify_document(app["id"], "PROOF_OF_RESIDENCY", "SD-RES",
                               specialist_headers=spec1)

    res = api.approve_application(
        app["id"], make_program_administrator_headers("spec-1"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    after = validate_success(
        api.get_application(app["id"], make_program_administrator_headers("admin-1")),
        200)
    assert after["status"] == "UNDER_REVIEW", "the rejected approval decides nothing"


def test_approval_without_all_document_types_rejected(api,
                                                      program_administrator_headers):
    """PRD §3.3: "Approval is guarded by four checks evaluated in the pinned
    order of §2.10 — the application must be `UNDER_REVIEW` (otherwise
    `ERR_APPLICATION_INVALID_STATE`); the segregation-of-duties guard then
    requires the approving administrator's `X-User-ID` to differ from the
    application's `reviewed_by_user_id` and from the `reviewed_by_user_id` of
    every `VERIFIED` document on the application, so that no one who examined
    the case can decide it (violations surface as `ERR_SEGREGATION_OF_DUTIES`,
    HTTP 403); document completeness then requires at least one `VERIFIED`
    document of each of the three types `PROOF_OF_AGE`, `PROOF_OF_INCOME`,
    and `PROOF_OF_RESIDENCY` (otherwise `ERR_MISSING_REQUIRED_DOCUMENTS`, HTTP
    422); and for a `RECERTIFICATION` application the linked cardholder must
    stand in `RECERTIFICATION_DUE` or `LAPSED` at decision time (otherwise
    `ERR_RECERTIFICATION_NOT_DUE`)."
    Only PROOF_OF_AGE and PROOF_OF_INCOME are verified here; no verified
    PROOF_OF_RESIDENCY exists.

    Design: Corner/validations/approval_without_all_document_types_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    app = submit_initial_application(full_name="Docs Missing",
                                     residency_address="45 Papers Pl")
    start_review(app["id"])
    upload_and_verify_document(app["id"], "PROOF_OF_AGE", "DM-AGE")
    upload_and_verify_document(app["id"], "PROOF_OF_INCOME", "DM-INC")

    res = api.approve_application(app["id"], program_administrator_headers)
    validate_error(res, ApiErrorId.ERR_MISSING_REQUIRED_DOCUMENTS)

    after = validate_success(
        api.get_application(app["id"], program_administrator_headers), 200)
    assert after["status"] == "UNDER_REVIEW"
    assert after["cardholder_id"] is None, "no cardholder is created on a failed approval"


def test_recertification_before_window_rejected(api):
    """PRD §3.1: "And recertification is accepted only when the member's
    record is actually due — the linked cardholder must be in
    `RECERTIFICATION_DUE` or `LAPSED` status, so a submission naming an
    `ACTIVE` cardholder whose window has not opened is rejected with
    `ERR_RECERTIFICATION_NOT_DUE` (HTTP 409)."

    Design: Corner/state_machines/recertification_submitted_before_window_rejected
    """
    onboard = onboard_cardholder(full_name="Early Recert",
                                 residency_address="32 Soon St")
    ch_id = onboard["cardholder"]["id"]
    assert onboard["cardholder"]["status"] == "ACTIVE"
    assert onboard["cardholder"]["recertification_due_date"] == "2027-08-01"

    res = api.create_application(
        create_application_payload(kind="RECERTIFICATION",
                                   applicant_full_name="Early Recert",
                                   residency_address="32 Soon St",
                                   cardholder_id=ch_id),
        make_cardholder_headers(ch_id))
    validate_error(res, ApiErrorId.ERR_RECERTIFICATION_NOT_DUE)


def test_duplicate_pending_recertification_rejected(api):
    """PRD §3.1: "A member may hold at most one non-terminal recertification
    application at a time: if the named cardholder already has a
    recertification application in `SUBMITTED`, `UNDER_REVIEW`, or
    `INFO_REQUESTED`, a further submission is rejected with
    `ERR_DUPLICATE_PENDING_APPLICATION` (HTTP 409)."

    Design: Corner/state_machines/duplicate_pending_recertification_rejected
    """
    onboard = onboard_cardholder(full_name="Dup Recert",
                                 residency_address="33 Twice Ave")
    ch_id = onboard["cardholder"]["id"]
    # Open the recertification window (due 2027-08-01 minus sixty days).
    set_clock("2027-06-02T00:00:00Z")
    ch_headers = make_cardholder_headers(ch_id)
    first = validate_success(api.create_application(
        create_application_payload(kind="RECERTIFICATION",
                                   applicant_full_name="Dup Recert",
                                   residency_address="33 Twice Ave",
                                   cardholder_id=ch_id),
        ch_headers), 201)

    res = api.create_application(
        create_application_payload(kind="RECERTIFICATION",
                                   applicant_full_name="Dup Recert",
                                   residency_address="33 Twice Ave",
                                   cardholder_id=ch_id),
        ch_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_PENDING_APPLICATION)

    first_after = validate_success(
        api.get_application(first["id"],
                            make_program_administrator_headers("admin-1")), 200)
    assert first_after["status"] == "SUBMITTED", (
        "the first recertification application is untouched by the rejected second")
