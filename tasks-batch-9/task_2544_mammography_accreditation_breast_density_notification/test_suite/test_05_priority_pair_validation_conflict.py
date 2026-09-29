"""When two rules both fail, the ladder decides which error the caller sees."""

import pytest

from test_helpers import (
    acquire_and_interpret,
    add_personnel,
    add_second_unit,
    assert_facility_ledger,
    assert_instant_equals,
    build_user_headers,
    exam_payload,
    list_total_count,
    packet_payload,
    personnel_payload,
    read_facility,
    read_unit,
    record_level_1_inspection,
    report_qualifying_failure,
    review_packet,
    set_clock,
    setup_core,
    setup_core_funded,
    unit_version,
    validate_error,
)


@pytest.fixture
def out_of_service_with_unqualified_tech(core):
    """A unit pulled out of service, plus a technologist who never met the thresholds."""
    weak = add_personnel(
        core["facility_id"],
        personnel_payload(
            "TECHNOLOGIST",
            full_name="Ute Untrained",
            initial_qualification_on="2026-01-10T00:00:00Z",
            initial_training_hours=10,
            initial_read_volume=5,
        ),
    )
    core["weak_tech"] = weak
    core["weak_tech_id"] = weak["id"]
    core["weak_tech_headers"] = build_user_headers(weak["id"], "Technologist")
    report_qualifying_failure(
        core, severity="CRITICAL", detected_at="2026-07-30T00:00:00Z"
    )
    return core


def _bad_exam(core):
    return exam_payload(
        core["unit_id"],
        core["weak_tech_id"],
        patient_ref="PT-9301",
        performed_at="2026-07-31T00:00:00Z",
    )


def test_out_of_service_state_error_is_reported_before_the_qualification_error(
    api, out_of_service_with_unqualified_tech
):
    """Priority 41 beats priority 50, so the 409 wins over the 422.

    PRD: "When more than one rule could reject a request, the service evaluates
    the checks in the fixed order below and reports the first failure it finds.
    Lower numbers are evaluated first."

    Design: Difficulty/priority_pair_validation_conflict/unit_out_of_service_state_error_outranks_technologist_qualification_error
    """
    core = out_of_service_with_unqualified_tech
    response = api.create_exam(_bad_exam(core), core["weak_tech_headers"])
    validate_error(response, "ERR_UNIT_NOT_IN_SERVICE", expected_status=409)
    assert core["weak_tech"]["qualification_status"] == "PROVISIONAL"


def test_the_rejected_acquisition_creates_no_exam_and_no_images(
    api, out_of_service_with_unqualified_tech
):
    """A masked-off request leaves the unit's image ledger at zero.

    PRD: "Acquisition is blocked when the unit's `operational_state` is
    `OUT_OF_SERVICE` (`ERR_UNIT_NOT_IN_SERVICE`), when the unit's
    `accreditation_status` is `SUSPENDED` (`ERR_UNIT_ACCREDITATION_SUSPENDED`),
    when the named technologist's `qualification_status` is anything other than
    `QUALIFIED` (`ERR_TECHNOLOGIST_NOT_QUALIFIED`), and when the technologist's
    `modality_certifications` does not contain the unit's `modality`
    (`ERR_MODALITY_NOT_CERTIFIED`)."

    Design: Difficulty/priority_pair_validation_conflict/unit_out_of_service_state_error_outranks_technologist_qualification_error
    """
    core = out_of_service_with_unqualified_tech
    validate_error(
        api.create_exam(_bad_exam(core), core["weak_tech_headers"]),
        "ERR_UNIT_NOT_IN_SERVICE",
    )
    listed = api.list_exams(core["coord_headers"], {"unit_id": core["unit_id"]})
    assert list_total_count(listed) == 0
    assert read_unit(core["unit_id"])["total_images_acquired"] == 0


@pytest.fixture
def lapsed_certificate_with_wrong_unit_exams(coordinator_headers):
    """An accredited unit one day past its certificate, and a packet built from unit two."""
    core = setup_core_funded(amount_cents=1000000)
    unit2 = add_second_unit(
        core["facility_id"],
        manufacturer="GE",
        model_serial="PRI-2200",
        modality="DM_2D",
        accreditation_expires_on="2027-09-30T00:00:00Z",
    )
    core["unit2_id"] = unit2["id"]
    own = [
        acquire_and_interpret(
            core, patient_ref="PT-9201", performed_at="2026-07-02T00:00:00Z"
        )["id"],
        acquire_and_interpret(
            core, patient_ref="PT-9202", performed_at="2026-07-03T00:00:00Z"
        )["id"],
    ]
    core["other_exam_ids"] = [
        acquire_and_interpret(
            core,
            patient_ref="PT-9203",
            performed_at="2026-07-04T00:00:00Z",
            unit_id=unit2["id"],
        )["id"],
        acquire_and_interpret(
            core,
            patient_ref="PT-9204",
            performed_at="2026-07-05T00:00:00Z",
            unit_id=unit2["id"],
        )["id"],
    ]
    from test_helpers import file_packet

    submission = file_packet(core, own, reviewer_note="Initial accreditation packet")
    review_packet(
        core,
        submission["id"],
        decision="PASS",
        reviewer_note="Meets clinical image quality criteria",
    )
    set_clock("2029-08-01T00:00:00Z")
    return core


