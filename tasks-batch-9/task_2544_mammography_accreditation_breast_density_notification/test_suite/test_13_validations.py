"""Validations: each declared rule violated in isolation, plus the happy path
that must clear every guard."""

import pytest

from test_helpers import (
    acquire_and_interpret,
    acquire_exam,
    add_personnel,
    add_second_radiologist,
    assert_coverage,
    assert_facility_ledger,
    assert_instant_equals,
    assert_personnel_state,
    audit_cycle_payload,
    close_cycle_payload,
    complete_order,
    create_facility,
    determine_coverage,
    exam_payload,
    funding_deposit_payload,
    generate_letter,
    interpret_payload,
    list_total_count,
    make_technologist_headers,
    minimal_state_policy_payload,
    open_cycle,
    packet_payload,
    personnel_payload,
    read_cycle,
    read_exam,
    read_facility,
    read_order,
    read_personnel,
    read_unit,
    recommend_order,
    run_compliance,
    run_qualification_review,
    schedule_payload,
    send_letter,
    set_clock,
    setup_two_interpreted_exams,
    supplemental_order_payload,
    unit_payload,
    unit_version,
    validate_error,
    validate_success,
)


def test_invalid_request_rejects_out_of_range_values_and_mispaired_credit_fields(
    api, core, coordinator_headers
):
    """One rule, four faces: enum range, minimum count, state-code shape and field pairing.

    PRD: "**Request schema (priority 20)** — required body fields present, enum
    values in range, numeric ranges honored, state codes exactly two uppercase
    letters, and conditional field pairings satisfied: `ERR_INVALID_REQUEST`, 400."

    Design: Corner/validations/invalid_request_rejects_out_of_range_values_and_mispaired_credit_fields
    """
    exam = acquire_exam(core, patient_ref="PT-IR-1", performed_at="2026-07-20T00:00:00Z")

    validate_error(
        api.interpret_exam(
            exam["id"], {"birads_assessment": 7, "density_category": "C"}, core["rad_headers"]
        ),
        "ERR_INVALID_REQUEST",
        expected_status=400,
    )
    validate_error(
        api.create_exam(
            exam_payload(
                core["unit_id"], core["tech_id"], patient_ref="PT-IR-2", original_image_count=0
            ),
            core["tech_headers"],
        ),
        "ERR_INVALID_REQUEST",
        expected_status=400,
    )
    validate_error(
        api.create_exam(
            exam_payload(
                core["unit_id"], core["tech_id"], patient_ref="PT-IR-3", patient_state_code="Ct"
            ),
            core["tech_headers"],
        ),
        "ERR_INVALID_REQUEST",
        expected_status=400,
    )
    validate_error(
        api.create_credit(
            core["tech_id"],
            {"credit_type": "READ_VOLUME", "awarded_on": "2026-01-10T00:00:00Z", "ce_hours": 5.0},
            coordinator_headers,
        ),
        "ERR_INVALID_REQUEST",
        expected_status=400,
    )

    stored = read_exam(exam["id"])
    assert stored["report_status"] == "AWAITING_INTERPRETATION"
    assert stored["birads_assessment"] is None
    assert list_total_count(api.list_exams(coordinator_headers)) == 1
    assert list_total_count(api.list_personnel_credits(core["tech_id"], coordinator_headers)) == 0
    assert read_personnel(core["tech_id"])["ce_hours_36mo"] == pytest.approx(0, abs=0.01)


