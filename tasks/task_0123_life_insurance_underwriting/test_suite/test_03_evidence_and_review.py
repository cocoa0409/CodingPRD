"""Evidence gathering and review gates: begin-review evidence completeness, the
uninsurable-risk approve gate, MIB result computation, exam state transitions, and
the risk-classification input-set / boundary rules.

Covers difficulty rule cross_entity_state_dependency and boundary instance
blood_pressure_band_boundary_135, plus the related corner instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    setup_application_in_exam_pending, setup_application_under_review,
    create_product, create_underwriter, create_draft_application, submit_application,
    attach_completed_exam, add_mib_check,
    make_underwriter_headers,
    EXAM_PREFERRED, EXAM_STANDARD,
)


def test_begin_review_requires_completed_paramed_exam(api):
    """PRD §3.4: "Beginning review without both a `COMPLETED` exam and at least one MIB
    check present is rejected with `ERR_EVIDENCE_INCOMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/begin_review_requires_completed_paramed_exam_application_to_exam
    """
    ctx = setup_application_in_exam_pending()
    app_id = ctx["application"]["id"]
    u1_h = make_underwriter_headers(ctx["u1"]["id"])
    u2_h = make_underwriter_headers(ctx["u2"]["id"])
    # Exam is ORDERED (not completed). One MIBCheck exists so only the exam branch fails.
    validate_success(
        api.create_paramed_exam(app_id, {"height_inches": 70, "weight_pounds": 160,
                                         "systolic_bp": 120, "exam_date": "2026-05-01"}, u1_h),
        expected_status=201,
    )
    add_mib_check(app_id, ctx["u1"]["id"])
    resp = api.begin_review(app_id, u2_h)
    validate_error(resp, ApiErrorId.ERR_EVIDENCE_INCOMPLETE.value)
    unchanged = validate_success(api.get_application(app_id, u2_h))
    assert unchanged["status"] == "EXAM_PENDING", unchanged


def test_approve_blocked_by_flagged_mib_check(api):
    """PRD §3.5: "An assessed class of `TABLE_7` or `TABLE_8`, or the presence of any
    `FLAGGED` MIB check, blocks approval as `ERR_UNINSURABLE_RISK`"

    Design: Difficulty/cross_entity_state_dependency/approve_blocked_by_flagged_mib_check_application_to_mibcheck
    """
    # Low-risk exam but a FLAGGED MIBCheck (mib_hit=true).
    ctx = setup_application_under_review(
        exam_overrides=dict(EXAM_PREFERRED),
        mib_overrides={"mib_hit": True, "rx_flag_count": 1},
    )
    app_id = ctx["application"]["id"]
    u2_h = make_underwriter_headers(ctx["u2"]["id"])
    resp = api.approve_application(
        app_id, {"expected_application_version": ctx["review_version"]}, u2_h
    )
    validate_error(resp, ApiErrorId.ERR_UNINSURABLE_RISK.value)
    unchanged = validate_success(api.get_application(app_id, u2_h))
    assert unchanged["status"] == "UNDER_REVIEW", unchanged


def test_blood_pressure_band_boundary_135_zero_debits(api):
    """PRD §3.4: "Systolic pressure maps to its own debits, again with inclusive upper
    edges: at or below 135 contributes 0; above 135 and at or below 150 contributes 50;
    above 150 contributes 100."
    PRD §3.4: "a BMI at or below 27.5 contributes 0 debits"

    Design: Difficulty/boundary_precision_check/blood_pressure_band_boundary_135_zero_debits_on_begin_review
    """
    # h70/w160 -> BMI 22.955 (0 build); systolic_bp 135 on the inclusive lower edge -> 0.
    ctx = setup_application_under_review(
        exam_overrides={"height_inches": 70, "weight_pounds": 160, "systolic_bp": 135},
        applicant_overrides={"tobacco_use": False},
    )
    ra, _ = validate_paginated(
        api.get_risk_assessment(ctx["application"]["id"], make_underwriter_headers(ctx["u2"]["id"]))
    )
    assert ra[0]["build_debits"] == 0, ra
    assert ra[0]["total_debits"] == 0, ra
    assert ra[0]["risk_class"] == "PREFERRED", ra


def test_begin_review_missing_mib_check_evidence_incomplete(api):
    """PRD §3.4: "Once at least one exam on the application has reached `COMPLETED` and at
    least one MIB check exists, an underwriter begins review, advancing `EXAM_PENDING` to
    `UNDER_REVIEW`."
    PRD §3.4: "Beginning review without both a `COMPLETED` exam and at least one MIB check
    present is rejected with `ERR_EVIDENCE_INCOMPLETE`."

    Design: Corner/validations/begin_review_missing_mib_check_evidence_incomplete
    """
    product = create_product()
    u1 = create_underwriter(name="U1")
    u2 = create_underwriter(name="U2")
    _, app = create_draft_application(product["id"], u1["id"])
    submit_application(app["id"], u1["id"])
    attach_completed_exam(app["id"], u1["id"], dict(EXAM_PREFERRED))
    # No MIBCheck recorded -> MIB branch of the evidence requirement fails.
    resp = api.begin_review(app["id"], make_underwriter_headers(u2["id"]))
    validate_error(resp, ApiErrorId.ERR_EVIDENCE_INCOMPLETE.value)


def test_mib_result_clear_when_no_hit(api):
    """PRD §3.3: "The check's `result` is computed at creation: it is `CLEAR` when there is
    no MIB hit and the flagged-prescription count is exactly zero, and `FLAGGED` otherwise."

    Design: Corner/entities/mib_check_result_computed_clear_when_no_hit
    """
    product = create_product()
    u = create_underwriter()
    _, app = create_draft_application(product["id"], u["id"])
    data = validate_success(
        api.create_mib_check(app["id"], {"mib_hit": False, "rx_flag_count": 0},
                             make_underwriter_headers(u["id"])),
        expected_status=201,
    )
    assert data["result"] == "CLEAR", data


def test_mib_result_flagged_when_rx_flagged(api):
    """PRD §3.3: "The check's `result` is computed at creation: it is `CLEAR` when there is
    no MIB hit and the flagged-prescription count is exactly zero, and `FLAGGED` otherwise."

    Design: Corner/entities/mib_check_result_computed_flagged_when_rx_flagged
    """
    product = create_product()
    u = create_underwriter()
    _, app = create_draft_application(product["id"], u["id"])
    data = validate_success(
        api.create_mib_check(app["id"], {"mib_hit": False, "rx_flag_count": 2},
                             make_underwriter_headers(u["id"])),
        expected_status=201,
    )
    assert data["result"] == "FLAGGED", data


def test_mib_check_is_append_only_no_version(api):
    """PRD §2.4: "Two entities are append-only audit records and therefore carry only `id`
    and `created_at` — they have neither an `updated_at` field nor a `version` field: the
    `MIBCheck` and the `CashValueEntry`."

    Design: Corner/entities/mib_check_immutable_no_version_field
    """
    product = create_product()
    u = create_underwriter()
    _, app = create_draft_application(product["id"], u["id"])
    data = validate_success(
        api.create_mib_check(app["id"], {"mib_hit": False, "rx_flag_count": 0},
                             make_underwriter_headers(u["id"])),
        expected_status=201,
    )
    assert "id" in data and "created_at" in data
    assert "version" not in data, data
    assert "updated_at" not in data, data


def test_classify_risk_uses_max_created_at_completed_exam(api):
    """PRD §3.4: "Risk classification reads the single `COMPLETED` paramed exam with the
    most recent `created_at` for the application."

    Design: Corner/calculations/classify_risk_uses_max_created_at_completed_exam
    """
    product = create_product()
    u1 = create_underwriter(name="U1")
    u2 = create_underwriter(name="U2")
    _, app = create_draft_application(product["id"], u1["id"],
                                      applicant_overrides={"tobacco_use": False})
    app_id = app["id"]
    u1_h = make_underwriter_headers(u1["id"])
    submit_application(app_id, u1["id"])
    # First COMPLETED exam: build 0.
    validate_success(api.order_exam(app_id, u1_h))
    e1 = validate_success(api.create_paramed_exam(
        app_id, {"height_inches": 70, "weight_pounds": 160, "systolic_bp": 120,
                 "exam_date": "2026-01-10"}, u1_h), expected_status=201)
    validate_success(api.complete_paramed_exam(e1["id"], u1_h))
    # Later COMPLETED exam (non-overlapping date): BMI 30.129 -> 50, bp 145 -> 50 = build 100.
    e2 = validate_success(api.create_paramed_exam(
        app_id, {"height_inches": 70, "weight_pounds": 210, "systolic_bp": 145,
                 "exam_date": "2026-09-01"}, u1_h), expected_status=201)
    validate_success(api.complete_paramed_exam(e2["id"], u1_h))
    add_mib_check(app_id, u1["id"])
    validate_success(api.begin_review(app_id, make_underwriter_headers(u2["id"])))
    ra, _ = validate_paginated(api.get_risk_assessment(app_id, make_underwriter_headers(u2["id"])))
    assert ra[0]["build_debits"] == 100, ra
    assert ra[0]["risk_class"] == "TABLE_1", ra


def test_cancelled_exam_cannot_be_completed(api):
    """PRD §3.3: "Alternatively, an ordered exam may be abandoned, moving `ORDERED` to
    `CANCELLED`."
    PRD §2.11: "then whether the requested transition is even defined from the resource's
    current state (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/exam_cancel_from_ordered_then_complete_invalid
    """
    product = create_product()
    u = create_underwriter()
    _, app = create_draft_application(product["id"], u["id"])
    u_h = make_underwriter_headers(u["id"])
    submit_application(app["id"], u["id"])
    validate_success(api.order_exam(app["id"], u_h))
    exam = validate_success(api.create_paramed_exam(
        app["id"], {"height_inches": 70, "weight_pounds": 160, "systolic_bp": 120,
                    "exam_date": "2026-05-01"}, u_h), expected_status=201)
    cancelled = validate_success(api.cancel_paramed_exam(exam["id"], u_h))
    assert cancelled["status"] == "CANCELLED"
    resp = api.complete_paramed_exam(exam["id"], u_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    final = validate_success(api.get_paramed_exam(exam["id"], u_h))
    assert final["status"] == "CANCELLED", final
