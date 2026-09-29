"""State transitions of the licensure register: declared edges, initial states,
invalid-transition refusals, the two independent case axes and the bubble-up of
an audit draw, as specified in PRD §3.2, §3.3, §3.4, §3.6, §3.7 and §3.9.
"""

import pytest

from test_helpers import (
    BOARD_INVESTIGATOR_2_HEADERS,
    BOARD_INVESTIGATOR_HEADERS,
    BOARD_LICENSING_OFFICER_HEADERS,
    BOARD_REVIEWER_2_HEADERS,
    BOARD_REVIEWER_HEADERS,
    assert_money_cents,
    assert_pdh_value,
    factories,
    fixtures,
    make_applicant_headers,
    make_board_reviewer_headers,
    make_licensee_headers,
    validate_error,
    validate_success,
)

LICENSE_ISSUED_ON = "2026-01-15T00:00:00Z"
CLOCK_ORIGIN_STAMP = "2026-08-01T00:00:00.000Z"


# ---------------------------------------------------------------------------
# Application review transitions
# ---------------------------------------------------------------------------
def test_start_review_moves_submitted_application_to_under_review(api):
    """PRD §3.4: "A `BoardReviewer` takes possession of a `SUBMITTED` file, advancing it `SUBMITTED → UNDER_REVIEW` and stamping `reviewer_user_id` with the acting `X-User-ID`."

    Design: Corner/state_machines/application_start_review_moves_submitted_to_under_review
    """
    engineer = fixtures.create_engineer(api)
    applicant = make_applicant_headers(engineer["id"])
    application = fixtures.create_application(
        api, engineer["id"], pathway="STANDARD_EXAM", exam_code="PE_CIVIL"
    )
    fixtures.evaluate_education(api, application["id"])
    fixtures.add_experience_record(
        api,
        application["id"],
        engineer["id"],
        period_start_month="2019-01",
        period_end_month="2022-12",
    )
    fixtures.pay_assessed_fee(api, application["id"], engineer["id"])
    submitted = fixtures.submit_application(api, application["id"], engineer["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["reviewer_user_id"] is None

    reviewed = validate_success(
        api.start_review(application["id"], make_board_reviewer_headers("REV-7")), 200
    )
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["reviewer_user_id"] == "REV-7"
    assert reviewed["submitted_at"] == CLOCK_ORIGIN_STAMP

    stored = validate_success(api.get_application(application["id"], applicant), 200)
    assert stored["status"] == "UNDER_REVIEW"
    assert stored["reviewer_user_id"] == "REV-7"
    assert stored["version"] == reviewed["version"]


def test_submit_stamps_clock_promotes_referenced_block_and_freezes_the_fee(api):
    """PRD §3.2: "On success the assessment is recomputed one final time and frozen, `submitted_at` is stamped from the logical clock, every experience block still in `UNVERIFIED` that already carries at least one verification request moves to `PENDING_VERIFICATION`, and `provisional_experience_months` is recomputed."

    Design: Corner/state_machines/application_submit_side_effects_stamp_and_promote_records
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="paid",
        experience_overrides={
            "period_start_month": "2019-01",
            "period_end_month": "2022-12",
        },
        referee_overrides={"license_overrides": {"issued_on": LICENSE_ISSUED_ON}},
    )
    engineer = track["engineer"]
    applicant = make_applicant_headers(engineer["id"])
    application = track["application"]

    submitted = validate_success(api.submit_application(application["id"], applicant), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_at"] == CLOCK_ORIGIN_STAMP
    assert submitted["provisional_experience_months"] == 48
    assert submitted["verified_experience_months"] == 0
    assert_money_cents(submitted["fee_assessment_cents"], 27500)

    record = validate_success(
        api.get_experience_record(track["experience_record"]["id"], applicant), 200
    )
    assert record["verification_status"] == "PENDING_VERIFICATION"
    assert record["raw_months"] == 48
    assert round(float(record["credit_multiplier"]), 2) == 1.0
    assert record["credited_months"] == 0

    reference = validate_success(api.get_reference(track["reference"]["id"], applicant), 200)
    assert reference["status"] == "REQUESTED"


def test_submit_leaves_a_block_carrying_no_verification_request_unverified(api):
    """PRD §3.2: "On success the assessment is recomputed one final time and frozen, `submitted_at` is stamped from the logical clock, every experience block still in `UNVERIFIED` that already carries at least one verification request moves to `PENDING_VERIFICATION`, and `provisional_experience_months` is recomputed."

    Design: Corner/state_machines/application_submit_side_effects_stamp_and_promote_records
    """
    engineer = fixtures.create_engineer(api)
    referee = fixtures.create_engineer(api)
    applicant = make_applicant_headers(engineer["id"])
    application = fixtures.create_application(api, engineer["id"])
    fixtures.evaluate_education(api, application["id"])
    referenced = fixtures.add_experience_record(
        api,
        application["id"],
        engineer["id"],
        period_start_month="2019-01",
        period_end_month="2022-12",
    )
    bare = fixtures.add_experience_record(
        api,
        application["id"],
        engineer["id"],
        period_start_month="2023-01",
        period_end_month="2023-06",
    )
    fixtures.request_reference(api, referenced["id"], engineer["id"], referee["id"])
    fixtures.pay_assessed_fee(api, application["id"], engineer["id"])

    submitted = validate_success(api.submit_application(application["id"], applicant), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["provisional_experience_months"] == 54
    assert_money_cents(submitted["fee_assessment_cents"], 30000)

    promoted = validate_success(api.get_experience_record(referenced["id"], applicant), 200)
    assert promoted["verification_status"] == "PENDING_VERIFICATION"
    untouched = validate_success(api.get_experience_record(bare["id"], applicant), 200)
    assert untouched["verification_status"] == "UNVERIFIED"
    assert untouched["raw_months"] == 6


def test_respond_deficiency_on_an_under_review_file_is_refused(api):
    """PRD §3.2: "Any application transition requested from a status that does not declare it — abandoning an already-issued file, submitting a file that is not `DRAFT`, or a dependent operation demanding a status the file is not in — is refused with `ERR_APPLICATION_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/application_respond_deficiency_from_under_review_returns_invalid_state
    """
    engineer = fixtures.create_engineer(api)
    applicant = make_applicant_headers(engineer["id"])
    application = fixtures.create_application(
        api, engineer["id"], exam_code="PE_MECHANICAL"
    )
    fixtures.evaluate_education(api, application["id"])
    fixtures.add_experience_record(
        api,
        application["id"],
        engineer["id"],
        period_start_month="2019-01",
        period_end_month="2022-12",
    )
    fixtures.pay_assessed_fee(api, application["id"], engineer["id"])
    fixtures.submit_application(api, application["id"], engineer["id"])
    under_review = fixtures.start_review(api, application["id"])
    assert under_review["status"] == "UNDER_REVIEW"

    validate_error(
        api.respond_deficiency(
            application["id"],
            factories.deficiency_response_payload(
                response_note="attaching the missing transcript"
            ),
            applicant,
        ),
        "ERR_APPLICATION_STATE_INVALID",
    )

    stored = validate_success(api.get_application(application["id"], applicant), 200)
    assert stored["status"] == "UNDER_REVIEW"
    assert stored["deficiency_cycle_count"] == 0
    assert stored["deficiency_due_at"] is None
    assert stored["deficiency_reason"] is None
    assert stored["version"] == under_review["version"]


# ---------------------------------------------------------------------------
# Licence renewal self-loop
# ---------------------------------------------------------------------------
def test_renewal_before_the_window_opens_is_refused_and_the_period_does_not_roll(api):
    """PRD §3.7: "The logical clock must fall at or after `renewal_window_opens_at` and at or before `current_period_end`; a request outside that 90-day window at either end is refused with `ERR_RENEWAL_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/state_machines/license_renew_before_window_opens_rejected
    """
    engineer, license_ = fixtures.create_licensed_engineer(
        api, license_overrides={"issued_on": LICENSE_ISSUED_ON}
    )
    licensee = make_licensee_headers(engineer["id"])
    assert license_["status"] == "ACTIVE"
    assert license_["current_period_start"][:10] == "2026-01-15"
    assert license_["current_period_end"][:10] == "2028-01-15"
    assert license_["renewal_window_opens_at"][:10] == "2027-10-17"

    validate_error(
        api.renew_license(license_["id"], licensee), "ERR_RENEWAL_WINDOW_CLOSED"
    )

    stored = validate_success(api.get_license(license_["id"], licensee), 200)
    assert stored["status"] == "ACTIVE"
    assert stored["current_period_start"] == license_["current_period_start"]
    assert stored["current_period_end"] == license_["current_period_end"]
    assert stored["renewal_window_opens_at"] == license_["renewal_window_opens_at"]
    assert stored["version"] == license_["version"]


# ---------------------------------------------------------------------------
# The two independent case axes
# ---------------------------------------------------------------------------
def test_new_case_opens_at_received_on_one_axis_and_none_on_the_other(api):
    """PRD §3.9: "The case opens with `investigation_status` at `RECEIVED`, `sanction_status` at `NONE`, `assigned_investigator_user_id` at `null`, all three factor counts at 0, `penalty_factor` at 0 and `assessed_penalty_cents` at 0, and answers HTTP 201."

    Design: Corner/state_machines/case_starts_received_and_none_on_both_axes
    """
    created = validate_success(
        api.create_case(
            factories.case_payload(
                allegation_type="UNLICENSED_PRACTICE",
                complainant_name="City Building Dept",
                received_on="2026-07-20T00:00:00Z",
                unlicensed_respondent_name="Bram Holt",
            ),
            BOARD_INVESTIGATOR_HEADERS,
        ),
        201,
    )
    assert created["investigation_status"] == "RECEIVED"
    assert created["sanction_status"] == "NONE"
    assert created["assigned_investigator_user_id"] is None
    assert created["aggravating_factor_count"] == 0
    assert created["mitigating_factor_count"] == 0
    assert created["violation_count"] == 0
    assert float(created["penalty_factor"]) == pytest.approx(0.0)
    assert_money_cents(created["assessed_penalty_cents"], 0)
    assert created["version"] == 1

    stored = validate_success(api.get_case(created["id"], BOARD_INVESTIGATOR_HEADERS), 200)
    assert stored["investigation_status"] == "RECEIVED"
    assert stored["sanction_status"] == "NONE"
    assert stored["assigned_investigator_user_id"] is None


def test_second_open_investigation_is_refused_and_keeps_the_first_investigator(api):
    """PRD §3.9: "a transition requested on either axis from a value that does not declare it is refused with `ERR_CASE_STATE_INVALID` (HTTP 409)"

    Design: Corner/state_machines/second_open_investigation_on_same_case_returns_invalid_state
    """
    case = fixtures.create_case(
        api,
        allegation_type="UNLICENSED_PRACTICE",
        complainant_name="Permit Desk",
        received_on="2026-07-05T00:00:00Z",
        unlicensed_respondent_name="Sal Deane",
    )
    investigating = fixtures.open_investigation(api, case["id"])
    assert investigating["investigation_status"] == "INVESTIGATING"
    assert investigating["assigned_investigator_user_id"] == "INV-1"

    validate_error(
        api.open_investigation(case["id"], BOARD_INVESTIGATOR_2_HEADERS),
        "ERR_CASE_STATE_INVALID",
    )

    stored = validate_success(api.get_case(case["id"], BOARD_INVESTIGATOR_HEADERS), 200)
    assert stored["investigation_status"] == "INVESTIGATING"
    assert stored["assigned_investigator_user_id"] == "INV-1"
    assert stored["version"] == investigating["version"]


def test_no_cause_finding_zeroes_the_penalty_and_leaves_the_sanction_axis_at_none(api):
    """PRD §3.9: "A finding of `NO_CAUSE` requires `violation_count` of exactly 0, moves the case `INVESTIGATING → NO_CAUSE`, and sets both `penalty_factor` and `assessed_penalty_cents` to 0 outright: no assessment is run and no plan set is flagged."

    Design: Corner/state_machines/case_axes_independent_no_cause_then_close
    """
    case = fixtures.create_case(
        api,
        allegation_type="UNLICENSED_PRACTICE",
        complainant_name="Neighbour Complaint",
        received_on="2026-07-10T00:00:00Z",
        unlicensed_respondent_name="Tess Rowe",
    )
    fixtures.open_investigation(api, case["id"])

    found = validate_success(
        api.record_finding(
            case["id"],
            factories.finding_payload(
                finding="NO_CAUSE",
                aggravating_factor_count=2,
                mitigating_factor_count=1,
                violation_count=0,
            ),
            BOARD_INVESTIGATOR_HEADERS,
        ),
        200,
    )
    assert found["investigation_status"] == "NO_CAUSE"
    assert found["sanction_status"] == "NONE"
    assert found["aggravating_factor_count"] == 2
    assert found["mitigating_factor_count"] == 1
    assert found["violation_count"] == 0
    assert float(found["penalty_factor"]) == pytest.approx(0.0)
    assert_money_cents(found["assessed_penalty_cents"], 0)

    stored = validate_success(api.get_case(case["id"], BOARD_INVESTIGATOR_HEADERS), 200)
    assert stored["investigation_status"] == "NO_CAUSE"
    assert stored["sanction_status"] == "NONE"
    assert_money_cents(stored["assessed_penalty_cents"], 0)


def test_case_closes_out_of_no_cause_while_the_sanction_axis_never_left_none(api):
    """PRD §3.9: "From `PROBABLE_CAUSE` the sanction axis must have resolved to `CONSENT_EXECUTED` or `HEARING_REFERRED`; from `NO_CAUSE` the sanction axis must still be `NONE`."

    Design: Corner/state_machines/case_axes_independent_no_cause_then_close
    """
    case = fixtures.create_case(
        api,
        allegation_type="UNLICENSED_PRACTICE",
        complainant_name="Neighbour Complaint",
        received_on="2026-07-10T00:00:00Z",
        unlicensed_respondent_name="Tess Rowe",
    )
    fixtures.open_investigation(api, case["id"])
    fixtures.record_finding(
        api,
        case["id"],
        finding="NO_CAUSE",
        aggravating_factor_count=2,
        mitigating_factor_count=1,
        violation_count=0,
    )

    closed = validate_success(api.close_case(case["id"], BOARD_INVESTIGATOR_HEADERS), 200)
    assert closed["investigation_status"] == "CLOSED"
    assert closed["sanction_status"] == "NONE"

    stored = validate_success(api.get_case(case["id"], BOARD_INVESTIGATOR_HEADERS), 200)
    assert stored["investigation_status"] == "CLOSED"
    assert stored["sanction_status"] == "NONE"


# ---------------------------------------------------------------------------
# Terminal consent-order posture
# ---------------------------------------------------------------------------
def test_executing_a_superseded_consent_order_is_refused(api):
    """PRD §3.9: "The order must stand in `PROPOSED` and the case's `sanction_status` must stand at `PROPOSED`; otherwise the request is refused with `ERR_CONSENT_ORDER_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/consent_order_execute_from_superseded_returns_invalid_state
    """
    case = fixtures.create_case(
        api,
        allegation_type="UNLICENSED_PRACTICE",
        complainant_name="Anonymous Tip Line",
        received_on="2026-07-01T00:00:00Z",
        unlicensed_respondent_name="Vic Marlow",
    )
    fixtures.open_investigation(api, case["id"])
    at_cause = fixtures.record_finding(
        api,
        case["id"],
        finding="PROBABLE_CAUSE",
        aggravating_factor_count=0,
        mitigating_factor_count=0,
        violation_count=1,
    )
    assert at_cause["investigation_status"] == "PROBABLE_CAUSE"
    assert_money_cents(at_cause["assessed_penalty_cents"], 298000)

    order = fixtures.propose_consent_order(
        api,
        case["id"],
        at_cause["version"],
        sanction_type="REPRIMAND",
        suspension_months=0,
        penalty_paid_cents=298000,
    )
    assert order["status"] == "PROPOSED"
    assert_money_cents(order["penalty_cents"], 298000)

    referred = fixtures.refer_hearing(api, case["id"])
    assert referred["sanction_status"] == "HEARING_REFERRED"

    validate_error(
        api.execute_consent_order(
            order["id"],
            factories.execute_payload(executed_on="2026-08-01T00:00:00Z"),
            BOARD_LICENSING_OFFICER_HEADERS,
        ),
        "ERR_CONSENT_ORDER_STATE_INVALID",
    )

    stored_order = validate_success(
        api.get_consent_order(order["id"], BOARD_LICENSING_OFFICER_HEADERS), 200
    )
    assert stored_order["status"] == "SUPERSEDED"
    assert stored_order["executed_on"] is None
    assert stored_order["executed_by_user_id"] is None
    assert_money_cents(stored_order["penalty_cents"], 298000)

    stored_case = validate_success(
        api.get_case(case["id"], BOARD_LICENSING_OFFICER_HEADERS), 200
    )
    assert stored_case["sanction_status"] == "HEARING_REFERRED"
    assert stored_case["investigation_status"] == "PROBABLE_CAUSE"


# ---------------------------------------------------------------------------
# Audit bubble-up and reference rejection
# ---------------------------------------------------------------------------
def test_deciding_the_last_report_under_audit_closes_the_draw(api):
    """PRD §3.6: "When the decision leaves no report of that draw still standing in `UNDER_AUDIT`, the draw itself bubbles up `SAMPLED → CLOSED`."

    Design: Corner/state_machines/cpc_audit_closes_when_last_report_decided
    """
    setup = fixtures.setup_cleared_cpc_report(
        api, license_overrides={"issued_on": LICENSE_ISSUED_ON}
    )
    engineer = setup["engineer"]
    license_ = setup["license"]
    report = setup["report"]
    assert report["status"] == "ACCEPTED"

    audit = fixtures.draw_audit(
        api,
        headers=BOARD_REVIEWER_HEADERS,
        sample_pct=1.0,
        as_of_period_end=license_["current_period_end"],
    )
    assert audit["status"] == "SAMPLED"
    assert audit["pool_size"] == 1
    assert audit["sampled_count"] == 1

    drawn = validate_success(
        api.get_cpc_report(report["id"], BOARD_REVIEWER_HEADERS), 200
    )
    assert drawn["status"] == "UNDER_AUDIT"
    assert drawn["audit_id"] == audit["id"]
    assert_pdh_value(drawn["audit_verified_total_pdh"], 0.0)

    decided = validate_success(
        api.audit_decision(report["id"], {"decision": "DEFICIENT"}, BOARD_REVIEWER_2_HEADERS),
        200,
    )
    assert decided["status"] == "AUDIT_DEFICIENT"
    assert_pdh_value(decided["audit_verified_total_pdh"], 0.0)
    assert_pdh_value(decided["shortfall_pdh"], 32.0)
    assert decided["audit_decided_by_user_id"] == "REV-2"

    closed = validate_success(api.get_cpc_audit(audit["id"], BOARD_REVIEWER_HEADERS), 200)
    assert closed["status"] == "CLOSED"
    assert closed["pool_size"] == 1
    assert closed["sampled_count"] == 1

    stored_license = validate_success(
        api.get_license(license_["id"], make_licensee_headers(engineer["id"])), 200
    )
    assert stored_license["discipline_flag"] is True


def test_rejecting_a_reference_disputes_its_block_and_zeroes_the_credit(api):
    """PRD §3.3: "Rejecting moves the request `SUBMITTED → REJECTED` and takes the other path entirely: the block moves `PENDING_VERIFICATION → DISPUTED`, its `credited_months` is forced to 0, and the file's `verified_experience_months` is recomputed — which will now be lower."

    Design: Corner/state_machines/reference_reject_disputes_experience_record_and_zeroes_credit
    """
    track = fixtures.setup_exam_track(
        api,
        stop_after="reference_submitted",
        experience_overrides={
            "period_start_month": "2019-01",
            "period_end_month": "2022-12",
        },
        submission_overrides={
            "evaluation_score": 4,
            "months_confirmed": 48,
            "responsibility_confirmed": True,
        },
        referee_overrides={"license_overrides": {"issued_on": LICENSE_ISSUED_ON}},
    )
    engineer = track["engineer"]
    applicant = make_applicant_headers(engineer["id"])
    assert track["reference"]["status"] == "SUBMITTED"

    rejected = validate_success(
        api.evaluate_reference(
            track["reference"]["id"], {"decision": "REJECT"}, BOARD_REVIEWER_HEADERS
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"

    record = validate_success(
        api.get_experience_record(track["experience_record"]["id"], applicant), 200
    )
    assert record["verification_status"] == "DISPUTED"
    assert record["credited_months"] == 0

    application = validate_success(
        api.get_application(track["application"]["id"], applicant), 200
    )
    assert application["verified_experience_months"] == 0
    assert application["provisional_experience_months"] == 48
