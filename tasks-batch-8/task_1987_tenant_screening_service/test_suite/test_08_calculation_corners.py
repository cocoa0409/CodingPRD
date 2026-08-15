"""Corner queue B tests: calculation corners (fee cap, suppression defaults, portable flat
fee, consistency-audit aggregation, identity threshold boundary)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    consent_application,
    create_and_resolve_income_verification,
    create_applicant,
    create_application,
    create_jurisdiction_rule,
    deliver_report,
    get_application,
    get_landlord,
    get_report,
    list_records,
    make_applicant_headers,
    make_landlord_headers,
    run_record_searches,
    score_application,
    setup_landlord_with_criteria,
    setup_submitted_application,
    submit_application,
    validate_success,
    verify_identity,
)

ADMIN = TEST_USERS["admin_headers"]
SCREENER = TEST_USERS["screener_headers"]


def test_fee_cap_applies_min_at_and_below_computed():
    """PRD §3.4: "When the covering rule carries a non-null
    `max_screening_fee_cents`, the charged fee is the lesser of the cap and
    the computed fee, and the cap binds inclusively — a computed fee exactly
    equal to the cap charges the cap."

    Design: Corner/calculations/fee_cap_applies_min_at_and_below_computed
    """
    create_jurisdiction_rule(state_code="GA", criminal_lookback_years=7,
                             eviction_lookback_years=7, max_screening_fee_cents=3439)
    create_jurisdiction_rule(state_code="FL", criminal_lookback_years=7,
                             eviction_lookback_years=7, max_screening_fee_cents=3000)
    landlord_ga, _ = setup_landlord_with_criteria()
    app_ga, _ = setup_submitted_application(landlord_ga, unit_state_code="GA", monthly_rent_cents=200000)
    run_record_searches(app_ga, credit_score=700)
    assert get_application(app_ga["id"])["fee_charged_cents"] == 3439, (
        "cap 3439 == computed 3439: equality binds inclusively, no error"
    )

    landlord_fl, _ = setup_landlord_with_criteria()
    app_fl, _ = setup_submitted_application(landlord_fl, unit_state_code="FL", monthly_rent_cents=200000)
    run_record_searches(app_fl, credit_score=700)
    assert get_application(app_fl["id"])["fee_charged_cents"] == 3000, (
        "cap 3000 < computed 3439: min applies"
    )
    assert get_landlord(landlord_fl["id"])["fee_balance_cents"] == 3000


def test_criminal_prohibited_state_suppresses_and_skips_surcharge():
    """PRD §3.4: "a `CRIMINAL` record in a state whose `criminal_lookback_years` is zero becomes `SUPPRESSED` with `suppression_reason` `SEARCH_PROHIBITED`;"
    PRD §3.4: "criminal (only when the covering rule's `criminal_lookback_years` is above zero — a prohibited criminal search is not executed and is not charged)."

    Design: Corner/calculations/criminal_prohibited_state_suppresses_and_skips_surcharge
    """
    create_jurisdiction_rule(
        state_code="NY", criminal_lookback_years=0, eviction_lookback_years=5,
        max_screening_fee_cents=3200,
    )
    landlord, _ = setup_landlord_with_criteria()
    app, _ = setup_submitted_application(landlord, unit_state_code="NY", monthly_rent_cents=200000)
    report = run_record_searches(app, credit_score=700, records=[
        {"record_type": "CRIMINAL", "jurisdiction_state_code": "NY",
         "record_date": "2024-01-01T00:00:00Z", "description": "misdemeanor"},
        {"record_type": "EVICTION", "jurisdiction_state_code": "NY",
         "record_date": "2024-01-01T00:00:00Z", "description": "eviction"},
    ])
    recs = list_records(report["id"])
    assert recs[0]["status"] == "SUPPRESSED"
    assert recs[0]["suppression_reason"] == "SEARCH_PROHIBITED", "criminal_lookback_years == 0"
    assert recs[1]["status"] == "INCLUDED", "2024-01-01 within 5-year eviction cutoff 2021-08-01"
    assert get_report(report["id"])["included_record_count"] == 1
    assert get_application(app["id"])["fee_charged_cents"] == 3126, (
        "2500 + 313*2; CRIMINAL search not executed; cap 3200 not binding"
    )


def test_default_lookbacks_apply_without_jurisdiction_rule():
    """PRD §3.4: "When no rule covers the state, default lookbacks of seven
    years apply to both record types and criminal searching is treated as
    allowed."

    Design: Corner/calculations/default_lookbacks_apply_without_jurisdiction_rule
    """
    landlord, _ = setup_landlord_with_criteria()
    app, _ = setup_submitted_application(landlord, unit_state_code="TX", monthly_rent_cents=200000)
    report = run_record_searches(app, credit_score=700, records=[
        {"record_type": "EVICTION", "jurisdiction_state_code": "TX",
         "record_date": "2020-01-01T00:00:00Z", "description": "recent eviction"},
        {"record_type": "CRIMINAL", "jurisdiction_state_code": "TX",
         "record_date": "2015-01-01T00:00:00Z", "description": "old misdemeanor"},
    ])
    recs = list_records(report["id"])
    assert recs[0]["status"] == "INCLUDED", "2020-01-01 >= default eviction cutoff 2019-08-01"
    assert recs[1]["status"] == "SUPPRESSED"
    assert recs[1]["suppression_reason"] == "LOOKBACK_EXPIRED", (
        "2015-01-01 < default criminal cutoff 2019-08-01"
    )
    assert get_report(report["id"])["included_record_count"] == 1
    assert get_application(app["id"])["fee_charged_cents"] == 3439, (
        "criminal search allowed by default rule"
    )


def test_portable_copy_charges_flat_fee():
    """PRD §3.3: "The application is charged the portable flat fee of 1000
    cents (ten dollars): `fee_charged_cents` is set to 1000 and the landlord's
    `fee_balance_cents` increases by the same amount, with no surcharges and
    no jurisdictional cap applied."
    PRD §3.3: "the system creates a new **ScreeningReport** as a copy of the source: `is_portable_copy` set to true, `source_report_id` pointing back at the submitted report, `status` `DRAFT`,"

    Design: Corner/calculations/portable_copy_charges_flat_fee
    """
    create_jurisdiction_rule(
        state_code="CA", criminal_lookback_years=7, eviction_lookback_years=7,
        portable_report_acceptance_required=True,
    )
    landlord, _ = setup_landlord_with_criteria()
    applicant = create_applicant(residence_state="CA")
    app1 = create_application(landlord, applicant, unit_state_code="CA",
                              monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    consent_application(app1, applicant)
    verify_identity(app1)
    app1 = submit_application(app1, landlord)
    report1 = run_record_searches(app1, credit_score=700, records=[
        {"record_type": "EVICTION", "jurisdiction_state_code": "CA",
         "record_date": "2024-03-01T00:00:00Z", "description": "eviction"},
    ])
    create_and_resolve_income_verification(app1, 600000)
    score_application(app1)
    deliver_report(report1)
    app2 = create_application(landlord, applicant, unit_state_code="CA",
                              monthly_rent_cents=180000, stated_monthly_income_cents=600000,
                              portable_report_id=report1["id"])
    submitted = submit_application(app2, landlord)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["fee_charged_cents"] == 1000, "flat portable fee"
    from test_helpers import get_success_data
    copies = get_success_data(api_client.list_reports(ADMIN, params={"application_id": app2["id"]}))
    assert copies[0]["is_portable_copy"] is True
    assert copies[0]["source_report_id"] == report1["id"]
    assert copies[0]["status"] == "DRAFT"
    assert copies[0]["included_record_count"] == 1, (
        "the included eviction is copied and re-swept under CA at the submission clock"
    )
    assert get_landlord(landlord["id"])["fee_balance_cents"] == 4439, (
        "3439 search fee + 1000 flat portable fee"
    )


def test_consistency_audit_reports_deviation_rate():
    """PRD §3.9: "An application is inconsistent when its `decision` is
    `APPROVE` while its `recommendation` is `RECOMMEND_DENY`, or when its
    `decision` is `DENY` while its `recommendation` is `RECOMMEND_APPROVE`;
    a `RECOMMEND_CONDITIONAL` recommendation is consistent with either
    decision. The `deviation_rate` is `inconsistencies_found` divided by
    `applications_examined`, rounded half-up to four decimal places, and is
    zero when no applications were examined."

    Design: Corner/calculations/consistency_audit_reports_deviation_rate
    """
    create_jurisdiction_rule(state_code="CA", criminal_lookback_years=7, eviction_lookback_years=7)
    landlord, _ = setup_landlord_with_criteria()

    def _decided(name, email, ssn, records, decision, score=700):
        ap = create_applicant(full_name=name, email=email, ssn_last4=ssn, residence_state="CA")
        app = create_application(landlord, ap, unit_state_code="CA",
                                 monthly_rent_cents=200000, stated_monthly_income_cents=600000)
        consent_application(app, ap)
        verify_identity(app)
        app = submit_application(app, landlord)
        report = run_record_searches(app, credit_score=score, records=records)
        create_and_resolve_income_verification(app, 600000)
        score_application(app)
        deliver_report(report)
        api_client.decide_application(app["id"], decision, make_landlord_headers(landlord["id"]))
        return app

    ev = [{"record_type": "EVICTION", "jurisdiction_state_code": "CA",
           "record_date": "2024-03-01T00:00:00Z", "description": "eviction"}]
    _decided("A One", "a1@x.com", "0001", [], "APPROVE")
    _decided("A Two", "a2@x.com", "0002", ev, "DENY")
    app3 = _decided("A Three", "a3@x.com", "0003", ev, "APPROVE")
    resp = api_client.run_consistency_audit(landlord["id"], ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["applications_examined"] == 3
    assert data["inconsistencies_found"] == 1
    assert data["inconsistent_application_ids"] == [app3["id"]], (
        "only the APPROVE-against-RECOMMEND_DENY application"
    )
    assert data["deviation_rate"] == 0.3333, "1/3, round_half_up to 4 decimal places"


def test_identity_evidence_threshold_boundary():
    """PRD §3.2: "an `evidence_score` of at least 70 — exactly 70 verifies, the boundary is inclusive — moves `identity_status` from `UNVERIFIED` or `FAILED` to `VERIFIED`, while anything below 70 moves it to (or keeps it in) `FAILED`,"

    Design: Corner/calculations/identity_evidence_threshold_boundary
    """
    from test_helpers import create_landlord
    landlord = create_landlord(name="L Idt", contact_email="lidt@x.com")
    applicant = create_applicant()
    app = create_application(landlord, applicant, unit_state_code="TX",
                             monthly_rent_cents=200000, stated_monthly_income_cents=600000)
    resp = api_client.verify_identity(app["id"], {"method": "KNOWLEDGE_BASED", "evidence_score": 69}, SCREENER)
    data = validate_success(resp)
    assert data["identity_status"] == "FAILED", "69 < 70"
    assert data["identity_attempts"] == 1
    resp = api_client.verify_identity(app["id"], {"method": "KNOWLEDGE_BASED", "evidence_score": 70}, SCREENER)
    data = validate_success(resp)
    assert data["identity_status"] == "VERIFIED", "70 >= 70 inclusive"
    assert data["identity_attempts"] == 2
