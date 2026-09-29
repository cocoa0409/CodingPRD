"""Error-path coverage for examination scoring, comity licensure, competency
reporting and audit, renewal and reinstatement, plan sealing and consent-order
execution."""

from test_helpers import (
    BOARD_LICENSING_OFFICER_HEADERS,
    BOARD_REVIEWER_2_HEADERS,
    BOARD_REVIEWER_HEADERS,
    BOARD_SECRETARY_HEADERS,
    TESTING_SERVICE_HEADERS,
    assert_money_cents,
    assert_pdh_value,
    factories,
    fixtures,
    make_licensee_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_scoring_an_authorization_with_no_appointment_is_exam_state_invalid(api):
    """PRD §3.5: "Scores arrive from the `TestingService` identity against a `SCHEDULED` authorization"

    Design: Corner/errors/err_exam_state_invalid_when_scoring_an_unscheduled_authorization
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="exam_approved",
        experience_overrides={
            "period_start_month": "2019-01",
            "period_end_month": "2022-12",
        },
        submission_overrides={"responsibility_confirmed": True},
        credit_headers=BOARD_REVIEWER_HEADERS,
        approve_headers=BOARD_LICENSING_OFFICER_HEADERS,
    )
    authorization = track["authorization"]
    assert authorization["status"] == "APPROVED_TO_SIT"

    response = api.score_exam(
        authorization["id"],
        factories.score_payload(
            raw_score=88, administered_at="2026-08-05T17:00:00Z"
        ),
        TESTING_SERVICE_HEADERS,
    )
    validate_error(response, "ERR_EXAM_STATE_INVALID")

    reread = validate_success(
        api.get_exam_authorization(authorization["id"], BOARD_SECRETARY_HEADERS)
    )
    assert reread["status"] == "APPROVED_TO_SIT"
    assert reread["result"] == "PENDING"
    assert reread["raw_score"] is None
    assert reread["ncees_transmission_id"] is None
    assert reread["attempt_number"] == 1
    assert reread["version"] == authorization["version"]

    application = validate_success(
        api.get_application(track["application"]["id"], BOARD_REVIEWER_HEADERS)
    )
    assert application["status"] == "EXAM_APPROVED"


def test_exam_approval_is_refused_while_a_verification_is_still_submitted(api):
    """PRD §3.4: "No verification request anywhere on the file may be left hanging: every one of them must have reached `ACCEPTED` or `REJECTED`, and one still sitting in `REQUESTED` or `SUBMITTED` — or a missing credit determination — is refused with `ERR_REFERENCE_NOT_ACCEPTED` (HTTP 422)."

    Design: Corner/errors/err_reference_not_accepted_blocks_exam_approval
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="under_review",
        experience_overrides={
            "period_start_month": "2019-01",
            "period_end_month": "2022-12",
        },
        submission_overrides={"responsibility_confirmed": True},
    )
    application_id = track["application"]["id"]
    assert track["reference"]["status"] == "SUBMITTED"

    response = api.approve_exam(application_id, BOARD_LICENSING_OFFICER_HEADERS)
    validate_error(response, "ERR_REFERENCE_NOT_ACCEPTED")

    application = validate_success(
        api.get_application(application_id, BOARD_REVIEWER_HEADERS)
    )
    assert application["status"] == "UNDER_REVIEW"
    assert application["provisional_experience_months"] == 48
    assert application["verified_experience_months"] == 0
    assert application["credit_determined_by_user_id"] is None

    _, meta = validate_paginated(
        api.list_exam_authorizations(
            BOARD_REVIEWER_HEADERS, {"application_id": application_id}
        )
    )
    assert meta["total_count"] == 0


