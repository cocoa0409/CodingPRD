"""The singleton public file, its derived posture, public comment handling,
and the public-file gate on examination fieldwork."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_posture_invariants,
    assert_public_file,
    create_active_area,
    create_complete_public_file,
    create_open_branch,
    create_public_comment_payload,
    create_public_file,
    create_public_file_payload,
    create_scheduled_exam,
    get_public_file,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Queue B — Corner/entities
# ---------------------------------------------------------------------------

def test_public_file_creation_defaults_incomplete(api, cra_officer_headers):
    """PRD §3.6: "The file is born with `branch_list_current` and
    `aa_list_current` true, `disclosure_statement_present` false, and
    `pending_comment_count` zero — which, under the posture rule of §2.10, means
    it starts `INCOMPLETE` until the disclosure statement is placed."

    Design: Corner/entities/public_file_creation_defaults_incomplete
    """
    resp = api.create_public_file(
        create_public_file_payload(bank_name="Default Bank"), cra_officer_headers
    )
    data = validate_success(resp, 201)
    assert_public_file(data)
    assert data["branch_list_current"] is True
    assert data["aa_list_current"] is True
    assert data["disclosure_statement_present"] is False
    assert data["pending_comment_count"] == 0
    assert data["posture"] == "INCOMPLETE"


def test_public_comment_creation_defaults(api, compliance_analyst_headers):
    """PRD §3.6: "The comment starts as `RECEIVED` with `received_at` stamped
    from the logical clock".
    PRD §2.5: "At server startup, before any adjustment, the logical clock reads
    exactly `2026-08-01T00:00:00Z`, and the server must never fall back to
    wall-clock time."
    PRD §3.6: "responding moves it from `PUBLISHED` to `RESPONDED` — terminal —
    recording the bank's `response_text`."

    Design: Corner/entities/public_comment_creation_defaults
    """
    resp = api.create_public_comment(
        create_public_comment_payload(
            commenter_name="Jane Public", channel="EMAIL", subject_area="LENDING",
            content="Please lend more in our neighborhood.",
        ),
        compliance_analyst_headers,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "RECEIVED"
    assert data.get("response_text") is None
    assert data["received_at"].startswith("2026-08-01")


# ---------------------------------------------------------------------------
# Queue B — Corner/state_machines
# ---------------------------------------------------------------------------

def test_comment_lifecycle_drives_pending_count(api, cra_officer_headers):
    """PRD §2.10: "Recording a new public comment increments
    `pending_comment_count` by one, and publishing a comment decrements it by
    one. Every one of these cascades recomputes the posture immediately."
    PRD §3.6: "Publishing moves a comment from `RECEIVED` to `PUBLISHED`,
    decrementing `pending_comment_count` by one; responding moves it from
    `PUBLISHED` to `RESPONDED` — terminal — recording the bank's
    `response_text`."

    Design: Corner/state_machines/comment_lifecycle_drives_pending_count
    """
    public_file = create_complete_public_file("Comment Bank")
    assert public_file["posture"] == "COMPLETE"

    comment = validate_success(
        api.create_public_comment(
            create_public_comment_payload(
                commenter_name="Jo Public", channel="WRITTEN_LETTER",
                subject_area="SERVICE", content="More branches needed.",
            ),
            cra_officer_headers,
        ), 201,
    )
    file_after_create = get_public_file(public_file["id"])
    assert file_after_create["pending_comment_count"] == 1
    assert file_after_create["posture"] == "INCOMPLETE"
    assert_posture_invariants(file_after_create)

    validate_success(api.publish_public_comment(comment["id"], cra_officer_headers))
    file_after_publish = get_public_file(public_file["id"])
    assert file_after_publish["pending_comment_count"] == 0
    assert file_after_publish["posture"] == "COMPLETE"

    responded = validate_success(
        api.respond_public_comment(
            comment["id"], {"response_text": "We appreciate the feedback."},
            cra_officer_headers,
        )
    )
    assert responded["status"] == "RESPONDED"
    assert responded["response_text"] == "We appreciate the feedback."


# ---------------------------------------------------------------------------
# Queue B — Corner/validations
# ---------------------------------------------------------------------------

def test_second_public_file_rejected(api, cra_officer_headers):
    """PRD §3.6: "Only one may exist; a second attempt is rejected with
    `ERR_PUBLIC_FILE_EXISTS`."

    Design: Corner/validations/second_public_file_rejected
    """
    create_public_file("First Bank")
    resp = api.create_public_file(
        create_public_file_payload(bank_name="Second Bank"), cra_officer_headers
    )
    validate_error(resp, ApiErrorId.ERR_PUBLIC_FILE_EXISTS)


# ---------------------------------------------------------------------------
# Queue A — Difficulty/compensating_invariant/public_file_checklist_count_conserved
# ---------------------------------------------------------------------------

def test_public_file_checklist_count_conserved(
    api, bank_executive_headers, cra_officer_headers,
):
    """PRD §2.10: "The posture is `COMPLETE` exactly when `branch_list_current`
    and `aa_list_current` and `disclosure_statement_present` are all true and
    `pending_comment_count` is zero; otherwise it is `INCOMPLETE`."
    PRD §2.10: "Opening or closing a branch sets `branch_list_current` to
    false."
    PRD §3.6: "The refresh accepts three optional flags — `branch_list`,
    `aa_list`, and `disclosure_statement` — and only an explicit true value
    takes effect; an omitted or false flag leaves the corresponding state
    untouched. Posture is recomputed after every refresh".

    Design: Difficulty/compensating_invariant/public_file_checklist_count_conserved
    """
    area = create_active_area(
        area_code="AA-CI3F", msa_code="16980", state_code="IL", census_tracts=["T1"],
        annual_cd_budget_cents=1000000,
    )
    branch = create_open_branch(area["id"], branch_code="BR-CI", census_tract="T1",
                                tract_income_level="MIDDLE")
    public_file = create_complete_public_file("Checklist Bank")
    # Three required checklist items present, none missing: COMPLETE.
    assert public_file["posture"] == "COMPLETE"
    assert_posture_invariants(public_file)

    # Forward action: the close knocks the branch list out of currency.
    validate_success(
        api.close_branch(branch["id"], {"notice_posted_date": "2026-04-01"},
                         bank_executive_headers)
    )
    after_close = get_public_file(public_file["id"])
    assert after_close["branch_list_current"] is False
    assert after_close["posture"] == "INCOMPLETE"
    assert_posture_invariants(after_close)

    # Compensating action: refreshing the branch list restores COMPLETE.
    after_refresh = validate_success(
        api.refresh_public_file_items(
            public_file["id"], {"branch_list": True}, cra_officer_headers
        )
    )
    assert after_refresh["branch_list_current"] is True
    assert after_refresh["posture"] == "COMPLETE"
    assert_posture_invariants(after_refresh)


def test_public_file_refresh_only_true_flags_take_effect(api, cra_officer_headers):
    """PRD §3.6: "The refresh accepts three optional flags — `branch_list`,
    `aa_list`, and `disclosure_statement` — and only an explicit true value
    takes effect; an omitted or false flag leaves the corresponding state
    untouched. Posture is recomputed after every refresh".

    Design: Difficulty/compensating_invariant/public_file_checklist_count_conserved
    """
    public_file = create_public_file("Conservative Bank")
    assert public_file["disclosure_statement_present"] is False
    assert public_file["posture"] == "INCOMPLETE"

    # An explicit false leaves the disclosure flag untouched.
    after_false = validate_success(
        api.refresh_public_file_items(
            public_file["id"], {"disclosure_statement": False}, cra_officer_headers
        )
    )
    assert after_false["disclosure_statement_present"] is False
    assert after_false["posture"] == "INCOMPLETE"

    # An omitted flag likewise leaves state untouched.
    after_omitted = validate_success(
        api.refresh_public_file_items(public_file["id"], {}, cra_officer_headers)
    )
    assert after_omitted["disclosure_statement_present"] is False
    assert after_omitted["posture"] == "INCOMPLETE"

    # An explicit true places the statement and completes the posture.
    after_true = validate_success(
        api.refresh_public_file_items(
            public_file["id"], {"disclosure_statement": True}, cra_officer_headers
        )
    )
    assert after_true["disclosure_statement_present"] is True
    assert after_true["posture"] == "COMPLETE"


# ---------------------------------------------------------------------------
# Queue A — Difficulty/cross_entity_state_dependency/fieldwork_gated_by_public_file_posture
# ---------------------------------------------------------------------------

def test_fieldwork_gated_by_public_file_posture(
    api, cra_officer_headers, bank_examiner_headers,
):
    """PRD §3.7: "Beginning fieldwork moves `DATA_COLLECTION → FIELDWORK` and is
    gated on the public file: the singleton file must exist and its `posture`
    must be `COMPLETE`, otherwise the request fails with
    `ERR_PUBLIC_FILE_INCOMPLETE`".

    Design: Difficulty/cross_entity_state_dependency/fieldwork_gated_by_public_file_posture
    """
    create_active_area(area_code="AA-XD1", census_tracts=["T1"])
    public_file = create_public_file("Gate Bank")  # disclosure missing: INCOMPLETE
    exam = create_scheduled_exam(
        "2024-01-01", "2024-12-31", exam_type="INTERMEDIATE_SMALL_BANK"
    )
    validate_success(api.begin_data_collection(exam["id"], bank_examiner_headers))

    blocked = api.begin_fieldwork(exam["id"], bank_examiner_headers)
    validate_error(blocked, ApiErrorId.ERR_PUBLIC_FILE_INCOMPLETE)
    exam_state = validate_success(api.get_exam_cycle(exam["id"], bank_examiner_headers))
    assert exam_state["status"] == "DATA_COLLECTION"

    refreshed = validate_success(
        api.refresh_public_file_items(
            public_file["id"], {"disclosure_statement": True}, cra_officer_headers
        )
    )
    assert refreshed["posture"] == "COMPLETE"

    fieldwork = validate_success(api.begin_fieldwork(exam["id"], bank_examiner_headers))
    assert fieldwork["status"] == "FIELDWORK"


def test_fieldwork_rejected_when_no_public_file_exists(api, bank_examiner_headers):
    """PRD §3.7: "Beginning fieldwork moves `DATA_COLLECTION → FIELDWORK` and is
    gated on the public file: the singleton file must exist and its `posture`
    must be `COMPLETE`, otherwise the request fails with
    `ERR_PUBLIC_FILE_INCOMPLETE`".

    Design: Difficulty/cross_entity_state_dependency/fieldwork_gated_by_public_file_posture
    """
    exam = create_scheduled_exam("2024-01-01", "2024-12-31")
    validate_success(api.begin_data_collection(exam["id"], bank_examiner_headers))

    resp = api.begin_fieldwork(exam["id"], bank_examiner_headers)
    validate_error(resp, ApiErrorId.ERR_PUBLIC_FILE_INCOMPLETE)
    exam_state = validate_success(api.get_exam_cycle(exam["id"], bank_examiner_headers))
    assert exam_state["status"] == "DATA_COLLECTION"
