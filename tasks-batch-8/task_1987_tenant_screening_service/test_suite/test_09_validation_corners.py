"""Corner queue B tests: validation corners (ownership, OCC-before-overlap, consent-first,
identity gates, SoD, reinvestigator, grounding, portable rules, dispute windows, SLA,
structural constraints)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    consent_application,
    create_and_resolve_income_verification,
    create_applicant,
    create_application,
    create_criteria_payload,
    create_income_verification_payload,
    create_jurisdiction_rule,
    create_landlord,
    deliver_report,
    file_dispute_payload,
    get_application,
    get_criteria,
    get_dispute,
    get_income_verification,
    get_landlord,
    get_record,
    get_report,
    list_notices,
    list_records,
    make_applicant_headers,
    make_landlord_headers,
    resolve_dispute_payload,
    run_record_searches,
    score_application,
    set_clock,
    setup_landlord_with_criteria,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_success,
    verify_identity,
)

ADMIN = TEST_USERS["admin_headers"]
SCREENER = TEST_USERS["screener_headers"]
SCR1 = TEST_USERS["screener_1_headers"]
SCR2 = TEST_USERS["screener_2_headers"]
SCR3 = TEST_USERS["screener_3_headers"]


def test_landlord_cannot_touch_other_landlords_application():
    """PRD §2.1: "When `X-User-Role` is `Landlord`, `X-User-ID` is the `id`
    of the acting Landlord record; ownership checks on any resource that
    references a landlord — criteria sets, applications, guarantors, adverse
    action notices — compare the resource's `landlord_id` field to
    `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH`."

    Design: Corner/validations/landlord_cannot_touch_other_landlords_application
    """
    landlord1, _ = setup_landlord_with_criteria()
    applicant = create_applicant()
    app = create_application(landlord1, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    landlord2 = create_landlord(name="L Own2", contact_email="lo2@x.com")
    resp1 = api_client.get_application(app["id"], make_landlord_headers(landlord2["id"]))
    validate_error(resp1, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    resp2 = api_client.submit_application(app["id"], make_landlord_headers(landlord2["id"]))
    validate_error(resp2, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    assert get_application(app["id"])["status"] == "DRAFT"


def test_stale_version_check_precedes_window_overlap():
    """PRD §2.6: "5. **Optimistic concurrency.** Where §2.8 applies, the
    carried version must match the parent's current `version`, failing with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.8: "if `expected_landlord_version` does not match the landlord's
    current `version`, the publish is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/validations/stale_version_check_precedes_window_overlap
    """
    set_clock()
    landlord = create_landlord(name="L Occ", contact_email="locc@x.com")
    ll_headers = make_landlord_headers(landlord["id"])
    c1 = api_client.create_criteria(
        create_criteria_payload(name="C1", effective_from="2026-01-01T00:00:00Z",
                                effective_to="2026-06-30T00:00:00Z"),
        ll_headers,
    ).json()["data"]
    api_client.publish_criteria(c1["id"], {"expected_landlord_version": landlord["version"]}, ll_headers)
    c2 = api_client.create_criteria(
        create_criteria_payload(name="C2", min_credit_score=700, income_multiplier=3.5,
                                guarantor_policy="INDEPENDENT_ONLY", accepts_portable_reports=False,
                                effective_from="2026-06-15T00:00:00Z",
                                effective_to="2026-12-31T00:00:00Z"),
        ll_headers,
    ).json()["data"]
    resp = api_client.publish_criteria(
        c2["id"], {"expected_landlord_version": landlord["version"]}, ll_headers
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_criteria(c2["id"])["status"] == "DRAFT"


def test_missing_consent_blocks_record_search_before_identity_check():
    """PRD §3.4: "then the two compliance gates — consent first, so a null
    `consent_signed_at` is rejected with `ERR_CONSENT_REQUIRED`, and only
    then identity, so an `identity_status` short of `VERIFIED` is rejected
    with `ERR_IDENTITY_NOT_VERIFIED`."

    Design: Corner/validations/missing_consent_blocks_record_search_before_identity_check
    """
    landlord, _ = setup_landlord_with_criteria()
    applicant = create_applicant()
    app = create_application(landlord, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    app = submit_application(app, landlord)
    resp = api_client.record_searches(app["id"], {"credit_score": 700, "records": []}, SCREENER)
    validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED)
    assert get_application(app["id"])["status"] == "SUBMITTED"
    from test_helpers import get_success_data
    reports = get_success_data(api_client.list_reports(ADMIN, params={"application_id": app["id"]}))
    assert reports == [], "no ScreeningReport is created"


def test_unverified_identity_blocks_record_search():
    """PRD §3.4: "an `identity_status` short of `VERIFIED` is rejected with
    `ERR_IDENTITY_NOT_VERIFIED`."

    Design: Corner/validations/unverified_identity_blocks_record_search
    """
    landlord, _ = setup_landlord_with_criteria()
    applicant = create_applicant()
    app = create_application(landlord, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    consent_application(app, applicant)
    app = submit_application(app, landlord)
    resp = api_client.record_searches(app["id"], {"credit_score": 700, "records": []}, SCREENER)
    validate_error(resp, ApiErrorId.ERR_IDENTITY_NOT_VERIFIED)
    assert get_application(app["id"])["status"] == "SUBMITTED"


def test_identity_attempts_exhausted_after_three_failures():
    """PRD §3.2: "Once `identity_attempts` has reached three, further
    attempts are rejected with `ERR_IDENTITY_ATTEMPTS_EXHAUSTED` before the
    evidence is even scored."

    Design: Corner/validations/identity_attempts_exhausted_after_three_failures
    """
    landlord = create_landlord(name="L Att", contact_email="latt@x.com")
    applicant = create_applicant()
    app = create_application(landlord, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    for _ in range(3):
        api_client.verify_identity(app["id"], {"method": "KNOWLEDGE_BASED", "evidence_score": 40}, SCREENER)
    resp = api_client.verify_identity(app["id"], {"method": "KNOWLEDGE_BASED", "evidence_score": 40}, SCREENER)
    validate_error(resp, ApiErrorId.ERR_IDENTITY_ATTEMPTS_EXHAUSTED)
    app_after = get_application(app["id"])
    assert app_after["identity_attempts"] == 3, "fourth attempt not consumed"
    assert app_after["identity_status"] == "FAILED"


def _setup_dispute_filed():
    """Full flow to a DELIVERED CA report with one INCLUDED eviction record
    (originated by scr-1) and a FILED dispute by the applicant."""
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
         "record_date": "2024-03-01T00:00:00Z", "description": "eviction"},
    ], screener_headers=SCR1)
    recs = list_records(report["id"])
    create_and_resolve_income_verification(app, 600000)
    score_application(app)
    deliver_report(report)
    resp = api_client.file_dispute(
        report["id"], file_dispute_payload([recs[0]["id"]], "not mine"),
        make_applicant_headers(applicant["id"]),
    )
    dispute = resp.json()["data"]
    return landlord, applicant, app, report, recs, dispute


def test_originator_cannot_reinvestigate_own_report():
    """PRD §3.9: "the reinvestigating screener's `X-User-ID` must differ
    from the report's `originating_screener_id`, and a match is rejected
    with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/originator_cannot_reinvestigate_own_report
    """
    _, _, _, _, _, dispute = _setup_dispute_filed()
    resp = api_client.start_reinvestigation(dispute["id"], SCR1)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    resp = api_client.start_reinvestigation(dispute["id"], SCR2)
    data = validate_success(resp)
    assert data["status"] == "UNDER_REINVESTIGATION"
    assert data["reinvestigator_screener_id"] == "scr-2"


def test_non_reinvestigator_cannot_resolve_dispute():
    """PRD §3.9: "only the recorded reinvestigator may resolve — any other
    screener is rejected with `ERR_NOT_REINVESTIGATOR`."

    Design: Corner/validations/non_reinvestigator_cannot_resolve_dispute
    """
    _, _, _, _, _, dispute = _setup_dispute_filed()
    api_client.start_reinvestigation(dispute["id"], SCR2)
    resp = api_client.resolve_dispute(
        dispute["id"], resolve_dispute_payload("UPHELD", "third-party attempt"), SCR3
    )
    validate_error(resp, ApiErrorId.ERR_NOT_REINVESTIGATOR)
    assert get_dispute(dispute["id"])["status"] == "UNDER_REINVESTIGATION"


def test_issue_notice_with_ungrounded_reason_rejected():
    """PRD §3.8: "The effective `reason_codes` are the request's override when one is provided, and the codes derived at decision time otherwise; in both cases the list must be non-empty and every code must be grounded in the application's current data."
    PRD §3.8: "An empty or ungrounded list is rejected with `ERR_UNGROUNDED_ADVERSE_REASON`."

    Design: Corner/validations/issue_notice_with_ungrounded_reason_rejected
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
    resp = api_client.issue_notice(notice["id"], make_landlord_headers(landlord["id"]),
                                   reason_codes=["EVICTION_RECORD"])
    validate_error(resp, ApiErrorId.ERR_UNGROUNDED_ADVERSE_REASON)
    resp = api_client.issue_notice(notice["id"], make_landlord_headers(landlord["id"]))
    assert validate_success(resp)["status"] == "ISSUED"


