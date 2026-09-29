"""Compensating writes must return conserved quantities to their prior values."""

import pytest

from test_helpers import (
    acquire_and_interpret,
    acquire_exam,
    assert_facility_ledger,
    assert_unit_image_ledger,
    document_repeat,
    file_packet,
    read_exam,
    read_facility,
    read_unit,
    list_total_count,
    retract_payload,
    unit_version,
    validate_success,
    withdraw_payload,
)


@pytest.fixture
def escrowed_packet(funded_core):
    """A funded facility with one SUBMITTED packet holding the application fee."""
    core = funded_core
    pair = [
        acquire_and_interpret(
            core, patient_ref="PT-9901", performed_at="2026-07-20T00:00:00Z"
        )["id"],
        acquire_and_interpret(
            core, patient_ref="PT-9902", performed_at="2026-07-21T00:00:00Z"
        )["id"],
    ]
    submission = file_packet(core, pair, reviewer_note="Packet later withdrawn")
    core["submission_id"] = submission["id"]
    return core


def test_the_escrow_holds_the_ledger_identity_before_the_compensation(api, escrowed_packet):
    """While the fee is held the four ledger fields still sum to the funded total.

    PRD: "First, the facility fee ledger: `total_funded_cents` always equals
    `prepaid_credit_cents` plus `fee_held_cents` plus `fee_consumed_cents`, with
    `total_funded_cents` and `fee_consumed_cents` both monotonically non-decreasing
    — neither ever goes down."

    Design: Difficulty/compensating_invariant/submission_withdrawal_restores_the_fee_ledger_identity_without_drift
    """
    core = escrowed_packet
    assert_facility_ledger(
        read_facility(core["facility_id"]),
        total_funded_cents=1000000,
        prepaid_credit_cents=750000,
        fee_held_cents=250000,
        fee_consumed_cents=0,
    )
    assert read_unit(core["unit_id"])["reaccreditation_attempts_remaining"] == 2


def test_withdrawal_returns_the_escrow_and_the_attempt_without_drift(
    api, escrowed_packet, coordinator_headers
):
    """The held money goes back to prepaid and the spent attempt is refunded.

    PRD: "Withdrawal moves the submission `SUBMITTED` to `WITHDRAWN` and reverses
    the escrow exactly: 250000 cents return from `fee_held_cents` to
    `prepaid_credit_cents`, the submission's `fee_held_cents` drops to 0, and
    `fee_consumed_cents` and `total_funded_cents` are left completely untouched — a
    withdrawal costs the facility nothing."

    Design: Difficulty/compensating_invariant/submission_withdrawal_restores_the_fee_ledger_identity_without_drift
    """
    core = escrowed_packet
    submission = validate_success(
        api.withdraw_clinical_image_review(
            core["submission_id"],
            withdraw_payload(
                expected_unit_version=unit_version(core),
                withdrawal_reason="Better comparison images became available",
            ),
            coordinator_headers,
        )
    )
    assert submission["status"] == "WITHDRAWN"
    assert submission["fee_held_cents"] == 0
    assert_facility_ledger(
        read_facility(core["facility_id"]),
        total_funded_cents=1000000,
        prepaid_credit_cents=1000000,
        fee_held_cents=0,
        fee_consumed_cents=0,
    )
    unit = read_unit(core["unit_id"])
    assert unit["reaccreditation_attempts_remaining"] == 3
    assert unit["accreditation_status"] == "PROVISIONAL"


@pytest.fixture
def repeated_exam(core):
    """A four-image exam carrying one two-image positioning repeat."""
    exam = acquire_exam(
        core,
        patient_ref="PT-9951",
        performed_at="2026-07-22T00:00:00Z",
        original_image_count=4,
    )
    core["exam_id"] = exam["id"]
    record = document_repeat(core, exam["id"], reason_code="POSITIONING", repeat_image_count=2)
    core["record_id"] = record["id"]
    return core


def test_documented_repeats_raise_both_rates_and_the_regulatory_flag(api, repeated_exam):
    """Two repeats on four originals give 33.33 image-based and 100.00 patient-based.

    PRD: "The patient-based rate, `patient_based_repeat_rate_pct`, is 100 multiplied
    by the number of the unit's exams that have at least one non-retracted repeat,
    divided by the total number of the unit's exams, rounded half up to two decimal
    places — and it is null when the unit has no exams at all."

    Design: Difficulty/compensating_invariant/repeat_record_retraction_restores_the_unit_image_ledger_without_drift
    """
    core = repeated_exam
    unit = read_unit(core["unit_id"])
    assert_unit_image_ledger(
        unit,
        total_images_acquired=6,
        repeat_images_acquired=2,
        image_based_repeat_rate_pct=33.33,
        patient_based_repeat_rate_pct=100.00,
    )
    assert unit["repeat_rate_flag"] is True
    assert unit["total_images_acquired"] == 4 + unit["repeat_images_acquired"]


def test_retraction_restores_the_image_ledger_and_recomputes_both_rates(
    api, repeated_exam, qa_headers
):
    """The two repeat images are removed, not hidden, and neither rate stays stale.

    PRD: "Retraction then reverses the ledger exactly: the exam's
    `repeat_image_count` and the unit's `repeat_images_acquired`,
    `total_images_acquired`, both rate variants and `repeat_rate_flag` are
    recomputed with the retracted record excluded, returning `total_images_acquired`
    to precisely the value it held before the record was ever documented."

    Design: Difficulty/compensating_invariant/repeat_record_retraction_restores_the_unit_image_ledger_without_drift
    """
    core = repeated_exam
    record = validate_success(
        api.retract_repeat_record(
            core["record_id"],
            retract_payload(
                retraction_reason="Repeat images were charted against the wrong accession"
            ),
            qa_headers,
        )
    )
    assert record["retracted"] is True
    unit = read_unit(core["unit_id"])
    assert_unit_image_ledger(
        unit,
        total_images_acquired=4,
        repeat_images_acquired=0,
        image_based_repeat_rate_pct=0.00,
        patient_based_repeat_rate_pct=0.00,
    )
    assert unit["repeat_rate_flag"] is False
    exam = read_exam(core["exam_id"])
    assert exam["repeat_image_count"] == 0
    assert exam["original_image_count"] == 4
    listed = api.list_exam_repeat_records(core["exam_id"], qa_headers)
    assert list_total_count(listed) == 1