def test_duplicate_state_code_and_duplicate_model_serial_are_rejected(
    api, core, coordinator_headers, reviewer_headers
):
    """`state_code` is globally unique; `model_serial` is unique only inside a facility.

    PRD: "**Uniqueness (priority 21)** — `state_code` is globally unique across
    `StatePolicy`, and `model_serial` is unique within a facility:
    `ERR_DUPLICATE_RESOURCE`, 409."

    Design: Corner/validations/duplicate_state_code_and_duplicate_model_serial_are_rejected
    """
    second_facility = create_facility(
        core["policy_id"], name="Second Harbor Imaging", accreditation_body="STATE_CERTIFIED"
    )

    validate_error(
        api.create_state_policy(minimal_state_policy_payload("CT"), reviewer_headers),
        "ERR_DUPLICATE_RESOURCE",
        expected_status=409,
    )
    validate_error(
        api.create_unit(
            core["facility_id"],
            unit_payload(model_serial="SEL-9001", modality="DM_2D"),
            coordinator_headers,
        ),
        "ERR_DUPLICATE_RESOURCE",
        expected_status=409,
    )

    twin = validate_success(
        api.create_unit(
            second_facility["id"],
            unit_payload(model_serial="SEL-9001", modality="DM_2D"),
            coordinator_headers,
        ),
        expected_status=201,
    )
    assert twin["model_serial"] == "SEL-9001"

    policy = validate_success(api.get_state_policy(core["policy_id"], reviewer_headers))
    assert policy["density_notice_rule"] == "STATE_ENHANCED_ALL"
    assert (
        list_total_count(api.list_facility_units(core["facility_id"], coordinator_headers)) == 1
    )


def test_future_timestamp_and_clock_rewind_are_rejected_while_a_no_op_hold_passes(
    api, core, coordinator_headers
):
    """Both temporal guards compare against the clock, but holding it still is legal.

    PRD: "**Clock monotonicity (priority 66)** — the requested `current_utc` is at
    or after the clock's present value: `ERR_CLOCK_REWIND`, 422."

    Design: Corner/validations/future_timestamp_and_clock_rewind_are_rejected_while_a_no_op_hold_passes
    """
    validate_error(
        api.create_exam(
            exam_payload(
                core["unit_id"],
                core["tech_id"],
                patient_ref="PT-TS-1",
                performed_at="2026-09-01T00:00:00Z",
            ),
            core["tech_headers"],
        ),
        "ERR_FUTURE_TIMESTAMP",
        expected_status=422,
    )
    validate_error(
        api.set_clock("2026-07-31T00:00:00Z", coordinator_headers),
        "ERR_CLOCK_REWIND",
        expected_status=422,
    )
    validate_success(api.set_clock("2026-08-01T00:00:00Z", coordinator_headers))

    now = validate_success(api.get_clock(coordinator_headers))
    assert_instant_equals(now["current_utc"], "2026-08-01T00:00:00Z", "current_utc")
    assert list_total_count(api.list_exams(coordinator_headers)) == 0


def test_screening_interpretation_without_a_density_category_is_rejected(
    api, core, coordinator_headers
):
    """The density requirement is conditional on `exam_type`, not universal.

    PRD: "**Density category required (priority 74)** — a `SCREENING` exam must
    carry a `density_category` at interpretation:
    `ERR_DENSITY_CATEGORY_REQUIRED`, 422."

    Design: Corner/validations/screening_interpretation_without_a_density_category_is_rejected
    """
    screening = acquire_exam(core, patient_ref="PT-DC-S", performed_at="2026-07-20T00:00:00Z")
    diagnostic = acquire_exam(
        core,
        patient_ref="PT-DC-D",
        exam_type="DIAGNOSTIC",
        performed_at="2026-07-20T00:00:00Z",
        original_image_count=6,
    )

    validate_error(
        api.interpret_exam(screening["id"], {"birads_assessment": 1}, core["rad_headers"]),
        "ERR_DENSITY_CATEGORY_REQUIRED",
        expected_status=422,
    )
    unread = read_exam(screening["id"])
    assert unread["report_status"] == "AWAITING_INTERPRETATION"
    assert unread["interpreting_physician_id"] is None

    read_out = validate_success(
        api.interpret_exam(diagnostic["id"], {"birads_assessment": 3}, core["rad_headers"])
    )
    assert read_out["report_status"] == "INTERPRETED_FINAL"
    assert read_out["density_category"] is None
    assert read_out["notification_status"] == "PENDING"
    assert read_out["recall_flag"] is False