def _setup_portable_report_origin():
    """apX's app1 fully delivered under a CA rule that mandates portable
    acceptance; returns (landlord, applicant, report1)."""
    create_jurisdiction_rule(
        state_code="CA", criminal_lookback_years=7, eviction_lookback_years=7,
        portable_report_acceptance_required=True,
    )
    landlord, _ = setup_landlord_with_criteria()
    applicant = create_applicant(full_name="Ann X", email="ax@x.com", residence_state="CA")
    app1 = create_application(landlord, applicant, unit_state_code="CA",
                              monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    consent_application(app1, applicant)
    verify_identity(app1)
    app1 = submit_application(app1, landlord)
    report1 = run_record_searches(app1, credit_score=700)
    create_and_resolve_income_verification(app1, 600000)
    score_application(app1)
    deliver_report(report1)
    return landlord, applicant, report1


def test_jurisdiction_portable_mandate_overrides_criteria_refusal():
    """PRD §3.3: "portable acceptance must hold, meaning either the
    jurisdiction rule covering `unit_state_code` mandates
    `portable_report_acceptance_required` or the pinned criteria's
    `accepts_portable_reports` is true, otherwise
    `ERR_PORTABLE_REPORT_NOT_ACCEPTED`."

    Design: Corner/validations/jurisdiction_portable_mandate_overrides_criteria_refusal
    """
    set_clock()
    create_jurisdiction_rule(
        state_code="CA", criminal_lookback_years=7, eviction_lookback_years=7,
        portable_report_acceptance_required=True,
    )
    # Landlord B with portable-refusing criteria; origin app1 produced rp1.
    landlord_b = create_landlord(name="L B", contact_email="lb@x.com")
    from test_helpers import create_published_criteria, get_landlord as _gl
    criteria_b = create_published_criteria(landlord_b, name="CR-REF",
                                           disclosure_summary="No portables accepted here",
                                           accepts_portable_reports=False)
    landlord_b = _gl(landlord_b["id"])
    ap_x = create_applicant(full_name="Ann X", email="ax@x.com", residence_state="CA")
    app1 = create_application(landlord_b, ap_x, unit_state_code="CA",
                              monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    consent_application(app1, ap_x)
    verify_identity(app1)
    app1 = submit_application(app1, landlord_b)
    report1 = run_record_searches(app1, credit_score=700)
    create_and_resolve_income_verification(app1, 600000)
    score_application(app1)
    deliver_report(report1)
    # app2 under the CA mandate succeeds despite the criteria refusal.
    app2 = create_application(landlord_b, ap_x, unit_state_code="CA",
                              monthly_rent_cents=190000, stated_monthly_income_cents=600000,
                              portable_report_id=report1["id"])
    resp = api_client.submit_application(app2["id"], make_landlord_headers(landlord_b["id"]))
    data = validate_success(resp)
    assert data["status"] == "SUBMITTED"
    assert data["fee_charged_cents"] == 1000, "flat portable fee"
    # Landlord C (TX, no mandate) with a portable-refusing criteria is rejected.
    landlord_c = create_landlord(name="L C", contact_email="lc@x.com")
    create_published_criteria(landlord_c, name="CR-REF2",
                              disclosure_summary="No portables accepted here either",
                              accepts_portable_reports=False)
    landlord_c = _gl(landlord_c["id"])
    app3 = create_application(landlord_c, ap_x, unit_state_code="TX",
                              monthly_rent_cents=190000, stated_monthly_income_cents=600000,
                              portable_report_id=report1["id"])
    resp = api_client.submit_application(app3["id"], make_landlord_headers(landlord_c["id"]))
    validate_error(resp, ApiErrorId.ERR_PORTABLE_REPORT_NOT_ACCEPTED)
    assert get_application(app3["id"])["status"] == "DRAFT"


def test_portable_report_older_than_30_days_rejected():
    """PRD §3.3: "the submission clock must be no later than the source
    report's `last_delivered_at` plus thirty days — the comparison is
    inclusive, so a submission landing exactly on the thirtieth day is
    accepted — and a report older than that is rejected with
    `ERR_PORTABLE_REPORT_EXPIRED`."

    Design: Corner/validations/portable_report_older_than_30_days_rejected
    """
    landlord, applicant, report1 = _setup_portable_report_origin()
    set_clock("2026-09-01T00:00:00Z")
    app2 = create_application(landlord, applicant, unit_state_code="CA",
                              monthly_rent_cents=190000, stated_monthly_income_cents=600000,
                              portable_report_id=report1["id"])
    resp = api_client.submit_application(app2["id"], make_landlord_headers(landlord["id"]))
    validate_error(resp, ApiErrorId.ERR_PORTABLE_REPORT_EXPIRED)
    assert get_application(app2["id"])["status"] == "DRAFT"


def test_portable_report_exactly_30_days_old_accepted():
    """PRD §3.3: "the comparison is inclusive, so a submission landing exactly on the thirtieth day is accepted"

    Design: Corner/validations/portable_report_exactly_30_days_old_accepted
    """
    landlord, applicant, report1 = _setup_portable_report_origin()
    set_clock("2026-08-31T00:00:00Z")
    app2 = create_application(landlord, applicant, unit_state_code="CA",
                              monthly_rent_cents=190000, stated_monthly_income_cents=600000,
                              portable_report_id=report1["id"])
    resp = api_client.submit_application(app2["id"], make_landlord_headers(landlord["id"]))
    data = validate_success(resp)
    assert data["status"] == "SUBMITTED", "day-30 boundary accepted, inclusive"
    assert data["fee_charged_cents"] == 1000, "flat portable fee"


def test_dispute_referencing_foreign_record_rejected():
    """PRD §3.8: "The filing names the challenged records as
    `disputed_record_ids` and a free-text `reason_text`; every id in the
    list must belong to this report, or the filing fails with
    `ERR_RECORD_NOT_ON_REPORT`."

    Design: Corner/validations/dispute_referencing_foreign_record_rejected
    """
    create_jurisdiction_rule(
        state_code="CA", criminal_lookback_years=7, eviction_lookback_years=7,
        portable_report_acceptance_required=True,
    )
    landlord, _ = setup_landlord_with_criteria()

    def _delivered(name, email, ssn, rec_date):
        ap = create_applicant(full_name=name, email=email, ssn_last4=ssn, residence_state="CA")
        app = create_application(landlord, ap, unit_state_code="CA",
                                 monthly_rent_cents=200000, stated_monthly_income_cents=600000)
        consent_application(app, ap)
        verify_identity(app)
        app = submit_application(app, landlord)
        report = run_record_searches(app, credit_score=700, records=[
            {"record_type": "EVICTION", "jurisdiction_state_code": "CA",
             "record_date": rec_date, "description": "eviction"},
        ])
        rec = list_records(report["id"])[0]
        create_and_resolve_income_verification(app, 600000)
        score_application(app)
        deliver_report(report)
        return ap, report, rec

    ap1, rp1, r1 = _delivered("Ann One", "a1@x.com", "0001", "2024-03-01T00:00:00Z")
    _, _, r2 = _delivered("Bob Two", "b2@x.com", "0002", "2024-05-01T00:00:00Z")
    resp = api_client.file_dispute(
        rp1["id"], file_dispute_payload([r2["id"]], "timely but references a foreign record"),
        make_applicant_headers(ap1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RECORD_NOT_ON_REPORT)
    assert get_report(rp1["id"])["status"] == "DELIVERED"
    assert get_record(r1["id"])["status"] == "INCLUDED"


def test_resolve_after_reinvestigation_deadline_rejected():
    """PRD §3.9: "The clock must be at or before the
    `reinvestigation_deadline`; exactly at the deadline is allowed, while a
    later resolution is rejected with `ERR_REINVESTIGATION_OVERDUE`."

    Design: Corner/validations/resolve_after_reinvestigation_deadline_rejected
    """
    _, _, _, _, _, dispute = _setup_dispute_filed()
    api_client.start_reinvestigation(dispute["id"], SCR2)
    set_clock("2026-09-15T00:00:00Z")
    resp = api_client.resolve_dispute(dispute["id"], resolve_dispute_payload("UPHELD", "too late"), SCR2)
    validate_error(resp, ApiErrorId.ERR_REINVESTIGATION_OVERDUE)
    dispute_after = get_dispute(dispute["id"])
    assert dispute_after["status"] == "UNDER_REINVESTIGATION"
    assert dispute_after["resolved_at"] is None


def test_submit_without_published_criteria_window_rejected():
    """PRD §3.3: "exactly one `PUBLISHED` criteria set of this landlord must have a closed effective window containing the submission clock, otherwise `ERR_NO_PUBLISHED_CRITERIA`;"

    Design: Corner/validations/submit_without_published_criteria_window_rejected
    """
    set_clock()
    landlord = create_landlord(name="L Noc", contact_email="lnoc@x.com")
    applicant = create_applicant()
    app = create_application(landlord, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    resp = api_client.submit_application(app["id"], make_landlord_headers(landlord["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_PUBLISHED_CRITERIA)
    app_after = get_application(app["id"])
    assert app_after["status"] == "DRAFT"
    assert app_after["criteria_id"] is None


def test_duplicate_income_verification_rejected():
    """PRD §3.5: "At most one income verification may exist per application — a second attempt to start one fails with `ERR_INCOME_VERIFICATION_EXISTS`"

    Design: Corner/validations/duplicate_income_verification_rejected
    """
    landlord, _ = setup_landlord_with_criteria()
    applicant = create_applicant()
    app = create_application(landlord, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    app = submit_application(app, landlord)
    api_client.create_income_verification(app["id"], create_income_verification_payload(), SCREENER)
    resp = api_client.create_income_verification(
        app["id"], create_income_verification_payload(employer_name="Acme Again"), SCREENER
    )
    validate_error(resp, ApiErrorId.ERR_INCOME_VERIFICATION_EXISTS)


def test_suspended_landlord_cannot_create_application():
    """PRD §3.2: "The landlord must be `ACTIVE`; attempts to open
    applications for a `SUSPENDED` landlord are rejected with
    `ERR_LANDLORD_SUSPENDED`."

    Design: Corner/validations/suspended_landlord_cannot_create_application
    """
    landlord = create_landlord(name="L Sus", contact_email="lsus@x.com")
    api_client.suspend_landlord(landlord["id"], ADMIN)
    applicant = create_applicant()
    resp = api_client.create_application(
        {"applicant_id": applicant["id"], "unit_state_code": "TX",
         "monthly_rent_cents": 200000, "stated_monthly_income_cents": 600000},
        make_landlord_headers(landlord["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LANDLORD_SUSPENDED)


def test_portable_report_of_other_applicant_rejected():
    """PRD §3.3: "the portable report must belong to the same consumer (its application's `applicant_id` equals this application's) and must be `DELIVERED` or `RE_DELIVERED`, otherwise `ERR_PORTABLE_REPORT_INVALID`;"

    Design: Corner/validations/portable_report_of_other_applicant_rejected
    """
    landlord, applicant_x, report1 = _setup_portable_report_origin()
    applicant_y = create_applicant(full_name="Yann Y", email="yy@x.com", ssn_last4="2222",
                                   residence_state="CA")
    app2 = create_application(landlord, applicant_y, unit_state_code="CA",
                              monthly_rent_cents=190000, stated_monthly_income_cents=600000,
                              portable_report_id=report1["id"])
    resp = api_client.submit_application(app2["id"], make_landlord_headers(landlord["id"]))
    validate_error(resp, ApiErrorId.ERR_PORTABLE_REPORT_INVALID)
    assert get_application(app2["id"])["status"] == "DRAFT"


def test_record_search_on_portable_application_forbidden():
    """PRD §3.4: "an application submitted with a `portable_report_id` is rejected with `ERR_PORTABLE_SEARCH_FORBIDDEN`, because portable files reuse their copied report and never run a fresh search;"

    Design: Corner/validations/record_search_on_portable_application_forbidden
    """
    landlord, applicant, report1 = _setup_portable_report_origin()
    app2 = create_application(landlord, applicant, unit_state_code="CA",
                              monthly_rent_cents=190000, stated_monthly_income_cents=600000,
                              portable_report_id=report1["id"])
    app2 = submit_application(app2, landlord)
    resp = api_client.record_searches(app2["id"], {"credit_score": 700, "records": []}, SCREENER)
    validate_error(resp, ApiErrorId.ERR_PORTABLE_SEARCH_FORBIDDEN)
    app_after = get_application(app2["id"])
    assert app_after["status"] == "SUBMITTED"
    assert app_after["fee_charged_cents"] == 1000
