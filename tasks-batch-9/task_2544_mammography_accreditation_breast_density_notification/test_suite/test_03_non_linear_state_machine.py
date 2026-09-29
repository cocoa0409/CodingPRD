"""Parallel dimensions and loops: states that disagree, and states that return."""

import pytest

from test_helpers import (
    acquire_and_interpret,
    assert_exam_dimensions,
    assert_facility_ledger,
    assert_instant_equals,
    assert_personnel_state,
    complete_order,
    determine_coverage,
    exam_version,
    generate_letter,
    read_facility,
    read_letter,
    read_order,
    read_personnel,
    read_submission,
    read_unit,
    recommend_order,
    review_packet,
    schedule_order,
    send_letter,
    set_clock,
    setup_core_funded,
    unit_version,
    validate_success,
)


@pytest.fixture
def three_dimension_exam(core):
    """A recalled exam whose follow-up closes, whose letter ships, then is amended."""
    exam = acquire_and_interpret(
        core,
        birads=0,
        density="C",
        patient_ref="PT-7001",
        performed_at="2026-07-10T00:00:00Z",
    )
    core["exam_id"] = exam["id"]
    order = recommend_order(
        core,
        exam["id"],
        "ULTRASOUND",
        headers=core["rad_headers"],
        recommendation_note="Recall workup",
    )
    core["order_id"] = order["id"]
    determine_coverage(core, order["id"])
    schedule_order(core, order["id"], appointment_start="2026-08-05T09:00:00Z")
    set_clock("2026-08-05T10:00:00Z")
    complete_order(core, order["id"])
    letter = generate_letter(
        core,
        exam["id"],
        expected_exam_version=exam_version(exam["id"]),
        dispatch_channel="PORTAL",
    )
    core["letter_id"] = letter["id"]
    send_letter(core, letter["id"])
    return core


def test_amendment_leaves_the_three_exam_dimensions_holding_three_values(
    api, three_dimension_exam
):
    """Report AMENDED, notification back to PENDING, follow-up still COMPLETED.

    PRD: "Level three, caused by that supersession, moves the exam's
    `notification_status` back to `PENDING` and clears `notification_deadline_at`,
    because the letter the patient received described a finding that no longer
    stands."

    Design: Difficulty/non_linear_state_machine/exam_three_parallel_dimensions_hold_three_different_values
    """
    core = three_dimension_exam
    exam = validate_success(
        api.amend_exam(
            core["exam_id"],
            {
                "birads_assessment": 2,
                "amendment_reason": "Second read downgraded the finding",
            },
            core["rad_headers"],
        )
    )
    assert_exam_dimensions(
        exam,
        report_status="AMENDED",
        notification_status="PENDING",
        follow_up_status="COMPLETED",
    )
    assert exam["amendment_count"] == 1
    assert exam["notification_deadline_at"] is None
    assert exam["recall_flag"] is False


def test_amendment_supersedes_the_sent_letter_and_keeps_the_finished_order(
    api, three_dimension_exam
):
    """The shipped letter is superseded while the completed obligation is untouched.

    PRD: "Level two supersedes the exam's current letter: whichever
    `NotificationLetter` of this exam is in `QUEUED`, `SENT` or
    `DELIVERED_ASSUMED` moves to `SUPERSEDED`."

    Design: Difficulty/non_linear_state_machine/exam_three_parallel_dimensions_hold_three_different_values
    """
    core = three_dimension_exam
    validate_success(
        api.amend_exam(
            core["exam_id"],
            {
                "birads_assessment": 2,
                "amendment_reason": "Second read downgraded the finding",
            },
            core["rad_headers"],
        )
    )
    letter = read_letter(core["letter_id"])
    assert letter["status"] == "SUPERSEDED"
    order = read_order(core["order_id"])
    assert order["status"] == "COMPLETED"
    assert_instant_equals(order["completed_at"], "2026-08-05T10:00:00Z", "completed_at")
    facility = read_facility(core["facility_id"])
    assert facility["open_notice_obligations"] == 1


@pytest.fixture
def revision_loop(coordinator_headers):
    """A funded unit whose first packet came back REVISION_REQUIRED."""
    core = setup_core_funded(amount_cents=1000000)
    first = acquire_and_interpret(
        core,
        birads=1,
        density="B",
        patient_ref="PT-8001",
        performed_at="2026-07-05T00:00:00Z",
    )
    second = acquire_and_interpret(
        core,
        birads=1,
        density="B",
        patient_ref="PT-8002",
        performed_at="2026-07-06T00:00:00Z",
    )
    core["exam_ids"] = [first["id"], second["id"]]
    submission = validate_success(
        api_packet(core, coordinator_headers), expected_status=201
    )
    core["submission_id"] = submission["id"]
    review_packet(
        core,
        submission["id"],
        decision="REVISION_REQUIRED",
        deficiency_categories=["POSITIONING"],
        reviewer_note="Inframammary fold not included",
    )
    return core