def test_supplemental_order_on_an_ineligible_exam_is_rejected(api, core, coordinator_headers):
    """Both halves of the eligibility conjunction are exercised on their own.

    PRD: "The exam must be in `report_status` `INTERPRETED_FINAL` or `AMENDED`
    and must carry a non-null `density_category`, or the recommendation is refused
    with `ERR_EXAM_NOT_ELIGIBLE_FOR_SUPPLEMENTAL`."

    Design: Corner/validations/supplemental_order_on_an_ineligible_exam_is_rejected
    """
    no_density = acquire_exam(
        core,
        patient_ref="PT-SE-D",
        exam_type="DIAGNOSTIC",
        performed_at="2026-07-20T00:00:00Z",
        original_image_count=6,
    )
    validate_success(
        api.interpret_exam(no_density["id"], {"birads_assessment": 3}, core["rad_headers"])
    )
    unread = acquire_exam(core, patient_ref="PT-SE-U", performed_at="2026-07-20T00:00:00Z")

    validate_error(
        api.create_supplemental_order(
            no_density["id"],
            supplemental_order_payload("MRI", recommendation_note="Density never recorded"),
            core["rad_headers"],
        ),
        "ERR_EXAM_NOT_ELIGIBLE_FOR_SUPPLEMENTAL",
        expected_status=422,
    )
    validate_error(
        api.create_supplemental_order(
            unread["id"],
            supplemental_order_payload(
                "ULTRASOUND", recommendation_note="Ordered before the read landed"
            ),
            core["rad_headers"],
        ),
        "ERR_EXAM_NOT_ELIGIBLE_FOR_SUPPLEMENTAL",
        expected_status=422,
    )

    assert read_exam(no_density["id"])["report_status"] == "INTERPRETED_FINAL"
    assert read_exam(no_density["id"])["density_category"] is None
    assert read_exam(unread["id"])["report_status"] == "AWAITING_INTERPRETATION"
    assert list_total_count(api.list_supplemental_orders(coordinator_headers)) == 0


def test_an_amendment_that_changes_nothing_is_rejected(api, core):
    """Re-sending the stored pair is refused; changing density alone is enough.

    PRD: "**Amendment changes something (priority 73)** — at least one of
    `birads_assessment` or `density_category` differs from the stored value:
    `ERR_AMENDMENT_NO_CHANGE`, 422."

    Design: Corner/validations/an_amendment_that_changes_nothing_is_rejected
    """
    exam = acquire_and_interpret(
        core, birads=1, density="B", patient_ref="PT-AN-1", performed_at="2026-07-20T00:00:00Z"
    )
    assert exam["amendment_count"] == 0

    validate_error(
        api.amend_exam(
            exam["id"],
            {
                "birads_assessment": 1,
                "density_category": "B",
                "amendment_reason": "Re-sent the identical values",
            },
            core["rad_headers"],
        ),
        "ERR_AMENDMENT_NO_CHANGE",
        expected_status=422,
    )
    unchanged = read_exam(exam["id"])
    assert unchanged["report_status"] == "INTERPRETED_FINAL"
    assert unchanged["amendment_count"] == 0
    assert unchanged["version"] == exam["version"]

    amended = validate_success(
        api.amend_exam(
            exam["id"],
            {"density_category": "C", "amendment_reason": "Density re-read as heterogeneously dense"},
            core["rad_headers"],
        )
    )
    assert amended["report_status"] == "AMENDED"
    assert amended["amendment_count"] == 1
    assert amended["density_category"] == "C"
    assert amended["birads_assessment"] == 1
    assert amended["recall_flag"] is False
    assert amended["notification_status"] == "PENDING"


