"""ExpenseLine creation constraints — receipts, category-specific fields,
trip window, polymorphic categories.

Covers PRD §3.3 (line shape), §3.4 (receipt requirement), §3.3 (category
fields), §2.7 priority order around receipt / category-field / trip
window.

Difficulty-design instances exercised here:
  - resource_temporal_overlap.expense_date_within_trip_window_inclusive
  - priority_pair_validation_conflict.business_safety_vs_business_referential_attach_receipt
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    add_days,
    add_meal_line,
    assert_expense_line,
    attach_receipt_payload,
    attach_receipt_to_line,
    create_flight_line_payload,
    create_lodging_line_payload,
    create_meal_line_payload,
    create_mileage_line_payload,
    create_rental_car_line_payload,
    create_other_line_payload,
    create_expense_report,
    make_finance_reviewer_headers,
    make_traveler_headers,
    seed_finance_reviewer,
    seed_manager,
    seed_traveler,
    setup_approved_trip,
    setup_report_with_meal_line_in_policy,
    upload_receipt,
    validate_error,
    validate_success,
)


# ===========================================================================
# Trip-window inclusivity — difficulty-design instance
# ===========================================================================
def test_expense_date_on_boundary_end_date_accepted(api):
    """PRD §3.3: "an `expense_date` (UTC midnight semantics) that must
    fall within the trip's `[start_date, end_date]` window inclusive on
    both ends".
    # difficulty: resource_temporal_overlap/expense_date_within_trip_window_inclusive
    """
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    res = api.create_expense_line(
        rpt["id"],
        create_meal_line_payload(
            expense_date=cast["trip"]["end_date"],
            meal_type="BREAKFAST",
            amount_claimed_cents=0,
            meal_was_provided=True,
        ),
        make_traveler_headers(cast["traveler"]["id"]),
    )
    line = validate_success(res, 201)
    assert_expense_line(line)


def test_expense_date_one_day_past_end_date_rejected(api):
    """PRD §3.3: "an `expense_date` (UTC midnight semantics) that must
    fall within the trip's `[start_date, end_date]` window inclusive on
    both ends — otherwise the line is rejected with
    `ERR_EXPENSE_OUTSIDE_TRIP_WINDOW`".
    # difficulty: resource_temporal_overlap/expense_date_within_trip_window_inclusive
    """
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    res = api.create_expense_line(
        rpt["id"],
        create_meal_line_payload(
            expense_date=add_days(cast["trip"]["end_date"], 1),
            meal_type="BREAKFAST",
            amount_claimed_cents=0,
            meal_was_provided=True,
        ),
        make_traveler_headers(cast["traveler"]["id"]),
    )
    validate_error(res, "ERR_EXPENSE_OUTSIDE_TRIP_WINDOW")


def test_expense_date_on_boundary_start_date_accepted(api):
    """PRD §3.3: "inclusive on both ends"."""
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    res = api.create_expense_line(
        rpt["id"],
        create_meal_line_payload(
            expense_date=cast["trip"]["start_date"],
            meal_type="BREAKFAST",
            amount_claimed_cents=0,
            meal_was_provided=True,
        ),
        make_traveler_headers(cast["traveler"]["id"]),
    )
    validate_success(res, 201)


def test_expense_date_one_day_before_start_date_rejected(api):
    """PRD §3.3: "inclusive on both ends — otherwise the line is
    rejected with `ERR_EXPENSE_OUTSIDE_TRIP_WINDOW`"."""
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    res = api.create_expense_line(
        rpt["id"],
        create_meal_line_payload(
            expense_date=add_days(cast["trip"]["start_date"], -1),
            meal_type="BREAKFAST",
            amount_claimed_cents=0,
            meal_was_provided=True,
        ),
        make_traveler_headers(cast["traveler"]["id"]),
    )
    validate_error(res, "ERR_EXPENSE_OUTSIDE_TRIP_WINDOW")


# ===========================================================================
# Category-specific required fields — PRD §3.3
# ===========================================================================
def test_mileage_line_without_miles_driven_rejected(api):
    """PRD §3.3: "Polymorphic per-category fields complete the picture:
    `MILEAGE` requires `miles_driven` ... A missing category-specific
    field yields `ERR_CATEGORY_FIELD_MISSING`."
    """
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    payload = create_mileage_line_payload(
        expense_date=cast["trip"]["start_date"], miles_driven=10.0,
    )
    payload.pop("miles_driven")
    res = api.create_expense_line(
        rpt["id"], payload,
        make_traveler_headers(cast["traveler"]["id"]),
    )
    validate_error(res, "ERR_CATEGORY_FIELD_MISSING")


