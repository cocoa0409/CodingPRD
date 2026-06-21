"""Application initial state, withdraw, hire-blocked/permitted by overall_result,
salary-history-ban, ban-the-box gate.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_application_payload,
    set_clock, create_jurisdiction, create_applicant, create_application,
    application_in_submitted, application_in_conditional_offer,
    order_complete_with_results,
    make_applicant_headers, make_recruiter_headers, PA, REC,
)


def test_new_application_starts_in_draft(api):
    """POST /applications inserts the Application with status=DRAFT.

    PRD §3.1: "With an applicant in hand, an `Application` is opened by
    supplying `applicant_id`, `jurisdiction_id`, and a `position_title` for
    the role being applied to. The application begins in `DRAFT`."

    Design: Corner/state_machines/application_initial_state_is_draft
    """
    set_clock("2026-06-01T10:00:00.000Z")
    jur = create_jurisdiction(state_code="AK")
    applicant = create_applicant(full_name="Ada Yonath", email="yonath@example.com",
                                 date_of_birth="1939-06-22T00:00:00.000Z")
    resp = api.create_application(
        create_application_payload(
            applicant_id=applicant["id"], jurisdiction_id=jur["id"],
            position_title="Engineer",
        ),
        make_applicant_headers(applicant["id"]),
    )
    app = validate_success(resp, 201)
    assert app["status"] == "DRAFT", f"new application must be DRAFT, got {app['status']!r}"


def test_withdraw_from_submitted_reaches_terminal_withdrawn(api):
    """An applicant may withdraw a SUBMITTED application; the resulting
    status is WITHDRAWN, a terminal state.

    PRD §3.2: "An applicant may withdraw the application from either `DRAFT`
    or `SUBMITTED` by submitting the withdraw call with
    `expected_application_version`; on success the application advances to
    `WITHDRAWN`, a terminal state."

    Design: Corner/state_machines/withdraw_from_submitted_succeeds_to_terminal
    """
    jur, applicant, app, consent = application_in_submitted(state_code="DE")
    resp = api.withdraw_application(
        app["id"],
        {"expected_application_version": app["version"]},
        make_applicant_headers(applicant["id"]),
    )
    out = validate_success(resp, 200)
    assert out["status"] == "WITHDRAWN", \
        f"withdraw from SUBMITTED must yield WITHDRAWN, got {out['status']!r}"


def test_hire_from_conditional_offer_with_clear_succeeds(api):
    """When the order is COMPLETE with overall_result=CLEAR, the recruiter
    may hire the applicant; the application advances to HIRED.

    PRD §3.7: "Once a background-check order has settled into `COMPLETE`
    with `overall_result` `CLEAR`, the recruiter may hire the applicant.
    The hire call carries `expected_application_version`; on success the
    application advances from `CONDITIONAL_OFFER` to `HIRED`."

    Design: Corner/state_machines/hire_from_conditional_offer_with_clear_succeeds
    """
    (jur, applicant, app, consent, order, crim, mvr, edu) = (
        order_complete_with_results(
            crim_result="PASS", mvr_result="PASS", edu_result="PASS",
            state_code="ME",
        )
    )
    # The order create bumped app.version once; we need the current app version.
    app_now = validate_success(api.get_application(app["id"], make_applicant_headers(applicant["id"])), 200)
    resp = api.hire_application(
        app["id"],
        {"expected_application_version": app_now["version"]},
        make_recruiter_headers("rec-001"),
    )
    out = validate_success(resp, 200)
    assert out["status"] == "HIRED", \
        f"hire on COMPLETE+CLEAR must yield HIRED, got {out['status']!r}"


def test_hire_when_overall_result_is_consider_rejected_with_invalid_state(api):
    """When overall_result is CONSIDER (any FAIL), hire is rejected with
    ERR_INVALID_STATE — the precondition "overall_result == CLEAR" is unmet.

    PRD §3.7: "An attempt to hire when the order is not yet `COMPLETE` or
    when `overall_result` is not `CLEAR` is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/hire_from_conditional_offer_with_consider_blocked_by_invalid_state
    """
    (jur, applicant, app, consent, order, crim, mvr, edu) = (
        order_complete_with_results(
            crim_result="FAIL", mvr_result="PASS", edu_result="PASS",
            state_code="NH",
        )
    )
    app_now = validate_success(api.get_application(app["id"], make_applicant_headers(applicant["id"])), 200)
    resp = api.hire_application(
        app["id"],
        {"expected_application_version": app_now["version"]},
        make_recruiter_headers("rec-001"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_submit_in_salary_ban_jurisdiction_with_disclosed_salary_rejected(api):
    """A salary-ban jurisdiction with salary_history_disclosed set on the
    Application at submission time is rejected with
    ERR_SALARY_HISTORY_DISCLOSED_BANNED.

    PRD §3.2: "in a jurisdiction with `salary_history_ban_enabled` set to
    true, the application's `salary_history_disclosed` must be null at
    submission, otherwise the submit is rejected with
    `ERR_SALARY_HISTORY_DISCLOSED_BANNED`."

    Design: Corner/validations/error_salary_history_disclosed_in_ban_jurisdiction_blocks_submit
    """
    set_clock("2026-06-01T10:00:00.000Z")
    jur = create_jurisdiction(state_code="CA", salary_history_ban_enabled=True)
    applicant = create_applicant(full_name="Maria Mayer", email="mayer@example.com",
                                 date_of_birth="1906-06-28T00:00:00.000Z")
    app = create_application(applicant["id"], jur["id"], position_title="Scientist",
                             salary_history_disclosed=95000)
    # Grant a consent so we get past the "needs GRANTED consent" precondition.
    consent_resp = api.create_consent(
        {"application_id": app["id"], "disclosure_text_version": "v2024-01",
         "signed_at": "2026-06-01T10:00:00.000Z", "ip_address": "1.2.3.4"},
        make_applicant_headers(applicant["id"]),
    )
    consent = validate_success(consent_resp, 201)
    api.grant_consent(consent["id"],
                      {"expected_consent_disclosure_version": consent["version"]},
                      make_applicant_headers(applicant["id"]))
    # Now submit — salary_history_disclosed is set + jurisdiction has ban → reject.
    resp = api.submit_application(
        app["id"],
        {"expected_application_version": app["version"]},
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SALARY_HISTORY_DISCLOSED_BANNED.value)


def test_order_create_premature_in_btb_jurisdiction_then_succeeds_after_offer(api):
    """In a ban-the-box jurisdiction, POST /background-check-orders is
    rejected with ERR_BAN_THE_BOX_PREMATURE_INQUIRY while the Application
    is SUBMITTED. After the conditional offer is extended, the same POST
    succeeds.

    PRD §3.3: "In a jurisdiction with `ban_the_box_enabled` set to true,
    the parent application's `status` must be `CONDITIONAL_OFFER` —
    `SUBMITTED` is not enough. An attempt against a `SUBMITTED` application
    in such a jurisdiction is rejected with
    `ERR_BAN_THE_BOX_PREMATURE_INQUIRY`."

    Design: Difficulty/cross_entity_state_dependency/order_create_requires_application_conditional_offer_in_btb_jurisdiction
    """
    jur, applicant, app, consent = application_in_submitted(
        state_code="CA", ban_the_box_enabled=True,
    )
    # First attempt — Application is SUBMITTED in BTB jurisdiction → premature.
    early = api.create_order(
        {"application_id": app["id"], "consent_id": consent["id"],
         "expected_application_version": app["version"]},
        make_recruiter_headers("rec-ivy"),
    )
    validate_error(early, ApiErrorId.ERR_BAN_THE_BOX_PREMATURE_INQUIRY.value)
    # Extend conditional offer, then retry — succeeds.
    offer = api.conditional_offer(
        app["id"], {"expected_application_version": app["version"]},
        make_recruiter_headers("rec-ivy"),
    )
    app_v2 = validate_success(offer, 200)["version"]
    resp = api.create_order(
        {"application_id": app["id"], "consent_id": consent["id"],
         "expected_application_version": app_v2},
        make_recruiter_headers("rec-ivy"),
    )
    order = validate_success(resp, 201)
    assert order["status"] == "PENDING", \
        f"new order must be PENDING, got {order['status']!r}"


def test_order_create_with_non_existent_application_returns_not_found(api):
    """A POST /background-check-orders where application_id does not resolve
    is rejected at validation step 4 (existence) before the consent-status
    check (step 7 business-referential) could fire — even though the
    referenced consent is also PENDING, ERR_NOT_FOUND wins.

    PRD §2.9: "Then every id referenced in the URL path and every foreign
    key in the body must resolve (otherwise `ERR_NOT_FOUND`)."
    PRD §2.9: "Then the business-safety, business-temporal, business-referential,
    and business-constraint rules of §3 apply in the order listed in §3."

    Design: Difficulty/priority_pair_validation_conflict/not_found_application_beats_consent_not_granted_check
    """
    from test_helpers import NON_EXISTENT_UUID
    set_clock("2026-06-01T10:00:00.000Z")
    jur = create_jurisdiction(state_code="MN")
    applicant = create_applicant(full_name="Tim Berners-Lee", email="tim@example.com",
                                 date_of_birth="1955-06-08T00:00:00.000Z")
    real_app = create_application(applicant["id"], jur["id"], position_title="Engineer")
    consent_resp = api.create_consent(
        {"application_id": real_app["id"], "disclosure_text_version": "v2024-01",
         "signed_at": "2026-06-01T10:00:00.000Z", "ip_address": "1.2.3.4"},
        make_applicant_headers(applicant["id"]),
    )
    pending_consent = validate_success(consent_resp, 201)
    # PENDING consent + non-existent application_id → existence wins.
    resp = api.create_order(
        {"application_id": NON_EXISTENT_UUID,
         "consent_id": pending_consent["id"],
         "expected_application_version": real_app["version"]},
        make_recruiter_headers("rec-gail"),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_resubmit_already_submitted_application_returns_invalid_state(api):
    """A second POST /applications/{id}/submit on an Application whose
    status is already SUBMITTED is rejected with ERR_INVALID_STATE — the
    state precondition fires before any §3 business-safety rule.

    PRD §2.9: "Then the target entity must be in a state from which the
    requested transition is legal (otherwise `ERR_INVALID_STATE`).
    Then, on the two writes guarded by §2.6, the `expected_*_version`
    value must equal the current parent `version` (otherwise
    `ERR_STALE_VERSION`). Then the business-safety, business-temporal,
    business-referential, and business-constraint rules of §3 apply in
    the order listed in §3."

    Design: Difficulty/priority_pair_validation_conflict/submit_in_wrong_state_beats_salary_history_ban_check
    """
    # CA has salary_history_ban_enabled=true, so a salary-ban precondition
    # is also live; the state precondition still wins per §2.9 ordering.
    jur, applicant, app, consent = application_in_submitted(
        state_code="CA", ban_the_box_enabled=True, salary_history_ban_enabled=True,
    )
    # Second submit — app is already SUBMITTED.
    resp = api.submit_application(
        app["id"],
        {"expected_application_version": app["version"]},
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