def test_an_overlapping_audit_cycle_for_the_same_radiologist_is_rejected(api, core, qa_headers):
    """Exclusivity is scoped per radiologist, so the colleague takes the same period.

    PRD: "**Audit cycle exclusivity (priority 72)** — at most one `OPEN` cycle may
    exist per radiologist, and a new cycle's period must not overlap an existing
    cycle's period: `ERR_AUDIT_CYCLE_OVERLAP`, 409."

    Design: Corner/validations/an_overlapping_audit_cycle_for_the_same_radiologist_is_rejected
    """
    add_second_radiologist(core)
    first = open_cycle(core)
    assert first["status"] == "OPEN"

    validate_error(
        api.create_audit_cycle(
            core["rad_id"],
            audit_cycle_payload(
                period_start="2026-06-01T00:00:00Z",
                period_end="2026-12-01T00:00:00Z",
                followup_window_days=180,
            ),
            qa_headers,
        ),
        "ERR_AUDIT_CYCLE_OVERLAP",
        expected_status=409,
    )

    colleague = validate_success(
        api.create_audit_cycle(core["rad2_id"], audit_cycle_payload(), qa_headers),
        expected_status=201,
    )
    assert colleague["status"] == "OPEN"
    assert colleague["radiologist_id"] == core["rad2_id"]
    assert colleague["followup_window_days"] == 365
    assert colleague["variant_at_close"] is None
    assert colleague["locked_at"] is None

    assert list_total_count(api.list_personnel_audit_cycles(core["rad_id"], qa_headers)) == 1
    assert list_total_count(api.list_personnel_audit_cycles(core["rad2_id"], qa_headers)) == 1


def test_closing_an_audit_cycle_before_its_period_end_is_rejected(api, core, qa_headers):
    """The elapsed comparison is inclusive, so an unreached `period_end` blocks the close.

    PRD: "**Audit period elapsed (priority 64)** — a cycle may only be closed once
    the logical clock has reached `period_end`: `ERR_AUDIT_PERIOD_NOT_ELAPSED`, 409."

    Design: Corner/validations/closing_an_audit_cycle_before_its_period_end_is_rejected
    """
    add_second_radiologist(core)
    elapsed = open_cycle(core)
    future = open_cycle(
        core, radiologist_id=core["rad2_id"], period_end="2026-12-01T00:00:00Z"
    )

    validate_error(
        api.close_audit_cycle(future["id"], close_cycle_payload(), qa_headers),
        "ERR_AUDIT_PERIOD_NOT_ELAPSED",
        expected_status=409,
    )
    still_open = read_cycle(future["id"], qa_headers)
    assert still_open["status"] == "OPEN"
    assert still_open["variant_at_close"] is None
    assert still_open["locked_at"] is None

    locked = validate_success(
        api.close_audit_cycle(elapsed["id"], close_cycle_payload(), qa_headers)
    )
    assert locked["status"] == "LOCKED"
    assert locked["variant_at_close"] == "PPV1_SCREENING"
    assert_instant_equals(locked["locked_at"], "2026-08-01T00:00:00Z", "locked_at")
    assert locked["screening_exam_count"] == 0
    assert locked["recall_count"] == 0
    assert locked["biopsy_count"] == 0
    assert locked["cancer_count"] == 0
    assert locked["excluded_exam_count"] == 0
    assert locked["recall_rate_pct"] is None
    assert locked["ppv_pct"] is None
    assert locked["abnormal_interpretation_flag"] is False


def test_a_packet_of_fewer_than_two_distinct_exams_is_rejected_before_the_fee_check(
    api, core, coordinator_headers
):
    """Priority 22 fires ahead of the escrow guard, so an unfunded facility still sees 422.

    PRD: "**Packet size (priority 22)** — a clinical image packet carries at least
    2 distinct exam ids with no duplicates: `ERR_PACKET_TOO_SMALL`, 422."

    Design: Corner/validations/a_packet_of_fewer_than_two_distinct_exams_is_rejected_before_the_fee_check
    """
    exams = setup_two_interpreted_exams(core)
    version = unit_version(core)

    validate_error(
        api.create_clinical_image_review(
            core["unit_id"], packet_payload([exams[0]["id"]], version), coordinator_headers
        ),
        "ERR_PACKET_TOO_SMALL",
        expected_status=422,
    )
    validate_error(
        api.create_clinical_image_review(
            core["unit_id"],
            packet_payload([exams[0]["id"], exams[0]["id"]], version),
            coordinator_headers,
        ),
        "ERR_PACKET_TOO_SMALL",
        expected_status=422,
    )

    assert_facility_ledger(
        read_facility(core["facility_id"]),
        total_funded_cents=0,
        prepaid_credit_cents=0,
        fee_held_cents=0,
        fee_consumed_cents=0,
    )
    unit = read_unit(core["unit_id"])
    assert unit["reaccreditation_attempts_remaining"] == 3
    assert unit["version"] == version
    assert (
        list_total_count(
            api.list_unit_clinical_image_reviews(core["unit_id"], coordinator_headers)
        )
        == 0
    )