def test_rental_car_line_without_rental_days_rejected(api):
    """PRD §3.3: "`RENTAL_CAR` requires `rental_days` ...
    A missing category-specific field yields `ERR_CATEGORY_FIELD_MISSING`."
    """
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    # Receipt for RENTAL_CAR.
    receipt = upload_receipt(
        uploader=cast["traveler"], merchant_total_cents=5000,
        ocr_extracted_date=cast["trip"]["start_date"],
    )
    payload = create_rental_car_line_payload(
        expense_date=cast["trip"]["start_date"],
        amount_claimed_cents=5000,
        rental_days=1,
        receipt_id=receipt["id"],
    )
    payload.pop("rental_days")
    res = api.create_expense_line(
        rpt["id"], payload,
        make_traveler_headers(cast["traveler"]["id"]),
    )
    validate_error(res, "ERR_CATEGORY_FIELD_MISSING")


def test_meal_line_without_meal_type_rejected(api):
    """PRD §3.3: "`MEAL` requires `meal_type` ... A missing
    category-specific field yields `ERR_CATEGORY_FIELD_MISSING`."
    """
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    # PRD §3.3: for non-MILEAGE categories, amount_claimed_cents must be
    # supplied. Supply it (so the ONLY missing field is meal_type) and
    # then drop meal_type to isolate the ERR_CATEGORY_FIELD_MISSING check.
    payload = create_meal_line_payload(
        expense_date=cast["trip"]["start_date"],
        meal_type="BREAKFAST",
        amount_claimed_cents=0,
        meal_was_provided=True,
    )
    payload.pop("meal_type")
    res = api.create_expense_line(
        rpt["id"], payload,
        make_traveler_headers(cast["traveler"]["id"]),
    )
    validate_error(res, "ERR_CATEGORY_FIELD_MISSING")


def test_lodging_line_without_per_diem_method_rejected(api):
    """PRD §3.3: "both `LODGING` and `MEAL` require a `per_diem_method`
    of either `ACTUAL` (itemized claim) or `PER_DIEM` (cap-based) ...
    A missing category-specific field yields
    `ERR_CATEGORY_FIELD_MISSING`."
    """
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    # Receipt required for LODGING.
    receipt = upload_receipt(
        uploader=cast["traveler"], merchant_total_cents=10000,
        ocr_extracted_date=cast["trip"]["start_date"],
    )
    payload = create_lodging_line_payload(
        expense_date=cast["trip"]["start_date"],
        amount_claimed_cents=10000,
        per_diem_method="ACTUAL",
        receipt_id=receipt["id"],
    )
    payload.pop("per_diem_method")
    res = api.create_expense_line(
        rpt["id"], payload,
        make_traveler_headers(cast["traveler"]["id"]),
    )
    validate_error(res, "ERR_CATEGORY_FIELD_MISSING")


# ===========================================================================
# MILEAGE: amount_claimed_cents MUST be omitted on create
# ===========================================================================
def test_mileage_line_creation_computes_amount_from_miles(api):
    """PRD §3.3: "for `MILEAGE`, `amount_claimed_cents` must be omitted
    on create and the server computes it from `miles_driven`."
    """
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    res = api.create_expense_line(
        rpt["id"],
        create_mileage_line_payload(
            expense_date=cast["trip"]["start_date"], miles_driven=10.0,
        ),
        make_traveler_headers(cast["traveler"]["id"]),
    )
    line = validate_success(res, 201)
    # PRD §3.9: "the server computes `amount_reimbursable_cents` and
    # copies it into `amount_claimed_cents` as well." 10.0 * 67 = 670c.
    assert line["amount_claimed_cents"] == 670
    assert line["amount_reimbursable_cents"] == 670