def api_packet(core, headers):
    """File the attempt-one packet through the raw client so the 201 is checked."""
    from test_helpers import api_client, packet_payload

    return api_client.create_clinical_image_review(
        core["unit_id"],
        packet_payload(
            core["exam_ids"], unit_version(core), reviewer_note="Attempt 1 packet"
        ),
        headers,
    )


def test_resubmission_returns_the_packet_to_the_state_it_already_occupied(
    api, revision_loop, coordinator_headers
):
    """The loop lands back in SUBMITTED, the same live state the row held before.

    PRD: "On success the submission returns `REVISION_REQUIRED` to `SUBMITTED`,
    `attempt_number` increases by 1 — bounded at 3 — the packet's `exam_ids` are
    replaced wholesale, `submitted_at` is re-stamped at the logical clock, the fee
    is escrowed again, the unit's `reaccreditation_attempts_remaining` decreases by
    1, and the unit's `version` advances."

    Design: Difficulty/non_linear_state_machine/clinical_image_review_revision_loop_returns_to_submitted
    """
    core = revision_loop
    from test_helpers import api_client, packet_payload

    submission = validate_success(
        api_client.resubmit_clinical_image_review(
            core["submission_id"],
            packet_payload(
                core["exam_ids"],
                unit_version(core),
                reviewer_note="Attempt 2 packet, positioning corrected",
            ),
            coordinator_headers,
        )
    )
    assert submission["status"] == "SUBMITTED"
    assert submission["attempt_number"] == 2
    assert submission["fee_held_cents"] == 250000
    assert_instant_equals(submission["submitted_at"], "2026-08-01T00:00:00Z", "submitted_at")
    unit = read_unit(core["unit_id"])
    assert unit["reaccreditation_attempts_remaining"] == 1
    assert unit["accreditation_status"] == "PROVISIONAL"


def test_revision_loop_re_escrows_a_second_fee_beside_the_consumed_one(
    api, revision_loop, coordinator_headers
):
    """The reviewed fee stays consumed and a fresh 250000 is escrowed alongside it.

    PRD: "Every decision, whatever its verdict, consumes the escrow: 250000 cents
    leave `fee_held_cents` and enter `fee_consumed_cents`, the submission's own
    `fee_held_cents` drops to 0, and `prepaid_credit_cents` is untouched — once
    images have been reviewed the fee is non-refundable."

    Design: Difficulty/non_linear_state_machine/clinical_image_review_revision_loop_returns_to_submitted
    """
    core = revision_loop
    from test_helpers import api_client, packet_payload

    validate_success(
        api_client.resubmit_clinical_image_review(
            core["submission_id"],
            packet_payload(
                core["exam_ids"],
                unit_version(core),
                reviewer_note="Attempt 2 packet, positioning corrected",
            ),
            coordinator_headers,
        )
    )
    facility = read_facility(core["facility_id"])
    assert_facility_ledger(
        facility,
        total_funded_cents=1000000,
        prepaid_credit_cents=500000,
        fee_held_cents=250000,
        fee_consumed_cents=250000,
    )
    assert read_submission(core["submission_id"])["status"] == "SUBMITTED"


def test_first_ce_shortfall_moves_only_the_continuing_education_dimension(api, core):
    """An empty credit history drops ce_status to GRACE while QUALIFIED stands.

    PRD: "Otherwise, when a shortfall is detected and `ce_status` was still
    `COMPLIANT`, this is a first detection: `ce_status` moves `COMPLIANT` to
    `GRACE` and `ce_deadline_at` is set to the logical clock plus the governing
    policy's `ce_grace_days`, while `qualification_status` is deliberately left
    untouched because the two dimensions are parallel."

    Design: Difficulty/non_linear_state_machine/personnel_ce_dimension_drops_to_grace_while_qualification_holds
    """
    person = validate_success(
        api.run_qualification_review(
            core["tech_id"],
            core["coord_headers"],
            {"review_note": "Annual continuing-requirement review"},
        )
    )
    assert_personnel_state(
        person,
        qualification_status="QUALIFIED",
        ce_status="GRACE",
        ce_hours_36mo=0.00,
        volume_credit_24mo=0,
    )


def test_ce_grace_deadline_is_the_clock_plus_the_policy_grace_days(api, core):
    """A 90-day grace window granted on 2026-08-01 expires on 2026-10-30.

    PRD: "A person can sit in `GRACE` for an entire grace period while remaining
    `QUALIFIED`."

    Design: Difficulty/non_linear_state_machine/personnel_ce_dimension_drops_to_grace_while_qualification_holds
    """
    validate_success(
        api.run_qualification_review(
            core["tech_id"],
            core["coord_headers"],
            {"review_note": "Annual continuing-requirement review"},
        )
    )
    person = read_personnel(core["tech_id"])
    assert_instant_equals(person["ce_deadline_at"], "2026-10-30T00:00:00Z", "ce_deadline_at")
    assert_instant_equals(
        person["last_qualification_review_at"], "2026-08-01T00:00:00Z", "last_qualification_review_at"
    )
    facility = read_facility(core["facility_id"])
    assert facility["compliance_posture"] == "CONDITIONAL"
