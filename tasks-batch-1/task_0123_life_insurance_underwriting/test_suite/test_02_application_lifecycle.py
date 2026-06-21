"""Application state machine: initial state, the revision cycle back to EXAM_PENDING,
invalid transitions, terminal lockdown, idempotency, and the version counter.

Covers difficulty rule non_linear_state_machine (application cycle instance) plus the
application-side corner state_machines / entities instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_application_under_review,
    create_product, create_underwriter, create_applicant, create_draft_application,
    submit_application, attach_completed_exam, add_mib_check,
    make_underwriter_headers,
    EXAM_PREFERRED,
)


def test_application_revision_cycle_under_review_back_to_exam_pending(api):
    """PRD §3.3: "The same ordering action is also available from `UNDER_REVIEW` as a
    revision loop — when a reviewer needs fresh evidence, ordering a new exam falls the
    case back from `UNDER_REVIEW` to `EXAM_PENDING`, re-pins the ordering underwriter, and
    bumps the version."
    PRD §3.4: "A postponed case may also re-enter review, advancing `POSTPONED` to
    `UNDER_REVIEW`, which requires only that at least one `COMPLETED` exam exist on the
    application." (begin-review re-runs from EXAM_PENDING too)

    Design: Difficulty/non_linear_state_machine/application_revision_cycle_under_review_back_to_exam_pending
    """
    ctx = setup_application_under_review(exam_overrides=dict(EXAM_PREFERRED))
    app_id = ctx["application"]["id"]
    u1_h = make_underwriter_headers(ctx["u1"]["id"])
    u2_h = make_underwriter_headers(ctx["u2"]["id"])

    # version at first UNDER_REVIEW is 4 (create=1, submit=2, order-exam=3, begin-review=4).
    assert ctx["application"]["version"] == 4, ctx["application"]

    # Revision loop: u1 re-orders an exam -> falls back to EXAM_PENDING (version 5).
    reordered = validate_success(api.order_exam(app_id, u1_h))
    assert reordered["status"] == "EXAM_PENDING"
    assert reordered["version"] == 5, reordered

    # Attach a fresh non-overlapping exam and complete it. The setup exam dated
    # 2026-05-01 (exam_validity_days 180) spans [2026-05-01, 2026-10-28); a second
    # exam dated 2026-11-01 starts after that exclusive end -> no overlap.
    exam2 = validate_success(
        api.create_paramed_exam(app_id, {"height_inches": 70, "weight_pounds": 160,
                                         "systolic_bp": 120, "exam_date": "2026-11-01"}, u1_h),
        expected_status=201,
    )
    validate_success(api.complete_paramed_exam(exam2["id"], u1_h))

    # Begin review again -> back to UNDER_REVIEW with version advanced to 6.
    second_review = validate_success(api.begin_review(app_id, u2_h))
    assert second_review["status"] == "UNDER_REVIEW"
    assert second_review["version"] == 6, second_review


def test_new_application_starts_in_draft(api):
    """PRD §3.2: "A new application begins in `DRAFT`."
    PRD §3.2: "Submission computes a provisional annual premium from the facts declared so
    far and writes it to `provisional_annual_premium_cents`, which is null until this point."

    Design: Corner/state_machines/application_initial_state_is_draft
    """
    product = create_product()
    u = create_underwriter()
    _, app = create_draft_application(product["id"], u["id"])
    assert app["status"] == "DRAFT", app
    assert app["provisional_annual_premium_cents"] is None, app
    assert app["version"] == 1, app


def test_approve_from_draft_invalid_transition(api):
    """PRD §3.5: "Approval advances `UNDER_REVIEW` to `APPROVED_OFFER`."
    PRD §2.11: "then whether the requested transition is even defined from the resource's
    current state (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/approve_from_draft_invalid_transition
    """
    product = create_product()
    u = create_underwriter()
    _, app = create_draft_application(product["id"], u["id"])
    resp = api.approve_application(
        app["id"], {"expected_application_version": app["version"]},
        make_underwriter_headers(u["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_declined_application_terminal_lockdown(api):
    """PRD §3.5: "A decline is also available directly from `SUBMITTED`, advancing
    `SUBMITTED` to `DECLINED` without a segregation check"
    PRD §3.5: "`DECLINED` is terminal."

    Design: Corner/state_machines/declined_application_terminal_lockdown
    """
    product = create_product()
    u = create_underwriter()
    _, app = create_draft_application(product["id"], u["id"])
    u_h = make_underwriter_headers(u["id"])
    submit_application(app["id"], u["id"])
    declined = validate_success(api.decline_application(app["id"], u_h))
    assert declined["status"] == "DECLINED"
    # Any further transition from DECLINED is rejected.
    resp = api.begin_review(app["id"], u_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    final = validate_success(api.get_application(app["id"], u_h))
    assert final["status"] == "DECLINED", final


def test_submit_twice_second_rejected(api):
    """PRD §3.2: "Submitting the application advances it from `DRAFT` to `SUBMITTED`, but
    only while it is in `DRAFT`"
    PRD §2.11: "then whether the requested transition is even defined from the resource's
    current state (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/submit_twice_idempotency_second_rejected
    """
    product = create_product()
    u = create_underwriter()
    _, app = create_draft_application(product["id"], u["id"])
    u_h = make_underwriter_headers(u["id"])
    validate_success(api.submit_application(app["id"], u_h))
    resp = api.submit_application(app["id"], u_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_version_increments_on_every_mutation(api):
    """PRD §2.4: "a `version` integer that begins at 1 and increments by one with each
    mutation."
    PRD §3.2: "Submission also increments the application's `version`."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
    """
    product = create_product()
    u = create_underwriter()
    _, app = create_draft_application(product["id"], u["id"])
    assert app["version"] == 1, app
    submitted = validate_success(api.submit_application(app["id"], make_underwriter_headers(u["id"])))
    assert submitted["version"] == 2, submitted