def test_exam_approval_is_refused_before_the_credit_determination_has_run(api):
    """PRD §3.4: "No verification request anywhere on the file may be left hanging: every one of them must have reached `ACCEPTED` or `REJECTED`, and one still sitting in `REQUESTED` or `SUBMITTED` — or a missing credit determination — is refused with `ERR_REFERENCE_NOT_ACCEPTED` (HTTP 422)."

    Design: Corner/errors/err_reference_not_accepted_blocks_exam_approval
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="reference_accepted",
        experience_overrides={
            "period_start_month": "2019-01",
            "period_end_month": "2022-12",
        },
        submission_overrides={"responsibility_confirmed": True},
    )
    application_id = track["application"]["id"]
    assert track["reference"]["status"] == "ACCEPTED"

    response = api.approve_exam(application_id, BOARD_LICENSING_OFFICER_HEADERS)
    validate_error(response, "ERR_REFERENCE_NOT_ACCEPTED")

    application = validate_success(
        api.get_application(application_id, BOARD_REVIEWER_HEADERS)
    )
    assert application["status"] == "UNDER_REVIEW"
    assert application["verified_experience_months"] == 48
    assert application["credit_determined_by_user_id"] is None

    _, meta = validate_paginated(
        api.list_exam_authorizations(
            BOARD_REVIEWER_HEADERS, {"application_id": application_id}
        )
    )
    assert meta["total_count"] == 0


COMITY_EXPERIENCE = {
    "employer_name": "Meyer Bridge",
    "position_title": "Principal Engineer",
    "period_start_month": "2019-01",
    "period_end_month": "2022-12",
    "responsibility_level": "RESPONSIBLE_CHARGE",
    "post_degree": True,
}


def test_exam_approval_on_a_comity_file_is_a_pathway_mismatch(api):
    """PRD §3.4: "Requesting the wrong one for the file's `pathway` — examination approval on a comity file, or direct comity issuance on an examination file — is refused with `ERR_PATHWAY_MISMATCH` (HTTP 409)."

    Design: Corner/errors/comity_issue_license_ncees_guards_then_grants
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="credit_determined",
        application_overrides={"pathway": "COMITY"},
        applicant_overrides={"ncees_record_id": "NCEES-77001"},
        experience_overrides=dict(COMITY_EXPERIENCE),
        submission_overrides={"responsibility_confirmed": True},
        credit_headers=BOARD_REVIEWER_HEADERS,
    )
    application_id = track["application"]["id"]
    assert track["application"]["pathway"] == "COMITY"

    response = api.approve_exam(application_id, BOARD_LICENSING_OFFICER_HEADERS)
    validate_error(response, "ERR_PATHWAY_MISMATCH")

    application = validate_success(
        api.get_application(application_id, BOARD_REVIEWER_HEADERS)
    )
    assert application["status"] == "UNDER_REVIEW"
    assert application["verified_experience_months"] == 48

    _, meta = validate_paginated(
        api.list_exam_authorizations(
            BOARD_REVIEWER_HEADERS, {"application_id": application_id}
        )
    )
    assert meta["total_count"] == 0