# ===========================================================================
# Receipt requirement — PRD §3.4
# ===========================================================================
def test_lodging_line_without_receipt_rejected(api):
    """PRD §3.4: "A receipt is required when the line's category is
    `LODGING`, `RENTAL_CAR`, or `FLIGHT`, or when `amount_claimed_cents`
    is strictly greater than 7500 cents ... When a line that demands a
    receipt is created or submitted without one, the request is rejected
    with `ERR_RECEIPT_REQUIRED`."
    """
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    res = api.create_expense_line(
        rpt["id"],
        create_lodging_line_payload(
            expense_date=cast["trip"]["start_date"],
            amount_claimed_cents=10000,
            per_diem_method="ACTUAL",
            receipt_id=None,
        ),
        make_traveler_headers(cast["traveler"]["id"]),
    )
    validate_error(res, "ERR_RECEIPT_REQUIRED")


def test_meal_line_above_75_dollars_without_receipt_rejected(api):
    """PRD §3.4: "or when `amount_claimed_cents` is strictly greater
    than 7500 cents (which is seventy-five dollars)"."""
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    res = api.create_expense_line(
        rpt["id"],
        create_meal_line_payload(
            expense_date=cast["trip"]["start_date"],
            meal_type="DINNER",
            per_diem_method="ACTUAL",
            amount_claimed_cents=7501,  # strictly greater than 7500
        ),
        make_traveler_headers(cast["traveler"]["id"]),
    )
    validate_error(res, "ERR_RECEIPT_REQUIRED")


def test_meal_line_at_75_dollars_without_receipt_succeeds(api):
    """PRD §3.4: "strictly greater than 7500 cents" — at 7500 exactly,
    receipt is NOT required.
    """
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    # 7500-cent breakfast: per_meal_cap = 8000 * 0.25 = 2000, so 7500
    # would be OUT_OF_POLICY. To isolate the boundary test on receipt
    # requirement (not on policy_status), use DINNER with cap 8000 *
    # 0.45 = 3600 → 7500 is still over cap, but creation succeeds.
    # The receipt-requirement check (priority 12) fires before policy
    # evaluation. PRD §2.7 only guarantees receipt-requirement at exactly
    # 7500 cents does NOT fire (because "strictly greater than"). So the
    # request is accepted by the receipt-requirement check; whether the
    # resulting line is IN_POLICY or OUT_OF_POLICY isn't relevant here.
    res = api.create_expense_line(
        rpt["id"],
        create_meal_line_payload(
            expense_date=cast["trip"]["start_date"],
            meal_type="DINNER",
            per_diem_method="ACTUAL",
            amount_claimed_cents=7500,
        ),
        make_traveler_headers(cast["traveler"]["id"]),
    )
    line = validate_success(res, 201)
    assert line["amount_claimed_cents"] == 7500


# ===========================================================================
# Receipt attach — already-used enforcement
# ===========================================================================
def test_attach_receipt_already_used_returns_receipt_already_used(api):
    """PRD §3.4: "It is null until first attached and, once set, may not
    be set to a different line; an attempt to bind a receipt that is
    already in use is rejected with `ERR_RECEIPT_ALREADY_USED`."
    """
    cast = setup_approved_trip()
    rpt1 = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    rpt2 = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    receipt = upload_receipt(
        uploader=cast["traveler"], merchant_total_cents=2500,
        ocr_extracted_date=cast["trip"]["start_date"],
    )
    line1 = add_meal_line(
        report=rpt1, traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        meal_type="BREAKFAST",
        per_diem_method="ACTUAL",
        amount_claimed_cents=2500,
    )
    line2 = add_meal_line(
        report=rpt2, traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        meal_type="BREAKFAST",
        per_diem_method="ACTUAL",
        amount_claimed_cents=2500,
    )
    attach_receipt_to_line(
        line=line1, receipt=receipt, traveler=cast["traveler"],
    )
    res = api.attach_receipt(
        line2["id"],
        attach_receipt_payload(receipt_id=receipt["id"]),
        make_traveler_headers(cast["traveler"]["id"]),
    )
    validate_error(res, "ERR_RECEIPT_ALREADY_USED")


# ===========================================================================
# Body-FK receipt_id resolution
# ===========================================================================
def test_attach_nonexistent_receipt_returns_reference_not_found(api):
    """PRD §2.7 #4: "existence of body-referenced foreign keys,
    returning `ERR_REFERENCE_NOT_FOUND`"."""
    cast = setup_report_with_meal_line_in_policy()
    res = api.attach_receipt(
        cast["line"]["id"],
        attach_receipt_payload(receipt_id=NON_EXISTENT_UUID),
        make_traveler_headers(cast["traveler"]["id"]),
    )
    validate_error(res, "ERR_REFERENCE_NOT_FOUND")