def test_packet_unit_mismatch_is_reported_before_the_closed_reaccreditation_window(
    api, lapsed_certificate_with_wrong_unit_exams, coordinator_headers
):
    """Priority 56 beats priority 63, so the referential 422 wins over the temporal 409.

    PRD: "23. **Packet unit match (priority 56)** — every exam in a packet belongs
    to the same unit as the submission: `ERR_EXAM_UNIT_MISMATCH`, 422. Applies to
    `POST /units/{id}/clinical-image-reviews`, `POST
    /clinical-image-reviews/{id}/resubmit`."

    Design: Difficulty/priority_pair_validation_conflict/packet_exam_unit_mismatch_outranks_closed_reaccreditation_window
    """
    core = lapsed_certificate_with_wrong_unit_exams
    unit = read_unit(core["unit_id"])
    assert_instant_equals(
        unit["accreditation_expires_on"], "2029-07-31T00:00:00Z", "accreditation_expires_on"
    )
    response = api.create_clinical_image_review(
        core["unit_id"],
        packet_payload(
            core["other_exam_ids"],
            unit["version"],
            reviewer_note="Reaccreditation packet built from the wrong unit",
        ),
        coordinator_headers,
    )
    validate_error(response, "ERR_EXAM_UNIT_MISMATCH", expected_status=422)


def test_the_masked_off_filing_consumes_no_attempt_and_takes_no_escrow(
    api, lapsed_certificate_with_wrong_unit_exams, coordinator_headers
):
    """The attempt budget restored by the passing review is still intact at three.

    PRD: "The escrow step moves exactly 250000 cents out of `prepaid_credit_cents`
    and into `fee_held_cents` on the facility."

    Design: Difficulty/priority_pair_validation_conflict/packet_exam_unit_mismatch_outranks_closed_reaccreditation_window
    """
    core = lapsed_certificate_with_wrong_unit_exams
    validate_error(
        api.create_clinical_image_review(
            core["unit_id"],
            packet_payload(
                core["other_exam_ids"],
                unit_version(core),
                reviewer_note="Reaccreditation packet built from the wrong unit",
            ),
            coordinator_headers,
        ),
        "ERR_EXAM_UNIT_MISMATCH",
    )
    assert read_unit(core["unit_id"])["reaccreditation_attempts_remaining"] == 3
    assert_facility_ledger(
        read_facility(core["facility_id"]),
        prepaid_credit_cents=750000,
        fee_held_cents=0,
        fee_consumed_cents=250000,
    )


@pytest.fixture
def open_level_1_without_credit():
    """An unfunded facility carrying an open LEVEL_1 finding and a ready packet."""
    core = setup_core()
    core["packet_exam_ids"] = [
        acquire_and_interpret(
            core, patient_ref="PT-9401", performed_at="2026-07-10T00:00:00Z"
        )["id"],
        acquire_and_interpret(
            core, patient_ref="PT-9402", performed_at="2026-07-11T00:00:00Z"
        )["id"],
    ]
    core["inspection"] = record_level_1_inspection(
        core, inspection_date="2026-07-28T00:00:00Z", finding_codes=["900.12(e)(5)"]
    )
    return core


def test_open_level_1_finding_is_reported_before_the_empty_prepaid_balance(
    api, open_level_1_without_credit, coordinator_headers
):
    """Priority 54 beats priority 81, so the safety 409 wins over the fiscal 402.

    PRD: "21. **No open Level 1 finding (priority 54)** — a facility with a
    `LEVEL_1` inspection finding still in `CORRECTIVE_ACTION_REQUIRED` cannot
    submit or resubmit a clinical image packet: `ERR_OPEN_LEVEL_1_FINDING`, 409."

    Design: Difficulty/priority_pair_validation_conflict/open_level_1_finding_outranks_insufficient_prepaid_credit
    """
    core = open_level_1_without_credit
    response = api.create_clinical_image_review(
        core["unit_id"],
        packet_payload(
            core["packet_exam_ids"],
            unit_version(core),
            reviewer_note="Packet attempted during an open level 1 finding",
        ),
        coordinator_headers,
    )
    validate_error(response, "ERR_OPEN_LEVEL_1_FINDING", expected_status=409)
    assert core["inspection"]["status"] == "CORRECTIVE_ACTION_REQUIRED"
    assert_instant_equals(
        core["inspection"]["corrective_action_due_at"],
        "2026-08-12T00:00:00Z",
        "corrective_action_due_at",
    )


def test_the_suspended_facility_keeps_an_untouched_ledger_and_attempt_budget(
    api, open_level_1_without_credit, coordinator_headers
):
    """Nothing is escrowed and no attempt is spent when the safety gate fires.

    PRD: "The ladder exists because masking matters: a facility must be told its
    unit is out of service before it is told its prepaid accreditation credit is
    short, and a caller whose attempt budget is exhausted must learn that rather
    than learning about the suspension that exhausting the budget causes."

    Design: Difficulty/priority_pair_validation_conflict/open_level_1_finding_outranks_insufficient_prepaid_credit
    """
    core = open_level_1_without_credit
    validate_error(
        api.create_clinical_image_review(
            core["unit_id"],
            packet_payload(
                core["packet_exam_ids"],
                unit_version(core),
                reviewer_note="Packet attempted during an open level 1 finding",
            ),
            coordinator_headers,
        ),
        "ERR_OPEN_LEVEL_1_FINDING",
    )
    facility = read_facility(core["facility_id"])
    assert facility["compliance_posture"] == "SUSPENDED"
    assert_facility_ledger(
        facility, prepaid_credit_cents=0, fee_held_cents=0, fee_consumed_cents=0
    )
    assert read_unit(core["unit_id"])["reaccreditation_attempts_remaining"] == 3