def test_scheduling_is_gated_on_coverage_then_on_the_appointment_instant(
    api, core, coordinator_headers
):
    """Coverage must land first, and only then is the appointment instant checked.

    PRD: "**Coverage determined before scheduling (priority 76)** — an order may
    only be scheduled once its `coverage_outcome` is something other than
    `UNDETERMINED`: `ERR_COVERAGE_NOT_DETERMINED`, 409."

    Design: Corner/validations/scheduling_is_gated_on_coverage_then_on_the_appointment_instant
    """
    exam = acquire_and_interpret(
        core, birads=1, density="C", patient_ref="PT-SC-1", performed_at="2026-07-20T00:00:00Z"
    )
    order = recommend_order(
        core,
        exam["id"],
        modality="ULTRASOUND",
        headers=core["rad_headers"],
        recommendation_note="Dense tissue, supplemental ultrasound advised",
    )
    assert order["status"] == "RECOMMENDED"
    assert order["coverage_outcome"] == "UNDETERMINED"

    # A `RECOMMENDED` order is not in a schedulable state at all, and the state
    # precondition at priority 40 is evaluated before the coverage gate at
    # priority 76: "Scheduling is a coordinator action, available from
    # `COVERAGE_DETERMINED` and from `LOST_TO_FOLLOW_UP` ... and from any other
    # state it is `ERR_ORDER_NOT_SCHEDULABLE`."
    validate_error(
        api.schedule_supplemental_order(
            order["id"], schedule_payload("2026-08-05T09:00:00Z"), coordinator_headers
        ),
        "ERR_ORDER_NOT_SCHEDULABLE",
        expected_status=409,
    )
    assert read_order(order["id"])["status"] == "RECOMMENDED"
    assert read_order(order["id"])["appointment_start"] is None

    determined = determine_coverage(core, order["id"])
    assert determined["status"] == "COVERAGE_DETERMINED"

    validate_error(
        api.schedule_supplemental_order(
            order["id"], schedule_payload("2026-07-31T09:00:00Z"), coordinator_headers
        ),
        "ERR_APPOINTMENT_IN_PAST",
        expected_status=422,
    )
    assert read_order(order["id"])["status"] == "COVERAGE_DETERMINED"

    scheduled = validate_success(
        api.schedule_supplemental_order(
            order["id"], schedule_payload("2026-08-01T00:00:00Z"), coordinator_headers
        )
    )
    assert scheduled["status"] == "SCHEDULED"
    assert_instant_equals(
        scheduled["appointment_start"], "2026-08-01T00:00:00Z", "appointment_start"
    )
    assert_instant_equals(scheduled["appointment_end"], "2026-08-01T00:30:00Z", "appointment_end")
    assert_coverage(
        scheduled,
        coverage_outcome="COVERED_NO_COST_SHARE",
        allowed_amount_cents=31500,
        covered_amount_cents=31500,
        patient_responsibility_cents=0,
        coverage_tier="TIER_1",
        governing_state_code="CT",
    )

    # `LOST_TO_FOLLOW_UP` is the one schedulable state an order can occupy while
    # its `coverage_outcome` is still `UNDETERMINED`, so it is where the
    # priority-76 gate is actually observable.  Sweep four takes a `RECOMMENDED`
    # order past its `followup_due_at` into `LOST_TO_FOLLOW_UP` without ever
    # determining coverage.
    undetermined_exam = acquire_and_interpret(
        core, birads=1, density="C", patient_ref="PT-SC-2", performed_at="2026-07-21T00:00:00Z"
    )
    undetermined = recommend_order(
        core,
        undetermined_exam["id"],
        modality="ULTRASOUND",
        headers=core["rad_headers"],
        recommendation_note="Dense tissue, patient not yet reached",
    )
    assert_instant_equals(
        undetermined["followup_due_at"], "2026-09-30T00:00:00Z", "followup_due_at"
    )

    set_clock("2026-10-01T00:00:00Z")
    run_compliance(core, headers=coordinator_headers)
    swept = read_order(undetermined["id"])
    assert swept["status"] == "LOST_TO_FOLLOW_UP"
    assert swept["coverage_outcome"] == "UNDETERMINED"

    validate_error(
        api.schedule_supplemental_order(
            undetermined["id"], schedule_payload("2026-10-05T09:00:00Z"), coordinator_headers
        ),
        "ERR_COVERAGE_NOT_DETERMINED",
        expected_status=409,
    )
    assert read_order(undetermined["id"])["status"] == "LOST_TO_FOLLOW_UP"
    assert read_order(undetermined["id"])["appointment_start"] is None


