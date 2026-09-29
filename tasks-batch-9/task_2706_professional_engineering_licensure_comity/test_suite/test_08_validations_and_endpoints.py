"""Intake validation gates, fee arithmetic and endpoint round trips of the
professional engineering licensure and comity API.

Covers the respondent-target rule on complaint intake, the renewal window and
period roll, the deficiency response window, the programme ceiling on experience
credit, the expedite surcharge, the education gate at submission, the test-centre
seat ledger, reinstatement's fresh biennium, the clock sweep's licence stage, the
verification-request link and the cross-axis guard on closing a case.
"""

from datetime import datetime, timedelta

from test_helpers import (
    BOARD_INVESTIGATOR_HEADERS,
    BOARD_LICENSING_OFFICER_HEADERS,
    BOARD_REVIEWER_HEADERS,
    BOARD_SECRETARY_HEADERS,
    assert_license_number_format,
    assert_money_cents,
    assert_pdh_value,
    assert_seat_ledger,
    constants,
    factories,
    fixtures,
    make_applicant_headers,
    make_licensee_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

SWEEP_INSTANT = "2028-02-01T00:00:00Z"


def _instant(value):
    """Read one ISO 8601 UTC instant off the wire as a naive UTC datetime."""
    text = str(value).replace("Z", "")
    return datetime.fromisoformat(text).replace(tzinfo=None)


def test_unlicensed_practice_complaint_without_respondent_name_is_refused(api):
    """PRD §3.9: "Supplying both, or neither, is refused with `ERR_RESPONDENT_TARGET_INVALID` (HTTP 422), as is an `UNLICENSED_PRACTICE` allegation without `unlicensed_respondent_name`"

    Design: Corner/validations/unlicensed_practice_case_requires_respondent_name
    """
    response = api.create_case(
        factories.case_payload(
            allegation_type="UNLICENSED_PRACTICE",
            complainant_name="Anonymous",
            received_on="2026-07-25T00:00:00Z",
        ),
        BOARD_INVESTIGATOR_HEADERS,
    )
    validate_error(response, "ERR_RESPONDENT_TARGET_INVALID")

    items, meta = validate_paginated(api.list_cases(BOARD_INVESTIGATOR_HEADERS))
    assert meta["total_count"] == 0, "the refused complaint must not persist a case row"
    assert items == []


def test_renewal_inside_window_rolls_biennium_off_old_period_end(api):
    """PRD §3.7: "`current_period_start` becomes the old `current_period_end`, the new `current_period_end` becomes 24 months after the old one, and `renewal_window_opens_at` is recomputed as 90 days before the new period end."

    Design: Corner/validations/license_renewal_inside_window_succeeds
    """
    setup = fixtures.setup_cleared_cpc_report(api)
    engineer_id = setup["engineer"]["id"]
    license_id = setup["license"]["id"]
    licensee_headers = make_licensee_headers(engineer_id)

    before = validate_success(api.get_license(license_id, licensee_headers))
    old_end = _instant(before["current_period_end"])
    assert _instant(before["renewal_window_opens_at"]) == old_end - timedelta(
        days=constants.RENEWAL_WINDOW_DAYS
    )

    fixtures.set_clock(api, before["renewal_window_opens_at"])
    renewed = validate_success(api.renew_license(license_id, licensee_headers))

    assert renewed["status"] == "ACTIVE"
    assert _instant(renewed["current_period_start"]) == old_end
    expected_end = old_end.replace(year=old_end.year + 2)
    assert _instant(renewed["current_period_end"]) == expected_end
    assert _instant(renewed["renewal_window_opens_at"]) == expected_end - timedelta(
        days=constants.RENEWAL_WINDOW_DAYS
    )
    assert renewed["version"] == before["version"] + 1

    report = validate_success(
        api.get_cpc_report(setup["report"]["id"], BOARD_REVIEWER_HEADERS)
    )
    assert report["status"] == "ACCEPTED"
    assert_pdh_value(report["shortfall_pdh"], 0)


def test_deficiency_response_after_due_date_is_refused(api):
    """PRD §3.4: "The response must arrive at or before `deficiency_due_at`; a response arriving after that instant is refused with `ERR_DEFICIENCY_RESPONSE_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/validations/deficiency_response_after_due_date_rejected
    """
    engineer = fixtures.create_engineer(api)
    applicant_headers = make_applicant_headers(engineer["id"])
    application = fixtures.create_application(api, engineer["id"])
    fixtures.evaluate_education(api, application["id"])
    fixtures.add_experience_record(api, application["id"], engineer["id"])
    fixtures.pay_assessed_fee(api, application["id"], engineer["id"])
    fixtures.submit_application(api, application["id"], engineer["id"])
    fixtures.start_review(api, application["id"])

    deficient = fixtures.raise_deficiency(
        api, application["id"], deficiency_reason="transcript legibility"
    )
    assert deficient["status"] == "DEFICIENT"
    assert deficient["deficiency_cycle_count"] == 1
    due_at = _instant(deficient["deficiency_due_at"])
    assert due_at == _instant(constants.INITIAL_CLOCK) + timedelta(
        days=constants.DEFICIENCY_RESPONSE_DAYS
    )

    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    response = api.respond_deficiency(
        application["id"],
        factories.deficiency_response_payload(response_note="clean transcript attached"),
        applicant_headers,
    )
    validate_error(response, "ERR_DEFICIENCY_RESPONSE_WINDOW_CLOSED")

    stored = validate_success(api.get_application(application["id"], applicant_headers))
    assert stored["status"] == "DEFICIENT"
    assert stored["deficiency_cycle_count"] == 1
    assert stored["deficiency_reason"] == "transcript legibility"
    assert _instant(stored["deficiency_due_at"]) == due_at


def test_provisional_experience_credit_is_capped_at_96_months(api):
    """PRD §3.3: "Sum those per-block contributions across every included block, and cap the sum at 96 months, which is the programme ceiling."

    Design: Corner/validations/total_experience_credit_capped_at_96_months
    """
    engineer = fixtures.create_engineer(api)
    applicant_headers = make_applicant_headers(engineer["id"])
    application = fixtures.create_application(
        api, engineer["id"], exam_code="PE_MECHANICAL"
    )
    fixtures.evaluate_education(api, application["id"])

    blocks = []
    for start_month, end_month in (
        ("2011-01", "2014-12"),
        ("2015-01", "2018-12"),
        ("2019-01", "2022-12"),
    ):
        blocks.append(
            fixtures.add_experience_record(
                api,
                application["id"],
                engineer["id"],
                period_start_month=start_month,
                period_end_month=end_month,
                responsibility_level="RESPONSIBLE_CHARGE",
                post_degree=True,
            )
        )
    for block in blocks:
        assert block["raw_months"] == constants.MAX_SINGLE_RECORD_MONTHS
        assert round(block["credit_multiplier"], 2) == 1.0

    fixtures.pay_assessed_fee(api, application["id"], engineer["id"], amount_cents=32500)
    submitted = validate_success(
        api.submit_application(application["id"], applicant_headers)
    )

    assert submitted["status"] == "SUBMITTED"
    assert submitted["provisional_experience_months"] == constants.MAX_TOTAL_CREDIT_MONTHS
    assert_money_cents(submitted["fee_assessment_cents"], 32500)

    for block in blocks:
        stored = validate_success(
            api.get_experience_record(block["id"], applicant_headers)
        )
        assert stored["raw_months"] == constants.MAX_SINGLE_RECORD_MONTHS
        assert stored["credited_months"] == 0


def test_fee_assessment_without_expedite_carries_no_surcharge(api):
    """PRD §3.2: "Step four adds the expedite surcharge, which is 18 percent of that subtotal rounded half up to whole cents when `expedite_requested` is true, and zero otherwise."

    Design: Corner/validations/expedite_surcharge_applied_only_when_requested
    """
    engineer = fixtures.create_engineer(api)
    applicant_headers = make_applicant_headers(engineer["id"])
    application = fixtures.create_application(
        api, engineer["id"], expedite_requested=False
    )
    fixtures.add_experience_record(api, application["id"], engineer["id"])

    assessment = validate_success(
        api.get_fee_assessment(application["id"], applicant_headers)
    )
    assert_money_cents(assessment["base_fee_cents"], 25000)
    assert_money_cents(assessment["records_verification_fee_cents"], 2500)
    assert_money_cents(assessment["ncees_record_fee_cents"], 0)
    assert_money_cents(assessment["expedite_surcharge_cents"], 0)
    assert_money_cents(assessment["pre_credit_total_cents"], 27500)
    assert_money_cents(assessment["comity_credit_cents"], 0)
    assert_money_cents(assessment["assessment_total_cents"], 27500)
    assert assessment["comity_credit_tier_pct"] == 0

    stored = validate_success(api.get_application(application["id"], applicant_headers))
    assert_money_cents(stored["fee_assessment_cents"], 27500)


def test_fee_assessment_with_expedite_adds_eighteen_percent_surcharge(api):
    """PRD §3.2: "Step four adds the expedite surcharge, which is 18 percent of that subtotal rounded half up to whole cents when `expedite_requested` is true, and zero otherwise."

    Design: Corner/validations/expedite_surcharge_applied_only_when_requested
    """
    engineer = fixtures.create_engineer(api)
    applicant_headers = make_applicant_headers(engineer["id"])
    application = fixtures.create_application(
        api, engineer["id"], expedite_requested=True
    )
    fixtures.add_experience_record(api, application["id"], engineer["id"])

    assessment = validate_success(
        api.get_fee_assessment(application["id"], applicant_headers)
    )
    assert_money_cents(assessment["base_fee_cents"], 25000)
    assert_money_cents(assessment["records_verification_fee_cents"], 2500)
    assert_money_cents(assessment["expedite_surcharge_cents"], 4950)
    assert_money_cents(assessment["pre_credit_total_cents"], 32450)
    assert_money_cents(assessment["comity_credit_cents"], 0)
    assert_money_cents(assessment["assessment_total_cents"], 32450)

    stored = validate_success(api.get_application(application["id"], applicant_headers))
    assert_money_cents(stored["fee_assessment_cents"], 32450)


def test_submit_reports_education_gate_before_the_unpaid_fee(api):
    """PRD §3.2: "The education evaluation must have landed on either `EABET_ACCREDITED` or `NON_ACCREDITED_EVALUATED`; a file still at `NOT_EVALUATED`, or one whose evaluation came back `REJECTED`, is refused with `ERR_EDUCATION_NOT_EVALUATED` (HTTP 422)."

    Design: Corner/validations/education_not_evaluated_blocks_submit_before_fee_check
    """
    engineer = fixtures.create_engineer(api)
    applicant_headers = make_applicant_headers(engineer["id"])
    application = fixtures.create_application(api, engineer["id"])
    fixtures.add_experience_record(api, application["id"], engineer["id"])

    response = api.submit_application(application["id"], applicant_headers)
    validate_error(response, "ERR_EDUCATION_NOT_EVALUATED")

    stored = validate_success(api.get_application(application["id"], applicant_headers))
    assert stored["status"] == "DRAFT"
    assert stored["education_status"] == "NOT_EVALUATED"
    assert stored["submitted_at"] is None
    assert_money_cents(stored["fee_assessment_cents"], 27500)
    assert_money_cents(stored["fee_paid_cents"], 0)


def test_test_center_create_and_read_round_trip(api):
    """PRD §3.1: "The centre's `seat_count` is simply the number of entries in `seat_labels` and is never supplied by the caller; `seats_committed` starts at 0 and `seats_available` starts equal to `seat_count`."

    Design: Corner/endpoints/test_center_create_and_read_round_trip
    """
    created = validate_success(
        api.create_test_center(
            factories.test_center_payload(
                name="Salem Assessment Center",
                state_code="OR",
                seat_labels=["S1", "S2"],
            ),
            BOARD_SECRETARY_HEADERS,
        ),
        201,
    )
    assert created["seat_count"] == 2
    assert_seat_ledger(created, seat_count=2, committed=0, available=2)

    stored = validate_success(api.get_test_center(created["id"], BOARD_SECRETARY_HEADERS))
    assert stored["id"] == created["id"]
    assert stored["name"] == "Salem Assessment Center"
    assert stored["state_code"] == "OR"
    assert stored["seat_labels"] == ["S1", "S2"]
    assert stored["status"] == "OPEN"
    assert stored["version"] == 1
    assert_seat_ledger(stored, seat_count=2, committed=0, available=2)


def test_reinstatement_after_expiry_opens_a_fresh_biennium(api):
    """PRD §3.7: "Both postures return the licence to `ACTIVE` and open a **fresh** biennium measured from the reinstatement instant rather than from the old period end: `current_period_start` becomes the logical clock's current value, `current_period_end` becomes 24 months later, and `renewal_window_opens_at` is recomputed accordingly."

    Design: Corner/endpoints/license_reinstate_after_expiry_opens_fresh_biennium
    """
    engineer, license_ = fixtures.create_licensed_engineer(api)
    old_end = _instant(license_["current_period_end"])

    sweep = fixtures.set_clock(api, SWEEP_INSTANT)
    assert sweep["expired_license_count"] == 1

    expired = validate_success(
        api.get_license(license_["id"], BOARD_LICENSING_OFFICER_HEADERS)
    )
    assert expired["status"] == "EXPIRED"
    assert _instant(expired["reinstatement_eligible_until"]) == old_end + timedelta(
        days=constants.REINSTATEMENT_GRACE_DAYS
    )

    reinstated = validate_success(
        api.reinstate_license(
            license_["id"],
            factories.reinstate_payload(makeup_pdh=15, reinstatement_fee_cents=45000),
            BOARD_LICENSING_OFFICER_HEADERS,
        )
    )
    clock = _instant(SWEEP_INSTANT)
    expected_end = clock.replace(year=clock.year + 2)
    assert reinstated["status"] == "ACTIVE"
    assert _instant(reinstated["current_period_start"]) == clock
    assert _instant(reinstated["current_period_end"]) == expected_end
    assert _instant(reinstated["renewal_window_opens_at"]) == expected_end - timedelta(
        days=constants.RENEWAL_WINDOW_DAYS
    )
    assert reinstated["reinstatement_eligible_until"] is None
    assert reinstated["suspension_ends_at"] is None
    assert reinstated["version"] == expired["version"] + 1

    roster = validate_success(
        api.get_engineer(engineer["id"], BOARD_LICENSING_OFFICER_HEADERS)
    )
    assert_license_number_format(reinstated["license_number"])
    assert roster["active_license_number"] == reinstated["license_number"]


def test_clock_sweep_expires_two_licenses_in_one_pass(api):
    """PRD §2.5: "Second, every `License` in `ACTIVE` whose `current_period_end` falls before the new clock value transitions to `EXPIRED`, has its `reinstatement_eligible_until` stamped"

    Design: Corner/endpoints/clock_sweep_expires_multiple_licenses_in_one_pass
    """
    first_engineer, first_license = fixtures.create_licensed_engineer(api)
    second_engineer, second_license = fixtures.create_licensed_engineer(api)

    sweep = fixtures.set_clock(api, SWEEP_INSTANT)
    assert _instant(sweep["current_utc"]) == _instant(SWEEP_INSTANT)
    assert sweep["expired_license_count"] == 2
    assert sweep["expired_authorization_count"] == 0
    assert sweep["cancelled_appointment_count"] == 0
    assert sweep["expired_firm_count"] == 0
    assert sweep["lapsed_firm_count"] == 0

    for engineer, license_ in (
        (first_engineer, first_license),
        (second_engineer, second_license),
    ):
        stored = validate_success(
            api.get_license(license_["id"], BOARD_LICENSING_OFFICER_HEADERS)
        )
        assert stored["status"] == "EXPIRED"
        assert _instant(stored["reinstatement_eligible_until"]) == _instant(
            license_["current_period_end"]
        ) + timedelta(days=constants.REINSTATEMENT_GRACE_DAYS)
        assert stored["version"] == license_["version"] + 1

        roster = validate_success(
            api.get_engineer(engineer["id"], BOARD_LICENSING_OFFICER_HEADERS)
        )
        assert roster["active_license_number"] is None


def test_reference_request_links_experience_record_and_referee(api):
    """PRD §3.3: "The request opens in `REQUESTED` with `evaluation_score`, `months_confirmed`, `responsibility_confirmed`, `submitted_at` and `recant_reason` all `null`. If the parent file has already been submitted, attaching the request also moves its block from `UNVERIFIED` to `PENDING_VERIFICATION`."

    Design: Corner/endpoints/reference_creation_links_experience_record_and_referee
    """
    applicant = fixtures.create_engineer(api)
    referee = fixtures.create_engineer(api)
    applicant_headers = make_applicant_headers(applicant["id"])
    application = fixtures.create_application(api, applicant["id"])
    record = fixtures.add_experience_record(
        api, application["id"], applicant["id"], employer_name="Vero Structures"
    )

    created = validate_success(
        api.create_reference(
            record["id"],
            factories.reference_payload(referee["id"], relationship="DIRECT_SUPERVISOR"),
            applicant_headers,
        ),
        201,
    )
    assert created["experience_record_id"] == record["id"]
    assert created["referee_engineer_id"] == referee["id"]
    assert created["relationship"] == "DIRECT_SUPERVISOR"
    assert created["status"] == "REQUESTED"
    for field in (
        "evaluation_score",
        "months_confirmed",
        "responsibility_confirmed",
        "submitted_at",
        "recant_reason",
    ):
        assert created[field] is None, f"{field} must open null"
    assert created["version"] == 1

    items, meta = validate_paginated(
        api.list_references(
            BOARD_REVIEWER_HEADERS, params={"experience_record_id": record["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [item["id"] for item in items] == [created["id"]]

    stored_record = validate_success(
        api.get_experience_record(record["id"], applicant_headers)
    )
    assert stored_record["verification_status"] == "UNVERIFIED"
    assert stored_record["credited_months"] == 0


def test_case_close_blocked_while_consent_order_still_proposed(api):
    """PRD §3.9: "A close attempted while the sanction axis sits at `NONE` behind a probable-cause finding, or at `PROPOSED`, is refused with `ERR_OPEN_SANCTION_BLOCKS_CLOSE` (HTTP 409)"

    Design: Corner/endpoints/case_close_blocked_while_sanction_unresolved
    """
    case = fixtures.create_case(
        api,
        allegation_type="UNLICENSED_PRACTICE",
        complainant_name="City of Bend",
        received_on="2026-07-20T00:00:00Z",
        unlicensed_respondent_name="Dell Prine",
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
    assert round(case["penalty_factor"], 2) == 1.0
    assert_money_cents(case["assessed_penalty_cents"], 298000)

    order = fixtures.propose_consent_order(
        api, case["id"], case["version"], sanction_type="REPRIMAND"
    )
    assert order["status"] == "PROPOSED"
    assert_money_cents(order["penalty_cents"], 298000)

    response = api.close_case(case["id"], BOARD_INVESTIGATOR_HEADERS)
    validate_error(response, "ERR_OPEN_SANCTION_BLOCKS_CLOSE")

    stored_case = validate_success(api.get_case(case["id"], BOARD_INVESTIGATOR_HEADERS))
    assert stored_case["investigation_status"] == "PROBABLE_CAUSE"
    assert stored_case["sanction_status"] == "PROPOSED"
    assert_money_cents(stored_case["assessed_penalty_cents"], 298000)

    stored_order = validate_success(
        api.get_consent_order(order["id"], BOARD_INVESTIGATOR_HEADERS)
    )
    assert stored_order["status"] == "PROPOSED"
    assert stored_order["executed_on"] is None
    assert stored_order["executed_by_user_id"] is None
