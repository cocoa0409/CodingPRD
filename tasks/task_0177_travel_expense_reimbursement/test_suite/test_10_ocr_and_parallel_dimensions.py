"""Receipt OCR behavior and the parallel policy_status × ocr_status
state-machine dimensions on ExpenseLine.

Covers PRD §3.3 (parallel state dimensions and OCR transitions),
§3.4 (receipt requirement and OCR thresholds), and:
  - non_linear_state_machine.expense_line_parallel_policy_and_ocr_dimensions
"""
from __future__ import annotations

import pytest

from test_helpers import (
    OCR_CONFIDENCE_VERIFY_THRESHOLD,
    OCR_CONFIDENCE_WAIVE_THRESHOLD,
    OCR_MEAL_WAIVE_TOLERANCE_CENTS,
    add_lodging_line,
    add_meal_line,
    attach_receipt_payload,
    attach_receipt_to_line,
    create_expense_report,
    get_line,
    make_traveler_headers,
    setup_approved_trip,
    upload_receipt,
    validate_error,
    validate_success,
)


# ===========================================================================
# OCR_VERIFIED happy path
# ===========================================================================
def test_attach_matching_receipt_verifies_ocr(api):
    """PRD §3.3: "when the receipt's `merchant_total_cents` equals the
    line's `amount_claimed_cents` and `ocr_confidence` is at least 0.80,
    the line advances to `OCR_VERIFIED`."
    """
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    # Lodging line claim = 10000.
    receipt = upload_receipt(
        uploader=cast["traveler"], merchant_total_cents=10000,
        ocr_extracted_date=cast["trip"]["start_date"],
        ocr_confidence=0.95,
    )
    line = add_lodging_line(
        report=rpt, traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        amount_claimed_cents=10000,
        per_diem_method="ACTUAL",
        receipt_id=receipt["id"],
    )
    # Line was created with receipt_id at construction time → OCR runs
    # inline. PRD §3.3 says "advances independently of `policy_status`";
    # at this point ocr_status should be OCR_VERIFIED.
    assert line["ocr_status"] in ("OCR_VERIFIED",)


def test_attach_mismatched_receipt_marks_ocr_mismatch(api):
    """PRD §3.3: "Otherwise it advances to `OCR_MISMATCH`".

    For a LODGING line (not MEAL), the meal waiver carve-out does NOT
    apply, so a $1 mismatch lands in OCR_MISMATCH.
    """
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    # Receipt total 10100 vs claim 10000 → mismatch (and category isn't
    # MEAL, so the waiver doesn't trigger).
    receipt = upload_receipt(
        uploader=cast["traveler"], merchant_total_cents=10100,
        ocr_extracted_date=cast["trip"]["start_date"],
        ocr_confidence=0.95,
    )
    line = add_lodging_line(
        report=rpt, traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        amount_claimed_cents=10000,
        per_diem_method="ACTUAL",
        receipt_id=receipt["id"],
    )
    assert line["ocr_status"] == "OCR_MISMATCH"


def test_attach_low_confidence_receipt_marks_ocr_mismatch(api):
    """PRD §3.3: "Otherwise it advances to `OCR_MISMATCH`" — including
    when `ocr_confidence` is below 0.80.
    """
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    receipt = upload_receipt(
        uploader=cast["traveler"], merchant_total_cents=10000,
        ocr_extracted_date=cast["trip"]["start_date"],
        ocr_confidence=0.50,
    )
    line = add_lodging_line(
        report=rpt, traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        amount_claimed_cents=10000,
        per_diem_method="ACTUAL",
        receipt_id=receipt["id"],
    )
    assert line["ocr_status"] == "OCR_MISMATCH"


# ===========================================================================
# Meal OCR waiver carve-out
# ===========================================================================
def test_meal_line_within_two_dollars_and_above_60_confidence_auto_waived(api):
    """PRD §3.3: "for meal lines, when the absolute difference between
    `merchant_total_cents` and `amount_claimed_cents` is at most 200
    cents (two dollars) and `ocr_confidence` is at least 0.60, the line
    is auto-set to `OCR_WAIVED` instead."

    Claim 2500 vs receipt 2700: diff=200, conf=0.70 → OCR_WAIVED.
    """
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    receipt = upload_receipt(
        uploader=cast["traveler"], merchant_total_cents=2700,
        ocr_extracted_date=cast["trip"]["start_date"],
        ocr_confidence=0.70,
    )
    line = add_meal_line(
        report=rpt, traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        meal_type="LUNCH", per_diem_method="ACTUAL",
        amount_claimed_cents=2500,
    )
    attached = attach_receipt_to_line(
        line=line, receipt=receipt, traveler=cast["traveler"],
    )
    assert attached["ocr_status"] == "OCR_WAIVED"