def test_deposit_must_be_positive_and_prepaid_credit_must_cover_the_application_fee(
    api, core, coordinator_headers
):
    """A zero deposit is refused, an unfunded filing is 402, and 250000 unblocks both.

    PRD: "**Prepaid credit sufficiency (priority 81)** — the facility holds at
    least 250000 cents of `prepaid_credit_cents` to escrow against a new submission
    or resubmission: `ERR_INSUFFICIENT_PREPAID_CREDIT`, 402."

    Design: Corner/validations/deposit_must_be_positive_and_prepaid_credit_must_cover_the_application_fee
    """
    exams = setup_two_interpreted_exams(core)
    exam_ids = [exams[0]["id"], exams[1]["id"]]

    validate_error(
        api.create_funding_deposit(
            core["facility_id"],
            funding_deposit_payload(0, memo="Zero-cent deposit"),
            coordinator_headers,
        ),
        "ERR_INVALID_DEPOSIT_AMOUNT",
        expected_status=422,
    )
    assert_facility_ledger(
        read_facility(core["facility_id"]),
        total_funded_cents=0,
        prepaid_credit_cents=0,
        fee_held_cents=0,
        fee_consumed_cents=0,
    )

    validate_error(
        api.create_clinical_image_review(
            core["unit_id"], packet_payload(exam_ids, unit_version(core)), coordinator_headers
        ),
        "ERR_INSUFFICIENT_PREPAID_CREDIT",
        expected_status=402,
    )

    funded = validate_success(
        api.create_funding_deposit(
            core["facility_id"],
            funding_deposit_payload(250000, memo="Exactly one application fee"),
            coordinator_headers,
        ),
        # A funding deposit is a ledger movement that answers with the refreshed
        # facility, not a resource creation: "Resource creation returns HTTP 201;
        # every other successful call, including all state-transition actions, all
        # ledger movements, the compliance run and every read, returns HTTP 200."
        expected_status=200,
    )
    assert_facility_ledger(
        funded,
        total_funded_cents=250000,
        prepaid_credit_cents=250000,
        fee_held_cents=0,
        fee_consumed_cents=0,
    )

    submission = validate_success(
        api.create_clinical_image_review(
            core["unit_id"], packet_payload(exam_ids, unit_version(core)), coordinator_headers
        ),
        expected_status=201,
    )
    assert submission["status"] == "SUBMITTED"
    assert submission["attempt_number"] == 1
    assert submission["fee_held_cents"] == 250000

    assert_facility_ledger(
        read_facility(core["facility_id"]),
        total_funded_cents=250000,
        prepaid_credit_cents=0,
        fee_held_cents=250000,
        fee_consumed_cents=0,
    )
    assert read_unit(core["unit_id"])["reaccreditation_attempts_remaining"] == 2