def test_comity_issuance_without_a_records_packet_is_not_matched(api):
    """PRD §3.4: "it requires that `ncees_record_status` be `MATCHED` and `ncees_verified_exam_pass` be true — an absent, mismatched or examination-silent packet is refused with `ERR_NCEES_RECORD_NOT_MATCHED` (HTTP 422)"

    Design: Corner/errors/comity_issue_license_ncees_guards_then_grants
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="credit_determined",
        application_overrides={"pathway": "COMITY"},
        applicant_overrides={"ncees_record_id": "NCEES-77001"},
        experience_overrides=dict(COMITY_EXPERIENCE),
        submission_overrides={"responsibility_confirmed": True},
        credit_headers=BOARD_REVIEWER_HEADERS,
    )
    application_id = track["application"]["id"]
    engineer_id = track["engineer"]["id"]
    assert track["application"]["ncees_record_status"] == "NOT_REQUESTED"

    response = api.issue_license(application_id, BOARD_LICENSING_OFFICER_HEADERS)
    validate_error(response, "ERR_NCEES_RECORD_NOT_MATCHED")

    application = validate_success(
        api.get_application(application_id, BOARD_REVIEWER_HEADERS)
    )
    assert application["status"] == "UNDER_REVIEW"
    assert application["ncees_record_status"] == "NOT_REQUESTED"
    assert application["ncees_verified_exam_pass"] is False

    engineer = validate_success(
        api.get_engineer(engineer_id, BOARD_SECRETARY_HEADERS)
    )
    assert engineer["active_license_number"] is None


def test_comity_issuance_below_four_verified_years_is_refused(api):
    """PRD §3.4: "that `ncees_verified_years_licensed` be at least 4, fewer years being refused with `ERR_COMITY_YEARS_INSUFFICIENT` (HTTP 422)"

    Design: Corner/errors/comity_issue_license_ncees_guards_then_grants
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="credit_determined",
        application_overrides={"pathway": "COMITY"},
        applicant_overrides={"ncees_record_id": "NCEES-77001"},
        experience_overrides=dict(COMITY_EXPERIENCE),
        submission_overrides={"responsibility_confirmed": True},
        credit_headers=BOARD_REVIEWER_HEADERS,
    )
    application_id = track["application"]["id"]
    frozen_fee = track["application"]["fee_assessment_cents"]
    assert_money_cents(frozen_fee, 36000)

    transmitted = validate_success(
        api.transmit_ncees_verification(
            application_id,
            factories.ncees_verification_payload(
                ncees_record_id="NCEES-77001",
                verified_years_licensed=3,
                record_expires_on="2027-06-30T00:00:00Z",
            ),
            TESTING_SERVICE_HEADERS,
        )
    )
    assert transmitted["ncees_record_status"] == "MATCHED"
    assert transmitted["ncees_verified_years_licensed"] == 3
    assert_money_cents(transmitted["fee_assessment_cents"], frozen_fee)

    response = api.issue_license(application_id, BOARD_LICENSING_OFFICER_HEADERS)
    validate_error(response, "ERR_COMITY_YEARS_INSUFFICIENT")

    application = validate_success(
        api.get_application(application_id, BOARD_REVIEWER_HEADERS)
    )
    assert application["status"] == "UNDER_REVIEW"
    assert_money_cents(application["fee_assessment_cents"], 36000)


