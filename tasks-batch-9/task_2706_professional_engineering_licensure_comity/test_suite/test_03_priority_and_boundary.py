"""Rejection-ladder priority between competing rules, and the exact numeric thresholds.

Covers the ordering the board fixes when one request violates two rules at once —
application state before the application fee gate, seal-licence activity before
responsible-charge identity, and the buffered seat calendar before aggregate
capacity — together with the three thresholds probed from both sides: the
48-month experience floor, the 45-minute seat turnover buffer, and the equality
between a competency report's period end and an audit draw's period end.
"""

from test_helpers import (
    BOARD_LICENSING_OFFICER_HEADERS,
    BOARD_LICENSING_OFFICER_2_HEADERS,
    BOARD_REVIEWER_HEADERS,
    BOARD_SECRETARY_HEADERS,
    assert_money_cents,
    assert_pdh_value,
    assert_seat_ledger,
    assert_version_is,
    factories,
    fixtures,
    make_applicant_headers,
    make_licensee_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# The clock every freshly launched server reports until a secretary moves it.
INITIAL_CLOCK_DATE = "2026-08-01T00:00:00"
# 365 days after the initial clock, the envelope a fresh authorization carries.
AUTHORIZATION_EXPIRY_DATE = "2027-08-01T00:00:00"
# 25,000 base charge plus one 2,500-cent experience block, no expedite, no discount.
ONE_BLOCK_STANDARD_FEE_CENTS = 27500
# 150,000 negligence base plus 48,000 cost recovery, both at a factor of 1.00.
NEGLIGENCE_NO_FACTOR_PENALTY_CENTS = 198000


# ---------------------------------------------------------------------------
# Local read helpers: each re-reads a row through the public API so that
# side effects are observed rather than inferred from the trigger response.
# ---------------------------------------------------------------------------
def _read_application(api, application_id, engineer_id):
    return validate_success(
        api.get_application(application_id, make_applicant_headers(engineer_id)), 200
    )


def _read_license(api, license_id):
    return validate_success(
        api.get_license(license_id, BOARD_LICENSING_OFFICER_HEADERS), 200
    )


def _read_experience_record(api, experience_record_id):
    return validate_success(
        api.get_experience_record(experience_record_id, BOARD_REVIEWER_HEADERS), 200
    )


def _read_test_center(api, test_center_id):
    return validate_success(
        api.get_test_center(test_center_id, BOARD_SECRETARY_HEADERS), 200
    )


def _read_authorization(api, exam_authorization_id):
    return validate_success(
        api.get_exam_authorization(exam_authorization_id, BOARD_REVIEWER_HEADERS), 200
    )


def _read_appointment(api, exam_appointment_id):
    return validate_success(
        api.get_exam_appointment(exam_appointment_id, BOARD_SECRETARY_HEADERS), 200
    )


def _read_plan(api, plan_submission_id):
    return validate_success(
        api.get_plan_submission(plan_submission_id, BOARD_LICENSING_OFFICER_HEADERS), 200
    )


def _read_firm(api, firm_registration_id):
    return validate_success(
        api.get_firm_registration(firm_registration_id, BOARD_LICENSING_OFFICER_HEADERS),
        200,
    )


def _read_cpc_report(api, cpc_report_id):
    return validate_success(
        api.get_cpc_report(cpc_report_id, BOARD_REVIEWER_HEADERS), 200
    )


# ---------------------------------------------------------------------------
# Submitting a file: the state of the file is decided before the money.
# ---------------------------------------------------------------------------
def test_submit_withdrawn_and_unpaid_file_reports_state_not_fee(api):
    """PRD §3.2: "underpayment is refused with `ERR_FEE_UNPAID` (HTTP 402), which sits at the very bottom of the rejection ladder so that every structural and eligibility problem surfaces before the money question"

    Design: Difficulty/priority_pair_validation_conflict/submit_state_invalid_outranks_fee_unpaid
    """
    engineer = fixtures.create_engineer(api, full_name="Lior Banda")
    application = fixtures.create_application(api, engineer["id"])
    fixtures.evaluate_education(api, application["id"])
    fixtures.add_experience_record(api, application["id"], engineer["id"])

    withdrawn = validate_success(
        api.withdraw_application(
            application["id"], make_applicant_headers(engineer["id"])
        ),
        200,
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert_money_cents(withdrawn["fee_assessment_cents"], ONE_BLOCK_STANDARD_FEE_CENTS)
    assert_money_cents(withdrawn["fee_paid_cents"], 0)

    # The file is terminal AND entirely unpaid: the terminal state is reported.
    response = api.submit_application(
        application["id"], make_applicant_headers(engineer["id"])
    )
    validate_error(response, "ERR_APPLICATION_STATE_INVALID")

    after = _read_application(api, application["id"], engineer["id"])
    assert after["status"] == "WITHDRAWN"
    assert after["submitted_at"] is None
    assert_money_cents(after["fee_assessment_cents"], ONE_BLOCK_STANDARD_FEE_CENTS)
    assert_money_cents(after["fee_paid_cents"], 0)


def test_submit_unpaid_draft_file_reports_the_fee_gate_on_its_own(api):
    """PRD §3.2: "And `fee_paid_cents` must be at least `fee_assessment_cents`; underpayment is refused with `ERR_FEE_UNPAID` (HTTP 402)"

    Design: Difficulty/priority_pair_validation_conflict/submit_state_invalid_outranks_fee_unpaid
    """
    engineer = fixtures.create_engineer(api, full_name="Lior Banda")
    application = fixtures.create_application(api, engineer["id"])
    fixtures.evaluate_education(api, application["id"])
    fixtures.add_experience_record(api, application["id"], engineer["id"])

    draft = _read_application(api, application["id"], engineer["id"])
    assert draft["status"] == "DRAFT"
    assert_money_cents(draft["fee_assessment_cents"], ONE_BLOCK_STANDARD_FEE_CENTS)
    assert_money_cents(draft["fee_paid_cents"], 0)

    # Nothing else is wrong with the file, so the money question surfaces.
    response = api.submit_application(
        application["id"], make_applicant_headers(engineer["id"])
    )
    validate_error(response, "ERR_FEE_UNPAID")

    unchanged = _read_application(api, application["id"], engineer["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["submitted_at"] is None

    # Remitting exactly the assessment clears the one remaining objection.
    validate_success(
        api.pay_application(
            application["id"],
            factories.payment_payload(ONE_BLOCK_STANDARD_FEE_CENTS),
            make_applicant_headers(engineer["id"]),
        ),
        200,
    )
    submitted = validate_success(
        api.submit_application(
            application["id"], make_applicant_headers(engineer["id"])
        ),
        200,
    )
    assert submitted["status"] == "SUBMITTED"
    assert_money_cents(submitted["fee_paid_cents"], ONE_BLOCK_STANDARD_FEE_CENTS)
    assert submitted["provisional_experience_months"] == 48
    assert submitted["submitted_at"].startswith(INITIAL_CLOCK_DATE)


# ---------------------------------------------------------------------------
# Sealing a plan set: the public-safety objection outranks the identity one.
# ---------------------------------------------------------------------------
def test_seal_by_revoked_outsider_reports_licence_not_active(api):
    """PRD §3.8: "The consequence is that a revoked outsider who tries to stamp a firm's drawings is told their licence is not active — the public-safety objection — rather than that they are not the firm's responsible charge, even though both statements are true."

    Design: Difficulty/priority_pair_validation_conflict/seal_license_not_active_outranks_not_responsible_charge
    """
    # An outsider whose licence is revoked by an executed revocation order.
    outsider = fixtures.setup_case_at_probable_cause(
        api, finding_overrides={"aggravating_factor_count": 0}
    )
    assert_money_cents(
        outsider["case"]["assessed_penalty_cents"], NEGLIGENCE_NO_FACTOR_PENALTY_CENTS
    )
    order = fixtures.propose_consent_order(
        api,
        outsider["case"]["id"],
        outsider["case"]["version"],
        sanction_type="REVOCATION",
        penalty_paid_cents=NEGLIGENCE_NO_FACTOR_PENALTY_CENTS,
    )
    assert_money_cents(order["penalty_cents"], NEGLIGENCE_NO_FACTOR_PENALTY_CENTS)
    fixtures.execute_consent_order(api, order["id"])

    revoked = _read_license(api, outsider["license"]["id"])
    assert revoked["status"] == "REVOKED"

    # A firm behind a different, ACTIVE responsible-charge licence, with a
    # draft set filed after the revocation so no void cascade touched it.
    host = fixtures.setup_firm_with_draft_plan(api, plan_overrides={"sheet_count": 5})
    assert _read_firm(api, host["firm"]["id"])["status"] == "ACTIVE"

    # The outsider is revoked AND is not the firm's responsible charge.
    response = api.seal_plan_submission(
        host["plan"]["id"],
        factories.seal_payload(
            outsider["license"]["id"], responsible_charge_attested=True
        ),
        make_licensee_headers(outsider["engineer"]["id"]),
    )
    validate_error(response, "ERR_SEAL_LICENSE_NOT_ACTIVE")

    plan = _read_plan(api, host["plan"]["id"])
    assert plan["status"] == "DRAFT"
    assert plan["sealing_license_id"] is None
    assert plan["seal_affixed_at"] is None
    assert plan["responsible_charge_attested"] is False
    assert_version_is(plan, 1)


def test_seal_by_active_outsider_reports_not_responsible_charge_on_its_own(api):
    """PRD §3.8: "Only then, at rung 14, must the sealing licence be the very licence the firm holds in responsible charge, otherwise `ERR_NOT_RESPONSIBLE_CHARGE` (HTTP 422)"

    Design: Difficulty/priority_pair_validation_conflict/seal_license_not_active_outranks_not_responsible_charge
    """
    outsider, outsider_license = fixtures.create_licensed_engineer(api)
    assert outsider_license["status"] == "ACTIVE"

    host = fixtures.setup_firm_with_draft_plan(api, plan_overrides={"sheet_count": 5})
    assert host["firm"]["responsible_charge_license_id"] == host["license"]["id"]

    # The seal licence is ACTIVE, so only the identity objection remains.
    response = api.seal_plan_submission(
        host["plan"]["id"],
        factories.seal_payload(outsider_license["id"], responsible_charge_attested=True),
        make_licensee_headers(outsider["id"]),
    )
    validate_error(response, "ERR_NOT_RESPONSIBLE_CHARGE")

    plan = _read_plan(api, host["plan"]["id"])
    assert plan["status"] == "DRAFT"
    assert plan["sealing_license_id"] is None
    assert plan["seal_affixed_at"] is None
    assert_version_is(plan, 1)

    # The firm's own responsible charge seals the very same set.
    sealed = validate_success(
        api.seal_plan_submission(
            host["plan"]["id"],
            factories.seal_payload(
                host["license"]["id"], responsible_charge_attested=True
            ),
            make_licensee_headers(host["engineer"]["id"]),
        ),
        200,
    )
    assert sealed["status"] == "SEALED"
    assert sealed["sealing_license_id"] == host["license"]["id"]
    assert sealed["seal_affixed_at"].startswith(INITIAL_CLOCK_DATE)


# ---------------------------------------------------------------------------
# Booking a seat: the seat's own calendar is consulted before capacity.
# ---------------------------------------------------------------------------
_VERIFIED_REFERENCE = {"responsibility_confirmed": True}


def test_booking_that_collides_at_a_full_centre_reports_the_seat_window(api):
    """PRD §3.5: "Only then is the seat's own calendar consulted, and only then is aggregate capacity consulted."

    Design: Difficulty/priority_pair_validation_conflict/seat_window_conflict_outranks_no_seat_available
    """
    booked = fixtures.setup_scheduled_appointment(
        api,
        center_overrides={"seat_labels": ["S1"]},
        submission_overrides=_VERIFIED_REFERENCE,
    )
    center = _read_test_center(api, booked["test_center"]["id"])
    assert_seat_ledger(center, seat_count=1, committed=1, available=0)

    rival = fixtures.setup_exam_track(
        api, stop_after="exam_approved", submission_overrides=_VERIFIED_REFERENCE
    )

    # The one seat is both taken for the day and exhausted as capacity.
    response = api.create_exam_appointment(
        factories.exam_appointment_payload(
            rival["authorization"]["id"],
            booked["test_center"]["id"],
            seat_label="S1",
            window_start="2026-10-05T13:00:00Z",
            window_end="2026-10-05T21:00:00Z",
        ),
        make_applicant_headers(rival["engineer"]["id"]),
    )
    validate_error(response, "ERR_SEAT_WINDOW_CONFLICT")

    assert_seat_ledger(
        _read_test_center(api, booked["test_center"]["id"]),
        seat_count=1,
        committed=1,
        available=0,
    )
    assert (
        _read_authorization(api, rival["authorization"]["id"])["status"]
        == "APPROVED_TO_SIT"
    )
    assert _read_appointment(api, booked["appointment"]["id"])["status"] == "SCHEDULED"


def test_booking_at_a_full_centre_without_collision_reports_no_seat_available(api):
    """PRD §3.5: "The centre must have `seats_available` of at least 1 and must stand in `OPEN`; a full centre or a `SUSPENDED` one is refused with `ERR_NO_SEAT_AVAILABLE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/seat_window_conflict_outranks_no_seat_available
    """
    booked = fixtures.setup_scheduled_appointment(
        api,
        center_overrides={"seat_labels": ["S1"]},
        submission_overrides=_VERIFIED_REFERENCE,
    )
    rival = fixtures.setup_exam_track(
        api, stop_after="exam_approved", submission_overrides=_VERIFIED_REFERENCE
    )

    # A month later on the same seat: no interval collision, but no capacity.
    response = api.create_exam_appointment(
        factories.exam_appointment_payload(
            rival["authorization"]["id"],
            booked["test_center"]["id"],
            seat_label="S1",
            window_start="2026-11-05T09:00:00Z",
            window_end="2026-11-05T17:00:00Z",
        ),
        make_applicant_headers(rival["engineer"]["id"]),
    )
    validate_error(response, "ERR_NO_SEAT_AVAILABLE")

    assert_seat_ledger(
        _read_test_center(api, booked["test_center"]["id"]),
        seat_count=1,
        committed=1,
        available=0,
    )
    assert (
        _read_authorization(api, rival["authorization"]["id"])["status"]
        == "APPROVED_TO_SIT"
    )
    items, meta = validate_paginated(
        api.list_exam_appointments(
            BOARD_SECRETARY_HEADERS,
            params={"test_center_id": booked["test_center"]["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert items[0]["id"] == booked["appointment"]["id"]


# ---------------------------------------------------------------------------
# The 48-month experience floor, probed at 47 and at exactly 48.
# ---------------------------------------------------------------------------
_FORTY_SEVEN_MONTH_BLOCK = {
    "employer_name": "Elder Geotechnical",
    "position_title": "Engineer in Responsible Charge",
    "period_start_month": "2019-02",
    "period_end_month": "2022-12",
    "responsibility_level": "RESPONSIBLE_CHARGE",
    "post_degree": True,
}


def _file_at_forty_seven_credited_months(api):
    """One examination file whose sole block credits exactly 47 months."""
    track = fixtures.setup_exam_track(
        api,
        stop_after="credit_determined",
        experience_overrides=_FORTY_SEVEN_MONTH_BLOCK,
        submission_overrides={"responsibility_confirmed": True, "months_confirmed": 47},
    )
    record = _read_experience_record(api, track["experience_record"]["id"])
    assert record["raw_months"] == 47
    assert round(float(record["credit_multiplier"]), 2) == 1.0
    assert record["credited_months"] == 47
    assert record["verification_status"] == "VERIFIED"
    assert track["application"]["verified_experience_months"] == 47
    return track


def test_exam_approval_at_forty_seven_credited_months_is_refused(api):
    """PRD §3.4: "a file at 47 months is refused with `ERR_EXPERIENCE_INSUFFICIENT` (HTTP 422), while a file at exactly 48 passes."

    Design: Difficulty/boundary_precision_check/min_experience_months_boundary_47_then_48
    """
    track = _file_at_forty_seven_credited_months(api)

    response = api.approve_exam(
        track["application"]["id"], BOARD_LICENSING_OFFICER_2_HEADERS
    )
    validate_error(response, "ERR_EXPERIENCE_INSUFFICIENT")

    after = _read_application(
        api, track["application"]["id"], track["engineer"]["id"]
    )
    assert after["status"] == "UNDER_REVIEW"
    assert after["verified_experience_months"] == 47
    items, meta = validate_paginated(
        api.list_exam_authorizations(
            BOARD_REVIEWER_HEADERS,
            params={"application_id": track["application"]["id"]},
        )
    )
    assert meta["total_count"] == 0
    assert items == []


def test_exam_approval_at_exactly_forty_eight_credited_months_succeeds(api):
    """PRD §3.4: "And `verified_experience_months` must be at least 48; a file at 47 months is refused with `ERR_EXPERIENCE_INSUFFICIENT` (HTTP 422), while a file at exactly 48 passes."

    Design: Difficulty/boundary_precision_check/min_experience_months_boundary_47_then_48
    """
    track = _file_at_forty_seven_credited_months(api)
    application_id = track["application"]["id"]
    engineer_id = track["engineer"]["id"]
    referee_id = track["referee"]["id"]

    # One further verified month lands the file exactly on the floor.
    extra = fixtures.add_experience_record(
        api,
        application_id,
        engineer_id,
        employer_name="Elder Geotechnical",
        position_title="Engineer in Responsible Charge",
        period_start_month="2023-01",
        period_end_month="2023-01",
        responsibility_level="RESPONSIBLE_CHARGE",
        post_degree=True,
    )
    assert extra["raw_months"] == 1
    reference = fixtures.request_reference(api, extra["id"], engineer_id, referee_id)
    fixtures.submit_reference(
        api,
        reference["id"],
        referee_id,
        evaluation_score=4,
        months_confirmed=1,
        responsibility_confirmed=True,
    )
    fixtures.evaluate_reference(api, reference["id"], "ACCEPT")
    assert _read_experience_record(api, extra["id"])["credited_months"] == 1

    determined = fixtures.determine_credit(api, application_id)
    assert determined["verified_experience_months"] == 48

    authorization = validate_success(
        api.approve_exam(application_id, BOARD_LICENSING_OFFICER_2_HEADERS), 201
    )
    assert authorization["status"] == "APPROVED_TO_SIT"
    assert authorization["attempt_number"] == 1
    assert authorization["exam_code"] == "PE_CIVIL"
    assert authorization["result"] == "PENDING"
    assert authorization["raw_score"] is None
    assert authorization["retake_eligible_at"] is None
    assert authorization["ncees_transmission_id"] is None
    assert authorization["authorization_expires_at"].startswith(
        AUTHORIZATION_EXPIRY_DATE
    )

    after = _read_application(api, application_id, engineer_id)
    assert after["status"] == "EXAM_APPROVED"
    assert after["verified_experience_months"] == 48
    assert_money_cents(after["fee_assessment_cents"], ONE_BLOCK_STANDARD_FEE_CENTS)
    assert_money_cents(after["fee_paid_cents"], ONE_BLOCK_STANDARD_FEE_CENTS)


# ---------------------------------------------------------------------------
# The 45-minute trailing turnover buffer, probed at 44 and at exactly 45.
# ---------------------------------------------------------------------------
def _seat_s1_taken_until_five(api):
    """A two-seat centre whose seat S1 is booked 09:00-17:00, plus a rival."""
    booked = fixtures.setup_scheduled_appointment(
        api, submission_overrides=_VERIFIED_REFERENCE
    )
    center = _read_test_center(api, booked["test_center"]["id"])
    assert_seat_ledger(center, seat_count=2, committed=1, available=1)
    assert booked["appointment"]["seat_label"] == "S1"
    rival = fixtures.setup_exam_track(
        api, stop_after="exam_approved", submission_overrides=_VERIFIED_REFERENCE
    )
    return booked, rival


def test_booking_forty_four_minutes_after_a_window_collides(api):
    """PRD §3.5: "Each existing appointment on the same centre and the same `seat_label` that still stands in `SCHEDULED` is inflated by appending 45 minutes to its `window_end`; the new booking collides with it when the new `window_start` falls strictly before that inflated end **and** the new booking's own inflated end falls strictly after the existing `window_start`."

    Design: Difficulty/boundary_precision_check/seat_turnover_buffer_boundary_44_then_45_minutes
    """
    booked, rival = _seat_s1_taken_until_five(api)

    response = api.create_exam_appointment(
        factories.exam_appointment_payload(
            rival["authorization"]["id"],
            booked["test_center"]["id"],
            seat_label="S1",
            window_start="2026-10-05T17:44:00Z",
            window_end="2026-10-06T01:44:00Z",
        ),
        make_applicant_headers(rival["engineer"]["id"]),
    )
    validate_error(response, "ERR_SEAT_WINDOW_CONFLICT")

    assert_seat_ledger(
        _read_test_center(api, booked["test_center"]["id"]),
        seat_count=2,
        committed=1,
        available=1,
    )
    assert (
        _read_authorization(api, rival["authorization"]["id"])["status"]
        == "APPROVED_TO_SIT"
    )
    assert _read_appointment(api, booked["appointment"]["id"])["status"] == "SCHEDULED"


def test_booking_exactly_forty_five_minutes_after_a_window_is_accepted(api):
    """PRD §3.5: "Because both comparisons are strict, a booking starting exactly 45 minutes after an existing window's end does not collide, while one starting 44 minutes after it does."

    Design: Difficulty/boundary_precision_check/seat_turnover_buffer_boundary_44_then_45_minutes
    """
    booked, rival = _seat_s1_taken_until_five(api)

    appointment = validate_success(
        api.create_exam_appointment(
            factories.exam_appointment_payload(
                rival["authorization"]["id"],
                booked["test_center"]["id"],
                seat_label="S1",
                window_start="2026-10-05T17:45:00Z",
                window_end="2026-10-06T01:45:00Z",
            ),
            make_applicant_headers(rival["engineer"]["id"]),
        ),
        201,
    )
    assert appointment["status"] == "SCHEDULED"
    assert appointment["seat_label"] == "S1"
    assert appointment["test_center_id"] == booked["test_center"]["id"]

    assert (
        _read_authorization(api, rival["authorization"]["id"])["status"] == "SCHEDULED"
    )
    assert _read_appointment(api, booked["appointment"]["id"])["status"] == "SCHEDULED"
    assert_seat_ledger(
        _read_test_center(api, booked["test_center"]["id"]),
        seat_count=2,
        committed=2,
        available=0,
    )


# ---------------------------------------------------------------------------
# Audit eligibility: the pool keys on period_end EQUALLING as_of_period_end.
# ---------------------------------------------------------------------------
def _accepted_report_for_the_2028_period(api):
    """One ACCEPTED report, shortfall 0, covering the period ending 2028-01-15."""
    cleared = fixtures.setup_cleared_cpc_report(api)
    report = _read_cpc_report(api, cleared["report"]["id"])
    assert report["status"] == "ACCEPTED"
    assert report["audit_id"] is None
    assert str(report["period_end"]).startswith("2028-01-15")
    assert_pdh_value(report["self_certified_total_pdh"], 30.0)
    assert_pdh_value(report["shortfall_pdh"], 0.0)
    assert _read_license(api, cleared["license"]["id"])["status"] == "ACTIVE"
    return report


def test_audit_draw_one_day_past_the_period_end_finds_an_empty_pool(api):
    """PRD §3.6: "If nothing qualifies, the draw is refused with `ERR_AUDIT_POOL_EMPTY` (HTTP 409) and no audit row is persisted at all."

    Design: Difficulty/boundary_precision_check/audit_pool_period_end_exact_match_boundary
    """
    report = _accepted_report_for_the_2028_period(api)
    label = factories.unique_audit_cycle_label()
    one_day_late = str(report["period_end"]).replace("2028-01-15", "2028-01-16")

    response = api.create_cpc_audit(
        factories.cpc_audit_payload(
            audit_cycle_label=label, sample_pct=0.20, as_of_period_end=one_day_late
        ),
        BOARD_SECRETARY_HEADERS,
    )
    validate_error(response, "ERR_AUDIT_POOL_EMPTY")

    _, meta = validate_paginated(api.list_cpc_audits(BOARD_SECRETARY_HEADERS))
    assert meta["total_count"] == 0
    untouched = _read_cpc_report(api, report["id"])
    assert untouched["status"] == "ACCEPTED"
    assert untouched["audit_id"] is None

    # Nothing was persisted, so the very same label is still free to use.
    retry = validate_success(
        api.create_cpc_audit(
            factories.cpc_audit_payload(
                audit_cycle_label=label,
                sample_pct=0.20,
                as_of_period_end=report["period_end"],
            ),
            BOARD_SECRETARY_HEADERS,
        ),
        201,
    )
    assert retry["status"] == "SAMPLED"
    assert retry["audit_cycle_label"] == label


def test_audit_draw_exactly_on_the_period_end_samples_the_whole_pool(api):
    """PRD §3.6: "A report enters the pool when it stands in `ACCEPTED`, its `period_end` equals the draw's `as_of_period_end`, its `audit_id` is still `null`, and the licence it covers stands in `ACTIVE` or `EXPIRED`"

    Design: Difficulty/boundary_precision_check/audit_pool_period_end_exact_match_boundary
    """
    report = _accepted_report_for_the_2028_period(api)
    label = factories.unique_audit_cycle_label()

    audit = validate_success(
        api.create_cpc_audit(
            factories.cpc_audit_payload(
                audit_cycle_label=label,
                sample_pct=0.20,
                as_of_period_end=report["period_end"],
            ),
            BOARD_SECRETARY_HEADERS,
        ),
        201,
    )
    assert audit["pool_size"] == 1
    assert audit["sampled_count"] == 1
    assert audit["status"] == "SAMPLED"
    assert audit["audit_cycle_label"] == label

    drawn = _read_cpc_report(api, report["id"])
    assert drawn["status"] == "UNDER_AUDIT"
    assert drawn["audit_id"] == audit["id"]
    assert_pdh_value(drawn["self_certified_total_pdh"], 30.0)
    assert_pdh_value(drawn["audit_verified_total_pdh"], 0.0)

    _, audit_meta = validate_paginated(api.list_cpc_audits(BOARD_SECRETARY_HEADERS))
    assert audit_meta["total_count"] == 1
    items, report_meta = validate_paginated(
        api.list_cpc_reports(BOARD_REVIEWER_HEADERS, params={"audit_id": audit["id"]})
    )
    assert report_meta["total_count"] == 1
    assert items[0]["id"] == report["id"]
