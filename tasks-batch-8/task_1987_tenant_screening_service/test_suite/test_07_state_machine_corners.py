"""Corner queue B tests: state-machine corners (invalid transitions, terminal lockdowns,
valid retry loops, side effects on archival, notice lifecycle, repeat-action guards)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_same_instant,
    consent_application,
    create_and_resolve_income_verification,
    create_applicant,
    create_application,
    create_guarantor_payload,
    create_income_verification_payload,
    create_jurisdiction_rule,
    deliver_report,
    evaluate_guarantor_payload,
    file_dispute_payload,
    get_application,
    get_criteria,
    get_dispute,
    get_guarantor,
    get_income_verification,
    get_report,
    list_notices,
    list_records,
    make_applicant_headers,
    make_landlord_headers,
    resolve_dispute_payload,
    resolve_income_failed_payload,
    run_record_searches,
    score_application,
    setup_landlord_with_criteria,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_success,
    verify_identity,
)

SCREENER = TEST_USERS["screener_headers"]
SCR1 = TEST_USERS["screener_1_headers"]
SCR2 = TEST_USERS["screener_2_headers"]
SCR3 = TEST_USERS["screener_3_headers"]


def test_submit_twice_returns_invalid_application_state():
    """PRD §3.3: "Submission by the owning `Landlord` moves a `DRAFT`
    application to `SUBMITTED`; from any other non-terminal state the attempt
    fails with `ERR_INVALID_APPLICATION_STATE`, and from a terminal state with
    `ERR_APPLICATION_TERMINAL`."

    Design: Corner/state_machines/submit_twice_returns_invalid_application_state
    """
    landlord, _ = setup_landlord_with_criteria()
    app, applicant = setup_submitted_application(landlord, unit_state_code="TX")
    resp = api_client.submit_application(app["id"], make_landlord_headers(landlord["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE)
    assert get_application(app["id"])["status"] == "SUBMITTED"


def test_decide_after_withdraw_returns_application_terminal():
    """PRD §2.6: "6. **Resource from-state.** The target resource must be in the state the operation requires. Terminal applications fail with `ERR_APPLICATION_TERMINAL`;"

    Design: Corner/state_machines/decide_after_withdraw_returns_application_terminal
    """
    landlord, _ = setup_landlord_with_criteria()
    applicant = create_applicant()
    app = create_application(landlord, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    consent_application(app, applicant)
    verify_identity(app)
    app = submit_application(app, landlord)
    run_record_searches(app)
    api_client.withdraw_application(app["id"], make_landlord_headers(landlord["id"]))
    resp = api_client.decide_application(app["id"], "APPROVE", make_landlord_headers(landlord["id"]))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_TERMINAL)
    app_after = get_application(app["id"])
    assert app_after["status"] == "WITHDRAWN"
    assert app_after["decision"] is None


def test_deliver_twice_returns_invalid_report_state():
    """PRD §3.6: "Delivery is what makes a report visible for decision. A `Screener` delivers a report from `DRAFT` to `DELIVERED`, allowed only while its application is `SCORED` — a report in any other state yields `ERR_INVALID_REPORT_STATE`,"

    Design: Corner/state_machines/deliver_twice_returns_invalid_report_state
    """
    landlord, _ = setup_landlord_with_criteria()
    applicant = create_applicant()
    app = create_application(landlord, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    consent_application(app, applicant)
    verify_identity(app)
    app = submit_application(app, landlord)
    report = run_record_searches(app)
    create_and_resolve_income_verification(app, 600000)
    score_application(app)
    deliver_report(report)
    resp = api_client.deliver_report(report["id"], SCREENER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REPORT_STATE)
    assert get_report(report["id"])["status"] == "DELIVERED"


def test_deny_decision_creates_notice_draft_with_derived_reasons():
    """PRD §3.6: "A denial has a compliance side effect: the system creates an **AdverseActionNotice** in `DRAFT` whose `reason_codes` are derived in pinned order — `CREDIT_SCORE_BELOW_MINIMUM` when the application's `credit_score` is below the criteria's `min_credit_score`;"

    Design: Corner/state_machines/deny_decision_creates_notice_draft_with_derived_reasons
    """
    landlord, _ = setup_landlord_with_criteria()
    applicant = create_applicant()
    app = create_application(landlord, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    consent_application(app, applicant)
    verify_identity(app)
    app = submit_application(app, landlord)
    report = run_record_searches(app, credit_score=600)
    create_and_resolve_income_verification(app, 600000)
    score_application(app)
    deliver_report(report)
    decided = api_client.decide_application(app["id"], "DENY", make_landlord_headers(landlord["id"]))
    data = validate_success(decided)
    assert data["status"] == "DENIED"
    notices = list_notices(app["id"])
    assert notices[0]["status"] == "DRAFT", "initial state of the auto-created notice"
    assert notices[0]["reason_codes"] == ["CREDIT_SCORE_BELOW_MINIMUM"], (
        "single grounded reason, pinned derivation order"
    )


def test_verify_identity_after_verified_returns_invalid_application_state():
    """PRD §3.2: "`VERIFIED` is terminal for this dimension: any further
    attempt against a verified application is rejected with
    `ERR_INVALID_APPLICATION_STATE`."

    Design: Corner/state_machines/verify_identity_after_verified_returns_invalid_application_state
    """
    from test_helpers import create_landlord
    landlord = create_landlord(name="L Idv", contact_email="lidv@x.com")
    applicant = create_applicant()
    app = create_application(landlord, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    api_client.verify_identity(app["id"], {"method": "KNOWLEDGE_BASED", "evidence_score": 85}, SCREENER)
    resp = api_client.verify_identity(app["id"], {"method": "DOCUMENT_REVIEW", "evidence_score": 90}, SCREENER)
    validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE)
    app_after = get_application(app["id"])
    assert app_after["identity_status"] == "VERIFIED"
    assert app_after["identity_attempts"] == 1


def test_failed_income_verification_retry_returns_to_pending():
    """PRD §3.5: "A failed verification is not final: retrying moves it from
    `FAILED` back to `PENDING`, clearing both the `failure_reason` and any
    `verified_monthly_income_cents` to null."

    Design: Corner/state_machines/failed_income_verification_retry_returns_to_pending
    """
    landlord, _ = setup_landlord_with_criteria()
    applicant = create_applicant()
    app = create_application(landlord, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    app = submit_application(app, landlord)
    resp = api_client.create_income_verification(app["id"], create_income_verification_payload(), SCREENER)
    iv = resp.json()["data"]
    api_client.resolve_income_verification(iv["id"], resolve_income_failed_payload(), SCREENER)
    resp = api_client.retry_income_verification(iv["id"], SCREENER)
    data = validate_success(resp)
    assert data["status"] == "PENDING"
    assert data["failure_reason"] is None, "failure data cleared"
    resp = api_client.resolve_income_verification(
        iv["id"], {"outcome": "VERIFIED", "verified_monthly_income_cents": 600000}, SCREENER
    )
    data = validate_success(resp)
    assert data["status"] == "VERIFIED"
    assert data["verified_monthly_income_cents"] == 600000


def test_evaluate_guarantor_twice_returns_invalid_guarantor_state():
    """PRD §3.5: "it requires the guarantor to be `PENDING` (otherwise `ERR_INVALID_GUARANTOR_STATE`)"

    Design: Corner/state_machines/evaluate_guarantor_twice_returns_invalid_guarantor_state
    """
    landlord, _ = setup_landlord_with_criteria(
        criteria_overrides={"guarantor_policy": "INDEPENDENT_ONLY"},
    )
    applicant = create_applicant()
    app = create_application(landlord, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    app = submit_application(app, landlord)
    resp = api_client.create_guarantor(
        app["id"], create_guarantor_payload(full_name="Gill G", stated_monthly_income_cents=900000),
        make_landlord_headers(landlord["id"]),
    )
    g = resp.json()["data"]
    api_client.evaluate_guarantor(g["id"], evaluate_guarantor_payload(900000, 760), SCREENER)
    resp = api_client.evaluate_guarantor(g["id"], evaluate_guarantor_payload(900000, 760), SCREENER)
    validate_error(resp, ApiErrorId.ERR_INVALID_GUARANTOR_STATE)
    assert get_guarantor(g["id"])["status"] == "APPROVED"


def test_archived_criteria_still_governs_pinned_applications():
    """PRD §3.1: "archiving does not disturb applications already pinned to
    the set, which continue to be evaluated against it."

    Design: Corner/state_machines/archived_criteria_still_governs_pinned_applications
    """
    landlord, criteria = setup_landlord_with_criteria()
    applicant = create_applicant()
    app = create_application(landlord, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    consent_application(app, applicant)
    verify_identity(app)
    app = submit_application(app, landlord)
    api_client.archive_criteria(criteria["id"], make_landlord_headers(landlord["id"]))
    run_record_searches(app, credit_score=700)
    create_and_resolve_income_verification(app, 600000)
    scored = score_application(app)
    assert get_criteria(criteria["id"])["status"] == "ARCHIVED"
    assert scored["criteria_id"] == criteria["id"], "pinning survives archival"
    assert scored["recommendation"] == "RECOMMEND_APPROVE", (
        "scored against the archived pinned criteria: credit 700 >= 650, no records, 600000 >= 600000"
    )


def test_rescinded_notice_records_rescinded_at():
    """PRD §3.8: "Issuing stamps `issued_at` with the clock and computes `dispute_deadline` as thirty days after issue. An `ISSUED` notice may later be rescinded, moving it to `RESCINDED` and stamping `rescinded_at`"

    Design: Corner/state_machines/rescinded_notice_records_rescinded_at
    """
    landlord, _ = setup_landlord_with_criteria()
    applicant = create_applicant()
    app = create_application(landlord, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    consent_application(app, applicant)
    verify_identity(app)
    app = submit_application(app, landlord)
    report = run_record_searches(app, credit_score=600)
    create_and_resolve_income_verification(app, 600000)
    score_application(app)
    deliver_report(report)
    api_client.decide_application(app["id"], "DENY", make_landlord_headers(landlord["id"]))
    notice = list_notices(app["id"])[0]
    resp = api_client.issue_notice(notice["id"], make_landlord_headers(landlord["id"]))
    issued = validate_success(resp)
    assert_same_instant(issued["issued_at"], "2026-08-01T00:00:00Z", "issued_at")
    assert_same_instant(issued["dispute_deadline"], "2026-08-31T00:00:00Z",
                        "dispute_deadline = issued_at + 30 days")
    resp = api_client.rescind_notice(notice["id"], make_landlord_headers(landlord["id"]))
    rescinded = validate_success(resp)
    assert rescinded["status"] == "RESCINDED"
    assert_same_instant(rescinded["rescinded_at"], "2026-08-01T00:00:00Z", "rescinded_at")
    notice_after = list_notices(app["id"])[0]
    assert_same_instant(notice_after["issued_at"], "2026-08-01T00:00:00Z",
                        "issued_at preserved")


def test_repeat_actions_return_invalid_state_errors():
    """PRD §2.6: "other wrong states fail with the resource's own state error
    (`ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_CRITERIA_STATE`,
    `ERR_INVALID_REPORT_STATE`, `ERR_INVALID_DISPUTE_STATE`,
    `ERR_INVALID_INCOME_VERIFICATION_STATE`, `ERR_INVALID_GUARANTOR_STATE`,
    or `ERR_INVALID_NOTICE_STATE`), all HTTP 409."

    Design: Corner/state_machines/repeat_actions_return_invalid_state_errors
    """
    create_jurisdiction_rule(
        state_code="CA", criminal_lookback_years=7, eviction_lookback_years=7,
        portable_report_acceptance_required=True,
    )
    landlord, _ = setup_landlord_with_criteria()
    applicant = create_applicant(residence_state="CA")
    app = create_application(landlord, applicant, unit_state_code="CA",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    consent_application(app, applicant)
    verify_identity(app)
    app = submit_application(app, landlord)
    report = run_record_searches(app, credit_score=700, records=[
        {"record_type": "EVICTION", "jurisdiction_state_code": "CA",
         "record_date": "2024-03-01T00:00:00Z", "description": "eviction filing"},
    ], screener_headers=SCR1)
    recs = list_records(report["id"])
    resp = api_client.create_income_verification(app["id"], create_income_verification_payload(), SCREENER)
    iv = resp.json()["data"]
    api_client.resolve_income_verification(
        iv["id"], {"outcome": "VERIFIED", "verified_monthly_income_cents": 600000}, SCREENER
    )
    score_application(app)
    deliver_report(report)
    api_client.decide_application(app["id"], "DENY", make_landlord_headers(landlord["id"]))
    notice = list_notices(app["id"])[0]
    api_client.issue_notice(notice["id"], make_landlord_headers(landlord["id"]))
    resp = api_client.file_dispute(
        report["id"], file_dispute_payload([recs[0]["id"]], "record is inaccurate"),
        make_applicant_headers(applicant["id"]),
    )
    dispute = resp.json()["data"]
    api_client.start_reinvestigation(dispute["id"], SCR2)
    # Repeat each action.
    resp1 = api_client.start_reinvestigation(dispute["id"], SCR3)
    validate_error(resp1, ApiErrorId.ERR_INVALID_DISPUTE_STATE)
    resp2 = api_client.issue_notice(notice["id"], make_landlord_headers(landlord["id"]))
    validate_error(resp2, ApiErrorId.ERR_INVALID_NOTICE_STATE)
    resp3 = api_client.resolve_income_verification(
        iv["id"], {"outcome": "VERIFIED", "verified_monthly_income_cents": 600000}, SCREENER
    )
    validate_error(resp3, ApiErrorId.ERR_INVALID_INCOME_VERIFICATION_STATE)