def test_comity_issuance_on_a_stale_packet_is_refused_then_granted_on_a_fresh_one(api):
    """PRD §3.4: "that the logical clock has not passed `ncees_record_expires_on`, a stale packet being refused with `ERR_NCEES_RECORD_EXPIRED` (HTTP 422)"

    Design: Corner/errors/comity_issue_license_ncees_guards_then_grants
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="credit_determined",
        application_overrides={"pathway": "COMITY"},
        applicant_overrides={"ncees_record_id": "NCEES-77001"},
        experience_overrides=dict(COMITY_EXPERIENCE),
        submission_overrides={"responsibility_confirmed": True},
        credit_headers=BOARD_REVIEWER_HEADERS,
    )
    application_id = track["application"]["id"]
    engineer_id = track["engineer"]["id"]

    stale = validate_success(
        api.transmit_ncees_verification(
            application_id,
            factories.ncees_verification_payload(
                ncees_record_id="NCEES-77001",
                verified_years_licensed=6,
                record_expires_on="2026-07-01T00:00:00Z",
            ),
            TESTING_SERVICE_HEADERS,
        )
    )
    assert stale["ncees_record_status"] == "MATCHED"

    validate_error(
        api.issue_license(application_id, BOARD_LICENSING_OFFICER_HEADERS),
        "ERR_NCEES_RECORD_EXPIRED",
    )

    validate_success(
        api.transmit_ncees_verification(
            application_id,
            factories.ncees_verification_payload(
                ncees_record_id="NCEES-77001",
                verified_years_licensed=6,
                record_expires_on="2027-06-30T00:00:00Z",
            ),
            TESTING_SERVICE_HEADERS,
        )
    )

    license_ = validate_success(
        api.issue_license(application_id, BOARD_LICENSING_OFFICER_HEADERS), 201
    )
    assert license_["license_type"] == "COMITY"
    assert license_["status"] == "ACTIVE"
    assert license_["current_period_start"] == "2026-08-01T00:00:00.000Z"
    assert license_["current_period_end"] == "2028-08-01T00:00:00.000Z"
    assert license_["renewal_window_opens_at"] == "2028-05-03T00:00:00.000Z"
    assert_pdh_value(license_["pdh_requirement"], 30)
    assert license_["discipline_flag"] is False

    application = validate_success(
        api.get_application(application_id, BOARD_REVIEWER_HEADERS)
    )
    assert application["status"] == "LICENSE_ISSUED"

    engineer = validate_success(
        api.get_engineer(engineer_id, BOARD_SECRETARY_HEADERS)
    )
    assert engineer["active_license_number"] == license_["license_number"]


def test_report_acceptance_is_refused_when_the_declared_hours_do_not_reconcile(api):
    """PRD §3.6: "It requires the licensee's arithmetic to reconcile: `self_certified_pdh` as declared must equal the recomputed `self_certified_total_pdh`, and a discrepancy is refused with `ERR_PDH_SELF_CERT_MISMATCH` (HTTP 422)."

    Design: Corner/errors/cpc_report_acceptance_guards_mismatch_then_state_then_audit_scope
    """
    setup = fixtures.setup_cpc_report(api, report_overrides={"self_certified_pdh": 31})
    report = setup["report"]
    engineer_id = setup["engineer"]["id"]
    assert report["status"] == "SUBMITTED"

    fixtures.add_pdh_record(
        api,
        report["id"],
        engineer_id,
        activity_type="COURSE",
        pdh_hours=28.0,
        completed_on="2027-02-10T00:00:00Z",
    )
    fixtures.add_pdh_record(
        api,
        report["id"],
        engineer_id,
        activity_type="COURSE",
        pdh_hours=2.0,
        completed_on="2027-03-10T00:00:00Z",
        ethics_flag=True,
    )

    response = api.accept_cpc_report(report["id"], BOARD_REVIEWER_HEADERS)
    validate_error(response, "ERR_PDH_SELF_CERT_MISMATCH")

    reread = validate_success(api.get_cpc_report(report["id"], BOARD_REVIEWER_HEADERS))
    assert reread["status"] == "SUBMITTED"
    assert reread["audit_id"] is None
    assert reread["audit_decided_by_user_id"] is None


def test_a_second_acceptance_of_an_accepted_report_is_a_report_state_conflict(api):
    """PRD §3.6: "a report transition requested from a status that does not declare it — accepting a `SUPERSEDED` report, for instance — is refused with `ERR_CPC_REPORT_STATE_INVALID` (HTTP 409)"

    Design: Corner/errors/cpc_report_acceptance_guards_mismatch_then_state_then_audit_scope
    """
    setup = fixtures.setup_cpc_report(api, report_overrides={"self_certified_pdh": 31})
    report = setup["report"]
    engineer_id = setup["engineer"]["id"]

    for activity_type, hours, day, ethics in (
        ("COURSE", 28.0, "2027-02-10T00:00:00Z", False),
        ("COURSE", 2.0, "2027-03-10T00:00:00Z", True),
        ("SEMINAR", 1.0, "2027-04-10T00:00:00Z", False),
    ):
        fixtures.add_pdh_record(
            api,
            report["id"],
            engineer_id,
            activity_type=activity_type,
            pdh_hours=hours,
            completed_on=day,
            ethics_flag=ethics,
        )

    accepted = validate_success(
        api.accept_cpc_report(report["id"], BOARD_REVIEWER_HEADERS)
    )
    assert accepted["status"] == "ACCEPTED"
    assert_pdh_value(accepted["self_certified_total_pdh"], 31.0)
    assert_pdh_value(accepted["shortfall_pdh"], 0.0)

    response = api.accept_cpc_report(report["id"], BOARD_REVIEWER_HEADERS)
    validate_error(response, "ERR_CPC_REPORT_STATE_INVALID")

    reread = validate_success(api.get_cpc_report(report["id"], BOARD_REVIEWER_HEADERS))
    assert reread["status"] == "ACCEPTED"
    assert reread["version"] == accepted["version"]


def test_an_audit_decision_on_a_never_sampled_report_is_refused(api):
    """PRD §3.6: "The report must actually stand in `UNDER_AUDIT`; an attempt against a report in any other status is refused with `ERR_REPORT_NOT_UNDER_AUDIT` (HTTP 409)."

    Design: Corner/errors/cpc_report_acceptance_guards_mismatch_then_state_then_audit_scope
    """
    setup = fixtures.setup_cleared_cpc_report(api)
    report = setup["report"]
    assert report["status"] == "ACCEPTED"
    assert report["audit_id"] is None

    response = api.audit_decision(
        report["id"], {"decision": "CLEAR"}, BOARD_REVIEWER_2_HEADERS
    )
    validate_error(response, "ERR_REPORT_NOT_UNDER_AUDIT")

    reread = validate_success(api.get_cpc_report(report["id"], BOARD_REVIEWER_HEADERS))
    assert reread["status"] == "ACCEPTED"
    assert reread["audit_id"] is None
    assert reread["audit_decided_by_user_id"] is None
    assert reread["version"] == report["version"]


def test_redrawing_a_period_whose_audit_cycle_is_closed_is_refused(api):
    """PRD §3.6: "A period whose audit cycle has already been closed can never be re-drawn: if any draw with status `CLOSED` already exists for the requested `as_of_period_end`, the request is refused with `ERR_AUDIT_STATE_INVALID` (HTTP 409)"

    Design: Corner/errors/err_audit_state_invalid_on_redraw_of_a_closed_cycle
    """
    thin_engineer, thin_license = fixtures.create_licensed_engineer(api)
    wide_engineer, wide_license = fixtures.create_licensed_engineer(api)
    period_end = thin_license["current_period_end"]
    assert wide_license["current_period_end"] == period_end

    thin_report = fixtures.create_cpc_report(
        api,
        thin_license["id"],
        thin_engineer["id"],
        thin_license["version"],
        period_start=thin_license["current_period_start"],
        period_end=period_end,
        self_certified_pdh=30,
    )
    for activity_type, hours, day, ethics in (
        ("COURSE", 28.0, "2027-02-10T00:00:00Z", False),
        ("COURSE", 2.0, "2027-03-10T00:00:00Z", True),
    ):
        fixtures.add_pdh_record(
            api,
            thin_report["id"],
            thin_engineer["id"],
            activity_type=activity_type,
            pdh_hours=hours,
            completed_on=day,
            ethics_flag=ethics,
        )
    thin_report = fixtures.accept_cpc_report(api, thin_report["id"])
    assert_pdh_value(thin_report["self_certified_total_pdh"], 30.0)

    wide_report = fixtures.create_cpc_report(
        api,
        wide_license["id"],
        wide_engineer["id"],
        wide_license["version"],
        period_start=wide_license["current_period_start"],
        period_end=period_end,
        self_certified_pdh=40,
    )
    for activity_type, hours, day, ethics in (
        ("COURSE", 28.0, "2027-02-10T00:00:00Z", False),
        ("COURSE", 2.0, "2027-03-10T00:00:00Z", True),
        ("SEMINAR", 10.0, "2027-04-10T00:00:00Z", False),
    ):
        fixtures.add_pdh_record(
            api,
            wide_report["id"],
            wide_engineer["id"],
            activity_type=activity_type,
            pdh_hours=hours,
            completed_on=day,
            ethics_flag=ethics,
        )
    wide_report = fixtures.accept_cpc_report(api, wide_report["id"])
    assert_pdh_value(wide_report["self_certified_total_pdh"], 40.0)

    draw = fixtures.draw_audit(
        api,
        headers=BOARD_SECRETARY_HEADERS,
        sample_pct=0.5,
        as_of_period_end=period_end,
    )
    assert draw["pool_size"] == 2
    assert draw["sampled_count"] == 1
    assert draw["status"] == "SAMPLED"

    drawn_thin = validate_success(
        api.get_cpc_report(thin_report["id"], BOARD_REVIEWER_HEADERS)
    )
    assert drawn_thin["status"] == "UNDER_AUDIT"
    assert drawn_thin["audit_id"] == draw["id"]

    decided = fixtures.decide_audit(
        api, thin_report["id"], decision="DEFICIENT", headers=BOARD_REVIEWER_HEADERS
    )
    assert decided["status"] == "AUDIT_DEFICIENT"

    closed_draw = validate_success(
        api.get_cpc_audit(draw["id"], BOARD_REVIEWER_HEADERS)
    )
    assert closed_draw["status"] == "CLOSED"

    response = api.create_cpc_audit(
        factories.cpc_audit_payload(sample_pct=0.5, as_of_period_end=period_end),
        BOARD_SECRETARY_HEADERS,
    )
    validate_error(response, "ERR_AUDIT_STATE_INVALID")

    untouched = validate_success(
        api.get_cpc_report(wide_report["id"], BOARD_REVIEWER_HEADERS)
    )
    assert untouched["status"] == "ACCEPTED"
    assert untouched["audit_id"] is None

    _, meta = validate_paginated(api.list_cpc_audits(BOARD_REVIEWER_HEADERS))
    assert meta["total_count"] == 1


def test_renewing_an_expired_licence_is_a_licence_state_conflict(api):
    """PRD §3.7: "A licence transition requested from a status that does not declare it — renewing an `EXPIRED` licence, reinstating an `ACTIVE` one, or anything at all against a `REVOKED` one — is refused with `ERR_LICENSE_STATE_INVALID` (HTTP 409)."

    Design: Corner/errors/license_renew_and_reinstate_guards_state_makeup_fee_and_window
    """
    engineer, license_ = fixtures.create_licensed_engineer(
        api, license_overrides={"issued_on": "2026-01-15T00:00:00Z"}
    )
    sweep = fixtures.set_clock(api, "2028-02-01T00:00:00Z")
    assert sweep["expired_license_count"] == 1

    expired = validate_success(
        api.get_license(license_["id"], BOARD_LICENSING_OFFICER_HEADERS)
    )
    assert expired["status"] == "EXPIRED"
    assert expired["current_period_end"] == "2028-01-15T00:00:00.000Z"
    assert expired["reinstatement_eligible_until"] == "2030-01-14T00:00:00.000Z"

    response = api.renew_license(
        license_["id"], make_licensee_headers(engineer["id"])
    )
    validate_error(response, "ERR_LICENSE_STATE_INVALID")

    reread = validate_success(
        api.get_license(license_["id"], BOARD_LICENSING_OFFICER_HEADERS)
    )
    assert reread["status"] == "EXPIRED"
    assert reread["current_period_end"] == "2028-01-15T00:00:00.000Z"
    assert reread["version"] == expired["version"]


def test_reinstatement_below_fifteen_makeup_hours_is_refused(api):
    """PRD §3.7: "`makeup_pdh` must be at least 15, and a lesser figure is refused with `ERR_REINSTATEMENT_MAKEUP_INSUFFICIENT` (HTTP 422)"

    Design: Corner/errors/license_renew_and_reinstate_guards_state_makeup_fee_and_window
    """
    _, license_ = fixtures.create_licensed_engineer(
        api, license_overrides={"issued_on": "2026-01-15T00:00:00Z"}
    )
    license_id = license_["id"]
    fixtures.set_clock(api, "2028-02-01T00:00:00Z")

    response = api.reinstate_license(
        license_id,
        factories.reinstate_payload(makeup_pdh=10, reinstatement_fee_cents=45000),
        BOARD_LICENSING_OFFICER_HEADERS,
    )
    validate_error(response, "ERR_REINSTATEMENT_MAKEUP_INSUFFICIENT")

    reread = validate_success(
        api.get_license(license_id, BOARD_LICENSING_OFFICER_HEADERS)
    )
    assert reread["status"] == "EXPIRED"
    assert reread["reinstatement_eligible_until"] == "2030-01-14T00:00:00.000Z"


def test_reinstatement_underpaying_the_fee_is_refused_as_unpaid(api):
    """PRD §3.7: "`reinstatement_fee_cents` must be at least 45,000 cents, and underpayment is refused with `ERR_PENALTY_UNPAID` (HTTP 402)."

    Design: Corner/errors/license_renew_and_reinstate_guards_state_makeup_fee_and_window
    """
    _, license_ = fixtures.create_licensed_engineer(
        api, license_overrides={"issued_on": "2026-01-15T00:00:00Z"}
    )
    fixtures.set_clock(api, "2028-02-01T00:00:00Z")

    response = api.reinstate_license(
        license_["id"],
        factories.reinstate_payload(makeup_pdh=15, reinstatement_fee_cents=30000),
        BOARD_LICENSING_OFFICER_HEADERS,
    )
    validate_error(response, "ERR_PENALTY_UNPAID")

    reread = validate_success(
        api.get_license(license_["id"], BOARD_LICENSING_OFFICER_HEADERS)
    )
    assert reread["status"] == "EXPIRED"
    assert reread["current_period_end"] == "2028-01-15T00:00:00.000Z"
    assert reread["reinstatement_eligible_until"] == "2030-01-14T00:00:00.000Z"


def test_reinstatement_after_the_grace_window_is_refused(api):
    """PRD §3.7: "Either gate failing — a lapsed grace window, or a suspension that has not yet run its course — is refused with `ERR_REINSTATEMENT_WINDOW_EXPIRED` (HTTP 409)."

    Design: Corner/errors/license_renew_and_reinstate_guards_state_makeup_fee_and_window
    """
    _, license_ = fixtures.create_licensed_engineer(
        api, license_overrides={"issued_on": "2026-01-15T00:00:00Z"}
    )
    fixtures.set_clock(api, "2028-02-01T00:00:00Z")
    fixtures.set_clock(api, "2030-01-15T00:00:00Z")

    response = api.reinstate_license(
        license_["id"],
        factories.reinstate_payload(makeup_pdh=15, reinstatement_fee_cents=45000),
        BOARD_LICENSING_OFFICER_HEADERS,
    )
    validate_error(response, "ERR_REINSTATEMENT_WINDOW_EXPIRED")

    reread = validate_success(
        api.get_license(license_["id"], BOARD_LICENSING_OFFICER_HEADERS)
    )
    assert reread["status"] == "EXPIRED"
    assert reread["reinstatement_eligible_until"] == "2030-01-14T00:00:00.000Z"


def test_renewal_inside_the_window_without_any_report_is_a_competency_shortfall(api):
    """PRD §3.7: "a competency report must exist for that licence whose `period_end` equals the licence's `current_period_end`, whose status is either `ACCEPTED` or `AUDIT_CLEARED`, and whose `shortfall_pdh` is exactly 0; anything else — no report, a superseded report, an `AUDIT_DEFICIENT` report, or a cleared report still carrying a shortfall — is refused with `ERR_CPC_SHORTFALL` (HTTP 422)."

    Design: Corner/errors/err_cpc_shortfall_blocks_renewal_without_a_cleared_report
    """
    engineer, license_ = fixtures.create_licensed_engineer(
        api, license_overrides={"issued_on": "2026-01-15T00:00:00Z"}
    )
    assert license_["current_period_end"] == "2028-01-15T00:00:00.000Z"
    assert license_["renewal_window_opens_at"] == "2027-10-17T00:00:00.000Z"

    fixtures.set_clock(api, "2027-11-01T00:00:00Z")

    reports, meta = validate_paginated(
        api.list_cpc_reports(BOARD_REVIEWER_HEADERS, {"license_id": license_["id"]})
    )
    assert meta["total_count"] == 0
    assert reports == []

    response = api.renew_license(
        license_["id"], make_licensee_headers(engineer["id"])
    )
    validate_error(response, "ERR_CPC_SHORTFALL")

    reread = validate_success(
        api.get_license(license_["id"], BOARD_LICENSING_OFFICER_HEADERS)
    )
    assert reread["status"] == "ACTIVE"
    assert reread["current_period_start"] == "2026-01-15T00:00:00.000Z"
    assert reread["current_period_end"] == "2028-01-15T00:00:00.000Z"
    assert reread["renewal_window_opens_at"] == "2027-10-17T00:00:00.000Z"
    assert reread["version"] == license_["version"]


def test_sealing_without_the_responsible_charge_attestation_is_refused(api):
    """PRD §3.8: "And last, at rung 41, `responsible_charge_attested` must be true, otherwise `ERR_ATTESTATION_MISSING` (HTTP 422)."

    Design: Corner/errors/plan_seal_guards_attestation_then_plan_state
    """
    setup = fixtures.setup_firm_with_draft_plan(api)
    plan = setup["plan"]
    assert plan["status"] == "DRAFT"
    assert setup["firm"]["status"] == "ACTIVE"

    response = api.seal_plan_submission(
        plan["id"],
        factories.seal_payload(
            setup["license"]["id"], responsible_charge_attested=False
        ),
        make_licensee_headers(setup["engineer"]["id"]),
    )
    validate_error(response, "ERR_ATTESTATION_MISSING")

    reread = validate_success(
        api.get_plan_submission(plan["id"], BOARD_LICENSING_OFFICER_HEADERS)
    )
    assert reread["status"] == "DRAFT"
    assert reread["sealing_license_id"] is None
    assert reread["responsible_charge_attested"] is False
    assert reread["seal_affixed_at"] is None
    assert reread["version"] == plan["version"]


def test_sealing_an_already_sealed_plan_set_is_a_plan_state_conflict(api):
    """PRD §3.8: "Sealing an already sealed or voided set, or flagging a set still in `DRAFT`, is refused with `ERR_PLAN_STATE_INVALID` (HTTP 409)."

    Design: Corner/errors/plan_seal_guards_attestation_then_plan_state
    """
    setup = fixtures.setup_firm_with_draft_plan(api)
    plan = setup["plan"]
    licensee_headers = make_licensee_headers(setup["engineer"]["id"])

    sealed = validate_success(
        api.seal_plan_submission(
            plan["id"],
            factories.seal_payload(setup["license"]["id"]),
            licensee_headers,
        )
    )
    assert sealed["status"] == "SEALED"
    assert sealed["sealing_license_id"] == setup["license"]["id"]
    assert sealed["responsible_charge_attested"] is True
    assert sealed["seal_affixed_at"] == "2026-08-01T00:00:00.000Z"

    response = api.seal_plan_submission(
        plan["id"],
        factories.seal_payload(setup["license"]["id"]),
        licensee_headers,
    )
    validate_error(response, "ERR_PLAN_STATE_INVALID")

    reread = validate_success(
        api.get_plan_submission(plan["id"], BOARD_LICENSING_OFFICER_HEADERS)
    )
    assert reread["status"] == "SEALED"
    assert reread["seal_affixed_at"] == "2026-08-01T00:00:00.000Z"
    assert reread["version"] == sealed["version"]


def test_executing_a_consent_order_with_an_underpaid_penalty_is_refused(api):
    """PRD §3.9: "`penalty_paid_cents` must be at least `penalty_cents` — an unpaid penalty is refused with `ERR_PENALTY_UNPAID` (HTTP 402)"

    Design: Corner/errors/err_penalty_unpaid_on_consent_order_execution
    """
    case = fixtures.create_case(
        api,
        allegation_type="UNLICENSED_PRACTICE",
        complainant_name="City of Albany",
        received_on="2026-07-18T00:00:00Z",
        unlicensed_respondent_name="Vic Sandel",
    )
    fixtures.open_investigation(api, case["id"])
    case = fixtures.record_finding(
        api,
        case["id"],
        finding="PROBABLE_CAUSE",
        aggravating_factor_count=0,
        mitigating_factor_count=0,
        violation_count=1,
    )
    assert case["investigation_status"] == "PROBABLE_CAUSE"
    assert_money_cents(case["assessed_penalty_cents"], 298000)

    order = fixtures.propose_consent_order(
        api,
        case["id"],
        case["version"],
        sanction_type="REPRIMAND",
        penalty_paid_cents=100000,
    )
    assert order["status"] == "PROPOSED"
    assert_money_cents(order["penalty_cents"], 298000)
    assert_money_cents(order["penalty_paid_cents"], 100000)

    response = api.execute_consent_order(
        order["id"],
        factories.execute_payload(executed_on="2026-08-10T00:00:00Z"),
        BOARD_LICENSING_OFFICER_HEADERS,
    )
    validate_error(response, "ERR_PENALTY_UNPAID")

    reread = validate_success(
        api.get_consent_order(order["id"], BOARD_LICENSING_OFFICER_HEADERS)
    )
    assert reread["status"] == "PROPOSED"
    assert_money_cents(reread["penalty_cents"], 298000)
    assert reread["executed_on"] is None
    assert reread["executed_by_user_id"] is None
    assert reread["version"] == order["version"]

    case_reread = validate_success(
        api.get_case(case["id"], BOARD_LICENSING_OFFICER_HEADERS)
    )
    assert case_reread["sanction_status"] == "PROPOSED"
    assert case_reread["investigation_status"] == "PROBABLE_CAUSE"
    assert_money_cents(case_reread["assessed_penalty_cents"], 298000)