def test_unqualified_technologist_and_uncertified_modality_both_block_an_exam(
    api, core, coordinator_headers
):
    """Two independent personnel guards on the same acquisition endpoint.

    PRD: "**Technologist qualified (priority 50)** — the technologist named on an
    exam has `qualification_status` exactly `QUALIFIED`, not `PROVISIONAL`,
    `LAPSED` or `INACTIVE`: `ERR_TECHNOLOGIST_NOT_QUALIFIED`, 422."

    Design: Corner/validations/unqualified_technologist_and_uncertified_modality_both_block_an_exam
    """
    provisional = add_personnel(
        core["facility_id"],
        personnel_payload(
            "TECHNOLOGIST",
            full_name="Provi Tech",
            initial_qualification_on="2026-06-01T00:00:00Z",
            initial_training_hours=10,
            initial_read_volume=5,
        ),
    )
    assert_personnel_state(
        provisional, qualification_status="PROVISIONAL", ce_status="COMPLIANT"
    )

    wrong_modality = add_personnel(
        core["facility_id"],
        personnel_payload(
            "TECHNOLOGIST", full_name="Duo Tech", modality_certifications=["DM_2D"]
        ),
    )
    assert_personnel_state(
        wrong_modality, qualification_status="QUALIFIED", ce_status="COMPLIANT"
    )

    validate_error(
        api.create_exam(
            exam_payload(core["unit_id"], provisional["id"], patient_ref="PT-QL-1"),
            make_technologist_headers(provisional["id"]),
        ),
        "ERR_TECHNOLOGIST_NOT_QUALIFIED",
        expected_status=422,
    )
    validate_error(
        api.create_exam(
            exam_payload(core["unit_id"], wrong_modality["id"], patient_ref="PT-QL-2"),
            make_technologist_headers(wrong_modality["id"]),
        ),
        "ERR_MODALITY_NOT_CERTIFIED",
        expected_status=422,
    )

    assert list_total_count(api.list_exams(coordinator_headers)) == 0
    unit = read_unit(core["unit_id"])
    assert unit["modality"] == "DBT_3D"
    assert unit["total_images_acquired"] == 0
    assert unit["image_based_repeat_rate_pct"] is None


def test_a_lapsed_physician_cannot_interpret(api, core):
    """An expired grace period lapses the reader, and the guard then blocks the read.

    PRD: "**Physician qualified (priority 51)** — the interpreting physician has
    `qualification_status` `QUALIFIED`: `ERR_PHYSICIAN_NOT_QUALIFIED`, 422. Applies
    to `POST /exams/{id}/interpret` and `POST /exams/{id}/amend`."

    Design: Corner/validations/a_lapsed_physician_cannot_interpret
    """
    first = run_qualification_review(
        core, core["rad_id"], review_note="First review — no credits on file"
    )
    assert_personnel_state(first, qualification_status="QUALIFIED", ce_status="GRACE")
    assert_instant_equals(first["ce_deadline_at"], "2026-10-30T00:00:00Z", "ce_deadline_at")

    set_clock("2026-10-31T00:00:00Z")
    lapsed = run_qualification_review(
        core, core["rad_id"], review_note="Grace period has expired"
    )
    assert_personnel_state(lapsed, qualification_status="LAPSED", ce_status="DEFICIENT")

    exam = acquire_exam(core, patient_ref="PT-LP-1", performed_at="2026-10-30T00:00:00Z")
    validate_error(
        api.interpret_exam(exam["id"], interpret_payload(1, "B"), core["rad_headers"]),
        "ERR_PHYSICIAN_NOT_QUALIFIED",
        expected_status=422,
    )

    unread = read_exam(exam["id"])
    assert unread["report_status"] == "AWAITING_INTERPRETATION"
    assert unread["interpreting_physician_id"] is None
    assert unread["interpreted_at"] is None
    assert unread["notification_status"] == "NOT_REQUIRED"

    assert_personnel_state(
        read_personnel(core["tech_id"]),
        qualification_status="QUALIFIED",
        ce_status="COMPLIANT",
    )
    assert read_facility(core["facility_id"])["compliance_posture"] == "CONDITIONAL"


