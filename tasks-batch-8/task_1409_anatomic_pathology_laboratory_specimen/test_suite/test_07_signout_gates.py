"""Sign-out readiness gates: slide/stain readiness, critical discrepancies,
open consultations, state-vs-safety precedence, and PENDING_SIGNOUT pull-back."""
from test_helpers import (
    HISTOTECH_HEADERS,
    ApiErrorId,
    accept_consultation,
    assign_case,
    create_case,
    create_consultation,
    create_discrepancy,
    create_pathologist,
    create_slide,
    get_case,
    get_discrepancy,
    get_slide,
    make_pathologist_headers,
    qc_review_slide,
    section_slide,
    setup_pending_signout_case,
    setup_qc_passed_case,
    setup_workup_case,
    sign_out_case,
    stain_complete_slide,
    submit_for_signout,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def test_case_submit_gated_on_slide_states_stained(api):
    """PRD §3.6: "Readiness is gated on every child: every slide of the case
    that is not `CANCELLED` must be `QC_PASSED`, and every stain order must be
    `RESULTED` or `CANCELLED` — a violation surfaces `ERR_SLIDES_NOT_READY`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/case_submit_gated_on_slide_states
    """
    ctx = setup_workup_case(mrn="MRN-800", num_blocks=1, slides_per_block=1)
    slide = ctx["slides"][0]
    section_slide(slide["id"], consumption_pct=10.0)
    stain_complete_slide(slide["id"])
    pathologist = create_pathologist(full_name="Dr Gate")
    assign_case(ctx["case"]["id"], pathologist["id"])
    assert get_slide(slide["id"])["status"] == "STAINED"

    resp = api.submit_for_signout(
        ctx["case"]["id"], make_pathologist_headers(pathologist["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SLIDES_NOT_READY)
    assert get_case(ctx["case"]["id"])["status"] == "WORKUP"


def test_case_submit_gated_on_slide_states_sectioned(api):
    """PRD §3.6: "Readiness is gated on every child: every slide of the case
    that is not `CANCELLED` must be `QC_PASSED`, and every stain order must be
    `RESULTED` or `CANCELLED` — a violation surfaces `ERR_SLIDES_NOT_READY`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/case_submit_gated_on_slide_states
    """
    ctx = setup_workup_case(mrn="MRN-800", num_blocks=1, slides_per_block=1)
    slide = ctx["slides"][0]
    section_slide(slide["id"], consumption_pct=10.0)
    pathologist = create_pathologist(full_name="Dr Gate")
    assign_case(ctx["case"]["id"], pathologist["id"])
    assert get_slide(slide["id"])["status"] == "SECTIONED"

    resp = api.submit_for_signout(
        ctx["case"]["id"], make_pathologist_headers(pathologist["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SLIDES_NOT_READY)
    case_after = get_case(ctx["case"]["id"])
    assert case_after["status"] == "WORKUP"
    assert get_slide(slide["id"])["status"] == "SECTIONED", "the failed submit mutates nothing"


def test_signout_state_error_beats_critical_discrepancy(api):
    """PRD §2.9: "When a single request violates several rules, the returned
    error is determined by a fixed validation priority; a rule with a lower
    priority number wins over a higher-numbered one. The broad funnel runs as
    follows: authentication of the headers (priority 1) comes before role
    authorization and entity-backed ownership checks (priority 2), which come
    before request-shape validation (priority 3), which comes before
    resource-existence checks ordered left to right across path identifiers and
    then body-referenced identifiers (priority 4), which come before the
    case-terminal guard on child mutations (priority 5). The specific state,
    safety, constraint, referential, temporal, and tissue-budget rules then
    follow in their declared order."
    PRD §3.6: "It requires `PENDING_SIGNOUT` (otherwise
    `ERR_CASE_NOT_PENDING_SIGNOUT`, HTTP 409), an
    `open_critical_discrepancy_count` of zero — meaning no discrepancy of
    severity `LEVEL_3` in `OPEN` or `ACKNOWLEDGED` status, a violation
    surfacing `ERR_UNRESOLVED_CRITICAL_DISCREPANCY` (HTTP 422)"

    Design: Difficulty/priority_pair_validation_conflict/signout_state_error_beats_critical_discrepancy_safety_error
    """
    ctx = setup_workup_case(mrn="MRN-600", num_blocks=0)
    case_id = ctx["case"]["id"]
    pathologist = create_pathologist(full_name="Dr Priority")
    assign_case(case_id, pathologist["id"])
    discrepancy = create_discrepancy(
        case_id, "LEVEL_3", "wrong-site concern"
    )
    assert discrepancy["status"] == "OPEN"

    resp = api.sign_out_case(
        case_id,
        {"diagnosis_text": "premature"},
        make_pathologist_headers(pathologist["id"]),
    )
    # Both the state rule (case not PENDING_SIGNOUT) and the safety rule
    # (open LEVEL_3) are violated; the state rule is evaluated first.
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_PENDING_SIGNOUT)
    assert get_case(case_id)["status"] == "WORKUP"
    assert get_discrepancy(discrepancy["id"])["status"] == "OPEN"


def test_signout_state_error_leaves_discrepancy_untouched(api):
    """PRD §3.6: "It requires `PENDING_SIGNOUT` (otherwise
    `ERR_CASE_NOT_PENDING_SIGNOUT`, HTTP 409)"
    PRD §3.6: "The case's `open_critical_discrepancy_count` tracks its
    `LEVEL_3` rows in `OPEN` or `ACKNOWLEDGED` and is what blocks sign-out."

    Design: Difficulty/priority_pair_validation_conflict/signout_state_error_beats_critical_discrepancy_safety_error
    """
    ctx = setup_workup_case(mrn="MRN-600", num_blocks=0)
    case_id = ctx["case"]["id"]
    pathologist = create_pathologist(full_name="Dr Priority")
    assign_case(case_id, pathologist["id"])
    discrepancy = create_discrepancy(case_id, "LEVEL_3", "wrong-site concern")

    resp = api.sign_out_case(
        case_id,
        {"diagnosis_text": "premature"},
        make_pathologist_headers(pathologist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_PENDING_SIGNOUT)
    # The failed sign-out leaves the case and the discrepancy untouched.
    assert get_discrepancy(discrepancy["id"])["status"] == "OPEN"
    case_after = get_case(case_id)
    assert case_after["status"] == "WORKUP"
    assert case_after["open_critical_discrepancy_count"] == 1


def test_signout_blocked_by_open_level3_discrepancy(api):
    """PRD §3.6: "an `open_critical_discrepancy_count` of zero — meaning no
    discrepancy of severity `LEVEL_3` in `OPEN` or `ACKNOWLEDGED` status, a
    violation surfacing `ERR_UNRESOLVED_CRITICAL_DISCREPANCY` (HTTP 422)"

    Design: Corner/validations/signout_blocked_by_open_level3_discrepancy
    """
    ctx = setup_qc_passed_case(mrn="MRN-V4")
    case_id = ctx["case"]["id"]
    assign_case(case_id, ctx["pathologist"]["id"])
    create_discrepancy(case_id, "LEVEL_3", "possible wrong patient")
    submit_for_signout(case_id, ctx["pathologist"]["id"])

    resp = api.sign_out_case(
        case_id,
        {"diagnosis_text": "x"},
        make_pathologist_headers(ctx["pathologist"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_CRITICAL_DISCREPANCY)
    assert get_case(case_id)["status"] == "PENDING_SIGNOUT"


def test_signout_blocked_by_accepted_consultation(api):
    """PRD §3.6: "and no consultation of the case still in `ACCEPTED`
    (otherwise `ERR_ACCEPTED_CONSULTATION_OPEN`, HTTP 409)."

    Design: Corner/validations/signout_blocked_by_accepted_consultation
    """
    ctx = setup_qc_passed_case(mrn="MRN-V5")
    case_id = ctx["case"]["id"]
    consultant = create_pathologist(full_name="Dr Consult")
    assign_case(case_id, ctx["pathologist"]["id"])
    consultation = create_consultation(
        case_id, ctx["pathologist"]["id"], consultant["id"], question_text="margin?"
    )
    accept_consultation(consultation["id"], consultant["id"])
    submit_for_signout(case_id, ctx["pathologist"]["id"])

    resp = api.sign_out_case(
        case_id,
        {"diagnosis_text": "x"},
        make_pathologist_headers(ctx["pathologist"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ACCEPTED_CONSULTATION_OPEN)
    assert get_case(case_id)["status"] == "PENDING_SIGNOUT"


def test_submit_from_open_and_amend_sign_without_amendment_rejected(api):
    """PRD §3.6: "Submission requires the case to be in `WORKUP` (otherwise
    `ERR_CASE_NOT_IN_WORKUP`, HTTP 409)"
    PRD §3.6: "The amender — and only the amender, with
    `ERR_CASE_NOT_AMENDING` (HTTP 409) guarding the case state — then either
    signs or abandons the draft."

    Design: Corner/errors/submit_from_open_and_amend_sign_without_amendment_rejected
    """
    ctx = setup_qc_passed_case(mrn="MRN-RA")
    p1 = ctx["pathologist"]
    # Case X: OPEN, assigned but never worked up.
    case_x = create_case(ctx["patient"]["id"], subspecialty="GI")
    assign_case(case_x["id"], p1["id"])

    resp = api.submit_for_signout(case_x["id"], make_pathologist_headers(p1["id"]))
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_IN_WORKUP)

    # Case Y: taken to FINAL; amend/sign with no open amendment is guarded by
    # the case state (a caller who is not any recorded amender may instead be
    # refused by the ownership check, so accept either documented refusal).
    case_y = ctx["case"]
    assign_case(case_y["id"], p1["id"])
    submit_for_signout(case_y["id"], p1["id"])
    sign_out_case(case_y["id"], p1["id"])
    resp = api.amend_sign(case_y["id"], make_pathologist_headers(p1["id"]))
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_CASE_NOT_AMENDING, ApiErrorId.ERR_FORBIDDEN]
    )
    assert get_case(case_y["id"])["status"] == "FINAL"


def test_amend_on_nonfinal_case_rejected(api):
    """PRD §3.6: "Opening an amendment requires the case to be `FINAL`
    (otherwise `ERR_CASE_NOT_FINAL`, HTTP 409)"

    Design: Corner/endpoints/amend_on_nonfinal_case_rejected
    """
    ctx = setup_workup_case(mrn="MRN-E3", num_blocks=0)
    p1 = create_pathologist(full_name="Dr Amend")
    resp = api.amend_case(
        ctx["case"]["id"],
        {"diagnosis_text": "x", "amendment_reason": "y"},
        make_pathologist_headers(p1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_FINAL)


def test_signout_by_non_assigned_pathologist_forbidden(api):
    """PRD §2.1: "Concretely, submitting a case for sign-out, signing it out,
    or acknowledging a discrepancy requires `X-User-ID` to equal the case's
    `assigned_pathologist_id`"
    PRD §2.1: "A request whose role is not on the endpoint's authorized list —
    or that fails an entity-backed ownership check — is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/signout_by_non_assigned_pathologist_forbidden
    """
    ctx = setup_pending_signout_case(mrn="MRN-RB2")
    other = create_pathologist(full_name="Dr Other")
    case_id = ctx["case"]["id"]

    resp = api.sign_out_case(
        case_id,
        {"diagnosis_text": "impostor"},
        make_pathologist_headers(other["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_case(case_id)["status"] == "PENDING_SIGNOUT"


def test_case_pending_signout_pullback_on_qc_fail(api):
    """PRD §3.3: "A QC failure on a case that is `PENDING_SIGNOUT` pulls the
    case back to `WORKUP` — readiness must be re-earned."
    PRD §3.3: "`FAIL` moves it to `QC_FAILED` and records the payload's
    `reason` in `qc_failure_reason`."

    Design: Corner/state_machines/case_pending_signout_pullback_on_qc_fail
    """
    ctx = setup_pending_signout_case(mrn="MRN-S3")
    case_id = ctx["case"]["id"]
    block_id = ctx["block"]["id"]
    assert get_case(case_id)["status"] == "PENDING_SIGNOUT"

    s2 = create_slide(block_id, slide_label="A1-2")
    section_slide(s2["id"], consumption_pct=5.0)
    stain_complete_slide(s2["id"])
    resp = api.qc_review_slide(s2["id"], {"result": "FAIL", "reason": "bubbles"}, HISTOTECH_HEADERS)
    failed = validate_success(resp, expected_status=200)
    assert failed["status"] == "QC_FAILED"
    assert failed["qc_failure_reason"] == "bubbles"
    assert get_case(case_id)["status"] == "WORKUP", (
        "the QC failure pulled the case back from PENDING_SIGNOUT"
    )