# ===========================================================================
# Finance waive-OCR — PRD §3.3
# ===========================================================================
def test_finance_waive_ocr_on_in_review_report(api):
    """PRD §3.3: "A finance reviewer can additionally waive an existing
    `OCR_MISMATCH` on a line whose parent report has `status` equal to
    `IN_REVIEW`, advancing `ocr_status` to `OCR_WAIVED` and accepting an
    optional `waiver_note`."
    """
    from test_helpers import (
        claim_report, make_finance_reviewer_headers, submit_report,
    )
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    receipt = upload_receipt(
        uploader=cast["traveler"], merchant_total_cents=10500,
        ocr_extracted_date=cast["trip"]["start_date"],
        ocr_confidence=0.95,
    )
    line = add_lodging_line(
        report=rpt, traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        amount_claimed_cents=10000,
        per_diem_method="ACTUAL",
        receipt_id=receipt["id"],
    )
    assert line["ocr_status"] == "OCR_MISMATCH"

    rpt = submit_report(report=rpt, traveler=cast["traveler"])
    rpt = claim_report(report=rpt, finance=cast["finance"])
    assert rpt["status"] == "IN_REVIEW"

    res = api.waive_ocr(
        line["id"], make_finance_reviewer_headers(cast["finance"]["id"]),
    )
    waived = validate_success(res, 200)
    assert waived["ocr_status"] == "OCR_WAIVED"


# ===========================================================================
# Parallel dimensions — difficulty: expense_line_parallel_policy_and_ocr
# ===========================================================================
def test_line_can_be_out_of_policy_and_ocr_verified_simultaneously(api):
    """PRD §3.3: "A line carries two parallel state dimensions that
    evolve independently. The first is `policy_status` ... The second
    dimension is `ocr_status`, which is initialized to `NO_RECEIPT` and
    advances independently of `policy_status`."

    Demonstrate (OUT_OF_POLICY, OCR_VERIFIED) — a non-trivial pair.
    # difficulty: non_linear_state_machine/expense_line_parallel_policy_and_ocr_dimensions
    """
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    # Breakfast cap = 2000; claim 2500 → OUT_OF_POLICY.
    line = add_meal_line(
        report=rpt, traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        meal_type="BREAKFAST", per_diem_method="ACTUAL",
        amount_claimed_cents=2500,
    )
    assert line["policy_status"] == "OUT_OF_POLICY"
    assert line["ocr_status"] == "NO_RECEIPT"

    # Now attach a matching receipt with high confidence.
    receipt = upload_receipt(
        uploader=cast["traveler"], merchant_total_cents=2500,
        ocr_extracted_date=cast["trip"]["start_date"],
        ocr_confidence=0.95,
    )
    line_after = attach_receipt_to_line(
        line=line, receipt=receipt, traveler=cast["traveler"],
    )
    assert line_after["policy_status"] == "OUT_OF_POLICY"
    assert line_after["ocr_status"] == "OCR_VERIFIED"


def test_parallel_dimensions_evolve_independently_after_oop_chain(api):
    """PRD §3.3: "A line carries two parallel state dimensions that
    evolve independently."

    Demonstrate that after the OOP chain transitions policy_status from
    OUT_OF_POLICY → OOP_APPROVED, ocr_status remains OCR_VERIFIED.
    # difficulty: non_linear_state_machine/expense_line_parallel_policy_and_ocr_dimensions
    """
    from test_helpers import (
        open_oop_approval, oop_l1_approve, oop_l2_approve,
    )
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    line = add_meal_line(
        report=rpt, traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        meal_type="BREAKFAST", per_diem_method="ACTUAL",
        amount_claimed_cents=2500,
    )
    receipt = upload_receipt(
        uploader=cast["traveler"], merchant_total_cents=2500,
        ocr_extracted_date=cast["trip"]["start_date"],
        ocr_confidence=0.95,
    )
    line = attach_receipt_to_line(
        line=line, receipt=receipt, traveler=cast["traveler"],
    )
    assert line["ocr_status"] == "OCR_VERIFIED"

    approval = open_oop_approval(line=line, traveler=cast["traveler"])
    approval = oop_l1_approve(approval=approval, manager=cast["manager"])
    approval = oop_l2_approve(approval=approval, finance=cast["finance"])
    line_after = get_line(line["id"], viewer=cast["finance"])
    assert line_after["policy_status"] == "OOP_APPROVED"
    assert line_after["ocr_status"] == "OCR_VERIFIED"