def test_a_technologist_cannot_be_given_an_audit_cycle(api, core, qa_headers):
    """The audit subject must be an interpreting physician, not any other role.

    PRD: "**Audit subject is a radiologist (priority 59)** — the `Personnel` row an
    audit cycle is opened on has `role_type` `INTERPRETING_PHYSICIAN`:
    `ERR_NOT_AN_INTERPRETING_PHYSICIAN`, 422. Applies to
    `POST /personnel/{id}/audit-cycles`."

    Design: Corner/validations/a_technologist_cannot_be_given_an_audit_cycle
    """
    validate_error(
        api.create_audit_cycle(core["tech_id"], audit_cycle_payload(), qa_headers),
        "ERR_NOT_AN_INTERPRETING_PHYSICIAN",
        expected_status=422,
    )
    validate_error(
        api.create_audit_cycle(core["phys_id"], audit_cycle_payload(), qa_headers),
        "ERR_NOT_AN_INTERPRETING_PHYSICIAN",
        expected_status=422,
    )

    assert list_total_count(api.list_personnel_audit_cycles(core["tech_id"], qa_headers)) == 0
    assert list_total_count(api.list_personnel_audit_cycles(core["phys_id"], qa_headers)) == 0
    assert list_total_count(api.list_personnel_audit_cycles(core["rad_id"], qa_headers)) == 0


def test_the_full_screening_notification_and_supplemental_path_passes_every_guard(api, core):
    """A `CONDITIONAL` posture must not block anything; only `SUSPENDED` does.

    PRD: "The order's `coverage_outcome` must no longer be `UNDETERMINED`
    (`ERR_COVERAGE_NOT_DETERMINED`), and the owning facility's `compliance_posture`
    must not be `SUSPENDED` (`ERR_FACILITY_SUSPENDED`)."

    Design: Corner/validations/the_full_screening_notification_and_supplemental_path_passes_every_guard
    """
    assert read_facility(core["facility_id"])["compliance_posture"] == "CONDITIONAL"

    exam = acquire_and_interpret(
        core, birads=1, density="C", patient_ref="PT-HP-1", performed_at="2026-07-20T00:00:00Z"
    )
    letter = generate_letter(core, exam["id"], dispatch_channel="MAIL")
    sent = send_letter(core, letter["id"])
    order = recommend_order(
        core,
        exam["id"],
        modality="ULTRASOUND",
        headers=core["rad_headers"],
        recommendation_note="Dense tissue, supplemental ultrasound advised",
    )
    determine_coverage(core, order["id"])
    scheduled = validate_success(
        api.schedule_supplemental_order(
            order["id"], schedule_payload("2026-08-01T09:00:00Z"), core["coord_headers"]
        )
    )
    assert scheduled["status"] == "SCHEDULED"
    completed = complete_order(core, order["id"])

    final_exam = read_exam(exam["id"])
    assert final_exam["report_status"] == "INTERPRETED_FINAL"
    assert final_exam["notification_status"] == "SENT"
    assert final_exam["follow_up_status"] == "COMPLETED"
    assert_instant_equals(final_exam["report_due_at"], "2026-08-19T00:00:00Z", "report_due_at")
    assert final_exam["interpreted_late"] is False
    assert_instant_equals(
        final_exam["notification_deadline_at"], "2026-08-22T00:00:00Z", "notification_deadline_at"
    )

    assert sent["status"] == "SENT"
    assert sent["letter_type"] == "COMBINED"
    assert sent["density_statement_code"] == "FDA_DENSE"
    assert sent["reading_grade_level"] == 8

    assert completed["status"] == "COMPLETED"
    assert_instant_equals(completed["completed_at"], "2026-08-01T00:00:00Z", "completed_at")
    assert_instant_equals(
        completed["appointment_end"], "2026-08-01T09:30:00Z", "appointment_end"
    )
    assert_coverage(
        completed,
        coverage_outcome="COVERED_NO_COST_SHARE",
        allowed_amount_cents=31500,
        covered_amount_cents=31500,
        patient_responsibility_cents=0,
        coverage_tier="TIER_1",
        governing_state_code="CT",
    )

    facility = read_facility(core["facility_id"])
    assert facility["compliance_posture"] == "CONDITIONAL"
    assert facility["open_notice_obligations"] == 1
